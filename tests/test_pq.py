# -*- coding: utf-8 -*-
"""Power-quality measurements (groundfault.pq): reading exports, 10-min values, quantiles with a known solution,
the factor by duration, the scaling of the harmonic content and its use in the evaluation, the equivalent sources and
the forecast."""
import math
import os

import numpy as np
import pandas as pd
import pytest

from groundfault import demo, equivalent_source, formulas as fml, i18n, pq


@pytest.fixture(scope="module")
def export_30s(tmp_path_factory):
    """Export with 30-s values over 3 days (known quantiles of the 10-min values)."""
    folder = tmp_path_factory.mktemp("pq30")
    return demo.make_pq_export(str(folder / "pq_30s.csv"), days=3.0, interval_s=30.0, seed=3)


@pytest.fixture(scope="module")
def export_10min(tmp_path_factory):
    """Export with 10-min values over 35 days."""
    folder = tmp_path_factory.mktemp("pq600")
    return demo.make_pq_export(str(folder / "pq_600s.csv"), days=35.0, interval_s=600.0, seed=1)


# ============================================================================================== columns
@pytest.mark.parametrize("name, meaning", [
    ("H5_UL1_[V]", ("harmonic", 5, "L1", "value", "V")),
    ("H13_UL3_max_[V]", ("harmonic", 13, "L3", "max", "V")),
    ("H5_UL2_[%]", ("harmonic", 5, "L2", "value", "%")),
    ("U12_[V]", ("rms", None, "L12", "value", "V")),
    ("UNE_[V]", ("rms", None, "NE", "value", "V")),
    ("THD31_[%]", ("thd", None, "L31", "value", "%")),
    ("THDNE_[%]", ("thd", None, "NE", "value", "%")),
    ("H7_L2", ("harmonic", 7, "L2", "value", "V")),
    ("U_H11_L23", ("harmonic", 11, "L23", "value", "V")),
    ("THD_L12", ("thd", None, "L12", "value", "%")),
    ("U_L31", ("rms", None, "L31", "value", "V")),
    ("f_[Hz]", None), ("Pst_UL1", None), ("Datum", None), ("I1_[A]", None)])
def test_column_names(name, meaning):
    assert pq.parse_column(name) == meaning


# ============================================================================================== reading
def test_read_winpq_export(export_30s):
    """Metadata, interval, columns and coverage of a WinPQ export with 30-s values."""
    d = pq.read_winpq(export_30s["path"])
    assert d.interval_s == 30.0 and d.meta["serial"] == "DEMO-0001" and d.meta["instrument"].startswith("PQ-Box")
    assert d.meta["measurement"].startswith("20251215_0000_000") and d.meta["nominal_voltage_V"] == pytest.approx(57.735)
    assert d.reference == "LE" and d.phases == ["L1", "L2", "L3"]
    assert d.orders == export_30s["orders"]
    assert set(d.thd.columns) == {"NE", "L12", "L23", "L31"} and set(d.rms.columns) == {"NE", "L12", "L23", "L31"}
    assert len(d.maxima.columns) == 3 * (len(d.orders) - 1)
    c = d.coverage()
    assert c["span_days"] == pytest.approx(3.0) and c["completeness"] == 1.0 and not c["gaps"]
    assert c["n"] == 3 * 2880 and str(d.start) == "2025-12-15 00:00:00"


def test_semicolon_decimal_comma_export(export_30s, tmp_path):
    """A German export (semicolon, decimal comma, Windows encoding) gives the same values."""
    with open(export_30s["path"], encoding="utf-8") as f:
        text = f.read()
    lines = text.splitlines()
    head = next(i for i, l in enumerate(lines) if l.startswith("Datum,"))
    out = lines[:head]
    for l in lines[head:]:
        parts = l.split(",")
        out.append(";".join(p.replace(".", ",") if i >= 2 else p for i, p in enumerate(parts)))
    p = tmp_path / "pq_de.csv"
    p.write_bytes("\r\n".join(out).encode("cp1252", errors="replace"))
    a, b = pq.read_winpq(export_30s["path"]), pq.read_winpq(str(p))
    assert b.interval_s == 30.0
    pd.testing.assert_frame_equal(a.harmonics, b.harmonics)
    pd.testing.assert_frame_equal(a.thd, b.thd)


def test_read_detects_identical_and_overlapping_exports(export_30s, tmp_path):
    """The same file twice is read once; a second export of the same period is used once; an overlap keeps the
    values of the first export; different intervals cannot be combined."""
    src = export_30s["path"]
    copy = tmp_path / "copy.csv"
    copy.write_bytes(open(src, "rb").read())
    d = pq.read([src, str(copy)])
    assert len(d.harmonics) == 3 * 2880 and any("identisch" in h for h in d.hints)
    # the same period, another file content (one value changed): used once, values of the first file
    text = open(src, encoding="utf-8").read().splitlines()
    head = next(i for i, l in enumerate(text) if l.startswith("Datum,"))
    changed = text[head + 1].split(",")
    changed[2] = "999.000"
    text[head + 1] = ",".join(changed)
    other = tmp_path / "same_period.csv"
    other.write_text("\n".join(text), encoding="utf-8")
    d2 = pq.read([src, str(other)])
    assert len(d2.harmonics) == 3 * 2880 and any("dieselben" in h for h in d2.hints)
    assert d2.rms["NE"].iloc[0] != 999.0
    # overlap: the second half of the period again plus one more day
    w = demo.make_pq_export(str(tmp_path / "later.csv"), days=3.0, interval_s=30.0,
                            start=pd.Timestamp("2025-12-16 00:00").to_pydatetime(), seed=9)
    d3 = pq.read([src, w["path"]])
    assert len(d3.harmonics) == 4 * 2880 and any("überschneiden" in h for h in d3.hints)
    assert d3.harmonics.index.is_monotonic_increasing and not d3.harmonics.index.duplicated().any()
    w10 = demo.make_pq_export(str(tmp_path / "ten.csv"), days=1.0, interval_s=600.0)
    with pytest.raises(ValueError, match="verschiedene Intervalle"):
        pq.read([src, w10["path"]])


def test_from_frame_and_percent_values():
    """Another instrument: a DataFrame with the time in a column, harmonics in % of the fundamental."""
    t = pd.date_range("2026-01-05 00:10", periods=12, freq="10min")
    df = pd.DataFrame({"time": t.astype(str), "H1_L1": 11500.0, "H5_L1_[%]": np.linspace(1.0, 2.0, 12),
                       "H5_L2": 150.0, "THD_L12": 2.0, "Flicker": 0.3})
    d = pq.from_frame(df)
    assert d.interval_s == 600.0 and d.orders == [1, 5]
    assert d.harmonics[(5, "L1")].iloc[-1] == pytest.approx(230.0)
    assert any("nicht verwendet" in h for h in d.hints)                    # the column "Flicker"
    with pytest.raises(ValueError, match="Oberschwingungsspannungen"):
        pq.from_frame(pd.DataFrame({"x": [1.0]}, index=t[:1]))


