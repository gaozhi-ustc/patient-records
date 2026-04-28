import base64
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import time
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from tkinter import Tk
from typing import Callable
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, build_opener
from urllib.request import Request, urlopen

from app.domain import deep_research_prompt
from app.worker.rpa.base import RpaArtifacts, RpaError


CLINIC_RECORD_ANSWER_MARKER = "这是一份为您梳理的纯净版门诊记录单"


def extract_clinic_record_markdown(page_text: str, prompt: str) -> str:
    candidate = _candidate_clinic_record_text(page_text, prompt)
    llm_result = _extract_clinic_record_with_llm(candidate, prompt)
    if llm_result.strip():
        return _format_clinic_record_markdown(_clean_clinic_record_markdown(llm_result))
    return _format_clinic_record_markdown(_clean_clinic_record_markdown(candidate))


def _candidate_clinic_record_text(page_text: str, prompt: str) -> str:
    text = page_text.replace("\r\n", "\n").replace("\r", "\n")
    start = 0
    if prompt:
        prompt_index = text.rfind(prompt)
        if prompt_index != -1:
            start = prompt_index + len(prompt)

    marker_index = text.find(CLINIC_RECORD_ANSWER_MARKER, start)
    if marker_index != -1:
        start = marker_index
    else:
        heading_positions = [
            position
            for position in (
                text.find("# 门诊记录单", start),
                text.find("门诊记录单", start),
            )
            if position != -1
        ]
        heading_index = min(heading_positions) if heading_positions else -1
        if heading_index != -1:
            start = heading_index

    return _trim_notebooklm_ui_tail(text[start:]).strip() or text.strip()


def _trim_notebooklm_ui_tail(text: str) -> str:
    tail_patterns = (
        r"\n保存到笔记\b",
        r"\n复制\b",
        r"\ncopy_all\b",
        r"\nthumb_up\b",
        r"\nthumb_down\b",
        r"\nNotebookLM\s*(?:提供的内容未必准确|can be inaccurate)",
        r"\n(?:Deep|Fast) Research[^\n]*(?:已完成[！!]?|completed)",
        r"\n演示文稿\b",
        r"\n音频概览\b",
        r"\n思维导图\b",
        r"\n简报文档\b",
        r"\nStudio\b",
        r"\n开始输入",
        r"\n\d+\s*个来源\b",
    )
    positions = []
    for pattern in tail_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match is not None and match.start() > 0:
            positions.append(match.start())
    if positions:
        return text[: min(positions)]
    return text


