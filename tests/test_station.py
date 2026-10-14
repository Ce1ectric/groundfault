# -*- coding: utf-8 -*-
"""Station: touch voltage from the probe distances and frequency-selective evaluation (direct and fault-related
component) on synthetic station recordings with background and drifting network frequency; frequency reference and
null test (reliability of the fault-related component); messages in German and English."""
import numpy as np
import pandas as pd
import pytest

from groundfault import Intervals, Settings, demo, detect_roles, i18n, open_recording, evaluate
from groundfault import station


def _roles(*short):
    names = ["DANEO 1_Spannungen_%s Inst" % k if k.startswith("U") else "DANEO 1_Ströme_%s Inst" % k for k in short]
    return detect_roles(names, ["V" if k.startswith("U") else "A" for k in short])


@pytest.mark.parametrize("channels,u_t,u_e_main", [
    (("UE80", "UE20", "UE1", "IF1"), "UE1", "UE80"),              # 1-m probe (names UE<distance>)
    (("U60m", "U25m", "U1m", "IF1"), "U1m", "U60m"),              # 1-m probe (names U<distance>m)
    (("UE_5m", "UE_70m", "IF1"), "UE_5m", "UE_70m"),              # shortest probe as approximation (as in the demo)
    (("U25m", "U60m", "IF1"), None, "U60m"),                      # shortest probe too far away
    (("UEr", "UEl", "UT", "IF1"), "UT", "UEr"),                   # named explicitly
    (("UE", "IF"), None, "UE"),                                   # one probe only
])
def test_touch_voltage_from_probe_distance(channels, u_t, u_e_main):
    r = _roles(*channels)
    assert (r.main("u_t").short if r.main("u_t") else None) == u_t
    assert r.main("u_e").short == u_e_main


def test_touch_voltage_override_takes_precedence():
    n = ["DANEO 1_Spannungen_UE_5m Inst", "DANEO 1_Spannungen_UE_70m Inst"]
    r = detect_roles(n, ["V", "V"], {"UE_5m": "u_e"})
    assert not r.has("u_t") and r.channels[0].source == "override"
    r = _roles("UE_5m", "UE_70m")
    assert "Näherung" in r.channels[0].source


