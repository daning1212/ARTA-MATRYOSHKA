"""Bounded localhost HTTP PoW microbenchmark; not AI or production protection."""
import argparse
import concurrent.futures
import hashlib
import http.client
import json
import multiprocessing
import secrets
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


class Gate:
    def __init__(self, bits=14, ttl=10, capacity=128):
        if not 0 <= bits <= 18:
            raise ValueError('bits must be 0..18')
        self.bits, self.ttl, self.capacity = bits, ttl, capacity
        self.pending = {}

    def issue(self, resource, now=None):
        now = time.monotonic() if now is None else now
        self.pending = {k: v for k, v in self.pending.items() if v[1] > now}
        if len(self.pending) >= self.capacity:
            return None
        token = secrets.token_hex(16)
        self.pending[token] = (resource, now + self.ttl)
        return {'challenge': token, 'resource': resource, 'bits': self.bits}

    def redeem(self, token, resource, nonce, now=None):
        now = time.monotonic() if now is None else now
        if not isinstance(token, str) or not isinstance(resource, str) or type(nonce) is not int or not 0 <= nonce < 2**32:
            return False
        entry = self.pending.get(token)
        if entry is None or entry[0] != resource or entry[1] <= now:
            return False
        digest = hashlib.sha256(f'{token}:{resource}:{nonce}'.encode()).digest()
        if int.from_bytes(digest, 'big') >> (256 - self.bits):
            return False
        del self.pending[token]
        return True


def server(bits, ready, resource_count=4, require_proof=False):
    gate = Gate(bits)
    counts = {'records': 0, 'requests': 0, 'verification_cpu': 0.0}
    served = set()
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(1)
        def log_message(self, *args):
            pass
        def do_POST(self):
            counts['requests'] += 1
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 1024 or self.headers.get('Transfer-Encoding'):
                    raise ValueError()
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError()
                resource = data.get('resource')
                if (not isinstance(resource, str) or not resource.startswith('demo-')
                        or not resource[5:].isascii() or not resource[5:].isdigit()
                        or not 0 <= int(resource[5:]) < resource_count
                        or resource != f'demo-{int(resource[5:])}'):
                    raise ValueError()
                if self.path == '/challenge':
                    value = gate.issue(resource)
                    status = 200 if value else 429
                elif self.path == '/record':
                    start = time.process_time()
                    accepted = (bits == 0 and not require_proof) or gate.redeem(data.get('challenge'), resource, data.get('nonce'))
                    counts['verification_cpu'] += time.process_time() - start
                    status = 200 if accepted else 403
                    value = {'record': {'id': resource, 'name': 'SYNTHETIC DEMO', 'payload': 'x' * 128}} if accepted else {'error': 'proof required'}
                    counts['records'] += int(accepted)
                    if accepted:
                        served.add(resource)
                else:
                    status, value = 404, {}
            except (ValueError, TypeError, RecursionError, TimeoutError):
                status, value = 400, {}
            raw = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass
    http = HTTPServer(('127.0.0.1', 0), Handler)
    http.timeout = 0.05
    ready.send(http.server_port)
    start = time.process_time()
    while not ready.poll():
        http.handle_request()
    ready.recv()
    ready.send({**counts, 'unique_records_served': len(served),
                'server_cpu': time.process_time() - start})
    http.server_close()


def trial(bits, seconds, workers):
    ctx = multiprocessing.get_context('spawn')
    parent, child = ctx.Pipe()
    proc = ctx.Process(target=server, args=(bits, child))
    proc.start()
    child.close()
    if not parent.poll(5):
        proc.terminate()
        proc.join()
        raise RuntimeError('startup failed')
    port = parent.recv()
    deadline = time.monotonic() + seconds
    cpu = time.process_time()
    def post(path, data):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
        try:
            conn.request('POST', path, json.dumps(data))
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()
    def worker(index):
        collected, hashes = 0, 0
        resource = f'demo-{index}'
        while time.monotonic() < deadline:
            proof = {'resource': resource}
            if bits:
                status, challenge = post('/challenge', proof)
                if status != 200:
                    continue
                for nonce in range(2**32):
                    if time.monotonic() >= deadline:
                        return collected, hashes
                    hashes += 1
                    digest = hashlib.sha256(f"{challenge['challenge']}:{resource}:{nonce}".encode()).digest()
                    if int.from_bytes(digest, 'big') >> (256 - bits) == 0:
                        proof.update(challenge=challenge['challenge'], nonce=nonce)
                        break
            if time.monotonic() < deadline:
                status, _ = post('/record', proof)
                collected += int(status == 200)
        return collected, hashes
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(worker, range(workers)))
        client_cpu = time.process_time() - cpu
        parent.send('stop')
        if not parent.poll(5):
            raise RuntimeError('server failed to stop')
        stats = parent.recv()
        proc.join(timeout=3)
        return {'bits': bits, 'workers': workers, 'budget_seconds': seconds,
                'records_served_including_repeats': sum(x[0] for x in results),
                'unique_available_records': workers, 'client_hashes': sum(x[1] for x in results),
                'client_cpu': client_cpu, **stats}
    finally:
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=3)
        parent.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seconds', type=float, default=2)
    p.add_argument('--repeats', type=int, default=3)
    args = p.parse_args()
    if not 0.1 <= args.seconds <= 300 or not 1 <= args.repeats <= 5:
        p.error('seconds 0.1..300, repeats 1..5')
    runs = []
    for workers in (1, 2):
        for repeat in range(args.repeats):
            for bits in ((0, 14) if repeat % 2 == 0 else (14, 0)):
                runs.append({'repeat': repeat, **trial(bits, args.seconds, workers)})
    print(json.dumps({'kind': 'localhost-scripted-pow-benchmark', 'ai_test': False,
                      'isolation': 'separate processes only; OS/network sandbox unverified',
                      'runs': runs}, indent=2))


if __name__ == '__main__':
    main()
