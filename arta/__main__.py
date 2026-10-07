"""Bounded, localhost-only HTTP deception simulator. No commands are executed."""
import argparse
import collections
import hashlib
import json
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit


class Store:
    def __init__(self, path, limit=10000):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.limit = limit
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts REAL, payload TEXT, previous TEXT, digest TEXT)')
        self.db.commit()

    def record(self, event):
        payload = json.dumps(event, sort_keys=True, ensure_ascii=False)
        with self.lock:
            previous = self.db.execute('SELECT digest FROM events ORDER BY id DESC LIMIT 1').fetchone()
            previous = previous[0] if previous else ''
            ts = time.time()
            digest = hashlib.sha256((previous + str(ts) + payload).encode()).hexdigest()
            self.db.execute('INSERT INTO events(ts,payload,previous,digest) VALUES(?,?,?,?)', (ts, payload, previous, digest))
            self.db.execute('DELETE FROM events WHERE id <= (SELECT COALESCE(MAX(id),0)-? FROM events)', (self.limit,))
            self.db.commit()

    def recent(self):
        with self.lock:
            return [{'id': row[0], 'time': row[1], **json.loads(row[2])} for row in self.db.execute('SELECT id,ts,payload FROM events ORDER BY id DESC LIMIT 100')]

    def verify(self):
        with self.lock:
            rows = list(self.db.execute('SELECT ts,payload,previous,digest FROM events ORDER BY id'))
        last = None
        for ts, payload, previous, digest in rows:
            if last is not None and previous != last:
                return False
            if hashlib.sha256((previous + str(ts) + payload).encode()).hexdigest() != digest:
                return False
            last = digest
        return True


class Lab:
    def __init__(self, store, rate=30, window=60, capacity=1000):
        self.store, self.rate, self.window, self.capacity = store, rate, window, capacity
        self.clients = collections.OrderedDict()
        self.sessions = collections.OrderedDict()

    def allowed(self, peer):
        now = time.monotonic()
        queue = self.clients.setdefault(peer, collections.deque())
        self.clients.move_to_end(peer)
        while queue and queue[0] <= now - self.window:
            queue.popleft()
        allowed = len(queue) < self.rate
        if allowed:
            queue.append(now)
        while len(self.clients) > self.capacity:
            self.clients.popitem(last=False)
        return allowed

    def session(self, token):
        now = time.monotonic()
        if token not in self.sessions or self.sessions[token]['expires'] < now:
            token = secrets.token_urlsafe(24)
            self.sessions[token] = {'expires': now + 900, 'settings': {'maintenance': False}, 'marker': secrets.token_hex(8)}
        self.sessions.move_to_end(token)
        while len(self.sessions) > self.capacity:
            self.sessions.popitem(last=False)
        return token, self.sessions[token]


def handler(lab, monitor=False):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'

        def setup(self):
            super().setup()
            self.connection.settimeout(3)

        def log_message(self, *args):
            pass

        def respond(self, status, value, cookie=None):
            content = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            if cookie:
                self.send_header('Set-Cookie', 'arta_session=' + cookie + '; HttpOnly; SameSite=Strict; Path=/')
            if status == 429:
                self.send_header('Retry-After', str(lab.window))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            self.process()

        def do_POST(self):
            self.process()

        def process(self):
            path = urlsplit(self.path).path
            if monitor:
                if self.command != 'GET':
                    return self.respond(405, {'error': 'read only'})
                if path == '/events':
                    return self.respond(200, lab.store.recent())
                if path == '/health':
                    return self.respond(200, {'chain_valid': lab.store.verify()})
                return self.respond(200, {'service': 'ARTA observer', 'events': '/events', 'integrity': '/health'})
            peer = self.client_address[0]  # Never trust client-supplied forwarded headers.
            status, value, token = 200, {}, None
            if not lab.allowed(peer):
                status, value = 429, {'error': 'request limit exceeded'}
            elif len(self.path) > 2048:
                status, value = 414, {'error': 'path too long'}
            else:
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if size < 0 or size > 4096 or self.headers.get('Transfer-Encoding'):
                        raise ValueError()
                except ValueError:
                    status, value = 413, {'error': 'unsupported body size or encoding'}
                else:
                    body = self.rfile.read(size) if size else b''
                    cookie = self.headers.get('Cookie', '')[:4096]
                    candidate = next((p.strip().split('=', 1)[1] for p in cookie.split(';') if p.strip().startswith('arta_session=')), '')
                    token, state = lab.session(candidate)
                    if path == '/':
                        value = {'service': 'Operations workspace', 'links': ['/admin', '/backup']}
                    elif path == '/admin':
                        value = {'role': 'workspace-admin', 'settings': '/api/settings'}
                    elif path == '/backup':
                        value = {'files': ['demo-inventory.json'], 'marker': state['marker'], 'inventory': [{'name': 'sample-node', 'status': 'ready'}]}
                    elif path == '/api/settings':
                        if self.command == 'POST':
                            try:
                                update = json.loads(body)
                                if not isinstance(update, dict) or set(update) != {'maintenance'} or type(update['maintenance']) is not bool:
                                    raise ValueError()
                                state['settings']['maintenance'] = update['maintenance']
                            except (ValueError, UnicodeDecodeError):
                                status, value = 400, {'error': 'expected maintenance boolean'}
                        if status == 200:
                            value = {'saved': True, 'settings': state['settings']}
                    else:
                        status, value = 404, {'error': 'not found'}
            # Do not collect body, query string, passwords, cookies or authorization headers.
            lab.store.record({'peer': peer, 'method': self.command, 'room': path if path in {'/', '/admin', '/backup', '/api/settings'} else 'unknown', 'status': status, 'session_tag': hashlib.sha256(token.encode()).hexdigest()[:16] if token else None})
            self.respond(status, value, token)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--monitor-port', type=int, default=8081)
    parser.add_argument('--data-dir', default='data')
    args = parser.parse_args()
    directory = Path(args.data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    lab = Lab(Store(directory / 'events.sqlite3'))
    decoy = HTTPServer(('127.0.0.1', args.port), handler(lab))
    observer = HTTPServer(('127.0.0.1', args.monitor_port), handler(lab, True))
    threading.Thread(target=observer.serve_forever, daemon=True).start()
    print(f'ARTA LOCAL LAB — decoy http://127.0.0.1:{args.port} | observer http://127.0.0.1:{args.monitor_port}', flush=True)
    try:
        decoy.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        observer.shutdown()
        observer.server_close()
        decoy.server_close()


if __name__ == '__main__':
    main()
