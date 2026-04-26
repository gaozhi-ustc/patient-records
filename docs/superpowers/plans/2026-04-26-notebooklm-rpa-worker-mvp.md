# NotebookLM RPA Worker MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the single-desktop NotebookLM automation MVP described in `docs/superpowers/specs/2026-04-26-notebooklm-rpa-worker-design.md`.

**Architecture:** A FastAPI API process accepts zip uploads and writes job state to MongoDB. A separate Python worker process owns one VNC display and Chrome profile, atomically claims queued jobs, extracts patient files, drives NotebookLM through an RPA adapter, saves result artifacts, and updates MongoDB. The worker starts in Playwright mode, can use pyautogui/xdotool for hybrid file-dialog operations, and preserves a pure visual adapter boundary for risk-check fallback.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic Settings, PyMongo, Playwright sync API, pytest, mongomock, pyautogui, xdotool, vncserver, Chrome/Chromium.

---

## File Structure

Create these files:

- `pyproject.toml`: package metadata, dependencies, pytest config.
- `README.md`: local setup and run commands.
- `app/__init__.py`: package marker.
- `app/config.py`: environment-driven settings.
- `app/domain.py`: enums, constants, Pydantic request/response/document models.
- `app/storage.py`: job directory creation, safe zip extraction, file hashing.
- `app/db/__init__.py`: database package marker.
- `app/db/mongo.py`: Mongo client creation and index setup.
- `app/db/repositories.py`: job, worker, artifact, and event persistence methods.
- `app/api/__init__.py`: API package marker.
- `app/api/main.py`: FastAPI app factory and endpoints.
- `app/worker/__init__.py`: worker package marker.
- `app/worker/desktop.py`: VNC and Chrome process orchestration.
- `app/worker/runner.py`: worker polling loop and job state machine.
- `app/worker/main.py`: worker CLI entrypoint.
- `app/worker/rpa/__init__.py`: RPA package marker.
- `app/worker/rpa/base.py`: RPA protocol, result models, and exceptions.
- `app/worker/rpa/playwright_adapter.py`: Playwright and hybrid NotebookLM automation.
- `app/worker/rpa/visual_adapter.py`: pure visual adapter boundary for pyautogui/xdotool fallback.
- `tests/conftest.py`: shared fixtures.
- `tests/test_imports.py`: package import smoke test.
- `tests/test_config_domain.py`: settings and domain model tests.
- `tests/test_storage.py`: safe extraction and hashing tests.
- `tests/test_repositories.py`: Mongo repository tests with mongomock.
- `tests/test_api.py`: API endpoint tests.
- `tests/test_desktop.py`: VNC and Chrome command construction tests.
- `tests/test_rpa_workflow.py`: RPA adapter orchestration tests with fake adapters.
- `tests/test_rpa_playwright_adapter.py`: Playwright helper and filtering tests.
- `tests/test_worker_runner.py`: worker state-machine tests.
- `tests/test_worker_main.py`: worker CLI parser tests.
- `tests/test_integration_fake_worker.py`: API-to-worker fake RPA integration test.

## Data Contracts

Use these status strings exactly:

```python
queued
running
waiting_login
uploading_sources
researching
generating_ppt
downloading_results
completed
failed
cancelled
```

Use this Deep Research prompt exactly:

```text
请帮我梳理成 门诊记录单格式，不带来源 编号（即去掉末尾数字）的纯净版门诊记录单
```

Use these artifact kinds exactly:

```python
research_markdown
research_text
research_pdf
slide_pdf
native_download
screenshot
diagnostic_log
```

---

### Task 1: Python Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `app/__init__.py`
- Create: `app/db/__init__.py`
- Create: `app/api/__init__.py`
- Create: `app/worker/__init__.py`
- Create: `app/worker/rpa/__init__.py`
- Test: `tests/test_imports.py`

- [ ] **Step 1: Write the failing import smoke test**

Create `tests/test_imports.py`:

```python
def test_core_packages_import() -> None:
    import app
    import app.api
    import app.db
    import app.worker
    import app.worker.rpa

    assert app is not None
    assert app.api is not None
    assert app.db is not None
    assert app.worker is not None
    assert app.worker.rpa is not None
```

- [ ] **Step 2: Run the smoke test and verify it fails**

Run:

```bash
pytest tests/test_imports.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app'`.

- [ ] **Step 3: Create package scaffold and project metadata**

Create `pyproject.toml`:

```toml
[project]
name = "patient-records-notebooklm-rpa"
version = "0.1.0"
description = "NotebookLM RPA worker MVP for patient record processing"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115.0",
  "uvicorn[standard]>=0.30.0",
  "pydantic>=2.8.0",
  "pydantic-settings>=2.4.0",
  "pymongo>=4.8.0",
  "python-multipart>=0.0.9",
  "playwright>=1.46.0",
  "pyautogui>=0.9.54",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.3.0",
  "pytest-cov>=5.0.0",
  "mongomock>=4.1.2",
  "httpx>=0.27.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
addopts = "-q"
```

Create `README.md`:

````markdown
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
````

Create empty package marker files:

```text
app/__init__.py
app/db/__init__.py
app/api/__init__.py
app/worker/__init__.py
app/worker/rpa/__init__.py
```

- [ ] **Step 4: Run the smoke test and verify it passes**

Run:

```bash
pytest tests/test_imports.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md app tests/test_imports.py
git commit -m "chore: scaffold notebooklm rpa project"
```

---

### Task 2: Configuration and Domain Models

**Files:**
- Create: `app/config.py`
- Create: `app/domain.py`
- Test: `tests/test_config_domain.py`

- [ ] **Step 1: Write failing tests for settings and domain values**

Create `tests/test_config_domain.py`:

```python
from pathlib import Path

from app.config import Settings
from app.domain import ArtifactKind, JobStatus, deep_research_prompt


def test_settings_defaults_are_mvp_safe() -> None:
    settings = Settings(mongo_uri="mongodb://localhost:27017")

    assert settings.database_name == "patient_records"
    assert settings.data_root == Path("/DATA/patients")
    assert settings.worker_root == Path("/DATA/notebooklm-workers")
    assert settings.worker_id == "worker-1"
    assert settings.display == ":21"
    assert settings.vnc_port == 5921
    assert settings.automation_mode == "playwright"


def test_domain_status_and_artifact_values_are_stable() -> None:
    assert JobStatus.QUEUED.value == "queued"
    assert JobStatus.WAITING_LOGIN.value == "waiting_login"
    assert JobStatus.GENERATING_PPT.value == "generating_ppt"
    assert ArtifactKind.RESEARCH_MARKDOWN.value == "research_markdown"
    assert ArtifactKind.SLIDE_PDF.value == "slide_pdf"


def test_deep_research_prompt_is_exact() -> None:
    assert deep_research_prompt() == "请帮我梳理成 门诊记录单格式，不带来源 编号（即去掉末尾数字）的纯净版门诊记录单"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
pytest tests/test_config_domain.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `app.config`.

- [ ] **Step 3: Implement settings and domain models**

Create `app/config.py`:

```python
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    mongo_uri: str = Field("mongodb://localhost:27017", alias="MONGO_URI")
    database_name: str = Field("patient_records", alias="DATABASE_NAME")
    data_root: Path = Field(Path("/DATA/patients"), alias="DATA_ROOT")
    worker_root: Path = Field(Path("/DATA/notebooklm-workers"), alias="WORKER_ROOT")
    worker_id: str = Field("worker-1", alias="WORKER_ID")
    display: str = Field(":21", alias="DISPLAY")
    vnc_port: int = Field(5921, alias="VNC_PORT")
    chrome_user_data_dir: Path | None = Field(None, alias="CHROME_USER_DATA_DIR")
    automation_mode: str = Field("playwright", alias="AUTOMATION_MODE")
    notebooklm_url: str = "https://notebooklm.google.com"
    page_load_timeout_seconds: int = 120
    upload_timeout_seconds: int = 1200
    research_timeout_seconds: int = 2700
    ppt_timeout_seconds: int = 1800
    download_timeout_seconds: int = 600
    poll_interval_seconds: float = 2.0
    supported_upload_extensions: tuple[str, ...] = (
        ".pdf",
        ".docx",
        ".doc",
        ".txt",
        ".md",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
        ".mp3",
        ".wav",
    )

    @property
    def resolved_chrome_user_data_dir(self) -> Path:
        if self.chrome_user_data_dir is not None:
            return self.chrome_user_data_dir
        return self.worker_root / self.worker_id / "chrome-profile"
