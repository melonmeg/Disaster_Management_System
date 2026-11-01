"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAction, useApi } from "@/lib/hooks";
import { dt } from "@/lib/format";
import { Async, Badge, ErrorBox, Field, Modal, Notice, PageHeader } from "@/components/ui";

type Kind = "admin" | "dispatcher" | "field";
const KINDS: { value: Kind; label: string; help: string }[] = [
  { value: "field", label: "Responder (police, fire, medical, rescue)", help: "Sees incidents, updates their availability, and edits patients on incidents their unit is dispatched to." },
  { value: "dispatcher", label: "Dispatcher", help: "Runs incidents, calls and dispatches. Calls they log are recorded under their name." },
  { value: "admin", label: "Administrator", help: "Full access, including accounts, units and resources. Not linked to a person record." },
];
const FIELD_TYPES = ["Police Officer", "Firefighter", "Paramedic", "Rescue Technician"];

/** Creates the login AND the person it belongs to in one step (POST /users). */
function NewAccount({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const orgs = useApi<any>("/organizations?page_size=100");
  const units = useApi<any>("/units?page_size=100");
  const [kind, setKind] = useState<Kind>("field");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [type, setType] = useState(FIELD_TYPES[0]);
  const [otherType, setOtherType] = useState("");
  const [org, setOrg] = useState("");
  const [unit, setUnit] = useState("");
  const { busy, error, run } = useAction();

  const isPerson = kind !== "admin";
  const hasUnit = kind === "field";
  // a unit must belong to the chosen organisation
  const unitOptions = (units.data?.data ?? []).filter((u: any) => u.organization_id === Number(org));
  const help = KINDS.find((k) => k.value === kind)!.help;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const responder_type = kind === "dispatcher" ? "Dispatcher" : type === "__other" ? otherType : type;
    const body: any = { username, password, role: kind === "admin" ? "admin" : kind === "dispatcher" ? "dispatcher" : "responder" };
    if (isPerson) body.person = {
      first_name: first, last_name: last, phone: phone || null, email: email || null, responder_type,
      organization_id: Number(org), unit_id: hasUnit && unit ? Number(unit) : null,
    };
    const ok = await run(() => api("/users", { method: "POST", json: body }));
    if (ok) { onSaved(); onClose(); }
  };

  return (
    <Modal title="New account" onClose={onClose}>
      <form onSubmit={submit}>
        <Field label="Account type" hint={help}><select value={kind} onChange={(e) => { setKind(e.target.value as Kind); setUnit(""); }}>
          {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}</select></Field>

        {isPerson && <>
          <div className="row">
            <Field label="First name"><input value={first} onChange={(e) => setFirst(e.target.value)} maxLength={50} required /></Field>
            <Field label="Last name"><input value={last} onChange={(e) => setLast(e.target.value)} maxLength={50} required /></Field>
          </div>
          {kind === "field" && (
            <Field label="Role"><select value={type} onChange={(e) => setType(e.target.value)}>
              {FIELD_TYPES.map((t) => <option key={t}>{t}</option>)}<option value="__other">Other…</option></select>
              {type === "__other" && <input value={otherType} onChange={(e) => setOtherType(e.target.value)} maxLength={50} placeholder="e.g. Fire Marshal" required />}</Field>)}
          <Field label="Organisation" hint="Their employer, for example the police department or fire service.">
            <select value={org} onChange={(e) => { setOrg(e.target.value); setUnit(""); }} required>
              <option value="">Select…</option>
              {orgs.data?.data.map((o: any) => <option key={o.organization_id} value={o.organization_id}>{o.organization_name}</option>)}</select></Field>
          {hasUnit && (
            <Field label="Unit (optional)" hint={org ? "Units of that organisation." : "Choose an organisation first."}>
              <select value={unit} onChange={(e) => setUnit(e.target.value)}>
                <option value="">Not assigned to a unit</option>
                {unitOptions.map((u: any) => <option key={u.unit_id} value={u.unit_id}>{u.unit_name}{u.unit_type ? ` — ${u.unit_type}` : ""}</option>)}</select></Field>)}
          <div className="row">
            <Field label="Phone"><input value={phone} maxLength={20} pattern="[0-9+\- ]{6,20}" title="Digits, +, - and spaces (6–20 characters)" onChange={(e) => setPhone(e.target.value)} /></Field>
            <Field label="Email"><input type="email" value={email} maxLength={100} onChange={(e) => setEmail(e.target.value)} /></Field>
          </div>
        </>}

        <h3 style={{ marginBottom: 4 }}>Sign-in</h3>
        <Field label="Username" hint="3–50 characters: letters, digits, dot, dash, underscore."><input value={username} onChange={(e) => setUsername(e.target.value)} minLength={3} maxLength={50} pattern="[A-Za-z0-9_.\-]+" required autoComplete="off" /></Field>
        <Field label="Password" hint="At least 8 characters. They can be asked to keep it private; you can reset it later."><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} maxLength={128} required autoComplete="new-password" /></Field>
        <ErrorBox error={error} />
        <div className="row"><button className="btn primary" disabled={busy}>{busy ? "Creating…" : "Create account"}</button><button type="button" className="btn" onClick={onClose}>Cancel</button></div>
      </form>
    </Modal>
  );
}

