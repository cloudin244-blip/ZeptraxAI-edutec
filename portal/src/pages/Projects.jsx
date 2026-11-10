import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { portal } from "../api.js";
import { useAuth } from "../auth.jsx";
import { Badge, Button, Card, ErrorText, Field, formatDate, Loading, Modal, Notice, PageHeader, Table, useLoad } from "../components/ui.jsx";
import { usePrograms } from "../components/ProgramSelect.jsx";
import { downloadCsv } from "./Invitations.jsx";

const AUDIENCE = { all_students: "All students", programs: "Programs", universities: "Universities" };

export function audienceText(p) {
  return p.audience === "all_students" ? "All students" : `${AUDIENCE[p.audience]}: ${p.target_names.join(", ")}`;
}

export const toDateInput = (seconds) => (seconds ? new Date(seconds * 1000 - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10) : "");
export const fromDateInput = (value) => (value ? new Date(`${value}T23:59:59`).getTime() / 1000 : null);

// ---------------------------------------------------------------- list (staff and coordinators)

export default function Projects() {
  const { user } = useAuth();
  const superAdmin = user.role === "super_admin";
  const [data, error] = useLoad(() => portal.get("/projects"), []);

  const columns = [
    {
      key: "title",
      label: "Project",
      render: (p) => (
        <Link to={`/projects/${p.id}`} className="block">
          <p className="font-medium text-slate-100 hover:text-primary">{p.title}</p>
          <p className="text-xs text-muted">{audienceText(p)}</p>
        </Link>
      ),
    },
    { key: "status", label: "Status", render: (p) => <Badge tone={p.status === "published" ? "green" : "neutral"}>{p.status === "published" ? "Published" : "Draft"}</Badge> },
    { key: "due_date", label: "Due", render: (p) => (p.due_date ? formatDate(p.due_date) : "No due date") },
    { key: "submitted", label: "Submitted", render: (p) => `${p.submitted} / ${p.assigned}` },
    { key: "evaluated", label: "Marked", render: (p) => p.evaluated },
    {
      key: "open",
      label: "",
      render: (p) => (
        <Link to={`/projects/${p.id}`}>
          <Button variant="secondary">Open</Button>
        </Link>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Projects"
        description="Final-year projects: students submit their work here and Zeptrax marks it against the rubric."
        action={
          superAdmin && (
            <Link to="/projects/new">
              <Button>New project</Button>
            </Link>
          )
        }
      />
      <ErrorText>{error}</ErrorText>
      <Card>{data ? <Table columns={columns} rows={data.projects} empty="No projects yet." /> : !error && <Loading />}</Card>
    </>
  );
}

// ---------------------------------------------------------------- create / edit (super admin)

export function ProjectForm() {
  const { id } = useParams();
  const navigate = useNavigate();
  const isNew = !id;
  const programs = usePrograms();
  const [universities] = useLoad(() => portal.get("/universities"), []);
  const [form, setForm] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (isNew) {
      setForm({ title: "", category: "", description: "", requirements: "", due: "", audience: "all_students", targets: [], rubric: null, status: "draft" });
    } else {
      portal
        .get(`/projects/${id}`)
        .then(({ project: p }) => setForm({ ...p, due: toDateInput(p.due_date) }))
        .catch((e) => setError(e.message));
    }
  }, [id, isNew]);

  if (!form) return error ? <ErrorText>{error}</ErrorText> : <Loading />;
  const rubric = form.rubric || DEFAULT_RUBRIC;
  const set = (k, v) => setForm({ ...form, [k]: v });
  const setRubric = (i, k, v) => set("rubric", rubric.map((r, j) => (j === i ? { ...r, [k]: k === "max_marks" ? v.replace(/\D/g, "") : v } : r)));
  const toggle = (t) => set("targets", form.targets.includes(t) ? form.targets.filter((x) => x !== t) : [...form.targets, t]);
  const total = rubric.reduce((s, r) => s + (Number(r.max_marks) || 0), 0);

  const save = async (status) => {
    setBusy(true);
    setError("");
    const body = {
      title: form.title, category: form.category, description: form.description, requirements: form.requirements,
      due_date: fromDateInput(form.due), audience: form.audience, targets: form.targets,
      rubric: rubric.map((r) => ({ criterion: r.criterion, max_marks: Number(r.max_marks) })), status,
    };
    try {
      const { project } = isNew ? await portal.post("/projects", body) : await portal.put(`/projects/${id}`, body);
      navigate(`/projects/${project.id}`);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title={isNew ? "New project" : `Edit ${form.title}`} />
      <Card className="max-w-3xl space-y-5 p-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Title">
            <input className="input" required maxLength={150} value={form.title} onChange={(e) => set("title", e.target.value)} placeholder="RAG-Based AI Assistant" />
          </Field>
          <Field label="Category" hint="e.g. Generative AI, Cybersecurity">
            <input className="input" maxLength={80} value={form.category} onChange={(e) => set("category", e.target.value)} />
          </Field>
        </div>
        <Field label="Brief">
          <textarea className="input" rows={4} maxLength={4000} value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="What students build and why" />
        </Field>
        <Field label="What to submit / requirements">
          <textarea className="input" rows={4} maxLength={4000} value={form.requirements} onChange={(e) => set("requirements", e.target.value)} placeholder="GitHub repository, architecture diagram, demo video…" />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Due date" hint="Submissions close at the end of this day. Leave empty for no deadline.">
            <input className="input" type="date" value={form.due} onChange={(e) => set("due", e.target.value)} />
          </Field>
          <Field label="Who does this project">
            <select className="input" value={form.audience} onChange={(e) => setForm({ ...form, audience: e.target.value, targets: [] })}>
              <option value="all_students">All students</option>
              <option value="programs">Students of chosen programs</option>
              <option value="universities">Students of chosen universities</option>
            </select>
          </Field>
        </div>
        {form.audience === "programs" && (
          <div className="grid max-h-60 gap-2 overflow-y-auto rounded-lg border border-border p-3 sm:grid-cols-2">
            {(programs || []).map((p) => (
              <label key={p.slug} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.targets.includes(p.slug)} onChange={() => toggle(p.slug)} /> {p.title}
              </label>
            ))}
          </div>
        )}
        {form.audience === "universities" && (
          <div className="grid gap-2 rounded-lg border border-border p-3 sm:grid-cols-3">
            {(universities?.universities || []).map((u) => (
              <label key={u.id} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.targets.includes(u.id)} onChange={() => toggle(u.id)} /> {u.name}
              </label>
            ))}
          </div>
        )}
        <div>
          <p className="label">
            Marking rubric <span className="font-normal text-muted">(total {total} marks)</span>
          </p>
          <div className="space-y-2">
            {rubric.map((r, i) => (
              <div key={i} className="flex items-center gap-2">
                <input className="input" maxLength={80} value={r.criterion} onChange={(e) => setRubric(i, "criterion", e.target.value)} aria-label={`Criterion ${i + 1}`} />
                <input className="input w-24" inputMode="numeric" value={r.max_marks} onChange={(e) => setRubric(i, "max_marks", e.target.value)} aria-label={`Marks for criterion ${i + 1}`} />
                {rubric.length > 1 && (
                  <button type="button" className="text-muted hover:text-red-300" onClick={() => set("rubric", rubric.filter((_, j) => j !== i))} aria-label={`Remove criterion ${i + 1}`}>
                    ✕
                  </button>
                )}
              </div>
            ))}
          </div>
          <button type="button" className="mt-2 text-sm text-primary hover:underline" onClick={() => set("rubric", [...rubric, { criterion: "", max_marks: 10 }])}>
            + Add criterion
          </button>
        </div>
        <ErrorText>{error}</ErrorText>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" onClick={() => navigate(isNew ? "/projects" : `/projects/${id}`)}>
            Cancel
          </Button>
          <Button variant="secondary" loading={busy} onClick={() => save("draft")}>
            Save as draft
          </Button>
          <Button loading={busy} onClick={() => save("published")}>
            {form.status === "published" ? "Save" : "Save and publish"}
          </Button>
        </div>
      </Card>
    </>
  );
}

