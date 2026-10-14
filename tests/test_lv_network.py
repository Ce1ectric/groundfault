# -*- coding: utf-8 -*-
"""Station: current into the LV network from the PEN currents (superposition, Kirchhoff's current law), earthing
impedance of the LV network, reduction factor from the staged fault test and the earthing measurement, parallel-branch
check – on synthetic stations with a known solution (``demo.make_station_recording(lv_network=…)``). RMS values are
additionally recomputed with a second method (time domain instead of the sum of the harmonics)."""
import math

import numpy as np
import pandas as pd
import pytest

from groundfault import Intervals, demo, earthing, channels, corrections, i18n, open_recording, evaluate

from test_earthing import _db, _z

PROBE = 0.93                       # share of the earth potential at the probe UE_70m (demo default)


def _evaluate(tmp_path, name="st.cfg", **kw):
    p = str(tmp_path / name)
    kw.setdefault("duration", 8.0); kw.setdefault("t_on", 2.0); kw.setdefault("t_off", 5.5)
    kw.setdefault("with_voltages", True)
    w = demo.make_station_recording(p, **kw)
    b = w["intervals"]
    res = evaluate(open_recording(p), Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]),
                                                tuple(b["post_fault"])))
    return w, res


def _truth(w, m):
    return w["orders"][m] if m in w["orders"] else w["orders"][str(m)]


# ---------------------------------------------------------------------------------------------- channels
@pytest.mark.parametrize("name,position", [("DANEO 1_Ströme_IPEN_v Inst", "feeders"),
                                           ("DANEO 1_Ströme_IPEN_n Inst", "busbar"),
                                           ("IPENvor", "feeders"), ("I_PEN_nach", "busbar"), ("IPEN", None),
                                           ("Ipen", None), ("IPEN2", None)])
def test_pen_position_from_name(name, position):
    assert channels.detect_role(name)[0] == "i_pen"
    assert channels.pen_position(name) == position


def test_pen_position_as_override_and_in_corrections(tmp_path):
    r = channels.detect_roles(["A1 Inst", "A2 Inst", "IF Inst"], ["A", "A", "A"],
                              {"A1": "i_pen_feeders", "A2": "i_pen_busbar"})
    assert [(k.role, k.position) for k in r.channels[:2]] == [("i_pen", "feeders"), ("i_pen", "busbar")]
    assert "position" in r.table()
    notes = tmp_path / "0_Notizen"; notes.mkdir()            # German campaign layout: legacy header and role
    (notes / "Korrekturen.csv").write_text("Datei;Kanal;Faktor;Rolle;Hauptkanal;Abstand_m;Bemerkung\n"
                                           "*;IPEN;;i_pen_n;;;clamp at the main earthing busbar\n", encoding="utf-8")
    k = corrections.load(str(tmp_path))
    assert k.rules[0].role == "i_pen_busbar"


# ---------------------------------------------------------------------------------------------- LV network
def test_current_into_lv_network_despite_load_unbalance(tmp_path):
    w, res = _evaluate(tmp_path, lv_network=dict(R_LV=4.0, X_LV1=0.4))
    # counting directions as measured: feeders from the star point to the LV network, busbar from the star point to
    # the main earthing busbar → ΔI_busbar = −ΔI_feeders
    assert {d["position"]: d["sign"] for d in res.values["station_lv_network"]["pen"]} == {"feeders": 1, "busbar": -1}
    currents = res.tables["station_currents_frequency"]
    lv = res.tables["station_lv_network"]
    remote = lv[lv["channel"] == "UE_70m"]
    assert len(remote) == len(w["orders"])
    for _, r in remote.iterrows():
        t = _truth(w, int(r["order"]))
        assert r["Z_E_LV_Ohm"] == pytest.approx(abs(complex(t["Z_LV_probe"]["re"], t["Z_LV_probe"]["im"]))
                                                if isinstance(t["Z_LV_probe"], dict) else abs(t["Z_LV_probe"]),
                                                rel=0.02)
        i_lv = t["I_LV"]
        i_lv = abs(complex(i_lv["re"], i_lv["im"])) if isinstance(i_lv, dict) else abs(i_lv)
        assert r["I_LV_A"] == pytest.approx(i_lv, rel=0.02)
        assert r["kcl_deviation_pct"] < 2.0
        assert r["parallel_check"] == "satisfied"
    # the load unbalance is contained in the direct value, not in the fault-related one
    v1 = currents[(currents["channel"] == "IPEN_v") & (currents["order"] == 1)].iloc[0]
    i_lv1 = remote[remote["order"] == 1]["I_LV_A"].iloc[0]
    assert abs(v1["I_during_fault_A"] - i_lv1) > 5.0
    assert v1["I_fault_A"] == pytest.approx(i_lv1, rel=0.02)
    assert v1["I_background_A"] == pytest.approx(18.0, rel=0.03)            # load_feeders at 50 Hz
    assert not [h for h in res.hints if h.startswith("Ortsnetz")]          # no LV-network hints


