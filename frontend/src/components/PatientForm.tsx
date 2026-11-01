"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import { ErrorBox, Field, Modal } from "./ui";

/** Add a patient to an incident, or edit one. The server numbers new patients within the incident. */
export function PatientForm({ incidentId, patient, onClose, onSaved }: { incidentId: number; patient?: any; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(patient?.patient_name ?? "");
  const [age, setAge] = useState(patient?.age?.toString() ?? "");
  const [gender, setGender] = useState(patient?.gender ?? "");
  const [condition, setCondition] = useState(patient?.patient_condition ?? "");
  const { busy, error, run } = useAction();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const body = { patient_name: name || null, age: age === "" ? null : Number(age), gender: gender || null, patient_condition: condition || null };
    const ok = await run(() => patient
      ? api(`/incidents/${incidentId}/patients/${patient.patient_no}`, { method: "PATCH", json: body })
      : api(`/incidents/${incidentId}/patients`, { method: "POST", json: body }));
    if (ok) { onSaved(); onClose(); }
  };

  return (
    <Modal title={patient ? `Edit patient #${patient.patient_no}` : "Add patient"} onClose={onClose}>
      <form onSubmit={submit}>
        <Field label="Name" hint="Leave blank if unknown."><input value={name} maxLength={100} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Age"><input type="number" min={0} max={130} value={age} onChange={(e) => setAge(e.target.value)} /></Field>
        <Field label="Gender"><select value={gender} onChange={(e) => setGender(e.target.value)}>
          <option value="">Not recorded</option><option>Female</option><option>Male</option><option>Other</option></select></Field>
        <Field label="Condition" hint="e.g. Smoke inhalation; breathing difficulty, stabilised"><textarea rows={2} value={condition} maxLength={100} onChange={(e) => setCondition(e.target.value)} /></Field>
        <ErrorBox error={error} />
        <div className="row"><button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Save"}</button><button type="button" className="btn" onClick={onClose}>Cancel</button></div>
      </form>
    </Modal>
  );
}
