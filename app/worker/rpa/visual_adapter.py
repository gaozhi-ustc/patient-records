from pathlib import Path

from app.worker.rpa.base import RpaArtifacts, RpaError


class VisualNotebookLMSession:
    def __init__(self, display: str, screenshots_dir: Path) -> None:
        self.display = display
        self.screenshots_dir = screenshots_dir

    def ensure_logged_in(self) -> bool:
        raise RpaError("Pure visual mode is preserved as a fallback boundary and is not implemented in the MVP")

    def create_new_notebook(self) -> tuple[str, str]:
        raise RpaError("Pure visual mode is preserved as a fallback boundary and is not implemented in the MVP")

    def upload_sources(self, files: list[Path]) -> int:
        raise RpaError("Pure visual mode is preserved as a fallback boundary and is not implemented in the MVP")

    def start_deep_research(self, prompt: str) -> None:
        raise RpaError("Pure visual mode is preserved as a fallback boundary and is not implemented in the MVP")

    def wait_for_research(self) -> None:
        raise RpaError("Pure visual mode is preserved as a fallback boundary and is not implemented in the MVP")

    def generate_slide_deck(self, language: str) -> None:
        raise RpaError("Pure visual mode is preserved as a fallback boundary and is not implemented in the MVP")

    def wait_for_slide_deck(self) -> None:
        raise RpaError("Pure visual mode is preserved as a fallback boundary and is not implemented in the MVP")

    def save_results(self, result_dir: Path) -> RpaArtifacts:
        raise RpaError("Pure visual mode is preserved as a fallback boundary and is not implemented in the MVP")
