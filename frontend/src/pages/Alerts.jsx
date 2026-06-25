import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/endpoints";
import { useAsync } from "../lib/useAsync";
import { useAuth } from "../auth/AuthContext";
import { Badge, Button, Card, EmptyState, ErrorBanner, Select, Spinner } from "../components/ui";
import { dt, sevStyle, statusStyle } from "../lib/format";

export default function Alerts() {
  const { isSenior } = useAuth();
  const [status, setStatus] = useState("");
  const [severity, setSeverity] = useState("");
  const q = `?page=1&page_size=100${status ? `&status=${status}` : ""}${severity ? `&severity=${severity}` : ""}`;
  const { data, error, loading, reload } = useAsync(() => api.listAlerts(q), [q]);
  const [fmr, setFmr] = useState(null);
  const [busy, setBusy] = useState(null);

  async function act(fn, id) {
    setBusy(id);
    try { await fn(); await reload(); } finally { setBusy(null); }
  }

  const items = data?.items || [];
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-slate-800">Fraud alerts</h1>
      <div className="flex gap-3">
        <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-44">
          {["", "OPEN", "ACKNOWLEDGED", "ESCALATED", "RESOLVED", "DISMISSED"].map((s) => <option key={s} value={s}>{s || "All statuses"}</option>)}
        </Select>
        <Select value={severity} onChange={(e) => setSeverity(e.target.value)} className="w-44">
          {["", "LOW", "MEDIUM", "HIGH", "CRITICAL"].map((s) => <option key={s} value={s}>{s || "All severities"}</option>)}
        </Select>
      </div>
      <ErrorBanner error={error} />

      {fmr && (
        <Card title="RBI FMR report" action={<Button variant="ghost" onClick={() => setFmr(null)}>Close</Button>}>
          <pre className="overflow-x-auto rounded bg-slate-900 p-3 text-xs text-slate-100">{JSON.stringify(fmr, null, 2)}</pre>
        </Card>
      )}

      <Card>
        {loading ? <Spinner /> : items.length ? (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-400"><tr><th className="py-2">Alert</th><th>Type</th><th>Sev</th><th>Status</th><th>RBI</th><th>SLA</th><th></th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((a) => (
                <tr key={a.id} className={a.sla_breached ? "bg-red-50" : ""}>
                  <td className="py-2 font-mono text-xs text-slate-500">{a.alert_number}</td>
                  <td className="text-xs">{a.alert_type}</td>
                  <td><Badge className={sevStyle(a.severity)}>{a.severity}</Badge></td>
                  <td><Badge className={statusStyle(a.status)}>{a.status}</Badge></td>
                  <td className="text-xs">{a.rbi_reporting_required ? <Badge className="bg-purple-100 text-purple-700">{a.rbi_report_type}</Badge> : "—"}</td>
                  <td className="text-xs text-slate-400">{a.sla_breached ? <span className="text-red-600">breached</span> : dt(a.sla_deadline)}</td>
                  <td className="space-x-2 text-right text-xs">
                    <Link to={`/app/applications/${a.application_id}`} className="text-brand-600">App</Link>
                    {["OPEN", "ACKNOWLEDGED", "ESCALATED", "INVESTIGATING"].includes(a.status) && (
                      <Link to={`/app/alerts/${a.id}/investigate`} className="text-indigo-600">Investigate</Link>
                    )}
                    {["OPEN", "ACKNOWLEDGED", "ESCALATED"].includes(a.status) && (
                      <>
                        <button className="text-brand-600" disabled={busy === a.id} onClick={() => act(() => api.ackAlert(a.id), a.id)}>Ack</button>
                        <button className="text-emerald-600" disabled={busy === a.id} onClick={() => act(() => api.resolveAlert(a.id, false), a.id)}>Resolve</button>
                      </>
                    )}
                    {isSenior && a.rbi_reporting_required && (
                      <button className="text-purple-600" onClick={async () => setFmr((await api.fmrReport(a.id)).report)}>FMR</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <EmptyState message="No alerts." />}
      </Card>
    </div>
  );
}
