import { Link, Navigate } from "react-router-dom";
import { ShieldCheck, ScanSearch, Network, FileSearch } from "lucide-react";
import { useAuth } from "../auth/AuthContext";

const FEATURES = [
  { icon: FileSearch, title: "Document Intelligence", body: "OCR + layout-agnostic extraction across Aadhaar, PAN, salary slips, bank statements, deeds." },
  { icon: ScanSearch, title: "Explainable Fraud Engine", body: "Deterministic rules + weighted risk scoring. Every decision is auditable, never a black box." },
  { icon: Network, title: "Graph & Identity", body: "Cross-application fraud rings, mule accounts, synthetic identities and duplicate collateral." },
];

export default function Landing() {
  const { isAuthenticated } = useAuth();
  if (isAuthenticated) return <Navigate to="/app/dashboard" replace />;

  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <div className="flex items-center gap-2 text-brand-700">
          <ShieldCheck size={24} /> <span className="text-xl font-bold">TrustLens AI</span>
        </div>
        <div className="flex gap-2">
          <Link to="/login" className="rounded-lg px-4 py-2 text-sm font-medium text-stone-600 hover:bg-stone-900/5">Sign in</Link>
          <Link to="/register" className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700">Get started</Link>
        </div>
      </header>

      <section className="mx-auto max-w-4xl px-6 py-20 text-center">
        <h1 className="text-4xl font-bold tracking-tight text-stone-900 sm:text-5xl">
          Case-based underwriting intelligence for Indian banks
        </h1>
        <p className="mx-auto mt-5 max-w-2xl text-lg text-stone-500">
          Detect forged documents, synthetic identities, collateral fraud and coordinated fraud rings —
          with explainable, regulator-ready decisions anchored to every loan application.
        </p>
        <div className="mt-8 flex justify-center gap-3">
          <Link to="/register" className="rounded-lg bg-brand-600 px-6 py-3 text-sm font-semibold text-white hover:bg-brand-700">Start an application</Link>
          <Link to="/login" className="rounded-lg border border-stone-900/10 bg-white/60 px-6 py-3 text-sm font-semibold text-stone-700 hover:bg-stone-900/5">Analyst sign in</Link>
        </div>
      </section>

      <section className="mx-auto grid max-w-5xl gap-5 px-6 pb-24 sm:grid-cols-3">
        {FEATURES.map(({ icon: Icon, title, body }) => (
          <div key={title} className="glass p-6">
            <Icon className="text-brand-700" size={24} />
            <h3 className="mt-3 font-semibold text-stone-800">{title}</h3>
            <p className="mt-1 text-sm text-stone-500">{body}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
