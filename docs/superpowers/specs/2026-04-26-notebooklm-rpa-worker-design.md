# NotebookLM RPA Worker Design

**Date:** 2026-04-26

**Goal:** Build a single-desktop MVP that accepts patient zip files through a Web API, drives NotebookLM in a VNC Chrome desktop to create a new notebook, uploads extracted files, runs Deep Research, generates a Simplified Chinese slide deck, downloads results, and records all state in MongoDB.

**Scope:** The MVP uses one VNC desktop and one Chrome profile, with API and worker split into separate Python processes. The design keeps worker registration and atomic job claiming so the same model can later expand to multiple desktops and Chrome browsers.

**Primary Stack:** Python, FastAPI, MongoDB, Playwright, Chrome/Chromium, vncserver, pyautogui/xdotool fallback, local filesystem storage under `/DATA`.

**NotebookLM References:** Google documents NotebookLM source upload and Deep Research support in its help page for adding sources, and documents Slide Deck generation in its help page for slide decks:
- https://support.google.com/notebooklm/answer/16215270
- https://support.google.com/notebooklm/answer/16757456

---

## Confirmed Decisions

- Use option A scope: build a single desktop end-to-end MVP first, then extend to a multi-worker cluster.
- Use Python for API, orchestration, desktop control, and RPA worker code.
- Split API and worker into separate processes from the start.
- Use MongoDB server as the only state database.
- Use asynchronous job submission: `POST /jobs` returns a `job_id`; clients poll status.
- Use semi-automatic Google login: the system detects missing login, pauses the job, exposes VNC connection details, and resumes after a human logs in.
- Prefer Playwright `set_input_files` for upload. If blocked or unreliable, fall back to system file chooser automation.
- Preserve a later full visual fallback path using pyautogui/xdotool if Playwright causes risk checks or DOM automation becomes unusable.
- Before generating the PPT, expand the language/settings panel using the `>` button and select `简体中文`.
- Save both native NotebookLM exports when available and fallback audit artifacts such as Markdown/text, PDF, screenshots, and diagnostic logs.

## Architecture

The MVP has three runtime components.

### API Server

The `api-server` is a FastAPI process. It receives zip uploads, writes job records to MongoDB, exposes status and worker diagnostic endpoints, and never directly manipulates NotebookLM.

Responsibilities:
- Accept a zip file and create a job.
- Store the uploaded zip under `/DATA/patients/{job_id}/upload/`.
- Create MongoDB records for the job.
- Return immediately with `job_id`.
- Report status, notebook URL, artifacts, errors, and VNC login instructions.
- Allow a paused job to be resumed after manual login.

### RPA Worker

The `rpa-worker` is a separate Python process. It owns one VNC display, one Chrome profile, and one NotebookLM automation session.

Responsibilities:
- Start or reuse one `vncserver` display.
- Start Chrome with a stable `user-data-dir`.
- Register heartbeat and worker state in MongoDB.
- Atomically claim queued jobs.
- Extract the uploaded zip into `/DATA/patients/{job_id}/input/`.
- Drive NotebookLM through the required RPA flow.
- Download or capture results into `/DATA/patients/{job_id}/result/`.
- Write events, artifacts, screenshots, and final status to MongoDB.

### MongoDB

MongoDB is the system of record for job state, worker state, events, and artifacts. The data model is intentionally compatible with later multi-worker deployment.

## Filesystem Layout

For each job:

```text
/DATA/patients/{job_id}/
  upload/
    original.zip
  input/
    extracted patient files
  result/
    research.md
    research.pdf
    slide_deck.pdf
    native_downloads/
    screenshots/
    diagnostics/
```

For workers:

```text
/DATA/notebooklm-workers/{worker_id}/
  chrome-profile/
  downloads/
  screenshots/
  logs/
```

Zip extraction must prevent zip-slip. Extracted paths must stay inside `/DATA/patients/{job_id}/input/`.

## MongoDB Collections

### `jobs`

```json
{
  "_id": "job_id",
  "original_filename": "patient.zip",
  "zip_path": "/DATA/patients/{job_id}/upload/patient.zip",
  "input_dir": "/DATA/patients/{job_id}/input",
  "result_dir": "/DATA/patients/{job_id}/result",
  "status": "queued",
  "worker_id": null,
  "display": null,
  "notebook_id": null,
  "notebook_url": null,
  "created_at": "2026-04-26T00:00:00Z",
  "updated_at": "2026-04-26T00:00:00Z",
  "started_at": null,
  "finished_at": null,
  "error": null,
  "retry_count": 0,
  "last_step": null,
  "login_required": false
}
```

