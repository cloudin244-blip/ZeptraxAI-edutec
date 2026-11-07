import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { portal } from "../api.js";
import { Badge, Button, Card, ErrorText, Loading, Modal } from "../components/ui.jsx";
import { formatClock } from "./MyTests.jsx";

export default function TakeTest() {
  const { id } = useParams();
  const [paper, setPaper] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    portal
      .post(`/assessments/${id}/start`)
      .then((res) => (res.submitted ? setResult(res.result) : setPaper(res)))
      .catch((e) => setError(e.message));
  }, [id]);

  if (error)
    return (
      <Centered>
        <ErrorText>{error}</ErrorText>
        <BackLink />
      </Centered>
    );
  if (result) return <Result result={result} />;
  if (!paper) return <Loading />;
  return <Exam paper={paper} onDone={setResult} />;
}

function Centered({ children }) {
  return <div className="mx-auto max-w-lg space-y-4 px-4 py-16">{children}</div>;
}

function BackLink() {
  return (
    <Link to="/tests" className="inline-block text-sm text-primary hover:underline">
      ← Back to my tests
    </Link>
  );
}

function Result({ result }) {
  const hasScore = result.score !== undefined && result.score !== null;
  return (
    <Centered>
      <Card className="p-8 text-center">
        <p className="text-sm font-semibold uppercase tracking-wider text-green-300">Test submitted</p>
        {hasScore ? (
          <>
            <p className="mt-4 text-5xl font-bold">
              {result.score}
              <span className="text-2xl text-muted"> / {result.total_marks}</span>
            </p>
            <p className="mt-2 text-sm text-muted">
              {result.correct} correct · {result.answered} answered
            </p>
          </>
        ) : (
          <p className="mt-4 text-slate-300">Your answers have been recorded. Your university will share the results.</p>
        )}
        {result.auto_submitted && <p className="mt-4 text-sm text-amber-300">Time ran out, so your saved answers were submitted automatically.</p>}
      </Card>
      <BackLink />
    </Centered>
  );
}

