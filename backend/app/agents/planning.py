import json
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.services.llm_client import (
    LLMClientError,
    llm_client,
)


logger = logging.getLogger(__name__)


class PlanningAgentError(Exception):
    """Base exception for Planning Agent errors."""


class PlanningOutputError(PlanningAgentError):
    """Raised when the generated planning output is invalid."""


class PlanningResult(BaseModel):
    """
    Structured output produced by the Planning Agent.
    """

    architecture: dict[str, Any] = Field(
        description="The proposed system architecture."
    )

    folder_structure: dict[str, Any] = Field(
        description="The proposed project directory structure."
    )

    implementation_plan: dict[str, Any] = Field(
        description="The ordered implementation tasks."
    )

    estimated_files: int = Field(
        ge=0,
        description="Estimated number of project files."
    )


class PlanningAgent:
    """
    Planning Agent.

    Converts user requirements into a structured
    architecture and implementation plan.

    This agent does not generate source code
    or modify project files.
    """

    SYSTEM_PROMPT = """
You are the Planning Agent of VeriReview,
an AI-powered software engineering platform.

Your responsibility is to analyze project requirements
and produce a comprehensive technical development plan.

You must:

1. Understand the user's requirements.
2. Identify the appropriate architecture.
3. Respect the requested technology stack.
4. Identify the necessary project components.
5. Design a complete folder and file structure.
6. Produce an ordered implementation plan.
7. Identify dependencies between implementation tasks.
8. Estimate the number of project files.

Architecture requirements:
- Explain the purpose of major components.
- Describe how components communicate.
- Identify the responsibilities of each layer.
- Include database and API design considerations
  when relevant.

Folder structure requirements:
- Include actual proposed filenames.
- Organize files logically.
- Include configuration and testing directories
  when appropriate.
- Do not create unnecessary files.

Implementation plan requirements:
- Divide development into ordered phases or tasks.
- Explain what each task accomplishes.
- Identify dependencies between tasks.
- Make the plan actionable for a Coding Agent.

Important restrictions:
- Do not generate source code.
- Do not claim that files have already been created.
- Do not invent requirements that contradict the user.
- Do not silently change the requested technology stack.
- Ask for clarification only when essential information
  is genuinely missing. Otherwise, make reasonable
  assumptions and explicitly document them.

Return ONLY valid JSON.

Required JSON structure:

{
    "architecture": {
        "overview": "Architecture overview",
        "components": [],
        "technology_decisions": [],
        "data_flow": [],
        "assumptions": []
    },
    "folder_structure": {
        "root": "project-name",
        "directories": [],
        "files": []
    },
    "implementation_plan": {
        "phases": [],
        "dependencies": [],
        "milestones": []
    },
    "estimated_files": 0
}

Every field must be present.
Use JSON-compatible values only.
"""

    async def plan(
        self,
        requirements: str,
        technology_stack: str | None = None,
    ) -> PlanningResult:
        """
        Generate a structured project plan.

        Args:
            requirements: User's project requirements.
            technology_stack: Optional requested technologies.

        Returns:
            Validated PlanningResult.

        Raises:
            ValueError: If requirements are empty.
            PlanningOutputError: If the model output is invalid.
            PlanningAgentError: If planning fails.
        """

        if not isinstance(requirements, str) or not requirements.strip():
            raise ValueError(
                "Project requirements cannot be empty."
            )

        stack_information = (
            technology_stack.strip()
            if technology_stack and technology_stack.strip()
            else "No specific technology stack supplied. "
                 "Recommend an appropriate stack."
        )

        user_prompt = f"""
Analyze the following software project requirements.

PROJECT REQUIREMENTS:
{requirements.strip()}

REQUESTED TECHNOLOGY STACK:
{stack_information}

Produce a complete technical architecture,
folder structure and ordered implementation plan.

Return the required JSON structure exactly.
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
                temperature=0.2,
                max_tokens=6000,
            )

            result_data = self._parse_response(response)

            return PlanningResult.model_validate(result_data)

        except ValidationError as exc:
            logger.warning(
                "Planning Agent produced invalid structured output."
            )

            raise PlanningOutputError(
                "Planning output did not match the required schema."
            ) from exc

        except LLMClientError as exc:
            logger.exception("Planning Agent LLM request failed.")

            raise PlanningAgentError(
                "Planning Agent could not complete the request."
            ) from exc

        except PlanningOutputError:
            raise

        except Exception as exc:
            logger.exception("Unexpected Planning Agent failure.")

            raise PlanningAgentError(
                "An unexpected Planning Agent error occurred."
            ) from exc

    @staticmethod
    def _parse_response(response: str) -> dict[str, Any]:
        """
        Parse JSON returned by the LLM.

        Supports plain JSON and JSON inside
        Markdown code fences.
        """

        if not isinstance(response, str) or not response.strip():
            raise PlanningOutputError(
                "Planning Agent returned an empty response."
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
            raise PlanningOutputError(
                "Planning Agent returned invalid JSON."
            ) from exc

        if not isinstance(parsed, dict):
            raise PlanningOutputError(
                "Planning output must be a JSON object."
            )

        return parsed


planning_agent = PlanningAgent()