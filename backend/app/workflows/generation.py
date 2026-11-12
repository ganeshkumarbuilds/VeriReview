"""VeriReview project generation workflow."""

import inspect
import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.agents.planning import planning_agent
from app.agents.coding import coding_agent
from app.agents.verifying import verifying_agent
from app.agents.review import review_agent
from app.workflows.state import AgentWorkflowState


logger = logging.getLogger(__name__)


class GenerationWorkflowError(Exception):
    """Raised when generation workflow execution fails."""


async def _call_lifecycle(
    lifecycle: Any,
    method_name: str,
    **kwargs: Any,
) -> Any:
    """Invoke an optional lifecycle callback."""

    if lifecycle is None:
        return None

    method = getattr(lifecycle, method_name, None)

    if method is None:
        return None

    result = method(**kwargs)

    if inspect.isawaitable(result):
        return await result

    return result


def _get_lifecycle(
    config: RunnableConfig | None,
) -> Any:
    """Retrieve lifecycle callbacks from runtime configuration."""

    if not config:
        return None

    configurable = config.get("configurable", {})

    if not isinstance(configurable, dict):
        return None

    return configurable.get("lifecycle")


async def _start_agent(
    lifecycle: Any,
    agent_type: str,
    input_data: dict[str, Any],
) -> Any:
    return await _call_lifecycle(
        lifecycle,
        "agent_started",
        agent_type=agent_type,
        input_data=input_data,
    )


async def _complete_agent(
    lifecycle: Any,
    agent_type: str,
    execution_id: Any,
    output_data: dict[str, Any],
) -> None:
    await _call_lifecycle(
        lifecycle,
        "agent_completed",
        agent_type=agent_type,
        execution_id=execution_id,
        output_data=output_data,
    )


async def _fail_agent(
    lifecycle: Any,
    agent_type: str,
    execution_id: Any,
    error: Exception,
) -> None:
    if lifecycle is None or execution_id is None:
        return

    try:
        await _call_lifecycle(
            lifecycle,
            "agent_failed",
            agent_type=agent_type,
            execution_id=execution_id,
            error_message=str(error),
        )
    except Exception:
        logger.exception(
            "Could not record failure for %s agent.",
            agent_type,
        )


async def _progress_agent(
    lifecycle: Any,
    agent_type: str,
    execution_id: Any,
    progress: int,
    output_data: dict[str, Any] | None = None,
) -> None:
    await _call_lifecycle(
        lifecycle,
        "agent_progress",
        agent_type=agent_type,
        execution_id=execution_id,
        progress=progress,
        output_data=output_data,
    )


