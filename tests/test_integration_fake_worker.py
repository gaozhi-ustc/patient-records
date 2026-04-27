import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.db.repositories import MongoRepository
from app.storage import StorageService
from app.worker.rpa.base import RpaArtifacts, RpaWorkflowResult
from app.worker.runner import WorkerRunner


def make_zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("record.txt", "hello")
    return buffer.getvalue()


class CompletingWorkflow:
    def run(self, files: list[Path], result_dir: Path, progress=None) -> RpaWorkflowResult:
        assert [path.name for path in files] == ["record.txt"]
        if progress is not None:
            progress("uploading_sources")
            progress("researching")
            progress("generating_ppt")
            progress("downloading_results")
        research = result_dir / "research.md"
        slide = result_dir / "slide_deck.pdf"
        research.write_text("research for record.txt", encoding="utf-8")
        slide.write_bytes(b"%PDF-1.4\n")
        return RpaWorkflowResult(
            notebook_id="notebook-123",
            notebook_url="https://notebooklm.google.com/notebook/notebook-123",
            artifacts=RpaArtifacts(paths=[research, slide]),
        )


def test_api_to_fake_worker_to_api_status(tmp_path: Path, mongo_db) -> None:
    repo = MongoRepository(mongo_db)
    storage = StorageService(tmp_path, supported_extensions=(".txt",))
    app = create_app(repository=repo, storage=storage)
    client = TestClient(app)

    create_response = client.post(
        "/jobs",
        files={"file": ("patient.zip", make_zip_bytes(), "application/zip")},
    )
    assert create_response.status_code == 200
    job_id = create_response.json()["job_id"]

    runner = WorkerRunner(
        repository=repo,
        storage=storage,
        worker_id="worker-1",
        display=":21",
        vnc_port=5921,
        chrome_user_data_dir=tmp_path / "profile",
        workflow_factory=lambda: CompletingWorkflow(),
    )

    processed = runner.process_once()

    status_response = client.get(f"/jobs/{job_id}")
    assert processed is True
    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["status"] == "completed"
    assert payload["notebook_id"] == "notebook-123"
    assert {artifact["kind"] for artifact in payload["artifacts"]} == {"research_markdown", "slide_pdf"}
