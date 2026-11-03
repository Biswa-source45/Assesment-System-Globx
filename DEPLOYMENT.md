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

The judge is a separate container because candidate code is untrusted (`Dockerfile.judge`, `docker-compose.yml`, built and proven on the development machine).
It has **no network at all**, a read-only filesystem, no `.env`, database client, secrets or pictures, every run is its own throw-away user, and the whole
container has process, memory and CPU limits. The api reaches it only through a Unix socket in the shared `judge-sock` volume (the api container joins group 3000).
`JUDGE_URL` empty = candidate code runs inside the api process: development only. With `ENVIRONMENT=production` and no judge, code runs are **refused** and the
admin screens show a red warning; the server never runs candidate code itself.
Safety is proven, not assumed: `docker compose run --rm --no-deps judge python -m app.sandbox.hostile` runs 39 attacks inside the real container (secret
theft, network, writes, root, kill, fork/thread/memory/disk/output bombs, compile-time tricks, SQL attacks) and must print `39 of 39 checks passed`.
Run it after every change to the judge or the compose file, and once on the office server before the first exam.
To check the api's side of the channel: `python -m app.sandbox.probe` inside the api container (group 3000, `JUDGE_URL` set) must print `AC`; the same command as any user outside group 3000 must print that the judge is not available.
Optional later upgrade: run the judge under gVisor (`runsc`) on a Linux host for a stronger wall against kernel exploits.

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

- Windows 10/11 with **Docker Desktop** (Linux containers, WSL2), confirmed; the judge image is Linux, so nothing depends on the host OS. Keep the repository checked out with LF line endings for `*.sh` (`.gitattributes` does this).
- **The server already runs another app (OneTrack, its own compose project):** Postgres on host port 5433, Redis 6379, backend 8081, Adminer 8080, its web front on port 80, and Watchtower (updates every container on the host every 60 s). Our stack is a **separate compose project (`oap`)**, touches nothing of OneTrack, and publishes **only port 443** (Caddy): db, api and judge have no host ports. The certificate is obtained by DNS challenge, so port 80 is not needed. Our services carry the label `com.centurylinklabs.watchtower.enable=false`, otherwise Watchtower would try to pull/restart our local images. Free disk and memory on the server still to be checked.
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
| `JUDGE_URL` | `unix:///run/judge/judge.sock` (the shared volume with the judge container) |
| `ENVIRONMENT` | `production` (turns on the refusal to run code without the judge) |
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
- [done] The exam's own dates decide who can take it (a candidate has no separate expiry); changing the closing time moves the end of people taking the exam now; the login sheet keeps every batch and can be had again for people who have not started
- [done] Evidence per exam: pictures or whole-exam video (deleted after 14 days by default), screen share, live view with messages and a private voice line (needs the `websockets` package, in `requirements.txt`; Caddy proxies the WebSocket by itself)
- [next] **Office check** with 2-3 laptops on the real Wi-Fi: open an exam with live view on, confirm camera and screen tiles appear, talk with headphones, note the CPU of the weakest laptop. If the tiles stay on "Connecting", the Wi-Fi blocks laptops from reaching each other: add a TURN server (coturn container) and put it in `LIVE_ICE_SERVERS`
- [planned] Disk: recorded video is about 150 MB per candidate per 90 minutes and is deleted after its exam's retention days; pictures are kept (about 3 to 12 MB per candidate). Keep `user-assets` on a volume with free space and back up the pictures with the database
- [done] SQL sandbox cannot open other databases; staff cannot read other organisations' submissions
- [done] Backend: participant credentials, coding case rules, proctoring rules (tab and face), AI JSON mode, test-case generator
- [done] Frontend scaffold (Vite, React JSX, shadcn/ui): login, admin shell, exams list, candidate home
- [done] Frontend screens: question bank, candidate check-in (camera + face gate), exam runner, proctoring client; Playwright suite (12 tests)
- [done] Frontend screens: exam setup, participants and credentials sheet, live monitor (extend, end exam, re-open, new password)
- [done] Frontend screens: results and review (declare, accept AI marks, review per candidate)
- [done] Docker judge container: image, locked-down compose service, per-run users, 39-attack drill passing (run it again on the office server)
- [planned] Docker compose, Caddy HTTPS, backups
- [planned] LAN test with 2-3 PCs

## 12. Open items

- Office server OS and its planned IP.
- GoDaddy API key test result (decides certificate option A or B).
- Confirm the domain spelling (`globx.co.in`).
- Confirm the coding language list.
- Retention period for snapshots and answers.
