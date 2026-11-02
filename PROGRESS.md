# Progress

Read at the start of every task; update after every change. Plan and decisions: `DEPLOYMENT.md`.

## Current state (2026-11-02)

- Codebase: FastAPI backend (`backend/app`) and a React **JSX** frontend (`frontend/`: Vite, Tailwind, shadcn/ui). 29 pytest tests and 19 Playwright browser tests pass.
- Built and browser-tested: login (staff email or candidate username); admin Exams list; **question bank** (list, filter, create/edit/archive MCQ, short,
  explained, coding and **SQL** questions; coding has a case table, reference-solution check and "Generate with AI", both working on the unsaved form; saving returns to the bank with the question at the top); **candidate flow** (home, camera check-in with
  MediaPipe face gate and consent, exam runner with section tabs, palette, mark for review, autosave, server timer, CodeMirror editor with Run/Submit,
  proctoring client, done page; SQL questions with an editor and the schema and sample data shown as tables; per-case loaders, Success/Failed labels and Time Limit Exceeded etc.; private cases as plain non-expandable blocks). Admin Results, Live monitor, exam setup and participant screens are still placeholders or missing.
- Run frontend: `cd frontend && npm install && npm run dev` (port 5173, proxies /api to 8000) or `npm run build` (backend serves `frontend/dist`).
  `SECRET_KEY` is required in `.env`. OpenAI is configured in `.env` (`LLM_PROVIDER=openai`, model `gpt-4o-mini`, key git-ignored); restart the backend after changing it.
- Browser tests: `cd frontend && npx playwright test` (starts its own API on :8001 with the throw-away `oap_test` database and Vite on :5174; add `RUN_AI=1` to include the
  real OpenAI call). Screenshots land in `frontend/test-results/screens/`. A dev-only hook `window.__faceCount` lets tests pin the face count (the fake camera is an animated picture).
- Theme: light/white only, black text, blue (`--primary`) for buttons and labels, green for success, red for warnings. Fonts (bundled, work offline): Inter body, Poppins headings, Montserrat brand.
- Dev logins after `python -m app.seed --reset`: staff as in `backend/data/seeded_accounts.txt`; candidates `rahul` / `sneha` / `amit`. All demo passwords are random per seed and live only in that file.
- Schema changes need a reseed (`python -m app.seed --reset`, wipes the `oap` database) until Alembic is added: `create_all` never alters existing tables.
- Local database: PostgreSQL 18, port 5433, local `postgres` account (credentials only in the git-ignored `.env`), databases `oap` (dev) and `oap_test` (tests). Config in repo-root `.env` (git-ignored).
- Run backend (from `backend/`): `.venv/Scripts/python -m app.seed` then `.venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload`.
  `backend/.venv` exists (git-ignored).
- Run tests: `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5433/oap_test python -m pytest tests -q` from `backend/`.
- Git: remote `origin` = github.com/Biswa-source45/Assesment-System-Globx, branch `main`. Commits are made locally; **the user pushes**. No Claude attribution in commits.
- graphify: kept local only (`.claude/`, `CLAUDE.local.md`, `.graphifyignore`, `graphify-out/` are git-ignored). Upgraded to 0.9.100 (0.9.66 segfaulted); graph built (817 nodes). Refresh with `graphify update .`.
- Tooling note: the PowerShell tool is broken in this environment; use Bash.

## Next

1. Admin: exam setup (title, schedule, duration, proctoring settings, sections, pick questions, publish), participants with printable credentials and reset/unban,
   then results/review (AI marks + override, proctoring timeline, snapshots) and the live monitor.
2. Docker judge container (the API still runs candidate code in-process: not safe for real candidates), compose, Caddy HTTPS, backups.
3. Check on a real laptop with a real face: MediaPipe false positives/negatives (`minDetectionConfidence` is 0.5 in `frontend/src/lib/faces.js`), fullscreen behaviour,
   camera permission prompt on the office HTTPS address.
4. Smaller gaps: "accept all AI marks" bulk action; camera-lost heartbeat; second-solution cross-check for generated cases; judge calls (`run_reference` too) must go
   through the judge container once it exists; old email-OTP/invite flow still in the backend; bundle is one 1.4 MB chunk (split later); rotate the OpenAI key.

## Log

### 2026-11-02 (white screen on SQL questions)
- User got a blank page opening a SQL question as a candidate: `SqlSamples` did `c.tables.map` and `tables` was undefined. Cause: the running backend predated the change that adds
  `tables` to the candidate payload (backend not restarted), and the frontend trusted the field. Fixed: `(c.tables ?? [])` in `CodeView.jsx`; and a new `ErrorBoundary.jsx` around the exam route
  so any render error shows "Something went wrong on this screen / Your answers are saved / Reload" instead of a blank page (answers autosave on the server).
