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
    chrome_remote_debugging_port: int | None = Field(None, alias="CHROME_REMOTE_DEBUGGING_PORT")
    automation_mode: str = Field("playwright", alias="AUTOMATION_MODE")
    notebooklm_url: str = "https://notebooklm.google.com"
    page_load_timeout_seconds: int = 120
    upload_timeout_seconds: int = 1200
    research_timeout_seconds: int = 2700
    ppt_timeout_seconds: int = 1800
    download_timeout_seconds: int = 600
    poll_interval_seconds: float = 2.0
    max_upload_bytes: int = Field(100 * 1024 * 1024, alias="MAX_UPLOAD_BYTES")
    max_zip_members: int = Field(500, alias="MAX_ZIP_MEMBERS")
    max_uncompressed_bytes: int = Field(500 * 1024 * 1024, alias="MAX_UNCOMPRESSED_BYTES")
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
