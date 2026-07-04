import { Link } from "react-router-dom";
import { api } from "../api/endpoints";
import { useAsync } from "../lib/useAsync";
import { Badge, Card, EmptyState, ErrorBanner, Spinner, Button } from "../components/ui";
import { inr, dt, tierStyle, statusStyle } from "../lib/format";

export default function ReviewQueue() {
  // Applications awaiting an analyst decision (submitted / under review), riskiest first.
  const { data, error, loading } = useAsync(
    () => api.listApplications("?page=1&page_size=100&sort=-created_at"), []
  );
  const items = (data?.items || []).filter((a) => ["SUBMITTED", "UNDER_REVIEW"].includes(a.status));
  const order = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };
  items.sort((a, b) => (order[a.risk_tier] ?? 9) - (order[b.risk_tier] ?? 9));

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-stone-800">Review queue</h1>
      <ErrorBanner error={error} />
      <Card>
        {loading ? <Spinner /> : items.length ? (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-stone-400"><tr><th className="py-2">Number</th><th>Type</th><th>Amount</th><th>Status</th><th>Risk</th><th>Submitted</th><th></th></tr></thead>
            <tbody className="divide-y divide-stone-900/10">
              {items.map((a) => (
                <tr key={a.id} className="hover:bg-stone-900/5">
                  <td className="py-2 font-mono text-xs text-stone-500">{a.application_number}</td>
                  <td>{a.loan_type}</td>
                  <td>{inr(a.loan_amount_requested)}</td>
                  <td><Badge className={statusStyle(a.status)}>{a.status}</Badge></td>
                  <td>{a.risk_tier ? <Badge className={tierStyle(a.risk_tier)}>{a.risk_tier} · {a.current_risk_score}</Badge> : "—"}</td>
                  <td className="text-xs text-stone-400">{dt(a.submitted_at)}</td>
                  <td className="text-right"><Link to={`/app/review/${a.id}`}><Button variant="secondary">Review</Button></Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <EmptyState message="Queue is clear — no applications awaiting review." />}
      </Card>
    </div>
  );
}
