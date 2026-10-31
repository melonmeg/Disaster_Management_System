"use client";
import { useEffect, useRef } from "react";
import { label } from "@/lib/format";

export function Badge({ value, kind }: { value?: string | null; kind?: "severity" | "status" }) {
  const v = value ?? "UNKNOWN";
  return <span className={`badge ${kind ?? "status"}-${v}`}>{label(v)}</span>;
}

export function Spinner({ text = "Loading…" }: { text?: string }) {
  return <div className="state" role="status" aria-live="polite"><span className="spin" aria-hidden /> {text}</div>;
}

export function ErrorBox({ error, onRetry }: { error: { message: string } | string | null; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div className="alert error" role="alert">
      <span>{typeof error === "string" ? error : error.message}</span>
      {onRetry && <button className="btn small" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Notice({ kind = "info", children }: { kind?: "info" | "warn" | "ok"; children: React.ReactNode }) {
  return <div className={`alert ${kind}`} role={kind === "warn" ? "alert" : "status"}>{children}</div>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="state empty">{children}</div>;
}

export function Card({ title, actions, className, children }: { title?: string; actions?: React.ReactNode; className?: string; children: React.ReactNode }) {
  return (
    <section className={className ? `card ${className}` : "card"}>
      {(title || actions) && <header className="card-head"><h2>{title}</h2><div>{actions}</div></header>}
      {children}
    </section>
  );
}

export function PageHeader({ title, children }: { title: string; children?: React.ReactNode }) {
  return <div className="page-head"><h1>{title}</h1><div className="row">{children}</div></div>;
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return (
    <dialog ref={ref} className="modal" onClose={onClose} aria-label={title}>
      <header className="card-head"><h2>{title}</h2><button className="btn small" onClick={() => ref.current?.close()} aria-label="Close dialog">✕</button></header>
      {children}
    </dialog>
  );
}

export function Field({ label: text, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return <label className="field"><span>{text}</span>{children}{hint && <small>{hint}</small>}</label>;
}

export function Pagination({ page, totalPages, onPage }: { page: number; totalPages: number; onPage: (p: number) => void }) {
  if (totalPages <= 1) return null;
  return (
    <nav className="row pager" aria-label="Pagination">
      <button className="btn small" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
      <span>Page {page} of {totalPages}</span>
      <button className="btn small" disabled={page >= totalPages} onClick={() => onPage(page + 1)}>Next</button>
    </nav>
  );
}

/** Wrap a request's loading / error / empty states around its content. */
export function Async({ state, empty, emptyText = "Nothing to show.", children }: {
  state: { loading: boolean; error: { message: string } | null; data: any; reload: () => void };
  empty?: (data: any) => boolean;
  emptyText?: string;
  children: (data: any) => React.ReactNode;
}) {
  if (state.loading && !state.data) return <Spinner />;
  if (state.error && !state.data) return <ErrorBox error={state.error} onRetry={state.reload} />;
  if (!state.data) return null;
  return <>
    {state.error && <ErrorBox error={state.error} onRetry={state.reload} />}
    {empty?.(state.data) ? <Empty>{emptyText}</Empty> : children(state.data)}
  </>;
}
