#!/usr/bin/env python3
"""Object storage through stock Git: a large object, and concurrent pushes and release
tags while the timer's online checkpoint bakes the database. No push may be refused."""
import concurrent.futures
import gzip
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))
from registry_client import Client, free_port, request, start, stop  # noqa: E402

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
            work, git_environment = client.repository('large', {'large.bin': large, 'small.txt': b'small\n'})
            code, stderr, elapsed = client.push(work, git_environment, 'main')
            assert code == 0, stderr
            print(f'TIMING large-object push (24 MiB) {elapsed:.2f}s', flush=True)
            client.clone('large', root / 'large-clone')
            assert (root / 'large-clone/large.bin').read_bytes() == large
            print('PASS a 24 MiB object pushes and clones byte for byte', flush=True)

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
                    futures = {name: pool.submit(client.push, work, env, 'main', 'v1.0.0')
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
                client.clone(name, root / f'{name}-clone')
                assert (root / f'{name}-clone/data.bin').read_bytes() == files['data.bin']
                assert (root / 'site/testadmin' / name / '1.0.0.pack').is_file()
            print(f'PASS three concurrent pushes and releases during {len(bakes)} online checkpoints, none refused', flush=True)

            # A clone wanting many refs makes stock Git gzip its upload-pack request.
            work, git_environment = client.repository('tagged', {'README.md': b'# tagged\n'})
            for index in range(180):
                (work / 'count.txt').write_text(f'{index}\n')
                for args in (('add', 'count.txt'), ('commit', '-qm', f'step {index}'), ('tag', f'step-{index:03}')):
                    subprocess.run(['git', '-C', str(work), *args], env=git_environment, check=True, capture_output=True)
            # A push updates at most 64 refs; send the tags in batches.
            for first in range(0, 180, 60):
                refs = [f'refs/tags/step-{index:03}' for index in range(first, first + 60)]
                code, stderr, _ = client.push(work, git_environment, *(['main'] if first == 0 else []), *refs)
                assert code == 0, stderr
            tagged = root / 'tagged-clone'
            client.clone('tagged', tagged)
            tags = subprocess.run(['git', '-C', str(tagged), 'tag'], check=True, capture_output=True, text=True).stdout.split()
            assert len(tags) == 180 and (tagged / 'count.txt').read_text() == '179\n', len(tags)
            print('PASS a full clone of a repository with 180 tags (a gzip request body)', flush=True)
            # Encoded bodies are bounded like plain ones: a bomb, corruption and an unknown encoding.
            path = '/git/testadmin/tagged/git-upload-pack'
            kind = {'Content-Type': 'application/x-git-upload-pack-request'}
            bomb = gzip.compress(b'0' * (2 * 1048576))
            assert len(bomb) < 16384
            assert request(port, 'POST', path, None, {**kind, 'Content-Encoding': 'gzip'}, bomb)[0] == 400
            assert request(port, 'POST', path, None, {**kind, 'Content-Encoding': 'gzip'}, bomb[:-9] + b'\0' * 9)[0] == 400
            assert request(port, 'POST', path, None, {**kind, 'Content-Encoding': 'br'}, b'0000')[0] == 415
            assert request(port, 'GET', '/health') == (200, b'ok')
            print('PASS gzip bodies are capped at the request limit; corrupt and unknown encodings are refused', flush=True)
        finally:
            if sys.exc_info()[0] is not None:
                log.flush()
                log.seek(0)
                print('REGISTRY LOG:\n' + log.read(), file=sys.stderr, flush=True)
            stop(process)
        # A restart reads everything back from the durable journal and snapshot.
        process = start(registry, database, port, environment, log)
        try:
            client.clone('large', root / 'large-after-restart')
            assert (root / 'large-after-restart/large.bin').read_bytes() == large
        finally:
            stop(process)
    print('PASS stored objects survive a restart', flush=True)
