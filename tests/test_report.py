# -*- coding: utf-8 -*-
"""Report exports (style, size, no titles, decimal separator, language), RMS/V curve, diagnostics, register,
campaign."""
import math
import os
import re
from pathlib import Path
from types import SimpleNamespace

import matplotlib
import numpy as np
import pandas as pd
import pytest

from groundfault import (report, demo, diagnostics, campaign, open_recording, register, rms, write_comtrade,
                         equivalent_source, i18n, interactive)
from groundfault.evaluation import load_result
from groundfault.station import MAX_PROBE


def _check_figure(fig, width_cm):
    assert fig.get_size_inches()[0] * 2.54 == pytest.approx(width_cm, abs=0.01)
    for ax in fig.axes:
        assert ax.get_title() == "" and ax.get_title("left") == "" and ax.get_title("right") == ""
    assert fig._suptitle is None


def _texts(fig) -> set:
    """All texts of a matplotlib figure (labels, legends, annotations, tick labels); closes the figure."""
    import matplotlib.pyplot as plt
    fig.canvas.draw()
    texts = {t.get_text() for t in fig.findobj(matplotlib.text.Text) if t.get_text()}
    plt.close(fig)
    return texts


def _legend_texts(fig, ax: int = 0) -> list:
    """Legend entries of axes ``ax`` of a matplotlib figure; closes the figure."""
    import matplotlib.pyplot as plt
    texts = [t.get_text() for t in fig.axes[ax].get_legend().get_texts()]
    plt.close(fig)
    return texts


def _station_table() -> pd.DataFrame:
    """Synthetic table ``station_frequency``: earth potential rise at 100 m and touch voltage, 350 Hz uncertain."""
    rows = []
    for channel, role, distance, factor in (("UE100", "u_e", 100.0, 1.0), ("UE1", "u_t", 1.0, 0.8)):
        for m in (1, 5, 7):
            z = factor * 0.05 * m ** 0.5
            rows.append(dict(channel=channel, role=role, distance_m=distance, order=m, f_Hz=50.0 * m, I_F_A=20.0 / m,
                             U_during_fault_V=1.1 * z * 20 / m, U_background_V=0.2 * z * 20 / m, U_fault_V=z * 20 / m,
                             Z_direct_Ohm=1.1 * z, Z_inception_Ohm=0.98 * z, Z_clearance_Ohm=1.02 * z,
                             Z_voltage_Ohm=np.nan, Z_fault_Ohm=z, Z_fault_angle_deg=30.0, Z_direct_angle_deg=25.0,
                             method_spread_pct=4.0 if m != 7 else 35.0, uncertain=m == 7))
    return pd.DataFrame(rows)


def _rf_spectrum(origin_250hz: str) -> pd.DataFrame:
    """Synthetic reduction factor per order (probe maximum against earthing measurement ID 1), the earthing
    measurement at 250 Hz with the origin ``origin_250hz``."""
    rows = []
    for m, origin in ((1, "gemessen bei 50 Hz"), (5, origin_250hz), (7, "gemessen bei 350 Hz")):
        rows.append(dict(channel=MAX_PROBE, probe="UE_5m", distance_fault_m=5.0, injection_id=1,
                         distance_injection_m=70.0, distance_match="maximum", order=m, f_Hz=50.0 * m, I_F_A=10.0,
                         UE_per_A_fault=0.5, UE_per_A_direct=0.5, UE_per_A_injection=1.0, injection_frequency=origin,
                         r=0.5, r_direct=0.5, r_to_r_50Hz=1.0, share_shield=np.nan, r_shield=np.nan, uncertain=False))
    return pd.DataFrame(rows)


def test_figures_without_title_and_in_final_size(demo_results, tmp_path):
    res, w, p, rec = demo_results[0.0]
    figs = [report.instantaneous(rec, res.roles, res.t_max_window, 0.06),
            report.rms_trend(res, rec), report.spectrum(res), report.harmonics_trend(res),
            report.phasor_diagram(res), report.voltage_spectrum(res)]
    for f in figs:
        _check_figure(f, report.STYLE.full_width_cm)
    paths = report.save(figs[0], str(tmp_path / "fig_path"), ("pdf", "svg", "png"))
    assert all(os.path.getsize(x) > 1000 for x in paths)
    with open(paths[1], encoding="utf-8") as f:
        svg = f.read()
    # text stays text (svg.fonttype = none): <text> elements with a font style – "font-family: …" (Matplotlib ≥ 3.10)
    # or the shorthand "font: …" (older versions)
    assert re.search(r'<text\b[^>]*style="[^"]*\bfont(-family)?:', svg)


def test_campaign_figures(demo_results):
    entry = [dict(file=p, Z=Z) for Z, (_, _, p, _) in sorted(demo_results.items())]
    r = equivalent_source.fit_equivalent_source(equivalent_source.load_series(entry))
    for f in (report.source_fit(r, Z_E=2.5), report.source_plane(r), report.ires_over_ze(r, 8.0),
              report.spectrum_comparison([e for e, *_ in demo_results.values()], ["a", "b", "c"])):
        assert all(ax.get_title() == "" for ax in f.axes)


