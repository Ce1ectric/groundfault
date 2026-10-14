# -*- coding: utf-8 -*-
"""End-to-end evaluation of synthetic recordings with a known solution."""
import json
import math
import os
import re

import numpy as np
import pytest

from groundfault import (Intervals, Settings, campaign, corrections, demo, detect_roles, i18n, open_recording,
                         evaluate, write_comtrade)
from groundfault.evaluation import load_result

#: steady state, pre-fault and post-fault of the 8-s demo recordings (fault from 2 s to 6 s)
INTERVALS_8S = Intervals((2.6, 5.9), (0.2, 1.8), (7.0, 7.8))
#: numbered references to equations, tables or sections of a document must not appear in any output
_NUMBERED_REFERENCE = re.compile(r"\b(?:Gl|Tab|Abschn|Eq|Table)\.?\s*\d")


def _intervals(w):
    b = w["intervals"]
    return Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]), tuple(b["post_fault"]))


def _texts(res):
    """All texts of a result shown to the user (plausibility table, assessment quantities, hints)."""
    pr = res.table("plausibility")
    aq = res.table("assessment_quantities")
    return (list(pr["check"]) + list(pr["value"]) + list(pr["comment"]) + list(aq["description"])
            + list(aq["equation"]) + list(res.hints))


def test_assessment_quantities_substation(demo_results):
    for Z, (res, w, _, _) in demo_results.items():
        v = res.values
        assert v["IG"] == pytest.approx(w["IG"], rel=2e-3), Z
        assert v["Iw"] == pytest.approx(w["Iw"], abs=0.05), Z
        assert v["Iv"] == pytest.approx(w["Iv"], abs=0.05), Z
        assert v["IRES"] == pytest.approx(w["IRES"], rel=3e-3), Z           # max window + noise
        assert v["IH_total"] == pytest.approx(w["IH"], rel=0.01), Z
        for m, s in w["harmonic_sources"].items():
            assert abs(v["I_phasors"][int(m)]) == pytest.approx(s["I"], rel=2e-3), (Z, m)


def test_polarity_corrected(demo_results):
    res, w, _, _ = demo_results[2.5]                  # generated with a reversed clamp
    assert res.polarity == -1 and res.values["Iw"] > 0
    assert any("verpolt" in h for h in res.hints)
    assert demo_results[0.0][0].polarity == 1


def test_voltage_analysis(demo_results):
    res, w, _, _ = demo_results[0.0]
    k = res.table("voltage_metrics").set_index("interval")
    assert k.at["pre_fault", "UH5g_V"] == pytest.approx(w["UH5g_pre"], rel=2e-3)
    assert k.at["pre_fault", "UH7m_V"] == pytest.approx(w["UH7m_pre"], rel=2e-3)
    for s in ("UTHD12_pct", "UTHD23_pct", "UTHD31_pct"):
        assert k.at["pre_fault", s] == pytest.approx(w["UTHD_LL_pre_pct"], rel=0.01)
    assert k.at["fault", "Uzero_H1_V"] == pytest.approx(w["U0_fault"], rel=1e-3)
    assert res.values["faulted_phase"] == "L3"


def test_coil_currents(demo_results):
    res, w, _, _ = demo_results[0.0]
    sp = res.table("coil_currents")
    assert np.allclose(sp["H1_A"], w["coils_H1_A"], rtol=1e-3)


def test_plausibility_ok(demo_results):
    res = demo_results[0.0][0]
    pr = res.table("plausibility").set_index("check")
    assert pr.at["Netzfrequenz f1", "status"] == "OK"
    assert pr.at["Fehlerbehafteter Leiter", "status"] == "OK"
    assert pr.at["Stationarität I_H1 im Bereich", "status"] == "OK"
    assert not any(s.startswith("Sättigung") for s in pr.index)
    # German output: decimal comma, no references to equation numbers
    assert re.fullmatch(r"\d+,\d{4} Hz \(Vergleich \d+,\d{4} Hz\)", pr.at["Netzfrequenz f1", "value"])
    assert not any(_NUMBERED_REFERENCE.search(t) for t in _texts(res))