Indexes:
- `status, created_at` for queue polling.
- `worker_id, status` for worker diagnostics.
- `notebook_id` for lookup by NotebookLM notebook.

### `workers`

```json
{
  "_id": "worker-1",
  "display": ":21",
  "vnc_port": 5921,
  "chrome_user_data_dir": "/DATA/notebooklm-workers/worker-1/chrome-profile",
  "status": "idle",
  "current_job_id": null,
  "login_status": "unknown",
  "heartbeat_at": "2026-04-26T00:00:00Z",
  "last_error": null,
  "automation_mode": "playwright"
}
```

Indexes:
- `status, heartbeat_at` for scheduler and health checks.

### `artifacts`

```json
{
  "_id": "artifact_id",
  "job_id": "job_id",
  "kind": "research_markdown",
  "path": "/DATA/patients/{job_id}/result/research.md",
  "sha256": "hex_digest",
  "created_at": "2026-04-26T00:00:00Z"
}
```

Allowed `kind` values:
- `research_markdown`
- `research_text`
- `research_pdf`
- `slide_pdf`
- `native_download`
- `screenshot`
- `diagnostic_log`

### `events`

```json
{
  "_id": "event_id",
  "job_id": "job_id",
  "worker_id": "worker-1",
  "step": "upload_sources",
  "level": "info",
  "message": "Uploaded 17 files",
  "screenshot_path": null,
  "created_at": "2026-04-26T00:00:00Z"
}
```

Indexes:
- `job_id, created_at` for timeline display.
- `level, created_at` for failure diagnostics.

## Job Status Machine

Allowed job statuses:

- `queued`: API accepted the zip and the job is waiting for a worker.
- `running`: a worker claimed the job and is preparing the desktop/session.
- `waiting_login`: NotebookLM is not logged in; a human must log in through VNC.
- `uploading_sources`: the worker is uploading extracted source files.
- `researching`: Deep Research has been submitted and is running.
- `generating_ppt`: slide deck generation has started after selecting `简体中文`.
- `downloading_results`: both outputs are complete enough to save/export.
- `completed`: result artifacts and `notebook_id` have been written to MongoDB.
- `failed`: execution failed; the job contains the error, last step, and diagnostics.
- `cancelled`: reserved for future cancellation support.

Important transitions:
- `queued -> running`: worker claims the job with an atomic MongoDB update.
- `running -> waiting_login`: login check fails.
- `waiting_login -> queued`: API resume request or automatic login detection releases the job for continuation.
- `running -> uploading_sources -> researching -> generating_ppt -> downloading_results -> completed`: normal path.
- Any active state can move to `failed` on unrecoverable timeout, UI mismatch, upload failure, or download failure.

## API Design

### `POST /jobs`

Request:
- `multipart/form-data`
- field `file`: zip file

Behavior:
- Validate file extension and content type.
- Create `job_id`.
- Save the zip to `/DATA/patients/{job_id}/upload/`.
- Insert a `jobs` document with `status: queued`.

Response:

```json
{
  "job_id": "job_id",
  "status": "queued"
}
```

### `GET /jobs/{job_id}`

Response includes:
- `job_id`
- `status`
- `worker_id`
- `display`
- `vnc_port`
- `notebook_id`
- `notebook_url`
- `last_step`
- `error`
- `artifacts`
- recent `events`

If status is `waiting_login`, the response includes a clear instruction that a human must connect to the listed VNC desktop and log in to Google manually.

### `POST /jobs/{job_id}/resume`

Behavior:
- If the job is `waiting_login`, move it back to `queued` and clear `login_required`.
- If the job is already active or completed, return the current state without changing it.

### `GET /workers`

Response includes each worker's:
- `worker_id`
- `display`
- `vnc_port`
- `status`
- `current_job_id`
- `login_status`
- `heartbeat_at`
- `automation_mode`
- `last_error`

## Worker Flow

### Startup

1. Load configuration.
2. Ensure required directories exist.
3. Start or verify `vncserver` for the configured display.
4. Start Chrome with the configured profile.
5. Register or update the worker document in MongoDB.
6. Enter the polling loop.

### Job Claiming

The worker claims one job with a MongoDB atomic update:

