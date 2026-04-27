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


def create_app(repository: MongoRepository | None = None, storage: StorageService | None = None) -> FastAPI:
    if (repository is None) != (storage is None):
        raise ValueError("repository and storage must be provided together")

    if repository is None and storage is None:
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
        _validate_zip(file)
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


def _validate_zip(file: UploadFile) -> None:
    try:
        file.file.seek(0)
        contents = file.file.read()
        with zipfile.ZipFile(io.BytesIO(contents)) as archive:
            if archive.testzip() is not None:
                raise HTTPException(status_code=400, detail="Invalid zip upload")
            for member in archive.infolist():
                _validate_zip_member_name(member.filename)
    except zipfile.BadZipFile as error:
        raise HTTPException(status_code=400, detail="Invalid zip upload") from error
    finally:
        file.file.seek(0)


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
