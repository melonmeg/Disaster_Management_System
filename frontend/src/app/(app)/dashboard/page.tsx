"use client";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import { dt } from "@/lib/format";
import { Async, Badge, Card, Empty, ErrorBox, Notice, PageHeader, Spinner } from "@/components/ui";

const REFRESH = 30_000;

function Stat({ value, text, href }: { value: React.ReactNode; text: string; href?: string }) {
  const body = <><div className="stat">{value}</div><div className="stat-label">{text}</div></>;
  return <div className="card">{href ? <Link href={href} style={{ textDecoration: "none", color: "inherit" }}>{body}</Link> : body}</div>;
}

function count(rows: { count: number | string }[] | undefined, key: string, value: string, field = "status") {
  const r = (rows as any[] | undefined)?.find((x) => x[field] === value);
  return r ? Number(r.count) : 0;
}

export default function Dashboard() {
  const { can } = useAuth();
  const staff = can("admin", "dispatcher");
  const summary = useApi<any>(staff ? "/reports/summary" : null, REFRESH);
  const recent = useApi<any>("/incidents?page_size=100", REFRESH);   // also feeds the responder's fallback grouping
  const units = useApi<any>("/units?page_size=100", REFRESH);
  const resources = useApi<any>("/resources?page_size=100", REFRESH);
  const active = useApi<any>("/dispatches?active=true&page_size=8", REFRESH);
  const pending = useApi<any>(staff ? "/recommendations/summary" : null, REFRESH);

  const incidents: any[] = recent.data?.data ?? [];
  const unresolved = incidents.filter((i) => i.status === "OPEN" || i.status === "IN_PROGRESS");
  const bySeverity = ["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((s) => ({
    severity: s,
    total: summary.data ? count(summary.data.incidents_by_severity, "severity", s, "severity") : incidents.filter((i) => i.severity === s).length,
    unresolved: summary.data
      ? Number(summary.data.incidents_by_severity.find((x: any) => x.severity === s)?.unresolved ?? 0)
      : unresolved.filter((i) => i.severity === s).length,
  }));
  const byStatus = ["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"].map((s) => ({
    status: s,
    count: summary.data ? count(summary.data.incidents_by_status, "status", s) : incidents.filter((i) => i.status === s).length,
  }));
  const unitRows: any[] = units.data?.data ?? [];
  const resRows: any[] = resources.data?.data ?? [];
  const shortages = resRows.filter((r) => r.quantity_available === 0 || r.quantity_available < 0.25 * r.quantity_total);

  return (
    <>
      <PageHeader title="Dispatcher dashboard"><span className="muted small-text">Auto-refreshes every 30 s</span></PageHeader>
      {!staff && <Notice>Showing figures derived from the latest 100 incidents (the summary report is limited to dispatchers and admins).</Notice>}
      <ErrorBox error={recent.error} onRetry={recent.reload} />
      <div className="grid g4">
        <Stat value={recent.loading && !recent.data ? "…" : unresolved.length} text="Open incidents" href="/incidents?unresolved=true" />
        <Stat value={units.data ? unitRows.filter((u) => u.is_free).length : "…"} text={`Units available (of ${unitRows.length})`} href="/units" />
        <Stat value={units.data ? unitRows.filter((u) => !u.is_free).length : "…"} text="Units dispatched / busy" href="/units" />
        <Stat value={resources.data ? shortages.length : "…"} text="Resource shortages" href="/resources" />
        {staff && <Stat value={pending.error ? "n/a" : pending.data ? pending.data.pending : "…"} text={pending.error ? "Pending recommendations (history store unavailable)" : "Pending recommendations"} href="/map" />}
      </div>

      <div className="grid g2" style={{ marginTop: 14 }}>
        <Card title="Incidents by severity">
          <div className="tablewrap"><table><thead><tr><th>Severity</th><th>Total</th><th>Unresolved</th></tr></thead>
            <tbody>{bySeverity.map((r) => <tr key={r.severity}><td><Badge value={r.severity} kind="severity" /></td><td>{r.total}</td><td>{r.unresolved}</td></tr>)}</tbody></table></div>
        </Card>
        <Card title="Incidents by status">
          <div className="tablewrap"><table><thead><tr><th>Status</th><th>Count</th></tr></thead>
            <tbody>{byStatus.map((r) => <tr key={r.status}><td><Badge value={r.status} /></td><td>{r.count}</td></tr>)}</tbody></table></div>
        </Card>
        <Card title="Active dispatches" actions={<Link href="/dispatches">All dispatches</Link>}>
          <Async state={active} empty={(d) => d.data.length === 0}>
            {(d) => <div className="tablewrap"><table><thead><tr><th>Unit</th><th>Incident</th><th>Status</th><th>Since</th></tr></thead><tbody>
              {d.data.map((x: any) => <tr key={x.dispatch_id}><td>{x.unit_name}</td><td><Link href={`/incidents/${x.incident_id}`}>#{x.incident_id} {x.incident_type}</Link></td><td><Badge value={x.status} /></td><td>{dt(x.dispatched_at)}</td></tr>)}
            </tbody></table></div>}
          </Async>
        </Card>
        <Card title="Recent incidents" actions={<Link href="/incidents">All incidents</Link>}>
          {recent.loading && !recent.data ? <Spinner /> : incidents.length === 0 ? <Empty>No incidents recorded.</Empty> :
            <div className="tablewrap"><table><thead><tr><th>Incident</th><th>Severity</th><th>Status</th><th>Created</th></tr></thead><tbody>
              {incidents.slice(0, 6).map((i) => <tr key={i.incident_id}><td><Link href={`/incidents/${i.incident_id}`}>#{i.incident_id} {i.incident_type}</Link></td><td><Badge value={i.severity} kind="severity" /></td><td><Badge value={i.status} /></td><td>{dt(i.created_at)}</td></tr>)}
            </tbody></table></div>}
        </Card>
        <Card title="Resource shortages (below 25 % of stock)">
          {resources.loading && !resources.data ? <Spinner /> : shortages.length === 0 ? <Empty>No shortages.</Empty> :
            <div className="tablewrap"><table><thead><tr><th>Resource</th><th>Available</th><th>Total</th></tr></thead><tbody>
              {shortages.map((r) => <tr key={r.resource_id}><td>{r.resource_name}</td><td>{r.quantity_available}</td><td>{r.quantity_total}</td></tr>)}
            </tbody></table></div>}
        </Card>
        {summary.data?.response_times && (
          <Card title="Response times">
            <p>Average: <strong>{summary.data.response_times.avg_response_minutes ?? "—"}</strong> min · Longest: <strong>{summary.data.response_times.max_response_minutes ?? "—"}</strong> min</p>
          </Card>
        )}
      </div>
    </>
  );
}
