import { createContext, useContext, useEffect, useState } from "react";
import { api } from "../api/endpoints";
import { tokens } from "../api/client";

const AuthCtx = createContext(null);

const ANALYST_ROLES = new Set(["ANALYST", "SENIOR_ANALYST", "ADMIN"]);
const SENIOR_ROLES = new Set(["SENIOR_ANALYST", "ADMIN"]);

function decodeRole(access) {
  try {
    const payload = JSON.parse(atob(access.split(".")[1]));
    return payload.role || null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  async function bootstrap() {
    if (!tokens.access) { setLoading(false); return; }
    try {
      const me = await api.me();
      setUser(me);
    } catch {
      tokens.clear();
      setUser(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { bootstrap(); }, []);

  async function login(email, password, mfa_code) {
    const t = await api.login({ email, password, mfa_code: mfa_code || null });
    tokens.set(t);
    setUser(await api.me());
  }

  async function register(data) {
    const res = await api.register(data);
    tokens.set(res.tokens);
    setUser(res.user);
  }

  async function logout() {
    try { if (tokens.refresh) await api.logout(tokens.refresh); } catch { /* ignore */ }
    tokens.clear();
    setUser(null);
  }

  const role = user?.role || (tokens.access ? decodeRole(tokens.access) : null);
  const value = {
    user, role, loading,
    isAuthenticated: !!user,
    isAnalyst: ANALYST_ROLES.has(role),
    isSenior: SENIOR_ROLES.has(role),
    isAdmin: role === "ADMIN",
    login, register, logout, refreshUser: bootstrap,
  };
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