def test_lv_network_rms_values_recomputed_in_time_domain(tmp_path):
    """Second method: RMS values from synthetic time series (truth) instead of √Σ of the harmonics."""
    w, res = _evaluate(tmp_path, lv_network=dict(R_LV=3.0, X_LV1=0.5))
    eff = res.tables["station_lv_network_eff"]
    e = eff[eff["channel"] == "UE_70m"].iloc[0]
    ords = [int(m) for m in e["orders"].split(", ")]
    t = np.arange(0, 1.0, 1 / 20000.0)
    u = np.zeros_like(t); i = np.zeros_like(t)
    for m in ords:
        x = _truth(w, m)
        z_lv = x["Z_LV_probe"]; i_lv = x["I_LV"]
        z_lv = complex(z_lv["re"], z_lv["im"]) if isinstance(z_lv, dict) else z_lv
        i_lv = complex(i_lv["re"], i_lv["im"]) if isinstance(i_lv, dict) else i_lv
        u += math.sqrt(2) * np.real(z_lv * i_lv * np.exp(2j * np.pi * 50 * m * t))
        i += math.sqrt(2) * np.real(i_lv * np.exp(2j * np.pi * 50 * m * t))
    u_rms, i_rms = math.sqrt(np.mean(u ** 2)), math.sqrt(np.mean(i ** 2))
    assert e["I_LV_eff_A"] == pytest.approx(i_rms, rel=0.02)
    assert e["U_E_fault_eff_V"] == pytest.approx(u_rms, rel=0.02)
    assert e["Z_E_LV_eff_Ohm"] == pytest.approx(u_rms / i_rms, rel=0.02)
    assert e["parallel_check"] == "satisfied"


@pytest.mark.parametrize("lv_network", [dict(sign_busbar=-1), dict(position="busbar"), dict(position="feeders")])
def test_counting_direction_and_single_measuring_point(tmp_path, lv_network):
    w, res = _evaluate(tmp_path, lv_network=dict(R_LV=4.0, X_LV1=0.4, **lv_network))
    lv = res.tables["station_lv_network"]
    r = lv[(lv["channel"] == "UE_70m") & (lv["order"] == 1)].iloc[0]
    t = _truth(w, 1)["Z_LV_probe"]
    assert r["Z_E_LV_Ohm"] == pytest.approx(abs(complex(t["re"], t["im"]) if isinstance(t, dict) else t),
                                            rel=0.02)
    if lv_network.get("sign_busbar") == -1:
        # busbar clamp connected the other way round: ΔI_busbar then points in the same direction as ΔI_feeders
        # (otherwise opposite)
        assert r["kcl_deviation_pct"] < 2.0
        signs = {d["position"]: d["sign"] for d in res.values["station_lv_network"]["pen"]}
        assert signs == {"feeders": 1, "busbar": 1}


def test_implausible_pen_current_violates_parallel_connection(tmp_path):
    w, res = _evaluate(tmp_path, lv_network=dict(R_LV=4.0, X_LV1=0.4, position="feeders", factor_feeders=10.0))
    lv = res.tables["station_lv_network"]
    remote = lv[lv["channel"] == "UE_70m"]
    assert (remote["I_LV_to_I_E"] > 1.0).all()
    assert (remote["parallel_check"] == "violated").all()
    assert any("größer als der Erdungsstrom" in h for h in res.hints)


def test_weighting_of_measuring_points_with_fluctuating_load(tmp_path):
    """IPEN_v carries a large, fluctuating load unbalance – the fault-related component is less certain there; the
    result then relies mainly on IPEN_n and stays accurate."""
    w, res = _evaluate(tmp_path, duration=16.0, t_on=6.0, t_off=10.0,
                       lv_network=dict(R_LV=4.0, X_LV1=0.4,
                                       load_feeders={1: demo.polar(60.0, -30.0), 3: demo.polar(25.0, 40.0)},
                                       load_busbar={1: demo.polar(1.0, -20.0)}, load_fluctuation=0.08))
    lv = res.tables["station_lv_network"]
    r = lv[(lv["channel"] == "UE_70m") & (lv["order"] == 1)].iloc[0]
    assert r["weight_busbar"] > r["weight_feeders"]
    t = _truth(w, 1)["Z_LV_probe"]
    assert r["Z_E_LV_Ohm"] == pytest.approx(abs(complex(t["re"], t["im"]) if isinstance(t, dict) else t),
                                            rel=0.05)


