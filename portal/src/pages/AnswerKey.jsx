import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { portal } from "../api.js";
import { Badge, Card, ErrorText, Loading, PageHeader, useLoad } from "../components/ui.jsx";
import { TestFacts } from "./MyTests.jsx";

export default function AnswerKey() {
  const { id } = useParams();
  const [data, error] = useLoad(() => portal.get(`/assessments/${id}/key`), [id]);
  const [onlyFlagged, setOnlyFlagged] = useState(false);

  if (error) return <ErrorText>{error}</ErrorText>;
  if (!data) return <Loading />;
  const flagged = data.questions.filter((q) => q.review).length;
  const questions = onlyFlagged ? data.questions.filter((q) => q.review) : data.questions;

  return (
    <>
      <PageHeader
        title={`Answer key: ${data.assessment.title}`}
        description={<TestFacts test={data.assessment} />}
        action={
          <Link to="/results" className="text-sm text-primary hover:underline">
            ← Test results
          </Link>
        }
      />
      <Card className="mb-4 p-4 text-sm text-slate-300">
        Only Zeptrax staff can see this page; students never receive the correct answers. Students see questions and options in a shuffled order.
        {flagged > 0 && (
          <label className="mt-3 flex items-center gap-2 text-amber-200">
            <input type="checkbox" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} />
            Show only the {flagged} questions marked for review (options written or wording changed when the test was set up)
          </label>
        )}
      </Card>
      <div className="space-y-4">
        {questions.map((q) => (
          <Card key={q.number} className="p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-semibold">Question {q.number}</p>
              <Badge tone="blue">{q.section}</Badge>
            </div>
            <p className="mt-2 text-sm leading-relaxed">{q.text}</p>
            {q.code && <pre className="mt-3 overflow-x-auto rounded-lg border border-border bg-background p-3 font-mono text-xs text-slate-200">{q.code}</pre>}
            <ol className="mt-3 space-y-1.5 text-sm">
              {q.options.map((opt, i) => (
                <li key={i} className={`rounded-md px-3 py-1.5 ${i === q.answer ? "bg-green-500/10 text-green-200" : "text-slate-300"}`}>
                  <span className="mr-2 font-semibold">{String.fromCharCode(97 + i)})</span>
                  {opt}
                  {i === q.answer && <span className="ml-2 text-xs font-semibold uppercase tracking-wide">✓ correct</span>}
                </li>
              ))}
            </ol>
            {q.review && <p className="mt-3 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">Review: {q.review}</p>}
          </Card>
        ))}
      </div>
    </>
  );
}