def test_active_current_increase_excluded(demo_series):
    """The interval includes the active residual current increase (4.6–5.4 s): it is detected and left out – the
    max window lies in the undisturbed state, the stationarity check over the reference is OK, a plausibility row
    and a hint report the excluded range."""
    folder, truth = demo_series
    rec = open_recording(os.path.join(str(folder), truth[0]["file"]))
    res = evaluate(rec, Intervals((2.6, 5.9), (0.2, 1.8), (7.0, 8.8)))
    assert res.values["IRES"] == pytest.approx(truth[0]["IRES"], rel=3e-3)               # not the step
    assert not 4.6 <= res.t_max_window <= 5.4
    pr = res.table("plausibility").set_index("check")
    assert pr.at["Stationarität I_H1 im Bereich", "status"] == "OK"
    line = pr.loc["Gestörte Zustände im stationären Bereich"]
    assert line["status"] == "NOTE" and "Wattreststromerhöhung 4,6–5,4 s" in line["value"]
    assert any(h.startswith("Gestörte Zustände ausgeblendet: Wattreststromerhöhung 4,6–5,4 s") for h in res.hints)
    seg = res.table("steady_state_segments")
    assert list(seg["state"]) == ["reference", "active increase", "reference"]
    assert list(seg["used"]) == [True, False, True]
    assert seg.loc[1, "d_Iw_A"] == pytest.approx(15.0, abs=0.2)
    assert res.reference_windows.sum() == 12 and len(res.steady_state.t_mid) == 16


def test_active_current_increase_not_excluded(demo_series):
    """exclude_disturbances=False: the predecessor's behaviour – the max window lies in the step, the stationarity
    check warns – and the plausibility row reports the disturbance as not excluded."""
    folder, truth = demo_series
    rec = open_recording(os.path.join(str(folder), truth[0]["file"]))
    res = evaluate(rec, Intervals((2.6, 5.9), (0.2, 1.8), (7.0, 8.8)), Settings(exclude_disturbances=False))
    pr = res.table("plausibility").set_index("check")
    assert pr.at["Stationarität I_H1 im Bereich", "status"] == "WARNING"
    assert "Wirkanteil ändert sich" in pr.at["Stationarität I_H1 im Bereich", "comment"]
    assert res.values["IRES"] == pytest.approx(truth[0]["IRES_active_step"], rel=3e-3)   # max window in the step
    assert pr.at["Gestörte Zustände im stationären Bereich", "status"] == "WARNING"
    assert any("nicht ausgeblendet (exclude_disturbances=False)" in h for h in res.hints)
    assert res.reference_windows.sum() == 16


def test_coil_adjustment_distinguished_from_active_current_increase(tmp_path):
    """Step of the detuning current (coil adjusted) at a constant active current: warning with the cause
    "reactive component" instead of an active-current increase; ΔIv is quantified."""
    w = demo.make_substation_recording(str(tmp_path / "reactive.cfg"), 0.0, duration=8.0, active_step=None,
                                       reactive_step=(4.6, 5.4, -12.0))
    res = evaluate(open_recording(str(tmp_path / "reactive.cfg")), INTERVALS_8S)
    pr = res.table("plausibility").set_index("check")
    line = pr.loc["Stationarität I_H1 im Bereich"]
    assert line["status"] == "WARNING" and "Blindanteil" in line["comment"]
    dIv = float(line["value"].split("ΔIv")[1].split("A")[0].replace(",", "."))     # German decimal comma
    assert dIv == pytest.approx(12.0, abs=0.5)
    assert any("Spulenverstellung" in h for h in res.hints)
    # max window: the largest I_RES lies outside the step (|Iv| drops there from 25 to 13 A)
    assert res.values["IRES"] == pytest.approx(w["IRES"], rel=3e-3)


def test_harmonic_scaling(demo_series):
    folder, truth = demo_series
    w = truth[0]
    rec = open_recording(os.path.join(str(folder), w["file"]))
    res = evaluate(rec, _intervals(w), Settings(u_thd95_percent=2.5, thd_reference="pre_fault"))
    v = res.values
    assert v["UTHD_meas"] == pytest.approx(w["UTHD_LL_pre_pct"], rel=0.01)
    assert v["IH_scaled"] == pytest.approx(v["IH_total"] * 2.5 / v["UTHD_meas"], rel=1e-9)
    assert v["IRES_scaled"] == pytest.approx(math.hypot(v["IG"], v["IH_scaled"]), rel=1e-9)
    eq = res.table("assessment_quantities").set_index("quantity")["equation"]
    assert eq["IH_scaled"] == "I_H,scaled = I_H·U_95/U_meas" and eq["IH_total"] == "I_H = √(I_RES² − I_G²)"