def _extract_clinic_record_with_llm(candidate_text: str, prompt: str) -> str:
    api_key = os.environ.get("RESEARCH_EXTRACTOR_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return ""

    api_url = _research_extractor_api_url()
    model = os.environ.get("RESEARCH_EXTRACTOR_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是病历文本抽取器。只输出 Markdown 格式的门诊记录单正文；"
                    "不要输出解释、不要保留 NotebookLM 页面导航、按钮、来源编号或引用编号。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请从下面 NotebookLM 页面复制文本中，提取用户这次提问之后返回的门诊记录单。\n"
                    f"用户提问：{prompt}\n\n页面相关文本：\n{candidate_text[-60000:]}"
                ),
            },
        ],
    }
    request = Request(
        api_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        timeout = float(os.environ.get("RESEARCH_EXTRACTOR_TIMEOUT_SECONDS", "60"))
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return ""

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message", {})
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _research_extractor_api_url() -> str:
    explicit_url = os.environ.get("RESEARCH_EXTRACTOR_API_URL")
    if explicit_url:
        return explicit_url
    base_url = (
        os.environ.get("RESEARCH_EXTRACTOR_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    )
    if base_url.rstrip("/").endswith("/chat/completions"):
        return base_url
    return f"{base_url.rstrip('/')}/chat/completions"


def _clean_clinic_record_markdown(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    cleaned = re.sub(r"^```(?:markdown|md)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    lines: list[str] = []
    previous_blank = False
    for line in cleaned.splitlines():
        stripped_line = re.sub(r"\s*\[\d+(?:\s*,\s*\d+)*\]\s*$", "", line.rstrip())
        stripped_line = stripped_line.strip()
        if re.fullmatch(r"\d+(?:\s+\d+)*", stripped_line):
            continue
        if not stripped_line.strip():
            if not previous_blank:
                lines.append("")
            previous_blank = True
            continue
        stripped_line = re.sub(r"^([，。；：！？、,.!?:;])\s+", r"\1", stripped_line)
        if lines and not previous_blank and stripped_line[0] in "，。；：！？、,.!?:;)]）】」》":
            lines[-1] = f"{lines[-1]}{stripped_line}"
            previous_blank = False
            continue
        lines.append(stripped_line)
        previous_blank = False
    return "\n".join(lines).strip()


def _format_clinic_record_markdown(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return cleaned
    if _clinic_record_already_formatted(cleaned):
        return cleaned
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not _looks_like_clinic_record(lines):
        return cleaned

    formatter = _ClinicRecordFormatter(lines)
    return formatter.format()


def _clinic_record_already_formatted(text: str) -> bool:
    return text.lstrip().startswith("# 门诊记录单") and "\n## " in text and (
        "\n- " in text or "\n1. " in text or "**" in text
    )


def _looks_like_clinic_record(lines: list[str]) -> bool:
    if not lines:
        return False
    if "门诊记录单" not in lines[0] and not any("门诊记录单" == line for line in lines[:3]):
        return False
    section_markers = ("基本信息", "主诉", "现病史", "既往史", "辅助检查", "初步诊断", "诊疗计划")
    return any(line.startswith(section_markers) for line in lines[1:])


class _ClinicRecordFormatter:
    main_sections = {
        "基本信息",
        "主诉",
        "现病史",
        "既往史",
        "辅助检查",
        "初步诊断",
        "诊疗计划与患者诉求",
        "诊疗计划",
        "患者诉求",
    }

    section_titles = {
        "基本信息": "## 一、基本信息",
        "主诉": "## 二、主诉",
        "现病史": "## 三、现病史",
        "既往史": "## 四、既往史",
        "辅助检查": "## 五、辅助检查",
        "初步诊断": "## 六、初步诊断",
        "诊疗计划与患者诉求": "## 七、诊疗计划与患者诉求",
        "诊疗计划": "## 七、诊疗计划与患者诉求",
        "患者诉求": "## 七、诊疗计划与患者诉求",
    }

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.index = 1 if "门诊记录单" in lines[0] else 0
        self.output: list[str] = ["# 门诊记录单"]
        self.questions: list[str] = []

    def format(self) -> str:
        while self.index < len(self.lines):
            line = self.lines[self.index]
            section = self._section_name(line)
            if section is None:
                if line.endswith("？") or line.endswith("?"):
                    self.questions.append(line)
                self.index += 1
                continue
            if section == "辅助检查":
                self._format_auxiliary_exams()
            elif section == "初步诊断":
                self._format_numbered_section(section, bold_diagnosis=True)
            elif section in {"诊疗计划与患者诉求", "诊疗计划", "患者诉求"}:
                self._format_plan_section(section)
            elif section == "基本信息":
                self._format_basic_info()
            elif section in {"主诉", "现病史", "既往史"}:
                self._format_text_section(section)
        if self.questions:
            self._append_block("## 八、待进一步明确的问题", [f"- {question}" for question in self.questions])
        return "\n".join(self.output).strip()

    def _format_basic_info(self) -> None:
        self._append_heading(self.section_titles["基本信息"])
        self.index += 1
        items: list[str] = []
        while self.index < len(self.lines) and self._section_name(self.lines[self.index]) is None:
            items.append(_format_field_bullet(self.lines[self.index]))
            self.index += 1
        self._append_lines(items)

    def _format_text_section(self, section: str) -> None:
        self._append_heading(self.section_titles[section])
        line = self.lines[self.index]
        body = self._remove_section_prefix(line, section)
        self.index += 1
        parts = [body] if body else []
        while self.index < len(self.lines) and self._section_name(self.lines[self.index]) is None:
            current = self.lines[self.index]
            if current.endswith("？") or current.endswith("?"):
                self.questions.append(current)
            else:
                parts.append(current)
            self.index += 1
        if section == "主诉":
            self._append_lines([" ".join(parts).strip()])
            return
        self._append_lines([f"- {item}" for item in _split_sentences(" ".join(parts))])

    def _format_auxiliary_exams(self) -> None:
        self._append_heading(self.section_titles["辅助检查"])
        self.index += 1
        while self.index < len(self.lines):
            section = self._section_name(self.lines[self.index])
            if section is not None:
                return
            line = self.lines[self.index]
            if line.startswith("影像学检查"):
                self._format_exam_subsection("影像学检查")
                continue
            if line.startswith("实验室检查"):
                self._format_exam_subsection("实验室检查")
                continue
            self._append_lines([_format_field_bullet(line)])
            self.index += 1

    def _format_exam_subsection(self, subsection: str) -> None:
        self._append_heading(f"### {subsection}")
        line = self.lines[self.index]
        body = self._remove_section_prefix(line, subsection)
        self.index += 1
        items: list[str] = []
        if body:
            items.append(f"- **{subsection}：** {body}")
        while self.index < len(self.lines):
            next_line = self.lines[self.index]
            if self._section_name(next_line) is not None or next_line.startswith(("影像学检查", "实验室检查")):
                break
            items.append(_format_field_bullet(next_line))
            self.index += 1
        self._append_lines(items)

    def _format_numbered_section(self, section: str, *, bold_diagnosis: bool = False) -> None:
        self._append_heading(self.section_titles[section])
        self.index += 1
        items: list[str] = []
        while self.index < len(self.lines) and self._section_name(self.lines[self.index]) is None:
            line = self.lines[self.index]
            if line.endswith("？") or line.endswith("?"):
                self.questions.append(line)
            elif bold_diagnosis:
                items.append(f"{len(items) + 1}. {_bold_diagnosis(line)}")
            else:
                items.append(f"{len(items) + 1}. {line}")
            self.index += 1
        self._append_lines(items)

    def _format_plan_section(self, section: str) -> None:
        self._append_heading(self.section_titles[section])
        line = self.lines[self.index]
        body = self._remove_section_prefix(line, section)
        self.index += 1
        parts = [body] if body else []
        while self.index < len(self.lines) and self._section_name(self.lines[self.index]) is None:
            parts.append(self.lines[self.index])
            self.index += 1
        items: list[str] = []
        for item in _split_sentences(" ".join(parts)):
            if item.endswith("？") or item.endswith("?"):
                self.questions.append(item)
            else:
                items.append(f"{len(items) + 1}. {item}")
        self._append_lines(items)

    def _append_block(self, heading: str, lines: list[str]) -> None:
        self._append_heading(heading)
        self._append_lines(lines)

    def _append_heading(self, heading: str) -> None:
        if self.output[-1] != "":
            self.output.append("")
        self.output.append(heading)
        self.output.append("")

    def _append_lines(self, lines: list[str]) -> None:
        for line in lines:
            if line.strip():
                self.output.append(line.strip())

    def _section_name(self, line: str) -> str | None:
        stripped = line.strip(" ：:")
        for section in sorted(self.main_sections, key=len, reverse=True):
            if stripped == section or line.startswith(f"{section} ") or line.startswith(f"{section}："):
                return section
        return None

    def _remove_section_prefix(self, line: str, section: str) -> str:
        body = line[len(section) :].strip()
        return body.lstrip("：: ").strip()


def _format_field_bullet(line: str) -> str:
    match = re.match(r"([^：:]{1,30})[：:]\s*(.+)", line)
    if match is None:
        return f"- {line}"
    return f"- **{match.group(1)}：** {match.group(2).strip()}"


def _split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    parts = re.findall(r".+?(?:[。！？?]|$)", normalized)
    return [part.strip() for part in parts if part.strip()]


def _bold_diagnosis(line: str) -> str:
    match = re.match(r"([^（(。]+)(.*)", line)
    if match is None:
        return f"**{line}**"
    diagnosis = match.group(1).strip()
    rest = match.group(2).strip()
    if rest:
        return f"**{diagnosis}**{rest}"
    return f"**{diagnosis}**"


def _research_result_is_ready(visible_text: str) -> bool:
    if re.search(r"(Deep|Fast) Research[^\n]*(已完成[！!]|completed)", visible_text, re.IGNORECASE):
        return True
    if CLINIC_RECORD_ANSWER_MARKER in visible_text:
        return True
    if "回复已就绪" in visible_text and "门诊记录单" in visible_text:
        return True
    return re.search(
        r"(一份为您[^\n]{0,80}纯净版门诊记录单|已为您整理出一份[^\n]{0,120}门诊记录单|纯净版门诊记录单[：:]\s*\n\s*门诊记录单)",
        visible_text,
    ) is not None


@dataclass(frozen=True)
class VisualCoordinates:
    create_notebook_primary: tuple[int, int] = (1538, 143)
    create_notebook_fallback: tuple[int, int] = (1684, 198)
    recent_untitled_notebook: tuple[int, int] = (300, 724)
    chrome_restore_close: tuple[int, int] = (1890, 144)
    sources_tab: tuple[int, int] = (50, 207)
    add_source: tuple[int, int] = (252, 320)
    add_source_research_dropdown: tuple[int, int] = (878, 600)
    add_source_deep_research: tuple[int, int] = (872, 665)
    upload_source: tuple[int, int] = (805, 791)
    file_picker_list: tuple[int, int] = (820, 566)
    file_picker_open: tuple[int, int] = (1370, 452)
    web_search_input: tuple[int, int] = (200, 276)
    fast_research: tuple[int, int] = (158, 310)
    deep_research: tuple[int, int] = (160, 376)
    web_search_submit: tuple[int, int] = (447, 310)
    chat_prompt_input: tuple[int, int] = (900, 1143)
    slide_deck: tuple[int, int] = (1650, 238)
    settings_button: tuple[int, int] = (1706, 203)
    output_language_menu: tuple[int, int] = (1726, 394)
    output_language_dropdown: tuple[int, int] = (1392, 553)
    language_simplified_chinese: tuple[int, int] = (590, 720)
    language_save: tuple[int, int] = (1385, 966)
    page_body: tuple[int, int] = (900, 500)
    studio_breadcrumb: tuple[int, int] = (1217, 184)
    presentation_item_menu: tuple[int, int] = (1863, 401)
    download_powerpoint: tuple[int, int] = (1798, 514)


class DesktopAutomation:
    def __init__(self, display: str, remote_debugging_port: int | None = None) -> None:
        self.display = display
        self.remote_debugging_port = remote_debugging_port
        self._cdp_ids = count(1)

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

    def wait_for_window(self, name: str, timeout_seconds: float = 15.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        last_error: subprocess.CalledProcessError | None = None
        while time.monotonic() <= deadline:
            try:
                self._xdotool("search", "--onlyvisible", "--name", name, "windowactivate", "--sync")
                return
            except subprocess.CalledProcessError as error:
                last_error = error
                time.sleep(0.5)
        raise RpaError(f"Window was not found for visual automation: {name}") from last_error

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

    def get_accessible_text(self) -> str:
        if self.remote_debugging_port is not None:
            return self._get_cdp_body_text()
        self.focus_chrome()
        try:
            import pyatspi
        except ImportError as error:
            raise RpaError("pyatspi is required for non-selecting visual text reads") from error

        desktop = pyatspi.Registry.getDesktop(0)
        chrome_apps = []
        for index in range(desktop.childCount):
            child = desktop.getChildAtIndex(index)
            name = (child.name or "").lower()
            if "chrome" in name:
                chrome_apps.append(child)
        if not chrome_apps:
            raise RpaError("Chrome accessibility tree is unavailable")

        parts: list[str] = []
        visited = 0
        for app in chrome_apps:
            visited = self._collect_accessible_text(app, parts, visited)
        text = "\n".join(part for part in parts if part.strip())
        if not text.strip():
            raise RpaError("Chrome accessibility tree did not expose page text")
        return text

    def _get_cdp_body_text(self) -> str:
        target = self._find_cdp_target()
        response = self._cdp_call(
            target["webSocketDebuggerUrl"],
            "Runtime.evaluate",
            {
                "expression": "document.body ? document.body.innerText : ''",
                "returnByValue": True,
            },
        )
        result = response.get("result", {}).get("result", {})
        text = result.get("value")
        if not isinstance(text, str) or not text.strip():
            raise RpaError("Chrome DevTools did not expose page text")
        return text

    def _find_cdp_target(self) -> dict:
        opener = build_opener(ProxyHandler({}))
        url = f"http://127.0.0.1:{self.remote_debugging_port}/json/list"
        try:
            with opener.open(url, timeout=5) as response:
                targets = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, json.JSONDecodeError) as error:
            raise RpaError(f"Chrome DevTools target list is unavailable on port {self.remote_debugging_port}") from error
        notebooklm_targets = [
            target
            for target in targets
            if target.get("type") == "page" and "notebooklm.google.com" in target.get("url", "")
        ]
        for target in notebooklm_targets:
            if self._target_has_focus(target):
                return target
        if notebooklm_targets:
            return notebooklm_targets[-1]
        raise RpaError("NotebookLM Chrome DevTools target was not found")

    def _target_has_focus(self, target: dict) -> bool:
        websocket_url = target.get("webSocketDebuggerUrl")
        if not isinstance(websocket_url, str):
            return False
        try:
            response = self._cdp_call(
                websocket_url,
                "Runtime.evaluate",
                {
                    "expression": "document.hasFocus()",
                    "returnByValue": True,
                },
            )
        except RpaError:
            return False
        return response.get("result", {}).get("result", {}).get("value") is True

    def _cdp_call(self, websocket_url: str, method: str, params: dict | None = None) -> dict:
        request_id = next(self._cdp_ids)
        parsed = urlparse(websocket_url)
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        if parsed.scheme == "wss":
            raise RpaError("Secure Chrome DevTools WebSocket is not supported")
        sock = socket.create_connection((parsed.hostname or "127.0.0.1", port), timeout=5)
        try:
            self._websocket_handshake(sock, parsed)
            self._websocket_send_json(
                sock,
                {
                    "id": request_id,
                    "method": method,
                    "params": params or {},
                },
            )
            deadline = time.monotonic() + 10
            while time.monotonic() <= deadline:
                message = self._websocket_recv_json(sock)
                if message.get("id") == request_id:
                    if "error" in message:
                        raise RpaError(f"Chrome DevTools call failed: {message['error']}")
                    return message
            raise RpaError(f"Chrome DevTools call timed out: {method}")
        finally:
            sock.close()

    def _websocket_handshake(self, sock: socket.socket, parsed) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{parsed.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RpaError("Chrome DevTools WebSocket handshake failed")

    def _websocket_send_json(self, sock: socket.socket, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        mask = os.urandom(4)
        header = bytearray([0x81])
        length = len(body)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask)
        sock.sendall(header + bytes(byte ^ mask[index % 4] for index, byte in enumerate(body)))

    def _websocket_recv_json(self, sock: socket.socket) -> dict:
        header = self._recv_exact(sock, 2)
        first, second = header
        opcode = first & 0x0F
        if opcode == 8:
            raise RpaError("Chrome DevTools WebSocket closed")
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(sock, 8))[0]
        mask = self._recv_exact(sock, 4) if second & 0x80 else None
        body = self._recv_exact(sock, length)
        if mask is not None:
            body = bytes(byte ^ mask[index % 4] for index, byte in enumerate(body))
        if opcode != 1:
            return {}
        return json.loads(body.decode("utf-8"))

    def _recv_exact(self, sock: socket.socket, size: int) -> bytes:
        data = b""
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise RpaError("Chrome DevTools WebSocket closed unexpectedly")
            data += chunk
        return data

    def _collect_accessible_text(self, node, parts: list[str], visited: int, limit: int = 5000) -> int:
        if visited >= limit:
            return visited
        visited += 1
        for value in (getattr(node, "name", ""), getattr(node, "description", "")):
            if value:
                parts.append(str(value))
        try:
            text = node.queryText()
            value = text.getText(0, text.characterCount)
            if value:
                parts.append(value)
        except Exception:
            pass
        try:
            child_count = node.childCount
        except Exception:
            return visited
        for index in range(child_count):
            try:
                visited = self._collect_accessible_text(node.getChildAtIndex(index), parts, visited, limit)
            except Exception:
                pass
            if visited >= limit:
                break
        return visited

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
        remote_debugging_port: int | None = None,
        record_extractor: Callable[[str, str], str] | None = None,
    ) -> None:
        self.display = display
        self.screenshots_dir = screenshots_dir
        self.downloads_dir = downloads_dir
        self.notebooklm_url = notebooklm_url
        self.automation = automation or DesktopAutomation(display, remote_debugging_port=remote_debugging_port)
        self.coordinates = coordinates
        self.delay_seconds = delay_seconds
        self.record_extractor = record_extractor or extract_clinic_record_markdown
        self.last_research_prompt = deep_research_prompt()

    def ensure_logged_in(self) -> bool:
        self._open_url(self.notebooklm_url)
        try:
            self._wait_for_home_page(timeout_seconds=10)
        except RpaError:
            pass
        current_url = self._copy_current_url().lower()
        self._screenshot("ensure_logged_in")
        return "accounts.google.com" not in current_url and "signin" not in current_url

    def create_new_notebook(self) -> tuple[str, str]:
        last_error: RpaError | None = None
        for _ in range(3):
            self._open_url(self.notebooklm_url)
            current_url = self.notebooklm_url
            try:
                self._wait_for_home_page()
                current_url = self._copy_current_url()
                self.automation.press("Escape")
                self._click(self.coordinates.chrome_restore_close)
                self.automation.press("Escape")
                self._sleep()
                self._click(self.coordinates.create_notebook_fallback)
                self.automation.press("Escape")
                self._sleep()
                notebook_url = self._wait_for_notebook_url(ignored_url=current_url)
                self._wait_for_blank_new_notebook()
                notebook_id = self._extract_notebook_id(notebook_url)
                self.automation.press("Escape")
                self._sleep()
                self._screenshot("create_new_notebook")
                return notebook_id, notebook_url
            except RpaError as error:
                last_error = error
                self.automation.press("Escape")
                self._sleep()
                try:
                    self._click(self.coordinates.recent_untitled_notebook)
                    self._sleep()
                    notebook_url = self._wait_for_notebook_url(ignored_url=current_url)
                    self._wait_for_blank_new_notebook()
                    notebook_id = self._extract_notebook_id(notebook_url)
                    self.automation.press("Escape")
                    self._sleep()
                    self._screenshot("create_new_notebook")
                    return notebook_id, notebook_url
                except RpaError as fallback_error:
                    last_error = fallback_error
                    self.automation.press("Escape")
                self._sleep_at_least(2.0)
        if last_error is not None:
            raise last_error
        raise RpaError("Cannot create a new NotebookLM notebook")

    def upload_sources(self, files: list[Path]) -> int:
        uploadable = [path for path in files if path.is_file()]
        if not uploadable:
            raise RpaError("No uploadable files found")
        parent_dir = self._common_parent(uploadable)
        self.automation.focus_chrome()
        self.automation.press("Escape")
        self._sleep()
        visible_text = self._wait_for_notebook_ready()
        last_error: RpaError | None = None
        for _ in range(2):
            if not self._add_source_dialog_is_open(visible_text):
                self._click(self.coordinates.add_source)
                self._sleep()
            self._select_add_source_deep_research()
            self._click(self.coordinates.upload_source)
            self._sleep()
            try:
                self.automation.wait_for_window("Open Files")
                last_error = None
                break
            except RpaError as error:
                last_error = error
                visible_text = self._read_visible_text()
        if last_error is not None:
            raise last_error
        self.automation.hotkey("ctrl", "l")
        self.automation.paste_text(str(parent_dir))
        self._sleep()
        self.automation.press("Return")
        self._sleep_at_least(2.0)
        self._click(self.coordinates.file_picker_list)
        self._sleep()
        self.automation.hotkey("ctrl", "a")
        self._sleep()
        self._click(self.coordinates.file_picker_open)
        self._wait_for_uploaded_sources(len(uploadable))
        self._screenshot("upload_sources")
        return len(uploadable)

    def start_deep_research(self, prompt: str) -> None:
        self.last_research_prompt = prompt
        self.automation.focus_chrome()
        self.automation.press("Escape")
        self._sleep()
        self._click(self.coordinates.chrome_restore_close)
        self._sleep()
        self.automation.press("Escape")
        for attempt in range(3):
            self._click(self.coordinates.chat_prompt_input)
            self._sleep()
            self.automation.paste_text(prompt)
            self._sleep()
            self.automation.press("Return")
            self._sleep_at_least(2.0)
            try:
                visible_text = self._read_visible_text()
            except RpaError:
                visible_text = ""
            if prompt in visible_text or _research_result_is_ready(visible_text):
                break
            if attempt < 2:
                self.automation.press("Escape")
        self._screenshot("start_deep_research")

    def wait_for_research(self) -> None:
        deadline = time.monotonic() + 2700
        last_text = ""
        while time.monotonic() <= deadline:
            last_text = self._read_visible_text()
            if _research_result_is_ready(last_text):
                self._screenshot("wait_for_research")
                return
            time.sleep(max(self.delay_seconds, 5.0))
        raise RpaError(f"Deep Research did not complete: {last_text[:120]}")

    def generate_slide_deck(self, language: str) -> None:
        self.automation.focus_chrome()
        if language == "简体中文":
            self._set_output_language_to_simplified_chinese()
        self._sleep()
        self._click(self.coordinates.slide_deck)
        self._screenshot("generate_slide_deck")

    def wait_for_slide_deck(self) -> None:
        deadline = time.monotonic() + 1800
        last_text = ""
        while time.monotonic() <= deadline:
            last_text = self._read_visible_text()
            if self._slide_deck_is_ready(last_text):
                self._screenshot("wait_for_slide_deck")
                return
            time.sleep(max(self.delay_seconds, 5.0))
        raise RpaError(f"Slide deck did not complete: {last_text[:120]}")

    def save_results(self, result_dir: Path) -> RpaArtifacts:
        result_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        existing_downloads = set(self.downloads_dir.glob("*"))
        self.automation.focus_chrome()
        self._click(self.coordinates.chrome_restore_close)
        self._sleep()
        self.automation.press("Escape")
        self._sleep()
        self._click(self.coordinates.studio_breadcrumb)
        self._sleep()
        self._click(self.coordinates.page_body)
        self._sleep()
        self.automation.hotkey("ctrl", "a")
        self._sleep()
        copied_text = self.automation.copy_selection()
        extracted_record = self.record_extractor(copied_text, self.last_research_prompt)
        research_path = result_dir / "research.md"
        research_path.write_text(extracted_record.rstrip() + "\n", encoding="utf-8")
        self._click(self.coordinates.presentation_item_menu)
        self._sleep()
        self._click(self.coordinates.download_powerpoint)
        downloaded = self._wait_for_new_downloads(existing_downloads)
        result_downloads = [self._copy_download_to_result(path, result_dir) for path in downloaded]
        screenshot_path = result_dir / "screenshots" / "final.png"
        self.automation.screenshot(screenshot_path)
        artifacts = [research_path, screenshot_path]
        artifacts.extend(result_downloads)
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

    def _sleep_at_least(self, minimum_seconds: float) -> None:
        if self.delay_seconds > 0:
            time.sleep(max(self.delay_seconds, minimum_seconds))

    def _wait_for_new_downloads(self, existing_downloads: set[Path], timeout_seconds: float = 60.0) -> list[Path]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() <= deadline:
            downloaded = [
                path
                for path in self.downloads_dir.glob("*")
                if path not in existing_downloads
                and path.is_file()
                and not path.name.endswith(".crdownload")
                and path.suffix.lower() in {".pptx", ".pdf"}
            ]
            if downloaded:
                return sorted(downloaded)
            time.sleep(0.5)
        raise RpaError("PowerPoint download did not appear")

    def _copy_download_to_result(self, download_path: Path, result_dir: Path) -> Path:
        target = result_dir / download_path.name
        if target.exists():
            stem = download_path.stem
            suffix = download_path.suffix
            for index in range(1, 1000):
                candidate = result_dir / f"{stem}-{index}{suffix}"
                if not candidate.exists():
                    target = candidate
                    break
        shutil.copy2(download_path, target)
        return target

    def _wait_for_notebook_ready(self, timeout_seconds: float = 60.0) -> str:
        deadline = time.monotonic() + timeout_seconds
        last_text = ""
        while time.monotonic() <= deadline:
            last_text = self._read_visible_text()
            if "添加来源" in last_text and "Loading Notebook" not in last_text:
                return last_text
            time.sleep(0.5)
        raise RpaError(f"Notebook page was not ready for upload: {last_text[:120]}")

    def _wait_for_uploaded_sources(self, expected_count: int, timeout_seconds: float = 1200.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        last_text = ""
        while time.monotonic() <= deadline:
            last_text = self._read_visible_text()
            if self._uploaded_sources_are_ready(last_text, expected_count):
                return
            time.sleep(2.0)
        raise RpaError(f"Uploaded sources were not ready: expected {expected_count}, saw {last_text[:120]}")

    def _read_visible_text(self) -> str:
        self.automation.focus_chrome()
        return self.automation.get_accessible_text()

    def _select_add_source_deep_research(self) -> None:
        self._click(self.coordinates.add_source_research_dropdown)
        self._sleep()
        self._click(self.coordinates.add_source_deep_research)
        self._sleep()

    def _chat_source_count(self, visible_text: str) -> int:
        if "开始输入" in visible_text:
            visible_text = visible_text.split("开始输入", 1)[1]
        match = re.search(r"(\d+)\s*个来源", visible_text)
        if match is None:
            return 0
        return int(match.group(1))

    def _add_source_dialog_is_open(self, visible_text: str) -> bool:
        return "上传文件" in visible_text and "或拖放文件" in visible_text

    def _uploaded_sources_are_ready(self, visible_text: str, expected_count: int) -> bool:
        if self._chat_source_count(visible_text) < expected_count:
            return False
        if "对话" not in visible_text or "Studio" not in visible_text:
            return False
        chat_panel = visible_text.split("对话", 1)[1].split("Studio", 1)[0]
        if any(marker in chat_panel for marker in ("这些文件", "摘要", "总结", "根据")):
            return True
        return "Untitled notebook" not in chat_panel and re.search(r"\S.+\n\d+\s*个来源\s*·", chat_panel) is not None

    def _slide_deck_is_ready(self, visible_text: str) -> bool:
        if "正在生成演示文稿" in visible_text:
            return False
        if "幻灯片" in visible_text and "已准备就绪" in visible_text:
            return True
        return (
            re.search(r"\n[^\n]+\n\d+\s*个来源\s*·\s*(刚刚|\d+\s*分钟|\d+\s*小时)", visible_text)
            is not None
        )

    def _set_output_language_to_simplified_chinese(self) -> None:
        self._click(self.coordinates.settings_button)
        self._sleep()
        self._click(self.coordinates.output_language_menu)
        self._sleep()
        settings_text = self._read_visible_text()
        if "中文（简体）" not in settings_text:
            self._click(self.coordinates.output_language_dropdown)
            self._sleep()
            for _ in range(8):
                self.automation.press("Page_Down")
            self._sleep()
            self._click(self.coordinates.language_simplified_chinese)
            self._sleep()
        self._click(self.coordinates.language_save)
        self._sleep()

    def _extract_notebook_id(self, url: str) -> str:
        parts = [part for part in urlparse(url).path.split("/") if part]
        if not parts:
            raise RpaError(f"Cannot extract notebook_id from URL: {url}")
        return parts[-1]

    def _wait_for_home_page(self, timeout_seconds: float = 20.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        last_text = ""
        while time.monotonic() <= deadline:
            last_text = self._read_visible_text()
            if (
                "NotebookLM" in last_text
                and (
                    "我的笔记本" in last_text
                    or "精选笔记本" in last_text
                    or "最近打开过的笔记本" in last_text
                )
            ):
                return
            time.sleep(0.5)
        raise RpaError(f"NotebookLM home page was not ready: {last_text[:120]}")

    def _wait_for_notebook_url(self, timeout_seconds: float = 15.0, ignored_url: str | None = None) -> str:
        deadline = time.monotonic() + timeout_seconds
        last_url = ""
        while time.monotonic() <= deadline:
            last_url = self._copy_current_url()
            path_parts = [part for part in urlparse(last_url).path.split("/") if part]
            if (
                len(path_parts) >= 2
                and path_parts[-2] == "notebook"
                and path_parts[-1] != "creating"
                and not self._same_notebook_url(last_url, ignored_url)
            ):
                return last_url
            time.sleep(0.5)
        raise RpaError(f"Cannot extract notebook_id from URL: {last_url}")

    def _wait_for_blank_new_notebook(self, timeout_seconds: float = 30.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        last_text = ""
        while time.monotonic() <= deadline:
            last_text = self._read_visible_text()
            if (
                "0 个来源" in last_text
                and (
                    "已保存的来源将显示在此处" in last_text
                    or "添加来源后" in last_text
                    or "Untitled notebook" in last_text
                )
            ):
                return
            time.sleep(0.5)
        raise RpaError(f"New notebook did not become blank: {last_text[:120]}")

    def _common_parent(self, files: list[Path]) -> Path:
        parents = {path.parent for path in files}
        if len(parents) != 1:
            raise RpaError("Visual upload currently requires all files to be in one directory")
        return parents.pop()

    def _same_notebook_url(self, url: str, other_url: str | None) -> bool:
        if other_url is None:
            return False
        try:
            return self._extract_notebook_id(url) == self._extract_notebook_id(other_url)
        except RpaError:
            return False
