"""Finite synthetic collection benchmark with independent Python processes.

Localhost only. No AI, GPU, distributed client, or security isolation claims.
"""
import argparse
import collections
import hashlib
import http.client
import json
import multiprocessing
import os
import platform
import statistics
import time

from .tollbench import server


def _client(port, bits, index, workers, resources, channel, require_proof=False, rate_limit=None):
    channel.send('ready')
    deadline = channel.recv()
    start_cpu = time.process_time()
    collected = hashes = errors = 0
    error_kinds = collections.Counter()
    error_samples = []
    stage = 'record'
    retry_after = 0

    def record_error(kind, status=None):
        nonlocal errors
        errors += 1
        error_kinds[kind] += 1
        if len(error_samples) < 10:
            error_samples.append({'kind': kind, 'stage': stage, 'status': status,
                                  'remaining_seconds': deadline - time.monotonic()})

    def post(path, data):
        nonlocal retry_after
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        connection = http.client.HTTPConnection('127.0.0.1', port,
                                                timeout=min(1, remaining))
        try:
            connection.request('POST', path, json.dumps(data))
            response = connection.getresponse()
            retry_after = float(response.getheader('Retry-After', '0'))
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    for number in range(index, resources, workers):
        if time.monotonic() >= deadline:
            break
        resource = f'demo-{number}'
        proof = {'resource': resource}
        try:
            if bits or require_proof:
                stage = 'challenge'
                status, challenge = post('/challenge', proof)
                if status != 200:
                    record_error('http_' + str(status), status)
                    continue
                # Zero-bit control performs both HTTP exchanges and redeems a
                # bound, expiring, single-use token, without client hash search.
                solved = bits == 0
                if solved:
                    proof.update(challenge=challenge['challenge'], nonce=0)
                for nonce in (range(2**32) if bits else ()):
                    if time.monotonic() >= deadline:
                        break
                    hashes += 1
                    digest = hashlib.sha256(
                        f"{challenge['challenge']}:{resource}:{nonce}".encode()
                    ).digest()
                    if int.from_bytes(digest, 'big') >> (256 - bits) == 0:
                        proof.update(challenge=challenge['challenge'], nonce=nonce)
                        solved = True
                        break
                if not solved:
                    break
            stage = 'record'
            status, _ = post('/record', proof)
            collected += int(status == 200)
            if status != 200:
                record_error('http_' + str(status), status)
                if status == 429 and rate_limit:
                    time.sleep(min(retry_after, max(0, deadline - time.monotonic())))
        except TimeoutError:
            record_error('deadline_timeout' if time.monotonic() >= deadline else 'timeout_before_deadline')
        except (OSError, http.client.HTTPException, ValueError):
            record_error('transport_or_decode_error')
    channel.send({'unique_records_collected': collected, 'hashes': hashes,
                  'cpu_seconds': time.process_time() - start_cpu,
                  'errors': errors, 'error_kinds': dict(error_kinds),
                  'error_samples': error_samples})
    channel.close()


