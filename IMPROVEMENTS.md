# TrustLens AI — Recommended Improvements

A prioritized review of the Phase 1 codebase as it stands today. Items are grouped by
priority; each one names the affected file so it can be picked up as a standalone task.
"P0" = fix before any real deployment; "P1" = should land during Phases 2–3; "P2" = important
but can ride along with the matching later phase; "P3" = nice-to-have.

## Implementation status (2026-06-12)

All 26 items have been implemented except the parts that genuinely require later-phase
infrastructure, which are deferred and flagged below.

**Done:** #1 (prod secret validation, `config.py`), #2 (rate-limit dependency, `core/ratelimit.py`),
#3 (token rotation/revocation/logout, `core/token_store.py` + `services/auth.py`), #4 (magic-byte
validation, `core/files.py`), #5 (chunked streaming upload, `api/v1/documents.py`), #6 (trusted-proxy
`client_ip`), #7 (audit hash chain + PG WORM trigger, `services/audit.py` + migration 002), #8 (app-number
retry), #9 (document versioning), #10 (orphan cleanup), #11 (PII-read audit), #12 (composite indexes),
#13 (tests → 32 passing, 76% cov, pytest-cov gate), #14 (CI workflow), #15 (.dockerignore), #16 (compose
migrate job), #17 (security headers + body-limit, `core/middleware.py`), #18 (Prometheus /metrics),
#19 (MultiFernet rotation), #20 (Argon2 + bcrypt fallback), #21 (list filter/sort), #22 (ErrorResponse
OpenAPI), #23 (/me cleanup), #24 (consent-withdrawal endpoint + RETENTION.md), #25 (TOTP MFA), #26
(pre-commit + git init).

**Deferred (need later-phase infra, hooks/docs in place):** #10 background reconciliation *job* (Phase 8
event outbox), #13 WORM-on-real-Postgres integration test (needs live PG/testcontainers), #19 background
re-encrypt sweep (Phase 14), #24 full erasure workflow (Phase 14). mypy runs advisory-only in CI until
annotations are tightened.

---

---

## P0 — Security gaps to close before any real deployment

### 1. Fail fast on default secrets in production
`app/config.py` ships `jwt_secret_key: str = "change-me-in-production"` and an empty
`fernet_key`. `app/core/encryption.py` silently generates an **ephemeral** Fernet key when
`FERNET_KEY` is unset — every restart makes previously-encrypted PII permanently unreadable,
and nothing warns you.

**Fix:** add a startup validator (in `Settings` or the FastAPI lifespan) that raises if
`environment == "production"` and the JWT secret is the default or `fernet_key` is empty.
Log a loud warning when the dev fallback key path is taken.

### 2. Rate limiting on `/auth` (spec §14 requires it)
`app/api/v1/auth.py` has no throttling — login is brute-forceable. Add `slowapi` (or a
Redis-backed limiter, since Redis is already in the stack) on `/auth/login`, `/auth/register`,
and `/auth/refresh`. Add simple account lockout (N failed attempts → temporary lock) with an
audit entry for each lockout.

### 3. Refresh-token rotation and revocation
`app/core/security.py` puts a `jti` in every token but nothing stores it, so logout and
"invalidate all sessions" are impossible — a stolen refresh token is valid for 7 days no
matter what. **Fix:** persist refresh `jti`s (Redis with TTL fits well), rotate the refresh
token on every `/auth/refresh` call, and reject reuse of a rotated token (reuse = likely
theft → revoke the whole family + audit entry). Add a `/auth/logout` endpoint.

### 4. Validate file content by magic bytes, not the client's Content-Type header
`app/services/document.py` trusts `file.content_type`, which the client controls. A
malicious upload can claim `application/pdf` and contain anything. **Fix:** sniff the first
bytes (`%PDF-`, PNG/JPEG/TIFF signatures) and reject mismatches. This also protects the
Phase 2 OCR workers from being fed hostile input.

