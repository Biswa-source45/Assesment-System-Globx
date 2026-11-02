# Progress

Read at the start of every task; update after every change. Plan and decisions: `DEPLOYMENT.md`.

## Current state (2026-11-02)

- Codebase: FastAPI backend (`backend/app`) and a React **JSX** frontend (`frontend/`: Vite, Tailwind, shadcn/ui). 49 pytest tests and 44 Playwright browser tests pass.
- Built and browser-tested: login (staff email or candidate username); admin Exams list; **question bank** (list, filter, create/edit/archive MCQ, short,
  explained, coding and **SQL** questions; coding has a case table, reference-solution check and "Generate with AI", both working on the unsaved form; saving returns to the bank with the question at the top); **candidate flow** (home, camera check-in with
  MediaPipe face gate and consent, exam runner with section tabs, palette, mark for review, autosave, server timer, CodeMirror editor with Run/Submit,
  proctoring client, done page; SQL questions with an editor and the schema and sample data shown as tables; per-case loaders, Success/Failed labels and Time Limit Exceeded etc.; private cases as plain non-expandable blocks). **Exam setup** (create/edit an exam: schedule, time allowed, pass mark, shuffle, show-result, proctoring rules; sections with optional timers; pick questions from the bank; publish with a server-side list of what is missing; published exams are frozen) with **participants** (one login per name, one-time printable/CSV credentials sheet, list with extend time, end exam, re-open, new password, cancel) and a **live monitor** (polls every 5 s: status, time left, answered, window leaves, face issues, risk, last signal, latest camera snapshot, same actions). **Departments** (Technical, HR, Finance, Operations, General, or your own; each decides which question types authors can use; every question and exam belongs to one; the bank and the picker filter by it) and **auto populate** (per section: choose department, types, how many easy/medium/hard, optional tags; the server picks random approved questions that are not already in the exam and are publishable; you review, drop or pick again, then add; shortfalls are explained). All confirmations (archive, remove, unpublish, publish, delete department) use one in-app dialog, no browser boxes. The code editor is dark by default (VS Code themes, coloured syntax) with a Light/Dark switch inside the editor; the choice is remembered per browser (`lib/useEditorTheme.js`). **Build with AI** (exam, Questions tab): the app writes a prompt from the exam's department, title, description, instructions, time, schedule and rules plus how many questions of each type (only the types the department offers); the examiner gives it to ChatGPT/Claude with their own question set and uploads the JSON that comes back (or pastes it, for chats that show the JSON instead of giving a file); the server checks the whole file, the examiner reviews a preview, and Import creates the questions in the bank and new sections in the exam (all or nothing). **Edit a question from the exam** (pencil on each question in the Questions tab, draft or published): the same editor opens in a side panel and the change is the question's own, so the bank shows it too. While candidates are in the exam, the saved text, options, answer key and marks reach their screen within about 15 seconds (their answers, position and timers are kept, and they get a short notice). **Roles and users:** the sidebar and every write button follow the person's role (matrix in README); **Users** (Org Admin and Super Admin) lists staff and candidates, adds users, edits name/email/roles/status, changes passwords, unlocks locked accounts. Admin Results/review is still a placeholder.
- Run frontend: `cd frontend && npm install && npm run dev` (port 5173, proxies /api to 8000) or `npm run build` (backend serves `frontend/dist`).
  `SECRET_KEY` is required in `.env`. OpenAI is configured in `.env` (`LLM_PROVIDER=openai`, model `gpt-4o-mini`, key git-ignored); restart the backend after changing it.
- Browser tests: `cd frontend && npx playwright test` (starts its own API on :8001 with the throw-away `oap_test` database and Vite on :5174; add `RUN_AI=1` to include the
  real OpenAI call). Screenshots land in `frontend/test-results/screens/`. A dev-only hook `window.__faceCount` lets tests pin the face count (the fake camera is an animated picture).
