# -*- coding: utf-8 -*-
"""Signal explorer, figures of the station and of the earthing comparison, RMS comparison and raw-data diagnostics.

The explorer computes the same values as the evaluation; a second method (FFT over whole cycles with a rectangular
window) checks RMS value, harmonics, THD and DC component. Further: event times, the HTML export (data,
reconstruction of the stored instantaneous values, keys shared by Python and the page script), the figure functions
and the messages in English.
"""
import base64
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from groundfault import (Intervals, Settings, demo, diagnostics, evaluate, explorer, i18n, interactive, open_recording,
                         report, rms, write_comtrade)


@pytest.fixture(scope="module")
def station(tmp_path_factory):
    p = str(tmp_path_factory.mktemp("ex") / "st.cfg")
    w = demo.make_station_recording(p, duration=6.0, t_on=1.5, t_off=4.5, background={1: demo.polar(8, 70)})
    rec = open_recording(p)
    # the explorer shows the raw signals (mean per window, no high-pass): compared with an evaluation without it
    res = evaluate(rec, Intervals(*[tuple(w["intervals"][k]) for k in ("steady_state", "pre_fault", "post_fault")]),
                   Settings(dc="mean"))
    return w, rec, res


def _voltages_delayed(rec, path, delay_s):
    """Copy of ``rec`` with the line-to-earth voltages recorded ``delay_s`` later (subsystems not synchronous)."""
    x = rec.read(0, rec.n); n = int(delay_s * rec.fs)
    sig = {nm: (unit, np.roll(x[:, j], n) if nm.split("_")[-1].startswith("V") else x[:, j])
           for j, (nm, unit) in enumerate(zip(rec.channel_names, rec.units))}
    write_comtrade(path, sig, rec.fs)
    return open_recording(path), n


def test_max_window_matches_evaluation(station):
    """Explorer and evaluation use the same functions: identical values in the max window (evaluation with the mean
    per window and without the high-pass, as the explorer computes)."""
    w, rec, res = station
    ex = explorer.explorer(rec, res)
    a, b = ex.times["max window"]
    all_ = [k.index for k in res.roles.channels]
    tab = ex.table(a, b, all_)
    st, wi = res.steady_state, res.max_index
    for j, k in enumerate(res.roles.channels):
        assert tab.loc[j, "rms"] == pytest.approx(st.rms[wi, k.index], rel=1e-9)
        for m in (1, 5, 7):
            assert tab.loc[j, "H%d" % m] == pytest.approx(abs(st.X[wi, k.index, st.ix(m)]), rel=1e-9, abs=1e-9)
    # overview: the window that coincides with the max window gives the same RMS value
    kw = ex.kw
    i = int(np.argmin(np.abs(kw.t - res.t_max_window)))
    if abs(kw.t[i] - res.t_max_window) < 1e-9:
        k = res.roles.main("i_res").index
        assert kw.rms[i, kw.column(k)] == pytest.approx(st.rms[wi, k], rel=1e-9)


