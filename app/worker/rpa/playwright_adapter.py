from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, sync_playwright

from app.worker.rpa.base import RpaArtifacts, RpaError


def extract_notebook_id(url: str) -> str:
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    if not path_parts:
        raise RpaError(f"Cannot extract notebook_id from URL: {url}")
    return path_parts[-1]


def supported_file_inputs(files: list[Path], supported_extensions: tuple[str, ...]) -> list[Path]:
    allowed = tuple(ext.lower() for ext in supported_extensions)
    return [path for path in files if path.is_file() and path.suffix.lower() in allowed]


class PlaywrightNotebookLMSession:
    def __init__(
        self,
        user_data_dir: Path,
        notebooklm_url: str,
        supported_extensions: tuple[str, ...],
        downloads_dir: Path,
        headless: bool = False,
    ) -> None:
        self.user_data_dir = user_data_dir
        self.notebooklm_url = notebooklm_url
        self.supported_extensions = supported_extensions
        self.downloads_dir = downloads_dir
        self.headless = headless
        self._playwright = None
        self._context = None
        self.page: Page | None = None

    def __enter__(self):
        self.start()
        return self

    def start(self) -> None:
        if self.page is not None:
            return
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.user_data_dir),
            headless=self.headless,
            accept_downloads=True,
            downloads_path=str(self.downloads_dir),
            args=["--start-maximized"],
        )
        self.page = self._context.pages[0] if self._context.pages else self._context.new_page()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        context = self._context
        playwright = self._playwright
        self._context = None
        self._playwright = None
        self.page = None
        try:
            if context is not None:
                context.close()
        finally:
            if playwright is not None:
                playwright.stop()

    def ensure_logged_in(self) -> bool:
        page = self._page()
        page.goto(self.notebooklm_url, wait_until="domcontentloaded")
        current_url = page.url.lower()
        if "accounts.google.com" in current_url:
            return False
        body_text = page.locator("body").inner_text(timeout=10_000).lower()
        if "sign in" in body_text or "登录" in body_text:
            return False
        return True

    def create_new_notebook(self) -> tuple[str, str]:
        page = self._page()
        if page.get_by_text("新建笔记本").count() > 0:
            page.get_by_text("新建笔记本").first.click()
        elif page.get_by_text("新建").count() > 0:
            page.get_by_text("新建").first.click()
        page.keyboard.press("Escape")
        page.wait_for_load_state("domcontentloaded")
        notebook_url = page.url
        notebook_id = extract_notebook_id(notebook_url)
        return notebook_id, notebook_url

    def upload_sources(self, files: list[Path]) -> int:
        page = self._page()
        uploadable = supported_file_inputs(files, self.supported_extensions)
        if not uploadable:
            raise RpaError("No uploadable files found")
        page.get_by_text("添加来源").first.click()
        with page.expect_file_chooser() as chooser_info:
            page.get_by_text("上传").first.click()
        chooser_info.value.set_files([str(path) for path in uploadable])
        return len(uploadable)

    def start_deep_research(self, prompt: str) -> None:
        page = self._page()
        page.get_by_text("在网络中搜索新来源").first.click()
        page.get_by_text("Fast Research").first.click()
        page.get_by_text("Deep Research").first.click()
        page.keyboard.type(prompt)
        page.keyboard.press("Enter")

    def wait_for_research(self) -> None:
        self._page().wait_for_timeout(5_000)

    def generate_slide_deck(self, language: str) -> None:
        page = self._page()
        page.get_by_text("演示文稿").first.click()
        page.get_by_text(">").first.click()
        page.get_by_text(language).first.click()
        page.keyboard.press("Enter")

    def wait_for_slide_deck(self) -> None:
        self._page().wait_for_timeout(5_000)

    def save_results(self, result_dir: Path) -> RpaArtifacts:
        result_dir.mkdir(parents=True, exist_ok=True)
        research_path = result_dir / "research.md"
        research_path.write_text(self._page().locator("body").inner_text(), encoding="utf-8")
        paths = [research_path]
        slide_path = self._download_slide_deck(result_dir)
        if slide_path is not None:
            paths.append(slide_path)
        screenshot_path = result_dir / "screenshots" / "final.png"
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        self._page().screenshot(path=str(screenshot_path), full_page=True)
        paths.append(screenshot_path)
        return RpaArtifacts(paths=paths)

    def _download_slide_deck(self, result_dir: Path) -> Path | None:
        page = self._page()
        candidates = (
            lambda: page.get_by_text("下载", exact=False),
            lambda: page.get_by_text("Download", exact=False),
            lambda: page.get_by_label("下载"),
            lambda: page.get_by_label("Download"),
            lambda: page.locator('a[download], button:has-text("下载"), button:has-text("Download")'),
        )
        for candidate in candidates:
            try:
                locator = candidate()
                if locator.count() == 0:
                    continue
                with page.expect_download(timeout=5_000) as download_info:
                    locator.first.click()
                download = download_info.value
                suggested_name = Path(download.suggested_filename).name
                target = result_dir / "slide_deck.pdf"
                if suggested_name and Path(suggested_name).suffix.lower() != ".pdf":
                    target = result_dir / "downloads" / suggested_name
                    target.parent.mkdir(parents=True, exist_ok=True)
                download.save_as(str(target))
                return target
            except Exception:
                continue
        return None

    def _page(self) -> Page:
        if self.page is None:
            self.start()
        if self.page is None:
            raise RpaError("Playwright page could not be initialized")
        return self.page
