from pathlib import Path

from app.worker import main as worker_main
from app.worker.main import display_to_vnc_port, parse_args


def test_parse_args_accepts_worker_id_and_display() -> None:
    args = parse_args(["--worker-id", "worker-2", "--display", ":22", "--once"])

    assert args.worker_id == "worker-2"
    assert args.display == ":22"
    assert args.once is True


def test_display_to_vnc_port_derives_port_from_display_number() -> None:
    assert display_to_vnc_port(":21") == 5921


def test_main_uses_cli_worker_id_for_default_chrome_profile(monkeypatch) -> None:
    calls: dict[str, object] = {}
    monkeypatch.delenv("DISPLAY", raising=False)

    class FakeSettings:
        mongo_uri = "mongodb://example.invalid:27017"
        database_name = "patient_records"
        data_root = Path("/tmp/data")
        worker_root = Path("/tmp/workers")
        worker_id = "worker-1"
        display = ":21"
        vnc_port = 5921
        chrome_user_data_dir = None
        automation_mode = "playwright"
        notebooklm_url = "https://notebooklm.example"
        poll_interval_seconds = 2.0
        supported_upload_extensions = (".pdf",)

        @property
        def resolved_chrome_user_data_dir(self):
            return self.worker_root / self.worker_id / "chrome-profile"

    class FakeDesktopManager:
        def __init__(self, display, vnc_port, chrome_user_data_dir):
            calls["desktop"] = {
                "display": display,
                "vnc_port": vnc_port,
                "chrome_user_data_dir": chrome_user_data_dir,
            }

        def ensure_vnc(self):
            calls["ensure_vnc"] = True

        def launch_chrome(self, url):
            raise AssertionError("main should not launch unmanaged Chrome")

    class FakePlaywrightNotebookLMSession:
        def __init__(
            self,
            user_data_dir,
            notebooklm_url,
            supported_extensions,
            downloads_dir,
            headless,
        ):
            calls["session"] = {
                "user_data_dir": user_data_dir,
                "notebooklm_url": notebooklm_url,
                "supported_extensions": supported_extensions,
                "downloads_dir": downloads_dir,
                "headless": headless,
            }

    class FakeWorkerRunner:
        def __init__(self, **kwargs):
            calls["runner"] = kwargs

        def process_once(self):
            calls["process_once"] = True
            calls["runner"]["workflow_factory"]()

    monkeypatch.setattr(worker_main, "Settings", FakeSettings)
    monkeypatch.setattr(worker_main, "create_mongo_database", lambda settings: "db")
    monkeypatch.setattr(worker_main, "ensure_indexes", lambda db: calls.setdefault("indexed_db", db))
    monkeypatch.setattr(worker_main, "MongoRepository", lambda db: ("repository", db))
    monkeypatch.setattr(worker_main, "StorageService", lambda data_root, extensions: ("storage", data_root, extensions))
    monkeypatch.setattr(worker_main, "DesktopManager", FakeDesktopManager)
    monkeypatch.setattr(worker_main, "PlaywrightNotebookLMSession", FakePlaywrightNotebookLMSession)
    monkeypatch.setattr(worker_main, "NotebookLMWorkflow", lambda session: ("workflow", session))
    monkeypatch.setattr(worker_main, "WorkerRunner", FakeWorkerRunner)

    worker_main.main(["--worker-id", "worker-2", "--display", ":22", "--once"])

    expected_profile = Path("/tmp/workers/worker-2/chrome-profile")
    assert calls["desktop"]["display"] == ":22"
    assert calls["desktop"]["vnc_port"] == 5922
    assert calls["desktop"]["chrome_user_data_dir"] == expected_profile
    assert calls["runner"]["worker_id"] == "worker-2"
    assert calls["runner"]["display"] == ":22"
    assert calls["runner"]["vnc_port"] == 5922
    assert calls["runner"]["chrome_user_data_dir"] == expected_profile
    assert calls["session"]["user_data_dir"] == expected_profile
    assert calls["session"]["downloads_dir"] == Path("/tmp/workers/worker-2/downloads")
    assert calls["process_once"] is True
    assert calls["ensure_vnc"] is True
    assert worker_main.os.environ["DISPLAY"] == ":22"
