# -*- coding: utf-8 -*-
"""Disturbed states during the fault (active residual current increase, network change): synthetic window series
and demo recordings with known solution."""
import json
import re

import numpy as np
import pytest

from groundfault import Intervals, Settings, demo, disturbances, evaluate, i18n, load_result, open_recording

T = 0.1 + 0.2 * np.arange(40)                          # window centres of an 8-s interval
U0 = np.full(T.size, 11500.0 + 0j)                    # zero-sequence voltage (reference of the angle method)
RNG = np.random.default_rng(1)


def _I1(Iw, Iv, noise=0.03):
    """Fault-current phasor with the angle-method components Iw (in phase with U0) and Iv (over-compensated > 0)."""
    Iw = np.broadcast_to(np.asarray(Iw, float), T.shape)
    Iv = np.broadcast_to(np.asarray(Iv, float), T.shape)
    return (Iw - 1j * Iv) + noise * (RNG.standard_normal(T.size) + 1j * RNG.standard_normal(T.size))


def test_active_increase_pulse():
    """Iw +12 A from 3.0 s to 5.0 s: one disturbed range, reference before and after it, step sizes reported."""
    Iw = np.where((T > 3.0) & (T < 5.0), 32.0, 20.0)
    d = disturbances.detect(T, _I1(Iw, 25.0), U0)
    seg = d.segments
    assert list(seg["state"]) == ["reference", "active increase", "reference"]
    assert seg.loc[1, "from_s"] == pytest.approx(3.0) and seg.loc[1, "to_s"] == pytest.approx(5.0)
    assert seg.loc[1, "d_Iw_A"] == pytest.approx(12.0, abs=0.1)
    assert list(d.events["kind"]) == ["active increase", "active decrease"]
    assert d.reference.sum() == 30 and d.found
    assert d.reference_intervals() == [(pytest.approx(0.0), pytest.approx(3.0)), (pytest.approx(5.0), pytest.approx(8.0))]
    assert d.suggestion() == (0.0, 3.0)
    with i18n.language("en"):
        assert d.parts_text() == "active residual current increase 3.0–5.0 s (ΔIw +12.0 A)"
    with i18n.language("de"):
        assert d.parts_text() == "Wattreststromerhöhung 3,0–5,0 s (ΔIw +12,0 A)"


def test_network_change_persists_and_cause_without_coils():
    """Iv +12 A from 4.0 s on (a network section trips): the rest of the interval is disturbed; without coil
    currents the cause is open."""
    Iv = np.where(T > 4.0, 37.0, 25.0)
    d = disturbances.detect(T, _I1(20.0, Iv), U0)
    assert list(d.segments["state"]) == ["reference", "reactive step"]
    assert d.segments.loc[0, "to_s"] == pytest.approx(4.0)
    assert d.reference.sum() == 20
    with i18n.language("en"):
        assert d.parts_text() == "step of the reactive component (network or coil) from 4.0 s (ΔIv +12.0 A)"
        assert any("without coil-current measurement" in n for n in d.notes())


def test_coil_currents_separate_network_and_coil_changes():
    """With coil currents: a step of Iv with unchanged coil currents is a network change (disturbance); a step that
    the coil currents follow is a coil change (reported, no disturbance) – also if the coil channel captures only
    half of the coil current."""
    Iv = np.where(T > 4.0, 37.0, 25.0)
    coil = np.full(T.size, 300.0)
    d = disturbances.detect(T, _I1(20.0, Iv), U0, coil=coil)
    assert list(d.segments["state"]) == ["reference", "network change"]
    assert list(d.events["kind"]) == ["network change"]
    for factor in (1.0, 0.5):
        d = disturbances.detect(T, _I1(20.0, Iv), U0, coil=coil + factor * np.where(T > 4.0, 12.0, 0.0))
        assert not d.found and list(d.segments["state"]) == ["reference"]
        assert list(d.events["kind"]) == ["coil change"]
        with i18n.language("de"):
            assert re.match(r"Spulenverstellung bei (3,9|4,1) s \(ΔIv \+12,0 A", d.notes()[0])


def test_ramp_is_not_a_step():
    """A coil adjustment changes Iv gradually (here 12 A over 4 s): not a disturbance."""
    Iv = 25.0 + np.clip((T - 2.0) / 4.0, 0, 1) * 12.0
    d = disturbances.detect(T, _I1(20.0, Iv), U0)
    assert not d.found and d.events.empty


