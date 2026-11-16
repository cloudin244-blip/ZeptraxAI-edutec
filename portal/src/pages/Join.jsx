import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { portal } from "../api.js";
import { useAuth } from "../auth.jsx";
import { Button, ErrorText, Field, Loading, Notice } from "../components/ui.jsx";
import { AuthLayout } from "./Login.jsx";
import ProgramSelect, { usePrograms } from "../components/ProgramSelect.jsx";

const BRANCHES = [
  "Computer Science and Engineering",
  "Information Technology",
  "Artificial Intelligence and Machine Learning",
  "Data Science",
  "Electronics and Communication Engineering",
  "Electrical and Electronics Engineering",
  "Mechanical Engineering",
  "Civil Engineering",
  "Computer Applications",
];

const thisYear = new Date().getFullYear();
const YEARS = Array.from({ length: 9 }, (_, i) => String(thisYear - 2 + i));

// Shareable signup link: /portal/#/join?code=...
export default function Join() {
  const [params] = useSearchParams();
  const code = (params.get("code") || "").trim();
  const { signIn, signOut, user } = useAuth();
  const navigate = useNavigate();
  const programs = usePrograms();
  const [link, setLink] = useState(null);
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    phone: "",
    registration_number: "",
    university_id: "",
    degree: "",
    department: "",
    graduation_year: "",
    program_slug: "",
    password: "",
    confirm: "",
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    portal
      .post("/join/validate", { code }, { retries: 3 })
      .then(setLink)
      .catch((e) => setLink({ valid: false, reason: e.message }));
  }, [code]);

  if (!link) return <Loading />;

  if (!link.valid) {
    return (
      <AuthLayout title="Signup link not valid">
        <ErrorText>{link.reason}</ErrorText>
        <p className="mt-4 text-sm text-muted">
          Already registered?{" "}
          <Link to="/login" className="text-primary hover:underline">
            Log in
          </Link>
        </p>
      </AuthLayout>
    );
  }

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    if (form.password !== form.confirm) return setError("Passwords do not match");
    setBusy(true);
    setError("");
    try {
      const { confirm, ...details } = form;
      // Safe to retry: submitting the same details twice signs the student in instead of failing
      const res = await portal.post("/join", { code, ...details }, { retries: 3 });
      await signIn(res.access_token);
      navigate(res.next_test_id ? `/tests?start=${encodeURIComponent(res.next_test_id)}` : "/home", { replace: true });
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  const where = link.university?.name || "your university";
  const subtitle = link.test
    ? `Register with your ${where} details. Right after signing up you'll start "${link.test.title}".`
    : `Register with your ${where} details to join the ZeptraAI University Portal.`;

  return (
    <AuthLayout title="Create your student account" subtitle={subtitle} wide>
      {user && (
        <div className="mb-4">
          <Notice>
            You're logged in as {user.email}. This link creates a new account.{" "}
            <button className="underline" onClick={signOut}>
              Log out first
            </button>
          </Notice>
        </div>
      )}
      <form onSubmit={submit} className="space-y-5">
        <fieldset className="space-y-4">
          <legend className="mb-3 text-xs font-semibold uppercase tracking-wider text-accent">About you</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Full name">
              <input className="input" required autoComplete="name" maxLength={120} value={form.full_name} onChange={set("full_name")} />
            </Field>
            <Field label="Email">
              <input className="input" type="email" required autoComplete="email" value={form.email} onChange={set("email")} />
            </Field>
            <Field label="Phone number" hint="With country code, e.g. +91 98765 43210">
              <input
                className="input"
                type="tel"
                required
                autoComplete="tel"
                inputMode="tel"
                pattern="[+]?[0-9 ()\-]{10,20}"
                title="10 to 15 digits, optionally starting with +"
                value={form.phone}
                onChange={set("phone")}
              />
            </Field>
            <Field label="Registration / roll number">
              <input className="input" required maxLength={60} value={form.registration_number} onChange={set("registration_number")} placeholder="e.g. AP23110010123" />
            </Field>
          </div>
        </fieldset>

        <fieldset className="space-y-4">
          <legend className="mb-3 text-xs font-semibold uppercase tracking-wider text-accent">Your university</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="University">
              {link.university ? (
                <input className="input opacity-60" value={link.university.name} disabled />
              ) : (
                <select className="input" required value={form.university_id} onChange={set("university_id")}>
                  <option value="">Choose your university</option>
                  {(link.universities || []).map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="Degree">
              <input className="input" required list="join-degrees" maxLength={60} value={form.degree} onChange={set("degree")} placeholder="e.g. B.Tech" />
              <datalist id="join-degrees">
                {(link.degrees || []).map((d) => (
                  <option key={d} value={d} />
                ))}
              </datalist>
            </Field>
            <Field label="Branch / department">
              {link.department ? (
                <input className="input opacity-60" value={link.department} disabled />
              ) : (
                <>
                  <input className="input" required list="join-branches" maxLength={80} value={form.department} onChange={set("department")} placeholder="e.g. Computer Science and Engineering" />
                  <datalist id="join-branches">
                    {BRANCHES.map((b) => (
                      <option key={b} value={b} />
                    ))}
                  </datalist>
                </>
              )}
            </Field>
            <Field label="Graduation year">
              <select className="input" required value={form.graduation_year} onChange={set("graduation_year")}>
                <option value="">Choose year</option>
                {YEARS.map((y) => (
                  <option key={y}>{y}</option>
                ))}
              </select>
            </Field>
            {link.batch && (
              <Field label="Batch">
                <input className="input opacity-60" value={link.batch} disabled />
              </Field>
            )}
            {programs?.length > 0 && (
              <div className="sm:col-span-2">
                <Field label="Masters program" hint="The ZeptraAI program you're enrolling in. You can change it later on your profile.">
                  <ProgramSelect programs={programs} value={form.program_slug} onChange={(v) => setForm({ ...form, program_slug: v })} required />
                </Field>
              </div>
            )}
          </div>
        </fieldset>

        <fieldset className="space-y-4">
          <legend className="mb-3 text-xs font-semibold uppercase tracking-wider text-accent">Password</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Password" hint="At least 8 characters">
              <input className="input" type="password" required minLength={8} autoComplete="new-password" value={form.password} onChange={set("password")} />
            </Field>
            <Field label="Confirm password">
              <input className="input" type="password" required autoComplete="new-password" value={form.confirm} onChange={set("confirm")} />
            </Field>
          </div>
        </fieldset>

        <ErrorText>{error}</ErrorText>
        <Button type="submit" loading={busy} className="w-full">
          {link.test ? "Create account and go to the test" : "Create account"}
        </Button>
        <p className="text-center text-sm text-muted">
          Already registered?{" "}
          <Link to="/login" className="text-primary hover:underline">
            Log in
          </Link>
        </p>
      </form>
    </AuthLayout>
  );
}
