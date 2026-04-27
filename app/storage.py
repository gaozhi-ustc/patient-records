import hashlib
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class UnsafeZipError(ValueError):
    pass


@dataclass(frozen=True)
class JobPaths:
    job_dir: Path
    upload_dir: Path
    input_dir: Path
    result_dir: Path
    zip_path: Path


class StorageService:
    def __init__(
        self,
        data_root: Path,
        supported_extensions: tuple[str, ...] = (
            ".pdf",
            ".docx",
            ".doc",
            ".txt",
            ".md",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".gif",
            ".bmp",
            ".tif",
            ".tiff",
            ".mp3",
            ".wav",
        ),
    ) -> None:
        self.data_root = data_root
        self.supported_extensions = tuple(ext.lower() for ext in supported_extensions)

    def prepare_job_paths(self, job_id: str, original_filename: str) -> JobPaths:
        safe_filename = Path(original_filename).name
        job_dir = self.data_root / job_id
        upload_dir = job_dir / "upload"
        input_dir = job_dir / "input"
        result_dir = job_dir / "result"
        for directory in (upload_dir, input_dir, result_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return JobPaths(
            job_dir=job_dir,
            upload_dir=upload_dir,
            input_dir=input_dir,
            result_dir=result_dir,
            zip_path=upload_dir / safe_filename,
        )

    def save_upload(self, source_file, paths: JobPaths) -> None:
        with paths.zip_path.open("wb") as output:
            shutil.copyfileobj(source_file, output)

    def extract_zip(self, paths: JobPaths) -> list[Path]:
        extracted: list[Path] = []
        with zipfile.ZipFile(paths.zip_path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                target = self._safe_target(paths.input_dir, member.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if target.suffix.lower() in self.supported_extensions:
                    extracted.append(target)
        return sorted(extracted)

    def _safe_target(self, input_dir: Path, member_name: str) -> Path:
        normalized = PurePosixPath(member_name.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise UnsafeZipError(f"unsafe zip member: {member_name}")
        target = (input_dir / Path(*normalized.parts)).resolve()
        input_root = input_dir.resolve()
        if input_root != target and input_root not in target.parents:
            raise UnsafeZipError(f"unsafe zip member: {member_name}")
        return target

    @staticmethod
    def sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as input_file:
            for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
