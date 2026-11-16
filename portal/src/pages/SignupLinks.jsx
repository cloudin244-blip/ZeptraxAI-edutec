import { useState } from "react";
import { portal, query } from "../api.js";
import { Badge, Button, Card, CopyButton, ErrorText, Field, formatDate, Loading, Modal, Notice, Table, useLoad } from "../components/ui.jsx";

export const joinLink = (code) => `${window.location.origin}/portal/#/join?code=${encodeURIComponent(code)}`;

const STATUS = {
  active: ["green", "Active"],
  expired: ["neutral", "Expired"],
  revoked: ["red", "Revoked"],
};

function shareText(link) {
  const what = link.test ? `sign up and take the "${link.test.title}" test` : "sign up on the ZeptraAI University Portal";
  return `Use this link to ${what}: ${joinLink(link.code)}`;
}

// One link per university: every student of that university uses it, up to the university's student limit
export default function SignupLinks({ staff, universities, universityId }) {
  const [data, error, reload] = useLoad(() => portal.get(`/invite-links${query({ university_id: universityId })}`), [universityId]);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState(null);
  const [revoking, setRevoking] = useState("");

  const revoke = async (link) => {
    if (!window.confirm("Turn off this signup link? Students who already registered keep their accounts.")) return;
    setRevoking(link.id);
    try {
      await portal.post(`/invite-links/${link.id}/revoke`);
      reload();
    } catch (err) {
      window.alert(err.message);
    }
    setRevoking("");
  };

  const columns = [
    {
      key: "label",
      label: "Link",
      render: (l) => (
        <div className="flex items-center gap-3">
          <div>
            <p className="font-medium">{l.label || "Signup link"}</p>
            <p className="font-mono text-xs text-muted">{l.code}</p>
          </div>
          {l.status === "active" && <CopyButton text={joinLink(l.code)} label="Copy link" />}
        </div>
      ),
    },
    ...(staff ? [{ key: "university_name", label: "University" }] : []),
    {
      key: "department",
      label: "Branch · batch",
      render: (l) => (
        <div>
          <p>{l.department || <span className="text-muted">Student enters</span>}</p>
          {l.batch && <p className="text-xs text-muted">{l.batch}</p>}
        </div>
      ),
    },
    { key: "test", label: "Test after signup", render: (l) => (l.test ? l.test.title : <span className="text-muted">Required test</span>) },
    { key: "signups", label: "Joined", render: (l) => l.signups },
    {
      key: "university_students",
      label: "Students / limit",
      render: (l) => (
        <span title="All students of this university on the portal, against its student limit (set on the Universities page)">
          {l.university_students}
          {l.university_limit ? ` / ${l.university_limit}` : <span className="text-muted"> (no limit)</span>}
        </span>
      ),
    },
    {
      key: "status",
      label: "Status",
      render: (l) => (
        <div>
          <Badge tone={STATUS[l.status][0]}>{STATUS[l.status][1]}</Badge>
          <p className="mt-1 text-xs text-muted">{l.status === "active" ? `until ${formatDate(l.expires_at)}` : formatDate(l.expires_at)}</p>
        </div>
      ),
    },
    {
      key: "actions",
      label: "",
      render: (l) =>
        l.status === "active" && (
          <Button variant="danger" loading={revoking === l.id} onClick={() => revoke(l)}>
            Turn off
          </Button>
        ),
    },
  ];

  return (
    <section className="mb-10">
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold">Shareable signup links</h2>
          <p className="text-sm text-muted">
            One link per university, shared with all its students on WhatsApp or email. Each student signs up with their own details and goes
            straight to the test. How many can join is the university's student limit.
          </p>
        </div>
        <Button className="shrink-0 whitespace-nowrap" onClick={() => setCreating(true)}>
          Create signup link
        </Button>
      </div>
      <ErrorText>{error}</ErrorText>
      <Card>{data ? <Table columns={columns} rows={data.links} empty="No signup links yet." /> : !error && <Loading />}</Card>
      {creating && (
        <CreateLinkForm
          staff={staff}
          universities={universities}
          defaultUniversity={universityId}
          onClose={() => setCreating(false)}
          onCreated={(link) => {
            setCreating(false);
            setCreated(link);
            reload();
          }}
        />
      )}
      {created && <CreatedModal link={created} onClose={() => setCreated(null)} />}
    </section>
  );
}

function CreatedModal({ link, onClose }) {
  const url = joinLink(link.code);
  return (
    <Modal title="Signup link ready" onClose={onClose}>
      <div className="space-y-4 text-sm">
        <Notice>Share this link with your students. You can copy it again from this page at any time.</Notice>
        <p className="break-all rounded-lg border border-border bg-background p-3 font-mono text-xs text-slate-300">{url}</p>
        <div className="flex flex-wrap justify-end gap-2">
          <a className="inline-flex items-center rounded-lg border border-border px-4 py-2 text-sm hover:bg-white/5" href={`https://wa.me/?text=${encodeURIComponent(shareText(link))}`} target="_blank" rel="noreferrer">
            Share on WhatsApp
          </a>
          <CopyButton text={url} label="Copy link" />
          <Button onClick={onClose}>Done</Button>
        </div>
      </div>
    </Modal>
  );
}

function CreateLinkForm({ staff, universities, defaultUniversity, onClose, onCreated }) {
  const [tests] = useLoad(() => portal.get("/assessments"), []);
  const [form, setForm] = useState({
    university_id: defaultUniversity || "",
    label: "",
    department: "",
    batch: "",
    assessment_id: "",
    expires_days: 30,
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = { ...form, expires_days: Number(form.expires_days) };
      if (!staff) delete body.university_id;
      const { link } = await portal.post("/invite-links", body);
      onCreated(link);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  const chosenTest = tests?.assessments?.find((t) => t.id === form.assessment_id);

  return (
    <Modal title="Create signup link" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        {staff && (
          <Field label="University" hint="Students who use this link join this university. Its student limit decides how many can join.">
            <select className="input" required value={form.university_id} onChange={set("university_id")}>
              <option value="">Choose a university</option>
              {universities
                .filter((u) => u.status === "active")
                .map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                  </option>
                ))}
            </select>
          </Field>
        )}
        <Field label="Name for this link" hint="Only you see this, e.g. “CSE 2027 placement drive”">
          <input className="input" maxLength={80} value={form.label} onChange={set("label")} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Branch" hint="Leave empty to let students enter theirs">
            <input className="input" maxLength={80} value={form.department} onChange={set("department")} placeholder="Any branch" />
          </Field>
          <Field label="Batch">
            <input className="input" maxLength={40} value={form.batch} onChange={set("batch")} placeholder="2023–2027" />
          </Field>
        </div>
        <Field label="Test after signup" hint="Students land on this test's start screen right after creating their account">
          <select className="input" value={form.assessment_id} onChange={set("assessment_id")}>
            <option value="">Their required test (default)</option>
            {(tests?.assessments || []).map((t) => (
              <option key={t.id} value={t.id}>
                {t.title}
                {t.status !== "published" ? " (draft)" : ""}
              </option>
            ))}
          </select>
        </Field>
        {chosenTest && chosenTest.status !== "published" && <Notice>This test is a draft. Publish it before students sign up, or they'll land on their dashboard instead.</Notice>}
        <Field label="Link expires after (days)">
          <input className="input" type="number" min={1} max={365} required value={form.expires_days} onChange={set("expires_days")} />
        </Field>
        <ErrorText>{error}</ErrorText>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={busy}>
            Create link
          </Button>
        </div>
      </form>
    </Modal>
  );
}
