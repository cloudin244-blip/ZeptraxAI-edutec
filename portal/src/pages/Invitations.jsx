import { useState } from "react";
import { portal, query } from "../api.js";
import { roleOf, useAuth } from "../auth.jsx";
import { Badge, Button, Card, ErrorText, Field, formatDate, Loading, Modal, Notice, PageHeader, Table, useLoad } from "../components/ui.jsx";

export const inviteLink = (token) => `${window.location.origin}/portal/#/register?token=${encodeURIComponent(token)}`;

function downloadCsv(filename, rows) {
  const escape = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const csv = rows.map((r) => r.map(escape).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function Invitations() {
  const { user } = useAuth();
  const staff = roleOf(user) === "staff";
  const [universityId, setUniversityId] = useState("");
  const [universities] = useLoad(() => (staff ? portal.get("/universities") : Promise.resolve(null)), [staff]);
  const [data, error, reload] = useLoad(() => portal.get(`/campaigns${query({ university_id: universityId })}`), [universityId]);
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState("");

  const revoke = async (campaign) => {
    if (!window.confirm(`Cancel the ${campaign.pending} unused links in this batch? Students who already registered are not affected.`)) return;
    setRevoking(campaign.id);
    try {
      await portal.post(`/campaigns/${campaign.id}/revoke`);
      reload();
    } catch (err) {
      window.alert(err.message);
    }
    setRevoking("");
  };

  const columns = [
    { key: "created_at", label: "Created", render: (c) => formatDate(c.created_at) },
    ...(staff ? [{ key: "university_name", label: "University" }] : []),
    { key: "role", label: "For", render: (c) => <Badge tone={c.role === "student" ? "blue" : "amber"}>{c.role === "student" ? "Students" : "University admin"}</Badge> },
    { key: "department", label: "Department" },
    { key: "batch", label: "Batch" },
    {
      key: "usage",
      label: "Registered / links",
      render: (c) => (
        <span>
          {c.used} / {c.count}
          <span className="ml-2 text-xs text-muted">
            {c.pending} pending{c.expired ? ` · ${c.expired} expired` : ""}
            {c.revoked ? ` · ${c.revoked} cancelled` : ""}
          </span>
        </span>
      ),
    },
    { key: "expires_at", label: "Expires", render: (c) => formatDate(c.expires_at) },
    {
      key: "actions",
      label: "",
      render: (c) =>
        c.pending > 0 && (
          <Button variant="danger" loading={revoking === c.id} onClick={() => revoke(c)}>
            Cancel unused
          </Button>
        ),
    },
  ];

  return (
    <>
      <PageHeader
        title={staff ? "Invitations" : "Bulk invitations"}
        description="Each student gets their own single-use link that expires. Links are only shown when you create them, so download the CSV straight away."
        action={<Button onClick={() => setCreating(true)}>Generate student invitations</Button>}
      />
      {staff && universities && (
        <div className="mb-4 max-w-xs">
          <select className="input" value={universityId} onChange={(e) => setUniversityId(e.target.value)} aria-label="Filter by university">
            <option value="">All universities</option>
            {universities.universities.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>
        </div>
      )}
      <ErrorText>{error}</ErrorText>
      <Card>{data ? <Table columns={columns} rows={data.campaigns} empty="No invitations yet." /> : !error && <Loading />}</Card>
      {creating && (
        <BulkForm
          staff={staff}
          universities={universities?.universities || []}
          defaultUniversity={universityId}
          onClose={() => setCreating(false)}
          onCreated={reload}
        />
      )}
    </>
  );
}

function BulkForm({ staff, universities, defaultUniversity, onClose, onCreated }) {
  const { user } = useAuth();
  const [form, setForm] = useState({ university_id: defaultUniversity || "", department: "", batch: "", count: 50, expires_days: 15 });
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = { ...form, count: Number(form.count), expires_days: Number(form.expires_days) };
      if (!staff) delete body.university_id;
      const res = await portal.post("/invitations/bulk", body);
      setResult(res);
      onCreated();
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };

  const download = () => {
    const c = result.campaign;
    const uni = universities.find((u) => u.id === c.university_id)?.name || user?.university?.name || "";
    const rows = [["#", "Invitation link", "Code", "University", "Department", "Batch", "Expires"]];
    result.tokens.forEach((t, i) => rows.push([i + 1, inviteLink(t), t, uni, c.department, c.batch, formatDate(c.expires_at)]));
    const slug = [c.department, c.batch].filter(Boolean).join("-").replace(/[^\w-]+/g, "_") || "students";
    downloadCsv(`zeptra-invitations-${slug}.csv`, rows);
  };

  if (result) {
    return (
      <Modal title="Invitations created" onClose={onClose}>
        <div className="space-y-4">
          <Notice>
            {result.tokens.length} single-use links were created. Download them now: for security the portal keeps only a one-way fingerprint of each link, so they can't be shown again.
          </Notice>
          <div className="max-h-40 overflow-y-auto rounded-lg border border-border bg-background p-3 font-mono text-xs text-slate-300">
            {result.tokens.slice(0, 5).map((t) => (
              <p key={t} className="truncate">
                {inviteLink(t)}
              </p>
            ))}
            {result.tokens.length > 5 && <p className="text-muted">…and {result.tokens.length - 5} more in the CSV</p>}
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose}>
              Close
            </Button>
            <Button onClick={download}>Download CSV</Button>
          </div>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title="Generate student invitations" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        {staff && (
          <Field label="University">
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
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Department">
            <input className="input" value={form.department} onChange={set("department")} placeholder="Computer Science" />
          </Field>
          <Field label="Batch">
            <input className="input" value={form.batch} onChange={set("batch")} placeholder="2023–2027" />
          </Field>
          <Field label="Number of students" hint="Up to 1000 per batch">
            <input className="input" type="number" min={1} max={1000} required value={form.count} onChange={set("count")} />
          </Field>
          <Field label="Links expire after (days)">
            <input className="input" type="number" min={1} max={90} required value={form.expires_days} onChange={set("expires_days")} />
          </Field>
        </div>
        <ErrorText>{error}</ErrorText>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={busy}>
            Generate {form.count || ""} links
          </Button>
        </div>
      </form>
    </Modal>
  );
}
