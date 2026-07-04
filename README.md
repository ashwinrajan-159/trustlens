# TrustLens AI

> Explainable, offline-capable **fraud-detection & underwriting-intelligence platform** for Indian banks.

TrustLens is a **case-based underwriting intelligence platform**, not a document scanner. Every
piece of intelligence — every extracted field, fraud signal, risk score and alert — is anchored to
a **loan application**, never to an isolated document. It detects forged documents, synthetic/stolen
identities, collateral fraud, shell-company indicators and coordinated fraud rings, and **explains
every decision** in a form a regulator and a human analyst can audit.

It is designed to run **fully offline / air-gapped**: there are no calls to any external/cloud AI.
The deterministic rule engine is the system of record; a **local** ML model provides an advisory
second opinion (never the final word).

---

## Table of contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [The analysis pipeline](#the-analysis-pipeline)
- [The analyst closed loop](#the-analyst-closed-loop)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Quickstart — run the whole app](#quickstart--run-the-whole-app)
- [First run — click-through](#first-run--click-through)
- [Backend — detailed build & run](#backend--detailed-build--run)
- [Frontend — detailed build & run](#frontend--detailed-build--run)
- [Screens](#screens)
- [Configuration](#configuration)
- [Testing & quality](#testing--quality)
- [API surface](#api-surface)
- [Security & compliance](#security--compliance)
- [Deployment (single-host / EC2)](#deployment-single-host--ec2)
- [Troubleshooting](#troubleshooting)
- [Offline / air-gapped operation](#offline--air-gapped-operation)

---

## What it does

A loan application flows through an **idempotent, explainable analysis pipeline**, then a
human **closed loop** (investigate → senior review → learn), and surfaces in a role-gated analyst
workbench:

- **Document intake & OCR** — upload PDFs/images (validated by magic bytes); OCR via PyMuPDF (digital
  PDFs) with PaddleOCR as an optional engine for scanned images.
- **Layout-agnostic extraction** — pulls structured fields (PAN, Aadhaar, name, salary, account,
  survey number, revenue, …) from messy documents; PII is encrypted at rest and masked in responses.
- **Deterministic fraud engine** — a standalone, unit-testable rule package (Aadhaar Verhoeff, PAN/
  IFSC/GSTIN validators, income/property/financial rules) producing weighted, explainable signals.
- **Document forensics** — an image/PDF tamper-and-reuse layer (metadata, font-consistency, copy-move,
  screenshot, signature/seal, ELA, noise analyzers) with **cross-application perceptual-hash reuse
  detection** — the same supporting document recycled across applications surfaces as a CRITICAL signal.
  Each technique is confidence-tiered (SUGGESTIVE/CORROBORATIVE/STRONG) so weak heuristics can never
  solo-drive a denial; findings fold into the score as ordinary, severity-weighted signals.
- **Cross-document & identity intelligence** — completeness checklist, salary↔bank reconciliation,
  identity resolution and synthetic-identity detection across an application's documents.
- **Property & financial intelligence** — inflated valuation, survey-number conflicts, **cross-application
  duplicate collateral**, ITR↔GST revenue mismatch, impossible ratios.
- **Graph intelligence** — an entity-relationship graph (NetworkX) detecting shared-PAN networks,
  mule accounts, duplicate-collateral networks and fraud rings.
- **Risk scoring** — a deterministic, weighted 0–100 score → tier (LOW/MEDIUM/HIGH/CRITICAL) with a
  full per-signal reasons breakdown.
- **Local ML second opinion** — scikit-learn/XGBoost classifier with governance (train → approve →
  deploy single champion), SHAP-style explanations and KS-test drift detection.
- **Events & streaming** — a transactional outbox + relay (Kafka in prod / in-process bus in dev),
  reconciliation/replay, and a real-time engine that turns CRITICAL events into alerts sub-second.
- **Alerting, cases & RBI compliance** — SLA-tracked fraud alerts with RBI reporting tier/deadline
  (FLASH ≥ ₹25 Cr, FMR-1 ≥ ₹1 Cr, quarterly ≥ ₹1 L), investigation cases, and FMR report generation.
- **Fraud-ops closed loop** — analysts claim alerts and file investigation reports; a *different*
  senior reviewer confirms or clears them (segregation of duties); outcomes feed a learning loop.
- **Fraud pattern library & signal analytics** — confirmed cases auto-cluster into named fraud
  patterns; per-signal precision is tracked with Wilson confidence intervals; signal weights are tuned
  only through a **governed, versioned, dual-control** workflow (propose ≠ approve) — never auto-tuned.
- **Regulatory Explainability Report (PDF)** — a per-application, analyst-generated PDF that
  reconstructs *how* the decision was reached (score reasons, signal evidence, masked fields, RBI
  classification) and proves it is **reproducible** (engine + weight-config versions) and
  **tamper-evident** (audit hash-chain attestation). Generated locally; no external AI.
- **Operations & audit** — operations dashboards, an immutable (WORM) audit trail with a tamper-evidence
  hash chain, and a role-gated React workbench.

---

## Architecture

```
┌──────────────┐      ┌───────────────┐      ┌──────────────────────────────────┐
│ React + Vite │─────▶│   FastAPI     │─────▶│ PostgreSQL (apps, docs, entities, │
│  SPA (5173)  │ JWT  │  REST (8000)  │ async│  signals, assessments, profiles,  │
└──────────────┘      └──────┬────────┘ SQLA │  alerts, cases, investigations,    │
                             │ enqueue        │  patterns, weights, fingerprints,  │
                             ▼                │  audit[WORM], event_log, ml_*)     │
                      ┌──────────────┐ broker └──────────────────────────────────┘
                      │ Redis (6379) │──────────▶┌──────────────────────────────┐
                      └──────────────┘           │ Celery worker                │
                             ▲                    │  analysis pipeline (chained) │
              ┌──────────────┴────────┐           └──────┬───────────────────────┘
              │ Event bus (in-proc /  │◀──── outbox ──────┤ docs in/out
              │ Kafka) + EventLog     │                   ▼
              └───────────────────────┘            ┌──────────────┐   ┌───────────┐
                                                   │ MinIO / S3   │   │ NetworkX  │
                                                   │ (documents)  │   │ (graph)   │
                                                   └──────────────┘   └───────────┘
```

**Bounded modular monolith** — each domain (`ingestion/ocr`, `extraction`, `fraud-engine`, `forensics`,
`identity`, `property`, `financial`, `graph`, `ml`, `events`, `alerting`, `cases`, `fraud-ops`,
`compliance`) lives behind a service-class interface so it can later be extracted into its own
deployable. Async tasks run on Celery; cross-cutting durability is a transactional-outbox `event_log`.

---

## The analysis pipeline

Triggered on document upload / application submit, each step is **idempotent and re-runnable** and
persists its results before chaining the next:

```
run_ocr_pipeline → extract_entities → run_fraud_engine → run_document_forensics
→ run_identity_resolution → run_cross_document_validation → run_property_validation
→ run_financial_validation → run_graph_analysis → compute_risk_assessment
→ (real-time) generate_fraud_alert
```

Document status flows `QUEUED → PROCESSING → PROCESSED | FAILED`. The deterministic engine remains the
system of record; ML inference and document forensics are advisory and degrade gracefully.

---

## The analyst closed loop

Beyond automated scoring, TrustLens models the human workflow a bank actually runs — with
**segregation of duties** and a **learning loop** that keeps detection honest:

```
CRITICAL signal ─▶ Fraud alert (SLA) ─▶ Analyst claims + files Investigation report
        ▲                                          │
        │                                          ▼
   Signal weights                       Senior reviewer (≠ analyst) confirms / clears
   (governed, versioned)                           │
        │                                          ▼
   Weight governance ◀── Signal analytics ◀── Outcome feeds learning ─▶ Fraud pattern library
   (propose ≠ approve)     (precision + Wilson CI)                       (auto-clustered patterns)
```

- **Investigation → review** — an analyst claims an alert and submits findings + a recommendation; a
  **different** senior reviewer records the final decision (CONFIRMED_FRAUD / FALSE_POSITIVE / …). The
  investigator can never approve their own case.
- **Learning** — confirmed/false-positive outcomes update per-signal precision (with Wilson confidence
  intervals, so small samples don't mislead) and cluster into a named **fraud pattern library**.
- **Governed tuning** — signal weights are changed only via a versioned propose→approve workflow; every
  risk assessment is stamped with the weight-config version used, so any past score is reproducible.
- **Regulatory report** — at any point an analyst can export the per-application **Regulatory
  Explainability Report (PDF)**: the auditable artifact that ties the score, signals, evidence, RBI
  classification and the tamper-evident audit chain together.

---

## Tech stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.12+, FastAPI 0.115, async SQLAlchemy 2.0 (asyncpg), Pydantic v2, Alembic |
| **Async** | Celery 5.4 + Redis (queues: `ocr`, `default`) |
| **Datastores** | PostgreSQL 16, Redis 7, MinIO / S3 (aioboto3) |
| **Events** | Transactional outbox (`event_log`) + in-process bus (dev) / Kafka via aiokafka (prod) |
| **OCR / NLP** | PyMuPDF (digital PDFs), PaddleOCR (optional, scanned images), regex + optional spaCy NER |
| **Fraud engine** | Standalone pure-Python rule package + weighted scorer (Verhoeff/PAN/IFSC/GSTIN) |
| **Document forensics** | OpenCV (headless), Pillow, imagehash (pHash reuse), scikit-image (SSIM); confidence-tiered analyzers |
| **ML (local)** | scikit-learn, XGBoost (optional), SHAP (optional), scipy (KS drift), joblib; MLflow optional |
| **Graph** | NetworkX (in-memory analytics); Neo4j optional for persistence |
| **Reporting** | reportlab (pure-Python PDF — Regulatory Explainability Report, offline) |
| **Security** | JWT (access+refresh, rotation), Argon2 password hashing, Fernet/MultiFernet field encryption, immutable WORM audit, rate limiting, security headers |
| **Frontend** | React 19, Vite 6, React Router 7, TailwindCSS 3, lucide-react |
| **Tooling** | pytest + pytest-cov, ruff, Docker / docker-compose, GitHub Actions CI |

---

## Project structure

```
truestlens/
├── app/                       # FastAPI backend
│   ├── main.py                # app + lifespan + middleware + exception handlers
│   ├── config.py              # pydantic-settings (env-driven)
│   ├── database.py            # async engine + session factory
│   ├── worker.py              # Celery app + task routing
│   ├── api/v1/                # REST routers (auth, applications, documents, ml, alerts,
│   │                          #   cases, operations, fraudops, health)
│   ├── core/                  # security, encryption, logging, rate limit, middleware, files
│   ├── models/                # SQLAlchemy ORM + central enums (incl. fraudops, document_fingerprint)
│   ├── schemas/               # Pydantic request/response models
│   ├── repositories/          # data-access layer
│   ├── services/              # business logic — auth, document, ocr, extraction, identity,
│   │                          #   cross_document, property_intel, financial, graph_intel, ml*,
│   │                          #   alerting, cases, rbi, storage, audit; fraud-ops closed loop
│   │                          #   (investigation, review, fraud_pattern, signal_analytics,
│   │                          #   weight_governance); regulatory_report (PDF)
│   ├── fraud_engine/          # standalone deterministic engine (rules, validators, scorer)
│   ├── forensics/             # image/PDF forensics layer (metadata, font, similarity/reuse,
│   │                          #   copy-move, screenshot, signatures, seals, ELA, noise)
│   └── tasks/                 # Celery pipeline tasks (ocr, extraction, fraud, forensics,
│                              #   identity, cross_document, property, financial, graph, events)
├── alembic/versions/          # database migrations (001 … 014):
│                              #   013 = fraud-ops closed loop · 014 = document_fingerprints
├── tests/                     # pytest suite (SQLite in-memory; no external services)
├── frontend/                  # React + Vite SPA
│   └── src/{api,auth,components,lib,pages}/
├── docker-compose.yml         # postgres · redis · minio · api · worker
├── Dockerfile                 # backend image
├── requirements.txt
├── pyproject.toml             # ruff / pytest / coverage config
├── TRUSTLENS_BUILD_SPEC.md    # master build specification / implementation prompt
├── RETENTION.md               # DPDP data-retention & erasure policy
└── IMPROVEMENTS.md            # hardening backlog
```

---

## Prerequisites

- **Python 3.12+**
- **Node.js 20+** and npm
- **Docker Desktop** (for Postgres, Redis, MinIO) — or your own running instances

---

## Quickstart — run the whole app

From the repo root (`truestlens/`). Five things must run: **infra (Docker)**, **API**, **worker**,
**frontend** — backed by the **database**.

```bash
# 1. Infra — Postgres + Redis + MinIO (Docker)
docker compose up -d postgres redis minio

# 2. Backend deps + env
python -m venv .venv
.venv\Scripts\activate                # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env                 # Windows  (macOS/Linux: cp .env.example .env)
#   then set in .env:  JWT_SECRET (≥32 chars) and FERNET_KEY:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 3. Database — migrate + create the object-storage bucket
alembic upgrade head
python -c "import asyncio; from app.services.storage import StorageService; asyncio.run(StorageService().ensure_bucket())"

# 4. API + worker  (two terminals)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# The worker MUST consume both queues — OCR (the pipeline's first step) routes to `ocr`,
# everything else to `default`. Omitting -Q leaves documents stuck at QUEUED forever.
celery -A app.worker.celery_app worker -Q ocr,default --pool=solo --loglevel=info   # --pool=solo on Windows; prefork on Linux

# 5. Frontend  (third terminal)
cd frontend && npm install && npm run dev
```

Open **http://localhost:5173**. API docs at **http://localhost:8000/docs**; health at
**http://localhost:8000/api/v1/health/ready**.

> **Connecting the SPA to the API.** The frontend reads its API base URL from `VITE_API_BASE`
> (see `frontend/src/api/client.js`). With no `.env`, it defaults to the relative path `/api/v1`,
> which only works if the API is same-origin. For local dev against a local API, create
> `frontend/.env.local` with `VITE_API_BASE=http://localhost:8000/api/v1`; against a remote box,
> point it at that host (e.g. `http://<server-ip>:8000/api/v1`). **Vite only reads env files at
> startup — restart `npm run dev` after changing it.** Add the SPA's origin to `CORS_ORIGINS` on
> the API. MinIO console is on **http://localhost:9001** (API on `:9000`).

**Run everything in containers instead** (API + worker + infra):

```bash
docker compose up -d --build   # builds api+worker images, runs migrations, starts postgres,
                               # redis, minio, api and the worker (consuming ocr,default)
docker compose ps              # all services should be Up; worker consumes queues ocr,default
docker compose logs -f worker  # watch the analysis pipeline process documents
docker compose down            # stop (add -v to wipe data volumes)
```

> Set a stable `FERNET_KEY` in `.env` **before** first run (see Configuration). Without it every
> container generates a throwaway key on boot, so PII encrypted by one process can't be decrypted
> by the next — extracted PANs/Aadhaar read back empty and the entity graph shows no links.

---

## First run — click-through

The database starts empty. To see the full system end-to-end:

1. **Register** at `/register` (creates a CUSTOMER), then **Apply** — create a loan application and
   upload documents (Aadhaar, PAN, salary slip, bank statement, …).
2. **Submit** the application — the Celery pipeline runs OCR → extraction → fraud engine → forensics →
   identity/cross-doc/property/financial → graph → risk score, and raises alerts for CRITICAL findings.
3. Sign in as an **analyst** to reach the workbench: **Review Queue**, **Analyst Review** (per-signal
   reasons + ML second opinion + **Regulatory Report (PDF)** button), **Network** graph, **Alerts**,
   **Cases**, **Operations**, **Investigation**, **Senior Review**, **Knowledge** (patterns / signal
   analytics / weight governance), **ML Platform**.
4. On **Analyst Review**, click **Regulatory Report** to download the per-application explainability PDF.

> Analyst/senior accounts: create users with the appropriate role (CUSTOMER / ANALYST /
> SENIOR_ANALYST / ADMIN). Role gates the workbench nav client-side; the backend enforces RBAC on every
> request regardless.

---

## Backend — detailed build & run

```bash
# install
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt

# database migrations (forward / inspect / down)
alembic upgrade head
alembic current
alembic downgrade -1

# run the API
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# run the analysis worker (solo pool required on Windows; prefork on Linux)
celery -A app.worker.celery_app worker --pool=solo --loglevel=info

# (optional) event reconciliation runs as a Celery task:
#   app.tasks.events.replay_pending_events  — re-publishes any PENDING outbox events
```

The compose `migrate` service runs `alembic upgrade head` to completion before `api` starts.

---

## Frontend — detailed build & run

```bash
cd frontend
npm install            # React 19, Vite, Tailwind, React Router, lucide-react
npm run dev            # dev server with HMR at http://localhost:5173
npm run build          # production bundle → frontend/dist/
npm run preview        # serve the production build locally
```

**Pointing at the API.** `VITE_API_BASE` (in `frontend/.env.local`) is the full API base the SPA
calls; path helpers in `src/api/endpoints.js` are appended to it, so it must include the `/api/v1`
prefix — e.g. `VITE_API_BASE=http://localhost:8000/api/v1` for a local API, or
`http://<server-ip>:8000/api/v1` for a remote one. If unset it defaults to the relative `/api/v1`
(same-origin only). Vite bakes env vars at startup, so **restart the dev server after editing it**,
and add the SPA origin to the API's `CORS_ORIGINS`. The production `dist/` is static.

**How the SPA connects:** a single API client (`src/api/client.js`) holds the JWT, performs a
transparent refresh-and-retry on `401`, surfaces the backend error envelope, and (for the PDF report)
streams a binary blob download. Every endpoint is wrapped in `src/api/endpoints.js`. `AuthContext`
decodes the JWT role for client-side nav gating — the backend still enforces RBAC on every request.

---

## Screens

`frontend/src/pages/` — the role-gated workbench:

| Page | Purpose |
|---|---|
| `Landing`, `Login`, `Register`, `Account` | marketing/auth + DPDP consent withdrawal |
| `Apply`, `Applications`, `AppDetail` | customer application + document upload; full application view |
| `Dashboard` | portfolio overview / KPIs |
| `ReviewQueue`, `AnalystReview` | analyst triage; per-signal reasons, ML opinion, **Regulatory Report** |
| `NetworkGraph` | entity-relationship fraud network visualization |
| `Alerts`, `Cases` | SLA-tracked alerts; investigation cases |
| `Investigation`, `SeniorReview` | file investigation reports; senior confirm/clear (segregation of duties) |
| `Knowledge` | fraud pattern library · signal precision (Wilson CI) · governed weight proposals |
| `Operations` | live ops dashboard, active threats, SLA breaches, event log |
| `MLPlatform` | train / approve / promote models, predictions, explanations, drift |

---

## Configuration

All settings come from the environment (or a local `.env`; see `.env.example`). Key values:

| Variable | Purpose | Dev default |
|---|---|---|
| `ENVIRONMENT` | `development` / `staging` / `production` | `development` |
| `DATABASE_URL` | async Postgres DSN | `postgresql+asyncpg://trustlens:trustlens@localhost:5432/trustlens` |
| `JWT_SECRET` | JWT signing secret (≥32 chars in prod) | — (required) |
| `FERNET_KEY` | field-encryption key for PII at rest (use KMS/HSM in prod). **Set a stable value even in dev** — if unset, each process generates a throwaway key, so data encrypted by one process (e.g. the worker) can't be decrypted by another (e.g. the API): PANs/Aadhaar read back empty and the entity graph stays empty. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` | — (ephemeral per-process if unset — **do not rely on this**) |
| `STORAGE_ENDPOINT_URL` / `STORAGE_*` | MinIO/S3 object storage | `http://localhost:9000`, `minioadmin` |
| `REDIS_URL` / `CELERY_BROKER_URL` | Redis broker | `redis://localhost:6379` |
| `EVENTS_BACKEND` | `memory` (dev) or `kafka` (prod) | `memory` |
| `CORS_ORIGINS` | comma-separated allowed origins | `http://localhost:5173` |

In `production`, startup **fails fast** if the JWT secret is default/weak, `FERNET_KEY` is unset, or
CORS is `*`.

---

## Testing & quality

```bash
pytest                       # full suite — SQLite in-memory, no Postgres/Redis/MinIO needed
ruff check app tests         # lint
python -m app.fraud_engine.smoke_test   # standalone fraud-engine smoke test
```

The suite covers core primitives, auth/RBAC, the fraud engine + every intelligence layer, document
forensics, the async pipeline (with injected fake OCR/storage), events/outbox, ML lifecycle, the
fraud-ops closed loop and RBI logic — with a coverage gate. CI (GitHub Actions) additionally runs ruff,
bandit, pip-audit and a secret scan.

---

## API surface

JWT bearer auth; role enforced per endpoint (CUSTOMER / ANALYST / SENIOR_ANALYST / ADMIN). Resource
groups under `/api/v1`:

- `auth` — register, login, refresh, logout, me, MFA (TOTP), DPDP consent withdrawal
- `applications` — CRUD + submit/decision + `risk`, `signals`, `identity`, `property`, `financial`,
  `graph`, `network`, `completeness`, `entities`, **`regulatory-report` (PDF, analyst-only, audited)**
- `documents` — upload (multipart), list, detail (+ OCR summary), extracted entities, presigned download
- `ml` — train / models / approve / reject / promote / predict / explain / labels / drift
- `alerts` — list / acknowledge / resolve / claim / transition / RBI FMR report
- `cases` — create / list / assign / close
- `fraudops` (closed loop) — submit/list investigations, review queue, record review decision,
  `knowledge/patterns` (+ merge), `signal-analytics`, `weights` (propose / activate)
- `operations` — overview / active-threats / sla-breaches / event log / replay
- `health` — live / ready

Full interactive docs: **`/docs`** (OpenAPI). Sensitive fields are masked in every response.

---

## Security & compliance

- **Zero PII leakage** — no PII in logs/events/external calls; sensitive fields encrypted at rest
  (Fernet/MultiFernet, KMS-swappable) and masked in responses (`XXXXXE1234F`). The Regulatory Report
  shows masked identifiers only.
- **Immutable audit** — WORM `audit_logs` (Postgres rules block UPDATE/DELETE) + SHA-256 hash chain for
  tamper-evidence; every state change, PII access and report download is recorded with a correlation id.
- **Segregation of duties** — investigators cannot review their own cases; weight changes require a
  separate approver (propose ≠ approve).
- **AuthN/Z** — Argon2 hashing, short-lived access + rotating refresh tokens (reuse detection), RBAC,
  rate limiting on `/auth` and `/ml/predict`, TOTP MFA for privileged roles, security headers.
- **RBI Fraud Management** — exposure-threshold engine (FLASH/FMR-1/quarterly), SLA deadlines,
  `rbi_reporting_required` flagging, FMR-shaped report generation, and the per-application Regulatory
  Explainability Report (reproducible via engine + weight-config versions; audit-chain attested).
- **DPDP Act 2023** — explicit consent capture/withdrawal and a documented retention/erasure policy
  (`RETENTION.md`) that preserves the immutable audit trail.

---

## Deployment (single-host / EC2)

The stack ships as a self-contained `docker compose` deployment — suitable for a single VM
(e.g. an EC2 `t3.large`) or an on-prem host. From a clone of the repo on the server:

```bash
# 1. One-time: create .env with production values (never commit it)
cp .env.example .env
#    REQUIRED, non-negotiable:
#      ENVIRONMENT=production
#      JWT_SECRET=<≥32 random chars>
#      FERNET_KEY=<python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
#      CORS_ORIGINS=<the exact origin the SPA is served from, e.g. http://13.222.59.168:5173>
#    In production the API refuses to start if JWT_SECRET is weak, FERNET_KEY is unset, or CORS is *.

# 2. Build + run the whole stack (postgres, redis, minio, api, worker + one-shot migrate)
docker compose up -d --build
docker compose ps               # confirm every service is Up; worker must show queues ocr,default

# 3. Smoke-test
curl -s http://localhost:8000/api/v1/health/ready
```

**Networking:** open the API port (`8000`) — and, if the SPA is served from the same box, the
frontend port — in the instance's security group. Keep Postgres (`5432`), Redis (`6379`) and MinIO
(`9000/9001`) **closed to the internet**; they're only reached over the compose network.

**Frontend:** either build it (`npm run build`) and serve `frontend/dist/` as static files behind a
web server, or run the Vite dev server. Either way set `VITE_API_BASE` to the API's public base
(`http://<server-ip>:8000/api/v1`) and add that SPA origin to `CORS_ORIGINS`.

**Users:** the database starts empty. Create the first analyst/admin directly (there is no public
"become an analyst" flow — customers self-register as `CUSTOMER`):

```python
# docker compose exec -T api python
import asyncio, secrets, string
from sqlalchemy import select
from app.database import SessionFactory
from app.models.user import User
from app.models.enums import UserRole
from app.core.security import hash_password
pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
async def main():
    async with SessionFactory() as s:
        s.add(User(email="analyst@trustlens.ai", full_name="Analyst",
                   hashed_password=hash_password(pw), role=UserRole.ANALYST,
                   is_active=True, mfa_enabled=False))
        await s.commit()
    print("analyst@trustlens.ai", pw)
asyncio.run(main())
```

> Use a real, resolvable email domain — the login schema validates `EmailStr`, which rejects
> reserved TLDs like `.local`.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Documents stay **QUEUED**, never PROCESSED | Worker not consuming the `ocr` queue (OCR is the pipeline's first step and routes to `ocr`) | Run the worker with `-Q ocr,default`; confirm `docker compose logs worker` shows both queues under `[queues]` |
| Worker crashes with **"Future attached to a different loop"** | Each Celery task runs in a fresh asyncio loop, but the async DB engine pools connections pinned to the loop that created them | The worker uses a `NullPool` engine when `WORKER_PROCESS=1` (set on the worker service); ensure that env var is present |
| Extracted **PANs/Aadhaar read back empty**, entity graph shows 0 connections | Blank/ephemeral `FERNET_KEY` — data was encrypted with a key that later processes don't have, so decryption silently returns empty | Set a stable `FERNET_KEY` in `.env`, restart api + worker, and re-run extraction on affected documents |
| SPA shows **"Failed to fetch"** on login | `VITE_API_BASE` unset or wrong (SPA calling `localhost` / the dev server instead of the API), or the SPA origin isn't in `CORS_ORIGINS` | Set `VITE_API_BASE` to the API base incl. `/api/v1`, restart Vite, add the origin to `CORS_ORIGINS` |
| Login returns **422** on a valid-looking email | `EmailStr` rejects reserved TLDs (`.local`, etc.) | Use a resolvable domain (e.g. `.ai`, `.com`) |
| **Senior Review** page errors for an analyst | `/reviews/queue` requires SENIOR_ANALYST/ADMIN (segregation of duties) — a plain ANALYST is correctly forbidden (403) | Expected; use a SENIOR_ANALYST account for that screen |
| OCR task fails: **"value too long for type character varying(64)"** | An OCR engine wrote an over-length `model_version` | Fixed — engine/version strings are clamped to 64 chars; rebuild the worker image if running old code |

---

## Offline / air-gapped operation

The platform runs with **no internet access**:

- All compute is local — deterministic rules, OCR, document forensics, graph analytics, the ML model
  (scikit-learn) and PDF report generation (reportlab).
- Datastores (Postgres, Redis, MinIO, optional Kafka) run as local containers.
- **No cloud AI / LLM APIs** are ever called; the deterministic engine is the system of record and ML
  is an advisory local second opinion.
- The only network touchpoints are build-time (`pip` / `npm`) and optional model downloads
  (PaddleOCR / spaCy) — bundle these into the image for a true air-gap; PyMuPDF needs no download.
