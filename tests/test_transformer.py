# -*- coding: utf-8 -*-
"""Transformer node: power, apparent and upstream impedance per order and sequence (synthetic recordings with known
solution)."""
import json

import numpy as np
import pytest

from groundfault import Intervals, Settings, demo, evaluate, i18n, open_recording, report, transformer
from groundfault.evaluation import load_result
from groundfault.symmetrical import A, A2


def _intervals(w, post=True):
    b = w["intervals"]
    return Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]), tuple(b["post_fault"]) if post else None)


def _complex(d):
    return complex(d["re"], d["im"])


@pytest.fixture(scope="module")
def plain(tmp_path_factory):
    """Consumer reference arrow system, HV voltages, no disturbance."""
    path = str(tmp_path_factory.mktemp("tr") / "TR_0_10_000kHz.cfg")
    w = demo.make_transformer_recording(path)
    with i18n.language("en"):
        return evaluate(open_recording(path), _intervals(w)), w, path


@pytest.fixture(scope="module")
def reversed_step(tmp_path_factory):
    """Generator reference arrow system and an active residual current increase during the fault."""
    path = str(tmp_path_factory.mktemp("tr") / "TR_gen_10_000kHz.cfg")
    w = demo.make_transformer_recording(path, generator_reference=True, active_step=(3.0, 3.8, 12.0), duration=7.0,
                                        t_off=5.5)
    with i18n.language("en"):
        return evaluate(open_recording(path), _intervals(w)), w, path


def test_upstream_impedance_per_order(plain):
    res, w, _ = plain
    zi = res.table("transformer_impedance").set_index(["order", "sequence"])
    for m in (5, 7, 11):
        for seq in ("pos", "neg"):
            r = zi.loc[(m, seq)]
            z = r["Z_up_Ohm"] * np.exp(1j * np.radians(r["Z_up_angle_deg"]))
            assert abs(z - _complex(w["Z_up"][m])) <= 0.01 * abs(_complex(w["Z_up"][m])), (m, seq)
            assert r["significant"]
            assert r["X_up_per_order_Ohm"] == pytest.approx(w["X1_up"], rel=0.01)
            # second estimate (fault − post-fault) and the deviation between positive and negative sequence
            assert r["Z_up_post_Ohm"] == pytest.approx(abs(_complex(w["Z_up"][m])), rel=0.01)
            assert r["deviation_pct"] < 1.0 and r["pos_neg_deviation_pct"] < 1.5
    v = res.values["transformer"]
    assert v["X1_up_Ohm"] == pytest.approx(w["X1_up"], rel=0.005)
    assert v["sign"] == 1 and v["polarity_source"] == "automatic"


def test_hv_side_splits_transformer_and_hv_network(plain):
    res, w, _ = plain
    v = res.values["transformer"]
    assert v["hv_group"] == 5 and v["hv_shift_deg"] == 150.0
    assert v["hv_ratio"] == pytest.approx(5.5, rel=0.03)          # ratio under load (voltage drop of the transformer)
    assert v["X1_transformer_Ohm"] == pytest.approx(w["X1_transformer"], rel=0.01)
    assert v["X1_hv_Ohm"] == pytest.approx(w["X1_hv"], rel=0.1)
    zi = res.table("transformer_impedance").set_index(["order", "sequence"])
    for m in (5, 7):
        assert zi.at[(m, "neg"), "Z_transformer_Ohm"] == pytest.approx(abs(_complex(w["Z_transformer"][m])), rel=0.01)
        assert zi.at[(m, "neg"), "Z_hv_Ohm"] == pytest.approx(abs(_complex(w["Z_hv"][m])), rel=0.1)


