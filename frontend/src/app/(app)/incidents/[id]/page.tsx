"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAction, useApi } from "@/lib/hooks";
import { dt, minutes } from "@/lib/format";
import { Async, Badge, Card, Empty, ErrorBox, Modal, Notice, PageHeader } from "@/components/ui";
import { IncidentForm } from "@/components/IncidentForm";
import { RecommendationPanel } from "@/components/RecommendationPanel";
import { DispatchDetail } from "@/components/DispatchDetail";
import { CallRecording } from "@/components/CallRecording";

export default function IncidentDetail() {
  const id = Number(useParams<{ id: string }>().id);
  const { can } = useAuth();
  const staff = can("admin", "dispatcher");
  const inc = useApi<any>(`/incidents/${id}`, 30_000);
  const calls = useApi<any>(staff ? `/incidents/${id}/calls` : null);
  const activity = useApi<any>(`/incidents/${id}/activity`, 30_000);
  const [editing, setEditing] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const resolve = useAction();

  const reloadAll = () => { inc.reload(); activity.reload(); };

  return (
    <Async state={inc}>{(i) => (
      <>
        <PageHeader title={`Incident #${i.incident_id} — ${i.incident_type}`}>
          <Link href="/incidents">← All incidents</Link>
          {staff && <button className="btn" onClick={() => setEditing(true)}>Edit</button>}
          {staff && (i.status === "OPEN" || i.status === "IN_PROGRESS") && (
            <button className="btn" disabled={resolve.busy} onClick={() => resolve.run(async () => { await api(`/incidents/${id}/resolve`, { method: "POST" }); reloadAll(); }, "Incident resolved")}>Resolve</button>)}
        </PageHeader>
        <ErrorBox error={resolve.error} />{resolve.ok && <Notice kind="ok">{resolve.ok}</Notice>}
        <div className="grid g2">
          <div className="grid">
            <Card title="Details">
              <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 14px", margin: 0 }}>
                <dt className="muted">Severity</dt><dd><Badge value={i.severity} kind="severity" /></dd>
                <dt className="muted">Status</dt><dd><Badge value={i.status} /></dd>
                <dt className="muted">Location</dt><dd>{i.location}</dd>
                <dt className="muted">Created</dt><dd>{dt(i.created_at)}</dd>
                <dt className="muted">Resolved</dt><dd>{dt(i.resolved_at)}</dd>
                <dt className="muted">Response time</dt><dd>{minutes(i.response_minutes)}</dd>
                <dt className="muted">Open for</dt><dd>{minutes(i.open_minutes)}</dd>
              </dl>
            </Card>
            <Card title={`Dispatches (${i.dispatches.length})`}>
              {i.dispatches.length === 0 ? <Empty>No unit dispatched yet.</Empty> : (
                <div className="tablewrap"><table><thead><tr><th>Unit</th><th>Status</th><th>Dispatched</th><th>Crew</th><th /></tr></thead><tbody>
                  {i.dispatches.map((d: any) => (
                    <tr key={d.dispatch_id}><td>{d.unit_name}<div className="muted small-text">{d.organization_name}</div></td><td><Badge value={d.status} /></td><td>{dt(d.dispatched_at)}</td>
                      <td>{d.crew?.map((c: any) => c.full_name).join(", ") || "—"}</td>
                      <td><button className="btn small" onClick={() => setOpen(d.dispatch_id)}>Manage</button></td></tr>))}
                </tbody></table></div>)}
            </Card>
            <Card title={`Patients (${i.patients.length})`}>
              {i.patients.length === 0 ? <Empty>No patients recorded.</Empty> : (
                <div className="tablewrap"><table><thead><tr><th>#</th><th>Name</th><th>Age</th><th>Gender</th><th>Condition</th></tr></thead><tbody>
                  {i.patients.map((p: any) => <tr key={p.patient_no}><td>{p.patient_no}</td><td>{p.patient_name ?? "—"}</td><td>{p.age ?? "—"}</td><td>{p.gender ?? "—"}</td><td>{p.patient_condition ?? "—"}</td></tr>)}
                </tbody></table></div>)}
            </Card>
            {staff && (
              <Card title="Calls">
                <Async state={calls} empty={(d) => d.data.length === 0}>{(d) => (
                  <div className="tablewrap"><table><thead><tr><th>Received</th><th>Caller</th><th>Priority</th><th>Status</th><th>Notes</th><th>Recording</th></tr></thead><tbody>
                    {d.data.map((c: any) => <tr key={c.call_id}><td>{dt(c.received_at)}</td><td>{c.caller_name ?? "—"}</td><td><Badge value={c.priority} kind="severity" /></td><td><Badge value={c.status} /></td><td>{c.transcript ?? "—"}</td><td><CallRecording call={c} onChanged={calls.reload} /></td></tr>)}
                  </tbody></table></div>)}</Async>
              </Card>)}
            <Card title="Activity log">
              <Async state={activity} empty={(d) => d.data.length === 0}>{(d) => (
                <ul style={{ margin: 0, paddingLeft: 18 }}>{d.data.map((a: any) => <li key={a.log_id}><span className="muted">{dt(a.action_time)}</span> — {a.action}</li>)}</ul>)}</Async>
            </Card>
          </div>
          <Card title="Dispatch recommendation"><RecommendationPanel incidentId={id} onDispatched={reloadAll} /></Card>
        </div>
        {editing && <IncidentForm incident={i} onClose={() => setEditing(false)} onSaved={reloadAll} />}
        {open !== null && <Modal title="Manage dispatch" onClose={() => setOpen(null)}><DispatchDetail dispatchId={open} onChanged={reloadAll} /></Modal>}
      </>
    )}</Async>
  );
}
