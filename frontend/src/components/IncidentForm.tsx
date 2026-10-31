"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import { INCIDENT_STATUSES, SEVERITIES, label } from "@/lib/format";
import { ErrorBox, Field, Modal } from "./ui";

export function IncidentForm({ incident, onClose, onSaved }: { incident?: any; onClose: () => void; onSaved: (i: any) => void }) {
  const [type, setType] = useState(incident?.incident_type ?? "");
  const [severity, setSeverity] = useState(incident?.severity ?? "MEDIUM");
  const [location, setLocation] = useState(incident?.location ?? "");
  const [status, setStatus] = useState(incident?.status ?? "OPEN");
  const { busy, error, run } = useAction();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const saved = await run(() => incident
      ? api(`/incidents/${incident.incident_id}`, { method: "PATCH", json: { incident_type: type, severity, location, ...(status !== incident.status ? { status } : {}) } })
      : api("/incidents", { method: "POST", json: { incident_type: type, severity, location } }));
    if (saved) { onSaved(saved); onClose(); }
  };

  return (
    <Modal title={incident ? `Edit incident #${incident.incident_id}` : "New incident"} onClose={onClose}>
      <form onSubmit={submit}>
        <Field label="Incident type" hint="e.g. Building Fire, Road Accident, Medical Emergency"><input value={type} maxLength={50} onChange={(e) => setType(e.target.value)} required /></Field>
        <Field label="Severity"><select value={severity} onChange={(e) => setSeverity(e.target.value)}>{SEVERITIES.map((s) => <option key={s}>{s}</option>)}</select></Field>
        <Field label="Location" hint="Address or landmark text; it is geocoded for the map."><input value={location} maxLength={255} onChange={(e) => setLocation(e.target.value)} required /></Field>
        {incident && (
          <Field label="Status" hint="Resolving requires all dispatches finished and resources returned; the server decides.">
            <select value={status} onChange={(e) => setStatus(e.target.value)}>{INCIDENT_STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}</select>
          </Field>
        )}
        <ErrorBox error={error} />
        <div className="row"><button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Save"}</button><button type="button" className="btn" onClick={onClose}>Cancel</button></div>
      </form>
    </Modal>
  );
}
