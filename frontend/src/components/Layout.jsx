import { NavLink, Outlet, useNavigate, Navigate } from "react-router-dom";
import {
  ShieldCheck, LayoutDashboard, FilePlus2, Files, ListChecks,
  Bell, Activity, FolderKanban, Brain, LogOut, UserCircle2,
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
      <aside className="flex w-60 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="flex items-center gap-2 px-4 py-4 text-brand-700">
          <ShieldCheck size={22} />
          <span className="text-lg font-bold">TrustLens</span>
        </div>
        <nav className="flex-1 space-y-1 px-2">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium ${
                  isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100"
                }`
              }
            >
              <Icon size={17} /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-100 p-3">
          <NavLink to="/app/account" className="mb-1 flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100">
            <UserCircle2 size={17} />
            <div className="truncate">
              <div className="truncate font-medium">{user?.full_name || user?.email}</div>
              <div className="text-xs text-slate-400">{role}</div>
            </div>
          </NavLink>
          <button
            onClick={async () => { await logout(); navigate("/login"); }}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-500 hover:bg-slate-100"
          >
            <LogOut size={17} /> Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-x-hidden">
        <div className="mx-auto max-w-6xl px-6 py-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
