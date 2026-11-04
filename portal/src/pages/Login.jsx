import { useState } from "react";
import { login } from "../api.js";
import { useAuth } from "../auth.jsx";
import { Button, Card, ErrorText, Field } from "../components/ui.jsx";

export function AuthLayout({ title, subtitle, children }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center">
          <p className="text-2xl font-bold">
            Zeptra<span className="text-primary">AI</span> <span className="text-accent">Edutech</span>
          </p>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted">University Portal</p>
        </div>
        <Card className="p-6 sm:p-8">
          <h1 className="text-xl font-semibold">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
          <div className="mt-6">{children}</div>
        </Card>
      </div>
    </div>
  );
}

export default function Login() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { access_token } = await login(email, password);
      await signIn(access_token);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <AuthLayout title="Log in" subtitle="Use the email and password you registered with.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Email">
          <input className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password">
          <input className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <ErrorText>{error}</ErrorText>
        <Button type="submit" loading={busy} className="w-full">
          Log in
        </Button>
        <p className="text-center text-xs text-muted">
          Students and university coordinators join with the invitation link they received. New here? Open your invitation link to register.
        </p>
      </form>
    </AuthLayout>
  );
}
