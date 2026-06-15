"""Core fraud-engine types.

This package is intentionally **standalone**: it imports nothing from ``app.*`` so it can
be unit-tested (and reused) without the web app, DB, or any I/O. Rules receive a
pre-fetched ``RuleContext`` (no DB access inside rules) and return ``RuleResult`` objects.
Severities/signal-types are plain strings that match the app enum *values*; the task layer
maps them back to ORM enums when persisting.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Severity strings (match app.models.enums.SignalSeverity values).
LOW, MEDIUM, HIGH, CRITICAL = "LOW", "MEDIUM", "HIGH", "CRITICAL"


@dataclass
class RuleContext:
    """Everything a single-document rule needs, pre-fetched. No DB/network in rules."""

    document_id: str
    document_type: str
    ocr_confidence: float | None = None
    ocr_text: str = ""
    # entity_type (str) -> list of extracted values.
    entities: dict[str, list[str]] = field(default_factory=dict)
    # Set when this document's checksum already exists on another document.
    duplicate_of_document_id: str | None = None

    def values(self, entity_type: str) -> list[str]:
        return self.entities.get(entity_type, [])

    def first(self, entity_type: str) -> str | None:
        vals = self.entities.get(entity_type)
        return vals[0] if vals else None

    def amount(self, entity_type: str) -> float | None:
        raw = self.first(entity_type)
        if raw is None:
            return None
        try:
            return float(str(raw).replace(",", ""))
        except ValueError:
            return None


@dataclass
class RuleResult:
    signal_type: str
    severity: str
    description: str
    rule_name: str
    confidence: float = 0.9
    evidence: dict = field(default_factory=dict)
