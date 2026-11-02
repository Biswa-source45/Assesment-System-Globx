# Progress

Read at the start of every task; update after every change. Plan and decisions: `DEPLOYMENT.md`.

## Current state (2026-11-02)

- Codebase: FastAPI backend (`backend/app`) and a new React **JSX** frontend (`frontend/`, Vite + Tailwind + shadcn/ui). 26 pytest tests pass on PostgreSQL.
- Backend Day-1 work is done (credentials login, coding case rules, proctoring rules, AI JSON mode + test-case generator).
- Frontend scaffold is done: login (staff email or candidate username), auth + API client, admin shell with sidebar, Exams list, candidate home
  (lists assignments). Other admin pages are placeholders. Run: `cd frontend && npm install && npm run dev` (port 5173, proxies /api to 8000),
  or `npm run build` and the backend serves `frontend/dist`. `SECRET_KEY` is now required in `.env`.
- Dev logins after `python -m app.seed --reset`: staff as in `backend/data/seeded_accounts.txt`; candidates `rahul` / `sneha` / `amit`. All demo passwords are random per seed and live only in that file.
- Schema changes need a reseed (`python -m app.seed --reset`, wipes the `oap` database) until Alembic is added: `create_all` never alters existing tables.
- Local database: PostgreSQL 18, port 5433, local `postgres` account (credentials only in the git-ignored `.env`), databases `oap` (dev) and `oap_test` (tests). Config in repo-root `.env` (git-ignored).
- Run backend (from `backend/`): `.venv/Scripts/python -m app.seed` then `.venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload`.
  `backend/.venv` exists (git-ignored).
- Run tests: `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5433/oap_test python -m pytest tests -q` from `backend/`.
- Git: remote `origin` = github.com/Biswa-source45/Assesment-System-Globx, branch `main`. Commits are made locally; **the user pushes**. No Claude attribution in commits.
- graphify: kept local only (`.claude/`, `CLAUDE.local.md`, `.graphifyignore`, `graphify-out/` are git-ignored). Graph build crashes (segfault, graphify 0.9.66), so it is unusable for now.
- Tooling note: the PowerShell tool is broken in this environment; use Bash.

## Next

1. Admin screens: question bank (MCQ, explained, coding with case table + "Generate with AI"), exam setup (schedule, questions, proctoring
   settings, participants + printable credentials), results/review (AI marks + override), live monitor.
2. Candidate screens: login, check-in (camera + MediaPipe face gate), exam runner (Monaco), proctoring client sending `face_missing`
   (duration >= 3 s) / `multi_face` events and handling `warn` / `force_submit` / `ban` actions.
3. Docker judge container (the API currently runs candidate code in-process: not safe for real candidates), compose, Caddy HTTPS, backups.
4. Smaller gaps noted: "accept all AI marks" bulk action; camera-lost heartbeat; second-solution cross-check for generated cases;
   `run_reference` and judge calls must go through the judge container once it exists; old email-OTP/invite flow is still in the code (remove later).

## Log

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
