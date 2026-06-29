import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { UploadCloud, CheckCircle2, Trash2, AlertCircle, Circle } from "lucide-react";
import { api } from "../api/endpoints";
import { Button, Card, ErrorBanner, Field, Input, Select, Badge } from "../components/ui";

const LOAN_TYPES = ["HOME", "PERSONAL", "BUSINESS", "AUTO"];

const DOC_GROUPS = [
  { group: "Identity", types: ["AADHAAR", "PAN", "PASSPORT", "VOTER_ID", "DRIVING_LICENSE"] },
  { group: "Income", types: ["SALARY_SLIP", "BANK_STATEMENT", "FORM_16", "ITR", "GST_RETURN"] },
  { group: "Property", types: ["SALE_DEED", "TITLE_DEED", "VALUATION_REPORT", "ENCUMBRANCE_CERTIFICATE", "PROPERTY_TAX", "APPROVED_PLAN"] },
];

// document_type -> category, derived once from DOC_GROUPS
const DOC_CATEGORY = Object.fromEntries(
  DOC_GROUPS.flatMap((g) => g.types.map((t) => [t, g.group]))
);
const CAT_COLORS = { Identity: "#6366f1", Income: "#10b981", Property: "#f59e0b", Other: "#94a3b8" };

function categoryCounts(docs) {
  const counts = { Identity: 0, Income: 0, Property: 0, Other: 0 };
  for (const d of docs) counts[DOC_CATEGORY[d.document_type] || "Other"]++;
  return counts;
}

