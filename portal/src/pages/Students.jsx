import { useMemo, useState } from "react";
import { portal, query } from "../api.js";
import { roleOf, useAuth } from "../auth.jsx";
import { Badge, Button, Card, ErrorText, formatDate, Loading, PageHeader, Table, useLoad } from "../components/ui.jsx";
import { downloadCsv } from "./Invitations.jsx";

export default function Students() {
  const { user } = useAuth();
  const staff = roleOf(user) === "staff";
  const [universityId, setUniversityId] = useState("");
  const [search, setSearch] = useState("");
  const [department, setDepartment] = useState("");
  const [batch, setBatch] = useState("");
  const [program, setProgram] = useState("");
  const [accountStatus, setAccountStatus] = useState("");
  const [busy, setBusy] = useState("");
  const [actionError, setActionError] = useState("");
  const [universities] = useLoad(() => (staff ? portal.get("/universities") : Promise.resolve(null)), [staff]);
  const [data, error, reload] = useLoad(() => portal.get(`/students${query({ university_id: universityId })}`), [universityId]);
  const chooseUniversity = (id) => {
    // Branch, batch and program options come from the loaded students, so start the other filters afresh
    setUniversityId(id);
    setDepartment("");
    setBatch("");
    setProgram("");
  };

  const toggleStatus = async (s) => {
    const next = s.status === "inactive" ? "active" : "inactive";
    if (next === "inactive" && !window.confirm(`Deactivate ${s.full_name || s.email}? They won't be able to sign in or take tests until reactivated. Their results are kept.`)) return;
    setBusy(s.id);
    setActionError("");
    try {
      await portal.put(`/accounts/${s.id}/status`, { status: next });
      reload();
    } catch (err) {
      setActionError(err.message);
    }
    setBusy("");
  };

  const students = data?.students || [];
  const departments = useMemo(() => [...new Set(students.map((s) => s.department).filter(Boolean))].sort(), [students]);
  const batches = useMemo(() => [...new Set(students.map((s) => s.batch).filter(Boolean))].sort(), [students]);
  const programs = useMemo(() => [...new Map(students.filter((s) => s.program_slug).map((s) => [s.program_slug, s.program_title])).entries()].sort((a, b) => a[1].localeCompare(b[1])), [students]);
  const q = search.trim().toLowerCase();
  const rows = students.filter(
    (s) =>
      (!department || s.department === department) &&
      (!batch || s.batch === batch) &&
      (!program || (program === "none" ? !s.program_slug : s.program_slug === program)) &&
      (!accountStatus || (s.status || "active") === accountStatus) &&
      (!q || [s.full_name, s.email, s.registration_number, s.phone].some((v) => (v || "").toLowerCase().includes(q)))
  );

  const columns = [
    {
      key: "full_name",
      label: "Student",
      render: (s) => (
        <div>
          <p className="font-medium">{s.full_name || "–"}</p>
          <p className="text-xs text-muted">{s.email}</p>
          {s.phone && <p className="text-xs text-muted">{s.phone}</p>}
        </div>
      ),
    },
    ...(staff ? [{ key: "university_name", label: "University" }] : []),
    { key: "program_title", label: "Program", render: (s) => s.program_title || <span className="text-amber-300">Not chosen</span> },
    { key: "degree", label: "Degree" },
    { key: "department", label: "Branch" },
    { key: "batch", label: "Batch" },
    { key: "registration_number", label: "Reg. no." },
    {
      key: "profile_completion",
      label: "Profile",
      render: (s) => <Badge tone={s.profile_completion === 100 ? "green" : s.profile_completion >= 50 ? "amber" : "red"}>{s.profile_completion}%</Badge>,
    },
    { key: "created_at", label: "Joined", render: (s) => formatDate(s.created_at) },
    {
      key: "actions",
      label: "",
      render: (s) => (
        <div className="flex items-center justify-end gap-2">
          {s.status === "inactive" && <Badge tone="red">Deactivated</Badge>}
          <Button variant={s.status === "inactive" ? "secondary" : "danger"} loading={busy === s.id} onClick={() => toggleStatus(s)}>
            {s.status === "inactive" ? "Reactivate" : "Deactivate"}
          </Button>
        </div>
      ),
    },
  ];

  const exportCsv = () =>
    downloadCsv(`students-${new Date().toISOString().slice(0, 10)}.csv`, [
      ["Name", "Email", "Phone", "University", "Program", "Degree", "Branch", "Batch", "Reg. no.", "Graduation year", "Status", "Joined"],
      ...rows.map((s) => [
        s.full_name, s.email, s.phone, s.university_name, s.program_title, s.degree, s.department, s.batch, s.registration_number,
        s.graduation_year, s.status || "active", s.created_at ? new Date(s.created_at * 1000).toLocaleDateString() : "",
      ]),
    ]);

  return (
    <>
      <PageHeader
        title="Students"
        description={`${rows.length} of ${students.length} students`}
        action={
          <Button variant="secondary" onClick={exportCsv} disabled={!rows.length}>
            Download CSV
          </Button>
        }
      />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <input className="input" placeholder="Search name, email, phone or reg. no." value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search students" />
        {staff && (
          <select className="input" value={universityId} onChange={(e) => chooseUniversity(e.target.value)} aria-label="University">
            <option value="">All universities</option>
            {universities?.universities.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>
        )}
        <select className="input" value={program} onChange={(e) => setProgram(e.target.value)} aria-label="Program">
          <option value="">All programs</option>
          {programs.map(([slug, title]) => (
            <option key={slug} value={slug}>
              {title}
            </option>
          ))}
          <option value="none">Program not chosen</option>
        </select>
        <select className="input" value={department} onChange={(e) => setDepartment(e.target.value)} aria-label="Department">
          <option value="">All branches</option>
          {departments.map((d) => (
            <option key={d}>{d}</option>
          ))}
        </select>
        <select className="input" value={batch} onChange={(e) => setBatch(e.target.value)} aria-label="Batch">
          <option value="">All batches</option>
          {batches.map((b) => (
            <option key={b}>{b}</option>
          ))}
        </select>
        <select className="input" value={accountStatus} onChange={(e) => setAccountStatus(e.target.value)} aria-label="Account status">
          <option value="">All accounts</option>
          <option value="active">Active only</option>
          <option value="inactive">Deactivated only</option>
        </select>
      </div>
      <ErrorText>{error || actionError}</ErrorText>
      <Card>{data ? <Table columns={columns} rows={rows} empty={students.length ? "No students match these filters." : "No students have registered yet."} /> : !error && <Loading />}</Card>
    </>
  );
}
