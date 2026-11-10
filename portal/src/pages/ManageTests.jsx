import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { portal } from "../api.js";
import { useAuth } from "../auth.jsx";
import { Badge, Button, Card, ErrorText, Field, Loading, Modal, PageHeader, Table, useLoad } from "../components/ui.jsx";

export default function ManageTests() {
  const { user } = useAuth();
  const superAdmin = user.role === "super_admin";
  const [data, error] = useLoad(() => portal.get("/assessments"), []);
  const [creating, setCreating] = useState(false);

  const columns = [
    {
      key: "title",
      label: "Test",
      render: (t) => (
        <div>
          <p className="font-medium">{t.title}</p>
          <p className="text-xs text-muted">
            {t.question_count} questions · {t.duration_minutes} min · {t.total_marks} marks{t.required ? " · required" : ""}
          </p>
        </div>
      ),
    },
    { key: "status", label: "Status", render: (t) => <Badge tone={t.status === "published" ? "green" : "neutral"}>{t.status === "published" ? "Published" : "Draft"}</Badge> },
    { key: "audience", label: "For", render: (t) => (t.audience === "universities" ? `${t.university_ids.length} universit${t.university_ids.length === 1 ? "y" : "ies"}` : "All students") },
    { key: "submitted", label: "Submitted", render: (t) => `${t.submitted} / ${t.assigned}` },
    { key: "average_score", label: "Average", render: (t) => (t.average_score != null ? `${t.average_score} / ${t.total_marks}` : "–") },
    {
      key: "actions",
      label: "",
      render: (t) => (
        <div className="flex justify-end gap-2">
          <Link to={`/results?test=${t.id}`}>
            <Button variant="secondary">Results</Button>
          </Link>
          {superAdmin && (
            <Link to={`/manage-tests/${t.id}`}>
              <Button variant="secondary">Edit</Button>
            </Link>
          )}
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Tests"
        description="Create tests, write their questions and publish them to students. Results are on each test's Results page."
        action={superAdmin && <Button onClick={() => setCreating(true)}>New test</Button>}
      />
      <ErrorText>{error}</ErrorText>
      <Card>{data ? <Table columns={columns} rows={data.assessments} empty="No tests yet." /> : !error && <Loading />}</Card>
      {creating && <NewTest onClose={() => setCreating(false)} />}
    </>
  );
}

function NewTest({ onClose }) {
  const navigate = useNavigate();
  const [form, setForm] = useState({ title: "", duration_minutes: 30, marks_per_question: 1 });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { assessment } = await portal.post("/assessments", form);
      navigate(`/manage-tests/${assessment.id}`);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <Modal title="New test" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Title">
          <input className="input" required maxLength={150} value={form.title} onChange={set("title")} placeholder="Aptitude Assessment" />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Duration (minutes)">
            <input className="input" type="number" min={1} max={600} required value={form.duration_minutes} onChange={set("duration_minutes")} />
          </Field>
          <Field label="Marks per question">
            <input className="input" type="number" min={0.5} max={100} step={0.5} required value={form.marks_per_question} onChange={set("marks_per_question")} />
          </Field>
        </div>
        <p className="text-sm text-muted">The test starts as a draft. Add questions, then publish it.</p>
        <ErrorText>{error}</ErrorText>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={busy}>
            Create and add questions
          </Button>
        </div>
      </form>
    </Modal>
  );
}
