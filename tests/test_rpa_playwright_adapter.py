from pathlib import Path

from app.worker.rpa.playwright_adapter import (
    PlaywrightNotebookLMSession,
    extract_notebook_id,
    supported_file_inputs,
)


def test_extract_notebook_id_from_notebooklm_url() -> None:
    assert (
        extract_notebook_id("https://notebooklm.google.com/notebook/abc123?_gl=1")
        == "abc123"
    )


def test_extract_notebook_id_from_unknown_url_returns_last_non_empty_segment() -> None:
    assert extract_notebook_id("https://notebooklm.google.com/notebooks/abc123/") == "abc123"


def test_supported_file_inputs_filters_directories_and_unsupported_suffixes(tmp_path: Path) -> None:
    pdf = tmp_path / "a.pdf"
    exe = tmp_path / "b.exe"
    nested = tmp_path / "nested"
    pdf.write_text("pdf")
    exe.write_text("exe")
    nested.mkdir()

    assert supported_file_inputs([pdf, exe, nested], supported_extensions=(".pdf",)) == [pdf]


def test_playwright_session_close_releases_handles(tmp_path: Path) -> None:
    class FakeContext:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FakePlaywright:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    context = FakeContext()
    playwright = FakePlaywright()
    session = PlaywrightNotebookLMSession(
        user_data_dir=tmp_path / "profile",
        notebooklm_url="https://notebooklm.example",
        supported_extensions=(".pdf",),
        downloads_dir=tmp_path / "downloads",
    )
    session._context = context
    session._playwright = playwright
    session.page = object()

    session.close()

    assert context.closed is True
    assert playwright.stopped is True
    assert session._context is None
    assert session._playwright is None
    assert session.page is None


def test_download_slide_deck_saves_pdf_artifact(tmp_path: Path) -> None:
    class FakeDownload:
        suggested_filename = "deck.pdf"

        def save_as(self, path: str) -> None:
            Path(path).write_bytes(b"%PDF")

    class FakeDownloadContext:
        value = FakeDownload()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

    class FakeLocator:
        def __init__(self) -> None:
            self.clicked = False
            self.first = self

        def count(self) -> int:
            return 1

        def click(self) -> None:
            self.clicked = True

    class FakePage:
        def __init__(self) -> None:
            self.locator_obj = FakeLocator()

        def get_by_text(self, text: str, exact: bool = False):
            return self.locator_obj

        def get_by_label(self, text: str):
            return self.locator_obj

        def locator(self, selector: str):
            return self.locator_obj

        def expect_download(self, timeout: int):
            return FakeDownloadContext()

    page = FakePage()
    session = PlaywrightNotebookLMSession(
        user_data_dir=tmp_path / "profile",
        notebooklm_url="https://notebooklm.example",
        supported_extensions=(".pdf",),
        downloads_dir=tmp_path / "downloads",
    )
    session.page = page

    slide_path = session._download_slide_deck(tmp_path)

    assert slide_path == tmp_path / "slide_deck.pdf"
    assert slide_path.read_bytes() == b"%PDF"
    assert page.locator_obj.clicked is True