def test_lv_network_messages_in_english(tmp_path):
    """English output of the LV network: the hints start with "LV network:" (German "Ortsnetz:"), the position is
    shown as a German label in German only, and the reference of the total earthing keeps its formula
    ("I_E = I_F − I_S" or "I_F") in both languages; numbers and status codes are the same."""
    from groundfault import write_comtrade
    p = str(tmp_path / "st.cfg")
    demo.make_station_recording(p, duration=8.0, t_on=2.0, t_off=5.5, with_voltages=True,
                                lv_network=dict(R_LV=4.0, X_LV1=0.4, position="feeders", factor_feeders=10.0))
    intervals = Intervals((2.5, 5.3), (0.2, 1.8), (5.8, 7.8))
    with i18n.language("en"):
        res = evaluate(open_recording(p), intervals)
    assert set(res.tables["station_lv_network"]["total_earthing_reference"]) == {"I_E = I_F − I_S (shield current IS)"}
    assert any(h.startswith("LV network: current into the LV network larger than the earth current (I_E = I_F − I_S) "
                            "at 50, ") for h in res.hints)
    # second PEN channel at the feeders and no shield-current channel
    rec = open_recording(p)
    x = rec.read(0, rec.n)
    sig = {}
    for j, (nm, unit) in enumerate(zip(rec.channel_names, rec.units)):
        if nm.endswith("_IS Inst"):
            continue
        sig[nm] = (unit, x[:, j].copy())
        if nm.endswith("_IPEN_v Inst"):
            sig[nm.replace("_IPEN_v ", "_IPEN_v2 ")] = (unit, 1.02 * x[:, j])
    q = str(tmp_path / "no_shield.cfg")
    write_comtrade(q, sig, rec.fs)
    res_de = evaluate(open_recording(q), intervals)
    with i18n.language("en"):
        res = evaluate(open_recording(q), intervals)
    lv_en = [h for h in res.hints if h.startswith("LV network:")]
    lv_de = [h for h in res_de.hints if h.startswith("Ortsnetz:")]
    assert len(lv_en) == len(lv_de) == 2
    assert "LV network: several PEN channels with position feeders (IPEN_v, IPEN_v2) – using IPEN_v." in lv_en
    assert "Ortsnetz: mehrere PEN-Kanäle mit Lage v (IPEN_v, IPEN_v2) – verwendet IPEN_v." in lv_de
    assert any(h.startswith("LV network: current into the LV network larger than the earth current (I_F) at 50, ")
               for h in lv_en)
    assert any(h.startswith("Ortsnetz: Strom ins Ortsnetz größer als der Erdungsstrom (I_F) bei 50, ") for h in lv_de)
    lv, lv_ger = res.tables["station_lv_network"], res_de.tables["station_lv_network"]
    assert set(lv["total_earthing_reference"]) == {"I_F (without shield current – weaker condition)"}
    assert set(lv_ger["total_earthing_reference"]) == {"I_F (ohne Schirmstrom – schwächere Bedingung)"}
    assert res.values["station_lv_network"]["shield"] == []
    pd.testing.assert_frame_equal(lv.drop(columns="total_earthing_reference"),
                                  lv_ger.drop(columns="total_earthing_reference"))
    assert (lv[lv["channel"] == "UE_70m"]["parallel_check"] == "violated").all()


# ---------------------------------------------------------------------------------------------- reduction factor
R_ORD = {1: demo.polar(0.55, -8.0), 5: demo.polar(0.35, -20.0), 7: demo.polar(0.30, -25.0), 11: demo.polar(0.25, -30.0)}


def _injection_test(tmp_path, freq_orders=(1, 3, 5, 7), factor=1.0):
    inj = []
    for m in freq_orders:
        ze = (1.0 + 1j * m * 0.08) * PROBE * factor
        inj += [_z("earthing_current", 10.0, 50.0 * m, "A", 0.0),
                _z("earthing_impedance", abs(ze) * 1000, 50.0 * m, "mOhm", math.degrees(np.angle(ze)), 70.0)]
    p = _db(str(tmp_path / "gm.db"), locations=[(1, "SSt Demo")],
            measurements=[(1, 1, "injection_earth_electrode", inj)])
    with earthing.Database(p) as db:
        return earthing.frequency_response(db, [1])