@pytest.mark.parametrize("with_voltages", [True, False])
def test_fault_component_despite_background_and_frequency_drift(tmp_path, with_voltages):
    """Background up to 60 % of the earth potential rise, network frequency drifting by 10 mHz/s: the superposition
    methods hit r·Z_E per order, the direct quotient does not. Without a voltage measurement the time reference at
    fault inception/clearance suffices."""
    p = str(tmp_path / "station.cfg")
    w = demo.make_station_recording(p, with_voltages=with_voltages, duration=7.0, t_on=1.6, t_off=5.0,
                                    f1_drift_hz_s=0.01,
                                    background={1: demo.polar(8, 70), 5: demo.polar(2, 100), 7: demo.polar(1, -30)})
    res = evaluate(open_recording(p), Intervals(*[tuple(w["intervals"][k])
                                                  for k in ("steady_state", "pre_fault", "post_fault")]))
    df = res.table("station_frequency").set_index(["channel", "order"])
    methods = res.values["station_frequency"]["method"]
    assert {"inception", "clearance", "fault"} <= set(methods) and (("voltage" in methods) == with_voltages)
    for m, tol_magnitude, tol_angle in ((1, 0.01, 1.0), (5, 0.02, 2.0), (7, 0.03, 3.0), (11, 0.01, 1.0)):
        target = w["orders"][m]["rZE_probe"]
        r = df.loc[("UE_70m", m)]
        assert r["Z_fault_Ohm"] == pytest.approx(abs(target), rel=tol_magnitude)
        assert r["Z_fault_angle_deg"] == pytest.approx(np.degrees(np.angle(target)), abs=tol_angle)
    r1 = df.loc[("UE_70m", 1)]
    assert abs(r1["Z_direct_Ohm"] / abs(w["orders"][1]["rZE_probe"]) - 1) > 0.2       # direct: distorted by background
    assert df.loc[("UT", 1)]["F_fault"] == pytest.approx(w["F"], rel=0.02)
    assert any("Grundlast vor dem Fehler" in h for h in res.hints)
    # no limits given (groundfault has none): no extrapolation, a hint names Settings.ires_limits
    assert res.table("station_extrapolation").empty and "station_extrapolation" in res.tables
    assert any(h.startswith("Keine Hochrechnung der Stationsspannungen") and "Settings.ires_limits" in h
               for h in res.hints)
    assert not any(c.startswith(("UT_at_", "UE_at_")) for c in res.table("station_metrics").columns)
    # limits of the user (invented): the voltages are extrapolated to them
    res = evaluate(open_recording(p), Intervals(*[tuple(w["intervals"][k])
                                                  for k in ("steady_state", "pre_fault", "post_fault")]),
                   Settings(ires_limits=(50.0, 100.0)))
    h = res.table("station_extrapolation")
    assert set(h["I_limit_A"]) == {50.0, 100.0}
    line = h[(h["channel"] == "UE_70m") & (h["I_limit_A"] == 50.0)].iloc[0]
    target50 = 50.0 / w["IF_rms"] * w["UE_70m_rms"]                       # fault-related only, scaled exactly
    assert line["U_fault_V"] == pytest.approx(target50, rel=0.02)
    # upper bound with background and fault-related component in phase at every order: at least the phasor sum of
    # the test, at most fault-related plus background (RMS values), and computed per order
    sf = res.table("station_frequency")
    g = sf[sf["channel"] == "UE_70m"]
    scale = 50.0 / float(res.steady_state.rms[res.max_index, res.roles.main("i_res").index])
    upper = np.sqrt(np.sum((g["U_background_V"] + scale * g["U_fault_V"]) ** 2))
    assert line["U_background_plus_fault_in_phase_V"] >= line["U_background_plus_fault_V"] - 1e-9
    assert line["U_background_plus_fault_in_phase_V"] == pytest.approx(upper, rel=0.05)      # + rest of background
    assert line["U_background_plus_fault_in_phase_V"] <= line["U_fault_V"] + np.sqrt(np.sum(g["U_background_V"] ** 2)) + 0.5
    assert not any(x.startswith("Keine Hochrechnung") for x in res.hints)
    assert {"UE_at_50A_V", "UE_at_100A_V"} <= set(res.table("station_metrics").columns)


def test_fault_times_and_settling(tmp_path):
    p = str(tmp_path / "s.cfg")
    demo.make_station_recording(p, duration=6.0, t_on=1.5, t_off=4.5)
    rec = open_recording(p)
    r = detect_roles(rec.channel_names, rec.units)
    t_on, t_off = station.fault_times(rec, r.main("i_res").index)
    assert t_on == pytest.approx(1.5, abs=0.03) and t_off == pytest.approx(4.5, abs=0.03)
    assert station.settled_from(rec, r.main("i_res").index, t_on, t_off) == pytest.approx(
        t_on + station.T_TRANSIENT_S, abs=0.11)
    p2 = str(tmp_path / "until_end.cfg")
    demo.make_station_recording(p2, duration=4.0, t_on=1.5, t_off=10.0)
    rec2 = open_recording(p2)
    assert station.fault_times(rec2, r.main("i_res").index)[1] is None              # fault until the end of the file


def test_one_sided_with_frequency_drift(tmp_path):
    """Fault until the end of the file (fault inception only), no voltage measurement, network frequency drifting by
    10 mHz/s: with the frequency linear between both sides, the fault-related component hits r·Z_E per order to a
    few per cent (as a phasor); a hint names the only available method."""
    p = str(tmp_path / "e.cfg")
    w = demo.make_station_recording(p, duration=5.0, t_on=1.6, t_off=99, f1_drift_hz_s=0.01, with_voltages=False,
                                    background={1: demo.polar(8, 70), 3: demo.polar(5, 10), 5: demo.polar(2, 100)},
                                    I_harm={3: demo.polar(1.5, 20), 5: demo.polar(30.0, 35.0),
                                            7: demo.polar(6.0, -20.0)})
    res = evaluate(open_recording(p), Intervals((2.1, 4.8), (0.2, 1.4), None))
    df = res.table("station_frequency").set_index(["channel", "order"])
    assert res.values["station_frequency"]["method"] == ["direct", "inception", "fault"]
    for m, tol in ((1, 0.02), (3, 0.08), (5, 0.02), (7, 0.03)):
        target = w["orders"][m]["rZE_probe"]
        r = df.loc[("UE_70m", m)]
        z = r["Z_fault_Ohm"] * np.exp(1j * np.radians(r["Z_fault_angle_deg"]))
        assert abs(z - target) / abs(target) < tol, m
    assert any("nur ein Überlagerungsverfahren" in h for h in res.hints)


