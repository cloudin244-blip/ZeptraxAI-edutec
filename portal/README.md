# ZeptraAI University Portal

React + Vite + Tailwind app served at `/portal/` on the Edutech site. Students, university
coordinators and Zeptrax staff use it for university onboarding, invitation links and profiles.

- **Backend:** `Zeptrax_AI_Edutech/zeptrax-learn-flow/api/_portal.py` (routes under `/api/portal/...`),
  using the same MongoDB and login tokens as the main site.
- **Roles:** Zeptrax staff (`admin` / `super_admin`) manage all universities; a `university_admin`
  sees only their own university; a `student` sees only their own profile. Roles, university,
  department and batch come from the invitation, never from the browser.
- **Links:** hash routing (`/portal/#/register?token=...`), so no Vercel rewrite rules are needed.

## Develop

```bash
cd portal
npm install
npm run dev          # http://localhost:5173/portal/ — proxies /api to the local Python server
```

Run the backend alongside it from the repo root: `python Zeptrax_AI_Edutech/serve_app.py` (port 8000).

## Deploy

```bash
npm run build        # writes to Zeptrax_AI_Edutech/zeptrax-learn-flow/portal/
```

Commit the build output: Vercel serves `zeptrax-learn-flow/` as-is, with no build step.
