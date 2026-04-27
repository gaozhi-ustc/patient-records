import argparse

from app.config import Settings
from app.db.mongo import create_mongo_database, ensure_indexes
from app.db.repositories import MongoRepository
from app.storage import StorageService
from app.worker.desktop import DesktopManager
from app.worker.runner import WorkerRunner
from app.worker.rpa.base import NotebookLMWorkflow
from app.worker.rpa.playwright_adapter import PlaywrightNotebookLMSession


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a NotebookLM RPA worker")
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--display", default=None)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    settings = Settings()
    worker_id = args.worker_id or settings.worker_id
    display = args.display or settings.display
    db = create_mongo_database(settings)
    ensure_indexes(db)
    repository = MongoRepository(db)
    storage = StorageService(settings.data_root, settings.supported_upload_extensions)
    desktop = DesktopManager(display, settings.vnc_port, settings.resolved_chrome_user_data_dir)
    desktop.ensure_vnc()
    desktop.launch_chrome(settings.notebooklm_url)

    def workflow_factory() -> NotebookLMWorkflow:
        session = PlaywrightNotebookLMSession(
            user_data_dir=settings.resolved_chrome_user_data_dir,
            notebooklm_url=settings.notebooklm_url,
            supported_extensions=settings.supported_upload_extensions,
            downloads_dir=settings.worker_root / worker_id / "downloads",
            headless=False,
        )
        return NotebookLMWorkflow(session=session)

    runner = WorkerRunner(
        repository=repository,
        storage=storage,
        worker_id=worker_id,
        display=display,
        vnc_port=settings.vnc_port,
        chrome_user_data_dir=settings.resolved_chrome_user_data_dir,
        workflow_factory=workflow_factory,
        poll_interval_seconds=settings.poll_interval_seconds,
        automation_mode=settings.automation_mode,
    )
    if args.once:
        runner.process_once()
    else:
        runner.run_forever()


if __name__ == "__main__":
    main()
