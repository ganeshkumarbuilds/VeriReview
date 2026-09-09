import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.graph import retrieve_context_node, reviewer_node, finding_verifier_node
from eval.cases import TEST_CASES


def _initial_state_for_diff(diff: str) -> dict:
    # New ReviewState schema: drive only the REVIEW half of the pipeline
    # (retrieve context -> reviewer -> finding verifier) over a fixed diff.
    return {
        "task": "Evaluate this code snippet for bugs",
        "product_spec": "",
        "architecture": "",
        "database_design": "",
        "backend_code": "",
        "frontend_code": "",
        "qa_notes": "",
        "test_report": "",
        "test_passed": True,
        "verification_report": "",
        "requirements_met": True,
        "documentation": "",
        "deployment_config": "",
        "diff": diff,
        "context": "",
        "raw_findings": [],
        "verified_findings": [],
        "review_passed": False,
        "revision_count": 0,
        "max_revisions": 0,
        "revision_history": [],
        "steps_log": [],
    }


def run_eval():
    actual_bugs_caught = 0
    false_alarms = 0
    missed_bugs = 0
    true_negatives = 0

    print(f"Running eval on {len(TEST_CASES)} cases...\n")

    for case in TEST_CASES:
        try:
            state = _initial_state_for_diff(case["diff"])
            state = retrieve_context_node(state)
            state = reviewer_node(state)
            state = finding_verifier_node(state)
        except Exception as e:
            print(f"[{case['id']}] ERROR running review nodes: {e}")
            continue

        found_something = len(state["verified_findings"]) > 0
        is_buggy = case["label"] == "buggy"

        if is_buggy and found_something:
            actual_bugs_caught += 1
            status = "CAUGHT"
        elif is_buggy and not found_something:
            missed_bugs += 1
            status = "MISSED"
        elif not is_buggy and found_something:
            false_alarms += 1
            status = "FALSE ALARM"
        else:
            true_negatives += 1
            status = "CORRECTLY CLEAN"

        print(f"[{case['id']}] label={case['label']:6s} -> {status} ({len(state['verified_findings'])} verified finding(s))")

    print("\n--- RESULTS ---")
    print(f"Actual Bugs Caught:  {actual_bugs_caught}")
    print(f"Missed Bugs:         {missed_bugs}")
    print(f"False Alarms Raised: {false_alarms}")
    print(f"Correctly Clean:     {true_negatives}")


if __name__ == "__main__":
    run_eval()