```

Create `app/domain.py`:

```python
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_LOGIN = "waiting_login"
    UPLOADING_SOURCES = "uploading_sources"
    RESEARCHING = "researching"
    GENERATING_PPT = "generating_ppt"
    DOWNLOADING_RESULTS = "downloading_results"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkerStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    WAITING_LOGIN = "waiting_login"
    OFFLINE = "offline"
    FAILED = "failed"


class ArtifactKind(str, Enum):
    RESEARCH_MARKDOWN = "research_markdown"
    RESEARCH_TEXT = "research_text"
    RESEARCH_PDF = "research_pdf"
    SLIDE_PDF = "slide_pdf"
    NATIVE_DOWNLOAD = "native_download"
    SCREENSHOT = "screenshot"
    DIAGNOSTIC_LOG = "diagnostic_log"


class EventLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def deep_research_prompt() -> str:
    return "请帮我梳理成 门诊记录单格式，不带来源 编号（即去掉末尾数字）的纯净版门诊记录单"


class JobDocument(BaseModel):
    id: str = Field(alias="_id")
    original_filename: str
    zip_path: str
    input_dir: str
    result_dir: str
    status: JobStatus
    worker_id: str | None = None
    display: str | None = None
    notebook_id: str | None = None
    notebook_url: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    retry_count: int = 0
    last_step: str | None = None
    login_required: bool = False

    model_config = {"populate_by_name": True}


class WorkerDocument(BaseModel):
    id: str = Field(alias="_id")
    display: str
    vnc_port: int
    chrome_user_data_dir: str
    status: WorkerStatus
    current_job_id: str | None = None
    login_status: str = "unknown"
    heartbeat_at: datetime
    last_error: str | None = None
    automation_mode: str = "playwright"

    model_config = {"populate_by_name": True}


class ArtifactDocument(BaseModel):
    id: str = Field(alias="_id")
    job_id: str
    kind: ArtifactKind
    path: str
    sha256: str
    created_at: datetime

    model_config = {"populate_by_name": True}


class EventDocument(BaseModel):
    id: str = Field(alias="_id")
    job_id: str
    worker_id: str
    step: str
    level: EventLevel
    message: str
    screenshot_path: str | None = None
    created_at: datetime

    model_config = {"populate_by_name": True}


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    worker_id: str | None = None
    display: str | None = None
    vnc_port: int | None = None
    notebook_id: str | None = None
    notebook_url: str | None = None
    last_step: str | None = None
    error: str | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
pytest tests/test_config_domain.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/domain.py tests/test_config_domain.py
git commit -m "feat: add configuration and domain models"
```

---

### Task 3: Safe Storage and Zip Extraction

**Files:**
- Create: `app/storage.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write failing storage tests**

Create `tests/test_storage.py`:

```python
import hashlib
import zipfile
from pathlib import Path

import pytest

from app.storage import JobPaths, StorageService, UnsafeZipError


def write_zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def test_job_paths_are_created_under_data_root(tmp_path: Path) -> None:
    service = StorageService(data_root=tmp_path)

    paths = service.prepare_job_paths("job-1", "patient.zip")

    assert paths.upload_dir == tmp_path / "job-1" / "upload"
    assert paths.input_dir == tmp_path / "job-1" / "input"
    assert paths.result_dir == tmp_path / "job-1" / "result"
    assert paths.zip_path == tmp_path / "job-1" / "upload" / "patient.zip"
    assert paths.upload_dir.is_dir()
    assert paths.input_dir.is_dir()
    assert paths.result_dir.is_dir()


def test_extract_zip_rejects_parent_directory_traversal(tmp_path: Path) -> None:
    zip_path = tmp_path / "bad.zip"
    write_zip(zip_path, {"../escape.txt": b"bad"})
    service = StorageService(data_root=tmp_path)
    paths = JobPaths(
        job_dir=tmp_path / "job-1",
        upload_dir=tmp_path / "job-1" / "upload",
        input_dir=tmp_path / "job-1" / "input",
        result_dir=tmp_path / "job-1" / "result",
        zip_path=zip_path,
    )
    paths.input_dir.mkdir(parents=True)

    with pytest.raises(UnsafeZipError, match="unsafe zip member"):
        service.extract_zip(paths)


def test_extract_zip_returns_supported_files_only(tmp_path: Path) -> None:
    zip_path = tmp_path / "patient.zip"
    write_zip(
        zip_path,
        {
            "a.pdf": b"pdf",
            "nested/b.txt": b"text",
            "skip.exe": b"binary",
        },
    )
    service = StorageService(data_root=tmp_path, supported_extensions=(".pdf", ".txt"))
    paths = JobPaths(
        job_dir=tmp_path / "job-1",
        upload_dir=tmp_path / "job-1" / "upload",
        input_dir=tmp_path / "job-1" / "input",
        result_dir=tmp_path / "job-1" / "result",
        zip_path=zip_path,
    )
    paths.input_dir.mkdir(parents=True)

    extracted = service.extract_zip(paths)

    assert [item.relative_to(paths.input_dir).as_posix() for item in extracted] == [
        "a.pdf",
        "nested/b.txt",
    ]


def test_sha256_file(tmp_path: Path) -> None:
    file_path = tmp_path / "result.md"
    file_path.write_bytes(b"abc")

    assert StorageService.sha256_file(file_path) == hashlib.sha256(b"abc").hexdigest()
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
pytest tests/test_storage.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `app.storage`.

- [ ] **Step 3: Implement storage service**

Create `app/storage.py`:

```python
import hashlib
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class UnsafeZipError(ValueError):
    pass


@dataclass(frozen=True)
class JobPaths:
    job_dir: Path
    upload_dir: Path
    input_dir: Path
    result_dir: Path
    zip_path: Path


