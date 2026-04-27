from pathlib import Path

from app.config import Settings
from app.domain import ArtifactKind, JobStatus, deep_research_prompt


def test_settings_defaults_are_mvp_safe(monkeypatch) -> None:
    for env_var in (
        "DATABASE_NAME",
        "DATA_ROOT",
        "WORKER_ROOT",
        "WORKER_ID",
        "DISPLAY",
        "VNC_PORT",
        "AUTOMATION_MODE",
        "MAX_UPLOAD_BYTES",
        "MAX_ZIP_MEMBERS",
        "MAX_UNCOMPRESSED_BYTES",
    ):
        monkeypatch.delenv(env_var, raising=False)

    settings = Settings(mongo_uri="mongodb://localhost:27017", _env_file=None)

    assert settings.database_name == "patient_records"
    assert settings.data_root == Path("/DATA/patients")
    assert settings.worker_root == Path("/DATA/notebooklm-workers")
    assert settings.worker_id == "worker-1"
    assert settings.display == ":21"
    assert settings.vnc_port == 5921
    assert settings.automation_mode == "playwright"
    assert settings.max_upload_bytes == 100 * 1024 * 1024
    assert settings.max_zip_members == 500
    assert settings.max_uncompressed_bytes == 500 * 1024 * 1024


def test_domain_status_and_artifact_values_are_stable() -> None:
    assert JobStatus.QUEUED.value == "queued"
    assert JobStatus.WAITING_LOGIN.value == "waiting_login"
    assert JobStatus.GENERATING_PPT.value == "generating_ppt"
    assert ArtifactKind.RESEARCH_MARKDOWN.value == "research_markdown"
    assert ArtifactKind.SLIDE_PDF.value == "slide_pdf"


def test_deep_research_prompt_is_exact() -> None:
    assert deep_research_prompt() == "请帮我梳理成 门诊记录单格式，不带来源 编号（即去掉末尾数字）的纯净版门诊记录单"
