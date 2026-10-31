"use client";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useMemo, useState } from "react";
import { api, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAction, useApi } from "@/lib/hooks";
import { INCIDENT_STATUSES, SEVERITIES, SEVERITY_COLOR, dt, label } from "@/lib/format";
import { Badge, Card, Empty, ErrorBox, Field, Notice, PageHeader, Spinner } from "@/components/ui";
import { RecommendationPanel } from "@/components/RecommendationPanel";

// Leaflet touches `window`, so it must only render in the browser.
const IncidentMap = dynamic(() => import("@/components/IncidentMap"), { ssr: false, loading: () => <Spinner text="Loading map…" /> });

const WINDOWS: Record<string, number | null> = { "24h": 24, "7d": 168, "30d": 720, all: null };

function ManualLocation({ incident, onSaved }: { incident: any; onSaved: () => void }) {
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const { busy, error, run } = useAction();
  return (
    <form className="row" onSubmit={async (e) => { e.preventDefault(); const ok = await run(() => api("/map/locations", { method: "PUT", json: { location: incident.location, latitude: Number(lat), longitude: Number(lon) } })); if (ok) onSaved(); }}>
      <input aria-label="Latitude" placeholder="lat" type="number" step="any" min={-90} max={90} value={lat} onChange={(e) => setLat(e.target.value)} style={{ width: 90 }} required />
      <input aria-label="Longitude" placeholder="lon" type="number" step="any" min={-180} max={180} value={lon} onChange={(e) => setLon(e.target.value)} style={{ width: 90 }} required />
      <button className="btn small" disabled={busy}>Set</button><ErrorBox error={error} />
    </form>
  );
}

