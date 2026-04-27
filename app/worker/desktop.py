import os
import subprocess
from pathlib import Path


class DesktopManager:
    def __init__(
        self,
        display: str,
        vnc_port: int,
        chrome_user_data_dir: Path,
        geometry: str = "1600x1000",
        depth: str = "24",
        chrome_binary: str = "google-chrome",
    ) -> None:
        self.display = display
        self.vnc_port = vnc_port
        self.chrome_user_data_dir = chrome_user_data_dir
        self.geometry = geometry
        self.depth = depth
        self.chrome_binary = chrome_binary

    def vnc_command(self) -> list[str]:
        return ["vncserver", self.display, "-geometry", self.geometry, "-depth", self.depth]

    def chrome_command(self, url: str) -> list[str]:
        return [
            self.chrome_binary,
            f"--user-data-dir={self.chrome_user_data_dir}",
            "--no-first-run",
            "--disable-default-apps",
            "--start-maximized",
            url,
        ]

    def ensure_vnc(self) -> None:
        subprocess.run(self.vnc_command(), check=True)

    def launch_chrome(self, url: str) -> subprocess.Popen:
        self.chrome_user_data_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["DISPLAY"] = self.display
        return subprocess.Popen(self.chrome_command(url), env=env)
