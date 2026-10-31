"use client";
import Link from "next/link";
import { useState } from "react";
import { api, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAction, useApi } from "@/lib/hooks";
import { dt, label } from "@/lib/format";
import { Async, Badge, ErrorBox, Field, Modal, Notice, PageHeader } from "@/components/ui";

function unitState(u: any) {
  if (u.status === "OUT_OF_SERVICE") return "OUT_OF_SERVICE";
  return u.is_free ? "AVAILABLE" : "DISPATCHED";
}

function UnitForm({ unit, onClose, onSaved }: { unit?: any; onClose: () => void; onSaved: () => void }) {
  const orgs = useApi<any>(unit ? null : "/organizations?page_size=100");
  const [name, setName] = useState(unit?.unit_name ?? "");
  const [type, setType] = useState(unit?.unit_type ?? "");
  const [base, setBase] = useState(unit?.base_location ?? "");
  const [status, setStatus] = useState(unit?.status === "OUT_OF_SERVICE" ? "OUT_OF_SERVICE" : "AVAILABLE");
  const [org, setOrg] = useState("");
  const { busy, error, run } = useAction();
  return (
    <Modal title={unit ? `Edit ${unit.unit_name}` : "New unit"} onClose={onClose}>
      <form onSubmit={async (e) => {
        e.preventDefault();
        const body = { unit_name: name, unit_type: type || null, base_location: base || null, status };
        const ok = await run(() => unit ? api(`/units/${unit.unit_id}`, { method: "PATCH", json: body }) : api("/units", { method: "POST", json: { ...body, organization_id: Number(org) } }));
        if (ok) { onSaved(); onClose(); }
      }}>
        <Field label="Name"><input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} required /></Field>
        <Field label="Type (capability)" hint="e.g. Ambulance, Fire Truck, Police Car, Rescue Vehicle — recommendations match on this."><input value={type} onChange={(e) => setType(e.target.value)} maxLength={50} /></Field>
        <Field label="Base location"><input value={base} onChange={(e) => setBase(e.target.value)} maxLength={255} /></Field>
        <Field label="Status" hint="DISPATCHED is set by the database when a unit is dispatched."><select value={status} onChange={(e) => setStatus(e.target.value)}><option value="AVAILABLE">AVAILABLE</option><option value="OUT_OF_SERVICE">OUT OF SERVICE</option></select></Field>
        {!unit && <Field label="Organisation"><select value={org} onChange={(e) => setOrg(e.target.value)} required><option value="">Select…</option>{orgs.data?.data.map((o: any) => <option key={o.organization_id} value={o.organization_id}>{o.organization_name}</option>)}</select></Field>}
        <ErrorBox error={error} /><button className="btn primary" disabled={busy}>Save</button>
      </form>
    </Modal>
  );
}