export default function MapPage() {
  const { can } = useAuth();
  const staff = can("admin", "dispatcher");
  const [severity, setSeverity] = useState<string[]>([]);
  const [status, setStatus] = useState<string[]>(["OPEN", "IN_PROGRESS"]);
  const [type, setType] = useState("");
  const [win, setWin] = useState("all");
  const [selected, setSelected] = useState<number | null>(null);
  const [listView, setListView] = useState(false);
  const geo = useAction();

  const createdFrom = useMemo(() => {
    const h = WINDOWS[win];
    if (!h) return undefined;
    // The API compares against server-local, timezone-less times, so send local wall-clock time (not UTC).
    const d = new Date(Date.now() - h * 3600_000), p = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }, [win]);
  const data = useApi<any>(`/map/incidents${qs({ severity, status, incident_type: type, created_from: createdFrom })}`, 30_000);
  const all = useApi<any>("/map/incidents");                                  // for the type filter options
  const types = Array.from(new Set<string>((all.data?.data ?? []).map((i: any) => i.incident_type))).sort();

  const rows: any[] = data.data?.data ?? [];
  const mapped = rows.filter((i) => i.latitude !== null);
  const unmapped = rows.filter((i) => i.latitude === null);
  const sel = rows.find((i) => i.incident_id === selected) ?? null;
  const toggle = (list: string[], set: (v: string[]) => void, v: string) => set(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  const geocode = async () => { await geo.run(async () => { const r = await api<any>("/map/geocode?limit=10", { method: "POST" }); if (r.error) throw new Error(r.error); data.reload(); return r; }); };

  return (
    <>
      <PageHeader title="Incident map">
        <button className="btn" onClick={() => setListView(!listView)} aria-pressed={listView}>{listView ? "Show map" : "Show list view"}</button>
        {staff && data.data?.summary.pending_geocode > 0 && <button className="btn" disabled={geo.busy} onClick={geocode}>{geo.busy ? "Resolving…" : `Resolve ${data.data.summary.pending_geocode} pending location(s)`}</button>}
      </PageHeader>
      <ErrorBox error={geo.error} />
      <div className="filters" role="group" aria-label="Map filters">
        <fieldset className="row" style={{ border: 0, padding: 0, margin: 0 }}><legend className="small-text"><strong>Severity</strong></legend>
          {SEVERITIES.map((s) => <label key={s} className="row"><input type="checkbox" checked={severity.includes(s)} onChange={() => toggle(severity, setSeverity, s)} />{s}</label>)}</fieldset>
        <fieldset className="row" style={{ border: 0, padding: 0, margin: 0 }}><legend className="small-text"><strong>Status</strong></legend>
          {INCIDENT_STATUSES.map((s) => <label key={s} className="row"><input type="checkbox" checked={status.includes(s)} onChange={() => toggle(status, setStatus, s)} />{label(s)}</label>)}</fieldset>
        <Field label="Type"><select value={type} onChange={(e) => setType(e.target.value)}><option value="">All</option>{types.map((t) => <option key={t}>{t}</option>)}</select></Field>
        <Field label="Created within"><select value={win} onChange={(e) => setWin(e.target.value)}><option value="24h">24 hours</option><option value="7d">7 days</option><option value="30d">30 days</option><option value="all">Any time</option></select></Field>
      </div>
      <div className="legend" aria-label="Legend">
        {SEVERITIES.map((s) => <span key={s}><i style={{ background: SEVERITY_COLOR[s] }} />{s}</span>)}
        <span>● solid = open / in progress</span><span>○ hollow = resolved / closed</span>
      </div>
      {data.error && <ErrorBox error={data.error} onRetry={data.reload} />}
      {data.loading && !data.data && <Spinner text="Loading incidents…" />}
      {data.data && <p className="muted small-text">{data.data.summary.mapped} of {data.data.summary.total} incident(s) have a known position{data.data.summary.pending_geocode > 0 ? `; ${data.data.summary.pending_geocode} location(s) not yet looked up` : ""}.</p>}

      <div className="mapwrap">
        <div>
          {listView
            ? <div className="card tablewrap"><table><caption className="small-text muted" style={{ textAlign: "left" }}>Incidents matching the filters</caption>
                <thead><tr><th>Incident</th><th>Severity</th><th>Status</th><th>Location</th><th>Position</th></tr></thead><tbody>
                  {rows.map((i) => <tr key={i.incident_id} className={`clickable ${i.incident_id === selected ? "selected" : ""}`}>
                    <td><button className="btn small" onClick={() => setSelected(i.incident_id)} aria-pressed={i.incident_id === selected}>#{i.incident_id} {i.incident_type}</button></td>
                    <td><Badge value={i.severity} kind="severity" /></td><td><Badge value={i.status} /></td><td>{i.location}</td>
                    <td>{i.latitude !== null ? `${i.latitude.toFixed(4)}, ${i.longitude.toFixed(4)}` : label(i.geocode_status)}</td></tr>)}
                  {rows.length === 0 && <tr><td colSpan={5}><Empty>No incidents match.</Empty></td></tr>}
                </tbody></table></div>
            : <IncidentMap incidents={mapped} selectedId={selected} onSelect={setSelected} />}
          {!listView && mapped.length === 0 && data.data && <Notice kind="warn">No incident has a known position yet, so none can be shown on the map.{staff ? " Use “Resolve pending locations” or set coordinates below." : ""}</Notice>}
          {unmapped.length > 0 && (
            <Card title={`Not on the map (${unmapped.length})`}>
              <p className="muted small-text">These locations could not be placed. They are listed here instead of being guessed.</p>
              <ul style={{ paddingLeft: 18 }}>{unmapped.map((i) => (
                <li key={i.incident_id} style={{ marginBottom: 6 }}>
                  <button className="btn small" onClick={() => setSelected(i.incident_id)}>#{i.incident_id} {i.incident_type}</button> {i.location} — <em>{label(i.geocode_status)}</em>
                  {staff && i.geocode_status !== "PENDING" && <ManualLocation incident={i} onSaved={data.reload} />}
                </li>))}</ul>
            </Card>)}
        </div>
        <aside aria-live="polite">
          <Card title={sel ? `Incident #${sel.incident_id}` : "Selected incident"}>
            {!sel ? <p className="muted">Select a marker or list entry to see details and dispatch recommendations.</p> : <>
              <p><strong>{sel.incident_type}</strong> <Badge value={sel.severity} kind="severity" /> <Badge value={sel.status} /></p>
              <p className="small-text">{sel.location}<br /><span className="muted">{dt(sel.created_at)} · {sel.active_dispatch_count} active dispatch(es)</span></p>
              <p><Link href={`/incidents/${sel.incident_id}`}>Open full incident →</Link></p>
              {(sel.status === "OPEN" || sel.status === "IN_PROGRESS") ? <RecommendationPanel incidentId={sel.incident_id} onDispatched={data.reload} /> : <Notice>Recommendations are only generated for open incidents.</Notice>}
            </>}
          </Card>
        </aside>
      </div>
    </>
  );
}
