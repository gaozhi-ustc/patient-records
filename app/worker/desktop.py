import json
import os
import subprocess
from pathlib import Path


class DesktopManager:
    def __init__(
        self,
        display: str,
        vnc_port: int,
        chrome_user_data_dir: Path,
        geometry: str = "1920x1200",
        depth: str = "24",
        chrome_binary: str = "google-chrome",
        proxy_url: str | None = None,
        downloads_dir: Path | None = None,
        remote_debugging_port: int | None = None,
        vnc_localhost: bool = True,
    ) -> None:
        self.display = display
        self.vnc_port = vnc_port
        self.chrome_user_data_dir = chrome_user_data_dir
        self.geometry = geometry
        self.depth = depth
        self.chrome_binary = chrome_binary
        self.proxy_url = proxy_url
        self.downloads_dir = downloads_dir
        self.remote_debugging_port = remote_debugging_port
        self.vnc_localhost = vnc_localhost

    def vnc_command(self) -> list[str]:
        localhost_value = "yes" if self.vnc_localhost else "no"
        return [
            "vncserver",
            self.display,
            "-localhost",
            localhost_value,
            "-geometry",
            self.geometry,
            "-depth",
            self.depth,
        ]

    def chrome_command(self, url: str) -> list[str]:
        command = [
            self.chrome_binary,
            f"--user-data-dir={self.chrome_user_data_dir}",
            "--no-first-run",
            "--disable-default-apps",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-crash-reporter",
            "--disable-crashpad",
            "--start-maximized",
            "--start-fullscreen",
            "--window-position=0,0",
            "--window-size=1920,1200",
            "--force-renderer-accessibility",
        ]
        if self.proxy_url:
            command.append(f"--proxy-server={self.proxy_url}")
        if self.remote_debugging_port is not None:
            command.extend(
                [
                    "--remote-debugging-address=127.0.0.1",
                    f"--remote-debugging-port={self.remote_debugging_port}",
                ]
            )
        command.append(url)
        return command

    def ensure_vnc(self) -> None:
        if self._display_is_active():
            return
        subprocess.run(self.vnc_command(), check=True)

    def launch_chrome(self, url: str) -> subprocess.Popen:
        self.chrome_user_data_dir.mkdir(parents=True, exist_ok=True)
        self._configure_download_directory()
        env = os.environ.copy()
        env["DISPLAY"] = self.display
        if "XAUTHORITY" not in env and Path.home().joinpath(".Xauthority").exists():
            env["XAUTHORITY"] = str(Path.home() / ".Xauthority")
        return subprocess.Popen(self.chrome_command(url), env=env)

    def _configure_download_directory(self) -> None:
        if self.downloads_dir is None:
            return
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        preferences_path = self.chrome_user_data_dir / "Default" / "Preferences"
        preferences_path.parent.mkdir(parents=True, exist_ok=True)
        preferences = {}
        if preferences_path.exists():
            try:
                preferences = json.loads(preferences_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                preferences = {}
        preferences.setdefault("download", {}).update(
            {
                "default_directory": str(self.downloads_dir),
                "directory_upgrade": True,
                "prompt_for_download": False,
            }
        )
        preferences.setdefault("profile", {}).setdefault("default_content_setting_values", {})[
            "automatic_downloads"
        ] = 1
        preferences_path.write_text(json.dumps(preferences, ensure_ascii=False), encoding="utf-8")

    def _display_is_active(self) -> bool:
        return subprocess.run(
            ["xdpyinfo"],
            env={**os.environ, "DISPLAY": self.display},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0
