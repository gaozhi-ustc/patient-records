import hashlib
import zipfile
from pathlib import Path

import pytest

from app.storage import JobPaths, StorageService, UnsafeZipError


def write_zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def test_job_paths_are_created_under_data_root(tmp_path: Path) -> None:
    service = StorageService(data_root=tmp_path)

    paths = service.prepare_job_paths("job-1", "patient.zip")

    assert paths.upload_dir == tmp_path / "job-1" / "upload"
    assert paths.input_dir == tmp_path / "job-1" / "input"
    assert paths.result_dir == tmp_path / "job-1" / "result"
    assert paths.zip_path == tmp_path / "job-1" / "upload" / "patient.zip"
    assert paths.upload_dir.is_dir()
    assert paths.input_dir.is_dir()
    assert paths.result_dir.is_dir()


def test_prepare_job_paths_rejects_job_ids_outside_data_root(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    relative_outside = tmp_path / "outside"
    absolute_outside = tmp_path / "absolute-outside"
    service = StorageService(data_root=data_root)

    for job_id in ("../outside", str(absolute_outside)):
        with pytest.raises(UnsafeZipError, match="unsafe job id"):
            service.prepare_job_paths(job_id, "patient.zip")

    assert not relative_outside.exists()
    assert not absolute_outside.exists()


def test_extract_zip_rejects_parent_directory_traversal(tmp_path: Path) -> None:
    zip_path = tmp_path / "bad.zip"
    write_zip(zip_path, {"../escape.txt": b"bad"})
    service = StorageService(data_root=tmp_path)
    paths = JobPaths(
        job_dir=tmp_path / "job-1",
        upload_dir=tmp_path / "job-1" / "upload",
        input_dir=tmp_path / "job-1" / "input",
        result_dir=tmp_path / "job-1" / "result",
        zip_path=zip_path,
    )
    paths.input_dir.mkdir(parents=True)

    with pytest.raises(UnsafeZipError, match="unsafe zip member"):
        service.extract_zip(paths)


def test_extract_zip_returns_supported_files_only(tmp_path: Path) -> None:
    zip_path = tmp_path / "patient.zip"
    write_zip(
        zip_path,
        {
            "a.pdf": b"pdf",
            "nested/b.txt": b"text",
            "skip.exe": b"binary",
        },
    )
    service = StorageService(data_root=tmp_path, supported_extensions=(".pdf", ".txt"))
    paths = JobPaths(
        job_dir=tmp_path / "job-1",
        upload_dir=tmp_path / "job-1" / "upload",
        input_dir=tmp_path / "job-1" / "input",
        result_dir=tmp_path / "job-1" / "result",
        zip_path=zip_path,
    )
    paths.input_dir.mkdir(parents=True)

    extracted = service.extract_zip(paths)

    assert [item.relative_to(paths.input_dir).as_posix() for item in extracted] == [
        "a.pdf",
        "nested/b.txt",
    ]
    assert not (paths.input_dir / "skip.exe").exists()


def test_sha256_file(tmp_path: Path) -> None:
    file_path = tmp_path / "result.md"
    file_path.write_bytes(b"abc")

    assert StorageService.sha256_file(file_path) == hashlib.sha256(b"abc").hexdigest()
