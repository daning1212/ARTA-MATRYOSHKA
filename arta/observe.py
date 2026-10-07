"""Read authenticated local telemetry without exposing tokens in command history."""
import argparse
import http.client
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default='data')
    parser.add_argument('--health', action='store_true')
    args = parser.parse_args()
    directory = Path(args.data_dir)
    runtime = json.loads((directory / 'runtime.json').read_text())
    token = (directory / 'monitor-token').read_text().strip()
    conn = http.client.HTTPConnection('127.0.0.1', runtime['collector']['port'], timeout=3)
    conn.request('GET', '/health' if args.health else '/events', headers={'Authorization': 'Bearer ' + token})
    response = conn.getresponse()
    value = json.loads(response.read())
    conn.close()
    if response.status != 200:
        raise SystemExit('observer request rejected')
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
