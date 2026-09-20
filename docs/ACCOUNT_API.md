# Loopback account and scoped-credential API

Production authorities use the auth package's 64 MiB / 3-pass / 4-lane Argon2id
profile; only explicit fixtures use the weak test profile. Do not expose the
backend port directly: public use requires the configured HTTPS proxy, request
rate limits, cleanup/quotas and the remaining deployment acceptance gates.

One database owner holds the Prism journal. Two HTTP application workers use
separate authenticated Unix-socket connections. `LUCE_REGISTRY_STORE_TOKEN` is
required locally; it is not an HTTP admin token. The process accepts a database
path and port, binds only `127.0.0.1`, and creates `<database>.sock`. Keep the
database and socket in a private directory. Never pass real secrets in CLI args.

| Method/path | Input | Success |
| --- | --- | --- |
| GET `/health` | None | `200 ok` |
| POST `/v1/invites/redeem` | JSON strings `code`, `name`, `password` | `201 registered` |
| POST `/v1/sessions` | JSON strings `name`, `password` | `200`, raw bearer token |
| GET `/v1/identity` | `Authorization: Bearer <token>` | `200`, account name |
| POST `/v1/sessions/revoke` | Same authorization header | `200 revoked` |
| POST `/v1/credentials` | Session Bearer plus exact JSON `scope`, `repository`, `lifetime_seconds` | `201`, raw 64-hex credential |
| POST `/v1/credentials/revoke` | Session Bearer plus exact JSON `token` | `200 revoked` |

JSON bodies are bounded to 4096 bytes and must contain exactly the listed fields.
Invitation/session tokens must be 32 lowercase hexadecimal characters. Scoped
credentials are 64 lowercase hexadecimal characters, bound to one repository,
one of `git:read`, `git:write`, `package:read`, `package:publish`, and an absolute
lifetime from 60 through 7,776,000 seconds. Git write includes Git read; package
publish includes package read; no other scope implication exists. Responses
are plain text with `Cache-Control: no-store`. Proxy headers are never identity,
and bearer values are not echoed by the identity endpoint. Invalid credentials
produce a generic error. Duplicate registration returns 409; an invalid invitation
returns 400. Persistence/admission errors may leave an ambiguous committed outcome;
this API does not promise exactly-once requests or safe automatic retries. Raw
credentials are returned once and never stored; Prism contains only SHA-256-keyed
records. Logout does not revoke independent credentials.

There is no public bootstrap or invitation-minting endpoint. The account fixture
creates deterministic disposable test credentials only; it is not an admin tool.
Account recovery, key rotation, lockout/rate limits, expired-record cleanup,
credential listing/labels and account-wide emergency revocation remain required.
ML-DSA account enrollment, signed package publication and Smart Git HTTP are
implemented and tested in the registry suite; production deployment remains a
separate authorization gate.

Use `python3 tools/bootstrap_registry.py`, then `python3 tests/run_registry.py`.
The registry bootstrap pins every source dependency. The older compiler-profile
bootstrap and synthetic import/link gate are separate checks, not registry evidence.
