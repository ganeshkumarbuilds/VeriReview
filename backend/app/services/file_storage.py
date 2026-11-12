import hashlib
import os
import shutil
import stat
import unicodedata
import zipfile

from pathlib import Path
from uuid import UUID, uuid4


BACKEND_ROOT = Path(__file__).resolve().parents[2]
STORAGE_ROOT = (BACKEND_ROOT / "storage" / "projects").resolve()

MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_ARCHIVE_SIZE = 100 * 1024 * 1024
MAX_EXTRACTED_SIZE = 500 * 1024 * 1024
MAX_ARCHIVE_FILES = 5000

CHUNK_SIZE = 1024 * 1024

WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

INVALID_WINDOWS_CHARACTERS = set('<>:"|?*')


def get_project_directory(project_id: UUID) -> Path:
    """Return the isolated storage directory for a project."""

    directory = (STORAGE_ROOT / str(project_id)).resolve()

    if not directory.is_relative_to(STORAGE_ROOT):
        raise ValueError("Invalid project storage path")

    return directory


def calculate_checksum(file_path: Path) -> str:
    """Calculate the SHA-256 checksum of a file."""

    sha256 = hashlib.sha256()

    with file_path.open("rb") as file:
        for chunk in iter(
            lambda: file.read(CHUNK_SIZE),
            b"",
        ):
            sha256.update(chunk)

    return sha256.hexdigest()


def validate_relative_path(file_path: str) -> str:
    """Validate a project-relative path for Windows compatibility."""

    if not isinstance(file_path, str) or not file_path:
        raise ValueError("File path is required")

    normalized = file_path.replace("\\", "/")

    if (
        normalized.startswith("/")
        or "\x00" in normalized
        or len(normalized) > 1000
    ):
        raise ValueError("Unsafe file path")

    parts = normalized.split("/")

    for part in parts:

        if part in ("", ".", ".."):
            raise ValueError("Unsafe file path")

        if part.endswith((" ", ".")):
            raise ValueError(
                "Windows filenames cannot end with spaces or dots"
            )

        if any(
            character in INVALID_WINDOWS_CHARACTERS
            or ord(character) < 32
            for character in part
        ):
            raise ValueError("Invalid filename characters")

        device_name = part.split(".")[0].upper()

        if device_name in WINDOWS_RESERVED_NAMES:
            raise ValueError("Reserved Windows filename")

    return normalized


def get_path_collision_key(file_path: str) -> str:
    """Generate a Windows-compatible path collision key."""

    return unicodedata.normalize(
        "NFC",
        file_path,
    ).casefold()


def ensure_inside_directory(
    path: Path,
    directory: Path,
) -> Path:
    """Resolve a path and ensure it stays inside its directory."""

    resolved_path = path.resolve()
    resolved_directory = directory.resolve()

    if not resolved_path.is_relative_to(resolved_directory):
        raise ValueError("Path escapes its storage directory")

    return resolved_path


def publish_file_without_overwrite(
    source: Path,
    destination: Path,
) -> None:
    """Atomically publish a file without replacing an existing file."""

    try:
        # Hard-link creation fails if the destination already exists.
        # Source and destination are on the same storage volume.
        os.link(source, destination)

    except FileExistsError:
        raise FileExistsError(
            f"File already exists: {destination.name}"
        )


