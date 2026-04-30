import json
from pathlib import Path
import socket
import subprocess
import inspect

from app.domain import deep_research_prompt
from app.worker.rpa import visual_adapter
from app.worker.rpa.visual_adapter import (
    DesktopAutomation,
    VisualNotebookLMSession,
    extract_presentation_download_url,
    extract_clinic_record_markdown,
)


HOME_TEXT = "NotebookLM\n我的笔记本\n精选笔记本\n最近打开过的笔记本\n新建"
BLANK_NOTEBOOK_TEXT = (
    "来源\n添加来源\n已保存的来源将显示在此处\n"
    "对话\nUntitled notebook\n0 个来源\nStudio\n添加来源后，点击即可添加音频概览"
)
READY_NOTEBOOK_TEXT = (
    "来源\n添加来源\n对话\n这些文件已经生成摘要，可继续提问和生成输出。"
    "根据来源内容，系统已准备好回答问题。\n开始输入…\n99 个来源\nStudio"
)


class FakeAutomation:
    def __init__(
        self,
        current_url: str = "https://notebooklm.google.com/notebook/abc123",
        visible_text: str | None = None,
    ) -> None:
        self.current_url = current_url
        self.visible_text = visible_text or self._default_visible_text(current_url)
        self.commands: list[tuple[str, object]] = []
        self.clipboard = ""

    def _default_visible_text(self, current_url: str) -> str:
        if current_url.rstrip("/") == "https://notebooklm.google.com":
            return HOME_TEXT
        if current_url.startswith("http"):
            return READY_NOTEBOOK_TEXT
        return current_url

    def focus_chrome(self) -> None:
        self.commands.append(("focus_chrome", None))

    def hotkey(self, *keys: str) -> None:
        self.commands.append(("hotkey", keys))

    def press(self, key: str) -> None:
        self.commands.append(("press", key))
        if key == "Return" and self.clipboard.startswith("https://notebooklm.google.com"):
            self.current_url = self.clipboard
            self.visible_text = self._default_visible_text(self.current_url)

    def click(self, x: int, y: int) -> None:
        self.commands.append(("click", (x, y)))

    def paste_text(self, text: str) -> None:
        self.clipboard = text
        self.commands.append(("paste_text", text))

    def navigate_to_blank_notebook(self, url: str) -> None:
        self.current_url = url
        self.visible_text = BLANK_NOTEBOOK_TEXT

    def copy_selection(self) -> str:
        self.commands.append(("copy_selection", None))
        if self.commands[-2:-1] == [("hotkey", ("ctrl", "l"))]:
            return self.current_url
        return self.visible_text

    def get_accessible_text(self) -> str:
        self.commands.append(("get_accessible_text", None))
        return self.visible_text

    def wait_for_window(self, name: str) -> None:
        self.commands.append(("wait_for_window", name))

    def screenshot(self, path: Path) -> None:
        self.commands.append(("screenshot", path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")


def test_ensure_logged_in_returns_false_on_google_login_url() -> None:
    class LoginAutomation(FakeAutomation):
        def press(self, key: str) -> None:
            self.commands.append(("press", key))

    automation = LoginAutomation("https://accounts.google.com/signin/v2", visible_text="Sign in")
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
    class HomeAutomation(FakeAutomation):
        def click(self, x: int, y: int) -> None:
            super().click(x, y)
            if (x, y) == (1600, 30):
                self.navigate_to_blank_notebook("https://notebooklm.google.com/notebook/notebook-123")

    automation = HomeAutomation("https://notebooklm.google.com/notebook/old-notebook")
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


def test_create_new_notebook_clears_address_bar_focus_after_url_detection() -> None:
    class HomeAutomation(FakeAutomation):
        def click(self, x: int, y: int) -> None:
            super().click(x, y)
            if (x, y) == (1600, 30):
                self.navigate_to_blank_notebook("https://notebooklm.google.com/notebook/notebook-123?addSource=true")

    automation = HomeAutomation("https://notebooklm.google.com/notebook/old-notebook")
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=Path("/tmp/screenshots"),
        downloads_dir=Path("/tmp/downloads"),
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    session.create_new_notebook()

    screenshot_index = next(
        index for index, command in enumerate(automation.commands) if command[0] == "screenshot"
    )
    assert ("press", "Escape") in automation.commands[:screenshot_index]


def test_create_new_notebook_uses_automation_current_url_when_available() -> None:
    class UrlAutomation(FakeAutomation):
        def get_current_url(self) -> str:
            self.commands.append(("get_current_url", None))
            return self.current_url

        def click(self, x: int, y: int) -> None:
            super().click(x, y)
            if (x, y) == (1600, 30):
                self.navigate_to_blank_notebook("https://notebooklm.google.com/notebook/url-api-new")

    automation = UrlAutomation("https://notebooklm.google.com/notebook/old-notebook")
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=Path("/tmp/screenshots"),
        downloads_dir=Path("/tmp/downloads"),
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    notebook_id, notebook_url = session.create_new_notebook()

    assert notebook_id == "url-api-new"
    assert notebook_url == "https://notebooklm.google.com/notebook/url-api-new"
    assert ("get_current_url", None) in automation.commands
    assert ("hotkey", ("ctrl", "l")) not in automation.commands


def test_create_new_notebook_clicks_home_new_button_when_on_homepage() -> None:
    class HomeAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__("https://notebooklm.google.com/")

        def click(self, x: int, y: int) -> None:
            super().click(x, y)
            if (x, y) == (1674, 147):
                self.navigate_to_blank_notebook("https://notebooklm.google.com/notebook/notebook-456?addSource=true")

    automation = HomeAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=Path("/tmp/screenshots"),
        downloads_dir=Path("/tmp/downloads"),
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    notebook_id, notebook_url = session.create_new_notebook()

    assert notebook_id == "notebook-456"
    assert notebook_url == "https://notebooklm.google.com/notebook/notebook-456?addSource=true"
    assert ("click", (1674, 147)) in automation.commands
    assert ("click", (1600, 30)) not in automation.commands


def test_create_new_notebook_prefers_direct_new_button_click_when_available() -> None:
    direct_url = "https://notebooklm.google.com/notebook/direct-new?addSource=true"

    class DirectNewAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__("https://notebooklm.google.com/")

        def click_new_notebook(self) -> None:
            self.commands.append(("click_new_notebook", None))
            self.navigate_to_blank_notebook(direct_url)

    class FastFailSession(VisualNotebookLMSession):
        def _wait_for_notebook_url(
            self,
            timeout_seconds: float = 15.0,
            ignored_url: str | None = None,
        ) -> str:
            if self.automation.current_url == direct_url:
                return direct_url
            raise visual_adapter.RpaError("direct new notebook click was not used")

    automation = DirectNewAutomation()
    session = FastFailSession(
        display=":1",
        screenshots_dir=Path("/tmp/screenshots"),
        downloads_dir=Path("/tmp/downloads"),
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    notebook_id, notebook_url = session.create_new_notebook()

    assert notebook_id == "direct-new"
    assert notebook_url == direct_url
    assert ("click_new_notebook", None) in automation.commands
    assert ("click", (1674, 147)) not in automation.commands


def test_create_new_notebook_uses_top_button_when_on_old_notebook() -> None:
    class NotebookAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__("https://notebooklm.google.com/notebook/old-notebook")

        def click(self, x: int, y: int) -> None:
            super().click(x, y)
            if (x, y) == (1600, 30):
                self.current_url = "https://notebooklm.google.com/notebook/new-notebook?addSource=true"
                self.visible_text = BLANK_NOTEBOOK_TEXT

    automation = NotebookAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=Path("/tmp/screenshots"),
        downloads_dir=Path("/tmp/downloads"),
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    notebook_id, notebook_url = session.create_new_notebook()

    assert notebook_id == "new-notebook"
    assert notebook_url == "https://notebooklm.google.com/notebook/new-notebook?addSource=true"
    assert ("paste_text", "https://notebooklm.google.com") not in automation.commands
    assert ("click", (1600, 30)) in automation.commands


def test_create_new_notebook_waits_until_creating_url_resolves(monkeypatch) -> None:
    class CreatingAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__("https://notebooklm.google.com/")
            self.copied_urls: list[str] = []

        def click(self, x: int, y: int) -> None:
            super().click(x, y)
            if (x, y) == (1674, 147):
                self.current_url = "https://notebooklm.google.com/notebook/creating"
                self.copied_urls = [
                    "https://notebooklm.google.com/notebook/creating",
                    "https://notebooklm.google.com/notebook/notebook-789?addSource=true",
                ]

        def copy_selection(self) -> str:
            self.commands.append(("copy_selection", None))
            if self.copied_urls:
                self.current_url = self.copied_urls.pop(0)
                if self.current_url.endswith("notebook-789?addSource=true"):
                    self.visible_text = BLANK_NOTEBOOK_TEXT
            return self.current_url

    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)
    automation = CreatingAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=Path("/tmp/screenshots"),
        downloads_dir=Path("/tmp/downloads"),
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    notebook_id, notebook_url = session.create_new_notebook()

    assert notebook_id == "notebook-789"
    assert notebook_url == "https://notebooklm.google.com/notebook/notebook-789?addSource=true"


def test_create_new_notebook_opens_recent_untitled_when_home_create_does_not_navigate() -> None:
    class RetrySession(VisualNotebookLMSession):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self.wait_attempts = 0

        def _wait_for_notebook_url(
            self,
            timeout_seconds: float = 15.0,
            ignored_url: str | None = None,
        ) -> str:
            self.wait_attempts += 1
            if self.wait_attempts == 1:
                raise visual_adapter.RpaError("Cannot extract notebook_id from URL: https://notebooklm.google.com/")
            return "https://notebooklm.google.com/notebook/retried-notebook?addSource=true"

        def _wait_for_blank_new_notebook(self, timeout_seconds: float = 30.0) -> None:
            return None

    automation = FakeAutomation("https://notebooklm.google.com/")
    session = RetrySession(
        display=":1",
        screenshots_dir=Path("/tmp/screenshots"),
        downloads_dir=Path("/tmp/downloads"),
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    notebook_id, notebook_url = session.create_new_notebook()

    assert notebook_id == "retried-notebook"
    assert notebook_url == "https://notebooklm.google.com/notebook/retried-notebook?addSource=true"
    assert automation.commands.count(("click", (1674, 147))) == 1
    assert ("click", (300, 724)) in automation.commands


def test_create_new_notebook_does_not_return_existing_notebook_url() -> None:
    class StuckAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__("https://notebooklm.google.com/")
            self.create_clicks = 0

        def click(self, x: int, y: int) -> None:
            super().click(x, y)
            if (x, y) == (1674, 147):
                self.create_clicks += 1
                if self.create_clicks == 1:
                    self.current_url = "https://notebooklm.google.com/notebook/old-notebook"
                    self.visible_text = READY_NOTEBOOK_TEXT
            elif (x, y) == (1600, 30):
                self.navigate_to_blank_notebook("https://notebooklm.google.com/notebook/recovered-notebook")

    class StrictBlankSession(VisualNotebookLMSession):
        def _wait_for_blank_new_notebook(self, timeout_seconds: float = 30.0) -> None:
            if self.automation.current_url.endswith("/old-notebook"):
                raise visual_adapter.RpaError("New notebook did not become blank")

    automation = StuckAutomation()
    session = StrictBlankSession(
        display=":1",
        screenshots_dir=Path("/tmp/screenshots"),
        downloads_dir=Path("/tmp/downloads"),
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    notebook_id, notebook_url = session.create_new_notebook()

    assert notebook_id == "recovered-notebook"
    assert notebook_url == "https://notebooklm.google.com/notebook/recovered-notebook"


def test_create_new_notebook_accepts_new_blank_ui_without_source_count() -> None:
    new_blank_ui_text = (
        "add\n创建笔记本\ntrending_up\n分析\nshare\n分享\nsettings\n设置\nULTRA\n"
        "来源\ndock_to_right\nadd\n添加来源\nsearch\nlanguage\nWeb\nkeyboard_arrow_down\nsearch"
    )

    class NewBlankAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__("https://notebooklm.google.com/")

        def click(self, x: int, y: int) -> None:
            super().click(x, y)
            if (x, y) == (1674, 147):
                self.navigate_to_blank_notebook("https://notebooklm.google.com/notebook/new-blank-ui")
                self.visible_text = new_blank_ui_text

    automation = NewBlankAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=Path("/tmp/screenshots"),
        downloads_dir=Path("/tmp/downloads"),
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    notebook_id, notebook_url = session.create_new_notebook()

    assert notebook_id == "new-blank-ui"
    assert notebook_url == "https://notebooklm.google.com/notebook/new-blank-ui"


def test_create_new_notebook_allows_slow_home_create_navigation() -> None:
    class SlowCreateSession(VisualNotebookLMSession):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self.notebook_url_timeout = None

        def _wait_for_notebook_url(
            self,
            timeout_seconds: float = 15.0,
            ignored_url: str | None = None,
        ) -> str:
            self.notebook_url_timeout = timeout_seconds
            return "https://notebooklm.google.com/notebook/slow-new-notebook"

        def _wait_for_blank_new_notebook(self, timeout_seconds: float = 30.0) -> None:
            return None

    class HomeAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__("https://notebooklm.google.com/")

    automation = HomeAutomation()
    session = SlowCreateSession(
        display=":1",
        screenshots_dir=Path("/tmp/screenshots"),
        downloads_dir=Path("/tmp/downloads"),
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    session.create_new_notebook()

    assert session.notebook_url_timeout == 60.0


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
    assert automation.commands.count(("hotkey", ("ctrl", "a"))) == 1
    assert ("press", "Return") in automation.commands


def test_upload_sources_clears_address_bar_focus_before_opening_file_picker(tmp_path: Path) -> None:
    source = tmp_path / "a.pdf"
    source.write_text("a")
    automation = FakeAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    session.upload_sources([source])

    escape_index = automation.commands.index(("press", "Escape"))
    upload_click_index = automation.commands.index(("click", (805, 791)))
    assert escape_index < upload_click_index


def test_upload_sources_waits_for_file_picker_before_typing_path(tmp_path: Path) -> None:
    source = tmp_path / "a.pdf"
    source.write_text("a")
    automation = FakeAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    session.upload_sources([source])

    picker_index = automation.commands.index(("wait_for_window", "Open Files"))
    path_index = automation.commands.index(("paste_text", str(tmp_path)))
    assert picker_index < path_index


def test_upload_sources_uses_direct_browser_upload_when_available(tmp_path: Path) -> None:
    class DirectUploadAutomation(FakeAutomation):
        def select_deep_research(self) -> None:
            self.commands.append(("select_deep_research", None))

        def upload_files(self, files: list[Path]) -> None:
            self.commands.append(("upload_files", tuple(files)))
            self.visible_text = (
                "来源\n添加来源\n对话\n这些文件已经生成摘要，可继续提问和生成输出。"
                "摘要包含患者现病史、既往治疗经过、主要检查结果和初步诊断。"
                "\n开始输入…\n2 个来源\nStudio"
            )

    first = tmp_path / "a.pdf"
    second = tmp_path / "b.docx"
    first.write_text("a")
    second.write_text("b")
    automation = DirectUploadAutomation()
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
    assert ("select_deep_research", None) in automation.commands
    assert ("upload_files", (first, second)) in automation.commands
    assert ("wait_for_window", "Open Files") not in automation.commands
    assert ("paste_text", str(tmp_path)) not in automation.commands
    assert ("click", (1370, 452)) not in automation.commands
    assert ("click", (878, 600)) not in automation.commands


def test_upload_sources_prefers_direct_add_source_click_before_upload(tmp_path: Path) -> None:
    source = tmp_path / "a.pdf"
    source.write_text("a")

    class DirectAddSourceAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__("https://notebooklm.google.com/notebook/new", visible_text=BLANK_NOTEBOOK_TEXT)

        def click_text(self, text: str) -> None:
            self.commands.append(("click_text", text))
            if text == "添加来源":
                self.visible_text = "上传文件\n或拖放文件\nFast Research\nDeep Research"

        def select_deep_research(self) -> None:
            self.commands.append(("select_deep_research", None))
            if "上传文件" not in self.visible_text:
                raise visual_adapter.RpaError("add source dialog was not opened")

        def upload_files(self, files: list[Path]) -> None:
            self.commands.append(("upload_files", tuple(files)))
            if "上传文件" not in self.visible_text:
                raise visual_adapter.RpaError("add source dialog was not opened")
            self.visible_text = READY_NOTEBOOK_TEXT

        def wait_for_window(self, name: str) -> None:
            self.commands.append(("wait_for_window", name))
            raise visual_adapter.RpaError("file picker should not be used")

    automation = DirectAddSourceAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    count = session.upload_sources([source])

    assert count == 1
    assert ("click_text", "添加来源") in automation.commands
    assert ("click", (252, 186)) not in automation.commands
    assert ("upload_files", (source,)) in automation.commands


def test_wait_for_new_downloads_default_timeout_matches_runtime_setting() -> None:
    timeout = inspect.signature(VisualNotebookLMSession._wait_for_new_downloads).parameters[
        "timeout_seconds"
    ].default

    assert timeout == 600.0


def test_research_result_ready_accepts_clinic_record_with_reply_ready_marker() -> None:
    text = (
        "请帮我梳理成 门诊记录单格式，不带来源 编号（即去掉末尾数字）的纯净版门诊记录单\n"
        "门诊记录单\n"
        "基本信息\n"
        "姓名：马振祥\n"
        "【主诉】\n发现肝脏占位3年。\n"
        "【现病史】\n患者近期复查发现增大。\n"
        "回复已就绪。"
    )

    assert visual_adapter._research_result_is_ready(text) is True


def test_research_result_ready_accepts_diagnosis_and_plan_with_reply_ready_marker() -> None:
    text = (
        "请帮我梳理成 门诊记录单格式，不带来源 编号（即去掉末尾数字）的纯净版门诊记录单\n"
        "六、初步诊断\n"
        "胆总管占位性病变（考虑胆道恶性肿瘤）\n"
        "七、患者主要诉求与拟解决问题\n"
        "明确当前疾病的具体阶段和严重程度。\n"
        "回复已就绪。"
    )

    assert visual_adapter._research_result_is_ready(text) is True


def test_research_result_ready_accepts_structured_clinic_record_without_reply_marker() -> None:
    prompt = deep_research_prompt()
    text = (
        f"{prompt}\n"
        "门诊记录单\n"
        "一、基本信息\n姓名：马振祥\n"
        "二、主诉\n发现肝脏血管瘤3年，近期复查提示病灶增大。\n"
        "三、现病史\n患者近期伴上腹及腰背痛。\n"
        "八、诊疗诉求\n明确最佳治疗方法。\n"
        "8 个来源\nStudio"
    )

    assert visual_adapter._research_result_is_ready(text, prompt) is True


def test_research_result_ready_accepts_diagnosis_record_without_reply_marker() -> None:
    prompt = deep_research_prompt()
    text = (
        f"{prompt}\n"
        "门诊/诊疗记录单\n"
        "【诊断】\n胆总管囊肿内引流术后\n"
        "【体格检查】\n腹软，全腹无压痛及反跳痛。\n"
        "【辅助检查】\n腹部核磁提示胆总管囊肿术后改变。\n"
        "【诊疗经过】\n入院后完善相关检查并行胆总管囊肿根治术。\n"
        "11 个来源\nStudio"
    )

    assert visual_adapter._research_result_is_ready(text, prompt) is True


def test_research_result_ready_accepts_long_medical_answer_without_standard_headings() -> None:
    text = (
        "请帮我梳理成 门诊记录单格式，不带来源 编号（即去掉末尾数字）的纯净版门诊记录单\n"
        "患者因先天性胆总管扩张接受手术治疗，术中记录胆囊约8×7×6cm，"
        "胆总管呈球型扩张，囊壁厚约3-4mm，穿刺抽出胆汁样液体约3000ml。"
        "术中行囊肿空肠端端吻合，并取肝脏组织送病理检查。"
        "术后患儿安返病房，麻醉满意，已向家属详细交代手术情况。"
        "后续需结合肝功能恢复情况评估根治手术时机。"
        "回复已就绪。"
    )

    assert visual_adapter._research_result_is_ready(text) is True


def test_research_result_ready_rejects_system_unable_answer() -> None:
    text = (
        "请帮我梳理成 门诊记录单格式，不带来源 编号（即去掉末尾数字）的纯净版门诊记录单\n"
        "系统无法回答。\n"
        "回复已就绪。"
    )

    assert visual_adapter._research_result_is_ready(text) is False


def test_research_result_invalid_detects_reply_marker_after_notebooklm_ui_tail() -> None:
    prompt = deep_research_prompt()
    text = (
        f"{prompt}\n"
        "系统无法回答。\n"
        "8 个来源\n"
        "Studio\n"
        "NotebookLM 提供的内容未必准确，因此请仔细核查回答内容。\n"
        "回复已就绪。"
    )

    assert visual_adapter._research_result_is_invalid(text, prompt) is True
    assert visual_adapter._research_result_is_ready(text, prompt) is False


def test_research_result_ready_rejects_missing_sources_answer() -> None:
    text = (
        "请帮我梳理成 门诊记录单格式，不带来源 编号（即去掉末尾数字）的纯净版门诊记录单\n"
        "目前笔记本中还没有添加任何来源。请先上传相关资料。\n"
        "回复已就绪。"
    )

    assert visual_adapter._research_result_is_ready(text) is False


def test_desktop_upload_files_sets_cdp_file_input_files(tmp_path: Path) -> None:
    source = tmp_path / "a.pdf"
    source.write_text("a")

    class CdpAutomation(DesktopAutomation):
        def __init__(self) -> None:
            super().__init__(display=":1", remote_debugging_port=9222)
            self.calls: list[tuple[str, dict | None]] = []

        def _find_cdp_target(self) -> dict:
            return {"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/1"}

        def _upload_files_with_file_chooser_intercept(self, websocket_url: str, files: list[str]) -> None:
            raise visual_adapter.RpaError("intercept unavailable")

        def _cdp_call(self, websocket_url: str, method: str, params: dict | None = None) -> dict:
            self.calls.append((method, params))
            if method == "Runtime.evaluate":
                return {"result": {"result": {"objectId": "file-input-1"}}}
            return {"result": {}}

    automation = CdpAutomation()

    automation.upload_files([source])

    assert ("DOM.setFileInputFiles", {"objectId": "file-input-1", "files": [str(source.resolve())]}) in automation.calls
    assert any(method == "Runtime.callFunctionOn" for method, _ in automation.calls)


def test_desktop_upload_files_prefers_intercepted_file_chooser(tmp_path: Path) -> None:
    source = tmp_path / "a.pdf"
    source.write_text("a")

    class InterceptAutomation(DesktopAutomation):
        def __init__(self) -> None:
            super().__init__(display=":1", remote_debugging_port=9222)
            self.intercepted: tuple[str, list[str]] | None = None

        def _find_cdp_target(self) -> dict:
            return {"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/1"}

        def _upload_files_with_file_chooser_intercept(self, websocket_url: str, files: list[str]) -> None:
            self.intercepted = (websocket_url, files)

        def _cdp_call(self, websocket_url: str, method: str, params: dict | None = None) -> dict:
            raise AssertionError("fallback CDP path should not run")

    automation = InterceptAutomation()

    automation.upload_files([source])

    assert automation.intercepted == (
        "ws://127.0.0.1/devtools/page/1",
        [str(source.resolve())],
    )


def test_desktop_upload_files_retries_intercept_before_fallback(tmp_path: Path) -> None:
    source = tmp_path / "a.pdf"
    source.write_text("a")

    class FlakyInterceptAutomation(DesktopAutomation):
        def __init__(self) -> None:
            super().__init__(display=":1", remote_debugging_port=9222)
            self.attempts = 0

        def _find_cdp_target(self) -> dict:
            return {"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/1"}

        def _upload_files_with_file_chooser_intercept(self, websocket_url: str, files: list[str]) -> None:
            self.attempts += 1
            if self.attempts == 1:
                raise visual_adapter.RpaError("file chooser event was not received")

        def _find_cdp_file_input(self, websocket_url: str) -> str:
            raise AssertionError("file input fallback should not run after retry succeeds")

    automation = FlakyInterceptAutomation()

    automation.upload_files([source])

    assert automation.attempts == 2


def test_upload_files_intercept_dispatches_mouse_events_for_file_button(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "a.pdf"
    source.write_text("a")

    class FakeSocket:
        def close(self) -> None:
            return None

    class MouseUploadAutomation(DesktopAutomation):
        def __init__(self) -> None:
            super().__init__(display=":1", remote_debugging_port=9222)
            self.commands: list[tuple[str, dict | None]] = []

        def _websocket_handshake(self, sock, parsed) -> None:
            return None

        def _send_cdp_command(self, sock, method: str, params: dict | None = None) -> dict:
            self.commands.append((method, params))
            if method == "Runtime.evaluate":
                return {"result": {"result": {"value": {"x": 692, "y": 756, "width": 124, "height": 40}}}}
            return {"result": {}}

        def _websocket_send_cdp_command(self, sock, method: str, params: dict | None = None) -> int:
            self.commands.append((method, params))
            return 7

        def _wait_for_file_chooser_backend_node(self, sock, click_request_id: int) -> int:
            return 42

    monkeypatch.setattr(visual_adapter.socket, "create_connection", lambda *args, **kwargs: FakeSocket())
    automation = MouseUploadAutomation()

    automation._upload_files_with_file_chooser_intercept(
        "ws://127.0.0.1:9222/devtools/page/1",
        [str(source)],
    )

    mouse_events = [params for method, params in automation.commands if method == "Input.dispatchMouseEvent"]
    assert ("Page.bringToFront", {}) in automation.commands
    assert [event["type"] for event in mouse_events] == ["mouseMoved", "mousePressed", "mouseReleased"]
    assert any(method == "DOM.setFileInputFiles" for method, _ in automation.commands)


def test_select_deep_research_brings_tab_front_and_uses_robust_script() -> None:
    class SelectAutomation(DesktopAutomation):
        def __init__(self) -> None:
            super().__init__(display=":1", remote_debugging_port=9222)
            self.calls: list[tuple[str, dict | None]] = []

        def _find_cdp_target(self) -> dict:
            return {"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/1"}

        def _cdp_call(self, websocket_url: str, method: str, params: dict | None = None) -> dict:
            self.calls.append((method, params))
            if method == "Runtime.evaluate":
                return {"result": {"result": {"value": {"ok": True}}}}
            return {"result": {}}

    automation = SelectAutomation()

    automation.select_deep_research()

    assert ("Page.bringToFront", {}) in automation.calls
    evaluate_calls = [params for method, params in automation.calls if method == "Runtime.evaluate"]
    assert len(evaluate_calls) == 1
    assert "Deep Research" in evaluate_calls[0]["expression"]


def test_wait_for_cdp_response_ignores_socket_timeout(monkeypatch) -> None:
    automation = DesktopAutomation(":1")
    messages: list[dict | BaseException] = [
        socket.timeout("timed out"),
        {"id": 3, "result": {"result": {"value": True}}},
    ]

    def fake_recv_json(sock) -> dict:
        message = messages.pop(0)
        if isinstance(message, BaseException):
            raise message
        return message

    monkeypatch.setattr(automation, "_websocket_recv_json", fake_recv_json)

    assert automation._wait_for_cdp_response(object(), 3, "Runtime.evaluate") == {
        "id": 3,
        "result": {"result": {"value": True}},
    }


def test_wait_for_file_chooser_backend_node_ignores_socket_timeout(monkeypatch) -> None:
    automation = DesktopAutomation(":1")
    messages: list[dict | BaseException] = [
        socket.timeout("timed out"),
        {"id": 7, "result": {"result": {"value": True}}},
        {"method": "Page.fileChooserOpened", "params": {"backendNodeId": 42}},
    ]

    def fake_recv_json(sock) -> dict:
        message = messages.pop(0)
        if isinstance(message, BaseException):
            raise message
        return message

    monkeypatch.setattr(automation, "_websocket_recv_json", fake_recv_json)

    assert automation._wait_for_file_chooser_backend_node(object(), 7) == 42


def test_upload_sources_falls_back_to_file_picker_when_direct_upload_fails(tmp_path: Path) -> None:
    class FailingDirectUploadAutomation(FakeAutomation):
        def upload_files(self, files: list[Path]) -> None:
            self.commands.append(("upload_files", tuple(files)))
            raise visual_adapter.RpaError("Chrome DevTools file input was not found")

    source = tmp_path / "a.pdf"
    source.write_text("a")
    automation = FailingDirectUploadAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    count = session.upload_sources([source])

    assert count == 1
    assert ("upload_files", (source,)) in automation.commands
    assert ("wait_for_window", "Open Files") in automation.commands
    assert ("paste_text", str(tmp_path)) in automation.commands


def test_upload_sources_retries_when_file_picker_does_not_open(tmp_path: Path) -> None:
    class RetryAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__()
            self.wait_attempts = 0

        def wait_for_window(self, name: str) -> None:
            self.wait_attempts += 1
            self.commands.append(("wait_for_window", name))
            if self.wait_attempts == 1:
                raise visual_adapter.RpaError("Window was not found for visual automation: Open Files")

    source = tmp_path / "a.pdf"
    source.write_text("a")
    automation = RetryAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    session.upload_sources([source])

    assert automation.wait_attempts == 2
    assert automation.commands.count(("click", (805, 791))) == 2


def test_upload_sources_selects_deep_research_in_add_source_dialog_before_upload(
    tmp_path: Path,
) -> None:
    source = tmp_path / "a.pdf"
    source.write_text("a")
    automation = FakeAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    session.upload_sources([source])

    add_source_index = automation.commands.index(("click", (252, 186)))
    research_dropdown_index = automation.commands.index(("click", (878, 600)))
    deep_research_index = automation.commands.index(("click", (872, 665)))
    upload_index = automation.commands.index(("click", (805, 791)))
    assert add_source_index < research_dropdown_index < deep_research_index < upload_index


def test_upload_sources_uses_open_add_source_dialog_without_reclicking_add_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "a.pdf"
    source.write_text("a")
    automation = FakeAutomation(
        visible_text=(
            "来源\n添加来源\n上传文件\n或拖放文件\n对话\n这些文件已经生成摘要，"
            "根据来源内容可继续提问。\n开始输入…\n99 个来源\nStudio"
        )
    )
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    session.upload_sources([source])

    upload_index = automation.commands.index(("click", (805, 791)))
    assert ("click", (252, 186)) not in automation.commands[:upload_index]


def test_upload_sources_focuses_file_list_and_clicks_open(tmp_path: Path) -> None:
    source = tmp_path / "a.pdf"
    source.write_text("a")
    automation = FakeAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    session.upload_sources([source])

    file_list_index = automation.commands.index(("click", (820, 566)))
    select_all_index = next(
        index
        for index, command in enumerate(automation.commands)
        if index > file_list_index and command == ("hotkey", ("ctrl", "a"))
    )
    open_index = automation.commands.index(("click", (1370, 452)))
    assert file_list_index < select_all_index < open_index


def test_upload_sources_waits_for_directory_listing_after_path_entry(
    tmp_path: Path, monkeypatch
) -> None:
    sleeps: list[float] = []
    source = tmp_path / "a.pdf"
    source.write_text("a")
    automation = FakeAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=1,
    )
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: sleeps.append(seconds))

    session.upload_sources([source])

    assert 2.0 in sleeps


def test_upload_sources_waits_after_pasting_path_before_return(tmp_path: Path) -> None:
    class SleepRecordingSession(VisualNotebookLMSession):
        def _sleep(self) -> None:
            self.automation.commands.append(("sleep", None))

        def _sleep_at_least(self, minimum_seconds: float) -> None:
            self.automation.commands.append(("sleep_at_least", minimum_seconds))

    source = tmp_path / "a.pdf"
    source.write_text("a")
    automation = FakeAutomation()
    session = SleepRecordingSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=1,
    )

    session.upload_sources([source])

    paste_index = automation.commands.index(("paste_text", str(tmp_path)))
    return_index = automation.commands.index(("press", "Return"))
    assert ("sleep", None) in automation.commands[paste_index:return_index]


def test_upload_sources_waits_for_notebook_page_before_clicking_add_source(
    tmp_path: Path, monkeypatch
) -> None:
    class LoadingAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__()
            self.visible_texts = [
                "Loading Notebook...",
                "来源\n添加来源\n对话\n这些文件已经生成摘要，"
                "根据来源内容可继续提问。\n开始输入…\n99 个来源\nStudio",
            ]

        def copy_selection(self) -> str:
            self.commands.append(("copy_selection", None))
            if self.visible_texts:
                return self.visible_texts.pop(0)
            return (
                "来源\n添加来源\n对话\n这些文件已经生成摘要，"
                "根据来源内容可继续提问。\n开始输入…\n99 个来源\nStudio"
            )

        def get_accessible_text(self) -> str:
            self.commands.append(("get_accessible_text", None))
            if self.visible_texts:
                return self.visible_texts.pop(0)
            return (
                "来源\n添加来源\n对话\n这些文件已经生成摘要，"
                "根据来源内容可继续提问。\n开始输入…\n99 个来源\nStudio"
            )

    source = tmp_path / "a.pdf"
    source.write_text("a")
    automation = LoadingAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)

    session.upload_sources([source])

    add_source_index = automation.commands.index(("click", (252, 186)))
    assert automation.commands[:add_source_index].count(("get_accessible_text", None)) == 2


def test_upload_sources_waits_until_uploaded_sources_are_available(
    tmp_path: Path, monkeypatch
) -> None:
    class UploadProcessingAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__()
            self.visible_texts = [
                "来源\n添加来源\n对话\n开始输入…\n0 个来源",
                "来源\n添加来源\n对话\n开始输入…\n1 个来源",
                "来源\n添加来源\n对话\n这些文件记录了患者的详细病史。"
                "影像学检查和实验室检查提示需要进一步诊疗。"
                "系统已经生成了可用于提问的资料摘要。"
                "摘要包含患者现病史、既往治疗经过、主要检查结果、初步诊断和后续咨询问题，"
                "能够说明来源已经完成解析并进入可问答状态。\n开始输入…\n2 个来源\nStudio",
            ]

        def copy_selection(self) -> str:
            self.commands.append(("copy_selection", None))
            if self.commands[-2:-1] == [("hotkey", ("ctrl", "l"))]:
                return self.current_url
            if self.visible_texts:
                return self.visible_texts.pop(0)
            return (
                "来源\n添加来源\n对话\n这些文件记录了患者的详细病史。"
                "影像学检查和实验室检查提示需要进一步诊疗。"
                "系统已经生成了可用于提问的资料摘要。"
                "摘要包含患者现病史、既往治疗经过、主要检查结果、初步诊断和后续咨询问题，"
                "能够说明来源已经完成解析并进入可问答状态。\n开始输入…\n2 个来源\nStudio"
            )

        def get_accessible_text(self) -> str:
            self.commands.append(("get_accessible_text", None))
            if self.visible_texts:
                return self.visible_texts.pop(0)
            return (
                "来源\n添加来源\n对话\n这些文件记录了患者的详细病史。"
                "影像学检查和实验室检查提示需要进一步诊疗。"
                "系统已经生成了可用于提问的资料摘要。"
                "摘要包含患者现病史、既往治疗经过、主要检查结果、初步诊断和后续咨询问题，"
                "能够说明来源已经完成解析并进入可问答状态。\n开始输入…\n2 个来源\nStudio"
            )

    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    first.write_text("a")
    second.write_text("b")
    automation = UploadProcessingAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)

    session.upload_sources([first, second])

    open_index = automation.commands.index(("click", (1370, 452)))
    post_open_reads = automation.commands[open_index:].count(("get_accessible_text", None))
    assert post_open_reads == 2
    assert automation.commands.count(("hotkey", ("ctrl", "a"))) == 1


def test_upload_sources_does_not_treat_source_count_alone_as_ready(
    tmp_path: Path, monkeypatch
) -> None:
    class SourceCountOnlyAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__()
            self.visible_texts = [
                "来源\n添加来源\n对话\n开始输入…\n0 个来源\nStudio",
                "来源\n添加来源\n对话\n开始输入…\n2 个来源",
                "来源\n添加来源\n对话\n这些文件记录了患者病情演变、检查结果和治疗需求，"
                "并已经生成可供继续提问的摘要内容。摘要列出了病史、辅助检查、诊断判断、"
                "治疗方案和患者诉求等内容，长度足以表明 NotebookLM 已经完成来源解析，"
                "不是单纯显示文件数量。\n开始输入…\n2 个来源\nStudio",
            ]

        def get_accessible_text(self) -> str:
            self.commands.append(("get_accessible_text", None))
            if self.visible_texts:
                return self.visible_texts.pop(0)
            return (
                "来源\n添加来源\n对话\n这些文件记录了患者病情演变、检查结果和治疗需求，"
                "并已经生成可供继续提问的摘要内容。摘要列出了病史、辅助检查、诊断判断、"
                "治疗方案和患者诉求等内容，长度足以表明 NotebookLM 已经完成来源解析，"
                "不是单纯显示文件数量。\n开始输入…\n2 个来源\nStudio"
            )

    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    first.write_text("a")
    second.write_text("b")
    automation = SourceCountOnlyAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)

    session.upload_sources([first, second])

    open_index = automation.commands.index(("click", (1370, 452)))
    assert automation.commands[open_index:].count(("get_accessible_text", None)) == 2


