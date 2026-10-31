"use client";
import { useRef, useState } from "react";
import { api, apiRaw } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAction, useApi } from "@/lib/hooks";
import { SEVERITIES } from "@/lib/format";
import { ErrorBox, Field, Modal, Notice } from "./ui";
import { audioMime } from "./CallRecording";

/** Log an emergency call against an incident, optionally with its audio recording (saved in MySQL). Transcription is a separate button on the call. */
export function LogCallForm({ incident, onClose, onSaved }: { incident: any; onClose: () => void; onSaved: () => void }) {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const dispatchers = useApi<any>(isAdmin ? "/responders?responder_type=Dispatcher&page_size=100" : null);
  const [caller, setCaller] = useState("");
  const [phone, setPhone] = useState("");
  const [priority, setPriority] = useState(incident.severity ?? "MEDIUM");
  const [location, setLocation] = useState(incident.location ?? "");
  const [notes, setNotes] = useState("");
  const [receivedBy, setReceivedBy] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const { busy, error, run } = useAction();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setWarning(null);
    const created = await run(() => api("/calls", { method: "POST", json: {
      incident_id: incident.incident_id, caller_name: caller || null, caller_phone: phone || null, location: location || null,
      priority, transcript: notes || null, ...(isAdmin && receivedBy ? { received_by: Number(receivedBy) } : {}),
    } }));
    if (!created) return;
    let problem: string | null = null;
    if (file) {
      try { await apiRaw(`/calls/${created.call_id}/recording?filename=${encodeURIComponent(file.name)}`, { method: "PUT", headers: { "Content-Type": audioMime(file) }, body: file }); }
      catch (err: any) { problem = `Call saved, but the recording was not: ${err?.message ?? "unknown error"}. Use “Upload call” on the call to try again.`; }
    }
    onSaved();
    if (problem) setWarning(problem); else onClose();
  };

  return (
    <Modal title={`Log call for incident #${incident.incident_id}`} onClose={onClose}>
      <form onSubmit={submit}>
        {isAdmin && (
          <Field label="Received by" hint="Your admin login has no responder record, so choose the dispatcher who took the call.">
            <select value={receivedBy} onChange={(e) => setReceivedBy(e.target.value)} required>
              <option value="">Select dispatcher…</option>
              {dispatchers.data?.data.map((r: any) => <option key={r.responder_id} value={r.responder_id}>{r.full_name}</option>)}
            </select>
          </Field>)}
        <Field label="Caller name"><input value={caller} maxLength={100} onChange={(e) => setCaller(e.target.value)} /></Field>
        <Field label="Caller phone"><input value={phone} maxLength={20} pattern="[0-9+\- ]{6,20}" title="Digits, +, - and spaces (6–20 characters)" onChange={(e) => setPhone(e.target.value)} /></Field>
        <Field label="Priority"><select value={priority} onChange={(e) => setPriority(e.target.value)}>{SEVERITIES.map((s) => <option key={s}>{s}</option>)}</select></Field>
        <Field label="Location the caller gave"><input value={location} maxLength={255} onChange={(e) => setLocation(e.target.value)} /></Field>
        <Field label="Notes" hint="What the caller reported (stored as the call's text).">
          <textarea value={notes} rows={3} maxLength={100000} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <Field label="Audio recording (optional)" hint="mp3, wav, ogg, flac, m4a or webm. It is stored in the database; press Transcribe on the call afterwards if you want a transcript.">
          <span className="row">
            <button type="button" className="btn small" onClick={() => fileInput.current?.click()} disabled={busy}>{file ? "Change file" : "Choose audio file"}</button>
            <span className="muted">{file ? file.name : "No file chosen"}</span>
            <input ref={fileInput} type="file" hidden accept="audio/*,.mp3,.wav,.ogg,.flac,.m4a,.webm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </span>
        </Field>
        <ErrorBox error={error} />
        {warning && <Notice kind="warn">{warning}</Notice>}
        <div className="row">
          <button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Log call"}</button>
          <button type="button" className="btn" onClick={onClose}>{warning ? "Close" : "Cancel"}</button>
        </div>
      </form>
    </Modal>
  );
}
