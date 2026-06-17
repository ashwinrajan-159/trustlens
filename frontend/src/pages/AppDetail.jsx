import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Download, Network as NetworkIcon } from "lucide-react";
import { api } from "../api/endpoints";
import { useAsync } from "../lib/useAsync";
import { useAuth } from "../auth/AuthContext";
import { Badge, Card, EmptyState, ErrorBanner, Spinner, Tabs, Button, StatCard } from "../components/ui";
import { inr, dt, tierStyle, sevStyle, statusStyle } from "../lib/format";

function RiskPanel({ id }) {
  const { data: risk, loading } = useAsync(() => api.risk(id), [id]);
  const { data: comp } = useAsync(() => api.completeness(id), [id]);
  if (loading) return <Spinner />;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Risk score" value={risk ? risk.total_score : "—"} />
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="text-xs uppercase tracking-wide text-slate-400">Risk tier</div>
          <div className="mt-2">{risk ? <Badge className={tierStyle(risk.risk_tier)}>{risk.risk_tier}</Badge> : "—"}</div>
        </div>
        <StatCard label="Documents complete" value={comp ? (comp.is_complete ? "Yes" : "No") : "—"}
          sub={comp && comp.missing_critical?.length ? `Missing: ${comp.missing_critical.join(", ")}` : undefined} />
      </div>
      <Card title="Score breakdown (explainable)">
        {risk?.reasons?.length ? (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-400"><tr><th className="py-1">Rule</th><th>Signal</th><th>Category</th><th>Severity</th><th>Weight</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {risk.reasons.map((r, i) => (
                <tr key={i}>
                  <td className="py-1 text-slate-600">{r.rule_name}</td>
                  <td className="text-xs text-slate-500">{r.signal_type}</td>
                  <td className="text-xs">{r.category}</td>
                  <td><Badge className={sevStyle(r.severity)}>{r.severity}</Badge></td>
                  <td>{r.weight}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <EmptyState message="No risk assessment yet (pipeline may still be running)." />}
      </Card>
    </div>
  );
}

function SignalsPanel({ id }) {
  const { data, loading } = useAsync(() => api.signals(id), [id]);
  if (loading) return <Spinner />;
  if (!data?.length) return <EmptyState message="No fraud signals." />;
  return (
    <div className="space-y-2">
      {data.map((s) => (
        <div key={s.id} className="rounded-lg border border-slate-200 bg-white p-3">
          <div className="flex items-center justify-between">
            <span className="font-medium text-slate-700">{s.signal_type}</span>
            <div className="flex gap-2">
              <Badge className="bg-slate-100 text-slate-500">{s.signal_scope}</Badge>
              <Badge className={sevStyle(s.severity)}>{s.severity}</Badge>
            </div>
          </div>
          <p className="mt-1 text-sm text-slate-500">{s.description}</p>
          <div className="mt-1 text-xs text-slate-400">{s.rule_name} · confidence {s.confidence}</div>
        </div>
      ))}
    </div>
  );
}

function KeyVals({ obj, fields }) {
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
      {fields.map(([key, label, fmt]) => (
        <div key={key} className="contents">
          <dt className="text-slate-400">{label}</dt>
          <dd className="text-slate-700">{obj[key] == null ? "—" : fmt ? fmt(obj[key]) : String(obj[key])}</dd>
        </div>
      ))}
    </dl>
  );
}

function IdentityPanel({ id }) {
  const { data, loading } = useAsync(() => api.identity(id), [id]);
  if (loading) return <Spinner />;
  if (!data) return <EmptyState message="No identity profile yet." />;
  return (
    <Card title="Resolved identity (masked)">
      <KeyVals obj={data} fields={[
        ["resolved_name_masked", "Name"], ["pan_masked", "PAN"], ["aadhaar_masked", "Aadhaar"],
        ["distinct_name_count", "Distinct names"], ["distinct_pan_count", "Distinct PANs"],
        ["is_synthetic_suspected", "Synthetic suspected", (v) => (v ? "⚠ Yes" : "No")],
      ]} />
      {data.indicators?.length ? <div className="mt-3 text-xs text-amber-600">Indicators: {data.indicators.join(", ")}</div> : null}
    </Card>
  );
}

function PropertyPanel({ id }) {
  const { data, loading } = useAsync(() => api.property(id), [id]);
  if (loading) return <Spinner />;
  if (!data) return <EmptyState message="No property profile (not a property-backed application)." />;
  return (
    <Card title="Property / collateral">
      <KeyVals obj={data} fields={[
        ["survey_numbers", "Survey numbers", (v) => (v || []).join(", ") || "—"],
        ["sale_consideration", "Sale consideration", inr], ["valuation", "Valuation", inr],
        ["valuation_ratio", "Valuation ratio"], ["is_inflated", "Inflated", (v) => (v ? "⚠ Yes" : "No")],
        ["duplicate_collateral_app_ids", "Duplicate collateral", (v) => (v || []).length ? `⚠ ${v.length} other app(s)` : "None"],
      ]} />
    </Card>
  );
}