def test_upload_sources_accepts_generated_title_as_ready(tmp_path: Path, monkeypatch) -> None:
    class GeneratedTitleAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__()
            self.visible_texts = [
                "来源\n添加来源\n对话\nUntitled notebook\n2 个来源\nStudio",
                "来源\n添加来源\n对话\n董家鸿院长肝胆胰疾病诊前问卷：董生明病史纪要\n"
                "2 个来源\n·\n2026年4月28日\n2 个来源\nStudio",
            ]

        def get_accessible_text(self) -> str:
            self.commands.append(("get_accessible_text", None))
            if self.visible_texts:
                return self.visible_texts.pop(0)
            return (
                "来源\n添加来源\n对话\n董家鸿院长肝胆胰疾病诊前问卷：董生明病史纪要\n"
                "2 个来源\n·\n2026年4月28日\n2 个来源\nStudio"
            )

    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    first.write_text("a")
    second.write_text("b")
    automation = GeneratedTitleAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)

    session.upload_sources([first, second])

    open_index = automation.commands.index(("click", (1370, 452)))
    assert automation.commands[open_index:].count(("get_accessible_text", None)) == 1


def test_uploaded_sources_ready_accepts_single_line_generated_title(tmp_path: Path) -> None:
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=FakeAutomation(),
        delay_seconds=0,
    )
    text = (
        "来源\n添加来源\n对话\n"
        "北京友谊医院临床检验报告单 10 个来源 · 2026年4月29日\n"
        "4 个来源\nStudio\n"
        "Studio 输出将保存在此处。"
    )

    assert session._uploaded_sources_are_ready(text, expected_count=10) is True


