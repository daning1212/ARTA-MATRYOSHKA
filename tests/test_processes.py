import http.client
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from arta.collector import valid
from arta.web import Lab
import queue


class BoundaryTests(unittest.TestCase):
    def test_collector_schema_and_queue_overflow(self):
        event = {'peer': '127.0.0.1', 'method': 'GET', 'room': '/admin', 'status': 200,
                 'session_tag': None, 'realm_before': None, 'realm_after': None, 'transition': None, 'steps': None}
        self.assertTrue(valid(event))
        self.assertFalse(valid({**event, 'password': 'never store'}))
        self.assertFalse(valid({**event, 'room': '/secret?password=123'}))
        sink = queue.Queue(maxsize=1)
        lab = Lab(sink)
        lab.record(event)
        lab.record(event)
        self.assertEqual(lab.dropped, 1)

    def test_process_separation_authentication_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.Popen([sys.executable, '-m', 'arta', '--port', '0', '--monitor-port', '0', '--data-dir', directory], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            runtime_path = Path(directory) / 'runtime.json'
            try:
                deadline = time.monotonic() + 10
                while not runtime_path.exists() and time.monotonic() < deadline and process.poll() is None:
                    time.sleep(0.05)
                self.assertTrue(runtime_path.exists(), 'lab failed to start')
                runtime = json.loads(runtime_path.read_text())
                self.assertNotEqual(runtime['collector']['pid'], runtime['decoy']['pid'])
                token_path = Path(directory) / 'monitor-token'
                token = token_path.read_text()
                if os.name == 'posix':
                    self.assertEqual(token_path.stat().st_mode & 0o777, 0o600)
                def request(name, path, auth=None, headers=None):
                    conn = http.client.HTTPConnection('127.0.0.1', runtime[name]['port'], timeout=3)
                    h = headers or {}
                    if auth:
                        h['Authorization'] = 'Bearer ' + auth
                    conn.request('GET', path, headers=h)
                    response = conn.getresponse()
                    result = response.status, json.loads(response.read())
                    conn.close()
                    return result
                self.assertEqual(request('collector', '/events')[0], 401)
                self.assertEqual(request('collector', '/events', 'wrong')[0], 401)
                self.assertEqual(request('collector', '/health', token)[0], 200)
                request('decoy', '/admin?password=hidden', headers={'X-Forwarded-For': 'spoofed'})
                deadline = time.monotonic() + 3
                events = []
                while not events and time.monotonic() < deadline:
                    events = request('collector', '/events', token)[1]
                    time.sleep(0.02)
                self.assertTrue(events)
                self.assertEqual(events[0]['peer'], '127.0.0.1')
                self.assertNotIn('hidden', json.dumps(events))
                self.assertEqual(request('decoy', '/events')[0], 404)
                process.terminate()
                process.wait(timeout=8)
                from arta.audit import Store
                store = Store(Path(directory) / 'events.sqlite3')
                self.assertTrue(store.recent())
                self.assertTrue(store.verify())
                store.db.close()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                stderr = process.stderr.read().decode()
                process.stderr.close()
                self.assertEqual(process.returncode, 0, stderr)

class WireTests(unittest.TestCase):
    def test_collector_rejects_invalid_wire_messages(self):
        import multiprocessing
        import socket
        from arta.collector import serve
        ctx = multiprocessing.get_context('spawn')
        with tempfile.TemporaryDirectory() as directory:
            receive, send = ctx.Pipe(duplex=False)
            child = ctx.Process(target=serve, args=(0, str(Path(directory) / 'events.db'), 'reader-key', 'writer-key', send))
            child.start()
            send.close()
            try:
                self.assertTrue(receive.poll(10))
                endpoints = receive.recv()
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                target = ('127.0.0.1', endpoints['ingest_port'])
                messages = [b'not json', b'x' * 2049,
                            json.dumps({'token': 'wrong', 'event': {}}).encode(),
                            json.dumps({'token': 'writer-key', 'event': {'password': 'secret'}}).encode()]
                for message in messages:
                    sock.sendto(message, target)
                event = {'peer': '127.0.0.1', 'method': 'GET', 'room': '/admin', 'status': 200,
                         'session_tag': None, 'realm_before': 'sandbox', 'realm_after': 'sandbox', 'transition': None, 'steps': 1}
                sock.sendto(json.dumps({'token': 'writer-key', 'event': event}).encode(), target)
                sock.close()
                deadline = time.monotonic() + 3
                health = {}
                while health.get('accepted', 0) < 1 and time.monotonic() < deadline:
                    conn = http.client.HTTPConnection('127.0.0.1', endpoints['port'], timeout=3)
                    conn.request('GET', '/health', headers={'Authorization': 'Bearer reader-key'})
                    health = json.loads(conn.getresponse().read())
                    conn.close()
                    time.sleep(0.02)
                self.assertEqual(health['accepted'], 1)
                self.assertEqual(health['rejected'], 4)
                self.assertTrue(health['chain_valid'])
            finally:
                receive.close()
                child.terminate()
                child.join(timeout=5)
                if child.is_alive():
                    child.kill()
                    child.join()
