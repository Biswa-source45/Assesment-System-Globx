# Deployment and project plan

Single source of truth for what we are building and how it will be deployed. Update it when a decision changes.
Status tags: **[done]** built and tested, **[next]** in progress, **[planned]** agreed but not built.

## 1. What we are building

An exam platform for hiring, used inside one office.

- One office server; 5-6 candidates per exam, all on the office Wi-Fi. No remote candidates.
- Admin logs in, creates an exam ahead of time, schedules it, adds questions and participants.
- Each participant gets a **username** (first name in lower case) and a **password** made from the name (`ash@globx472`) for that exam (printable list); an email can be added per line and also signs in. No OTP.
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
  caddy  - HTTPS on 443 (the only published port), forwards everything to the api
  api    - FastAPI; also serves the built web app; talks to the database, the judge and OpenAI
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

1. **DNS (Cloudflare, one time):** the domain is registered at GoDaddy but its DNS is managed at **Cloudflare** (GoDaddy's DNS tab says so; do not move the nameservers back, other records and mail depend on them). In Cloudflare, DNS > Records, add an **A** record for `globx.co.in`: name `assessment`, value = the server's office IP (192.168.1.50), **Proxy status: DNS only (grey cloud)**, TTL Auto. A proxied (orange) record cannot point to a private address.
2. **Fixed IP:** reserve the server's address in the office router so it never changes.
3. **Certificate:** Let's Encrypt, proven with a DNS TXT record that Caddy writes itself through the Cloudflare API (Caddy built with the `caddy-dns/cloudflare` module), so the server needs no internet exposure. The token is a Cloudflare **API token** limited to the `globx.co.in` zone with `Zone: Zone: Read` and `Zone: DNS: Edit`.
4. Some routers refuse DNS answers that point to private IPs ("DNS rebinding protection"). If candidate PCs cannot open the page,
   add a local DNS entry on the router, or a hosts-file entry on the PCs.

## 5. Server prerequisites [planned]

- Windows 10/11 with **Docker Desktop** (Linux containers, WSL2), confirmed; the judge image is Linux, so nothing depends on the host OS. Keep the repository checked out with LF line endings for `*.sh` (`.gitattributes` does this).
- **The server already runs another app (OneTrack, its own compose project):** Postgres on host port 5433, Redis 6379, backend 8081, Adminer 8080, its web front on port 80, and Watchtower (updates every container on the host every 60 s). Our stack is a **separate compose project (`oap`)**, touches nothing of OneTrack, and publishes **only port 443** (Caddy): db, api and judge have no host ports. The certificate is obtained by DNS challenge, so port 80 is not needed. Our services carry the label `com.centurylinklabs.watchtower.enable=false`, otherwise Watchtower would try to pull/restart our local images. Free disk and memory on the server still to be checked.
- **The server is an ordinary office PC (Windows 11, LAN cable, user `Globx-2`, Docker 29.7.2) that staff sometimes switch off at closing time, and power cuts happen.** It cannot be always on, so: exams are scheduled only while it is on and told to the office in advance; it must come back by itself after a power-on (BIOS "power on after power loss", Docker Desktop starts at sign-in, automatic sign-in with the screen locked, `restart: unless-stopped`); if it goes off during an exam, start it and use *Extend time* (answers are saved as they are typed); backups go to another disk or PC because this one can fail. OneTrack's Watchtower is in a restart loop (`Restarting (1)`), not our concern.
- **Measured on the server:** LAN IP **192.168.1.50** (Ethernet, gateway 192.168.1.1), **7.9 GB RAM with only 0.8 GB free while OneTrack runs**, 111 GB free disk, WSL2 works, Docker and Docker Desktop start by themselves after Windows starts. RAM is the tight resource: the judge is limited to 1.5 GB and 2 programs at once (drill still 39/39), and Docker's WSL2 memory is capped in `%UserProfile%\.wslconfig` so Windows keeps enough. The practice exam must measure real memory with the expected number of candidates.
- A reserved office IP; firewall allows inbound 443 (and 80 for the redirect) from the office network only.
- Outbound internet for the api container to reach OpenAI and Let's Encrypt.
- Time synced (NTP): exam deadlines are set by the server clock.

## 6. Configuration (`.env` on the server)

`deploy.ps1` writes it the first time (random passwords, only the user and administrators can read it); `docker-compose.yml` passes what the containers need (production mode, the judge socket, the storage folder). Nothing else has to be set by hand.

| Variable | Value |
|---|---|
| `DOMAIN` | `assessment.globx.co.in` |
| `DB_PASSWORD`, `SECRET_KEY` | long random strings, generated |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token for the `globx.co.in` zone (Zone:Read, DNS:Edit); used to get the certificate |
| `LLM_PROVIDER` / `LLM_OPENAI_MODEL` / `LLM_OPENAI_API_KEY` | `none` until an OpenAI key is added (then `openai` / `gpt-4o-mini` / the key) |
| `OAP_TAG` | optional: a commit id to run an earlier version |

Local development uses the repo-root `.env` (git-ignored). See `.env.example`; `server.env.example` lists the server's file.

## 7. Deploy steps (GitHub builds the images, the server pulls them)

**How it flows.** A push to `main` runs `.github/workflows/ci.yml`: backend tests (Postgres service), the judge's 39-attack drill, and only if both pass it builds `oap-api`, `oap-judge`, `oap-caddy` and publishes them to `ghcr.io/biswa-source45/` (tags `latest` and the commit). GitHub cannot reach the office PC, so the **server pulls**: you run `deploy.ps1` there when you choose (never in an exam). The server holds only `docker-compose.yml`, `deploy.ps1` and `.env`, no source code.

**Once, from your PC (browser):**
1. Push the code to GitHub. Watch the *Actions* tab: `tests`, `judge-drill` and `publish` must turn green. The repository stays private; the images are private too and belong to the repository.
2. GitHub, *Settings > Developer settings > Personal access tokens > Tokens (classic) > Generate new token*: tick only **`read:packages`**, no expiry (or a long one), name it `office-server`. Copy it once. This is the only GitHub key; it can read the images and nothing else.
3. Cloudflare (the account that manages `globx.co.in`), DNS > Records: add an **A** record, name `assessment`, value `192.168.1.50`, **Proxy status: DNS only (grey cloud)**.
4. Cloudflare, My Profile > API Tokens > Create Token > *Create Custom Token*: permissions **Zone / Zone / Read** and **Zone / DNS / Edit**, Zone Resources: Include, Specific zone, `globx.co.in`. Create it and copy the token once.

**Once, on the server (UltraViewer, then PowerShell as Administrator):**
5. Make a folder, for example `C:\oap`, and copy into it only `docker-compose.yml` and `deploy.ps1` from the repository. Docker Desktop must be running and no exam must be running.
6. `cd C:\oap`, then `docker login ghcr.io -u Biswa-source45` and paste the token from step 2 as the password.
7. `powershell -ExecutionPolicy Bypass -File .\deploy.ps1 -Seed -Drill`. It asks for the address (Enter keeps `assessment.globx.co.in`) and the Cloudflare token (hidden), writes `.env` with random passwords, opens port 443 for the office network, pulls the images, starts everything, creates the first accounts (the passwords are shown once: note them, sign in, make real users, change the passwords) and runs the drill, which must end with `39 of 39 checks passed`. The first start also gets the certificate through GoDaddy (`docker compose logs caddy`).
8. From another office computer open `https://assessment.globx.co.in`; check sign-in, the camera, screen sharing, the live view and a coding question.

**After the 3 November fixes, check on the real laptops:** (1) candidate presses **Accept and start exam**, keeps *Entire screen* selected in Chrome's box and presses Share; the exam opens in full screen; (2) the office PC's live view shows camera and screen and the badge says **Live**; if it says **Cannot connect**, send the text and a screenshot of `chrome://webrtc-internals` (the next step would be a TURN relay); (3) a blank submission shows **Did not attempt** in red, never Passed; an exam with pass mark 0 shows scores and "No pass mark set".

**Every later update (no exam running):** push to GitHub, wait for the green *publish*, then on the server `cd C:\oap; .\deploy.ps1`. Roll back: add `OAP_TAG=<commit id>` to `.env` and run it again (the commit ids are the image tags in GitHub, *Packages*). If `docker-compose.yml` itself changed in a release, copy the new file to the server first (rare). Data (database, pictures, certificate) lives in volumes and the `user-assets` folder and survives updates.

**Keys, in one table**

| Key | Made where | Used where | Kept in |
|---|---|---|---|
| GitHub token `read:packages` | GitHub settings | the server's one-time `docker login` | Docker's credential store on the server |
| Cloudflare API token (Zone:Read, DNS:Edit for the one zone) | Cloudflare dashboard | Caddy (certificate) | `.env` on the server only |
| Database password, `SECRET_KEY` | generated by `deploy.ps1` | the stack | `.env` on the server only |
| OpenAI key (optional) | OpenAI | the api | `.env` on the server only |
| GitHub Actions needs none of these | it uses its built-in token to publish | | |

**Not yet in the pipeline:** the Playwright browser suite (it needs fake camera and screen devices; it stays a local check before pushing), automatic updating on the server (deliberately off: a restart during an exam would drop everyone).

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
- [done] Docker compose with db, api, Caddy and the judge, run end to end locally with a test certificate; Playwright through HTTPS passes
- [done] GitHub Actions (`.github/workflows/ci.yml`): tests on Linux (Postgres service), judge drill, then publish the three images to ghcr.io; `deploy.ps1` pulls and starts them on the server; tried locally against a local registry in a simulated server folder
- [done] First real exam fixes (2026-11-07): written answers show in the review, strict multiple-answer marking, live view with the camera off, submit box without the coding line. **After deploying this, press Calculate again on the exam that already ran** (marks are redone; answers an admin marked by hand are kept)
- [done] Renamed to APTIVON by GLOBX with the new APTIVON logos and favicon (2026-11-10): after deploying, hard-refresh once (Ctrl+F5) to see the new tab icon; if `server.env` sets `SMTP_FROM` by hand, change its display name to APTIVON
- [planned] Backups; push to GitHub and see the workflow turn green; real certificate and DNS record on the office server
- [planned] LAN test with 2-3 PCs

## 12. Open items

- Office server OS and its planned IP.
- Cloudflare API token created and the certificate obtained on the server.
- Confirm the domain spelling (`globx.co.in`).
- Confirm the coding language list.
- Retention period for snapshots and answers.
