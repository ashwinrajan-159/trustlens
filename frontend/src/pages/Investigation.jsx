import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Search } from "lucide-react";
import { api } from "../api/endpoints";
import { useAsync } from "../lib/useAsync";
import { useAuth } from "../auth/AuthContext";
import { Badge, Button, Card, EmptyState, ErrorBanner, Field, Input, Select, Spinner, Textarea } from "../components/ui";
import { dt, sevStyle, statusStyle } from "../lib/format";

const RECOMMENDATIONS = ["REQUEST_INFORMATION", "APPROVE_APPLICATION", "ESCALATE_FRAUD", "REJECT_APPLICATION"];

// Investigation workspace for a single alert: claim it, study the firing signals, then file
// a structured report. The report routes the alert to a senior reviewer (a different person —
// segregation of duties is enforced server-side).
export default function Investigation() {
  const { alertId } = useParams();
  const { user } = useAuth();
  const { data: alert, loading, error, reload } = useAsync(() => api.getAlert(alertId), [alertId]);
  const { data: reports, reload: reloadReports } = useAsync(() => api.listInvestigations(alertId), [alertId]);
  const signalsQ = useAsync(() => (alert ? api.signals(alert.application_id) : Promise.resolve([])), [alert?.application_id]);

  const [form, setForm] = useState({ investigation_summary: "", findings: "", recommendation: "REQUEST_INFORMATION" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  if (loading) return <Spinner />;
  if (!alert) return <ErrorBanner error={{ message: "Alert not found" }} />;

  const mine = alert.claimed_by === user?.id;
  const claimable = !alert.claimed_by;
  const canReport = mine && alert.status === "INVESTIGATING";

  async function act(fn) {
    setBusy(true); setErr(null);
    try { await fn(); await reload(); } catch (e) { setErr(e); } finally { setBusy(false); }
  }

  async function submit() {
    if (!form.investigation_summary.trim()) { setErr({ message: "An investigation summary is required." }); return; }
    setBusy(true); setErr(null);
    try {
      await api.submitInvestigation(alertId, { ...form, evidence: {} });
      await reload(); await reloadReports();
      setForm({ investigation_summary: "", findings: "", recommendation: "REQUEST_INFORMATION" });
    } catch (e) { setErr(e); } finally { setBusy(false); }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold text-slate-800"><Search size={20} /> Investigation</h1>
          <p className="font-mono text-xs text-slate-500">{alert.alert_number} · {alert.alert_type}</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge className={sevStyle(alert.severity)}>{alert.severity}</Badge>
          <Badge className={statusStyle(alert.status)}>{alert.status}</Badge>
          <Link to={`/app/applications/${alert.application_id}`}><Button variant="secondary">Application</Button></Link>
        </div>
      </div>

      <ErrorBanner error={err || error} />

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title={`Fraud signals (${signalsQ.data?.length || 0})`}>
            {signalsQ.data?.length ? (
              <div className="space-y-2">
                {signalsQ.data.map((s) => (
                  <div key={s.id} className="flex items-start justify-between rounded-lg bg-slate-50 px-3 py-2">
                    <div>
                      <div className="text-sm font-medium text-slate-700">{s.signal_type}</div>
                      <div className="text-xs text-slate-500">{s.description}</div>
                    </div>
                    <Badge className={sevStyle(s.severity)}>{s.severity}</Badge>
                  </div>
                ))}
              </div>
            ) : <EmptyState message="No fraud signals on this application." />}
          </Card>

          <Card title="Submit investigation report">
            {claimable ? (
              <EmptyState message="Claim this alert before reporting." />
            ) : !mine ? (
              <p className="text-sm text-slate-500">Claimed by another analyst ({alert.claimed_by?.slice(0, 8)}…). Only the claimant can report.</p>
            ) : !canReport ? (
              <p className="text-sm text-slate-500">Report already submitted — alert is {alert.status}.</p>
            ) : (
              <div className="space-y-3">
                <Field label="Investigation summary">
                  <Textarea rows={3} value={form.investigation_summary}
                    onChange={(e) => setForm({ ...form, investigation_summary: e.target.value })}
                    placeholder="What you investigated and concluded (for the audit trail)" />
                </Field>
                <Field label="Findings">
                  <Textarea rows={3} value={form.findings}
                    onChange={(e) => setForm({ ...form, findings: e.target.value })}
                    placeholder="Supporting evidence and detail" />
                </Field>
                <Field label="Recommendation">
                  <Select value={form.recommendation} onChange={(e) => setForm({ ...form, recommendation: e.target.value })}>
                    {RECOMMENDATIONS.map((r) => <option key={r} value={r}>{r.replace(/_/g, " ")}</option>)}
                  </Select>
                </Field>
                <Button variant="primary" loading={busy} onClick={submit}>Submit to senior review</Button>
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-4">
          <Card title="Assignment">
            {claimable ? (
              <Button variant="primary" loading={busy} onClick={() => act(() => api.claimAlert(alertId))}>Claim for investigation</Button>
            ) : (
              <div className="text-sm">
                <div className="text-slate-500">Claimed by</div>
                <div className="font-mono text-xs">{alert.claimed_by?.slice(0, 12)}…{mine && <Badge className="ml-2 bg-emerald-100 text-emerald-700">you</Badge>}</div>
                <div className="mt-1 text-xs text-slate-400">{dt(alert.claimed_at)}</div>
              </div>
            )}
          </Card>

          <Card title="Report history">
            {reports?.length ? (
              <ul className="space-y-2 text-sm">
                {reports.map((r) => (
                  <li key={r.id} className="rounded-lg bg-slate-50 px-3 py-2">
                    <Badge className="bg-slate-200 text-slate-700">{r.recommendation}</Badge>
                    <div className="mt-1 text-xs text-slate-500">{r.investigation_summary}</div>
                    <div className="text-xs text-slate-400">{dt(r.created_at)}</div>
                  </li>
                ))}
              </ul>
            ) : <span className="text-xs text-slate-400">No reports yet.</span>}
          </Card>
        </div>
      </div>
    </div>
  );
}
