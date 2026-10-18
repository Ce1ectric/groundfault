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


def test_natural_sequence_and_summary_rows(plain):
    res, w, _ = plain
    assert transformer.is_natural(5, "neg") and transformer.is_natural(7, "pos") and transformer.is_natural(9, "zero")
    assert not transformer.is_natural(5, "pos") and not transformer.is_natural(7, "neg")
    assert transformer.is_natural(2, "neg") and transformer.is_natural(4, "pos")
    zi = res.table("transformer_impedance").set_index(["order", "sequence"])
    assert bool(zi.at[(5, "neg"), "natural_sequence"]) and not bool(zi.at[(5, "pos"), "natural_sequence"])
    assert bool(zi.at[(7, "pos"), "natural_sequence"]) and not bool(zi.at[(7, "neg"), "natural_sequence"])
    # the summary value uses the sequence other than the natural one (hardly any pre-fault harmonic) …
    v = res.values["transformer"]
    assert v["X1_up_other_sequence"] is True
    other = zi[(~zi["natural_sequence"].astype(bool)) & zi["significant"] & (zi.index.get_level_values(0) >= 2)
               & (zi.index.get_level_values(0) % 3 != 0)]
    assert v["X1_up_count"] == len(other)
    with i18n.language("de"):
        rows = transformer.plausibility_rows(res)
    assert any("nicht natürlichen Drehsystem" in r["value"] for r in rows)
    # … and falls back to both sequences without a significant entry there
    orders = [1, 5, 7]
    u = np.full((3, 3), 0.05)
    z = dict(u_rel=u, Z=np.full((3, 3), 1 + 2j))
    rows_, flag = transformer._summary_rows(z, orders)
    assert flag and sorted(rows_) == [(1, 1), (2, 2)]           # 5: positive, 7: negative sequence
    u[1, 1] = u[2, 2] = 0.5
    rows_, flag = transformer._summary_rows(z, orders)
    assert not flag and sorted(rows_) == [(1, 2), (2, 1)]


def test_voltage_divider_gives_the_hv_share(plain):
    res, w, _ = plain
    d = res.values["transformer_divider"]
    assert d["group"] == 5 and d["k_other_sequence"]
    assert d["k"] == pytest.approx(w["X1_hv"] / w["X1_up"], rel=0.05)
    assert d["X1_hv_Ohm"] == pytest.approx(w["X1_hv"], rel=0.05)              # second method beside the HV current
    assert d["X1_transformer_Ohm"] == pytest.approx(w["X1_transformer"], rel=0.01)
    tab = res.table("transformer_divider").set_index(["order", "sequence"])
    for m in (5, 7):
        for seq in ("pos", "neg"):
            assert tab.at[(m, seq), "significant"]
            assert tab.at[(m, seq), "Z_hv_Ohm"] == pytest.approx(abs(_complex(w["Z_hv"][m])), rel=0.1)
    with i18n.language("en"):
        rows = transformer.plausibility_rows(res)
    assert any(r["check"].startswith("HV share of the upstream impedance") for r in rows)
    assert "transformer_divider" in res.result_set and "transformer_divider" in res.result_set["tables"]


def test_voltage_divider_without_transformer_currents(plain):
    _, w, path = plain
    rec = open_recording(path)
    from groundfault import detect_roles
    currents = {k.name: None for k in detect_roles(rec.channel_names, rec.units).channels
                if k.role in ("i_l1", "i_l2", "i_l3")}
    assert len(currents) == 3
    roles = detect_roles(rec.channel_names, rec.units, currents)
    with i18n.language("en"):
        res = evaluate(rec, _intervals(w), roles=roles)
    assert "transformer" not in res.values and "transformer_impedance" not in res.tables
    d = res.values["transformer_divider"]
    assert d["k"] == pytest.approx(w["X1_hv"] / w["X1_up"], rel=0.05) and "X1_hv_Ohm" not in d
    assert "Z_hv_Ohm" not in res.table("transformer_divider").columns
    pr = res.table("plausibility").set_index("check")
    assert "HV share of the upstream impedance (voltage divider)" in pr.index


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


# ---------------------------------------------------------------- MV network from undisturbed operation
@pytest.fixture(scope="module")
def undisturbed(tmp_path_factory):
    """Undisturbed transformer node with independently fluctuating sources on the HV and on the MV side."""
    d = tmp_path_factory.mktemp("iv")
    out = {}
    for gen in (False, True):
        path = str(d / ("TRU%s_10_000kHz.cfg" % ("_gen" if gen else "")))
        out[gen] = (path, demo.make_undisturbed_transformer_recording(path, generator_reference=gen))
    return out