def test_characteristic_values_second_method(tmp_path):
    """Known signal (DC component + 1st/5th/7th harmonic): explorer (Hann, DFT at m·f1) against an FFT over exactly
    10 cycles with a rectangular window (integer bins) and against the target values."""
    fs, f1, n = 10000.0, 50.0, 30000
    t = np.arange(n) / fs
    target = {1: (10.0, 0.0), 5: (3.0, 0.3), 7: (1.0, -1.0)}
    x = 0.5 + sum(math.sqrt(2) * A * np.cos(2 * np.pi * m * f1 * t + ph) for m, (A, ph) in target.items())
    p = str(tmp_path / "sig.cfg")
    write_comtrade(p, {"DANEO 1_Ströme_IF Inst": ("A", x)}, fs)
    rec = open_recording(p)
    tab = explorer.excerpt_table(rec, [0], 1.0, 1.2, f1)
    # second method
    seg = rec.read(int(1.0 * fs), int(1.2 * fs), [0])[:, 0]
    X = np.fft.rfft(seg) / len(seg) * math.sqrt(2)                # RMS values; bin m·10 = m-th harmonic
    fft = {m: abs(X[10 * m]) for m in (1, 3, 5, 7)}
    rms_value = math.sqrt(np.mean((seg - seg.mean()) ** 2))
    r = tab.iloc[0]
    assert r["H1"] == pytest.approx(fft[1], rel=1e-3) and r["H1"] == pytest.approx(10.0, rel=1e-3)
    assert r["H5"] == pytest.approx(fft[5], rel=1e-3) and r["H7"] == pytest.approx(fft[7], rel=2e-3)
    assert r["H3"] < 2e-3
    assert r["rms"] == pytest.approx(rms_value, rel=1e-3) and r["rms"] == pytest.approx(math.sqrt(110), rel=1e-3)
    assert r["THD_pct"] == pytest.approx(100 * math.sqrt(10) / 10, rel=2e-3)
    assert r["dc"] == pytest.approx(0.5, abs=2e-3)
    sp = explorer.excerpt_spectrum(rec, [0], 1.0, 1.2, f1).set_index("order")
    # angles referred to H1 (φ_m − m·φ_1): target 0.3 rad and −1 rad
    assert sp.at[5, "angle_deg"] == pytest.approx(math.degrees(0.3), abs=0.2)
    assert sp.at[7, "angle_deg"] == pytest.approx(math.degrees(-1.0), abs=0.2)
    kw = explorer.window_metrics(rec, None, 0.2, 0.2, range(1, 14), f1)
    i = int(np.argmin(np.abs(kw.t - 1.1)))
    assert kw.H(5)[i, 0] == pytest.approx(3.0, rel=1e-3) and kw.thd[i, 0] == pytest.approx(math.sqrt(10) / 10, rel=2e-3)
    assert kw.dc[i, 0] == pytest.approx(0.5, abs=2e-3)


def test_event_times(station):
    w, rec, res = station
    z = explorer.event_times(rec, res.roles, res)
    assert list(z) == ["pre-fault", "fault inception", "max window", "fault clearance", "post-fault"]
    assert z["fault inception"][0] < 1.5 < z["fault inception"][1]
    assert z["fault clearance"][0] < 4.5 < z["fault clearance"][1]
    T = res.settings.T_win
    assert z["max window"] == pytest.approx((res.t_max_window - T / 2, res.t_max_window + T / 2))
    assert z["pre-fault"][1] < 1.5 and z["post-fault"][0] > 4.5


def test_min_max_decimation_keeps_peaks():
    t = np.linspace(0, 1, 100001)
    x = np.sin(2 * np.pi * 50 * t)[:, None] * np.array([1.0, 2.0])[None, :]
    x[54321, 1] = 9.0
    tt, xx = explorer._min_max_decimate(t, x, 2000)
    assert len(tt) <= 2000 and xx[:, 1].max() == 9.0 and xx[:, 0].min() == pytest.approx(-1.0, abs=1e-3)


def _data(path):
    s = Path(path).read_text(encoding="utf-8")
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', s, flags=re.S)
    return json.loads(m.group(1).replace("<\\/", "</")), s