def test_power_per_state_and_sequence(plain):
    res, w, _ = plain
    node = res.table("transformer_node")
    tot = node[node["sequence"] == "total"].set_index(["interval", "order"])
    for m in (1, 5, 7, 11):
        for state, key in (("pre_fault", "S"), ("fault", "S_fault")):
            assert tot.at[(state, m), "P_kW"] == pytest.approx(w[key][m]["P_kW"], abs=0.02 + 1e-4 * abs(w[key][m]["P_kW"]))
            assert tot.at[(state, m), "Q_kvar"] == pytest.approx(w[key][m]["Q_kvar"], abs=0.02 + 1e-4 * abs(w[key][m]["Q_kvar"]))
    # the sum over the sequences equals the sum over the phases
    seq = node[node["sequence"] != "total"].groupby(["interval", "order"])[["P_kW", "Q_kvar"]].sum()
    assert np.allclose(seq.loc[tot.index].to_numpy(), tot[["P_kW", "Q_kvar"]].to_numpy(), atol=1e-6)
    ch = res.table("transformer_power_change").set_index(["order", "sequence"])
    assert ch.at[(1, "total"), "dP_fault_kW"] == pytest.approx(w["dP1_fault_kW"], abs=0.5)
    assert ch.at[(1, "total"), "dQ_fault_kvar"] == pytest.approx(w["dQ1_fault_kvar"], abs=1.0)
    assert abs(ch.at[(5, "total"), "dP_post_kW"]) < 0.05           # null test: post-fault = pre-fault
    v = res.values["transformer"]
    assert v["dP1_fault_kW"] == pytest.approx(w["dP1_fault_kW"], abs=0.5)
    # table of version 2: orders ≤ 13, zero-sequence current of the coil during the fault
    t = res.table("transformer_power")
    assert t["order"].max() <= 13
    assert t.set_index(["interval", "order"]).at[("fault", 1), "I_zero_A"] == pytest.approx(w["I_zero_fault_A"], rel=2e-3)


def test_generator_reference_and_estimated_fault_current(reversed_step):
    res, w, _ = reversed_step
    v = res.values["transformer"]
    assert w["sign"] == -1 and v["sign"] == -1 and v["polarity_source"] == "automatic"
    assert v["polarity_angle_deg"] < 0
    assert any("generator reference arrow system" in h for h in res.hints)
    assert any("estimated from the change of the negative-sequence current" in h for h in res.hints)
    pr = res.table("plausibility").set_index("check")
    assert pr.at["Polarity of the transformer currents", "status"] == "CORRECTED"
    # the active residual current increase is found from the transformer currents and left out of the fault state
    seg = res.table("steady_state_segments")
    dist = seg[~seg["used"]]
    assert list(dist["state"]) == ["active increase"]
    assert dist.iloc[0]["from_s"] == pytest.approx(3.0, abs=0.2) and dist.iloc[0]["to_s"] == pytest.approx(3.8, abs=0.2)
    t_ref = res.steady_state.t_mid[res.reference_windows]
    assert not ((t_ref > 3.0) & (t_ref < 3.8)).any()
    # powers in the consumer reference arrow system and the upstream impedance as without reversal
    node = res.table("transformer_node")
    tot = node[node["sequence"] == "total"].set_index(["interval", "order"])
    assert tot.at[("fault", 5), "P_kW"] == pytest.approx(w["S_fault"][5]["P_kW"], abs=0.02)
    assert v["X1_up_Ohm"] == pytest.approx(w["X1_up"], rel=0.01)
    zi = res.table("transformer_impedance").set_index(["order", "sequence"])
    assert 80 < zi.at[(5, "neg"), "Z_up_angle_deg"] < 100


def test_explicit_sign_overrides_and_warns(tmp_path):
    path = str(tmp_path / "TR_gen_10_000kHz.cfg")
    w = demo.make_transformer_recording(path, generator_reference=True)
    with i18n.language("en"):
        res = evaluate(open_recording(path), _intervals(w), Settings(transformer_sign=1))
    v = res.values["transformer"]
    assert v["sign"] == 1 and v["polarity_source"] == "setting" and v["polarity_auto"] == -1
    assert any("contradicts the angle of the upstream impedance" in h for h in res.hints)
    pr = res.table("plausibility").set_index("check")
    assert pr.at["Polarity of the transformer currents", "status"] == "WARNING"
    node = res.table("transformer_node")
    p1 = node[(node["sequence"] == "total") & (node["order"] == 1) & (node["interval"] == "pre_fault")]["P_kW"].iloc[0]
    assert p1 == pytest.approx(-w["S"][1]["P_kW"], rel=1e-3)      # as measured: reversed
    with i18n.language("en"):
        res2 = evaluate(open_recording(path), _intervals(w), Settings(transformer_sign=-1))
    assert res2.values["transformer"]["polarity_source"] == "setting"
    assert not any("contradicts" in h for h in res2.hints)


def test_without_post_fault_interval(plain):
    _, w, path = plain
    res = evaluate(open_recording(path), _intervals(w, post=False))
    zi = res.table("transformer_impedance").set_index(["order", "sequence"])
    assert np.isnan(zi.at[(5, "neg"), "Z_up_post_Ohm"]) and np.isnan(zi.at[(5, "neg"), "dI_null_A"])
    assert zi.at[(5, "neg"), "Z_up_Ohm"] == pytest.approx(abs(_complex(w["Z_up"][5])), rel=0.01)
    ch = res.table("transformer_power_change")
    assert ch["dP_post_kW"].isna().all()
    assert set(res.table("transformer_node")["interval"]) == {"pre_fault", "fault"}


