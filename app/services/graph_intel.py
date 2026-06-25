"""Graph intelligence (Phase 7) — entity-relationship graph + network fraud detection.

Pure analytics over a NetworkX graph (the in-memory engine; a Neo4j cluster is the
production persistence target — same node/edge model). Nodes are applications and the
attributes they share (PAN, Aadhaar, bank account, property survey number, GSTIN, person
name); an edge links an application to each of its attributes. Two applications are
"connected" when they share an attribute node (a 2-hop path).

Detects: shared-PAN across applications, mule-account reuse, duplicate-collateral
networks, high-centrality hub attributes, and fraud rings (connected components over the
*strong* identity/financial/collateral attributes — person-name links are treated as weak
to avoid false positives on common names).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import networkx as nx

from app.core.encryption import mask_aadhaar, mask_account, mask_pan
from app.fraud_engine.result import CRITICAL, HIGH, MEDIUM, RuleResult

# Attribute kinds that meaningfully link applications (names are weak → excluded from rings).
STRONG_KINDS = {"PAN", "AADHAAR", "ACCOUNT", "PROPERTY", "GSTIN"}
HUB_DEGREE_THRESHOLD = 3   # an attribute shared by ≥3 applications is a hub
RING_MIN_APPS = 3          # ≥3 applications in one strong-attribute component = ring


@dataclass
class AppRecord:
    application_id: str
    names: list[str] = field(default_factory=list)
    pans: list[str] = field(default_factory=list)
    aadhaars: list[str] = field(default_factory=list)
    accounts: list[str] = field(default_factory=list)
    surveys: list[str] = field(default_factory=list)
    gstins: list[str] = field(default_factory=list)


@dataclass
class GraphSummary:
    graph_risk_score: float = 0.0
    fraud_connections_count: int = 0
    shared_pan_count: int = 0
    shared_account_count: int = 0
    shared_property_count: int = 0
    ring_size: int = 0
    in_fraud_ring: bool = False
    connected_application_ids: list[str] = field(default_factory=list)


def _norm(v: str) -> str:
    return v.strip().upper()


def build_graph(records: list[AppRecord]) -> nx.Graph:
    g = nx.Graph()
    for rec in records:
        app_node = ("APP", rec.application_id)
        g.add_node(app_node, kind="APP", application_id=rec.application_id)
        for kind, values in (
            ("PAN", rec.pans),
            ("AADHAAR", rec.aadhaars),
            ("ACCOUNT", rec.accounts),
            ("PROPERTY", rec.surveys),
            ("GSTIN", rec.gstins),
            ("PERSON", rec.names),
        ):
            for raw in values:
                if not raw or not raw.strip():
                    continue
                attr_node = (kind, _norm(raw))
                g.add_node(attr_node, kind=kind)
                g.add_edge(app_node, attr_node)
    return g


def _other_apps(g: nx.Graph, attr_node) -> list[str]:
    return [n[1] for n in g.neighbors(attr_node) if n[0] == "APP"]


def analyze(g: nx.Graph, application_id: str) -> tuple[GraphSummary, list[RuleResult]]:
    app_node = ("APP", application_id)
    if app_node not in g:
        return GraphSummary(), []

    shared_by_kind: dict[str, set[str]] = {}
    hub_attributes: list[tuple[str, int]] = []
    for attr in g.neighbors(app_node):
        kind = attr[0]
        others = [a for a in _other_apps(g, attr) if a != application_id]
        if others:
            shared_by_kind.setdefault(kind, set()).update(others)
        degree_apps = len(_other_apps(g, attr))
        if degree_apps >= HUB_DEGREE_THRESHOLD:
            hub_attributes.append((kind, degree_apps))

    connected = set()
    for kind in STRONG_KINDS:
        connected |= shared_by_kind.get(kind, set())

    # Fraud ring: connected component over APP + strong-attribute nodes only.
    strong_nodes = [
        n for n in g.nodes
        if n[0] == "APP" or n[0] in STRONG_KINDS
    ]
    strong = g.subgraph(strong_nodes)
    ring_apps: list[str] = []
    if app_node in strong:
        comp = nx.node_connected_component(strong, app_node)
        ring_apps = sorted(n[1] for n in comp if n[0] == "APP")
    ring_size = len(ring_apps)
    in_ring = ring_size >= RING_MIN_APPS

    signals: list[RuleResult] = []
    shared_pan = len(shared_by_kind.get("PAN", set()))
    shared_acct = len(shared_by_kind.get("ACCOUNT", set()))
    shared_prop = len(shared_by_kind.get("PROPERTY", set()))

    if shared_pan:
        signals.append(RuleResult(
            "SHARED_PAN_MULTIPLE_APPLICATIONS", HIGH,
            f"PAN is shared with {shared_pan} other application(s)",
            "graph_shared_pan", 0.9, {"shared_with": sorted(shared_by_kind['PAN'])},
        ))
    if shared_acct:
        signals.append(RuleResult(
            "MULE_ACCOUNT_REUSE", HIGH,
            f"Bank account is reused across {shared_acct} other application(s) — mule indicator",
            "graph_mule_account", 0.85, {"shared_with": sorted(shared_by_kind['ACCOUNT'])},
        ))
    if shared_prop:
        signals.append(RuleResult(
            "DUPLICATE_COLLATERAL_NETWORK", CRITICAL,
            f"Collateral (survey number) appears on {shared_prop} other application(s)",
            "graph_duplicate_collateral", 0.9, {"shared_with": sorted(shared_by_kind['PROPERTY'])},
        ))
    for kind, deg in hub_attributes:
        signals.append(RuleResult(
            "HIGH_CENTRALITY_HUB", MEDIUM,
            f"A shared {kind} attribute links {deg} applications (high-centrality hub)",
            "graph_high_centrality", 0.7, {"kind": kind, "degree": deg},
        ))
    if in_ring:
        sev = CRITICAL if ring_size >= 4 else HIGH
        signals.append(RuleResult(
            "FRAUD_RING_DETECTED", sev,
            f"Application belongs to a network of {ring_size} applications sharing identity/collateral",
            "graph_fraud_ring", 0.8, {"ring_size": ring_size, "applications": ring_apps},
        ))

    score = min(100.0, shared_pan * 30 + shared_acct * 30 + shared_prop * 50
                + len(hub_attributes) * 15 + (20 if in_ring else 0))
    summary = GraphSummary(
        graph_risk_score=float(score),
        fraud_connections_count=len(connected),
        shared_pan_count=shared_pan,
        shared_account_count=shared_acct,
        shared_property_count=shared_prop,
        ring_size=ring_size,
        in_fraud_ring=in_ring,
        connected_application_ids=sorted(connected),
    )
    return summary, signals


_LABELERS = {
    "PAN": mask_pan,
    "AADHAAR": mask_aadhaar,
    "ACCOUNT": mask_account,
}


def _label(kind: str, value: str) -> str:
    """Masked, display-safe label for an attribute node (no raw PII in the network view)."""
    if kind in _LABELERS:
        return _LABELERS[kind](value) or kind
    if kind == "PERSON":
        toks = value.split()
        return (toks[0] + " *") if toks else "Person"
    return value  # PROPERTY / GSTIN are not PII


def _node_id(node) -> str:
    """Stable, PII-free node id. APP uses its (non-PII) UUID; attribute values are
    hashed so the raw PAN/account/etc. never appears in the network payload."""
    kind, value = node
    if kind == "APP":
        return f"APP:{value}"
    digest = hashlib.sha256(value.encode()).hexdigest()[:12]
    return f"{kind}:{digest}"


def ego_network(g: nx.Graph, application_id: str, *, radius: int = 2) -> dict:
    """Nodes + edges around an application for the analyst UI (PII masked + ids hashed)."""
    app_node = ("APP", application_id)
    if app_node not in g:
        return {"nodes": [], "edges": []}
    ego = nx.ego_graph(g, app_node, radius=radius)
    nodes = [
        {
            "id": _node_id(n),
            "kind": n[0],
            "label": n[1] if n[0] == "APP" else _label(n[0], n[1]),
        }
        for n in ego.nodes
    ]
    edges = [{"source": _node_id(u), "target": _node_id(v)} for u, v in ego.edges]
    return {"nodes": nodes, "edges": edges}
