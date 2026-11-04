import { useState } from "react";
import { portal } from "../api.js";
import { Badge, Button, Card, CopyButton, ErrorText, Field, Loading, Modal, Notice, PageHeader, Table, useLoad } from "../components/ui.jsx";
import { inviteLink } from "./Invitations.jsx";

export default function Universities() {
  const [data, error, reload] = useLoad(() => portal.get("/universities"), []);
  const [editing, setEditing] = useState(null); // {} for new, university for edit
  const [inviting, setInviting] = useState(null);

  const columns = [
    {
      key: "name",
      label: "University",
      render: (u) => (
        <div>
          <p className="font-medium">{u.name}</p>
          <p className="text-xs text-muted">Code {u.code}</p>
        </div>
      ),
    },
    { key: "status", label: "Status", render: (u) => <Badge tone={u.status === "active" ? "green" : "red"}>{u.status}</Badge> },
    { key: "students", label: "Students", render: (u) => `${u.students}${u.max_students ? ` / ${u.max_students}` : ""}` },
    { key: "pending_invitations", label: "Pending invites", render: (u) => u.pending_invitations },
    { key: "admins", label: "Admins", render: (u) => u.admins },
    {
      key: "actions",
      label: "",
      render: (u) => (
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setInviting(u)}>
            Invite admin
          </Button>
          <Button variant="secondary" onClick={() => setEditing(u)}>
            Edit
          </Button>
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader title="Universities" description="Universities on the portal, their student limits and admins." action={<Button onClick={() => setEditing({})}>Add university</Button>} />
      <ErrorText>{error}</ErrorText>
      <Card>{data ? <Table columns={columns} rows={data.universities} empty="No universities yet. Add the first one." /> : !error && <Loading />}</Card>
      {editing && (
        <UniversityForm
          university={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            reload();
          }}
        />
      )}
      {inviting && <AdminInvite university={inviting} onClose={() => setInviting(null)} />}
    </>
  );
}

function UniversityForm({ university, onClose, onSaved }) {
  const isNew = !university.id;
  const [form, setForm] = useState({
    name: university.name || "",
    code: university.code || "",
    max_students: university.max_students || "",
    status: university.status || "active",
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (isNew) await portal.post("/universities", form);
      else await portal.put(`/universities/${university.id}`, { name: form.name, max_students: form.max_students, status: form.status });
      onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <Modal title={isNew ? "Add university" : `Edit ${university.name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="University name">
          <input className="input" required value={form.name} onChange={set("name")} placeholder="Mewar University" />
        </Field>
        {isNew && (
          <Field label="Short code" hint="2–8 letters or digits. Appears in invitation codes, e.g. ZP-MEW-…">
            <input className="input uppercase" required value={form.code} onChange={set("code")} placeholder="MEW" maxLength={8} />
          </Field>
        )}
        <Field label="Maximum students" hint="Leave empty for no limit. Pending invitations count towards the limit.">
          <input className="input" type="number" min={1} value={form.max_students} onChange={set("max_students")} placeholder="500" />
        </Field>
        {!isNew && (
          <Field label="Status" hint="Inactive universities can't create invitations, and their invitation links stop working.">
            <select className="input" value={form.status} onChange={set("status")}>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </Field>
        )}
        <ErrorText>{error}</ErrorText>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={busy}>
            {isNew ? "Add university" : "Save"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function AdminInvite({ university, onClose }) {
  const [days, setDays] = useState(7);
  const [link, setLink] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true);
    setError("");
    try {
      const { tokens } = await portal.post("/admin-invitations", { university_id: university.id, expires_days: days });
      setLink(inviteLink(tokens[0]));
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };

  return (
    <Modal title={`Invite an admin for ${university.name}`} onClose={onClose}>
      {link ? (
        <div className="space-y-4">
          <Notice>Copy this link now and send it to the university coordinator. It works once, and for security it can't be shown again.</Notice>
          <input className="input font-mono text-xs" readOnly value={link} onFocus={(e) => e.target.select()} />
          <div className="flex justify-end gap-2">
            <CopyButton text={link} label="Copy link" />
            <Button onClick={onClose}>Done</Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-muted">The coordinator registers with this link and can then manage only {university.name}'s students.</p>
          <Field label="Link expires after (days)">
            <input className="input" type="number" min={1} max={30} value={days} onChange={(e) => setDays(e.target.value)} />
          </Field>
          <ErrorText>{error}</ErrorText>
          <div className="flex justify-end">
            <Button onClick={create} loading={busy}>
              Create admin link
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