# ============================================================================================== 10-min values
def test_ten_minute_values_rms_and_mean(export_30s):
    """10-min values of alternating 30-s values a·(1 ± r): exactly a·√(1 + r²) (RMS) and a (mean)."""
    d = pq.read_winpq(export_30s["path"])
    r = export_30s["ripple"]
    rms = pq.ten_minute_values(d)
    mean = pq.ten_minute_values(d, how="mean")
    assert rms.interval_s == 600.0 and len(rms.harmonics) == 3 * 144
    assert rms.harmonics.index[0] == pd.Timestamp("2025-12-15 00:10")          # labelled with the end
    ratio = (rms.harmonics / mean.harmonics).to_numpy()
    assert np.nanmax(np.abs(ratio - math.sqrt(1 + r * r))) < 2e-5
    assert rms.meta["aggregation"]["per"] == 20 and any("20 Werten" in h for h in rms.hints)


def test_incomplete_intervals_are_left_out(export_30s):
    """A missing 30-s value makes its 10-min interval incomplete (left out, counted); min_share lowers the need."""
    d = pq.read_winpq(export_30s["path"])
    drop = d.harmonics.index[[5, 400]]
    cut = pq.PQData(harmonics=d.harmonics.drop(drop), thd=d.thd.drop(drop), rms=d.rms.drop(drop),
                    interval_s=d.interval_s, meta=d.meta)
    a = pq.ten_minute_values(cut)
    assert len(a.harmonics) == 3 * 144 - 2 and a.meta["aggregation"]["n_incomplete"] == 2
    assert any("unvollständig" in h for h in a.hints)
    b = pq.ten_minute_values(cut, min_share=0.9)
    assert len(b.harmonics) == 3 * 144
    with pytest.raises(ValueError, match="länger"):
        pq.ten_minute_values(pq.PQData(harmonics=d.harmonics, interval_s=900.0))
    with pytest.raises(ValueError, match="teilt"):
        pq.ten_minute_values(pq.PQData(harmonics=d.harmonics, interval_s=7.0))


# ============================================================================================== quantiles
@pytest.mark.parametrize("q", [0.5, 0.95, 0.99])
def test_quantiles_known_solution(export_30s, export_10min, q):
    """The quantile of the largest phase per 10-min interval agrees with the truth of the generator (the exported values
    have three decimals)."""
    for w in (export_30s, export_10min):
        a = pq.assess(pq.read(w["path"]), quantile=q)
        for m, u in w["quantiles"][q].items():
            assert a.u95()[m] == pytest.approx(u, rel=1e-4, abs=2e-3), (w["interval_s"], m)


def test_quantile_of_the_largest_phase_per_interval():
    """Per interval the largest phase first, then the quantile – at least the largest quantile of the phases."""
    t = pd.date_range("2026-01-05 00:10", periods=4, freq="10min")
    H = pd.DataFrame({(5, "L1"): [1.0, 9.0, 1.0, 1.0], (5, "L2"): [8.0, 1.0, 1.0, 1.0], (5, "L3"): [1.0, 1.0, 7.0, 1.0],
                      (1, "L1"): 100.0, (1, "L2"): 100.0, (1, "L3"): 100.0})
    H.columns = pd.MultiIndex.from_tuples(H.columns, names=["order", "phase"])
    H.index = t
    a = pq.assess(pq.PQData(harmonics=H, interval_s=600.0), quantile=0.5)
    row = a.table().set_index("order").loc[5]
    assert row["U_quantile_V"] == pytest.approx(np.quantile([8.0, 9.0, 7.0, 1.0], 0.5))       # 7.5
    assert row["U_quantile_L1_V"] == pytest.approx(1.0) and row["U_quantile_V"] > row[["U_quantile_L1_V",
                                                                                         "U_quantile_L2_V",
                                                                                         "U_quantile_L3_V"]].max()


def test_assessment_values(export_10min):
    """THD, harmonic voltage of the loops, dominant order, summary and the values for the evaluation."""
    a = pq.assess(pq.read(export_10min["path"]), factor=1.25)
    assert a.dominant_order == 5 and a.factor == 1.25 and a.valid
    assert np.isfinite(a.thd95_ll) and np.isfinite(a.thd95_le) and a.uh95_ll > 0
    assert a.u95(factored=True)[5] == pytest.approx(1.25 * a.u95()[5])
    assert a.voltages()[5] == pytest.approx(1.25 * a.u95()[5]) and 1 not in a.voltages()
    s = a.series()
    assert set(s) == {"L1", "L2", "L3"} and 5 in s["L1"].columns
    assert s["L3"][5].max() == pytest.approx(1.25 * a.data.harmonics[(5, "L3")].max())
    st = a.settings()
    assert st == dict(u_thd95_percent=a.thd95(), u_thd95_volt=None, pq_safety_factor=1.25, pq_u95=a.u95(),
                      pq_u95_reference="seq")
    sc = a.scaling(thd_measured_percent=2.0)
    assert sc["u95_reference"] == "seq" and sc["safety_factor"] == 1.25 and sc["thd95_percent"] == a.thd95()
    assert set(sc) == {"u95", "u95_reference", "safety_factor", "thd95_percent", "thd_measured_percent"}
    t = a.summary_table().set_index("quantity")
    assert t.loc["span_days", "value"] == pytest.approx(35.0) and t.loc["dominant_order", "value"] == 5
    assert t.loc["gapless_days", "value"] == pytest.approx(35.0) and t.loc["valid", "value"] == True  # noqa: E712
    assert "35.0" in a.summary() or "35,0" in a.summary()
    p = a.profile()
    assert len(p) == 7 * 24 and set(p.columns) == {"weekday", "hour", "median_V", "P95_V", "n"}
    sat, mon = p[p.weekday == 5]["median_V"].mean(), p[p.weekday == 0]["median_V"].mean()
    assert sat / mon == pytest.approx(demo.PQ_WEEKDAY_FACTORS[5] / demo.PQ_WEEKDAY_FACTORS[0], rel=0.08)


def test_invalid_options(export_10min):
    d = pq.read(export_10min["path"])
    with pytest.raises(ValueError, match="quantile"):
        pq.assess(d, quantile=95)
    with pytest.raises(ValueError, match="nicht beides"):
        pq.assess(d, factor=1.2, factors={10: 1.2})
    with pytest.raises(ValueError, match="factor"):
        pq.assess(d, factor=0.0)
    with pytest.raises(ValueError, match="factors"):
        pq.assess(d, factors={-1: 1.0})
    with pytest.raises(ValueError, match="max_gap_minutes"):
        pq.assess(d, max_gap_minutes=-1)


# ============================================================================================== factor
def test_duration_factor_rule():
    """The factor of the longest minimum duration the measurement reaches (an invented rule)."""
    rule = {360.0: 1.0, 20.0: 1.5}
    assert pq.duration_factor(400.0, rule)[0] == 1.0
    assert pq.duration_factor(360.0, rule)[0] == 1.0
    k, hint, valid = pq.duration_factor(40.0, rule)
    assert k == 1.5 and valid and "40.0" in hint.replace(",", ".")
    k, hint, valid = pq.duration_factor(5.0, rule)          # shorter than every duration: not valid, no factor
    assert math.isnan(k) and not valid and "nicht gültig" in hint
    with pytest.raises(ValueError):
        pq.duration_factor(5.0, {})


