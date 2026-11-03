import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError, setCsrfToken, setUnauthorizedHandler } from "./api";
import type { PublicConfig, SessionInfo, User } from "./types";

interface AuthCtx {
  user: User | null;
  config: PublicConfig | null;
  status: "loading" | "signed_in" | "signed_out" | "offline";
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  retry: () => void;
}
const Ctx = createContext<AuthCtx>(null as unknown as AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [status, setStatus] = useState<AuthCtx["status"]>("loading");

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      setConfig(await api.get<PublicConfig>("/config"));
    } catch {
      setStatus("offline");
      return;
    }
    try {
      const s = await api.get<SessionInfo>("/auth/me");
      setCsrfToken(s.csrf_token);
      setUser(s.user);
      setStatus("signed_in");
    } catch (e) {
      setStatus(e instanceof ApiError && e.status === 0 ? "offline" : "signed_out");
    }
  }, []);

  useEffect(() => {
    load();
    setUnauthorizedHandler(() => {
      setUser(null);
      setStatus("signed_out");
    });
  }, [load]);

  const login = async (email: string, password: string) => {
    const s = await api.post<SessionInfo>("/auth/login", { email, password });
    setCsrfToken(s.csrf_token);
    setUser(s.user);
    setStatus("signed_in");
    qc.clear();
  };
  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      setCsrfToken(null);
      setUser(null);
      setStatus("signed_out");
      qc.clear();
    }
  };

  return <Ctx.Provider value={{ user, config, status, login, logout, retry: load }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
export const canWrite = (u: User | null) => !!u && u.role !== "viewer";
export const isAdmin = (u: User | null) => !!u && u.role === "admin";