- Match: `status: queued`
- Sort: oldest `created_at`
- Set: `status: running`, `worker_id`, `display`, `started_at`, `updated_at`

This prevents duplicate processing after the system grows to multiple workers.

### Zip Extraction

1. Create `/DATA/patients/{job_id}/input/`.
2. Inspect every zip member before extraction.
3. Reject absolute paths, parent directory traversal, and unsupported special files.
4. Extract allowed files.
5. Build a list of uploadable files.
6. Record an event with file count and skipped files.

### Login Detection

The worker opens `https://notebooklm.google.com`.

If NotebookLM redirects to Google login, account chooser, CAPTCHA, or another manual challenge:
- Set job status to `waiting_login`.
- Set worker `login_status` to `required`.
- Record VNC connection details in the job response path.
- Pause this job without failing it.

After the human logs in:
- The user calls `POST /jobs/{job_id}/resume`, or the worker detects the logged-in NotebookLM homepage and resumes automatically.
- The system does not store Google account passwords.

## NotebookLM RPA Flow

All UI labels and selectors are configurable because NotebookLM UI text and layout can vary by language, account, and rollout.

### Create a New Notebook

1. Navigate to NotebookLM.
2. If currently inside an old notebook, click the top middle `新建笔记本`.
3. If on the homepage or empty state, click the top right `新建`.
4. Press `Escape` to close any initial upload/source popup.
5. Wait until the URL is stable.
6. Read `page.url`; if needed, also copy the address bar URL through desktop automation.
7. Extract `notebook_id` from the URL.
8. Persist `notebook_id` and `notebook_url` immediately.

### Upload Sources

1. Click `添加来源`.
2. Click `上传`.
3. Preferred path: use Playwright `set_input_files` with every supported file extracted under `/DATA/patients/{job_id}/input/`.
4. If `set_input_files` fails or NotebookLM blocks the path, use system file chooser automation through pyautogui/xdotool.
5. Wait for upload completion indicators.
6. Record uploaded count, failed count, and screenshots.

Supported files follow NotebookLM's documented upload support, including PDF, Microsoft Word, text, Markdown, common image formats, audio formats, and other supported source types.

### Start Deep Research

1. Click the left-side `在网络中搜索新来源` area.
2. Click `Fast Research`.
3. Select `Deep Research`.
4. Enter:

```text
请帮我梳理成 门诊记录单格式，不带来源 编号（即去掉末尾数字）的纯净版门诊记录单
```

5. Press `Enter`.
6. Set job status to `researching`.
7. Poll until the research report is visible and generation is complete.

### Generate Slide Deck

1. Open the right-side Studio panel area.
2. Click `演示文稿`.
3. Before generation, click the `>` button to expand settings or language options.
4. Select output language `简体中文`.
5. Start slide deck generation.
6. Set job status to `generating_ppt`.
7. Poll until the slide deck is complete.

### Save Results

1. Prefer NotebookLM native download or export buttons when available.
2. Save the research document as Markdown/text by extracting visible content.
3. Save the research view as PDF when possible.
4. Save the slide deck as PDF or NotebookLM's available export format.
5. Save screenshots for key final states.
6. Compute SHA-256 for saved files.
7. Insert `artifacts` records.
8. Mark job `completed`.

## Automation Modes

The worker uses an automation adapter so the implementation can switch modes without rewriting the state machine.

### Mode 1: `playwright`

Primary MVP mode.

Uses:
- Browser navigation.
- Accessible labels and text selectors.
- DOM events.
- `set_input_files`.
- Playwright downloads.
- Screenshots and DOM text snapshots for diagnostics.

### Mode 2: `hybrid`

Fallback for file upload or dialogs.

Uses Playwright for most page actions, but uses pyautogui/xdotool for:
- Native file chooser windows.
- Address bar copy.
- Keyboard shortcuts.
- Dialogs that Playwright cannot access.

### Mode 3: `visual`

Reserved fallback if Playwright triggers risk checks, automation detection, or persistent UI incompatibility.

Uses only desktop-level control:
- pyautogui mouse and keyboard actions.
- xdotool window focus, typing, and hotkeys.
- screenshot capture from the VNC desktop.
- image/template matching for stable icons and buttons.
- OCR for Chinese and English labels when coordinates are not stable.