def test_source_plane_draws_monte_carlo_spread(demo_results):
    """With the Monte Carlo result, source_plane draws one box per order spanning the 5–95 % range of R_q and X_q
    (and the axes include it); without it, no box."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    plt.close("all")                                      # figures left open by earlier tests
    entry = [dict(file=p, Z=Z) for Z, (_, _, p, _) in sorted(demo_results.items())]
    r = equivalent_source.fit_equivalent_source(equivalent_source.load_series(entry))
    mc = equivalent_source.monte_carlo(r, 2.5, n=200, seed=3)
    boxes = lambda f: [p for p in f.axes[0].patches if isinstance(p, Rectangle)]
    assert boxes(report.source_plane(r)) == []
    fig = report.source_plane(r, mc)
    got = sorted((b.get_x(), b.get_x() + b.get_width(), b.get_y(), b.get_y() + b.get_height()) for b in boxes(fig))
    want = sorted((s["Rq_P5"], s["Rq_P95"], s["Xq_P5"], s["Xq_P95"]) for s in mc["Zq"].values())
    assert len(got) == len(r.fits) and np.allclose(got, want)
    x0, x1 = fig.axes[0].get_xlim(); y0, y1 = fig.axes[0].get_ylim()
    assert all(x0 <= a and b <= x1 and y0 <= c and d <= y1 for a, b, c, d in got)
    partial = dict(mc, Zq={m: v for m, v in list(mc["Zq"].items())[:1]})        # orders without an entry: no box
    assert len(boxes(report.source_plane(r, partial))) == 1
    plt.close("all")


def test_slug_one_rule_for_names():
    """report.slug: letters and digits, everything else '_', lower case – the rule of the per-measurement table and
    figure names of a campaign export (report_tables and the campaign notebook)."""
    assert report.slug("Measurement 4 (Station)") == "measurement_4_station"
    assert report.slug("M1 (2,5 Ω)") == "m1_2_5" and report.slug("SUB_2.5-x") == "sub_2_5_x"
    assert "slug" in report.__all__


def test_numbers_decimal_comma():
    assert report.number(1234.5678, 3) == "1235"
    assert report.number(0.012345, 3) == "0,0123"
    assert report.number(12.5, 2, "fixed") == "12,50"
    assert report.number(float("nan")) == "–"


def test_numbers_follow_the_language():
    """Decimal point in English, decimal comma in German; an explicit ``lang`` and ``STYLE.decimal_comma``
    override the output language."""
    with i18n.language("en"):
        assert report.number(0.012345, 3) == "0.0123" and report.number(12.5, 2, "fixed") == "12.50"
        assert report.number(-1234.5, thousands=True) == "\u22121\u2009235"       # half away from zero
        df = report.format_table(pd.DataFrame({"notes": [0, 2], "I in A": [1.5, 12.25]}))
        assert list(df.columns) == ["notes", "I in A"] and list(df["I in A"]) == ["1.50", "12.3"]
        assert report.number(0.5, 2, lang="de") == "0,50"
    assert report.number(0.5, 2, lang="en") == "0.50"
    old = report.STYLE
    try:
        report.set_style(decimal_comma=False)
        assert report.number(0.5, 2) == "0.50"                 # German output, decimal point set by the style
        assert report.number(0.5, 2, lang="de") == "0,50"      # an explicit language wins
    finally:
        report.STYLE = old


def test_table_export(tmp_path, demo_results):
    res = demo_results[0.0][0]
    paths = report.export_tables({"assessment_quantities": res.table("assessment_quantities")}, str(tmp_path),
                                 formats=("csv", "md", "tex"))
    extensions = {os.path.splitext(p)[1] for p in paths}
    assert {".csv", ".md", ".tex", ".xlsx"} <= extensions
    csv = Path([p for p in paths if p.endswith(".csv")][0]).read_text(encoding="utf-8-sig")
    assert ";" in csv and "," in csv
    md = Path([p for p in paths if p.endswith(".md")][0]).read_text(encoding="utf-8")
    expected = report.number(res.values["IRES"], 3, lang="de")
    assert "|" in md and expected in md and "," in expected      # IRES with a decimal comma


def test_table_export_localized(tmp_path, demo_results):
    """German export: German column names and code values (``i18n.localize``), decimal comma also in mixed
    columns; English export: English names and decimal points. File names are English in both languages."""
    res = demo_results[0.0][0]
    tables = {"assessment_quantities": res.table("assessment_quantities")}
    paths = report.export_tables(tables, str(tmp_path / "de"), formats=("csv",))
    lines = Path([p for p in paths if p.endswith(".csv")][0]).read_text(encoding="utf-8-sig").splitlines()
    assert lines[0].startswith("Groesse;Beschreibung;Messwert;Bewertung;Einheit")
    assert any(z.startswith("IH_ges;") for z in lines)                 # code IH_total with its German name
    assert sorted(os.path.basename(p) for p in paths) == ["assessment_quantities.csv", "tables.docx", "tables.xlsx"]
    report.export_table(pd.DataFrame({"f_Hz": ["Rest", 150.5]}), str(tmp_path / "mixed"), formats=("csv",))
    assert "150,5" in (tmp_path / "mixed.csv").read_text(encoding="utf-8-sig")
    with i18n.language("en"):
        paths = report.export_tables(tables, str(tmp_path / "en"), formats=("csv", "md"))
    lines = Path([p for p in paths if p.endswith(".csv")][0]).read_text(encoding="utf-8-sig").splitlines()
    assert lines[0].startswith("quantity;description;measured_value;assessment;unit")
    ires = next(z for z in lines if z.startswith("IRES;")).split(";")
    assert float(ires[2]) == pytest.approx(res.values["IRES"])        # decimal point
    md = Path([p for p in paths if p.endswith(".md")][0]).read_text(encoding="utf-8")
    assert report.number(res.values["IRES"], 3, lang="en") in md
    assert any(p.endswith("tables.xlsx") for p in paths)
    docx = pytest.importorskip("docx")
    headings = [p.text for p in docx.Document(str(tmp_path / "de" / "tables.docx")).paragraphs if p.text]
    assert headings == ["Bewertungsgrößen"]


def test_localize_translates_string_dtype_columns():
    """Code values are translated in text columns of dtype ``object`` and of the pandas string dtype (``str`` in
    pandas ≥ 3)."""
    base = pd.DataFrame({"status": ["WARNING", "NOTE"], "value": [1.0, 2.0]})
    for df in (base.astype({"status": object}), base.astype({"status": "string"})):
        assert i18n.localize(df, "de")["Status"].tolist() == ["WARNUNG", "HINWEIS"]
        assert report._localize(df, "de")["Status"].tolist() == ["WARNUNG", "HINWEIS"]


def test_report_tables_from_result_files(demo_results):
    dat = {"M%g" % Z: load_result(p) for Z, (_, _, p, _) in sorted(demo_results.items())}
    t = report.report_tables(dat)
    assert {"voltages", "residual_current", "split_50hz", "assessment_quantities"} <= set(t)
    e = t["residual_current"].set_index("Größe in A")
    assert e.at["250 Hz", "M0"] > e.at["250 Hz", "M5"]


def test_report_tables_in_english(demo_results):
    dat = {"M%g" % Z: load_result(p) for Z, (_, _, p, _) in sorted(demo_results.items())}
    with i18n.language("en"):
        t = report.report_tables(dat)
    e = t["residual_current"].set_index("Quantity in A")
    assert {"RMS value", "50 Hz", "Harmonic content"} <= set(e.index)
    assert e.at["250 Hz", "M0"] > e.at["250 Hz", "M5"]
    assert "50 Hz (positive sequence)" in set(t["voltages"]["Quantity in V"])
    assert list(t["assessment_quantities"].columns[:4]) == ["quantity", "unit", "M0 measured value",
                                                            "M0 assessment value"]
    g = report.report_tables(dat)                     # German: localized canonical columns, German row labels
    assert list(g["assessment_quantities"].columns[:4]) == ["Groesse", "Einheit", "M0 Messwert", "M0 Bewertung"]
    assert "250 Hz (Gegensystem)" in set(g["voltages"]["Größe in V"])


def test_figure_texts_in_english(demo_results):
    res, w, p, rec = demo_results[0.0]
    e = SimpleNamespace(tables={"station_frequency": _station_table()}, name="Test")
    with i18n.language("en"):
        assert {"pre-fault", "steady state", "post-fault"} <= _texts(report.rms_trend(res, rec))
        assert "RMS value" in _texts(report.harmonics_trend(res))
        assert report.probe_label("UE100", "u_e", 100.0) == "UE100 – earth potential rise, 100 m"
        legend = _legend_texts(report.station_frequency(e))
        assert "uncertain (background/methods)" in legend and "UE1 – touch voltage, 1 m" in legend
        fig = interactive.station_frequency(e)
        assert fig.layout.separators == ".," and fig.layout.title.text.startswith("Earth potential rise")
        assert "uncertain" in fig.data[0].hovertext[2]
        with pytest.raises(ValueError, match="No frequency-selective station evaluation"):
            report.station_frequency(SimpleNamespace(tables={}, name="x"))
    assert report.probe_label("UE100", "u_e", 100.0) == "UE100 – Erdungsspannung, 100 m"
    assert interactive.station_frequency(e).layout.separators == ",."
    with pytest.raises(ValueError, match="Tabelle station_frequency"):
        report.station_frequency(SimpleNamespace(tables={}, name="x"))


def test_messages_complete_in_both_languages():
    for lang in ("en", "de"):
        assert [k for k in i18n.missing_keys(lang) if k.startswith(("report.", "interactive."))] == []


def test_interpolated_injection_values_are_marked():
    """Interpolated values of the earthing measurement are drawn open and named in the legend – for the German text
    written by ``groundfault.earthing`` ("interpoliert …") and for an English code ("interpolated …")."""
    for origin in ("interpoliert 150–350 Hz", "interpolated 150–350 Hz"):
        sp = _rf_spectrum(origin)
        assert "Erdungsmessung interpoliert" in _legend_texts(report.reduction_factor(sp, impedances=False))
        fig = interactive.reduction_factor(sp, impedances=False)
        trace = next(t for t in fig.data if t.name.startswith("Sondenmaximum (UE_5m) ↔"))
        assert list(trace.marker.symbol) == ["circle", "circle-open", "circle"]


def test_hv_voltages_in_the_line_to_earth_panel():
    """Line-to-earth voltages of the HV side (roles ``u_hv_l1e`` …) share the panel of the MV line-to-earth
    voltages."""
    roles = SimpleNamespace(channels=[SimpleNamespace(index=i, role=r, unit="V", short=s) for i, (r, s) in
                                      enumerate((("u_l1e", "U1"), ("u_hv_l1e", "U1HV"), ("u_e", "UE")))])
    groups = report._groups(roles, None)
    assert [k.short for k in groups["Leiter-Erde-Spannung"]] == ["U1", "U1HV"]
    with i18n.language("en"):
        assert list(report._groups(roles, None)) == ["Line-to-earth voltage", "Earth potential rise/touch voltage"]


def test_v_curve_two_methods():
    I_res, Iw, IH = 600.0, 13.0, 5.0
    IL = np.linspace(580, 620, 81)
    ires = np.sqrt(Iw ** 2 + IH ** 2 + (IL - I_res) ** 2)
    t = np.linspace(0, 8, IL.size)
    v = rms.v_curve(t, ires, i_coil=IL)
    assert v.I_min_measured == pytest.approx(math.hypot(Iw, IH), rel=1e-3)
    assert v.I_min_fit == pytest.approx(math.hypot(Iw, IH), rel=1e-6)
    assert v.x_min_fit == pytest.approx(I_res, abs=1e-6)
    assert rms.v_curve(t, ires, Iv_operating=12.0).IG_v_curve == pytest.approx(math.hypot(math.hypot(Iw, IH), 12.0), rel=1e-3)


def test_rms_comparison_and_fundamental_trend(demo_series, tmp_path):
    folder, truth = demo_series
    w = truth[0]
    inst = os.path.join(str(folder), w["file"])
    demo.rms_file_from_instantaneous(inst, str(tmp_path / "rms.cfg"))
    v = rms.compare_with_instantaneous(open_recording(inst), open_recording(str(tmp_path / "rms.cfg")), tuple(w["intervals"]["steady_state"]))
    large = v["mean_device"] > 0.01 * v["mean_device"].max()      # leave out the faulted phase (≈ 0 V)
    assert (v.loc[large, "deviation_median_pct"].abs() < 0.05).all()
    g = rms.fundamental_trend(open_recording(inst), tuple(w["intervals"]["steady_state"]))
    assert g["Iw_A"].median() == pytest.approx(w["Iw"], abs=0.05)


def test_diagnosis_detects_time_offset(tmp_path):
    demo.make_substation_recording(str(tmp_path / "ok.cfg"), 0.0, duration=8.0)
    rec = open_recording(str(tmp_path / "ok.cfg"))
    d = diagnostics.diagnose(rec)
    assert d.alignment_suggestion is None
    # shift the voltages by 1.5 s (reproduces an export error between subsystems)
    x = rec.read(0, rec.n)
    n = int(1.5 * rec.fs)
    sig = {}
    for j, (nm, eh) in enumerate(zip(rec.channel_names, rec.units)):
        v = x[:, j]
        if eh == "V":
            v = np.roll(v, n)                         # voltages 1.5 s later (end appended at the front)
        sig[nm] = (eh, v)
    write_comtrade(str(tmp_path / "versatz.cfg"), sig, rec.fs)
    d2 = diagnostics.diagnose(open_recording(str(tmp_path / "versatz.cfg")))
    assert d2.alignment_suggestion is not None
    assert d2.alignment_suggestion["dt_s"] == pytest.approx(1.5, abs=0.05)


def test_diagnosis_active_range_despite_inrush_peak():
    """The transient peak at fault inception (20 ms RMS value ≫ steady current) must not shorten the active range to
    this instant; a short fault (0.3 s) is still detected."""
    t = np.arange(0, 60, 0.02)
    r = np.full(t.size, 0.3)
    r[(t >= 20.0) & (t < 28.0)] = 35.0
    r[(t >= 20.0) & (t < 20.04)] = 450.0                       # transient peak 13 × the steady current
    from_, until = diagnostics._active_range(t, r)
    assert from_ == pytest.approx(20.0, abs=0.05) and until == pytest.approx(27.98, abs=0.05)
    k = np.full(t.size, 0.3)
    k[(t >= 10.0) & (t < 10.3)] = 40.0                         # a short fault (0.3 s) is kept
    from_, until = diagnostics._active_range(t, k)
    assert from_ == pytest.approx(10.0, abs=0.05) and until == pytest.approx(10.28, abs=0.05)


@pytest.mark.parametrize("name,z", [
    ("SUB_0_10_000kHz.cfg", 0.0), ("SUB_2_5_10_000kHz.cfg", 2.5), ("SUB_5_10_000Hz.cfg", 5.0),
    ("SUB_0_Messung_10_000kHz.cfg", 0.0), ("SUB_25_measurement_10_000kHz.cfg", 2.5),
    ("SUB_Trafo_25_Messung_10_000kHz.cfg", 2.5), ("Southdale_Trafo_5_10_000kHz.cfg", 5.0),
    ("SUB_Transformer_2_5_10_000kHz.cfg", 2.5), ("Y_Trafo_7_5_10_000kHz.cfg", 7.5), ("Station_A_40_000kHz.cfg", None),
    ("Y_Station_10_000kHz.cfg", None), ("2026-01-15-10-00-00_10_000kHz.cfg", None)])
def test_resistance_from_file_name(name, z):
    assert register.resistance_from_name(name) == z


@pytest.mark.parametrize("name,z", [
    ("SUB_3_10_000kHz.cfg", 3.0), ("SUB_15_40_000kHz.cfg", 15.0), ("SUB_50_Messung_40_000kHz.cfg", 50.0),
    ("SUB_7_5_40_000kHz.cfg", 7.5), ("SUB_7.5_10_000kHz.cfg", 7.5), ("SUB_12,5_10_000Hz.cfg", 12.5),
    ("SUB_12.25_measurement_40_000kHz.cfg", 12.25), ("SUB_25_40_000kHz.cfg", 2.5),         # 25: shorthand of 2.5 Ω
    ("SUB_12_5_10_000kHz.cfg", 12.5), ("SUB_110_5_40_000kHz.cfg", 110.5), ("SUB_1000_25_40_000kHz.cfg", 1000.25),
    ("SUB_12_25_10_000kHz.cfg", 12.25), ("SUB_12345_5_10_000kHz.cfg", 5.0),   # five digits: no integer part
    ("SUB_40_000kHz.cfg", None), ("SUB_10_000Hz.cfg", None), ("UW_10_000kHz.cfg", None),     # sampling rate only
    ("Station7_40_000kHz.cfg", None), ("Messung_20260115_10_000kHz.cfg", None),
])
def test_resistance_from_file_name_any_number(name, z):
    """Any integer and decimals (2_5, 12_5, 7.5, 12,5) are read; the sampling-rate part is never taken for a
    resistance."""
    assert register.resistance_from_name(name) == z


def _resistance_from_name_before(filename):
    """resistance_from_name as it was before integers other than 0, 1, 2, 5, 10, 25 and decimals with a point or
    comma were read – the reference for the backward compatibility."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    stem = re.sub(r"_\d+_\d+k?Hz$", "", stem, flags=re.I)
    stem = re.sub(r"_(Messung|measurement)$", "", stem, flags=re.I)
    m = re.search(r"(?:^|_)(\d+)_(\d+)$", stem)
    if m and m.group(1) in ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"):
        return float("%s.%s" % (m.group(1), m.group(2)))
    m = re.search(r"(?:^|_)(\d+)$", stem)
    if m:
        v = m.group(1)
        if v == "25":
            return 2.5
        if v in ("0", "5", "10", "1", "2"):
            return float(v)
    return None


