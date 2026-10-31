"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";

export type Fetched<T> = { data: T | null; error: ApiError | null; loading: boolean; reload: () => void };

/** GET `path` (null = skip). Keeps previous data while refreshing; `refreshMs` polls. */
export function useApi<T = any>(path: string | null, refreshMs?: number): Fetched<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const seq = useRef(0);

  const load = useCallback(async () => {
    if (path === null) return;
    const mine = ++seq.current;
    try {
      const d = await api<T>(path);
      if (mine === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (mine === seq.current) setError(e instanceof ApiError ? e : new ApiError(0, "UNKNOWN", String(e)));
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => { setLoading(path !== null); load(); }, [load, path]);
  useEffect(() => {
    if (!refreshMs || path === null) return;
    const t = setInterval(() => { if (!document.hidden) load(); }, refreshMs);
    return () => clearInterval(t);
  }, [load, refreshMs, path]);

  return { data, error, loading, reload: load };
}

/** Run a mutation with busy / error / success state. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const run = useCallback(async <T,>(fn: () => Promise<T>, success?: string): Promise<T | undefined> => {
    setBusy(true); setError(null); setOk(null);
    try {
      const r = await fn();
      if (success) setOk(success);
      return r;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }, []);
  return { busy, error, ok, run, clear: () => { setError(null); setOk(null); } };
}
