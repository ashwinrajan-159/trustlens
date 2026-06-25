# TrustLens AI — Master Build Specification & Implementation Prompt

> **Use this document as the single source of truth to build TrustLens AI from a clean repository.**
> It is written as an instruction prompt for an autonomous engineering agent (or a team). Build in the
> phase order given. Do not skip the security, compliance, and audit requirements — they are not optional
> in a banking context.

---

## 0. Role & Mission

You are a **Principal Banking Fraud Architect and Senior Staff Engineer**. Build a production-grade,
AI-powered **fraud detection and underwriting-intelligence platform** for Indian banks (target deployment:
Canara Bank, SBI, HDFC, ICICI, Axis) processing **100,000+ loan applications per year**.

**Core thesis:** TrustLens is a **case-based underwriting intelligence platform**, not a document scanner.
Every piece of intelligence is anchored to a **loan application**, never to an isolated document. The system
detects forged documents, synthetic/stolen identities, collateral fraud, shell companies, and coordinated
fraud rings — and **explains every decision** in a way a regulator and a human analyst can audit.

**Non-negotiable principles:**
1. **Explainable, deterministic-first.** Risk decisions come from an auditable rule engine + weighted scoring. ML augments but never replaces explainability (use SHAP). Never let a black-box LLM produce a risk score.
2. **Zero PII leakage.** No PII in logs, events, or external LLM calls. Sensitive fields are encrypted at rest and masked in every API response.
3. **Immutable audit.** Every state change and PII access is recorded in a write-once audit trail.
4. **Fail safe, never fail open.** External verification failures degrade gracefully (signal "unverified"), never silently pass.
5. **Idempotent pipeline.** Every async step is safely re-runnable.

---

## 1. Domain Context

- **Loan types:** HOME, PERSONAL, BUSINESS, AUTO.
- **Applicant types:** salaried and self-employed.
- **Document set (home loan, representative):**
  - *Identity:* Aadhaar, PAN, Passport, Voter ID, Driving License.
  - *Address:* Aadhaar/Passport/Voter ID, Utility Bill, Rental Agreement.
  - *Income (salaried):* Salary Slips (3–6 mo), Bank Statements (6–12 mo), Form 16 (2 yr).
  - *Income (self-employed):* ITR (2–3 yr), P&L, Balance Sheet, GST Returns, business proof.
  - *Property:* Sale Deed, Title Deed, Mother Deed, Encumbrance Certificate, Valuation Report, approved plan, property tax.
- **Compliance regimes:** RBI Fraud Management Framework + FMR reporting, RBI Cyber Security Framework, DPDP Act 2023.
- **Indian-specific validators:** Aadhaar **Verhoeff checksum**, PAN format `[A-Z]{5}[0-9]{4}[A-Z]`, GSTIN 15-char, IFSC, CIN.

---

## 2. Architecture

```
┌──────────────┐      ┌───────────────┐      ┌─────────────────────────────────┐
│ React + Vite │─────▶│   FastAPI     │─────▶│ PostgreSQL (apps, docs, entities,│
│  (SPA, 5173) │ JWT  │  (REST, 8000) │ async│ signals, assessments, cases,     │
└──────────────┘      └──────┬────────┘ SQLA │ alerts, audit[WORM], event_log)  │
                             │ enqueue        └─────────────────────────────────┘
                             ▼
                      ┌──────────────┐   broker   ┌──────────────────────────────┐
                      │ Redis (6379) │───────────▶│ Celery workers               │
                      └──────────────┘            │  14-step analysis pipeline   │
                             ▲                     └──────┬───────────────────────┘
              ┌──────────────┴───────┐                   │ docs in/out
              │ Kafka (event bus)    │◀──── producer ─────┤
              │ + EventLog dual-write│                    ▼
              └──────────────────────┘            ┌──────────────┐   ┌───────────┐
                                                  │ MinIO / S3   │   │ Neo4j     │
                                                  │ (documents)  │   │ (graph)   │
                                                  └──────────────┘   └───────────┘
        Sidecars: MLflow (model registry), Prometheus/Grafana/Loki (observability)
```

**Service boundaries (modular monolith first, microservice-ready):**
`api` · `ingestion/ocr` · `extraction` · `fraud-engine` · `identity-intel` · `property-intel` ·
`financial-intel` · `graph-intel` · `ml-platform` · `case-management` · `alerting` · `compliance` ·
`external-verification`. Keep each behind a service-class interface so it can be extracted into its own
deployable later. Do **not** start with microservices — start with a well-bounded monolith + Celery.

---

## 3. Technology Stack (pin major versions)

