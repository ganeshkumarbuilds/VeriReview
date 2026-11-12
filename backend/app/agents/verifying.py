import ast
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import tomllib

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.agents.dependency_checker import DependencyChecker
from app.services.llm_client import LLMClientError, llm_client


logger = logging.getLogger(__name__)


class VerifyingAgentError(Exception):
    """Base exception for Verifying Agent errors."""


class VerificationOutputError(VerifyingAgentError):
    """Raised when verification output is invalid."""


class VerificationFinding(BaseModel):
    file_path: str
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1)
    severity: str
    category: str
    line_number: int | None = Field(default=None, ge=1)
    suggested_fix: str | None = None


class VerificationResult(BaseModel):
    passed: bool
    summary: str
    findings: list[VerificationFinding]
    files_checked: int = Field(ge=0)
    checks_performed: list[str]


class VerifyingAgent:
    """Performs deterministic checks and LLM-based source inspection."""

    SYSTEM_PROMPT = """
You are the Verifying Agent of VeriReview.

Inspect actual project source code and identify genuine defects.

Analyze:
1. Runtime and logical bugs.
2. Security vulnerabilities.
3. Incorrect API usage.
4. Missing error handling.
5. Data validation problems.
6. Dependency and configuration problems.
7. Incomplete or inconsistent implementations.
8. Potential performance problems.

Rules:
- Report only issues supported by supplied files.
- Never invent findings.
- Do not report stylistic preferences as bugs.
- Do not claim tests were executed unless test results
  were explicitly provided.
- Distinguish confirmed defects from potential risks.
- Include exact file paths and line numbers when identifiable.
- Explain the impact of each finding.
- Provide a concrete suggested fix.
- Do not modify files.
- Do not claim that an issue has been fixed.
- Do not duplicate deterministic findings.
- Do not contradict supplied test results.

Return ONLY valid JSON:

{
    "passed": false,
    "summary": "Verification summary",
    "files_checked": 1,
    "checks_performed": ["Source code inspection"],
    "findings": [
        {
            "file_path": "src/main.py",
            "title": "Description of the defect",
            "description": "Explanation and impact",
            "severity": "HIGH",
            "category": "LOGIC",
            "line_number": 10,
            "suggested_fix": "Suggested correction"
        }
    ]
}

Severity: CRITICAL, HIGH, MEDIUM, LOW, INFO.

When no defects exist, return an empty findings array
and passed=true.
"""

    def __init__(self) -> None:
        self._node_executable = shutil.which("node")
        self.dependency_checker = DependencyChecker()

    async def verify_files(
        self,
        files: list[dict[str, str]],
        technology_stack: str | None = None,
        test_results: dict[str, Any] | None = None,
    ) -> VerificationResult:

        self._validate_files(files)

        deterministic_findings, deterministic_checks = (
            await asyncio.to_thread(
                self._run_deterministic_checks,
                files,
            )
        )

        stack_information = (
            technology_stack.strip()
            if technology_stack and technology_stack.strip()
            else "Not specified."
        )

        user_prompt = f"""
Inspect the following actual project files.

TECHNOLOGY STACK:
{stack_information}

FILES:
{json.dumps(files, ensure_ascii=False)}

AVAILABLE TEST RESULTS:
{json.dumps(test_results, ensure_ascii=False)}

DETERMINISTIC CHECK RESULTS:
{json.dumps(
    [finding.model_dump() for finding in deterministic_findings],
    ensure_ascii=False,
)}

CHECKS ALREADY PERFORMED:
{json.dumps(deterministic_checks, ensure_ascii=False)}

Report additional genuine defects supported by the files
and supplied test results.

Do not duplicate deterministic findings.

files_checked must equal {len(files)}.

Return the required JSON structure.
"""

        try:
            response = await llm_client.chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": self.SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": user_prompt,
                    },
                ],
                temperature=0.1,
                max_tokens=6000,
            )

            result_data = self._parse_response(response)
            llm_result = VerificationResult.model_validate(result_data)

            if llm_result.files_checked != len(files):
                raise VerificationOutputError(
                    "Verifier returned an incorrect file count."
                )

            if llm_result.passed and llm_result.findings:
                raise VerificationOutputError(
                    "Verification cannot pass while findings exist."
                )

            if not llm_result.passed and not llm_result.findings:
                raise VerificationOutputError(
                    "Failed verification must contain findings."
                )

            combined_findings = self._merge_findings(
                deterministic_findings,
                llm_result.findings,
            )

            checks = list(
                dict.fromkeys(
                    deterministic_checks
                    + llm_result.checks_performed
                )
            )

            return VerificationResult(
                passed=not combined_findings,
                summary=self._build_summary(
                    deterministic_findings,
                    llm_result,
                    len(combined_findings),
                ),
                findings=combined_findings,
                files_checked=len(files),
                checks_performed=checks,
            )

        except ValidationError as exc:
            raise VerificationOutputError(
                "Verification output does not match the required schema."
            ) from exc

        except LLMClientError as exc:
            logger.exception("Verifying Agent LLM request failed.")

            if deterministic_findings:
                return VerificationResult(
                    passed=False,
                    summary=(
                        "Deterministic checks detected defects. "
                        "LLM inspection could not be completed."
                    ),
                    findings=deterministic_findings,
                    files_checked=len(files),
                    checks_performed=deterministic_checks,
                )

            raise VerifyingAgentError(
                "Verifying Agent could not complete verification."
            ) from exc

        except VerificationOutputError:
            raise

        except Exception as exc:
            logger.exception("Unexpected Verifying Agent failure.")
            raise VerifyingAgentError(
                "An unexpected Verifying Agent error occurred."
            ) from exc

    @staticmethod
    def _validate_files(files: list[dict[str, str]]) -> None:
        if not isinstance(files, list) or not files:
            raise ValueError("At least one project file is required.")

        for item in files:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("file_path"), str)
                or not isinstance(item.get("content"), str)
            ):
                raise ValueError("Invalid project file input.")

            if not item["file_path"].strip():
                raise ValueError("Project file path cannot be empty.")

    def _run_deterministic_checks(
        self,
        files: list[dict[str, str]],
    ) -> tuple[list[VerificationFinding], list[str]]:
        findings: list[VerificationFinding] = []
        checks: list[str] = ["File input validation"]

        for item in files:
            file_path = item["file_path"]
            content = item["content"]
            suffix = Path(file_path).suffix.lower()

            if suffix == ".py":
                checks.append("Python syntax validation")
                finding = self._check_python_syntax(file_path, content)
                if finding:
                    findings.append(finding)

            elif suffix == ".json":
                checks.append("JSON validation")
                finding = self._check_json(file_path, content)
                if finding:
                    findings.append(finding)

            elif suffix == ".toml":
                # Record TOML validation for every TOML file.
                # DependencyChecker performs pyproject.toml parsing so
                # it is not parsed a second time here.
                checks.append("TOML validation")
                if Path(file_path).name.lower() != "pyproject.toml":
                    finding = self._check_toml(file_path, content)
                    if finding:
                        findings.append(finding)

            elif suffix in {".js", ".mjs", ".cjs"}:
                if self._node_executable:
                    checks.append("JavaScript syntax validation")
                    finding = self._check_javascript(file_path, content)
                    if finding:
                        findings.append(finding)
                else:
                    checks.append(
                        "JavaScript syntax validation skipped: "
                        "Node.js unavailable"
                    )

        dependency_result = self.dependency_checker.check_files(files)
        checks.extend(dependency_result.checks_performed)

        for finding in dependency_result.findings:
            findings.append(
                VerificationFinding(
                    file_path=finding.file_path,
                    title=finding.title,
                    description=finding.description,
                    severity=finding.severity,
                    category=finding.category,
                    line_number=finding.line_number,
                    suggested_fix=finding.suggested_fix,
                )
            )

        checks.append("LLM-based source code inspection")

        return (
            self._merge_findings(findings, []),
            list(dict.fromkeys(checks)),
        )

    @staticmethod
    def _check_python_syntax(
        file_path: str,
        content: str,
    ) -> VerificationFinding | None:
        try:
            ast.parse(content, filename=file_path)
            return None

        except SyntaxError as exc:
            return VerificationFinding(
                file_path=file_path,
                title="Python syntax error",
                description=(
                    f"Python could not parse this file: {exc.msg}. "
                    "The file cannot be imported or executed until corrected."
                ),
                severity="HIGH",
                category="SYNTAX",
                line_number=exc.lineno,
                suggested_fix="Correct the syntax near the reported line.",
            )

        except (ValueError, TypeError) as exc:
            return VerificationFinding(
                file_path=file_path,
                title="Python source parsing failed",
                description=str(exc),
                severity="HIGH",
                category="SYNTAX",
                suggested_fix="Check the Python source encoding and content.",
            )

    @staticmethod
    def _check_json(
        file_path: str,
        content: str,
    ) -> VerificationFinding | None:
        try:
            json.loads(content)
            return None

        except json.JSONDecodeError as exc:
            return VerificationFinding(
                file_path=file_path,
                title="Invalid JSON",
                description=(
                    f"JSON parsing failed: {exc.msg}. "
                    "Applications loading this file may fail."
                ),
                severity="HIGH",
                category="CONFIGURATION",
                line_number=exc.lineno,
                suggested_fix="Correct the JSON syntax.",
            )

    @staticmethod
    def _check_toml(
        file_path: str,
        content: str,
    ) -> VerificationFinding | None:
        try:
            tomllib.loads(content)
            return None

        except tomllib.TOMLDecodeError as exc:
            return VerificationFinding(
                file_path=file_path,
                title="Invalid TOML configuration",
                description=f"TOML parsing failed: {exc}.",
                severity="HIGH",
                category="CONFIGURATION",
                line_number=getattr(exc, "lineno", None),
                suggested_fix="Correct the TOML syntax.",
            )

    def _check_javascript(
        self,
        file_path: str,
        content: str,
    ) -> VerificationFinding | None:
        if not self._node_executable:
            return None

        suffix = Path(file_path).suffix.lower()

        try:
            with tempfile.TemporaryDirectory(
                prefix="verireview-check-"
            ) as temporary_directory:

                temporary_file = (
                    Path(temporary_directory)
                    / f"verification{suffix}"
                )

                temporary_file.write_text(content, encoding="utf-8")

                completed = subprocess.run(
                    [
                        self._node_executable,
                        "--check",
                        str(temporary_file),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                    shell=False,
                    env={
                        **os.environ,
                        "NODE_OPTIONS": "",
                    },
                )

                if completed.returncode == 0:
                    return None

                error_output = (
                    completed.stderr.strip()
                    or completed.stdout.strip()
                    or "Unknown JavaScript syntax error."
                )

                return VerificationFinding(
                    file_path=file_path,
                    title="JavaScript syntax error",
                    description=(
                        "Node.js could not parse this file. "
                        f"Parser output: {error_output[:2000]}"
                    ),
                    severity="HIGH",
                    category="SYNTAX",
                    line_number=self._extract_node_line(error_output),
                    suggested_fix="Correct the JavaScript syntax.",
                )

        except subprocess.TimeoutExpired:
            return VerificationFinding(
                file_path=file_path,
                title="JavaScript syntax check timed out",
                description="Node.js did not finish within 15 seconds.",
                severity="MEDIUM",
                category="CONFIGURATION",
                suggested_fix="Inspect the file and retry.",
            )

        except OSError as exc:
            logger.warning(
                "JavaScript validation failed for %s: %s",
                file_path,
                exc,
            )

            return VerificationFinding(
                file_path=file_path,
                title="JavaScript syntax check unavailable",
                description=str(exc),
                severity="LOW",
                category="CONFIGURATION",
                suggested_fix=(
                    "Ensure Node.js is installed and accessible."
                ),
            )

    @staticmethod
    def _extract_node_line(error_output: str) -> int | None:
        patterns = [
            r":(\d+)\s*$",
            r"\((\d+):\d+\)",
            r"line\s+(\d+)",
        ]

        for pattern in patterns:
            matches = re.findall(
                pattern,
                error_output,
                flags=re.IGNORECASE | re.MULTILINE,
            )

            if matches:
                try:
                    return int(matches[-1])
                except ValueError:
                    continue

        return None

    @staticmethod
    def _merge_findings(
        deterministic_findings: list[VerificationFinding],
        llm_findings: list[VerificationFinding],
    ) -> list[VerificationFinding]:

        merged: list[VerificationFinding] = []
        seen: set[tuple[str, str, int | None]] = set()

        for finding in deterministic_findings + llm_findings:
            identity = (
                finding.file_path.casefold(),
                finding.title.strip().casefold(),
                finding.line_number,
            )

            if identity in seen:
                continue

            seen.add(identity)
            merged.append(finding)

        return merged

    @staticmethod
    def _build_summary(
        deterministic_findings: list[VerificationFinding],
        llm_result: VerificationResult,
        total_findings: int,
    ) -> str:

        if total_findings == 0:
            return (
                "Deterministic checks and LLM-based source inspection "
                "completed without reported findings. "
                "This does not guarantee the absence of defects."
            )

        return (
            f"Verification identified {total_findings} unique finding(s). "
            f"Deterministic checks reported "
            f"{len(deterministic_findings)}; LLM inspection reported "
            f"{len(llm_result.findings)} before deduplication."
        )

    @staticmethod
    def _parse_response(response: str) -> dict[str, Any]:
        if not isinstance(response, str) or not response.strip():
            raise VerificationOutputError(
                "Verifying Agent returned an empty response."
            )

        content = response.strip()

        if content.startswith("```"):
            lines = content.splitlines()

            if lines[-1].strip() == "```":
                lines = lines[1:-1]

            content = "\n".join(lines).strip()

            if content.lower().startswith("json"):
                content = content[4:].strip()

        try:
            parsed = json.loads(content)

        except json.JSONDecodeError as exc:
            raise VerificationOutputError(
                "Verifying Agent returned invalid JSON."
            ) from exc

        if not isinstance(parsed, dict):
            raise VerificationOutputError(
                "Verification output must be a JSON object."
            )

        return parsed


verifying_agent = VerifyingAgent()