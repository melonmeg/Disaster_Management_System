"use client";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useAction } from "@/lib/hooks";
import { ErrorBox, Field, Notice } from "@/components/ui";

function LoginForm() {
  const { login } = useAuth();
  const router = useRouter();
  const expired = useSearchParams().get("expired");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, run } = useAction();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const ok = await run(async () => { await login(username, password); return true; });
    if (ok) router.replace("/dashboard");
  };

  return (
    <main className="login">
      <form className="card" onSubmit={submit}>
        <h1>ERMS Dispatcher Console</h1>
        <p className="muted">Sign in with your application account.</p>
        {expired && <Notice kind="warn">Your session expired. Please sign in again.</Notice>}
        <Field label="Username"><input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required autoFocus /></Field>
        <Field label="Password"><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></Field>
        <ErrorBox error={error} />
        <button className="btn primary" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </main>
  );
}

export default function LoginPage() {
  return <Suspense><LoginForm /></Suspense>;
}