function UnitDetail({ unitId, onChanged }: { unitId: number; onChanged: () => void }) {
  const { can } = useAuth();
  const unit = useApi<any>(`/units/${unitId}`);
  const crew = useApi<any>(`/units/${unitId}/responders`);
  const candidates = useApi<any>(can("admin", "dispatcher") && unit.data ? `/responders?organization_id=${unit.data.organization_id}&page_size=100` : null);
  const [pick, setPick] = useState("");
  const act = useAction();
  const reload = () => { unit.reload(); crew.reload(); candidates.reload(); onChanged(); };
  const unassigned = (candidates.data?.data ?? []).filter((r: any) => r.unit_id === null && r.responder_type !== "Dispatcher");

  return (
    <Async state={unit}>{(u) => <div>
      <p><Badge value={unitState(u)} /> {u.unit_type ?? "no type"} · {u.organization_name} · base: {u.base_location ?? "unknown"}</p>
      <h3>Active assignments</h3>
      {u.active_dispatches.length === 0 ? <p className="muted small-text">None.</p> : <ul>{u.active_dispatches.map((d: any) => <li key={d.dispatch_id}><Link href={`/incidents/${d.incident_id}`}>#{d.incident_id} {d.incident_type}</Link> — <Badge value={d.dispatch_status} /> since {dt(d.dispatched_at)}</li>)}</ul>}
      <h3>Responders ({crew.data?.data.length ?? "…"})</h3>
      <ErrorBox error={act.error} />{act.ok && <Notice kind="ok">{act.ok}</Notice>}
      <Async state={crew} empty={(d) => d.data.length === 0}>{(d) => <div className="tablewrap"><table><thead><tr><th>Name</th><th>Role</th><th>Availability</th><th /></tr></thead><tbody>
        {d.data.map((r: any) => <tr key={r.responder_id}><td>{r.full_name}</td><td>{r.responder_type ?? "—"}</td>
          <td>{can("admin", "dispatcher") ? <select aria-label={`Availability of ${r.full_name}`} value={r.availability} onChange={(e) => act.run(async () => { await api(`/responders/${r.responder_id}/availability`, { method: "PATCH", json: { availability: e.target.value } }); reload(); }, "Availability updated")}>
            {["AVAILABLE", "ON_DUTY", "OFF_DUTY"].map((a) => <option key={a} value={a}>{label(a)}</option>)}</select> : <Badge value={r.availability} />}</td>
          <td>{can("admin", "dispatcher") && <button className="btn small" disabled={act.busy} onClick={() => act.run(async () => { await api(`/responders/${r.responder_id}/unit`, { method: "PUT", json: { unit_id: null } }); reload(); }, "Responder unassigned")}>Unassign</button>}</td></tr>)}
      </tbody></table></div>}</Async>
      {can("admin", "dispatcher") && (
        <div className="filters" style={{ marginTop: 8 }}>
          <Field label="Assign responder (same organisation, unassigned)"><select value={pick} onChange={(e) => setPick(e.target.value)}><option value="">Select…</option>{unassigned.map((r: any) => <option key={r.responder_id} value={r.responder_id}>{r.full_name} — {r.responder_type}</option>)}</select></Field>
          <button className="btn" disabled={!pick || act.busy} onClick={() => act.run(async () => { await api(`/responders/${pick}/unit`, { method: "PUT", json: { unit_id: unitId } }); setPick(""); reload(); }, "Responder assigned")}>Assign</button>
        </div>)}
    </div>}</Async>
  );
}

export default function UnitsPage() {
  const { can } = useAuth();
  const [state, setState] = useState("");
  const [type, setType] = useState("");
  const [editing, setEditing] = useState<any | "new" | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const list = useApi<any>(`/units${qs({ unit_type: type, page_size: 100 })}`, 30_000);
  const all: any[] = list.data?.data ?? [];
  const types = Array.from(new Set(all.map((u) => u.unit_type).filter(Boolean)));
  const rows = all.filter((u) => !state || unitState(u) === state);

  return (
    <>
      <PageHeader title="Units & responders">{can("admin") && <button className="btn primary" onClick={() => setEditing("new")}>New unit</button>}</PageHeader>
      <div className="filters">
        <Field label="State"><select value={state} onChange={(e) => setState(e.target.value)}><option value="">All</option><option value="AVAILABLE">Available</option><option value="DISPATCHED">Dispatched / busy</option><option value="OUT_OF_SERVICE">Out of service</option></select></Field>
        <Field label="Type"><select value={type} onChange={(e) => setType(e.target.value)}><option value="">All</option>{types.map((t) => <option key={t}>{t}</option>)}</select></Field>
      </div>
      <Async state={list}>{() => rows.length === 0 ? <div className="state empty">No units match.</div> : (
        <div className="card tablewrap"><table><thead><tr><th>Unit</th><th>Type</th><th>Organisation</th><th>State</th><th>Crew</th><th>Base location</th><th>Current incident</th><th /></tr></thead><tbody>
          {rows.map((u) => <tr key={u.unit_id}><td>{u.unit_name}</td><td>{u.unit_type ?? "—"}</td><td>{u.organization_name}</td><td><Badge value={unitState(u)} /></td><td>{u.crew_size}</td><td>{u.base_location ?? "—"}</td>
            <td>{u.current_incident_id ? <Link href={`/incidents/${u.current_incident_id}`}>#{u.current_incident_id}</Link> : "—"}</td>
            <td><span className="row"><button className="btn small" onClick={() => setOpen(u.unit_id)}>Details</button>{can("admin") && <button className="btn small" onClick={() => setEditing(u)}>Edit</button>}</span></td></tr>)}
        </tbody></table></div>)}</Async>
      {editing && <UnitForm unit={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} onSaved={list.reload} />}
      {open !== null && <Modal title="Unit details" onClose={() => setOpen(null)}><UnitDetail unitId={open} onChanged={list.reload} /></Modal>}
    </>
  );
}
