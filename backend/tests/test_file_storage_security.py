import stat
import zipfile

import pytest

from app.services.file_storage import (
    validate_relative_path,
    get_path_collision_key,
    validate_zip_entries,
)


# 1. Valid project paths


@pytest.mark.parametrize(
    "path",
    [
        "main.py",
        "src/main.py",
        "frontend/src/App.tsx",
        "README.md",
    ],
)
def test_valid_paths(path):
    assert validate_relative_path(path) == path


# 2. Unsafe paths


@pytest.mark.parametrize(
    "path",
    [
        "../secret.txt",
        "src/../../secret.txt",
        "/absolute/path.txt",
        "C:/Windows/system.ini",
        "CON",
        "NUL.txt",
        "AUX",
        "src/file?.txt",
        "src/file.txt.",
        "src/file.txt ",
    ],
)
def test_unsafe_paths_are_rejected(path):
    with pytest.raises(ValueError):
        validate_relative_path(path)


# 3. Windows case-insensitive collisions


def test_case_insensitive_collision():
    first = get_path_collision_key("src/App.py")
    second = get_path_collision_key("src/app.py")

    assert first == second


# 4. ZIP duplicate paths


def test_duplicate_zip_paths_are_rejected():
    entries = [
        zipfile.ZipInfo("src/main.py"),
        zipfile.ZipInfo("src/main.py"),
    ]

    with pytest.raises(ValueError):
        validate_zip_entries(entries)


# 5. ZIP case-insensitive collisions


def test_case_collision_in_zip_is_rejected():
    entries = [
        zipfile.ZipInfo("src/App.py"),
        zipfile.ZipInfo("src/app.py"),
    ]

    with pytest.raises(ValueError):
        validate_zip_entries(entries)


# 6. ZIP file/directory conflicts


def test_file_directory_collision_is_rejected():
    entries = [
        zipfile.ZipInfo("src"),
        zipfile.ZipInfo("src/main.py"),
    ]

    with pytest.raises(ValueError):
        validate_zip_entries(entries)


# 7. Symbolic links


def test_symbolic_link_is_rejected():
    entry = zipfile.ZipInfo("malicious_link")

    entry.create_system = 3
    entry.external_attr = (
        stat.S_IFLNK | 0o777
    ) << 16

    with pytest.raises(ValueError):
        validate_zip_entries([entry])


# 8. Normal ZIP directory entries


def test_normal_zip_directory_is_allowed():
    entries = [
        zipfile.ZipInfo("src/"),
        zipfile.ZipInfo("src/main.py"),
    ]

    result = validate_zip_entries(entries)

    assert len(result) == 1
    assert result[0][1] == "src/main.py"