def test_uploaded_sources_ready_accepts_untitled_image_only_notebook_with_expected_count(
    tmp_path: Path,
) -> None:
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=FakeAutomation(),
        delay_seconds=0,
    )
    text = (
        "来源\n添加来源\nimage a.jpg\nimage b.jpg\n对话\n"
        "Untitled notebook 10 个来源 · 2026年4月29日\n"
        "0 个来源\nStudio\n"
        "Studio 输出将保存在此处。"
    )

    assert session._uploaded_sources_are_ready(text, expected_count=10) is True


def test_start_deep_research_uses_bottom_chat_input_and_enter(tmp_path: Path) -> None:
    automation = FakeAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    session.start_deep_research("prompt")

    assert ("click", (158, 310)) not in automation.commands
    assert ("click", (160, 376)) not in automation.commands
    input_index = automation.commands.index(("click", (900, 1143)))
    paste_index = automation.commands.index(("paste_text", "prompt"))
    submit_index = automation.commands.index(("press", "Return"))
    assert input_index < paste_index < submit_index


def test_start_deep_research_uses_direct_chat_submit_when_available(tmp_path: Path) -> None:
    class DirectChatAutomation(FakeAutomation):
        def submit_chat_prompt(self, prompt: str) -> None:
            self.commands.append(("submit_chat_prompt", prompt))
            self.visible_text = f"今天\n{prompt}\nInitiating the Analysis..."

    automation = DirectChatAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    session.start_deep_research("prompt")

    assert ("submit_chat_prompt", "prompt") in automation.commands
    assert ("click", (900, 1143)) not in automation.commands
    assert ("paste_text", "prompt") not in automation.commands