def test_factor_from_the_rule_in_the_assessment(export_10min):
    d = pq.read(export_10min["path"])
    a = pq.assess(d, factors={360.0: 1.0, 20.0: 1.5})
    assert a.factor == 1.5 and a.valid and a.factor_rule == {360.0: 1.0, 20.0: 1.5}
    b = pq.assess(d, factors={360.0: 1.0, 60.0: 1.5})          # 35 days < 60 days: not valid
    assert math.isnan(b.factor) and not b.valid and any("nicht gültig" in h for h in b.hints)
    for use in (b.scaling, b.settings, b.voltages, b.series):
        with pytest.raises(ValueError, match="nicht gültig"):
            use()
    assert b.voltages(factored=False) == b.u95() and b.table()["U_assessment_V"].iloc[1:].isna().all()
    c = pq.assess(d)
    assert c.factor == 1.0 and c.valid and any("Kein Faktor" in h for h in c.hints)


# ============================================================================================== fault tests
def test_comparability_and_pre_fault_levels(export_10min, demo_results):
    """The pre-fault voltage of a test in the distribution of the PQ measurement, over the whole measurement and in
    the time window of the test (time zone of the PQ clock and UTC of the recorder)."""
    res = demo_results[0.0][0]
    levels, start = pq.pre_fault_levels(res)
    assert set(levels) >= {3, 5, 7, 11, 13} and start is not None
    v = res.values["voltage"]
    i = v["orders"].index(5)
    assert levels[5] == pytest.approx(max(v["pre_fault"][k][i] for k in ("U_L1E", "U_L2E", "U_L3E")))
    a = pq.assess(pq.read(export_10min["path"]))
    s = a.largest(5)
    tab = a.comparability({"low": {5: 1.0}, "mid": {5: float(s.median())}, "high": {5: 1e4}})
    assert list(tab["position_in_range"]) == ["below", "inside", "above"]
    assert tab.iloc[1]["percentile_all"] == pytest.approx(50.0, abs=1.0)
    assert tab.iloc[1]["factor_to_test"] == pytest.approx(a.u95()[5] / s.median())
    # time window: a Saturday 12:00 in local time = 11:00 UTC in winter; 5 Saturdays with 12 intervals each whose
    # middle lies within 11:00 … 13:00
    a_tz = pq.assess(pq.read(export_10min["path"], timezone="Europe/Berlin"))
    t = a_tz.comparability({"sat": {5: 100.0}}, times={"sat": "2025-12-20 11:00:00"})
    names = i18n.tr("pq.weekday_names").split(",")
    assert t.iloc[0]["window"].startswith(names[5] + " 12:00") and t.iloc[0]["n_window"] == 5 * 12
    t_local = a_tz.comparability({"sat": {5: 100.0}}, times={"sat": "2025-12-20 12:00:00"}, times_timezone=None)
    assert t_local.iloc[0]["window"] == t.iloc[0]["window"]
    naive = a.comparability({"sat": {5: 100.0}}, times={"sat": pd.Timestamp("2025-12-20 11:00", tz="UTC")},
                            times_timezone="Europe/Berlin")
    assert naive.iloc[0]["window"].startswith(names[5] + " 12:00")


# ============================================================================================== scaling
def test_scaled_harmonic_current_unscaled_part():
    """The part not scaled (zero sequence, even orders) keeps its measured value: √((I_H² − I_u²)·f² + I_u²); I_u is
    limited to I_H."""
    assert fml.scaled_harmonic_current(10.0, 3.0, 1.5, I_unscaled=0.0) == pytest.approx(20.0)
    assert fml.scaled_harmonic_current(10.0, 3.0, 1.5, I_unscaled=10.0) == pytest.approx(10.0)
    assert fml.scaled_harmonic_current(10.0, 3.0, 1.5, I_unscaled=12.0) == pytest.approx(10.0)
    assert fml.scaled_harmonic_current(10.0, 3.0, 1.5, I_unscaled=6.0) == pytest.approx(math.sqrt(64 * 4 + 36))


def test_harmonic_categories_and_rule_per_order():
    """Positive/negative sequence with its own voltage (from a line-to-line value /√3, at least the smallest level),
    otherwise with the THD, without one as measured; zero sequence and even orders always as measured."""
    assert [fml.harmonic_category(m) for m in (1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 15, 17)] == [
        "fundamental", "even", "zero", "even", "pos_neg", "even", "pos_neg", "zero", "even", "pos_neg", "even",
        "pos_neg", "zero", "pos_neg"]
    assert fml.order_scaling(5, 300.0, 100.0, safety_factor=1.2) == (pytest.approx(3.6), "own voltage")
    assert fml.order_scaling(5, 300.0, 100.0, from_ll=True)[0] == pytest.approx(3.0 / math.sqrt(3))
    assert fml.order_scaling(7, float("nan"), 10.0, f_thd=2.5) == (2.5, "THD")
    assert fml.order_scaling(7, 30.0, 0.5, f_thd=2.5, min_level=1.0) == (2.5, "THD")     # level too small
    assert fml.order_scaling(11, None, 10.0) == (1.0, "no information")
    for m in (2, 3, 4, 6, 9, 10, 15):
        assert fml.order_scaling(m, 100.0, 1.0, f_thd=3.0, safety_factor=2.0) == (1.0, "as measured")


