"use client";
import Link from "next/link";
import { useState } from "react";
import { api, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAction, useApi } from "@/lib/hooks";
import { dt, label } from "@/lib/format";
import { Async, Badge, ErrorBox, Field, Modal, Notice, PageHeader, Pagination } from "@/components/ui";
import { DispatchDetail } from "@/components/DispatchDetail";

const STATUSES = ["DISPATCHED", "EN_ROUTE", "ON_SCENE", "COMPLETED", "CANCELLED"];

function NewDispatch({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const incidents = useApi<any>("/incidents?unresolved=true&sort=severity&page_size=100");
  const units = useApi<any>("/units?available=true&page_size=100");
  const [incidentId, setIncidentId] = useState("");
  const [unitId, setUnitId] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const { busy, error, run } = useAction();
  const incident = incidents.data?.data.find((i: any) => String(i.incident_id) === incidentId);
  const unit = units.data?.data.find((u: any) => String(u.unit_id) === unitId);

  return (
    <Modal title="New dispatch" onClose={onClose}>
      <form onSubmit={async (e) => { e.preventDefault(); const ok = await run(() => api("/dispatches", { method: "POST", json: { incident_id: Number(incidentId), unit_id: Number(unitId) } })); if (ok) { onCreated(); onClose(); } }}>
        <Async state={incidents}>{(d) => <Field label="Incident (unresolved)"><select value={incidentId} onChange={(e) => setIncidentId(e.target.value)} required><option value="">Select…</option>
          {d.data.map((i: any) => <option key={i.incident_id} value={i.incident_id}>#{i.incident_id} {i.incident_type} · {i.severity} · {i.location}</option>)}</select></Field>}</Async>
        <Async state={units}>{(d) => d.data.length === 0 ? <Notice kind="warn">No unit is currently available.</Notice> :
          <Field label="Available unit"><select value={unitId} onChange={(e) => setUnitId(e.target.value)} required><option value="">Select…</option>
            {d.data.map((u: any) => <option key={u.unit_id} value={u.unit_id}>{u.unit_name} — {u.unit_type} ({u.organization_name})</option>)}</select></Field>}</Async>
        {incident && unit && <Notice>Dispatch <strong>{unit.unit_name}</strong> to <strong>#{incident.incident_id} {incident.incident_type}</strong> at {incident.location}.</Notice>}
        <label className="row"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /> I confirm this dispatch.</label>
        <ErrorBox error={error} />
        <div className="row" style={{ marginTop: 10 }}><button className="btn primary" disabled={busy || !confirmed || !incidentId || !unitId}>{busy ? "Dispatching…" : "Create dispatch"}</button></div>
      </form>
    </Modal>
  );
}

export default function DispatchesPage() {
  const { can } = useAuth();
  const [status, setStatus] = useState("");
  const [active, setActive] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const list = useApi<any>(`/dispatches${qs({ status, active, page, page_size: 15 })}`, 30_000);

  return (
    <>
      <PageHeader title="Dispatches">{can("admin", "dispatcher") && <button className="btn primary" onClick={() => setCreating(true)}>New dispatch</button>}</PageHeader>
      <div className="filters">
        <Field label="Status"><select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}><option value="">All</option>{STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}</select></Field>
        <Field label="Scope"><select value={active} onChange={(e) => { setActive(e.target.value); setPage(1); }}><option value="">All</option><option value="true">Active only</option><option value="false">Finished only</option></select></Field>
      </div>
      <Async state={list} empty={(d) => d.data.length === 0}>{(d) => <>
        <div className="card tablewrap"><table><thead><tr><th>ID</th><th>Unit</th><th>Incident</th><th>Status</th><th>Dispatched</th><th /></tr></thead><tbody>
          {d.data.map((x: any) => <tr key={x.dispatch_id}><td>#{x.dispatch_id}</td><td>{x.unit_name}<div className="muted small-text">{x.unit_type}</div></td>
            <td><Link href={`/incidents/${x.incident_id}`}>#{x.incident_id} {x.incident_type}</Link><div className="muted small-text">{x.location}</div></td>
            <td><Badge value={x.status} /></td><td>{dt(x.dispatched_at)}</td><td><button className="btn small" onClick={() => setOpen(x.dispatch_id)}>Details</button></td></tr>)}
        </tbody></table></div>
        <Pagination page={page} totalPages={d.pagination.total_pages} onPage={setPage} />
      </>}</Async>
      {creating && <NewDispatch onClose={() => setCreating(false)} onCreated={list.reload} />}
      {open !== null && <Modal title="Dispatch" onClose={() => setOpen(null)}><DispatchDetail dispatchId={open} onChanged={list.reload} /></Modal>}
    </>
  );
}
