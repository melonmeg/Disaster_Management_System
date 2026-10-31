"use client";
import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import { qs } from "@/lib/api";
import { INCIDENT_STATUSES, SEVERITIES, dt, label, minutes } from "@/lib/format";
import { Async, Badge, Field, PageHeader, Pagination } from "@/components/ui";
import { IncidentForm } from "@/components/IncidentForm";

function IncidentList() {
  const { can } = useAuth();
  const params = useSearchParams();
  const [text, setText] = useState("");
  const [location, setLocation] = useState("");           // debounced
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [unresolved, setUnresolved] = useState(params.get("unresolved") === "true");
  const [sort, setSort] = useState("newest");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);

  useEffect(() => { const t = setTimeout(() => { setLocation(text); setPage(1); }, 300); return () => clearTimeout(t); }, [text]);
  const list = useApi<any>(`/incidents${qs({ location, severity, status, incident_type: type, unresolved: unresolved || undefined, sort, page, page_size: 15 })}`, 30_000);

  return (
    <>
      <PageHeader title="Incidents">
        {can("admin", "dispatcher") && <button className="btn primary" onClick={() => setCreating(true)}>New incident</button>}
      </PageHeader>
      <div className="filters" role="search">
        <Field label="Search location"><input value={text} onChange={(e) => setText(e.target.value)} placeholder="Street, district…" /></Field>
        <Field label="Type"><input value={type} onChange={(e) => { setType(e.target.value); setPage(1); }} placeholder="exact type" /></Field>
        <Field label="Severity"><select value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(1); }}><option value="">All</option>{SEVERITIES.map((s) => <option key={s}>{s}</option>)}</select></Field>
        <Field label="Status"><select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}><option value="">All</option>{INCIDENT_STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}</select></Field>
        <Field label="Sort"><select value={sort} onChange={(e) => setSort(e.target.value)}><option value="newest">Newest</option><option value="oldest">Oldest</option><option value="severity">Severity</option></select></Field>
        <label className="row"><input type="checkbox" checked={unresolved} onChange={(e) => { setUnresolved(e.target.checked); setPage(1); }} /> Unresolved only</label>
      </div>
      <Async state={list} empty={(d) => d.data.length === 0}>
        {(d) => <>
          <div className="card tablewrap"><table>
            <caption className="muted small-text" style={{ textAlign: "left", padding: 6 }}>{d.pagination.total} incident(s)</caption>
            <thead><tr><th>ID</th><th>Type</th><th>Severity</th><th>Status</th><th>Location</th><th>Created</th><th>Resolved</th><th>Dispatches</th></tr></thead>
            <tbody>{d.data.map((i: any) => (
              <tr key={i.incident_id}>
                <td><Link href={`/incidents/${i.incident_id}`}>#{i.incident_id}</Link></td><td>{i.incident_type}</td>
                <td><Badge value={i.severity} kind="severity" /></td><td><Badge value={i.status} /></td><td>{i.location}</td>
                <td>{dt(i.created_at)}</td><td>{i.resolved_at ? `${dt(i.resolved_at)} (${minutes(i.open_minutes)})` : "—"}</td>
                <td>{i.active_dispatch_count} active / {i.dispatch_count}</td>
              </tr>))}
            </tbody></table></div>
          <Pagination page={page} totalPages={d.pagination.total_pages} onPage={setPage} />
        </>}
      </Async>
      {creating && <IncidentForm onClose={() => setCreating(false)} onSaved={() => list.reload()} />}
    </>
  );
}

export default function IncidentsPage() {
  return <Suspense><IncidentList /></Suspense>;
}
