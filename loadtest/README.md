# Load tests (KAUTILYA)

Scripts that act as many candidates and examiners at once, ramp the load up until the system breaks, and write a PDF report. Open source tools only:
**Locust** (load), **psutil** and `docker stats` (machine health), **matplotlib** and **reportlab** (report), **Playwright** (real browsers and screenshots).
Nothing here is part of the server's Docker images. `.venv/`, `results/` and `reports/` are git-ignored; no password is ever saved in a file except the random,
test-only logins of the fake candidates (in `results/`, this computer only).

## What is in the folder
| File | Purpose |
|---|---|
| `setup_data.py` | Makes the test department, exam, questions, candidates and a temporary staff user through the application's own API. Everything is named with the run id (`LT-yyyymmdd-hhmm`). |
| `bigdata.py` | Large-data set by bulk SQL: a question bank, thousands of people, an exam with finished attempts. Run inside the api container. |
| `locustfile.py` | The virtual candidate (`Steady`), the storms (`LoginStorm`, `StartStorm`, `SubmitStorm`, `CodeBurst`), the examiner (`Staff`, `BigReader`). |
| `shape.py` | The staged ramp and its break rules. |
| `run_load.py` | Starts one scenario (Locust master and workers, sampler) and writes `results/<run>/<label>/`. |
| `monitor_host.ps1` | Run on the office PC: machine and container health, served read-only on the office network. |
| `snapshot_counts.py`, `compare_counts.py`, `cleanup.py` | Row counts before/after, and the cleanup that erases exactly one run. |
| `browsers.mjs` | Real browsers: candidates taking a small exam and the examiner's pages, with screenshots. |
| `report.py` | The PDF. |
| `local_server.py` | A throw-away copy of the server on this computer (own database `oap_load`). |

## One-time install (this computer)
```
cd loadtest
..\backend\.venv\Scripts\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## The break rules
A step **broke** when, for two 30-second checks in a row, more than 1% of requests failed, or the 95th-percentile time of saving an answer, the clock or the exam state was
above 2 s, or the health check failed, or a container restarted or was killed for memory. The run **stops to protect the PC** if its free memory falls under 400 MB.
Capacity = the highest step that stayed healthy. The report recommends 70% of it.

## Local run (this computer)
```
..\backend\.venv\Scripts\python.exe local_server.py start          (fresh database oap_load, server on :8001)
set LT_HOST=http://127.0.0.1:8001 & set LT_ADMIN_EMAIL=orgadmin@globx.co.in & set LT_ADMIN_PASSWORD=<printed in results\local_server.json>
.\.venv\Scripts\python.exe setup_data.py create --candidates 1500 --browser-exam 6 --run-id LT-local-1
.\.venv\Scripts\python.exe run_load.py ramp --run LT-local-1 --label ramp --steps 25,50,100,200,400,800,1200 --hold 240 --staff 5
.\.venv\Scripts\python.exe run_load.py login --run LT-local-1 --users 200 --spawn-rate 10
```
then `start`, `submit` (use `--offset` to take candidates no earlier scenario used), `code`, `big`.

## Office PC run
Nothing is installed on the office PC. The load comes from this computer over the office network (`--resolve` sends the site's name to the PC's address, so no hosts-file edit is needed and the HTTPS certificate still matches).

1. **On the office PC** (UltraViewer), PowerShell in the folder with `docker-compose.yml` (`D:\oap`):
   1. Back up the database first: `docker compose exec -T db pg_dump -U oap oap > backup-before-loadtest.sql`
   2. Copy `monitor_host.ps1`, `snapshot_counts.py` and `cleanup.py` into `D:\oap`.
   3. Start the monitor (as Administrator): `powershell -ExecutionPolicy Bypass -File .\monitor_host.ps1 -Token <a long random word>` and leave it open.
   4. Take the "before" counts: `Get-Content -Raw snapshot_counts.py | docker compose exec -T api python - > before.json`
2. **On this computer** (`loadtest` folder; the admin password is typed into the terminal's environment only):
   ```
   set LT_ADMIN_EMAIL=...  &  set LT_ADMIN_PASSWORD=...
   set LT_HOST=https://assessment.globx.co.in  &  set LT_RESOLVE=assessment.globx.co.in=192.168.1.50
   .\.venv\Scripts\python.exe setup_data.py create --candidates 600 --browser-exam 6 --run-id LT-office-1
   .\.venv\Scripts\python.exe run_load.py ramp --run LT-office-1 --label ramp --steps 10,25,50,100,150,200,300 --hold 180 --ramp 45 --staff 3 \
        --resolve assessment.globx.co.in=192.168.1.50 --status-url http://192.168.1.50:9100/status/<token>
   ```
   then the storms, the large data (`bigdata.py` runs on the PC: `Get-Content -Raw bigdata.py | docker compose exec -T -e RUN=LT-office-1 api python -`),
   the soak, and the real browsers (`node browsers.mjs candidates`, `node browsers.mjs staff`).
3. The gentle **internet-path** test: the same command without `--resolve`, up to 100 candidates.
4. **Cleanup** (office PC): `Get-Content -Raw cleanup.py | docker compose exec -T -e RUN=LT-office-1 api python -` counts what it would erase; add `-e YES=1` (and `-e FULL=1` in
   quiet hours) to erase. Take the "after" counts and compare: `python compare_counts.py before.json after.json`. Stop the monitor (Ctrl+C), delete the copied files and
   `backup-before-loadtest.sql` once you are satisfied, and **change the Super Admin password**.

## Report
```
.\.venv\Scripts\python.exe report.py --env "This computer (test copy)" --run LT-local-1 --env "Office PC" --run LT-office-1 --out reports\load-test-report.pdf
```