def test_resistance_from_file_name_backward_compatible():
    """Every name that was recognised before gives the same value – except ``<int>_<digits>`` with an integer part
    above 10 (or with a leading zero), which is now read as a decimal instead of the last number alone
    (``SUB_12_5`` → 12.5 Ω instead of 5 Ω)."""
    import itertools
    numbers = ["0", "1", "2", "3", "5", "7", "10", "12", "15", "25", "50", "05", "110"]
    tails = ["", "_5", "_25", "_0", "_50", "_3", "_75"]
    suffixes = ["", "_Messung", "_measurement"]
    rates = ["", "_10_000kHz", "_40_000kHz", "_10_000Hz", "_40kHz"]
    known = 0
    for prefix, n, tail, suffix, rate in itertools.product(("UW_", "SUB_", "Trafo_", ""), numbers, tails, suffixes,
                                                           rates):
        name = prefix + n + tail + suffix + rate + ".cfg"
        before = _resistance_from_name_before(name)
        if before is not None:
            known += 1
            stem = re.sub(r"_\d+_\d+k?Hz$", "", name[:-4])
            m = re.search(r"(?:^|_)(\d{1,4})_(\d+)$", re.sub(r"_(Messung|measurement)$", "", stem))
            changed = m is not None and m.group(1) not in [str(i) for i in range(11)]
            expected = float("%s.%s" % m.groups()) if changed else before
            assert register.resistance_from_name(name) == expected, name
    assert known > 500


