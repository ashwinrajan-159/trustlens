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
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Quickstart — run the whole app](#quickstart--run-the-whole-app)
- [Backend — detailed build & run](#backend--detailed-build--run)
- [Frontend — detailed build & run](#frontend--detailed-build--run)
- [Configuration](#configuration)
- [Testing & quality](#testing--quality)
- [API surface](#api-surface)
- [Security & compliance](#security--compliance)
- [Offline / air-gapped operation](#offline--air-gapped-operation)

---

## What it does

A loan application flows through an **idempotent, explainable analysis pipeline** and surfaces in an
analyst workbench:

- **Document intake & OCR** — upload PDFs/images (validated by magic bytes); OCR via PyMuPDF (digital
  PDFs) with PaddleOCR as an optional engine for scanned images.
- **Layout-agnostic extraction** — pulls structured fields (PAN, Aadhaar, name, salary, account,
  survey number, revenue, …) from messy documents; PII is encrypted at rest and masked in responses.
- **Deterministic fraud engine** — a standalone, unit-testable rule package (Aadhaar Verhoeff, PAN/
  IFSC/GSTIN validators, income/property/financial rules) producing weighted, explainable signals.
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
- **Operations & audit** — operations dashboards, an immutable (WORM) audit trail with a tamper-evidence
  hash chain, and a role-gated React workbench.

---

## Architecture

```
┌──────────────┐      ┌───────────────┐      ┌──────────────────────────────────┐
│ React + Vite │─────▶│   FastAPI     │─────▶│ PostgreSQL (apps, docs, entities, │
│  SPA (5173)  │ JWT  │  REST (8000)  │ async│  signals, assessments, profiles,  │
└──────────────┘      └──────┬────────┘ SQLA │  alerts, cases, audit[WORM],       │
                             │ enqueue        │  event_log, ml_*)                  │
                             ▼                └──────────────────────────────────┘
                      ┌──────────────┐  broker   ┌──────────────────────────────┐
                      │ Redis (6379) │──────────▶│ Celery worker                │
                      └──────────────┘           │  analysis pipeline (chained) │
                             ▲                    └──────┬───────────────────────┘
              ┌──────────────┴────────┐                  │ docs in/out
              │ Event bus (in-proc /  │◀──── outbox ──────┤
              │ Kafka) + EventLog     │                   ▼
              └───────────────────────┘            ┌──────────────┐   ┌───────────┐
                                                   │ MinIO / S3   │   │ NetworkX  │
                                                   │ (documents)  │   │ (graph)   │
                                                   └──────────────┘   └───────────┘
```

**Bounded modular monolith** — each domain (`ingestion/ocr`, `extraction`, `fraud-engine`,
`identity`, `property`, `financial`, `graph`, `ml`, `events`, `alerting`, `cases`, `compliance`) lives
behind a service-class interface so it can later be extracted into its own deployable. Async tasks run
on Celery; cross-cutting durability is provided by a transactional-outbox `event_log`.

---

## The analysis pipeline

Triggered on document upload / application submit, each step is **idempotent and re-runnable** and
persists its results before chaining the next:

```
run_ocr_pipeline → extract_entities → run_fraud_engine → run_identity_resolution
→ run_cross_document_validation → run_property_validation → run_financial_validation
→ run_graph_analysis → compute_risk_assessment → (real-time) generate_fraud_alert
```

Document status flows `QUEUED → PROCESSING → PROCESSED | FAILED`. The deterministic engine remains the
system of record; ML inference and external verification are advisory and degrade gracefully.

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
| **ML (local)** | scikit-learn, XGBoost (optional), SHAP (optional), scipy (KS drift), joblib; MLflow optional |
| **Graph** | NetworkX (in-memory analytics); Neo4j optional for persistence |
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
│   ├── api/v1/                # REST routers (auth, applications, documents, ml,
│   │                          #   alerts, cases, operations, health)
│   ├── core/                  # security, encryption, logging, rate limit, middleware, files
│   ├── models/                # SQLAlchemy ORM + central enums
│   ├── schemas/               # Pydantic request/response models
│   ├── repositories/          # data-access layer
│   ├── services/              # business logic (auth, document, ocr, extraction,
│   │                          #   identity, cross_document, property_intel, financial,
│   │                          #   graph_intel, ml*, alerting, cases, rbi, storage, audit)
│   ├── fraud_engine/          # standalone deterministic engine (rules, validators, scorer)
│   └── tasks/                 # Celery pipeline tasks (ocr, extraction, fraud, identity,
│                              #   cross_document, property, financial, graph, events)
├── alembic/versions/          # database migrations (001 … 012)
├── tests/                     # pytest suite (SQLite in-memory; no external services)
├── frontend/                  # React + Vite SPA
│   └── src/{api,auth,components,lib,pages}/
├── docker-compose.yml         # postgres · redis · minio · api · worker
├── Dockerfile                 # backend image
├── requirements.txt
├── pyproject.toml             # ruff / pytest / coverage config
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

From the repo root (`truestlens/`):

```bash
# 1. Infra (Postgres + Redis + MinIO)
docker compose up -d postgres redis minio

# 2. Backend deps + env
python -m venv .venv && . .venv/Scripts/activate     # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                                  # then set JWT_SECRET_KEY + FERNET_KEY (below)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # → FERNET_KEY

# 3. Database
alembic upgrade head
python -c "import asyncio; from app.services.storage import StorageService; asyncio.run(StorageService().ensure_bucket())"

# 4. Run API + worker (two terminals)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
celery -A app.worker.celery_app worker --pool=solo -Q ocr,default --loglevel=info   # use --pool=solo on Windows

# 5. Frontend (third terminal)
cd frontend && npm install && npm run dev
```

Open **http://localhost:5173** — register, create an application, upload documents, and watch the
risk/signals/identity/graph populate. API docs at **http://localhost:8000/docs**.

> The Vite dev server proxies `/api` → `http://localhost:8000`, so the SPA is same-origin in dev
> (no CORS setup needed).

---

## Backend — detailed build & run

```bash
# install
python -m venv .venv && . .venv/Scripts/activate
pip install -r requirements.txt

# database migrations (forward / inspect / down)
alembic upgrade head
alembic current
alembic downgrade -1

# run the API
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# run the analysis worker (solo pool required on Windows; prefork on Linux)
celery -A app.worker.celery_app worker -Q ocr,default --loglevel=info

# (optional) event reconciliation / scheduled jobs run as Celery tasks:
#   app.tasks.events.replay_pending_events  — re-publishes any PENDING outbox events
```

**Build the backend Docker image** and run the full stack in containers:

```bash
docker compose up -d --build              # builds api + worker images, runs migrations, starts everything
docker compose --profile workers up -d    # also start the Celery worker service
docker compose logs -f api
docker compose down                       # stop (add -v to wipe volumes)
```

The compose `migrate` service runs `alembic upgrade head` to completion before `api` starts.

---

## Frontend — detailed build & run

```bash
cd frontend

npm install            # install deps (React 19, Vite, Tailwind, React Router, lucide-react)
npm run dev            # dev server with HMR at http://localhost:5173 (proxies /api → :8000)
npm run build          # production bundle → frontend/dist/
npm run preview        # serve the production build locally
```

To point the SPA at a non-default API origin, set `VITE_API_TARGET` (dev proxy target) or
`VITE_API_BASE` (the API path prefix, default `/api/v1`). The production `dist/` is static and can be
served from any web server / behind the API's origin.

**How the SPA connects to the services:** a single API client (`src/api/client.js`) holds the JWT,
performs a transparent refresh-and-retry on `401`, and surfaces the backend error envelope; every
endpoint is wrapped in `src/api/endpoints.js`. `AuthContext` decodes the JWT role for client-side nav
gating — the backend still enforces RBAC on every request.

---

## Configuration

All settings come from the environment (or a local `.env`; see `.env.example`). Key values:

| Variable | Purpose | Dev default |
|---|---|---|
| `ENVIRONMENT` | `development` / `staging` / `production` | `development` |
| `DATABASE_URL` | async Postgres DSN | `postgresql+asyncpg://trustlens:trustlens@localhost:5432/trustlens` |
| `JWT_SECRET_KEY` | JWT signing secret (≥32 chars in prod) | — (required) |
| `FERNET_KEY` | field-encryption key (use KMS/HSM in prod) | — (ephemeral in dev if unset) |
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

The suite covers core primitives, auth/RBAC, the fraud engine + every intelligence layer, the async
pipeline (with injected fake OCR/storage), events/outbox, ML lifecycle, alerting/cases and RBI logic —
with a coverage gate. CI (GitHub Actions) additionally runs ruff, bandit, pip-audit and a secret scan.

---

## API surface

JWT bearer auth; role enforced per endpoint (CUSTOMER / ANALYST / SENIOR_ANALYST / ADMIN). Resource
groups under `/api/v1`:

- `auth` — register, login, refresh, logout, me, MFA (TOTP), DPDP consent withdrawal
- `applications` — CRUD + submit/decision + `risk`, `signals`, `identity`, `property`, `financial`,
  `graph`, `network`, `completeness`, `entities`
- `documents` — upload (multipart), list, detail (+ OCR summary), extracted entities, presigned download
- `ml` — train / models / approve / reject / promote / predict / explain / labels / drift
- `alerts` — list / acknowledge / resolve / RBI FMR report
- `cases` — create / list / assign / close
- `operations` — overview / active-threats / sla-breaches / event log / replay
- `health` — live / ready

Full interactive docs: **`/docs`** (OpenAPI). Sensitive fields are masked in every response.

---

## Security & compliance

- **Zero PII leakage** — no PII in logs/events/external calls; sensitive fields encrypted at rest
  (Fernet/MultiFernet, KMS-swappable) and masked in responses (`XXXXXE1234F`).
- **Immutable audit** — WORM `audit_logs` (Postgres trigger blocks UPDATE/DELETE) + SHA-256 hash chain
  for tamper-evidence; every state change and PII access is recorded with a correlation id.
- **AuthN/Z** — Argon2 hashing, short-lived access + rotating refresh tokens (reuse detection), RBAC,
  rate limiting on `/auth` and `/ml/predict`, TOTP MFA for privileged roles, security headers.
- **RBI Fraud Management** — exposure-threshold engine (FLASH/FMR-1/quarterly), SLA deadlines,
  `rbi_reporting_required` flagging and FMR-shaped report generation.
- **DPDP Act 2023** — explicit consent capture/withdrawal and a documented retention/erasure policy
  (`RETENTION.md`) that preserves the immutable audit trail.

---

## Offline / air-gapped operation

The platform runs with **no internet access**:

- All compute is local — deterministic rules, OCR, graph analytics and the ML model (scikit-learn).
- Datastores (Postgres, Redis, MinIO, optional Kafka) run as local containers.
- **No cloud AI / LLM APIs** are ever called; the deterministic engine is the system of record and ML
  is an advisory local second opinion.
- The only network touchpoints are build-time (`pip` / `npm`) and optional model downloads
  (PaddleOCR / spaCy) — bundle these into the image for a true air-gap; PyMuPDF needs no download.