def test_station(tmp_path):
    w = demo.make_station_recording(str(tmp_path / "st.cfg"))
    rec = open_recording(str(tmp_path / "st.cfg"))
    res = evaluate(rec, _intervals(w))
    df = res.table("station_voltages").set_index("channel")
    assert df.at["UE_70m", "V_per_100A_RMS"] == pytest.approx(w["V_per_100A"], rel=2e-3)
    for m in (1, 5, 7):
        zc = w["orders"][m]["rZE_probe"]                     # truth: r·Z_E,m × share of the probe
        assert df.at["UE_70m", "rZE_H%d_Ohm" % m] == pytest.approx(abs(zc), rel=3e-3)
        assert df.at["UE_70m", "rZE_H%d_angle_deg" % m] == pytest.approx(np.degrees(np.angle(zc)), abs=0.3)
    k = res.values["station"]
    assert k["F_UE_to_UT"] == pytest.approx(w["F"], rel=2e-3)
    s = res.table("station_currents").set_index("channel")
    assert s.at["IS", "r_H1_complex"] == pytest.approx(abs(w["r"]), rel=2e-3)
    assert np.isnan(df.loc["UE_70m"].get("rZE_H3_Ohm", np.nan))     # no 150-Hz current → no quotient
    meta = json.loads(json.dumps(res.result_set["station_frequency"], allow_nan=False))   # traceable in the file
    assert meta["inception"]["f_fault_source"] == "U_L1-L2" and meta["t_fault_inception_s"] == pytest.approx(1.5, abs=0.03)


def test_transformer(tmp_path):
    w = demo.make_transformer_recording(str(tmp_path / "tr.cfg"))
    rec = open_recording(str(tmp_path / "tr.cfg"))
    res = evaluate(rec, _intervals(w))
    t = res.table("transformer_power")
    vf = t[t["interval"] == "pre_fault"].set_index("order")
    for m, s in w["S"].items():
        m = int(m)
        assert vf.at[m, "P_kW"] == pytest.approx(s["P_kW"], abs=0.02 + 1e-4 * abs(s["P_kW"]))
        assert vf.at[m, "Q_kvar"] == pytest.approx(s["Q_kvar"], abs=0.02 + 1e-4 * abs(s["Q_kvar"]))
    fe = t[t["interval"] == "fault"].set_index("order")
    assert fe.at[1, "I_zero_A"] == pytest.approx(w["I_zero_fault_A"], rel=2e-3)


def test_result_file_round_trip(demo_results, tmp_path):
    res, w, path, _ = demo_results[5.0]
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    assert d["format"] == "groundfault-result" and d["version"] == 4
    e = load_result(path)
    assert e.values["IRES"] == pytest.approx(res.values["IRES"])
    assert set(res.tables) <= set(e.tables) | {"voltage_pre_fault", "voltage_fault", "voltage_post_fault"}
    assert e.z_fault_ohm == 5.0
    bw = e.tables["assessment_quantities"].set_index("quantity")
    assert bw.at["IH5", "measured_value"] == pytest.approx(res.table("assessment_quantities").set_index("quantity").at["IH5", "measured_value"])
    (tmp_path / "other.json").write_text('{"format": "other"}', encoding="utf-8")
    with pytest.raises(ValueError, match="keine Ergebnisdatei von groundfault"):
        load_result(str(tmp_path / "other.json"))


def test_sampling_rate_too_low(tmp_path):
    rec_path = str(tmp_path / "inst.cfg")
    demo.make_substation_recording(rec_path, 0.0, duration=4.0, t_on=1.0, t_off=3.0, active_step=None)
    demo.rms_file_from_instantaneous(rec_path, str(tmp_path / "rms.cfg"))
    with pytest.raises(ValueError, match="evaluate_rms_recording"):
        evaluate(open_recording(str(tmp_path / "rms.cfg")), Intervals((1.5, 2.8)))


