import asyncio
import json

import pytest

from app.agents.verifying import (
    VerifyingAgent,
    VerifyingAgentError,
    VerificationFinding,
    VerificationOutputError,
    VerificationResult,
)


def run_async(coroutine):
    return asyncio.run(
        coroutine,
        loop_factory=asyncio.SelectorEventLoop,
    )


def valid_result(passed=True, findings=None):
    return json.dumps({
        "passed": passed,
        "summary": "Verification completed.",
        "files_checked": 1,
        "checks_performed": ["Source code inspection"],
        "findings": findings or [],
    })


# ---------------------------------------------------------
# Response parsing
# ---------------------------------------------------------

def test_parse_valid_json():
    result = VerifyingAgent._parse_response(valid_result())
    assert result["passed"] is True


def test_parse_markdown_json():
    response = f"```json\n{valid_result()}\n```"
    result = VerifyingAgent._parse_response(response)
    assert result["passed"] is True


def test_reject_invalid_json():
    with pytest.raises(VerificationOutputError):
        VerifyingAgent._parse_response("invalid")


def test_reject_non_object_json():
    with pytest.raises(VerificationOutputError):
        VerifyingAgent._parse_response('["invalid"]')


def test_reject_empty_response():
    with pytest.raises(VerificationOutputError):
        VerifyingAgent._parse_response("")


# ---------------------------------------------------------
# Verification schema
# ---------------------------------------------------------

def test_verification_result_schema():
    result = VerificationResult.model_validate(
        json.loads(valid_result())
    )

    assert result.passed is True
    assert result.files_checked == 1
    assert result.findings == []


def test_reject_empty_file_list():
    agent = VerifyingAgent()

    with pytest.raises(ValueError):
        run_async(agent.verify_files([]))


# ---------------------------------------------------------
# LLM verification
# ---------------------------------------------------------

def test_successful_verification(monkeypatch):
    agent = VerifyingAgent()

    async def mock_completion(**kwargs):
        return valid_result()

    monkeypatch.setattr(
        "app.agents.verifying.llm_client.chat_completion",
        mock_completion,
    )

    result = run_async(
        agent.verify_files([
            {
                "file_path": "main.py",
                "content": "print('Hello')",
            }
        ])
    )

    assert result.passed is True
    assert result.files_checked == 1


def test_verification_with_findings(monkeypatch):
    agent = VerifyingAgent()

    finding = {
        "file_path": "main.py",
        "title": "Unsafe input handling",
        "description": "Input is not validated.",
        "severity": "HIGH",
        "category": "SECURITY",
        "line_number": 4,
        "suggested_fix": "Validate input.",
    }

    async def mock_completion(**kwargs):
        return valid_result(
            passed=False,
            findings=[finding],
        )

    monkeypatch.setattr(
        "app.agents.verifying.llm_client.chat_completion",
        mock_completion,
    )

    result = run_async(
        agent.verify_files([
            {
                "file_path": "main.py",
                "content": "user_input = input()",
            }
        ])
    )

    assert result.passed is False
    assert len(result.findings) == 1
    assert result.findings[0].severity == "HIGH"


def test_reject_inconsistent_file_count(monkeypatch):
    agent = VerifyingAgent()

    async def mock_completion(**kwargs):
        result = json.loads(valid_result())
        result["files_checked"] = 5
        return json.dumps(result)

    monkeypatch.setattr(
        "app.agents.verifying.llm_client.chat_completion",
        mock_completion,
    )

    with pytest.raises(VerificationOutputError):
        run_async(
            agent.verify_files([
                {
                    "file_path": "main.py",
                    "content": "print('Hello')",
                }
            ])
        )


def test_reject_passed_result_with_findings(monkeypatch):
    agent = VerifyingAgent()

    finding = {
        "file_path": "main.py",
        "title": "Bug",
        "description": "A defect exists.",
        "severity": "HIGH",
        "category": "LOGIC",
    }

    async def mock_completion(**kwargs):
        return valid_result(
            passed=True,
            findings=[finding],
        )

    monkeypatch.setattr(
        "app.agents.verifying.llm_client.chat_completion",
        mock_completion,
    )

    with pytest.raises(VerificationOutputError):
        run_async(
            agent.verify_files([
                {
                    "file_path": "main.py",
                    "content": "print('Hello')",
                }
            ])
        )


def test_handles_llm_failure(monkeypatch):
    agent = VerifyingAgent()

    async def mock_completion(**kwargs):
        from app.services.llm_client import LLMAPIError
        raise LLMAPIError("Simulated failure")

    monkeypatch.setattr(
        "app.agents.verifying.llm_client.chat_completion",
        mock_completion,
    )

    with pytest.raises(VerifyingAgentError):
        run_async(
            agent.verify_files([
                {
                    "file_path": "main.py",
                    "content": "print('Hello')",
                }
            ])
        )


