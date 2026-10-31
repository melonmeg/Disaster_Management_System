"use client";
import { useEffect, useRef, useState } from "react";
import { api, apiRaw } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAction } from "@/lib/hooks";
import { ErrorBox, Notice } from "./ui";

const MIME_BY_EXT: Record<string, string> = {
  mp3: "audio/mpeg", wav: "audio/wav", ogg: "audio/ogg", oga: "audio/ogg", flac: "audio/flac",
  m4a: "audio/x-m4a", mp4: "audio/mp4", webm: "audio/webm",
};
const mb = (n: number) => (n / 1024 / 1024).toFixed(2) + " MB";
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/** Audio recording (MySQL BLOB) and transcription (MongoDB) of one call. */
export function CallRecording({ call, onChanged }: { call: any; onChanged: () => void }) {
  const { can } = useAuth();
  const fileInput = useRef<HTMLInputElement>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<any | "none" | null>(null);
  const act = useAction();

  // the browser <audio> element cannot send our bearer token, so fetch the bytes and play a local blob URL
  useEffect(() => () => { if (audioUrl) URL.revokeObjectURL(audioUrl); }, [audioUrl]);
  useEffect(() => { setAudioUrl(null); setTranscript(null); }, [call.audio_sha256]);

  const load = () => act.run(async () => {
    const res = await apiRaw(`/calls/${call.call_id}/recording`);
    setAudioUrl(URL.createObjectURL(await res.blob()));
  });
  const loadTranscript = () => act.run(async () => {
    try { setTranscript(await api(`/calls/${call.call_id}/transcription`)); }
    catch (e: any) { if (e?.status === 404) setTranscript("none"); else throw e; }
  });
  // Groq speech-to-text: the backend reads the stored audio, transcribes it and saves the result in MongoDB
  const transcribe = async () => { setTranscript(await api(`/calls/${call.call_id}/transcribe`, { method: "POST" })); };
  const doTranscribe = () => act.run(transcribe, "Transcription saved");
  const upload = (file: File) => act.run(async () => {
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    const type = MIME_BY_EXT[ext] ?? file.type;
    await apiRaw(`/calls/${call.call_id}/recording?filename=${encodeURIComponent(file.name)}`, { method: "PUT", headers: { "Content-Type": type }, body: file });
    if (fileInput.current) fileInput.current.value = "";
    onChanged();
    // A failed transcription must not hide that the upload worked: the Transcribe button stays available.
    try { await transcribe(); } catch (e: any) { setTranscript(null); throw new Error(`Recording saved, but transcription failed: ${e?.message ?? "unknown error"}`); }
  }, "Recording saved and transcribed");
  const remove = () => {
    if (!confirm("Remove this recording? The call record and any transcription are kept.")) return;
    act.run(async () => { await apiRaw(`/calls/${call.call_id}/recording`, { method: "DELETE" }); onChanged(); }, "Recording removed");
  };

  return (
    <div className="small-text">
      {call.has_recording ? <>
        <div>{call.audio_filename} · {mb(call.audio_size_bytes)}</div>
        {audioUrl ? <audio controls src={audioUrl} style={{ width: 220 }} aria-label={`Recording of call ${call.call_id}`} />
          : <button className="btn small" onClick={load} disabled={act.busy}>Load audio</button>}
        {" "}<button className="btn small" onClick={loadTranscript} disabled={act.busy}>Transcription</button>
        {" "}<button className="btn small" onClick={doTranscribe} disabled={act.busy}>{act.busy ? "Working…" : "Transcribe"}</button>
        {can("admin") && <>{" "}<button className="btn small danger" onClick={remove} disabled={act.busy}>Remove</button></>}
      </> : <span className="muted">No recording</span>}
      {can("admin", "dispatcher") && (
        <div style={{ marginTop: 4 }}>
          <input ref={fileInput} type="file" accept="audio/*,.mp3,.wav,.ogg,.flac,.m4a,.webm" aria-label={`Upload recording for call ${call.call_id}`}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); }} disabled={act.busy} />
        </div>)}
      <ErrorBox error={act.error} />
      {act.ok && <Notice kind="ok">{act.ok}</Notice>}
      {transcript === "none" && <p className="muted">No transcription stored for this call yet.</p>}
      {transcript && transcript !== "none" && (
        <div className="card" style={{ marginTop: 6 }}>
          <div className="muted">{transcript.engine ?? "unknown engine"} · {transcript.language ?? "language unknown"}</div>
          {transcript.matches_current_recording === false && <Notice kind="warn">This transcription was made from a different recording than the current one.</Notice>}
          <p>{transcript.text}</p>
          {transcript.segments.length > 0 && <ul style={{ paddingLeft: 16 }}>{transcript.segments.map((s: any, i: number) => (
            <li key={i}><span className="muted">{clock(s.start)}–{clock(s.end)}{s.speaker ? ` ${s.speaker}` : ""}</span> {s.text}</li>))}</ul>}
        </div>)}
    </div>
  );
}
