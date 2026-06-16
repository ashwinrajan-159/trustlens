"""ML platform schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MLLabelSource, MLModelStatus


class TrainRequest(BaseModel):
    name: str = "fraud_classifier"
    algorithm: str = Field("random_forest", pattern="^(random_forest|xgboost)$")


class MLModelPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    name: str
    version: int
    algorithm: str
    status: MLModelStatus
    metrics: dict | None
    feature_names: list | None
    training_samples: int
    is_champion: bool
    approved_by: str | None
    approved_at: datetime | None
    created_at: datetime


class MLPredictionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    application_id: str
    model_id: str
    fraud_probability: float
    risk_tier: str
    shap_top: list | None
    latency_ms: float
    created_at: datetime


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class LabelCreate(BaseModel):
    application_id: str
    label: int = Field(ge=0, le=1)
    source: MLLabelSource = MLLabelSource.ANALYST_FEEDBACK


class DriftResponse(BaseModel):
    drift_detected: bool
    recommendation: str
    drifted_features: list[str] = []
    per_feature_ks: dict = {}
    samples: int | None = None
