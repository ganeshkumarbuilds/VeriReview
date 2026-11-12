import asyncio
import uuid

import pytest

from app.workflows import generation


def run_async(coroutine):
    return asyncio.run(
        coroutine,
        loop_factory=asyncio.SelectorEventLoop,
    )


class FakeLifecycle:
    def __init__(self):
        self.started = []
        self.completed = []
        self.failed = []
        self.progress_updates = []

    def agent_started(self, agent_type, input_data):
        execution_id = str(uuid.uuid4())
        self.started.append(agent_type)
        return execution_id

    def agent_progress(
        self,
        agent_type,
        execution_id,
        progress,
        output_data=None,
    ):
        self.progress_updates.append(
            (agent_type, progress, output_data)
        )

    def agent_completed(
        self,
        agent_type,
        execution_id,
        output_data,
    ):
        self.completed.append(agent_type)

    def agent_failed(
        self,
        agent_type,
        execution_id,
        error_message,
    ):
        self.failed.append(agent_type)


class FakePlanningResult:
    architecture = {"overview": "Simple Python application"}

    folder_structure = {
        "files": [
            {
                "path": "main.py",
                "purpose": "Application entry point",
            },
            {
                "path": "requirements.txt",
                "purpose": "Dependencies",
            },
        ],
    }

    implementation_plan = {
        "phases": [
            "Create application",
            "Configure dependencies",
        ],
    }

    estimated_files = 2

    def model_dump(self):
        return {
            "architecture": self.architecture,
            "folder_structure": self.folder_structure,
            "implementation_plan": self.implementation_plan,
            "estimated_files": self.estimated_files,
        }


class FakeGeneratedFile:
    def __init__(self, file_path, content):
        self.file_path = file_path
        self.content = content

    def model_dump(self):
        return {
            "file_path": self.file_path,
            "purpose": "Generated test file",
            "content": self.content,
        }


class FakeVerificationResult:
    def __init__(self, findings=None):
        self.findings = findings or []
        self.passed = not bool(self.findings)

    def model_dump(self):
        return {
            "passed": self.passed,
            "summary": "Mock verification completed",
            "files_checked": 2,
            "checks_performed": ["Source code inspection"],
            "findings": self.findings,
        }


class FakeReviewResult:
    def model_dump(self):
        return {
            "summary": "Issues require user approval.",
            "total_findings": 1,
            "critical_count": 0,
            "high_count": 1,
            "medium_count": 0,
            "low_count": 0,
            "findings": [
                {
                    "file_path": "main.py",
                    "title": "Potential runtime error",
                    "description": "A potential runtime issue was detected.",
                    "severity": "HIGH",
                    "category": "BUG",
                    "line_number": 5,
                    "suggested_fix": "Correct the implementation.",
                }
            ],
            "requires_user_approval": True,
        }


@pytest.fixture
def initial_state():
    return {
        "workflow_id": str(uuid.uuid4()),
        "workflow_type": "GENERATION",
        "project_id": str(uuid.uuid4()),
        "workflow_status": "RUNNING",
        "progress_percentage": 0,
        "iteration": 1,
        "requirements": "Build a simple Python application.",
        "technology_stack": "Python",
        "generated_files": [],
        "project_file_ids": [],
        "finding_ids": [],
        "pending_fix_request_ids": [],
        "approved_fix_request_ids": [],
        "agent_execution_ids": {},
    }


def configure_fake_agents(monkeypatch, findings=None):

    async def fake_plan(**kwargs):
        return FakePlanningResult()

    async def fake_generate_file(**kwargs):
        file_path = kwargs["file_path"]

        contents = {
            "main.py": (
                "def main():\n"
                "    print('Hello VeriReview')\n"
            ),
            "requirements.txt": "",
        }

        return FakeGeneratedFile(
            file_path=file_path,
            content=contents[file_path],
        )

    async def fake_verify_files(**kwargs):
        return FakeVerificationResult(findings)

    # Accept the positional verification_results argument.
    async def fake_review(verification_results):
        return FakeReviewResult()

    monkeypatch.setattr(
        generation.planning_agent,
        "plan",
        fake_plan,
    )

    monkeypatch.setattr(
        generation.coding_agent,
        "generate_file",
        fake_generate_file,
    )

    monkeypatch.setattr(
        generation.verifying_agent,
        "verify_files",
        fake_verify_files,
    )

    monkeypatch.setattr(
        generation.review_agent,
        "review",
        fake_review,
    )


def test_complete_generation_graph_without_findings(
    monkeypatch,
    initial_state,
):
    configure_fake_agents(monkeypatch)

    lifecycle = FakeLifecycle()
    graph = generation.build_generation_graph()

    result = run_async(
        graph.ainvoke(
            initial_state,
            config={
                "configurable": {
                    "thread_id": initial_state["workflow_id"],
                    "lifecycle": lifecycle,
                }
            },
        )
    )

    assert result["workflow_status"] == "COMPLETED"
    assert result["progress_percentage"] == 100
    assert len(result["generated_files"]) == 2

    assert result["verification_results"]["passed"] is True
    assert result["review_summary"]["total_findings"] == 0

    assert lifecycle.started == [
        "PLANNING",
        "CODING",
        "VERIFYING",
    ]

    assert lifecycle.completed == [
        "PLANNING",
        "CODING",
        "VERIFYING",
    ]

    assert lifecycle.failed == []


def test_complete_generation_graph_with_findings(
    monkeypatch,
    initial_state,
):
    findings = [
        {
            "file_path": "main.py",
            "title": "Potential runtime error",
            "description": "A potential runtime issue was detected.",
            "severity": "HIGH",
            "category": "BUG",
            "line_number": 5,
            "suggested_fix": "Correct the implementation.",
        }
    ]

    configure_fake_agents(
        monkeypatch,
        findings=findings,
    )

    lifecycle = FakeLifecycle()
    graph = generation.build_generation_graph()

    result = run_async(
        graph.ainvoke(
            initial_state,
            config={
                "configurable": {
                    "thread_id": initial_state["workflow_id"],
                    "lifecycle": lifecycle,
                }
            },
        )
    )

    assert result["workflow_status"] == "WAITING_FOR_APPROVAL"
    assert result["progress_percentage"] == 95
    assert len(result["generated_files"]) == 2

    assert result["verification_results"]["passed"] is False
    assert result["review_summary"]["total_findings"] == 1
    assert result["review_summary"]["requires_user_approval"] is True

    assert lifecycle.started == [
        "PLANNING",
        "CODING",
        "VERIFYING",
        "REVIEW",
    ]

    assert lifecycle.completed == [
        "PLANNING",
        "CODING",
        "VERIFYING",
        "REVIEW",
    ]

    assert lifecycle.failed == []


def test_generation_graph_records_agent_failure(
    monkeypatch,
    initial_state,
):
    lifecycle = FakeLifecycle()

    async def failing_plan(**kwargs):
        raise RuntimeError("Simulated planning failure")

    monkeypatch.setattr(
        generation.planning_agent,
        "plan",
        failing_plan,
    )

    graph = generation.build_generation_graph()

    with pytest.raises(RuntimeError):
        run_async(
            graph.ainvoke(
                initial_state,
                config={
                    "configurable": {
                        "thread_id": initial_state["workflow_id"],
                        "lifecycle": lifecycle,
                    }
                },
            )
        )

    assert lifecycle.started == ["PLANNING"]
    assert lifecycle.failed == ["PLANNING"]
    assert lifecycle.completed == []