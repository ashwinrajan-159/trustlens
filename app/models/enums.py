"""Centrally-defined enums shared across models, schemas and the fraud engine.

Phase 1 defines the foundation enums (roles, loan/application/document state).
Later phases extend this module (fraud signals, scopes, risk categories) — they
live here so there is one source of truth.
"""
from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    CUSTOMER = "CUSTOMER"
    ANALYST = "ANALYST"
    SENIOR_ANALYST = "SENIOR_ANALYST"
    ADMIN = "ADMIN"


# Roles that may act on the analyst side of the product.
ANALYST_ROLES = {UserRole.ANALYST, UserRole.SENIOR_ANALYST, UserRole.ADMIN}
SENIOR_ROLES = {UserRole.SENIOR_ANALYST, UserRole.ADMIN}


class LoanType(str, enum.Enum):
    HOME = "HOME"
    PERSONAL = "PERSONAL"
    BUSINESS = "BUSINESS"
    AUTO = "AUTO"


class ApplicationStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# Enforced state machine: status -> allowed next states.
APPLICATION_TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.DRAFT: {ApplicationStatus.SUBMITTED},
    ApplicationStatus.SUBMITTED: {ApplicationStatus.UNDER_REVIEW, ApplicationStatus.REJECTED},
    ApplicationStatus.UNDER_REVIEW: {ApplicationStatus.APPROVED, ApplicationStatus.REJECTED},
    ApplicationStatus.APPROVED: set(),
    ApplicationStatus.REJECTED: set(),
}


