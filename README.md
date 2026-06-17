# TrustLens AI

Production-grade, explainable **fraud detection & underwriting-intelligence platform** for Indian
banks. Every piece of intelligence is anchored to a **loan application**, never to an isolated
document. The system is **explainable-first** (deterministic rule engine + weighted scoring; ML
augments but never replaces explainability) and **fail-safe** (external failures degrade to
"unverified", never silently pass).

> ⚠️ Banking context: zero PII leakage, immutable audit, encryption at rest. These are not optional.

## Status

Built in phases per `TRUSTLENS_BUILD_SPEC.md`.

| Phase | Scope | Status |
|------:|-------|--------|
| 1 | Foundations: FastAPI, async DB + Alembic, users/auth (JWT, RBAC), encryption + audit, health | ✅ done |
| — | Hardening pass (all 26 `IMPROVEMENTS.md` items) | ✅ done |
| 2 | Documents + OCR: Celery `run_ocr_pipeline`, pluggable OCR (PyMuPDF/PaddleOCR), `ocr_results`, status flow | ✅ done |
| 3a | Extraction: layout-agnostic entity extraction (`extracted_entities`), chained after OCR, masked view endpoints | ✅ done |
| 3b | Single-doc `fraud_engine` (standalone, Verhoeff/PAN/IFSC/GSTIN validators) + weighted risk scoring → tier | ✅ done |
| 4 | Identity intelligence: cross-document resolution + synthetic-identity detection (`identity_profiles`) | ✅ done |
| 5 | Cross-document: home-loan completeness checklist + salary↔bank income reconciliation | ✅ done |
| 6 | Property intel (owner/survey/area/inflated-valuation, cross-app duplicate collateral) + financial recon (revenue mismatch, impossible ratio) | ✅ done |
| 7 | Graph intel (NetworkX): shared-PAN / mule-account / duplicate-collateral networks, fraud rings, high-centrality hubs; per-app network endpoint | ✅ done |
| 8 | Events: versioned PII-free schemas, transactional outbox (`event_log`) dual-write, relay + reconciliation/replay, real-time engine | ✅ done |
| 9 | ML platform (local): feature store, sklearn/XGBoost training w/ gates + governance, champion inference + SHAP, KS drift | ✅ done |
| 10 | Alerting (SLA + real-time escalation), investigation cases, RBI FMR reporting, operations dashboards | ✅ done |
| 11 | Frontend (React 19 + Vite + Tailwind + Router 7): all pages, role-gated nav, every service wired | ✅ done |
| 12+ | External-verification, anti-spoofing, DPDP erasure, infra/CI/k8s | ⏳ |

## Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (proxies /api → http://localhost:8000)
npm run build      # production bundle in dist/
```

React 19 · Vite · TailwindCSS · React Router 7 · lucide-react (no chart lib — lightweight
inline SVG/CSS). Single API client (`src/api/client.js`) with token storage + transparent
401-refresh-retry; `AuthContext` decodes the JWT role for client-side nav gating (backend
still enforces). Pages: Landing, Login, Register, Dashboard (role-aware), Apply (multi-step
upload), Applications, App Detail (risk/signals/identity/property/financial/documents tabs),
Analyst Review (signals + ML second opinion + decision), Review Queue, Alerts (+ RBI FMR),
Cases, Operations (overview + event log + replay), ML Platform, Network Graph, Account
(MFA + DPDP consent).
| … | see spec | ⏳ |

## Stack (Phase 1)

Python 3.12+ · FastAPI 0.115 · async SQLAlchemy 2.0 · Pydantic v2 · Alembic · PostgreSQL 16 ·
MinIO/S3 (aioboto3) · JWT (python-jose) · Fernet field encryption · structlog.

## Layout

```
app/
  main.py            FastAPI app + lifespan + middleware
  config.py          pydantic-settings
  database.py        async engine + session factory
  dependencies.py    FastAPI DI wiring
  core/              security (JWT/hash), encryption, logging, exceptions
  models/            SQLAlchemy ORM + enums
  schemas/           Pydantic request/response models
  repositories/      data-access layer
  services/          business logic (auth, application, document, storage)
  api/v1/            REST endpoints
alembic/             migrations
tests/               pytest + httpx (SQLite in-memory)
docker-compose.yml   postgres · redis · minio · api · worker
```

## Quickstart (local dev)

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                                # then fill JWT_SECRET_KEY + FERNET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # -> FERNET_KEY
docker compose up -d postgres redis minio           # infra
alembic upgrade head                                # migrate
uvicorn app.main:app --reload                       # http://localhost:8000/docs
```

## Tests

```bash
pytest -q          # uses SQLite in-memory; no Postgres/MinIO needed
```

## Security & compliance principles (enforced)

- **Explainable, deterministic-first** — no black-box LLM produces a risk score.
- **Zero PII leakage** — no PII in logs/events/external LLM calls; sensitive fields encrypted at rest, masked in responses.
- **Immutable audit** — every state change & PII access in a write-once audit trail (DB-level `no_update`/`no_delete`).
- **Fail safe** — external verification failures signal "unverified", never silently pass.
- **Idempotent pipeline** — every async step is safely re-runnable.
