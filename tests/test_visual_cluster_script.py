import os
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "start_visual_cluster.sh"


def test_visual_cluster_script_exists_and_is_executable() -> None:
    assert SCRIPT_PATH.exists()
    assert os.access(SCRIPT_PATH, os.X_OK)


def test_visual_cluster_script_starts_proxy_visual_workers_on_display_range() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "DISPLAY_START=\"${DISPLAY_START:-20}\"" in script
    assert "DISPLAY_END=\"${DISPLAY_END:-29}\"" in script
    assert "VNC_GEOMETRY=\"${VNC_GEOMETRY:-1920x1200}\"" in script
    assert "PROXY_URL=\"${PROXY_URL:-http://localhost:7890}\"" in script
    assert "NOTEBOOKLM_URL=\"${NOTEBOOKLM_URL:-https://notebooklm.google.com}\"" in script
    assert "vncserver \"$display\" -localhost no" in script
    assert "setsid -f env" in script
    assert "AUTOMATION_MODE=\"visual\"" in script
    assert "NOTEBOOKLM_URL=\"$NOTEBOOKLM_URL\"" in script
    assert "VNC_LOCALHOST=\"false\"" in script
    assert "CHROME_REMOTE_DEBUGGING_PORT=\"$remote_debugging_port\"" in script
    assert "all_proxy=\"$PROXY_URL\"" in script
    assert "-m app.worker.main --worker-id \"$worker_id\" --display \"$display\"" in script