// Dependency-free SVG donut of the uploaded documents by category. Renders for
// any count >= 1 (a single document shows one full ring).
function DocGraph({ docs }) {
  const total = docs.length;
  if (!total) return null;
  const counts = categoryCounts(docs);
  const present = Object.entries(counts).filter(([, n]) => n > 0);
  const R = 42, CX = 60, CY = 60, C = 2 * Math.PI * R;
  let acc = 0;
  const segs = present.map(([cat, n]) => {
    const len = (n / total) * C;
    const seg = { cat, n, color: CAT_COLORS[cat], dash: `${len} ${C - len}`, off: -acc };
    acc += len;
    return seg;
  });
  return (
    <div className="flex items-center gap-4">
      <svg width="120" height="120" viewBox="0 0 120 120" aria-label="Documents by category">
        <circle cx={CX} cy={CY} r={R} fill="none" stroke="#f1f5f9" strokeWidth="14" />
        {segs.map((s) => (
          <circle key={s.cat} cx={CX} cy={CY} r={R} fill="none" stroke={s.color} strokeWidth="14"
            strokeDasharray={s.dash} strokeDashoffset={s.off}
            transform={`rotate(-90 ${CX} ${CY})`} />
        ))}
        <text x={CX} y={CY - 1} textAnchor="middle" fontSize="22" fontWeight="700" fill="#1e293b">{total}</text>
        <text x={CX} y={CY + 16} textAnchor="middle" fontSize="9" fill="#94a3b8">
          document{total > 1 ? "s" : ""}
        </text>
      </svg>
      <div className="space-y-1 text-sm">
        {present.map(([cat, n]) => (
          <div key={cat} className="flex items-center gap-2">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: CAT_COLORS[cat] }} />
            <span className="text-slate-600">{cat}</span>
            <span className="ml-3 font-medium text-slate-700">{n}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// Per-loan-type required-document checklist (status comes from the backend, which is
// the authoritative gate — this just visualizes it and drives the Submit button).
function RequirementsCard({ reqs }) {
  return (
    <Card title={`Required documents · ${reqs.loan_type} loan`}>
      <ul className="space-y-1.5 text-sm">
        {reqs.groups.map((g) => (
          <li key={g.key} className="flex items-center gap-2">
            {g.ok
              ? <CheckCircle2 size={15} className="shrink-0 text-emerald-500" />
              : g.required
                ? <AlertCircle size={15} className="shrink-0 text-amber-500" />
                : <Circle size={15} className="shrink-0 text-slate-300" />}
            <span className={g.ok ? "text-slate-700" : "text-slate-500"}>{g.label}</span>
            {!g.required && <span className="text-xs text-slate-400">(optional)</span>}
            {g.present.length > 0 && (
              <span className="ml-auto text-xs text-slate-400">{g.present.join(", ")}</span>
            )}
          </li>
        ))}
      </ul>
      <p className={`mt-3 text-xs ${reqs.satisfied ? "text-emerald-600" : "text-amber-600"}`}>
        {reqs.satisfied
          ? "All required documents provided — ready to submit."
          : `Still required: ${reqs.missing_required.join("; ")}`}
      </p>
    </Card>
  );
}

export default function Apply() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [app, setApp] = useState(null);
  const [form, setForm] = useState({ loan_type: "HOME", loan_amount_requested: "" });
  const [docType, setDocType] = useState("AADHAAR");
  const [file, setFile] = useState(null);
  const [uploaded, setUploaded] = useState([]);
  const [reqs, setReqs] = useState(null);          // per-loan-type requirement status
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function loadReqs(appId) {
    try { setReqs(await api.requirements(appId)); } catch { /* non-fatal for UX */ }
  }

  async function createApp(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const created = await api.createApplication({
        loan_type: form.loan_type,
        loan_amount_requested: String(form.loan_amount_requested),
      });
      setApp(created);
      setStep(2);
      loadReqs(created.id);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  async function upload(e) {
    e.preventDefault();
    if (!file) return;
    setBusy(true); setError(null);
    try {
      const fd = new FormData();
      fd.append("document_type", docType);
      fd.append("file", file);
      const doc = await api.uploadDocument(app.id, fd);
      setUploaded((u) => [...u, doc]);
      setFile(null);
      e.target.reset();
      loadReqs(app.id);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  async function removeDoc(docId) {
    setBusy(true); setError(null);
    try {
      await api.deleteDocument(docId);
      setUploaded((u) => u.filter((d) => d.id !== docId));
      loadReqs(app.id);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  async function submitApp() {
    setBusy(true); setError(null);
    try {
      await api.submitApplication(app.id);
      setStep(3);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-semibold text-slate-800">New loan application</h1>
      <div className="flex gap-2 text-sm">
        {["Loan details", "Documents", "Submit"].map((s, i) => (
          <Badge key={s} className={step >= i + 1 ? "bg-brand-100 text-brand-700" : "bg-slate-100 text-slate-400"}>
            {i + 1}. {s}
          </Badge>
        ))}
      </div>
      <ErrorBanner error={error} />

      {step === 1 && (
        <Card title="Loan details">
          <form onSubmit={createApp} className="max-w-md space-y-4">
            <Field label="Loan type">
              <Select value={form.loan_type} onChange={(e) => setForm({ ...form, loan_type: e.target.value })}>
                {LOAN_TYPES.map((t) => <option key={t}>{t}</option>)}
              </Select>
            </Field>
            <Field label="Loan amount (₹)">
              <Input type="number" min="1" required value={form.loan_amount_requested}
                onChange={(e) => setForm({ ...form, loan_amount_requested: e.target.value })} />
            </Field>
            <Button type="submit" loading={busy}>Create & continue</Button>
          </form>
        </Card>
      )}

      {step === 2 && (
        <div className="space-y-4">
          {reqs && <RequirementsCard reqs={reqs} />}
          <div className="grid gap-4 lg:grid-cols-2">
          <Card title={`Upload documents · ${app.application_number}`}>
            <form onSubmit={upload} className="space-y-4">
              <Field label="Document type">
                <Select value={docType} onChange={(e) => setDocType(e.target.value)}>
                  {DOC_GROUPS.map((g) => (
                    <optgroup key={g.group} label={g.group}>
                      {g.types.map((t) => <option key={t}>{t}</option>)}
                    </optgroup>
                  ))}
                </Select>
              </Field>
              <Field label="File" hint="PDF / PNG / JPEG / TIFF, up to 25 MB">
                <Input type="file" accept=".pdf,.png,.jpg,.jpeg,.tiff" onChange={(e) => setFile(e.target.files[0])} />
              </Field>
              <Button type="submit" loading={busy} disabled={!file}><UploadCloud size={15} /> Upload</Button>
            </form>
          </Card>
          <Card title={`Uploaded (${uploaded.length})`}>
            {uploaded.length ? (
              <div className="space-y-4">
                {/* Documents graph — composition by category (renders for 1+ docs) */}
                <DocGraph docs={uploaded} />

                {/* Summary of what's been submitted */}
                <p className="text-xs text-slate-500">
                  {uploaded.length} document{uploaded.length > 1 ? "s" : ""} attached to this draft —{" "}
                  {Object.entries(categoryCounts(uploaded))
                    .filter(([, n]) => n > 0)
                    .map(([cat, n]) => `${n} ${cat}`)
                    .join(" · ")}
                  . Remove any wrong file before submitting.
                </p>

                {/* List with per-document cancel/remove */}
                <ul className="space-y-2">
                  {uploaded.map((d) => (
                    <li key={d.id} className="flex items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2 text-sm">
                      <span className="flex min-w-0 items-center">
                        <CheckCircle2 size={14} className="mr-1 inline shrink-0 text-emerald-500" />
                        <span className="font-medium text-slate-700">{d.document_type}</span>
                        <span className="ml-2 truncate text-xs text-slate-400">{d.original_filename}</span>
                      </span>
                      <button
                        type="button"
                        onClick={() => removeDoc(d.id)}
                        disabled={busy}
                        title="Remove this document"
                        aria-label={`Remove ${d.document_type}`}
                        className="shrink-0 rounded p-1 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
                      >
                        <Trash2 size={15} />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : <p className="text-sm text-slate-400">No documents uploaded yet.</p>}
            <div className="mt-4">
              <Button
                onClick={submitApp}
                loading={busy}
                disabled={!uploaded.length || (reqs && !reqs.satisfied)}
              >
                Submit for analysis
              </Button>
              {reqs && !reqs.satisfied && (
                <p className="mt-2 text-xs text-amber-600">
                  Provide all required documents above before submitting.
                </p>
              )}
            </div>
          </Card>
          </div>
        </div>
      )}

      {step === 3 && (
        <Card>
          <div className="flex flex-col items-center gap-3 py-8 text-center">
            <CheckCircle2 size={40} className="text-emerald-500" />
            <h2 className="text-lg font-semibold text-slate-800">Application submitted</h2>
            <p className="max-w-md text-sm text-slate-500">
              {app.application_number} is queued for the analysis pipeline (OCR → extraction → fraud →
              identity → property/financial → graph → risk). Results appear on the detail page as they complete.
            </p>
            <div className="flex gap-2">
              <Button onClick={() => navigate(`/app/applications/${app.id}`)}>View application</Button>
              <Button variant="secondary" onClick={() => { setStep(1); setApp(null); setUploaded([]); }}>New application</Button>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
