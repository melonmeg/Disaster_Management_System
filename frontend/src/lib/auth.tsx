"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { loadSession, login as apiLogin, logout as apiLogout, setSessionLostHandler, type User } from "./api";

type Ctx = {
  user: User | null;
  ready: boolean;
  login: (u: string, p: string) => Promise<void>;
  logout: () => Promise<void>;
  can: (...roles: User["role"][]) => boolean;
};
const AuthContext = createContext<Ctx | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setUser(loadSession()?.user ?? null);
    setReady(true);
    setSessionLostHandler(() => { setUser(null); router.replace("/login?expired=1"); });
    return () => setSessionLostHandler(null);
  }, [router]);

  const login = useCallback(async (u: string, p: string) => setUser(await apiLogin(u, p)), []);
  const logout = useCallback(async () => { await apiLogout(); setUser(null); router.replace("/login"); }, [router]);
  const can = useCallback((...roles: User["role"][]) => !!user && roles.includes(user.role), [user]);

  return <AuthContext.Provider value={{ user, ready, login, logout, can }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
