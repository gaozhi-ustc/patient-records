from pathlib import Path
import subprocess

from app.worker.desktop import DesktopManager


def test_vnc_command_uses_display_and_geometry() -> None:
    manager = DesktopManager(display=":21", vnc_port=5921, chrome_user_data_dir=Path("/profiles/w1"))

    assert manager.vnc_command() == [
        "vncserver",
        ":21",
        "-localhost",
        "yes",
        "-geometry",
        "1920x1200",
        "-depth",
        "24",
    ]


def test_vnc_command_can_disable_localhost_binding() -> None:
    manager = DesktopManager(
        display=":20",
        vnc_port=5920,
        chrome_user_data_dir=Path("/profiles/w20"),
        vnc_localhost=False,
    )

    assert manager.vnc_command() == [
        "vncserver",
        ":20",
        "-localhost",
        "no",
        "-geometry",
        "1920x1200",
        "-depth",
        "24",
    ]


def test_chrome_command_uses_profile_and_notebook_url() -> None:
    manager = DesktopManager(display=":21", vnc_port=5921, chrome_user_data_dir=Path("/profiles/w1"))

    command = manager.chrome_command("https://notebooklm.google.com")

    assert "--user-data-dir=/profiles/w1" in command
    assert "--no-first-run" in command
    assert "--force-renderer-accessibility" in command
    assert "--start-fullscreen" in command
    assert "--window-position=0,0" in command
    assert "--window-size=1920,1200" in command
    assert "https://notebooklm.google.com" == command[-1]


def test_chrome_command_uses_proxy_when_provided() -> None:
    manager = DesktopManager(
        display=":21",
        vnc_port=5921,
        chrome_user_data_dir=Path("/profiles/w1"),
        proxy_url="http://localhost:7890",
        remote_debugging_port=9241,
    )

    command = manager.chrome_command("https://notebooklm.google.com")

    assert "--proxy-server=http://localhost:7890" in command
    assert "--remote-debugging-address=127.0.0.1" in command
    assert "--remote-debugging-port=9241" in command
    assert "--disable-gpu" in command
    assert "--no-sandbox" in command
    assert "--disable-crash-reporter" in command
    assert "--disable-crashpad" in command


def test_launch_chrome_configures_download_directory(tmp_path: Path, monkeypatch) -> None:
    profile = tmp_path / "profile"
    downloads = tmp_path / "downloads"
    launched = {}
    manager = DesktopManager(
        display=":21",
        vnc_port=5921,
        chrome_user_data_dir=profile,
        downloads_dir=downloads,
    )

    def fake_popen(command, env):
        launched["command"] = command
        launched["env"] = env
        return "process"

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    process = manager.launch_chrome("https://notebooklm.google.com")

    assert process == "process"
    preferences = (profile / "Default" / "Preferences").read_text(encoding="utf-8")
    assert str(downloads) in preferences
    assert downloads.is_dir()
