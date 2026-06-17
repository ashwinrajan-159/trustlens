import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/endpoints";
import { useAsync } from "../lib/useAsync";
import { useAuth } from "../auth/AuthContext";
import { Badge, Card, EmptyState, ErrorBanner, Select, Spinner, Button } from "../components/ui";
import { inr, dt, statusStyle, tierStyle } from "../lib/format";

const STATUSES = ["", "DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED"];
const TYPES = ["", "HOME", "PERSONAL", "BUSINESS", "AUTO"];

export default function Applications() {
  const { isAnalyst } = useAuth();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [loanType, setLoanType] = useState("");
  const q = `?page=${page}&page_size=20${status ? `&status=${status}` : ""}${loanType ? `&loan_type=${loanType}` : ""}`;
  const { data, error, loading } = useAsync(() => api.listApplications(q), [q]);

  const items = data?.items || [];
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-800">Applications</h1>
        {!isAnalyst && <Link to="/app/apply"><Button>+ New application</Button></Link>}
      </div>

      <div className="flex flex-wrap gap-3">
        <Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className="w-44">
          {STATUSES.map((s) => <option key={s} value={s}>{s || "All statuses"}</option>)}
        </Select>
        <Select value={loanType} onChange={(e) => { setLoanType(e.target.value); setPage(1); }} className="w-44">
          {TYPES.map((t) => <option key={t} value={t}>{t || "All loan types"}</option>)}
        </Select>
      </div>

      <ErrorBanner error={error} />
      <Card>
        {loading ? <Spinner /> : items.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-slate-400">
                <tr>
                  <th className="py-2">Number</th><th>Type</th><th>Amount</th>
                  <th>Status</th><th>Risk</th><th>Submitted</th><th></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items.map((a) => (
                  <tr key={a.id} className="hover:bg-slate-50">
                    <td className="py-2 font-mono text-xs text-slate-500">{a.application_number}</td>
                    <td>{a.loan_type}</td>
                    <td>{inr(a.loan_amount_requested)}</td>
                    <td><Badge className={statusStyle(a.status)}>{a.status}</Badge></td>
                    <td>{a.risk_tier ? <Badge className={tierStyle(a.risk_tier)}>{a.risk_tier} · {a.current_risk_score ?? "—"}</Badge> : <span className="text-slate-300">—</span>}</td>
                    <td className="text-xs text-slate-400">{dt(a.submitted_at)}</td>
                    <td className="text-right">
                      <Link to={`/app/applications/${a.id}`} className="text-xs font-medium text-brand-600">View</Link>
                      {isAnalyst && <Link to={`/app/review/${a.id}`} className="ml-3 text-xs font-medium text-brand-600">Review</Link>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyState message="No applications match these filters." />}
      </Card>

      <div className="flex items-center justify-between text-sm text-slate-500">
        <span>Page {page} of {pages} · {data?.total ?? 0} total</span>
        <div className="flex gap-2">
          <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
          <Button variant="secondary" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>Next</Button>
        </div>
      </div>
    </div>
  );
}
