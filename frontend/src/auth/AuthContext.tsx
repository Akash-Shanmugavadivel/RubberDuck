import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setToken } from "../api/client";
import type { User } from "../api/types";

type AuthValue = {
  user: User | null; loading: boolean;
  login(email: string, password: string): Promise<void>;
  register(email: string, password: string): Promise<void>;
  logout(): Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!sessionStorage.getItem("rubberduck_token")) { setLoading(false); return; }
    api.me().then(setUser).catch(() => setToken(null)).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const expireSession = () => setUser(null);
    window.addEventListener("rubberduck:unauthorized", expireSession);
    return () => window.removeEventListener("rubberduck:unauthorized", expireSession);
  }, []);

  const value = useMemo<AuthValue>(() => ({
    user, loading,
    login: async (email, password) => { const result = await api.login(email, password); setToken(result.access_token); setUser(result.user); },
    register: async (email, password) => { await api.register(email, password); const result = await api.login(email, password); setToken(result.access_token); setUser(result.user); },
    logout: async () => { try { await api.logout(); } finally { setToken(null); setUser(null); } },
  }), [user, loading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
