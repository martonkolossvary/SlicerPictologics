from __future__ import annotations

import copy

from PictologicsLib.result_browser import filter_result_indices, result_details, roi_identity


def browser_fixture():
    row = {
        "run_id": "run-a",
        "roi_source": "segmentation",
        "roi_id": "same-id",
        "roi_name": "Lesion",
        "image_name": "Image",
        "subject_id": "Case",
        "timestamp": "now",
        "configuration": "test",
        "feature_family": "ivh",
        "feature_name": "Volume fraction",
        "feature_key": "volume_BC2M_10",
        "ibsi_code": "BC2M",
        "pictologics_ibsi_code": "BC2M_10",
        "pictologics_feature_name": "test__volume_BC2M_10",
        "preprocessing_sequence": "1:resample",
        "value": 1.25,
        "status": "ok",
        "pictologics_version": "0.5.1",
        "extension_version": "0.1.0",
    }
    history = [
        {
            "run_id": "run-a",
            "configuration_sha256": "hash-a",
            "provenance": {
                "effective_configuration": {
                    "configs": {
                        "test": {
                            "source_mode": "auto",
                            "sentinel_value": -1000,
                            "steps": [{"step": "resample", "params": {"new_spacing": [1, 1, 1]}}],
                        }
                    }
                },
                "processing_logs": [
                    {
                        "roi_id": "same-id",
                        "roi_source": "segmentation",
                        "entries": [
                            {
                                "config_name": "test",
                                "status": "completed",
                                "result_feature_count": 1,
                                "steps_executed": [
                                    {
                                        "step": "filter",
                                        "params": {"type": "gabor"},
                                        "params_requested": {"boundary": "mirror"},
                                        "params_effective": {"boundary": "periodic"},
                                        "boundary_requested": "mirror",
                                        "boundary_effective": "periodic",
                                    }
                                ],
                            }
                        ],
                    }
                ],
                "feature_catalog": [
                    {"config": "test", "feature_key": "volume_BC2M_10", "mask_usage": "intensity"}
                ],
            },
            "errors": [{"roi_id": "same-id", "roi_source": "segmentation", "error": "ROI warning"}],
        }
    ]
    return row, history


def test_combined_filters_and_duplicate_roi_names_are_run_scoped():
    row, _ = browser_fixture()
    rows = [
        row,
        dict(
            row, run_id="run-b", configuration="other", feature_family="intensity", status="error"
        ),
    ]
    original = copy.deepcopy(rows)
    assert filter_result_indices(rows) == [0, 1]
    assert filter_result_indices(
        rows,
        query="BC2M_10 RESAMPLE",
        roi=roi_identity(row),
        configuration="test",
        family="ivh",
        status="ok",
    ) == [0]
    assert filter_result_indices(rows, query="not-a-feature") == []
    assert filter_result_indices(rows, configuration="other", status="error") == [1]
    assert filter_result_indices(rows, family="missing") == []
    assert rows == original


def test_details_join_exact_run_configuration_and_roi_without_modifying_provenance():
    row, history = browser_fixture()
    history.insert(0, {"run_id": "run-b", "configuration_sha256": "WRONG RUN"})
    original = copy.deepcopy(history)
    text = result_details(row, history)
    for expected in (
        "Value: 1.25",
        "Pictologics IBSI code: BC2M_10",
        "hash-a",
        "new_spacing: [1, 1, 1]",
        "params requested",
        "params effective",
        "periodic",
        "ROI warning",
        "mask usage: intensity",
    ):
        assert expected in text
    assert "WRONG RUN" not in text
    assert history == original


def test_missing_ambiguous_and_malformed_optional_details_are_readable():
    row, history = browser_fixture()
    assert "unavailable or ambiguous" in result_details(row, [])
    assert "unavailable or ambiguous" in result_details(row, history * 2)
    row["value"] = None
    history[0]["provenance"] = {
        "processing_logs": [None, {"entries": "bad"}],
        "feature_catalog": "bad",
    }
    text = result_details(row, history)
    assert "Value: Not available" in text
    assert "No matching processing log" in text
    history[0]["provenance"] = None
    assert "CONFIGURATION" in result_details(row, history)


def test_details_do_not_attach_another_regions_or_configurations_error():
    row, history = browser_fixture()
    history[0]["provenance"]["processing_logs"][0]["entries"][0]["config_name"] = "other"
    history[0]["errors"][0]["roi_source"] = "whole-volume"
    history[0]["provenance"]["feature_catalog"][0]["feature_key"] = "other"
    text = result_details(row, history)
    assert "No matching processing log" in text
    assert "ROI warning" not in text
    assert "FEATURE DICTIONARY" not in text
