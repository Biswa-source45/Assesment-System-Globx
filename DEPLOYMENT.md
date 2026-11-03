# Deployment and project plan

Single source of truth for what we are building and how it will be deployed. Update it when a decision changes.
Status tags: **[done]** built and tested, **[next]** in progress, **[planned]** agreed but not built.

## 1. What we are building

An exam platform for hiring, used inside one office.

- One office server; 5-6 candidates per exam, all on the office Wi-Fi. No remote candidates.
- Admin logs in, creates an exam ahead of time, schedules it, adds questions and participants.
- Each participant gets a generated **username and password** for that exam (printable list). No email, no OTP.
- Question types: MCQ, explained (descriptive) answers with a model answer, coding (stdin/stdout programs).
- Coding: 1-2 sample cases visible to the candidate, 6-7 hidden cases (edge cases) used for marking.
- Written answers are marked by AI (OpenAI `gpt-4o-mini`) after the exam; admin can override any mark.
- The exam ends automatically at the cut-off time, or earlier if the candidate submits. Everything is stored with timestamps.

## 2. Decisions

| Topic | Decision |
|---|---|
| Backend | Keep FastAPI (Python). The scoring, sandbox and tests already exist. |
| Database | PostgreSQL. Local dev: the PostgreSQL 18 service on port **5433**, database `oap` (tests use `oap_test`). Production: PostgreSQL in Docker. |
| Frontend | React + **JavaScript (JSX, no TypeScript)** + Tailwind + **shadcn/ui** (JS mode), CodeMirror for code (lighter than Monaco, works offline). Light white theme, blue buttons, Inter/Poppins/Montserrat fonts. **[done]** |
| Hosting | Docker only on the office server. No other software installed there. |
| Address | `https://assessment.globx.co.in` pointing to the server's **private office IP**. Only reachable from the office network. (Confirm the domain spelling.) |
| Why HTTPS | Browsers block the camera on plain `http://192.168.x.x`. A real HTTPS address fixes it. `localhost` is exempt, so development needs nothing. |
| AI | OpenAI `gpt-4o-mini`. Key lives in the server's `.env`, never in git or chat. |
| Test cases | AI proposes test **inputs** only. Expected outputs always come from running the admin's reference solution. Admin reviews before use. |
| Languages | Default: Python, Java, JavaScript, C++ (C also works). Admin picks per question. **[confirm]** |

## 3. Production layout [planned]

```
Office server (Docker)
  caddy  - HTTPS on 443, serves the web app, forwards /api to the api
  api    - FastAPI; talks to the database and to OpenAI
  judge  - runs candidate code; own container, cannot reach the database or any secret
  db     - PostgreSQL, data on a Docker volume
Candidate PCs (Chrome/Edge) - the browser does camera and face detection
```

One domain serves both the website and the API, so there is no CORS and no separate backend address.

The judge is a separate container because candidate code is untrusted. It runs as an unprivileged user with a read-only filesystem,
CPU/memory/process limits, and sits on an internal network that has no route to the database. The api calls it over HTTP.
During development the judge runs as a local process (not safe for real candidates).

## 4. Domain and HTTPS [planned - Day 4]

1. **DNS (GoDaddy, one time):** add an A record for `globx.co.in`: name `assessment`, value = the server's office IP, TTL 600.
2. **Fixed IP:** reserve the server's address in the office router so it never changes.
3. **Certificate:** Let's Encrypt, proven with a DNS TXT record, so the server needs no internet exposure. Options, in order of preference:
   - **A. GoDaddy API** - the server writes the TXT record itself. GoDaddy restricted its DNS API for small accounts in 2024
     and the current rules are unclear: create a key at developer.godaddy.com and test it first.
   - **B. acme-dns** - one permanent CNAME `_acme-challenge.assessment` in GoDaddy pointing to a small helper service. Use if A is refused.
   - **C. Manual TXT record** every ~60-90 days. Avoid: a missed renewal breaks the camera on exam day.
4. Some routers refuse DNS answers that point to private IPs ("DNS rebinding protection"). If candidate PCs cannot open the page,
   add a local DNS entry on the router, or a hosts-file entry on the PCs.

## 5. Server prerequisites [planned]

- Docker Engine (Linux) or Docker Desktop with WSL2 (Windows). Confirm the OS.
- A reserved office IP; firewall allows inbound 443 (and 80 for the redirect) from the office network only.
- Outbound internet for the api container to reach OpenAI and Let's Encrypt.
- Time synced (NTP): exam deadlines are set by the server clock.

