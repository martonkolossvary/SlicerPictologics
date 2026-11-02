from __future__ import annotations

import json
from collections import Counter

import pytest
from PictologicsLib.inline_config import preset_names
from PictologicsLib.jobs import _validate_configuration_document
from PictologicsLib.preset_catalog import PRESET_GROUPS, PRESETS, all_preset_names
from PictologicsLib.profiles import build_profile, validate_profile


def test_grouped_catalogue_names_and_descriptions():
    assert PRESET_GROUPS == ("General", "Coronary plaque", "Myocardium")
    assert Counter(preset.group for preset in PRESETS.values()) == {
        "General": 6, "Coronary plaque": 30, "Myocardium": 30}
    assert all_preset_names()[:6] == preset_names()
    assert len(set(all_preset_names())) == 66
    assert all(preset.label and preset.description and preset.spacing == 0.5 for preset in PRESETS.values())
    assert "-99.999 to 29.999 HU" in PRESETS["coronary_lap_fbs_16"].description
    assert PRESETS["lv_myo_orig"].intensity_range == (-29.0, 350.0)
    assert "coronary_fbn_128" in PRESETS and "coronary_cp_fbn_128" not in PRESETS
    assert "lv_fbs_128" in PRESETS and "lv_calc_fbs_128" not in PRESETS


def test_grouped_profile_round_trip_preserves_individual_selection():
    names = ["standard_fbn_32", "coronary_ncp_fbn_16", "lv_myo_orig"]
    profile = build_profile("Cardiac selection", names, None)
    assert validate_profile(json.loads(json.dumps(profile)))["presets"] == names
    assert build_profile("All known", list(all_preset_names()), None)["presets"] == list(all_preset_names())
    for invalid in ("coronary_unknown", "lv_unknown"):
        with pytest.raises(ValueError, match="unknown"):
            build_profile("Bad", [invalid], None)


@pytest.mark.parametrize("name", ["coronary_cp_fbs_16", "lv_myo_orig"])
def test_cardiac_names_are_allowed_by_scene_job_validation(name):
    _validate_configuration_document({"standard_configurations": [name],
                                      "custom_configuration_path": None, "warmup": False})