- Theme: light/white only, black text, blue (`--primary`) for buttons and labels, green for success, red for warnings. Fonts (bundled, work offline): Inter body, Poppins headings, Montserrat brand.
- Dev logins after `python -m app.seed --reset`: staff as in `backend/data/seeded_accounts.txt`; candidates `rahul` / `sneha` / `amit`. All demo passwords are random per seed and live only in that file.
- Schema changes: Alembic. The app upgrades the database on start (an old database is adopted and keeps its data). After editing `models.py`: `cd backend && .venv/Scripts/alembic revision --autogenerate -m "what changed"`, check the file, commit it. `seed --reset` still wipes and rebuilds.
- Local database: PostgreSQL 18, port 5433, local `postgres` account (credentials only in the git-ignored `.env`), databases `oap` (dev) and `oap_test` (tests). Config in repo-root `.env` (git-ignored).
- Run backend (from `backend/`): `.venv/Scripts/python -m app.seed` then `.venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload`.
  `backend/.venv` exists (git-ignored).
- Run tests: `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5433/oap_test python -m pytest tests -q` from `backend/`.
- Git: remote `origin` = github.com/Biswa-source45/Assesment-System-Globx, branch `main`. Commits are made locally; **the user pushes**. No Claude attribution in commits.
- graphify: kept local only (`.claude/`, `CLAUDE.local.md`, `.graphifyignore`, `graphify-out/` are git-ignored). Upgraded to 0.9.100 (0.9.66 segfaulted); graph built (817 nodes). Refresh with `graphify update .`.
- Tooling note: the PowerShell tool is broken in this environment; use Bash.

## Next

1. Department-specific question patterns (the department design supports them; only the type list differs per department today): numeric answer with tolerance (Finance, Operations), situational judgement with scored options (HR), rating scales. Then admin results and review: candidate list with scores, per-answer view with AI marks and override ("accept all AI marks"), proctoring timeline and snapshots, export.
   The exam editor does not yet expose linked groups, random pools, per-question mark overrides or reordering (the API supports them).
2. Docker judge container (the API still runs candidate code in-process: not safe for real candidates), compose, Caddy HTTPS, backups.
3. Check on a real laptop with a real face: MediaPipe false positives/negatives (`minDetectionConfidence` is 0.5 in `frontend/src/lib/faces.js`), fullscreen behaviour,
   camera permission prompt on the office HTTPS address.
4. Smaller gaps: "accept all AI marks" bulk action; camera-lost heartbeat; second-solution cross-check for generated cases; judge calls (`run_reference` too) must go
   through the judge container once it exists; old email-OTP/invite flow still in the backend; bundle is one 1.4 MB chunk (split later); rotate the OpenAI key.

## Log

### 2026-11-02 (where exam images are stored)
- **What the images are:** one webcam picture every 15 s (exam setting) per candidate: the server counts faces in it and staff see it in the live monitor and the candidate report (`GET /snapshots/{id}`, staff only). The database table `proctor_snapshots` holds the attempt, time, face count, flags and the file path; the picture itself is a file.
- **Now stored in `user-assets/` at the project root** (git-ignored): `user-assets/proctor/<attempt id>/<time>_webcam_<id>.jpg`, answer files in `user-assets/uploads/<attempt id>/`. Setting `STORAGE_DIR` moves it. The database keeps the path **relative** to that folder (so the folder can move to Docker or another disk); older absolute rows still resolve; a path that escapes the folder is refused (404).
- **Cleaned:** the 69 folders (121 green fake-camera pictures) left by Playwright runs were deleted (they had no database row); the 3 real sessions (Rahul, Amit, Sneha, 97 pictures) were moved to `user-assets` and their database paths rewritten. Cause: the browser-test server wrote into the real storage folder while its database was wiped on every run. `e2e_server.py` now uses a throw-away folder in the system temp directory (`oap-e2e-storage`, emptied at each start); pytest already did.
- Open: no retention rule yet (pictures are never deleted); decide how long to keep them.
- Tests: 49 pytest (+1: stored under the folder by relative path, byte-identical, staff only, outside paths refused, old absolute rows still served). Browser monitor tests re-run: real folder untouched.
- Restart the backend after pulling this (new storage location).

