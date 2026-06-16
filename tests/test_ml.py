"""ML platform: feature builder, training gates/metrics, inference, governance, endpoints."""
import pytest
from sqlalchemy import select

from app.models.application import Application
from app.models.enums import LoanType, MLLabelSource, MLModelStatus, UserRole
from app.models.ml import MLFeatureSnapshot, MLLabel, MLPrediction
from app.models.user import User
from app.services import ml_features, ml_inference, ml_training
from app.services.ml import MLService
from tests.conftest import _SessionFactory

# ── Pure feature builder ──

def test_build_features_has_full_schema():
    feats = ml_features.build_features(ml_features.FeatureInputs(
        severity_counts={"CRITICAL": 2, "HIGH": 1}, category_counts={"IDENTITY": 1},
        deterministic_risk_score=75, graph_in_ring=True,
    ))
    assert set(feats) == set(ml_features.FEATURE_NAMES)
    assert feats["signal_critical"] == 2.0
    assert feats["signal_total"] == 3.0
    assert feats["graph_in_ring"] == 1.0
    vec = ml_features.to_vector(feats)
    assert len(vec) == len(ml_features.FEATURE_NAMES)


# ── Pure training gates + metrics ──

def _separable(n=40):
    X, y = [], []
    for i in range(n):
        fraud = i % 2
        X.append([90.0, 3.0] if fraud else [5.0, 0.0])
        y.append(fraud)
    return X, y


def test_training_refuses_insufficient_samples():
    r = ml_training.train([[1.0], [2.0]], [0, 1], config=ml_training.TrainConfig(min_samples=20))
    assert not r.ok and "insufficient_samples" in r.reason


def test_training_refuses_single_class():
    X = [[1.0]] * 30
    r = ml_training.train(X, [0] * 30, config=ml_training.TrainConfig(min_samples=10))
    assert not r.ok and "single_class" in r.reason


def test_training_produces_metrics():
    X, y = _separable()
    r = ml_training.train(X, y, config=ml_training.TrainConfig(min_samples=10))
    assert r.ok
    assert r.metrics["pr_auc"] is not None
    assert 0.0 <= r.metrics["fpr"] <= 1.0
    assert "fdr_at_10" in r.metrics


def test_inference_predicts_and_tiers():
    X, y = _separable()
    r = ml_training.train(X, y, config=ml_training.TrainConfig(min_samples=10))
    out = ml_inference.predict(r.model, [90.0, 3.0], ["f0", "f1"])
    assert 0.0 <= out.fraud_probability <= 1.0
    assert out.risk_tier in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert out.shap_top  # feature contributions present


def test_proba_to_tier_bands():
    assert ml_inference.proba_to_tier(0.1) == "LOW"
    assert ml_inference.proba_to_tier(0.85) == "CRITICAL"


# ── Integration: train → approve → promote → predict (DB) ──

async def _seed(n=30):
    """Seed N applications with separable feature snapshots + labels (50% fraud)."""
    async with _SessionFactory() as s:
        user = User(email="seed@example.com", hashed_password="x", full_name="Seed", role=UserRole.CUSTOMER)
        s.add(user)
        await s.flush()
        app_ids = []
        for i in range(n):
            fraud = i % 2
            app = Application(
                application_number=f"TL-SEED-{i:03d}", applicant_id=user.id,
                loan_type=LoanType.HOME, loan_amount_requested=1000000,
            )
            s.add(app)
            await s.flush()
            feats = ml_features.build_features(ml_features.FeatureInputs(
                severity_counts={"CRITICAL": 4} if fraud else {},
                category_counts={"IDENTITY": 3} if fraud else {},
                deterministic_risk_score=92 if fraud else 5,
                identity_synthetic=bool(fraud), graph_in_ring=bool(fraud),
            ))
            s.add(MLFeatureSnapshot(application_id=app.id, features=feats, feature_version=1))
            s.add(MLLabel(application_id=app.id, label=fraud, source=MLLabelSource.ANALYST_DECISION))
            app_ids.append(app.id)
        await s.commit()
        return app_ids


@pytest.mark.asyncio
async def test_full_ml_lifecycle(client):  # client fixture ensures DB schema is set up
    app_ids = await _seed()

    async with _SessionFactory() as s:
        model = await MLService(s).train()
    assert model.status == MLModelStatus.TRAINED
    assert model.training_samples == 30
    assert model.metrics["pr_auc"] is not None

    # Governance: approve (gated) then promote to single champion.
    async with _SessionFactory() as s:
        approved = await MLService(s).approve(model.id, approver="senior-1")
        assert approved.status == MLModelStatus.APPROVED
    async with _SessionFactory() as s:
        champ = await MLService(s).promote(model.id)
        assert champ.status == MLModelStatus.DEPLOYED and champ.is_champion is True

    # Inference on a seeded application persists a prediction + emits an event.
    async with _SessionFactory() as s:
        pred = await MLService(s).predict(app_ids[1])  # a fraud-shaped app
    assert 0.0 <= pred.fraud_probability <= 1.0
    assert pred.risk_tier in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

    async with _SessionFactory() as s:
        stored = (await s.execute(select(MLPrediction).where(MLPrediction.application_id == app_ids[1]))).scalars().all()
    assert len(stored) == 1


@pytest.mark.asyncio
async def test_training_refused_endpoint_and_rbac(client):
    # Customer cannot train.
    reg = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": "mlcust@example.com", "password": "supersecret1", "full_name": "C"},
        )
    ).json()
    ch = {"Authorization": f"Bearer {reg['tokens']['access_token']}"}
    assert (await client.post("/api/v1/ml/train", json={}, headers=ch)).status_code == 403

    # Senior analyst can; with no data, training is refused with a 422 (gate), not a 500.
    await client.post(
        "/api/v1/auth/register",
        json={"email": "mlsenior@example.com", "password": "supersecret1", "full_name": "S"},
    )
    async with _SessionFactory() as s:
        u = (await s.execute(select(User).where(User.email == "mlsenior@example.com"))).scalar_one()
        u.role = UserRole.SENIOR_ANALYST
        await s.commit()
    login = (
        await client.post(
            "/api/v1/auth/login", json={"email": "mlsenior@example.com", "password": "supersecret1"}
        )
    ).json()
    sh = {"Authorization": f"Bearer {login['access_token']}"}
    r = await client.post("/api/v1/ml/train", json={}, headers=sh)
    assert r.status_code == 422  # insufficient samples gate
    assert (await client.get("/api/v1/ml/models", headers=sh)).status_code == 200


@pytest.mark.asyncio
async def test_predict_without_champion_conflicts(client):
    from app.core.exceptions import ConflictError

    app_ids = await _seed(n=2)
    async with _SessionFactory() as s:
        with pytest.raises(ConflictError):  # no deployed champion
            await MLService(s).predict(app_ids[0])
