# -*- coding: utf-8 -*-
"""Figures of the documentation, generated from the demo campaign (no measurement data).

Usage::

    python docs/scripts/make_figures.py [--out docs/assets]

Writes PNG files of the report figures (English labels) and a screenshot-free set of interactive figures as HTML is
not needed – the documentation embeds the PNG files only.
"""
import argparse
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")

from groundfault import (Intervals, corrections, demo, detect_roles, earthing, equivalent_source, evaluate,  # noqa: E402
                         i18n, open_recording, report)
from groundfault.layout import ENGLISH  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "assets"))
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    i18n.set_language("en")
    base = tempfile.mkdtemp()
    d = demo.make_campaign(base, layout="en")
    camp = d["campaign"]

    def save(fig, name):
        report.save(fig, os.path.join(a.out, name), ("png",), close=True)
        print("written:", name + ".png")

    # substation series
    results = {}
    for w in d["substation"]:
        rec = open_recording(os.path.join(camp, w["cfg"]))
        b = w["intervals"]
        res = evaluate(rec, Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]), tuple(b["post_fault"])),
                       z_fault_ohm=w["Z_F"])
        results[w["Z_F"]] = (res, rec)
        res.save_json(ENGLISH.result_path(camp, os.path.splitext(w["file"])[0]))
    res0, rec0 = results[0.0]
    save(report.rms_trend(res0, rec0, channels=("i_res", "i_coil")), "substation_rms_trend")
    save(report.spectrum(res0), "substation_spectrum")
    save(report.phasor_diagram(res0), "substation_phasor_diagram")
    save(report.spectrum_comparison([results[z][0] for z in (0.0, 2.5, 5.0)], ["0 Ω", "2.5 Ω", "5 Ω"]),
         "substation_spectrum_comparison")
    entries = [dict(file=ENGLISH.result_path(camp, os.path.splitext(w["file"])[0]), Z=w["Z_F"], name="%g Ω" % w["Z_F"])
               for w in d["substation"]]
    series = equivalent_source.fit_equivalent_source(equivalent_source.load_series(entries))
    save(report.source_fit(series, Z_E=2.5), "equivalent_source_fit")
    save(report.ires_over_ze(series, 10.0), "equivalent_source_ires_over_ze")    # no limits: the user defines them

    # station with the earthing measurement of the demo database
    st = d["station"]
    rec = open_recording(os.path.join(camp, st["cfg"]))
    corr = corrections.load(camp)
    corr.apply(rec)
    roles = detect_roles(rec.channel_names, rec.units, corr.role_overrides(rec), corr.main_channel(rec),
                         corr.distances(rec))
    b = st["intervals"]
    res = evaluate(rec, Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]), tuple(b["post_fault"])),
                   roles=roles)
    save(report.station_frequency(res), "station_frequency")
    save(report.station_background(res), "station_background")
    with earthing.Database(d["db"]) as db:
        response = earthing.frequency_response(db, db.measurements(location="Station Elm Road")["measurement_id"])
    long_df, ratio = earthing.compare(res.table("station_frequency"), response, measurement="Station Elm Road")
    save(report.earthing_comparison(long_df, ratio), "station_earthing_comparison")
    spectrum, effective = earthing.reduction_factor(res, response)       # no typical range of r: defined by the user
    save(report.reduction_factor(spectrum, effective), "station_reduction_factor")
    check, _ = earthing.check_lv_network(res, response)
    save(report.lv_network(res.table("station_lv_network"), check), "station_lv_network")


if __name__ == "__main__":
    main()
