import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from tkinter import Tk
from urllib.parse import urlparse

from app.worker.rpa.base import RpaArtifacts, RpaError


@dataclass(frozen=True)
class VisualCoordinates:
    create_notebook_primary: tuple[int, int] = (960, 96)
    create_notebook_fallback: tuple[int, int] = (1730, 96)
    add_source: tuple[int, int] = (155, 170)
    upload_source: tuple[int, int] = (420, 360)
    web_search_sources: tuple[int, int] = (255, 650)
    fast_research: tuple[int, int] = (310, 720)
    deep_research: tuple[int, int] = (315, 770)
    slide_deck: tuple[int, int] = (1540, 300)
    language_menu: tuple[int, int] = (1680, 300)
    simplified_chinese: tuple[int, int] = (1530, 430)
    download_button: tuple[int, int] = (1710, 300)


class DesktopAutomation:
    def __init__(self, display: str) -> None:
        self.display = display

    def focus_chrome(self, timeout_seconds: float = 15.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        last_error: subprocess.CalledProcessError | None = None
        while time.monotonic() <= deadline:
            try:
                self._xdotool("search", "--onlyvisible", "--class", "chrome", "windowactivate", "--sync")
                return
            except subprocess.CalledProcessError as error:
                last_error = error
                time.sleep(0.5)
        raise RpaError("Chrome window was not found for visual automation") from last_error

    def hotkey(self, *keys: str) -> None:
        self._xdotool("key", "+".join(keys))

    def press(self, key: str) -> None:
        self._xdotool("key", key)

    def click(self, x: int, y: int) -> None:
        self._xdotool("mousemove", str(x), str(y), "click", "1")

    def paste_text(self, text: str) -> None:
        self._set_clipboard(text)
        self.hotkey("ctrl", "v")

    def copy_selection(self) -> str:
        self.hotkey("ctrl", "c")
        time.sleep(0.2)
        return self._get_clipboard()

    def screenshot(self, path: Path) -> None:
        import pyautogui

        path.parent.mkdir(parents=True, exist_ok=True)
        pyautogui.screenshot(str(path))

    def _xdotool(self, *args: str) -> None:
        if shutil.which("xdotool") is None:
            raise RpaError("xdotool is required for visual automation")
        subprocess.run(["xdotool", *args], check=True, env={"DISPLAY": self.display})

    def _set_clipboard(self, text: str) -> None:
        if shutil.which("xclip") is not None:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text,
                text=True,
                check=True,
                env={"DISPLAY": self.display},
            )
            return
        if shutil.which("xsel") is not None:
            subprocess.run(
                ["xsel", "--clipboard", "--input"],
                input=text,
                text=True,
                check=True,
                env={"DISPLAY": self.display},
            )
            return
        self._tk_set_clipboard(text)

    def _get_clipboard(self) -> str:
        if shutil.which("xclip") is not None:
            return subprocess.check_output(
                ["xclip", "-selection", "clipboard", "-o"],
                text=True,
                env={"DISPLAY": self.display},
            )
        if shutil.which("xsel") is not None:
            return subprocess.check_output(
                ["xsel", "--clipboard", "--output"],
                text=True,
                env={"DISPLAY": self.display},
            )
        return self._tk_get_clipboard()

    def _tk_set_clipboard(self, text: str) -> None:
        root = Tk()
        try:
            root.withdraw()
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update()
        finally:
            root.destroy()

    def _tk_get_clipboard(self) -> str:
        root = Tk()
        try:
            root.withdraw()
            return root.clipboard_get()
        finally:
            root.destroy()