### 5. Stream uploads instead of buffering whole files in memory
`app/api/v1/documents.py` does `data = await file.read()` before the 25 MB check in the
service, so the size limit is enforced only **after** the full body is already in RAM.
A handful of large concurrent uploads can exhaust worker memory. **Fix:** read in chunks,
count bytes as you go, abort past the limit, and compute the SHA-256 incrementally on the
same pass.

### 6. Don't trust `X-Forwarded-For` unconditionally
`app/dependencies.py:client_ip()` takes the first XFF value from any caller — audit-log IPs
are trivially spoofable. Only honor XFF when the direct peer is a trusted proxy (config list);
otherwise use `request.client.host`.

---

## P1 — Correctness and robustness (land during Phases 2–3)

### 7. Make the WORM audit rules tamper-*evident*, not silently tolerant
The PG rules in `alembic/versions/001_initial_schema.py` turn UPDATE/DELETE on `audit_logs`
into silent no-ops. An attacker (or a buggy job) attempting to rewrite history gets **no
error**, and you get no signal. Two upgrades:
- Replace the rules with a trigger that `RAISE EXCEPTION` — attempts then fail loudly and
  can themselves be logged.
- Add a hash chain: each row stores `sha256(prev_hash || row_payload)`. A periodic verifier
  job can then prove the trail wasn't truncated or rewritten (rules/triggers don't protect
  against a superuser; a hash chain at least makes it detectable). This is cheap now and
  very hard to retrofit later.

### 8. Handle application-number collisions
`app/services/application.py:_generate_application_number()` uses 4 random bytes per day
(~65k values before birthday collisions become likely at scale). The unique index will make
the INSERT fail with an opaque 500. Catch `IntegrityError` and retry with a fresh number
(bounded retries), or widen the random part.

### 9. Implement document versioning (the fields exist but do nothing)
`documents.version` and `is_current_version` are written as `1/True` and never updated.
Re-uploading a PAN card should mark the old row `is_current_version=False` and increment
`version` — Phase 2's cross-document logic will silently double-count entities otherwise.
Do it in `DocumentService.upload` inside the same transaction.

### 10. Orphaned storage objects on commit failure
In `DocumentService.upload`, bytes are pushed to MinIO **before** the DB commit. If the
commit then fails, the object is orphaned in the bucket with no DB row pointing at it.
Acceptable for dev, but add (a) a key-naming scheme that makes orphans identifiable (already
true: `applications/{app_id}/{doc_id}/…`), and (b) a small reconciliation/cleanup job. The
Phase 8 event-outbox pattern can absorb this.

### 11. Audit PII reads, not just writes
The spec says *every PII access* goes to the audit trail. Currently only mutations and
downloads are recorded. `GET /applications/{id}` and the Phase 3+ entity endpoints should
write `AuditAction.READ_PII` entries when an analyst views another person's data. Add it as
a small decorator/dependency so endpoints opt in declaratively instead of hand-writing
`audit.record(...)` calls.

### 12. Composite and partial indexes
`documents` is always queried by `(application_id, is_current_version, deleted_at IS NULL)`
— add a composite (or PG partial) index for that shape. Same for
`applications(applicant_id, created_at DESC)` used by the customer list view.

