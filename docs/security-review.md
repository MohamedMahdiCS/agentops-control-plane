# Security and Configuration Review

**Scope:** backend API, worker, tool gateway, evaluation and benchmark modules, console, container
stack and CI, as of the Day 15 release.

**Method:** code review against the project's security rules (least privilege, backend-enforced
policy, validated tool inputs, auditable actions), automated tests, dependency audits and a local
production-mode container run.

## Summary

| Area | Status |
|---|---|
| Tool authorization enforced in the backend, default deny | ✅ |
| Sensitive actions require scoped, expiring human approval | ✅ |
| Operator authentication for traces, approvals, evaluations, benchmarks | ✅ |
| Secrets kept out of the repository | ✅ |
| Production configuration fails fast when unsafe | ✅ |
| HTTP hardening (headers, CSP, no-store, docs hidden in production) | ✅ |
| Dependency vulnerabilities (pip-audit, npm audit) | ✅ none known at review time |
| Unauthenticated agent registration and run submission | ⚠️ open, see F1 |
| Single shared operator identity, no roles | ⚠️ accepted for MVP, see F2 |
| No rate limiting | ⚠️ open, see F3 |

## Controls in place

**Policy and execution**
- The Tool Gateway authorizes every request from trusted registry metadata. Agent text can't grant
  permissions. Arguments are validated with strict Pydantic schemas, and resources are scoped to
  the incident's services and their transitive dependencies.
- The policy decision and audit event are committed *before* dispatch. If an outcome is missing
  after a crash, it is recorded as unknown completion, never as success.
- Worker leases use fencing generations, so a stale worker can't checkpoint, finalize or dispatch.
- Approvals bind to one action execution key, expire automatically and are serialized with row
  locks, so they can't be replayed or reused for altered arguments.
- Benchmark harness injections go through the same gateway, can't target read tools and are never
  agent-supplied.

**Authentication**
- Operator tokens are compared as SHA-256 digests with `hmac.compare_digest`. Only the digest is
  configured on the server. The operator identity comes from server configuration, never from
  request headers.
- Authentication runs before any database access on protected routes, which tests verify.
- The console keeps the operator token in component memory only, never in browser storage.

**Data exposure**
- Trace and evaluation responses use explicit allowlisted schemas. Raw tool arguments, responses,
  audit payloads and actor identifiers are not exposed.
- Error responses map service exceptions to fixed messages, without stack traces or exception text.
- Benchmark manifest paths are built from parsed UUIDs, which prevents path traversal. Manifests are
  checksummed, and modified files are reported as corrupt rather than served.

**Configuration** (`backend/app/core/config.py`)
- `APP_ENV=production` requires a valid `OPERATOR_TOKEN_SHA256` and `OPERATOR_ID`, and disables
  `/docs`, `/redoc` and `/openapi.json`.
- CORS is off unless `CORS_ORIGINS` is set. Wildcards are rejected, and production requires HTTPS
  origins.
- API responses carry `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`,
  `Permissions-Policy` and `Cache-Control: no-store`.
- The nginx console adds a restrictive Content-Security-Policy (`script-src 'self'`, no framing).

**Repository and supply chain**
- `.env`, `.env.*` (except `.env.example`) and `deploy/stack.env` are gitignored. A pre-commit
  hook detects private keys.
- Dependencies are pinned by `uv.lock` and `package-lock.json`, and CI audits both.
- Container images run as a non-root user. The database and API are not published to the host
  in the compose stack.
- CI uses read-only `contents` permissions and ephemeral database credentials.

## Findings and recommendations

**F1 — Agent registration and run submission are unauthenticated (medium).**
`POST /api/v1/agents` and `POST /api/v1/agents/{id}/runs` accept anonymous requests. That was the
original API contract and is acceptable on a developer machine. Anyone who can reach a shared
deployment could register agents and queue simulated investigations. Before exposing the stack
beyond localhost, require operator authentication on these routes, and update the console to send
the token.

**F2 — Single operator identity (low, accepted for MVP).**
All operators share one token and one identity, so audit records can't distinguish people.
Recommendation: per-user identities from an identity provider, plus roles that separate approvers
from viewers.

**F3 — No rate limiting (low).**
Benchmark runs execute inside the request and are limited only by a single-runner lock.
Recommendation: rate-limit at the proxy and move benchmark execution to the worker queue.

**F4 — TLS is not terminated by the stack (informational).**
nginx listens on plain HTTP. Put it behind a TLS-terminating load balancer or add certificates
before any non-local use.

## Verification

- `tests/test_operator_auth.py`, `tests/test_*_api.py`: authentication, identity spoofing,
  validation and error mapping.
- `tests/test_tool_gateway_policy.py`, `tests/test_run_claims.py`: policy, fencing and approvals.
- `tests/test_production_config.py`: fail-fast configuration, headers, docs visibility, CORS.
- Production-mode compose stack: unauthenticated evaluation request → 401, health OK, CSP present.
