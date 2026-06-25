import { useState } from "react";
import { BookOpen, Gauge, SlidersHorizontal } from "lucide-react";
import { api } from "../api/endpoints";
import { useAsync } from "../lib/useAsync";
import { useAuth } from "../auth/AuthContext";
import { Badge, Button, Card, EmptyState, ErrorBanner, Field, Input, Spinner, Textarea } from "../components/ui";
import { dt } from "../lib/format";

const pct = (x) => `${(x * 100).toFixed(1)}%`;

// Fraud knowledge base: learned patterns, per-signal precision (with a confidence interval and
// a sample-size gate so thin data is never treated as actionable), and governed signal weights.
// Patterns/precision are projections recomputed from immutable reviews; weights are versioned
// and require an ADMIN who is not the proposer to activate.
export default function Knowledge() {
  return (
    <div className="space-y-5">
      <h1 className="flex items-center gap-2 text-2xl font-semibold text-slate-800"><BookOpen size={22} /> Fraud knowledge</h1>
      <SignalAnalytics />
      <Patterns />
      <WeightGovernance />
    </div>
  );
}

function SignalAnalytics() {
  const { data, error, loading } = useAsync(() => api.signalAnalytics(), []);
  return (
    <Card title={<span className="flex items-center gap-2"><Gauge size={16} /> Signal precision</span>}>
      <ErrorBanner error={error} />
      {loading ? <Spinner /> : data?.length ? (
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-slate-400"><tr><th className="py-2">Signal</th><th>Confirmed</th><th>FP</th><th>Precision</th><th>95% CI</th><th>Actionable</th></tr></thead>
          <tbody className="divide-y divide-slate-100">
            {data.map((s) => (
              <tr key={s.signal_name}>
                <td className="py-2 text-xs text-slate-600">{s.signal_name}</td>
                <td className="text-emerald-600">{s.confirmed_fraud_count}</td>
                <td className="text-red-600">{s.false_positive_count}</td>
                <td className="font-medium">{pct(s.precision_score)}</td>
                <td className="text-xs text-slate-400">{pct(s.precision_ci_low)}–{pct(s.precision_ci_high)}</td>
                <td>{s.sample_sufficient ? <Badge className="bg-emerald-100 text-emerald-700">yes</Badge> : <Badge className="bg-amber-100 text-amber-700">low n</Badge>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <EmptyState message="No reviewed signals yet — precision appears after confirmed/false-positive decisions." />}
    </Card>
  );
}

function Patterns() {
  const { isAdmin } = useAuth();
  const { data, error, loading, reload } = useAsync(() => api.patterns(), []);
  const [merge, setMerge] = useState({ source_id: "", target_id: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function doMerge() {
    setBusy(true); setErr(null);
    try { await api.mergePatterns(merge.source_id, merge.target_id); setMerge({ source_id: "", target_id: "" }); await reload(); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  }

  return (
    <Card title={<span className="flex items-center gap-2"><BookOpen size={16} /> Fraud patterns</span>}>
      <ErrorBanner error={error || err} />
      {loading ? <Spinner /> : data?.length ? (
        <div className="space-y-2">
          {data.map((p) => (
            <div key={p.id} className="rounded-lg bg-slate-50 px-3 py-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-slate-700">{p.name}</span>
                <Badge className="bg-brand-100 text-brand-700">conf {pct(p.pattern_confidence)}</Badge>
              </div>
              <div className="mt-1 text-xs text-slate-500">{p.description}</div>
              <div className="mt-1 text-xs text-slate-400">
                {p.occurrences} cases · {p.confirmed_cases} confirmed · {p.false_positive_count} FP
                <span className="ml-2 font-mono">{p.id.slice(0, 8)}</span>
              </div>
            </div>
          ))}
        </div>
      ) : <EmptyState message="No patterns learned yet." />}

      {isAdmin && data?.length > 1 && (
        <div className="mt-4 flex items-end gap-2 border-t border-slate-100 pt-3">
          <Field label="Merge source id"><Input value={merge.source_id} onChange={(e) => setMerge({ ...merge, source_id: e.target.value })} placeholder="duplicate" /></Field>
          <Field label="into target id"><Input value={merge.target_id} onChange={(e) => setMerge({ ...merge, target_id: e.target.value })} placeholder="keep" /></Field>
          <Button variant="secondary" loading={busy} disabled={!merge.source_id || !merge.target_id} onClick={doMerge}>Merge</Button>
        </div>
      )}
    </Card>
  );
}

function WeightGovernance() {
  const { isSenior, isAdmin } = useAuth();
  const { data, error, loading, reload } = useAsync(() => api.weights(), []);
  const [raw, setRaw] = useState("");
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function propose() {
    setErr(null);
    let weights;
    try { weights = JSON.parse(raw); } catch { setErr({ message: "Weights must be valid JSON, e.g. {\"INVALID_PAN_FORMAT\": 40}" }); return; }
    setBusy(true);
    try { await api.proposeWeights(weights, rationale); setRaw(""); setRationale(""); await reload(); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  }

  async function activate(id) {
    setBusy(true); setErr(null);
    try { await api.activateWeights(id); await reload(); } catch (e) { setErr(e); } finally { setBusy(false); }
  }

  const statusStyles = { ACTIVE: "bg-emerald-100 text-emerald-700", PROPOSED: "bg-amber-100 text-amber-700", RETIRED: "bg-slate-200 text-slate-500", DRAFT: "bg-slate-100 text-slate-500" };

  return (
    <Card title={<span className="flex items-center gap-2"><SlidersHorizontal size={16} /> Signal-weight governance</span>}>
      <ErrorBanner error={error || err} />
      {loading ? <Spinner /> : data?.length ? (
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-slate-400"><tr><th className="py-2">Version</th><th>Status</th><th>Rationale</th><th>Activated</th><th></th></tr></thead>
          <tbody className="divide-y divide-slate-100">
            {data.map((w) => (
              <tr key={w.id}>
                <td className="py-2">v{w.version}</td>
                <td><Badge className={statusStyles[w.status] || ""}>{w.status}</Badge></td>
                <td className="text-xs text-slate-500">{w.rationale}</td>
                <td className="text-xs text-slate-400">{dt(w.activated_at)}</td>
                <td className="text-right">{isAdmin && w.status === "PROPOSED" && (
                  <Button variant="secondary" loading={busy} onClick={() => activate(w.id)}>Activate</Button>
                )}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <EmptyState message="No weight configs — the engine uses built-in severity defaults." />}

      {isSenior && (
        <div className="mt-4 space-y-2 border-t border-slate-100 pt-3">
          <Field label="Propose weights (JSON {signal_type: weight})">
            <Textarea rows={2} value={raw} onChange={(e) => setRaw(e.target.value)} placeholder='{"INVALID_PAN_FORMAT": 40, "ROUND_NUMBER_SALARY": 8}' />
          </Field>
          <Field label="Rationale"><Input value={rationale} onChange={(e) => setRationale(e.target.value)} placeholder="Why these weights (audit trail)" /></Field>
          <Button variant="primary" loading={busy} disabled={!raw.trim() || !rationale.trim()} onClick={propose}>Propose</Button>
          <p className="text-xs text-slate-400">An ADMIN who is not the proposer must activate (segregation of duties).</p>
        </div>
      )}
    </Card>
  );
}