def test_interval_starting_during_an_increase():
    """The interval starts in an active residual current increase that ends at 2.0 s: the windows before are
    disturbed (the increase only adds active current), the rest is the reference."""
    Iw = np.where(T < 2.0, 35.0, 20.0)
    d = disturbances.detect(T, _I1(Iw, 25.0), U0)
    assert list(d.segments["state"]) == ["active increase", "reference"]
    assert d.suggestion() == (2.0, 8.0)


def test_step_in_the_last_window_and_small_steps():
    """A step in the last window is caught (no window after it); a step below the threshold (5 % of |I_H1|) is
    ignored."""
    Iw = np.where(T > 7.8, 30.0, 20.0)
    d = disturbances.detect(T, _I1(Iw, 25.0), U0)
    assert d.state[-1] == "active increase" and d.reference.sum() == 39
    small = disturbances.detect(T, _I1(np.where(T > 4.0, 21.2, 20.0), 25.0), U0)       # 1.2 A < 0.05·32 A
    assert not small.found
    assert small.threshold_A == pytest.approx(0.05 * np.hypot(20.0, 25.0), rel=0.02)


def test_without_u0_and_with_invalid_windows():
    """Without U0 only |I_H1| is used (cause open); windows without values (NaN) are neither disturbed nor part of
    the reference."""
    I1 = _I1(np.where((T > 3.0) & (T < 5.0), 32.0, 20.0), 25.0)
    I1[7] = np.nan
    d = disturbances.detect(T, I1)
    assert not d.with_u0
    assert set(d.segments["state"]) == {"reference", "fundamental step"}
    assert d.state[7] == "" and not d.reference[7]


def test_windows_without_fault_current_are_no_state_of_the_fault():
    """An interval that reaches beyond the clearance (or begins before the inception): the windows without fault
    current are a state of their own – never the reference, and the drop of Iw at the clearance does not turn the
    whole fault into an active residual current increase."""
    Iw = np.where((T > 2.0) & (T < 3.0), 32.0, 20.0)
    I1 = _I1(Iw, 25.0)
    I1[T > 7.0] = 0.01 + 0.01j                          # cleared at 7.0 s: only noise remains
    I1[T < 1.0] = 0.02 + 0.0j                           # fault inception at 1.0 s
    d = disturbances.detect(T, I1, U0, np.abs(I1))
    assert list(d.segments["state"]) == ["no fault current", "reference", "active increase", "reference",
                                         "no fault current"]
    assert d.reference_intervals() == [(pytest.approx(1.0), pytest.approx(2.0)), (pytest.approx(3.0),
                                                                                   pytest.approx(7.0))]
    assert not d.reference[(T < 1.0) | (T > 7.0)].any()
    with i18n.language("en"):
        assert d.parts_text() == ("no fault current (before the fault inception or after the clearance) 0.0–1.0 s; "
                                  "active residual current increase 2.0–3.0 s (ΔIw +12.0 A); no fault current "
                                  "(before the fault inception or after the clearance) 7.0–8.0 s")
    # without RMS values |I_H1| decides
    d = disturbances.detect(T, I1, U0)
    assert d.state[T > 7.0].tolist() == ["no fault current"] * int((T > 7.0).sum())


def test_evaluation_interval_beyond_the_clearance(tmp_path):
    """Demo substation (fault 2–6 s): a steady-state interval up to 6.5 s gives the same residual current as one
    that ends before the active residual current increase; the windows after the clearance are reported."""
    cfg = str(tmp_path / "SUB_0_10_000kHz.cfg")
    w = demo.make_substation_recording(cfg, 0.0, duration=9.0)
    rec = open_recording(cfg)
    res = evaluate(rec, Intervals((2.6, 6.5), (0.2, 1.8), (7.0, 8.8)))
    assert res.values["IRES"] == pytest.approx(w["IRES"], rel=3e-3)
    assert res.t_max_window < 4.6 or 5.4 < res.t_max_window < 6.0
    seg = res.table("steady_state_segments")
    assert list(seg["state"])[-1] == "no fault current"
    assert seg["to_s"].iloc[-1] == pytest.approx(6.4) and seg["from_s"].iloc[-1] == pytest.approx(6.0, abs=0.21)
    assert any("ohne Fehlerstrom" in h for h in res.hints)
    assert not res.reference_windows[res.steady_state.t_mid > 6.2].any()
    keep = evaluate(rec, Intervals((2.6, 6.5), (0.2, 1.8), (7.0, 8.8)), Settings(exclude_disturbances=False))
    assert keep.reference_windows.all()                  # as groundfault 2.0: every window counts


