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
export const audioMime = (file: File) => MIME_BY_EXT[file.name.split(".").pop()?.toLowerCase() ?? ""] ?? file.type;
const mb = (n: number) => (n / 1024 / 1024).toFixed(2) + " MB";
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/** One call's audio (MySQL BLOB, playable) and its Groq transcription (MongoDB): [Upload call] → player → [Transcribe] → timed lines. */
export function CallRecording({ call, onChanged }: { call: any; onChanged: () => void }) {
  const { can } = useAuth();
  const fileInput = useRef<HTMLInputElement>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [audioError, setAudioError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<any | null>(null);
  const act = useAction();
  const hasRecording = !!call.has_recording;

  // The <audio> element cannot send our bearer token, so fetch the bytes and play a local blob URL.
  // Re-runs when the recording changes (new upload) and also loads a transcription that was stored earlier.
  useEffect(() => {
    setAudioError(null);
    if (!hasRecording) { setAudioUrl(null); setTranscript(null); return; }
    let dead = false;
    let url: string | null = null;
    (async () => {
      try {
        const res = await apiRaw(`/calls/${call.call_id}/recording`);
        const blobUrl = URL.createObjectURL(await res.blob());
        if (dead) URL.revokeObjectURL(blobUrl); else { url = blobUrl; setAudioUrl(blobUrl); }
      } catch (e: any) { if (!dead) setAudioError(e?.message ?? "Could not load the audio"); }
    })();
    (async () => {
      try { const t = await api(`/calls/${call.call_id}/transcription`); if (!dead) setTranscript(t); }
      catch { if (!dead) setTranscript(null); }          // 404 = not transcribed yet
    })();
    return () => { dead = true; if (url) URL.revokeObjectURL(url); };
  }, [call.call_id, hasRecording, call.audio_sha256]);

  const upload = (file: File) => act.run(async () => {
    await apiRaw(`/calls/${call.call_id}/recording?filename=${encodeURIComponent(file.name)}`, { method: "PUT", headers: { "Content-Type": audioMime(file) }, body: file });
    if (fileInput.current) fileInput.current.value = "";
    onChanged();
  });
  const transcribe = () => act.run(async () => { setTranscript(await api(`/calls/${call.call_id}/transcribe`, { method: "POST" })); });
  const remove = () => {
    if (!confirm("Remove this recording? The call record and any transcription are kept.")) return;
    act.run(async () => { await apiRaw(`/calls/${call.call_id}/recording`, { method: "DELETE" }); onChanged(); });
  };

  return (
    <div className="small-text">
      {can("admin", "dispatcher") && (
        <div className="row">
          <button type="button" className="btn small" onClick={() => fileInput.current?.click()} disabled={act.busy}>{hasRecording ? "Replace call audio" : "Upload call"}</button>
          <input ref={fileInput} type="file" hidden accept="audio/*,.mp3,.wav,.ogg,.flac,.m4a,.webm" aria-label={`Upload recording for call ${call.call_id}`}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); }} />
          {can("admin") && hasRecording && <button type="button" className="btn small danger" onClick={remove} disabled={act.busy}>Remove audio</button>}
        </div>)}
      {!hasRecording && !can("admin", "dispatcher") && <span className="muted">No recording</span>}

      {hasRecording && <>
        <div className="muted" style={{ marginTop: 6 }}>{call.audio_filename} · {mb(call.audio_size_bytes)}</div>
        {audioUrl ? <audio controls src={audioUrl} aria-label={`Recording of call ${call.call_id}`} />
          : audioError ? <ErrorBox error={audioError} /> : <div className="muted">Loading audio…</div>}
        <button type="button" className="btn small" onClick={transcribe} disabled={act.busy}>
          {act.busy ? "Working…" : transcript ? "Transcribe again" : "Transcribe"}
        </button>
      </>}

      <ErrorBox error={act.error} />
      {transcript && transcript.matches_current_recording === false && <Notice kind="warn">This transcript belongs to an earlier recording of this call. Transcribe again to update it.</Notice>}
      {transcript && (transcript.segments.length > 0
        ? <ul className="transcript">{transcript.segments.map((s: any, i: number) => (
            <li key={i}><span className="t">{clock(s.start)}–{clock(s.end)}</span><span>{s.speaker ? `${s.speaker}: ` : ""}{s.text}</span></li>))}</ul>
        : <p className="transcript">{transcript.text}</p>)}
    </div>
  );
}