def test_spread_as_phasor_and_hint_per_frequency(tmp_path):
    """The background at 150 Hz turns by 90° during the fault: inception and clearance contradict each other at
    150 Hz (large spread as phasors, the hint names 150 Hz), at 50/250 Hz they agree."""
    p = str(tmp_path / "s.cfg")
    w = demo.make_station_recording(p, duration=7.0, t_on=1.6, t_off=5.0, with_voltages=False,
                                    background={1: demo.polar(8, 70), 3: demo.polar(5, 10)},
                                    background_post={1: demo.polar(8, 70), 3: demo.polar(5, 100)},
                                    I_harm={3: demo.polar(4.0, 20), 5: demo.polar(30.0, 35.0)})
    res = evaluate(open_recording(p), Intervals(*[tuple(w["intervals"][k])
                                                  for k in ("steady_state", "pre_fault", "post_fault")]))
    df = res.table("station_frequency").set_index(["channel", "order"])
    assert df.loc[("UE_70m", 3)]["method_spread_pct"] > 50
    assert df.loc[("UE_70m", 1)]["method_spread_pct"] < 5 and df.loc[("UE_70m", 5)]["method_spread_pct"] < 5
    assert df.loc[("UE_70m", 3)]["uncertain"] and not df.loc[("UE_70m", 5)]["uncertain"]
    h = [x for x in res.hints if "unsichere Werte" in x]
    assert len(h) == 1 and "150 Hz (Verfahren weichen" in h[0] and "250 Hz" not in h[0]


def test_fault_from_start_of_file(tmp_path):
    p = str(tmp_path / "b.cfg")
    demo.make_station_recording(p, duration=4.0, t_on=0.0, t_off=3.0)
    rec = open_recording(p)
    r = detect_roles(rec.channel_names, rec.units)
    t_on, t_off = station.fault_times(rec, r.main("i_res").index)
    assert t_on is None and t_off == pytest.approx(3.0, abs=0.03)


def _z(r, method="fault"):
    return r["Z_%s_Ohm" % method] * np.exp(1j * np.radians(r["Z_%s_angle_deg" % method]))


@pytest.mark.parametrize("t_off", [5.0, 99])
def test_network_frequency_from_background_at_150_hz(tmp_path, t_off):
    """Background at 50 Hz only 0.3 V (in the noise), at 150 Hz 5 V; no voltage measurement, network frequency
    drifting by 10 mHz/s: the frequency before/after the fault comes from the 150-Hz background of a probe, the
    fault-related component at 150 Hz (I_F only 1.5 A, background six times as large) hits to a few per cent – with
    a constant frequency it would be off by more than 100 %."""
    p = str(tmp_path / "f150.cfg")
    w = demo.make_station_recording(p, duration=7.0 if t_off < 99 else 5.0, t_on=1.6, t_off=t_off,
                                    f1_drift_hz_s=0.01, with_voltages=False, noise_U=0.3,
                                    background={1: demo.polar(0.3, 70), 3: demo.polar(5, 10)},
                                    I_harm={3: demo.polar(1.5, 20), 5: demo.polar(30.0, 35.0),
                                            7: demo.polar(6.0, -20.0)})
    b = (Intervals(*[tuple(w["intervals"][k]) for k in ("steady_state", "pre_fault", "post_fault")]) if t_off < 99
         else Intervals((2.3, 4.8), (0.2, 1.4), None))
    res = evaluate(open_recording(p), b)
    sf = res.values["station_frequency"]
    for side in ("inception", "clearance") if t_off < 99 else ("inception",):
        assert sf[side]["f_background_source"].endswith("bei 150 Hz") and sf[side]["f_fault_source"] == "IF1"
    r = res.table("station_frequency").set_index(["channel", "order"]).loc[("UE_70m", 3)]
    target = w["orders"][3]["rZE_probe"]
    assert abs(_z(r) - target) / abs(target) < 0.05
    assert r["background_to_fault"] > 4


