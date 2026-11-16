# ZeptraAI University Portal

React + Vite + Tailwind app served at `/portal/` on the Edutech site. Students, university
coordinators and Zeptrax staff use it for university onboarding, invitation links and profiles.

- **Backend:** `Zeptrax_AI_Edutech/zeptrax-learn-flow/api/_portal.py` (routes under `/api/portal/...`),
  using the same MongoDB and login tokens as the main site.
- **Roles:** Zeptrax staff (`admin` / `super_admin`) manage all universities; a `university_admin`
  sees only their own university; a `student` sees only their own profile. Roles, university,
  department and batch come from the invitation, never from the browser.
- **Links:** hash routing (`/portal/#/register?token=...`), so no Vercel rewrite rules are needed.

## Signup links (how students join)

Staff and university admins open **Signup links → Create signup link** and pick a university (university
admins always get their own). That one link is shared with all the university's students on WhatsApp or
email (`/portal/#/join?code=...`); nothing is generated per student. Each student fills in name, email,
phone, registration/roll number, degree, branch, graduation year, Masters program and a password, joins
that university and lands on the test's start screen. There is no Google / social sign-in anywhere.

How many students can join is the university's **student limit** (Universities page); leave it empty for
no limit. A link can also fix the branch and batch, choose the test students are sent to (default: their
required test), expire, and be turned off. Backend: `api/_signup_links.py`.

## Proctoring (per test, on by default)

Before the timer starts, students pass a camera and screen check (camera on, detection model loaded,
no second monitor), then the test runs in full screen with the camera on.

- **Warnings** (limit set per test, default 3; at the limit the test is auto-submitted as malpractice):
  leaving the tab or window, leaving full screen, nobody on camera for ~10 s, camera turned off.
- **Immediate malpractice**: a mobile phone (~3 s) or a second person (~4.5 s) on camera, detected in
  the browser with TensorFlow.js COCO-SSD. A snapshot is stored as evidence (`ProctorEvidence`).
- Copy, paste, right-click and common shortcuts are blocked.
- The browser only reports events; `api/_proctoring.py` decides warnings and malpractice. Results show
  the flag, reason, event timeline and snapshots; staff can clear a wrong flag (the score then counts).
- Limits of a web page: it can't stop a student opening other apps, only detect and penalise leaving;
  the camera can't see a phone held out of view. A locked-down setup needs Safe Exam Browser or similar.
- The detection model (~5 MB) is fetched from Google's CDN (`storage.googleapis.com`) on the exam
  screen. If it can't load, the student can still start and "detection unavailable" is recorded.

## Running under heavy load

What the backend does so a whole university can sign up and take a test at once:

- **Indexes** for every per-request lookup (sessions, attempts, answers), built once per
  `INDEX_VERSION` instead of on every cold start. Bump `INDEX_VERSION` in `_db_router.py` when adding one.
- **Small connection pools** per serverless instance (`MONGO_MAX_POOL_SIZE`, default 20) so many
  instances don't exhaust the Atlas connection limit, with short timeouts.
- **Caching**: signed-in users (15 s), published tests and their locked questions, catalog lookups;
  `/api/catalog` and `/api/partner/universities` are cached by the CDN. Hashed assets are cached for a year.
- **Overload handling**: a database error returns `503` + `Retry-After`; the portal retries reads,
  answer saves, start/submit and signup with exponential backoff and jitter. A slow retry can't
  overwrite a newer answer.
- **Abuse limits**: sign-in attempts per email (`LOGIN_ATTEMPTS_PER_EMAIL`, default 20 per 15 min) and
  signups per IP (`SIGNUPS_PER_IP`, default 600 per 10 min; generous because a campus often shares one IP).

Before a large drive:

1. Use an Atlas tier sized for it (the free M0 tier allows 500 connections and throttles throughput;
   an M10+ dedicated cluster is the realistic minimum for thousands of simultaneous students).
2. Put the Vercel function region next to the Atlas cluster region (Vercel → Settings → Functions).
   A cross-continent hop adds ~200 ms to every request.
3. Load-test a staging deployment pointed at a separate database (set `MONGODB_DB`, e.g. `zeptrax_staging`):
   ```bash
   python scripts/load_test.py --base-url https://<staging-url> --code <link code> \
       --students 1000 --concurrency 200 --i-understand-this-creates-accounts
   ```

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
