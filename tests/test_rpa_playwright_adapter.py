from pathlib import Path

from app.worker.rpa.playwright_adapter import extract_notebook_id, supported_file_inputs


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
