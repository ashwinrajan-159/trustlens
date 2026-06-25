import { useState } from "react";
import { Link } from "react-router-dom";
import { Gavel } from "lucide-react";
import { api } from "../api/endpoints";
import { useAsync } from "../lib/useAsync";
import { Badge, Button, Card, EmptyState, ErrorBanner, Field, Select, Spinner, Textarea } from "../components/ui";
import { dt, sevStyle } from "../lib/format";

const DECISIONS = ["CONFIRMED_FRAUD", "FALSE_POSITIVE", "INSUFFICIENT_EVIDENCE", "NEED_MORE_REVIEW"];
const FP_REASONS = ["EXPLAINABLE_DOCUMENT_VARIANT", "KNOWN_GOOD_CUSTOMER", "DATA_ENTRY_ERROR", "LEGITIMATE_REPETITION", "THRESHOLD_TOO_SENSITIVE", "OTHER"];

// Senior-reviewer queue: alerts awaiting a final decision. The reviewer picks an alert, reads
// the investigator's report, and records a decision. Segregation of duties (the reviewer can't
// be the investigator) is enforced server-side and surfaced as an error if violated.
export default function SeniorReview() {
  const { data: queue, error, loading, reload } = useAsync(() => api.reviewQueue(), []);
  const [selected, setSelected] = useState(null);

  return (
    <div className="space-y-4">
      <h1 className="flex items-center gap-2 text-2xl font-semibold text-slate-800"><Gavel size={22} /> Senior review queue</h1>
      <ErrorBanner error={error} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={`Awaiting review (${queue?.length || 0})`}>
          {loading ? <Spinner /> : queue?.length ? (
            <table className="w-full text-sm">
              <tbody className="divide-y divide-slate-100">
                {queue.map((a) => (
                  <tr key={a.id} className={`cursor-pointer hover:bg-slate-50 ${selected?.id === a.id ? "bg-brand-50" : ""}`} onClick={() => setSelected(a)}>
                    <td className="py-2 font-mono text-xs text-slate-500">{a.alert_number}</td>
                    <td><Badge className={sevStyle(a.severity)}>{a.severity}</Badge></td>
                    <td className="text-xs text-slate-400">{dt(a.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <EmptyState message="No alerts awaiting review." />}
        </Card>

        {selected ? <ReviewPanel key={selected.id} alert={selected} onDone={() => { setSelected(null); reload(); }} /> : (
          <Card title="Decision"><EmptyState message="Select an alert to review." /></Card>
        )}
      </div>
    </div>
  );
}

function ReviewPanel({ alert, onDone }) {
  const { data: reports, loading } = useAsync(() => api.listInvestigations(alert.id), [alert.id]);
  const [form, setForm] = useState({ decision: "CONFIRMED_FRAUD", comments: "", fp_reason_code: "EXPLAINABLE_DOCUMENT_VARIANT" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const report = reports?.[0];
  const isFP = form.decision === "FALSE_POSITIVE";

  async function submit() {
    if (!report) return;
    setBusy(true); setErr(null);
    try {
      await api.recordReview(report.id, {
        decision: form.decision,
        comments: form.comments,
        fp_reason_code: isFP ? form.fp_reason_code : null,
      });
      onDone();
    } catch (e) { setErr(e); } finally { setBusy(false); }
  }

  return (
    <Card title={`Review · ${alert.alert_number}`} action={<Link to={`/app/applications/${alert.application_id}`} className="text-xs text-brand-600">Application</Link>}>
      {loading ? <Spinner /> : !report ? <EmptyState message="No investigation report on this alert." /> : (
        <div className="space-y-3">
          <div className="rounded-lg bg-slate-50 p-3 text-sm">
            <Badge className="bg-slate-200 text-slate-700">{report.recommendation}</Badge>
            <p className="mt-2 text-slate-600">{report.investigation_summary}</p>
            {report.findings && <p className="mt-1 text-xs text-slate-500">{report.findings}</p>}
            <p className="mt-1 text-xs text-slate-400">Investigator {report.underwriter_id?.slice(0, 8)}… · {dt(report.created_at)}</p>
          </div>

          <ErrorBanner error={err} />
          <Field label="Decision">
            <Select value={form.decision} onChange={(e) => setForm({ ...form, decision: e.target.value })}>
              {DECISIONS.map((d) => <option key={d} value={d}>{d.replace(/_/g, " ")}</option>)}
            </Select>
          </Field>
          {isFP && (
            <Field label="False-positive reason" hint="Captured so the signal's precision can be tracked.">
              <Select value={form.fp_reason_code} onChange={(e) => setForm({ ...form, fp_reason_code: e.target.value })}>
                {FP_REASONS.map((r) => <option key={r} value={r}>{r.replace(/_/g, " ")}</option>)}
              </Select>
            </Field>
          )}
          <Field label="Comments">
            <Textarea rows={2} value={form.comments} onChange={(e) => setForm({ ...form, comments: e.target.value })} placeholder="Rationale for the audit trail" />
          </Field>
          <Button variant="primary" loading={busy} onClick={submit}>Record decision</Button>
        </div>
      )}
    </Card>
  );
}