def test_evaluation_scaling_with_the_pq_settings(demo_series, export_10min):
    """Settings from the PQ assessment: every order of the positive or negative sequence with its own quantile
    (k_m = factor·U_95,m/U_m, U_m = level of its natural sequence before/after the fault), the others of them with
    the THD; the zero sequence (3rd harmonic of the demo) and the even orders keep their measured value."""
    from dataclasses import replace
    from groundfault import Intervals, Settings, evaluate, open_recording
    folder, truth = demo_series
    w = truth[0]
    b = w["intervals"]
    rec = open_recording(os.path.join(str(folder), w["file"]))
    a = pq.assess(pq.read(export_10min["path"]), factor=1.4)
    iv = Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]), tuple(b["post_fault"]))
    r = evaluate(rec, iv, replace(Settings(), **a.settings()))
    t = r.tables["harmonic_scaling"].set_index("order")
    v = r.values["voltage"]
    for m in (5, 7, 11, 13):
        i = v["orders"].index(m)
        seq = "U_neg" if m % 3 == 2 else "U_pos"
        level = 0.5 * (v["pre_fault"][seq][i] + v["post_fault"][seq][i])
        assert t.at[m, "U_level_V"] == pytest.approx(level) and t.at[m, "rule"] == "own voltage"
        assert t.at[m, "factor"] == pytest.approx(1.4 * a.u95()[m] / level)
    f_thd = 1.4 * a.thd95() / r.values["UTHD_meas"]
    without = [m for m in t.index if fml.harmonic_category(m) == "pos_neg" and m not in a.u95()]
    assert without and all(t.at[m, "factor"] == pytest.approx(f_thd) for m in without)      # THD for the others
    assert (t.loc[[m for m in t.index if fml.harmonic_category(m) != "pos_neg"], "factor"] == 1.0).all()
    ph = r.values["I_phasors"]
    i_0 = math.sqrt(sum(abs(z) ** 2 for m, z in ph.items() if m >= 3 and m % 3 == 0 and m % 2))
    i_even = math.sqrt(sum(abs(z) ** 2 for m, z in ph.items() if m >= 2 and m % 2 == 0))
    assert r.values["IH_zero"] == pytest.approx(i_0) and r.values["IH_even"] == pytest.approx(i_even)
    s2 = float((t["I_scaled_A"] ** 2).sum())
    assert r.values["IH_scaled"] == pytest.approx(math.sqrt(s2 + r.values["IH_other"] ** 2))
    q = r.table("assessment_quantities")["quantity"].tolist()
    assert q[-7:] == ["UTHD_meas", "UTHD_95", "IH_zero", "IH_even", "IH_other", "IH_scaled", "IRMS_forecast"]
    # the THD alone (no quantiles per order): every order of the positive or negative sequence with the THD factor
    r_thd = evaluate(rec, iv, replace(Settings(), **dict(a.settings(), pq_u95=None)))
    t_thd = r_thd.tables["harmonic_scaling"].set_index("order")
    assert all(t_thd.at[m, "factor"] == pytest.approx(f_thd) for m in (5, 7, 11, 13))
    # the quantiles per order alone (no THD): an order without its own value stays as measured, with a hint
    r_u = evaluate(rec, iv, replace(Settings(), **dict(a.settings(), u_thd95_percent=None)))
    t_u = r_u.tables["harmonic_scaling"].set_index("order")
    assert all(t_u.at[m, "rule"] == "no information" for m in without) and "UTHD_meas" not in set(
        r_u.tables["assessment_quantities"]["quantity"])
    assert any("ohne eigenen Wert" in h for h in r_u.hints)
    with pytest.raises(ValueError, match="pq_u95_reference"):
        Settings(pq_u95_reference="null")
    with pytest.raises(ValueError, match="pq_min_level_V"):
        Settings(pq_min_level_V=-1.0)


@pytest.fixture(scope="module")
def measured(demo_results):
    entries = [dict(file=p, Z=z, name="Z%g" % z) for z, (_, _, p, _) in sorted(demo_results.items())]
    series = equivalent_source.fit_equivalent_source(equivalent_source.load_series(entries))
    return equivalent_source.measured_source(series)


def test_scaling_rules_of_the_model_and_the_remainder(measured):
    """The orders of the model and of the remainder with the same rules: positive/negative sequence with its own
    quantile (the remainder with the levels of its test), otherwise with the THD; zero sequence and even orders as
    measured; without a scaling everything as measured."""
    u95 = {m: 1.5 * F.level_reference for m, F in measured.fits.items() if F.sequence != "zero"}
    for m in (17, 19):                                         # two orders of the remainder with a quantile
        u95[m] = 40.0
    r = equivalent_source.ires_at_impedance(measured, 2.5, u95=u95, thd95_percent=3.0, thd_measured_percent=1.5)
    assert r["factors"][3] == 1.0 and r["rules"][3] == "as measured"              # zero sequence: not scaled
    assert all(r["factors"][m] == pytest.approx(1.5) for m in measured.fits if m != 3)
    t = r["table"]
    rest = t[t["part"] == "remainder"].set_index("order")
    assert set(rest["test"]) == {r["rest_test"]} and r["rest_test"]
    # the levels of the demo's remainder are below 1 V (settings["min_level_V"]): the THD factor instead
    assert rest.loc[[17, 19, 23], "U_level_V"].max() < 1.0 and set(rest.loc[[17, 19, 23], "rule"]) == {"THD"}
    from dataclasses import replace
    low = replace(measured, settings=dict(measured.settings, min_level_V=0.0))
    r = equivalent_source.ires_at_impedance(low, 2.5, u95=u95, thd95_percent=3.0, thd_measured_percent=1.5)
    t = r["table"]
    rest = t[t["part"] == "remainder"].set_index("order")
    for m in (17, 19):
        assert rest.at[m, "rule"] == "own voltage" and rest.at[m, "factor"] == pytest.approx(40.0 / rest.at[m, "U_level_V"])
    assert rest.at[23, "rule"] == "THD" and rest.at[23, "factor"] == pytest.approx(2.0)
    assert (rest.loc[[m for m in rest.index if m % 2 == 0 or m % 3 == 0], "factor"] == 1.0).all()
    assert r["IH_rest_scaled"] == pytest.approx(math.sqrt(float((rest["I_scaled_A"] ** 2).sum()) + r["IH_other"] ** 2))
    assert r["IH_scaled"] == pytest.approx(math.sqrt(float((t["I_scaled_A"] ** 2).sum()) + r["IH_other"] ** 2))
    assert r["IH_zero"] == pytest.approx(math.sqrt(float((t.loc[t["category"] == "zero", "I_A"] ** 2).sum())))
    assert any("Nullsystems [3, 9" in h for h in r["hints"])
    plain = equivalent_source.ires_at_impedance(measured, 2.5)
    assert plain["IH_rest_scaled"] == plain["IH_rest"] and plain["IRES_scaled"] == pytest.approx(plain["IRES"])
    assert set(plain["table"]["rule"]) == {"as measured"} and (plain["table"]["factor"] == 1.0).all()
    with pytest.raises(TypeError):
        equivalent_source.ires_at_impedance(measured, 2.5, rest_scaling="thd")        # no longer an option


def test_ires_over_time(measured):
    """The time series with the same voltage at every time step equals ires_at_impedance; with varying voltages the
    quantile of I_RES lies between the values of the smallest and the largest voltage."""
    u = {m: F.level_reference for m, F in measured.fits.items() if F.sequence != "zero"}
    t = pd.date_range("2026-01-05 00:10", periods=5, freq="10min")
    V = pd.DataFrame({m: [v] * 5 for m, v in u.items()}, index=t)
    ts = equivalent_source.ires_over_time(measured, 2.5, V, safety_factor=1.2)
    one = equivalent_source.ires_at_impedance(measured, 2.5, u95=u, safety_factor=1.2)
    assert (ts["IRES"] - one["IRES_scaled"]).abs().max() < 1e-9 and list(ts.index) == list(t)
    V2 = V * np.array([0.5, 0.8, 1.0, 1.2, 1.5])[:, None]
    ts2 = equivalent_source.ires_over_time(measured, 2.5, V2)
    assert ts2["IRES"].is_monotonic_increasing
    lo = equivalent_source.ires_at_impedance(measured, 2.5, u95={m: 0.5 * v for m, v in u.items()})["IRES_scaled"]
    assert ts2["IRES"].iloc[0] == pytest.approx(lo)
    with pytest.raises(ValueError, match="ires_over_time"):
        equivalent_source.ires_over_time(measured, 2.5, pd.DataFrame({"x": [1.0]}, index=t[:1]))


def test_assessment_scaling_in_ires(measured, export_10min):
    """The keyword arguments of PQAssessment.scaling work in ires_at_impedance and in the figure of I_RES(Z_E)."""
    from groundfault import report
    a = pq.assess(pq.read(export_10min["path"]), factor=1.4)
    sc = a.scaling(thd_measured_percent=2.0)
    r = equivalent_source.ires_at_impedance(measured, 2.5, **sc)
    for m, F in measured.fits.items():
        expected = 1.0 if F.sequence == "zero" else 1.4 * a.u95()[m] / F.level_reference
        assert r["factors"][m] == pytest.approx(expected)
    fig = report.ires_over_ze(measured, 10.0, (), "max", sc)
    assert fig.axes