| Layer | Technology |
|---|---|
| Backend | Python 3.12+, FastAPI 0.115, **async** SQLAlchemy 2.0, Pydantic v2, Alembic |
| Async | Celery 5.4 (+ Redis broker/result), task queues: `ocr`, `default`, `dlq` |
| Datastores | PostgreSQL 16 (Neon/RDS), Redis 7, Neo4j 5, MinIO/S3 |
| Events | Kafka (aiokafka producer) + PostgreSQL `event_log` dual-write durability |
| OCR/NLP | PaddleOCR (+ PyMuPDF `fitz` text fallback), spaCy NER, Pillow + numpy for image metrics |
| ML | scikit-learn, XGBoost, LightGBM, (CatBoost optional), IsolationForest; MLflow; SHAP; scipy (KS drift) |
| Graph | Neo4j (persisted) + NetworkX (in-memory analytics fallback) |
| Frontend | React 19, Vite, React Router 7, TailwindCSS, Recharts, lucide-react |
| Infra | Docker, Kubernetes/EKS, Terraform, multi-AZ, blue/green |
| Observability | Prometheus, Grafana, Loki, OpenTelemetry, AlertManager |
| Security | Fernet field encryption (→ AWS KMS/HSM in prod), JWT auth, immutable audit |

---

## 4. Data Model (core tables)

Build with async SQLAlchemy + Alembic migrations. All tables: UUID PK, `created_at`, `updated_at`,
soft-delete `deleted_at` (except audit). Sensitive columns use an `EncryptedString` TypeDecorator.

- **users** — email, hashed_password, full_name, `role` (CUSTOMER|ANALYST|SENIOR_ANALYST|ADMIN), is_active, data_consent_given_at, deleted_at.
- **applications** — application_number, applicant_id→users, loan_type, loan_amount_requested, status (DRAFT|SUBMITTED|UNDER_REVIEW|APPROVED|REJECTED), risk_tier, current_risk_score, submitted_at, decision_*.
- **documents** — application_id, document_type, original_filename, storage_bucket/key, content_type, file_size, checksum_sha256 (indexed), is_current_version, version, status (QUEUED|PROCESSING|PROCESSED|FAILED), uploaded_by.
- **ocr_results** — document_id, raw_text, confidence_score, page_count, pages_data(JSONB), engine, model_version.
- **extracted_entities** — document_id, application_id, entity_type, value (encrypted if sensitive), masked_value, is_sensitive, confidence, extraction_method, source_page.
- **fraud_signals** — application_id, document_id?, signal_type, severity (LOW|MEDIUM|HIGH|CRITICAL), description, evidence(JSONB), confidence, rule_name, engine_version, **signal_scope** (DOCUMENT|CROSS_DOCUMENT|IDENTITY|PROPERTY|FINANCIAL|GRAPH), source_document_ids, is_confirmed.
- **risk_assessments** — application_id, total_score (0–100), risk_tier, reasons(JSONB of weighted RuleResults), engine_version.
- **identity_profiles / property_profiles / business_profiles** — resolved per-application intelligence.
- **graph_analyses** — application_id, graph_risk_score, fraud_connections_count, shared_*_count.
- **review_queue / review_decisions** — analyst workflow, priority, SLA deadline, assignment.
- **fraud_alerts** — alert_number, alert_type, severity, application_id, status, rbi_reporting_required, sla_deadline, sla_breached.
- **investigation_cases** — case_number, case_type, status, priority, application_ids[], alert_ids[], summary, sla_deadline, closed_outcome.
- **ml_models / ml_predictions / ml_labels / ml_feature_snapshots** — model registry + inference + training labels.
- **audit_logs** — `ImmutableBase`: actor_id, action, entity_type, entity_id, before_state, after_state, ip, user_agent, correlation_id. **Enforce write-once with PostgreSQL rules** `no_update`/`no_delete`.
- **event_log** — durable event outbox (dual-write before Kafka).

**Enums to define centrally:** DocumentType, DocumentStatus, EntityType, FraudSignalType, SignalSeverity, SignalScope, RiskCategory, UserRole, plus a `SIGNAL_CATEGORY_MAP`.

---

## 5. The 14-Step Analysis Pipeline (Celery chain)

Triggered on application **submit**. Each task is idempotent and re-runnable; each persists results and emits a domain event.

```
run_ocr_pipeline → extract_entities → run_fraud_engine
→ run_document_identity_validation → run_cross_document_validation
→ run_identity_resolution → run_property_validation
→ run_collateral_deduplication → run_financial_validation
→ run_invoice_deduplication → run_graph_analysis
→ compute_risk_assessment → generate_fraud_alerts → enqueue_for_review
```