def test_reduction_factor_per_harmonic_and_effective(tmp_path):
    w, res = _evaluate(tmp_path, lv_network=dict(R_LV=4.0, X_LV1=0.4), r_per_order=R_ORD)
    response = _injection_test(tmp_path)
    spectrum, eff = earthing.reduction_factor(res.tables, response)
    remote = spectrum[spectrum["channel"] == "UE_70m"]
    for _, r in remote.iterrows():
        m = int(r["order"])
        if m == 11:                                        # 550 Hz: no earthing measurement, never extrapolated
            assert np.isnan(r["r"]) and r["injection_frequency"] == ""
            continue
        assert r["r"] == pytest.approx(abs(R_ORD[m]), rel=0.02)
        assert r["r_shield"] == pytest.approx(abs(R_ORD[m]), rel=0.02)
        assert r["distance_match"] == "equal"
    e = eff[eff["channel"] == "UE_70m"].iloc[0]
    # truth (sum of the harmonics) and second method (RMS values of synthetic time series)
    num = den = 0.0
    t = np.arange(0, 1.0, 1 / 20000.0)
    u_f = np.zeros_like(t); u_i = np.zeros_like(t)
    for m in (1, 5, 7):
        x = _truth(w, m)
        ze = (1.0 + 1j * m * 0.08) * PROBE
        num += (abs(R_ORD[m]) * abs(ze) * x["I_F"]) ** 2; den += (abs(ze) * x["I_F"]) ** 2
        u_f += math.sqrt(2) * np.real(R_ORD[m] * ze * x["I_F"] * np.exp(2j * np.pi * 50 * m * t))
        u_i += math.sqrt(2) * np.real(ze * x["I_F"] * np.exp(2j * np.pi * 50 * m * t + 0.7j * m))
    r_true = math.sqrt(num / den)
    r_time = math.sqrt(np.mean(u_f ** 2) / np.mean(u_i ** 2))
    assert r_time == pytest.approx(r_true, rel=1e-6)
    assert e["r_eff"] == pytest.approx(r_true, rel=0.01)
    assert e["r_eff_shield"] == pytest.approx(r_true, rel=0.02)
    assert e["orders"] == "1, 5, 7"
    i_f = [_truth(w, m)["I_F"] for m in (1, 5, 7, 11)]
    assert e["I_F_coverage_pct"] == pytest.approx(100 * sum(x * x for x in i_f[:3]) / sum(x * x for x in i_f), rel=1e-3)
    # second method of the evaluation: RMS values as measured ÷ earthing impedance at 50 Hz (> r_eff, because the
    # earthing impedance rises with the frequency)
    voltages = res.tables["station_voltages"]
    rze = voltages[voltages["channel"] == "UE_70m"]["rZE_RMS_Ohm"].iloc[0]
    assert e["r_eff_rms"] == pytest.approx(rze / (abs(1 + 0.08j) * PROBE), rel=1e-6)


def test_reduction_factor_interpolated_between_measured_frequencies(tmp_path):
    w, res = _evaluate(tmp_path, r_per_order={m: demo.polar(0.4, 0.0) for m in (1, 5, 7, 11)})
    response = _injection_test(tmp_path, freq_orders=(1, 7))                 # only 50 and 350 Hz measured
    spectrum, eff = earthing.reduction_factor(res.tables, response)
    r5 = spectrum[(spectrum["channel"] == "UE_70m") & (spectrum["order"] == 5)].iloc[0]
    assert r5["injection_frequency"] == "interpoliert 50–350 Hz"
    z50, z350 = abs(1 + 0.08j) * PROBE, abs(1 + 0.56j) * PROBE
    f5 = r5["f_Hz"]
    assert r5["Z_E_injection_Ohm"] == pytest.approx(z50 + (z350 - z50) * (f5 - 50) / 300, rel=1e-3)
    without, _ = earthing.reduction_factor(res.tables, response, interpolate=False)
    assert np.isnan(without[(without["channel"] == "UE_70m") & (without["order"] == 5)]["r"].iloc[0])


def test_parallel_connection_against_earthing_measurement(tmp_path):
    w, res = _evaluate(tmp_path, lv_network=dict(R_LV=4.0, X_LV1=0.4))
    check, check_eff = earthing.check_lv_network(res.tables, _injection_test(tmp_path))
    remote = check[(check["channel"] == "UE_70m") & check["Z_LV_to_Z_E"].notna()]
    assert len(remote) == 3 and (remote["injection_comparison"] == "satisfied").all()
    assert (remote["parallel_check"] == "satisfied").all()        # against the fault test (station evaluation)
    for _, r in remote.iterrows():
        m = int(r["order"])
        z_lv = _truth(w, m)["Z_LV"]; z_lv = complex(z_lv["re"], z_lv["im"]) if isinstance(z_lv, dict) else z_lv
        assert r["Z_LV_to_Z_E"] == pytest.approx(abs(z_lv) / abs(1 + 0.08j * m), rel=0.03)
    assert check_eff[check_eff["channel"] == "UE_70m"]["injection_comparison"].iloc[0] == "satisfied"
    # earthing measurement ten times too large → LV network apparently smaller than the total earthing of the
    # earthing measurement
    (tmp_path / "x").mkdir()
    check2, _ = earthing.check_lv_network(res.tables, _injection_test(tmp_path / "x", factor=10.0))
    assert (check2[(check2["channel"] == "UE_70m") & check2["Z_LV_to_Z_E"].notna()]["injection_comparison"]
            == "below").all()


