# Experimental loopback account API

This is not a production identity service. The password KDF is still the auth
package's weak test profile. Do not store real credentials or expose these routes
publicly until KDF/rate-limit/expiry, TLS deployment and identity policy are ready.

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

JSON bodies are bounded to 4096 bytes and must contain exactly the listed fields.
Invitation/session tokens must be 32 lowercase hexadecimal characters. Responses
are plain text with `Cache-Control: no-store`. Proxy headers are never identity,
and bearer values are not echoed by the identity endpoint. Invalid credentials
produce a generic error. Duplicate registration returns 409; an invalid invitation
returns 400. Persistence/admission errors may leave an ambiguous committed outcome;
this API does not promise exactly-once requests or safe automatic retries.

There is no public bootstrap or invitation-minting endpoint. The account fixture
creates deterministic disposable test credentials only; it is not an admin tool.
Role-based administration, ML-DSA account keys, password policy, session expiration,
account recovery, lockout/rate limits, signed package publication and Git routes
remain separate required work. Tests currently exercise native Base handlers;
high-level Luce application composition remains to be integrated.

Use `python3 tools/bootstrap_registry.py`, then `python3 tests/run_registry.py`.
The registry bootstrap pins every source dependency. The older compiler-profile
bootstrap and synthetic import/link gate are separate checks, not registry evidence.
