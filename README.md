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
- **Git hosting.** Native Git Smart HTTP over Prism storage: anonymous clone and
  fetch, authenticated push with atomic ref updates, released tags immutable.
- **Accounts.** Invitation-only registration, password login, sessions that last
  until revoked, and short-lived repository credentials for Git. Registration can
  be closed once the intended accounts exist.

`luc publish` is the client side; see [luce-luc](https://github.com/dymokomi/luce-luc).

## Layout

| Path | What |
| --- | --- |
| `src/luce_pkg_server/registry.lucb` | HTTP routes and the process |
| `src/luce_pkg_server/repositories.lucb` | repositories, objects, refs, Smart HTTP, tag releases |
| `src/luce_pkg_server/site.lucb`, `pages.lucb` | the static site: listings, pages, source browser |
| `src/luce_pkg_server/admin.lucb` | `luce-pkg-admin`: store token, init, invite, checkpoint |
| `deploy/` | systemd unit, Caddyfile, host limits, backup and restore, the release bundle builder |
| `docs/CONTRACTS.md` | the decisions the design rests on |

Dependencies are sibling checkouts pinned in `bootstrap/`: `luce-auth`, `luce-db`,
`luce-prism`, `luce-git`, `luce-compress`, `luce-crypto`, `luce-tls`, `luce-server`,
`luce-http-client`, `luce-json` and `luce-pkg`.

## Build and test

```sh
python3 tools/bootstrap_registry.py      # builds the pinned compilers into build/toolchain
python3 tests/run_registry.py            # accounts, Git, releases and the site, in every compiler mode
python3 tests/run_repositories.py        # native storage fixtures; --fixture refs|graph|receive|large_objects
python3 tests/deployment.py build/native0/admin
```

Add `--mode native0` to either runner for one fast pass.

## Deploying

`deploy/README.md` is the operator's document: the bundle CI builds on every push
(the `Deployment bundle` workflow), the service user and directories, the
environment file, Caddy, host limits, backup and restore.