def trial(bits, seconds, workers, resources=10000, require_proof=False, rate_limit=None):
    if (type(bits) is not int or not 0 <= bits <= 18
            or not 0.1 <= seconds <= 300
            or type(workers) is not int or not 1 <= workers <= 8
            or type(resources) is not int or not 1 <= resources <= 100000
            or type(require_proof) is not bool):
        raise ValueError('bits 0..18, seconds 0.1..300, workers 1..8, resources 1..100000')
    if rate_limit is not None:
        if (not isinstance(rate_limit, tuple) or len(rate_limit) != 2
                or type(rate_limit[0]) is not int or not 1 <= rate_limit[0] <= 1000
                or type(rate_limit[1]) is not int or not 1 <= rate_limit[1] <= 60
                or bits or require_proof):
            raise ValueError('rate_limit requires (requests 1..1000, window 1..60), zero bits, no proof')
    ctx = multiprocessing.get_context('spawn')
    parent, child = ctx.Pipe()
    service = ctx.Process(target=server, args=(bits, child, resources, require_proof, rate_limit))
    clients, channels = [], []
    service.start()
    child.close()
    try:
        if not parent.poll(10):
            raise RuntimeError('server startup failed')
        port = parent.recv()
        for index in range(workers):
            control, remote = ctx.Pipe()
            client = ctx.Process(target=_client,
                                 args=(port, bits, index, workers, resources, remote, require_proof, rate_limit))
            channels.append(control)
            clients.append(client)
            client.start()
            remote.close()
        for channel in channels:
            if not channel.poll(10) or channel.recv() != 'ready':
                raise RuntimeError('client startup failed')
        start = time.monotonic()
        deadline = start + seconds
        for channel in channels:
            channel.send(deadline)
        results = []
        for channel in channels:
            if not channel.poll(max(0, deadline - time.monotonic()) + 3):
                raise RuntimeError('client failed to finish')
            results.append(channel.recv())
        elapsed = time.monotonic() - start
        parent.send('stop')
        if not parent.poll(5):
            raise RuntimeError('server failed to stop')
        stats = parent.recv()
        client_count = sum(result['unique_records_collected'] for result in results)
        condition = 'rate-limit' if rate_limit else ('pow' if bits else ('no-work' if require_proof else 'direct'))
        error_kinds = collections.Counter()
        for result in results:
            error_kinds.update(result['error_kinds'])
        return {'condition': condition, 'bits': bits, 'client_processes': workers, 'budget_seconds': seconds,
                'rate_limit': {'requests': rate_limit[0], 'window_seconds': rate_limit[1]} if rate_limit else None,
                'elapsed_seconds': elapsed, 'available_unique_records': resources,
                'unique_records_collected': client_count,
                'collection_fraction': client_count / resources,
                'client_hashes': sum(result['hashes'] for result in results),
                'client_cpu_seconds': sum(result['cpu_seconds'] for result in results),
                'client_errors': sum(result['errors'] for result in results),
                'client_error_kinds': dict(error_kinds),
                'client_error_samples': [sample for result in results for sample in result['error_samples']],
                'dataset_exhausted': client_count == resources,
                'count_matches_server': client_count == stats['unique_records_served'],
                **stats}
    finally:
        for process in clients + [service]:
            process.join(timeout=2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
        for channel in channels + [parent]:
            channel.close()


def summarize(runs):
    groups = {}
    for run in runs:
        condition = run.get('condition', 'pow' if run['bits'] else 'direct')
        key = (run['client_processes'], condition, run['bits'])
        groups.setdefault(key, []).append(run)
    summaries = []
    for (workers, condition, bits), group in sorted(groups.items()):
        values = [run['unique_records_collected'] for run in group]
        summaries.append({'client_processes': workers, 'condition': condition, 'bits': bits,
                          'repeats': len(group), 'unique_mean': statistics.mean(values),
                          'unique_median': statistics.median(values),
                          'unique_stdev': statistics.stdev(values) if len(values) > 1 else None,
                          'unique_min': min(values), 'unique_max': max(values),
                          'server_unique_mean': statistics.mean(r['unique_records_served'] for r in group),
                          'count_mismatch_runs': sum(not r['count_matches_server'] for r in group),
                          'client_cpu_mean': statistics.mean(r['client_cpu_seconds'] for r in group),
                          'server_cpu_mean': statistics.mean(r['server_cpu'] for r in group),
                          'dataset_exhausted_runs': sum(r['dataset_exhausted'] for r in group),
                          'client_errors': sum(r['client_errors'] for r in group)})
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=5)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--workers', type=int, nargs='+', default=[1, 2, 4])
    parser.add_argument('--bits', type=int, default=14)
    parser.add_argument('--resources', type=int, default=100000)
    parser.add_argument('--include-rate-limit', action='store_true', help='Compare existing per-IP limiter too')
    parser.add_argument('--rate', type=int, default=30)
    parser.add_argument('--window', type=int, default=60)
    args = parser.parse_args()
    if (not 0.1 <= args.seconds <= 300 or not 1 <= args.repeats <= 10
            or not 1 <= args.bits <= 18 or not 1 <= args.resources <= 100000
            or not args.workers or len(args.workers) > 8
            or len(set(args.workers)) != len(args.workers)
            or any(not 1 <= n <= 8 for n in args.workers)
            or not 1 <= args.rate <= 1000 or not 1 <= args.window <= 60):
        parser.error('seconds 0.1..300, repeats 1..10, bits 1..18, resources 1..100000, distinct workers 1..8, rate 1..1000, window 1..60')
    runs = []
    for repeat in range(args.repeats):
        # Rotate process-count and condition order; retain repeat IDs for paired comparisons.
        order = args.workers[repeat % len(args.workers):] + args.workers[:repeat % len(args.workers)]
        for workers in order:
            conditions = [(0, False, None), (0, True, None), (args.bits, True, None)]
            if args.include_rate_limit:
                conditions.append((0, False, (args.rate, args.window)))
            offset = repeat % len(conditions)
            conditions = conditions[offset:] + conditions[:offset]
            if repeat % 2:
                conditions.reverse()
            for bits, require_proof, rate_limit in conditions:
                runs.append({'repeat': repeat, **trial(bits, args.seconds, workers, args.resources, require_proof, rate_limit)})
    print(json.dumps({'kind': 'localhost-finite-synthetic-collection', 'ai_test': False,
                      'environment': {'python': platform.python_version(),
                                      'platform': platform.platform(), 'logical_cpus': os.cpu_count()},
                      'limitations': ['same-host CPU contention', 'single synchronous HTTP server',
                                      'no verified OS/network isolation', 'no GPU or distributed client',
                                      'puzzle costs alone do not establish security effectiveness'],
                      'planned_budget_seconds': args.seconds * args.repeats * len(args.workers) * (4 if args.include_rate_limit else 3),
                      'runs': runs, 'summary': summarize(runs)}, indent=2))


if __name__ == '__main__':
    main()