# ============================================================================================== forecast
def test_forecast_with_the_pq_voltages(demo_results, export_10min):
    """The quantiles as voltages of the forecast, and the 10-min values per phase as a time series."""
    from groundfault import forecast as fc
    model = fc.NetworkModel("demo")
    for z, (res, w, p, _) in sorted(demo_results.items()):
        model.add_test(fc.load_fault_data(p, z))
    a = pq.assess(pq.read(export_10min["path"]), factor=1.2)
    single = model.forecast(a.voltages(), reference="LE")
    series = model.forecast(a.series(), reference="LE")
    assert len(single.currents) == 1 and len(series.currents) == len(a.data.harmonics)
    q = series.quantile(0.95)
    assert q["IH"] <= single.IH.iloc[0] * (1 + 1e-6)          # quantile of I_H(t) ≤ I_H of the quantiles (orders rise together)


# ============================================================================================== figures, texts
@pytest.mark.parametrize("lang", ["en", "de"])
def test_figures(export_10min, lang):
    import matplotlib.pyplot as plt
    from groundfault import report
    a = pq.assess(pq.read(export_10min["path"]), factor=1.4)
    with i18n.language(lang):
        for fig in (report.pq_series(a), report.pq_duration(a, levels={"T1": 200.0}), report.pq_profile(a)):
            assert len(fig.axes) == 1 and fig.axes[0].get_legend() is not None
            plt.close(fig)
        assert report.table_title("pq_scaling") != "pq_scaling"


def test_messages_in_both_languages():
    assert [k for k in i18n.missing_keys("en") + i18n.missing_keys("de") if k.startswith(("pq.", "report.pq"))] == []
    with i18n.language("de"):
        assert i18n.column_label("U_quantile_V") == "U_Quantil_V"


def test_demo_campaign_contains_the_pq_export(tmp_path):
    w = demo.make_campaign(str(tmp_path), layout="de", groundmeas=False)
    assert w["pq"]["file"] == "1_Rohdaten/PQ/UW_PQ_Export.csv"
    path = os.path.join(w["campaign"], w["pq"]["file"])
    a = pq.assess(pq.read(path))
    assert a.u95()[5] == pytest.approx(w["pq"]["quantiles"][0.95][5], rel=1e-4)
    assert pd.Timestamp(a.coverage["start"]) <= pd.Timestamp("2026-01-15 09:00") <= pd.Timestamp(a.coverage["end"])


# ============================================================================================== robustness
def _frame(index, h5=250.0, phases=("L1", "L2", "L3"), h1=11500.0, thd=2.0, extra=None):
    """A PQ table for pq.from_frame: H1 and H5 per phase, THD of the loops."""
    n = len(index)
    cols = {}
    for k, ph in enumerate(phases):
        cols["H1_%s" % ph] = np.full(n, h1)
        cols["H5_%s" % ph] = np.asarray(h5 if np.ndim(h5) else np.full(n, h5), float) * (1.0 + 0.05 * k)
    if thd is not None:
        for loop in ("L12", "L23", "L31"):
            cols["THD_%s" % loop] = np.full(n, thd)
    cols.update(extra or {})
    return pd.DataFrame(cols, index=index)


def test_end_of_daylight_saving_time():
    """A local-clock export across the end of daylight saving time: the repeated hour is told apart by the order of
    the file – no time stamp is lost, the index is monotonic, the 10-min values are formed as usual."""
    wall = pd.date_range("2025-10-26 00:00:30", "2025-10-26 01:59:30", freq="30s")
    repeated = pd.date_range("2025-10-26 02:00:00", "2025-10-26 02:59:30", freq="30s")
    after = pd.date_range("2025-10-26 03:00:00", "2025-10-26 04:00:00", freq="30s")
    idx = wall.append(repeated).append(repeated).append(after)               # the order of the file
    d = pq.from_frame(_frame(idx), interval_s=30.0, timezone="Europe/Berlin")
    assert len(d.harmonics) == len(idx) and d.harmonics.index.is_monotonic_increasing
    assert not d.harmonics.index.duplicated().any() and not any("Zeitumstellung" in h for h in d.hints)
    assert (d.end - d.start) == pd.Timedelta(hours=5)                       # 00:00 CEST … 04:00 CET
    ten = pq.ten_minute_values(d)
    assert len(ten.harmonics) == 30 and ten.meta["aggregation"]["n_incomplete"] == 0


def test_beginning_of_daylight_saving_time_and_fixed_clock():
    """An instrument clock that does not follow daylight saving time has stamps in the skipped hour: with the time
    zone of the place they are left out with a hint, with a fixed offset they are kept."""
    idx = pd.date_range("2026-03-29 01:00", "2026-03-29 04:00", freq="10min")
    d = pq.from_frame(_frame(idx), timezone="Europe/Berlin")
    assert len(d.harmonics) == len(idx) - 6 and any("Etc/GMT-1" in h for h in d.hints)
    fixed = pq.from_frame(_frame(idx), timezone="Etc/GMT-1")
    assert len(fixed.harmonics) == len(idx)


def test_time_window_around_midnight_and_naive_clock():
    """The window of a test on Monday 00:30 ± 1 h reaches into Sunday evening; with a PQ clock without a time zone
    the comparison names it."""
    idx = pd.date_range("2026-01-05 00:10", periods=14 * 144, freq="10min")       # Monday, two weeks
    hours = (idx - pd.Timedelta(minutes=5))
    value = np.where(hours.dayofweek == 6, 100.0, np.where(hours.dayofweek == 0, 200.0, 300.0))
    a = pq.assess(pq.from_frame(_frame(idx, h5=value), timezone="UTC"), factor=1.0)
    t = a.comparability({"Mon": {5: 150.0}}, times={"Mon": pd.Timestamp("2026-01-12 00:30", tz="UTC")})
    row = t.iloc[0]
    # 12 intervals per week whose middle lies within Sunday 23:30 … Monday 01:30 (3 of them on Sunday): the data
    # start on Monday 00:00 (9 of the first window) and end on Monday 00:00 two weeks later (3 of the last): 9+12+3
    assert row["n_window"] == 24 and row["window_min_V"] == pytest.approx(110.0)     # largest phase: L3 × 1.1
    assert row["window_max_V"] == pytest.approx(220.0)
    naive = pq.assess(pq.from_frame(_frame(idx, h5=value)), factor=1.0)
    t2 = naive.comparability({"Mon": {5: 150.0}}, times={"Mon": "2026-01-12 00:30"})
    assert t2.attrs["hints"] and "Zeitzone" in t2.attrs["hints"][0] and t2.attrs["hints"][0] in naive.hints