**Rules:** OCR on a dedicated CPU queue; all else on default I/O queue. `task_acks_late=True`.
Deduplicate by document `checksum_sha256` (a checksum legitimately recurs — use ordered `limit(1)`, never `scalar_one_or_none`). Cross-doc steps exit "deferred" until their prerequisite docs are PROCESSED, and are idempotent (soft-delete prior same-scope signals before regenerating).

---

## 6. Extraction (format-agnostic)

- OCR: PaddleOCR primary, PyMuPDF `get_text` fallback (0.85 confidence) for digital PDFs.
- Entity extraction must be **layout-agnostic**: handle label/value on the same line, on adjacent lines, with parenthetical suffixes (`Net Pay (computed):`), and all currency prefixes (`INR`, `₹`, `Rs.`). Anchor ambiguous labels to line-start to avoid substring collisions (e.g. "Total Income" vs "Gross Total Income").
- Route by document type to a dedicated extraction service (salary, bank statement, Aadhaar, PAN, property, financial). spaCy NER as fallback for names; labeled regex preferred.

---

## 7. Fraud Detection (deterministic `fraud_engine` package)

Build `fraud_engine` as a **standalone package** (own tests, `smoke_test.py`) so it is reusable and unit-testable without the web app. Pattern: each rule receives a **context dataclass** (pre-fetched, no DB access inside rules) and returns `RuleResult(signal_type, severity, description, evidence, confidence, rule_name)`. Tasks convert `RuleResult → FraudSignal` with the correct `signal_scope`.

**Signal families (implement all):**
- *Document integrity:* low OCR confidence, suspicious PDF producer (cracked editing tools), modified-after-creation, missing metadata, font inconsistency, watermark anomalies, synthetic-document markers, duplicate document.
- *Image anti-spoofing (on photographed IDs):* screen-capture (moiré + glare), photocopy (low contrast + desaturation), ELA tamper regions, blur/glare quality, signature-region presence.
- *Identity:* invalid Aadhaar (Verhoeff), invalid PAN format, PAN/Aadhaar name/DOB/address mismatch, possible synthetic identity.
- *Income:* salary extraction failure, round-number salary, salary mismatch (payslip vs bank credits), employer-deposit-not-found, irregular pattern.
- *Property:* owner mismatch, survey-number conflict, area mismatch, timeline anomaly, inflated valuation, duplicate collateral.
- *Financial:* revenue mismatch, GST inconsistencies, invalid/unverifiable CA, fake/duplicate invoices, shell-company indicators, impossible ratios.
- *Graph:* connected fraud network, mule-account reuse, duplicate-collateral network, hidden ownership, fraud ring (community detection), high centrality.
- *Document completeness (home loan checklist):* missing Aadhaar/PAN/bank/income-proof/sale-deed/valuation (CRITICAL); missing Form 16/property-tax/EC/building-plan (MEDIUM).

**Risk scoring:** weighted sum of signal severities by `RiskCategory` (INCOME, IDENTITY, DOCUMENT, BEHAVIOR) → 0–100 → tier (LOW<30, MEDIUM 30–60, HIGH 60–80, CRITICAL>80). Persist the full `reasons` breakdown.

---

## 8. External Verification Framework (adapter + circuit breaker)

All third-party verifications (which need bank-provisioned credentials/contracts) follow one pattern so they
are testable before going live:

- **Adapter interface** per provider: `verify_*(…) -> Result | None`, `is_available()`, `get_registry_name()`.
- Ship a **sandbox/simulator adapter** + a **live adapter**; select by config. `is_available()` gates live calls.
- Wrap every outbound call in a **circuit breaker** (CLOSED→OPEN→HALF_OPEN) + timeout + retries. **Never throw into the pipeline** — return `None`/"unverified" and emit a signal.
- Map results → `RuleResult` → `FraudSignal`.

**Providers to implement (sandbox first, live on credential availability):**
Identity — PAN/NSDL, CKYC, Aadhaar eKYC, Passport, DL, Voter ID, face-match + liveness.
Banking — penny-drop account ownership, IFSC, UPI.
Income — EPFO, Form 16 / ITR validation, employer verification.
Property — land registry (Dharani/IGRS/Kaveri), encumbrance, valuation.
Credit bureaus — CIBIL, Experian, CRIF, Equifax.
Fraud intel — watchlists, blacklisted PAN/account, fraud-consortium feeds.

---

## 9. ML Platform