## 6. Configuration (`.env` on the server)

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://<user>:<password>@db:5432/oap` (use a strong password, not `postgres`) |
| `SECRET_KEY` | long random string, never reuse the dev one |
| `DEMO_MODE` | `false` |
| `PUBLIC_BASE_URL` | `https://assessment.globx.co.in` |
| `LLM_PROVIDER` / `LLM_OPENAI_MODEL` / `LLM_OPENAI_API_KEY` | `openai` / `gpt-4o-mini` / the key |
| `JUDGE_URL` | internal address of the judge container |
| GoDaddy key and secret | only if certificate option A is used |

Local development uses the repo-root `.env` (git-ignored). See `.env.example`.

## 7. Deploy steps [planned - commands confirmed when the compose file exists]

1. Copy the project to the server, create `.env` from section 6.
2. `docker compose up -d --build`.
3. Create the first admin account.
4. Open `https://assessment.globx.co.in` from a candidate PC and run the check-in page (camera, face, fullscreen).
5. Run one practice exam end to end with 2-3 PCs before the real one.

## 8. Exam-day runbook

Before: exam published, schedule correct, participants created and credentials printed, hidden test cases reviewed,
one candidate PC tested, server clock correct, OpenAI key working (admin page shows AI status).

During: admin watches the live monitor (who is in progress, violations, time left). A reset action re-opens a terminated candidate.

After: AI marks written answers; admin reviews and overrides; export results.

## 9. Proctoring rules

| Event | Action |
|---|---|
| Start button | Fullscreen on (browsers need a click for this) |
| Check-in | Start is disabled until exactly one face is visible |
| Tab switch / leaving fullscreen | Warning each time; **the 4th terminates the exam** (3 allowed) |
| No face, or several faces, for 3 s or more | Warning; **the 5th terminates the exam and bans the login** until an admin resets it |
| Copy / cut / paste / right-click / drag-drop | Blocked and logged |
| Time over | Server auto-submits (candidate may submit earlier) |

Every event is stored with a timestamp, plus when and why the exam ended. Browser proctoring can be bypassed
(for example help from a second device), so an invigilator in the room still matters.

## 10. Backups and updates [planned]

- Nightly database dump to a folder outside the Docker volume, kept for 30 days; also copy snapshots and uploads.
- Migrations: Alembic (`backend/migrations`). The app runs `alembic upgrade head` on every start; a database from before migrations is adopted as revision 0001 and keeps its data.
  After changing `app/models.py`, write a migration (`alembic revision --autogenerate`); a test fails if the models and migrations disagree. Back up before upgrading production.
- Never deploy during a live exam.
- Snapshots and answers are personal data; delete them after the retention period the company agrees.

## 11. Build checklist

- [done] Local PostgreSQL database and seed data; Alembic migrations (departments is revision 0002)
- [done] Departments (Technical, HR, Finance, Operations, General, or your own) decide question types; auto populate for exam sections; in-app confirmation dialogs
- [done] Build an exam from AI-made JSON: the app writes the prompt (exam details + counts per type), the examiner uploads the JSON, the server checks all of it and imports it (all or nothing)
- [done] Roles and user management: one permission table on the server, sent to the browser; Users screen (add, edit roles, change password, disable, unlock; candidates listed); sessions end on a new password or a disabled account
- [done] Real exam images live in `user-assets/` at the project root (`proctor/<attempt id>/`, `uploads/<attempt id>/`), paths stored relative in the database; in Docker mount `user-assets` as a volume and back it up with the database; decide a retention period (face pictures are personal data)
- [done] Results and review: per-exam calculation after the end time (AI only for text answers, once each), absent and ended-early candidates recorded, review screen with overrides, declare/withdraw, export
- [done] SQL sandbox cannot open other databases; staff cannot read other organisations' submissions
- [done] Backend: participant credentials, coding case rules, proctoring rules (tab and face), AI JSON mode, test-case generator
- [done] Frontend scaffold (Vite, React JSX, shadcn/ui): login, admin shell, exams list, candidate home
- [done] Frontend screens: question bank, candidate check-in (camera + face gate), exam runner, proctoring client; Playwright suite (12 tests)
- [done] Frontend screens: exam setup, participants and credentials sheet, live monitor (extend, end exam, re-open, new password)
- [next] Frontend screens: results and review
- [planned] Docker judge container
- [planned] Docker compose, Caddy HTTPS, backups
- [planned] LAN test with 2-3 PCs

## 12. Open items

- Office server OS and its planned IP.
- GoDaddy API key test result (decides certificate option A or B).
- Confirm the domain spelling (`globx.co.in`).
- Confirm the coding language list.
- Retention period for snapshots and answers.