def test_evaluation_excludes_network_change_and_increase(tmp_path):
    """Demo substation: a network section trips at 3.8 s (Iv +12 A, coil currents unchanged), then an active residual
    current increase (4.6–5.4 s). The max window lies in the undisturbed state before 3.8 s; result file, table and
    plausibility row document it; loading the result file keeps the information."""
    cfg = str(tmp_path / "SUB_0_10_000kHz.cfg")
    w = demo.make_substation_recording(cfg, 0.0, duration=9.0, network_step=(3.8, 12.0))
    res = evaluate(open_recording(cfg), Intervals((2.6, 5.9), (0.2, 1.8), (7.0, 8.8)))
    assert res.values["IRES"] == pytest.approx(w["IRES"], rel=3e-3)
    assert res.t_max_window < 3.8
    seg = res.table("steady_state_segments")
    assert list(seg["state"]) == ["reference", "network change", "active increase + network change",
                                  "network change"]
    assert seg.loc[0, "to_s"] == pytest.approx(3.8)
    line = res.table("plausibility").set_index("check").loc["Gestörte Zustände im stationären Bereich"]
    assert line["status"] == "NOTE"
    assert line["value"] == "Netzänderung ab 3,8 s (ΔIv +12,0 A); Wattreststromerhöhung 4,6–5,4 s (ΔIw +15,0 A)"
    p = res.save_json(str(tmp_path / "result.json"))
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    assert data["disturbances"]["excluded"] is True
    assert data["disturbances"]["reference_s"] == [[pytest.approx(2.6), pytest.approx(3.8)]]
    assert data["measurement"]["settings"]["exclude_disturbances"] is True
    back = load_result(p)
    assert list(back.table("steady_state_segments")["state"]) == list(seg["state"])
    # without the exclusion: max window in the disturbed part (largest residual current), warning
    keep = evaluate(open_recording(cfg), Intervals((2.6, 5.9), (0.2, 1.8), (7.0, 8.8)),
                    Settings(exclude_disturbances=False))
    assert keep.values["IRES"] > 1.15 * w["IRES"]
    assert keep.table("plausibility").set_index("check").loc[
        "Gestörte Zustände im stationären Bereich", "status"] == "WARNING"


def test_finer_max_search_stays_in_the_reference(tmp_path):
    """max_search_hop: the finer grid only searches inside the undisturbed time span."""
    cfg = str(tmp_path / "SUB_0_10_000kHz.cfg")
    w = demo.make_substation_recording(cfg, 0.0, duration=9.0)
    res = evaluate(open_recording(cfg), Intervals((2.6, 5.9), (0.2, 1.8), (7.0, 8.8)), Settings(max_search_hop=0.05))
    assert not 4.5 <= res.t_max_window <= 5.5
    assert res.values["IRES"] == pytest.approx(w["IRES"], rel=3e-3)


def test_scan_suggests_the_undisturbed_interval(tmp_path):
    """scan: the whole fault (2–6 s) is searched; the suggestion ends before the active residual current increase."""
    cfg = str(tmp_path / "SUB_0_10_000kHz.cfg")
    demo.make_substation_recording(cfg, 0.0, duration=9.0)
    d = disturbances.scan(open_recording(cfg))
    assert d.meta["t_fault_inception_s"] == pytest.approx(2.0, abs=0.05)
    assert d.meta["t_fault_clearance_s"] == pytest.approx(6.0, abs=0.05)
    a, b = d.suggestion()
    assert 2.3 <= a <= 3.0 and b == pytest.approx(4.6, abs=0.11)
    with i18n.language("en"):
        text = d.text()
    assert "Suggestion: STEADY_STATE = (%.1f, %.1f)" % (a, b) in text
    assert "active residual current increase 4.6–5.4 s (ΔIw +15.0 A)" in text


@pytest.mark.parametrize("kwargs", [dict(exclude_disturbances="yes"), dict(disturbance_threshold=0.0),
                                    dict(disturbance_threshold=1.5), dict(disturbance_threshold="5 %")])
def test_settings_are_checked(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)