class StorageService:
    def __init__(
        self,
        data_root: Path,
        supported_extensions: tuple[str, ...] = (
            ".pdf",
            ".docx",
            ".doc",
            ".txt",
            ".md",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".gif",
            ".bmp",
            ".tif",
            ".tiff",
            ".mp3",
            ".wav",
        ),
    ) -> None:
        self.data_root = data_root
        self.supported_extensions = tuple(ext.lower() for ext in supported_extensions)

    def prepare_job_paths(self, job_id: str, original_filename: str) -> JobPaths:
        safe_filename = Path(original_filename).name
        job_dir = self.data_root / job_id
        upload_dir = job_dir / "upload"
        input_dir = job_dir / "input"
        result_dir = job_dir / "result"
        for directory in (upload_dir, input_dir, result_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return JobPaths(
            job_dir=job_dir,
            upload_dir=upload_dir,
            input_dir=input_dir,
            result_dir=result_dir,
            zip_path=upload_dir / safe_filename,
        )

    def save_upload(self, source_file, paths: JobPaths) -> None:
        with paths.zip_path.open("wb") as output:
            shutil.copyfileobj(source_file, output)

    def extract_zip(self, paths: JobPaths) -> list[Path]:
        extracted: list[Path] = []
        with zipfile.ZipFile(paths.zip_path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                target = self._safe_target(paths.input_dir, member.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if target.suffix.lower() in self.supported_extensions:
                    extracted.append(target)
        return sorted(extracted)

    def _safe_target(self, input_dir: Path, member_name: str) -> Path:
        normalized = PurePosixPath(member_name.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise UnsafeZipError(f"unsafe zip member: {member_name}")
        target = (input_dir / Path(*normalized.parts)).resolve()
        input_root = input_dir.resolve()
        if input_root != target and input_root not in target.parents:
            raise UnsafeZipError(f"unsafe zip member: {member_name}")
        return target

    @staticmethod
    def sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as input_file:
            for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
```

- [ ] **Step 4: Run storage tests**

Run:

```bash
pytest tests/test_storage.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/storage.py tests/test_storage.py
git commit -m "feat: add secure job storage"
```

---

### Task 4: MongoDB Repository Layer

**Files:**
- Create: `app/db/mongo.py`
- Create: `app/db/repositories.py`
- Test: `tests/conftest.py`
- Test: `tests/test_repositories.py`

- [ ] **Step 1: Write failing repository tests**

Create `tests/conftest.py`:

```python
from collections.abc import Iterator

import mongomock
import pytest


@pytest.fixture
def mongo_db() -> Iterator:
    client = mongomock.MongoClient()
    yield client["patient_records_test"]
    client.close()
```

Create `tests/test_repositories.py`:

```python
from pathlib import Path

from app.db.repositories import MongoRepository
from app.domain import ArtifactKind, JobStatus, WorkerStatus


def test_create_and_get_job(mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    repo.create_job(
        job_id="job-1",
        original_filename="patient.zip",
        zip_path=Path("/DATA/patients/job-1/upload/patient.zip"),
        input_dir=Path("/DATA/patients/job-1/input"),
        result_dir=Path("/DATA/patients/job-1/result"),
    )

    job = repo.get_job("job-1")

    assert job is not None
    assert job["_id"] == "job-1"
    assert job["status"] == JobStatus.QUEUED.value
    assert job["original_filename"] == "patient.zip"


def test_claim_oldest_queued_job_is_atomic(mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    repo.create_job("job-1", "a.zip", Path("/z1"), Path("/i1"), Path("/r1"))
    repo.create_job("job-2", "b.zip", Path("/z2"), Path("/i2"), Path("/r2"))

    claimed = repo.claim_next_job(worker_id="worker-1", display=":21")
    second_claim = repo.claim_next_job(worker_id="worker-2", display=":22")

    assert claimed is not None
    assert claimed["_id"] == "job-1"
    assert second_claim is not None
    assert second_claim["_id"] == "job-2"
    assert repo.get_job("job-1")["status"] == JobStatus.RUNNING.value


def test_resume_waiting_login_job(mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    repo.create_job("job-1", "a.zip", Path("/z"), Path("/i"), Path("/r"))
    repo.set_job_waiting_login("job-1", "worker-1", ":21", "login required")

    resumed = repo.resume_waiting_login_job("job-1")

    assert resumed["status"] == JobStatus.QUEUED.value
    assert resumed["login_required"] is False
    assert resumed["error"] is None


def test_worker_event_and_artifact_records(mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    repo.upsert_worker(
        worker_id="worker-1",
        display=":21",
        vnc_port=5921,
        chrome_user_data_dir=Path("/profiles/worker-1"),
        status=WorkerStatus.IDLE,
        automation_mode="playwright",
    )
    repo.add_event("job-1", "worker-1", "upload_sources", "info", "Uploaded 2 files")
    repo.add_artifact("job-1", ArtifactKind.RESEARCH_MARKDOWN, Path("/result/research.md"), "abc")

    assert repo.list_workers()[0]["_id"] == "worker-1"
    assert repo.list_events("job-1")[0]["message"] == "Uploaded 2 files"
    assert repo.list_artifacts("job-1")[0]["kind"] == ArtifactKind.RESEARCH_MARKDOWN.value
```

- [ ] **Step 2: Run repository tests and verify they fail**

Run:

```bash
pytest tests/test_repositories.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `app.db.repositories`.

- [ ] **Step 3: Implement Mongo client and repository**

Create `app/db/mongo.py`:

```python
from pymongo import ASCENDING, MongoClient

from app.config import Settings


def create_mongo_database(settings: Settings):
    client = MongoClient(settings.mongo_uri)
    return client[settings.database_name]


def ensure_indexes(db) -> None:
    db.jobs.create_index([("status", ASCENDING), ("created_at", ASCENDING)])
    db.jobs.create_index([("worker_id", ASCENDING), ("status", ASCENDING)])
    db.jobs.create_index([("notebook_id", ASCENDING)])
    db.workers.create_index([("status", ASCENDING), ("heartbeat_at", ASCENDING)])
    db.artifacts.create_index([("job_id", ASCENDING), ("created_at", ASCENDING)])
    db.events.create_index([("job_id", ASCENDING), ("created_at", ASCENDING)])
    db.events.create_index([("level", ASCENDING), ("created_at", ASCENDING)])
```

Create `app/db/repositories.py`:

```python
from pathlib import Path
from uuid import uuid4

from pymongo import ASCENDING, ReturnDocument

from app.domain import ArtifactKind, EventLevel, JobStatus, WorkerStatus, utc_now


class MongoRepository:
    def __init__(self, db) -> None:
        self.db = db

    def create_indexes(self) -> None:
        self.db.jobs.create_index([("status", ASCENDING), ("created_at", ASCENDING)])
        self.db.jobs.create_index([("worker_id", ASCENDING), ("status", ASCENDING)])
        self.db.jobs.create_index([("notebook_id", ASCENDING)])
        self.db.workers.create_index([("status", ASCENDING), ("heartbeat_at", ASCENDING)])
        self.db.artifacts.create_index([("job_id", ASCENDING), ("created_at", ASCENDING)])
        self.db.events.create_index([("job_id", ASCENDING), ("created_at", ASCENDING)])

    def create_job(
        self,
        job_id: str,
        original_filename: str,
        zip_path: Path,
        input_dir: Path,
        result_dir: Path,
    ) -> dict:
        now = utc_now()
        document = {
            "_id": job_id,
            "original_filename": original_filename,
            "zip_path": str(zip_path),
            "input_dir": str(input_dir),
            "result_dir": str(result_dir),
            "status": JobStatus.QUEUED.value,
            "worker_id": None,
            "display": None,
            "notebook_id": None,
            "notebook_url": None,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
            "error": None,
            "retry_count": 0,
            "last_step": None,
            "login_required": False,
        }
        self.db.jobs.insert_one(document)
        return document

    def get_job(self, job_id: str) -> dict | None:
        return self.db.jobs.find_one({"_id": job_id})

    def claim_next_job(self, worker_id: str, display: str) -> dict | None:
        now = utc_now()
        return self.db.jobs.find_one_and_update(
            {"status": JobStatus.QUEUED.value},
            {
                "$set": {
                    "status": JobStatus.RUNNING.value,
                    "worker_id": worker_id,
                    "display": display,
                    "started_at": now,
                    "updated_at": now,
                    "last_step": "claimed",
                }
            },
            sort=[("created_at", ASCENDING)],
            return_document=ReturnDocument.AFTER,
        )

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        last_step: str,
        error: str | None = None,
        extra: dict | None = None,
    ) -> dict | None:
        values = {"status": status.value, "last_step": last_step, "updated_at": utc_now(), "error": error}
        if status == JobStatus.COMPLETED:
            values["finished_at"] = utc_now()
        if extra:
            values.update(extra)
        return self.db.jobs.find_one_and_update(
            {"_id": job_id},
            {"$set": values},
            return_document=ReturnDocument.AFTER,
        )

    def set_job_waiting_login(self, job_id: str, worker_id: str, display: str, message: str) -> dict | None:
        return self.update_job_status(
            job_id,
            JobStatus.WAITING_LOGIN,
            "waiting_login",
            error=message,
            extra={"worker_id": worker_id, "display": display, "login_required": True},
        )

    def resume_waiting_login_job(self, job_id: str) -> dict | None:
        return self.db.jobs.find_one_and_update(
            {"_id": job_id, "status": JobStatus.WAITING_LOGIN.value},
            {
                "$set": {
                    "status": JobStatus.QUEUED.value,
                    "login_required": False,
                    "error": None,
                    "updated_at": utc_now(),
                    "last_step": "resume_requested",
                }
            },
            return_document=ReturnDocument.AFTER,
        )

    def upsert_worker(
        self,
        worker_id: str,
        display: str,
        vnc_port: int,
        chrome_user_data_dir: Path,
        status: WorkerStatus,
        automation_mode: str,
        current_job_id: str | None = None,
        login_status: str = "unknown",
        last_error: str | None = None,
    ) -> dict:
        values = {
            "display": display,
            "vnc_port": vnc_port,
            "chrome_user_data_dir": str(chrome_user_data_dir),
            "status": status.value,
            "current_job_id": current_job_id,
            "login_status": login_status,
            "heartbeat_at": utc_now(),
            "last_error": last_error,
            "automation_mode": automation_mode,
        }
        return self.db.workers.find_one_and_update(
            {"_id": worker_id},
            {"$set": values},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

    def list_workers(self) -> list[dict]:
        return list(self.db.workers.find().sort("heartbeat_at", ASCENDING))

    def add_event(
        self,
        job_id: str,
        worker_id: str,
        step: str,
        level: str,
        message: str,
        screenshot_path: str | None = None,
    ) -> dict:
        document = {
            "_id": str(uuid4()),
            "job_id": job_id,
            "worker_id": worker_id,
            "step": step,
            "level": EventLevel(level).value,
            "message": message,
            "screenshot_path": screenshot_path,
            "created_at": utc_now(),
        }
        self.db.events.insert_one(document)
        return document

    def list_events(self, job_id: str, limit: int = 50) -> list[dict]:
        return list(self.db.events.find({"job_id": job_id}).sort("created_at", ASCENDING).limit(limit))

    def add_artifact(self, job_id: str, kind: ArtifactKind, path: Path, sha256: str) -> dict:
        document = {
            "_id": str(uuid4()),
            "job_id": job_id,
            "kind": kind.value,
            "path": str(path),
            "sha256": sha256,
            "created_at": utc_now(),
        }
        self.db.artifacts.insert_one(document)
        return document

    def list_artifacts(self, job_id: str) -> list[dict]:
        return list(self.db.artifacts.find({"job_id": job_id}).sort("created_at", ASCENDING))
```

- [ ] **Step 4: Run repository tests**

Run:

```bash
pytest tests/test_repositories.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/db tests/conftest.py tests/test_repositories.py
git commit -m "feat: add mongodb repository layer"
```

---

### Task 5: FastAPI Job API

**Files:**
- Create: `app/api/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_api.py`:

```python
import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.db.repositories import MongoRepository
from app.domain import WorkerStatus
from app.storage import StorageService


def make_zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("record.txt", "hello")
    return buffer.getvalue()


def test_post_jobs_creates_queued_job(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    app = create_app(repository=repo, storage=StorageService(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/jobs",
        files={"file": ("patient.zip", make_zip_bytes(), "application/zip")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert repo.get_job(payload["job_id"])["original_filename"] == "patient.zip"


def test_get_job_returns_status_artifacts_and_events(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    repo.create_job("job-1", "patient.zip", Path("/z"), Path("/i"), Path("/r"))
    repo.add_event("job-1", "worker-1", "claimed", "info", "Claimed job")
    app = create_app(repository=repo, storage=StorageService(tmp_path))
    client = TestClient(app)

    response = client.get("/jobs/job-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == "job-1"
    assert payload["status"] == "queued"
    assert payload["events"][0]["message"] == "Claimed job"


def test_resume_waiting_login_job(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    repo.create_job("job-1", "patient.zip", Path("/z"), Path("/i"), Path("/r"))
    repo.set_job_waiting_login("job-1", "worker-1", ":21", "login required")
    app = create_app(repository=repo, storage=StorageService(tmp_path))
    client = TestClient(app)

    response = client.post("/jobs/job-1/resume")

    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_get_workers(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    repo.upsert_worker("worker-1", ":21", 5921, Path("/profile"), status=WorkerStatus.IDLE, automation_mode="playwright")
    app = create_app(repository=repo, storage=StorageService(tmp_path))
    client = TestClient(app)

    response = client.get("/workers")

    assert response.status_code == 200
    assert response.json()[0]["worker_id"] == "worker-1"
```

- [ ] **Step 2: Run API tests and verify they fail**

Run:

```bash
pytest tests/test_api.py -v
```

Expected: FAIL because `create_app` is not defined.

- [ ] **Step 3: Implement FastAPI app factory and endpoints**

Create `app/api/main.py`:

```python
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile

from app.config import Settings
from app.db.mongo import create_mongo_database, ensure_indexes
from app.db.repositories import MongoRepository
from app.domain import JobStatus
from app.storage import StorageService


def create_app(repository: MongoRepository | None = None, storage: StorageService | None = None) -> FastAPI:
    if repository is None or storage is None:
        settings = Settings()
        db = create_mongo_database(settings)
        ensure_indexes(db)
        repository = MongoRepository(db)
        storage = StorageService(settings.data_root, settings.supported_upload_extensions)

    app = FastAPI(title="NotebookLM RPA Worker API")

    @app.post("/jobs")
    def create_job(file: UploadFile = File(...)) -> dict:
        if not file.filename or not file.filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="Only .zip uploads are accepted")
        job_id = str(uuid4())
        paths = storage.prepare_job_paths(job_id, file.filename)
        storage.save_upload(file.file, paths)
        repository.create_job(job_id, file.filename, paths.zip_path, paths.input_dir, paths.result_dir)
        return {"job_id": job_id, "status": JobStatus.QUEUED.value}

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = repository.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        artifacts = repository.list_artifacts(job_id)
        events = repository.list_events(job_id)
        worker = repository.db.workers.find_one({"_id": job.get("worker_id")}) if job.get("worker_id") else None
        return {
            "job_id": job["_id"],
            "status": job["status"],
            "worker_id": job.get("worker_id"),
            "display": job.get("display"),
            "vnc_port": worker.get("vnc_port") if worker else None,
            "notebook_id": job.get("notebook_id"),
            "notebook_url": job.get("notebook_url"),
            "last_step": job.get("last_step"),
            "error": job.get("error"),
            "artifacts": _public_documents(artifacts),
            "events": _public_documents(events),
        }

    @app.post("/jobs/{job_id}/resume")
    def resume_job(job_id: str) -> dict:
        resumed = repository.resume_waiting_login_job(job_id)
        job = resumed or repository.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"job_id": job["_id"], "status": job["status"]}

    @app.get("/workers")
    def get_workers() -> list[dict]:
        return [
            {
                "worker_id": worker["_id"],
                "display": worker["display"],
                "vnc_port": worker["vnc_port"],
                "status": worker["status"],
                "current_job_id": worker.get("current_job_id"),
                "login_status": worker.get("login_status"),
                "heartbeat_at": worker["heartbeat_at"].isoformat(),
                "automation_mode": worker.get("automation_mode"),
                "last_error": worker.get("last_error"),
            }
            for worker in repository.list_workers()
        ]

    return app


def _public_documents(documents: list[dict]) -> list[dict]:
    public = []
    for document in documents:
        item = dict(document)
        item["id"] = str(item.pop("_id"))
        if "created_at" in item:
            item["created_at"] = item["created_at"].isoformat()
        public.append(item)
    return public

```
- [ ] **Step 4: Run API tests**

Run:

```bash
pytest tests/test_api.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/main.py tests/test_api.py
git commit -m "feat: add notebooklm job api"
```

---

### Task 6: Desktop Manager

**Files:**
- Create: `app/worker/desktop.py`
- Test: `tests/test_desktop.py`

- [ ] **Step 1: Write failing desktop command tests**

Create `tests/test_desktop.py`:

```python
from pathlib import Path

from app.worker.desktop import DesktopManager


def test_vnc_command_uses_display_and_geometry() -> None:
    manager = DesktopManager(display=":21", vnc_port=5921, chrome_user_data_dir=Path("/profiles/w1"))

    assert manager.vnc_command() == ["vncserver", ":21", "-geometry", "1600x1000", "-depth", "24"]


def test_chrome_command_uses_profile_and_notebook_url() -> None:
    manager = DesktopManager(display=":21", vnc_port=5921, chrome_user_data_dir=Path("/profiles/w1"))

    command = manager.chrome_command("https://notebooklm.google.com")

    assert "--user-data-dir=/profiles/w1" in command
    assert "--no-first-run" in command
    assert "https://notebooklm.google.com" == command[-1]
```

- [ ] **Step 2: Run desktop tests and verify they fail**

Run:

```bash
pytest tests/test_desktop.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `app.worker.desktop`.

- [ ] **Step 3: Implement desktop manager**

Create `app/worker/desktop.py`:

```python
import os
import subprocess
from pathlib import Path


class DesktopManager:
    def __init__(
        self,
        display: str,
        vnc_port: int,
        chrome_user_data_dir: Path,
        geometry: str = "1600x1000",
        depth: str = "24",
        chrome_binary: str = "google-chrome",
    ) -> None:
        self.display = display
        self.vnc_port = vnc_port
        self.chrome_user_data_dir = chrome_user_data_dir
        self.geometry = geometry
        self.depth = depth
        self.chrome_binary = chrome_binary

    def vnc_command(self) -> list[str]:
        return ["vncserver", self.display, "-geometry", self.geometry, "-depth", self.depth]

    def chrome_command(self, url: str) -> list[str]:
        return [
            self.chrome_binary,
            f"--user-data-dir={self.chrome_user_data_dir}",
            "--no-first-run",
            "--disable-default-apps",
            "--start-maximized",
            url,
        ]

    def ensure_vnc(self) -> None:
        subprocess.run(self.vnc_command(), check=True)

    def launch_chrome(self, url: str) -> subprocess.Popen:
        self.chrome_user_data_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["DISPLAY"] = self.display
        return subprocess.Popen(self.chrome_command(url), env=env)
```

- [ ] **Step 4: Run desktop tests**

Run:

```bash
pytest tests/test_desktop.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/worker/desktop.py tests/test_desktop.py
git commit -m "feat: add desktop process manager"
```

---

### Task 7: RPA Adapter Interface and Workflow

**Files:**
- Create: `app/worker/rpa/base.py`
- Test: `tests/test_rpa_workflow.py`

- [ ] **Step 1: Write failing RPA workflow tests**

Create `tests/test_rpa_workflow.py`:

```python
from pathlib import Path

import pytest

from app.domain import deep_research_prompt
from app.worker.rpa.base import LoginRequired, NotebookLMWorkflow, RpaArtifacts, RpaSession


class FakeSession(RpaSession):
    def __init__(self, logged_in: bool = True) -> None:
        self.logged_in = logged_in
        self.calls: list[str] = []

    def ensure_logged_in(self) -> bool:
        self.calls.append("ensure_logged_in")
        return self.logged_in

    def create_new_notebook(self) -> tuple[str, str]:
        self.calls.append("create_new_notebook")
        return "notebook-123", "https://notebooklm.google.com/notebook/notebook-123"

    def upload_sources(self, files: list[Path]) -> int:
        self.calls.append(f"upload_sources:{len(files)}")
        return len(files)

    def start_deep_research(self, prompt: str) -> None:
        self.calls.append(f"start_deep_research:{prompt}")

    def wait_for_research(self) -> None:
        self.calls.append("wait_for_research")

    def generate_slide_deck(self, language: str) -> None:
        self.calls.append(f"generate_slide_deck:{language}")

    def wait_for_slide_deck(self) -> None:
        self.calls.append("wait_for_slide_deck")

    def save_results(self, result_dir: Path) -> RpaArtifacts:
        self.calls.append(f"save_results:{result_dir}")
        return RpaArtifacts(paths=[result_dir / "research.md", result_dir / "slide_deck.pdf"])


def test_workflow_runs_expected_notebooklm_steps(tmp_path: Path) -> None:
    session = FakeSession()
    workflow = NotebookLMWorkflow(session=session)
    progress: list[str] = []

    result = workflow.run(files=[tmp_path / "a.pdf"], result_dir=tmp_path / "result", progress=progress.append)

    assert result.notebook_id == "notebook-123"
    assert result.notebook_url.endswith("notebook-123")
    assert result.artifacts.paths == [tmp_path / "result" / "research.md", tmp_path / "result" / "slide_deck.pdf"]
    assert progress == ["uploading_sources", "researching", "generating_ppt", "downloading_results"]
    assert session.calls == [
        "ensure_logged_in",
        "create_new_notebook",
        "upload_sources:1",
        f"start_deep_research:{deep_research_prompt()}",
        "wait_for_research",
        "generate_slide_deck:简体中文",
        "wait_for_slide_deck",
        f"save_results:{tmp_path / 'result'}",
    ]


def test_workflow_raises_login_required_when_not_logged_in(tmp_path: Path) -> None:
    session = FakeSession(logged_in=False)
    workflow = NotebookLMWorkflow(session=session)

    with pytest.raises(LoginRequired):
        workflow.run(files=[tmp_path / "a.pdf"], result_dir=tmp_path / "result")
```

- [ ] **Step 2: Run RPA workflow tests and verify they fail**

Run:

```bash
pytest tests/test_rpa_workflow.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `app.worker.rpa.base`.

- [ ] **Step 3: Implement RPA protocol and workflow**

Create `app/worker/rpa/base.py`:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from app.domain import deep_research_prompt


class LoginRequired(RuntimeError):
    pass


class RpaError(RuntimeError):
    pass


@dataclass(frozen=True)
class RpaArtifacts:
    paths: list[Path]


@dataclass(frozen=True)
class RpaWorkflowResult:
    notebook_id: str
    notebook_url: str
    artifacts: RpaArtifacts


class RpaSession(Protocol):
    def ensure_logged_in(self) -> bool:
        raise NotImplementedError

    def create_new_notebook(self) -> tuple[str, str]:
        raise NotImplementedError

    def upload_sources(self, files: list[Path]) -> int:
        raise NotImplementedError

    def start_deep_research(self, prompt: str) -> None:
        raise NotImplementedError

    def wait_for_research(self) -> None:
        raise NotImplementedError

    def generate_slide_deck(self, language: str) -> None:
        raise NotImplementedError

    def wait_for_slide_deck(self) -> None:
        raise NotImplementedError

    def save_results(self, result_dir: Path) -> RpaArtifacts:
        raise NotImplementedError


class NotebookLMWorkflow:
    def __init__(self, session: RpaSession) -> None:
        self.session = session

    def run(
        self,
        files: list[Path],
        result_dir: Path,
        progress: Callable[[str], None] | None = None,
    ) -> RpaWorkflowResult:
        if not self.session.ensure_logged_in():
            raise LoginRequired("NotebookLM login is required")
        notebook_id, notebook_url = self.session.create_new_notebook()
        self._notify(progress, "uploading_sources")
        self.session.upload_sources(files)
        self._notify(progress, "researching")
        self.session.start_deep_research(deep_research_prompt())
        self.session.wait_for_research()
        self._notify(progress, "generating_ppt")
        self.session.generate_slide_deck(language="简体中文")
        self.session.wait_for_slide_deck()
        self._notify(progress, "downloading_results")
        artifacts = self.session.save_results(result_dir)
        return RpaWorkflowResult(notebook_id=notebook_id, notebook_url=notebook_url, artifacts=artifacts)

    def _notify(self, progress: Callable[[str], None] | None, step: str) -> None:
        if progress is not None:
            progress(step)
```

- [ ] **Step 4: Run RPA workflow tests**

Run:

```bash
pytest tests/test_rpa_workflow.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/worker/rpa/base.py tests/test_rpa_workflow.py
git commit -m "feat: add notebooklm rpa workflow contract"
```

---

### Task 8: Playwright and Visual RPA Adapters

**Files:**
- Create: `app/worker/rpa/playwright_adapter.py`
- Create: `app/worker/rpa/visual_adapter.py`
- Test: `tests/test_rpa_playwright_adapter.py`

- [ ] **Step 1: Write failing adapter unit tests**

Create `tests/test_rpa_playwright_adapter.py`:

```python
from pathlib import Path

from app.worker.rpa.playwright_adapter import extract_notebook_id, supported_file_inputs


def test_extract_notebook_id_from_notebooklm_url() -> None:
    assert (
        extract_notebook_id("https://notebooklm.google.com/notebook/abc123?_gl=1")
        == "abc123"
    )


def test_extract_notebook_id_from_unknown_url_returns_last_non_empty_segment() -> None:
    assert extract_notebook_id("https://notebooklm.google.com/notebooks/abc123/") == "abc123"


def test_supported_file_inputs_filters_directories_and_unsupported_suffixes(tmp_path: Path) -> None:
    pdf = tmp_path / "a.pdf"
    exe = tmp_path / "b.exe"
    nested = tmp_path / "nested"
    pdf.write_text("pdf")
    exe.write_text("exe")
    nested.mkdir()

    assert supported_file_inputs([pdf, exe, nested], supported_extensions=(".pdf",)) == [pdf]
```

- [ ] **Step 2: Run adapter tests and verify they fail**

Run:

```bash
pytest tests/test_rpa_playwright_adapter.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `app.worker.rpa.playwright_adapter`.

- [ ] **Step 3: Implement Playwright adapter helpers and method skeletons**

Create `app/worker/rpa/playwright_adapter.py`:

```python
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from app.worker.rpa.base import RpaArtifacts, RpaError


def extract_notebook_id(url: str) -> str:
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    if not path_parts:
        raise RpaError(f"Cannot extract notebook_id from URL: {url}")
    return path_parts[-1]


def supported_file_inputs(files: list[Path], supported_extensions: tuple[str, ...]) -> list[Path]:
    allowed = tuple(ext.lower() for ext in supported_extensions)
    return [path for path in files if path.is_file() and path.suffix.lower() in allowed]


class PlaywrightNotebookLMSession:
    def __init__(
        self,
        user_data_dir: Path,
        notebooklm_url: str,
        supported_extensions: tuple[str, ...],
        downloads_dir: Path,
        headless: bool = False,
    ) -> None:
        self.user_data_dir = user_data_dir
        self.notebooklm_url = notebooklm_url
        self.supported_extensions = supported_extensions
        self.downloads_dir = downloads_dir
        self.headless = headless
        self._playwright = None
        self._context = None
        self.page: Page | None = None

    def __enter__(self):
        self.start()
        return self

    def start(self) -> None:
        if self.page is not None:
            return
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.user_data_dir),
            headless=self.headless,
            accept_downloads=True,
            downloads_path=str(self.downloads_dir),
            args=["--start-maximized"],
        )
        self.page = self._context.pages[0] if self._context.pages else self._context.new_page()

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._context is not None:
            self._context.close()
        if self._playwright is not None:
            self._playwright.stop()

    def ensure_logged_in(self) -> bool:
        page = self._page()
        page.goto(self.notebooklm_url, wait_until="domcontentloaded")
        current_url = page.url.lower()
        if "accounts.google.com" in current_url:
            return False
        body_text = page.locator("body").inner_text(timeout=10_000).lower()
        if "sign in" in body_text or "登录" in body_text:
            return False
        return True

    def create_new_notebook(self) -> tuple[str, str]:
        page = self._page()
        if page.get_by_text("新建笔记本").count() > 0:
            page.get_by_text("新建笔记本").first.click()
        elif page.get_by_text("新建").count() > 0:
            page.get_by_text("新建").first.click()
        page.keyboard.press("Escape")
        page.wait_for_load_state("domcontentloaded")
        notebook_url = page.url
        notebook_id = extract_notebook_id(notebook_url)
        return notebook_id, notebook_url

    def upload_sources(self, files: list[Path]) -> int:
        page = self._page()
        uploadable = supported_file_inputs(files, self.supported_extensions)
        if not uploadable:
            raise RpaError("No uploadable files found")
        page.get_by_text("添加来源").first.click()
        with page.expect_file_chooser() as chooser_info:
            page.get_by_text("上传").first.click()
        chooser_info.value.set_files([str(path) for path in uploadable])
        return len(uploadable)

    def start_deep_research(self, prompt: str) -> None:
        page = self._page()
        page.get_by_text("在网络中搜索新来源").first.click()
        page.get_by_text("Fast Research").first.click()
        page.get_by_text("Deep Research").first.click()
        page.keyboard.type(prompt)
        page.keyboard.press("Enter")

    def wait_for_research(self) -> None:
        self._page().wait_for_timeout(5_000)

    def generate_slide_deck(self, language: str) -> None:
        page = self._page()
        page.get_by_text("演示文稿").first.click()
        page.get_by_text(">").first.click()
        page.get_by_text(language).first.click()
        page.keyboard.press("Enter")

    def wait_for_slide_deck(self) -> None:
        self._page().wait_for_timeout(5_000)

    def save_results(self, result_dir: Path) -> RpaArtifacts:
        result_dir.mkdir(parents=True, exist_ok=True)
        research_path = result_dir / "research.md"
        research_path.write_text(self._page().locator("body").inner_text(), encoding="utf-8")
        screenshot_path = result_dir / "screenshots" / "final.png"
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        self._page().screenshot(path=str(screenshot_path), full_page=True)
        return RpaArtifacts(paths=[research_path, screenshot_path])

    def _page(self) -> Page:
        if self.page is None:
            self.start()
        if self.page is None:
            raise RpaError("Playwright page could not be initialized")
        return self.page
```

Create `app/worker/rpa/visual_adapter.py`:

```python
from pathlib import Path

from app.worker.rpa.base import RpaArtifacts, RpaError


class VisualNotebookLMSession:
    def __init__(self, display: str, screenshots_dir: Path) -> None:
        self.display = display
        self.screenshots_dir = screenshots_dir

    def ensure_logged_in(self) -> bool:
        raise RpaError("Pure visual mode is preserved as a fallback boundary and is not implemented in the MVP")

    def create_new_notebook(self) -> tuple[str, str]:
        raise RpaError("Pure visual mode is preserved as a fallback boundary and is not implemented in the MVP")

    def upload_sources(self, files: list[Path]) -> int:
        raise RpaError("Pure visual mode is preserved as a fallback boundary and is not implemented in the MVP")

    def start_deep_research(self, prompt: str) -> None:
        raise RpaError("Pure visual mode is preserved as a fallback boundary and is not implemented in the MVP")

    def wait_for_research(self) -> None:
        raise RpaError("Pure visual mode is preserved as a fallback boundary and is not implemented in the MVP")

    def generate_slide_deck(self, language: str) -> None:
        raise RpaError("Pure visual mode is preserved as a fallback boundary and is not implemented in the MVP")

    def wait_for_slide_deck(self) -> None:
        raise RpaError("Pure visual mode is preserved as a fallback boundary and is not implemented in the MVP")

    def save_results(self, result_dir: Path) -> RpaArtifacts:
        raise RpaError("Pure visual mode is preserved as a fallback boundary and is not implemented in the MVP")
```

- [ ] **Step 4: Run adapter tests**

Run:

```bash
pytest tests/test_rpa_playwright_adapter.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/worker/rpa/playwright_adapter.py app/worker/rpa/visual_adapter.py tests/test_rpa_playwright_adapter.py
git commit -m "feat: add notebooklm rpa adapters"
```

---

### Task 9: Worker Runner State Machine

**Files:**
- Create: `app/worker/runner.py`
- Test: `tests/test_worker_runner.py`

- [ ] **Step 1: Write failing worker runner tests**

Create `tests/test_worker_runner.py`:

```python
from pathlib import Path

from app.db.repositories import MongoRepository
from app.domain import ArtifactKind, JobStatus, WorkerStatus
from app.storage import StorageService
from app.worker.rpa.base import LoginRequired, RpaArtifacts
from app.worker.runner import WorkerRunner


class CompletingWorkflow:
    def run(self, files: list[Path], result_dir: Path, progress=None):
        if progress is not None:
            progress("uploading_sources")
            progress("researching")
            progress("generating_ppt")
            progress("downloading_results")
        research = result_dir / "research.md"
        slide = result_dir / "slide_deck.pdf"
        research.write_text("record", encoding="utf-8")
        slide.write_bytes(b"pdf")
        return type(
            "Result",
            (),
            {
                "notebook_id": "notebook-123",
                "notebook_url": "https://notebooklm.google.com/notebook/notebook-123",
                "artifacts": RpaArtifacts(paths=[research, slide]),
            },
        )()


class LoginRequiredWorkflow:
    def run(self, files: list[Path], result_dir: Path, progress=None):
        raise LoginRequired("login required")


def test_process_once_completes_job(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    storage = StorageService(tmp_path, supported_extensions=(".txt",))
    paths = storage.prepare_job_paths("job-1", "patient.zip")
    paths.zip_path.write_bytes(b"not-used")
    input_file = paths.input_dir / "record.txt"
    input_file.write_text("hello", encoding="utf-8")
    repo.create_job("job-1", "patient.zip", paths.zip_path, paths.input_dir, paths.result_dir)
    runner = WorkerRunner(
        repository=repo,
        storage=storage,
        worker_id="worker-1",
        display=":21",
        vnc_port=5921,
        chrome_user_data_dir=tmp_path / "profile",
        workflow_factory=lambda: CompletingWorkflow(),
        extract_zip=False,
    )

    processed = runner.process_once()

    job = repo.get_job("job-1")
    assert processed is True
    assert job["status"] == JobStatus.COMPLETED.value
    assert job["notebook_id"] == "notebook-123"
    assert len(repo.list_artifacts("job-1")) == 2


def test_process_once_sets_waiting_login(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    storage = StorageService(tmp_path, supported_extensions=(".txt",))
    paths = storage.prepare_job_paths("job-1", "patient.zip")
    paths.zip_path.write_bytes(b"not-used")
    (paths.input_dir / "record.txt").write_text("hello", encoding="utf-8")
    repo.create_job("job-1", "patient.zip", paths.zip_path, paths.input_dir, paths.result_dir)
    runner = WorkerRunner(
        repository=repo,
        storage=storage,
        worker_id="worker-1",
        display=":21",
        vnc_port=5921,
        chrome_user_data_dir=tmp_path / "profile",
        workflow_factory=lambda: LoginRequiredWorkflow(),
        extract_zip=False,
    )

    runner.process_once()

    job = repo.get_job("job-1")
    worker = repo.list_workers()[0]
    assert job["status"] == JobStatus.WAITING_LOGIN.value
    assert job["login_required"] is True
    assert worker["status"] == WorkerStatus.WAITING_LOGIN.value
```

- [ ] **Step 2: Run worker tests and verify they fail**

Run:

```bash
pytest tests/test_worker_runner.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `app.worker.runner`.

- [ ] **Step 3: Implement worker runner**

Create `app/worker/runner.py`:

```python
import time
from pathlib import Path
from typing import Callable

from app.db.repositories import MongoRepository
from app.domain import ArtifactKind, JobStatus, WorkerStatus
from app.storage import JobPaths, StorageService
from app.worker.rpa.base import LoginRequired, NotebookLMWorkflow, RpaError


class WorkerRunner:
    def __init__(
        self,
        repository: MongoRepository,
        storage: StorageService,
        worker_id: str,
        display: str,
        vnc_port: int,
        chrome_user_data_dir: Path,
        workflow_factory: Callable[[], NotebookLMWorkflow],
        poll_interval_seconds: float = 2.0,
        automation_mode: str = "playwright",
        extract_zip: bool = True,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.worker_id = worker_id
        self.display = display
        self.vnc_port = vnc_port
        self.chrome_user_data_dir = chrome_user_data_dir
        self.workflow_factory = workflow_factory
        self.poll_interval_seconds = poll_interval_seconds
        self.automation_mode = automation_mode
        self.extract_zip_enabled = extract_zip

    def process_once(self) -> bool:
        self.repository.upsert_worker(
            self.worker_id,
            self.display,
            self.vnc_port,
            self.chrome_user_data_dir,
            WorkerStatus.IDLE,
            self.automation_mode,
        )
        job = self.repository.claim_next_job(self.worker_id, self.display)
        if job is None:
            return False
        job_id = job["_id"]
        self.repository.upsert_worker(
            self.worker_id,
            self.display,
            self.vnc_port,
            self.chrome_user_data_dir,
            WorkerStatus.BUSY,
            self.automation_mode,
            current_job_id=job_id,
        )
        try:
            files = self._prepare_files(job)
            workflow = self.workflow_factory()
            result = workflow.run(
                files=files,
                result_dir=Path(job["result_dir"]),
                progress=lambda step: self._record_progress(job_id, step),
            )
            for artifact_path in result.artifacts.paths:
                kind = ArtifactKind.SCREENSHOT
                if artifact_path.name == "research.md":
                    kind = ArtifactKind.RESEARCH_MARKDOWN
                if artifact_path.name == "slide_deck.pdf":
                    kind = ArtifactKind.SLIDE_PDF
                sha256 = self.storage.sha256_file(artifact_path)
                self.repository.add_artifact(job_id, kind, artifact_path, sha256)
            self.repository.update_job_status(
                job_id,
                JobStatus.COMPLETED,
                "completed",
                extra={"notebook_id": result.notebook_id, "notebook_url": result.notebook_url},
            )
            self.repository.add_event(job_id, self.worker_id, "completed", "info", "Job completed")
            self._set_worker_idle()
            return True
        except LoginRequired as exc:
            self.repository.set_job_waiting_login(job_id, self.worker_id, self.display, str(exc))
            self.repository.upsert_worker(
                self.worker_id,
                self.display,
                self.vnc_port,
                self.chrome_user_data_dir,
                WorkerStatus.WAITING_LOGIN,
                self.automation_mode,
                current_job_id=job_id,
                login_status="required",
            )
            return True
        except Exception as exc:
            self.repository.update_job_status(job_id, JobStatus.FAILED, "failed", error=str(exc))
            self.repository.add_event(job_id, self.worker_id, "failed", "error", str(exc))
            self._set_worker_idle()
            return True

    def run_forever(self) -> None:
        while True:
            processed = self.process_once()
            if not processed:
                time.sleep(self.poll_interval_seconds)

    def _prepare_files(self, job: dict) -> list[Path]:
        paths = JobPaths(
            job_dir=Path(job["zip_path"]).parents[1],
            upload_dir=Path(job["zip_path"]).parent,
            input_dir=Path(job["input_dir"]),
            result_dir=Path(job["result_dir"]),
            zip_path=Path(job["zip_path"]),
        )
        if self.extract_zip_enabled:
            files = self.storage.extract_zip(paths)
            if not files:
                raise RpaError("No uploadable files found")
            return files
        files = [path for path in paths.input_dir.rglob("*") if path.is_file()]
        if not files:
            raise RpaError("No uploadable files found")
        return sorted(files)

    def _record_progress(self, job_id: str, step: str) -> None:
        status_by_step = {
            "uploading_sources": JobStatus.UPLOADING_SOURCES,
            "researching": JobStatus.RESEARCHING,
            "generating_ppt": JobStatus.GENERATING_PPT,
            "downloading_results": JobStatus.DOWNLOADING_RESULTS,
        }
        status = status_by_step[step]
        self.repository.update_job_status(job_id, status, step)
        self.repository.add_event(job_id, self.worker_id, step, "info", f"RPA step: {step}")

    def _set_worker_idle(self) -> None:
        self.repository.upsert_worker(
            self.worker_id,
            self.display,
            self.vnc_port,
            self.chrome_user_data_dir,
            WorkerStatus.IDLE,
            self.automation_mode,
            current_job_id=None,
        )
```

- [ ] **Step 4: Run worker tests**

Run:

```bash
pytest tests/test_worker_runner.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/worker/runner.py tests/test_worker_runner.py
git commit -m "feat: add worker job runner"
```

---

### Task 10: Worker CLI Entrypoint

**Files:**
- Create: `app/worker/main.py`
- Test: `tests/test_worker_main.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_worker_main.py`:

```python
from app.worker.main import parse_args


def test_parse_args_accepts_worker_id_and_display() -> None:
    args = parse_args(["--worker-id", "worker-2", "--display", ":22", "--once"])

    assert args.worker_id == "worker-2"
    assert args.display == ":22"
    assert args.once is True
```

- [ ] **Step 2: Run CLI tests and verify they fail**

Run:

```bash
pytest tests/test_worker_main.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `app.worker.main`.

- [ ] **Step 3: Implement worker CLI**

Create `app/worker/main.py`:

```python
import argparse

from app.config import Settings
from app.db.mongo import create_mongo_database, ensure_indexes
from app.db.repositories import MongoRepository
from app.storage import StorageService
from app.worker.desktop import DesktopManager
from app.worker.runner import WorkerRunner
from app.worker.rpa.base import NotebookLMWorkflow
from app.worker.rpa.playwright_adapter import PlaywrightNotebookLMSession


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a NotebookLM RPA worker")
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--display", default=None)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    settings = Settings()
    worker_id = args.worker_id or settings.worker_id
    display = args.display or settings.display
    db = create_mongo_database(settings)
    ensure_indexes(db)
    repository = MongoRepository(db)
    storage = StorageService(settings.data_root, settings.supported_upload_extensions)
    desktop = DesktopManager(display, settings.vnc_port, settings.resolved_chrome_user_data_dir)
    desktop.ensure_vnc()
    desktop.launch_chrome(settings.notebooklm_url)

    def workflow_factory() -> NotebookLMWorkflow:
        session = PlaywrightNotebookLMSession(
            user_data_dir=settings.resolved_chrome_user_data_dir,
            notebooklm_url=settings.notebooklm_url,
            supported_extensions=settings.supported_upload_extensions,
            downloads_dir=settings.worker_root / worker_id / "downloads",
            headless=False,
        )
        return NotebookLMWorkflow(session=session)

    runner = WorkerRunner(
        repository=repository,
        storage=storage,
        worker_id=worker_id,
        display=display,
        vnc_port=settings.vnc_port,
        chrome_user_data_dir=settings.resolved_chrome_user_data_dir,
        workflow_factory=workflow_factory,
        poll_interval_seconds=settings.poll_interval_seconds,
        automation_mode=settings.automation_mode,
    )
    if args.once:
        runner.process_once()
    else:
        runner.run_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
pytest tests/test_worker_main.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/worker/main.py tests/test_worker_main.py
git commit -m "feat: add worker cli entrypoint"
```

---

### Task 11: Fake End-to-End Integration

**Files:**
- Test: `tests/test_integration_fake_worker.py`

- [ ] **Step 1: Write integration test using API, Mongo repository, storage, and fake workflow**

Create `tests/test_integration_fake_worker.py`:

```python
import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.db.repositories import MongoRepository
from app.domain import JobStatus
from app.storage import StorageService
from app.worker.rpa.base import RpaArtifacts
from app.worker.runner import WorkerRunner


class CompletingWorkflow:
    def run(self, files: list[Path], result_dir: Path, progress=None):
        assert [path.name for path in files] == ["record.txt"]
        if progress is not None:
            progress("uploading_sources")
            progress("researching")
            progress("generating_ppt")
            progress("downloading_results")
        research = result_dir / "research.md"
        slide = result_dir / "slide_deck.pdf"
        research.write_text("门诊记录单", encoding="utf-8")
        slide.write_bytes(b"%PDF")
        return type(
            "Result",
            (),
            {
                "notebook_id": "notebook-123",
                "notebook_url": "https://notebooklm.google.com/notebook/notebook-123",
                "artifacts": RpaArtifacts(paths=[research, slide]),
            },
        )()


def zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("record.txt", "hello")
    return buffer.getvalue()


def test_api_job_then_worker_once_completes_job(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    storage = StorageService(tmp_path, supported_extensions=(".txt",))
    app = create_app(repository=repo, storage=storage)
    client = TestClient(app)

    created = client.post(
        "/jobs",
        files={"file": ("patient.zip", zip_bytes(), "application/zip")},
    ).json()
    runner = WorkerRunner(
        repository=repo,
        storage=storage,
        worker_id="worker-1",
        display=":21",
        vnc_port=5921,
        chrome_user_data_dir=tmp_path / "profile",
        workflow_factory=lambda: CompletingWorkflow(),
    )

    runner.process_once()

    status = client.get(f"/jobs/{created['job_id']}").json()
    assert status["status"] == JobStatus.COMPLETED.value
    assert status["notebook_id"] == "notebook-123"
    assert {artifact["kind"] for artifact in status["artifacts"]} == {"research_markdown", "slide_pdf"}
```

- [ ] **Step 2: Run integration test and verify it passes**

Run:

```bash
pytest tests/test_integration_fake_worker.py -v
```

Expected: PASS.

- [ ] **Step 3: Run the focused test suite**

Run:

```bash
pytest tests/test_config_domain.py tests/test_storage.py tests/test_repositories.py tests/test_api.py tests/test_desktop.py tests/test_rpa_workflow.py tests/test_rpa_playwright_adapter.py tests/test_worker_runner.py tests/test_worker_main.py tests/test_integration_fake_worker.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_fake_worker.py
git commit -m "test: add fake notebooklm integration coverage"
```

---

### Task 12: Operational Verification and Documentation

**Files:**
- Modify: `README.md`
- Create: `.env.example`

- [ ] **Step 1: Add operational configuration sample**

Create `.env.example`:

```dotenv
MONGO_URI=mongodb://localhost:27017
DATABASE_NAME=patient_records
DATA_ROOT=/DATA/patients
WORKER_ROOT=/DATA/notebooklm-workers
WORKER_ID=worker-1
DISPLAY=:21
VNC_PORT=5921
AUTOMATION_MODE=playwright
```

- [ ] **Step 2: Expand README with runbook**

Append this content to `README.md`:

````markdown
## Runtime Requirements

- MongoDB server reachable through `MONGO_URI`.
- `vncserver` installed and available on `PATH`.
- Google Chrome or Chromium installed.
- `xdotool` installed for hybrid desktop fallback.
- `/DATA/patients` writable by the service user.
- `/DATA/notebooklm-workers` writable by the service user.

## Manual Login Flow

1. Start the API server.
2. Start a worker with `python -m app.worker.main --worker-id worker-1 --display :21`.
3. Submit a zip to `POST /jobs`.
4. If `GET /jobs/{job_id}` returns `waiting_login`, connect to VNC display `:21`.
5. Log in to Google manually in the Chrome window.
6. Call `POST /jobs/{job_id}/resume`.
7. Continue polling `GET /jobs/{job_id}` until `completed` or `failed`.

## API Examples

Submit a job:

```bash
curl -F "file=@patient.zip" http://localhost:8000/jobs
```

Check status:

```bash
curl http://localhost:8000/jobs/<job_id>
```

Resume after manual login:

```bash
curl -X POST http://localhost:8000/jobs/<job_id>/resume
```

List workers:

```bash
curl http://localhost:8000/workers
```
````

- [ ] **Step 3: Run all automated tests**

Run:

```bash
pytest -v
```

Expected: PASS.

- [ ] **Step 4: Run local import checks**

Run:

```bash
python -m app.worker.main --help
```

Expected: prints the worker CLI help and exits with code 0.

- [ ] **Step 5: Commit**

```bash
git add README.md .env.example
git commit -m "docs: add notebooklm rpa runbook"
```

---

## Self-Review

Spec coverage:
- API job submission and polling are implemented by Tasks 4, 5, and 11.
- MongoDB collections, state transitions, atomic claiming, and artifacts are implemented by Tasks 2, 4, 9, and 11.
- Zip extraction safety and `/DATA/patients/{job_id}` layout are implemented by Task 3.
- VNC and Chrome process ownership are implemented by Task 6 and wired by Task 10.
- NotebookLM RPA flow, including Deep Research prompt and `简体中文` slide deck language, is represented by Tasks 7 and 8.
- Playwright-first mode, hybrid upload fallback boundary, and pure visual fallback boundary are represented by Tasks 7 and 8.
- Manual login pause and resume are implemented by Tasks 4, 5, 7, and 9.
- Result artifact hashing and MongoDB persistence are implemented by Tasks 3, 4, 9, and 11.
- Operational setup is documented by Task 12.

Placeholder scan:
- No task contains banned placeholder markers or unspecified implementation instructions.
- The pure visual adapter is explicitly out of MVP runtime behavior and raises a clear `RpaError` while preserving the boundary required by the approved design.

Type consistency:
- `JobStatus`, `ArtifactKind`, `WorkerStatus`, and `deep_research_prompt` are defined in Task 2 and reused consistently in later tasks.
- Repository method names used by API and worker tasks match the methods introduced in Task 4.
- `NotebookLMWorkflow` and `RpaArtifacts` introduced in Task 7 are used consistently by Task 9 and Task 11.
