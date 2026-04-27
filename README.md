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

- MongoDB reachable at `MONGO_URI`.
- Writable `DATA_ROOT` for uploaded zip files, extracted inputs, and job results.
- Writable `WORKER_ROOT` for per-worker Chrome profiles and downloads.
- Playwright Chromium installed with `python -m playwright install chromium`.
- A VNC server command available as `vncserver`.
- Google Chrome available for the worker desktop environment when using the NotebookLM RPA workflow.
- Network access from the worker to Google NotebookLM.

Copy `.env.example` to `.env` and adjust values for the host:

```bash
cp .env.example .env
```

## Manual Login Flow

Start the API server:

```bash
uvicorn app.api.main:create_app --factory --host 0.0.0.0 --port 8000
```

Start a worker on its assigned display:

```bash
python -m app.worker.main --worker-id worker-1 --display :21
```

Connect to the worker VNC session, for example `localhost:5921` for display `:21`, and complete Google login in the browser profile for that worker. The worker profile is stored under `WORKER_ROOT/WORKER_ID/chrome-profile` unless `CHROME_USER_DATA_DIR` is set.

If a job enters `waiting_login`, complete login in the same VNC session, then resume the job through the API.

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
