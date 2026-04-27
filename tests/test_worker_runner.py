from pathlib import Path

from app.db.repositories import MongoRepository
from app.domain import JobStatus, WorkerStatus
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


def test_process_once_preserves_waiting_login_when_no_job_is_available(tmp_path: Path, mongo_db) -> None:
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
    processed = runner.process_once()

    worker = repo.list_workers()[0]
    assert processed is False
    assert worker["status"] == WorkerStatus.WAITING_LOGIN.value
    assert worker["current_job_id"] == "job-1"
    assert worker["login_status"] == "required"