def test_html_export(station, tmp_path):
    w, rec, res = station
    fig = interactive.station_frequency(res)
    p = explorer.explorer_html(rec, str(tmp_path / "x.html"), res, plotly_js="cdn", n_uniform=6,
                               figures={"Station frequency-selective": fig})
    D, html = _data(p)
    assert "cdn.plot.ly" in html and len(D["channels"]) == len(rec.channel_names)
    keys = [a["key"] for a in D["excerpts"]]
    assert {"fault inception", "fault clearance", "max window"} <= set(keys) and len(keys) >= 9
    assert D["figures"][0]["title"] == "Station frequency-selective" and D["figures"][0]["fig"]["data"]
    # reconstruct the stored instantaneous values (int16 + scale) and compare them with the file (fs ≤ 10 kHz: 1:1)
    a = D["excerpts"][keys.index("max window")]
    k = D["channels"][0]
    d = a["data"][k["column"]]
    q = np.frombuffer(base64.b64decode(d["b64"]), dtype="<i2").astype(float) * d["scale"] + d["middle"]
    i0 = int(round(a["t0"] * rec.fs))
    x = rec.read(i0, i0 + a["n"], [k["i"]])[:, 0]
    assert np.max(np.abs(q - x)) <= 1.01 * d["scale"]
    # overview: RMS value of the main channel during the fault as in the evaluation (window in the middle of the fault)
    ires = res.roles.main("i_res")
    col = next(c["column"] for c in D["channels"] if c["i"] == ires.index)
    tt = np.array(D["overview"]["t"]); r = np.array(D["overview"]["rms"][col], float)
    assert np.nanmax(r[(tt > 2.5) & (tt < 4.0)]) == pytest.approx(res.values["IRES"], rel=0.02)
    # texts in the output language (German in the test suite), all placeholders filled
    labels = dict((a["key"], a["label"]) for a in D["excerpts"] if a["key"])
    assert labels == {"pre-fault": "vor dem Fehler", "fault inception": "Fehlereintritt",
                      "max window": "Max-Fenster (Auswertung)", "fault clearance": "Fehlerende",
                      "post-fault": "nach dem Fehler"}
    assert "t = 0,5 s" in [a["label"] for a in D["excerpts"] if not a["key"]]
    assert all(a["important"] == bool(a["key"]) for a in D["excerpts"])
    assert '<html lang="de">' in html and ">alle</button>" in html and ">Effektivwert über der Zeit<" in html
    assert "@@" not in html and not re.search(r"__(TITLE|LANG|PLOTLY|DATA)__", html)
    assert D["text"]["table_head"][:2] == ["Kanal", "Größe"] and D["locale"] == "de-DE" and D["separators"] == ",."


def test_html_script_reads_written_keys(station, tmp_path):
    """The page script reads only keys that Python writes (page data, texts, channels, excerpts, spectra, overview,
    envelope, figures) – both sides must be renamed together."""
    w, rec, res = station
    D, html = _data(explorer.explorer_html(rec, str(tmp_path / "k.html"), res, plotly_js="cdn", n_uniform=2,
                                           figures={"figure": interactive.station_frequency(res)}))
    script = html[html.rindex("<script>"):]
    excerpt = D["excerpts"][0]
    written = {"D": D, "X": D["text"], "k": D["channels"][0], "ks[0]": D["channels"][0], "kk[0]": D["channels"][0],
               "a": excerpt, "S": excerpt["spectrum"], "enc": excerpt["data"][0], "O": D["overview"],
               "E": D["envelope"], "f": D["figures"][0]}
    for var, keys in written.items():
        read = set(re.findall(r"(?<![\w.\]])%s\.([A-Za-z_]\w*)" % re.escape(var), script))
        assert read and read <= set(keys), (var, read - set(keys))


def test_notebook_interface(station):
    pytest.importorskip("ipywidgets")
    w, rec, res = station
    ex = explorer.explorer(rec, res)
    ui = ex.ui()
    assert ui.children and "SignalExplorer" in repr(ex)
    a, b = ex.times["fault inception"]
    assert len(ex.instantaneous(a, b).data) == len(ex.defaults)
    assert len(ex.spectrum(a, b, relative=True).data) == len(ex.defaults)
    # common time axis: all traces of the overview on xaxis "x" (hover label across all panels)
    f = ex.overview()
    assert {trace.xaxis or "x" for trace in f.data} == {"x"} and f.layout.hoversubplots == "axis"
    # jump list with display names; the max window is selected exactly (same values as the evaluation), the other
    # events with the chosen width around their centre
    w_jump, w_width = ui.children[0].children[1].children[:2]
    w_time = ui.children[3]
    assert ("Max-Fenster (Auswertung)", "max window") in w_jump.options and w_width.label == "10 Perioden (0,2 s)"
    w_width.value = 1.0
    w_jump.value = "max window"
    t0, t1 = ex.times["max window"]
    assert w_time.value == pytest.approx((round(t0, 3), round(t1, 3)))
    w_jump.value = "fault inception"
    m = 0.5 * sum(ex.times["fault inception"])
    assert w_time.value == pytest.approx((round(m - 0.5, 3), round(m + 0.5, 3)))
    with i18n.language("en"):
        w_jump = ex.ui().children[0].children[1].children[0]
    assert w_jump.description == "Time" and ("max window (evaluation)", "max window") in w_jump.options


