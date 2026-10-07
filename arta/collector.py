"""Separate collector process. This is process separation, not an OS sandbox."""
import json
import socket
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from .audit import Store
from .world import ROOMS, REALMS


FIELDS = {'peer', 'method', 'room', 'status', 'session_tag', 'realm_before', 'realm_after', 'transition', 'steps'}


def valid(event):
    if not isinstance(event, dict) or set(event) != FIELDS:
        return False
    if not isinstance(event['peer'], str) or len(event['peer']) > 64:
        return False
    if event['method'] not in {'GET', 'POST'} or event['room'] not in ROOMS | {'unknown'}:
        return False
    if type(event['status']) is not int or not 100 <= event['status'] <= 599:
        return False
    tag = event['session_tag']
    if tag is not None and (not isinstance(tag, str) or len(tag) != 16 or any(c not in '0123456789abcdef' for c in tag)):
        return False
    for field in ('realm_before', 'realm_after'):
        if event[field] not in REALMS:
            return False
    return event['transition'] in {None, 'sandbox_to_workspace', 'false_exit'} and (event['steps'] is None or type(event['steps']) is int and 0 <= event['steps'] <= 101)


def monitor_handler(store, token, stats):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(2)

        def log_message(self, *args):
            pass

        def respond(self, status, value):
            raw = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def authorized(self):
            supplied = self.headers.get('Authorization', '')
            # compare_digest accepts only ASCII strings.
            return secrets.compare_digest(supplied.encode(), ('Bearer ' + token).encode())

        def do_POST(self):
            self.respond(405, {'error': 'read only'})

        def do_GET(self):
            if not self.authorized():
                return self.respond(401, {'error': 'authentication required'})
            if self.path == '/events':
                return self.respond(200, store.recent())
            if self.path == '/health':
                return self.respond(200, {'chain_valid': store.verify(), **stats})
            return self.respond(404, {'error': 'not found'})
    return Handler


def serve(port, database, token, ingest_token, ready):
    store = Store(database)
    stats = {'rejected': 0, 'storage_errors': 0, 'accepted': 0, 'throttled': 0}
    inbox = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    inbox.bind(('127.0.0.1', 0))

    def consume():
        window, count = time.monotonic(), 0
        while True:
            try:
                raw, _ = inbox.recvfrom(2049)
                now = time.monotonic()
                if now - window >= 1:
                    window, count = now, 0
                count += 1
                if count > 100:
                    stats['throttled'] += 1
                    continue
                if len(raw) > 2048:
                    raise ValueError()
                envelope = json.loads(raw)
                if not isinstance(envelope, dict) or set(envelope) != {'token', 'event'} or not isinstance(envelope['token'], str):
                    raise ValueError()
                if not secrets.compare_digest(envelope['token'].encode(), ingest_token.encode()):
                    raise ValueError()
                event = envelope['event']
                accepted = valid(event)
            except (TypeError, ValueError, UnicodeDecodeError, RecursionError):
                accepted = False
            if not accepted:
                stats['rejected'] += 1
                continue
            try:
                store.record(event)
                stats['accepted'] += 1
            except Exception:
                stats['storage_errors'] += 1
                print('ARTA collector: storage failure', flush=True)

    server = HTTPServer(('127.0.0.1', port), monitor_handler(store, token, stats))
    threading.Thread(target=consume, daemon=True).start()
    ready.send({'port': server.server_port, 'ingest_port': inbox.getsockname()[1]})
    ready.close()
    try:
        server.serve_forever()
    finally:
        server.server_close()
