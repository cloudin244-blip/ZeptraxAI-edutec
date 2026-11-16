import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { portal, query } from "../api.js";
import { roleOf, useAuth } from "../auth.jsx";
import { Badge, Button, Card, ErrorText, Field, formatDate, Loading, Modal, PageHeader, Stat, Table, useLoad } from "../components/ui.jsx";
import { downloadCsv } from "./Invitations.jsx";
import { TestFacts } from "./MyTests.jsx";

const STATUS = {
  submitted: ["green", "Submitted"],
  malpractice: ["red", "Malpractice"],
  in_progress: ["blue", "In progress"],
  not_started: ["neutral", "Not started"],
};

const EVENT_LABEL = {
  tab_hidden: "Left the test tab",
  window_blur: "Switched to another window",
  fullscreen_exit: "Left full screen",
  no_person: "Not visible on camera",
  camera_off: "Camera turned off",
  phone_detected: "Mobile phone detected",
  multiple_people: "Another person detected",
  proctor_unavailable: "Camera detection couldn't load on this device",
  fullscreen_unavailable: "Full screen not supported on this device",
};

// "malpractice" is shown as its own status even though the attempt itself is submitted
const statusOf = (r) => (r.malpractice ? "malpractice" : r.status);

export default function TestResults() {
  const { user } = useAuth();
  const staff = roleOf(user) === "staff";
  const [tests, testsError] = useLoad(() => portal.get("/assessments"), []);
  const [params] = useSearchParams();
  const [testId, setTestId] = useState(params.get("test") || "");
  const [universityId, setUniversityId] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [universities] = useLoad(() => (staff ? portal.get("/universities") : Promise.resolve(null)), [staff]);
  const selected = testId || tests?.assessments[0]?.id || "";
  const [reviewing, setReviewing] = useState(null);
  const [data, error, reload] = useLoad(
    () => (selected ? portal.get(`/assessments/${selected}/results${query({ university_id: universityId })}`) : Promise.resolve(null)),
    [selected, universityId]
  );

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (data?.results || []).filter(
      (r) => (!status || statusOf(r) === status) && (!q || [r.full_name, r.email, r.department, r.batch].some((v) => (v || "").toLowerCase().includes(q)))
    );
  }, [data, status, search]);

  if (testsError) return <ErrorText>{testsError}</ErrorText>;
  if (!tests) return <Loading />;
  if (!tests.assessments.length) return <Card className="p-6 text-sm text-muted">No tests yet.</Card>;

  const all = data?.results || [];
  const submitted = all.filter((r) => r.status === "submitted");
  const flagged = all.filter((r) => r.malpractice).length;
  const average = submitted.length ? (submitted.reduce((s, r) => s + r.score, 0) / submitted.length).toFixed(1) : null;
  const totalMarks = data?.assessment.total_marks;

  const exportCsv = () => {
    const header = ["Name", "Email", "University", "Department", "Batch", "Status", "Score", "Out of", "Correct", "Answered", "Submitted", "Auto-submitted", "Tab switches", "Warnings", "Malpractice reason"];
    downloadCsv(`test-results-${new Date().toISOString().slice(0, 10)}.csv`, [
      header,
      ...rows.map((r) => [
        r.full_name, r.email, r.university_name, r.department, r.batch, STATUS[statusOf(r)][1],
        r.score ?? "", r.status === "submitted" ? totalMarks : "", r.correct ?? "", r.answered ?? "",
        r.submitted_at ? new Date(r.submitted_at * 1000).toLocaleString() : "", r.auto_submitted ? "yes" : "", r.tab_switches,
        r.warnings, r.malpractice ? r.malpractice_reason : "",
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
    {
      key: "status",
      label: "Status",
      render: (r) => (
        <div>
          <Badge tone={STATUS[statusOf(r)][0]}>{STATUS[statusOf(r)][1]}</Badge>
          {r.malpractice && <p className="mt-1 max-w-[220px] whitespace-normal text-xs text-red-300">{r.malpractice_reason}</p>}
          {r.malpractice_cleared && !r.malpractice && <p className="mt-1 text-xs text-muted">Flag cleared after review</p>}
        </div>
      ),
    },
    {
      key: "warnings",
      label: "Proctoring",
      render: (r) =>
        r.attempt_id && (r.warnings || r.malpractice || r.malpractice_cleared) ? (
          <div className="flex items-center gap-2">
            <Badge tone={r.malpractice ? "red" : "amber"}>
              {r.warnings} warning{r.warnings === 1 ? "" : "s"}
            </Badge>
            <Button variant="secondary" onClick={() => setReviewing(r)}>
              Evidence
            </Button>
          </div>
        ) : (
          <span className="text-slate-600">–</span>
        ),
    },
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
          <option value="malpractice">Malpractice</option>
          <option value="in_progress">In progress</option>
          <option value="not_started">Not started</option>
        </select>
        <input className="input" placeholder="Search name, email, department…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search" />
      </div>
      <div className="mb-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Students assigned" value={data ? all.length : null} />
        <Stat label="Submitted" value={data ? submitted.length : null} hint={all.length ? `${Math.round((100 * submitted.length) / all.length)}% of students` : undefined} />
        <Stat label="Average score" value={average ?? "–"} hint={average ? `out of ${totalMarks}` : undefined} />
        <Stat label="Malpractice" value={data ? flagged : null} hint="Auto-submitted by proctoring" />
      </div>
      <ErrorText>{error}</ErrorText>
      <Card>{data ? <Table columns={columns} rows={rows} empty={all.length ? "No students match these filters." : "No students are assigned yet."} /> : !error && <Loading />}</Card>
      {reviewing && (
        <EvidenceModal
          row={reviewing}
          canClear={staff}
          onClose={() => setReviewing(null)}
          onCleared={() => {
            setReviewing(null);
            reload();
          }}
        />
      )}
    </>
  );
}

function EvidenceModal({ row, canClear, onClose, onCleared }) {
  const [data, error] = useLoad(() => portal.get(`/attempts/${row.attempt_id}/evidence`), [row.attempt_id]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const time = (t) => new Date(t * 1000).toLocaleTimeString();

  const clear = async () => {
    setBusy(true);
    setProblem("");
    try {
      await portal.post(`/attempts/${row.attempt_id}/clear-malpractice`, { note });
      onCleared();
    } catch (e) {
      setProblem(e.message);
      setBusy(false);
    }
  };

  return (
    <Modal title={`Proctoring: ${row.full_name || row.email}`} onClose={onClose}>
      <ErrorText>{error}</ErrorText>
      {!data && !error && <Loading />}
      {data && (
        <div className="space-y-4 text-sm">
          {data.malpractice && <ErrorText>Marked as malpractice: {data.malpractice_reason}</ErrorText>}
          {data.malpractice_cleared && (
            <p className="text-muted">
              Flag ({data.malpractice_cleared.reason}) cleared by {data.malpractice_cleared.by}
              {data.malpractice_cleared.note ? `: "${data.malpractice_cleared.note}"` : ""}
            </p>
          )}
          <p className="text-muted">
            {data.warnings} warning{data.warnings === 1 ? "" : "s"} · left the test {data.tab_switches} time{data.tab_switches === 1 ? "" : "s"}
          </p>
          {data.snapshots.length > 0 && (
            <div className="grid grid-cols-2 gap-2">
              {data.snapshots.map((s, i) => (
                <figure key={i} className="overflow-hidden rounded-lg border border-border">
                  <img src={s.image} alt={EVENT_LABEL[s.type] || s.type} className="w-full" />
                  <figcaption className="px-2 py-1 text-xs text-muted">
                    {EVENT_LABEL[s.type] || s.type} · {time(s.at)}
                  </figcaption>
                </figure>
              ))}
            </div>
          )}
          {data.events.length > 0 && (
            <ul className="max-h-48 space-y-1 overflow-y-auto rounded-lg border border-border p-3 text-xs">
              {data.events.map((e, i) => (
                <li key={i} className="flex justify-between gap-3">
                  <span>{EVENT_LABEL[e.type] || e.type}</span>
                  <span className="text-muted">{time(e.at)}</span>
                </li>
              ))}
            </ul>
          )}
          {canClear && data.malpractice && (
            <div className="space-y-2 border-t border-border pt-4">
              <Field label="Clear the malpractice flag" hint="Use this if the evidence shows the detection was wrong. The score then counts normally.">
                <input className="input" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Reason, e.g. it was a calculator, not a phone" />
              </Field>
              <ErrorText>{problem}</ErrorText>
              <Button variant="danger" loading={busy} onClick={clear}>
                Clear flag
              </Button>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
