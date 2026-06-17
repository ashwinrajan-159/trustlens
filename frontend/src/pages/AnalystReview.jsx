import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { Brain, Network as NetworkIcon } from "lucide-react";
import { api } from "../api/endpoints";
import { useAsync } from "../lib/useAsync";
import { Badge, Button, Card, EmptyState, ErrorBanner, Field, Input, Spinner } from "../components/ui";
import { inr, tierStyle, sevStyle, statusStyle } from "../lib/format";

export default function AnalystReview() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: app, loading, reload } = useAsync(() => api.getApplication(id), [id]);
  const { data: risk } = useAsync(() => api.risk(id), [id]);
  const { data: signals } = useAsync(() => api.signals(id), [id]);
  const { data: identity } = useAsync(() => api.identity(id), [id]);

  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [ml, setMl] = useState(null);

  async function decide(approve) {
    if (!reason.trim()) { setError({ message: "A decision reason is required." }); return; }
    setBusy(true); setError(null);
    try {
      await api.decide(id, { approve, reason });
      await reload();
      navigate("/app/review-queue");
    } catch (e) { setError(e); } finally { setBusy(false); }
  }

  async function runMl() {
    setError(null);
    try { setMl(await api.mlPredict(id)); }
    catch (e) { setError(e); }
  }

  if (loading) return <Spinner />;
  if (!app) return <ErrorBanner error={{ message: "Application not found" }} />;
  const decided = ["APPROVED", "REJECTED"].includes(app.status);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-mono text-lg text-slate-700">{app.application_number}</h1>
          <p className="text-sm text-slate-500">{app.loan_type} · {inr(app.loan_amount_requested)}</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge className={statusStyle(app.status)}>{app.status}</Badge>
          {app.risk_tier && <Badge className={tierStyle(app.risk_tier)}>{app.risk_tier} · {app.current_risk_score}</Badge>}
          <Link to={`/app/network/${id}`}><Button variant="secondary"><NetworkIcon size={14} /> Network</Button></Link>
          <Link to={`/app/applications/${id}`}><Button variant="secondary">Full detail</Button></Link>
        </div>
      </div>

      <ErrorBanner error={error} />

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title={`Fraud signals (${signals?.length || 0})`}>
            {signals?.length ? (
              <div className="space-y-2">
                {signals.map((s) => (
                  <div key={s.id} className="flex items-start justify-between rounded-lg bg-slate-50 px-3 py-2">
                    <div>
                      <div className="text-sm font-medium text-slate-700">{s.signal_type} <span className="text-xs text-slate-400">· {s.signal_scope}</span></div>
                      <div className="text-xs text-slate-500">{s.description}</div>
                    </div>
                    <Badge className={sevStyle(s.severity)}>{s.severity}</Badge>
                  </div>
                ))}
              </div>
            ) : <EmptyState message="No fraud signals." />}
          </Card>

          <Card title="Deterministic score breakdown">
            {risk?.reasons?.length ? (
              <ul className="space-y-1 text-sm">
                {risk.reasons.map((r, i) => (
                  <li key={i} className="flex justify-between"><span className="text-slate-600">{r.signal_type}</span><span className="text-slate-400">{r.category} · +{r.weight}</span></li>
                ))}
              </ul>
            ) : <EmptyState message="No assessment yet." />}
          </Card>
        </div>

        <div className="space-y-4">
          <Card title="Identity">
            {identity ? (
              <div className="space-y-1 text-sm">
                <div>{identity.resolved_name_masked || "—"}</div>
                <div className="text-slate-400">PAN {identity.pan_masked || "—"}</div>
                {identity.is_synthetic_suspected && <Badge className="bg-red-100 text-red-700">⚠ Synthetic suspected</Badge>}
              </div>
            ) : <span className="text-sm text-slate-400">No identity profile.</span>}
          </Card>

          <Card title="ML second opinion" action={<Button variant="ghost" onClick={runMl}><Brain size={14} /> Predict</Button>}>
            {ml ? (
              <div className="space-y-2 text-sm">
                <div>Fraud probability: <b>{(ml.fraud_probability * 100).toFixed(1)}%</b></div>
                <Badge className={tierStyle(ml.risk_tier)}>{ml.risk_tier}</Badge>
                {ml.shap_top?.length ? (
                  <ul className="mt-1 text-xs text-slate-500">
                    {ml.shap_top.slice(0, 4).map((c) => <li key={c.feature}>{c.feature}: {c.contribution}</li>)}
                  </ul>
                ) : null}
              </div>
            ) : <span className="text-xs text-slate-400">Run the champion model for an advisory probability (needs a deployed model).</span>}
          </Card>

          <Card title="Decision">
            {decided ? (
              <div className="text-sm">
                <Badge className={statusStyle(app.status)}>{app.status}</Badge>
                {app.decision_reason && <p className="mt-2 text-slate-500">{app.decision_reason}</p>}
              </div>
            ) : (
              <div className="space-y-3">
                <Field label="Decision reason"><Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Rationale for the audit trail" /></Field>
                <div className="flex gap-2">
                  <Button variant="primary" loading={busy} onClick={() => decide(true)}>Approve</Button>
                  <Button variant="danger" loading={busy} onClick={() => decide(false)}>Reject</Button>
                </div>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