def test_desktop_submit_chat_prompt_uses_cdp_textarea_submit() -> None:
    class CdpAutomation(DesktopAutomation):
        def __init__(self) -> None:
            super().__init__(display=":1", remote_debugging_port=9222)
            self.calls: list[tuple[str, dict | None]] = []

        def _find_cdp_target(self) -> dict:
            return {"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/1"}

        def _cdp_call(self, websocket_url: str, method: str, params: dict | None = None) -> dict:
            self.calls.append((method, params))
            return {"result": {"result": {"value": {"ok": True, "submitted": "button"}}}}

    automation = CdpAutomation()

    automation.submit_chat_prompt("prompt")

    assert automation.calls[0][0] == "Runtime.evaluate"
    params = automation.calls[0][1] or {}
    assert params["awaitPromise"] is True
    assert "textarea" in params["expression"]
    assert "prompt" in params["expression"]


def test_start_deep_research_dismisses_restore_prompt_before_bottom_chat_input(
    tmp_path: Path,
) -> None:
    automation = FakeAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    session.start_deep_research("prompt")

    input_index = automation.commands.index(("click", (900, 1143)))
    assert ("press", "Escape") in automation.commands[:input_index]


def test_start_deep_research_retries_when_prompt_does_not_appear(
    tmp_path: Path,
) -> None:
    class RetryPromptAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__()
            self.pastes = 0

        def paste_text(self, text: str) -> None:
            super().paste_text(text)
            self.pastes += 1
            if self.pastes == 2:
                self.visible_text = f"今天\n{text}\nInitiating the Analysis..."

    automation = RetryPromptAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    session.start_deep_research("prompt")

    assert automation.commands.count(("paste_text", "prompt")) == 2
    assert automation.commands.count(("press", "Return")) == 2