- **Training pipeline:** features from `ml_feature_snapshots` + labels from `analyst_feedback`; stratified split; min-sample + min-fraud-rate gates; algorithms XGBoost, LightGBM, RandomForest, IsolationForest (CatBoost/ensemble optional). Log to **MLflow** (params, metrics, artifact). Metrics: PR-AUC, ROC-AUC, F1, precision, recall, FPR, FDR@5/10/20.
- **Governance:** TRAINING→TRAINED→EVALUATING→APPROVED→DEPLOYED; approval gates (min PR-AUC, max FPR); single champion; **human approval required** (senior analyst).
- **Inference:** champion from MLflow, cached; `predict_proba`; risk tier; **SHAP** top-feature contributions with direction; latency tracked.
- **Drift:** scipy KS-test for feature/prediction/label drift with thresholds + recommendation; scheduled.
- ML is a **second opinion**; the deterministic engine remains the system of record for explainability.

---

## 10. Graph Intelligence

Build an entity-relationship graph (Application, Person, Company, BankAccount, Property, PAN, GSTIN, Document)
in Neo4j (NetworkX fallback). Detect: fraud rings (community detection), mule accounts, duplicate collateral
across applications, hidden ownership chains (multi-hop), UBO discovery, high-centrality hubs. Expose a
per-application network endpoint for the analyst UI.

---

## 11. Events & Streaming

- Define ~12 versioned event schemas (ApplicationCreated, DocumentUploaded, RiskCalculated, FraudSignalGenerated, FraudAlertGenerated, CaseCreated/Closed, AnalystDecisionMade, IdentityFlagged, PropertyFlagged, FraudRingDetected, ModelPredictionGenerated). **No PII in payloads** — IDs + correlation_id only.
- **Dual-write durability:** write `event_log` (PENDING) → publish to Kafka → mark SENT. Build the **reconciliation/replay job** that re-publishes PENDING events (required, not optional).
- Build **Kafka consumers** + a real-time risk engine that turns CRITICAL events into alerts/cases sub-second, with idempotency on (event_id, application_id).
- Topic naming: `trustlens.<entity>.<action>`; DLQ `trustlens.dlq.<topic>`.

---

## 12. API Surface (FastAPI, ~47 endpoints)

JWT bearer; role enforced per endpoint via dependencies. Resource groups: `auth`, `applications`,
`documents` (incl. presigned download), `risk` (analyze/risk/signals), `signals` (override),
`review-queue`, `identity`, `property`, `financial`, `graph` (overview/network/risk/feedback),
`ml` (train/models/predict/explain/drift/labels/approve/reject/promote), `alerts`, `cases`,
`operations` (overview/active-threats/sla-breaches/trends), `health` (live/ready), `demo`.

Conventions: paginated list responses; sensitive fields masked in responses; analyst-feedback endpoints
become ML training labels; every mutating call writes an audit entry.

---

## 13. Frontend (React + Vite)

- Pages: **Dashboard** (real applications + KPIs), **Apply** (multi-step: loan → grouped document upload → submit/analyze), **Analyst Review** (signal-by-signal verdicts + per-domain identity/financial/property/graph feedback + final decision + document downloads + view-network link), **Review Queue**, **Alerts**, **Operations**, **Cases** (+ detail), **ML Platform**, **Network Graph** (per-application), **App Detail**, **Login/Register**.
- **Role-based gating:** decode JWT role client-side; hide the analyst nav cluster from customers; hide senior-only actions (ML approve/reject/promote, case close) from plain analysts. Backend still enforces.
- No demo/synthetic data in the product UI; public landing when logged out, real data when logged in.
- Single API client with one `req()` helper; token from storage; graceful error + loading states.

---

## 14. Security (mandatory)

- **Encryption at rest:** field-level for PAN, Aadhaar (store only last-4 + validate-then-discard full number), account numbers. Fernet (AES) in dev → **AWS KMS / HSM** in prod with key rotation. Tokenization for cross-system references.
- **Secrets:** AWS Secrets Manager / Vault; never in code or `.env` committed (`.env` gitignored).
- **Masking:** every API response masks sensitive values (`XXXXXE1234F`, `XXXX XXXX 1234`).
- **Audit:** immutable WORM `audit_logs` (DB `no_update`/`no_delete` rules); record every PII access and state change with correlation_id.
- **Zero PII logging:** structured logs (structlog/JSON) with correlation_id + user_id only — never raw PII or full document text.
- **Transport/authz:** TLS everywhere, JWT with short-lived access + refresh, RBAC, rate limiting on `/auth` and `/ml/predict`.

---

## 15. Compliance (mandatory)