def test_duration_of_the_rule_is_the_longest_gapless_stretch():
    """Two weeks of values half a year apart: the rule sees the longest gapless stretch (7 days), not the span of the
    calendar or the covered 14 days – shorter than every duration of the rule: not valid."""
    first = pd.date_range("2026-01-05 00:10", periods=7 * 144, freq="10min")
    second = pd.date_range("2026-07-06 00:10", periods=7 * 144, freq="10min")
    a = pq.assess(pq.from_frame(_frame(first.append(second))), factors={300.0: 1.0, 10.0: 1.5})
    assert a.coverage["covered_days"] == pytest.approx(14.0) and a.coverage["span_days"] > 180
    assert a.coverage["gapless_days"] == pytest.approx(7.0) and a.coverage["gapless_start"] == pd.Timestamp("2026-01-05")
    assert math.isnan(a.factor) and not a.valid and any("längste lückenlose Strecke" in h for h in a.hints)
    gap = next(h for h in a.hints if "Lücken" in h)
    assert "1 Lücken" in gap
    # one missing 10-min value in four weeks: strictly not gapless; a tolerated gap keeps the stretch
    idx = pd.date_range("2026-01-05 00:10", periods=28 * 144, freq="10min").delete(14 * 144)
    strict = pq.assess(pq.from_frame(_frame(idx)), factors={20.0: 1.5})
    assert strict.coverage["gapless_days"] == pytest.approx(14.0) and not strict.valid
    tolerant = pq.assess(pq.from_frame(_frame(idx)), factors={20.0: 1.5}, max_gap_minutes=10)
    assert tolerant.coverage["gapless_days"] == pytest.approx(28.0 - 1 / 144) and tolerant.factor == 1.5


def test_gap_of_one_interval_and_empty_columns():
    """One missing 10-min value is a gap of 10 min; a column without values is left out instead of making every
    interval incomplete; a fundamental of one phase only gives a hint."""
    idx = pd.date_range("2026-01-05 00:10", periods=20, freq="10min").delete(5)
    a = pq.assess(pq.from_frame(_frame(idx)))
    assert any("0 days 00:10:00" in h for h in a.hints)
    df = pd.DataFrame({"time": pd.date_range("2026-01-05 00:00:30", periods=40, freq="30s").astype(str),
                       "H1_L1": 11500.0, "H5_L1": 250.0, "H5_L2": np.nan, "H5_L3": 260.0})
    d = pq.from_frame(df)
    assert (5, "L2") not in d.harmonics.columns and any("ohne einen Wert" in h for h in d.hints)
    b = pq.assess(d)
    assert len(b.data.harmonics) == 2 and b.u95()[5] == pytest.approx(260.0)
    assert any("nur die Leiter L1, L3" in h for h in b.hints)


def test_combine_exports_with_different_orders(tmp_path):
    first = pd.date_range("2026-01-05 00:10", periods=12, freq="10min")
    second = pd.date_range("2026-01-05 02:10", periods=12, freq="10min")
    a = pq.from_frame(_frame(first))
    b = pq.from_frame(_frame(second, extra={"H7_L1": np.full(12, 100.0)}))
    both = pq.assess(pq.combine([a, b]))
    assert len(both.data.harmonics) == 24 and both.u95()[7] == pytest.approx(100.0)


def test_interval_from_the_time_stamps():
    """A header interval that does not fit the time stamps gives way to the step of the stamps; one row without an
    interval cannot be aggregated."""
    idx = pd.date_range("2026-01-05 00:10", periods=12, freq="10min")
    d = pq.from_frame(_frame(idx), interval_s=30.0)
    assert d.interval_s == 600.0 and any("Abstand der Zeitstempel" in h for h in d.hints)
    with pytest.raises(ValueError, match="Intervall"):
        pq.from_frame(_frame(idx[:1]))


def test_label_start_gives_end_labels():
    idx = pd.date_range("2026-01-05 00:00", periods=40, freq="30s")            # stamps at the beginning
    d = pq.from_frame(_frame(idx), interval_s=30.0)
    ten = pq.ten_minute_values(d, label="start")
    assert list(ten.harmonics.index) == [pd.Timestamp("2026-01-05 00:10"), pd.Timestamp("2026-01-05 00:20")]
    assert ten.start == pd.Timestamp("2026-01-05 00:00")


def test_earth_faults_are_left_out():
    """10-min intervals with an earth fault (one phase down, two up) do not enter the quantiles."""
    idx = pd.date_range("2026-01-05 00:10", periods=100, freq="10min")
    df = _frame(idx)
    df.loc[idx[40:43], "H1_L3"] = 1000.0
    df.loc[idx[40:43], ["H1_L1", "H1_L2"]] = 19900.0
    df.loc[idx[40:43], ["H5_L1", "H5_L2", "H5_L3"]] = 900.0                 # distorted during the fault
    a = pq.assess(pq.from_frame(df))
    assert len(a.data.harmonics) == 97 and a.coverage["n_excluded"] == 3
    assert a.table().set_index("order").loc[5, "U_max_V"] < 300 and any("Erdschluss" in h for h in a.hints)
    keep = pq.assess(pq.from_frame(df), fault_threshold=None)
    assert len(keep.data.harmonics) == 100 and keep.table().set_index("order").loc[5, "U_max_V"] == 900.0


def test_line_to_line_data():
    """Only line-to-line harmonic voltages: quantiles, test levels and the time series keep the reference "LL"."""
    idx = pd.date_range("2026-01-05 00:10", periods=50, freq="10min")
    a = pq.assess(pq.from_frame(_frame(idx, h5=430.0, phases=("L12", "L23", "L31"), h1=20000.0)))
    assert a.reference == "LL" and a.scaling()["u95_reference"] == "LL"
    assert a.voltages()[5] == pytest.approx(430.0 * 1.1)
    s = a.series()
    assert isinstance(s, pd.DataFrame) and s[5].iloc[0] == pytest.approx(430.0 * 1.1)
    t = a.comparability({"T": {5: 430.0 * 1.1}})
    assert t.iloc[0]["position_in_range"] == "inside" and t.iloc[0]["factor_to_test"] == pytest.approx(1.0)


def test_thd_from_the_orders_and_without_thd():
    """Without the THD of the loops the THD comes from the line-to-earth orders without the zero sequence; without
    any THD the settings do not scale."""
    idx = pd.date_range("2026-01-05 00:10", periods=50, freq="10min")
    df = _frame(idx, thd=None, extra={"H3_L1": np.full(50, 500.0), "H3_L2": np.full(50, 500.0),
                                       "H3_L3": np.full(50, 500.0)})
    a = pq.assess(pq.from_frame(df))
    assert a.thd95() == pytest.approx(100.0 * 250.0 * 1.1 / 11500.0)          # order 5 only, the largest phase
    assert a.thd95_le > a.thd95() and any("ohne das Nullsystem" in h for h in a.hints)
    b = pq.assess(pq.from_frame(_frame(idx, thd=None)).select(end=idx[-1]))
    nothd = pq.from_frame(pd.DataFrame({"H5_L12": np.full(50, 400.0)}, index=idx))
    c = pq.assess(nothd)
    st = c.settings()
    assert st["u_thd95_percent"] is None and any("keinen THD" in h for h in c.hints)
    assert np.isfinite(b.thd95())


