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
LUCE_REGISTRY_SITE=/var/lib/luce-pkg-site
```

`LUCE_REGISTRY_SITE` is the directory of public release files. Pushing a tag
`v<major.minor.patch>` makes the registry write `<owner>/<name>/<version>.pack`,
`<version>.prisma`, the package's `versions` listing and the global `index` there,
and Caddy serves them as static files without involving the registry. Create it
once so Caddy can read what the service writes:

```sh
sudo install -d -o luce-pkg -g caddy -m 2750 /var/lib/luce-pkg-site
```

Copy the site's stylesheets and scripts from the release bundle; they are shared
with luce.luciaos.com and are not written by the registry:

```sh
sudo install -d -o luce-pkg -g caddy -m 2750 /var/lib/luce-pkg-site/assets
sudo install -o luce-pkg -g caddy -m 0640 /opt/luce-pkg-server/current/site-assets/* /var/lib/luce-pkg-site/assets/
```

Each release also writes `index.html` (the package list with a filter) and
`<owner>/<name>/index.html` (description, install command, versions, dependencies
and the rendered README). README text is untrusted: raw HTML is escaped, links
other than `http(s)://` and `#` are neutralised, and Caddy sends a
Content-Security-Policy that forbids inline script.

The setgid bit gives new files the `caddy` group, and the unit's `UMask=0027`
makes them group-readable. The database directory stays `0700`, so the wider
umask exposes nothing there. Back this directory up together with the database:
it is derived from repository state, but there is no command yet that rebuilds it,
and re-pushing an existing tag is a no-op for Git.

Never place the token in an argument, repository, log, backup directory, or Caddy
configuration. Initialize once while the service is stopped:

```sh
sudo bash -c 'set -a; source /etc/luce-pkg-server/environment; set +a; \
  exec setpriv --reuid luce-pkg --regid luce-pkg --clear-groups \
  env -i PATH=/usr/bin LUCE_REGISTRY_STORE_TOKEN="$LUCE_REGISTRY_STORE_TOKEN" \
  LUCE_REGISTRY_ORIGIN="$LUCE_REGISTRY_ORIGIN" \
  /opt/luce-pkg-server/current/luce-pkg-admin init /var/lib/luce-pkg-server/registry.db'
```

The environment file is root-only, so the service user cannot `source` it. Root
reads it and then drops to `luce-pkg` with `setpriv`; the token travels only in
the environment and never in an argument.

After `systemctl enable --now luce-pkg-server`, issue an invitation through the
private owner socket. The command prints the secret once; deliver it through a
protected channel and do not log it:

```sh
sudo bash -c 'set -a; source /etc/luce-pkg-server/environment; set +a; \
  exec setpriv --reuid luce-pkg --regid luce-pkg --clear-groups \
  env -i PATH=/usr/bin LUCE_REGISTRY_STORE_TOKEN="$LUCE_REGISTRY_STORE_TOKEN" \
  LUCE_REGISTRY_ORIGIN="$LUCE_REGISTRY_ORIGIN" \
  /opt/luce-pkg-server/current/luce-pkg-admin invite /var/lib/luce-pkg-server/registry.db.sock'
```

Append the reviewed `Caddyfile` block only after the loopback health check passes.
Validate the complete Caddy configuration before reload, as the `caddy` user
(`sudo -u caddy caddy validate ...`): validation opens the access log, and a
root-owned log file makes the following reload fail. DNS is one Route53 A record
for `pkg.luciaos.com` to the static address of the dedicated registry VPS; the
registry does not share a host with other sites.
The installed Caddy 2.11 build does not accept site-local request `timeouts`;
the backend therefore enforces explicit 15-second idle and five-minute
request/response/application deadlines, while Caddy enforces the body cap plus
five-minute upstream response-header and five-second dial deadlines.

## Abuse and bandwidth limits

`deploy/host/` holds what runs on the VPS itself, outside the registry:

- `luce-limits.nft` with `luce-limits.service`: per-address limits in the kernel,
  before Caddy. New HTTP(S) connections are limited to 30 a second (burst 120) and
  64 simultaneous connections per address; SSH to 20 new connections a minute.
  Install the rules as `/etc/luce-limits.nft`.
- `luce-egress-budget.sh` with its service and five-minute timer, installed as
  `/usr/local/sbin/luce-egress-budget`: counts the month's transfer (in and out,
  as Lightsail bills it) in `/var/lib/luce-egress/usage` and shapes egress with
  `tc cake` at 200 Mbit, then 20 Mbit from 70% of the budget, 1 Mbit from 90% and
  256 kbit from 97%. The default budget is 2800 GiB against the plan's 3 TB, so
  the transfer bill is bounded by construction. The site slows down; it does not
  go offline and it does not run up overage.

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
