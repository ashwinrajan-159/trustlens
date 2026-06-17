import { useParams, Link } from "react-router-dom";
import { api } from "../api/endpoints";
import { useAsync } from "../lib/useAsync";
import { Card, EmptyState, ErrorBanner, Spinner, Badge } from "../components/ui";

const KIND_COLORS = {
  APP: "#2563eb", PAN: "#dc2626", AADHAAR: "#ea580c", ACCOUNT: "#7c3aed",
  PROPERTY: "#0891b2", GSTIN: "#0d9488", PERSON: "#64748b",
};

function GraphSVG({ nodes, edges }) {
  const size = 520, cx = size / 2, cy = size / 2, r = size / 2 - 60;
  const pos = {};
  nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2;
    // APP nodes pulled toward the centre, attributes on the ring.
    const radius = n.kind === "APP" ? r * 0.45 : r;
    pos[n.id] = { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
  });
  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="w-full max-w-2xl">
      {edges.map((e, i) => {
        const a = pos[e.source], b = pos[e.target];
        if (!a || !b) return null;
        return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#cbd5e1" strokeWidth="1" />;
      })}
      {nodes.map((n) => {
        const p = pos[n.id];
        const rad = n.kind === "APP" ? 9 : 6;
        return (
          <g key={n.id}>
            <circle cx={p.x} cy={p.y} r={rad} fill={KIND_COLORS[n.kind] || "#94a3b8"} />
            <text x={p.x} y={p.y - rad - 3} textAnchor="middle" fontSize="9" fill="#475569">{n.label}</text>
          </g>
        );
      })}
    </svg>
  );
}

export default function NetworkGraph() {
  const { id } = useParams();
  const { data, error, loading } = useAsync(() => api.network(id), [id]);
  const { data: g } = useAsync(() => api.graph(id), [id]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-800">Entity network</h1>
        <Link to={`/app/applications/${id}`} className="text-sm font-medium text-brand-600">← Back to application</Link>
      </div>

      {g && (
        <div className="flex flex-wrap gap-2">
          <Badge className="bg-slate-100 text-slate-600">Connections: {g.fraud_connections_count}</Badge>
          <Badge className="bg-slate-100 text-slate-600">Ring size: {g.ring_size}</Badge>
          {g.in_fraud_ring && <Badge className="bg-red-100 text-red-700">⚠ In fraud ring</Badge>}
          {g.shared_pan_count > 0 && <Badge className="bg-orange-100 text-orange-700">Shared PAN ×{g.shared_pan_count}</Badge>}
          {g.shared_account_count > 0 && <Badge className="bg-orange-100 text-orange-700">Shared account ×{g.shared_account_count}</Badge>}
        </div>
      )}

      <ErrorBanner error={error} />
      <Card title="Relationship graph (PII masked)">
        {loading ? <Spinner /> : data?.nodes?.length ? (
          <div className="flex flex-col items-center gap-4">
            <GraphSVG nodes={data.nodes} edges={data.edges} />
            <div className="flex flex-wrap justify-center gap-3 text-xs text-slate-500">
              {Object.entries(KIND_COLORS).map(([k, c]) => (
                <span key={k} className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-full" style={{ background: c }} />{k}</span>
              ))}
            </div>
          </div>
        ) : <EmptyState message="No network connections found." />}
      </Card>
    </div>
  );
}