class RiskTier(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DocumentType(str, enum.Enum):
    # Identity
    AADHAAR = "AADHAAR"
    PAN = "PAN"
    PASSPORT = "PASSPORT"
    VOTER_ID = "VOTER_ID"
    DRIVING_LICENSE = "DRIVING_LICENSE"
    # Address
    UTILITY_BILL = "UTILITY_BILL"
    RENTAL_AGREEMENT = "RENTAL_AGREEMENT"
    # Income (salaried)
    SALARY_SLIP = "SALARY_SLIP"
    BANK_STATEMENT = "BANK_STATEMENT"
    FORM_16 = "FORM_16"
    # Income (self-employed)
    ITR = "ITR"
    PROFIT_LOSS = "PROFIT_LOSS"
    BALANCE_SHEET = "BALANCE_SHEET"
    GST_RETURN = "GST_RETURN"
    BUSINESS_PROOF = "BUSINESS_PROOF"
    # Property
    SALE_DEED = "SALE_DEED"
    TITLE_DEED = "TITLE_DEED"
    MOTHER_DEED = "MOTHER_DEED"
    ENCUMBRANCE_CERTIFICATE = "ENCUMBRANCE_CERTIFICATE"
    VALUATION_REPORT = "VALUATION_REPORT"
    APPROVED_PLAN = "APPROVED_PLAN"
    PROPERTY_TAX = "PROPERTY_TAX"
    OTHER = "OTHER"


class DocumentStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class AuditAction(str, enum.Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    READ_PII = "READ_PII"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    STATE_TRANSITION = "STATE_TRANSITION"
    DOWNLOAD = "DOWNLOAD"


class EntityType(str, enum.Enum):
    # Identity
    NAME = "NAME"
    PAN = "PAN"
    AADHAAR = "AADHAAR"
    DOB = "DOB"
    GENDER = "GENDER"
    ADDRESS = "ADDRESS"
    # Income / employment
    EMPLOYER = "EMPLOYER"
    DESIGNATION = "DESIGNATION"
    GROSS_SALARY = "GROSS_SALARY"
    NET_SALARY = "NET_SALARY"
    PAY_PERIOD = "PAY_PERIOD"
    # Banking
    ACCOUNT_NUMBER = "ACCOUNT_NUMBER"
    IFSC = "IFSC"
    BANK_NAME = "BANK_NAME"
    CLOSING_BALANCE = "CLOSING_BALANCE"
    # Business
    GSTIN = "GSTIN"
    CIN = "CIN"
    # Generic
    OTHER = "OTHER"


# Entities whose VALUE is PII: stored encrypted + only ever returned masked.
SENSITIVE_ENTITY_TYPES: set[EntityType] = {
    EntityType.PAN,
    EntityType.AADHAAR,
    EntityType.ACCOUNT_NUMBER,
    EntityType.DOB,
    EntityType.ADDRESS,
}


class ExtractionMethod(str, enum.Enum):
    REGEX = "REGEX"
    NER = "NER"
    LAYOUT = "LAYOUT"


class SignalSeverity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SignalScope(str, enum.Enum):
    DOCUMENT = "DOCUMENT"
    CROSS_DOCUMENT = "CROSS_DOCUMENT"
    IDENTITY = "IDENTITY"
    PROPERTY = "PROPERTY"
    FINANCIAL = "FINANCIAL"
    GRAPH = "GRAPH"


class RiskCategory(str, enum.Enum):
    INCOME = "INCOME"
    IDENTITY = "IDENTITY"
    DOCUMENT = "DOCUMENT"
    BEHAVIOR = "BEHAVIOR"


class FraudSignalType(str, enum.Enum):
    # Document integrity
    LOW_OCR_CONFIDENCE = "LOW_OCR_CONFIDENCE"
    EXTRACTION_FAILURE = "EXTRACTION_FAILURE"
    DUPLICATE_DOCUMENT = "DUPLICATE_DOCUMENT"
    # Identity
    INVALID_PAN_FORMAT = "INVALID_PAN_FORMAT"
    INVALID_AADHAAR_CHECKSUM = "INVALID_AADHAAR_CHECKSUM"
    INVALID_IFSC_FORMAT = "INVALID_IFSC_FORMAT"
    INVALID_GSTIN_FORMAT = "INVALID_GSTIN_FORMAT"
    # Income
    SALARY_EXTRACTION_FAILURE = "SALARY_EXTRACTION_FAILURE"
    ROUND_NUMBER_SALARY = "ROUND_NUMBER_SALARY"
    NET_EXCEEDS_GROSS = "NET_EXCEEDS_GROSS"
    # Identity (cross-document resolution — Phase 4)
    NAME_MISMATCH_ACROSS_DOCS = "NAME_MISMATCH_ACROSS_DOCS"
    PAN_MISMATCH_ACROSS_DOCS = "PAN_MISMATCH_ACROSS_DOCS"
    DOB_MISMATCH_ACROSS_DOCS = "DOB_MISMATCH_ACROSS_DOCS"
    POSSIBLE_SYNTHETIC_IDENTITY = "POSSIBLE_SYNTHETIC_IDENTITY"


# FraudSignalType → RiskCategory (drives weighted scoring by category).
SIGNAL_CATEGORY_MAP: dict[FraudSignalType, RiskCategory] = {
    FraudSignalType.LOW_OCR_CONFIDENCE: RiskCategory.DOCUMENT,
    FraudSignalType.EXTRACTION_FAILURE: RiskCategory.DOCUMENT,
    FraudSignalType.DUPLICATE_DOCUMENT: RiskCategory.DOCUMENT,
    FraudSignalType.INVALID_PAN_FORMAT: RiskCategory.IDENTITY,
    FraudSignalType.INVALID_AADHAAR_CHECKSUM: RiskCategory.IDENTITY,
    FraudSignalType.INVALID_IFSC_FORMAT: RiskCategory.IDENTITY,
    FraudSignalType.INVALID_GSTIN_FORMAT: RiskCategory.IDENTITY,
    FraudSignalType.SALARY_EXTRACTION_FAILURE: RiskCategory.INCOME,
    FraudSignalType.ROUND_NUMBER_SALARY: RiskCategory.INCOME,
    FraudSignalType.NET_EXCEEDS_GROSS: RiskCategory.INCOME,
    FraudSignalType.NAME_MISMATCH_ACROSS_DOCS: RiskCategory.IDENTITY,
    FraudSignalType.PAN_MISMATCH_ACROSS_DOCS: RiskCategory.IDENTITY,
    FraudSignalType.DOB_MISMATCH_ACROSS_DOCS: RiskCategory.IDENTITY,
    FraudSignalType.POSSIBLE_SYNTHETIC_IDENTITY: RiskCategory.IDENTITY,
}
