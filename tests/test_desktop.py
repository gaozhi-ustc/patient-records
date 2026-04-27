from pathlib import Path

from app.worker.desktop import DesktopManager


def test_vnc_command_uses_display_and_geometry() -> None:
    manager = DesktopManager(display=":21", vnc_port=5921, chrome_user_data_dir=Path("/profiles/w1"))

    assert manager.vnc_command() == ["vncserver", ":21", "-geometry", "1600x1000", "-depth", "24"]


def test_chrome_command_uses_profile_and_notebook_url() -> None:
    manager = DesktopManager(display=":21", vnc_port=5921, chrome_user_data_dir=Path("/profiles/w1"))

    command = manager.chrome_command("https://notebooklm.google.com")

    assert "--user-data-dir=/profiles/w1" in command
    assert "--no-first-run" in command
    assert "https://notebooklm.google.com" == command[-1]


def test_chrome_command_uses_proxy_when_provided() -> None:
    manager = DesktopManager(
        display=":21",
        vnc_port=5921,
        chrome_user_data_dir=Path("/profiles/w1"),
        proxy_url="http://localhost:7890",
    )

    command = manager.chrome_command("https://notebooklm.google.com")

    assert "--proxy-server=http://localhost:7890" in command
    assert "--disable-gpu" in command
    assert "--no-sandbox" in command
    assert "--disable-crash-reporter" in command
    assert "--disable-crashpad" in command