def _sf():
    z = []
    for channel, role, a, factor in (("UE100", "u_e", 100.0, 1.0), ("UE1", "u_t", 1.0, 0.8), ("UEr", "u_e", np.nan, 0.9)):
        for m in (1, 5, 7):
            Z = factor * 0.05 * m ** 0.5
            z.append(dict(channel=channel, role=role, distance_m=a, order=m, f_Hz=50.0 * m, I_F_A=20.0 / m,
                          U_during_fault_V=1.1 * Z * 20 / m, U_background_V=0.2 * Z * 20 / m, U_fault_V=Z * 20 / m,
                          Z_direct_Ohm=1.1 * Z, Z_inception_Ohm=0.98 * Z, Z_clearance_Ohm=1.02 * Z, Z_voltage_Ohm=np.nan,
                          Z_fault_Ohm=Z, Z_fault_angle_deg=30.0, Z_direct_angle_deg=25.0,
                          method_spread_pct=4.0 if m != 7 else 35.0, uncertain=m == 7))
    return pd.DataFrame(z)


def test_station_and_comparison_figures():
    from types import SimpleNamespace
    sf = _sf()
    e = SimpleNamespace(tables={"station_frequency": sf}, name="Test")
    f = report.station_frequency(e); assert len(f.axes) == 1
    f = report.station_background(e); assert len(f.axes) == 3
    inj = pd.DataFrame([dict(source="injection test", measurement_id=2, date="2026-01-10", quantity=g, distance_m=a,
                             f_Hz=50.0 * m, Z_Ohm=0.2 * m ** 0.5 * (0.6 if a == 1 else 1.0), angle_deg=40.0)
                        for m in (1, 3, 5, 7) for g, a in (("earth_potential_rise", 100.0), ("touch_voltage", 1.0))])
    from groundfault import earthing
    long_df, rat = earthing.compare(sf, inj, measurement="Test")
    assert set(rat["distance_match"]) == {"equal", "touch", "unknown", "maximum"}
    mx = rat[rat["channel"] == "max(UE)"].set_index("order")             # probe maximum = UE100 (highest voltage)
    assert set(mx["probe"]) == {"UE100"} and set(mx["distance_match"]) == {"maximum"}
    ue100 = rat[rat["channel"] == "UE100"].set_index("order")
    assert (mx["ratio_fault"] - ue100["ratio_fault"]).abs().max() < 1e-12
    f = report.earthing_comparison(long_df, rat); assert len(f.axes) == 3
    assert any("unsicher" in t.get_text() for ax in f.axes if ax.get_legend() for t in ax.get_legend().get_texts())
    fi = interactive.earthing_comparison(long_df, rat); assert len(fi.data) >= 7
    fs = interactive.station_frequency(e); assert len(fs.data) == 3 * 5
    # uncertain values (here 350 Hz) as ⊗, with a warning on hover; the ratio takes over the marking
    sym = list(fs.data[0].marker.symbol)
    assert sym == ["circle", "circle", "circle-x-open"] and "unsicher" in fs.data[0].hovertext[2]
    assert set(rat.loc[rat["order"] == 7, "uncertain"]) == {True} and not rat.loc[rat["order"] == 1, "uncertain"].any()
    leg = report.station_frequency(e).axes[0].get_legend()
    assert any("unsicher" in t.get_text() for t in leg.get_texts())
    # first point uncertain: the legend still shows the normal symbol (own entry, trace without legend)
    sf2 = sf.copy(); sf2.loc[0, "uncertain"] = True
    fs2 = interactive.station_frequency(SimpleNamespace(tables={"station_frequency": sf2}, name="Test"))
    entries = [t for t in fs2.data if t.legendgroup == "UE100" and t.showlegend is not False and t.name.startswith("UE100")]
    assert len(entries) == 1 and entries[0].x[0] is None and entries[0].marker.symbol in (None, "circle")
    with pytest.raises(ValueError):
        report.station_frequency(SimpleNamespace(tables={}, name="x"))