def test_network_frequency_from_line_to_line_voltage(tmp_path):
    """With line-to-earth voltages, U_L1-L2 is the frequency reference on both sides (unaffected by the earth fault
    and by the background) – accurate to fractions of a mHz."""
    p = str(tmp_path / "ll.cfg")
    demo.make_station_recording(p, duration=7.0, t_on=1.6, t_off=5.0, f1_drift_hz_s=0.01, with_voltages=True,
                                background={1: demo.polar(8, 70), 3: demo.polar(5, 10)})
    res = evaluate(open_recording(p), Intervals((2.3, 4.8), (0.2, 1.4), (5.5, 6.8)))
    sf = res.values["station_frequency"]
    for side in ("inception", "clearance"):
        assert sf[side]["f_background_source"] == "U_L1-L2" and sf[side]["f_fault_source"] == "U_L1-L2"
    # frequency at the centre of the window sequences: f(t) = 49.98 Hz + 10 mHz/s · t
    t_g = np.mean(sf["inception"]["t_background_s"]); t_f = np.mean(sf["inception"]["t_fault_s"])
    assert sf["inception"]["f_background_hz"] == pytest.approx(49.98 + 0.01 * t_g, abs=5e-4)
    assert sf["inception"]["f_fault_hz"] == pytest.approx(49.98 + 0.01 * t_f, abs=5e-4)


@pytest.mark.parametrize("fluctuation,with_voltages", [(0.0, True), (0.0, False), (0.15, False)])
def test_null_test_flags_fluctuating_background(tmp_path, fluctuation, with_voltages):
    """Long fault-free sections before and after the fault: the null test estimates how accurately the background can
    be predicted across the gap. At 150 Hz the background is twelve times as large as the fault-related component.

    * constant background, voltages measured: reliable (small uncertainty, not flagged);
    * constant background, no voltages: the frequency reference is then the fault current, whose phase can drift
      against the network – with a twelve-fold background 3 mHz cause large errors → uncertain (frequency-reference
      contribution);
    * fluctuating background (15 %, as at real stations): the null test itself flags 150 Hz as uncertain.

    250 Hz (much fault current, no background) always stays inconspicuous."""
    p = str(tmp_path / "nt.cfg")
    w = demo.make_station_recording(p, duration=16.0, t_on=6.0, t_off=10.0, with_voltages=with_voltages,
                                    background={1: demo.polar(8, 70), 3: demo.polar(5, 10)},
                                    background_fluctuation=fluctuation,
                                    I_harm={3: demo.polar(1.5, 20), 5: demo.polar(30.0, 35.0),
                                            7: demo.polar(6.0, -20.0)})
    res = evaluate(open_recording(p), Intervals(*[tuple(w["intervals"][k])
                                                  for k in ("steady_state", "pre_fault", "post_fault")]))
    sf = res.values["station_frequency"]
    assert sf["inception"]["null_test"] and sf["clearance"]["null_test"]
    df = res.table("station_frequency").set_index(["channel", "order"])
    r3, r5 = df.loc[("UE_70m", 3)], df.loc[("UE_70m", 5)]
    assert not r5["uncertain"] and r5["uncertainty_pct"] < 5
    h = [x for x in res.hints if "unsichere Werte" in x]
    target = w["orders"][3]["rZE_probe"]
    if fluctuation:
        assert r3["uncertain"] and r3["uncertainty_pct"] > 20 and r3["background_forecast_error_pct"] > 5
        assert len(h) == 1 and "150 Hz" in h[0] and "250 Hz" not in h[0]
    elif with_voltages:
        assert not r3["uncertain"] and r3["uncertainty_pct"] < 5 and not h
        assert np.isnan(r3["frequency_uncertainty_pct"])                 # U_L-L: no frequency-reference contribution
        assert abs(_z(r3) - target) / abs(target) < 0.02
    else:
        assert r3["background_forecast_error_pct"] < 2 and r3["frequency_uncertainty_pct"] > 20 and r3["uncertain"]
        assert len(h) == 1 and "Frequenzbezug ohne Spannungsmessung" in h[0]
        # correct nevertheless here (the fault current is network-synchronous)
        assert abs(_z(r3) - target) / abs(target) < 0.02