async def planning_node(
    state: AgentWorkflowState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:

    lifecycle = _get_lifecycle(config)

    input_data = {
        "requirements": state["requirements"],
        "technology_stack": state.get("technology_stack"),
    }

    execution_id = None

    try:
        execution_id = await _start_agent(
            lifecycle,
            "PLANNING",
            input_data,
        )

        result = await planning_agent.plan(**input_data)

        output_data = result.model_dump()

        plan_id = await _call_lifecycle(
            lifecycle,
            "save_plan",
            requirements=state["requirements"],
            plan_data=output_data,
        )

        await _complete_agent(
            lifecycle,
            "PLANNING",
            execution_id,
            output_data,
        )

        return {
            "generation_plan": output_data,
            "generation_plan_id": plan_id,
            "architecture": result.architecture,
            "folder_structure": result.folder_structure,
            "implementation_plan": result.implementation_plan,
            "estimated_files": result.estimated_files,
            "workflow_status": "RUNNING",
            "current_agent": "CODING",
            "progress_percentage": 20,
        }

    except Exception as exc:
        await _fail_agent(
            lifecycle,
            "PLANNING",
            execution_id,
            exc,
        )
        raise


async def coding_node(
    state: AgentWorkflowState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:

    lifecycle = _get_lifecycle(config)

    plan = state["generation_plan"]
    structure = plan["folder_structure"]
    files = structure.get("files", [])

    if not files:
        raise GenerationWorkflowError(
            "Planning Agent did not produce a file list."
        )

    input_data = {
        "requirements": state["requirements"],
        "architecture": plan["architecture"],
        "implementation_plan": plan["implementation_plan"],
        "files_to_generate": files,
        "technology_stack": state.get("technology_stack"),
    }

    execution_id = None
    generated_files = []

    try:
        execution_id = await _start_agent(
            lifecycle,
            "CODING",
            input_data,
        )

        for index, item in enumerate(files):

            if isinstance(item, str):
                file_path = item
                purpose = f"Project file: {item}"

            elif isinstance(item, dict):
                file_path = (
                    item.get("path")
                    or item.get("file_path")
                )
                purpose = item.get(
                    "purpose",
                    "Project source file",
                )

            else:
                raise GenerationWorkflowError(
                    "Invalid file entry in the generation plan."
                )

            if (
                not isinstance(file_path, str)
                or not file_path.strip()
            ):
                raise GenerationWorkflowError(
                    "A planned file is missing its path."
                )

            result = await coding_agent.generate_file(
                requirements=state["requirements"],
                architecture=plan["architecture"],
                implementation_plan=plan["implementation_plan"],
                file_path=file_path,
                file_purpose=purpose,
                technology_stack=state.get("technology_stack"),
            )

            generated_file = result.model_dump()
            generated_files.append(generated_file)

            progress = int(
                ((index + 1) / len(files)) * 100
            )

            await _progress_agent(
                lifecycle,
                "CODING",
                execution_id,
                progress,
                {
                    "generated_files": len(generated_files),
                    "latest_file": file_path,
                },
            )

            logger.info(
                "Generated file %s of %s: %s",
                index + 1,
                len(files),
                file_path,
            )

        file_ids = await _call_lifecycle(
            lifecycle,
            "persist_files",
            generated_files=generated_files,
        )

        await _call_lifecycle(
            lifecycle,
            "set_project_status",
            status="VERIFYING",
        )

        await _complete_agent(
            lifecycle,
            "CODING",
            execution_id,
            {
                "generated_files": generated_files,
                "total_files": len(generated_files),
            },
        )

        return {
            "generated_files": generated_files,
            "project_file_ids": file_ids or [],
            "progress_percentage": 75,
            "current_agent": "VERIFYING",
        }

    except Exception as exc:
        await _fail_agent(
            lifecycle,
            "CODING",
            execution_id,
            exc,
        )
        raise


async def verification_node(
    state: AgentWorkflowState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:

    lifecycle = _get_lifecycle(config)

    generated_files = state.get("generated_files", [])

    if not generated_files:
        raise GenerationWorkflowError(
            "There are no generated files to verify."
        )

    files = [
        {
            "file_path": item["file_path"],
            "content": item["content"],
        }
        for item in generated_files
    ]

    input_data = {
        "files": files,
        "technology_stack": state.get("technology_stack"),
    }

    execution_id = None

    try:
        execution_id = await _start_agent(
            lifecycle,
            "VERIFYING",
            input_data,
        )

        result = await verifying_agent.verify_files(
            **input_data,
        )

        output_data = result.model_dump()

        await _complete_agent(
            lifecycle,
            "VERIFYING",
            execution_id,
            output_data,
        )

        return {
            "verification_results": output_data,
            "progress_percentage": 85,
            "current_agent": "REVIEW",
        }

    except Exception as exc:
        await _fail_agent(
            lifecycle,
            "VERIFYING",
            execution_id,
            exc,
        )
        raise


async def review_node(
    state: AgentWorkflowState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:

    lifecycle = _get_lifecycle(config)

    await _call_lifecycle(
        lifecycle,
        "set_project_status",
        status="REVIEWING",
    )

    verification_results = state.get("verification_results")

    if not isinstance(verification_results, dict):
        raise GenerationWorkflowError(
            "Verification results are missing or invalid."
        )

    findings = verification_results.get("findings")

    if not isinstance(findings, list):
        raise GenerationWorkflowError(
            "Verification findings must be a list."
        )

    passed = verification_results.get("passed")

    if not isinstance(passed, bool):
        raise GenerationWorkflowError(
            "Verification result must contain a valid passed value."
        )

    # Persist an empty review when verification reports no findings.
    if not findings:

        if not passed:
            raise GenerationWorkflowError(
                "Verification failed without reporting any findings."
            )

        summary = {
            "summary": (
                "Generation and verification completed. "
                "No findings were reported."
            ),
            "total_findings": 0,
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "findings": [],
            "requires_user_approval": False,
        }

        persisted = await _call_lifecycle(
            lifecycle,
            "persist_review",
            verification_results=verification_results,
            review_data=summary,
        )

        await _call_lifecycle(
            lifecycle,
            "complete_workflow",
        )

        logger.info(
            "Generation completed successfully with no findings."
        )

        return {
            "review_summary": summary,
            "review_id": (
                persisted.get("review_id")
                if persisted else None
            ),
            "finding_ids": (
                persisted.get("finding_ids", [])
                if persisted else []
            ),
            "workflow_status": "COMPLETED",
            "current_agent": "REVIEW",
            "progress_percentage": 100,
        }

    execution_id = None

    try:
        execution_id = await _start_agent(
            lifecycle,
            "REVIEW",
            verification_results,
        )

        result = await review_agent.review(
            verification_results
        )

        output_data = result.model_dump()

        # Save the completed review and findings before
        # exposing the approval state.
        persisted = await _call_lifecycle(
            lifecycle,
            "persist_review",
            verification_results=verification_results,
            review_data=output_data,
        )

        await _complete_agent(
            lifecycle,
            "REVIEW",
            execution_id,
            output_data,
        )

        return {
            "review_summary": output_data,
            "review_id": (
                persisted.get("review_id")
                if persisted else None
            ),
            "finding_ids": (
                persisted.get("finding_ids", [])
                if persisted else []
            ),
            "workflow_status": "WAITING_FOR_APPROVAL",
            "current_agent": "REVIEW",
            "progress_percentage": 95,
        }

    except Exception as exc:
        await _fail_agent(
            lifecycle,
            "REVIEW",
            execution_id,
            exc,
        )
        raise


def build_generation_graph(checkpointer=None):
    """
    Build the generation workflow graph.

    Checkpoint persistence is supplied by the application.
    Lifecycle callbacks are supplied through RunnableConfig.
    """

    builder = StateGraph(AgentWorkflowState)

    builder.add_node("planning", planning_node)
    builder.add_node("coding", coding_node)
    builder.add_node("verification", verification_node)
    builder.add_node("review", review_node)

    builder.add_edge(START, "planning")
    builder.add_edge("planning", "coding")
    builder.add_edge("coding", "verification")
    builder.add_edge("verification", "review")
    builder.add_edge("review", END)

    return builder.compile(
        checkpointer=checkpointer
    )