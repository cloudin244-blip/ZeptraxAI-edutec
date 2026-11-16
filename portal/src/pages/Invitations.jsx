import { useState } from "react";
import { portal, query } from "../api.js";
import { roleOf, useAuth } from "../auth.jsx";
import { Badge, Button, Card, ErrorText, formatDate, PageHeader, Table, useLoad } from "../components/ui.jsx";
import SignupLinks from "./SignupLinks.jsx";

export const inviteLink = (token) => `${window.location.origin}/portal/#/register?token=${encodeURIComponent(token)}`;

export function downloadCsv(filename, rows) {
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
  const [revoking, setRevoking] = useState("");

  const revoke = async (campaign) => {
    if (!window.confirm(`Cancel the ${campaign.pending} unused invitations? People who already registered are not affected.`)) return;
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
      <PageHeader title="Signup links" description="Invite students to register and take their test." />
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
      <SignupLinks staff={staff} universities={universities?.universities || []} universityId={universityId} />
      {/* Coordinator invitations (sent from Universities) and personal links sent out earlier; none are created here any more */}
      <ErrorText>{error}</ErrorText>
      {data?.campaigns?.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold">Personal invitations</h2>
          <p className="mb-3 text-sm text-muted">
            Single-use invitations already sent, such as coordinator invitations from the Universities page. You can cancel the unused ones.
          </p>
          <Card>
            <Table columns={columns} rows={data.campaigns} empty="" />
          </Card>
        </section>
      )}
    </>
  );
}
