"""Patient-free GUI metadata; actual pipelines always come from Pictologics.

The release API check verifies names and preflight spacing against the installed
wheel. This module never imports Pictologics into the Slicer GUI process.
"""
from __future__ import annotations

from dataclasses import dataclass

from .inline_config import preset_names

PRESET_GROUPS = ("General", "Coronary plaque", "Myocardium")


@dataclass(frozen=True)
class Preset:
    group: str
    label: str
    description: str
    spacing: float
    intensity_range: tuple[float, float] | None = None


PRESETS: dict[str, Preset] = {}
for _name in preset_names():
    _method, _text_value = _name.split("_")[1:]
    _detail = (f"Fixed bin count: {_text_value} bins." if _method == "fbn" else
               f"Fixed bin size: {_text_value} HU, starting at -1000 HU; intended for CT.")
    PRESETS[_name] = Preset("General", _name, f"General-purpose radiomics; 0.5 mm isotropic resampling. {_detail}", 0.5)

for _group, _prefix, _label, _range, _extended in (
    ("Coronary plaque", "coronary", "All plaque", "-99.999 to 3000", True),
    ("Coronary plaque", "coronary_ncp", "Non-calcified plaque", "-99.999 to 350.999", False),
    ("Coronary plaque", "coronary_lap", "Low-attenuation plaque", "-99.999 to 29.999", False),
    ("Coronary plaque", "coronary_cp", "Calcified plaque", "351 to 3000", False),
    ("Myocardium", "lv", "Whole myocardium", "-179.999 to 2000", True),
    ("Myocardium", "lv_fat", "Fat compartment", "-179.999 to -30", False),
    ("Myocardium", "lv_myo", "Myocardial tissue", "-29 to 350", False),
    ("Myocardium", "lv_calc", "Calcium compartment", "351 to 2000", False),
):
    _base = f"CT template for {_label.lower()}; 0.5 mm isotropic resampling; retain {_range} HU. "
    _lo, _hi = map(float, _range.split(" to "))
    PRESETS[f"{_prefix}_orig"] = Preset(
        _group, f"{_label} — intensity and shape",
        _base + "Intensity and morphology features, without discretisation.", 0.5, (_lo, _hi))
    for _method in ("fbn", "fbs"):
        for _value in ((16, 32, 64, 128) if _extended else (16, 32, 64)):
            _detail = (f"Fixed bin count: {_value} bins." if _method == "fbn" else
                       f"Fixed bin size: {_value} HU, starting at the retained range's lower bound.")
            PRESETS[f"{_prefix}_{_method}_{_value}"] = Preset(
                _group, f"{_label} — {_method.upper()} {_value} {'bins' if _method == 'fbn' else 'HU'}",
                _base + _detail + " Texture, histogram and intensity-volume histogram features.", 0.5, (_lo, _hi))


def all_preset_names() -> tuple[str, ...]:
    return tuple(PRESETS)
