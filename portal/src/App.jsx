import { useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { roleOf, useAuth } from "./auth.jsx";
import { Loading } from "./components/ui.jsx";
import Login from "./pages/Login.jsx";
import Register from "./pages/Register.jsx";
import Overview from "./pages/Overview.jsx";
import Universities from "./pages/Universities.jsx";
import Invitations from "./pages/Invitations.jsx";
import Students from "./pages/Students.jsx";
import StudentHome from "./pages/StudentHome.jsx";
import Profile from "./pages/Profile.jsx";
import MyTests from "./pages/MyTests.jsx";
import TakeTest from "./pages/TakeTest.jsx";
import TestResults from "./pages/TestResults.jsx";
import AnswerKey from "./pages/AnswerKey.jsx";
import Catalog from "./pages/Catalog.jsx";
import ManageTests from "./pages/ManageTests.jsx";
import TestEditor from "./pages/TestEditor.jsx";
import Projects, { ProjectDetail, ProjectForm } from "./pages/Projects.jsx";
import MyProjects, { MyProject } from "./pages/MyProjects.jsx";

const NAV = {
  staff: [
    { to: "/overview", label: "Overview" },
    { to: "/universities", label: "Universities" },
    { to: "/invitations", label: "Invitations" },
    { to: "/students", label: "Students" },
    { to: "/manage-tests", label: "Tests" },
    { to: "/results", label: "Test results" },
    { to: "/projects", label: "Projects" },
  ],
  university_admin: [
    { to: "/overview", label: "Overview" },
    { to: "/students", label: "Students" },
    { to: "/invitations", label: "Bulk invitations" },
    { to: "/results", label: "Test results" },
    { to: "/projects", label: "Projects" },
  ],
  student: [
    { to: "/home", label: "My dashboard" },
    { to: "/tests", label: "My tests" },
    { to: "/my-projects", label: "My projects" },
    { to: "/profile", label: "My profile" },
  ],
  user: [{ to: "/home", label: "Home" }],
};

const ROLE_LABEL = { staff: "Zeptrax admin", university_admin: "University admin", student: "Student", user: "Member" };

export default function App() {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return <Loading />;

  return (
    <Routes>
      <Route path="/register" element={<Register />} />
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
      {/* The exam screen is full-width, without the sidebar */}
      <Route path="/tests/:id/take" element={user ? <TakeTest /> : <Navigate to="/login" replace />} />
      <Route path="/*" element={user ? <Shell /> : <Navigate to="/login" replace state={{ from: location.pathname }} />} />
    </Routes>
  );
}

function Shell() {
  const { user, signOut } = useAuth();
  const role = roleOf(user);
  const [menuOpen, setMenuOpen] = useState(false);
  const superAdmin = user.role === "super_admin";
  const nav = [...(NAV[role] || NAV.user), ...(superAdmin ? [{ to: "/catalog", label: "Website catalog" }] : [])];
  const manager = role === "staff" || role === "university_admin";

  return (
    <div className="min-h-screen md:flex">
      <aside className={`border-b border-border bg-card md:sticky md:top-0 md:h-screen md:w-60 md:shrink-0 md:border-b-0 md:border-r ${menuOpen ? "" : ""}`}>
        <div className="flex items-center justify-between px-5 py-4">
          <div>
            <p className="text-lg font-bold leading-tight">
              Zeptra<span className="text-primary">AI</span>
            </p>
            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-accent">University Portal</p>
          </div>
          <button className="rounded-lg border border-border px-3 py-1.5 text-sm md:hidden" onClick={() => setMenuOpen((o) => !o)} aria-expanded={menuOpen}>
            Menu
          </button>
        </div>
        <nav className={`${menuOpen ? "block" : "hidden"} space-y-1 px-3 pb-4 md:block`}>
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={() => setMenuOpen(false)}
              className={({ isActive }) =>
                `block rounded-lg px-3 py-2 text-sm ${isActive ? "bg-primary/10 font-medium text-blue-300" : "text-slate-300 hover:bg-white/5"}`
              }
            >
              {item.label}
            </NavLink>
          ))}
          <div className="mt-6 border-t border-border px-3 pt-4 text-xs text-muted">
            <p className="truncate text-slate-300">{user.full_name || user.name || user.email}</p>
            <p className="truncate">{user.email}</p>
            <p className="mt-1">
              {ROLE_LABEL[role]}
              {user.university ? ` · ${user.university.name}` : ""}
            </p>
            <button onClick={signOut} className="mt-3 text-red-300 hover:underline">
              Log out
            </button>
          </div>
        </nav>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-6 sm:px-8 sm:py-8">
        <Routes>
          {manager && <Route path="/overview" element={<Overview />} />}
          {manager && <Route path="/students" element={<Students />} />}
          {manager && <Route path="/invitations" element={<Invitations />} />}
          {manager && <Route path="/results" element={<TestResults />} />}
          {manager && <Route path="/projects" element={<Projects />} />}
          {manager && <Route path="/projects/:id" element={<ProjectDetail />} />}
          {superAdmin && <Route path="/projects/new" element={<ProjectForm />} />}
          {superAdmin && <Route path="/projects/:id/edit" element={<ProjectForm />} />}
          {role === "staff" && <Route path="/manage-tests" element={<ManageTests />} />}
          {superAdmin && <Route path="/manage-tests/:id" element={<TestEditor />} />}
          {role === "student" && <Route path="/my-projects" element={<MyProjects />} />}
          {role === "student" && <Route path="/my-projects/:id" element={<MyProject />} />}
          {role === "staff" && <Route path="/universities" element={<Universities />} />}
          {role === "staff" && <Route path="/tests/:id/key" element={<AnswerKey />} />}
          {superAdmin && <Route path="/catalog" element={<Catalog />} />}
          {role === "student" && <Route path="/tests" element={<MyTests />} />}
          {!manager && <Route path="/home" element={<StudentHome />} />}
          {!manager && <Route path="/profile" element={<Profile />} />}
          <Route path="*" element={<Navigate to={manager ? "/overview" : "/home"} replace />} />
        </Routes>
      </main>
    </div>
  );
}
