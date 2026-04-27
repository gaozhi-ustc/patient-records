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


def test_claim_queued_job_ties_are_ordered_by_id(mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    job_b = repo.create_job("job-b", "b.zip", Path("/z-b"), Path("/i-b"), Path("/r-b"))
    repo.create_job("job-a", "a.zip", Path("/z-a"), Path("/i-a"), Path("/r-a"))
    mongo_db.jobs.update_many({}, {"$set": {"created_at": job_b["created_at"]}})

    claimed = repo.claim_next_job(worker_id="worker-1", display=":21")

    assert claimed is not None
    assert claimed["_id"] == "job-a"


def test_resume_waiting_login_job(mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    repo.create_job("job-1", "a.zip", Path("/z"), Path("/i"), Path("/r"))
    repo.claim_next_job("worker-1", ":21")
    repo.set_job_waiting_login("job-1", "worker-1", ":21", "login required")

    resumed = repo.resume_waiting_login_job("job-1")

    assert resumed["status"] == JobStatus.QUEUED.value
    assert resumed["worker_id"] is None
    assert resumed["display"] is None
    assert resumed["started_at"] is None
    assert resumed["login_required"] is False
    assert resumed["error"] is None


def test_failed_job_status_sets_finished_at(mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    repo.create_job("job-1", "a.zip", Path("/z"), Path("/i"), Path("/r"))

    failed = repo.update_job_status("job-1", JobStatus.FAILED, "failed", error="boom")

    assert failed is not None
    assert failed["status"] == JobStatus.FAILED.value
    assert failed["finished_at"] is not None


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
