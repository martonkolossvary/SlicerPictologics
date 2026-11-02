"""Reject incomplete or misleading mixed-batch qualification evidence."""

import copy
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "batch_soak_support", Path(__file__).resolve().parents[1] / "scripts/batch_soak_support.py"
)
support = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(support)


def fixture():
    plan = [{"case_name": "ok", "expected_status": "completed"},
            {"case_name": "failed", "expected_status": "failed"}]
    rows = [{"subject_id": "ok", "roi_id": roi, "config": config, "feature_key": feature,
             "run_id": "run-1", "status": "ok"}
            for roi in ("a", "b") for config in ("one", "two") for feature in ("mean", "min")]
    document = {"rows": [{"case_name": "ok", "status": "completed", "row_count": 8,
                          "roi_count": 2, "run_id": "run-1", "result_table": "results", "reason": ""},
                         {"case_name": "failed", "status": "failed", "row_count": 0, "reason": "Expected failure"}]}
    return document, rows, plan


def audit(document, rows, plan):
    return support.audit_batch(document, rows, plan, ("one", "two"), features_per_roi_config=2)


def test_default_plan_is_interleaved_and_recovers_after_both_failures():
    plan = support.mixed_plan()
    assert len(plan) == 33
    assert sum(item["expected_status"] == "completed" for item in plan) == 30
    assert len({item["case_name"] for item in plan}) == len(plan)
    assert plan == sorted(plan, key=lambda item: item["case_name"])
    assert [item["fixture"] for item in plan[:5]] == list(support.FIXTURES)
    for index, item in enumerate(plan):
        if item["expected_status"] == "failed":
            assert plan[index + 1]["expected_status"] == "completed"
    assert {item["injection"] for item in plan} == {"", "invalid-segmentation", "invalid-worker-manifest", "missing-segmentation"}


@pytest.mark.parametrize("rounds", [True, 1, 21, 2.5, "6"])
def test_plan_rejects_unbounded_or_too_small_runs(rounds):
    with pytest.raises(ValueError):
        support.mixed_plan(rounds)


def test_complete_feature_matrix_passes_without_mutation():
    document, rows, plan = fixture()
    before = copy.deepcopy((document, rows, plan))
    assert audit(document, rows, plan) == {"cases": 2, "statuses": {"completed": 1, "failed": 1}, "rows": 8, "successful_runs": 1}
    assert (document, rows, plan) == before


@pytest.mark.parametrize("mutation", ["missing_report", "duplicate_report", "unexpected_case", "wrong_status",
                                     "wrong_count", "missing_reason", "failed_rows", "wrong_roi_count",
                                     "missing_run", "wrong_run", "failed_feature", "missing_table",
                                     "missing_feature", "missing_config", "wrong_roi", "duplicate_feature"])
def test_audit_rejects_corrupt_or_incomplete_evidence(mutation):
    document, rows, plan = fixture()
    if mutation == "missing_report":
        document["rows"].pop()
    elif mutation == "duplicate_report":
        document["rows"].append(document["rows"][0])
    elif mutation == "unexpected_case":
        rows[0]["subject_id"] = "surprise"
    elif mutation == "wrong_status":
        document["rows"][1]["status"] = "completed"
    elif mutation == "wrong_count":
        document["rows"][0]["row_count"] = 7
    elif mutation == "missing_reason":
        document["rows"][1]["reason"] = ""
    elif mutation == "failed_rows":
        rows.append(dict(rows[0], subject_id="failed"))
        document["rows"][1]["row_count"] = 1
    elif mutation == "wrong_roi_count":
        document["rows"][0]["roi_count"] = 3
    elif mutation == "missing_run":
        document["rows"][0]["run_id"] = ""
    elif mutation == "wrong_run":
        rows[0]["run_id"] = "wrong"
    elif mutation == "failed_feature":
        rows[0]["status"] = "error"
    elif mutation == "missing_table":
        document["rows"][0]["result_table"] = ""
    elif mutation == "missing_feature":
        rows.pop()
        document["rows"][0]["row_count"] -= 1
    elif mutation == "missing_config":
        rows[0]["config"] = "wrong"
    elif mutation == "wrong_roi":
        rows[0]["roi_id"] = "third"
    elif mutation == "duplicate_feature":
        rows[1]["feature_key"] = rows[0]["feature_key"]
    with pytest.raises(AssertionError):
        audit(document, rows, plan)


def test_cancelled_and_not_started_cases_need_no_result_rows():
    document, rows, plan = fixture()
    for status in ("cancelled", "not_started", "skipped"):
        document["rows"][1]["status"] = status
        plan[1]["expected_status"] = status
        assert audit(document, rows, plan)["rows"] == 8