def test_no_estimate_without_reference_interval(plain):
    _, w, path = plain
    with i18n.language("en"):
        res = evaluate(open_recording(path), Intervals(tuple(w["intervals"]["steady_state"])))
    assert res.disturbances is None
    assert not any("negative-sequence current" in h for h in res.hints)
    assert "transformer_impedance" not in res.tables                  # no state to compare with
    assert set(res.table("transformer_node")["interval"]) == {"fault"}
    assert res.values["transformer"]["polarity_source"] == "default"


def test_result_file_round_trip(plain, tmp_path):
    res, w, _ = plain
    path = res.save_json(str(tmp_path / "res.json"))
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    assert d["transformer"]["sign"] == 1 and d["transformer"]["hv_group"] == 5
    for t in ("transformer_node", "transformer_power_change", "transformer_impedance", "transformer_power"):
        assert t in d["tables"]
    e = load_result(path)
    zi = e.tables["transformer_impedance"]
    assert set(zi["sequence"]) == {"pos", "neg"}
    assert zi["significant"].dtype == bool or set(zi["significant"].unique()) <= {True, False}


def test_german_output(plain):
    res, w, path = plain
    with i18n.language("de"):
        res_de = evaluate(open_recording(path), _intervals(w))
        df = i18n.localize(res_de.table("transformer_node"))
        assert "Bereich" in df.columns and set(df["Sequenz"] if "Sequenz" in df else df["sequence"]) >= {"Mit"}
        pr = res_de.table("plausibility")
        assert "Polarität der Trafoströme" in set(pr["check"])
        assert any("Verbraucherzählpfeilsystem" in str(x) for x in pr["value"])


def test_sequence_power_identity():
    rng = np.random.default_rng(1)
    U = rng.standard_normal((5, 3, 4)) + 1j * rng.standard_normal((5, 3, 4))
    I = rng.standard_normal((5, 3, 4)) + 1j * rng.standard_normal((5, 3, 4))
    from groundfault.symmetrical import fortescue
    Us = np.stack(fortescue(U[:, 0], U[:, 1], U[:, 2]), axis=1)
    Is = np.stack(fortescue(I[:, 0], I[:, 1], I[:, 2]), axis=1)
    assert np.allclose((3 * Us * np.conj(Is)).sum(axis=1), (U * np.conj(I)).sum(axis=1))


def test_upstream_impedance_and_polarity_functions():
    orders = [1, 2, 4, 5, 7]
    Z = np.array([complex(0.1, 2.0 * m) for m in orders])
    n = len(orders)

    def state(dI, U0=0.0):
        U = np.zeros((3, n), complex); I = np.zeros((3, n), complex)
        I[1:] = dI
        U[1:] = U0 - Z * dI
        z = np.zeros((3, n))
        return dict(n=20, U=U, I=I, se_U=z + 0.01, se_I=z + 0.001, U_rms=np.abs(U), I_rms=np.abs(I),
                    S=3 * U * np.conj(I), S_phases=(3 * U * np.conj(I)).sum(axis=0))
    pre, fault, post = state(0.0, 100.0), state(2.0 + 1.0j, 100.0), state(0.0, 100.0)
    z = transformer.upstream_impedance(fault, pre, post)
    assert np.allclose(z["Z"][1:], Z) and np.allclose(z["Z_post"][1:], Z)
    assert np.all(z["u_rel"][1:] < 0.01)
    assert transformer.polarity(fault, pre, post, orders)[0] == 1
    rev = {k: (-v if k == "I" else v) for k, v in fault.items()}
    rev_pre = {k: (-v if k == "I" else v) for k, v in pre.items()}
    sign, angle, count = transformer.polarity(rev, rev_pre, None, orders)
    assert sign == -1 and angle < 0 and count == 8          # orders 2, 4, 5, 7 (not m = 1), two sequences
    zr = transformer.upstream_impedance(rev, rev_pre, None, sign=-1)
    assert np.allclose(zr["Z"][1:], Z) and np.isnan(zr["Z_post"]).all() and np.isnan(zr["dI_null"]).all()


def test_fault_current_estimate_phase_factor(plain):
    res, w, _ = plain
    est = transformer.fault_current_estimate(res.steady_state, res.pre_fault, res.roles, 1)
    I1, U0, coil, ph = est
    assert ph == 2                                            # fault in L3
    ok = res.reference_windows
    # −I_F relative to U0: active component share·Iw, reactive share·Iv (share 0.9 of the demo)
    d = np.angle(U0[ok]) - np.angle(I1[ok])
    iw = np.median(np.abs(I1[ok]) * np.cos(d)); iv = np.median(np.abs(I1[ok]) * np.sin(d))
    assert iw == pytest.approx(0.9 * 20.0, rel=0.02) and abs(iv) == pytest.approx(0.9 * 5.0, rel=0.05)
    assert coil is not None and np.nanmedian(coil) == pytest.approx(w["I_coil_A"], rel=0.01)
    assert A * A2 == pytest.approx(1.0)


