import { NavLink, Outlet, useNavigate, Navigate } from "react-router-dom";
import {
  ShieldCheck, LayoutDashboard, FilePlus2, Files, ListChecks,
  Bell, Activity, FolderKanban, Brain, LogOut, UserCircle2, Gavel, BookOpen,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { Spinner } from "./ui";

const CUSTOMER_NAV = [
  { to: "/app/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/app/apply", label: "New Application", icon: FilePlus2 },
  { to: "/app/applications", label: "My Applications", icon: Files },
];

const ANALYST_NAV = [
  { to: "/app/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/app/applications", label: "Applications", icon: Files },
  { to: "/app/review-queue", label: "Review Queue", icon: ListChecks },
  { to: "/app/alerts", label: "Alerts", icon: Bell },
  { to: "/app/senior-review", label: "Senior Review", icon: Gavel },
  { to: "/app/knowledge", label: "Knowledge", icon: BookOpen },
  { to: "/app/cases", label: "Cases", icon: FolderKanban },
  { to: "/app/operations", label: "Operations", icon: Activity },
  { to: "/app/ml", label: "ML Platform", icon: Brain },
];

export function ProtectedRoute() {
  const { isAuthenticated, loading } = useAuth();
  if (loading) return <Spinner label="Authenticating…" />;
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <Outlet />;
}

export function AnalystRoute() {
  const { isAnalyst, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!isAnalyst) return <Navigate to="/app/dashboard" replace />;
  return <Outlet />;
}

export default function Layout() {
  const { user, role, isAnalyst, logout } = useAuth();
  const navigate = useNavigate();
  const nav = isAnalyst ? ANALYST_NAV : CUSTOMER_NAV;

  return (
    <div className="flex min-h-screen">
      <aside className="m-3 mr-0 flex w-60 shrink-0 flex-col self-stretch rounded-2xl border border-white/60 bg-white/45 shadow-glass backdrop-blur-xl">
        <div className="flex items-center gap-2.5 px-4 py-4">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-ink text-white shadow-sm">
            <ShieldCheck size={20} />
          </span>
          <div className="leading-tight">
            <div className="text-lg font-bold text-stone-800">TrustLens</div>
            <div className="text-[10px] font-medium uppercase tracking-wider text-stone-400">Fraud Intelligence</div>
          </div>
        </div>
        <nav className="flex-1 space-y-1 px-2 pt-2">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `group flex items-center gap-3 rounded-full px-3.5 py-2 text-sm font-medium transition ${
                  isActive
                    ? "bg-ink text-white shadow-sm"
                    : "text-stone-600 hover:bg-stone-900/5 hover:text-stone-900"
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <Icon size={17} className={isActive ? "text-brand-300" : "text-stone-400 group-hover:text-stone-600"} />
                  {label}
                </>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-stone-900/5 p-3">
          <NavLink to="/app/account" className="mb-1 flex items-center gap-2 rounded-xl px-3 py-2 text-sm text-stone-600 transition hover:bg-stone-900/5">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-100 text-brand-800">
              <UserCircle2 size={18} />
            </span>
            <div className="truncate">
              <div className="truncate font-medium">{user?.full_name || user?.email}</div>
              <div className="text-xs text-stone-400">{role}</div>
            </div>
          </NavLink>
          <button
            onClick={async () => { await logout(); navigate("/login"); }}
            className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-stone-500 transition hover:bg-red-50 hover:text-red-600"
          >
            <LogOut size={17} /> Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-x-hidden">
        <div className="page-enter mx-auto max-w-6xl px-6 py-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
