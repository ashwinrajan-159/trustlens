import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { Button, ErrorBanner, Field, Input } from "../components/ui";

export default function Register() {
  const { register, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ full_name: "", email: "", password: "", data_consent_given: true });
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  if (isAuthenticated) return <Navigate to="/app/dashboard" replace />;

  async function submit(e) {
    e.preventDefault();
    setLoading(true); setError(null);
    try {
      await register(form);
      navigate("/app/dashboard");
    } catch (err) { setError(err); } finally { setLoading(false); }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="flex items-center gap-2 text-brand-700"><ShieldCheck size={22} /><span className="text-lg font-bold">TrustLens</span></div>
        <h1 className="text-xl font-semibold text-slate-800">Create account</h1>
        <ErrorBanner error={error} />
        <Field label="Full name"><Input required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
        <Field label="Email"><Input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
        <Field label="Password" hint="Minimum 8 characters"><Input type="password" required minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" checked={form.data_consent_given} onChange={(e) => setForm({ ...form, data_consent_given: e.target.checked })} />
          I consent to processing my data (DPDP Act 2023)
        </label>
        <Button type="submit" loading={loading} className="w-full" disabled={!form.data_consent_given}>Create account</Button>
        <p className="text-center text-sm text-slate-500">Have an account? <Link to="/login" className="font-medium text-brand-600">Sign in</Link></p>
      </form>
    </div>
  );
}
