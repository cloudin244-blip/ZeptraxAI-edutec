import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { portal } from "../api.js";
import { useAuth } from "../auth.jsx";
import { Button, ErrorText, Field, Loading, Notice } from "../components/ui.jsx";
import { AuthLayout } from "./Login.jsx";
import ProgramSelect, { usePrograms } from "../components/ProgramSelect.jsx";

export default function Register() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const { signIn, signOut, user } = useAuth();
  const navigate = useNavigate();
  const [invite, setInvite] = useState(null);
  const [form, setForm] = useState({ full_name: "", email: "", password: "", confirm: "", program_slug: "" });
  const programs = usePrograms();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    portal
      .post("/invitations/validate", { token })
      .then(setInvite)
      .catch((e) => setInvite({ valid: false, reason: e.message }));
  }, [token]);

  if (!invite) return <Loading />;

  if (!invite.valid) {
    return (
      <AuthLayout title="Invitation not valid">
        <ErrorText>{invite.reason}</ErrorText>
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
  const isAdmin = invite.role === "university_admin";

  const submit = async (e) => {
    e.preventDefault();
    if (form.password !== form.confirm) return setError("Passwords do not match");
    setBusy(true);
    setError("");
    try {
      const { access_token } = await portal.post("/register", { token, full_name: form.full_name, email: form.email, password: form.password, program_slug: form.program_slug });
      await signIn(access_token);
      navigate(isAdmin ? "/overview" : "/tests", { replace: true }); // students start with their required test
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <AuthLayout
      title={isAdmin ? "Create your university admin account" : "Create your student account"}
      subtitle={`You've been invited to join ${invite.university?.name || "a university"} on the ZeptraAI University Portal.`}
    >
      {user && (
        <div className="mb-4">
          <Notice>
            You're logged in as {user.email}. This invitation creates a new account.{" "}
            <button className="underline" onClick={signOut}>
              Log out first
            </button>
          </Notice>
        </div>
      )}
      {(invite.department || invite.batch) && (
        <p className="mb-4 text-sm text-muted">
          {[invite.department && `Department: ${invite.department}`, invite.batch && `Batch: ${invite.batch}`].filter(Boolean).join(" · ")}
        </p>
      )}
      <form onSubmit={submit} className="space-y-4">
        <Field label="Full name">
          <input className="input" required autoComplete="name" value={form.full_name} onChange={set("full_name")} />
        </Field>
        <Field label="Email">
          <input className="input" type="email" required autoComplete="email" value={form.email} onChange={set("email")} />
        </Field>
        {!isAdmin && programs?.length > 0 && (
          <Field label="Masters program" hint="The program you're enrolling in. You can change it later on your profile.">
            <ProgramSelect programs={programs} value={form.program_slug} onChange={(v) => setForm({ ...form, program_slug: v })} required />
          </Field>
        )}
        <Field label="Password" hint="At least 8 characters">
          <input className="input" type="password" required minLength={8} autoComplete="new-password" value={form.password} onChange={set("password")} />
        </Field>
        <Field label="Confirm password">
          <input className="input" type="password" required autoComplete="new-password" value={form.confirm} onChange={set("confirm")} />
        </Field>
        <ErrorText>{error}</ErrorText>
        <Button type="submit" loading={busy} className="w-full">
          Create account
        </Button>
      </form>
    </AuthLayout>
  );
}
