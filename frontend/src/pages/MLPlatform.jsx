import { useState } from "react";
import { api } from "../api/endpoints";
import { useAsync } from "../lib/useAsync";
import { useAuth } from "../auth/AuthContext";
import { Badge, Button, Card, EmptyState, ErrorBanner, Field, Input, Spinner } from "../components/ui";
import { dt, statusStyle } from "../lib/format";

export default function MLPlatform() {
  const { isSenior } = useAuth();
  const { data: models, loading, error, reload } = useAsync(() => api.mlModels(), []);
  const { data: drift } = useAsync(() => api.mlDrift(), []);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [predictId, setPredictId] = useState("");
  const [pred, setPred] = useState(null);

  async function run(fn) {
    setBusy(true); setErr(null);
    try { await fn(); await reload(); } catch (e) { setErr(e); } finally { setBusy(false); }
  }
  async function predict() {
    setErr(null); setPred(null);
    try { setPred(await api.mlPredict(predictId)); } catch (e) { setErr(e); }
  }

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-semibold text-stone-800">ML platform <span className="text-sm font-normal text-stone-400">· advisory second opinion</span></h1>
      <ErrorBanner error={error || err} />

      <div className="flex flex-wrap items-center gap-3">
        {isSenior && <Button loading={busy} onClick={() => run(() => api.mlTrain({ name: "fraud_classifier", algorithm: "random_forest" }))}>Train new model</Button>}
        {drift && <Badge className={drift.drift_detected ? "bg-red-100 text-red-700" : "bg-emerald-100 text-emerald-700"}>
          Drift: {drift.recommendation}
        </Badge>}
      </div>

      <Card title="Model registry">
        {loading ? <Spinner /> : models?.length ? (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-stone-400"><tr><th className="py-2">Model</th><th>Algo</th><th>Status</th><th>PR-AUC</th><th>FPR</th><th>Champion</th><th></th></tr></thead>
            <tbody className="divide-y divide-stone-900/10">
              {models.map((m) => (
                <tr key={m.id}>
                  <td className="py-2">{m.name} v{m.version}</td>
                  <td className="text-xs">{m.algorithm}</td>
                  <td><Badge className={statusStyle(m.status === "DEPLOYED" ? "APPROVED" : m.status === "REJECTED" ? "REJECTED" : "SUBMITTED")}>{m.status}</Badge></td>
                  <td>{m.metrics?.pr_auc ?? "—"}</td>
                  <td>{m.metrics?.fpr ?? "—"}</td>
                  <td>{m.is_champion ? "★" : ""}</td>
                  <td className="space-x-2 text-right text-xs">
                    {isSenior && m.status === "TRAINED" && (
                      <button className="text-brand-700" onClick={() => run(() => api.mlApprove(m.id))}>Approve</button>
                    )}
                    {isSenior && m.status === "APPROVED" && (
                      <button className="text-emerald-600" onClick={() => run(() => api.mlPromote(m.id))}>Promote</button>
                    )}
                    {isSenior && ["TRAINED", "APPROVED"].includes(m.status) && (
                      <button className="text-red-600" onClick={() => run(() => api.mlReject(m.id, "rejected via UI"))}>Reject</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <EmptyState message="No models trained. Labels accrue from analyst decisions; train once enough exist." />}
      </Card>

      <Card title="Score an application (champion)">
        <div className="flex items-end gap-3">
          <Field label="Application ID"><Input value={predictId} onChange={(e) => setPredictId(e.target.value)} placeholder="application uuid" /></Field>
          <Button onClick={predict} disabled={!predictId}>Predict</Button>
        </div>
        {pred && (
          <div className="mt-3 text-sm">
            Fraud probability <b>{(pred.fraud_probability * 100).toFixed(1)}%</b> · tier {pred.risk_tier} · {pred.latency_ms}ms
            {pred.shap_top?.length ? (
              <ul className="mt-1 text-xs text-stone-500">{pred.shap_top.map((c) => <li key={c.feature}>{c.feature}: {c.contribution}</li>)}</ul>
            ) : null}
          </div>
        )}
      </Card>
    </div>
  );
}
