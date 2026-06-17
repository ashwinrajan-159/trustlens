"""ORM models. Importing this package registers every model on ``Base.metadata``
(needed for Alembic autogenerate and ``create_all`` in tests)."""
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.business_profile import BusinessProfile
from app.models.document import Document
from app.models.event_log import EventLog
from app.models.extracted_entity import ExtractedEntity
from app.models.fraud_alert import FraudAlert
from app.models.fraud_signal import FraudSignal
from app.models.graph_analysis import GraphAnalysis
from app.models.identity_profile import IdentityProfile
from app.models.investigation_case import InvestigationCase
from app.models.ml import MLFeatureSnapshot, MLLabel, MLModel, MLPrediction
from app.models.ocr_result import OcrResult
from app.models.property_profile import PropertyProfile
from app.models.risk_assessment import RiskAssessment
from app.models.user import User

__all__ = [
    "Base",
    "User",
    "Application",
    "Document",
    "AuditLog",
    "OcrResult",
    "ExtractedEntity",
    "FraudSignal",
    "RiskAssessment",
    "IdentityProfile",
    "PropertyProfile",
    "BusinessProfile",
    "GraphAnalysis",
    "EventLog",
    "MLFeatureSnapshot",
    "MLLabel",
    "MLModel",
    "MLPrediction",
    "FraudAlert",
    "InvestigationCase",
]