def test_generate_slide_deck_sets_simplified_chinese_before_clicking_presentation(
    tmp_path: Path,
) -> None:
    automation = FakeAutomation("配置设置\n默认")
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    session.generate_slide_deck(language="简体中文")

    settings_index = automation.commands.index(("click", (1706, 203)))
    output_language_index = automation.commands.index(("click", (1726, 394)))
    dropdown_index = automation.commands.index(("click", (1392, 553)))
    chinese_index = automation.commands.index(("click", (590, 720)))
    save_index = automation.commands.index(("click", (1385, 966)))
    presentation_index = automation.commands.index(("click", (1662, 193)))
    assert settings_index < output_language_index < dropdown_index < chinese_index < save_index < presentation_index
    assert automation.commands.count(("press", "Page_Down")) == 8


def test_generate_slide_deck_uses_direct_presentation_click_when_available(
    tmp_path: Path,
) -> None:
    class DirectPresentationAutomation(FakeAutomation):
        def click_text(self, text: str) -> None:
            self.commands.append(("click_text", text))

    automation = DirectPresentationAutomation("配置设置\n中文（简体）")
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    session.generate_slide_deck(language="简体中文")

    assert ("click_text", "演示文稿") in automation.commands
    assert ("click", (1662, 193)) not in automation.commands