def test_register_and_readme(tmp_path):
    k = tmp_path / "01_Messkampagnen" / "2026-01-15_Demo" / "1_Rohdaten" / "UW"
    k.mkdir(parents=True)
    demo.make_substation_series(str(k), Z_values=(0.0, 2.5), prefix="UW")
    path = register.write_register(str(tmp_path))
    assert path.endswith("Messregister.csv")                  # German layout: German file and column names
    assert Path(path).read_text(encoding="utf-8-sig").startswith("Kampagne;Datum;Ort;Messort")
    df, lang = register.read_register(path)
    assert lang == "de" and len(df) == 2
    assert {float(v.replace(",", ".")) for v in df["fault_resistance_Ohm"]} == {0.0, 2.5}
    assert set(df["kind"]) == {"instantaneous"} and set(df["measurement_kind"]) == {"substation"}
    assert register.record_intervals(str(tmp_path), df["path"].iloc[0], steady_state=(2.6, 4.4))
    raw = pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str)
    assert raw["Stationaer_s"].iloc[0] == "2,6–4,4" and set(raw["Art"]) == {"Momentanwerte"} and \
        set(raw["Messart"]) == {"UW"}
    register.write_register(str(tmp_path))                    # manual columns are kept
    assert register.read_register(path)[0]["steady_state_s"].iloc[0] == "2,6–4,4"
    txt = register.campaign_readme(str(tmp_path / "01_Messkampagnen" / "2026-01-15_Demo"), register.scan(str(tmp_path)))
    assert "UW_0_10_000kHz.cfg" in txt and "## Aufzeichnungen" in txt and "Messung_Nr" in txt
    assert (df["status"] == "ok").all()


