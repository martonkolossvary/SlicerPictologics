"""Portable assertions for the opt-in public CT/MRI batch soak harness."""

from __future__ import annotations

from collections import Counter, defaultdict

FIXTURES = ("ct-small", "mri-coarse", "ct-medium", "mri-native", "ct-large")


def mixed_plan(rounds=6):
    """Repeat five size/modality variants, with two different recovery failures."""
    if isinstance(rounds, bool) or not isinstance(rounds, int) or not 2 <= rounds <= 20:
        raise ValueError("Use 2–20 rounds (10–100 successful public-fixture cases).")
    plan = []

    def add(fixture, status="completed", injection=""):
        label = injection or fixture
        plan.append({"case_name": f"{len(plan) + 1:03d}-{label}", "fixture": fixture,
                     "expected_status": status, "injection": injection})

    for index in range(rounds):
        for fixture in FIXTURES:
            add(fixture)
        if index == 0:
            add("ct-small", "failed", "invalid-segmentation")
        if index == rounds // 2:
            add("mri-coarse", "failed", "invalid-worker-manifest")
    add("ct-small", "skipped", "missing-segmentation")
    return plan


def audit_batch(document, rows, plan, configurations, *, features_per_roi_config=170):
    """Require exact case outcomes and agreement between reports and feature rows.

    `rows` must contain only this batch's newly committed rows. The current pinned
    all-family configuration produces 170 features per ROI/configuration; keeping
    this explicit prevents a truncated successful payload from passing the soak.
    """
    expected = {case["case_name"]: case["expected_status"] for case in plan}
    actual = {row["case_name"]: row for row in document["rows"]}
    if len(expected) != len(plan) or len(actual) != len(document["rows"]) or actual.keys() != expected.keys():
        raise AssertionError("Batch report case names differ from the workload plan")
    grouped = defaultdict(list)
    for row in rows:
        if row["subject_id"] not in expected:
            raise AssertionError("Unexpected case committed feature rows")
        grouped[row["subject_id"]].append(row)
    successful_run_ids = set()
    for name, status in expected.items():
        report = actual[name]
        case_rows = grouped[name]
        if report["status"] != status or report["row_count"] != len(case_rows):
            raise AssertionError(f"Report outcome/row count differs for {name}")
        if status != "completed":
            if case_rows or not report["reason"]:
                raise AssertionError(f"Unsuccessful case committed rows or lacks a reason: {name}")
            continue
        if report["roi_count"] != 2 or not report["run_id"] or report["run_id"] in successful_run_ids:
            raise AssertionError(f"Missing/duplicate run ID or wrong ROI count: {name}")
        successful_run_ids.add(report["run_id"])
        if not report["result_table"] or any(row["run_id"] != report["run_id"] or row["status"] != "ok" for row in case_rows):
            raise AssertionError(f"Feature status/run ID differs from its report: {name}")
        roi_ids = {row["roi_id"] for row in case_rows}
        pairs = Counter((row["roi_id"], row["config"]) for row in case_rows)
        expected_pairs = {(roi, config) for roi in roi_ids for config in configurations}
        keys = {(row["roi_id"], row["config"], row["feature_key"]) for row in case_rows}
        if len(roi_ids) != 2 or set(pairs) != expected_pairs or any(count != features_per_roi_config for count in pairs.values()):
            raise AssertionError(f"Incomplete ROI/configuration feature matrix: {name}")
        if len(keys) != len(case_rows):
            raise AssertionError(f"Duplicate feature keys within a case: {name}")
    return {"cases": len(plan), "statuses": dict(Counter(expected.values())),
            "rows": len(rows), "successful_runs": len(successful_run_ids)}
