from datetime import datetime, timezone
from enum import Enum
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