def test_generate_slide_deck_uses_direct_presentation_generation_when_available(
    tmp_path: Path,
) -> None:
    class DirectPresentationAutomation(FakeAutomation):
        def start_presentation_generation(self) -> None:
            self.commands.append(("start_presentation_generation", None))

        def click_text(self, text: str) -> None:
            raise visual_adapter.RpaError("text fallback should not be used")

    automation = DirectPresentationAutomation("配置设置\n中文（简体）")
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    session.generate_slide_deck(language="简体中文")

    assert ("start_presentation_generation", None) in automation.commands
    assert ("click", (1662, 193)) not in automation.commands


def test_generate_slide_deck_does_not_reselect_language_when_already_simplified_chinese(
    tmp_path: Path,
) -> None:
    automation = FakeAutomation("配置设置\n中文（简体）")
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    session.generate_slide_deck(language="简体中文")

    assert ("click", (590, 720)) not in automation.commands
    assert ("press", "Page_Down") not in automation.commands
    save_index = automation.commands.index(("click", (1385, 966)))
    presentation_index = automation.commands.index(("click", (1662, 193)))
    assert save_index < presentation_index


def test_wait_for_research_waits_until_deep_research_is_complete(
    tmp_path: Path, monkeypatch
) -> None:
    class ResearchAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__()
            self.visible_texts = [
                "正在规划...请留在此页面",
                "Deep Research 深度研究已完成！\n发现了 10 个来源",
            ]

        def copy_selection(self) -> str:
            self.commands.append(("copy_selection", None))
            if self.visible_texts:
                return self.visible_texts.pop(0)
            return "Deep Research 深度研究已完成！"

        def get_accessible_text(self) -> str:
            self.commands.append(("get_accessible_text", None))
            if self.visible_texts:
                return self.visible_texts.pop(0)
            return "Deep Research 深度研究已完成！"

    automation = ResearchAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)

    session.wait_for_research()

    assert automation.commands.count(("get_accessible_text", None)) == 2
    assert ("hotkey", ("ctrl", "a")) not in automation.commands


def test_wait_for_research_accepts_fast_research_completion_text(
    tmp_path: Path, monkeypatch
) -> None:
    automation = FakeAutomation(visible_text="Fast Research 已完成！\n另外 7 个来源")
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)
    ticks = iter([0.0, 0.0, 2701.0])
    monkeypatch.setattr(visual_adapter.time, "monotonic", lambda: next(ticks))

    session.wait_for_research()

    assert ("screenshot", tmp_path / "screenshots" / "wait_for_research.png") in automation.commands


def test_wait_for_research_accepts_clinic_record_answer_text(
    tmp_path: Path, monkeypatch
) -> None:
    automation = FakeAutomation(visible_text="这是一份为您梳理的纯净版门诊记录单。\n主诉：腹痛。")
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)

    session.wait_for_research()

    assert ("screenshot", tmp_path / "screenshots" / "wait_for_research.png") in automation.commands


def test_wait_for_research_accepts_variant_clean_clinic_record_answer_text(
    tmp_path: Path, monkeypatch
) -> None:
    automation = FakeAutomation(
        visible_text="一份为您整理好的、去除了来源编号的纯净版门诊记录单：\n门诊记录单\n主诉：腹痛。"
    )
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)
    ticks = iter([0.0, 0.0, 2701.0])
    monkeypatch.setattr(visual_adapter.time, "monotonic", lambda: next(ticks))

    session.wait_for_research()

    assert ("screenshot", tmp_path / "screenshots" / "wait_for_research.png") in automation.commands


def test_wait_for_research_accepts_direct_clean_record_intro(
    tmp_path: Path, monkeypatch
) -> None:
    automation = FakeAutomation(
        visible_text="为您梳理的纯净版门诊记录单如下：\n门诊记录单\n【主诉】腹胀。"
    )
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)
    ticks = iter([0.0, 0.0, 2701.0])
    monkeypatch.setattr(visual_adapter.time, "monotonic", lambda: next(ticks))

    session.wait_for_research()

    assert ("screenshot", tmp_path / "screenshots" / "wait_for_research.png") in automation.commands


def test_wait_for_research_accepts_ready_clean_record_answer_variant(
    tmp_path: Path, monkeypatch
) -> None:
    automation = FakeAutomation(
        visible_text=(
            "根据您提供的病史资料和要求，已为您整理出一份纯净版"
            "（无来源编号）的标准门诊记录单：\n门诊记录单\n主诉：腹痛。\n回复已就绪。"
        )
    )
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)
    ticks = iter([0.0, 0.0, 2701.0])
    monkeypatch.setattr(visual_adapter.time, "monotonic", lambda: next(ticks))

    session.wait_for_research()

    assert ("screenshot", tmp_path / "screenshots" / "wait_for_research.png") in automation.commands


def test_wait_for_research_does_not_treat_prompt_with_ready_footer_as_complete(
    tmp_path: Path, monkeypatch
) -> None:
    class PromptOnlyAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__()
            self.visible_texts = [
                (
                    "今天\n请帮我梳理成 门诊记录单格式，不带来源 编号"
                    "\nPrioritizing User Request...\n回复已就绪。"
                ),
                "这是一份为您梳理的纯净版门诊记录单。\n主诉：腹痛。",
            ]

        def get_accessible_text(self) -> str:
            self.commands.append(("get_accessible_text", None))
            if self.visible_texts:
                return self.visible_texts.pop(0)
            return "这是一份为您梳理的纯净版门诊记录单。\n主诉：腹痛。"

    automation = PromptOnlyAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)

    session.wait_for_research()

    assert automation.commands.count(("get_accessible_text", None)) == 2


def test_wait_for_research_does_not_treat_step_progress_as_complete(
    tmp_path: Path, monkeypatch
) -> None:
    class ProgressAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__()
            self.visible_texts = [
                "Deep Research\n已完成第 2 步/共 5 步",
                "Deep Research 深度研究已完成！\n发现了 9 个来源",
            ]

        def get_accessible_text(self) -> str:
            self.commands.append(("get_accessible_text", None))
            if self.visible_texts:
                return self.visible_texts.pop(0)
            return "Deep Research 深度研究已完成！"

    automation = ProgressAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)

    session.wait_for_research()

    assert automation.commands.count(("get_accessible_text", None)) == 2