def test_cfg_files_once_in_any_letter_case(tmp_path):
    """Every configuration file once, whatever the letter case of its extension: one pass over the folder tree instead
    of one search per letter case (on Windows a search for *.CFG also finds x.cfg, which listed every recording twice);
    hidden files such as macOS' ._x.cfg and hidden folders are skipped."""
    raw = tmp_path / "raw"
    (raw / "SUB").mkdir(parents=True)
    (raw / ".hidden").mkdir()
    for name in ("SUB/a.cfg", "SUB/B.CFG", "SUB/c.Cfg", "SUB/._a.cfg", ".hidden/d.cfg", "SUB/a.dat"):
        (raw / name).write_text("")
    files = [os.path.relpath(f, str(raw)).replace(os.sep, "/") for f in register._cfg_files(str(raw))]
    assert files == ["SUB/B.CFG", "SUB/a.cfg", "SUB/c.Cfg"]


def test_register_written_on_windows(tmp_path):
    """Rows are matched by the path with forward slashes: a register written on Windows (backslashes) keeps its
    manual entries when it is refreshed on another operating system, and new rows use forward slashes."""
    k = tmp_path / "campaigns" / "2026-01-15_Demo" / "raw" / "SUB"
    k.mkdir(parents=True)
    demo.make_substation_series(str(k), Z_values=(0.0, 2.5))
    path = register.write_register(str(tmp_path))
    df, _ = register.read_register(path)
    assert all("/" in p and "\\" not in p for p in df["path"])
    raw = pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str)
    raw["path"] = raw["path"].str.replace("/", "\\")                     # as written on Windows
    raw["remark"] = ["manual note", ""]
    raw.to_csv(path, sep=";", encoding="utf-8-sig", index=False)
    assert register.record_intervals(str(tmp_path), "campaigns/2026-01-15_Demo/raw/SUB/" + raw["file"].iloc[1],
                                     steady_state=(2.6, 4.4))
    register.write_register(str(tmp_path))
    df, _ = register.read_register(path)
    assert len(df) == 2 and all("\\" not in p for p in df["path"])
    assert list(df["remark"].fillna("")) == ["manual note", ""]
    assert df["steady_state_s"].iloc[1] == "2.6–4.4"


