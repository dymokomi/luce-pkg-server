#!/usr/bin/env python3
"""Object storage through stock Git: a release holding a large object, and concurrent
releases while the timer's online checkpoint bakes the database. No push may be refused."""
import concurrent.futures
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))
from registry_client import Client, free_port, released, request, start, stop  # noqa: E402

registry, admin, fixture = [Path(value).resolve() for value in sys.argv[1:4]]
TOKEN = 'integration-store-token'

with tempfile.TemporaryDirectory(prefix='registry-storage-', dir='/tmp') as temporary:
    root = Path(temporary)
    database = root / 'registry.db'
    socket_path = Path(str(database) + '.sock')
    subprocess.check_output([str(fixture), str(database)], text=True, timeout=30)
    port = free_port()
    environment = dict(os.environ, LUCE_REGISTRY_STORE_TOKEN=TOKEN, LUCE_REGISTRY_ORIGIN='https://pkg.luciaos.com',
                       LUCE_REGISTRY_SITE=str(root / 'site'))
    with (root / 'registry.log').open('w+') as log:
        process = start(registry, database, port, environment, log)
        try:
            status, session = request(port, 'POST', '/v1/sessions', {'name': 'testadmin', 'password': 'fixture-password'})
            assert status == 200
            client = Client(root, port, {'Authorization': 'Bearer ' + session.decode()})

            # One object far above the 16 MiB Prism journal frame, incompressible.
            large = os.urandom(24 * 1048576)
            large_work, git_environment = client.repository('large', {'large.bin': large, 'small.txt': b'small\n'}, '1.0.0')
            code, stderr, elapsed = client.push(large_work, git_environment, 'v1.0.0')
            assert code == 0, stderr
            print(f'TIMING large-object push (24 MiB) {elapsed:.2f}s', flush=True)
            assert released(root / 'site', 'testadmin/large', '1.0.0', 'large.bin') == large
            print('PASS a 24 MiB object pushes and is released byte for byte', flush=True)

            # Concurrent pushes, each a ~2 MiB package with a release tag, while the
            # timer's online checkpoint bakes the database in a loop. Nothing is refused.
            baking = threading.Event()
            bakes, bake_failures = [], []
            def bake_loop():
                while not baking.is_set():
                    result = subprocess.run([str(admin), 'checkpoint', str(socket_path)], env=environment,
                                            capture_output=True, timeout=120)
                    (bakes if result.returncode == 0 else bake_failures).append(result.stderr)
            payloads = {f'para-{index}': {'data.bin': os.urandom(2 * 1048576), 'README.md': b'# fixture\n'}
                        for index in range(3)}
            prepared = {name: client.repository(name, files, '1.0.0') for name, files in payloads.items()}
            baker = threading.Thread(target=bake_loop)
            baker.start()
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                    futures = {name: pool.submit(client.push, work, env, 'v1.0.0')
                               for name, (work, env) in prepared.items()}
                    results = {name: future.result() for name, future in futures.items()}
            finally:
                baking.set()
                baker.join()
            for name, (code, stderr, elapsed) in results.items():
                assert code == 0, (name, stderr)
                print(f'TIMING concurrent push {name} (2 MiB + release) {elapsed:.2f}s', flush=True)
            assert bakes and not bake_failures, bake_failures
            for name, files in payloads.items():
                assert released(root / 'site', f'testadmin/{name}', '1.0.0', 'data.bin') == files['data.bin']
            print(f'PASS three concurrent releases during {len(bakes)} online checkpoints, none refused', flush=True)
        finally:
            if sys.exc_info()[0] is not None:
                log.flush()
                log.seek(0)
                print('REGISTRY LOG:\n' + log.read(), file=sys.stderr, flush=True)
            stop(process)
        # A restart reads everything back from the durable journal, snapshot and object
        # files: the next release builds on the stored tree, sending only what changed.
        process = start(registry, database, port, environment, log)
        try:
            git_environment = client.environment('large')
            text = (large_work / 'package.prisma').read_text().replace('"1.0.0"', '"1.0.1"')
            (large_work / 'package.prisma').write_text(text)
            for args in (('commit', '-qam', '1.0.1'), ('tag', '-a', 'v1.0.1', '-m', 'large 1.0.1')):
                subprocess.run(['git', '-C', str(large_work), *args], env=git_environment, check=True, capture_output=True)
            code, stderr, _ = client.push(large_work, git_environment, 'v1.0.1')
            assert code == 0, stderr
            assert released(root / 'site', 'testadmin/large', '1.0.1', 'large.bin') == large
        finally:
            stop(process)
    print('PASS stored objects survive a restart and a later release builds on them', flush=True)
