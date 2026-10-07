# luce-pkg-server

The registry behind [pkg.luciaos.com](https://pkg.luciaos.com): a Git host and
package index for Luce and Luce Base, written in Luce Base. MIT OR Apache-2.0.

## What it does

- **Public registry.** Every repository and release is public. Pushing an annotated
  tag `v<major.minor.patch>` publishes that commit as a release: a history-free Git
  pack, its `package.prisma`, the tag message as release notes, a `versions`
  listing with SHA-256 digests, and a global `index`. The registry also writes the
  site's HTML: a front page split into applications, tools and packages, a page per
  package with its README, dependencies and versions, and browsable, highlighted
  source for every release. Caddy serves all of that as static files; the registry
  is not on the path of a download.
- **Git hosting.** Native Git Smart HTTP, refs and object listings in Prism, object
  bytes in content-addressed files: anonymous clone and
  fetch, authenticated push with atomic ref updates; a push never moves or deletes a
  release tag, an operator can withdraw one.
- **Accounts.** Invitation-only registration, password login, sessions that last
  until revoked, and short-lived repository credentials for Git. Registration can
  be closed once the intended accounts exist.

`luc publish` is the client side; see [luce-luc](https://github.com/dymokomi/luce-luc).

## Layout

| Path | What |
| --- | --- |
| `src/registry.lucb` | HTTP routes and the process |
| `src/repositories.lucb` | repositories, objects, refs, Smart HTTP, tag releases |
| `src/gzip.lucb` | gzip request bodies, which stock Git sends for large fetch requests |
| `src/objects.lucb` | the content-addressed object files beside the database |
| `src/migrate.lucb` | `luce-pkg-admin migrate`: objects out of the database, once |
| `src/site.lucb`, `pages.lucb` | the static site: listings, pages, source browser |
| `src/admin.lucb` | `luce-pkg-admin`: store token, init, invite, checkpoint, migrate, remove, withdraw, rebuild-site |
| `deploy/` | systemd unit, Caddyfile, host limits, backup and restore, the release bundle builder |
| `docs/CONTRACTS.md` | the decisions the design rests on |

Dependencies are sibling checkouts, at main in CI (`python3 ../luce-base/tools/checkout_main.py
luce-pkg-server luce luce-luc` clones the missing ones): `luce-auth`, `luce-db`, `luce-prism`,
`luce-git`, `luce-compress`, `luce-crypto`, `luce-tls`, `luce-server`, `luce-http-client`,
`luce-json` and `luce-pkg`.

## Build and test

```sh
luc test
```

`tests/http_auth` and `tests/rate_limit` check those modules on their own.
`tests/registry` builds the registry, the admin tool, the fixtures in
`tests/registry/drivers/` and luc from the luce-luc checkout beside this one, and drives
them with the Python clients beside it: accounts and Git, admin, deployment scripts,
storage, removal, the rebuilt site, migration, and a published release (about five
minutes, most of it the 72 MiB release). `tests/repositories` runs the native storage
fixtures (repositories, refs, large objects, graph, receive) phase by phase.

## Deploying

`deploy/README.md` is the operator's document: the bundle CI builds on every push
(the `Deployment bundle` workflow), the service user and directories, the
environment file, Caddy, host limits, backup and restore.
