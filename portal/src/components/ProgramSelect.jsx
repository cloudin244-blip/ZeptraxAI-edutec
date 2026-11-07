import { useEffect, useState } from "react";

// Masters programs currently shown on the website, grouped by category
export function usePrograms() {
  const [programs, setPrograms] = useState(null);
  useEffect(() => {
    fetch("/api/catalog")
      .then((r) => r.json())
      .then((c) => setPrograms(c.programs || []))
      .catch(() => setPrograms([]));
  }, []);
  return programs;
}

export default function ProgramSelect({ programs, value, onChange, required }) {
  const groups = {};
  (programs || []).forEach((p) => (groups[p.category || "Other programs"] ||= []).push(p));
  return (
    <select className="input" required={required} value={value} onChange={(e) => onChange(e.target.value)} aria-label="Masters program">
      <option value="">{programs ? "Choose your program" : "Loading programs…"}</option>
      {Object.entries(groups).map(([category, items]) => (
        <optgroup key={category} label={category}>
          {items.map((p) => (
            <option key={p.slug} value={p.slug}>
              {p.title}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}
