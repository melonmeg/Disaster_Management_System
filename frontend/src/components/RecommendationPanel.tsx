"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAction, useApi } from "@/lib/hooks";
import { dt, label } from "@/lib/format";
import { Badge, ErrorBox, Field, Modal, Notice, Spinner } from "./ui";

type Pick = { unit: any; kind: "ACCEPTED" | "OVERRIDDEN" };

/**
 * AI-assisted suggestions for one incident. Nothing is dispatched until the dispatcher presses
 * "Confirm dispatch" in the dialog; the recommendation is only a suggestion.
 */
export function RecommendationPanel({ incidentId, onDispatched }: { incidentId: number; onDispatched?: () => void }) {
  const { can } = useAuth();
  const history = useApi<any>(can("admin", "dispatcher") ? `/incidents/${incidentId}/recommendations?limit=1` : null);
  const [fresh, setFresh] = useState<any>(null);          // result of a generate call in this session
  const gen = useAction();
  const [pick, setPick] = useState<Pick | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [overriding, setOverriding] = useState(false);

  useEffect(() => { setFresh(null); }, [incidentId]);

  if (!can("admin", "dispatcher")) return <Notice>Recommendations are available to dispatchers and admins.</Notice>;

  const stored = history.data?.data?.[0] && history.data.data[0].status !== "SUPERSEDED" ? history.data.data[0] : null;
  const rec = fresh ?? stored;
  const storeDown = history.error?.status === 503;

  const generate = async () => {
    const r = await gen.run(() => api(`/incidents/${incidentId}/recommendations`, { method: "POST" }));
    if (r) { setFresh(r); history.reload(); }
  };
  const refreshRec = async (id: string) => { setFresh(await api(`/recommendations/${id}`)); history.reload(); };

  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <button className="btn primary" onClick={generate} disabled={gen.busy}>{gen.busy ? "Analysing…" : rec ? "Regenerate" : "Generate recommendation"}</button>
        {rec?.generated_at && <span className="muted small-text">Generated {dt(rec.generated_at)}</span>}
      </div>
      <ErrorBox error={gen.error} />
      {storeDown && <Notice kind="warn">Recommendation history (MongoDB) is unavailable. You can still generate a ranking, but it cannot be saved or reviewed.</Notice>}
      {history.loading && !history.data && !storeDown && <Spinner />}
      {!rec && !history.loading && !gen.busy && <p className="muted">No recommendation yet. Suggestions never dispatch a unit on their own.</p>}

      {rec && <Ranking rec={rec} onPick={(unit) => setPick({ unit, kind: "ACCEPTED" })} />}

      {rec && !rec.decision && (
        <div className="row" style={{ marginTop: 8 }}>
          {rec.recommendation_id && <button className="btn" onClick={() => setRejecting(true)}>Reject all</button>}
          <button className="btn" onClick={() => setOverriding(true)}>Choose a different unit…</button>
        </div>
      )}
      {rec?.decision && <Decision rec={rec} onChanged={() => refreshRec(rec.recommendation_id)} />}
      {rec?.recommendation_id && can("admin") && (
        <button className="btn small danger" style={{ marginTop: 8 }} onClick={async () => {
          if (!confirm("Delete this recommendation record? Any dispatch it led to is not affected.")) return;
          await gen.run(() => api(`/recommendations/${rec.recommendation_id}`, { method: "DELETE" }));
          setFresh(null); history.reload();
        }}>Delete record (admin)</button>)}

      {pick && rec && (
        <ConfirmDispatch incidentId={incidentId} rec={rec} pick={pick} onClose={() => setPick(null)}
          onDone={async () => { setPick(null); if (rec.recommendation_id) await refreshRec(rec.recommendation_id); onDispatched?.(); }} />
      )}
      {overriding && rec && (
        <OverrideDialog onClose={() => setOverriding(false)} onChosen={(unit) => { setOverriding(false); setPick({ unit, kind: "OVERRIDDEN" }); }} />
      )}
      {rejecting && rec && <RejectDialog rec={rec} onClose={() => setRejecting(false)} onDone={async () => { setRejecting(false); await refreshRec(rec.recommendation_id); }} />}
    </div>
  );
}

