from pathlib import Path

import pytest

from app.domain import deep_research_prompt
from app.worker.rpa.base import LoginRequired, NotebookLMWorkflow, RpaArtifacts, RpaSession


class FakeSession(RpaSession):
    def __init__(self, logged_in: bool = True) -> None:
        self.logged_in = logged_in
        self.calls: list[str] = []

    def ensure_logged_in(self) -> bool:
        self.calls.append("ensure_logged_in")
        return self.logged_in

    def create_new_notebook(self) -> tuple[str, str]:
        self.calls.append("create_new_notebook")
        return "notebook-123", "https://notebooklm.google.com/notebook/notebook-123"

    def upload_sources(self, files: list[Path]) -> int:
        self.calls.append(f"upload_sources:{len(files)}")
        return len(files)

    def start_deep_research(self, prompt: str) -> None:
        self.calls.append(f"start_deep_research:{prompt}")

    def wait_for_research(self) -> None:
        self.calls.append("wait_for_research")

    def generate_slide_deck(self, language: str) -> None:
        self.calls.append(f"generate_slide_deck:{language}")

    def wait_for_slide_deck(self) -> None:
        self.calls.append("wait_for_slide_deck")

    def save_results(self, result_dir: Path) -> RpaArtifacts:
        self.calls.append(f"save_results:{result_dir}")
        return RpaArtifacts(paths=[result_dir / "research.md", result_dir / "slide_deck.pdf"])


def test_workflow_runs_expected_notebooklm_steps(tmp_path: Path) -> None:
    session = FakeSession()
    workflow = NotebookLMWorkflow(session=session)
    progress: list[str] = []

    result = workflow.run(files=[tmp_path / "a.pdf"], result_dir=tmp_path / "result", progress=progress.append)

    assert result.notebook_id == "notebook-123"
    assert result.notebook_url.endswith("notebook-123")
    assert result.artifacts.paths == [tmp_path / "result" / "research.md", tmp_path / "result" / "slide_deck.pdf"]
    assert progress == ["uploading_sources", "researching", "generating_ppt", "downloading_results"]
    assert session.calls == [
        "ensure_logged_in",
        "create_new_notebook",
        "upload_sources:1",
        f"start_deep_research:{deep_research_prompt()}",
        "wait_for_research",
        "generate_slide_deck:简体中文",
        "wait_for_slide_deck",
        f"save_results:{tmp_path / 'result'}",
    ]


def test_workflow_raises_login_required_when_not_logged_in(tmp_path: Path) -> None:
    session = FakeSession(logged_in=False)
    workflow = NotebookLMWorkflow(session=session)

    with pytest.raises(LoginRequired):
        workflow.run(files=[tmp_path / "a.pdf"], result_dir=tmp_path / "result")
