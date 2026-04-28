import argparse
import os

from app.config import Settings
from app.db.mongo import create_mongo_database, ensure_indexes
from app.db.repositories import MongoRepository
from app.storage import StorageService
from app.worker.desktop import DesktopManager
from app.worker.runner import WorkerRunner
from app.worker.rpa.base import NotebookLMWorkflow
from app.worker.rpa.playwright_adapter import PlaywrightNotebookLMSession
from app.worker.rpa.visual_adapter import VisualNotebookLMSession


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a NotebookLM RPA worker")
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--display", default=None)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args(argv)


def display_to_vnc_port(display: str) -> int:
    return 5900 + int(display.removeprefix(":").split(".", 1)[0])


def display_to_remote_debugging_port(display: str) -> int:
    return 9220 + int(display.removeprefix(":").split(".", 1)[0])


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    settings = Settings()
    worker_id = args.worker_id or settings.worker_id
    display = args.display or settings.display
    vnc_port = display_to_vnc_port(display) if args.display else settings.vnc_port
    automation_mode = settings.automation_mode.lower()
    chrome_user_data_dir = settings.chrome_user_data_dir or settings.worker_root / worker_id / "chrome-profile"
    downloads_dir = settings.worker_root / worker_id / "downloads"
    remote_debugging_port = settings.chrome_remote_debugging_port or display_to_remote_debugging_port(display)
    proxy_url = (
        os.environ.get("all_proxy")
        or os.environ.get("http_proxy")
        or os.environ.get("https_proxy")
        or os.environ.get("ALL_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("HTTPS_PROXY")
    )
    os.environ["DISPLAY"] = display
    db = create_mongo_database(settings)
    ensure_indexes(db)
    repository = MongoRepository(db)
    storage = StorageService(settings.data_root, settings.supported_upload_extensions)
    desktop = DesktopManager(
        display,
        vnc_port,
        chrome_user_data_dir,
        proxy_url=proxy_url,
        downloads_dir=downloads_dir,
        remote_debugging_port=remote_debugging_port if automation_mode == "visual" else None,
    )
    desktop.ensure_vnc()
    if automation_mode == "visual":
        desktop.launch_chrome(settings.notebooklm_url)

    def workflow_factory() -> NotebookLMWorkflow:
        if automation_mode == "visual":
            session = VisualNotebookLMSession(
                display=display,
                screenshots_dir=settings.worker_root / worker_id / "screenshots",
                downloads_dir=downloads_dir,
                notebooklm_url=settings.notebooklm_url,
                remote_debugging_port=remote_debugging_port,
            )
        else:
            session = PlaywrightNotebookLMSession(
                user_data_dir=chrome_user_data_dir,
                notebooklm_url=settings.notebooklm_url,
                supported_extensions=settings.supported_upload_extensions,
                downloads_dir=downloads_dir,
                headless=False,
            )
        return NotebookLMWorkflow(session=session)

    runner = WorkerRunner(
        repository=repository,
        storage=storage,
        worker_id=worker_id,
        display=display,
        vnc_port=vnc_port,
        chrome_user_data_dir=chrome_user_data_dir,
        workflow_factory=workflow_factory,
        poll_interval_seconds=settings.poll_interval_seconds,
        automation_mode=automation_mode,
    )
    if args.once:
        runner.process_once()
    else:
        runner.run_forever()


if __name__ == "__main__":
    main()