- Tests: `exam.spec.js` rewrites the attempt state in flight (`tamperWithAttemptState`) to play out an older server (no `tables`) and a broken question (`options: null`); the first test was
  confirmed to fail without the fix. Rule of thumb: restart the backend after every pull/commit, because the frontend and backend change together.

### 2026-11-02 (SQL question authoring)
- User noticed the question bank had no SQL type (the one SQL question came from the seed) and wanted SQL authored as tables, not code. Added a "SQL" type with a table builder:
  `SqlBuilder.jsx` (tables with column names and types from dropdowns; datasets whose rows are typed into grids; sample or hidden, weight, duplicate) and `lib/sqlbuild.js`
  (turns the grids into CREATE TABLE and INSERT statements, validates names). The only SQL the author writes is the solution query.
- Expected output is computed, never typed: `_fill_sql_expected` runs the solution query on every dataset when the question is saved (a broken query is refused with "Dataset N: ..."),
  and `POST /questions/sql-preview` shows it in the editor before saving. `describe_tables` now returns column types, and `GET /questions/{id}` returns `sql_tables` so any
  existing SQL question (including the seeded one) opens as grids. Limitation: constraints such as PRIMARY KEY are not kept when a question is edited and saved in the builder.
- Engines for authored SQL questions are SQLite only. Tests: 29 pytest (+1), 17 Playwright (+3: author from scratch and reopen, bad names and broken query, seeded question round trip).

### 2026-11-02 (user's real-laptop test: fixes)
- User tested on a real laptop with a real face: face gate, warnings, incident counts, code Run/Submit all worked. Reported and fixed:
  1. Saving a question now returns to the question bank (new/updated question shown first). To allow that, `POST /questions/generate-cases` and
     `POST /questions/check-reference` are stateless (they take the form contents), replacing the per-question generate endpoint. The editor shows Success/Failed per case after the check.
  2. SQL questions had no editor in the exam. `CodeView.jsx` now handles coding and SQL (engine select, CodeMirror SQL). `describe_tables` (sandbox/sql.py) builds the
     schema and sample data per sample case; the candidate payload carries `tables`; the exam shows them as formatted tables plus the expected output.
  3. Test results: placeholder row with spinner per case while running (3 samples on Run, 3 samples + private on Submit), verdict codes shown as Success (green) / Failed,
     Time Limit Exceeded, Memory Limit Exceeded, Runtime Error, Compilation Error (red); private cases use the same block style but cannot be expanded.
     `public_view` now returns the real verdict code for private cases (never their input or output).
- Tests: 28 pytest (new: stateless generate/check, SQL tables, hidden verdicts without leaking data), 14 Playwright (new: redirect after save, loaders, labels, private blocks,
  TLE, SQL question end to end; new participants are made through the participants API). Specs renamed: `questions.spec.js`, `exam.spec.js`, `proctoring.spec.js`.
- Committed in logical commits (no push, no attribution).

### 2026-11-02 (question bank + candidate exam + theme)
- OpenAI key put in the git-ignored `.env` and verified through the app (JSON mode). Advised to rotate it because it was pasted in chat.
- graphify upgraded 0.9.66 -> 0.9.100 (fixed the segfault); graph built and `graphify-out/` stays local.
- Theme: first version had a navy sidebar; user asked for a fully white app, so surfaces are white, text black, blue only on buttons/labels, red/green for status.
- Frontend: question bank pages (`admin/Questions.jsx`, `admin/QuestionEditor.jsx`), candidate `CheckIn.jsx`, `Exam.jsx`, `questions.jsx`, `Done.jsx`;
  libs `proctor.js` (tab/fullscreen/paste/face-episode reporting, snapshots), `faces.js` (MediaPipe, wasm and model served from `/mediapipe`, copied by `postinstall`),
  `media.js`, `useCountdown.js`. Code editor is CodeMirror (not Monaco): lighter and offline-friendly.
- Backend: AI test-case generation now sends the sample inputs as format examples and `keep_same_shape` drops generated inputs whose line count differs
  (the model had invented multi-line inputs for a one-number problem); prompt forbids out-of-constraint inputs. 27 backend tests pass.
- Playwright (12 tests): login errors, question bank CRUD, MCQ validation message, explained and coding questions, AI generation (real OpenAI, `RUN_AI=1`),
  full practice exam with code Run/Submit, failed-sample reporting, face gate, 4th tab leave ends exam, sub-second leave ignored, 5th face incident bans and locks login.
- Bugs found by the tests and fixed: coding helpers stayed disabled after creating a question; camera preview covered the Save-and-next button (now in the page flow).

