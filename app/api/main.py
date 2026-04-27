import io
import zipfile
from pathlib import PurePosixPath
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile

from app.config import Settings
from app.db.mongo import create_mongo_database, ensure_indexes
from app.db.repositories import MongoRepository
from app.domain import JobStatus
from app.storage import StorageService


def create_app(
    repository: MongoRepository | None = None,
    storage: StorageService | None = None,
    *,
    max_upload_bytes: int | None = None,
    max_zip_members: int | None = None,
    max_uncompressed_bytes: int | None = None,
) -> FastAPI:
    if (repository is None) != (storage is None):
        raise ValueError("repository and storage must be provided together")

    if repository is None and storage is None:
        settings = Settings()
        db = create_mongo_database(settings)
        ensure_indexes(db)
        repository = MongoRepository(db)
        storage = StorageService(settings.data_root, settings.supported_upload_extensions)
        max_upload_bytes = settings.max_upload_bytes if max_upload_bytes is None else max_upload_bytes
        max_zip_members = settings.max_zip_members if max_zip_members is None else max_zip_members
        max_uncompressed_bytes = (
            settings.max_uncompressed_bytes if max_uncompressed_bytes is None else max_uncompressed_bytes
        )
    else:
        max_upload_bytes = 100 * 1024 * 1024 if max_upload_bytes is None else max_upload_bytes
        max_zip_members = 500 if max_zip_members is None else max_zip_members
        max_uncompressed_bytes = 500 * 1024 * 1024 if max_uncompressed_bytes is None else max_uncompressed_bytes

    app = FastAPI(title="NotebookLM RPA Worker API")

    @app.post("/jobs")
    def create_job(file: UploadFile = File(...)) -> dict:
        if not file.filename or not file.filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="Only .zip uploads are accepted")
        _validate_zip(file, max_upload_bytes, max_zip_members, max_uncompressed_bytes)
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
        worker = repository.get_worker(job["worker_id"]) if job.get("worker_id") else None
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


def _validate_zip(
    file: UploadFile,
    max_upload_bytes: int,
    max_zip_members: int,
    max_uncompressed_bytes: int,
) -> None:
    try:
        file.file.seek(0)
        contents = _read_limited_upload(file, max_upload_bytes)
        with zipfile.ZipFile(io.BytesIO(contents)) as archive:
            members = archive.infolist()
            if len(members) > max_zip_members:
                raise HTTPException(status_code=413, detail="Zip upload has too many files")
            total_uncompressed = 0
            for member in members:
                _validate_zip_member_name(member.filename)
                if member.is_dir():
                    continue
                total_uncompressed += member.file_size
                if total_uncompressed > max_uncompressed_bytes:
                    raise HTTPException(status_code=413, detail="Zip upload is too large when extracted")
    except zipfile.BadZipFile as error:
        raise HTTPException(status_code=400, detail="Invalid zip upload") from error
    finally:
        file.file.seek(0)


def _read_limited_upload(file: UploadFile, max_upload_bytes: int) -> bytes:
    chunks = []
    total_size = 0
    while chunk := file.file.read(1024 * 1024):
        total_size += len(chunk)
        if total_size > max_upload_bytes:
            raise HTTPException(status_code=413, detail="Zip upload is too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_zip_member_name(member_name: str) -> None:
    normalized = PurePosixPath(member_name.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise HTTPException(status_code=400, detail="Invalid zip upload")


def _public_documents(documents: list[dict]) -> list[dict]:
    public = []
    for document in documents:
        item = dict(document)
        item["id"] = str(item.pop("_id"))
        if "created_at" in item:
            item["created_at"] = item["created_at"].isoformat()
        public.append(item)
    return public
