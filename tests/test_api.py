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
