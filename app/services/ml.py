"""MLService — DB orchestration for the local ML platform (Phase 9).

Ties together feature snapshots, labels, training, governance and inference. Governance
is explicit: TRAINED → APPROVED (senior, gated on PR-AUC/FPR) → DEPLOYED (single champion).
Inference loads the cached champion and is advisory only — the deterministic engine remains
the system of record. A local MLflow run is logged when MLflow is installed (best-effort).
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import joblib
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.security import new_id
from app.models.application import Application
from app.models.document import Document
from app.models.enums import (
    SIGNAL_CATEGORY_MAP,
    DocumentStatus,
    FraudSignalType,
    MLLabelSource,
    MLModelStatus,
)
from app.models.fraud_signal import FraudSignal
from app.models.graph_analysis import GraphAnalysis
from app.models.identity_profile import IdentityProfile
from app.models.ml import MLFeatureSnapshot, MLLabel, MLModel, MLPrediction
from app.models.property_profile import PropertyProfile
from app.models.risk_assessment import RiskAssessment
from app.services import ml_features, ml_inference, ml_training

log = get_logger(__name__)

# Champion model cache: artifact_path -> loaded estimator (warm inference).
_MODEL_CACHE: dict[str, Any] = {}


def _load_model(artifact_path: str):
    if artifact_path not in _MODEL_CACHE:
        _MODEL_CACHE[artifact_path] = joblib.load(artifact_path)
    return _MODEL_CACHE[artifact_path]


def reset_model_cache() -> None:
    _MODEL_CACHE.clear()


class MLService:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Features ──
    async def _feature_inputs(self, application_id: str) -> ml_features.FeatureInputs:
        signals = (
            await self.session.execute(
                select(FraudSignal).where(
                    FraudSignal.application_id == application_id,
                    FraudSignal.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        sev: dict[str, int] = {}
        cat: dict[str, int] = {}
        for s in signals:
            sev[s.severity.value] = sev.get(s.severity.value, 0) + 1
            category = SIGNAL_CATEGORY_MAP.get(FraudSignalType(s.signal_type.value))
            if category:
                cat[category.value] = cat.get(category.value, 0) + 1

        risk = (
            await self.session.execute(
                select(RiskAssessment)
                .where(RiskAssessment.application_id == application_id, RiskAssessment.deleted_at.is_(None))
                .order_by(RiskAssessment.created_at.desc()).limit(1)
            )
        ).scalars().first()
        graph = (
            await self.session.execute(
                select(GraphAnalysis)
                .where(GraphAnalysis.application_id == application_id, GraphAnalysis.deleted_at.is_(None))
                .order_by(GraphAnalysis.created_at.desc()).limit(1)
            )
        ).scalars().first()
        identity = (
            await self.session.execute(
                select(IdentityProfile)
                .where(IdentityProfile.application_id == application_id, IdentityProfile.deleted_at.is_(None))
                .order_by(IdentityProfile.created_at.desc()).limit(1)
            )
        ).scalars().first()
        prop = (
            await self.session.execute(
                select(PropertyProfile)
                .where(PropertyProfile.application_id == application_id, PropertyProfile.deleted_at.is_(None))
                .order_by(PropertyProfile.created_at.desc()).limit(1)
            )
        ).scalars().first()

        docs = (
            await self.session.execute(
                select(Document).where(
                    Document.application_id == application_id,
                    Document.deleted_at.is_(None),
                    Document.is_current_version.is_(True),
                    Document.status == DocumentStatus.PROCESSED,
                )
            )
        ).scalars().all()
        present = {d.document_type.value for d in docs}
        app = (
            await self.session.execute(select(Application).where(Application.id == application_id))
        ).scalar_one_or_none()
        missing_critical = 0
        if app:
            from app.services.cross_document import compute_completeness

            missing_critical = len(compute_completeness(app.loan_type.value, present)[0])

        return ml_features.FeatureInputs(
            severity_counts=sev,
            category_counts=cat,
            deterministic_risk_score=risk.total_score if risk else 0.0,
            graph_connections=graph.fraud_connections_count if graph else 0,
            graph_ring_size=graph.ring_size if graph else 0,
            graph_in_ring=graph.in_fraud_ring if graph else False,
            shared_pan=graph.shared_pan_count if graph else 0,
            shared_account=graph.shared_account_count if graph else 0,
            shared_property=graph.shared_property_count if graph else 0,
            identity_synthetic=identity.is_synthetic_suspected if identity else False,
            distinct_pan=identity.distinct_pan_count if identity else 0,
            property_inflated=prop.is_inflated if prop else False,
            valuation_ratio=(prop.valuation_ratio or 0.0) if prop else 0.0,
            missing_critical_docs=missing_critical,
            document_count=len(docs),
        )

    async def snapshot_features(self, application_id: str) -> MLFeatureSnapshot:
        feats = ml_features.build_features(await self._feature_inputs(application_id))
        snap = MLFeatureSnapshot(
            application_id=application_id, features=feats,
            feature_version=ml_features.FEATURE_VERSION,
        )
        self.session.add(snap)
        await self.session.commit()
        return snap

    async def record_label(
        self, application_id: str, label: int, *, source: MLLabelSource, created_by: str | None = None
    ) -> MLLabel:
        row = MLLabel(application_id=application_id, label=int(bool(label)), source=source, created_by=created_by)
        self.session.add(row)
        await self.session.commit()
        return row

    # ── Training ──
    async def _latest_snapshot_map(self) -> dict[str, dict]:
        rows = (
            await self.session.execute(
                select(MLFeatureSnapshot)
                .where(MLFeatureSnapshot.deleted_at.is_(None))
                .order_by(MLFeatureSnapshot.created_at.asc())
            )
        ).scalars().all()
        latest: dict[str, dict] = {}
        for r in rows:
            latest[r.application_id] = r.features  # asc order → last wins = latest
        return latest

    async def _latest_label_map(self) -> dict[str, int]:
        rows = (
            await self.session.execute(
                select(MLLabel).where(MLLabel.deleted_at.is_(None)).order_by(MLLabel.created_at.asc())
            )
        ).scalars().all()
        latest: dict[str, int] = {}
        for r in rows:
            latest[r.application_id] = r.label
        return latest

    async def train(self, *, name: str = "fraud_classifier", algorithm: str = "random_forest") -> MLModel:
        snaps = await self._latest_snapshot_map()
        labels = await self._latest_label_map()
        app_ids = [a for a in snaps if a in labels]
        X = [ml_features.to_vector(snaps[a]) for a in app_ids]
        y = [labels[a] for a in app_ids]

        cfg = ml_training.TrainConfig(
            algorithm=algorithm,
            min_samples=settings.ml_min_samples,
            min_fraud_rate=settings.ml_min_fraud_rate,
        )
        result = ml_training.train(X, y, config=cfg)

        version = ((await self.session.execute(
            select(func.coalesce(func.max(MLModel.version), 0)).where(MLModel.name == name)
        )).scalar_one()) + 1

        if not result.ok:
            model = MLModel(
                name=name, version=version, algorithm=algorithm,
                status=MLModelStatus.REJECTED, training_samples=result.n_samples,
                notes=f"training refused: {result.reason}",
            )
            self.session.add(model)
            await self.session.commit()
            raise ValidationError(f"Training refused: {result.reason}")

        os.makedirs(settings.ml_artifacts_dir, exist_ok=True)
        artifact_path = os.path.join(settings.ml_artifacts_dir, f"{name}_v{version}.joblib")
        joblib.dump(result.model, artifact_path)
        _MODEL_CACHE[artifact_path] = result.model
        self._log_mlflow(name, version, result)

        model = MLModel(
            name=name, version=version, algorithm=result.algorithm,
            status=MLModelStatus.TRAINED, metrics=result.metrics,
            feature_names=ml_features.FEATURE_NAMES, artifact_path=artifact_path,
            training_samples=result.n_samples,
        )
        self.session.add(model)
        await self.session.commit()
        log.info("ml.trained", model=name, version=version, metrics=result.metrics)
        return model

    @staticmethod
    def _log_mlflow(name: str, version: int, result: ml_training.TrainResult) -> None:
        try:  # pragma: no cover - MLflow optional, local file store
            import mlflow

            mlflow.set_experiment("trustlens-fraud")
            with mlflow.start_run(run_name=f"{name}_v{version}"):
                mlflow.log_param("algorithm", result.algorithm)
                mlflow.log_params({"n_samples": result.n_samples})
                mlflow.log_metrics({k: v for k, v in result.metrics.items() if isinstance(v, int | float)})
        except Exception:  # noqa: BLE001 - never let telemetry break training
            pass

    # ── Governance ──
    async def _get_model(self, model_id: str) -> MLModel:
        model = (await self.session.execute(select(MLModel).where(MLModel.id == model_id))).scalar_one_or_none()
        if not model:
            raise NotFoundError("Model not found")
        return model

    async def approve(self, model_id: str, *, approver: str) -> MLModel:
        model = await self._get_model(model_id)
        if model.status not in {MLModelStatus.TRAINED, MLModelStatus.EVALUATING}:
            raise ConflictError(f"Model in {model.status.value} cannot be approved")
        m = model.metrics or {}
        pr_auc = m.get("pr_auc")
        fpr = m.get("fpr", 1.0)
        if pr_auc is None or pr_auc < settings.ml_approval_min_pr_auc:
            raise ValidationError(f"PR-AUC {pr_auc} below approval gate {settings.ml_approval_min_pr_auc}")
        if fpr > settings.ml_approval_max_fpr:
            raise ValidationError(f"FPR {fpr} above approval gate {settings.ml_approval_max_fpr}")
        model.status = MLModelStatus.APPROVED
        model.approved_by = approver
        model.approved_at = datetime.now(UTC)
        await self.session.commit()
        log.info("ml.approved", model_id=model_id, approver=approver)
        return model

    async def reject(self, model_id: str, *, approver: str, reason: str) -> MLModel:
        model = await self._get_model(model_id)
        model.status = MLModelStatus.REJECTED
        model.notes = reason
        model.approved_by = approver
        await self.session.commit()
        return model

    async def promote(self, model_id: str) -> MLModel:
        """Deploy as the single champion (demote any current champion)."""
        model = await self._get_model(model_id)
        if model.status != MLModelStatus.APPROVED:
            raise ConflictError("Only an APPROVED model can be promoted to champion")
        for current in (
            await self.session.execute(select(MLModel).where(MLModel.is_champion.is_(True)))
        ).scalars().all():
            current.is_champion = False
            current.status = MLModelStatus.ARCHIVED
        model.is_champion = True
        model.status = MLModelStatus.DEPLOYED
        await self.session.commit()
        log.info("ml.promoted", model_id=model_id, version=model.version)
        return model

    async def _champion(self) -> MLModel | None:
        return (
            await self.session.execute(
                select(MLModel).where(MLModel.is_champion.is_(True), MLModel.deleted_at.is_(None)).limit(1)
            )
        ).scalars().first()

    # ── Inference ──
    async def predict(self, application_id: str) -> MLPrediction:
        champion = await self._champion()
        if not champion or not champion.artifact_path:
            raise ConflictError("No deployed champion model available")
        feats = ml_features.build_features(await self._feature_inputs(application_id))
        names = champion.feature_names or ml_features.FEATURE_NAMES
        vector = ml_features.to_vector(feats, names)
        model = _load_model(champion.artifact_path)
        out = ml_inference.predict(model, vector, names)

        pred = MLPrediction(
            application_id=application_id, model_id=champion.id,
            fraud_probability=out.fraud_probability, risk_tier=out.risk_tier,
            shap_top=out.shap_top, latency_ms=out.latency_ms,
        )
        self.session.add(pred)
        # Emit MODEL_PREDICTION_GENERATED (outbox).
        from app.events import schemas as ev
        from app.events.service import publish_pending, stage

        stage(self.session, ev.model_prediction_generated(
            new_id(), application_id,
            probability=out.fraud_probability, tier=out.risk_tier, model_id=champion.id))
        await self.session.commit()
        try:
            await publish_pending(self.session)
        except Exception as exc:  # noqa: BLE001
            log.warning("events.relay_failed", error=str(exc))
        return pred

    # ── Drift ──
    async def drift(self) -> dict:
        """KS-test drift: first half of snapshots (reference) vs recent half."""
        rows = (
            await self.session.execute(
                select(MLFeatureSnapshot)
                .where(MLFeatureSnapshot.deleted_at.is_(None))
                .order_by(MLFeatureSnapshot.created_at.asc())
            )
        ).scalars().all()
        if len(rows) < 10:
            return {"drift_detected": False, "recommendation": "insufficient_data", "samples": len(rows)}
        vectors = [ml_features.to_vector(r.features) for r in rows]
        mid = len(vectors) // 2
        return ml_inference.ks_drift(vectors[:mid], vectors[mid:], ml_features.FEATURE_NAMES)
