import { Link } from "react-router-dom";
import { portal } from "../api.js";
import { roleOf, useAuth } from "../auth.jsx";
import { Card, ErrorText, Loading, PageHeader, Stat, useLoad } from "../components/ui.jsx";

export default function Overview() {
  const { user } = useAuth();
  const staff = roleOf(user) === "staff";
  const [data, error] = useLoad(() => portal.get("/overview"), []);

  if (error) return <ErrorText>{error}</ErrorText>;
  if (!data) return <Loading />;

  if (staff) {
    return (
      <>
        <PageHeader title="Overview" description="All universities on the ZeptraAI University Portal." />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Universities" value={data.universities} />
          <Stat label="Registered students" value={data.students} />
          <Stat label="University admins" value={data.university_admins} />
          <Stat label="Active signup links" value={data.active_links} hint={data.inactive_students ? `${data.inactive_students} deactivated students` : undefined} />
        </div>
        <Steps
          steps={[
            ["Add a university", "Set its short code and how many students it may onboard.", "/universities"],
            ["Invite the university admin", "Create a one-time admin link from the university's row and send it to the coordinator.", "/universities"],
            ["Share a signup link", "Create the university's signup link and share it with its students. Each one registers and goes straight to the test.", "/invitations"],
            ["Follow the results", "See test results, malpractice flags and project marks under Tests and Projects.", "/results"],
          ]}
        />
      </>
    );
  }

  const limit = data.max_students;
  return (
    <>
      <PageHeader title={data.university?.name || "Your university"} description="Your students on the ZeptraAI University Portal." />
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Registered students" value={data.students} hint={limit ? `Limit: ${limit} students` : undefined} />
        <Stat label="Active signup links" value={data.active_links} />
        <Stat label="Complete profiles" value={data.profiles_complete} hint={data.students ? `${Math.round((100 * data.profiles_complete) / data.students)}% of students` : undefined} />
      </div>
      <Steps
        steps={[
          ["Create your signup link", "One link for your university, optionally for a branch and batch, and the test students take after signing up.", "/invitations"],
          ["Share it", "Post it in your class WhatsApp group or email it. Every student signs up with their own details."],
          ["Track your students", "See who registered, their test results and project submissions.", "/students"],
        ]}
      />
    </>
  );
}

function Steps({ steps }) {
  return (
    <Card className="mt-6 p-5">
      <h2 className="font-semibold">How it works</h2>
      <ol className="mt-3 space-y-3">
        {steps.map(([title, text, to], i) => (
          <li key={title} className="flex gap-3 text-sm">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-blue-300">{i + 1}</span>
            <span>
              {to ? (
                <Link to={to} className="font-medium text-slate-100 hover:text-primary">
                  {title}
                </Link>
              ) : (
                <span className="font-medium">{title}</span>
              )}
              <span className="block text-muted">{text}</span>
            </span>
          </li>
        ))}
      </ol>
    </Card>
  );
}