class VisualNotebookLMSession:
    def __init__(
        self,
        display: str,
        screenshots_dir: Path,
        downloads_dir: Path,
        notebooklm_url: str,
        automation: DesktopAutomation | None = None,
        coordinates: VisualCoordinates = VisualCoordinates(),
        delay_seconds: float = 1.0,
    ) -> None:
        self.display = display
        self.screenshots_dir = screenshots_dir
        self.downloads_dir = downloads_dir
        self.notebooklm_url = notebooklm_url
        self.automation = automation or DesktopAutomation(display)
        self.coordinates = coordinates
        self.delay_seconds = delay_seconds

    def ensure_logged_in(self) -> bool:
        self._open_url(self.notebooklm_url)
        current_url = self._copy_current_url().lower()
        self._screenshot("ensure_logged_in")
        return "accounts.google.com" not in current_url and "signin" not in current_url

    def create_new_notebook(self) -> tuple[str, str]:
        self.automation.focus_chrome()
        self._click(self.coordinates.create_notebook_primary)
        self._sleep()
        self._click(self.coordinates.create_notebook_fallback)
        self._sleep()
        self.automation.press("Escape")
        self._sleep()
        notebook_url = self._copy_current_url()
        notebook_id = self._extract_notebook_id(notebook_url)
        self._screenshot("create_new_notebook")
        return notebook_id, notebook_url

    def upload_sources(self, files: list[Path]) -> int:
        uploadable = [path for path in files if path.is_file()]
        if not uploadable:
            raise RpaError("No uploadable files found")
        parent_dir = self._common_parent(uploadable)
        self.automation.focus_chrome()
        self._click(self.coordinates.add_source)
        self._sleep()
        self._click(self.coordinates.upload_source)
        self._sleep()
        self.automation.hotkey("ctrl", "l")
        self.automation.paste_text(str(parent_dir))
        self.automation.press("Return")
        self._sleep()
        self.automation.hotkey("ctrl", "a")
        self.automation.press("Return")
        self._screenshot("upload_sources")
        return len(uploadable)

    def start_deep_research(self, prompt: str) -> None:
        self.automation.focus_chrome()
        self._click(self.coordinates.web_search_sources)
        self._sleep()
        self._click(self.coordinates.fast_research)
        self._sleep()
        self._click(self.coordinates.deep_research)
        self._sleep()
        self.automation.paste_text(prompt)
        self.automation.press("Return")
        self._screenshot("start_deep_research")

    def wait_for_research(self) -> None:
        time.sleep(max(self.delay_seconds, 60))
        self._screenshot("wait_for_research")

    def generate_slide_deck(self, language: str) -> None:
        self.automation.focus_chrome()
        self._click(self.coordinates.language_menu)
        self._sleep()
        if language == "简体中文":
            self._click(self.coordinates.simplified_chinese)
        self._sleep()
        self._click(self.coordinates.slide_deck)
        self._screenshot("generate_slide_deck")

    def wait_for_slide_deck(self) -> None:
        time.sleep(max(self.delay_seconds, 60))
        self._screenshot("wait_for_slide_deck")

    def save_results(self, result_dir: Path) -> RpaArtifacts:
        result_dir.mkdir(parents=True, exist_ok=True)
        self.automation.focus_chrome()
        self.automation.hotkey("ctrl", "a")
        copied_text = self.automation.copy_selection()
        research_path = result_dir / "research.md"
        research_path.write_text(copied_text, encoding="utf-8")
        self._click(self.coordinates.download_button)
        self._sleep()
        screenshot_path = result_dir / "screenshots" / "final.png"
        self.automation.screenshot(screenshot_path)
        artifacts = [research_path, screenshot_path]
        artifacts.extend(sorted(self.downloads_dir.glob("*")))
        return RpaArtifacts(paths=artifacts)

    def close(self) -> None:
        return None

    def _open_url(self, url: str) -> None:
        self.automation.focus_chrome()
        self.automation.hotkey("ctrl", "l")
        self.automation.paste_text(url)
        self.automation.press("Return")
        self._sleep()

    def _copy_current_url(self) -> str:
        self.automation.focus_chrome()
        self.automation.hotkey("ctrl", "l")
        return self.automation.copy_selection()

    def _click(self, point: tuple[int, int]) -> None:
        self.automation.click(point[0], point[1])

    def _screenshot(self, name: str) -> None:
        self.automation.screenshot(self.screenshots_dir / f"{name}.png")

    def _sleep(self) -> None:
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)

    def _extract_notebook_id(self, url: str) -> str:
        parts = [part for part in urlparse(url).path.split("/") if part]
        if not parts:
            raise RpaError(f"Cannot extract notebook_id from URL: {url}")
        return parts[-1]

    def _common_parent(self, files: list[Path]) -> Path:
        parents = {path.parent for path in files}
        if len(parents) != 1:
            raise RpaError("Visual upload currently requires all files to be in one directory")
        return parents.pop()