def test_check_intervals():
    with pytest.raises(ValueError):
        Intervals((5.0, 4.0)).check(10.0)
    assert Intervals((2, 4), (3, 5)).check(10.0)          # overlap → hint


def test_decaying_dc_component_detected(tmp_path):
    """Decaying DC component after fault inception (coil DC, τ = 0.3 s): an interval that starts early puts the
    max window on the DC component (I_RES too high) → warning with the share; later start: OK."""
    w = demo.make_substation_recording(str(tmp_path / "dc.cfg"), 0.0, duration=8.0, active_step=None, dc_offset=(150.0, 0.3))
    rec = open_recording(str(tmp_path / "dc.cfg"))
    early = evaluate(rec, Intervals((2.1, 5.8), (0.2, 1.8), (7.0, 7.8)))
    pr = early.table("plausibility").set_index("check")
    assert pr.at["Niederfrequenter Anteil I_RES (< f1/2)", "status"] == "WARNING"
    assert early.values["IRES"] > 1.01 * w["IRES"] and any("Gleichanteil" in h for h in early.hints)
    late = evaluate(rec, Intervals((4.2, 5.8), (0.2, 1.8), (7.0, 7.8)))
    pr = late.table("plausibility").set_index("check")
    assert pr.at["Niederfrequenter Anteil I_RES (< f1/2)", "status"] == "OK"
    assert late.values["IRES"] == pytest.approx(w["IRES"], rel=3e-3)


def test_saturation_detected(tmp_path):
    """Fault current clipped at 80 % of its peak (flat tops) → saturation warning for this channel only."""
    demo.make_substation_recording(str(tmp_path / "ok.cfg"), 0.0, duration=8.0, active_step=None)
    with open_recording(str(tmp_path / "ok.cfg")) as q:
        x = q.read(0, q.n)
        main = detect_roles(q.channel_names, q.units).main("i_res")
        limit = 0.8 * np.nanmax(np.abs(x[int(3.0 * q.fs):int(5.0 * q.fs), main.index]))
        signals = {nm: (unit, np.clip(x[:, j], -limit, limit) if j == main.index else x[:, j])
                   for j, (nm, unit) in enumerate(zip(q.channel_names, q.units))}
        write_comtrade(str(tmp_path / "clipped.cfg"), signals, q.fs, t_start=q.t_start)
    pr = evaluate(open_recording(str(tmp_path / "clipped.cfg")), INTERVALS_8S).table("plausibility").set_index("check")
    assert [s for s in pr.index if s.startswith("Sättigung")] == ["Sättigung %s" % main.short]
    assert pr.at["Sättigung %s" % main.short, "status"] == "WARNING"


def test_corrections_check_follows_campaign_layout(tmp_path):
    """The plausibility check names the corrections file the corrections came from – notes/corrections.csv in an
    English-layout campaign (0_Notizen/Korrekturen.csv in a German one, see test_corrections.py); corrections set by
    hand name the file of the layout."""
    camp = tmp_path / "campaigns" / "2026-01-15_Demo"
    (camp / "raw" / "SUB").mkdir(parents=True)
    (camp / "notes").mkdir()
    (camp / "notes" / "corrections.csv").write_text("file;channel;factor;role;main_channel;remark\n"
                                                    "SUB_*;ISp21;3;;;clamp on 1 of 3 conductors\n",
                                                    encoding="utf-8-sig")
    cfg = str(camp / "raw" / "SUB" / "SUB_0_10_000kHz.cfg")
    demo.make_substation_recording(cfg, 0.0, duration=8.0, active_step=None)
    rec = open_recording(cfg)
    corrections.load(str(camp)).apply(rec)
    res = evaluate(rec, INTERVALS_8S)
    pr = res.table("plausibility").set_index("check")
    assert pr.at["Korrekturen (notes/corrections.csv)", "status"] == "CORRECTED"
    assert pr.at["Korrekturen (notes/corrections.csv)", "value"] == "ISp21 × 3"
    assert any(h.startswith("Korrektur angewendet: ISp21 × 3 (notes/corrections.csv, Zeile 2)") for h in res.hints)
    with i18n.language("en"):
        res_en = evaluate(rec, INTERVALS_8S)
    pr_en = res_en.table("plausibility").set_index("check")
    assert pr_en.at["Corrections (notes/corrections.csv)", "comment"].startswith("measured values corrected")
    by_hand = open_recording(cfg)
    by_hand.set_correction("ISp21", 0.5)
    res = evaluate(by_hand, INTERVALS_8S)
    assert "Korrekturen (notes/corrections.csv)" in set(res.table("plausibility")["check"])
    assert "Korrektur angewendet: ISp21 × 0,5 (manuell)" in res.hints


