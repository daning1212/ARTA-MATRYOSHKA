import http.client
import json
import multiprocessing
import queue
import unittest
from unittest.mock import patch

from arta.collectionbench import summarize, trial
from arta.tollbench import server
from arta.web import Lab


class CollectionTests(unittest.TestCase):
    def test_existing_rate_window_replenishes_and_separates_ips(self):
        lab = Lab(queue.Queue(), rate=2, window=1)
        with patch('arta.web.time.monotonic', return_value=0):
            self.assertTrue(lab.allowed('one'))
            self.assertTrue(lab.allowed('one'))
            self.assertFalse(lab.allowed('one'))
            self.assertTrue(lab.allowed('two'))
        with patch('arta.web.time.monotonic', return_value=0.9):
            self.assertFalse(lab.allowed('one'))
        with patch('arta.web.time.monotonic', return_value=1):
            self.assertTrue(lab.allowed('one'))

    def test_rate_limit_is_shared_across_clients_on_one_ip(self):
        result = trial(0, 0.3, 2, resources=8, rate_limit=(3, 60))
        self.assertEqual(result['condition'], 'rate-limit')
        self.assertEqual(result['unique_records_collected'], 3)
        self.assertEqual(result['client_hashes'], 0)
        self.assertGreater(result['rate_limit_denials'], 0)
        self.assertEqual(result['client_error_kinds'], {'http_429': result['client_errors']})
        self.assertTrue(result['count_matches_server'])

    def test_zero_bit_server_enforces_token_and_single_use(self):
        ctx = multiprocessing.get_context('spawn')
        parent, child = ctx.Pipe()
        process = ctx.Process(target=server, args=(0, child, 8, True))
        process.start()
        child.close()
        try:
            self.assertTrue(parent.poll(5))
            port = parent.recv()
            def post(path, data):
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
                try:
                    connection.request('POST', path, json.dumps(data))
                    response = connection.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    connection.close()
            self.assertEqual(post('/record', {'resource': 'demo-0'})[0], 403)
            status, challenge = post('/challenge', {'resource': 'demo-0'})
            self.assertEqual(status, 200)
            proof = dict(resource='demo-0', challenge=challenge['challenge'], nonce=0)
            self.assertEqual(post('/record', dict(proof, resource='demo-1'))[0], 403)
            self.assertEqual(post('/record', proof)[0], 200)
            self.assertEqual(post('/record', proof)[0], 403)
            parent.send('stop')
            self.assertTrue(parent.poll(5))
            self.assertEqual(parent.recv()['records'], 1)
        finally:
            process.join(timeout=2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
            parent.close()

    def test_no_work_control_matches_two_exchanges_without_search(self):
        result = trial(0, 2, 2, resources=8, require_proof=True)
        self.assertEqual(result['condition'], 'no-work')
        self.assertEqual(result['unique_records_collected'], 8)
        self.assertEqual(result['requests'], 16)
        self.assertEqual(result['client_hashes'], 0)
        self.assertTrue(result['count_matches_server'])
        self.assertEqual(result['client_errors'], 0)

    def test_finite_dataset_with_multiple_processes(self):
        result = trial(0, 2, 2, resources=8)
        self.assertEqual(result['unique_records_collected'], 8)
        self.assertEqual(result['unique_records_served'], 8)
        self.assertEqual(result['records'], 8)
        self.assertTrue(result['dataset_exhausted'])
        self.assertTrue(result['count_matches_server'])
        self.assertEqual(result['client_errors'], 0)

    def test_toll_requires_work_for_distinct_records(self):
        result = trial(4, 2, 2, resources=8)
        self.assertEqual(result['unique_records_collected'], 8)
        self.assertGreaterEqual(result['client_hashes'], 8)
        self.assertEqual(result['requests'], 16)
        self.assertTrue(result['count_matches_server'])
        self.assertEqual(result['client_errors'], 0)

    def test_invalid_configuration(self):
        for kwargs in ({'bits': 19}, {'workers': 0}, {'resources': 0}, {'seconds': 301},
                       {'rate_limit': (0, 1)}, {'rate_limit': (1, 0)},
                       {'rate_limit': (1, 61)}, {'rate_limit': (1, 1), 'bits': 4},
                       {'rate_limit': (1, 1), 'require_proof': True}):
            values = dict(bits=0, seconds=1, workers=1, resources=8)
            values.update(kwargs)
            with self.assertRaises(ValueError):
                trial(**values)

    def test_summary_spread(self):
        base = dict(client_processes=2, bits=14, client_cpu_seconds=1,
                    server_cpu=0.1, dataset_exhausted=False, client_errors=0,
                    unique_records_served=4, count_matches_server=True)
        result = summarize([dict(base, unique_records_collected=n) for n in (2, 4, 6)])[0]
        self.assertEqual(result['unique_mean'], 4)
        self.assertEqual(result['unique_median'], 4)
        self.assertEqual(result['unique_stdev'], 2)
