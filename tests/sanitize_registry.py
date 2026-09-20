#!/usr/bin/env python3
"""ASan/UBSan registry and account fixture, including native IPC workers."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--base', type=Path, required=True)
args = parser.parse_args()
env = dict(os.environ)
env.setdefault('LUCE_STD', str(ROOT.parent / 'luce-base/src/std'))
env.setdefault('LUCE_CACHE', str(ROOT / 'build/cache'))
env['ASAN_OPTIONS'] = 'halt_on_error=1:abort_on_error=1'
env['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
output = ROOT / 'build/sanitize'
output.mkdir(parents=True, exist_ok=True)
runtime = ROOT.parent / 'luce-base/runtime'

def run(command):
    subprocess.run(list(map(str, command)), cwd=ROOT, env=env, check=True, timeout=600)

for source, name in [('src/luce_pkg_server/registry.lucb', 'registry'),
                     ('src/luce_pkg_server/admin.lucb', 'admin'),
                     ('tests/http_auth.lucb', 'http-auth'),
                     ('tests/rate_limit.lucb', 'rate-limit'),
                     ('tests/account_fixture.lucb', 'account-fixture'),
                     ('tests/client/native_transfer.lucb', 'native-transfer')]:
    generated = output / f'{name}.c'
    run([args.base.resolve(), 'build', ROOT / source, '--emit=c', '-o', generated])
    run([os.environ.get('CC', 'cc'), '-std=gnu11', '-O1', '-g', '-w',
         '-fno-strict-aliasing', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
         '-I', runtime, generated, runtime / 'lucb_rt.c', '-pthread', '-lm', '-o', output / name])
run([output / 'http-auth'])
run([output / 'rate-limit'])
run([sys.executable, ROOT / 'tests/check_accounts.py', output / 'registry', output / 'account-fixture', output / 'native-transfer'])
run([sys.executable, ROOT / 'tests/admin.py', output / 'admin', output / 'registry'])
run([sys.executable, ROOT / 'tests/deployment.py', output / 'admin'])
print('PASS registry ASan/UBSan account and IPC integration')