function Ranking({ rec, onPick }: { rec: any; onPick: (unit: any) => void }) {
  const r = rec.ranking;
  const ex = rec.explanation;
  const decided = !!rec.decision || rec.status === "SUPERSEDED";
  return (
    <div style={{ marginTop: 10 }}>
      {rec.persisted === false && <Notice kind="warn">Not saved: {rec.persistence_error}. Decisions on this ranking will not be recorded.</Notice>}
      <Notice kind={r.confidence === "HIGH" ? "ok" : "warn"}>
        Overall confidence: <strong>{label(r.confidence)}</strong>
        {r.confidence === "INSUFFICIENT" && " — there is not enough evidence for a confident recommendation."}
      </Notice>
      {r.missing.length > 0 && <ul className="small-text">{r.missing.map((m: string) => <li key={m}>{m}</li>)}</ul>}
      {ex ? (
        <div className="card" style={{ background: "#f8fafc" }}>
          <strong>Explanation</strong> <span className="badge status-HIGH">AI-generated, checked against the data</span>
          <p>{ex.summary}</p>
          {ex.sufficient_evidence === false && <p><em>The model and rules agree evidence is limited.</em></p>}
          {ex.limitations.length > 0 && <ul>{ex.limitations.map((l: string) => <li key={l}>{l}</li>)}</ul>}
        </div>
      ) : (
        <p className="muted small-text">No AI explanation: {rec.explanation_unavailable_reason ?? "unavailable"}. The deterministic ranking below stands on its own.</p>
      )}
      {r.candidates.length === 0 && <Notice kind="warn">No eligible unit. See the excluded units below.</Notice>}
      {r.candidates.map((c: any) => {
        const reasons = ex?.candidate_reasons?.find((x: any) => x.unit_id === c.unit_id)?.reasons ?? [];
        return (
          <div key={c.unit_id} className={`rec ${c.rank === 1 ? "top" : ""}`}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>#{c.rank} {c.unit_name}</strong>
              <span className="row"><span className="badge status-HIGH">score {c.score}</span><Badge value={c.confidence} /></span>
            </div>
            <div className="small-text muted">{c.unit_type} · {c.organization_name} · base: {c.base_location ?? "unknown"}</div>
            <ul className="small-text">
              <li>Availability: free, crew of {c.crew_size}</li>
              <li>Suitability: {label(c.capability_code)}</li>
              <li>Distance: {c.distance_km !== null ? `${c.distance_km} km straight-line (not travel time)` : "unknown — not shown because coordinates are missing"}</li>
              {c.relevant_stock_available !== null && (
                <li>Relevant stock held by its organisation (to consider allocating after dispatch; quantities are your call):
                  {c.relevant_resources.length === 0 ? " none available" : <ul>{c.relevant_resources.map((x: any) => <li key={x.resource_id}>{x.resource_name}: {x.quantity_available} available</li>)}</ul>}
                </li>)}
              {reasons.map((x: string) => <li key={x}>{x}</li>)}
              {c.missing.filter((m: string) => !r.missing.includes(m)).map((m: string) => <li key={m} className="muted">Missing: {m}</li>)}
            </ul>
            {!decided && <button className="btn small primary" onClick={() => onPick(c)}>Dispatch this unit…</button>}
          </div>
        );
      })}
      {r.resource_shortages.length > 0 && <Notice kind="warn">Resource shortage: {r.resource_shortages.map((s: any) => s.resource_type).join(", ")} — no stock available.</Notice>}
      {r.excluded.length > 0 && (
        <details><summary>{r.excluded.length} unit(s) excluded</summary>
          <ul className="small-text">{r.excluded.map((e: any) => <li key={e.unit_id}>{e.unit_name} ({e.unit_type}): {label(e.reason_code)}</li>)}</ul>
        </details>
      )}
      <p className="muted small-text">Algorithm {r.algorithm_version}{rec.model?.llm ? ` · explanation by ${rec.model.llm}` : ""}. Straight-line distances only; no routing or historical outcomes are used.</p>
    </div>
  );
}

