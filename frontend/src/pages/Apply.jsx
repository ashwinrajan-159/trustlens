import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { UploadCloud, CheckCircle2, Trash2 } from "lucide-react";
import { api } from "../api/endpoints";
import { Button, Card, ErrorBanner, Field, Input, Select, Badge } from "../components/ui";

const LOAN_TYPES = ["HOME", "PERSONAL", "BUSINESS", "AUTO"];

const DOC_GROUPS = [
  { group: "Identity", types: ["AADHAAR", "PAN", "PASSPORT", "VOTER_ID", "DRIVING_LICENSE"] },
  { group: "Income", types: ["SALARY_SLIP", "BANK_STATEMENT", "FORM_16", "ITR", "GST_RETURN"] },
  { group: "Property", types: ["SALE_DEED", "TITLE_DEED", "VALUATION_REPORT", "ENCUMBRANCE_CERTIFICATE", "PROPERTY_TAX", "APPROVED_PLAN"] },
];

export default function Apply() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [app, setApp] = useState(null);
  const [form, setForm] = useState({ loan_type: "HOME", loan_amount_requested: "" });
  const [docType, setDocType] = useState("AADHAAR");
  const [file, setFile] = useState(null);
  const [uploaded, setUploaded] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

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
              <ul className="space-y-2">
                {uploaded.map((d) => (
                  <li key={d.id} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm">
                    <span><CheckCircle2 size={14} className="mr-1 inline text-emerald-500" />{d.document_type}</span>
                    <span className="text-xs text-slate-400">{d.original_filename}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-slate-400">No documents uploaded yet.</p>}
            <div className="mt-4">
              <Button onClick={submitApp} loading={busy} disabled={!uploaded.length}>Submit for analysis</Button>
            </div>
          </Card>
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