def test_register_english_layout(tmp_path):
    """English layout: campaigns/…/raw, register.csv with English column names, values and decimal points in the
    intervals; README.md in English."""
    k = tmp_path / "campaigns" / "2026-01-15_Demo" / "raw" / "SUB"
    k.mkdir(parents=True)
    demo.make_substation_series(str(k), Z_values=(0.0, 2.5))
    out = register.update_all(str(tmp_path))
    assert out["register"].endswith("register.csv") and out["files"] == 2
    assert Path(out["register"]).read_text(encoding="utf-8-sig").startswith("campaign;date;location;site")
    df, lang = register.read_register(out["register"])
    assert lang == "en" and set(df["site"]) == {"SUB"} and set(df["kind"]) == {"instantaneous"}
    assert register.record_intervals(str(tmp_path), df["path"].iloc[0], steady_state=(2.6, 4.4))
    assert register.read_register(out["register"])[0]["steady_state_s"].iloc[0] == "2.6–4.4"
    assert sorted(df["fault_resistance_Ohm"]) == ["0", "2.5"]                 # decimal point in English
    assert register.fault_resistance(str(tmp_path), "2026-01-15_Demo", "SUB_2_5_10_000kHz.cfg") == 2.5
    readme = tmp_path / "campaigns" / "2026-01-15_Demo" / "README.md"
    txt = readme.read_text(encoding="utf-8")
    assert txt.startswith("# Staged earth fault test Demo – 2026-01-15") and "## Recordings" in txt
    assert "| 2.5 |" in txt and "| 2,5 |" not in txt and "None" not in txt
    notes = tmp_path / "campaigns" / "2026-01-15_Demo" / "notes"
    assert (notes / "notes.txt").exists() and (notes / "corrections.csv").exists() and (notes / "sites.csv").exists()
    assert (notes / "corrections.csv").read_text(encoding="utf-8-sig").startswith("file;channel;factor")
    assert (notes / "sites.csv").read_text(encoding="utf-8-sig").startswith("site;location_groundmeas;latitude")


def test_register_date_mismatch(tmp_path):
    """The cfg date does not match the campaign folder (e.g. a wrongly set device clock) → hint in the status."""
    k = tmp_path / "01_Messkampagnen" / "2026-02-20_Other" / "1_Rohdaten" / "Station"
    k.mkdir(parents=True)
    demo.make_substation_recording(str(k / "SSt_X_10_000kHz.cfg"), 0.0, duration=3.0, t_on=1.0, t_off=2.0, active_step=None)
    df = register.scan(str(tmp_path))
    assert "cfg-Datum 2026-01-15" in df["status"].iloc[0]


def test_campaign_consistency(demo_results):
    dat = {"M%g" % Z: load_result(p) for Z, (_, _, p, _) in sorted(demo_results.items())}
    k = campaign.consistency(dat).set_index("check")
    assert k.at["I_G gleich in allen Messungen", "status"] == "OK"
    assert k.at["I_H sinkt mit Z_F", "status"] == "OK"
    u = campaign.overview(dat)
    assert len(u) == 3
    ra = campaign.resistive_approach(180.0, 30.0, 2.0, 0.25, 0.75, U_Tp=100.0, F=1.5)    # invented limits
    assert ra["R_limit_Ohm"] == pytest.approx(1.856, abs=0.001) and ra["l_limit_km"] == pytest.approx(1.485, abs=0.001)


def test_campaign_consistency_coil_current_zero():
    """A coil current of exactly 0 A (coil switched off, clamp not connected) cannot be assessed as a ratio: it is
    left out like a missing value instead of crashing; the other measurements are still compared."""
    def result(*h1):
        coils = pd.DataFrame([dict(channel="ISp%d" % (i + 1), H1_A=v) for i, v in enumerate(h1)])
        return SimpleNamespace(values={"IG": 30.0}, tables={"coil_currents": coils}, z_fault_ohm=None)
    with i18n.language("en"):
        k = campaign.consistency({"M0": result(20.0, 0.0), "M1": result(20.5, 15.0), "M2": result(0.0, 15.2),
                                  "M3": result(200.0, 15.1)})
    rows = k.set_index("check")
    assert rows.at["Coil current ISp2", "status"] == "OK"                    # 15.0/15.2/15.1 A, the 0 A left out
    assert "ISp1 in M2" not in " ".join(k["check"]) and "ISp2 in M0" not in " ".join(k["check"])
    assert rows.at["Coil current ISp1 in M3", "status"] == "WARNING"       # 200 A against 20 A: factor 10
    assert "factor ≈ 10: check the measuring range/CT ratio" in rows.at["Coil current ISp1 in M3", "comment"]
    only_zero = campaign.consistency({"M0": result(0.0), "M1": result(0.0)})
    assert not any(str(c).startswith(("Coil current", "Spulenstrom")) for c in only_zero["check"])


