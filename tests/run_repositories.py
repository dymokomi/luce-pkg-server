#!/usr/bin/env python3
"""Native repository ownership, persistence, malformed input and race gates."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import heap_process

ROOT = Path(__file__).resolve().parents[1]
MODES = {f'native{i}': ['--native', '--opt', str(i)] for i in range(4)}
MODES.update({'c': ['--backend=c'], 'c-release': ['--backend=c', '--release']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=ROOT / 'build/toolchain/luce-base')
    parser.add_argument('--mode', choices=[*MODES, 'all', 'sanitize'], default='all')
    parser.add_argument('--fixture', choices=['repositories', 'refs', 'large_objects'], default='repositories')
    parser.add_argument('--heap', action='store_true', help='also require zero macOS leaks on separate stores')
    args = parser.parse_args()
    if args.heap and sys.platform != 'darwin':
        parser.error('--heap requires macOS; use --mode sanitize on Linux')
    env = dict(os.environ)
    env.setdefault('LUCE_STD', str(ROOT.parent / 'luce-base/src/std'))
    env.setdefault('LUCE_CACHE', str(ROOT / 'build/cache'))
    out = ROOT / 'build' / args.fixture
    out.mkdir(parents=True, exist_ok=True)

    def run(command):
        print('RUN', ' '.join(map(str, command)), flush=True)
        subprocess.run(list(map(str, command)), cwd=ROOT, env=env, check=True, timeout=180)

    def fixture(binary, store, phase):
        # leaks reports its own exit, not the child's. Check the real fixture
        # separately, then require completion AND zero leaks on an isolated store.
        extra = [ROOT.parent / 'luce-base/bootstrap/luce-base-arm64-macos.c'] if args.fixture == 'large_objects' else []
        run([binary, store, phase, *extra])
        if args.heap:
            result = heap_process.run(['/usr/bin/leaks', '--quiet', '--noContent', '--atExit', '--',
                                     str(binary), str(store) + '-heap', phase, *extra],
                                    cwd=ROOT, env=env, timeout=180)
            print(result.stdout, end='', flush=True)
            print(result.stderr, end='', file=sys.stderr, flush=True)
            result.check_returncode()
            assert 'PASS repository ' in result.stdout, 'instrumented fixture did not complete'
            assert '0 leaks for 0 total leaked bytes' in result.stdout, result.stdout

    modes = MODES if args.mode == 'all' else {args.mode: MODES.get(args.mode, [])}
    for name, flags in modes.items():
        binary = out / name
        source = ROOT / 'tests' / f'{args.fixture}.lucb'
        if name == 'sanitize':
            generated = out / 'sanitize.c'
            runtime = ROOT.parent / 'luce-base/runtime'
            run([args.base.resolve(), 'build', source, '--emit=c', '-o', generated])
            run([os.environ.get('CC', 'cc'), '-std=gnu11', '-O1', '-g', '-w',
                 '-fno-strict-aliasing', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                 '-I', runtime, generated, runtime / 'lucb_rt.c', '-pthread', '-lm', '-o', binary])
            env['ASAN_OPTIONS'] = 'halt_on_error=1:abort_on_error=1'
            env['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
        else:
            run([args.base.resolve(), 'build', source, *flags, '-o', binary])
        with tempfile.TemporaryDirectory(prefix='repo-', dir='/tmp') as temporary:
            store = Path(temporary) / 'data'
            fixture(binary, store, 'write')
            fixture(binary, store, 'read')
            fixture(binary, Path(temporary) / 'ipc', 'ipc')
            fixture(binary, Path(temporary) / 'ipc', 'read')
            if args.fixture == 'large_objects':
                fixture(binary, Path(temporary) / 'faults', 'faults')
                fixture(binary, Path(temporary) / 'interrupted', 'stage')
                fixture(binary, Path(temporary) / 'interrupted', 'resume')
            else:
                for attempt in range(4):
                    fixture(binary, Path(temporary) / f'race-{attempt}', 'race')
            if args.fixture in ('refs', 'large_objects'):
                fixture(binary, Path(temporary) / 'limits', 'limits')
        print(f'PASS repository mode {name}', flush=True)


if __name__ == '__main__':
    main()
