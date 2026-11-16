import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { portal } from "../api.js";
import { useAuth } from "../auth.jsx";
import { Badge, Button, Card, ErrorText, Field, formatDate, Loading, Modal, Notice, PageHeader, Table, useLoad } from "../components/ui.jsx";
import { usePrograms } from "../components/ProgramSelect.jsx";
import { BANK_TIME_LIMIT_HOURS, BRANCHES, PROJECT_BANK } from "../data/projectBank.js";
import { fromDateInput, toDateInput } from "./Projects.jsx";

const DIFFICULTY_TONE = { Easy: "green", Medium: "amber", Hard: "red" };

export function Difficulty({ level }) {
  return level ? <Badge tone={DIFFICULTY_TONE[level] || "neutral"}>{level}</Badge> : null;
}

export function BranchTags({ branches }) {
  if (!branches?.length) return <span className="text-xs text-muted">All branches</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {branches.map((b) => (
        <Badge key={b}>{BRANCHES[b] || b}</Badge>
      ))}
    </span>
  );
}

export const hoursText = (h) => (h ? `${h % 1 ? h : Math.round(h)} hour${h === 1 ? "" : "s"}` : "");

export function formatDateTime(seconds) {
  return seconds ? new Date(seconds * 1000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "";
}

// Live "time left" for a deadline; null when there is none
export function useTimeLeft(deadline) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!deadline) return undefined;
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, [deadline]);
  if (!deadline) return null;
  const left = Math.max(0, deadline - now);
  const h = Math.floor(left / 3600);
  const m = Math.floor((left % 3600) / 60);
  const s = Math.floor(left % 60);
  return { seconds: left, text: h >= 48 ? `${Math.floor(h / 24)} days` : `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` };
}

function audienceText(s, names) {
  if (s.audience === "all_students") return "All students";
  const list = s.targets.map((t) => names[t] || t).join(", ");
  return `${s.audience === "programs" ? "Programs" : "Universities"}: ${list}`;
}

function useNames() {
  const programs = usePrograms();
  const { user } = useAuth();
  const staff = user.portal_role === "staff";
  const [universities] = useLoad(() => (staff ? portal.get("/universities") : Promise.resolve(null)), [staff]);
  return useMemo(() => {
    const names = {};
    (programs || []).forEach((p) => (names[p.slug] = p.title));
    (universities?.universities || []).forEach((u) => (names[u.id] = u.name));
    if (user.university) names[user.university.id] = user.university.name;
    return { names, programs: programs || [], universities: universities?.universities || [] };
  }, [programs, universities, user.university]);
}

// ---------------------------------------------------------------- staff: list on the Projects page

export function ProjectSetsSection() {
  const { user } = useAuth();
  const superAdmin = user.role === "super_admin";
  const [data, error, reload] = useLoad(() => portal.get("/project-sets"), []);
  const [creating, setCreating] = useState(false);
  const { names } = useNames();

  const columns = [
    {
      key: "title",
      label: "Selection",
      render: (s) => (
        <Link to={`/projects/sets/${s.id}`} className="block">
          <p className="font-medium text-slate-100 hover:text-primary">{s.title}</p>
          <p className="text-xs text-muted">{audienceText(s, names)}</p>
        </Link>
      ),
    },
    { key: "status", label: "Status", render: (s) => <Badge tone={s.status === "published" ? "green" : "neutral"}>{s.status === "published" ? "Published" : "Draft"}</Badge> },
    { key: "projects", label: "Projects", render: (s) => s.projects },
    { key: "time", label: "Time to finish", render: (s) => (s.time_limit_hours ? hoursText(s.time_limit_hours) : "No limit") },
    { key: "chosen", label: "Students chose", render: (s) => s.chosen },
    {
      key: "open",
      label: "",
      render: (s) => (
        <Link to={`/projects/sets/${s.id}`}>
          <Button variant="secondary">Open</Button>
        </Link>
      ),
    },
  ];

  return (
    <section className="mb-10">
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold">Project selections</h2>
          <p className="text-sm text-muted">Students pick one project from a list. Their time starts when they choose.</p>
        </div>
        {superAdmin && (
          <Button className="shrink-0" onClick={() => setCreating(true)}>
            New project selection
          </Button>
        )}
      </div>
      <ErrorText>{error}</ErrorText>
      <Card>
        {!data ? (
          !error && <Loading />
        ) : data.sets.length ? (
          <Table columns={columns} rows={data.sets} empty="" />
        ) : (
          <div className="px-5 py-10 text-center text-sm text-muted">
            <p>No project selections yet. A selection holds the list of projects students choose from.</p>
            {superAdmin && (
              <>
                <p className="mt-1">Create one and the {PROJECT_BANK.length} ready-made final-year projects are added to it automatically.</p>
                <Button className="mt-4" onClick={() => setCreating(true)}>
                  Create a selection with the {PROJECT_BANK.length} projects
                </Button>
              </>
            )}
          </div>
        )}
      </Card>
      {creating && (
        <SetForm
          onClose={() => setCreating(false)}
          onSaved={() => {
            setCreating(false);
            reload();
          }}
        />
      )}
    </section>
  );
}

