import unittest
from arta.world import new_state, route


class WorldTests(unittest.TestCase):
    def test_recovery_is_consistent_and_session_bound(self):
        state = new_state(0)
        self.assertEqual(route(state, 'GET', '/workspace', None)[0], 403)
        code = route(state, 'GET', '/backup', None)[1]['recovery_code']
        self.assertEqual(route(state, 'POST', '/recovery', {'recovery_code': 'wrong'})[0], 403)
        self.assertEqual(state['realm'], 'sandbox')
        other = new_state(0)
        self.assertEqual(route(other, 'POST', '/recovery', {'recovery_code': code})[0], 403)
        result = route(state, 'POST', '/recovery', {'recovery_code': code})
        self.assertEqual(result[2], 'sandbox_to_workspace')
        self.assertEqual(route(state, 'POST', '/recovery', {'recovery_code': code})[2], None)
        self.assertEqual(route(state, 'GET', '/workspace', None)[0], 200)
        self.assertFalse(route(state, 'GET', '/diagnostics', None)[1]['sandbox_detected'])

    def test_no_mutation_on_get_or_invalid_post(self):
        state = new_state(0)
        self.assertEqual(route(state, 'GET', '/recovery', None)[0], 200)
        self.assertEqual(state['realm'], 'sandbox')
        self.assertEqual(route(state, 'POST', '/admin', {})[0], 405)
        self.assertEqual(route(state, 'POST', '/api/settings', {'maintenance': 1})[0], 400)
        self.assertFalse(state['settings']['maintenance'])

    def test_world_has_finite_budget(self):
        state = new_state(0)
        for _ in range(100):
            self.assertEqual(route(state, 'GET', '/admin', None)[0], 200)
        for _ in range(20):
            self.assertEqual(route(state, 'GET', '/admin', None)[0], 429)
        self.assertEqual(state['steps'], 101)
