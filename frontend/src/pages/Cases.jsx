import { useState } from "react";
import { api } from "../api/endpoints";
import { useAsync } from "../lib/useAsync";
import { useAuth } from "../auth/AuthContext";
import { Badge, Button, Card, EmptyState, ErrorBanner, Field, Input, Select, Spinner } from "../components/ui";
import { dt, statusStyle } from "../lib/format";

export default function Cases() {
  const { isSenior } = useAuth();
  const { data, error, loading, reload } = useAsync(() => api.listCases(), []);
  const [form, setForm] = useState({ case_type: "INVESTIGATION", priority: "MEDIUM", summary: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function create(e) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      await api.createCase({ ...form, application_ids: [], alert_ids: [] });
      setForm({ case_type: "INVESTIGATION", priority: "MEDIUM", summary: "" });
      await reload();
    } catch (e2) { setErr(e2); } finally { setBusy(false); }
  }
  async function close(id) {
    const outcome = prompt("Close outcome (e.g. FRAUD_CONFIRMED, CLEARED):");
    if (!outcome) return;
    try { await api.closeCase(id, outcome); await reload(); } catch (e2) { setErr(e2); }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-slate-800">Investigation cases</h1>
      <ErrorBanner error={error || err} />

      <Card title="Open a case">
        <form onSubmit={create} className="grid gap-3 sm:grid-cols-4">
          <Select value={form.case_type} onChange={(e) => setForm({ ...form, case_type: e.target.value })}>
            {["INVESTIGATION", "FRAUD_RING", "RBI_REPORTABLE"].map((t) => <option key={t}>{t}</option>)}
          </Select>
          <Select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
            {["LOW", "MEDIUM", "HIGH", "URGENT"].map((p) => <option key={p}>{p}</option>)}
          </Select>
          <Input className="sm:col-span-2" placeholder="Summary" value={form.summary} required onChange={(e) => setForm({ ...form, summary: e.target.value })} />
          <Button type="submit" loading={busy} className="sm:col-span-4 w-fit">Create case</Button>
        </form>
      </Card>

      <Card>
        {loading ? <Spinner /> : data?.length ? (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-400"><tr><th className="py-2">Case</th><th>Type</th><th>Priority</th><th>Status</th><th>Summary</th><th></th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((c) => (
                <tr key={c.id}>
                  <td className="py-2 font-mono text-xs text-slate-500">{c.case_number}</td>
                  <td className="text-xs">{c.case_type}</td>
                  <td className="text-xs">{c.priority}</td>
                  <td><Badge className={statusStyle(c.status)}>{c.status}</Badge></td>
                  <td className="max-w-xs truncate text-slate-600">{c.summary}</td>
                  <td className="text-right text-xs">
                    {isSenior && c.status !== "CLOSED" && <button className="text-emerald-600" onClick={() => close(c.id)}>Close</button>}
                    {c.closed_outcome && <span className="text-slate-400">{c.closed_outcome}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <EmptyState message="No cases." />}
      </Card>
    </div>
  );
}
