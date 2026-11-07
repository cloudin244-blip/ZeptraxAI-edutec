import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { portal } from "../api.js";
import { Badge, Button, Card, ErrorText, Loading, Modal, PageHeader, useLoad } from "../components/ui.jsx";

export function formatClock(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

export function TestFacts({ test }) {
  return (
    <p className="text-sm text-muted">
      {test.question_count} questions · {test.duration_minutes} minutes · {test.total_marks} marks ({test.marks_per_question} per question)
      {test.negative_marks ? ` · −${test.negative_marks} per wrong answer` : " · no negative marking"}
    </p>
  );
}

export default function MyTests() {
  const [data, error] = useLoad(() => portal.get("/assessments"), []);
  const [confirming, setConfirming] = useState(null);
  const navigate = useNavigate();

  if (error) return <ErrorText>{error}</ErrorText>;
  if (!data) return <Loading />;
  const clockOffset = data.server_time - Date.now() / 1000;

  return (
    <>
      <PageHeader title="My tests" description="Tests assigned to you by ZeptraAI and your university." />
      {!data.assessments.length && <Card className="p-6 text-sm text-muted">No tests are assigned to you right now.</Card>}
      <div className="space-y-4">
        {data.assessments.map((t) => (
          <TestCard key={t.id} test={t} clockOffset={clockOffset} onStart={() => setConfirming(t)} onResume={() => navigate(`/tests/${t.id}/take`)} />
        ))}
      </div>
      {confirming && <StartModal test={confirming} onClose={() => setConfirming(null)} onStart={() => navigate(`/tests/${confirming.id}/take`)} />}
    </>
  );
}

export function TestCard({ test, clockOffset = 0, onStart, onResume }) {
  const a = test.attempt;
  return (
    <Card className="p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-semibold">{test.title}</h2>
            {test.required && <Badge tone="amber">Required</Badge>}
            {a.status === "submitted" && <Badge tone="green">Submitted</Badge>}
            {a.status === "in_progress" && <Badge tone="blue">In progress</Badge>}
          </div>
          <div className="mt-1">
            <TestFacts test={test} />
          </div>
          {test.description && <p className="mt-2 text-sm text-slate-300">{test.description}</p>}
        </div>
        <div className="shrink-0 sm:text-right">
          {a.status === "not_started" && <Button onClick={onStart}>Start test</Button>}
          {a.status === "in_progress" && (
            <>
              <Button onClick={onResume}>Resume test</Button>
              <p className="mt-1 text-xs text-muted">{formatClock(a.deadline - (Date.now() / 1000 + clockOffset))} left</p>
            </>
          )}
          {a.status === "submitted" &&
            (a.score !== undefined && a.score !== null ? (
              <div>
                <p className="text-2xl font-bold">
                  {a.score}
                  <span className="text-base text-muted"> / {a.total_marks}</span>
                </p>
                <p className="text-xs text-muted">
                  {a.correct} correct · {a.answered} answered
                </p>
              </div>
            ) : (
              <p className="text-sm text-muted">Your answers were submitted.</p>
            ))}
        </div>
      </div>
    </Card>
  );
}

export function StartModal({ test, onClose, onStart }) {
  return (
    <Modal title={`Start "${test.title}"?`} onClose={onClose}>
      <div className="space-y-4 text-sm">
        <TestFacts test={test} />
        <ul className="list-disc space-y-1.5 pl-5 text-slate-300">
          <li>You get one attempt. The {test.duration_minutes}-minute timer starts as soon as you begin and keeps running even if you close the page.</li>
          <li>Your answers save automatically. You can change them and move between questions until you submit.</li>
          <li>When time runs out, the test is submitted automatically.</li>
          <li>Stay on the test page: leaving the tab is recorded.</li>
        </ul>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Not yet
          </Button>
          <Button onClick={onStart}>Start now</Button>
        </div>
      </div>
    </Modal>
  );
}

export function RequiredTestBanner({ tests }) {
  const pending = (tests || []).filter((t) => t.required && t.attempt.status !== "submitted");
  if (!pending.length) return null;
  return (
    <Card className="mb-6 border-amber-500/40 bg-amber-500/5 p-5">
      <p className="font-semibold text-amber-200">You have a required test to complete</p>
      <p className="mt-1 text-sm text-slate-300">
        {pending.map((t) => t.title).join(", ")} — {pending[0].duration_minutes} minutes, one attempt.
      </p>
      <Link to="/tests" className="mt-3 inline-block text-sm font-medium text-primary hover:underline">
        Go to my tests →
      </Link>
    </Card>
  );
}
