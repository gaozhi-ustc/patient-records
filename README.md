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