const DEFAULT_RUBRIC = [
  { criterion: "Problem understanding", max_marks: 10 },
  { criterion: "Technical implementation", max_marks: 25 },
  { criterion: "Code quality", max_marks: 15 },
  { criterion: "Innovation", max_marks: 10 },
  { criterion: "Architecture & design", max_marks: 10 },
  { criterion: "Working demonstration", max_marks: 15 },
  { criterion: "Documentation", max_marks: 5 },
  { criterion: "Presentation & viva", max_marks: 10 },
];

// ---------------------------------------------------------------- detail + submissions (staff and coordinators)

export function ProjectDetail() {
  const { id } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const superAdmin = user.role === "super_admin";
  const canMark = user.portal_role === "staff";
  const [data, error, reload] = useLoad(() => portal.get(`/projects/${id}/submissions`), [id]);
  const [marking, setMarking] = useState(null);
  const [busy, setBusy] = useState("");
  const [actionError, setActionError] = useState("");

  if (error) return <ErrorText>{error}</ErrorText>;
  if (!data) return <Loading />;
  const p = data.project;
  const submitted = data.rows.filter((r) => r.submission);
  const marked = submitted.filter((r) => r.submission.status === "evaluated");

  const run = async (label, action) => {
    setBusy(label);
    setActionError("");
    try {
      await action();
      reload();
    } catch (e) {
      setActionError(e.message);
    }
    setBusy("");
  };

  const exportCsv = () =>
    downloadCsv(`project-${p.title.replace(/[^\w-]+/g, "_")}.csv`, [
      ["Name", "Email", "University", "Program", "Department", "Batch", "Status", "Repository", "Demo", "Documents", "Video", "Submitted", "Marks", "Out of", "Feedback"],
      ...data.rows.map(({ student: s, submission: sub }) => [
        s.full_name, s.email, s.university_name, s.program_title, s.department, s.batch,
        sub ? (sub.status === "evaluated" ? "Marked" : "Submitted") : "Not submitted",
        sub?.repo_url, sub?.demo_url, sub?.docs_url, sub?.video_url, sub ? new Date(sub.submitted_at * 1000).toLocaleString() : "",
        sub?.evaluation?.total ?? "", sub?.evaluation ? p.total_marks : "", sub?.evaluation?.feedback ?? "",
      ]),
    ]);

  const columns = [
    {
      key: "student",
      label: "Student",
      render: ({ student: s }) => (
        <div>
          <p className="font-medium">{s.full_name || "–"}</p>
          <p className="text-xs text-muted">{s.email}</p>
        </div>
      ),
    },
    { key: "university", label: "University", render: ({ student: s }) => s.university_name || "–" },
    { key: "program", label: "Program", render: ({ student: s }) => s.program_title || "–" },
    {
      key: "status",
      label: "Status",
      render: ({ submission: sub }) =>
        !sub ? <Badge>Not submitted</Badge> : sub.status === "evaluated" ? <Badge tone="green">Marked {sub.evaluation.total}/{p.total_marks}</Badge> : <Badge tone="blue">Submitted</Badge>,
    },
    {
      key: "links",
      label: "Work",
      render: ({ submission: sub }) =>
        sub ? (
          <div className="flex flex-wrap gap-2 text-xs">
            {[["Code", sub.repo_url], ["Demo", sub.demo_url], ["Docs", sub.docs_url], ["Video", sub.video_url]].map(([label, url]) =>
              url ? (
                <a key={label} href={url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                  {label}
                </a>
              ) : null
            )}
          </div>
        ) : (
          "–"
        ),
    },
    { key: "submitted_at", label: "Submitted", render: ({ submission: sub }) => (sub ? formatDate(sub.updated_at || sub.submitted_at) : "–") },
    {
      key: "actions",
      label: "",
      render: (row) =>
        canMark && row.submission ? (
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setMarking(row)}>
              {row.submission.status === "evaluated" ? "View marks" : "Mark"}
            </Button>
            {row.submission.status === "evaluated" && (
              <Button variant="secondary" loading={busy === row.submission.id} onClick={() => run(row.submission.id, () => portal.post(`/submissions/${row.submission.id}/reopen`))}>
                Reopen
              </Button>
            )}
          </div>
        ) : null,
    },
  ];

  return (
    <>
      <PageHeader
        title={p.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={p.status === "published" ? "green" : "neutral"}>{p.status === "published" ? "Published" : "Draft"}</Badge>
            {audienceText(p)} · {p.due_date ? `due ${formatDate(p.due_date)}` : "no due date"} · {p.total_marks} marks
          </span>
        }
        action={
          <div className="flex flex-wrap gap-2">
            <Link to="/projects">
              <Button variant="secondary">All projects</Button>
            </Link>
            <Button variant="secondary" onClick={exportCsv} disabled={!data.rows.length}>
              Download CSV
            </Button>
            {superAdmin && (
              <>
                <Link to={`/projects/${id}/edit`}>
                  <Button variant="secondary">Edit</Button>
                </Link>
                <Button loading={busy === "status"} onClick={() => run("status", () => portal.put(`/projects/${id}`, { status: p.status === "published" ? "draft" : "published" }))}>
                  {p.status === "published" ? "Unpublish" : "Publish to students"}
                </Button>
              </>
            )}
          </div>
        }
      />
      <ErrorText>{actionError}</ErrorText>
      <div className="mb-4 grid gap-4 sm:grid-cols-3">
        <Card className="p-4">
          <p className="text-2xl font-bold">{data.rows.length}</p>
          <p className="text-xs text-muted">Students assigned</p>
        </Card>
        <Card className="p-4">
          <p className="text-2xl font-bold">{submitted.length}</p>
          <p className="text-xs text-muted">Submitted</p>
        </Card>
        <Card className="p-4">
          <p className="text-2xl font-bold">{marked.length}</p>
          <p className="text-xs text-muted">Marked</p>
        </Card>
      </div>
      <details className="mb-4 rounded-xl border border-border bg-card p-4 text-sm">
        <summary className="cursor-pointer font-medium">Project brief and rubric</summary>
        <ProjectBrief project={p} />
      </details>
      <Card>
        <Table columns={columns} rows={data.rows.map((r) => ({ ...r, id: r.student.id }))} empty="No students are assigned to this project yet." />
      </Card>
      {superAdmin && !submitted.length && (
        <div className="mt-6">
          <Button
            variant="danger"
            onClick={() =>
              window.confirm(`Delete the project "${p.title}"?`) &&
              run("delete", async () => {
                await portal.del(`/projects/${id}`);
                navigate("/projects");
              })
            }
          >
            Delete project
          </Button>
        </div>
      )}
      {marking && (
        <MarkForm
          project={p}
          row={marking}
          onClose={() => setMarking(null)}
          onSaved={() => {
            setMarking(null);
            reload();
          }}
        />
      )}
    </>
  );
}