function Decision({ rec, onChanged }: { rec: any; onChanged: () => void }) {
  const d = rec.decision;
  const fb = useAction();
  const [rating, setRating] = useState("");
  const [comment, setComment] = useState("");
  const send = async () => {
    const ok = await fb.run(() => api(`/recommendations/${rec.recommendation_id}/feedback`, { method: "POST", json: { rating: rating ? Number(rating) : undefined, comment: comment || undefined } }), "Feedback saved");
    if (ok) { setRating(""); setComment(""); onChanged(); }
  };
  return (
    <div className="card" style={{ marginTop: 8 }}>
      <strong>Dispatcher decision:</strong> <Badge value={d.decision} /> {d.unit_id && <>unit #{d.unit_id}</>} · {dt(d.decided_at)}
      {d.reason && <div className="small-text">Reason: {d.reason}</div>}
      {d.dispatch_id && <div className="small-text">Dispatch #{d.dispatch_id} created.</div>}
      {rec.feedback?.map((f: any, i: number) => <div key={i} className="small-text muted">Feedback: {f.rating ? `${f.rating}/5` : ""} {f.comment}</div>)}
      <details style={{ marginTop: 6 }}><summary>Add feedback</summary>
        <Field label="Rating (1–5)"><select value={rating} onChange={(e) => setRating(e.target.value)}><option value="">—</option>{[1, 2, 3, 4, 5].map((n) => <option key={n}>{n}</option>)}</select></Field>
        <Field label="Comment"><textarea value={comment} maxLength={1000} onChange={(e) => setComment(e.target.value)} rows={2} /></Field>
        <ErrorBox error={fb.error} />{fb.ok && <Notice kind="ok">{fb.ok}</Notice>}
        <button className="btn small" disabled={fb.busy || (!rating && !comment)} onClick={send}>Save feedback</button>
      </details>
    </div>
  );
}

function ConfirmDispatch({ incidentId, rec, pick, onClose, onDone }: { incidentId: number; rec: any; pick: Pick; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const { busy, error, run } = useAction();
  const [warning, setWarning] = useState<string | null>(null);
  const override = pick.kind === "OVERRIDDEN";

  const confirm = async () => {
    // 1) the explicit dispatch via the existing API (MySQL stays authoritative; it re-validates availability)
    const dispatch = await run(() => api("/dispatches", { method: "POST", json: { incident_id: incidentId, unit_id: pick.unit.unit_id } }));
    if (!dispatch) return;
    // 2) record the decision and link it; a failure here must not hide that the dispatch exists
    if (rec.recommendation_id) {
      try {
        await api(`/recommendations/${rec.recommendation_id}/decision`, { method: "POST", json: { decision: pick.kind, unit_id: pick.unit.unit_id, reason: reason || undefined } });
        await api(`/recommendations/${rec.recommendation_id}/dispatch`, { method: "PUT", json: { dispatch_id: dispatch.dispatch_id } });
      } catch (e) {
        setWarning(`Dispatch #${dispatch.dispatch_id} was created, but recording the decision failed: ${e instanceof Error ? e.message : e}`);
        return;
      }
    }
    onDone();
  };

  return (
    <Modal title="Confirm dispatch" onClose={onClose}>
      {warning ? <><Notice kind="warn">{warning}</Notice><button className="btn" onClick={onDone}>Close</button></> : <>
        <p>Dispatch <strong>{pick.unit.unit_name}</strong> ({pick.unit.unit_type}) to incident <strong>#{incidentId}</strong>?</p>
        <p className="muted small-text">This creates a real dispatch and marks the unit busy. The server will refuse it if the unit is no longer available.</p>
        {override && <Field label="Reason for overriding the recommendation (required)"><textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={500} /></Field>}
        {!rec.recommendation_id && <Notice kind="warn">This ranking was not saved, so the decision will not be recorded.</Notice>}
        <ErrorBox error={error} />
        <div className="row">
          <button className="btn primary" disabled={busy || (override && reason.trim().length < 3)} onClick={confirm}>{busy ? "Dispatching…" : "Confirm dispatch"}</button>
          <button className="btn" onClick={onClose}>Cancel</button>
        </div>
      </>}
    </Modal>
  );
}

function OverrideDialog({ onClose, onChosen }: { onClose: () => void; onChosen: (u: any) => void }) {
  const units = useApi<any>("/units?available=true&page_size=100");
  const [id, setId] = useState("");
  return (
    <Modal title="Choose a different unit" onClose={onClose}>
      {units.loading && <Spinner />}<ErrorBox error={units.error} onRetry={units.reload} />
      {units.data && (units.data.data.length === 0 ? <Notice kind="warn">No unit is currently available.</Notice> : <>
        <Field label="Available unit"><select value={id} onChange={(e) => setId(e.target.value)}><option value="">Select…</option>
          {units.data.data.map((u: any) => <option key={u.unit_id} value={u.unit_id}>{u.unit_name} — {u.unit_type} ({u.organization_name})</option>)}</select></Field>
        <button className="btn primary" disabled={!id} onClick={() => onChosen(units.data.data.find((u: any) => String(u.unit_id) === id))}>Continue</button>
      </>)}
    </Modal>
  );
}

function RejectDialog({ rec, onClose, onDone }: { rec: any; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const { busy, error, run } = useAction();
  return (
    <Modal title="Reject recommendation" onClose={onClose}>
      <Field label="Reason (optional)"><textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={500} /></Field>
      <ErrorBox error={error} />
      <button className="btn danger" disabled={busy} onClick={async () => { const ok = await run(() => api(`/recommendations/${rec.recommendation_id}/decision`, { method: "POST", json: { decision: "REJECTED", reason: reason || undefined } })); if (ok) onDone(); }}>Reject</button>
    </Modal>
  );
}