def test_without_earthing_measurement_or_empty_lv_network(tmp_path):
    w, res = _evaluate(tmp_path)                                          # simple PEN channel without position
    spectrum, eff = earthing.reduction_factor(res.tables, None)
    assert spectrum.empty and eff.empty
    check, check_eff = earthing.check_lv_network(res.tables, pd.DataFrame())
    assert check.empty and check_eff.empty
    assert not res.tables["station_lv_network"].empty                     # PEN without position: I_LV from this channel


def test_hints_reduction_and_parallel_connection():
    """Tables without the new columns (older notebooks): shield current ≈ 0 from r_S, LV network with the old
    status."""
    eff = pd.DataFrame([dict(channel="UE_70m", distance_match="equal", r_eff=0.06, r_eff_shield=0.95)])
    check = pd.DataFrame([dict(channel="UE_70m", distance_match="equal", f_Hz=50.02, parallel_check="violated"),
                          dict(channel="UE_70m", distance_match="equal", f_Hz=250.0, parallel_check="satisfied")])
    h = earthing.reduction_hints(eff, check)
    assert len(h) == 2 and "Schirmstrom nahezu null" in h[0] and "r_eff = 0,06" in h[0]
    assert "bei 50 Hz" in h[1] and "ferner" in h[1]
    assert earthing.reduction_hints(eff.assign(r_eff_shield=0.05), check.iloc[1:]) == []
    # r from the earth potential rise and r from the shield current differ by more than a factor of 2 (shield current
    # present)
    h = earthing.reduction_hints(eff.assign(r_eff=0.1, r_eff_shield=0.5, share_shield_eff=0.5))
    assert len(h) == 1 and "weitere Rückleiter" in h[0] and "0,2-Fache" in h[0]


def _c(x) -> complex:
    return complex(x["re"], x["im"]) if isinstance(x, dict) else complex(x)


# ---------------------------------------------------------------------------------------------- probe maximum
def test_probe_maximum_lv_network_and_naive_check(tmp_path):
    """The near probe shows more voltage than the remote one (different potential field) → the probe maximum takes
    it; the check against the fault test (Z_E,LV ≥ max(U_E)/I_F) depends on I_LV/I_F only."""
    w, res = _evaluate(tmp_path, probes={"UE_5m": 0.97, "UE_70m": 0.80}, lv_network=dict(R_LV=4.0, X_LV1=0.4))
    lv = res.tables["station_lv_network"]
    mx, remote = lv[lv["channel"] == "max(UE)"], lv[lv["channel"] == "UE_70m"]
    assert len(mx) == len(remote) == len(w["orders"]) and (mx["probe"] == "UE_5m").all()
    for _, r in mx.iterrows():
        t = _truth(w, int(r["order"]))
        z_lv, r_m, ze = _c(t["Z_LV"]), _c(t["r"]), _c(t["ZE"])
        assert r["Z_E_LV_Ohm"] == pytest.approx(0.97 * abs(z_lv), rel=0.02)
        assert r["rZE_fault_Ohm"] == pytest.approx(0.97 * abs(r_m * ze), rel=0.02)
        # second method: ratio from the currents, independent of the probe
        assert r["Z_LV_to_rZE_fault"] == pytest.approx(abs(z_lv) / abs(r_m * ze), rel=0.02)
        assert r["Z_LV_to_rZE_fault"] == pytest.approx(1.0 / r["share_I_LV"], rel=1e-9)
        assert r["parallel_check"] == "satisfied" and r["earth_current_check"] == "satisfied"
    f = remote.set_index("order")
    assert (mx.set_index("order")["Z_LV_to_rZE_fault"] - f["Z_LV_to_rZE_fault"]).abs().max() < 1e-9
    eff = res.tables["station_lv_network_eff"]
    e_max, e_5 = eff[eff["channel"] == "max(UE)"].iloc[0], eff[eff["channel"] == "UE_70m"].iloc[0]
    assert e_max["probe"] == "UE_5m"
    assert e_max["U_E_fault_eff_V"] == pytest.approx(e_5["U_E_fault_eff_V"] * 0.97 / 0.80, rel=0.02)
    assert e_max["parallel_check"] == "satisfied"


