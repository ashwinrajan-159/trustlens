// Single API client. One req() helper; bearer token from storage; transparent
// access-token refresh on 401 (once), then retry. Errors surface the backend's
// {error:{code,message}} envelope as a thrown ApiError.

const BASE = import.meta.env.VITE_API_BASE || "/api/v1";

const store = {
  get access() { return localStorage.getItem("tl_access"); },
  get refresh() { return localStorage.getItem("tl_refresh"); },
  set({ access_token, refresh_token }) {
    if (access_token) localStorage.setItem("tl_access", access_token);
    if (refresh_token) localStorage.setItem("tl_refresh", refresh_token);
  },
  clear() {
    localStorage.removeItem("tl_access");
    localStorage.removeItem("tl_refresh");
  },
};

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message || code || `HTTP ${status}`);
    this.status = status;
    this.code = code;
  }
}

let refreshing = null;

async function doRefresh() {
  if (!store.refresh) return false;
  if (!refreshing) {
    refreshing = fetch(`${BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: store.refresh }),
    })
      .then(async (r) => {
        if (!r.ok) return false;
        store.set(await r.json());
        return true;
      })
      .catch(() => false)
      .finally(() => { refreshing = null; });
  }
  return refreshing;
}

async function parse(res) {
  const text = await res.text();
  if (!text) return null;
  try { return JSON.parse(text); } catch { return text; }
}

export async function req(path, { method = "GET", body, formData, auth = true, retry = true } = {}) {
  const headers = {};
  if (auth && store.access) headers.Authorization = `Bearer ${store.access}`;
  let payload;
  if (formData) {
    payload = formData; // browser sets multipart boundary
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const res = await fetch(`${BASE}${path}`, { method, headers, body: payload });

  if (res.status === 401 && auth && retry && (await doRefresh())) {
    return req(path, { method, body, formData, auth, retry: false });
  }

  const data = await parse(res);
  if (!res.ok) {
    const err = data && data.error ? data.error : {};
    throw new ApiError(res.status, err.code, err.message || (typeof data === "string" ? data : `Request failed (${res.status})`));
  }
  return data;
}

// Fetch a binary artifact (e.g. a PDF report) and trigger a browser download.
// Reuses the same bearer token + one-shot refresh as req(), but returns a Blob
// instead of parsing JSON.
export async function downloadBlob(path, { filename, retry = true } = {}) {
  const headers = {};
  if (store.access) headers.Authorization = `Bearer ${store.access}`;

  const res = await fetch(`${BASE}${path}`, { method: "GET", headers });

  if (res.status === 401 && retry && (await doRefresh())) {
    return downloadBlob(path, { filename, retry: false });
  }
  if (!res.ok) {
    const data = await parse(res);
    const err = data && data.error ? data.error : {};
    throw new ApiError(res.status, err.code, err.message || `Download failed (${res.status})`);
  }

  // Prefer the server's Content-Disposition filename when present.
  let name = filename;
  const cd = res.headers.get("Content-Disposition") || "";
  const m = cd.match(/filename="?([^"]+)"?/i);
  if (m) name = m[1];

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name || "download";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export const tokens = store;
