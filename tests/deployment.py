#!/usr/bin/env python3
"""Static and disposable backup/restore verification for deployment assets."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
admin = Path(sys.argv[1]).resolve()
service = (ROOT / 'deploy/luce-pkg-server.service').read_text()
caddy = (ROOT / 'deploy/Caddyfile').read_text()

for required in ('User=luce-pkg', 'ProtectSystem=strict', 'NoNewPrivileges=true',
                 'ReadWritePaths=/var/lib/luce-pkg-server',
                 'EnvironmentFile=/etc/luce-pkg-server/environment'):
    assert required in service
assert 'registry.db 9420' in service and '127.0.0.1:9420' in caddy
for required in ('pkg.luciaos.com', 'max_size 65MiB', 'Cache-Control "no-store"',
                 'Strict-Transport-Security', 'response_header_timeout 5m'):
    assert required in caddy
assert 'encode ' not in caddy and 'basic_auth' not in caddy
for required in ('root * /var/lib/luce-pkg-site', 'file_server', 'immutable', '@registry path /git/* /v1/* /health'):
    assert required in caddy
assert "script-src 'self'" in caddy and "unsafe-inline" not in caddy
for asset in ('core.css', 'style.css', 'packages.css', 'site.js', 'theme.js', 'packages.js', 'mark.svg'):
    assert (ROOT / 'deploy/site-assets' / asset).is_file()
assert 'ReadWritePaths=/var/lib/luce-pkg-server /var/lib/luce-pkg-site' in service and 'UMask=0027' in service
subprocess.run(['bash', '-n', ROOT / 'deploy/host/luce-egress-budget.sh'], check=True)
for script in ('backup.sh', 'restore.sh'):
    subprocess.run(['bash', '-n', ROOT / 'deploy' / script], check=True)
subprocess.run(['bash', '-n', ROOT / 'deploy' / 'build-release.sh'], check=True)

builder = (ROOT / 'deploy' / 'build-release.sh').read_text()
for required in ('--native --release', 'SOURCE_COMMIT', 'DEPENDENCY_PINS',
                 'SHA256SUMS', 'git -C "$root" diff --quiet',
                 'release destination already exists'):
    assert required in builder
assert 'x86_64' in builder and 'Linux' in builder

with tempfile.TemporaryDirectory(prefix='luce-pkg-deploy-', dir='/tmp') as temporary:
    root = Path(temporary)
    state = root / 'state'
    state.mkdir()
    database = state / 'registry.db'
    environment_file = root / 'environment'
    environment_file.write_text('LUCE_REGISTRY_STORE_TOKEN=deployment-test-token\n'
                                'LUCE_REGISTRY_ORIGIN=https://pkg.luciaos.com\n')
    environment_file.chmod(0o600)
    environment = dict(os.environ, LUCE_REGISTRY_STORE_TOKEN='deployment-test-token',
                       LUCE_REGISTRY_ORIGIN='https://pkg.luciaos.com')
    subprocess.run([admin, 'init', database], env=environment, check=True,
                   capture_output=True, timeout=60)
    backup = root / 'backup'
    subprocess.run([ROOT / 'deploy/backup.sh', state, database, admin,
                    environment_file, backup], check=True, capture_output=True, timeout=60)
    restored = root / 'restored'
    subprocess.run([ROOT / 'deploy/restore.sh', backup, restored, admin,
                    environment_file], check=True, capture_output=True, timeout=60)
    assert (restored / 'registry.db').is_file()
    subprocess.run([admin, 'checkpoint', restored / 'registry.db'], env=environment,
                   check=True, capture_output=True, timeout=60)
    # Any altered state byte must make restoration fail without publishing a path.
    regular = next(path for path in (backup / 'state').rglob('*') if path.is_file())
    regular.write_bytes(regular.read_bytes() + b'corrupt')
    rejected = root / 'rejected'
    result = subprocess.run([ROOT / 'deploy/restore.sh', backup, rejected, admin,
                             environment_file], capture_output=True, timeout=60)
    assert result.returncode != 0 and not rejected.exists()

print('PASS hardened service/proxy contract and verified no-clobber backup restore')
