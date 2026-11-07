import { useMemo, useState } from "react";
import { portal, query } from "../api.js";
import { roleOf, useAuth } from "../auth.jsx";
import { Badge, Card, ErrorText, formatDate, Loading, PageHeader, Table, useLoad } from "../components/ui.jsx";

export default function Students() {
  const { user } = useAuth();
  const staff = roleOf(user) === "staff";
  const [universityId, setUniversityId] = useState("");
  const [search, setSearch] = useState("");
  const [department, setDepartment] = useState("");
  const [batch, setBatch] = useState("");
  const [program, setProgram] = useState("");
  const [universities] = useLoad(() => (staff ? portal.get("/universities") : Promise.resolve(null)), [staff]);
  const [data, error] = useLoad(() => portal.get(`/students${query({ university_id: universityId })}`), [universityId]);

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
      (!q || [s.full_name, s.email, s.registration_number].some((v) => (v || "").toLowerCase().includes(q)))
  );

  const columns = [
    {
      key: "full_name",
      label: "Student",
      render: (s) => (
        <div>
          <p className="font-medium">{s.full_name || "–"}</p>
          <p className="text-xs text-muted">{s.email}</p>
        </div>
      ),
    },
    ...(staff ? [{ key: "university_name", label: "University" }] : []),
    { key: "program_title", label: "Program", render: (s) => s.program_title || <span className="text-amber-300">Not chosen</span> },
    { key: "department", label: "Department" },
    { key: "batch", label: "Batch" },
    { key: "registration_number", label: "Reg. no." },
    {
      key: "profile_completion",
      label: "Profile",
      render: (s) => <Badge tone={s.profile_completion === 100 ? "green" : s.profile_completion >= 50 ? "amber" : "red"}>{s.profile_completion}%</Badge>,
    },
    { key: "created_at", label: "Joined", render: (s) => formatDate(s.created_at) },
  ];

  return (
    <>
      <PageHeader title="Students" description={`${rows.length} of ${students.length} students`} />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <input className="input" placeholder="Search name, email or reg. no." value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search students" />
        {staff && (
          <select className="input" value={universityId} onChange={(e) => setUniversityId(e.target.value)} aria-label="University">
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
          <option value="">All departments</option>
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
      </div>
      <ErrorText>{error}</ErrorText>
      <Card>{data ? <Table columns={columns} rows={rows} empty={students.length ? "No students match these filters." : "No students have registered yet."} /> : !error && <Loading />}</Card>
    </>
  );
}