def test_reduction_factor_probe_maximum_against_farthest_probe(tmp_path):
    w, res = _evaluate(tmp_path, probes={"UE_5m": 0.97, "UE_70m": 0.80}, r_per_order=R_ORD)
    response = _injection_test(tmp_path)                                   # probe at 70 m, share PROBE = 0.93
    spectrum, eff = earthing.reduction_factor(res, response)
    mx = spectrum[spectrum["channel"] == "max(UE)"]
    assert (mx["probe"] == "UE_5m").all() and (mx["distance_match"] == "maximum").all()
    for _, r in mx[mx["r"].notna()].iterrows():
        assert r["r"] == pytest.approx(abs(R_ORD[int(r["order"])]) * 0.97 / PROBE, rel=0.02)
    remote = spectrum[spectrum["channel"] == "UE_70m"]
    assert (remote["distance_match"] == "equal").all()
    assert remote[remote["order"] == 1]["r"].iloc[0] == pytest.approx(abs(R_ORD[1]) * 0.80 / PROBE, rel=0.02)
    e = eff[eff["channel"] == "max(UE)"].iloc[0]
    assert e["probe"] == "UE_5m"
    num = den = 0.0                                                        # truth: sum of the harmonics
    for m in (1, 5, 7):
        x = _truth(w, m); ze = abs((1.0 + 1j * m * 0.08) * PROBE)
        num += (abs(R_ORD[m]) * 0.97 * abs(_c(x["ZE"])) * x["I_F"]) ** 2; den += (ze * x["I_F"]) ** 2
    assert e["r_eff"] == pytest.approx(math.sqrt(num / den), rel=0.01)
    # comparison table of earthing.compare(): the same rows of the probe maximum
    _, rat = earthing.compare(res.table("station_frequency"), response)
    v = rat[rat["channel"] == "max(UE)"].set_index("order")["ratio_fault"]
    assert (v - mx.set_index("order")["r"].reindex(v.index)).abs().max() < 1e-12


# parameters of the user for the classification and the relevance (invented values – groundfault has no defaults)
USER = dict(reference_current_A=100.0, U_Tp=100.0, F=2.5, r_typical=(0.3, 0.8))


def test_reduction_factor_classification_trend_and_assessment(tmp_path):
    w, res = _evaluate(tmp_path, r_per_order=R_ORD)
    response = _injection_test(tmp_path)
    # without parameters: r and its trend, but no classification and no relevance
    spectrum, eff = earthing.reduction_factor(res, response)
    e = eff[eff["channel"] == "max(UE)"].iloc[0]
    assert e["classification_r_50Hz"] == "–" and np.isnan(e["r_typical_min"]) and e["trend_r_vs_f"] == "falling"
    assert e["assessment_relevance"] == "–" and np.isnan(e["assessment_relevance_pct"])
    assert all(np.isnan(e[c]) for c in ("reference_current_A", "U_Tp_V", "F_factor", "F_times_U_Tp_V",
                                        "U_E_fault_at_reference_current_V", "U_E_injection_at_reference_current_V"))
    assert spectrum["U_E_fault_at_reference_current_V"].isna().all()
    assert spectrum["assessment_relevance_pct"].isna().all()
    h = earthing.reduction_hints(eff, earthing.check_lv_network(res, response)[0])
    assert len(h) == 1 and "nicht angegeben: reference_current_A, U_Tp, F." in h[0]
    # with the parameters of the user
    spectrum, eff = earthing.reduction_factor(res, response, **USER)
    e = eff[eff["channel"] == "max(UE)"].iloc[0]
    assert e["r_50Hz"] == pytest.approx(abs(R_ORD[1]) * 0.93 / PROBE, rel=0.02)
    assert e["classification_r_50Hz"] == "typical" and (e["r_typical_min"], e["r_typical_max"]) == (0.3, 0.8)
    assert e["trend_r_vs_f"] == "falling" and e["trend_orders"] == "1, 5, 7"
    f = [_truth(w, m)["I_F"] for m in (1, 5, 7)]
    b = np.polyfit(np.log([1, 5, 7]), np.log([abs(R_ORD[m]) for m in (1, 5, 7)]), 1)[0]   # log(c·m): same slope
    assert e["exponent_r_vs_f"] == pytest.approx(b, abs=0.02)
    # voltage at the reference current (100 A): second method via the truth per order
    i_all = math.sqrt(sum(_truth(w, m)["I_F"] ** 2 for m in w["orders"]))
    i_eff = math.sqrt(sum(x ** 2 for x in f))
    u_f = math.sqrt(sum((abs(R_ORD[m]) * abs(_c(_truth(w, m)["ZE"])) * 0.93 * _truth(w, m)["I_F"]) ** 2
                        for m in (1, 5, 7))) / i_eff * 100.0
    u_m = math.sqrt(sum((abs((1.0 + 1j * m * 0.08) * PROBE) * _truth(w, m)["I_F"]) ** 2
                        for m in (1, 5, 7))) / i_eff * 100.0
    assert (e["reference_current_A"], e["U_Tp_V"], e["F_factor"], e["F_times_U_Tp_V"]) == (100.0, 100.0, 2.5, 250.0)
    assert e["U_E_fault_at_reference_current_V"] == pytest.approx(u_f, rel=0.02)
    assert e["U_E_injection_at_reference_current_V"] == pytest.approx(u_m, rel=0.01)
    assert e["assessment_relevance_pct"] == pytest.approx(100 * (u_m - u_f) / 250.0, rel=0.03)
    assert e["assessment_relevance"] == "unchanged"                          # both below F·U_Tp = 250 V
    # per order: spectrum as measured, scaled to the reference current
    r1 = spectrum[(spectrum["channel"] == "max(UE)") & (spectrum["order"] == 1)].iloc[0]
    assert r1["U_E_injection_at_reference_current_V"] == pytest.approx(
        abs((1 + 0.08j) * PROBE) * f[0] * 100.0 / i_all, rel=0.01)
    _, eff2 = earthing.reduction_factor(res, response, **dict(USER, U_Tp=0.5 * (u_f + u_m) / 2.5))   # F·U_Tp between
    assert eff2.iloc[0]["assessment_relevance"] == "relevant"
    _, eff3 = earthing.reduction_factor(res, response, relevance_threshold_pct=60.0, **USER)
    assert eff3.iloc[0]["assessment_relevance"] == "negligible"
    # tables only (no result object): the given reference current applies
    _, eff4 = earthing.reduction_factor(res.tables, response, reference_current_A=50.0)
    assert eff4.iloc[0]["U_E_fault_at_reference_current_V"] == pytest.approx(u_f / 2.0, rel=0.02)
    assert eff4.iloc[0]["assessment_relevance"] == "–"                        # U_Tp and F not given
    assert earthing.reduction_hints(eff, earthing.check_lv_network(res, response)[0]) == []


