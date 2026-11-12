import json
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.services.llm_client import (
    LLMClientError,
    llm_client,
)


logger = logging.getLogger(__name__)


class ReviewAgentError(Exception):
    """Base exception for Review Agent errors."""


class ReviewOutputError(ReviewAgentError):
    """Raised when review output is invalid."""


class ReviewedFinding(BaseModel):
    file_path: str
    title: str
    description: str
    severity: str
    category: str
    line_number: int | None = Field(default=None, ge=1)
    suggested_fix: str | None = None
    recommended_action: str


class ReviewResult(BaseModel):
    summary: str
    total_findings: int = Field(ge=0)
    critical_count: int = Field(ge=0)
    high_count: int = Field(ge=0)
    medium_count: int = Field(ge=0)
    low_count: int = Field(ge=0)
    findings: list[ReviewedFinding]
    requires_user_approval: bool


class ReviewAgent:
    """
    Review Agent.

    Converts verification findings into an organized,
    actionable report for the user.

    This agent never modifies project files or
    independently approves fixes.
    """

    SYSTEM_PROMPT = """
You are the Review Agent of VeriReview.

Your responsibility is to interpret verification
findings and present a clear, actionable review.

You must:

1. Summarize the verification results.
2. Organize findings by severity.
3. Explain the practical impact of each issue.
4. Preserve the original file paths and line numbers.
5. Recommend a suitable corrective action.
6. Clearly distinguish critical defects from minor issues.
7. Avoid inventing findings.
8. Never claim that a fix has been applied.
9. Never approve fixes on behalf of the user.
10. Always require explicit user approval before fixes.

Severity levels:
CRITICAL, HIGH, MEDIUM, LOW, INFO.

Return ONLY valid JSON:

{
    "summary": "Review summary",
    "total_findings": 1,
    "critical_count": 0,
    "high_count": 1,
    "medium_count": 0,
    "low_count": 0,
    "requires_user_approval": true,
    "findings": [
        {
            "file_path": "src/main.py",
            "title": "Finding title",
            "description": "Explanation of the issue",
            "severity": "HIGH",
            "category": "SECURITY",
            "line_number": 10,
            "suggested_fix": "Suggested correction",
            "recommended_action": "Ask the user to approve the proposed fix."
        }
    ]
}

Counts must match the supplied findings.
total_findings must equal the number of findings.
"""

    async def review(
        self,
        verification_results: dict[str, Any],
    ) -> ReviewResult:
        """Convert verification findings into a user-facing report."""

        if not isinstance(verification_results, dict):
            raise ValueError(
                "Verification results must be an object."
            )

        if "findings" not in verification_results:
            raise ValueError(
                "Verification results must contain findings."
            )

        findings = verification_results["findings"]

        if not isinstance(findings, list):
            raise ValueError(
                "Verification findings must be a list."
            )

        user_prompt = f"""
Review these verification results.

VERIFICATION RESULTS:
{json.dumps(verification_results, ensure_ascii=False)}

Produce a complete, accurate and actionable report.

Preserve all original findings.
Do not invent additional issues.
All severity counts must be accurate.
Require user approval for corrective actions.

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
                max_tokens=5000,
            )

            result_data = self._parse_response(response)

            result = ReviewResult.model_validate(result_data)

            if result.total_findings != len(result.findings):
                raise ReviewOutputError(
                    "Review finding count is inconsistent."
                )

            expected_counts = {
                "CRITICAL": result.critical_count,
                "HIGH": result.high_count,
                "MEDIUM": result.medium_count,
                "LOW": result.low_count,
            }

            actual_counts = {
                severity: sum(
                    1
                    for finding in result.findings
                    if finding.severity == severity
                )
                for severity in expected_counts
            }

            if expected_counts != actual_counts:
                raise ReviewOutputError(
                    "Review severity counts are inconsistent."
                )

            if len(result.findings) != len(findings):
                raise ReviewOutputError(
                    "Review Agent changed the number of findings."
                )

            if not result.requires_user_approval:
                raise ReviewOutputError(
                    "Corrective actions must require user approval."
                )

            return result

        except ValidationError as exc:
            raise ReviewOutputError(
                "Review output does not match the required schema."
            ) from exc

        except LLMClientError as exc:
            logger.exception("Review Agent LLM request failed.")

            raise ReviewAgentError(
                "Review Agent could not complete the review."
            ) from exc

        except ReviewOutputError:
            raise

        except Exception as exc:
            logger.exception("Unexpected Review Agent failure.")

            raise ReviewAgentError(
                "An unexpected Review Agent error occurred."
            ) from exc

    @staticmethod
    def _parse_response(response: str) -> dict[str, Any]:
        if not isinstance(response, str) or not response.strip():
            raise ReviewOutputError(
                "Review Agent returned an empty response."
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
            raise ReviewOutputError(
                "Review Agent returned invalid JSON."
            ) from exc

        if not isinstance(parsed, dict):
            raise ReviewOutputError(
                "Review output must be a JSON object."
            )

        return parsed


review_agent = ReviewAgent()