def _z_true(w, m):
    z = w["Z_mv"][m]
    return complex(z["re"], z["im"])


def test_mv_network_impedance_from_undisturbed_operation(undisturbed):
    """The HV voltage as instrument gives the impedance of the MV network – not the mix of Z_MV and −Z_up that
    U/I of the undisturbed node shows."""
    path, w = undisturbed[False]
    with i18n.language("en"):
        df = transformer.mv_network_impedance(path, orders=(5, 7), n_boot=100)
    assert df.attrs["sign"] == 1.0 and df.attrs["group"] == 5 and df.attrs["ratio"] == pytest.approx(5.5, rel=0.05)
    assert set(df.sequence) == {"pos", "neg"} and len(df) == 4
    for _, r in df.iterrows():
        z = _z_true(w, r.order)
        assert r.Z_Ohm == pytest.approx(abs(z), rel=0.12)
        assert abs(r.Z_angle_deg - np.degrees(np.angle(z))) < 10.0
        assert r.reliable and r.instrument == "U_hv" and r.corr_I_hv > 0.5
        assert r.Z_low_Ohm <= r.Z_Ohm <= r.Z_high_Ohm
        y = 1.0 / complex(r.R_Ohm, r.X_Ohm)
        assert (r.G_S, r.B_S) == pytest.approx((y.real, y.imag))
    assert df.set_index(["order", "sequence"]).loc[(5, "neg"), "natural_sequence"]


def test_mv_network_impedance_with_hv_network_and_reversed_currents(undisturbed):
    """Currents in the generator reference arrow system are recognised from the passivity of Z_MV; with the HV network
    impedance the instrument is the HV source voltage and the bias of the MV sources disappears."""
    path, w = undisturbed[True]
    with i18n.language("en"):
        df = transformer.mv_network_impedance(path, orders=(5, 7), n_boot=50, Z_hv=complex(0.03, 0.12))
    assert df.attrs["sign"] == -1.0 and any("reversed" in h for h in df.attrs["hints"])
    for _, r in df.iterrows():
        z = _z_true(w, r.order)
        assert r.instrument == "E_hv" and r.reliable
        assert r.Z_Ohm == pytest.approx(abs(z), rel=0.08)
        assert abs(r.Z_angle_deg - np.degrees(np.angle(z))) < 6.0
    # explicit sign and Z_hv per order give the same estimate
    again = transformer.mv_network_impedance(path, orders=(5,), n_boot=10, sign=-1, Z_hv={5: complex(0.03, 0.6)})
    assert np.allclose(again.Z_Ohm, df[df.order == 5].Z_Ohm)


@pytest.fixture(scope="module")
def shares(tmp_path_factory):
    """Undisturbed recordings with a decreasing share of the HV-driven variation; current transformers with an angle
    error of 3° at 250 Hz and 4° at 350 Hz, a reference clamp on L1."""
    d = tmp_path_factory.mktemp("share")
    out = {}
    for name, hf, mf in (("high", 0.08, 0.08), ("low", 0.03, 0.12)):
        path = str(d / ("TRS_%s_10_000kHz.cfg" % name))
        out[name] = (path, demo.make_undisturbed_transformer_recording(
            path, hv_fluctuation=hf, mv_fluctuation=mf, duration=60.0, ct_angle_deg={5: 3.0, 7: 4.0},
            reference_clamp=True))
    return out


def test_ct_angle_from_reference_clamp(shares, tmp_path):
    """The angle error of the transformer current channel against a reference clamp on the same conductor – also
    with the clamp connected the other way round."""
    path, w = shares["high"]
    ref = transformer.ct_angle_from_reference(path, "I1", "IRef", orders=(1, 5, 7)).set_index("order")
    for m in (1, 5, 7):
        assert ref.loc[m, "angle_deg"] == pytest.approx(w["ct_angle_deg"][m], abs=0.05)
        assert ref.loc[m, "ratio"] == pytest.approx(1.0, abs=0.01)
        assert ref.loc[m, "angle_low_deg"] <= ref.loc[m, "angle_deg"] <= ref.loc[m, "angle_high_deg"]
    assert not ref.reference_reversed.any()
    # the clamp reversed
    rec = open_recording(path)
    data = rec.read(0, rec.n)
    names = list(rec.channel_names)
    j = names.index("DANEO 1_System 4_IRef Inst")
    data[:, j] *= -1.0
    rev = str(tmp_path / "TRS_rev_10_000kHz.cfg")
    demo.write_comtrade(rev, {nm: (u, data[:, k]) for k, (nm, u) in enumerate(zip(names, rec.units))}, rec.fs)
    again = transformer.ct_angle_from_reference(rev, 3, j, orders=(5,))
    assert bool(again.reference_reversed.iloc[0]) and again.angle_deg.iloc[0] == pytest.approx(3.0, abs=0.05)
    with i18n.language("en"):
        with pytest.raises(ValueError, match="not found"):
            transformer.ct_angle_from_reference(path, "I9", "IRef")


