import asyncio

from app.workflows.generation import (
    build_generation_graph,
    planning_node,
    coding_node,
    verification_node,
    review_node,
)


def run_async(coroutine):
    return asyncio.run(
        coroutine,
        loop_factory=asyncio.SelectorEventLoop,
    )


def test_generation_graph_compiles():
    graph = build_generation_graph()
    assert graph is not None


def test_generation_graph_has_expected_nodes():
    graph = build_generation_graph()

    assert "planning" in graph.nodes
    assert "coding" in graph.nodes
    assert "verification" in graph.nodes
    assert "review" in graph.nodes


def test_planning_node(monkeypatch):
    from app.workflows import generation

    class FakeResult:
        architecture = {"overview": "Modular"}
        folder_structure = {"files": ["main.py"]}
        implementation_plan = {"phases": []}
        estimated_files = 1

        def model_dump(self):
            return {
                "architecture": self.architecture,
                "folder_structure": self.folder_structure,
                "implementation_plan": self.implementation_plan,
                "estimated_files": self.estimated_files,
            }

    async def fake_plan(**kwargs):
        return FakeResult()

    monkeypatch.setattr(
        generation.planning_agent,
        "plan",
        fake_plan,
    )

    result = run_async(
        planning_node({
            "requirements": "Build a Python application",
            "technology_stack": "Python",
        })
    )

    assert result["current_agent"] == "CODING"
    assert result["estimated_files"] == 1


def test_coding_node(monkeypatch):
    from app.workflows import generation

    class FakeFile:
        def model_dump(self):
            return {
                "file_path": "main.py",
                "purpose": "Entry point",
                "content": "print('Hello')",
            }

    async def fake_generate(**kwargs):
        return FakeFile()

    monkeypatch.setattr(
        generation.coding_agent,
        "generate_file",
        fake_generate,
    )

    result = run_async(
        coding_node({
            "requirements": "Python application",
            "generation_plan": {
                "architecture": {},
                "implementation_plan": {},
                "folder_structure": {
                    "files": ["main.py"],
                },
            },
        })
    )

    assert len(result["generated_files"]) == 1
    assert result["current_agent"] == "VERIFYING"


def test_verification_node(monkeypatch):
    from app.workflows import generation

    class FakeResult:
        def model_dump(self):
            return {
                "passed": True,
                "summary": "No defects detected.",
                "files_checked": 1,
                "findings": [],
                "checks_performed": ["Inspection"],
            }

    async def fake_verify(**kwargs):
        return FakeResult()

    monkeypatch.setattr(
        generation.verifying_agent,
        "verify_files",
        fake_verify,
    )

    result = run_async(
        verification_node({
            "generated_files": [{
                "file_path": "main.py",
                "content": "print('Hello')",
            }],
        })
    )

    assert result["verification_results"]["passed"] is True
    assert result["current_agent"] == "REVIEW"


def test_review_node_completes_when_no_findings(monkeypatch):
    from app.workflows import generation

    async def fake_review(verification_results):
        raise AssertionError(
            "Review Agent should not run when there are no findings."
        )

    monkeypatch.setattr(
        generation.review_agent,
        "review",
        fake_review,
    )

    result = run_async(
        review_node({
            "verification_results": {
                "passed": True,
                "findings": [],
            }
        })
    )

    assert result["workflow_status"] == "COMPLETED"
    assert result["current_agent"] == "REVIEW"
    assert result["progress_percentage"] == 100
    assert result["review_summary"]["total_findings"] == 0
    assert result["review_summary"]["requires_user_approval"] is False


def test_review_node_waits_for_approval_when_findings_exist(monkeypatch):
    from app.workflows import generation

    class FakeResult:
        def model_dump(self):
            return {
                "summary": "A potential security issue was detected.",
                "total_findings": 1,
                "critical_count": 0,
                "high_count": 1,
                "medium_count": 0,
                "low_count": 0,
                "findings": [
                    {
                        "file_path": "main.py",
                        "title": "Unsafe input handling",
                        "description": "Input is not validated.",
                        "severity": "HIGH",
                        "category": "SECURITY",
                        "line_number": 10,
                        "suggested_fix": "Validate user input.",
                        "recommended_action": "Fix the input validation.",
                    }
                ],
                "requires_user_approval": True,
            }

    async def fake_review(verification_results):
        return FakeResult()

    monkeypatch.setattr(
        generation.review_agent,
        "review",
        fake_review,
    )

    result = run_async(
        review_node({
            "verification_results": {
                "passed": False,
                "findings": [
                    {
                        "file_path": "main.py",
                        "title": "Unsafe input handling",
                        "description": "Input is not validated.",
                        "severity": "HIGH",
                        "category": "SECURITY",
                        "line_number": 10,
                        "suggested_fix": "Validate user input.",
                    }
                ],
            }
        })
    )

    assert result["workflow_status"] == "WAITING_FOR_APPROVAL"
    assert result["current_agent"] == "REVIEW"
    assert result["progress_percentage"] == 95
    assert result["review_summary"]["total_findings"] == 1
    assert result["review_summary"]["requires_user_approval"] is True