from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from app.domain import deep_research_prompt


class LoginRequired(RuntimeError):
    pass


class RpaError(RuntimeError):
    pass


@dataclass(frozen=True)
class RpaArtifacts:
    paths: list[Path]


@dataclass(frozen=True)
class RpaWorkflowResult:
    notebook_id: str
    notebook_url: str
    artifacts: RpaArtifacts


class RpaSession(Protocol):
    def ensure_logged_in(self) -> bool:
        raise NotImplementedError

    def create_new_notebook(self) -> tuple[str, str]:
        raise NotImplementedError

    def upload_sources(self, files: list[Path]) -> int:
        raise NotImplementedError

    def start_deep_research(self, prompt: str) -> None:
        raise NotImplementedError

    def wait_for_research(self) -> None:
        raise NotImplementedError

    def generate_slide_deck(self, language: str) -> None:
        raise NotImplementedError

    def wait_for_slide_deck(self) -> None:
        raise NotImplementedError

    def save_results(self, result_dir: Path) -> RpaArtifacts:
        raise NotImplementedError


class NotebookLMWorkflow:
    def __init__(self, session: RpaSession) -> None:
        self.session = session

    def run(
        self,
        files: list[Path],
        result_dir: Path,
        progress: Callable[[str], None] | None = None,
    ) -> RpaWorkflowResult:
        if not self.session.ensure_logged_in():
            raise LoginRequired("NotebookLM login is required")
        notebook_id, notebook_url = self.session.create_new_notebook()
        self._notify(progress, "uploading_sources")
        self.session.upload_sources(files)
        self._notify(progress, "researching")
        self.session.start_deep_research(deep_research_prompt())
        self.session.wait_for_research()
        self._notify(progress, "generating_ppt")
        self.session.generate_slide_deck(language="简体中文")
        self.session.wait_for_slide_deck()
        self._notify(progress, "downloading_results")
        artifacts = self.session.save_results(result_dir)
        return RpaWorkflowResult(notebook_id=notebook_id, notebook_url=notebook_url, artifacts=artifacts)

    def close(self) -> None:
        close = getattr(self.session, "close", None)
        if callable(close):
            close()

    def _notify(self, progress: Callable[[str], None] | None, step: str) -> None:
        if progress is not None:
            progress(step)
