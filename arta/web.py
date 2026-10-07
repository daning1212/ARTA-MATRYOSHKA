"""Loopback-only sequential HTTP lab with bounded sessions and telemetry."""
import collections
import hashlib
import json
import queue
import secrets
import socket
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit
from .world import ROOMS, new_state, route, WorldConfig
from .telemetry import DatagramSink


class Lab:
    def __init__(self, sink, rate=30, window=60, capacity=1000, config=None):
        self.sink, self.rate, self.window, self.capacity = sink, rate, window, capacity
        self.clients = collections.OrderedDict()
        self.sessions = collections.OrderedDict()
        self.dropped = 0
        self.config = config or WorldConfig()

    def record(self, event):
        # A full/failed collector never blocks the decoy waiting for storage.
        try:
            self.sink.put_nowait(event)
        except (queue.Full, OSError, ValueError):
            self.dropped += 1
        if self.dropped and self.dropped % 100 == 1:
            print(f'ARTA telemetry dropped: {self.dropped}', flush=True)

    def allowed(self, peer):
        now = time.monotonic()
        q = self.clients.setdefault(peer, collections.deque())
        self.clients.move_to_end(peer)
        while q and q[0] <= now - self.window:
            q.popleft()
        allowed = len(q) < self.rate
        if allowed:
            q.append(now)
        while len(self.clients) > self.capacity:
            self.clients.popitem(last=False)
        return allowed

    def session(self, token):
        now = time.monotonic()
        if token not in self.sessions or self.sessions[token]['expires'] <= now:
            token = secrets.token_urlsafe(24)
            self.sessions[token] = new_state(now, self.config)
        self.sessions.move_to_end(token)
        while len(self.sessions) > self.capacity:
            self.sessions.popitem(last=False)
        return token, self.sessions[token]


def handler(lab):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'
        server_version = 'WorkspaceHTTP/1.0'
        sys_version = ''

        def setup(self):
            super().setup()
            self.connection.settimeout(2)

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
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            self.process()

        def do_POST(self):
            self.process()

        def process(self):
            try:
                path = urlsplit(self.path).path
            except ValueError:
                path = 'unknown'
            peer = self.client_address[0]
            token, state, transition = None, None, None
            before = None
            if not lab.allowed(peer):
                status, value = 429, {'error': 'request limit exceeded'}
            elif len(self.path) > 2048:
                status, value = 414, {'error': 'path too long'}
            else:
                try:
                    lengths = self.headers.get_all('Content-Length', [])
                    if len(lengths) > 1 or self.headers.get('Transfer-Encoding'):
                        raise ValueError()
                    size = int(lengths[0]) if lengths else 0
                    if not 0 <= size <= 4096:
                        raise ValueError()
                except ValueError:
                    status, value = 413, {'error': 'unsupported body size or encoding'}
                else:
                    try:
                        raw = self.rfile.read(size) if size else b''
                        if len(raw) != size:
                            raise ValueError()
                        body = json.loads(raw) if self.command == 'POST' else None
                    except socket.timeout:
                        status, value = 408, {'error': 'body timeout'}
                    except (ValueError, UnicodeDecodeError, RecursionError):
                        status, value = 400, {'error': 'invalid JSON body'}
                    else:
                        cookie = self.headers.get('Cookie', '')[:4096]
                        candidate = next((p.strip().split('=', 1)[1] for p in cookie.split(';') if p.strip().startswith('arta_session=')), '')
                        token, state = lab.session(candidate)
                        before = state['realm']
                        status, value, transition = route(state, self.command, path, body)
            # No body, arbitrary path/query, auth header, recovery code or raw cookie.
            lab.record({'peer': peer, 'method': self.command, 'room': path if path in ROOMS else 'unknown',
                        'status': status, 'session_tag': hashlib.sha256(token.encode()).hexdigest()[:16] if token else None,
                        'realm_before': before, 'realm_after': state['realm'] if state else None,
                        'transition': transition, 'steps': state['steps'] if state else None})
            self.respond(status, value, token)
    return Handler


def serve(port, ingest_port, ingest_token, ready, config=None):
    sink = DatagramSink(ingest_port, ingest_token)
    server = HTTPServer(('127.0.0.1', port), handler(Lab(sink, config=config)))
    ready.send(server.server_port)
    ready.close()
    try:
        server.serve_forever()
    finally:
        server.server_close()
