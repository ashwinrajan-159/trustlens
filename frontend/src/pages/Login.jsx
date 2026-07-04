import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { Button, ErrorBanner, Field, Input } from "../components/ui";

export default function Login() {
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ email: "", password: "", mfa_code: "" });
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [needMfa, setNeedMfa] = useState(false);

  if (isAuthenticated) return <Navigate to="/app/dashboard" replace />;

  async function submit(e) {
    e.preventDefault();
    setLoading(true); setError(null);
    try {
      await login(form.email, form.password, needMfa ? form.mfa_code : undefined);
      navigate("/app/dashboard");
    } catch (err) {
      if (err.message?.toLowerCase().includes("mfa")) setNeedMfa(true);
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="glass w-full max-w-sm space-y-4 p-8">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-ink text-white shadow-sm"><ShieldCheck size={20} /></span>
          <span className="text-lg font-bold text-stone-800">TrustLens</span>
        </div>
        <h1 className="text-xl font-semibold text-stone-800">Sign in</h1>
        <ErrorBanner error={error} />
        <Field label="Email"><Input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
        <Field label="Password"><Input type="password" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
        {needMfa && <Field label="MFA code" hint="Required for analyst accounts with MFA enabled"><Input value={form.mfa_code} onChange={(e) => setForm({ ...form, mfa_code: e.target.value })} /></Field>}
        <Button type="submit" loading={loading} className="w-full">Sign in</Button>
        <p className="text-center text-sm text-stone-500">No account? <Link to="/register" className="font-medium text-brand-700 hover:text-brand-800">Register</Link></p>
      </form>
    </div>
  );
}
