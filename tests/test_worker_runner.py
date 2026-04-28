from pathlib import Path

from app.db.repositories import MongoRepository
from app.domain import ArtifactKind, JobStatus, WorkerStatus
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


class LoginThenCompletingWorkflow:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    def run(self, files: list[Path], result_dir: Path, progress=None):
        self.calls += 1
        if self.calls == 1:
            raise LoginRequired("login required")
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

    def close(self) -> None:
        self.closed = True


class FailingWorkflow:
    def run(self, files: list[Path], result_dir: Path, progress=None):
        raise RuntimeError("workflow exploded")


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
    artifacts = repo.list_artifacts("job-1")
    assert {artifact["kind"] for artifact in artifacts} == {"research_markdown", "slide_pdf"}
    assert all(artifact["sha256"] for artifact in artifacts)
    events = repo.list_events("job-1")
    assert {"uploading_sources", "researching", "generating_ppt", "downloading_results"}.issubset(
        {event["step"] for event in events}
    )


def test_artifact_kind_classifies_native_downloads(tmp_path: Path, mongo_db) -> None:
    runner = WorkerRunner(
        repository=MongoRepository(mongo_db),
        storage=StorageService(tmp_path),
        worker_id="worker-1",
        display=":21",
        vnc_port=5921,
        chrome_user_data_dir=tmp_path / "profile",
        workflow_factory=lambda: CompletingWorkflow(),
    )

    assert runner._artifact_kind(tmp_path / "downloads" / "deck.pptx") == ArtifactKind.NATIVE_DOWNLOAD
    assert runner._artifact_kind(tmp_path / "results" / "deck.pptx") == ArtifactKind.NATIVE_DOWNLOAD


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

    processed = runner.process_once()

    job = repo.get_job("job-1")
    worker = repo.list_workers()[0]
    assert processed is False
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


def test_process_once_does_not_claim_new_job_while_waiting_login(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    storage = StorageService(tmp_path, supported_extensions=(".txt",))
    first_paths = storage.prepare_job_paths("job-1", "patient.zip")
    first_paths.zip_path.write_bytes(b"not-used")
    (first_paths.input_dir / "record.txt").write_text("hello", encoding="utf-8")
    repo.create_job("job-1", "patient.zip", first_paths.zip_path, first_paths.input_dir, first_paths.result_dir)
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
    second_paths = storage.prepare_job_paths("job-2", "patient.zip")
    second_paths.zip_path.write_bytes(b"not-used")
    (second_paths.input_dir / "record.txt").write_text("hello", encoding="utf-8")
    repo.create_job("job-2", "patient.zip", second_paths.zip_path, second_paths.input_dir, second_paths.result_dir)
    processed = runner.process_once()

    second_job = repo.get_job("job-2")
    worker = repo.list_workers()[0]
    assert processed is False
    assert second_job["status"] == JobStatus.QUEUED.value
    assert worker["status"] == WorkerStatus.WAITING_LOGIN.value
    assert worker["current_job_id"] == "job-1"
    assert worker["login_status"] == "required"


def test_process_once_claims_resumed_waiting_login_job(tmp_path: Path, mongo_db) -> None:
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
    repo.resume_waiting_login_job("job-1")
    resumed_runner = WorkerRunner(
        repository=repo,
        storage=storage,
        worker_id="worker-1",
        display=":21",
        vnc_port=5921,
        chrome_user_data_dir=tmp_path / "profile",
        workflow_factory=lambda: CompletingWorkflow(),
        extract_zip=False,
    )
    processed = resumed_runner.process_once()

    job = repo.get_job("job-1")
    worker = repo.list_workers()[0]
    assert processed is True
    assert job["status"] == JobStatus.COMPLETED.value
    assert worker["status"] == WorkerStatus.IDLE.value
    assert worker["current_job_id"] is None


def test_process_once_reuses_waiting_login_workflow_for_resume(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    storage = StorageService(tmp_path, supported_extensions=(".txt",))
    paths = storage.prepare_job_paths("job-1", "patient.zip")
    paths.zip_path.write_bytes(b"not-used")
    (paths.input_dir / "record.txt").write_text("hello", encoding="utf-8")
    repo.create_job("job-1", "patient.zip", paths.zip_path, paths.input_dir, paths.result_dir)
    created_workflows: list[LoginThenCompletingWorkflow] = []

    def workflow_factory() -> LoginThenCompletingWorkflow:
        workflow = LoginThenCompletingWorkflow()
        created_workflows.append(workflow)
        return workflow

    runner = WorkerRunner(
        repository=repo,
        storage=storage,
        worker_id="worker-1",
        display=":21",
        vnc_port=5921,
        chrome_user_data_dir=tmp_path / "profile",
        workflow_factory=workflow_factory,
        extract_zip=False,
    )

    first_processed = runner.process_once()
    repo.resume_waiting_login_job("job-1")
    second_processed = runner.process_once()

    job = repo.get_job("job-1")
    assert first_processed is False
    assert second_processed is True
    assert len(created_workflows) == 1
    assert created_workflows[0].calls == 2
    assert created_workflows[0].closed is True
    assert job["status"] == JobStatus.COMPLETED.value


def test_process_once_marks_job_failed_when_workflow_raises(tmp_path: Path, mongo_db) -> None:
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
        workflow_factory=lambda: FailingWorkflow(),
        extract_zip=False,
    )

    processed = runner.process_once()

    job = repo.get_job("job-1")
    worker = repo.list_workers()[0]
    failed_events = [event for event in repo.list_events("job-1") if event["step"] == "failed"]
    assert processed is True
    assert job["status"] == JobStatus.FAILED.value
    assert job["error"] == "workflow exploded"
    assert job["finished_at"] is not None
    assert worker["status"] == WorkerStatus.IDLE.value
    assert worker["current_job_id"] is None
    assert failed_events
    assert failed_events[0]["level"] == "error"
