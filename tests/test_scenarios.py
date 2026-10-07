import unittest
from arta.world import PRESETS, WorldConfig, new_state, route
from arta.experiment import run


class ScenarioTests(unittest.TestCase):
    def recover(self, state):
        code = route(state, 'GET', '/backup', None)[1]['recovery_code']
        route(state, 'POST', '/recovery', {'recovery_code': code})

    def test_options_bounded_and_disabled_by_default(self):
        for kwargs in ({'doors': 9}, {'exits': 4}, {'doors': True}, {'mirror': 1}):
            with self.assertRaises(ValueError):
                WorldConfig(**kwargs)
        state = new_state(0)
        for path in ('/doors/0', '/exit/0', '/replica', '/manifest'):
            self.assertEqual(route(state, 'GET', path, None)[0], 404)

    def test_many_doors_are_local_and_finite(self):
        state = new_state(0, PRESETS['combined'])
        links = route(state, 'GET', '/', None)[1]['links']
        self.assertEqual(len(links), 8)
        for link in links:
            result = route(state, 'GET', link, None)
            self.assertEqual(result[0], 200)
            if 'target' in result[1]:
                self.assertTrue(result[1]['target'].startswith('/'))
                self.assertFalse(result[1]['target'].startswith('//'))
        self.assertEqual(route(state, 'GET', '/doors/999', None)[0], 404)

    def test_false_exit_cannot_skip_repeat_or_mutate_on_get(self):
        state = new_state(0, PRESETS['combined'])
        self.assertEqual(route(state, 'POST', '/exit/0', {'confirm': True})[0], 403)
        self.recover(state)
        route(state, 'POST', '/api/settings', {'maintenance': True})
        self.assertEqual(route(state, 'POST', '/exit/1', {'confirm': True})[0], 403)
        route(state, 'GET', '/exit/0', None)
        self.assertEqual(state['layer'], 0)
        result = route(state, 'POST', '/exit/0', {'confirm': True})
        self.assertEqual(result[2], 'false_exit')
        self.assertFalse(state['settings']['maintenance'])
        self.assertTrue(state['contexts'][0]['settings']['maintenance'])
        self.assertIsNone(route(state, 'POST', '/exit/0', {'confirm': True})[2])
        self.assertEqual(state['layer'], 1)
        route(state, 'POST', '/exit/1', {'confirm': True})
        self.assertEqual(state['layer'], 2)
        self.assertNotIn('next_system', route(state, 'GET', '/workspace', None)[1])
        self.assertEqual(route(state, 'POST', '/exit/2', {'confirm': True})[0], 404)

    def test_mirror_and_manifest_consistent_without_raw_input(self):
        state = new_state(0, PRESETS['combined'])
        self.recover(state)
        route(state, 'POST', '/api/settings', {'maintenance': True})
        replica = route(state, 'GET', '/replica', None)[1]
        manifest = route(state, 'GET', '/manifest', None)[1]
        self.assertEqual(replica['settings'], state['settings'])
        self.assertEqual(replica['revision'], manifest['summary']['revision'])
        self.assertEqual(manifest['summary']['revision'], manifest['detail']['settings_revision'])
        self.assertEqual(route(state, 'POST', '/api/settings', {'maintenance': True, 'payload': 'secret'})[0], 400)
        self.assertNotIn('payload', replica)

    def test_easy_hint_and_scripted_comparisons(self):
        state = new_state(0, PRESETS['easy'])
        admin = route(state, 'GET', '/admin', None)[1]
        self.assertEqual(admin['recovery_code'], state['recovery_code'])
        for scenario in PRESETS:
            for strategy in ('direct', 'verify', 'enumerate'):
                result = run(scenario, strategy)
                self.assertTrue(result['simulated_setting_changed'])
                self.assertLess(result['requests'], 100)
                self.assertEqual(result['false_exit_transitions'], PRESETS[scenario].exits)
                self.assertEqual(result['ai_effectiveness'], 'not measured')

    def test_unknown_requests_consume_world_budget(self):
        state = new_state(0)
        for _ in range(100):
            self.assertEqual(route(state, 'GET', '/unknown', None)[0], 404)
        self.assertEqual(route(state, 'GET', '/', None)[0], 429)