export function ProjectBrief({ project: p }) {
  return (
    <div className="mt-3 space-y-4">
      {p.description && <p className="whitespace-pre-line text-slate-300">{p.description}</p>}
      {p.requirements && (
        <div>
          <p className="font-medium">What to submit</p>
          <p className="mt-1 whitespace-pre-line text-slate-300">{p.requirements}</p>
        </div>
      )}
      <div>
        <p className="font-medium">Marking rubric ({p.total_marks} marks)</p>
        <ul className="mt-1 grid gap-1 text-slate-300 sm:grid-cols-2">
          {p.rubric.map((r) => (
            <li key={r.criterion} className="flex justify-between gap-4 rounded-md bg-white/[0.03] px-3 py-1.5">
              <span>{r.criterion}</span>
              <span className="text-muted">{r.max_marks}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function MarkForm({ project, row, onClose, onSaved }) {
  const sub = row.submission;
  const [scores, setScores] = useState(() => Object.fromEntries(project.rubric.map((r) => [r.criterion, sub.evaluation?.scores?.[r.criterion] ?? ""])));
  const [feedback, setFeedback] = useState(sub.evaluation?.feedback || "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const total = Object.values(scores).reduce((s, v) => s + (Number(v) || 0), 0);
  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await portal.put(`/submissions/${sub.id}/evaluation`, { scores: Object.fromEntries(Object.entries(scores).map(([k, v]) => [k, Number(v)])), feedback });
      onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <Modal title={`Mark: ${row.student.full_name}`} onClose={onClose}>
      <form onSubmit={save} className="space-y-4 text-sm">
        <div className="flex flex-wrap gap-3">
          {[["Code repository", sub.repo_url], ["Demo", sub.demo_url], ["Documents", sub.docs_url], ["Video", sub.video_url]].map(([label, url]) =>
            url ? (
              <a key={label} href={url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                {label} ↗
              </a>
            ) : null
          )}
        </div>
        {sub.notes && <p className="whitespace-pre-line rounded-lg bg-white/[0.03] p-3 text-slate-300">{sub.notes}</p>}
        <div className="space-y-2">
          {project.rubric.map((r) => (
            <label key={r.criterion} className="flex items-center justify-between gap-3">
              <span>{r.criterion}</span>
              <span className="flex items-center gap-2">
                <input
                  className="input w-20"
                  type="number"
                  min={0}
                  max={r.max_marks}
                  step={0.5}
                  required
                  value={scores[r.criterion]}
                  onChange={(e) => setScores({ ...scores, [r.criterion]: e.target.value })}
                  aria-label={`Marks for ${r.criterion}`}
                />
                <span className="w-10 text-muted">/ {r.max_marks}</span>
              </span>
            </label>
          ))}
        </div>
        <p className="text-right font-semibold">
          Total: {total} / {project.total_marks}
        </p>
        <Field label="Feedback for the student">
          <textarea className="input" rows={3} maxLength={3000} value={feedback} onChange={(e) => setFeedback(e.target.value)} />
        </Field>
        {sub.status === "evaluated" && <Notice>Saving replaces the existing marks.</Notice>}
        <ErrorText>{error}</ErrorText>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={busy}>
            Save marks
          </Button>
        </div>
      </form>
    </Modal>
  );
}
