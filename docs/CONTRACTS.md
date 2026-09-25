# Contracts

Decisions that shape the registry. Everything below is implemented.

## Visibility and accounts

Owner decision, September 21, 2026:

- Every repository, package and release on `pkg.luciaos.com` is **public**. There
  is no private package, no visibility flag and no per-reader ACL.
- Browsing, search, Git clone/fetch, version listing, release download and
  `luc` installation require **no account and no credential**.
- An account is required only for operations that change state: repository
  creation, Git push, pull-request creation and state changes, signing-key
  enrollment and release publication. Registration stays invite-only.
- `dymokomi` is the only account for now. Collaborator roles remain later work.
- A release is a pushed tag `v<major.minor.patch>` whose commit carries a root
  `package.prisma` naming this owner, this repository and this version. The
  registry publishes it as static files (a history-free Git pack, the package
  definition, a per-package `versions` listing with SHA-256 digests, and a global
  `index`). Released tags cannot be moved or deleted. The tag must be annotated:
  its message is the mandatory release notes.
- Integrity is the SHA-256 recorded in `luc.lock` plus HTTPS. Publisher
  signatures, signing-key enrollment and the separate publish protocol are
  dropped; they may return later as an additional file without changing this model.
- Nothing has been released and there is one user, so no format, command or
  protocol is kept for backward compatibility. Old ones are replaced outright.

## Git object format

- Hosted repositories speak ordinary **SHA-1** Git for v1 stock-Git compatibility.
- SHA-1 is forbidden for account secrets, vault keys, release signatures and
  lock digests. Those use SHA-256 and ML-DSA-65.
- Collision defense: reject the known SHAttered colliding PDF prefixes; reject
  inserting two distinct byte-strings that hash to one object ID; never silently
  alias SHA-1 and SHA-256 object IDs.
- Object bytes live outside Prism, one immutable file per object at
  `<database>.objects/ab/cdef...`, named by the Git id and shared by every repository
  that holds it. Prism keeps only the listing (`kind`, `size`) that makes an object
  part of a repository; reads are confined to listed objects and re-check the id.
  Keeping bytes out of the database keeps each bake proportional to metadata, far
  from Prism's 256 MiB snapshot and journal bounds.

## HTTPS proxy boundary

Inspected 2026-09-16 on the existing host, read-only:

- Public HTTPS is terminated by Caddy on :443 with Let's Encrypt certificates.
- Application backends already used by other sites bind loopback only
  (`127.0.0.1`). `pkg.luciaos.com` is one Caddy site: `/git/*`, `/v1/*` and `/health` go to the registry, everything else is static release files.
- Identity is never taken from `X-Forwarded-For` or the proxy source IP. The
  package server authenticates invitations, sessions and tokens itself.
- Git routes must preserve method, path/query, `Authorization`, Git content
  types and `Git-Protocol`. Do not HTML-rewrite Git bodies. Do not cache
  authenticated discovery or Git service responses.
- `luc` reaches the registry through its own TLS 1.3 client (`luce-tls`), which
  validates the Let's Encrypt chain under the pinned ISRG Root X2 key.