def test_wait_for_research_retries_invalid_ready_answer_and_ignores_old_invalid_text(
    tmp_path: Path, monkeypatch
) -> None:
    prompt = deep_research_prompt()

    class RetryInvalidAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__()
            self.visible_texts = [
                f"{prompt}\n目前笔记本中还没有添加任何来源。请先上传相关资料。\n回复已就绪。",
                f"{prompt}\n正在处理您的请求。",
                (
                    f"{prompt}\n目前笔记本中还没有添加任何来源。请先上传相关资料。\n回复已就绪。\n"
                    f"{prompt}\n# 门诊记录单\n【主诉】腹痛。\n【现病史】患者反复腹痛。\n回复已就绪。"
                ),
            ]

        def get_accessible_text(self) -> str:
            self.commands.append(("get_accessible_text", None))
            if self.visible_texts:
                return self.visible_texts.pop(0)
            return "# 门诊记录单\n【主诉】腹痛。\n【现病史】患者反复腹痛。\n回复已就绪。"

    automation = RetryInvalidAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )
    session.last_research_prompt = prompt
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)

    session.wait_for_research()

    assert ("paste_text", prompt) in automation.commands
    assert ("screenshot", tmp_path / "screenshots" / "wait_for_research.png") in automation.commands


def test_wait_for_slide_deck_waits_until_ready_message_appears(
    tmp_path: Path, monkeypatch
) -> None:
    class SlideAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__()
            self.visible_texts = [
                "正在生成演示文稿…\n基于26 个来源",
                "幻灯片“门诊记录单”已准备就绪。",
            ]

        def copy_selection(self) -> str:
            self.commands.append(("copy_selection", None))
            if self.visible_texts:
                return self.visible_texts.pop(0)
            return "幻灯片“门诊记录单”已准备就绪。"

        def get_accessible_text(self) -> str:
            self.commands.append(("get_accessible_text", None))
            if self.visible_texts:
                return self.visible_texts.pop(0)
            return "幻灯片“门诊记录单”已准备就绪。"

    automation = SlideAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)

    session.wait_for_slide_deck()

    assert automation.commands.count(("get_accessible_text", None)) == 2
    assert ("hotkey", ("ctrl", "a")) not in automation.commands


def test_wait_for_slide_deck_accepts_generated_presentation_item(
    tmp_path: Path, monkeypatch
) -> None:
    class SlideAutomation(FakeAutomation):
        def __init__(self) -> None:
            super().__init__()
            self.visible_texts = [
                "正在生成演示文稿…\n基于26 个来源",
                "Studio\nComplex Hepatobiliary Case Consultation\n26 个来源 · 9分钟前",
            ]

        def get_accessible_text(self) -> str:
            self.commands.append(("get_accessible_text", None))
            if self.visible_texts:
                return self.visible_texts.pop(0)
            return "Studio\nComplex Hepatobiliary Case Consultation\n26 个来源 · 9分钟前"

    automation = SlideAutomation()
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=tmp_path / "downloads",
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)

    session.wait_for_slide_deck()

    assert automation.commands.count(("get_accessible_text", None)) == 2


