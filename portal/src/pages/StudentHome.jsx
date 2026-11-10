import { Link } from "react-router-dom";
import { portal } from "../api.js";
import { roleOf, useAuth } from "../auth.jsx";
import { Card, PageHeader, useLoad } from "../components/ui.jsx";
import { RequiredTestBanner } from "./MyTests.jsx";
import { projectStatus } from "./MyProjects.jsx";

export default function StudentHome() {
  const { user } = useAuth();
  const [tests] = useLoad(() => (roleOf(user) === "student" ? portal.get("/assessments") : Promise.resolve(null)), [user?.id]);
  const [projects] = useLoad(() => (roleOf(user) === "student" ? portal.get("/projects") : Promise.resolve(null)), [user?.id]);

  if (roleOf(user) !== "student") {
    return (
      <>
        <PageHeader title={`Welcome, ${user.full_name || user.name || user.email}`} />
        <Card className="p-6 text-sm text-muted">
          Your account isn't linked to a university yet. The University Portal is for students and coordinators of partner universities: ask your
          university's placement coordinator for your personal invitation link, then register with it.
        </Card>
      </>
    );
  }

  const done = user.profile_completion;
  return (
    <>
      <PageHeader
        title={`Welcome, ${(user.full_name || user.name || "").split(" ")[0] || "student"}`}
        description={[user.program?.title, user.university?.name, user.department, user.batch].filter(Boolean).join(" · ")}
      />
      {!user.program && (
        <Card className="mb-6 border-primary/40 p-5 text-sm">
          You haven't chosen your Masters program yet.{" "}
          <Link to="/profile" className="font-medium text-primary hover:underline">
            Choose it on your profile →
          </Link>
        </Card>
      )}
      <RequiredTestBanner tests={tests?.assessments} />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">Your profile</h2>
            <span className="text-sm text-muted">{done}% complete</span>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/5">
            <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${done}%` }} />
          </div>
          <p className="mt-3 text-sm text-muted">
            {done === 100
              ? "Your profile is complete. Your university and ZeptraAI can see your details for assessments and placements."
              : "Complete your profile so your university and ZeptraAI have your registration number, skills and links."}
          </p>
          <Link to="/profile" className="mt-4 inline-block text-sm font-medium text-primary hover:underline">
            {done === 100 ? "View profile" : "Complete profile"} →
          </Link>
        </Card>
        <Card className="p-5">
          <h2 className="font-semibold">Your tests</h2>
          {tests?.assessments?.length ? (
            <ul className="mt-3 space-y-2 text-sm">
              {tests.assessments.map((t) => (
                <li key={t.id} className="flex justify-between gap-2">
                  <span className="text-slate-300">{t.title}</span>
                  <span className="shrink-0 text-muted">
                    {t.attempt.status === "submitted" ? (t.attempt.score != null ? `${t.attempt.score}/${t.attempt.total_marks}` : "Submitted") : t.attempt.status === "in_progress" ? "In progress" : "Not started"}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-muted">No tests assigned yet.</p>
          )}
          <Link to="/tests" className="mt-4 inline-block text-sm font-medium text-primary hover:underline">
            Go to my tests →
          </Link>
          <h2 className="mt-6 font-semibold">Your projects</h2>
          {projects?.projects?.length ? (
            <ul className="mt-3 space-y-2 text-sm">
              {projects.projects.map((p) => (
                <li key={p.id} className="flex items-center justify-between gap-2">
                  <Link to={`/my-projects/${p.id}`} className="truncate text-slate-300 hover:text-primary">
                    {p.title}
                  </Link>
                  {projectStatus(p)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-muted">No projects assigned yet.</p>
          )}
          <Link to="/my-projects" className="mt-4 inline-block text-sm font-medium text-primary hover:underline">
            Go to my projects →
          </Link>
        </Card>
      </div>
    </>
  );
}
