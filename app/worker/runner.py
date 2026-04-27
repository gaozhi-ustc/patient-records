import time
from pathlib import Path
from typing import Callable

from app.db.repositories import MongoRepository
from app.domain import ArtifactKind, JobStatus, WorkerStatus
from app.storage import JobPaths, StorageService
from app.worker.rpa.base import LoginRequired, NotebookLMWorkflow, RpaError


class WorkerRunner:
    def __init__(
        self,
        repository: MongoRepository,
        storage: StorageService,
        worker_id: str,
        display: str,
        vnc_port: int,
        chrome_user_data_dir: Path,
        workflow_factory: Callable[[], NotebookLMWorkflow],
        poll_interval_seconds: float = 2.0,
        automation_mode: str = "playwright",
        extract_zip: bool = True,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.worker_id = worker_id
        self.display = display
        self.vnc_port = vnc_port
        self.chrome_user_data_dir = chrome_user_data_dir
        self.workflow_factory = workflow_factory
        self.poll_interval_seconds = poll_interval_seconds
        self.automation_mode = automation_mode
        self.extract_zip_enabled = extract_zip
        self._waiting_login_workflows: dict[str, NotebookLMWorkflow] = {}

    def process_once(self) -> bool:
        current_worker = self.repository.get_worker(self.worker_id)
        if current_worker is not None and current_worker["status"] == WorkerStatus.WAITING_LOGIN.value:
            current_job_id = current_worker.get("current_job_id")
            current_job = self.repository.get_job(current_job_id) if current_job_id else None
            if current_job is not None and current_job["status"] == JobStatus.WAITING_LOGIN.value:
                return False
        self._set_worker_idle()
        job = self.repository.claim_next_job(self.worker_id, self.display)
        if job is None:
            return False
        job_id = job["_id"]
        self.repository.upsert_worker(
            self.worker_id,
            self.display,
            self.vnc_port,
            self.chrome_user_data_dir,
            WorkerStatus.BUSY,
            self.automation_mode,
            current_job_id=job_id,
        )
        workflow: NotebookLMWorkflow | None = None
        try:
            files = self._prepare_files(job)
            workflow = self._waiting_login_workflows.pop(job_id, None) or self.workflow_factory()
            result = workflow.run(
                files=files,
                result_dir=Path(job["result_dir"]),
                progress=lambda step: self._record_progress(job_id, step),
            )
            self._close_workflow(workflow)
            workflow = None
            for artifact_path in result.artifacts.paths:
                kind = ArtifactKind.SCREENSHOT
                if artifact_path.name == "research.md":
                    kind = ArtifactKind.RESEARCH_MARKDOWN
                if artifact_path.name == "slide_deck.pdf":
                    kind = ArtifactKind.SLIDE_PDF
                sha256 = self.storage.sha256_file(artifact_path)
                self.repository.add_artifact(job_id, kind, artifact_path, sha256)
            self.repository.update_job_status(
                job_id,
                JobStatus.COMPLETED,
                "completed",
                extra={"notebook_id": result.notebook_id, "notebook_url": result.notebook_url},
            )
            self.repository.add_event(job_id, self.worker_id, "completed", "info", "Job completed")
            self._set_worker_idle()
            return True
        except LoginRequired as exc:
            if workflow is not None:
                self._waiting_login_workflows[job_id] = workflow
            self.repository.set_job_waiting_login(job_id, self.worker_id, self.display, str(exc))
            self.repository.upsert_worker(
                self.worker_id,
                self.display,
                self.vnc_port,
                self.chrome_user_data_dir,
                WorkerStatus.WAITING_LOGIN,
                self.automation_mode,
                current_job_id=job_id,
                login_status="required",
            )
            return False
        except Exception as exc:
            if workflow is not None:
                self._close_workflow(workflow)
            self.repository.update_job_status(job_id, JobStatus.FAILED, "failed", error=str(exc))
            self.repository.add_event(job_id, self.worker_id, "failed", "error", str(exc))
            self._set_worker_idle()
            return True

    def run_forever(self) -> None:
        while True:
            processed = self.process_once()
            if not processed:
                time.sleep(self.poll_interval_seconds)

    def _prepare_files(self, job: dict) -> list[Path]:
        paths = JobPaths(
            job_dir=Path(job["zip_path"]).parents[1],
            upload_dir=Path(job["zip_path"]).parent,
            input_dir=Path(job["input_dir"]),
            result_dir=Path(job["result_dir"]),
            zip_path=Path(job["zip_path"]),
        )
        if self.extract_zip_enabled:
            files = self.storage.extract_zip(paths)
            if not files:
                raise RpaError("No uploadable files found")
            return files
        files = [path for path in paths.input_dir.rglob("*") if path.is_file()]
        if not files:
            raise RpaError("No uploadable files found")
        return sorted(files)

    def _record_progress(self, job_id: str, step: str) -> None:
        status_by_step = {
            "uploading_sources": JobStatus.UPLOADING_SOURCES,
            "researching": JobStatus.RESEARCHING,
            "generating_ppt": JobStatus.GENERATING_PPT,
            "downloading_results": JobStatus.DOWNLOADING_RESULTS,
        }
        status = status_by_step[step]
        self.repository.update_job_status(job_id, status, step)
        self.repository.add_event(job_id, self.worker_id, step, "info", f"RPA step: {step}")

    def _set_worker_idle(self) -> None:
        self.repository.upsert_worker(
            self.worker_id,
            self.display,
            self.vnc_port,
            self.chrome_user_data_dir,
            WorkerStatus.IDLE,
            self.automation_mode,
            current_job_id=None,
        )

    def _close_workflow(self, workflow: NotebookLMWorkflow) -> None:
        close = getattr(workflow, "close", None)
        if callable(close):
            close()
