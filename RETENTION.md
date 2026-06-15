# Data Retention & DPDP Compliance

TrustLens processes sensitive personal data (PII) and financial documents under India's
**DPDP Act 2023** and **RBI** frameworks. This document records the consent model, the
retention schedule, and the erasure workflow. It is policy-as-documentation today; the
automated jobs land with Phase 14 (DPDP + data deletion).

## Consent model

- **Capture:** `users.data_consent_given_at` is set at registration (the API requires an
  explicit `data_consent_given` flag). No processing without recorded consent.
- **Withdrawal:** `POST /api/v1/auth/consent/withdraw` sets `users.data_consent_withdrawn_at`
  and writes an audit entry. Withdrawal triggers the erasure workflow below.

## Retention schedule

| Data class | Store | Retention | Basis |
|---|---|---|---|
| Identity PII (PAN, Aadhaar last-4, account no.) | Postgres (encrypted) | `PII_RETENTION_DAYS` (default ~7 yrs) | RBI KYC record-keeping |
| Uploaded documents | MinIO/S3 (encrypted) | Same as PII | RBI / underwriting evidence |
| Risk assessments & fraud signals | Postgres | 7 yrs | Audit / dispute resolution |
| **Audit logs** | Postgres (WORM) | **Never deleted** | Immutable regulatory trail |
| Application metadata | Postgres | 7 yrs after decision | RBI |
| Refresh-token state | Redis | Token TTL (≤7 days) | Operational |

`PII_RETENTION_DAYS` is configurable; tune to the controlling RBI/DPDP policy at deployment.

## Right to erasure (Phase 14 workflow)

Erasure must respect the immutable audit trail — we erase the *data*, not the *evidence
that it existed*:

1. Verify identity + the erasure request (or honour a consent withdrawal).
2. **Soft-delete** the user and their applications (`deleted_at`), revoke all token families.
3. **Crypto-shred** PII: null out encrypted PII columns and delete the object-storage
   documents. Because PII is field-encrypted, discarding/rotating the key for those records
   renders any residual ciphertext unrecoverable.
4. **Preserve** `audit_logs` rows — they reference only IDs and redacted snapshots, never raw
   PII, so they remain compliant while proving the lifecycle (including the erasure itself,
   which is also audited).
5. Emit a `DataErased` event (IDs only) and produce an erasure certificate.

## Notes

- Audit logs are append-only and enforced at the database level (WORM trigger, migration
  `002`), plus a tamper-evidence hash chain — they are intentionally **out of scope** for
  deletion.
- No raw PII or full document text is ever written to logs or events (IDs + correlation_id
  only).