def test_long_excerpts_save_memory(station):
    """Long excerpts: phasors computed block by block equal those computed in one piece; instantaneous values are
    condensed for the display and keep their peaks."""
    from groundfault import dsp
    fs, n = 40000.0, 600000
    t = np.arange(n) / fs
    x = 3 + 10 * np.cos(2 * np.pi * 49.97 * t + 0.4) + 2 * np.cos(2 * np.pi * 5 * 49.97 * t - 1.0)
    f = 49.97 * np.array([1.0, 3.0, 5.0, 7.0])
    assert np.allclose(explorer._phasors(x, fs, f), dsp.window_phasors(x, fs, f)[0], rtol=1e-9, atol=1e-9)
    w, rec, res = station
    tt, X, condensed = explorer._read_instantaneous(rec, [0, 6], 0.0, rec.duration_s, 2000, block=8192)
    full = rec.read(0, rec.n, [0, 6])
    assert condensed and len(tt) <= 2002
    assert np.nanmax(X[:, 1]) == pytest.approx(np.nanmax(full[:, 1])) and np.nanmin(X[:, 0]) == pytest.approx(
        np.nanmin(full[:, 0]))
    tab = explorer.excerpt_table(rec, [6], 0.0, rec.duration_s, 50.0)
    assert "mittleren" in tab.attrs["note"] or rec.duration_s <= explorer.MAX_SPECTRUM_S


def test_explorer_with_alignment(tmp_path):
    """Voltages recorded 0.5 s later (subsystems): with the alignment of the evaluation the explorer shows the same
    values in the max window – for the shifted channels, too."""
    p = str(tmp_path / "s.cfg")
    w = demo.make_station_recording(p, duration=6.0, t_on=1.5, t_off=4.5)
    rec2, n = _voltages_delayed(open_recording(p), str(tmp_path / "offset.cfg"), 0.5)
    out = dict(roles=["u_l1e", "u_l2e", "u_l3e"], dt_s=0.5)
    res = evaluate(rec2, Intervals(*[tuple(w["intervals"][k]) for k in ("steady_state", "pre_fault", "post_fault")]),
                   Settings(dc="mean"), alignment=out)
    ex = explorer.explorer(rec2, res)                      # alignment taken from the result
    assert ex.shift and set(ex.shift.values()) == {n}
    chan = [k.index for k in res.roles.with_role("u_l1e") + res.roles.with_role("i_res")]
    tab = ex.table(*ex.times["max window"], chan)
    st, wi = res.steady_state, res.max_index
    for j, k in enumerate(chan):
        assert tab.loc[j, "H1"] == pytest.approx(abs(st.X[wi, k, st.ix(1)]), rel=1e-9)
    # with the default high-pass of the evaluation the harmonics agree as well (the high-pass leaves them unchanged)
    hp = evaluate(rec2, Intervals(*[tuple(w["intervals"][k]) for k in ("steady_state", "pre_fault", "post_fault")]),
                  alignment=out)
    for j, k in enumerate(chan):
        assert tab.loc[j, "H1"] == pytest.approx(abs(hp.steady_state.X[hp.max_index, k, hp.steady_state.ix(1)]),
                                                 rel=1e-5)