function Exam({ paper, onDone }) {
  const questions = paper.questions;
  const total = questions.length;
  const offset = useRef(paper.server_time - Date.now() / 1000);
  const [answers, setAnswers] = useState(paper.answers || {});
  const [current, setCurrent] = useState(0);
  const [remaining, setRemaining] = useState(paper.deadline - paper.server_time);
  const [saveState, setSaveState] = useState({}); // qid -> "saving" | "error"
  const [tabSwitches, setTabSwitches] = useState(paper.tab_switches || 0);
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [banner, setBanner] = useState("");
  const done = useRef(false);

  const submit = useCallback(async () => {
    if (done.current) return;
    done.current = true;
    setSubmitting(true);
    try {
      const { result } = await portal.post(`/attempts/${paper.attempt_id}/submit`);
      onDone(result);
    } catch (e) {
      done.current = false;
      setSubmitting(false);
      setBanner(`Couldn't submit: ${e.message} Check your connection and press Submit again.`);
    }
  }, [paper.attempt_id, onDone]);

  // Server-owned clock
  useEffect(() => {
    const tick = () => {
      const left = paper.deadline - (Date.now() / 1000 + offset.current);
      setRemaining(left);
      if (left <= 0) submit();
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [paper.deadline, submit]);

  // Leaving the tab is recorded
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "hidden" && !done.current) {
        portal
          .post(`/attempts/${paper.attempt_id}/event`, { type: "tab_hidden" })
          .then((r) => setTabSwitches(r.tab_switches))
          .catch(() => {});
      }
    };
    const onUnload = (e) => {
      if (!done.current) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("beforeunload", onUnload);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("beforeunload", onUnload);
    };
  }, [paper.attempt_id]);

  const choose = async (qid, option) => {
    if (done.current) return;
    const previous = answers[qid];
    const next = previous === option ? null : option; // tapping the chosen option clears it
    setAnswers((a) => {
      const copy = { ...a };
      if (next === null) delete copy[qid];
      else copy[qid] = next;
      return copy;
    });
    setSaveState((s) => ({ ...s, [qid]: "saving" }));
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        await portal.put(`/attempts/${paper.attempt_id}/answer`, { question_id: qid, option: next });
        setSaveState((s) => ({ ...s, [qid]: undefined }));
        return;
      } catch (e) {
        if (e.status === 409) return submit(); // time is up on the server
      }
    }
    setSaveState((s) => ({ ...s, [qid]: "error" }));
  };

  const q = questions[current];
  const answered = Object.keys(answers).length;
  const urgent = remaining <= 300;

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-border bg-card/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="min-w-0">
            <p className="truncate font-semibold">{paper.assessment.title}</p>
            <p className="text-xs text-muted">
              {answered} of {total} answered
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span
              className={`rounded-lg px-3 py-1.5 font-mono text-lg font-semibold tabular-nums ${urgent ? "bg-red-500/15 text-red-300" : "bg-white/5"}`}
              aria-label="Time left"
              aria-live={urgent ? "polite" : "off"}
            >
              {formatClock(remaining)}
            </span>
            <Button onClick={() => setConfirming(true)} loading={submitting}>
              Submit
            </Button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-4 py-6">
        {banner && (
          <div className="mb-4">
            <ErrorText>{banner}</ErrorText>
          </div>
        )}
        {tabSwitches > 0 && (
          <p className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
            You left the test tab {tabSwitches} {tabSwitches === 1 ? "time" : "times"}. This is recorded and shared with your university.
          </p>
        )}
        <div className="grid gap-6 lg:grid-cols-[1fr_260px]">
          <Card className="p-5 sm:p-7">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm text-muted">
                Question {current + 1} of {total}
              </p>
              <Badge tone="blue">{q.section}</Badge>
            </div>
            <p className="mt-4 whitespace-pre-line text-base leading-relaxed">{q.text}</p>
            {q.code && (
              <pre className="mt-4 overflow-x-auto rounded-lg border border-border bg-background p-4 font-mono text-sm leading-relaxed text-slate-200">
                {q.code}
              </pre>
            )}
            <div className="mt-6 space-y-3" role="radiogroup" aria-label={`Answer for question ${current + 1}`}>
              {q.options.map((opt, i) => {
                const selected = answers[q.id] === i;
                return (
                  <button
                    key={i}
                    role="radio"
                    aria-checked={selected}
                    onClick={() => choose(q.id, i)}
                    className={`flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-left text-sm transition-colors ${
                      selected ? "border-primary bg-primary/10" : "border-border hover:bg-white/5"
                    }`}
                  >
                    <span
                      className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold ${
                        selected ? "border-primary bg-primary text-white" : "border-border text-muted"
                      }`}
                    >
                      {String.fromCharCode(65 + i)}
                    </span>
                    <span className="leading-relaxed">{opt}</span>
                  </button>
                );
              })}
            </div>
            <p className="mt-3 h-5 text-xs text-muted">
              {saveState[q.id] === "saving" && "Saving…"}
              {saveState[q.id] === "error" && <span className="text-red-300">Not saved — check your connection and choose again.</span>}
              {!saveState[q.id] && answers[q.id] !== undefined && "Saved. Tap your answer again to clear it."}
            </p>
            <div className="mt-4 flex justify-between gap-2">
              <Button variant="secondary" disabled={current === 0} onClick={() => setCurrent((c) => c - 1)}>
                ← Previous
              </Button>
              {current < total - 1 ? (
                <Button variant="secondary" onClick={() => setCurrent((c) => c + 1)}>
                  Next →
                </Button>
              ) : (
                <Button onClick={() => setConfirming(true)}>Finish</Button>
              )}
            </div>
          </Card>

          <Card className="h-fit p-4 lg:sticky lg:top-24">
            <p className="mb-3 text-sm font-medium">Questions</p>
            <div className="grid grid-cols-8 gap-1.5 lg:grid-cols-5">
              {questions.map((item, i) => {
                const isAnswered = answers[item.id] !== undefined;
                return (
                  <button
                    key={item.id}
                    onClick={() => setCurrent(i)}
                    aria-label={`Question ${i + 1}${isAnswered ? ", answered" : ""}`}
                    aria-current={i === current}
                    className={`h-9 rounded-md text-xs font-medium ${isAnswered ? "bg-primary text-white" : "bg-white/5 text-slate-300 hover:bg-white/10"} ${
                      i === current ? "ring-2 ring-accent ring-offset-2 ring-offset-card" : ""
                    }`}
                  >
                    {i + 1}
                  </button>
                );
              })}
            </div>
            <p className="mt-3 text-xs text-muted">
              <span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm bg-primary align-middle" /> answered
              <span className="mx-1 ml-3 inline-block h-2.5 w-2.5 rounded-sm bg-white/10 align-middle" /> not answered
            </p>
          </Card>
        </div>
      </div>

      {confirming && (
        <Modal title="Submit your test?" onClose={() => setConfirming(false)}>
          <div className="space-y-4 text-sm">
            <p>
              You've answered <strong>{answered}</strong> of {total} questions.
              {answered < total && ` ${total - answered} ${total - answered === 1 ? "is" : "are"} unanswered.`}
            </p>
            <p className="text-muted">After submitting you can't change your answers or take the test again.</p>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setConfirming(false)}>
                Keep working
              </Button>
              <Button
                loading={submitting}
                onClick={() => {
                  setConfirming(false);
                  submit();
                }}
              >
                Submit test
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