### 2026-11-02 (roles, permissions and user management)
- **What existed:** roles in the database (`super_admin, org_admin, test_creator, recruiter, evaluator, candidate`), checked on every API route by `require(...)` (Super Admin always passes), but the same role lists were copied into four files and the screens showed every button to every staff role (a recruiter saw the question bank and a Save button that answered 403). A basic users API existed with no screen.
- **Now:** `ROLE_GROUPS` in `core/deps.py` is the one table (author, recruit, view, bank, evaluate, admin) used by all routers; `/auth/me` returns `can` (the same answers per person); the sidebar, route guards (`Need`), Exams, Questions, Departments, exam editor (details read-only, no publish), exam questions, participants and the participant actions menu follow it. The question bank is no longer readable by Recruiters (it holds answer keys).
- **Users screen** (`pages/admin/Users.jsx`, sidebar item for Org Admin and Super Admin): Staff and Candidates tabs with counts, search, role filter; add user (generated or typed password), edit name/email/roles/status, change password (generate, show/hide), Unlock; candidates show their username and exams and can get a new password or be disabled. Own account: roles and status are locked. No delete (disable keeps the history).
- **Server safeguards found missing and added (`staff.py`):** an Org Admin could reset the password of, disable or demote a Super Admin: now 403. Nobody can disable themselves or remove their own admin access (409). A new password or a disabled account revokes all refresh tokens (open sessions ended; before, a reset left the old session alive). An edit without a status no longer re-enables a disabled user. Unlock is explicit (`unlock`), no longer a side effect of any save. Staff roles only (a candidate role cannot be given here); candidates' roles cannot be changed. Email checked and unique.
- **Bug found:** with a backend that was not restarted, `/auth/me` has no `can` and the admin screen crashed to a blank page (`user.can.view` of undefined). The screen now says "The server needs a restart"; a browser test replays the old server.
- Tests: 48 pytest (+6: the whole role matrix over 11 actions x 5 roles + candidate + signed out, what `/auth/me` tells the browser, create/edit validation, sessions/disable/lock/unlock, who may change whom, candidates), 44 Playwright (+5: user management end to end, protections, candidates, what each role sees, old server). Two guards were switched off to prove the tests fail without them.
- Restart the backend after pulling this (the screens need `can` from `/auth/me`).

### 2026-11-02 (edit questions from the exam, live)
- **Where:** exam, Questions tab, pencil on each question -> side panel with the full question editor (`QuestionEditor` now takes `id`, `onSaved`, `embedded`; the bank page uses the `QuestionPage` wrapper). Works on draft and published exams (sections and the question list stay frozen when published; the question's content can be corrected). The panel says who will see the change (bank and other exams / everyone from now on / N candidates right now).
- **One question, one record:** the edit is the bank's question, no copy. **Live:** no WebSocket (the app already polls: the exam page asks the server for its clock every 15 s, on a LAN of a few candidates that is enough and survives reconnects). The clock answer now carries `content_version` (sum of the versions of the attempt's questions); when it moves, the page reloads the questions, keeps answers, position and section timers, and shows a notice naming what changed.
- **Server rules (`library.update_question`, `attempts.sync_live_attempts`):** text, options and answer key are read live. Marks and option order are frozen per attempt, so a save now pushes new marks (the exam's marks override still wins) and a new/removed option into attempts *in progress* and recomputes their `max_score`; finished attempts keep what they were graded with (a regrade is a separate feature, not built). The question's type cannot change once it is in an exam; a coding/SQL question of a published exam cannot be saved unless its reference solution still passes every case (422, nothing changed). `GET /tests/{id}` has `taking` (candidates in the exam now).
- **Bug found:** the editor never sent `group_id`, so saving a question of a linked set from the bank detached it from its set. Fixed, with a test proven to fail without the fix.
- Tests: 42 pytest (+1 live edit: text, new and removed option, marks, override wins, refused edits, finished attempts untouched), 39 Playwright (+3: edit in the exam draft and published, live change reaches a candidate who keeps their answer, linked-set save). One old locator fixed (a question row now has Edit and Remove buttons).
- Restart the backend after pulling this.

### 2026-11-02 (build an exam with AI-made JSON)
- **Paste as well as upload:** some AI chats show the JSON on screen and give no file, so step 2 also has a paste box and *Check pasted JSON*; both routes share one check function in `QuestionPack.jsx`. New browser test (36 Playwright).
- **Flow:** exam, Questions tab, *Build with AI*. Step 1: counts per question type -> `POST /tests/{id}/question-prompt` returns a prompt (exam details, counts, format rules, one valid example per type) to copy into ChatGPT or Claude together
  with the examiner's questions. Step 2: upload the JSON the AI returns -> `POST /tests/{id}/import-questions` with `dry_run` (default) returns every problem or a preview; with `dry_run: false` it creates the questions (bank, exam's department, approved)
  and appends one section per file section. All or nothing. Draft exams only. Code: `backend/app/api/exam_pack.py`, `frontend/src/pages/admin/QuestionPack.jsx`. No migration.