def test_mv_network_impedance_ct_angle_and_hv_share(shares):
    """The angle correction rotates the estimate by the angle error of the current transformers; the share of the
    HV-driven variation follows the true share (natural sequence, corrected instrument) and – with a limit – marks
    a recording driven from the MV side as not reliable."""
    path, w = shares["high"]
    z_up = {m: _complex(z) for m, z in w["Z_up"].items()}
    ref = transformer.ct_angle_from_reference(path, "I1", "IRef", orders=(5, 7))
    # with the HV voltage as instrument the correction only rotates the estimate
    raw = transformer.mv_network_impedance(path, orders=(5, 7), n_boot=10)
    rot = transformer.mv_network_impedance(path, orders=(5, 7), n_boot=10, ct_angle_deg=ref)
    assert rot.attrs["ct_angle_deg"] == pytest.approx({5: 3.0, 7: 4.0}, abs=0.05)
    assert np.allclose(rot.Z_Ohm, raw.Z_Ohm, rtol=1e-6)
    assert np.allclose((rot.Z_angle_deg - raw.Z_angle_deg).to_numpy(), [3.0, 4.0, 3.0, 4.0], atol=0.06)
    assert raw.hv_share.isna().all()
    # corrected instrument, angle correction and the share of the HV-driven variation
    cor = transformer.mv_network_impedance(path, orders=(5, 7), n_boot=10, Z_hv=complex(0.03, 0.12), Z_up=z_up,
                                           ct_angle_deg=ref, min_hv_share=0.2)
    nat = cor[cor.natural_sequence]
    for _, r in nat.iterrows():
        z = _z_true(w, r.order)
        assert abs(r.Z_angle_deg - np.degrees(np.angle(z))) < 4.0
        assert r.hv_share == pytest.approx(w["hv_share"][r.order][r.sequence], abs=0.05)
        assert r.corr_U_hv ** 2 == pytest.approx(r.hv_share, abs=0.05)
        assert r.reliable
    # the same angle as one value or per order
    assert np.allclose(transformer.mv_network_impedance(path, orders=(5,), n_boot=5, ct_angle_deg={5: 3.0}).Z_angle_deg,
                       transformer.mv_network_impedance(path, orders=(5,), n_boot=5, ct_angle_deg=3.0).Z_angle_deg)
    # driven from the MV side: the share shows it, the other checks do not
    path, w = shares["low"]
    z_up = {m: _complex(z) for m, z in w["Z_up"].items()}
    with i18n.language("en"):
        low = transformer.mv_network_impedance(path, orders=(5, 7), n_boot=10, Z_hv=complex(0.03, 0.12), Z_up=z_up,
                                               ct_angle_deg={5: 3.0, 7: 4.0}, min_hv_share=0.25)
    nat = low[low.natural_sequence].set_index("order")
    assert nat.loc[5, "hv_share"] == pytest.approx(w["hv_share"][5]["neg"], abs=0.05) and nat.loc[5, "hv_share"] < 0.25
    assert nat.loc[5, "corr_I_hv"] >= 0.2 and not nat.loc[5, "reliable"]
    assert any("MV network dominate" in h for h in low.attrs["hints"])
    with i18n.language("de"):
        again = transformer.mv_network_impedance(path, orders=(5,), n_boot=5, Z_hv=complex(0.03, 0.12), Z_up=z_up,
                                                 ct_angle_deg=3.0, min_hv_share=0.25)
        assert any("MS-Netz überwiegen" in h for h in again.attrs["hints"])
        with pytest.raises(ValueError, match="Z_hv"):
            transformer.mv_network_impedance(path, orders=(5,), Z_up=z_up, min_hv_share=0.25)
    with i18n.language("en"):
        with pytest.raises(ValueError, match="Z_up"):
            transformer.mv_network_impedance(path, orders=(5,), Z_hv=complex(0.03, 0.12), min_hv_share=0.25)
        with pytest.raises(ValueError, match="angle error"):
            transformer.mv_network_impedance(path, orders=(5, 7), ct_angle_deg={5: 3.0})
        with pytest.raises(ValueError, match="no value for the orders"):
            transformer.mv_network_impedance(path, orders=(5, 7), Z_up={5: complex(0.1, 9.0)})


