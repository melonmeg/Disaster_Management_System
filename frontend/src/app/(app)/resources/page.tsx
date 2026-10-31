"use client";
import { useState } from "react";
import { api, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAction, useApi } from "@/lib/hooks";
import { Async, Badge, ErrorBox, Field, Modal, Notice, PageHeader } from "@/components/ui";

function ResourceForm({ resource, onClose, onSaved }: { resource?: any; onClose: () => void; onSaved: () => void }) {
  const orgs = useApi<any>(resource ? null : "/organizations?page_size=100");
  const [name, setName] = useState(resource?.resource_name ?? "");
  const [type, setType] = useState(resource?.resource_type ?? "");
  const [location, setLocation] = useState(resource?.location ?? "");
  const [status, setStatus] = useState(resource?.status === "UNAVAILABLE" ? "UNAVAILABLE" : "AVAILABLE");
  const [total, setTotal] = useState("1");
  const [org, setOrg] = useState("");
  const { busy, error, run } = useAction();
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const ok = await run(() => resource
      ? api(`/resources/${resource.resource_id}`, { method: "PATCH", json: { resource_name: name, resource_type: type || null, location: location || null, status } })
      : api("/resources", { method: "POST", json: { resource_name: name, resource_type: type || null, location: location || null, quantity_total: Number(total), organization_id: Number(org) } }));
    if (ok) { onSaved(); onClose(); }
  };
  return (
    <Modal title={resource ? `Edit ${resource.resource_name}` : "New resource"} onClose={onClose}>
      <form onSubmit={submit}>
        <Field label="Name"><input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} required /></Field>
        <Field label="Type"><input value={type} onChange={(e) => setType(e.target.value)} maxLength={50} /></Field>
        <Field label="Location"><input value={location} onChange={(e) => setLocation(e.target.value)} maxLength={255} /></Field>
        {resource ? <Field label="Status"><select value={status} onChange={(e) => setStatus(e.target.value)}><option>AVAILABLE</option><option>UNAVAILABLE</option></select></Field> : <>
          <Field label="Total quantity"><input type="number" min={0} value={total} onChange={(e) => setTotal(e.target.value)} required /></Field>
          <Field label="Organisation"><select value={org} onChange={(e) => setOrg(e.target.value)} required><option value="">Select…</option>{orgs.data?.data.map((o: any) => <option key={o.organization_id} value={o.organization_id}>{o.organization_name}</option>)}</select></Field></>}
        <ErrorBox error={error} />
        <button className="btn primary" disabled={busy}>Save</button>
      </form>
    </Modal>
  );
}

export default function ResourcesPage() {
  const { can } = useAuth();
  const [type, setType] = useState("");
  const [onlyAvail, setOnlyAvail] = useState(false);
  const [editing, setEditing] = useState<any | "new" | null>(null);
  const [restock, setRestock] = useState<Record<number, string>>({});
  const act = useAction();
  const list = useApi<any>(`/resources${qs({ resource_type: type, available: onlyAvail || undefined, page_size: 100 })}`, 30_000);
  const types = Array.from(new Set<string>((list.data?.data ?? []).map((r: any) => r.resource_type).filter(Boolean)));

  return (
    <>
      <PageHeader title="Resources">{can("admin") && <button className="btn primary" onClick={() => setEditing("new")}>New resource</button>}</PageHeader>
      <div className="filters">
        <Field label="Type"><select value={type} onChange={(e) => setType(e.target.value)}><option value="">All</option>{types.map((t) => <option key={t}>{t}</option>)}</select></Field>
        <label className="row"><input type="checkbox" checked={onlyAvail} onChange={(e) => setOnlyAvail(e.target.checked)} /> In stock only</label>
      </div>
      <ErrorBox error={act.error} />{act.ok && <Notice kind="ok">{act.ok}</Notice>}
      <Async state={list} empty={(d) => d.data.length === 0}>{(d) => (
        <div className="card tablewrap"><table><thead><tr><th>Resource</th><th>Type</th><th>Organisation</th><th>Available / total</th><th>In field</th><th>Status</th><th /></tr></thead><tbody>
          {d.data.map((r: any) => {
            const low = r.quantity_available === 0 || r.quantity_available < 0.25 * r.quantity_total;
            return <tr key={r.resource_id}>
              <td>{r.resource_name}<div className="muted small-text">{r.location ?? ""}</div></td><td>{r.resource_type ?? "—"}</td><td>{r.organization_name}</td>
              <td>{r.quantity_available} / {r.quantity_total} {low && <span className="badge status-CANCELLED">LOW</span>}
                <div className="bar" role="img" aria-label={`${r.utilisation_pct ?? 0}% in use`}><i style={{ width: `${r.utilisation_pct ?? 0}%` }} /></div></td>
              <td>{r.quantity_in_field}</td><td><Badge value={r.status} /></td>
              <td>{can("admin") && <span className="row">
                <button className="btn small" onClick={() => setEditing(r)}>Edit</button>
                <input aria-label={`Restock quantity for ${r.resource_name}`} type="number" min={1} style={{ width: 70 }} value={restock[r.resource_id] ?? ""} onChange={(e) => setRestock({ ...restock, [r.resource_id]: e.target.value })} />
                <button className="btn small" disabled={act.busy || !restock[r.resource_id]} onClick={() => act.run(async () => { await api(`/resources/${r.resource_id}/restock`, { method: "POST", json: { quantity: Number(restock[r.resource_id]) } }); setRestock({ ...restock, [r.resource_id]: "" }); list.reload(); }, `${r.resource_name} restocked`)}>Restock</button></span>}</td>
            </tr>;
          })}
        </tbody></table>
          <p className="muted small-text">Allocate and return resources from a dispatch (Dispatches → Details).</p></div>)}</Async>
      {editing && <ResourceForm resource={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} onSaved={list.reload} />}
    </>
  );
}
