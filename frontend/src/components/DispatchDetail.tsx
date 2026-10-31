"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAction, useApi } from "@/lib/hooks";
import { DISPATCH_NEXT, dt, label } from "@/lib/format";
import { Async, Badge, ErrorBox, Field, Notice } from "./ui";

/** One dispatch: status changes, allocated resources, allocation and returns. The server validates everything. */
export function DispatchDetail({ dispatchId, onChanged }: { dispatchId: number; onChanged?: () => void }) {
  const { can, user } = useAuth();
  const d = useApi<any>(`/dispatches/${dispatchId}`);
  const res = useApi<any>(can("admin", "dispatcher") ? "/resources?page_size=100" : null);
  const act = useAction();
  const [resourceId, setResourceId] = useState("");
  const [qty, setQty] = useState("1");
  const [returnQty, setReturnQty] = useState<Record<number, string>>({});

  const changed = () => { d.reload(); res.reload(); onChanged?.(); };
  const selected = res.data?.data.find((r: any) => String(r.resource_id) === resourceId);
  const over = selected && Number(qty) > selected.quantity_available;

  return (
    <Async state={d}>{(x) => {
      const next = DISPATCH_NEXT[x.status] ?? [];
      const finished = next.length === 0;
      return <div>
        <div className="row"><strong>Dispatch #{x.dispatch_id}</strong><Badge value={x.status} /> <span className="muted">{x.unit_name} → #{x.incident_id} {x.incident_type}</span></div>
        <div className="small-text muted">Dispatched {dt(x.dispatched_at)}</div>
        <ErrorBox error={act.error} />
        {act.ok && <Notice kind="ok">{act.ok}</Notice>}

        {next.length > 0 && (
          <div className="row" style={{ margin: "8px 0" }}>
            <span className="small-text">Move to:</span>
            {next.map((s) => (
              <button key={s} className={`btn small ${s === "CANCELLED" ? "danger" : ""}`} disabled={act.busy}
                onClick={() => { if (s !== "CANCELLED" || confirm("Cancel this dispatch?")) act.run(async () => { await api(`/dispatches/${x.dispatch_id}/status`, { method: "PATCH", json: { status: s } }); changed(); }, `Status set to ${label(s)}`); }}>
                {label(s)}
              </button>))}
          </div>)}

        <h3>Allocated resources</h3>
        {x.resources.length === 0 ? <p className="muted small-text">None allocated.</p> :
          <div className="tablewrap"><table><thead><tr><th>Resource</th><th>Assigned</th><th>Returned</th><th>Outstanding</th><th /></tr></thead><tbody>
            {x.resources.map((r: any) => (
              <tr key={r.dispatch_resource_id}><td>{r.resource_name}</td><td>{r.quantity_assigned}</td><td>{r.quantity_returned}</td><td>{r.quantity_outstanding}</td>
                <td>{r.quantity_outstanding > 0 && (can("admin", "dispatcher") || user?.role === "responder") && (
                  <span className="row">
                    <input aria-label={`Quantity of ${r.resource_name} to return`} type="number" min={1} max={r.quantity_outstanding} style={{ width: 70 }}
                      value={returnQty[r.resource_id] ?? String(r.quantity_outstanding)} onChange={(e) => setReturnQty({ ...returnQty, [r.resource_id]: e.target.value })} />
                    <button className="btn small" disabled={act.busy} onClick={() => act.run(async () => {
                      await api(`/dispatches/${x.dispatch_id}/resources/${r.resource_id}/return`, { method: "POST", json: { quantity: Number(returnQty[r.resource_id] ?? r.quantity_outstanding) } }); changed();
                    }, "Resource returned")}>Return</button>
                  </span>)}</td></tr>))}
          </tbody></table></div>}

        {can("admin", "dispatcher") && !finished && (
          <>
            <h3>Allocate a resource</h3>
            <Async state={res}>{(r) => (
              <form className="filters" onSubmit={(e) => { e.preventDefault(); act.run(async () => { await api(`/dispatches/${x.dispatch_id}/resources`, { method: "POST", json: { resource_id: Number(resourceId), quantity: Number(qty) } }); setQty("1"); changed(); }, "Resource allocated"); }}>
                <Field label="Resource"><select value={resourceId} onChange={(e) => setResourceId(e.target.value)} required><option value="">Select…</option>
                  {r.data.map((o: any) => <option key={o.resource_id} value={o.resource_id} disabled={o.quantity_available === 0}>{o.resource_name} ({o.quantity_available} available)</option>)}</select></Field>
                <Field label="Quantity"><input type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} required style={{ width: 90 }} /></Field>
                <button className="btn primary" disabled={act.busy || !resourceId}>Allocate</button>
                {over && <Notice kind="warn">Requested {qty} but only {selected.quantity_available} available; the server will refuse this.</Notice>}
              </form>)}</Async>
          </>)}
      </div>;
    }}</Async>
  );
}