def test_extract_clinic_record_markdown_trims_page_chrome_after_answer(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_EXTRACTOR_API_KEY", raising=False)
    page_text = (
        "NotebookLM\n来源\n"
        f"{deep_research_prompt()}\n"
        "这是一份为您梳理的纯净版门诊记录单。\n\n"
        "# 门诊记录单\n"
        "主诉：腹痛。\n\n"
        "保存到笔记\n"
        "thumb_up\n"
        "Studio"
    )

    result = extract_clinic_record_markdown(page_text, deep_research_prompt())

    assert result == "# 门诊记录单\n\n## 二、主诉\n\n腹痛。"


def test_extract_clinic_record_markdown_uses_record_heading_after_completion_card(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_EXTRACTOR_API_KEY", raising=False)
    page_text = (
        f"{deep_research_prompt()}\n"
        "Deep Research 深度研究已完成！\n"
        "发现了 10 个来源\n\n"
        "# 门诊记录单\n"
        "主诉：腹痛。\n"
        "保存到笔记\n"
        "Studio"
    )

    result = extract_clinic_record_markdown(page_text, deep_research_prompt())

    assert result == "# 门诊记录单\n\n## 二、主诉\n\n腹痛。"


def test_extract_clinic_record_markdown_joins_punctuation_split_by_source_numbers(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_EXTRACTOR_API_KEY", raising=False)
    page_text = (
        f"{deep_research_prompt()}\n"
        "门诊记录单\n"
        "主诉 右上腹痛伴恶心呕吐\n"
        "3\n"
        "。\n"
        "现病史 患者因胆管占位性病变就诊\n"
        "1\n"
        "。2026年3月行PTCD。\n"
        "开始输入…\n"
        "28 个来源\n"
    )

    result = extract_clinic_record_markdown(page_text, deep_research_prompt())

    assert result == (
        "# 门诊记录单\n\n"
        "## 二、主诉\n\n"
        "右上腹痛伴恶心呕吐。\n\n"
        "## 三、现病史\n\n"
        "- 患者因胆管占位性病变就诊。\n"
        "- 2026年3月行PTCD。"
    )


def test_extract_clinic_record_markdown_formats_plain_clinic_record(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_EXTRACTOR_API_KEY", raising=False)
    page_text = (
        f"{deep_research_prompt()}\n"
        "门诊记录单\n"
        "基本信息\n"
        "姓名： 耿新忠\n"
        "性别： 男\n"
        "年龄： 71岁\n"
        "就诊科室： 肝胆胰外科\n"
        "主诉 右上腹痛伴恶心呕吐。\n"
        "现病史 患者因胆管占位性病变就诊。2026年3月行PTCD。\n"
        "既往史 否认高血压。否认既往腹部手术史。\n"
        "辅助检查\n"
        "影像学检查： CT提示胆总管扩张。\n"
        "实验室检查：\n"
        "肿瘤标志物（3月5日）：CA19-9异常升高。\n"
        "初步诊断\n"
        "胆管占位性病变（考虑胆管恶性肿瘤）。\n"
        "梗阻性黄疸（PTCD胆道引流术后）。\n"
        "诊疗计划与患者诉求\n"
        "需由专科医生结合病理明确疾病阶段。\n"
        "针对目前的呕吐和进食困难，有哪些具体的营养支持建议？\n"
    )

    result = extract_clinic_record_markdown(page_text, deep_research_prompt())

    assert result.startswith("# 门诊记录单\n\n## 一、基本信息")
    assert "- **姓名：** 耿新忠" in result
    assert "## 二、主诉\n\n右上腹痛伴恶心呕吐。" in result
    assert "- 患者因胆管占位性病变就诊。" in result
    assert "### 影像学检查\n\n- **影像学检查：** CT提示胆总管扩张。" in result
    assert "### 实验室检查\n\n- **肿瘤标志物（3月5日）：** CA19-9异常升高。" in result
    assert "1. **胆管占位性病变**（考虑胆管恶性肿瘤）。" in result
    assert "## 八、待进一步明确的问题\n\n- 针对目前的呕吐和进食困难，有哪些具体的营养支持建议？" in result


def test_extract_clinic_record_markdown_uses_configured_llm(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {"message": {"content": "```markdown\n门诊记录单\n主诉：腹痛。\n```"}}
                    ]
                }
            ).encode("utf-8")

    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    monkeypatch.setenv("RESEARCH_EXTRACTOR_API_KEY", "test-key")
    monkeypatch.setenv("RESEARCH_EXTRACTOR_MODEL", "test-model")
    monkeypatch.setenv("RESEARCH_EXTRACTOR_TIMEOUT_SECONDS", "12")
    monkeypatch.setattr(visual_adapter, "urlopen", fake_urlopen)

    result = extract_clinic_record_markdown(
        f"{deep_research_prompt()}\n这是一份为您梳理的纯净版门诊记录单。\n主诉：腹痛。",
        deep_research_prompt(),
    )

    assert result == "# 门诊记录单\n\n## 二、主诉\n\n腹痛。"
    assert requests[0][1] == 12.0
    payload = json.loads(requests[0][0].data.decode("utf-8"))
    assert payload["model"] == "test-model"


def test_save_results_downloads_powerpoint_from_presentation_menu(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"

    class DownloadAutomation(FakeAutomation):
        def download_presentation(self) -> None:
            self.commands.append(("download_presentation", None))
            downloads.mkdir(parents=True, exist_ok=True)
            (downloads / "deck.pptx").write_bytes(b"pptx")

        def copy_selection(self) -> str:
            self.commands.append(("copy_selection", None))
            return "https://notebooklm.google.com"

    automation = DownloadAutomation("页面噪音\n这是一份为您梳理的纯净版门诊记录单。\n主诉：腹痛。")
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=downloads,
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
        record_extractor=lambda text, prompt: "门诊记录单\n主诉：腹痛。",
    )

    artifacts = session.save_results(tmp_path / "result")

    assert tmp_path / "result" / "research.md" in artifacts.paths
    assert (tmp_path / "result" / "research.md").read_text(encoding="utf-8") == "门诊记录单\n主诉：腹痛。\n"
    assert tmp_path / "result" / "deck.pptx" in artifacts.paths
    assert (tmp_path / "result" / "deck.pptx").read_bytes() == b"pptx"
    assert ("hotkey", ("ctrl", "a")) not in automation.commands
    assert ("copy_selection", None) not in automation.commands
    assert ("download_presentation", None) in automation.commands
    assert ("click", (1863, 401)) not in automation.commands
    assert ("click", (1798, 514)) not in automation.commands


def test_desktop_download_presentation_uses_powerpoint_menu() -> None:
    class CdpAutomation(DesktopAutomation):
        def __init__(self) -> None:
            super().__init__(
                display=":1",
                remote_debugging_port=9222,
                downloads_dir=Path("/tmp/downloads"),
            )
            self.calls: list[tuple[str, dict | None]] = []

        def _find_cdp_target(self) -> dict:
            return {"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/1"}

        def _get_latest_presentation_download_url(self, websocket_url: str) -> str:
            assert websocket_url == "ws://127.0.0.1/devtools/page/1"
            return "https://contribution.usercontent.google.com/download?filename=deck.pptx"

        def _cdp_call(self, websocket_url: str, method: str, params: dict | None = None) -> dict:
            self.calls.append((method, params))
            return {"result": {}}

    automation = CdpAutomation()

    automation.download_presentation()

    assert ("Page.enable", {}) in automation.calls
    assert (
        "Page.setDownloadBehavior",
        {"behavior": "allow", "downloadPath": "/tmp/downloads"},
    ) in automation.calls
    assert (
        "Page.navigate",
        {"url": "https://contribution.usercontent.google.com/download?filename=deck.pptx"},
    ) in automation.calls


def test_extract_presentation_download_url_from_list_artifacts_body() -> None:
    body = """)]}'

123
[["wrb.fr","gArtLc","[[[\\"artifact-1\\",\\"Deck\\",8,null,null,null,null,null,null,null,null,null,null,null,null,null,null,[[null,\\"zh-Hans\\"],\\"Deck\\",[],\\"https://contribution.usercontent.google.com/download?c=pdf&filename=Deck.pdf\\",\\"https://contribution.usercontent.google.com/download?c=ppt&filename=Deck.pptx\\"]]]]"]]
"""

    assert (
        extract_presentation_download_url(body)
        == "https://contribution.usercontent.google.com/download?c=ppt&filename=Deck.pptx"
    )


def test_desktop_download_presentation_uses_existing_powerpoint_menu_before_reclicking() -> None:
    expression = DesktopAutomation(":1", remote_debugging_port=9222)._download_presentation_expression()

    assert "existingPowerPointItem" in expression
    assert expression.index("existingPowerPointItem") < expression.index("toolbarMenu.click")


def test_save_results_returns_to_studio_list_before_opening_presentation_menu(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"

    class DownloadAutomation(FakeAutomation):
        def click(self, x: int, y: int) -> None:
            super().click(x, y)
            if (x, y) == (1798, 514):
                downloads.mkdir(parents=True, exist_ok=True)
                (downloads / "deck.pptx").write_bytes(b"pptx")

    automation = DownloadAutomation("page text")
    session = VisualNotebookLMSession(
        display=":1",
        screenshots_dir=tmp_path / "screenshots",
        downloads_dir=downloads,
        notebooklm_url="https://notebooklm.google.com",
        automation=automation,
        delay_seconds=0,
    )

    session.save_results(tmp_path / "result")

    studio_index = automation.commands.index(("click", (1217, 184)))
    menu_index = automation.commands.index(("click", (1863, 401)))
    assert ("press", "Escape") in automation.commands[:studio_index]
    assert studio_index < menu_index


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


def test_find_cdp_target_prefers_focused_notebooklm_tab(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                [
                    {
                        "type": "page",
                        "url": "https://notebooklm.google.com/notebook/old",
                        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/old",
                    },
                    {
                        "type": "page",
                        "url": "https://notebooklm.google.com/notebook/active",
                        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/active",
                    },
                ]
            ).encode("utf-8")

    class FakeOpener:
        def open(self, url: str, timeout: int) -> FakeResponse:
            return FakeResponse()

    automation = DesktopAutomation(":1", remote_debugging_port=9222)

    def fake_cdp_call(websocket_url: str, method: str, params: dict | None = None) -> dict:
        return {"result": {"result": {"value": websocket_url.endswith("/active")}}}

    monkeypatch.setattr(visual_adapter, "build_opener", lambda proxy_handler: FakeOpener())
    monkeypatch.setattr(automation, "_cdp_call", fake_cdp_call)

    target = automation._find_cdp_target()

    assert target["url"] == "https://notebooklm.google.com/notebook/active"


def test_find_cdp_target_prefers_ready_notebooklm_tab_over_blank_tab(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                [
                    {
                        "type": "page",
                        "url": "https://notebooklm.google.com/notebook/ready",
                        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/ready",
                    },
                    {
                        "type": "page",
                        "url": "https://notebooklm.google.com/",
                        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/blank",
                    },
                ]
            ).encode("utf-8")

    class FakeOpener:
        def open(self, url: str, timeout: int) -> FakeResponse:
            return FakeResponse()

    automation = DesktopAutomation(":1", remote_debugging_port=9222)

    def fake_cdp_call(websocket_url: str, method: str, params: dict | None = None) -> dict:
        expression = (params or {}).get("expression", "")
        if expression == "document.hasFocus()":
            return {"result": {"result": {"value": False}}}
        if "innerText" in expression:
            length = 0 if websocket_url.endswith("/blank") else 42
            return {"result": {"result": {"value": length}}}
        raise AssertionError(f"unexpected CDP call: {method} {params}")

    monkeypatch.setattr(visual_adapter, "build_opener", lambda proxy_handler: FakeOpener())
    monkeypatch.setattr(automation, "_cdp_call", fake_cdp_call)

    target = automation._find_cdp_target()

    assert target["url"] == "https://notebooklm.google.com/notebook/ready"


def test_focus_chrome_retries_until_window_appears(monkeypatch) -> None:
    automation = DesktopAutomation(":1")
    attempts = []

    def fake_xdotool(*args: str) -> None:
        attempts.append(args)
        if len(attempts) == 1:
            raise subprocess.CalledProcessError(1, ["xdotool", *args])

    monkeypatch.setattr(automation, "_xdotool", fake_xdotool)
    monkeypatch.setattr(
        automation,
        "_xdotool_output",
        lambda *args: (_ for _ in ()).throw(subprocess.CalledProcessError(1, ["xdotool", *args])),
    )
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)

    automation.focus_chrome(timeout_seconds=1)

    assert len(attempts) == 2


def test_focus_chrome_falls_back_to_windowfocus_when_windowactivate_is_unsupported(monkeypatch) -> None:
    automation = DesktopAutomation(":1")
    calls = []

    def fake_xdotool(*args: str) -> None:
        calls.append(args)
        if args == ("search", "--onlyvisible", "--class", "chrome", "windowactivate", "--sync"):
            raise subprocess.CalledProcessError(1, ["xdotool", *args])

    monkeypatch.setattr(automation, "_xdotool", fake_xdotool)
    monkeypatch.setattr(automation, "_xdotool_output", lambda *args: "4194307\n")
    monkeypatch.setattr(visual_adapter.time, "sleep", lambda seconds: None)

    automation.focus_chrome(timeout_seconds=1)

    assert ("windowmove", "4194307", "0", "0") in calls
    assert ("windowsize", "4194307", "1920", "1200") in calls
    assert ("windowraise", "4194307") in calls
    assert ("windowfocus", "4194307") in calls
