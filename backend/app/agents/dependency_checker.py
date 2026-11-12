import logging
import re
import tomllib

from collections import defaultdict
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)


class DependencyCheckError(Exception):
    """Base exception for dependency checking errors."""


class DependencyFinding(BaseModel):
    file_path: str
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1)
    severity: str
    category: str = "DEPENDENCY"
    line_number: int | None = Field(default=None, ge=1)
    suggested_fix: str | None = None


class DependencyCheckResult(BaseModel):
    passed: bool
    summary: str
    manifests_checked: int = Field(ge=0)
    dependencies_checked: int = Field(ge=0)
    checks_performed: list[str]
    findings: list[DependencyFinding]


class DependencyChecker:
    """
    Deterministic Python dependency manifest checker.

    Supported manifests:
    - requirements.txt
    - requirements-*.txt
    - pyproject.toml

    Checks:
    - Dependency declaration syntax.
    - Duplicate dependencies.
    - Invalid version specifiers.
    - Invalid TOML structure.
    - Invalid dependency declaration types.
    - Empty dependency declarations.

    Does not install packages or access the network.
    """

    REQUIREMENTS_PATTERN = re.compile(
        r"^requirements(?:[-_][a-zA-Z0-9_.-]+)?\.txt$",
        re.IGNORECASE,
    )

    SUPPORTED_OPTIONS = (
        "-r ",
        "--requirement ",
        "-c ",
        "--constraint ",
        "-e ",
        "--editable ",
        "--index-url ",
        "--extra-index-url ",
        "--find-links ",
        "--trusted-host ",
        "--no-index",
        "--pre",
        "--prefer-binary",
        "--only-binary ",
        "--no-binary ",
        "--require-hashes",
    )

    def check_files(
        self,
        files: list[dict[str, str]],
    ) -> DependencyCheckResult:
        """
        Inspect dependency manifests supplied as file contents.

        Each file must contain:
        - file_path
        - content
        """

        if not isinstance(files, list):
            raise ValueError("Files must be a list.")

        findings: list[DependencyFinding] = []
        checks = [
            "Dependency manifest discovery",
            "Dependency declaration validation",
            "Duplicate dependency detection",
        ]

        manifests_checked = 0
        dependencies_checked = 0

        for item in files:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("file_path"), str)
                or not isinstance(item.get("content"), str)
            ):
                raise ValueError("Invalid project file input.")

            file_path = item["file_path"]
            content = item["content"]

            if not file_path.strip():
                raise ValueError("File path cannot be empty.")

            filename = Path(file_path).name.lower()

            if filename == "pyproject.toml":
                manifests_checked += 1

                file_findings, dependency_count = (
                    self._check_pyproject(
                        file_path,
                        content,
                    )
                )

            elif self.REQUIREMENTS_PATTERN.match(filename):
                manifests_checked += 1

                file_findings, dependency_count = (
                    self._check_requirements(
                        file_path,
                        content,
                    )
                )

            else:
                continue

            findings.extend(file_findings)
            dependencies_checked += dependency_count

        passed = not findings

        if manifests_checked == 0:
            summary = (
                "No supported Python dependency manifests "
                "were found."
            )
        elif passed:
            summary = (
                f"Checked {manifests_checked} dependency "
                f"manifest(s) and {dependencies_checked} "
                "dependency declaration(s). "
                "No manifest errors were detected."
            )
        else:
            summary = (
                f"Checked {manifests_checked} dependency "
                f"manifest(s) and {dependencies_checked} "
                f"dependency declaration(s). "
                f"Detected {len(findings)} issue(s)."
            )

        return DependencyCheckResult(
            passed=passed,
            summary=summary,
            manifests_checked=manifests_checked,
            dependencies_checked=dependencies_checked,
            checks_performed=checks,
            findings=findings,
        )

    def _check_requirements(
        self,
        file_path: str,
        content: str,
    ) -> tuple[list[DependencyFinding], int]:
        findings: list[DependencyFinding] = []
        dependencies: dict[str, list[int]] = defaultdict(list)

        dependency_count = 0

        for line_number, raw_line in enumerate(
            content.splitlines(),
            start=1,
        ):
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            if line.startswith(self.SUPPORTED_OPTIONS):
                continue

            line = self._remove_inline_comment(line)

            if not line:
                continue

            try:
                requirement = Requirement(line)

            except InvalidRequirement as exc:
                findings.append(
                    DependencyFinding(
                        file_path=file_path,
                        title="Invalid dependency declaration",
                        description=(
                            f"Line {line_number} contains an "
                            f"invalid requirement: {exc}"
                        ),
                        severity="HIGH",
                        line_number=line_number,
                        suggested_fix=(
                            "Correct the package name, version "
                            "specifier, extras, marker, or "
                            "direct URL syntax."
                        ),
                    )
                )
                continue

            dependency_count += 1

            normalized_name = self._normalize_name(
                requirement.name
            )

            dependencies[normalized_name].append(
                line_number
            )

        findings.extend(
            self._find_duplicates(
                file_path,
                dependencies,
            )
        )

        return findings, dependency_count

    def _check_pyproject(
        self,
        file_path: str,
        content: str,
    ) -> tuple[list[DependencyFinding], int]:
        findings: list[DependencyFinding] = []

        try:
            data = tomllib.loads(content)

        except tomllib.TOMLDecodeError as exc:
            return [
                DependencyFinding(
                    file_path=file_path,
                    title="Invalid TOML configuration",
                    description=(
                        f"Cannot parse pyproject.toml: {exc}"
                    ),
                    severity="HIGH",
                    category="CONFIGURATION",
                    line_number=getattr(
                        exc,
                        "lineno",
                        None,
                    ),
                    suggested_fix=(
                        "Correct the TOML syntax and validate "
                        "the manifest again."
                    ),
                )
            ], 0

        project = data.get("project", {})

        if not isinstance(project, dict):
            return [
                DependencyFinding(
                    file_path=file_path,
                    title="Invalid project configuration",
                    description=(
                        "The [project] section must be a "
                        "TOML table."
                    ),
                    severity="HIGH",
                    category="CONFIGURATION",
                    suggested_fix=(
                        "Define [project] as a valid TOML table."
                    ),
                )
            ], 0

        dependencies: dict[str, list[int]] = defaultdict(list)

        dependency_count = 0

        dependency_groups = [
            (
                "project.dependencies",
                project.get("dependencies", []),
            )
        ]

        optional_dependencies = project.get(
            "optional-dependencies",
            {},
        )

        if not isinstance(optional_dependencies, dict):
            findings.append(
                DependencyFinding(
                    file_path=file_path,
                    title="Invalid optional dependencies",
                    description=(
                        "The optional-dependencies field "
                        "must be a TOML table."
                    ),
                    severity="HIGH",
                    category="CONFIGURATION",
                    suggested_fix=(
                        "Use named optional dependency groups "
                        "containing arrays of requirement strings."
                    ),
                )
            )
        else:
            for group_name, group_dependencies in (
                optional_dependencies.items()
            ):
                dependency_groups.append(
                    (
                        f"project.optional-dependencies."
                        f"{group_name}",
                        group_dependencies,
                    )
                )

        for group_name, group in dependency_groups:
            if not isinstance(group, list):
                findings.append(
                    DependencyFinding(
                        file_path=file_path,
                        title="Invalid dependency group",
                        description=(
                            f"{group_name} must be an array "
                            "of dependency strings."
                        ),
                        severity="HIGH",
                        category="CONFIGURATION",
                        suggested_fix=(
                            "Provide dependency declarations "
                            "as an array of strings."
                        ),
                    )
                )
                continue

            for index, declaration in enumerate(
                group,
                start=1,
            ):
                if not isinstance(declaration, str):
                    findings.append(
                        DependencyFinding(
                            file_path=file_path,
                            title="Invalid dependency declaration",
                            description=(
                                f"{group_name} entry {index} "
                                "must be a string."
                            ),
                            severity="HIGH",
                            category="CONFIGURATION",
                            suggested_fix=(
                                "Replace the entry with a valid "
                                "PEP 508 dependency string."
                            ),
                        )
                    )
                    continue

                try:
                    requirement = Requirement(declaration)

                except InvalidRequirement as exc:
                    findings.append(
                        DependencyFinding(
                            file_path=file_path,
                            title="Invalid dependency declaration",
                            description=(
                                f"{group_name} entry {index} "
                                f"is invalid: {exc}"
                            ),
                            severity="HIGH",
                            category="DEPENDENCY",
                            suggested_fix=(
                                "Correct the dependency "
                                "declaration using PEP 508 syntax."
                            ),
                        )
                    )
                    continue

                dependency_count += 1

                normalized_name = self._normalize_name(
                    requirement.name
                )

                dependencies[normalized_name].append(
                    index
                )

        findings.extend(
            self._find_duplicates(
                file_path,
                dependencies,
            )
        )

        return findings, dependency_count

    @staticmethod
    def _normalize_name(name: str) -> str:
        """
        Normalize package names according to Python
        package naming conventions.
        """

        return re.sub(
            r"[-_.]+",
            "-",
            name,
        ).lower()

    @staticmethod
    def _remove_inline_comment(line: str) -> str:
        """
        Remove requirements.txt comments while preserving
        URL fragments and quoted content.
        """

        quote: str | None = None

        for index, character in enumerate(line):
            if character in {"'", '"'}:
                if quote is None:
                    quote = character
                elif quote == character:
                    quote = None

            elif (
                character == "#"
                and quote is None
                and (
                    index == 0
                    or line[index - 1].isspace()
                )
            ):
                return line[:index].strip()

        return line.strip()

    @staticmethod
    def _find_duplicates(
        file_path: str,
        dependencies: dict[str, list[int]],
    ) -> list[DependencyFinding]:
        findings: list[DependencyFinding] = []

        for package_name, locations in dependencies.items():
            if len(locations) <= 1:
                continue

            findings.append(
                DependencyFinding(
                    file_path=file_path,
                    title="Duplicate dependency declaration",
                    description=(
                        f"Package '{package_name}' is declared "
                        f"multiple times at entries "
                        f"{', '.join(map(str, locations))}."
                    ),
                    severity="MEDIUM",
                    category="DEPENDENCY",
                    line_number=locations[-1],
                    suggested_fix=(
                        "Review the dependency declarations "
                        "and consolidate duplicate entries "
                        "into one consistent requirement."
                    ),
                )
            )

        return findings