def test_without_background_frequency_continued(tmp_path):
    """No background (only noise before the fault): the network frequency cannot be estimated there – the frequency
    during the fault is continued (hint naming the side); without a background the fault-related component is
    correct nevertheless."""
    p = str(tmp_path / "og.cfg")
    w = demo.make_station_recording(p, duration=7.0, t_on=1.6, t_off=5.0, f1_drift_hz_s=0.003, with_voltages=False)
    res = evaluate(open_recording(p), Intervals(*[tuple(w["intervals"][k])
                                                  for k in ("steady_state", "pre_fault", "post_fault")]))
    sf = res.values["station_frequency"]
    assert sf["inception"]["f_background_source"].startswith("nicht schätzbar")
    assert sf["inception"]["f_background_hz"] == sf["inception"]["f_fault_hz"]
    assert any("Netzfrequenz vor dem Fehler nicht schätzbar" in h for h in res.hints)
    assert any(h.startswith("Station (Fehlereintritt): Netzfrequenz vor dem Fehler") for h in res.hints)
    assert any(h.startswith("Station (Fehlerende): Netzfrequenz nach dem Fehler") for h in res.hints)
    r = res.table("station_frequency").set_index(["channel", "order"]).loc[("UE_70m", 5)]
    target = w["orders"][5]["rZE_probe"]
    assert abs(_z(r) - target) / abs(target) < 0.01 and not r["uncertain"]


def test_short_transient_before_the_fault(tmp_path):
    """Short transient (0.15 s) in the fault current 2 s before the earth fault: inception and clearance refer to the
    active section around the steady-state interval – not to the transient; the fault-related component stays
    correct."""
    from groundfault import write_comtrade
    p = str(tmp_path / "w.cfg")
    w = demo.make_station_recording(p, duration=8.0, t_on=3.5, t_off=6.5, with_voltages=False,
                                    background={1: demo.polar(8, 70), 3: demo.polar(5, 10)})
    rec = open_recording(p)
    x = rec.read(0, rec.n)
    t = np.arange(rec.n) / rec.fs
    sig = {}
    for j, (nm, unit) in enumerate(zip(rec.channel_names, rec.units)):
        y = x[:, j].copy()
        if nm.endswith("IF1 Inst"):
            y += ((t >= 1.5) & (t < 1.65)) * 40.0 * np.sqrt(2) * np.sin(2 * np.pi * 49.98 * t)
        sig[nm] = (unit, y)
    q = str(tmp_path / "transient.cfg")
    write_comtrade(q, sig, rec.fs)
    res = evaluate(open_recording(q), Intervals((4.0, 6.3), (0.2, 1.3), (7.0, 7.8)))
    sf = res.values["station_frequency"]
    assert sf["t_fault_inception_s"] == pytest.approx(3.5, abs=0.05)
    assert sf["t_fault_clearance_s"] == pytest.approx(6.5, abs=0.05)
    r = res.table("station_frequency").set_index(["channel", "order"]).loc[("UE_70m", 1)]
    target = w["orders"][1]["rZE_probe"]
    assert abs(_z(r) - target) / abs(target) < 0.01
    # without an interval (e.g. explorer): first/last active instant as before
    ires = res.roles.main("i_res").index
    assert station.fault_times(open_recording(q), ires)[0] == pytest.approx(1.5, abs=0.05)