# ---------------------------------------------------------
# Python syntax validation
# ---------------------------------------------------------

def test_valid_python_syntax():
    finding = VerifyingAgent._check_python_syntax(
        "main.py",
        "def hello():\n    return 'Hello'\n",
    )

    assert finding is None


def test_invalid_python_syntax():
    finding = VerifyingAgent._check_python_syntax(
        "main.py",
        "def hello(\n    return 'Hello'\n",
    )

    assert isinstance(finding, VerificationFinding)
    assert finding.severity == "HIGH"
    assert finding.category == "SYNTAX"
    assert finding.line_number is not None


# ---------------------------------------------------------
# JSON validation
# ---------------------------------------------------------

def test_valid_json():
    finding = VerifyingAgent._check_json(
        "config.json",
        '{"name": "VeriReview", "version": 1}',
    )

    assert finding is None


def test_invalid_json():
    finding = VerifyingAgent._check_json(
        "config.json",
        '{"name": "VeriReview",}',
    )

    assert isinstance(finding, VerificationFinding)
    assert finding.category == "CONFIGURATION"
    assert finding.severity == "HIGH"


# ---------------------------------------------------------
# TOML validation
# ---------------------------------------------------------

def test_valid_toml():
    finding = VerifyingAgent._check_toml(
        "pyproject.toml",
        '[project]\nname = "verireview"\nversion = "1.0.0"\n',
    )

    assert finding is None


def test_invalid_toml():
    finding = VerifyingAgent._check_toml(
        "pyproject.toml",
        '[project\nname = "verireview"\n',
    )

    assert isinstance(finding, VerificationFinding)
    assert finding.category == "CONFIGURATION"


# ---------------------------------------------------------
# Combined deterministic validation
# ---------------------------------------------------------

def test_deterministic_checks_detect_multiple_errors():
    agent = VerifyingAgent()

    files = [
        {
            "file_path": "main.py",
            "content": "def hello(\n",
        },
        {
            "file_path": "config.json",
            "content": '{"invalid": }',
        },
        {
            "file_path": "pyproject.toml",
            "content": '[project\n',
        },
    ]

    findings, checks = agent._run_deterministic_checks(files)

    assert len(findings) == 3

    assert all(
        isinstance(item, VerificationFinding)
        for item in findings
    )

    assert "Python syntax validation" in checks
    assert "JSON validation" in checks
    assert "TOML validation" in checks


def test_deterministic_checks_accept_valid_files():
    agent = VerifyingAgent()

    files = [
        {
            "file_path": "main.py",
            "content": "print('Hello')\n",
        },
        {
            "file_path": "config.json",
            "content": '{"enabled": true}',
        },
        {
            "file_path": "pyproject.toml",
            "content": '[project]\nname = "test"\n',
        },
    ]

    findings, checks = agent._run_deterministic_checks(files)

    assert findings == []
    assert "Python syntax validation" in checks
    assert "JSON validation" in checks
    assert "TOML validation" in checks


# ---------------------------------------------------------
# JavaScript syntax validation
# ---------------------------------------------------------

def test_javascript_syntax_when_node_is_available():
    agent = VerifyingAgent()

    if not agent._node_executable:
        pytest.skip("Node.js is not installed.")

    finding = agent._check_javascript(
        "main.js",
        "const message = 'Hello';\nconsole.log(message);\n",
    )

    assert finding is None


def test_invalid_javascript_syntax_when_node_is_available():
    agent = VerifyingAgent()

    if not agent._node_executable:
        pytest.skip("Node.js is not installed.")

    finding = agent._check_javascript(
        "main.js",
        "function hello( {\n",
    )

    assert isinstance(finding, VerificationFinding)
    assert finding.category == "SYNTAX"


# ---------------------------------------------------------
# Finding deduplication
# ---------------------------------------------------------

def test_finding_merge_removes_duplicates():
    first = VerificationFinding(
        file_path="main.py",
        title="Syntax error",
        description="Invalid syntax.",
        severity="HIGH",
        category="SYNTAX",
        line_number=4,
    )

    duplicate = VerificationFinding(
        file_path="MAIN.PY",
        title="Syntax error",
        description="Another description.",
        severity="HIGH",
        category="SYNTAX",
        line_number=4,
    )

    merged = VerifyingAgent._merge_findings(
        [first],
        [duplicate],
    )

    assert len(merged) == 1


def test_finding_merge_preserves_distinct_findings():
    first = VerificationFinding(
        file_path="main.py",
        title="Syntax error",
        description="Invalid syntax.",
        severity="HIGH",
        category="SYNTAX",
        line_number=4,
    )

    second = VerificationFinding(
        file_path="main.py",
        title="Security issue",
        description="Unsafe operation.",
        severity="CRITICAL",
        category="SECURITY",
        line_number=10,
    )

    merged = VerifyingAgent._merge_findings(
        [first],
        [second],
    )

    assert len(merged) == 2