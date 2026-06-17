import { useState } from "react";
import { api } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { Button, Card, ErrorBanner, Field, Input, Badge } from "../components/ui";

export default function Account() {
  const { user, role } = useAuth();
  const [enroll, setEnroll] = useState(null);
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);

  async function startMfa() {
    setError(null); setMsg(null);
    try { setEnroll(await api.mfaEnroll()); } catch (e) { setError(e); }
  }
  async function verifyMfa() {
    setError(null);
    try { await api.mfaVerify(code); setMsg("MFA enabled."); setEnroll(null); } catch (e) { setError(e); }
  }
  async function withdraw() {
    setError(null); setMsg(null);
    try { await api.withdrawConsent(); setMsg("Consent withdrawal recorded (DPDP)."); } catch (e) { setError(e); }
  }

  return (
    <div className="max-w-xl space-y-5">
      <h1 className="text-2xl font-semibold text-slate-800">Account</h1>
      {msg && <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{msg}</div>}
      <ErrorBanner error={error} />

      <Card title="Profile">
        <div className="space-y-1 text-sm">
          <div><span className="text-slate-400">Name:</span> {user?.full_name}</div>
          <div><span className="text-slate-400">Email:</span> {user?.email}</div>
          <div><span className="text-slate-400">Role:</span> <Badge className="bg-brand-100 text-brand-700">{role}</Badge></div>
        </div>
      </Card>

      <Card title="Multi-factor authentication (TOTP)">
        {!enroll ? (
          <Button variant="secondary" onClick={startMfa}>Enroll in MFA</Button>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-slate-500">Add this secret to your authenticator app, then enter a code to confirm.</p>
            <div className="rounded bg-slate-100 px-3 py-2 font-mono text-sm">{enroll.secret}</div>
            <a href={enroll.provisioning_uri} className="text-xs text-brand-600 break-all">{enroll.provisioning_uri}</a>
            <Field label="6-digit code"><Input value={code} onChange={(e) => setCode(e.target.value)} /></Field>
            <Button onClick={verifyMfa} disabled={!code}>Verify & enable</Button>
          </div>
        )}
      </Card>

      <Card title="Data privacy (DPDP Act 2023)">
        <p className="mb-3 text-sm text-slate-500">You may withdraw consent to processing of your personal data. This is recorded in the immutable audit trail and triggers the data-erasure workflow.</p>
        <Button variant="danger" onClick={withdraw}>Withdraw consent</Button>
      </Card>
    </div>
  );
}