def test_select_with_naive_bounds_and_generic_csv(tmp_path):
    idx = pd.date_range("2026-01-05 00:10", periods=50, freq="10min")
    d = pq.from_frame(_frame(idx), timezone="Europe/Berlin")
    part = d.select("2026-01-05 01:00", "2026-01-05 02:00")
    assert len(part.harmonics) == 7
    df = _frame(idx)
    df.index.name = "Zeitpunkt"
    p = tmp_path / "other.csv"
    df.to_csv(p, sep=";", decimal=",")
    g = pq.read(str(p))
    assert g.harmonics[(5, "L1")].iloc[0] == pytest.approx(250.0) and g.interval_s == 600.0


def test_nan_voltages_in_the_scaling(measured):
    """A NaN quantile counts as missing (THD factor or unscaled), a time step without a voltage is left out."""
    u = {m: F.level_reference for m, F in measured.fits.items() if F.sequence != "zero"}
    bad = dict(u)
    bad[5] = float("nan")
    r = equivalent_source.ires_at_impedance(measured, 2.5, u95=bad)
    assert np.isfinite(r["IRES_scaled"]) and r["factors"][5] == 1.0
    t = pd.date_range("2026-01-05 00:10", periods=3, freq="10min")
    V = pd.DataFrame({m: [v, v, v] for m, v in u.items()}, index=t)
    V.iloc[1, 0] = np.nan
    ts = equivalent_source.ires_over_time(measured, 2.5, V)
    assert ts["IRES"].isna().tolist() == [False, True, False]
    assert any("Zeitschritten" in h for h in ts.attrs["hints"])


def test_export_of_the_tables_with_a_time_zone(tmp_path, export_10min):
    """The characteristic values of a measurement with a time zone are written to CSV and the Excel workbook (Excel
    has no time zones: the time stamps as text)."""
    pytest.importorskip("openpyxl")
    from groundfault import report
    a = pq.assess(pq.read(export_10min["path"], timezone="Europe/Berlin"), factor=1.4)
    paths = report.export_tables({"pq_summary": a.summary_table(), "pq_quantiles": a.table()}, str(tmp_path),
                                 prefix="campaign_", formats=("csv", "xlsx"))
    names = sorted(os.path.basename(p) for p in paths)
    assert "campaign_tables.xlsx" in names and "campaign_pq_summary.xlsx" in names
    text = (tmp_path / "campaign_pq_summary.csv").read_text(encoding="utf-8-sig")
    assert "2025-12-15 00:00:00+01:00" in text


def test_window_factors_of_shorter_windows(export_10min):
    """Sub-window analysis: one row per complete window, the ratio quantile(all)/quantile(window) per order and of
    the THD; a window as long as the measurement gives 1; windows with a gap are left out; invalid lengths refused."""
    a = pq.assess(pq.read(export_10min["path"]), factor=1.0)
    w = a.window_factors(days=7)
    span = a.data.span_days
    assert len(w) == int(np.floor(span - 7 + 1e-9)) + 1
    assert list(w.columns[:3]) == ["start", "end", "n_intervals"] and 5 in w.columns and "THD_LL_pct" in w.columns
    assert ((w["end"] - w["start"]) == pd.Timedelta(days=7)).all()
    assert w.attrs["days"] == 7.0 and w.attrs["full"][5] == pytest.approx(a.u95()[5])
    r = w[5]
    assert bool((r > 0.5).all() and (r < 2.0).all())
    one = a.window_factors(days=span, step_days=1.0)
    assert len(one) == 1 and one[5].iloc[0] == pytest.approx(1.0)
    assert a.window_factors(days=span + 1).empty
    gap = pq.assess(a.data.select(end=a.data.start + pd.Timedelta(days=10)), factor=1.0)
    assert len(gap.window_factors(days=7, step_days=0.5)) == 7
    for bad in (0, -1.0, float("nan"), "x"):
        with pytest.raises(ValueError):
            a.window_factors(days=bad)
    with pytest.raises(ValueError):
        a.window_factors(days=7, step_days=0)


def test_short_earth_fault_in_the_values_of_the_export_is_left_out():
    """An earth fault of 30 s hardly changes the 10-min value of the fundamental (one phase 1 % lower) but it
    distorts the 10-min harmonic value: with 30-s values in the export the criterion of the fundamental is applied to
    them as well – the 10-min interval that contains the fault is left out, with a hint naming the 30-s value."""
    idx = pd.date_range("2026-01-05 00:00:30", periods=6 * 20, freq="30s")        # one hour, end-labelled stamps
    df = _frame(idx)
    t = idx[45]                                                                    # in the 10-min interval 00:30
    df.loc[t, "H1_L3"] = 2000.0
    df.loc[t, ["H1_L1", "H1_L2"]] = 19900.0
    df.loc[t, ["H5_L1", "H5_L2", "H5_L3"]] = 3000.0
    d = pq.from_frame(df, interval_s=30.0)
    ten = pq.ten_minute_values(d).harmonics
    u1 = ten[[(1, p) for p in ("L1", "L2", "L3")]]
    assert (u1.min(axis=1) / u1.max(axis=1)).min() > 0.8                          # the 10-min value does not show it
    a = pq.assess(d)
    assert a.coverage["n_excluded"] == 1 and pd.Timestamp("2026-01-05 00:30") not in a.data.harmonics.index
    assert a.table().set_index("order").loc[5, "U_max_V"] < 300
    assert any("30-s-Werten" in h and str(t) in h for h in a.hints)
    keep = pq.assess(d, fault_threshold=None)
    assert keep.coverage["n_excluded"] == 0 and keep.table().set_index("order").loc[5, "U_max_V"] > 600
    ten_min = pq.assess(pq.from_frame(ten), fault_threshold=0.8)                  # 10-min values only: not visible
    assert ten_min.coverage["n_excluded"] == 0


def test_measuring_periods_with_their_quantiles(tmp_path):
    """Three exports weeks apart are three measuring periods: per period the quantile with the definition of the
    assessment (largest phase per interval), the whole measurement over all of them, a hint with the quantile of the
    dominant order per period; a gap shorter than a day stays inside a period."""
    starts = [pd.Timestamp("2026-03-02 00:10"), pd.Timestamp("2026-06-01 00:10"), pd.Timestamp("2026-09-07 00:10")]
    levels = [200.0, 250.0, 300.0]
    parts = [pq.from_frame(_frame(pd.date_range(s, periods=7 * 144, freq="10min"), h5=v))
             for s, v in zip(starts, levels)]
    a = pq.assess(pq.combine(parts), factors={30.0: 1.2, 5.0: 1.5})
    p = a.periods()
    assert len(p) == 3 and list(p["days"].round(6)) == [7.0, 7.0, 7.0] and list(p["n_intervals"]) == [1008] * 3
    assert list(p[5]) == pytest.approx([v * 1.1 for v in levels])                 # largest phase: L3 × 1.1
    assert p.attrs["whole"][5] == pytest.approx(a.u95()[5]) and p.attrs["quantile"] == 0.95
    assert p["start"].iloc[1] == pd.Timestamp("2026-06-01 00:00") and p["end"].iloc[0] == starts[0] + pd.Timedelta(days=7) - pd.Timedelta(minutes=10)
    assert len(a.coverage["periods"]) == 3 and a.factor == 1.5                     # 7 days gapless: the rule ≥ 5 days
    hint = next(h for h in a.hints if "Messabschnitte" in h)
    assert hint.startswith("3 Messabschnitte") and "220,0 / 275,0 / 330,0 V" in hint
    # a gap of 12 h does not split, one of 1 day does
    idx = pd.date_range("2026-01-05 00:10", periods=10 * 144, freq="10min")
    short = idx.delete(range(3 * 144, 3 * 144 + 72))
    assert len(pq.from_frame(_frame(short)).periods()) == 1
    long_ = idx.delete(range(3 * 144, 4 * 144 + 1))
    assert len(pq.from_frame(_frame(long_)).periods()) == 2
    assert len(pq.from_frame(_frame(long_)).periods(min_gap_days=2.0)) == 1
    one = pq.assess(pq.from_frame(_frame(idx)), factor=1.0)
    assert len(one.periods()) == 1 and not any("Messabschnitte" in h for h in one.hints)
    for bad in (0, -1.0, float("nan"), "x", True):
        with pytest.raises(ValueError):
            pq.from_frame(_frame(idx)).periods(min_gap_days=bad)


