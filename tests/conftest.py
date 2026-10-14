# -*- coding: utf-8 -*-
"""Shared test data: a synthetic measurement series with known solution (created once per test run)."""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))   # package in src/

import matplotlib  # noqa: E402

matplotlib.use("Agg")

from groundfault import i18n  # noqa: E402

# The test suite checks the German output (messages and labels of the original in-house tool); English output is
# tested explicitly with ``i18n.language("en")``.
i18n.set_language("de")


@pytest.fixture(scope="session")
def demo_series(tmp_path_factory):
    """Substation series 0/2.5/5 Ω with a strong source drift (magnitude and phase), different time origins and a
    clamp with reversed polarity in the 2.5-Ω measurement."""
    from groundfault import demo
    folder = tmp_path_factory.mktemp("demo_series")
    truth = demo.make_substation_series(str(folder), drift={0.0: 1.0, 2.5: demo.polar(1.2, 30), 5.0: demo.polar(0.9, -25)},
                                  polarities={2.5: -1})
    return folder, truth


@pytest.fixture(scope="session")
def demo_results(demo_series):
    """Evaluated demo series: {Z: (result, truth, path of the result file, recording)}."""
    from groundfault import Intervals, open_recording, evaluate
    folder, truth = demo_series
    out = {}
    for w in truth:
        rec = open_recording(os.path.join(str(folder), w["file"]))
        b = w["intervals"]
        res = evaluate(rec, Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]), tuple(b["post_fault"])),
                        z_fault_ohm=w["Z_F"])
        p = res.save_json(os.path.join(str(folder), w["file"].replace(".cfg", "_result.json")))
        out[w["Z_F"]] = (res, w, p, rec)
    return out


def truth_(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