def test_messages_in_english(demo_series):
    """English output: plausibility checks, descriptions, hints and summary in English with decimal points; no
    references to equation numbers."""
    folder, truth = demo_series
    w = [x for x in truth if x["Z_F"] == 2.5][0]                       # clamp with reversed polarity
    rec = open_recording(os.path.join(str(folder), w["file"]))
    with i18n.language("en"):
        res = evaluate(rec, _intervals(w), z_fault_ohm=2.5)
        summary = res.summary()
    pr = res.table("plausibility").set_index("check")
    assert pr.at["Network frequency f1", "status"] == "OK"
    assert re.fullmatch(r"\d+\.\d{4} Hz \(comparison \d+\.\d{4} Hz\)", pr.at["Network frequency f1", "value"])
    assert pr.at["Faulted phase", "status"] == "OK"
    assert pr.at["Stationarity of I_H1 in the interval", "comment"] == "fundamental component constant in the interval"
    assert pr.at["Polarity of the fault current", "status"] == "CORRECTED"
    assert pr.at["Polarity of the fault current", "comment"] == "current phasors rotated by 180° (clamp reversed?)"
    assert "RMS ↔ √ΣX² (orders 1,3,5,7)" in pr.index
    assert any(h.startswith("Iw was negative → current measurement reversed") for h in res.hints)
    aq = res.table("assessment_quantities").set_index("quantity")
    assert aq.at["IRES", "description"] == "residual earth-fault current (max 200-ms window, steady state)"
    assert aq.at["IH5", "description"].startswith("harmonic of order 5 (")
    assert aq.at["Iw", "equation"] == "Iw = I_H1·cos(φ_U0 − φ_I1)"
    assert summary.splitlines()[0].startswith("Measurement: ") and summary.splitlines()[1].startswith("Max window: ")
    assert not any(_NUMBERED_REFERENCE.search(t) for t in _texts(res))
    with i18n.language("en"), pytest.raises(ValueError, match="is shorter than one window"):
        evaluate(rec, Intervals((2.6, 2.7)))


def test_campaign_messages(demo_results):
    """Consistency checks and the resistive approach in English and German; overview without equation numbers."""
    files = {"M%g" % Z: load_result(p) for Z, (_, _, p, _) in sorted(demo_results.items())}
    with i18n.language("en"):
        k = campaign.consistency(files).set_index("check")
        comment = campaign.resistive_approach(180.0, 30.0, 2.0, 0.25, 0.75, U_Tp=100.0, F=1.5)["comment"]
        with pytest.raises(ValueError, match="give I_res_max, or U_Tp and F \\(missing: U_Tp, F\\)"):
            campaign.resistive_approach(180.0, 30.0, 2.0, 0.25, 0.75)
    assert k.at["I_G equal in all measurements", "status"] == "OK"
    assert "(span " in k.at["I_G equal in all measurements", "value"]
    assert k.at["I_H decreases with Z_F", "status"] == "OK"
    assert k.at["Faulted phase", "value"] == "L3"
    assert "l_lim = 1.48 km" in comment and "equivalent-source method" in comment
    k = campaign.consistency(files).set_index("check")
    assert k.at["Fehlerleiter", "comment"] == "alle Messungen im selben Leiter"
    comment = campaign.resistive_approach(180.0, 30.0, 2.0, 0.25, 0.75, I_res_max=75.0)["comment"]
    assert "l_Grenz = 1,48 km" in comment and not _NUMBERED_REFERENCE.search(comment)
    with pytest.raises(ValueError, match="fehlt: F\\)"):
        campaign.resistive_approach(180.0, 30.0, 2.0, 0.25, 0.75, U_Tp=100.0)
    u = campaign.overview(files)
    assert "IH in A" in u.columns and not any(_NUMBERED_REFERENCE.search(c) for c in u.columns)
    assert list(u["IH in A"]) == pytest.approx([files[n].values["IH_total"] for n in files])


