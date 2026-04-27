import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.db.repositories import MongoRepository
from app.domain import ArtifactKind, WorkerStatus
from app.storage import StorageService


def make_zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("record.txt", "hello")
    return buffer.getvalue()


def make_zip_bytes_with_member(member_name: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member_name, "hello")
    return buffer.getvalue()


def make_zip_bytes_with_members(count: int) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for index in range(count):
            archive.writestr(f"record-{index}.txt", "hello")
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


def test_post_jobs_rejects_invalid_zip_without_creating_job(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    app = create_app(repository=repo, storage=StorageService(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/jobs",
        files={"file": ("patient.zip", b"not a zip", "application/zip")},
    )

    assert response.status_code == 400
    assert mongo_db.jobs.count_documents({}) == 0
    assert list(tmp_path.iterdir()) == []


def test_post_jobs_rejects_unsafe_zip_member_without_creating_job(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    app = create_app(repository=repo, storage=StorageService(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/jobs",
        files={"file": ("patient.zip", make_zip_bytes_with_member("../evil.txt"), "application/zip")},
    )

    assert response.status_code == 400
    assert mongo_db.jobs.count_documents({}) == 0
    assert list(tmp_path.iterdir()) == []


def test_post_jobs_rejects_upload_larger_than_limit_without_creating_job(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    app = create_app(repository=repo, storage=StorageService(tmp_path), max_upload_bytes=10)
    client = TestClient(app)

    response = client.post(
        "/jobs",
        files={"file": ("patient.zip", make_zip_bytes(), "application/zip")},
    )

    assert response.status_code == 413
    assert mongo_db.jobs.count_documents({}) == 0
    assert list(tmp_path.iterdir()) == []


def test_post_jobs_rejects_too_many_zip_members_without_creating_job(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    app = create_app(repository=repo, storage=StorageService(tmp_path), max_zip_members=1)
    client = TestClient(app)

    response = client.post(
        "/jobs",
        files={"file": ("patient.zip", make_zip_bytes_with_members(2), "application/zip")},
    )

    assert response.status_code == 413
    assert mongo_db.jobs.count_documents({}) == 0
    assert list(tmp_path.iterdir()) == []


def test_post_jobs_rejects_uncompressed_zip_larger_than_limit_without_creating_job(
    tmp_path: Path, mongo_db
) -> None:
    repo = MongoRepository(mongo_db)
    app = create_app(repository=repo, storage=StorageService(tmp_path), max_uncompressed_bytes=4)
    client = TestClient(app)

    response = client.post(
        "/jobs",
        files={"file": ("patient.zip", make_zip_bytes(), "application/zip")},
    )

    assert response.status_code == 413
    assert mongo_db.jobs.count_documents({}) == 0
    assert list(tmp_path.iterdir()) == []


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


def test_get_job_serializes_public_artifacts_and_events(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    repo.create_job("job-1", "patient.zip", Path("/z"), Path("/i"), Path("/r"))
    repo.add_artifact("job-1", ArtifactKind.RESEARCH_MARKDOWN, Path("/r/research.md"), "abc")
    repo.add_event("job-1", "worker-1", "claimed", "info", "Claimed job")
    app = create_app(repository=repo, storage=StorageService(tmp_path))
    client = TestClient(app)

    response = client.get("/jobs/job-1")

    assert response.status_code == 200
    payload = response.json()
    artifact = payload["artifacts"][0]
    event = payload["events"][0]
    assert "id" in artifact
    assert "_id" not in artifact
    assert isinstance(artifact["created_at"], str)
    assert "id" in event
    assert "_id" not in event
    assert isinstance(event["created_at"], str)


def test_get_missing_job_returns_404(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    app = create_app(repository=repo, storage=StorageService(tmp_path))
    client = TestClient(app)

    response = client.get("/jobs/missing")

    assert response.status_code == 404


def test_resume_waiting_login_job(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    repo.create_job("job-1", "patient.zip", Path("/z"), Path("/i"), Path("/r"))
    repo.set_job_waiting_login("job-1", "worker-1", ":21", "login required")
    app = create_app(repository=repo, storage=StorageService(tmp_path))
    client = TestClient(app)

    response = client.post("/jobs/job-1/resume")

    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_resume_missing_job_returns_404(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    app = create_app(repository=repo, storage=StorageService(tmp_path))
    client = TestClient(app)

    response = client.post("/jobs/missing/resume")

    assert response.status_code == 404


def test_get_workers(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    repo.upsert_worker("worker-1", ":21", 5921, Path("/profile"), status=WorkerStatus.IDLE, automation_mode="playwright")
    app = create_app(repository=repo, storage=StorageService(tmp_path))
    client = TestClient(app)

    response = client.get("/workers")

    assert response.status_code == 200
    assert response.json()[0]["worker_id"] == "worker-1"


def test_create_app_rejects_partial_dependency_injection(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)

    with pytest.raises(ValueError, match="repository and storage must be provided together"):
        create_app(repository=repo)

    with pytest.raises(ValueError, match="repository and storage must be provided together"):
        create_app(storage=StorageService(tmp_path))
