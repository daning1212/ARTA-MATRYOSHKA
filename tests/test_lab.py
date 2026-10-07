import http.client
import json
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
import queue
from arta.audit import Store
from arta.web import Lab, handler


class LabTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'events.db', limit=20)
        self.inbox = queue.Queue(maxsize=256)
        self.lab = Lab(self.inbox)
        self.server = HTTPServer(('127.0.0.1', 0), handler(self.lab))
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.store.db.close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, cookie=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        headers = {'Cookie': cookie} if cookie else {}
        conn.request(method, path, body, headers)
        response = conn.getresponse()
        result = response.status, json.loads(response.read()), response.getheader('Set-Cookie')
        conn.close()
        return result

    def test_shadow_state_is_session_local(self):
        _, _, cookie = self.request('GET', '/admin')
        status, body, _ = self.request('POST', '/api/settings', '{"maintenance":true}', cookie)
        self.assertEqual(status, 200)
        self.assertTrue(body['settings']['maintenance'])
        self.assertTrue(self.request('GET', '/api/settings', cookie=cookie)[1]['settings']['maintenance'])
        self.assertFalse(self.request('GET', '/api/settings')[1]['settings']['maintenance'])

    def test_rate_limit(self):
        self.lab.rate = 2
        self.request('GET', '/')
        self.request('GET', '/')
        self.assertEqual(self.request('GET', '/')[0], 429)

    def test_secrets_not_recorded_and_tamper_detected(self):
        self.request('POST', '/login?password=secret-query', 'password=secret-body')
        while not self.inbox.empty():
            self.store.record(self.inbox.get_nowait())
        events = json.dumps(self.store.recent())
        self.assertNotIn('secret', events)
        self.assertTrue(self.store.verify())
        self.store.db.execute("UPDATE events SET payload='{}'")
        self.store.db.commit()
        self.assertFalse(self.store.verify())

    def test_retention_and_capacity(self):
        for i in range(30):
            self.store.record({'n': i})
        self.assertEqual(len(self.store.recent()), 20)
        self.assertTrue(self.store.verify())
        self.lab.capacity = 2
        for i in range(10):
            self.lab.session(str(i))
            self.lab.allowed(str(i))
        self.assertEqual(len(self.lab.sessions), 2)
        self.assertEqual(len(self.lab.clients), 2)

    def test_combined_http_flow_and_event_schema(self):
        from arta.world import PRESETS
        from arta.collector import valid
        self.lab.config = PRESETS['combined']
        _, backup, cookie = self.request('GET', '/backup')
        self.assertEqual(self.request('POST', '/recovery', json.dumps({'recovery_code': backup['recovery_code']}), cookie)[0], 200)
        self.assertEqual(self.request('POST', '/exit/0', '{"confirm":true}', cookie)[0], 200)
        self.request('POST', '/api/settings', '{"maintenance":true}', cookie)
        self.assertTrue(self.request('GET', '/replica', cookie=cookie)[1]['settings']['maintenance'])
        events = []
        while not self.inbox.empty():
            events.append(self.inbox.get_nowait())
        self.assertTrue(all(valid(event) for event in events))
        self.assertTrue(any(event['transition'] == 'false_exit' for event in events))
        self.assertNotIn(backup['recovery_code'], json.dumps(events))

    def test_invalid_and_oversized_bodies(self):
        self.assertEqual(self.request('POST', '/api/settings', '{"maintenance":"yes"}')[0], 400)
        self.assertEqual(self.request('POST', '/api/settings', 'x' * 4097)[0], 413)


if __name__ == '__main__':
    unittest.main()

class StorageBudgetTests(unittest.TestCase):
    def test_sqlite_page_budget(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'bounded.db', max_bytes=32 * 1024)
            with self.assertRaises(sqlite3.OperationalError):
                for _ in range(100):
                    store.record({'value': 'x' * 4096})
            self.assertLessEqual(store.db.execute('PRAGMA page_count').fetchone()[0] * store.db.execute('PRAGMA page_size').fetchone()[0], 32 * 1024)
            self.assertTrue(store.verify())
            store.db.close()
