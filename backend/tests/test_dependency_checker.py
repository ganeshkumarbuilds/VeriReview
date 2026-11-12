import pytest

from app.agents.dependency_checker import (
    DependencyChecker,
    DependencyFinding,
)


@pytest.fixture
def checker():
    return DependencyChecker()


# ---------------------------------------------------------
# requirements.txt
# ---------------------------------------------------------

def test_valid_requirements(checker):
    result = checker.check_files([
        {
            "file_path": "requirements.txt",
            "content": (
                "fastapi>=0.100\n"
                "uvicorn[standard]>=0.20\n"
                "sqlalchemy>=2.0\n"
            ),
        }
    ])

    assert result.passed is True
    assert result.manifests_checked == 1
    assert result.dependencies_checked == 3
    assert result.findings == []


def test_invalid_requirement_declaration(checker):
    result = checker.check_files([
        {
            "file_path": "requirements.txt",
            "content": "fastapi>>=0.100\n",
        }
    ])

    assert result.passed is False
    assert len(result.findings) == 1
    assert result.findings[0].severity == "HIGH"


def test_duplicate_requirements(checker):
    result = checker.check_files([
        {
            "file_path": "requirements.txt",
            "content": (
                "fastapi>=0.100\n"
                "FastAPI>=0.110\n"
            ),
        }
    ])

    assert result.passed is False
    assert len(result.findings) == 1
    assert "Duplicate" in result.findings[0].title


def test_requirements_comments_and_blank_lines(checker):
    result = checker.check_files([
        {
            "file_path": "requirements.txt",
            "content": (
                "# Backend dependencies\n"
                "\n"
                "fastapi>=0.100  # API framework\n"
                "uvicorn>=0.20\n"
            ),
        }
    ])

    assert result.passed is True
    assert result.dependencies_checked == 2


def test_requirements_include_option(checker):
    result = checker.check_files([
        {
            "file_path": "requirements.txt",
            "content": (
                "-r requirements-dev.txt\n"
                "fastapi>=0.100\n"
            ),
        }
    ])

    assert result.passed is True
    assert result.dependencies_checked == 1


# ---------------------------------------------------------
# pyproject.toml
# ---------------------------------------------------------

def test_valid_pyproject(checker):
    result = checker.check_files([
        {
            "file_path": "pyproject.toml",
            "content": """
[project]
name = "verireview"
version = "1.0.0"
dependencies = [
    "fastapi>=0.100",
    "sqlalchemy>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]
""",
        }
    ])

    assert result.passed is True
    assert result.manifests_checked == 1
    assert result.dependencies_checked == 3


def test_invalid_toml(checker):
    result = checker.check_files([
        {
            "file_path": "pyproject.toml",
            "content": """
[project
name = "verireview"
""",
        }
    ])

    assert result.passed is False
    assert len(result.findings) == 1
    assert result.findings[0].category == "CONFIGURATION"


def test_invalid_project_dependency(checker):
    result = checker.check_files([
        {
            "file_path": "pyproject.toml",
            "content": """
[project]
name = "verireview"
dependencies = [
    "fastapi>>=0.100",
]
""",
        }
    ])

    assert result.passed is False
    assert len(result.findings) == 1


def test_invalid_optional_dependency_group(checker):
    result = checker.check_files([
        {
            "file_path": "pyproject.toml",
            "content": """
[project]
name = "verireview"

[project.optional-dependencies]
dev = "pytest>=8.0"
""",
        }
    ])

    assert result.passed is False
    assert any(
        finding.title == "Invalid dependency group"
        for finding in result.findings
    )


def test_duplicate_pyproject_dependencies(checker):
    result = checker.check_files([
        {
            "file_path": "pyproject.toml",
            "content": """
[project]
name = "verireview"
dependencies = [
    "fastapi>=0.100",
    "FastAPI>=0.110",
]
""",
        }
    ])

    assert result.passed is False
    assert any(
        finding.title == "Duplicate dependency declaration"
        for finding in result.findings
    )


# ---------------------------------------------------------
# Manifest discovery
# ---------------------------------------------------------

def test_unsupported_files_are_ignored(checker):
    result = checker.check_files([
        {
            "file_path": "main.py",
            "content": "print('Hello')",
        }
    ])

    assert result.passed is True
    assert result.manifests_checked == 0
    assert result.dependencies_checked == 0


def test_requirements_dev_file_is_discovered(checker):
    result = checker.check_files([
        {
            "file_path": "requirements-dev.txt",
            "content": "pytest>=8.0\n",
        }
    ])

    assert result.passed is True
    assert result.manifests_checked == 1
    assert result.dependencies_checked == 1


# ---------------------------------------------------------
# Input validation
# ---------------------------------------------------------

def test_reject_invalid_input_type(checker):
    with pytest.raises(ValueError):
        checker.check_files("invalid")


def test_reject_invalid_file_entry(checker):
    with pytest.raises(ValueError):
        checker.check_files([
            {
                "file_path": "requirements.txt",
            }
        ])


def test_reject_empty_file_path(checker):
    with pytest.raises(ValueError):
        checker.check_files([
            {
                "file_path": "",
                "content": "fastapi>=0.100",
            }
        ])


# ---------------------------------------------------------
# Normalization
# ---------------------------------------------------------

def test_package_name_normalization(checker):
    assert checker._normalize_name("My_Package") == "my-package"
    assert checker._normalize_name("my.package") == "my-package"
    assert checker._normalize_name("MY-PACKAGE") == "my-package"


def test_result_schema(checker):
    result = checker.check_files([
        {
            "file_path": "requirements.txt",
            "content": "fastapi>=0.100\n",
        }
    ])

    assert result.passed is True
    assert result.manifests_checked == 1
    assert isinstance(result.checks_performed, list)
    assert isinstance(result.findings, list)