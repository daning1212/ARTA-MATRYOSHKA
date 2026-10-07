import hashlib
import unittest
from arta.tollbench import Gate, trial

class TollTests(unittest.TestCase):
    def test_nonzero_proof_rejection_and_single_use(self):
        gate = Gate(bits=4)
        proof = gate.issue('demo-0', now=0)
        def valid(nonce):
            digest = hashlib.sha256(f"{proof['challenge']}:demo-0:{nonce}".encode()).digest()
            return digest[0] < 16
        invalid = next(n for n in range(10000) if not valid(n))
        solved = next(n for n in range(10000) if valid(n))
        self.assertFalse(gate.redeem(proof['challenge'], 'demo-0', invalid, now=1))
        self.assertFalse(gate.redeem(proof['challenge'], 'demo-1', solved, now=1))
        self.assertTrue(gate.redeem(proof['challenge'], 'demo-0', solved, now=1))
        self.assertFalse(gate.redeem(proof['challenge'], 'demo-0', solved, now=1))
    def test_binding_expiry_replay_and_limits(self):
        gate = Gate(bits=0, ttl=2, capacity=1)
        proof = gate.issue('demo-0', now=0)
        self.assertIsNone(gate.issue('demo-0', now=1))
        self.assertFalse(gate.redeem(proof['challenge'], 'demo-1', 0, now=1))
        self.assertTrue(gate.redeem(proof['challenge'], 'demo-0', 0, now=1))
        self.assertFalse(gate.redeem(proof['challenge'], 'demo-0', 0, now=1))
        proof = gate.issue('demo-0', now=3)
        self.assertFalse(gate.redeem(proof['challenge'], 'demo-0', 0, now=5))
        self.assertFalse(gate.redeem([], 'demo-0', True))
        with self.assertRaises(ValueError):
            Gate(bits=19)
    def test_http_trial(self):
        for bits in (0, 14):
            result = trial(bits, 0.2, 1)
            self.assertEqual(result['records'], result['records_served_including_repeats'])
            self.assertGreater(result['requests'], 0)