- **RBI Fraud Management:** threshold engine — ≥₹25Cr flash report (24h), ≥₹1Cr FMR-1 (7d), ≥₹1L quarterly; compute deadlines; flag `rbi_reporting_required`; generate FMR-shaped reports.
- **DPDP Act 2023:** explicit **consent capture/withdrawal** model; **data-retention schedule**; **right-to-erasure** deletion workflow that respects the immutable audit trail (erase PII, retain audit references).
- **Model governance:** documented approval, versioning, drift monitoring, champion lineage.

---

## 16. Infrastructure & Deployment

- Containerize all services; Kubernetes/EKS; Terraform IaC. RDS (multi-AZ), MSK (Kafka), ElastiCache/Redis cluster, Neo4j cluster, MinIO→S3.
- Multi-AZ, autoscaling (HPA on queue depth + CPU), blue/green deploys, disaster recovery + backup/restore runbooks (RPO/RTO defined), DLQ + reconciliation for events.
- Separate worker pools for OCR (CPU) vs I/O tasks.

---

## 17. Observability

- Prometheus metrics + Grafana dashboards; Loki logs; OpenTelemetry traces (correlation_id end-to-end); AlertManager.
- **Business/fraud KPIs:** applications/day, fraud-detection rate, amount-at-risk prevented, analyst decision latency, SLA breaches.
- **ML metrics:** PR-AUC over time, prediction latency, drift flags, alert budget / top-K recall.
- **Pipeline health:** queue depth, task latency, failure/DLQ rate.

---

## 18. Non-Functional Requirements

- Scale: 100k+ applications/year; pipeline horizontally scalable via Celery workers.
- Every async task idempotent; exactly-once *effects* via dedup keys.
- p95 API latency < 300ms (excl. async analysis); warm ML inference < 50ms.
- Test coverage: unit tests for `fraud_engine` rules + extraction; integration tests for the pipeline; API contract tests; a QA checklist (genuine / fraud / missing-docs scenarios).

---

## 19. Build Order (phases — implement sequentially, ship each)

1. **Foundations:** FastAPI skeleton, async DB + Alembic, users/auth (JWT, roles), encryption + audit, config/secrets, health checks.
2. **Documents + OCR:** upload→MinIO, Celery `run_ocr_pipeline`, OCR service, document model + status.
3. **Extraction + single-doc fraud_engine:** entity extraction, deterministic rules, signals, risk assessment.
4. **Identity intelligence:** PAN/Aadhaar validators (Verhoeff), identity resolution, synthetic-identity.
5. **Cross-document + income:** salary↔bank reconciliation, completeness checklist.
6. **Property + financial intelligence.**
7. **Graph intelligence:** Neo4j/NetworkX, ring/mule/collateral detection.
8. **Events:** schemas, EventLog dual-write, Kafka producer, **consumers + reconciliation**, real-time risk engine.
9. **ML platform:** feature store, training, MLflow, governance, inference, SHAP, drift.
10. **Case management + alerting + operations + RBI compliance.**
11. **Frontend:** all pages, role-gated nav, real data.
12. **External verification framework:** adapter + circuit breaker + sandbox simulators; wire live per credential.
13. **Image anti-spoofing forensics** (screen/ELA/photocopy/signature).
14. **DPDP consent + data deletion; KMS/HSM; LLM copilot/RAG (optional, PII-safe).**
15. **Infra hardening, observability, DR, CI/CD (SAST/secret-scan/dependency-scan), k8s.**

---

## 20. Definition of Done (per feature)

- Service-class interface + context dataclass; no DB access inside rules.
- Idempotent Celery task (if async); emits a domain event; writes audit entries.
- Sensitive data encrypted + masked; zero PII in logs/events.
- Unit + integration tests; QA scenarios pass.
- Prometheus metrics + structured logs with correlation_id.
- Alembic migration; API documented in OpenAPI; frontend wired (if user-facing) and role-gated.
- Graceful degradation on external/dependency failure.

---

## 21. Guardrails (do NOT)

- Do **not** send PII or full document text to any external LLM.
- Do **not** let an LLM/ML model output a final risk score without the deterministic engine + SHAP.
- Do **not** hard-delete audit records; do **not** log raw PII.
- Do **not** use `scalar_one_or_none()` on checksum/duplicate lookups (multiple matches are expected).
- Do **not** ship demo/synthetic records in the production UI or DB.
- Do **not** go live with an external verification adapter unless `is_available()` + circuit breaker + sandbox parity tests pass.
- Do **not** start with microservices — build a bounded modular monolith + Celery; extract services later.

---

*End of specification. Build phase 1 first; do not proceed to a phase until the previous phase's Definition of Done is met.*
