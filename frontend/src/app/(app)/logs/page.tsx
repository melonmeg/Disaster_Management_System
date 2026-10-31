"use client";
import { useState } from "react";
import { qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import { dt } from "@/lib/format";
import { Async, Field, Notice, PageHeader, Pagination } from "@/components/ui";

/** MongoDB operational log (admin): data changes and failed requests. Never shows request bodies or tokens. */
export default function LogsPage() {
  const { can } = useAuth();
  const [method, setMethod] = useState("");
  const [failedOnly, setFailedOnly] = useState(false);
  const [path, setPath] = useState("");
  const [page, setPage] = useState(1);
  const logs = useApi<any>(can("admin") ? `/logs${qs({ method, status_min: failedOnly ? 400 : undefined, path_prefix: path, page, page_size: 25 })}` : null, 30_000);

  if (!can("admin")) return <Notice kind="warn">Only administrators can view the operational log.</Notice>;
  return (
    <>
      <PageHeader title="Operational log" />
      <p className="muted">Stored in MongoDB. Records every change and every failed request (who, what, result, how long). Successful reads, request bodies and passwords are not kept; entries expire automatically.</p>
      <div className="filters">
        <Field label="Method"><select value={method} onChange={(e) => { setMethod(e.target.value); setPage(1); }}>
          <option value="">All</option>{["POST", "PUT", "PATCH", "DELETE", "GET"].map((m) => <option key={m}>{m}</option>)}</select></Field>
        <Field label="Path starts with"><input value={path} placeholder="/api/calls" onChange={(e) => { setPath(e.target.value); setPage(1); }} /></Field>
        <label><input type="checkbox" checked={failedOnly} onChange={(e) => { setFailedOnly(e.target.checked); setPage(1); }} /> Failed requests only</label>
      </div>
      <Async state={logs} empty={(d) => d.data.length === 0}>{(d) => (
        <>
          <div className="tablewrap"><table><thead><tr><th>Time</th><th>User</th><th>Request</th><th>Result</th><th>Duration</th></tr></thead><tbody>
            {d.data.map((r: any) => (
              <tr key={r.request_id}><td>{dt(r.ts + "Z")}</td><td>{r.user_id ? `#${r.user_id} (${r.role})` : "anonymous"}</td>
                <td><code>{r.method} {r.path}</code></td>
                <td><strong style={{ color: r.status >= 500 ? "var(--danger, #b00020)" : r.status >= 400 ? "var(--warn, #9a6700)" : undefined }}>{r.status}</strong></td><td>{r.duration_ms} ms</td></tr>))}
          </tbody></table></div>
          <Pagination page={d.pagination.page} totalPages={d.pagination.total_pages} onPage={setPage} />
        </>)}</Async>
    </>
  );
}
