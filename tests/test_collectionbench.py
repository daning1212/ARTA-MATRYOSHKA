import unittest

from arta.collectionbench import summarize, trial


class CollectionTests(unittest.TestCase):
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
        for kwargs in ({'bits': 19}, {'workers': 0}, {'resources': 0}, {'seconds': 301}):
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