function ResetPassword({ user, onClose }: { user: any; onClose: () => void }) {
  const [password, setPassword] = useState("");
  const { busy, error, ok, run } = useAction();
  return (
    <Modal title={`Reset password for ${user.username}`} onClose={onClose}>
      <form onSubmit={async (e) => { e.preventDefault(); await run(() => api(`/users/${user.user_id}`, { method: "PATCH", json: { password } }), "Password changed. Their current session was ended."); setPassword(""); }}>
        <Field label="New password" hint="At least 8 characters."><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} maxLength={128} required autoComplete="new-password" /></Field>
        <ErrorBox error={error} />{ok && <Notice kind="ok">{ok}</Notice>}
        <div className="row"><button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Change password"}</button><button type="button" className="btn" onClick={onClose}>Close</button></div>
      </form>
    </Modal>
  );
}

/** Admin only: create and manage logins. There is no public sign-up: anyone able to register could dispatch units. */
export default function UsersPage() {
  const { can, user: me } = useAuth();
  const users = useApi<any>(can("admin") ? "/users" : null);
  const responders = useApi<any>(can("admin") ? "/responders?page_size=100" : null);
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState<any | null>(null);
  const act = useAction();
  if (!can("admin")) return <Notice kind="warn">Only administrators can manage accounts.</Notice>;
  const nameOf = (id: number | null) => id ? (responders.data?.data.find((r: any) => r.responder_id === id)?.full_name ?? `#${id}`) : "—";

  return (
    <>
      <PageHeader title="Accounts"><button className="btn primary" onClick={() => setCreating(true)}>New account</button></PageHeader>
      <p className="muted">These are the people who can sign in to this console. Accounts are created by an administrator only. Deactivating someone ends their session, blocks sign-in and takes them off their unit’s crew; their name stays on past calls and records. Accounts are deactivated, not deleted.</p>
      <ErrorBox error={act.error} />{act.ok && <Notice kind="ok">{act.ok}</Notice>}
      <Async state={users} empty={(d) => d.data.length === 0}>{(d) => (
        <div className="card tablewrap"><table><thead><tr><th>Username</th><th>Role</th><th>Responder record</th><th>Status</th><th>Last sign-in</th><th /></tr></thead><tbody>
          {d.data.map((u: any) => (
            <tr key={u.user_id}><td>{u.username}{u.user_id === me?.user_id && <span className="muted"> (you)</span>}</td>
              <td style={{ textTransform: "capitalize" }}>{u.role}</td><td>{nameOf(u.responder_id)}</td>
              <td><Badge value={u.is_active ? "ACTIVE" : "INACTIVE"} /></td><td>{u.last_login_at ? dt(u.last_login_at) : "never"}</td>
              <td><span className="row">
                <button className="btn small" onClick={() => setResetting(u)}>Reset password</button>
                <button className="btn small" disabled={act.busy || u.user_id === me?.user_id} title={u.user_id === me?.user_id ? "You cannot deactivate your own account" : undefined}
                  onClick={() => act.run(async () => { await api(`/users/${u.user_id}`, { method: "PATCH", json: { is_active: !u.is_active } }); users.reload(); }, u.is_active ? `${u.username} deactivated${u.responder_id ? " and taken off their unit" : ""}` : `${u.username} reactivated`)}>
                  {u.is_active ? "Deactivate" : "Reactivate"}</button></span></td></tr>))}
        </tbody></table></div>)}</Async>
      {creating && <NewAccount onClose={() => setCreating(false)} onSaved={() => { users.reload(); responders.reload(); }} />}
      {resetting && <ResetPassword user={resetting} onClose={() => setResetting(null)} />}
    </>
  );
}