def test_event_times_with_alignment(tmp_path):
    """If the channels are aligned in time (here by 0.6 s), the explorer jumps – like the station evaluation – to the
    aligned fault inception and clearance (the ★ excerpts of the HTML page use the same times)."""
    p = str(tmp_path / "a.cfg")
    demo.make_station_recording(p, duration=6.4, t_on=1.6, t_off=5.0, background={1: demo.polar(8, 70)})
    rec = open_recording(p)
    out = dict(channels=rec.channel_names, dt_s=0.6)
    res = evaluate(rec, Intervals((1.5, 4.0), (0.2, 0.8), (4.8, 5.7)), alignment=out)
    ex = explorer.explorer(rec, res, alignment=out)
    sf = res.values["station_frequency"]
    assert sf["t_fault_inception_s"] == pytest.approx(1.0, abs=0.05)
    for name, t in (("fault inception", sf["t_fault_inception_s"]), ("fault clearance", sf["t_fault_clearance_s"])):
        a, b = ex.times[name]
        assert a < t < b, name


def test_explorer_in_english(station, tmp_path):
    """English output: figure titles and number format, notes on the excerpt and the texts of the HTML page."""
    w, rec, res = station
    ex = explorer.explorer(rec, res)
    a, b = ex.times["fault inception"]
    assert ex.overview().layout.title.text.startswith("Effektivwert je 200-ms-Fenster")
    with i18n.language("en"):
        assert ex.overview().layout.title.text.startswith("RMS value per 200 ms window (hover: harmonics")
        fig = ex.instantaneous(a, b)
        assert fig.layout.title.text.startswith("Instantaneous values %.3f … " % a) and fig.layout.separators == ".,"
        assert fig.layout.xaxis.title.text == "t in s" and fig.layout.yaxis.title.text in ("u in V", "i in A")
        spec = ex.spectrum(a, b, relative=True)
        assert spec.layout.title.text.startswith("Spectrum ") and "(Hann, f1 = 49.98" in spec.layout.title.text
        assert "% of H1 · angle" in spec.data[0].hovertemplate and spec.layout.yaxis.title.text == "Share of H1 in %"
        tab = explorer.excerpt_table(rec, [6], 1.0, 1.01, 50.0)
        assert tab.attrs["note"] == "Excerpt < 2 cycles – spectrum over 10 cycles around the centre"
        p = explorer.explorer_html(rec, str(tmp_path / "en.html"), res, plotly_js="cdn", n_uniform=6)
    D, html = _data(p)
    labels = dict((a["key"], a["label"]) for a in D["excerpts"] if a["key"])
    assert labels["max window"] == "max window (evaluation)" and labels["pre-fault"] == "before the fault"
    assert "t = 0.5 s" in [a["label"] for a in D["excerpts"] if not a["key"]]
    assert '<html lang="en">' in html and ">all</button>" in html and ">RMS value over time<" in html
    assert "Created " in html and "(package <code>groundfault</code>)" in html and D["title"] == "Signal explorer – st.cfg"
    assert D["text"]["table_head"][:3] == ["Channel", "Quantity", "Unit"] and D["locale"] == "en-GB"
    assert D["text"]["excerpt_title"] == "Instantaneous values in the excerpt “{name}” ({t0} … {t1} s)"
    assert D["separators"] == ".,"


