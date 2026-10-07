import http.client
import json
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from arta.__main__ import Lab, Store, handler


class LabTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'events.db', limit=20)
        self.lab = Lab(self.store)
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

    def test_rate_limit_and_untrusted_forwarded_header(self):
        self.lab.rate = 2
        self.request('GET', '/')
        self.request('GET', '/')
        self.assertEqual(self.request('GET', '/')[0], 429)

    def test_secrets_not_recorded_and_tamper_detected(self):
        self.request('POST', '/login?password=secret-query', 'password=secret-body')
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

    def test_invalid_and_oversized_bodies(self):
        self.assertEqual(self.request('POST', '/api/settings', '{"maintenance":"yes"}')[0], 400)
        self.assertEqual(self.request('POST', '/api/settings', 'x' * 4097)[0], 413)


if __name__ == '__main__':
    unittest.main()
