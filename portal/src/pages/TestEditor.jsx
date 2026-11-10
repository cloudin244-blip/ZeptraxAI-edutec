import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { portal } from "../api.js";
import { Badge, Button, Card, ErrorText, Field, Loading, Modal, Notice, PageHeader, useLoad } from "../components/ui.jsx";

export default function TestEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [tests, testsError, reloadTests] = useLoad(() => portal.get("/assessments"), []);
  const [key, keyError, reloadKey] = useLoad(() => portal.get(`/assessments/${id}/key`), [id]);
  const [universities] = useLoad(() => portal.get("/universities"), []);
  const [editing, setEditing] = useState(null); // {} = new question
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const test = tests?.assessments.find((t) => t.id === id);
  if (testsError || keyError) return <ErrorText>{testsError || keyError}</ErrorText>;
  if (!tests || !key) return <Loading />;
  if (!test) return <ErrorText>Test not found.</ErrorText>;
  const locked = test.attempts > 0;
  const questions = key.questions;

  const run = async (label, action) => {
    setBusy(label);
    setError("");
    try {
      await action();
      reloadTests();
      reloadKey();
    } catch (e) {
      setError(e.message);
    }
    setBusy("");
  };
  const move = (i, d) => {
    const ids = questions.map((q) => q.id);
    [ids[i], ids[i + d]] = [ids[i + d], ids[i]];
    run(`move-${i}`, () => portal.post(`/assessments/${id}/questions/reorder`, { ids }));
  };

  return (
    <>
      <PageHeader
        title={test.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={test.status === "published" ? "green" : "neutral"}>{test.status === "published" ? "Published" : "Draft"}</Badge>
            {questions.length} questions · {test.total_marks} marks · {test.duration_minutes} minutes
          </span>
        }
        action={
          <div className="flex flex-wrap gap-2">
            <Link to="/manage-tests">
              <Button variant="secondary">All tests</Button>
            </Link>
            <Button
              loading={busy === "status"}
              variant={test.status === "published" ? "secondary" : "primary"}
              onClick={() => run("status", () => portal.put(`/assessments/${id}`, { status: test.status === "published" ? "draft" : "published" }))}
            >
              {test.status === "published" ? "Unpublish" : "Publish to students"}
            </Button>
          </div>
        }
      />
      <ErrorText>{error}</ErrorText>
      {locked && (
        <div className="mb-4">
          <Notice>
            {test.attempts} {test.attempts === 1 ? "student has" : "students have"} started this test, so its questions and marking are locked. You can still change the title,
            description, duration and who it's for.
          </Notice>
        </div>
      )}
      <Settings test={test} universities={universities?.universities || []} locked={locked} onSaved={reloadTests} />

      <div className="mb-3 mt-8 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Questions</h2>
        {!locked && <Button onClick={() => setEditing({})}>Add question</Button>}
      </div>
      {!questions.length && <Card className="p-6 text-sm text-muted">No questions yet. Add at least one before publishing.</Card>}
      <div className="space-y-3">
        {questions.map((q, i) => (
          <Card key={q.id} className="p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
              <div className="flex shrink-0 items-center gap-1">
                <button className="rounded px-2 py-1 text-muted hover:bg-white/5 disabled:opacity-30" disabled={locked || i === 0 || !!busy} onClick={() => move(i, -1)} aria-label={`Move question ${i + 1} up`}>
                  ↑
                </button>
                <button className="rounded px-2 py-1 text-muted hover:bg-white/5 disabled:opacity-30" disabled={locked || i === questions.length - 1 || !!busy} onClick={() => move(i, 1)} aria-label={`Move question ${i + 1} down`}>
                  ↓
                </button>
                <span className="w-6 text-right text-sm font-semibold">{i + 1}</span>
              </div>
              <div className="min-w-0 flex-1">
                {q.section && <Badge tone="blue">{q.section}</Badge>}
                <p className="mt-1 text-sm">{q.text}</p>
                {q.code && <pre className="mt-2 overflow-x-auto rounded-md border border-border bg-background p-2 font-mono text-xs">{q.code}</pre>}
                <ul className="mt-2 space-y-1 text-sm">
                  {q.options.map((o, j) => (
                    <li key={j} className={j === q.answer ? "text-green-300" : "text-slate-400"}>
                      {String.fromCharCode(97 + j)}) {o} {j === q.answer && "✓"}
                    </li>
                  ))}
                </ul>
              </div>
              {!locked && (
                <div className="flex shrink-0 gap-2">
                  <Button variant="secondary" onClick={() => setEditing(q)}>
                    Edit
                  </Button>
                  <Button
                    variant="danger"
                    loading={busy === `del-${q.id}`}
                    onClick={() => window.confirm(`Delete question ${i + 1}?`) && run(`del-${q.id}`, () => portal.del(`/assessments/${id}/questions/${q.id}`))}
                  >
                    Delete
                  </Button>
                </div>
              )}
            </div>
          </Card>
        ))}
      </div>
      {!locked && (
        <div className="mt-8 border-t border-border pt-6">
          <Button
            variant="danger"
            loading={busy === "delete"}
            onClick={() =>
              window.confirm(`Delete the test "${test.title}" and all its questions?`) &&
              run("delete", async () => {
                await portal.del(`/assessments/${id}`);
                navigate("/manage-tests");
              })
            }
          >
            Delete test
          </Button>
        </div>
      )}
      {editing && (
        <QuestionForm
          testId={id}
          question={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            reloadKey();
            reloadTests();
          }}
        />
      )}
    </>
  );
}

