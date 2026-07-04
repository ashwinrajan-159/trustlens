import { Loader2, AlertCircle, Inbox } from "lucide-react";

export function Card({ title, action, icon: Icon, children, className = "", hover = false }) {
  return (
    <div
      className={`glass transition ${
        hover ? "hover:-translate-y-0.5 hover:shadow-card-hover" : ""
      } ${className}`}
    >
      {(title || action) && (
        <div className="flex items-center justify-between gap-3 border-b border-stone-900/5 px-4 py-3">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-stone-700">
            {Icon && <Icon size={15} className="text-brand-600" />}
            {title}
          </h3>
          {action}
        </div>
      )}
      <div className="p-4">{children}</div>
    </div>
  );
}

export function Badge({ children, className = "", tone }) {
  // Optional semantic tone (incl. risk tiers) — falls back to any className passed in.
  const tones = {
    neutral: "bg-stone-900/5 text-stone-600",
    brand: "bg-brand-100/80 text-brand-800 ring-1 ring-inset ring-brand-200",
    low: "bg-emerald-50/90 text-emerald-700 ring-1 ring-inset ring-emerald-100",
    medium: "bg-amber-50/90 text-amber-700 ring-1 ring-inset ring-amber-100",
    high: "bg-orange-50/90 text-orange-700 ring-1 ring-inset ring-orange-100",
    critical: "bg-red-50/90 text-red-700 ring-1 ring-inset ring-red-100",
    success: "bg-emerald-50/90 text-emerald-700 ring-1 ring-inset ring-emerald-100",
    danger: "bg-red-50/90 text-red-700 ring-1 ring-inset ring-red-100",
  };
  const toneClass = tone ? tones[tone] || tones.neutral : "";
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${toneClass} ${className}`}>
      {children}
    </span>
  );
}

// Map a risk tier / severity string to a Badge tone. Safe on unknown/empty input.
export function tierTone(value) {
  const v = String(value || "").toUpperCase();
  if (v.includes("CRITICAL")) return "critical";
  if (v.includes("HIGH")) return "high";
  if (v.includes("MEDIUM") || v.includes("MED")) return "medium";
  if (v.includes("LOW")) return "low";
  return "neutral";
}

export function Button({ children, variant = "primary", size = "md", className = "", loading, ...props }) {
  // Pill buttons; primary is stamp-ink black (dossier theme), secondary is frosted glass.
  const styles = {
    primary: "bg-ink text-white shadow-sm hover:bg-ink-soft active:bg-ink-mute",
    secondary:
      "border border-stone-300/70 bg-white/60 text-stone-700 shadow-sm backdrop-blur hover:border-stone-400 hover:bg-white/80",
    danger: "bg-red-600 text-white shadow-sm hover:bg-red-700 active:bg-red-800",
    ghost: "text-stone-600 hover:bg-stone-900/5",
  };
  const sizes = {
    sm: "px-3 py-1.5 text-xs gap-1.5",
    md: "px-4 py-2 text-sm gap-2",
    lg: "px-5 py-2.5 text-sm gap-2",
  };
  return (
    <button
      className={`inline-flex items-center justify-center rounded-full font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${styles[variant]} ${sizes[size]} ${className}`}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading && <Loader2 size={15} className="animate-spin" />}
      {children}
    </button>
  );
}

export function Spinner({ label = "Loading…" }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-stone-400">
      <Loader2 className="animate-spin" size={18} /> <span className="text-sm">{label}</span>
    </div>
  );
}

export function ErrorBanner({ error }) {
  if (!error) return null;
  return (
    <div className="flex items-start gap-2 rounded-xl border border-red-200/80 bg-red-50/80 px-3 py-2.5 text-sm text-red-700 shadow-sm backdrop-blur">
      <AlertCircle size={16} className="mt-0.5 shrink-0" />
      <span>{error.message || String(error)}</span>
    </div>
  );
}

export function EmptyState({ message = "Nothing here yet." }) {
  return (
    <div className="flex flex-col items-center gap-2 py-12 text-stone-400">
      <div className="rounded-full bg-stone-900/5 p-3">
        <Inbox size={22} />
      </div>
      <span className="text-sm">{message}</span>
    </div>
  );
}

export function Field({ label, children, hint }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-stone-600">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-stone-400">{hint}</span>}
    </label>
  );
}

const controlCls =
  "w-full rounded-xl border border-stone-300/70 bg-white/70 px-3 py-2 text-sm outline-none backdrop-blur transition placeholder:text-stone-400 focus:border-brand-500 focus:shadow-focus";

export function Input(props) {
  return <input {...props} className={`${controlCls} ${props.className || ""}`} />;
}

export function Textarea(props) {
  return <textarea {...props} className={`${controlCls} ${props.className || ""}`} />;
}

export function Select({ children, ...props }) {
  return (
    <select {...props} className={`${controlCls} ${props.className || ""}`}>
      {children}
    </select>
  );
}

export function StatCard({ label, value, sub, tone, icon: Icon }) {
  // Optional accent bar + icon keyed to a semantic tone (e.g. risk tier).
  const accents = {
    brand: "before:bg-brand-500", low: "before:bg-emerald-500", medium: "before:bg-amber-500",
    high: "before:bg-orange-500", critical: "before:bg-red-500", neutral: "before:bg-stone-300",
  };
  const accent = accents[tone] || accents.neutral;
  return (
    <div
      className={`glass relative overflow-hidden p-4 transition hover:shadow-card-hover
        before:absolute before:inset-y-0 before:left-0 before:w-1 ${accent}`}
    >
      <div className="flex items-start justify-between">
        <div className="text-xs font-medium uppercase tracking-wide text-stone-400">{label}</div>
        {Icon && <Icon size={16} className="text-stone-300" />}
      </div>
      <div className="mt-1.5 text-2xl font-semibold tracking-tight text-stone-800">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-stone-400">{sub}</div>}
    </div>
  );
}

export function Tabs({ tabs, active, onChange }) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-stone-900/10">
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition ${
            active === t.key
              ? "border-ink text-stone-900"
              : "border-transparent text-stone-500 hover:border-stone-300 hover:text-stone-700"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
