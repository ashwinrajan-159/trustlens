export function inr(amount) {
  if (amount == null) return "—";
  const n = Number(amount);
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return `₹${n.toLocaleString("en-IN")}`;
}

export function dt(s) {
  if (!s) return "—";
  try { return new Date(s).toLocaleString(); } catch { return s; }
}

const TIER_STYLES = {
  LOW: "bg-emerald-100 text-emerald-700",
  MEDIUM: "bg-amber-100 text-amber-700",
  HIGH: "bg-orange-100 text-orange-700",
  CRITICAL: "bg-red-100 text-red-700",
};
export const tierStyle = (t) => TIER_STYLES[t] || "bg-slate-100 text-slate-600";

const SEV_STYLES = {
  LOW: "bg-slate-100 text-slate-600",
  MEDIUM: "bg-amber-100 text-amber-700",
  HIGH: "bg-orange-100 text-orange-700",
  CRITICAL: "bg-red-100 text-red-700",
};
export const sevStyle = (s) => SEV_STYLES[s] || "bg-slate-100 text-slate-600";

const STATUS_STYLES = {
  DRAFT: "bg-slate-100 text-slate-600",
  SUBMITTED: "bg-blue-100 text-blue-700",
  UNDER_REVIEW: "bg-indigo-100 text-indigo-700",
  APPROVED: "bg-emerald-100 text-emerald-700",
  REJECTED: "bg-red-100 text-red-700",
  OPEN: "bg-blue-100 text-blue-700",
  ACKNOWLEDGED: "bg-indigo-100 text-indigo-700",
  ESCALATED: "bg-orange-100 text-orange-700",
  RESOLVED: "bg-emerald-100 text-emerald-700",
  DISMISSED: "bg-slate-100 text-slate-600",
  IN_PROGRESS: "bg-indigo-100 text-indigo-700",
  CLOSED: "bg-emerald-100 text-emerald-700",
};
export const statusStyle = (s) => STATUS_STYLES[s] || "bg-slate-100 text-slate-600";