### 2026-11-02 (user check)
- User ran backend (port 8000) and frontend (port 5173) locally, logged in as super admin, and confirmed the admin shell and Exams list work. Next: Day 2 admin screens.

### 2026-11-02 (frontend rebuild, git, credentials)
- Deleted the TypeScript frontend (backup only in the session scratchpad). New `frontend/`: Vite + React + JSX, Tailwind v4, shadcn/ui (radix-nova, `"tsx": false`),
  react-router. Pages: `Login`, `admin/AdminLayout` (sidebar), `admin/Exams` (GET /tests), `candidate/Home` (GET /me/assignments). Build passes; 0 `.ts/.tsx` files.
- Credentials: seed now generates random staff/candidate passwords (written only to `backend/data/seeded_accounts.txt`); tests read them from the seed result;
  `SECRET_KEY` has no default; docs and `.env.example` use placeholders. Removed the stale `docs/ADMIN_MANUAL` (old `.bat` workflow, listed passwords).
- Git: `.gitignore` covers `.env`, `*.docx`, `graphify-out/`, `.claude/`, `CLAUDE.local.md`, `.graphifyignore`, `frontend/dist`, `frontend/node_modules`.
  The graphify section moved from `CLAUDE.md` to the git-ignored `CLAUDE.local.md`.

### 2026-11-02 (decision)
- Frontend is JavaScript + JSX, **not TypeScript** (user decision). The old `frontend/` is TSX and will be replaced, not extended.
  Dropped the "typed client generated from OpenAPI" idea since it only made sense with TypeScript.

### 2026-11-02 (Day 1, backend)
- Added `PROGRESS.md` and the project-memory rule in `CLAUDE.md`; wrote `DEPLOYMENT.md` (agreed plan).
- Participants: `User.username` column; `POST /tests/{id}/participants` generates username + 8-char password (shown once);
  `POST /assignments/{id}/password` resets it; `/auth/login` accepts username or email; candidates get a single session.
- Coding questions: removed the exact 3+3 rule (needs >= 1 sample + >= 1 hidden); case weights are scaled to the question's marks.
- Proctoring: tab/fullscreen leaves allowed = `tab_switch_limit` (default 3), the next one terminates (`force_submit`);
  face incidents (browser-reported `face_missing` >= `face_min_seconds` or `multi_face`) warn, the `face_limit`-th (default 5) terminates
  and bans (`assignment.status = banned`, cleared by the admin `reset` action). Server snapshot face checks are evidence only
  (payload `source=snapshot`), never double-counted. New `terminate_attempt` stops the attempt immediately so grading cannot run twice.
- AI: OpenAI JSON mode; default one-criterion rubric for explained answers that have a model answer; `ai_generate_inputs` +
  `POST /questions/{id}/generate-cases` (AI proposes inputs, reference solution produces expected outputs, invalid inputs dropped, nothing saved).
- Seed: candidates now have username/password; sample exam uses `tab_switch_limit: 3`.
- Tests: `backend/tests/test_exam_rules.py` (5 tests). 26/26 pass on PostgreSQL. A Windows `\r` leaking into generated expected outputs was found
  by the tests and fixed.
- Created `backend/.venv`. Reseeded the `oap` database (new column).
- Not done yet: any frontend work, Docker judge, compose/Caddy, Alembic.

### 2026-11-02
- Reviewed SRS v2.1 and the whole codebase. Findings: SQL sandbox could `ATTACH` the platform database; code sandbox is not isolated
  (candidate code can read server files); staff could read other organisations' submissions; no face detection without a Chrome flag;
  no migrations; grading pool of 2 threads can stall.
- Fixed: SQL authorizer denies ATTACH/DETACH/PRAGMA (`backend/app/sandbox/sql.py`); org check on `GET /submissions/{id}`
  (`backend/app/api/candidate.py`); tests in `backend/tests/test_security.py`.
- Created local PostgreSQL databases `oap`, `oap_test`; switched config to Postgres; added `psycopg[binary]` to `requirements.txt`; seeded demo data.
- Removed `.bat`/`.sh` scripts, `manage.py`, `scripts/bootstrap.py`; updated `README.md` and `.env.example`.
- Installed graphify into the repo (`CLAUDE.md` section, `.claude/settings.json` hooks, `.graphifyignore`).
- Agreed the product plan and deployment approach (office-only server, Docker, `assessment.globx.co.in` -> private IP, Caddy HTTPS);
  written to `DEPLOYMENT.md`.
- Decided: keep FastAPI; skip Redis/Celery/Alembic for now (Alembic before first production data); AI proposes test inputs only,
  expected outputs come from the reference solution.