def test_rms_messages_in_english(tmp_path):
    """Notes of the comparison with the recorder's RMS values and errors of the V curve in English (the German notes
    are checked in test_report.py)."""
    fs, T = 10000.0, 3.0
    t = np.arange(int(fs * T)) / fs
    sine = math.sqrt(2) * 10.0 * np.cos(2 * np.pi * 50.0 * t)                  # 10 A RMS
    write_comtrade(str(tmp_path / "inst.cfg"), {"DANEO 1_Ströme_IA Inst": ("A", sine + 8.0),   # 8 A DC (clamp)
                                                "DANEO 1_Ströme_IB Inst": ("A", sine)}, fs)
    n = int(T * 10)
    write_comtrade(str(tmp_path / "rms.cfg"), {"DANEO 1_Ströme_IA RMS": ("A", np.full(n, math.hypot(10.0, 8.0))),
                                               "DANEO 1_Ströme_IB RMS": ("A", np.full(n, 100.0))}, 10.0)
    write_comtrade(str(tmp_path / "other.cfg"), {"DANEO 1_Ströme_IX RMS": ("A", np.full(n, 1.0))}, 10.0)
    inst = open_recording(str(tmp_path / "inst.cfg"))
    IL = np.linspace(580, 620, 81)                                   # resonance at 650 A, outside the points
    ires = np.sqrt(13.0 ** 2 + (IL - 650.0) ** 2)
    assert rms.v_curve(np.linspace(0, 8, IL.size), ires, i_coil=IL).note.startswith("Scheitel außerhalb")
    with i18n.language("en"):
        v = rms.compare_with_instantaneous(inst, open_recording(str(tmp_path / "rms.cfg")), (0.5, 2.5))
        v = v.set_index("channel")
        assert v.at["IA", "note"].startswith("The device includes the DC component (RMS incl. DC deviates by only")
        assert v.at["IB", "note"] == "Scaling of the RMS file? Factor ≈ 10"
        with pytest.raises(ValueError, match="No common channels"):
            rms.compare_with_instantaneous(inst, open_recording(str(tmp_path / "other.cfg")))
        with pytest.raises(ValueError, match="Too few points for the resonance curve"):
            rms.v_curve(np.arange(4.0), np.ones(4))
        vc = rms.v_curve(np.linspace(0, 8, IL.size), ires, i_coil=IL)
    assert vc.axis == "coil current" and vc.x_min_fit == pytest.approx(650.0, rel=1e-6)
    assert vc.note == "Vertex outside the measured points – resonance not passed through?"


def test_diagnosis_text(station, tmp_path):
    """Summary of the raw-data diagnosis in German and English (numbers in the style of the language) and the
    suggested alignment for a recording whose voltages were recorded 0.5 s later."""
    w, rec, res = station
    d = diagnostics.diagnose(rec)
    de = d.text()
    assert de.startswith("Datei: st.cfg | ") and "| 60.000 Abtastwerte | 6,000 s" in de
    assert "Abtastnummern fortlaufend: ja" in de and de.endswith("✓ keine Auffälligkeiten")
    with i18n.language("en"):
        en = d.text()
        notes = set(diagnostics.diagnose(rec).channels["note"])
    assert en.startswith("File: st.cfg | ") and "| 60,000 samples | 6.000 s" in en
    assert "sample numbers consecutive: yes" in en and en.endswith("✓ no anomalies")
    assert "≈ 0 at the check time (faulted phase?)" in notes
    rec2, n = _voltages_delayed(rec, str(tmp_path / "offset.cfg"), 0.5)
    d2 = diagnostics.diagnose(rec2)
    assert d2.alignment_suggestion["roles"] == ["u_l1e", "u_l2e", "u_l3e"] and 0.4 < d2.alignment_suggestion["dt_s"] < 0.7
    assert "Zuerst Neu-Export versuchen, sonst alignment setzen." in d2.warnings[-1]
    with i18n.language("en"):
        text = d2.text()
    assert "⚠ Subsystems not synchronous – suggestion: alignment = {'roles': ['u_l1e', 'u_l2e', 'u_l3e']" in text


def test_message_catalog_complete():
    for lang in ("en", "de"):
        assert [m for m in i18n.missing_keys(lang) if m.startswith(("explorer.", "rms.", "diagnostics."))] == []


def test_missing_plotly_names_the_extra(monkeypatch):
    """Without plotly the interactive figures and the signal explorer raise an ImportError that names the extra
    ``interactive``."""
    import sys
    monkeypatch.setattr(interactive, "HAS_PLOTLY", False)
    with i18n.language("en"), pytest.raises(ImportError, match=r'^plotly is not installed: pip install '
                                                               r'"groundfault\[interactive\]"$'):
        interactive.overview(None)
    monkeypatch.setitem(sys.modules, "plotly.graph_objects", None)
    with pytest.raises(ImportError, match=r'^plotly ist nicht installiert: pip install "groundfault\[interactive\]"$'):
        explorer._go()