function Settings({ test, universities, locked, onSaved }) {
  const [form, setForm] = useState(test);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setForm(test), [test]);
  const set = (k, v) => {
    setSaved(false);
    setForm({ ...form, [k]: v });
  };
  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    const body = {
      title: form.title, description: form.description, duration_minutes: form.duration_minutes, required: form.required,
      show_score_to_students: form.show_score_to_students, audience: form.audience, university_ids: form.university_ids,
      ...(locked ? {} : { marks_per_question: form.marks_per_question, negative_marks: form.negative_marks }),
    };
    try {
      await portal.put(`/assessments/${test.id}`, body);
      setSaved(true);
      onSaved();
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };
  const toggleUni = (uid) => set("university_ids", form.university_ids.includes(uid) ? form.university_ids.filter((u) => u !== uid) : [...form.university_ids, uid]);

  return (
    <Card className="p-5">
      <form onSubmit={save} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Title">
            <input className="input" required maxLength={150} value={form.title} onChange={(e) => set("title", e.target.value)} />
          </Field>
          <Field label="Duration (minutes)">
            <input className="input" type="number" min={1} max={600} required value={form.duration_minutes} onChange={(e) => set("duration_minutes", e.target.value)} />
          </Field>
          <Field label="Marks per question">
            <input className="input" type="number" min={0.5} max={100} step={0.5} disabled={locked} value={form.marks_per_question} onChange={(e) => set("marks_per_question", e.target.value)} />
          </Field>
          <Field label="Marks taken off per wrong answer" hint="0 = no negative marking">
            <input className="input" type="number" min={0} max={100} step={0.25} disabled={locked} value={form.negative_marks} onChange={(e) => set("negative_marks", e.target.value)} />
          </Field>
        </div>
        <Field label="Description (shown to students before they start)">
          <textarea className="input" rows={2} maxLength={1000} value={form.description} onChange={(e) => set("description", e.target.value)} />
        </Field>
        <div className="flex flex-wrap gap-6 text-sm">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={form.required} onChange={(e) => set("required", e.target.checked)} /> Required (highlighted on students' dashboards)
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={form.show_score_to_students} onChange={(e) => set("show_score_to_students", e.target.checked)} /> Show students their score
          </label>
        </div>
        <Field label="Who takes this test">
          <select className="input max-w-xs" value={form.audience} onChange={(e) => set("audience", e.target.value)}>
            <option value="all_students">All students</option>
            <option value="universities">Students of chosen universities</option>
          </select>
        </Field>
        {form.audience === "universities" && (
          <div className="grid gap-2 sm:grid-cols-3">
            {universities.map((u) => (
              <label key={u.id} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.university_ids.includes(u.id)} onChange={() => toggleUni(u.id)} /> {u.name}
              </label>
            ))}
            {!universities.length && <p className="text-sm text-muted">No universities yet.</p>}
          </div>
        )}
        <ErrorText>{error}</ErrorText>
        {saved && <Notice>Settings saved.</Notice>}
        <div className="flex justify-end">
          <Button type="submit" loading={busy}>
            Save settings
          </Button>
        </div>
      </form>
    </Card>
  );
}

function QuestionForm({ testId, question, onClose, onSaved }) {
  const isNew = !question.id;
  const [form, setForm] = useState({
    section: question.section || "",
    text: question.text || "",
    code: question.code || "",
    options: question.options ? [...question.options] : ["", "", "", ""],
    answer: question.answer ?? null,
    review: question.review || "",
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const setOption = (i, v) => setForm({ ...form, options: form.options.map((o, j) => (j === i ? v : o)) });
  const removeOption = (i) =>
    setForm({ ...form, options: form.options.filter((_, j) => j !== i), answer: form.answer === i ? null : form.answer > i ? form.answer - 1 : form.answer });

  const submit = async (e) => {
    e.preventDefault();
    if (form.answer === null) return setError("Mark which option is correct");
    setBusy(true);
    setError("");
    try {
      if (isNew) await portal.post(`/assessments/${testId}/questions`, form);
      else await portal.put(`/assessments/${testId}/questions/${question.id}`, form);
      onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <Modal title={isNew ? "Add question" : "Edit question"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Section" hint="e.g. Aptitude, Coding, DSA (optional)">
          <input className="input" maxLength={60} value={form.section} onChange={(e) => setForm({ ...form, section: e.target.value })} />
        </Field>
        <Field label="Question">
          <textarea className="input" rows={3} required maxLength={2000} value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} />
        </Field>
        <Field label="Code snippet (optional)" hint="Shown in a code box under the question">
          <textarea className="input font-mono text-xs" rows={3} maxLength={4000} value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
        </Field>
        <div>
          <p className="label">Options (select the correct one)</p>
          <div className="space-y-2">
            {form.options.map((o, i) => (
              <div key={i} className="flex items-center gap-2">
                <input type="radio" name="correct" checked={form.answer === i} onChange={() => setForm({ ...form, answer: i })} aria-label={`Option ${i + 1} is correct`} />
                <input className="input" required maxLength={500} value={o} onChange={(e) => setOption(i, e.target.value)} placeholder={`Option ${String.fromCharCode(65 + i)}`} />
                {form.options.length > 2 && (
                  <button type="button" className="text-muted hover:text-red-300" onClick={() => removeOption(i)} aria-label={`Remove option ${i + 1}`}>
                    ✕
                  </button>
                )}
              </div>
            ))}
          </div>
          {form.options.length < 6 && (
            <button type="button" className="mt-2 text-sm text-primary hover:underline" onClick={() => setForm({ ...form, options: [...form.options, ""] })}>
              + Add option
            </button>
          )}
        </div>
        <Field label="Note for reviewers (optional, never shown to students)">
          <input className="input" maxLength={1000} value={form.review} onChange={(e) => setForm({ ...form, review: e.target.value })} />
        </Field>
        <ErrorText>{error}</ErrorText>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={busy}>
            {isNew ? "Add question" : "Save"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