The visual mode keeps the same high-level steps and MongoDB state transitions. It is slower and more sensitive to screen resolution, so it should use a fixed VNC resolution, fixed browser zoom, stored screenshots, and explicit per-step verification.

Mode switching rules:
- Start in `playwright`.
- Use `hybrid` when one isolated operation fails due to native desktop boundaries.
- Use `visual` when Playwright repeatedly causes risk checks, cannot access NotebookLM UI reliably, or the user explicitly configures `AUTOMATION_MODE=visual`.
- Record the selected mode in `workers.automation_mode` and job events.

## Timeouts

Defaults are configurable:

- NotebookLM page load: 2 minutes.
- Source upload: 20 minutes plus file-count adjustment.
- Deep Research: 45 minutes.
- Slide deck generation: 30 minutes.
- Result download/export: 10 minutes.

On timeout:
- Save screenshot and diagnostic logs.
- Write a clear `events` record.
- Mark job `failed` unless the condition is a login requirement, which moves to `waiting_login`.

## Deployment

API:

```bash
uvicorn app.api.main:app --host 0.0.0.0 --port 8000
```

Worker:

```bash
python -m app.worker.main --worker-id worker-1 --display :21
```

Required system dependencies:
- MongoDB server.
- `vncserver`.
- Chrome or Chromium.
- Playwright Python package and installed browser support.
- `xdotool`.
- pyautogui dependencies.
- Writable `/DATA/patients`.
- Writable `/DATA/notebooklm-workers`.

Configuration values:
- `MONGO_URI`
- `DATABASE_NAME`
- `DATA_ROOT=/DATA/patients`
- `WORKER_ROOT=/DATA/notebooklm-workers`
- `WORKER_ID=worker-1`
- `DISPLAY=:21`
- `VNC_PORT=5921`
- `CHROME_USER_DATA_DIR`
- `AUTOMATION_MODE=playwright`
- timeout values
- supported upload file extensions

## Cluster Extension

After the MVP works end to end:

1. Start multiple VNC displays.
2. Start one worker process per display.
3. Give every worker a unique Chrome profile.
4. Let every worker register heartbeat in `workers`.
5. Let workers atomically claim jobs from MongoDB.
6. Add health checks for stale worker heartbeat and abandoned jobs.
7. Add scheduler policy for idle workers, per-account rate limits, and NotebookLM daily quota protection.
8. Add an API endpoint to pause or drain a worker before maintenance.

The API does not need to know which worker will handle a job. It writes `queued`; workers compete safely through MongoDB atomic updates.

## Security and Privacy

- Do not store Google passwords or recovery credentials.
- Store only Chrome profile session data on disk.
- Keep each job's input and output isolated by `job_id`.
- Validate zip contents before extraction.
- Avoid logging patient file contents.
- Store only file paths, hashes, status, and diagnostic metadata in MongoDB.
- Screenshots may contain patient data; save them inside the job result/diagnostic directory and treat them as sensitive artifacts.

## Failure Handling

Recoverable conditions:
- Missing Google login: `waiting_login`.
- Native file chooser incompatibility: switch to `hybrid`.
- Playwright risk check or persistent selector failure: switch to `visual` if configured or mark failed with diagnostics.
- Temporary page load failure: retry within the same job up to the configured retry count.

Unrecoverable conditions:
- Invalid zip.
- No uploadable files after extraction.
- NotebookLM upload rejection for all files.
- Deep Research timeout after retries.
- Slide deck generation timeout after retries.
- Download/export failure with no fallback capture possible.

## Verification Strategy

MVP verification should cover:

- API accepts a zip and creates a MongoDB job.
- Worker claims exactly one queued job.
- Zip extraction blocks traversal paths.
- Missing login moves the job to `waiting_login`.
- Resume moves a waiting job back to executable state.
- Notebook creation captures and stores `notebook_id`.
- Upload selects all extracted supported files.
- Deep Research prompt is submitted exactly as configured.
- Slide deck generation selects `简体中文` before starting.
- Result artifacts are saved and hashed.
- Failure creates screenshot and event records.

## Out of Scope for MVP

- Automatic Google credential login.
- Multiple simultaneous desktops.
- Full scheduler UI.
- Automatic deletion or retention policy for patient data.
- Full pure visual implementation before Playwright has been tested.
- Clinical validation of NotebookLM output quality.

The pure visual mode is intentionally preserved in the design as a fallback path, but MVP implementation should first prove the Playwright and hybrid modes end to end.
