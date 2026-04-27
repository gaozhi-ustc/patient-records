from pathlib import Path
import subprocess

from app.worker.rpa import visual_adapter
from app.worker.rpa.visual_adapter import DesktopAutomation, VisualNotebookLMSession


class FakeAutomation:
    def __init__(self, current_url: str = "https://notebooklm.google.com/notebook/abc123") -> None:
        self.current_url = current_url
        self.commands: list[tuple[str, object]] = []
        self.clipboard = ""

    def focus_chrome(self) -> None:
        self.commands.append(("focus_chrome", None))

    def hotkey(self, *keys: str) -> None:
        self.commands.append(("hotkey", keys))

    def press(self, key: str) -> None:
        self.commands.append(("press", key))

    def click(self, x: int, y: int) -> None:
        self.commands.append(("click", (x, y)))

    def paste_text(self, text: str) -> None:
        self.clipboard = text
        self.commands.append(("paste_text", text))

    def copy_selection(self) -> str:
        self.commands.append(("copy_selection", None))
        return self.current_url

    def screenshot(self, path: Path) -> None:
        self.commands.append(("screenshot", path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")


def test_ensure_logged_in_returns_false_on_google_login_url() -> None:
    automation = FakeAutomation("https://accounts.google.com/signin/v2")
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=Path("/tmp/screenshots"),
        downloads_dir=Path("/tmp/downloads"),
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    assert session.ensure_logged_in() is False
    assert ("paste_text", "https://notebooklm.google.com") in automation.commands


def test_create_new_notebook_copies_url_and_extracts_notebook_id() -> None:
    automation = FakeAutomation("https://notebooklm.google.com/notebook/notebook-123")
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=Path("/tmp/screenshots"),
        downloads_dir=Path("/tmp/downloads"),
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    notebook_id, notebook_url = session.create_new_notebook()

    assert notebook_id == "notebook-123"
    assert notebook_url == "https://notebooklm.google.com/notebook/notebook-123"
    assert ("press", "Escape") in automation.commands


def test_upload_sources_selects_common_parent_directory(tmp_path: Path) -> None:
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.docx"
    first.write_text("a")
    second.write_text("b")
    automation = FakeAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    count = session.upload_sources([first, second])

    assert count == 2
    assert ("paste_text", str(tmp_path)) in automation.commands
    assert ("hotkey", ("ctrl", "a")) in automation.commands
    assert ("press", "Return") in automation.commands


def test_desktop_automation_falls_back_to_tk_clipboard(monkeypatch) -> None:
    clipboard: dict[str, str] = {}

    class FakeTk:
        def withdraw(self) -> None:
            return None

        def clipboard_clear(self) -> None:
            clipboard["value"] = ""

        def clipboard_append(self, text: str) -> None:
            clipboard["value"] = text

        def clipboard_get(self) -> str:
            return clipboard["value"]

        def update(self) -> None:
            return None

        def destroy(self) -> None:
            return None

    monkeypatch.setattr(visual_adapter.shutil, "which", lambda name: None)
    monkeypatch.setattr(visual_adapter, "Tk", FakeTk)
    automation = DesktopAutomation(":1")

    automation._set_clipboard("中文路径")

    assert automation._get_clipboard() == "中文路径"


def test_focus_chrome_retries_until_window_appears(monkeypatch) -> None:
    automation = DesktopAutomation(":1")
    attempts = []

    def fake_xdotool(*args: str) -> None:
        attempts.append(args)
        if len(attempts) == 1:
            raise subprocess.CalledProcessError(1, ["xdotool", *args])

    monkeypatch.setattr(automation, "_xdotool", fake_xdotool)
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)

    automation.focus_chrome(timeout_seconds=1)

    assert len(attempts) == 2