def test_rms_comparison_notes(tmp_path):
    """A deviation from the device RMS value is explained: DC component included or scaling factor 10."""
    fs, T = 10000.0, 3.0
    t = np.arange(int(fs * T)) / fs
    sine = math.sqrt(2) * 10.0 * np.cos(2 * np.pi * 50.0 * t)                  # 10 A RMS
    write_comtrade(str(tmp_path / "inst.cfg"), {"DANEO 1_Ströme_IA Inst": ("A", sine + 8.0),   # 8 A DC (clamp)
                                                   "DANEO 1_Ströme_IB Inst": ("A", sine),
                                                   "DANEO 1_Ströme_IC Inst": ("A", sine)}, fs)
    n = int(T * 10)
    write_comtrade(str(tmp_path / "rms.cfg"), {"DANEO 1_Ströme_IA RMS": ("A", np.full(n, math.hypot(10.0, 8.0))),
                                                  "DANEO 1_Ströme_IB RMS": ("A", np.full(n, 100.0)),
                                                  "DANEO 1_Ströme_IC RMS": ("A", np.full(n, 10.0))}, 10.0)
    v = rms.compare_with_instantaneous(open_recording(str(tmp_path / "inst.cfg")), open_recording(str(tmp_path / "rms.cfg")),
                                         (0.5, 2.5)).set_index("channel")
    assert v.at["IA", "mean_own"] == pytest.approx(10.0, rel=1e-3)        # DC component removed
    assert "DC" in v.at["IA", "note"] and abs(v.at["IA", "deviation_incl_dc_pct"]) < 0.5
    assert "Faktor ≈ 10" in v.at["IB", "note"]
    assert v.at["IC", "note"] == "" and abs(v.at["IC", "deviation_median_pct"]) < 0.1


def test_resistive_approach_three_cases():
    limits = dict(U_Tp=100.0, F=1.5)                                          # invented: I_RES,max = 75 A at 2 Ω
    a = campaign.resistive_approach(180.0, 30.0, 2.0, 0.25, 0.75, **limits)   # R_lim > 0 → l_lim
    assert a["R_limit_Ohm"] > 0 and "l_Grenz" in a["comment"]
    b = campaign.resistive_approach(24.0, 30.0, 2.0, 0.25, 0.75, **limits)    # 24 V / 2 Ω = 12 A < I_H,perm
    assert b["R_limit_Ohm"] < 0 and b["l_limit_km"] == 0 and b["assessment_substation"] == "uncritical"
    assert "12,0 A" in b["comment"].replace(".", ",")
    with pytest.warns(UserWarning):
        c = campaign.resistive_approach(180.0, 80.0, 2.0, 0.25, 0.75, **limits)  # I_G > I_RES,max = 75 A
    assert math.isinf(c["R_limit_Ohm"]) and c["assessment_substation"] == "countermeasures"
    assert "Grundschwingung" in c["comment"]


def test_integers_and_closing(tmp_path):
    assert report.number(2) == "2" and report.number(np.int64(12345), thousands=True) == "12\u2009345"
    df = report.format_table(pd.DataFrame({"notes": [0, 2], "I in A": [1.5, 12.25]}))
    assert list(df["Hinweise"]) == ["0", "2"] and list(df["I in A"]) == ["1,50", "12,3"]   # German column name
    import matplotlib.pyplot as plt
    fig, _ = report.figure("half")
    report.save(fig, str(tmp_path / "x"), ("png",), close=True)
    assert not plt.fignum_exists(fig.number)


def test_resistive_approach_with_reduction_factor():
    """r < 1 increases the limit from the permissible touch voltage, I_RES,max = F·U_Tp/(r·R_E,max), but only r·R_E
    acts in the fault circuit (U_E = r·Z_E·I_F) – otherwise R_lim would be too small (not conservative)."""
    a = campaign.resistive_approach(180.0, 30.0, 2.0, 0.25, 0.75, U_Tp=100.0, F=1.5, r=0.5)   # invented limits
    assert a["I_RES_max_A"] == pytest.approx(150.0) and a["R_E_effective_Ohm"] == pytest.approx(1.0)
    expected = 3 * 180.0 / math.sqrt(150.0 ** 2 - 30.0 ** 2) - 3 * 1.0
    assert a["R_limit_Ohm"] == pytest.approx(expected) and a["R_limit_Ohm"] > 0
    assert a["l_limit_km"] == pytest.approx(expected / (2 * 0.25 + 0.75))
    # a permissible residual current given directly needs neither U_Tp nor F
    b = campaign.resistive_approach(180.0, 30.0, 2.0, 0.25, 0.75, I_res_max=150.0, r=0.5)
    assert b["R_limit_Ohm"] == pytest.approx(expected)


def test_update_all(tmp_path):
    k = tmp_path / "01_Messkampagnen" / "2026-01-15_Demo" / "1_Rohdaten" / "UW"
    k.mkdir(parents=True)
    demo.make_substation_series(str(k), Z_values=(0.0,), prefix="UW")
    r = register.update_all(str(tmp_path))
    assert r["files"] == 1 and len(r["readme"]) == 1
    txt = Path(r["readme"][0]).read_text(encoding="utf-8")
    assert "UW_0_10_000kHz.cfg" in txt and "# Erdschlussmessung Demo – 2026-01-15" in txt


def test_table_titles_complete_in_both_languages(demo_results):
    """Every table of report_tables, of a result and of the notebook exports has a title of its own in English and
    German (before, German titles fell back to English words such as “Earthing ratio” or to “Uebersicht”)."""
    res = demo_results[0.0][0]
    names = set(res.tables) | set(report.report_tables({"M1": res})) | {
        "overview", "station_frequency", "earthing_comparison", "earthing_ratio", "station_lv_network",
        "station_lv_network_eff", "reduction_factor", "reduction_factor_eff", "lv_network_check",
        "lv_network_check_eff", "station_metrics", "station_voltages", "station_currents", "station_currents_frequency",
        "station_extrapolation", "transformer_power", "transformer", "epr", "shield_current", "equivalent_sources"}
    titles = {}
    for lang in ("en", "de"):
        with i18n.language(lang):
            titles[lang] = {n: report.table_title(n) for n in names}
    for n in names:
        assert n in report._TABLE_TITLES, n
        assert titles["en"][n] != titles["de"][n], n                      # a German title of its own
        assert "_" not in titles["en"][n] + titles["de"][n], n
    assert titles["de"]["overview"] == "Übersicht der Messungen"
    assert titles["de"]["lv_network_check"] == "Ortsnetz und Erdungsmessung je Frequenz"
    assert titles["de"]["earthing_ratio"] == "Verhältnis Erdschluss / Erdungsmessung je Frequenz"
    assert titles["en"]["lv_network_check_eff"] == "LV network and earthing measurement (RMS values)"


