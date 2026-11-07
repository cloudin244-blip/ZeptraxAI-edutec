import { useEffect, useState } from "react";

export function Card({ className = "", children }) {
  return <div className={`rounded-xl border border-border bg-card ${className}`}>{children}</div>;
}

export function PageHeader({ title, description, action }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-bold">{title}</h1>
        {description && <div className="mt-1 text-sm text-muted">{description}</div>}
      </div>
      {action}
    </div>
  );
}

export function Button({ variant = "primary", className = "", loading, children, ...props }) {
  const styles = {
    primary: "bg-primary text-white hover:bg-primary-hover",
    secondary: "border border-border bg-background text-slate-200 hover:bg-white/5",
    danger: "border border-red-500/40 text-red-300 hover:bg-red-500/10",
  };
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${styles[variant]} ${className}`}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading && <Spinner small />}
      {children}
    </button>
  );
}

export function Field({ label, hint, children }) {
  return (
    <div>
      <label className="block">
        <span className="label">{label}</span>
        {children}
      </label>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

export function Spinner({ small }) {
  return (
    <span
      className={`inline-block animate-spin rounded-full border-2 border-current border-t-transparent ${small ? "h-4 w-4" : "h-6 w-6 text-primary"}`}
      aria-label="Loading"
    />
  );
}

export function Loading() {
  return (
    <div className="flex justify-center py-16">
      <Spinner />
    </div>
  );
}

export function ErrorText({ children }) {
  return children ? <p className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{children}</p> : null;
}

export function Notice({ children }) {
  return <p className="rounded-lg border border-primary/30 bg-primary/10 px-3 py-2 text-sm text-blue-200">{children}</p>;
}

export function Stat({ label, value, hint }) {
  return (
    <Card className="p-5">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-1 text-3xl font-bold">{value ?? "–"}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </Card>
  );
}

export function Badge({ tone = "neutral", children }) {
  const tones = {
    neutral: "bg-white/5 text-slate-300",
    green: "bg-green-500/10 text-green-300",
    amber: "bg-amber-500/10 text-amber-300",
    red: "bg-red-500/10 text-red-300",
    blue: "bg-primary/10 text-blue-300",
  };
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${tones[tone]}`}>{children}</span>;
}

export function Table({ columns, rows, empty }) {
  if (!rows.length) return <p className="px-5 py-10 text-center text-sm text-muted">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-border text-xs uppercase tracking-wide text-muted">
          <tr>
            {columns.map((c) => (
              <th key={c.key} className="whitespace-nowrap px-5 py-3 font-medium">
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((row) => (
            <tr key={row.id} className="hover:bg-white/[0.02]">
              {columns.map((c) => (
                <td key={c.key} className="whitespace-nowrap px-5 py-3">
                  {c.render ? c.render(row) : row[c.key] || <span className="text-slate-600">–</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Modal({ title, onClose, children }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onMouseDown={onClose}>
      <div role="dialog" aria-label={title} className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-border bg-card p-6" onMouseDown={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} className="text-muted hover:text-white" aria-label="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function CopyButton({ text, label = "Copy" }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="secondary"
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          window.prompt("Copy this:", text);
        }
      }}
    >
      {copied ? "Copied" : label}
    </Button>
  );
}

// Loads data on mount and whenever `deps` change; returns [data, error, reload]
export function useLoad(load, deps) {
  const [state, setState] = useState({ data: null, error: "" });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, error: "" }));
    load()
      .then((data) => alive && setState({ data, error: "" }))
      .catch((e) => alive && setState({ data: null, error: e.message }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return [state.data, state.error, () => setTick((t) => t + 1)];
}

export const formatDate = (seconds) =>
  seconds ? new Date(seconds * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "–";