function FinancialPanel({ id }) {
  const { data, loading } = useAsync(() => api.financial(id), [id]);
  if (loading) return <Spinner />;
  if (!data) return <EmptyState message="No financial profile (no ITR/GST documents)." />;
  return (
    <Card title="Business / financial">
      <KeyVals obj={data} fields={[
        ["itr_revenue", "ITR revenue", inr], ["gst_revenue", "GST turnover", inr],
        ["net_profit", "Net profit", inr], ["revenue_gap_ratio", "Revenue gap"],
      ]} />
    </Card>
  );
}

function DocumentsPanel({ id }) {
  const { data, loading, error } = useAsync(() => api.listDocuments(id), [id]);
  const [entities, setEntities] = useState({});

  async function download(docId) {
    const { url } = await api.downloadDocument(docId);
    window.open(url, "_blank");
  }
  async function loadEntities(docId) {
    const list = await api.documentEntities(docId);
    setEntities((e) => ({ ...e, [docId]: list }));
  }

  if (loading) return <Spinner />;
  return (
    <div className="space-y-3">
      <ErrorBanner error={error} />
      {data?.length ? data.map((d) => (
        <div key={d.id} className="rounded-lg border border-slate-200 bg-white p-3">
          <div className="flex items-center justify-between">
            <span className="font-medium text-slate-700">{d.document_type}</span>
            <div className="flex items-center gap-2">
              <Badge className={statusStyle(d.status)}>{d.status}</Badge>
              <Button variant="ghost" onClick={() => download(d.id)}><Download size={14} /></Button>
            </div>
          </div>
          <div className="mt-1 text-xs text-slate-400">{d.original_filename} · v{d.version}</div>
          <div className="mt-2">
            <button onClick={() => loadEntities(d.id)} className="text-xs font-medium text-brand-600">Show extracted fields</button>
            {entities[d.id] && (
              <div className="mt-2 flex flex-wrap gap-2">
                {entities[d.id].length ? entities[d.id].map((e) => (
                  <span key={e.id} className="rounded bg-slate-100 px-2 py-1 text-xs">
                    <b>{e.entity_type}:</b> {e.value ?? "—"}{e.is_sensitive ? " 🔒" : ""}
                  </span>
                )) : <span className="text-xs text-slate-400">No fields extracted.</span>}
              </div>
            )}
          </div>
        </div>
      )) : <EmptyState message="No documents uploaded." />}
    </div>
  );
}

export default function AppDetail() {
  const { id } = useParams();
  const { isAnalyst } = useAuth();
  const [tab, setTab] = useState("overview");
  const { data: app, error, loading } = useAsync(() => api.getApplication(id), [id]);

  const tabs = [
    { key: "overview", label: "Risk & Overview" },
    { key: "signals", label: "Fraud Signals" },
    { key: "identity", label: "Identity" },
    { key: "property", label: "Property" },
    { key: "financial", label: "Financial" },
    { key: "documents", label: "Documents" },
  ];

  if (loading) return <Spinner />;
  if (error) return <ErrorBanner error={error} />;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-mono text-lg text-slate-700">{app.application_number}</h1>
          <p className="text-sm text-slate-500">{app.loan_type} · {inr(app.loan_amount_requested)} · created {dt(app.created_at)}</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge className={statusStyle(app.status)}>{app.status}</Badge>
          {app.risk_tier && <Badge className={tierStyle(app.risk_tier)}>{app.risk_tier} · {app.current_risk_score}</Badge>}
          <Link to={`/app/network/${id}`}><Button variant="secondary"><NetworkIcon size={14} /> Network</Button></Link>
          {isAnalyst && <Link to={`/app/review/${id}`}><Button>Review</Button></Link>}
        </div>
      </div>

      <Tabs tabs={tabs} active={tab} onChange={setTab} />
      <div>
        {tab === "overview" && <RiskPanel id={id} />}
        {tab === "signals" && <SignalsPanel id={id} />}
        {tab === "identity" && <IdentityPanel id={id} />}
        {tab === "property" && <PropertyPanel id={id} />}
        {tab === "financial" && <FinancialPanel id={id} />}
        {tab === "documents" && <DocumentsPanel id={id} />}
      </div>
    </div>
  );
}