function SetForm({ existing, onClose, onSaved }) {
  const navigate = useNavigate();
  const { programs, universities } = useNames();
  const [form, setForm] = useState(() =>
    existing
      ? { ...existing, time_limit_hours: existing.time_limit_hours ?? "", due: toDateInput(existing.due_date) }
      : { title: "", description: "", audience: "universities", targets: [], time_limit_hours: BANK_TIME_LIMIT_HOURS, due: "", filter_by_branch: true, with_bank: true }
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setForm({ ...form, [k]: v });
  const toggle = (t) => set("targets", form.targets.includes(t) ? form.targets.filter((x) => x !== t) : [...form.targets, t]);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    const body = {
      title: form.title, description: form.description, audience: form.audience, targets: form.targets,
      time_limit_hours: form.time_limit_hours === "" ? null : Number(form.time_limit_hours), due_date: fromDateInput(form.due),
      filter_by_branch: !!form.filter_by_branch,
    };
    try {
      if (existing) {
        await portal.put(`/project-sets/${existing.id}`, body);
        onSaved();
      } else {
        const { set: created } = await portal.post("/project-sets", body);
        if (form.with_bank) await portal.post(`/project-sets/${created.id}/projects`, { projects: PROJECT_BANK }, { retries: 2 });
        navigate(`/projects/sets/${created.id}`);
      }
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <Modal title={existing ? "Edit project selection" : "New project selection"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Title" hint="Students see this, e.g. “Final-year project 2026”">
          <input className="input" required maxLength={150} value={form.title} onChange={(e) => set("title", e.target.value)} />
        </Field>
        <Field label="Instructions for students">
          <textarea className="input" rows={3} maxLength={3000} value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="Read the briefs carefully. Your choice is final." />
        </Field>
        <Field label="Who chooses from this list">
          <select className="input" value={form.audience} onChange={(e) => setForm({ ...form, audience: e.target.value, targets: [] })}>
            <option value="universities">Students of chosen universities</option>
            <option value="programs">Students of chosen programs</option>
            <option value="all_students">All students</option>
          </select>
        </Field>
        {form.audience !== "all_students" && (
          <div className="grid max-h-48 gap-2 overflow-y-auto rounded-lg border border-border p-3 sm:grid-cols-2">
            {(form.audience === "programs" ? programs.map((p) => [p.slug, p.title]) : universities.map((u) => [u.id, u.name])).map(([id, name]) => (
              <label key={id} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.targets.includes(id)} onChange={() => toggle(id)} /> {name}
              </label>
            ))}
          </div>
        )}
        <div>
          <label className="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" checked={!!form.filter_by_branch} onChange={(e) => set("filter_by_branch", e.target.checked)} /> Show each student only the
            projects for their branch
          </label>
          <p className="mt-1 text-xs text-muted">
            Uses the branch students entered at signup and the branch tags on each project. Projects without tags are shown to everyone; a student whose
            branch isn't recognised sees the whole list.
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Time to finish (hours)" hint="Counted from when each student chooses. Empty = no limit.">
            <input className="input" type="number" min={0.5} step={0.5} value={form.time_limit_hours} onChange={(e) => set("time_limit_hours", e.target.value)} />
          </Field>
          <Field label="Closing date (optional)" hint="No new choices after this day; all deadlines end by then.">
            <input className="input" type="date" value={form.due} onChange={(e) => set("due", e.target.value)} />
          </Field>
        </div>
        {!existing && (
          <label className="flex items-start gap-2 rounded-lg border border-border p-3 text-sm">
            <input type="checkbox" className="mt-0.5" checked={form.with_bank} onChange={(e) => set("with_bank", e.target.checked)} />
            <span>
              <span className="font-medium">Add the {PROJECT_BANK.length} ready-made projects</span>
              <span className="block text-xs text-muted">AI/ML, Generative AI, full-stack, cybersecurity, data, IoT, mechanical, electrical and civil, with briefs, branch tags and a 100-mark rubric. You can edit or hide any of them.</span>
            </span>
          </label>
        )}
        <ErrorText>{error}</ErrorText>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={busy}>
            {existing ? "Save" : "Create"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------- staff: one selection

export function ProjectSetDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const superAdmin = user.role === "super_admin";
  const [data, error, reload] = useLoad(() => portal.get(`/project-sets/${id}`), [id]);
  const { names } = useNames();
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState("");
  const [problem, setProblem] = useState("");
  const [notice, setNotice] = useState("");

  if (error) return <ErrorText>{error}</ErrorText>;
  if (!data) return <Loading />;
  const s = data.set;

  const run = async (label, action) => {
    setBusy(label);
    setProblem("");
    setNotice("");
    try {
      await action();
      reload();
    } catch (e) {
      setProblem(e.message);
    }
    setBusy("");
  };

  const addBank = () =>
    run("bank", async () => {
      const res = await portal.post(`/project-sets/${id}/projects`, { projects: PROJECT_BANK });
      setNotice(`${res.added} projects added${res.skipped ? `, ${res.skipped} already in this selection` : ""}.`);
    });

  const columns = [
    {
      key: "title",
      label: "Project",
      render: (p) => (
        <Link to={`/projects/${p.id}`} className="block max-w-md whitespace-normal">
          <p className="font-medium text-slate-100 hover:text-primary">{p.title}</p>
          <p className="text-xs text-muted">{p.category}</p>
        </Link>
      ),
    },
    { key: "difficulty", label: "Difficulty", render: (p) => <Difficulty level={p.difficulty} /> },
    ...(s.filter_by_branch ? [{ key: "branches", label: "For branches", render: (p) => <BranchTags branches={p.branches} /> }] : []),
    { key: "status", label: "Status", render: (p) => (p.status === "published" ? <Badge tone="green">Listed</Badge> : <Badge>Hidden</Badge>) },
    { key: "chosen", label: "Chosen by", render: (p) => p.chosen },
    { key: "submitted", label: "Submitted", render: (p) => p.submitted },
    { key: "evaluated", label: "Marked", render: (p) => p.evaluated },
    {
      key: "open",
      label: "",
      render: (p) => (
        <Link to={`/projects/${p.id}`}>
          <Button variant="secondary">{p.submitted ? "Mark" : "Open"}</Button>
        </Link>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title={s.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={s.status === "published" ? "green" : "neutral"}>{s.status === "published" ? "Published" : "Draft"}</Badge>
            {audienceText(s, names)} · {s.time_limit_hours ? `${hoursText(s.time_limit_hours)} from choosing` : "No time limit"}
            {s.due_date ? ` · closes ${formatDate(s.due_date)}` : ""}
            {s.filter_by_branch ? " · filtered by branch" : ""} · {data.total_chosen} chose
          </span>
        }
        action={
          <div className="flex flex-wrap gap-2">
            <Link to="/projects">
              <Button variant="secondary">All projects</Button>
            </Link>
            {superAdmin && (
              <>
                <Button variant="secondary" onClick={() => setEditing(true)}>
                  Edit settings
                </Button>
                <Button
                  loading={busy === "status"}
                  variant={s.status === "published" ? "secondary" : "primary"}
                  onClick={() => run("status", () => portal.put(`/project-sets/${id}`, { status: s.status === "published" ? "draft" : "published" }))}
                >
                  {s.status === "published" ? "Unpublish" : "Publish to students"}
                </Button>
              </>
            )}
          </div>
        }
      />
      {s.description && <p className="mb-4 max-w-3xl whitespace-pre-line text-sm text-slate-300">{s.description}</p>}
      <ErrorText>{problem}</ErrorText>
      {notice && (
        <div className="mb-4">
          <Notice>{notice}</Notice>
        </div>
      )}
      {superAdmin && (
        <Card className="mb-4 flex flex-col gap-3 p-4 text-sm sm:flex-row sm:items-center sm:justify-between">
          <p className="text-muted">
            Add projects one by one, or add the ready-made bank of {PROJECT_BANK.length} final-year projects (AI/ML, Generative AI, full-stack, cybersecurity,
            data science, IoT, mechanical, electrical, civil) with briefs, branch tags and a 100-mark rubric. You can edit or hide any of them afterwards.
          </p>
          <div className="flex shrink-0 gap-2">
            <Button variant="secondary" loading={busy === "bank"} onClick={addBank}>
              Add project bank ({PROJECT_BANK.length})
            </Button>
            <Link to={`/projects/new?set=${id}`}>
              <Button>Add project</Button>
            </Link>
          </div>
        </Card>
      )}
      <Card>
        <Table columns={columns} rows={data.projects} empty={superAdmin ? `No projects yet. Click "Add project bank (${PROJECT_BANK.length})" above, or add your own.` : "No projects in this selection yet."} />
      </Card>
      {superAdmin && !data.total_chosen && (
        <div className="mt-6">
          <Button
            variant="danger"
            loading={busy === "delete"}
            onClick={() =>
              window.confirm(`Delete "${s.title}" and its ${data.projects.length} projects?`) &&
              run("delete", async () => {
                await portal.del(`/project-sets/${id}`);
                navigate("/projects");
              })
            }
          >
            Delete selection
          </Button>
        </div>
      )}
      {editing && (
        <SetForm
          existing={s}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            reload();
          }}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------- students: choose one project

export function ChooseCard({ set: s }) {
  return (
    <Link to={`/my-projects/choose/${s.id}`} className="block">
      <Card className="border-primary/40 bg-primary/5 p-5 transition-colors hover:border-primary">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-semibold">Choose your project: {s.title}</p>
            <p className="text-sm text-muted">
              {s.options.length} projects to choose from
              {s.time_limit_hours ? ` · ${hoursText(s.time_limit_hours)} to finish once you choose` : ""}
              {s.due_date ? ` · choose by ${formatDate(s.due_date)}` : ""}
            </p>
          </div>
          <Badge tone="blue">{s.closed ? "Closed" : "Choose"}</Badge>
        </div>
      </Card>
    </Link>
  );
}

export function ChooseProject() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, error] = useLoad(() => portal.get("/projects"), []);
  const [category, setCategory] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(null);
  const [confirming, setConfirming] = useState(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  if (error) return <ErrorText>{error}</ErrorText>;
  if (!data) return <Loading />;
  const s = data.sets.find((x) => x.id === id);
  if (!s) {
    // Already chosen (or not available): go to the chosen project
    const chosen = data.projects.find((p) => p.set_id === id);
    return chosen ? (
      <Notice>
        You've already chosen <Link to={`/my-projects/${chosen.id}`} className="underline">{chosen.title}</Link>.
      </Notice>
    ) : (
      <ErrorText>This project selection isn't available to you.</ErrorText>
    );
  }

  const categories = [...new Set(s.options.map((o) => o.category).filter(Boolean))];
  const q = search.trim().toLowerCase();
  const shown = s.options.filter(
    (o) => (!category || o.category === category) && (!difficulty || o.difficulty === difficulty) && (!q || o.title.toLowerCase().includes(q))
  );
  const groups = {};
  shown.forEach((o) => (groups[o.category || "Other projects"] ||= []).push(o));

  const choose = async () => {
    setBusy(true);
    setProblem("");
    try {
      const res = await portal.post(`/project-sets/${id}/choose`, { project_id: confirming.id });
      navigate(`/my-projects/${res.project_id}`, { replace: true });
    } catch (e) {
      setProblem(e.message);
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        title={s.title}
        description={`Pick one project. ${s.time_limit_hours ? `You'll have ${hoursText(s.time_limit_hours)} to finish it from the moment you choose. ` : ""}Your choice is final.`}
        action={
          <Link to="/my-projects">
            <Button variant="secondary">My projects</Button>
          </Link>
        }
      />
      {s.description && <p className="mb-4 max-w-3xl whitespace-pre-line text-sm text-slate-300">{s.description}</p>}
      {s.closed && <ErrorText>This project selection has closed.</ErrorText>}
      {s.branch_note && (
        <div className="mb-4">
          <Notice>{s.branch_note}</Notice>
        </div>
      )}
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <input className="input" placeholder="Search projects" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search projects" />
        <select className="input" value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category">
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
        <select className="input" value={difficulty} onChange={(e) => setDifficulty(e.target.value)} aria-label="Difficulty">
          <option value="">Any difficulty</option>
          <option>Easy</option>
          <option>Medium</option>
          <option>Hard</option>
        </select>
      </div>
      {!shown.length && <Card className="p-6 text-sm text-muted">No projects match these filters.</Card>}
      <div className="space-y-6">
        {Object.entries(groups).map(([group, items]) => (
          <section key={group}>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-accent">{group}</h2>
            <div className="space-y-2">
              {items.map((o) => (
                <Card key={o.id} className="p-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <button className="min-w-0 text-left" onClick={() => setOpen(open === o.id ? null : o.id)} aria-expanded={open === o.id}>
                      <p className="font-medium">{o.title}</p>
                      <p className="mt-0.5 text-sm text-muted">{o.description}</p>
                    </button>
                    <div className="flex shrink-0 items-center gap-2">
                      <Difficulty level={o.difficulty} />
                      <Button variant="secondary" onClick={() => setOpen(open === o.id ? null : o.id)}>
                        {open === o.id ? "Hide brief" : "Read brief"}
                      </Button>
                      <Button disabled={s.closed} onClick={() => setConfirming(o)}>
                        Choose
                      </Button>
                    </div>
                  </div>
                  {open === o.id && (
                    <div className="mt-4 space-y-3 border-t border-border pt-4 text-sm">
                      <p className="whitespace-pre-line text-slate-300">{o.requirements}</p>
                      <div>
                        <p className="font-medium">Marking ({o.total_marks} marks)</p>
                        <ul className="mt-1 grid gap-1 text-muted sm:grid-cols-2">
                          {o.rubric.map((r) => (
                            <li key={r.criterion}>
                              {r.criterion}: {r.max_marks}
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  )}
                </Card>
              ))}
            </div>
          </section>
        ))}
      </div>
      {confirming && (
        <Modal title="Choose this project?" onClose={() => !busy && setConfirming(null)}>
          <div className="space-y-4 text-sm">
            <p className="font-medium">{confirming.title}</p>
            <ul className="list-disc space-y-1.5 pl-5 text-slate-300">
              <li>Your choice is final: you can't switch to another project.</li>
              {s.time_limit_hours ? (
                <li>
                  Your {hoursText(s.time_limit_hours)} start now. Submit your links before the time runs out, or you won't be able to submit.
                </li>
              ) : null}
            </ul>
            <ErrorText>{problem}</ErrorText>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" disabled={busy} onClick={() => setConfirming(null)}>
                Not yet
              </Button>
              <Button loading={busy} onClick={choose}>
                Choose and start
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}
