import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { portal } from "../api.js";
import { Badge, Button, Card, ErrorText, Field, formatDate, Loading, Notice, PageHeader, useLoad } from "../components/ui.jsx";
import { ProjectBrief } from "./Projects.jsx";

export function projectStatus(p) {
  const sub = p.submission;
  if (sub?.status === "evaluated") return <Badge tone="green">Marked {sub.evaluation.total}/{p.total_marks}</Badge>;
  if (sub) return <Badge tone="blue">Submitted</Badge>;
  if (p.overdue) return <Badge tone="red">Missed</Badge>;
  return <Badge tone="amber">To do</Badge>;
}

export default function MyProjects() {
  const [data, error] = useLoad(() => portal.get("/projects"), []);
  if (error) return <ErrorText>{error}</ErrorText>;
  if (!data) return <Loading />;
  return (
    <>
      <PageHeader title="My projects" description="Projects assigned to you. Submit your work before the due date; ZeptraAI marks it against the rubric." />
      {!data.projects.length && <Card className="p-6 text-sm text-muted">No projects are assigned to you yet.</Card>}
      <div className="space-y-3">
        {data.projects.map((p) => (
          <Link key={p.id} to={`/my-projects/${p.id}`} className="block">
            <Card className="p-5 transition-colors hover:border-primary/50">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="font-semibold">{p.title}</p>
                  <p className="text-sm text-muted">
                    {p.category && `${p.category} · `}
                    {p.due_date ? `Due ${formatDate(p.due_date)}` : "No due date"} · {p.total_marks} marks
                  </p>
                </div>
                {projectStatus(p)}
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </>
  );
}

export function MyProject() {
  const { id } = useParams();
  const [data, error, reload] = useLoad(() => portal.get(`/projects/${id}`), [id]);
  if (error) return <ErrorText>{error}</ErrorText>;
  if (!data) return <Loading />;
  const p = data.project;
  const sub = p.submission;
  const locked = sub?.status === "evaluated" || p.overdue;

  return (
    <>
      <PageHeader
        title={p.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            {projectStatus(p)} {p.due_date ? `Due ${formatDate(p.due_date)}` : "No due date"} · {p.total_marks} marks
          </span>
        }
        action={
          <Link to="/my-projects">
            <Button variant="secondary">All my projects</Button>
          </Link>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
        <Card className="p-5 text-sm">
          <h2 className="font-semibold">The brief</h2>
          <ProjectBrief project={p} />
        </Card>
        <div className="space-y-4">
          {sub?.evaluation && <Evaluation project={p} evaluation={sub.evaluation} />}
          <Submission project={p} submission={sub} locked={locked} onSaved={reload} />
        </div>
      </div>
    </>
  );
}

function Evaluation({ project, evaluation }) {
  return (
    <Card className="border-green-500/30 p-5 text-sm">
      <p className="text-xs font-semibold uppercase tracking-wider text-green-300">Your marks</p>
      <p className="mt-2 text-3xl font-bold">
        {evaluation.total}
        <span className="text-lg text-muted"> / {project.total_marks}</span>
      </p>
      <ul className="mt-3 space-y-1">
        {project.rubric.map((r) => (
          <li key={r.criterion} className="flex justify-between gap-3 text-slate-300">
            <span>{r.criterion}</span>
            <span>
              {evaluation.scores[r.criterion]} / {r.max_marks}
            </span>
          </li>
        ))}
      </ul>
      {evaluation.feedback && (
        <div className="mt-4">
          <p className="font-medium">Feedback</p>
          <p className="mt-1 whitespace-pre-line text-slate-300">{evaluation.feedback}</p>
        </div>
      )}
    </Card>
  );
}

function Submission({ project, submission, locked, onSaved }) {
  const empty = { repo_url: "", demo_url: "", docs_url: "", video_url: "", notes: "" };
  const [form, setForm] = useState(empty);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => setForm({ ...empty, ...(submission || {}) }), [submission]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k) => (e) => {
    setSaved(false);
    setForm({ ...form, [k]: e.target.value });
  };
  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await portal.put(`/projects/${project.id}/submission`, form);
      setSaved(true);
      onSaved();
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };
  return (
    <Card className="p-5">
      <h2 className="font-semibold">{submission ? "Your submission" : "Submit your project"}</h2>
      {submission && <p className="mt-1 text-xs text-muted">Last updated {formatDate(submission.updated_at || submission.submitted_at)}</p>}
      {locked && (
        <div className="mt-3">
          <Notice>{submission?.status === "evaluated" ? "Your project has been marked, so the submission is closed." : "The due date has passed, so submissions are closed."}</Notice>
        </div>
      )}
      <form onSubmit={save} className="mt-4 space-y-3">
        <Field label="Code repository (required)">
          <input className="input" type="url" required disabled={locked} value={form.repo_url} onChange={set("repo_url")} placeholder="https://github.com/you/project" />
        </Field>
        <Field label="Live demo">
          <input className="input" type="url" disabled={locked} value={form.demo_url} onChange={set("demo_url")} placeholder="https://…" />
        </Field>
        <Field label="Documentation / report">
          <input className="input" type="url" disabled={locked} value={form.docs_url} onChange={set("docs_url")} placeholder="Google Drive or PDF link" />
        </Field>
        <Field label="Demo video">
          <input className="input" type="url" disabled={locked} value={form.video_url} onChange={set("video_url")} placeholder="YouTube or Drive link" />
        </Field>
        <Field label="Notes for the evaluator">
          <textarea className="input" rows={3} maxLength={3000} disabled={locked} value={form.notes} onChange={set("notes")} placeholder="Tech stack, how to run it, anything we should know" />
        </Field>
        <ErrorText>{error}</ErrorText>
        {saved && <Notice>Submission saved. You can update it until the due date or until it's marked.</Notice>}
        {!locked && (
          <Button type="submit" loading={busy} className="w-full">
            {submission ? "Update submission" : "Submit project"}
          </Button>
        )}
      </form>
    </Card>
  );
}
