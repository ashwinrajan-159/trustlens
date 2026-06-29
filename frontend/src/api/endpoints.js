// Thin, typed-ish wrappers over every backend service so pages never build URLs.
import { req, downloadBlob } from "./client";

export const api = {
  // ── auth ──
  register: (data) => req("/auth/register", { method: "POST", body: data, auth: false }),
  login: (data) => req("/auth/login", { method: "POST", body: data, auth: false }),
  logout: (refresh_token) => req("/auth/logout", { method: "POST", body: { refresh_token }, auth: false }),
  me: () => req("/auth/me"),
  mfaEnroll: () => req("/auth/mfa/enroll", { method: "POST" }),
  mfaVerify: (code) => req("/auth/mfa/verify", { method: "POST", body: { code } }),
  withdrawConsent: () => req("/auth/consent/withdraw", { method: "POST" }),

  // ── applications ──
  createApplication: (data) => req("/applications", { method: "POST", body: data }),
  listApplications: (q = "") => req(`/applications${q}`),
  getApplication: (id) => req(`/applications/${id}`),
  submitApplication: (id) => req(`/applications/${id}/submit`, { method: "POST" }),
  deleteApplication: (id) => req(`/applications/${id}`, { method: "DELETE" }),
  decide: (id, data) => req(`/applications/${id}/decision`, { method: "POST", body: data }),
  signals: (id) => req(`/applications/${id}/signals`),
  risk: (id) => req(`/applications/${id}/risk`),
  identity: (id) => req(`/applications/${id}/identity`),
  property: (id) => req(`/applications/${id}/property`),
  financial: (id) => req(`/applications/${id}/financial`),
  graph: (id) => req(`/applications/${id}/graph`),
  network: (id) => req(`/applications/${id}/network`),
  completeness: (id) => req(`/applications/${id}/completeness`),
  requirements: (id) => req(`/applications/${id}/requirements`),
  appEntities: (id) => req(`/applications/${id}/entities`),
  regulatoryReport: (id) => downloadBlob(`/applications/${id}/regulatory-report`),

  // ── documents ──
  listDocuments: (appId) => req(`/applications/${appId}/documents`),
  uploadDocument: (appId, formData) => req(`/applications/${appId}/documents`, { method: "POST", formData }),
  getDocument: (id) => req(`/documents/${id}`),
  documentEntities: (id) => req(`/documents/${id}/entities`),
  downloadDocument: (id) => req(`/documents/${id}/download`),
  deleteDocument: (id) => req(`/documents/${id}`, { method: "DELETE" }),

  // ── alerts ──
  listAlerts: (q = "") => req(`/alerts${q}`),
  getAlert: (id) => req(`/alerts/${id}`),
  ackAlert: (id) => req(`/alerts/${id}/acknowledge`, { method: "POST" }),
  resolveAlert: (id, dismiss = false) => req(`/alerts/${id}/resolve`, { method: "POST", body: { dismiss } }),
  fmrReport: (id) => req(`/alerts/${id}/fmr-report`),
  claimAlert: (id) => req(`/alerts/${id}/claim`, { method: "POST" }),
  transitionAlert: (id, target_status, reason = "") =>
    req(`/alerts/${id}/transition`, { method: "POST", body: { target_status, reason } }),

  // ── fraud-ops closed loop ──
  submitInvestigation: (alertId, data) =>
    req(`/alerts/${alertId}/investigation`, { method: "POST", body: data }),
  listInvestigations: (alertId) => req(`/alerts/${alertId}/investigations`),
  reviewQueue: () => req("/reviews/queue"),
  recordReview: (reportId, data) => req(`/reports/${reportId}/review`, { method: "POST", body: data }),
  patterns: () => req("/knowledge/patterns"),
  mergePatterns: (source_id, target_id) =>
    req("/knowledge/patterns/merge", { method: "POST", body: { source_id, target_id } }),
  signalAnalytics: () => req("/signal-analytics"),
  weights: () => req("/weights"),
  proposeWeights: (weights, rationale) =>
    req("/weights/propose", { method: "POST", body: { weights, rationale } }),
  activateWeights: (configId) => req(`/weights/${configId}/activate`, { method: "POST" }),

  // ── cases ──
  listCases: (q = "") => req(`/cases${q}`),
  getCase: (id) => req(`/cases/${id}`),
  createCase: (data) => req("/cases", { method: "POST", body: data }),
  assignCase: (id, assignee) => req(`/cases/${id}/assign`, { method: "POST", body: { assignee } }),
  closeCase: (id, outcome) => req(`/cases/${id}/close`, { method: "POST", body: { outcome } }),

  // ── operations ──
  opsOverview: () => req("/operations/overview"),
  activeThreats: () => req("/operations/active-threats"),
  slaBreaches: () => req("/operations/sla-breaches"),
  events: (q = "") => req(`/operations/events${q}`),
  replayEvents: () => req("/operations/events/replay", { method: "POST" }),

  // ── ml ──
  mlModels: () => req("/ml/models"),
  mlTrain: (data) => req("/ml/train", { method: "POST", body: data }),
  mlApprove: (id) => req(`/ml/models/${id}/approve`, { method: "POST" }),
  mlReject: (id, reason) => req(`/ml/models/${id}/reject`, { method: "POST", body: { reason } }),
  mlPromote: (id) => req(`/ml/models/${id}/promote`, { method: "POST" }),
  mlPredict: (appId) => req(`/ml/predict/${appId}`, { method: "POST" }),
  mlExplain: (appId) => req(`/ml/explain/${appId}`),
  mlDrift: () => req("/ml/drift"),
};
