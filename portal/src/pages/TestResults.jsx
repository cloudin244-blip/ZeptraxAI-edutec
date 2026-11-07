import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { portal, query } from "../api.js";
import { roleOf, useAuth } from "../auth.jsx";
import { Badge, Button, Card, ErrorText, formatDate, Loading, PageHeader, Stat, Table, useLoad } from "../components/ui.jsx";
import { downloadCsv } from "./Invitations.jsx";
import { TestFacts } from "./MyTests.jsx";

const STATUS = {
  submitted: ["green", "Submitted"],
  in_progress: ["blue", "In progress"],
  not_started: ["neutral", "Not started"],
};

export default function TestResults() {
  const { user } = useAuth();
  const staff = roleOf(user) === "staff";
  const [tests, testsError] = useLoad(() => portal.get("/assessments"), []);
  const [testId, setTestId] = useState("");
  const [universityId, setUniversityId] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [universities] = useLoad(() => (staff ? portal.get("/universities") : Promise.resolve(null)), [staff]);
  const selected = testId || tests?.assessments[0]?.id || "";
  const [data, error] = useLoad(
    () => (selected ? portal.get(`/assessments/${selected}/results${query({ university_id: universityId })}`) : Promise.resolve(null)),
    [selected, universityId]
  );

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (data?.results || []).filter(
      (r) => (!status || r.status === status) && (!q || [r.full_name, r.email, r.department, r.batch].some((v) => (v || "").toLowerCase().includes(q)))
    );
  }, [data, status, search]);

  if (testsError) return <ErrorText>{testsError}</ErrorText>;
  if (!tests) return <Loading />;
  if (!tests.assessments.length) return <Card className="p-6 text-sm text-muted">No tests yet.</Card>;

  const all = data?.results || [];
  const submitted = all.filter((r) => r.status === "submitted");
  const average = submitted.length ? (submitted.reduce((s, r) => s + r.score, 0) / submitted.length).toFixed(1) : null;
  const totalMarks = data?.assessment.total_marks;

  const exportCsv = () => {
    const header = ["Name", "Email", "University", "Department", "Batch", "Status", "Score", "Out of", "Correct", "Answered", "Submitted", "Auto-submitted", "Tab switches"];
    downloadCsv(`test-results-${new Date().toISOString().slice(0, 10)}.csv`, [
      header,
      ...rows.map((r) => [
        r.full_name, r.email, r.university_name, r.department, r.batch, STATUS[r.status][1],
        r.score ?? "", r.status === "submitted" ? totalMarks : "", r.correct ?? "", r.answered ?? "",
        r.submitted_at ? new Date(r.submitted_at * 1000).toLocaleString() : "", r.auto_submitted ? "yes" : "", r.tab_switches,
      ]),
    ]);
  };

  const columns = [
    {
      key: "full_name",
      label: "Student",
      render: (r) => (
        <div>
          <p className="font-medium">{r.full_name || "–"}</p>
          <p className="text-xs text-muted">{r.email}</p>
        </div>
      ),
    },
    ...(staff ? [{ key: "university_name", label: "University" }] : []),
    { key: "department", label: "Department" },
    { key: "batch", label: "Batch" },
    { key: "status", label: "Status", render: (r) => <Badge tone={STATUS[r.status][0]}>{STATUS[r.status][1]}</Badge> },
    {
      key: "score",
      label: "Score",
      render: (r) =>
        r.status === "submitted" ? (
          <span>
            <strong>{r.score}</strong> / {totalMarks}
            <span className="ml-2 text-xs text-muted">{Math.round((100 * r.score) / totalMarks)}%</span>
          </span>
        ) : (
          <span className="text-slate-600">–</span>
        ),
    },
    { key: "answered", label: "Answered", render: (r) => (r.answered ?? <span className="text-slate-600">–</span>) },
    {
      key: "tab_switches",
      label: "Left tab",
      render: (r) => (r.tab_switches ? <Badge tone={r.tab_switches > 3 ? "red" : "amber"}>{r.tab_switches}×</Badge> : <span className="text-slate-600">–</span>),
    },
    {
      key: "submitted_at",
      label: "Submitted",
      render: (r) => (r.submitted_at ? `${formatDate(r.submitted_at)}${r.auto_submitted ? " (time ran out)" : ""}` : <span className="text-slate-600">–</span>),
    },
  ];

  return (
    <>
      <PageHeader
        title="Test results"
        description={data ? <TestFacts test={data.assessment} /> : null}
        action={
          <div className="flex gap-2">
            {staff && selected && (
              <Link to={`/tests/${selected}/key`}>
                <Button variant="secondary">Answer key</Button>
              </Link>
            )}
            <Button variant="secondary" onClick={exportCsv} disabled={!rows.length}>
              Download CSV
            </Button>
          </div>
        }
      />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {tests.assessments.length > 1 && (
          <select className="input" value={selected} onChange={(e) => setTestId(e.target.value)} aria-label="Test">
            {tests.assessments.map((t) => (
              <option key={t.id} value={t.id}>
                {t.title}
              </option>
            ))}
          </select>
        )}
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
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="">All statuses</option>
          <option value="submitted">Submitted</option>
          <option value="in_progress">In progress</option>
          <option value="not_started">Not started</option>
        </select>
        <input className="input" placeholder="Search name, email, department…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search" />
      </div>
      <div className="mb-4 grid gap-4 sm:grid-cols-3">
        <Stat label="Students assigned" value={data ? all.length : null} />
        <Stat label="Submitted" value={data ? submitted.length : null} hint={all.length ? `${Math.round((100 * submitted.length) / all.length)}% of students` : undefined} />
        <Stat label="Average score" value={average ?? "–"} hint={average ? `out of ${totalMarks}` : undefined} />
      </div>
      <ErrorText>{error}</ErrorText>
      <Card>{data ? <Table columns={columns} rows={rows} empty={all.length ? "No students match these filters." : "No students are assigned yet."} /> : !error && <Loading />}</Card>
    </>
  );
}
