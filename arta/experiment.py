"""Scripted local smoke comparisons. Not an AI effectiveness benchmark."""
import argparse
import json
from .world import PRESETS, new_state, route


def run(scenario, strategy):
    state = new_state(0, PRESETS[scenario])
    trace = []

    def call(method, path, body=None):
        status, value, transition = route(state, method, path, body)
        trace.append({'method': method, 'path': path, 'status': status, 'transition': transition})
        return value

    root = call('GET', '/')
    admin = call('GET', '/admin')
    if strategy == 'enumerate':
        for path in root['links']:
            call('GET', path)
    code = admin.get('recovery_code')
    if code is None:
        code = call('GET', '/backup')['recovery_code']
    if strategy == 'verify':
        call('GET', '/workspace')
        diagnostics = call('GET', '/diagnostics')
        if 'manifest' in diagnostics:
            call('GET', diagnostics['manifest'])
    call('POST', '/recovery', {'recovery_code': code})
    while True:
        workspace = call('GET', '/workspace')
        if strategy == 'verify':
            call('GET', '/diagnostics')
        if 'next_system' not in workspace:
            break
        call('POST', workspace['next_system'], {'confirm': True})
    call('POST', '/api/settings', {'maintenance': True})
    if strategy == 'verify':
        call('GET', '/api/settings')
        if 'replica' in workspace:
            call('GET', workspace['replica'])
    seen = set()
    revisits = 0
    for event in trace:
        if event['method'] == 'GET':
            if event['path'] in seen:
                revisits += 1
            seen.add(event['path'])
    return {'scenario': scenario, 'strategy': strategy, 'requests': len(trace),
            'distinct_paths': len({event['path'] for event in trace}), 'repeated_gets': revisits,
            'false_exit_transitions': sum(event['transition'] == 'false_exit' for event in trace),
            'simulated_setting_changed': state['settings']['maintenance'],
            'ai_effectiveness': 'not measured', 'trace': trace}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps({'kind': 'scripted-functional-comparison',
                      'warning': 'Fixed scripts, no LLM, no inference or attacker cost measurement.',
                      'runs': [run(s, p) for s in PRESETS for p in ('direct', 'verify', 'enumerate')]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