def test_series_figure_has_no_line_across_a_gap():
    import matplotlib.pyplot as plt
    from groundfault import report
    first = pd.date_range("2026-01-05 00:10", periods=144, freq="10min")
    second = pd.date_range("2026-03-02 00:10", periods=144, freq="10min")
    a = pq.assess(pq.from_frame(_frame(first.append(second))), factor=1.0)
    fig = report.pq_series(a, orders=[5])
    y = fig.axes[0].lines[0].get_ydata()
    assert np.isnan(np.asarray(y, float)).sum() == 1 and len(y) == 289
    plt.close(fig)


# ============================================================================================== LEM Memobox (CODAM)
def _pql(path, rows, interval=600, pow_sys=1, nominal=2000000, extra_row=None):
    """A small PQL file of the CODAM software (structure of a real file, invented values): per row the time stamp
    and per phase the fundamental and the harmonic voltages 1 … 5 (V); returns the path."""
    title = ["Nr", "Status", "DateTime", "Freq10min"]
    for x in range(3):
        title += ["VoltMaxPhaseLxRawVal%d" % x, "VoltUh1AvgPhaseLxRawVal%d" % x, "VoltTHDMaxPhaseLxRawVal%d" % x]
        title += ["VoltHarmPhaseLxRawVal%d_%d" % (x, k) for k in range(5)]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<Codam>", "<Version>1.0.2</Version>",
             "<MemoboxConfiguration>", "<t>HardwType=TEST 50Hz</t>", "<t>SerialNr=0000</t>", "</MemoboxConfiguration>",
             "<MemoboxJob>", "<t>JobText1=Busbar A / transformer 1</t>", "<t>Interval=%d</t>" % interval,
             "<t>VoltPowSysType=%d</t>" % pow_sys, "<t>NomVoltRawVal=%d</t>" % nominal,
             "<t>MeasStartMeasured=2026-1-5 12:0:0.0</t>", "<t>MeasStopMeasured=2026-1-6 0:0:0.0</t>",
             "</MemoboxJob>", "<MemoboxIntervals>", "<Title>," + ",".join(title) + "</Title>",
             "<Unit>,(not implemented),</Unit>", "<Scale>,(not implemented),</Scale>"]
    for i, (stamp, u1, h5) in enumerate(rows):
        vals = [str(i), "8192", stamp, "5000"]
        for x in range(3):
            vals += ["14800", str(u1), "400", str(u1), "0", "10", "0", str(h5 + 10 * x)]
        lines.append("<i>," + ",".join(vals) + "</i>")
    if extra_row:
        lines.append(extra_row)
    lines += ["</MemoboxIntervals>", "</Codam>"]
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    return path


def test_read_pql_of_a_lem_memobox(tmp_path):
    """read_pql: line-to-line voltages of a three-wire job, order k + 1 from column _k, time stamps at the end of the
    intervals, THD from the harmonics; read() recognises the file; a row with too many values is skipped."""
    stamps = ["2026-1-5 12:10:0.0", "2026-1-5 12:20:0.0", "2026-1-5 12:30:0.0"]
    p = _pql(str(tmp_path / "busbar.PQL"), [(s, 20000, 300 + 100 * i) for i, s in enumerate(stamps)],
             extra_row="<i>,9,8192,2026-1-5 12:40:0.0,1,2,3</i>")
    d = pq.read_pql(p)
    assert d.reference == "LL" and d.phases == ["L12", "L23", "L31"] and d.orders == [1, 2, 3, 4, 5]
    assert d.interval_s == 600.0 and str(d.start) == "2026-01-05 12:00:00" and str(d.end) == "2026-01-05 12:30:00"
    assert list(d.harmonics[(5, "L23")]) == [310.0, 410.0, 510.0]
    assert d.thd["L12"].iloc[0] == pytest.approx(100 * math.hypot(10, 300) / 20000)
    assert d.meta["instrument"] == "LEM Memobox TEST 50Hz" and d.meta["measurement"] == "Busbar A / transformer 1"
    assert any("1 rows with a wrong number" in h or "1 Zeilen" in h for h in d.hints)
    assert any("10 V (0.05 %" in h or "10 V (0,05 %" in h for h in d.hints)     # harmonic voltages in 10-V steps
    assert pq.read(p).harmonics.equals(d.harmonics)
    le = pq.read_pql(_pql(str(tmp_path / "wye.PQL"), [(stamps[0], 11547, 200)], pow_sys=0))
    assert le.reference == "LE" and le.phases == ["L1", "L2", "L3"]
    assert pq.read_pql(p, reference="LE").phases == ["L1", "L2", "L3"]
    scaled = pq.read_pql(_pql(str(tmp_path / "raw.PQL"), [(stamps[0], 200, 3)]))        # raw values in 100 V
    assert scaled.harmonics[(1, "L12")].iloc[0] == pytest.approx(20000.0)
    with pytest.raises(ValueError):
        pq.read_pql(str(tmp_path / "busbar.PQL"), reference="XY")
    (tmp_path / "empty.PQL").write_text("<Codam><MemoboxJob></MemoboxJob></Codam>", encoding="utf-8")
    with pytest.raises(ValueError):
        pq.read_pql(str(tmp_path / "empty.PQL"))


def test_thd_only_export_and_quoted_columns(tmp_path):
    """An export with THD columns only (names in quotes) cannot scale the orders: a clear message."""
    p = tmp_path / "thd.csv"
    p.write_text("Messdaten Export PQ-Box 50,,Seriennummer: 0000\n\nIntervall: 30 sec\n\n"
                 "Datum,Zeit,'THD12_[%]','THD23_[%]','THD31_[%]'\n"
                 "05.01.2026,12:00:30.000,2.1,2.2,2.3\n05.01.2026,12:01:00.000,2.0,2.1,2.2\n", encoding="utf-8")
    assert pq.parse_column("'THD12_[%]'") == ("thd", None, "L12", "value", "%")
    with i18n.language("en"):
        with pytest.raises(ValueError, match="only THD values"):
            pq.read(str(p))