def test_settings_transformer_sign_invalid():
    for bad in (2, 0, True, "auto"):
        with pytest.raises(ValueError, match="transformer_sign"):
            Settings(transformer_sign=bad)
    assert Settings().transformer_sign is None
    assert Settings(transformer_sign=-1.0).transformer_sign == -1.0


def test_report_figure(plain, tmp_path):
    res, _, _ = plain
    fig = report.transformer_impedance(res)
    assert len(fig.axes) == 2
    paths = report.save(fig, str(tmp_path / "tr_imp"), ["png"], close=True)
    assert paths and all(p.endswith(".png") for p in paths)
    fig = report.transformer_power(res)
    fig.canvas.draw()                   # one legend above both panels, which keep the same width
    w = [ax.get_position().width for ax in fig.axes]
    assert len(fig.legends) == 1 and len(fig.legends[0].get_texts()) == 3 and abs(w[0] - w[1]) < 0.02 * w[0]
    report.save(fig, str(tmp_path / "tr_pow"), ["png"], close=True)


def test_scan_of_a_transformer_recording(tmp_path):
    """The scan finds the fault from U0 and the active residual current increase from the estimated fault current,
    starts after the settling time and proposes the undisturbed range before it."""
    from groundfault import disturbances
    path = str(tmp_path / "TR_scan_10_000kHz.cfg")
    demo.make_transformer_recording(path, duration=9.0, t_on=1.5, t_off=7.5, active_step=(4.5, 5.5, 12.0),
                                    generator_reference=True)
    rec = open_recording(path)
    t_on, t_off = transformer.fault_times(rec, transformer_roles(rec))
    assert t_on == pytest.approx(1.5, abs=0.05) and t_off == pytest.approx(7.5, abs=0.1)
    with i18n.language("en"):
        d = disturbances.scan(rec)
        text = d.text()
    assert d.meta["estimated"] and d.meta["faulted_phase"] == "L3" and d.meta["transformer_sign"] == -1
    assert d.meta["t_from_s"] >= 1.5 + transformer.T_SETTLE_S - 0.15
    active = [ep for ep in d.episodes if ep["kind"] == "active"]
    assert len(active) == 1 and active[0]["from_s"] == pytest.approx(4.5, abs=0.2)
    assert active[0]["to_s"] == pytest.approx(5.5, abs=0.2) and active[0]["step_A"] == pytest.approx(10.8, rel=0.05)
    s = d.suggestion()
    assert s is not None and s[0] >= 2.9 and s[1] <= 4.5
    assert "estimated from the negative-sequence current" in text


def transformer_roles(rec):
    from groundfault import detect_roles
    return detect_roles(rec.channel_names, rec.units)


def test_settling_and_end_of_the_estimate():
    rng = np.random.default_rng(3)
    noisy = 20 + rng.normal(0, 1.0, 40)                        # noise of ±5 % per window: settled at once
    assert transformer.settled_index(noisy) == 0
    decay = np.concatenate([20 + 30 * np.exp(-np.arange(15) / 3.0), np.full(25, 20.0)])
    k = transformer.settled_index(decay)
    assert 3 <= k <= 12                                          # after the transient
    step = np.concatenate([np.full(10, 20.0), np.full(20, 30.0)])  # a later step stays inside the range
    assert transformer.settled_index(step) == 0
    end = np.concatenate([np.full(20, 20.0), [11.0, 0.5]])
    assert transformer.fault_end_index(end) == 20


def test_estimate_noise_is_robust_against_steps():
    rng = np.random.default_rng(5)
    n = 60
    U0 = np.full(n, 11000.0 + 0j) * np.exp(1j * 0.3)
    iw = 20 + rng.normal(0, 0.8, n); iw[30:40] += 12.0                 # a step of 12 A for ten windows
    iv = 5 + rng.normal(0, 0.4, n)
    I1 = (iw + 1j * iv) * np.exp(1j * 0.3)
    noise = transformer.estimate_noise(I1, U0)
    assert noise == pytest.approx(0.8, rel=0.3)                       # the step does not inflate it
    assert transformer.estimate_noise(I1[:2], U0[:2]) == 0.0
