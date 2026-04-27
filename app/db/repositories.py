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
        self.db.events.create_index([("level", ASCENDING), ("created_at", ASCENDING)])

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
