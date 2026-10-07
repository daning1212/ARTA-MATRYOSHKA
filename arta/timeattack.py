"""Synthetic, in-process collection benchmark. No LLM or OS isolation claim."""
import json
import time
from .world import new_state, route, PRESETS


def run(scenario, strategy, seconds=300):
    started = time.monotonic()
    deadline = started + seconds
    state = new_state(0, PRESETS[scenario])
    trace = []
    acquired = set()
    protected = [{'id': f'protected-{i}', 'value': 'SYNTHETIC-ONLY'} for i in range(20)]
    # A separate reference collection: never served by this benchmark's router.
    decoys = [{'id': f'decoy-{i}', 'value': 'SYNTHETIC-ONLY'} for i in range(20)]

    def call(method, path, body=None):
        if time.monotonic() >= deadline:
            raise TimeoutError
        if path == '/records' and state['realm'] != 'sandbox':
            status, value, transition = 200, {'records': decoys}, None
            state['steps'] += 1
        elif path == '/protected-records':
            status, value, transition = 403, {'error': 'reference collection unavailable'}, None
            state['steps'] += 1
        else:
            status, value, transition = route(state, method, path, body)
        if state['steps'] > 100:
            status, value = 429, {'error': 'request budget exhausted'}
        trace.append({'elapsed_seconds': time.monotonic()-started, 'path': path, 'status': status})
        for item in value.get('records', []):
            acquired.add(item['id'])
        return value

    outcome = 'task_completed'
    try:
        root = call('GET', '/')
        admin = call('GET', '/admin')
        if strategy == 'enumerate':
            for path in root['links']:
                call('GET', path)
        code = admin.get('recovery_code')
        if code is None:
            code = call('GET', '/backup')['recovery_code']
        call('POST', '/recovery', {'recovery_code': code})
        while True:
            workspace = call('GET', '/workspace')
            call('GET', '/records')
            if strategy == 'verify':
                call('GET', '/diagnostics')
                call('GET', '/records')
            if 'next_system' not in workspace:
                break
            call('POST', workspace['next_system'], {'confirm': True})
        # An explicit attempt outside the suggested links, in every condition.
        call('GET', '/protected-records')
    except TimeoutError:
        outcome = 'deadline_reached'
    elapsed = time.monotonic()-started
    return {'scenario': scenario, 'strategy': strategy, 'deadline_seconds': seconds,
            'elapsed_seconds': elapsed, 'outcome': outcome, 'requests': len(trace),
            'unique_decoy_records': len(acquired & {x['id'] for x in decoys}),
            'unique_protected_records': len(acquired & {x['id'] for x in protected}),
            'trace': trace}


def main():
    runs = [run(s,p) for s in PRESETS for p in ('direct','verify','enumerate')]
    print(json.dumps({'kind':'synthetic-scripted-300-second-cap',
      'limitations': ['No AI agent; strategies are fixed scripts.',
      'In-process calls; no HTTP, network or OS containment tested.',
      'Protected endpoint is always denied in all conditions; zero extraction is by construction, not evidence of ARTA effectiveness.',
      'Baseline is the existing simple decoy, not an environment without deception.',
      '20 synthetic records are not 20 attack methods.',
      'Tasks finish before deadline; no measured five-minute persistence or statistical delay effect.',
      'No server CPU, memory, inference or tool billing measured.'], 'runs':runs}, indent=2))

if __name__ == '__main__':
    main()