def save_uploaded_file(
    project_id: UUID,
    file_path: str,
    content: bytes,
) -> tuple[Path, str]:
    """Save an uploaded file inside project storage."""

    if len(content) > MAX_FILE_SIZE:
        raise ValueError("File exceeds the 50 MB limit")

    relative_path = validate_relative_path(file_path)

    project_directory = get_project_directory(project_id)

    project_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = ensure_inside_directory(
        project_directory / Path(*relative_path.split("/")),
        project_directory,
    )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = ensure_inside_directory(
        destination,
        project_directory,
    )

    temporary_path = destination.with_name(
        f".{destination.name}.{uuid4().hex}.tmp"
    )

    try:
        with temporary_path.open("xb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())

        publish_file_without_overwrite(
            temporary_path,
            destination,
        )

    finally:
        temporary_path.unlink(missing_ok=True)

    return destination, calculate_checksum(destination)


def validate_zip_entries(entries):
    """Validate ZIP paths, collisions, and filesystem entry types."""

    validated_entries = []
    seen_paths = {}
    file_paths = set()
    directory_paths = set()

    for entry in entries:

        relative_path = validate_relative_path(
            entry.filename.rstrip("/")
        )

        collision_key = get_path_collision_key(relative_path)

        if collision_key in seen_paths:
            raise ValueError(
                "Duplicate or case-insensitive ZIP path collision"
            )

        seen_paths[collision_key] = relative_path

        parts = relative_path.split("/")

        for index in range(1, len(parts)):
            parent = "/".join(parts[:index])
            directory_paths.add(get_path_collision_key(parent))

        unix_mode = entry.external_attr >> 16
        entry_type = stat.S_IFMT(unix_mode)

        if entry_type not in (
            0,
            stat.S_IFREG,
            stat.S_IFDIR,
        ):
            raise ValueError(
                "Symbolic links and special ZIP entries are not allowed"
            )

        if entry.is_dir():

            if entry_type not in (0, stat.S_IFDIR):
                raise ValueError("Invalid ZIP directory entry")

            directory_paths.add(collision_key)
            continue

        if entry_type == stat.S_IFDIR:
            raise ValueError("Invalid ZIP file entry")

        if entry.flag_bits & 0x1:
            raise ValueError(
                "Encrypted ZIP entries are not supported"
            )

        if entry.file_size < 0:
            raise ValueError("Invalid ZIP entry size")

        file_paths.add(collision_key)

        validated_entries.append(
            (entry, relative_path)
        )

    # A file cannot also be a parent directory.
    if file_paths.intersection(directory_paths):
        raise ValueError(
            "ZIP archive contains conflicting file and directory paths"
        )

    return validated_entries


def extract_zip_archive(
    archive_path: Path,
    project_id: UUID,
) -> list[tuple[str, Path, str, int]]:
    """Safely extract a ZIP archive with rollback on failure."""

    if archive_path.stat().st_size > MAX_ARCHIVE_SIZE:
        raise ValueError("ZIP archive exceeds the 100 MB limit")

    if not zipfile.is_zipfile(archive_path):
        raise ValueError("Invalid ZIP archive")

    project_directory = get_project_directory(project_id)

    project_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    staging_directory = (
        project_directory / f".staging-{uuid4().hex}"
    )

    extracted_files = []
    published_paths = []

    total_declared_size = 0
    total_actual_size = 0

    try:
        with zipfile.ZipFile(archive_path, "r") as archive:

            entries = archive.infolist()

            if len(entries) > MAX_ARCHIVE_FILES:
                raise ValueError(
                    "ZIP archive contains too many entries"
                )

            validated_entries = validate_zip_entries(entries)

            for entry, _ in validated_entries:

                total_declared_size += entry.file_size

                if total_declared_size > MAX_EXTRACTED_SIZE:
                    raise ValueError(
                        "ZIP extraction exceeds the 500 MB limit"
                    )

            staging_directory.mkdir()

            # Extract all files into isolated staging storage.
            for entry, relative_path in validated_entries:

                staging_path = ensure_inside_directory(
                    staging_directory
                    / Path(*relative_path.split("/")),
                    staging_directory,
                )

                staging_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                actual_size = 0

                with archive.open(entry, "r") as source:
                    with staging_path.open("xb") as target:

                        while True:
                            chunk = source.read(CHUNK_SIZE)

                            if not chunk:
                                break

                            actual_size += len(chunk)
                            total_actual_size += len(chunk)

                            if actual_size > entry.file_size:
                                raise ValueError(
                                    "ZIP entry exceeds declared size"
                                )

                            if total_actual_size > MAX_EXTRACTED_SIZE:
                                raise ValueError(
                                    "ZIP extraction exceeds size limit"
                                )

                            target.write(chunk)

                if actual_size != entry.file_size:
                    raise ValueError(
                        "ZIP entry size mismatch"
                    )

            # Publish only after successful extraction.
            for _, relative_path in validated_entries:

                source_path = (
                    staging_directory
                    / Path(*relative_path.split("/"))
                )

                destination = ensure_inside_directory(
                    project_directory
                    / Path(*relative_path.split("/")),
                    project_directory,
                )

                destination.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                destination = ensure_inside_directory(
                    destination,
                    project_directory,
                )

                publish_file_without_overwrite(
                    source_path,
                    destination,
                )

                published_paths.append(destination)

                checksum = calculate_checksum(destination)
                file_size = destination.stat().st_size

                extracted_files.append(
                    (
                        relative_path,
                        destination,
                        checksum,
                        file_size,
                    )
                )

        return extracted_files

    except Exception:

        # Remove only files published by this extraction.
        for path in reversed(published_paths):
            path.unlink(missing_ok=True)

        raise

    finally:

        if staging_directory.exists():
            shutil.rmtree(
                staging_directory,
                ignore_errors=True,
            )


def delete_project_directory(project_id: UUID) -> None:
    """Delete all stored files belonging to a project."""

    directory = get_project_directory(project_id)

    if directory.exists():
        shutil.rmtree(directory)