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