def test_result_file_without_null_test_figures(tmp_path):
    """Short recording (no null test possible): the result file stores NaN as null – after loading, the columns are
    numbers again, and figures and hover texts work."""
    from groundfault import interactive, report
    from groundfault.evaluation import ResultFile
    p = str(tmp_path / "k.cfg")
    w = demo.make_station_recording(p, duration=6.0, t_on=1.5, t_off=4.5, with_voltages=True,
                                    background={1: demo.polar(8, 70)})
    res = evaluate(open_recording(p), Intervals(*[tuple(w["intervals"][k])
                                                  for k in ("steady_state", "pre_fault", "post_fault")]))
    assert res.table("station_frequency")["background_forecast_error_pct"].isna().all()
    e = ResultFile(res.save_json(str(tmp_path / "k_result.json")))
    sf = e.table("station_frequency")
    assert sf["uncertainty_pct"].dtype.kind == "f" and sf["background_forecast_error_pct"].isna().all()
    fig = interactive.station_frequency(e)
    assert all("None" not in h for tr in fig.data if tr.hovertext is not None for h in tr.hovertext)
    report.station_frequency(e)


# ---------------------------------------------------------------------------------------------- messages
def test_method_labels_follow_the_language():
    """METHODS renders the labels in the active language; the method codes stay the same."""
    assert list(station.METHODS) == ["direct", "inception", "clearance", "voltage", "fault"]
    assert station.METHODS["inception"] == "Überlagerung am Fehlereintritt (Zeitbezug)"
    assert "voltage" in station.METHODS and "spannung" not in station.METHODS
    with i18n.language("en"):
        assert station.METHODS["inception"] == "superposition at fault inception (time reference)"
        assert dict(station.METHODS)["direct"] == "direct (as measured, including background)"
    with pytest.raises(KeyError):
        station.METHODS["unknown"]


def test_messages_in_english(tmp_path):
    """English output: the hints keep their prefix ("Station") and use decimal points, the frequency sources and the
    method names are English; the tables (numbers, codes) are the same in both languages."""
    p = str(tmp_path / "en.cfg")
    demo.make_station_recording(p, duration=5.0, t_on=0.55, t_off=99, with_voltages=True,
                                background={1: demo.polar(8, 70), 3: demo.polar(5, 10)},
                                I_harm={3: demo.polar(1.5, 20), 5: demo.polar(30.0, 35.0), 7: demo.polar(6.0, -20.0)})
    intervals = Intervals((1.2, 4.8), None, None)
    res_de = evaluate(open_recording(p), intervals)
    with i18n.language("en"):
        res = evaluate(open_recording(p), intervals)
    station_en = [h for h in res.hints if h.startswith("Station")]
    station_de = [h for h in res_de.hints if h.startswith("Station")]
    assert len(station_en) == len(station_de) == 4
    assert ("No extrapolation of the station voltages to limits of the residual current: Settings.ires_limits is "
            "empty (the limits are defined by the user).") in res.hints
    assert any(h.startswith("Station: uncertain values – 150 Hz (background ") and " times as large)" in h
               and "(column 'uncertain' in station_frequency)" in h for h in station_en)
    assert any(h.startswith("Station (fault inception): network frequency before the fault not estimable (section "
                            "before the fault too short)") for h in station_en)
    assert any(h.startswith("Station: background before the fault up to ") for h in station_en)
    assert ("Station: only one superposition method available (superposition at fault inception) – no mutual check, "
            "spread not determinable.") in station_en
    # numbers: decimal point in English, decimal comma in German (the hint names the largest ratio at 150 Hz)
    df = res.table("station_frequency")
    ratio = df[(df["order"] == 3) & df["uncertain"]]["background_to_fault"].max()
    assert ("background %.1f times as large" % ratio) in " ".join(station_en)
    assert ("Grundlast %s-mal so groß" % ("%.1f" % ratio).replace(".", ",")) in " ".join(station_de)
    sf = res.values["station_frequency"]["inception"]
    assert sf["f_background_source"] == "not estimable (too short) – frequency during the fault continued"
    sf_de = res_de.values["station_frequency"]["inception"]
    assert sf_de["f_background_source"].startswith("nicht schätzbar (zu kurz)")
    pd.testing.assert_frame_equal(res.table("station_frequency"), res_de.table("station_frequency"))


def test_message_catalog_complete():
    """Every message of the station module exists in English and German."""
    assert i18n.has_message("station.uncertain_values") and i18n.has_message("station.lv_kcl_violated")
    for lang in ("en", "de"):
        assert [m for m in i18n.missing_keys(lang) if m.startswith("station.")] == []
