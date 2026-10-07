"""ARTA localhost lab supervisor. No production isolation is claimed."""
import argparse
import json
import multiprocessing
import os
import secrets
import signal
import time
from pathlib import Path
from . import collector, web
from .world import PRESETS


def private_write(path, content):
    # Refuse symlink writes. Refresh permissions even for an existing file.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w') as stream:
        os.chmod(path, 0o600)
        stream.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--monitor-port', type=int, default=8081)
    parser.add_argument('--data-dir', default='data')
    parser.add_argument('--scenario', choices=PRESETS, default='baseline')
    parser.add_argument('--max-runtime', type=int, default=900)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535 or not 0 <= args.monitor_port <= 65535:
        parser.error('ports must be between 0 and 65535')
    if not 1 <= args.max_runtime <= 3600:
        parser.error('max-runtime must be 1..3600 seconds')
    directory = Path(args.data_dir).resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    token = secrets.token_urlsafe(32)
    private_write(directory / 'monitor-token', token)
    ctx = multiprocessing.get_context('spawn')
    ingest_token = secrets.token_urlsafe(32)
    processes = []
    try:
        endpoints = {}
        def start(name, target, parameters, extra=()):
            receive, send = ctx.Pipe(duplex=False)
            process = ctx.Process(target=target, args=(*parameters, send, *extra), name='arta-' + name)
            process.start()
            processes.append(process)
            send.close()
            if not receive.poll(10):
                raise RuntimeError(name + ' startup timed out')
            result = receive.recv()
            receive.close()
            endpoints[name] = {'pid': process.pid, 'port': result['port'] if isinstance(result, dict) else result}
            return result
        result = start('collector', collector.serve, (args.monitor_port, str(directory / 'events.sqlite3'), token, ingest_token))
        start('decoy', web.serve, (args.port, result['ingest_port'], ingest_token), (PRESETS[args.scenario],))
        private_write(directory / 'runtime.json', json.dumps(endpoints))
        print(f"ARTA LOCAL LAB — decoy http://127.0.0.1:{endpoints['decoy']['port']} | observer http://127.0.0.1:{endpoints['collector']['port']}", flush=True)
        print(f'Monitor credential: {directory / "monitor-token"}; use python -m arta.observe', flush=True)

        def stop(*_):
            raise KeyboardInterrupt()
        signal.signal(signal.SIGTERM, stop)
        deadline = time.monotonic() + args.max_runtime
        while all(p.is_alive() for p in processes):
            if time.monotonic() >= deadline:
                print('ARTA runtime budget reached', flush=True)
                return
            time.sleep(0.2)
        raise RuntimeError('child process exited; stopping lab')
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            process.join(timeout=3)
            if process.is_alive():
                process.kill()
                process.join(timeout=3)
        (directory / 'runtime.json').unlink(missing_ok=True)


if __name__ == '__main__':
    main()