def test_mv_network_series_pools_the_reliable_recordings(tmp_path):
    """A measuring day in brief: recordings with a falling share of the HV-driven variation, each evaluated on its
    own; with a limit for the share only the HV-driven ones are pooled, and the pooled estimate is close to the
    true MV network."""
    import datetime
    paths, truths = [], []
    for k, (hf, mf) in enumerate(((0.10, 0.05), (0.08, 0.08), (0.03, 0.12), (0.02, 0.14))):
        p = str(tmp_path / ("TRD_%02d_10_000kHz.cfg" % k))
        truths.append(demo.make_undisturbed_transformer_recording(
            p, hv_fluctuation=hf, mv_fluctuation=mf, duration=40.0, ct_angle_deg=2.0, seed=20 + k,
            start=datetime.datetime(2026, 3, 10, 2 + 4 * k, 0)))
        paths.append(p)
    z_up = {m: _complex(z) for m, z in truths[0]["Z_up"].items()}
    with i18n.language("en"):
        table, pooled = transformer.mv_network_series(paths, (5, 7), Z_hv=complex(0.03, 0.12), Z_up=z_up,
                                                      ct_angle_deg=2.0, min_hv_share=0.25, n_boot=20)
    assert table.attrs["sign"] == 1.0 and len(table) == 8 and table.natural_sequence.all()
    assert list(table.start.unique()) == ["2026-03-10 %02d:00:00" % h for h in (2, 6, 10, 14)]
    for _, r in table.iterrows():
        true = truths[int(r.recording[4:6])]["hv_share"][r.order][r.sequence]
        if true >= 0.2:
            assert r.hv_share == pytest.approx(true, abs=0.06)
        else:                         # a weak instrument: the share is less precise but stays below the limit
            assert r.hv_share < 0.25 and not r.reliable
    assert set(table[table.reliable].recording) == {"TRD_00_10_000kHz", "TRD_01_10_000kHz"}
    for _, r in pooled.iterrows():
        assert r.recordings == 2 and r.reliable
        z = _z_true(truths[0], r.order)
        assert r.Z_Ohm == pytest.approx(abs(z), rel=0.06)
        assert abs(r.Z_angle_deg - np.degrees(np.angle(z))) < 5.0
    # without a reliable recording the pooled row is empty
    _, none = transformer.mv_network_series(paths[2:], (5,), Z_hv=complex(0.03, 0.12), Z_up=z_up, ct_angle_deg=2.0,
                                            min_hv_share=0.25, n_boot=5)
    assert none.recordings.iloc[0] == 0 and not none.reliable.iloc[0] and np.isnan(none.get("Z_Ohm", np.nan)).all()
    with pytest.raises(ValueError):
        transformer.mv_network_series(paths, (5,), intervals=[None])


def test_mv_network_impedance_weak_instrument_and_errors(tmp_path):
    path = str(tmp_path / "TRW_10_000kHz.cfg")
    demo.make_undisturbed_transformer_recording(path, hv_fluctuation=0.0005, duration=20.0)
    with i18n.language("en"):
        df = transformer.mv_network_impedance(path, orders=(5,), intervals=[(0.5, 10.0), (10.0, 19.5)], n_boot=10)
        # only MV-driven variation: the HV voltage follows the current through the HV network, the estimate is the
        # upstream impedance (inductive) – not reliable
        assert not df.reliable.any()
        assert (df.Z_angle_deg > 45).all()
        assert any("upstream impedance" in h for h in df.attrs["hints"])
        with pytest.raises(ValueError, match="interval lists"):
            transformer.mv_network_impedance([path, path], intervals=[[(0.5, 5.0)]])
        with pytest.raises(ValueError, match="not computed"):
            transformer.mv_network_impedance(path, orders=(5, 11), settings=Settings(
                harmonics=(1, 5), export_orders=(1, 5), voltage_harmonics=(1, 5), thd_max_order=5))
        nohv = str(tmp_path / "TRN_10_000kHz.cfg")
        demo.make_transformer_recording(nohv, hv=False)
        with pytest.raises(ValueError, match="HV voltages"):
            transformer.mv_network_impedance(nohv)
    with i18n.language("de"):
        with pytest.raises(ValueError, match="HS-Spannungen"):
            transformer.mv_network_impedance(nohv)
