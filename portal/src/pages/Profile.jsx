import { useState } from "react";
import { portal } from "../api.js";
import { useAuth } from "../auth.jsx";
import { Button, Card, ErrorText, Field, Notice, PageHeader } from "../components/ui.jsx";
import ProgramSelect, { usePrograms } from "../components/ProgramSelect.jsx";

const FIELDS = ["full_name", "phone", "registration_number", "graduation_year", "skills", "github", "linkedin"];

export default function Profile() {
  const { user, setUser } = useAuth();
  const [form, setForm] = useState(() => ({ ...Object.fromEntries(FIELDS.map((f) => [f, user[f] || ""])), program_slug: user.program?.slug || "" }));
  const programs = usePrograms();
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const set = (key) => (e) => {
    setSaved(false);
    setForm({ ...form, [key]: e.target.value });
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { user: me } = await portal.put("/me/profile", form);
      setUser(me);
      setSaved(true);
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };

  return (
    <>
      <PageHeader title="My profile" description={`${user.profile_completion}% complete`} />
      <Card className="max-w-3xl p-6">
        <form onSubmit={submit} className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Full name">
              <input className="input" required value={form.full_name} onChange={set("full_name")} />
            </Field>
            <Field label="Email" hint="Contact ZeptraAI to change your email">
              <input className="input opacity-60" value={user.email} disabled />
            </Field>
            <Field label="University">
              <input className="input opacity-60" value={user.university?.name || "–"} disabled />
            </Field>
            <Field label="Department · Batch">
              <input className="input opacity-60" value={[user.department, user.batch].filter(Boolean).join(" · ") || "–"} disabled />
            </Field>
            {user.role === "student" && programs?.length > 0 && (
              <div className="sm:col-span-2">
                <Field label="Masters program">
                  <ProgramSelect programs={programs} value={form.program_slug} onChange={(v) => setForm({ ...form, program_slug: v })} required />
                </Field>
              </div>
            )}
            <Field label="Registration number">
              <input className="input" value={form.registration_number} onChange={set("registration_number")} placeholder="MU-CSE-2023-042" />
            </Field>
            <Field label="Graduation year">
              <input className="input" inputMode="numeric" maxLength={4} value={form.graduation_year} onChange={set("graduation_year")} placeholder="2027" />
            </Field>
            <Field label="Phone">
              <input className="input" type="tel" value={form.phone} onChange={set("phone")} placeholder="+91 98765 43210" />
            </Field>
            <Field label="Skills" hint="Separate with commas">
              <input className="input" value={form.skills} onChange={set("skills")} placeholder="Python, Machine Learning, SQL" />
            </Field>
            <Field label="GitHub">
              <input className="input" type="url" value={form.github} onChange={set("github")} placeholder="https://github.com/username" />
            </Field>
            <Field label="LinkedIn">
              <input className="input" type="url" value={form.linkedin} onChange={set("linkedin")} placeholder="https://linkedin.com/in/username" />
            </Field>
          </div>
          <ErrorText>{error}</ErrorText>
          {saved && <Notice>Profile saved.</Notice>}
          <div className="flex justify-end">
            <Button type="submit" loading={busy}>
              Save profile
            </Button>
          </div>
        </form>
      </Card>
    </>
  );
}
