# Registry deployment contract

The production topology is Caddy HTTPS on `pkg.luciaos.com` to a registry bound
only to `127.0.0.1:9420`. The service never accepts proxy identity headers as
authentication. Its database owner socket and state remain under
`/var/lib/luce-pkg-server`.

Install immutable, reviewed Linux binaries in a commit-addressed directory under
`/opt/luce-pkg-server/releases/`, then atomically point
`/opt/luce-pkg-server/current` at that directory. Install the unit as
`/etc/systemd/system/luce-pkg-server.service`. The dedicated system user has no
login shell or home directory. Do not build as that user.

The public Linux CI produces a no-clobber, commit-stamped deployment artifact with
`deploy/build-release.sh`. It builds natively on x86-64 Linux from an exact clean
Git commit and the checked-in dependency pins. The bundle contains the registry
and admin executables, deployment assets, `SOURCE_COMMIT`, `DEPENDENCY_PINS` and
`SHA256SUMS`. Verify every checksum and both commit records before installing;
never substitute an untracked local binary or build directly as the service user.

Create `/etc/luce-pkg-server/environment` as root, mode `0600`, containing exactly:

```text
LUCE_REGISTRY_STORE_TOKEN=<64 lowercase hex characters from luce-pkg-admin token>
LUCE_REGISTRY_ORIGIN=https://pkg.luciaos.com
```

Never place the token in an argument, repository, log, backup directory, or Caddy
configuration. Initialize once while the service is stopped:

```sh
sudo -u luce-pkg env -i PATH=/usr/bin:/opt/luce-pkg-server/current \
  bash -c 'set -a; source /etc/luce-pkg-server/environment; set +a; \
  exec luce-pkg-admin init /var/lib/luce-pkg-server/registry.db'
```

After `systemctl enable --now luce-pkg-server`, issue an invitation through the
private owner socket. The command prints the secret once; deliver it through a
protected channel and do not log it:

```sh
sudo -u luce-pkg env -i PATH=/usr/bin:/opt/luce-pkg-server/current \
  bash -c 'set -a; source /etc/luce-pkg-server/environment; set +a; \
  exec luce-pkg-admin invite /var/lib/luce-pkg-server/registry.db.sock'
```

Append the reviewed `Caddyfile` block only after the loopback health check passes.
Validate the complete Caddy configuration before reload. DNS is one Route53 A
record for `pkg.luciaos.com` to the existing static VPS address.
The installed Caddy 2.11 build does not accept site-local request `timeouts`;
the backend therefore enforces explicit 15-second idle and five-minute
request/response/application deadlines, while Caddy enforces the body cap plus
five-minute upstream response-header and five-second dial deadlines.

## Backup and restore

Backups deliberately require service downtime. Stop the registry, run `backup.sh`
with absolute paths, then restart and verify `/health`. The script checkpoints the
native Prism database, copies the complete state directory into a fresh directory,
and writes SHA-256 checksums. It never copies the environment file or store token.

`restore.sh` verifies every checksum and restores only into a path that does not
exist. It opens and checkpoints the copied database before atomically publishing
the new directory. To replace production, restore alongside the current state,
stop the service, move the old directory aside, move the verified restore into its
canonical pathname, start the service, and retain the old directory until the
HTTPS/Git/package acceptance checks pass. The identical store token must be
restored separately from protected operator custody.

Every upgrade follows the same shape: backup, install an immutable release, stop,
offline checkpoint/open with the new admin binary, change the `current` symlink,
start, then run health, registration, stock-Git, signed-release and `luc` download
checks. Rollback restores both the previous binary link and its matching backup;
never assume a newer on-disk encoding is readable by an older release.