- **The server never trusts the AI's computed answers.** Coding: the file has the reference solution and test *inputs*; `run_reference` makes the expected outputs. SQL: expected results come from the reference query. Both go through the
  library's own `validate_question`, `_apply` and `_check_on_save`, so imported coding and SQL questions are validated and publishable. Expected values put into the file are ignored (test proves it).
- The examples shown to the AI are real data (`EXAMPLES`) and a test imports them, so the prompt cannot drift from what the server accepts. Fenced ```json blocks and chatter around the JSON are tolerated by the browser; trailing-comma slips are reported in plain words.
- **Found on the way:** the shared `Dialog` has `sm:max-w-sm`, so a plain `max-w-2xl` on a dialog never applied: the auto populate dialog and the question picker were narrower than intended. All three dialogs now use `sm:max-w-*`; tests check the width.
  Also, Postgres returns times in its own zone, so the prompt converts opens/closes to UTC explicitly before labelling them UTC.
- Limits: a coding reference solution from the file runs in the same in-process sandbox as the existing reference check (Docker judge still to come); the AI can still choose a wrong MCQ answer, so the preview lists every question; the same file imported twice makes duplicates in the bank.
- Tests: 41 pytest (+5: prompt, examples import and publish, every mistake listed and nothing created, expected outputs not from the file, department/draft/permission rules), 35 Playwright (+4: build and publish, mistakes then a fixed file, non-JSON files, HR has no coding).
- Restart the backend after pulling this (new routes).

### 2026-11-02 (editor theme switch)
- Code editor: Dark/Light switch inside the editor (VS Code dark default), remembered per browser; replaced the GitHub theme package. New browser test checks dark by default, white after the switch, coloured tokens in both, and that the choice survives a reload (31 Playwright tests).

### 2026-11-02 (departments, auto populate, migrations, dialogs, black editor)
- **Global, not only technical.** New `Department` model (`departments` table); `questions.department_id` and `tests.department_id`; the department's `question_types` decide what an author can create
  (HR/Finance/Operations/General offer MCQ single/multiple, short and explained; only Technical also offers coding and SQL). `GET/POST/PUT/DELETE /departments` (delete refused while used), department filters on the
  question list and the exam picker, `Departments` admin page. New organisations get the default departments (`services/departments.py`). The seed adds about 13 sample HR, Finance and Operations questions.
- **Alembic introduced** (it was promised for production and the schema now changes): `0001_baseline` (generated from the old models), `0002_departments` (hand-finished: names its constraints, files all existing
  questions and exams under Technical, creates the defaults per organisation). `db.migrate()` runs on start and from the seed; a database from before migrations is stamped 0001 first. Verified on real old-schema data,
  downgrade and re-upgrade; `test_migrations.py` covers adoption and fails if models and migrations disagree.
- **Auto populate** (`POST /tests/{id}/auto-populate`, `services/populate.py`, `AutoPopulate.jsx`): random questions by difficulty mix, department, types and tags; never a question already in the exam, a group child or an
  unvalidated coding/SQL question; preview only, nothing saved until the admin adds; shortfall reported. A fixed paper for everyone (order is still shuffled per candidate). Per-candidate random draws (pools) exist in
  the backend but were left out: totals break when marks differ.
- **Dialogs, not browser boxes:** `ConfirmDialog.jsx` (`useConfirm`) replaced the three native `confirm()` calls and now also guards removing a question, publishing and deleting a department. The shared `Dialog` scrolls
  when taller than the screen (the populate dialog buttons were cut off on a 720px screen; the test was proven to fail without the fix).
- **Code editor theme:** first read as "make it black"; the user clarified: a normal editor with coloured syntax like VS Code, black by default, switchable to white by anyone. Now `@uiw/codemirror-theme-vscode` (dark default, light option), toggle button in the editor toolbar, choice kept in localStorage. Dark+ is very dark grey (#1e1e1e), not pure black.
- Tests: 36 pytest (+4: departments, auto populate, two migration tests), 30 Playwright (+6: departments, department-driven types and filters, server refusal, auto populate x2, small-screen dialog).
- Restart the backend after pulling this: it upgrades the database itself.

### 2026-11-02 (exam setup, participants, live monitor, SQL colours)
- **SQL editor had no colours.** Root cause: for SQL questions `lang` is the engine key (`sqlite`), so the language lookup `EXT[lang]` matched nothing and no language was loaded. Now the language
  comes from the SQL dialect (`SQLite`/`PostgreSQL`/`MySQL`) in `CodeView.jsx`. Test asserts keywords get a colour in upper and lower case and was confirmed to fail on the old lookup.
- **Found while planning: no question authored in the new editors could be published.** `publish_errors` needs `config.validated` for coding/SQL, set only by the old validate endpoint. Now the server
  decides on every save (`_check_on_save` in `library.py`): SQL expected output is computed from the solution query; coding runs the reference solution on every case. A forged `validated` from the
  client is ignored. The redundant `POST /questions/{id}/validate` was removed.
- Backend: `GET /tests/{id}/monitor` (`reports.monitor_rows`), `GET /attempts/{id}/clock`, action `terminate` (end a running exam; reason required, 409 if not running), `username` in the candidates table,
  sections/questions of a published exam are frozen (409), unpublish refused while someone is taking the exam, generated participants no longer get their own `expires_at` (the exam window decides).
- Candidate exam page now follows the server clock (`syncClock`, every 15 s and on a 423): an admin's time extension reaches the countdown (before, the page would have submitted at the old
  deadline) and an admin ending the exam sends the candidate to the done page ("Exam ended") within seconds.
- Frontend: `ExamEditor` (tabs Details / Questions / Participants), `ExamDetails`, `ExamQuestions` (+ picker), `ExamParticipants`, shared `components/AssignmentActions`, `Monitor`, new `Exams` list,
  `lib/html.js` (shared text<->HTML helpers, were duplicated), `lib/labels.js`. Print styles for the logins sheet. `api()` got `raw` responses for snapshots (fetched with the login header, no token in URLs).
- Test-writing lessons: leftover candidates from other specs make global counts unreliable (assert non-zero, not exact); a face problem must visibly end before the next starts.
- Tests: 32 pytest (+3: save-time validation and publishing, monitor/clock/extend/end, frozen exams), 24 Playwright (+5: build and publish an exam then a candidate takes it, schedule/proctoring settings,
  monitor with extend and end and re-open, locked candidate, new password; plus SQL colour assertions).

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