def test_reduction_factor_from_result_file_with_limits(tmp_path):
    from groundfault import Settings, load_result
    p = str(tmp_path / "st.cfg")
    w = demo.make_station_recording(p, duration=8.0, t_on=2.0, t_off=5.5, r_per_order=R_ORD)
    b = w["intervals"]
    res = evaluate(open_recording(p), Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]),
                                                tuple(b["post_fault"])),
                   Settings(ires_limits=(40.0, 70.0), u_tp=80.0, f_factor=2.5))       # invented limits
    file = load_result(res.save_json(str(tmp_path / "e.json")))
    assert (file.settings.ires_limits, file.settings.u_tp, file.settings.f_factor) == ((40.0, 70.0), 80.0, 2.5)
    response = _injection_test(tmp_path)
    _, eff = earthing.reduction_factor(file, response)
    assert eff.iloc[0]["reference_current_A"] == 70.0 and eff.iloc[0]["F_times_U_Tp_V"] == 200.0
    _, eff = earthing.reduction_factor(file, response, F=3.0)                     # an argument wins
    assert eff.iloc[0]["F_times_U_Tp_V"] == 240.0
    # a result file without limits (evaluated with the defaults) gives no reference current, U_Tp or F
    res = evaluate(open_recording(p), Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]),
                                                tuple(b["post_fault"])))
    file = load_result(res.save_json(str(tmp_path / "e0.json")))
    assert (file.settings.ires_limits, file.settings.u_tp, file.settings.f_factor) == ((), None, None)
    _, eff = earthing.reduction_factor(file, response)
    assert eff.iloc[0]["assessment_relevance"] == "–" and np.isnan(eff.iloc[0]["reference_current_A"])


def test_hints_below_typical_range_and_lv_network_against_earthing_measurement(tmp_path):
    """Earthing measurement ten times too high: r below the typical range (methodical error), LV network below Z_E of
    the earthing measurement, but satisfied against the fault test → the contradiction lies with the earthing
    measurement."""
    w, res = _evaluate(tmp_path, lv_network=dict(R_LV=4.0, X_LV1=0.4), r_per_order=R_ORD)
    response = _injection_test(tmp_path, factor=10.0)
    spectrum, eff = earthing.reduction_factor(res, response, **USER)
    e = eff[eff["channel"] == "max(UE)"].iloc[0]
    assert e["classification_r_50Hz"] == "below"
    check, check_eff = earthing.check_lv_network(res, response)
    mx = check[(check["channel"] == "max(UE)") & check["Z_LV_to_Z_E"].notna()]
    assert len(mx) == 3 and (mx["injection_comparison"] == "below").all()
    assert (mx["parallel_check"] == "satisfied").all()
    assert check_eff[check_eff["channel"] == "max(UE)"]["injection_comparison"].iloc[0].startswith("below")
    h = earthing.reduction_hints(eff, check)
    assert len(h) == 3
    assert "unter dem üblichen Bereich 0,3–0,8" in h[0] and "methodischer Fehler" in h[0] and "F·U_Tp = 250 V" in h[0]
    assert "Sondenmaximum (UE_70m)" in h[0]
    # the shield current explains r ≈ 0.5, the earth potential rise only r ≈ 0.05 → earthing measurement too high (or
    # further return conductors)
    assert "0,1-Fache" in h[1] and "zu hoch" in h[1]
    assert "Ortsnetz" in h[2] and "liegt bei der Erdungsmessung" in h[2] and "50, 250, 350 Hz" in h[2]