### 13. Test gaps
- No tests for the document endpoints at all (mock `StorageService` via the existing
  `get_storage` dependency override — it's already injectable).
- No test that audit entries are actually written on register/login/submit/decide.
- WORM behavior is Postgres-only and untested; add an integration test against real PG
  (testcontainers, or a CI job using the compose Postgres).
- Add `pytest-cov` and ratchet toward the spec's coverage bar.

---

## P2 — Production hardening (pairs with later phases)

### 14. CI pipeline (spec §19 phase 15, but start now)
A minimal GitHub Actions workflow: `pytest`, `ruff check`, `mypy app/`, `pip-audit`
(dependency CVEs), `bandit` (SAST), and a secret scanner (gitleaks). Cheap to add while the
codebase is small; painful to bolt on later. Also add `pip-tools`/`uv` lockfile so transitive
dependencies are pinned, not just direct ones.

### 15. `.dockerignore` is missing
The Docker build context currently includes `.venv`, `tests/`, `.git` metadata, local DBs,
etc. Add a `.dockerignore` mirroring `.gitignore` plus `tests/`, `*.md`. Smaller context,
faster builds, and no risk of a local `.env` leaking into an image layer.

### 16. Run migrations as a one-shot job, not in the API container command
`docker-compose.yml` runs `alembic upgrade head && uvicorn …` in the api service. With one
replica that's fine; with 2+ replicas (K8s later) every pod races to migrate. Split it into
a dedicated `migrate` service / init job that the api depends on.

### 17. Security headers + request limits middleware
Add a middleware setting `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, and a sane `Content-Security-Policy` for the docs page. Also cap
request body size at the ASGI level so oversized bodies are rejected before routing.
Tighten CORS in production (explicit methods/headers instead of `*` with credentials).

### 18. Observability stubs now, dashboards later (spec §17)
Add `prometheus-fastapi-instrumentator` for request metrics and expose `/metrics` now —
the Phase 2 Celery pipeline will want counters from day one (queue depth, task latency,
failure rate). OpenTelemetry tracing can wait, but pick the correlation-id header as the
trace correlation key now so it's consistent end-to-end.

### 19. Key rotation support
Swap `Fernet` for `MultiFernet` in `app/core/encryption.py` so a new key can be introduced
while old ciphertexts stay readable, with a background re-encrypt job. This is the bridge
to the spec's KMS/HSM requirement and is much easier before millions of rows exist.

### 20. Replace passlib with direct `bcrypt` or `argon2-cffi`
`passlib` is effectively unmaintained and already needs the `bcrypt` pin workaround. The
checklist explicitly allows Argon2 — `argon2-cffi` is the stronger, maintained choice. Easy
swap now (one module, `verify` can fall back to bcrypt for existing hashes), annoying later.

---

## P3 — Quality-of-life / API polish

21. **List endpoint filtering & sorting** (spec §12 conventions): `GET /applications` should
    accept `status=`, `loan_type=`, `sort=` params; analysts will need them immediately.
22. **Error response schema in OpenAPI**: the `{"error": {code, message}}` envelope isn't
    declared, so generated clients won't know about it. Add a shared `ErrorResponse` model
    and wire it via `responses={...}` on the routers.
23. **`/auth/me` cleanup**: it re-queries the user via an inline import
    (`app/api/v1/auth.py`); have `get_current_user` return the ORM user (it already fetched
    it) or move the lookup into `AuthService`.
24. **DPDP groundwork** (spec §15): consent is captured at registration but there's no
    withdrawal endpoint or retention schedule yet. Add `POST /auth/consent/withdraw` and a
    documented retention table now — the erasure workflow can come with Phase 14.
25. **MFA for analyst/admin roles** (checklist §3): TOTP via `pyotp` gating analyst logins.
    Customers can wait; the people who can approve loans should not.
26. **Pre-commit hooks**: `ruff` + `ruff format` + gitleaks locally, matching CI, so style
    and secrets issues never reach a commit. (Note: the repo is currently rooted at the home
    directory — initialize a proper repo at `truestlens/` first; that's worth doing anyway.)

---

## Suggested sequencing

| When | Items |
|---|---|
| Immediately (before Phase 2) | 1, 4, 5, 8, 15, 26 (repo init) |
| With Phase 2 (documents/OCR) | 9, 10, 12, 13, 18 |
| With Phase 3–4 (fraud/identity) | 7, 11, 19 |
| First deploy prep | 2, 3, 6, 14, 16, 17, 20 |
| Anytime | 21–25 |
