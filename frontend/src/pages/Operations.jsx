import { api } from "../api/endpoints";
import { useAsync } from "../lib/useAsync";
import { Badge, Button, Card, EmptyState, ErrorBanner, Spinner, StatCard } from "../components/ui";
import { dt, sevStyle } from "../lib/format";
import { useState } from "react";

export default function Operations() {
  const { data: ov, loading, error } = useAsync(() => api.opsOverview(), []);
  const { data: threats } = useAsync(() => api.activeThreats(), []);
  const { data: events, reload: reloadEvents } = useAsync(() => api.events("?page=1&page_size=25"), []);
  const [replaying, setReplaying] = useState(false);

  async function replay() {
    setReplaying(true);
    try { await api.replayEvents(); await reloadEvents(); } finally { setReplaying(false); }
  }

  if (loading) return <Spinner />;
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-semibold text-stone-800">Operations</h1>
      <ErrorBanner error={error} />
      <div className="grid gap-4 sm:grid-cols-5">
        <StatCard label="Applications" value={ov?.applications_total ?? 0} />
        <StatCard label="Open alerts" value={ov?.alerts_open ?? 0} />
        <StatCard label="RBI reportable" value={ov?.alerts_rbi_reportable ?? 0} />
        <StatCard label="SLA breached" value={ov?.alerts_sla_breached ?? 0} />
        <StatCard label="Open cases" value={ov?.cases_open ?? 0} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Active threats">
          {threats?.length ? (
            <ul className="space-y-2 text-sm">
              {threats.map((a) => (
                <li key={a.id} className="flex items-center justify-between">
                  <span className="font-mono text-xs text-stone-500">{a.alert_number}</span>
                  <span className="text-stone-600">{a.alert_type}</span>
                  <Badge className={sevStyle(a.severity)}>{a.severity}</Badge>
                </li>
              ))}
            </ul>
          ) : <EmptyState message="No active threats." />}
        </Card>

        <Card title="Event log (outbox)" action={<Button variant="ghost" loading={replaying} onClick={replay}>Replay pending</Button>}>
          {events?.items?.length ? (
            <ul className="max-h-72 space-y-1 overflow-y-auto text-sm">
              {events.items.map((e) => (
                <li key={e.id} className="flex items-center justify-between">
                  <span className="text-stone-600">{e.event_type}</span>
                  <span className="flex items-center gap-2">
                    <Badge className={e.status === "SENT" ? "bg-emerald-100 text-emerald-700" : e.status === "FAILED" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"}>{e.status}</Badge>
                    <span className="text-xs text-stone-400">{dt(e.created_at)}</span>
                  </span>
                </li>
              ))}
            </ul>
          ) : <EmptyState message="No events yet." />}
        </Card>
      </div>
    </div>
  );
}