def test_message_catalog_complete():
    """Every message of the evaluation and campaign modules exists in English and German."""
    for lang in ("en", "de"):
        assert [m for m in i18n.missing_keys(lang) if m.startswith(("evaluation.", "campaign."))] == []


@pytest.mark.parametrize("option,former,new", [("thd_reference", "mittel", "mean"),
                                               ("f1_method", "spektral", "spectral"),
                                               ("window", "rechteck", "rectangular"), ("dc", "mittel", "mean"),
                                               ("transformer_voltage", "hs", "hv")])
def test_settings_reject_former_values(option, former, new):
    """Text options of the settings take their English values: a former value raises at once and names the current
    one (before, thd_reference="mittel" raised a bare KeyError during the evaluation, transformer_voltage="hs" and
    f1_method="spektral" were misread)."""
    with pytest.raises(ValueError, match=r"^%s='%s' ist nicht zulässig – zulässig: .*\('%s' ist der frühere Name "
                                         r"von '%s'\)$" % (option, former, former, new)):
        Settings(**{option: former})
    assert getattr(Settings(**{option: new}), option) == new


def test_settings_unknown_values_and_later_changes(demo_series):
    with i18n.language("en"), pytest.raises(ValueError, match=r"^thd_reference='average' is not allowed – allowed: "
                                                               r"'pre_fault', 'post_fault', 'mean'$"):
        Settings(thd_reference="average")
    s = Settings(window="hann_periodic", dc=None, f1_method="spectral", thd_reference="post_fault",
                 transformer_voltage="hv")
    assert (s.window, s.dc) == ("hann_periodic", None)
    folder, truth = demo_series
    rec = open_recording(os.path.join(str(folder), truth[0]["file"]))
    s = Settings()
    s.thd_reference = "mittel"                     # changed after the construction: checked by evaluate
    with pytest.raises(ValueError, match="'mittel' ist der frühere Name von 'mean'"):
        evaluate(rec, _intervals(truth[0]), s)
    s = Settings()
    s.pq_safety_factor = 0.0                       # the factor as well
    with pytest.raises(ValueError, match="pq_safety_factor muss ein Faktor > 0"):
        evaluate(rec, _intervals(truth[0]), s)


def test_settings_contain_no_limits_or_margins():
    """groundfault has no presets: no limits of the residual current, no U_Tp, no F, no uncertainty margins and a
    neutral PQ factor – each user defines them."""
    s = Settings()
    assert (s.ires_limits, s.u_tp, s.f_factor) == ((), None, None)
    assert (s.uncertainty_I, s.uncertainty_U, s.pq_safety_factor) == (0.0, 0.0, 1.0)
    s = Settings(ires_limits=[50, 100], u_tp=100, f_factor=2.5, uncertainty_I=0.03, uncertainty_U=0.02)   # invented
    assert s.ires_limits == (50.0, 100.0) and (s.u_tp, s.f_factor) == (100, 2.5)


@pytest.mark.parametrize("kw,text", [(dict(ires_limits=100.0), "ires_limits muss eine Folge"),
                                     (dict(ires_limits="100"), "ires_limits muss eine Folge"),
                                     (dict(ires_limits=(50.0, -1.0)), "ires_limits muss eine Folge"),
                                     (dict(ires_limits=(50.0, float("nan"))), "ires_limits muss eine Folge"),
                                     (dict(u_tp=0.0), "u_tp muss eine Zahl > 0 oder None"),
                                     (dict(f_factor=-2.0), "f_factor muss eine Zahl > 0 oder None"),
                                     (dict(f_factor=True), "f_factor muss eine Zahl > 0 oder None"),
                                     (dict(uncertainty_I=1.5), "uncertainty_I muss ein relativer Zuschlag"),
                                     (dict(uncertainty_U=-0.01), "uncertainty_U muss ein relativer Zuschlag"),
                                     (dict(uncertainty_U=None), "uncertainty_U muss ein relativer Zuschlag"),
                                     (dict(pq_safety_factor=0.0), "pq_safety_factor muss ein Faktor > 0"),
                                     (dict(pq_safety_factor=-1.2), "pq_safety_factor muss ein Faktor > 0"),
                                     (dict(pq_safety_factor=None), "pq_safety_factor muss ein Faktor > 0"),
                                     (dict(pq_safety_factor=float("inf")), "pq_safety_factor muss ein Faktor > 0")])