@pytest.mark.parametrize("r_ord,expected", [
    ({m: demo.polar(0.98, -2.0) for m in (1, 5, 7, 11)}, ("über dem üblichen Bereich", "Schirmstrom nahezu null")),
    ({1: demo.polar(0.3, 0.0), 5: demo.polar(0.5, 0.0), 7: demo.polar(0.6, 0.0), 11: demo.polar(0.65, 0.0)},
     ("steigt mit der Frequenz",)),
])
def test_hints_shield_without_current_and_rising_trend(tmp_path, r_ord, expected):
    w, res = _evaluate(tmp_path, r_per_order=r_ord)
    spectrum, eff = earthing.reduction_factor(res, _injection_test(tmp_path), r_typical=USER["r_typical"])
    h = earthing.reduction_hints(eff)
    for text in expected:
        assert any(text in x for x in h), (text, h)
    if "Schirmstrom nahezu null" in expected:
        assert eff.iloc[0]["share_shield_eff"] == pytest.approx(abs(1 - r_ord[1]), rel=0.15)


# ---------------------------------------------------------------------------------------------- figures
def test_figures_reduction_factor_and_lv_network(tmp_path):
    from groundfault import report, interactive
    w, res = _evaluate(tmp_path, probes={"UE_5m": 0.97, "UE_70m": 0.80}, lv_network=dict(R_LV=4.0, X_LV1=0.4),
                       r_per_order=R_ORD)
    response = _injection_test(tmp_path)
    import matplotlib.pyplot as plt
    spectrum, eff0 = earthing.reduction_factor(res, response)                   # no range given: no grey bar
    f0 = report.reduction_factor(spectrum, eff0)
    texts = [t.get_text() for ax in f0.axes if ax.get_legend() for t in ax.get_legend().get_texts()]
    assert not any("üblich bei 50 Hz" in t for t in texts)
    assert not any("üblich bei 50 Hz" in (t.name or "") for t in interactive.reduction_factor(spectrum, eff0).data)
    f1 = report.reduction_factor(spectrum, eff0, r_typical=(0.25, 0.75))
    texts = [t.get_text() for t in f1.axes[0].get_legend().get_texts()]
    assert any("üblich bei 50 Hz (0,25–0,75)" in t for t in texts)              # a range given to the figure
    plt.close(f0); plt.close(f1)
    spectrum, eff = earthing.reduction_factor(res, response, r_typical=USER["r_typical"])
    check, _ = earthing.check_lv_network(res, response)
    f = report.reduction_factor(spectrum, eff)
    assert len(f.axes) == 2
    texts = [t.get_text() for ax in f.axes if ax.get_legend() for t in ax.get_legend().get_texts()]
    assert any(t.startswith("Sondenmaximum (UE_5m) ↔ Erdungsmessung ID 1") for t in texts)
    assert any("üblich bei 50 Hz (0,3–0,8)" in t for t in texts)               # the range of the classification
    assert not any(t.startswith("UE_70m") for t in texts)                 # default: only the probe maximum
    assert len(report.reduction_factor(spectrum, eff, impedances=False).axes) == 1
    texts = [t.get_text() for t in report.reduction_factor(spectrum, eff, probes="all").axes[0].get_legend()
             .get_texts()]
    assert any(t.startswith("UE_70m (70 m)") for t in texts) and any(t.startswith("Sondenmaximum") for t in texts)
    texts = [t.get_text() for t in report.reduction_factor(spectrum, eff, remote_probes_only=True).axes[0].get_legend()
             .get_texts()]
    assert any(t.startswith("UE_70m") for t in texts) and not any(t.startswith("Sondenmaximum") for t in texts)
    f = report.lv_network(res.tables["station_lv_network"], check)
    texts = [t.get_text() for t in f.axes[0].get_legend().get_texts()]
    assert any("Sondenmaximum (UE_5m)" in t for t in texts) and any("Erdungsmessung ID 1" in t for t in texts)
    fi = interactive.reduction_factor(spectrum, eff)
    names = [t.name for t in fi.data]
    assert names[0].startswith("üblich bei 50 Hz (0,3–0,8)")
    assert any(n.startswith("Sondenmaximum (UE_5m) ↔") for n in names) and any("U<sub>E</sub>/I<sub>F</sub>" in n
                                                                                for n in names)
    assert {t.line.color for t in fi.data if t.name.startswith("Sondenmaximum")} == {report.COLOR_MAX}
    fo = interactive.lv_network(res.tables["station_lv_network"], check)
    assert any("Sondenmaximum (UE_5m)" in (t.name or "") for t in fo.data)