def test_table_titles_keep_the_names_of_the_measurements(tmp_path, demo_results):
    """Tables per measurement carry the name as given (the table name only holds it as report.slug)."""
    measurements = ["Messung 3 (UW 0 Ω)", "Messung 4 (Station)", "Eff test"]
    assert report.table_title("station_frequency_messung_4_station", measurements) == \
        "Erdungs- und Berührungsspannung je Frequenz – Messung 4 (Station)"
    assert report.table_title("epr_messung_4_station", measurements) == "Erdungsspannungen – Messung 4 (Station)"
    assert report.table_title("lv_network_check_eff_messung_4_station") == \
        "Ortsnetz und Erdungsmessung (Effektivwerte) – messung 4 station"          # without the names
    assert report.table_title("reduction_factor_eff_test", measurements) == \
        "Reduktionsfaktor je Harmonische – Eff test"
    assert report.table_title("reduction_factor_eff_test") == "Reduktionsfaktor (effektiv) – test"
    with i18n.language("en"):
        assert report.table_title("earthing_ratio_messung_4_station", measurements) == \
            "Ratio fault test / earthing measurement per frequency – Messung 4 (Station)"
        assert report.table_title("my_table") == "My table"
    docx = pytest.importorskip("docx")
    res = demo_results[0.0][0]
    tables = {"station_frequency_messung_3_uw_0": res.table("assessment_quantities"),
              "overview": res.table("plausibility")}
    paths = report.export_tables(tables, str(tmp_path), prefix="campaign_", formats=(), names=measurements)
    doc = next(p for p in paths if p.endswith(".docx"))
    headings = [p.text for p in docx.Document(doc).paragraphs if p.style.name == "Heading 2"]
    assert headings == ["Erdungs- und Berührungsspannung je Frequenz – Messung 3 (UW 0 Ω)",
                        "Übersicht der Messungen"]


@pytest.mark.parametrize("layout,lang,expected", [
    ("de", None, ["Messregister: {register} – Aufzeichnungen: 5", "Liesmich-Dateien (LIESMICH.md) geschrieben: 1"]),
    ("de", "en", ["register: {register} – recordings: 5", "read-me files (LIESMICH.md) written: 1"]),
    ("en", None, ["register: {register} – recordings: 5", "read-me files (README.md) written: 1"]),
])
def test_update_register_tool_in_the_language_of_the_layout(tmp_path, capsys, layout, lang, expected):
    """tools/update_register.py prints its messages in the language of the folder layout (before: always English),
    or in the language given with --lang."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("update_register", os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "update_register.py"))
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    d = demo.make_campaign(str(tmp_path), layout=layout, groundmeas=False)
    session = i18n.get_language()
    try:
        with i18n.language("en" if layout == "de" else "de"):           # the language of the session does not count
            tool.main([str(tmp_path)] + (["--lang", lang] if lang else []))
    finally:
        i18n.set_language(session)
    out = capsys.readouterr().out.splitlines()
    assert out[:2] == [e.format(register=d["register"]) for e in expected]


def test_export_without_the_export_extra(tmp_path, monkeypatch, demo_results):
    """Without openpyxl or python-docx (extra ``export``) ``export_tables`` skips the workbook or the Word file with a
    warning that names the extra; an explicit XLSX or DOCX export of one table raises an ImportError and writes
    nothing."""
    import sys
    res = demo_results[0.0][0]
    tables = {"assessment_quantities": res.table("assessment_quantities")}
    df = tables["assessment_quantities"]
    for module, library, kept, skipped in (("openpyxl", "openpyxl", "tables.docx", "tables.xlsx"),
                                           ("docx", "python-docx", "tables.xlsx", "tables.docx")):
        with monkeypatch.context() as m:
            m.setitem(sys.modules, module, None)                          # the library cannot be imported
            folder = tmp_path / module
            with pytest.warns(UserWarning, match=r'^%s nicht geschrieben: %s ist nicht installiert \(pip install '
                                                 r'"groundfault\[export\]"\)\.$' % (skipped, library)):
                paths = report.export_tables(tables, str(folder), formats=("csv", "md"))
            assert sorted(os.path.basename(p) for p in paths) == sorted(["assessment_quantities.csv",
                                                                         "assessment_quantities.md", kept])
            fmt = "xlsx" if module == "openpyxl" else "docx"
            with i18n.language("en"), pytest.raises(ImportError, match=r'^The %s export needs %s, which is not '
                                                                        r'installed: pip install "groundfault\[export\]"$'
                                                                        % (fmt.upper(), library)):
                report.export_table(df, str(tmp_path / ("single_" + fmt)), formats=("csv", fmt))
            assert not list(tmp_path.glob("single_%s.*" % fmt))                 # nothing written
            with pytest.raises(ImportError, match=r'^Der %s-Export braucht %s' % (fmt.upper(), library)):
                report.export_table(df, str(tmp_path / ("single_" + fmt)), formats=(fmt,))
    assert report.export_table(df, str(tmp_path / "all"), formats=("xlsx", "docx"))       # with the libraries: written
