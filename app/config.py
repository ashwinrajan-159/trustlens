"""Application configuration via pydantic-settings.

All values are read from the environment (or a local ``.env`` file in dev).
Secrets are never hardcoded; in production these come from a secrets manager.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Sentinel default — if this ever reaches production we must fail fast.
_DEFAULT_JWT_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── App ──
    app_name: str = "TrustLens AI"
    environment: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # ── Database ──
    database_url: str = (
        "postgresql+asyncpg://trustlens:trustlens@localhost:5432/trustlens"
    )
    db_echo: bool = False

    # ── Security ──
    jwt_secret_key: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Rate limiting (slowapi). Disabled under tests so the suite isn't throttled.
    rate_limit_enabled: bool = True
    rate_limit_auth: str = "10/minute"
    rate_limit_login: str = "5/minute"

    # Trusted reverse-proxy CIDRs/IPs — only these may set X-Forwarded-For.
    trusted_proxies: list[str] = Field(default_factory=list)

    # Max request body (bytes) rejected at the edge before routing.
    max_request_body_bytes: int = 26_214_400  # 25 MB

    # ── Field-level PII encryption ──
    # Primary key + optional comma-separated older keys for MultiFernet rotation.
    fernet_key: str = ""
    fernet_old_keys: list[str] = Field(default_factory=list)

    # ── DPDP / data retention ──
    pii_retention_days: int = 2555  # ~7 years; tune per RBI/DPDP policy

    # ── ML platform (Phase 9) — all local ──
    ml_artifacts_dir: str = "ml_artifacts"
    ml_min_samples: int = 20          # refuse to train below this
    ml_min_fraud_rate: float = 0.10   # refuse if fraud prevalence too low
    ml_approval_min_pr_auc: float = 0.70   # governance gate to APPROVE
    ml_approval_max_fpr: float = 0.30      # governance gate to APPROVE

    # ── Object storage ──
    storage_endpoint_url: str = "http://localhost:9000"
    storage_access_key: str = "minioadmin"
    storage_secret_key: str = "minioadmin"
    storage_bucket: str = "trustlens-documents"
    storage_region: str = "us-east-1"
    presigned_url_ttl_seconds: int = 900

    # ── Events / streaming ──
    # "memory" (dev/test, in-process bus) or "kafka" (prod). Kafka runs locally too.
    events_backend: str = "memory"
    kafka_bootstrap_servers: str = "localhost:9092"

    # ── Redis / Celery ──
    # Refresh-token rotation store. False -> in-memory (dev/test); True -> Redis (prod).
    use_redis_token_store: bool = False
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── CORS ──
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @field_validator(
        "cors_origins", "trusted_proxies", "fernet_old_keys", mode="before"
    )
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def is_test(self) -> bool:
        return self.environment.lower() == "test"

    @model_validator(mode="after")
    def _enforce_production_secrets(self) -> Settings:
        """Fail fast: never boot production with default/empty secrets (#1)."""
        if self.is_production:
            problems: list[str] = []
            if self.jwt_secret_key == _DEFAULT_JWT_SECRET or len(self.jwt_secret_key) < 32:
                problems.append("JWT_SECRET_KEY must be set to a strong (>=32 char) value")
            if not self.fernet_key:
                problems.append("FERNET_KEY must be set (KMS/HSM in prod)")
            if "*" in self.cors_origins:
                problems.append("CORS_ORIGINS must not be '*' in production")
            if problems:
                raise ValueError(
                    "Insecure production configuration: " + "; ".join(problems)
                )
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()
