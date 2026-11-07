import { useMemo, useState } from "react";
import { portal } from "../api.js";
import { Badge, Button, Card, ErrorText, Field, Loading, Modal, Notice, PageHeader, useLoad } from "../components/ui.jsx";

const KINDS = {
  programs: { label: "Masters programs", one: "program", key: "programs" },
  "free-courses": { label: "Free courses", one: "free course", key: "free_courses" },
};

export default function Catalog() {
  const [data, error, reload] = useLoad(() => portal.get("/catalog"), []);
  const [kind, setKind] = useState("programs");
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState(null); // {} = new item
  const [busy, setBusy] = useState("");
  const [actionError, setActionError] = useState("");

  const items = data ? data[KINDS[kind].key] : [];
  const categories = useMemo(() => [...new Set(items.map((i) => i.category).filter(Boolean))].sort(), [items]);
  const q = search.trim().toLowerCase();
  const shown = items.filter((i) => !q || [i.title, i.category, i.slug].some((v) => (v || "").toLowerCase().includes(q)));

  const run = async (id, action) => {
    setBusy(id);
    setActionError("");
    try {
      await action();
      reload();
    } catch (e) {
      setActionError(e.message);
    }
    setBusy("");
  };

  const move = (index, delta) => {
    const ids = items.map((i) => i.id);
    const target = index + delta;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    run(items[index].id, () => portal.post(`/catalog/${kind}/reorder`, { ids }));
  };

  const remove = (item) => {
    if (!window.confirm(`Delete "${item.title}" from the website? This can't be undone. (To take it down temporarily, hide it instead.)`)) return;
    run(item.id, () => portal.del(`/catalog/${kind}/${item.id}`));
  };

  if (error) return <ErrorText>{error}</ErrorText>;
  if (!data) return <Loading />;

  return (
    <>
      <PageHeader
        title="Website catalog"
        description="The Masters programs and free courses shown on the landing page, AI Programs, program pages, Free Courses and the footer. Visitors see changes the next time they open the site."
        action={<Button onClick={() => setEditing({})}>Add {KINDS[kind].one}</Button>}
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {Object.entries(KINDS).map(([k, v]) => (
          <button
            key={k}
            onClick={() => {
              setKind(k);
              setSearch("");
            }}
            className={`rounded-lg px-4 py-2 text-sm font-medium ${kind === k ? "bg-primary/15 text-blue-300" : "text-slate-300 hover:bg-white/5"}`}
          >
            {v.label} <span className="text-muted">({data[v.key].length})</span>
          </button>
        ))}
        <input className="input ml-auto max-w-xs" placeholder="Search title or category" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search catalog" />
      </div>
      <ErrorText>{actionError}</ErrorText>
      {!items.length && (
        <Card className="p-6 text-sm text-muted">
          Nothing here yet. While this list is empty the website keeps showing its built-in {KINDS[kind].label.toLowerCase()}.
        </Card>
      )}
      <Card>
        <ul className="divide-y divide-border">
          {shown.map((item) => {
            const index = items.indexOf(item);
            return (
              <li key={item.id} className={`flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center ${item.visible ? "" : "opacity-60"}`}>
                <div className="flex shrink-0 items-center gap-1">
                  <button className="rounded px-2 py-1 text-muted hover:bg-white/5 disabled:opacity-30" disabled={!!q || index === 0 || !!busy} onClick={() => move(index, -1)} aria-label={`Move ${item.title} up`}>
                    ↑
                  </button>
                  <button className="rounded px-2 py-1 text-muted hover:bg-white/5 disabled:opacity-30" disabled={!!q || index === items.length - 1 || !!busy} onClick={() => move(index, 1)} aria-label={`Move ${item.title} down`}>
                    ↓
                  </button>
                  <span className="w-8 text-right text-xs text-muted">{index + 1}</span>
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{item.title}</p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted">
                    {item.category ? <span>{item.category}</span> : kind === "programs" ? <Badge tone="amber">No category: not listed on the AI Programs page</Badge> : null}
                    {kind === "programs" && (
                      <a href={`/programs/${item.slug}`} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                        /programs/{item.slug}
                      </a>
                    )}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Badge tone={item.visible ? "green" : "neutral"}>{item.visible ? "Shown" : "Hidden"}</Badge>
                  <Button variant="secondary" loading={busy === item.id} onClick={() => run(item.id, () => portal.put(`/catalog/${kind}/${item.id}`, { visible: !item.visible }))}>
                    {item.visible ? "Hide" : "Show"}
                  </Button>
                  <Button variant="secondary" onClick={() => setEditing(item)}>
                    Edit
                  </Button>
                  <Button variant="danger" onClick={() => remove(item)} disabled={!!busy}>
                    Delete
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      </Card>
      {q && <p className="mt-2 text-xs text-muted">Clear the search to reorder items.</p>}
      {editing && (
        <ItemForm
          kind={kind}
          item={editing}
          categories={categories}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            reload();
          }}
        />
      )}
    </>
  );
}

function ItemForm({ kind, item, categories, onClose, onSaved }) {
  const isNew = !item.id;
  const programs = kind === "programs";
  const [form, setForm] = useState({
    title: item.title || "",
    slug: item.slug || "",
    category: item.category || "",
    tagline: item.tagline ?? (isNew ? "AI-focused masters program." : ""),
    description: item.description ?? "",
    duration: item.duration ?? (isNew && programs ? "4 months" : ""),
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    const body = programs ? form : { title: form.title, category: form.category, description: form.description };
    try {
      if (isNew) await portal.post(`/catalog/${kind}`, body);
      else await portal.put(`/catalog/${kind}/${item.id}`, body);
      onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <Modal title={isNew ? `Add ${KINDS[kind].one}` : `Edit ${item.title}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Title">
          <input className="input" required maxLength={150} value={form.title} onChange={set("title")} />
        </Field>
        {programs && (
          <Field label="Web address" hint={`The page is /programs/${form.slug || "(made from the title)"}. Changing it breaks links people have saved.`}>
            <input className="input font-mono text-xs" maxLength={100} value={form.slug} onChange={set("slug")} placeholder="made from the title if left empty" />
          </Field>
        )}
        <Field label="Category" hint={programs ? "Programs are grouped by category on the AI Programs page. Leave empty to keep a program off that page." : "Courses are grouped by category on the Free Courses page."}>
          <input className="input" list="catalog-categories" maxLength={60} value={form.category} onChange={set("category")} />
          <datalist id="catalog-categories">
            {categories.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </Field>
        {programs && (
          <>
            <Field label="Tagline">
              <input className="input" maxLength={200} value={form.tagline} onChange={set("tagline")} />
            </Field>
            <Field label="Duration">
              <input className="input" maxLength={40} value={form.duration} onChange={set("duration")} placeholder="4 months" />
            </Field>
          </>
        )}
        <Field label="Description">
          <textarea className="input" rows={4} maxLength={programs ? 2000 : 500} value={form.description} onChange={set("description")} />
        </Field>
        {isNew && <Notice>New items are added at the end of the list and shown on the website straight away.</Notice>}
        <ErrorText>{error}</ErrorText>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={busy}>
            {isNew ? "Add" : "Save"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
