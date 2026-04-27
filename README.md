# NotebookLM RPA Worker MVP

This repository contains a Python FastAPI API server and a separate Python RPA worker for processing patient zip uploads through Google NotebookLM.

## Development

Install dependencies:

```bash
python -m pip install -e ".[dev]"
python -m playwright install chromium
```

Run tests:

```bash
pytest
```

Run API:

```bash
uvicorn app.api.main:create_app --factory --host 0.0.0.0 --port 8000
```

Run one worker:

```bash
python -m app.worker.main --worker-id worker-1 --display :21
```

## Runtime Requirements

- MongoDB server reachable through `MONGO_URI`.
- `/DATA/patients` writable, or set `DATA_ROOT` to another writable path for uploaded zip files, extracted inputs, and job results.
- `/DATA/notebooklm-workers` writable, or set `WORKER_ROOT` to another writable path for per-worker Chrome profiles and downloads.
- Playwright Chromium installed with `python -m playwright install chromium`.
- `vncserver` installed and on `PATH`.
- Google Chrome or Chromium installed.
- `xdotool` installed for hybrid desktop fallback.
- Network access from the worker to Google NotebookLM.

Copy `.env.example` to `.env` and adjust values for the host:

```bash
cp .env.example .env
```

## Manual Login Flow

1. Start the API server:

   ```bash
   uvicorn app.api.main:create_app --factory --host 0.0.0.0 --port 8000
   ```

2. Start a worker on its assigned display:

   ```bash
   python -m app.worker.main --worker-id worker-1 --display :21
   ```

   On hosts without a `python` command, use `python3` for the same module commands.

3. Submit a patient zip to `POST /jobs`.

4. Poll `GET /jobs/{job_id}`.

5. If the job status is `waiting_login`, connect to the worker VNC session, for example `localhost:5921` for display `:21`, and complete Google login manually. The worker profile is stored under `WORKER_ROOT/WORKER_ID/chrome-profile` unless `CHROME_USER_DATA_DIR` is set.

6. Resume the job:

   ```bash
   curl -X POST http://localhost:8000/jobs/JOB_ID/resume
   ```

7. Continue polling `GET /jobs/{job_id}` until the job reaches `completed` or `failed`.

## API Examples

Submit a job:

```bash
curl -F "file=@patient.zip;type=application/zip" http://localhost:8000/jobs
```

Check job status:

```bash
curl http://localhost:8000/jobs/JOB_ID
```

Resume a job after manual login:

```bash
curl -X POST http://localhost:8000/jobs/JOB_ID/resume
```

List workers:

```bash
curl http://localhost:8000/workers
```