def test_settings_reject_invalid_limits_and_margins(kw, text):
    with pytest.raises(ValueError, match=text):
        Settings(**kw)
    with i18n.language("en"), pytest.raises(ValueError, match="must be"):
        Settings(**kw)


def test_uncertainty_margins_of_the_user(demo_series):
    """Without margins the assessment value is the measured value; with the margins of the user (invented here)
    currents are increased by m_I and voltages decreased by m_U – also in the scaled rows."""
    folder, truth = demo_series
    w = truth[0]
    rec = open_recording(os.path.join(str(folder), w["file"]))
    a0 = evaluate(rec, _intervals(w), Settings(u_thd95_percent=2.5)).table("assessment_quantities")
    a0 = a0.set_index("quantity")
    assert (a0["assessment"] == a0["measured_value"]).all()
    a = evaluate(rec, _intervals(w), Settings(u_thd95_percent=2.5, uncertainty_I=0.03, uncertainty_U=0.02))
    v, a = a.values, a.table("assessment_quantities").set_index("quantity")
    assert a.at["IRES", "assessment"] == pytest.approx(1.03 * a.at["IRES", "measured_value"])
    assert a.at["UH1n", "assessment"] == pytest.approx(0.98 * a.at["UH1n", "measured_value"])
    assert a.at["UTHD_meas", "assessment"] == pytest.approx(0.98 * v["UTHD_meas"])
    assert a.at["IH_scaled", "assessment"] == pytest.approx(1.03 * v["IH_total"] * 2.5 / (0.98 * v["UTHD_meas"]))
    assert a.at["IH_scaled", "measured_value"] == a0.at["IH_scaled", "measured_value"]     # measured values unchanged


def test_alignment_keys_and_roles(demo_series, tmp_path):
    """Former keys of the alignment (rollen, kanaele) shifted nothing before; now they raise, unknown roles too,
    while role names of the predecessor are translated as in the role overrides."""
    from groundfault.evaluation import _shift
    folder, truth = demo_series
    rec = open_recording(os.path.join(str(folder), truth[0]["file"]))
    with pytest.raises(ValueError, match=r"^alignment: unbekannter Schlüssel 'rollen' – zulässig: 'dt_s', 'roles', "
                                         r"'channels' \('rollen' ist der frühere Name von 'roles'\)$"):
        evaluate(rec, _intervals(truth[0]), alignment=dict(rollen=["u_l1e"], dt_s=0.01))
    with i18n.language("en"), pytest.raises(ValueError, match=r"^alignment: unknown key 'kanaele' .*\('kanaele' is "
                                                               r"the former name of 'channels'\)$"):
        evaluate(rec, _intervals(truth[0]), alignment=dict(kanaele=["V1"], dt_s=0.01))
    with pytest.raises(ValueError, match="^alignment='u_lle' ist nicht zulässig – zulässig: 'u_l1e'"):
        evaluate(rec, _intervals(truth[0]), alignment=dict(roles=["u_lle"], dt_s=0.01))
    demo.make_station_recording(str(tmp_path / "st.cfg"))
    st = open_recording(str(tmp_path / "st.cfg"))
    roles = detect_roles(st.channel_names, st.units)
    shifted = _shift(st, roles, dict(dt_s=0.01, roles=["i_schirm", "i_pen_v"]))
    assert shifted == _shift(st, roles, dict(dt_s=0.01, roles=["i_shield", "i_pen"])) == {roles.index("i_shield"): 100,
                                                                                          roles.index("i_pen"): 100}
