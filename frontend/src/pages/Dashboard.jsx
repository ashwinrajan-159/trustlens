import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { api } from "../api/endpoints";
import { useAsync } from "../lib/useAsync";
import { Badge, Card, EmptyState, Spinner, StatCard, ErrorBanner } from "../components/ui";
import { inr, statusStyle, tierStyle, sevStyle } from "../lib/format";

function TierBars({ byTier }) {
  const tiers = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
  const max = Math.max(1, ...tiers.map((t) => byTier[t] || 0));
  return (
    <div className="space-y-2">
      {tiers.map((t) => (
        <div key={t} className="flex items-center gap-2">
          <span className="w-20"><Badge className={tierStyle(t)}>{t}</Badge></span>
          <div className="h-3 flex-1 overflow-hidden rounded bg-stone-900/5">
            <div className="h-full bg-brand-500" style={{ width: `${((byTier[t] || 0) / max) * 100}%` }} />
          </div>
          <span className="w-8 text-right text-sm text-stone-500">{byTier[t] || 0}</span>
        </div>
      ))}
    </div>
  );
}

function AnalystDashboard() {
  const { data: ov, error, loading } = useAsync(() => api.opsOverview(), []);
  const { data: threats } = useAsync(() => api.activeThreats(), []);
  if (loading) return <Spinner />;
  return (
    <div className="space-y-6">
      <ErrorBanner error={error} />
      <div className="grid gap-4 sm:grid-cols-4">
        <StatCard label="Applications" value={ov?.applications_total ?? 0} />
        <StatCard label="Open alerts" value={ov?.alerts_open ?? 0} />
        <StatCard label="RBI reportable" value={ov?.alerts_rbi_reportable ?? 0} />
        <StatCard label="SLA breached" value={ov?.alerts_sla_breached ?? 0} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Risk tier distribution">
          <TierBars byTier={ov?.applications_by_tier || {}} />
        </Card>
        <Card title="Active threats" action={<Link to="/app/alerts" className="text-xs font-medium text-brand-700">View all</Link>}>
          {threats?.length ? (
            <ul className="space-y-2">
              {threats.slice(0, 6).map((a) => (
                <li key={a.id} className="flex items-center justify-between text-sm">
                  <span className="font-mono text-xs text-stone-500">{a.alert_number}</span>
                  <span className="truncate px-2 text-stone-600">{a.alert_type}</span>
                  <Badge className={sevStyle(a.severity)}>{a.severity}</Badge>
                </li>
              ))}
            </ul>
          ) : <EmptyState message="No active threats." />}
        </Card>
      </div>
    </div>
  );
}

function CustomerDashboard() {
  const { data, error, loading } = useAsync(() => api.listApplications("?page=1&page_size=50"), []);
  if (loading) return <Spinner />;
  const items = data?.items || [];
  const byStatus = items.reduce((acc, a) => ({ ...acc, [a.status]: (acc[a.status] || 0) + 1 }), {});
  return (
    <div className="space-y-6">
      <ErrorBanner error={error} />
      <div className="grid gap-4 sm:grid-cols-4">
        <StatCard label="Total applications" value={items.length} />
        <StatCard label="Submitted" value={byStatus.SUBMITTED || 0} />
        <StatCard label="Approved" value={byStatus.APPROVED || 0} />
        <StatCard label="Rejected" value={byStatus.REJECTED || 0} />
      </div>
      <Card title="Recent applications" action={<Link to="/app/apply" className="text-xs font-medium text-brand-700">+ New</Link>}>
        {items.length ? (
          <div className="divide-y divide-stone-900/10">
            {items.slice(0, 8).map((a) => (
              <Link key={a.id} to={`/app/applications/${a.id}`} className="flex items-center justify-between py-2 text-sm hover:bg-stone-900/5">
                <span className="font-mono text-xs text-stone-500">{a.application_number}</span>
                <span className="text-stone-600">{a.loan_type} · {inr(a.loan_amount_requested)}</span>
                <Badge className={statusStyle(a.status)}>{a.status}</Badge>
              </Link>
            ))}
          </div>
        ) : <EmptyState message="No applications yet — start one." />}
      </Card>
    </div>
  );
}

export default function Dashboard() {
  const { isAnalyst, user } = useAuth();
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold text-stone-800">Welcome, {user?.full_name?.split(" ")[0] || "there"}</h1>
        <p className="text-sm text-stone-500">{isAnalyst ? "Fraud operations overview" : "Your loan applications"}</p>
      </div>
      {isAnalyst ? <AnalystDashboard /> : <CustomerDashboard />}
    </div>
  );
}
