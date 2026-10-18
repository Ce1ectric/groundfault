# -*- coding: utf-8 -*-
"""Forecast package – network model of the earth-fault loop per harmonic order: calibration with staged fault tests
(fault current measured), update with recorded earth faults (busbar voltages, coil currents), a source that arises in
the fault (orders of the zero sequence), forecast of the harmonic residual current at the busbar and behind a line,
checks between the tests and at recorded earth faults, upstream split, campaigns as input and persistence – exact
phasor data and synthetic COMTRADE recordings with known solution."""
import json
import math
import os

import numpy as np
import pandas as pd
import pytest

from groundfault import Intervals, demo, evaluate, i18n, open_recording
from groundfault import forecast as nm
from groundfault.equivalent_source import load_measurement, natural_sequence, phase_factor

SEQ = ("zero", "pos", "neg")

# invented network: order → (pre-fault voltage of the natural sequence in V, Z_0, Z_1, Z_2 in Ω, source in the fault)
NET = {3: (demo.polar(4.0, 30), 6.0 - 3.0j, 0j, 0j, demo.polar(30, -60)),
       5: (demo.polar(220, -35), 1.0 + 1.5j, 9.0 + 2.0j, 8.0 + 1.0j, 0j),
       7: (demo.polar(110, 50), 12.0 + 0.5j, 1.0 - 6.0j, 2.0 - 5.0j, 0j),
       11: (demo.polar(35, 80), 6.0 - 8.1j, 0.5 + 1.0j, 1.0 + 0.5j, 0j)}
REST = 1.5          # harmonic content of the tests outside the modelled orders in A
DRIFT = {0.0: 1.0, 2.5: demo.polar(1.2, 30), 5.0: demo.polar(0.9, -25)}


def close(a, b, tol=1e-9):
    assert abs(complex(a) - complex(b)) <= tol * max(1.0, abs(complex(b))), (a, b)


def Zq_of(m):
    _, Z0, Z1, Z2, _ = NET[m]
    return (Z0 + Z1 + Z2) / 3


X_COIL = 40.0      # coil reactance at 50 Hz in Ω (linear part of the coil current)


def phasors(name, Z_F, phase="L3", drift=1.0, kind="test", net=NET, keep_current=False, Iw=20.0, Iv=25.0,
            line=None, coils=False):
    """Busbar phasors and fault current of an earth fault through Z_F – behind ``line`` if given – (exact model,
    angle-method orientation); with ``coils`` also the coil currents of a coil that carries the source of the fault
    (I_coil = ΔU_0/(j·m·X_L) + 3·U_s/Z_0)."""
    pf = {s: phase_factor(s, phase) for s in SEQ}
    U_pre, U_fault, I, Ic, dU0c = {}, {}, {}, {}, {}
    for m, (U, Z0, Z1, Z2, Us) in net.items():
        pre = {s: 0j for s in SEQ}
        pre[natural_sequence(m)] = U * drift
        Uq = -sum(pf[s] * pre[s] for s in SEQ)
        Im = (Uq + Us) / ((Z0 + Z1 + Z2) / 3 + Z_F + (line.Zq(m) if line is not None else 0))
        dU = {"zero": (Z0 * Im / 3 - Us) / pf["zero"], "pos": Z1 * Im / (3 * pf["pos"]),
              "neg": Z2 * Im / (3 * pf["neg"])}                  # the busbar voltages contain the source U_s
        U_pre[m] = pre
        U_fault[m] = {s: pre[s] + dU[s] for s in SEQ}
        I[m] = Im
        Ic[m] = dU["zero"] / (1j * m * X_COIL) + 3 * Us / Z0
        dU0c[m] = dU["zero"]
    IH = math.sqrt(sum(abs(v) ** 2 for v in I.values()) + REST ** 2)
    test = kind == "test"
    return nm.FaultData(name=name, kind=kind, U_pre=U_pre, U_fault=U_fault, faulted_phase=phase,
                        I=I if test or keep_current else {}, Z_F=complex(Z_F) if test else None, Iw=Iw, Iv=Iv,
                        IH_sum=IH, I_coil=Ic if coils else {}, dU0_coil=dU0c if coils else {}, line=line)


@pytest.fixture()
def three():
    """Model with the three tests 0, 2.5 and 5 Ω (source drift between them)."""
    model = nm.NetworkModel("net")
    for Z, d in DRIFT.items():
        model.add_test(phasors("%g" % Z, Z, drift=d))
    return model


# ------------------------------------------------------------------------------------------- calibration and update
@pytest.mark.parametrize("phase", ["L1", "L2", "L3"])
def test_calibration_recovers_the_sequence_impedances(phase):
    """B method: Z_s = 3·p_s·ΔU_s/I exact for every faulted phase; at the order with a source that arises in the
    fault the busbar voltages give the apparent impedance Z_q − U_s/I."""
    c = nm.NetworkModel().add_test(phasors("t", 2.5, phase))
    assert sorted(c.orders) == [3, 5, 7, 11] and c.kind == "test" and c.Z_F == 2.5
    for m, (U, Z0, Z1, Z2, Us) in NET.items():
        e = c.orders[m]
        close(e.Z1, Z1)
        close(e.Z2, Z2)
        close(e.Zq, Zq_of(m) - Us / e.I)
        if not Us:
            close(e.Z0, Z0)
        close(e.U_q, -sum(phase_factor(s, phase) * (U if s == natural_sequence(m) else 0) for s in SEQ))


def test_automatic_orders_and_rejected_tests():
    net = dict(NET)
    net[9] = (0.05, 30.0 + 0j, 0j, 0j, 0j)                     # current below 0.3 A
    net[2] = (demo.polar(30, 10), 5.0 + 0j, 0j, 0j, 0j)         # even order
    fd = phasors("t", 0.0, net=net)
    model = nm.NetworkModel()
    assert sorted(model.add_test(fd).orders) == [3, 5, 7, 11]
    assert sorted(model.add_test(fd, orders=[2, 5, 9], name="t2").orders) == [2, 5, 9]
    assert sorted(model.add_test(fd, min_current_A=0.0, name="t3").orders) == [3, 5, 7, 9, 11]
    with pytest.raises(ValueError, match="Kalibrierung mit dem Namen 't' gibt es schon"):
        model.add_test(fd)
    with pytest.raises(ValueError, match="braucht den Fehlerstrom"):
        model.add_test(phasors("f", 0.0, kind="fault"))
    with pytest.raises(ValueError, match="keine Ordnung"):
        model.add_test(fd, orders=[13], name="t4")
    with pytest.raises(ValueError, match="orders='all' ist nicht zulässig"):
        model.add_test(fd, orders="all", name="t5")
    unknown = phasors("u", 0.0)
    unknown.faulted_phase = ""
    assert any("Fehlerleiter unbekannt" in h for h in model.add_test(unknown).hints)


def test_update_from_busbar_voltages(three):
    """Recorded earth fault: Z_1, Z_2, Z_q and the fault current exact from the busbar voltages and Z_0 of the tests;
    the order with a source that arises in the fault is not updated."""
    true = phasors("x", 0.0, "L1", drift=demo.polar(1.3, 40))
    c = three.add_fault(phasors("f", 0.0, "L1", drift=demo.polar(1.3, 40), kind="fault"))
    assert c.kind == "fault" and c.reference == "0, 2.5, 5" and c.Z_F is None
    assert sorted(c.orders) == [5, 7, 11]
    assert any("Ordnung 3: im Fehler entstehende Quelle" in h for h in c.hints)
    for m in (5, 7, 11):
        e = c.orders[m]
        close(e.Z1, NET[m][2])
        close(e.Z2, NET[m][3])
        close(e.Zq, Zq_of(m))
        assert e.I_estimated == pytest.approx(abs(true.I[m]))
        assert np.isnan(e.I)
    assert [x.name for x in three.faults] == ["f"] and len(three.tests) == 3 and len(three) == 4
    # Z_0 of one calibration or given; a current in the data is kept for comparison
    c2 = three.add_fault(phasors("f2", 0.0, drift=1.1, kind="fault", keep_current=True), z0="5", orders=[5, 7])
    assert c2.reference == "5" and sorted(c2.orders) == [5, 7]
    close(c2.orders[5].I, phasors("y", 0.0, drift=1.1).I[5])
    c3 = three.add_fault(phasors("f3", 0.0, kind="fault"), z0={5: NET[5][1]}, orders=[5, 7])
    assert sorted(c3.orders) == [5] and any("Ordnung 7: kein Z_0" in h for h in c3.hints)
    # all orders, also the zero sequence (apparent impedance)
    c4 = three.add_fault(phasors("f4", 0.0, kind="fault"), two_source=None)
    assert 3 in c4.orders
    # small change of the zero-sequence voltage
    c5 = three.add_fault(phasors("f5", 0.0, kind="fault"), min_dU0_V=60.0)
    assert any("unter 60 V – nicht nachgeführt" in h for h in c5.hints) and 11 not in c5.orders
    with pytest.raises(ValueError, match="keine Ordnung"):
        three.add_fault(phasors("f6", 0.0, kind="fault"), min_dU0_V=1e6)
    with pytest.raises(ValueError, match="braucht Z_0 aus einer Kalibrierung"):
        nm.NetworkModel().add_fault(phasors("f", 0.0, kind="fault"))
    with pytest.raises(KeyError, match="keine Kalibrierung mit dem Namen 'x'"):
        three.add_fault(phasors("f7", 0.0, kind="fault"), z0="x")


def test_source_that_arises_in_the_fault(three):
    """Orders of the zero sequence: Z_q and U_s from tests with different additional impedances (least squares);
    with fewer the current of one test is used for every fault impedance."""
    T = three.source_terms()
    assert T[3].kind == "two_source" and {T[m].kind for m in (5, 7, 11)} == {"pre_fault"}
    close(T[3].Zq, Zq_of(3))
    close(T[3].Us, NET[3][4])
    assert T[3].residual < 1e-9 and T[3].n == 3 and T[3].calibrations == ["0", "2.5", "5"]
    for m in (5, 7, 11):
        close(T[m].Zq, Zq_of(m))
    # the source term also for another order (none there) and none at all
    T2 = three.source_terms(two_source=[3, 5])
    assert T2[5].kind == "two_source" and abs(T2[5].Us) < 1e-9
    assert three.source_terms(two_source=None)[3].kind == "pre_fault"
    # one test: constant current with a hint – underestimated for a smaller fault impedance
    one = three.subset(names=["2.5"])
    T1 = one.source_terms()[3]
    assert T1.kind == "constant" and T1.Z_F_constant == 2.5
    assert T1.I_constant == pytest.approx(abs(one.tests[0].orders[3].I))
    assert any("lässt sich mit weniger als zwei Versuchen" in h for h in T1.hints)
    f = one.forecast({3: 4.0, 5: 220.0, 7: 110.0, 11: 35.0}, Z_F=0.0)
    assert f.currents.loc["value", 3] == pytest.approx(T1.I_constant)
    assert any("für die kleineren 0 Ω wird er unterschätzt" in h for h in f.hints)
    assert not any("kleinere" in h for h in one.forecast({5: 220.0}, Z_F=5.0).hints)
    # two tests with the same additional impedance do not separate the sources either
    same = nm.NetworkModel()
    same.add_test(phasors("a", 0.0))
    same.add_test(phasors("b", 0.0, drift=1.1))
    assert same.source_terms()[3].kind == "constant"
    # tests that do not separate U_q and U_s: pre-fault source only
    bad = three.subset(names=["0", "5"])
    bad.calibration("5").orders[3].I = bad.calibration("0").orders[3].I
    Tb = bad.source_terms()[3]
    assert Tb.kind == "pre_fault" and any("trennen U_q und U_s nicht" in h for h in Tb.hints)


def test_conservative_and_phasor_current_of_a_source_term():
    T = nm.SourceTerm(3, "two_source", 3.0 + 4.0j, Us=10.0 + 0j)
    assert T.current(5.0) == pytest.approx(3.0)
    assert T.current(5.0j, conservative=False) == pytest.approx(abs(10 + 5j) / 5)
    np.testing.assert_allclose(T.current(np.array([0.0, 5.0]), Z_F=0.0), [2.0, 3.0])
    P = nm.SourceTerm(5, "pre_fault", 3.0 + 4.0j, Us=10.0 + 0j)       # U_s is ignored for the pre-fault source
    assert P.current(5.0, Z_F=-3.0) == pytest.approx(5.0 / 4.0)
    K = nm.SourceTerm(3, "constant", 1.0 + 0j, I_constant=7.5)
    assert K.current(100.0) == 7.5 and list(K.current(np.zeros(3))) == [7.5] * 3


# ------------------------------------------------------------------------------------------- forecast
def test_forecast_per_order_and_totals(three):
    T = three.source_terms()
    U = {3: 4.0, 5: 220.0, 7: 110.0, 11: 35.0}
    f = three.forecast(U, Z_F=1.0, margin_A=2.0)
    for m in (5, 7, 11):
        assert f.currents.loc["value", m] == pytest.approx(U[m] / abs(T[m].Zq + 1.0) + 2.0)
    assert f.currents.loc["value", 3] == pytest.approx((4.0 + abs(T[3].Us)) / abs(T[3].Zq + 1.0) + 2.0)
    assert f.rest_A == pytest.approx(REST) and f.I1 == pytest.approx(math.hypot(20, 25))
    IH = math.sqrt(sum(f.currents.loc["value"] ** 2) + REST ** 2)
    assert f.IH.iloc[0] == pytest.approx(IH) and f.IRES.iloc[0] == pytest.approx(math.hypot(f.I1, IH))
    assert any("Median von √(I_w² + I_v²)" in h for h in f.hints)
    tab = f.table()
    assert list(tab.order) == [3, 5, 7, 11, "I_rest", "I_H", "I_1", "I_RES"]
    r5 = tab.set_index("order").loc[5]
    assert r5["I_A"] == pytest.approx(220.0 / abs(T[5].Zq + 1.0)) and r5["margin_A"] == 2.0
    assert r5["U_V"] == 220.0 and r5["kind"] == "pre_fault"
    # margin per order, given fundamental and rest
    g = three.forecast(U, 1.0, {5: 1.0}, fundamental_A=10.0, rest_A=0.0)
    assert g.margin == {3: 0.0, 5: 1.0, 7: 0.0, 11: 0.0} and g.I1 == 10.0 and g.rest_A == 0.0
    assert g.currents.loc["value", 5] == pytest.approx(f.currents.loc["value", 5] - 1.0)
    assert three.forecast(U, rest_A=None).rest_A == 0.0
    assert list(three.forecast(U, orders=[5, 7]).currents.columns) == [5, 7]


def test_forecast_rest_covers_the_orders_not_forecast(three):
    """The rest of a test = its harmonic content outside the forecast orders; the largest of the tests is used."""
    f = three.forecast({5: 220.0, 7: 110.0}, orders=[5, 7])
    expect = max(math.sqrt(c.IH_sum ** 2 - abs(c.orders[5].I) ** 2 - abs(c.orders[7].I) ** 2) for c in three.tests)
    assert f.rest_A == pytest.approx(expect)
    assert any("größter Oberschwingungsanteil" in h for h in f.hints)


def test_forecast_input_formats(three):
    ref = three.forecast({3: 4.0, 5: 220.0, 7: 110.0, 11: 35.0}, Z_F=1.0)
    I = ref.currents.loc["value"]
    same = [three.forecast(pd.Series({"H3": 4.0, "H5": 220.0, "H7": 110.0, "H11": 35.0}), 1.0),
            three.forecast({"U_L1_H3": 4.0, "U_L1_H5": 220.0, "U_L1_H7": 110.0, "U_L1_H11": 35.0}, 1.0),
            three.forecast({3: 2.0, 5: 110.0, 7: 55.0, 11: 17.5}, 1.0, percent_of=200.0),
            three.forecast({"L1": {3: 1.0, 5: 100.0, 7: 110.0, 11: 5.0}, "L2": {3: 4.0, 5: 220.0, 7: 10.0, 11: 35.0},
                            "l3": {3: 2.0, 5: 120.0, 7: 50.0}}, 1.0)]
    for f in same:
        pd.testing.assert_series_equal(f.currents.loc["value"], I, check_names=False)
    # line-to-line voltages: divided by √3; no zero sequence in them
    ll = three.forecast({3: 50.0, 5: 220.0 * math.sqrt(3), 7: 110.0 * math.sqrt(3), 11: 35.0 * math.sqrt(3)}, 1.0,
                        reference="LL")
    for m in (5, 7, 11):
        assert ll.currents.loc["value", m] == pytest.approx(I[m])
    T3 = three.source_terms()[3]
    assert ll.currents.loc["value", 3] == pytest.approx(abs(T3.Us) / abs(T3.Zq + 1.0))
    assert any("enthalten kein Nullsystem – die Vorfehlerspannung wird 0" in h for h in ll.hints)
    ll2 = three.forecast({5: 220.0, 3: 50.0}, 1.0, reference="LL", two_source=None)
    assert 3 not in ll2.currents.columns and any("kein Nullsystem – keine Prognose" in h for h in ll2.hints)
    # missing voltages
    mi = three.forecast({5: 220.0}, 1.0)
    assert list(mi.currents.columns) == [3, 5]
    assert mi.currents.loc["value", 3] == pytest.approx(abs(T3.Us) / abs(T3.Zq + 1.0))
    assert any("Ordnungen 7, 11: keine Spannung angegeben" in h for h in mi.hints)
    assert any("Ordnung 3: keine Spannung angegeben – nur die im Fehler" in h for h in mi.hints)
    with pytest.raises(ValueError, match="keine Oberschwingungsordnung"):
        three.forecast({"THD": 3.0})
    with pytest.raises(ValueError, match="reference='LN' ist nicht zulässig"):
        three.forecast({5: 1.0}, reference="LN")


def test_forecast_of_a_time_series(three):
    rng = np.random.default_rng(1)
    idx = pd.date_range("2026-01-01", periods=500, freq="10min")
    df = pd.DataFrame({"U_H3": rng.uniform(1, 6, 500), "U_H5": rng.uniform(100, 250, 500),
                       "U_H7": rng.uniform(50, 120, 500), "U_H11": rng.uniform(10, 40, 500)}, index=idx)
    f = three.forecast(df, Z_F=0.0, margin_A=1.0)
    assert f.currents.shape == (500, 4) and f.voltages.index.equals(idx)
    T = three.source_terms()
    np.testing.assert_allclose(f.currents[5], df["U_H5"] / abs(T[5].Zq) + 1.0)
    q = f.quantile(0.95)
    assert q["IH"] == pytest.approx(float(f.IH.quantile(0.95)))
    assert q["IRES"] == pytest.approx(float(f.IRES.quantile(0.95)))
    assert q["orders"][5] == pytest.approx(float(f.currents[5].quantile(0.95)))
    tab = f.table(0.95).set_index("order")
    assert tab.loc["I_H", "I_forecast_A"] == pytest.approx(q["IH"])
    with pytest.raises(ValueError, match="quantile\\(\\) braucht eine Zeitreihe"):
        f.table()
    with pytest.raises(ValueError, match="quantile\\(\\) braucht eine Zeitreihe"):
        three.forecast({5: 1.0}).quantile(0.95)
    # phases with gaps and other time steps: the largest phase per time step
    a = pd.DataFrame({5: [100.0, np.nan, 50.0]}, index=[0, 1, 2])
    b = pd.DataFrame({5: [10.0, 80.0]}, index=[1, 3])
    g = three.forecast({"L1": a, "L2": b}, orders=[5])
    np.testing.assert_allclose(g.voltages[5].to_numpy(), [100.0, 10.0, 50.0, 80.0])


def test_forecast_without_calibration_and_wrong_options(three):
    with pytest.raises(ValueError, match="enthält keine Kalibrierung"):
        nm.NetworkModel().forecast({5: 1.0})
    with pytest.raises(ValueError, match="how='max' ist nicht zulässig"):
        three.forecast({5: 1.0}, how="max")
    with pytest.raises(ValueError, match="kinds='tests' ist nicht zulässig"):
        three.forecast({5: 1.0}, kinds=("tests",))
    with pytest.raises(ValueError, match="two_source='all' ist nicht zulässig"):
        three.forecast({5: 1.0}, two_source="all")
    with pytest.raises(ValueError, match="rest_A='tests' ist nicht zulässig"):
        three.forecast({5: 1.0}, rest_A="tests")
    with pytest.raises(ValueError, match="mode='all' ist nicht zulässig"):
        three.cross_check(mode="all")


def test_aggregation_over_the_earth_faults():
    """Z_q per order: median (component-wise), mean or the latest earth fault; the selection by kinds."""
    net_b = {m: (U, Z0 * 1.2, Z1, Z2, Us) for m, (U, Z0, Z1, Z2, Us) in NET.items()}
    net_c = {m: (U, Z0 * 0.9, Z1, Z2, Us) for m, (U, Z0, Z1, Z2, Us) in NET.items()}
    model = nm.NetworkModel()
    for name, net in (("a", NET), ("b", net_b), ("c", net_c)):
        model.add_test(phasors(name, 0.0, net=net))
    zq = [model.calibration(n).orders[5].Zq for n in "abc"]
    close(model.source_terms(how="median")[5].Zq, complex(np.median(np.real(zq)), np.median(np.imag(zq))))
    close(model.source_terms(how="mean")[5].Zq, np.mean(zq))
    close(model.source_terms(how="latest")[5].Zq, zq[-1])
    model.add_fault(phasors("f", 0.0, kind="fault", net=net_b), z0="b")
    assert model.source_terms(kinds=("fault",))[5].calibrations == ["f"]
    assert model.source_terms(kinds=("test",))[5].n == 3
    sub = model.subset(where=lambda c: c.name in "ab", kinds=("test",))
    assert sub.names == ["a", "b"] and sub.name == model.name
    model.remove("a")
    assert model.names == ["b", "c", "f"]
    assert repr(model).startswith("NetworkModel('', tests=2, faults=1, orders=[3, 5, 7, 11]")


# ------------------------------------------------------------------------------------------- cross-check
def test_cross_check_between_the_tests(three):
    loo = three.cross_check(mode="loo", conservative=False)
    assert set(loo.target) == {"0", "2.5", "5"} and set(loo["mode"]) == {"loo"}
    np.testing.assert_allclose(loo.ratio, 1.0, rtol=1e-9)        # exact data: every order and I_H exact
    assert set(loo.order) == {3, 5, 7, 11, "I_H"}
    assert loo.set_index(["target", "order"]).loc[("0", 3), "model"] == "2.5, 5"
    cons = three.cross_check(2.0, mode="loo")
    o3 = cons[cons.order == 3]
    assert (o3.deviation_A > 2.0).all()                           # magnitudes added: on the safe side
    np.testing.assert_allclose(cons[cons.order == 5].deviation_A, 2.0, atol=1e-9)
    pw = three.cross_check(mode="pairwise", conservative=False)
    assert len(pw[pw.order == 5]) == 6
    np.testing.assert_allclose(pw[pw.order.isin([5, 7, 11])].ratio, 1.0, rtol=1e-9)
    c3 = pw[pw.order == 3].set_index(["target", "model"])
    assert set(c3.kind) == {"constant"}
    assert c3.loc[("0", "5"), "I_forecast_A"] == pytest.approx(abs(three.calibration("5").orders[3].I))
    ch = three.cross_check(mode="chain", conservative=False)
    assert set(ch.model) == {"%s → %s" % (k, j) for k in ("0", "2.5", "5") for j in ("0", "2.5", "5") if k != j}
    np.testing.assert_allclose(ch[ch.order.isin([5, 7, 11])].ratio, 1.0, rtol=1e-9)
    # per-order margin
    pm = three.cross_check({5: 1.0}, mode="loo", conservative=False)
    np.testing.assert_allclose(pm[pm.order == 5].deviation_A, 1.0, atol=1e-9)
    np.testing.assert_allclose(pm[pm.order == 7].deviation_A, 0.0, atol=1e-9)
    with pytest.raises(ValueError, match="mindestens zwei Kalibrierversuche"):
        three.subset(names=["0"]).cross_check()
    with pytest.raises(ValueError, match="mindestens drei Kalibrierversuche"):
        three.subset(names=["0", "5"]).cross_check(mode="chain")


# ------------------------------------------------------------------------------------------- upstream split
def test_upstream_split_and_another_upstream_impedance(three):
    Zu = {5: 0.4 + 6.0j, 7: 0.5 + 8.0j}
    three.add_upstream("0", Zu)
    e = three.calibration("0").orders[5]
    close(1 / (1 / e.Z_down("pos") + 1 / Zu[5]), e.Z1)
    close(1 / (1 / e.Z_down("neg") + 1 / Zu[5]), e.Z2)
    new = 0.2 + 3.0j
    e2 = e.with_upstream(new)
    close(e2.Z1, new * e.Z_down("pos") / (new + e.Z_down("pos")))
    assert e2.Z0 == e.Z0 and e2.Z_up == new
    assert np.isnan(three.calibration("0").orders[11].Z_down())
    assert three.calibration("0").orders[11].with_upstream(new) is three.calibration("0").orders[11]
    T = three.subset(names=["0"]).source_terms(upstream={5: new, 11: new})
    close(T[5].Zq, e2.Zq)
    assert any("keine Vorimpedanz für Ordnung 11" in h for h in T[11].hints)
    tab = three.table().set_index(["name", "order"])
    assert tab.loc[("0", 5), "Z_up_Ohm"] == pytest.approx(abs(Zu[5]))
    assert tab.loc[("0", 5), "Z_down_Ohm"] == pytest.approx(abs(e.Z_down("pos")))
    assert np.isnan(tab.loc[("2.5", 5), "Z_up_Ohm"])


def test_upstream_from_the_transformer_node(tmp_path):
    path = str(tmp_path / "TR_0_10_000kHz.cfg")
    w = demo.make_transformer_recording(path)
    b = w["intervals"]
    res = evaluate(open_recording(path), Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]),
                                                   tuple(b["post_fault"])))
    zu = nm.upstream_from_result(res)
    assert {5, 7, 11} <= set(zu) <= set(w["Z_up"])
    for m, z in zu.items():
        true = complex(w["Z_up"][m]["re"], w["Z_up"][m]["im"])
        assert abs(z - true) <= 0.01 * abs(true), m
    p = res.save_json(str(tmp_path / "TR_result.json"))
    assert nm.upstream_from_result(p) == pytest.approx(zu)
    # the busbar voltages of the transformer recording as a recorded earth fault: Z_up attached by itself
    fd = nm.load_fault_data(p)
    assert fd.kind == "fault" and fd.Z_up == pytest.approx(zu)
    model = nm.NetworkModel()
    c = model.add_fault(fd, z0={m: 10.0 - 30.0j for m in (5, 7, 11, 13)}, min_dU0_V=0.0)
    assert {m: e.Z_up for m, e in c.orders.items() if e.Z_up is not None} == pytest.approx(
        {m: z for m, z in zu.items() if m in c.orders})
    assert "Z_up_Ohm" in model.table().columns


def test_upstream_prefers_the_sequence_other_than_the_natural_one():
    from groundfault.forecast.data import _upstream_rows

    def row(m, seq, z, sig=True):
        return dict(order=m, sequence=seq, Z_up_Ohm=abs(z), Z_up_angle_deg=float(np.degrees(np.angle(z))),
                    significant=sig)
    rows = [row(5, "neg", 8 * np.exp(1.75j)), row(5, "pos", 10 * np.exp(1.53j)),        # natural 5: negative
            row(7, "pos", 34 * np.exp(2.1j)), row(7, "neg", 13 * np.exp(1.52j), sig=False),
            row(11, "pos", 20 * np.exp(1.5j)), row(9, "pos", 3 + 1j), row(1, "pos", 1 + 1j)]
    zu = _upstream_rows(rows, True)
    assert set(zu) == {5, 11}                           # 7: only the natural sequence is significant – no Z_up
    assert zu[5] == pytest.approx(10 * np.exp(1.53j))
    assert zu[11] == pytest.approx(20 * np.exp(1.5j))
    assert _upstream_rows(rows, False)[7] == pytest.approx(13 * np.exp(1.52j))


def test_upstream_needs_the_transformer_table(demo_results):
    res = demo_results[0.0][0]
    with pytest.raises(ValueError, match="keine Tabelle transformer_impedance"):
        nm.upstream_from_result(res)


# ------------------------------------------------------------------------------------------- persistence
def test_save_and_load(three, tmp_path):
    three.add_fault(phasors("f", 0.0, kind="fault"), meta={"load_MW": np.float64(12.5), "PV": True, "Z": 1 + 2j,
                                                           "feeders": ("A", np.int64(3))})
    three.add_upstream("0", {5: 0.4 + 6.0j})
    three.description = "Demo"
    p = three.save(str(tmp_path / "models" / "net.json"))
    d = json.load(open(p, encoding="utf-8"))
    assert d["format"] == nm.MODEL_FORMAT and d["version"] == nm.MODEL_VERSION and d["name"] == "net"
    back = nm.NetworkModel.load(p)
    assert back.name == "net" and back.description == "Demo" and back.names == three.names
    pd.testing.assert_frame_equal(back.table(), three.table())
    pd.testing.assert_frame_equal(back.source_table(), three.source_table())
    assert back.calibration("f").meta == {"load_MW": 12.5, "PV": True, "Z": {"re": 1.0, "im": 2.0},
                                          "feeders": ["A", 3]}
    assert back.calibration("f").Z_F is None and back.calibration("0").Z_F == 0
    f1 = three.forecast({3: 4.0, 5: 220.0, 7: 110.0, 11: 35.0}, 1.0, 2.0)
    f2 = back.forecast({3: 4.0, 5: 220.0, 7: 110.0, 11: 35.0}, 1.0, 2.0)
    pd.testing.assert_frame_equal(f1.table(), f2.table())
    d["format"] = "something"
    with pytest.raises(ValueError, match="keine Netzmodell-Datei"):
        nm.NetworkModel.from_dict(d, "x.json")
    d["format"] = nm.MODEL_FORMAT
    d["version"] = nm.MODEL_VERSION + 1
    with pytest.raises(ValueError, match="ist neuer als dieses groundfault"):
        nm.NetworkModel.from_dict(d, "x.json")


# ------------------------------------------------------------------------------------------- recordings
H = [demo.DemoHarmonic(3, demo.polar(4, 30), -demo.polar(4, 30), 2.0 - 1.0j, Us=demo.polar(30, -60))]
for _m, _U, _Zq, _Z1, _Z2 in ((5, demo.polar(220, -35), 6.0 + 1.5j, 9.0 + 2.0j, 8.0 + 1.0j),
                              (7, demo.polar(110, 50), 5.0 - 3.5j, 1.0 - 6.0j, 2.0 - 5.0j),
                              (11, demo.polar(35, 80), 2.5 - 2.2j, 0.5 + 1.0j, 1.0 + 0.5j)):
    H.append(demo.DemoHarmonic(_m, _U, -phase_factor(natural_sequence(_m), "L3") * _U, _Zq, _Z1, _Z2))


def _evaluate(folder, w, Z=None):
    b = w["intervals"]
    res = evaluate(open_recording(os.path.join(folder, w["file"])),
                   Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]), tuple(b["post_fault"])),
                   z_fault_ohm=Z)
    return res.save_json(os.path.join(folder, w["file"].replace(".cfg", "_result.json")))


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    """Tests 0/2.5/5 Ω with Z_1, Z_2 and a source that arises in the fault, and an earth fault without fault
    current (busbar voltages only, other source drift)."""
    folder = str(tmp_path_factory.mktemp("network_model"))
    truth = demo.make_substation_series(folder, harmonic_sources=H, prefix="NET",
                                        drift={0.0: 1.0, 2.5: demo.polar(1.2, 30), 5.0: demo.polar(0.9, -25)})
    paths = {w["Z_F"]: _evaluate(folder, w, w["Z_F"]) for w in truth}
    w = demo.make_substation_recording(os.path.join(folder, "NET_fault_10_000kHz.cfg"), 0.0, harmonic_sources=H,
                                       drift=demo.polar(1.1, 15), fault_current=False, seed=9)
    w["file"] = "NET_fault_10_000kHz.cfg"
    return truth, paths, w, _evaluate(folder, w)


def test_recordings_end_to_end(recorded):
    truth, paths, wf, pf = recorded
    model = nm.NetworkModel("NET")
    for w in truth:
        fd = nm.load_fault_data(paths[w["Z_F"]], w["Z_F"], name="%g" % w["Z_F"], meta={"PV": False})
        assert fd.kind == "test" and fd.faulted_phase == "L3" and fd.meta == {"PV": False}
        c = model.add_test(fd)
        assert sorted(c.orders) == [3, 5, 7, 11]
        for m in (5, 7, 11):
            hs = w["harmonic_sources"][m]
            e = c.orders[m]
            assert abs(e.Zq - hs["Zq"]) <= 0.02 * abs(hs["Zq"]), m
            for est, true in ((e.Z1, hs["Z1"]), (e.Z2, hs["Z2"])):
                assert abs(est - true) <= 0.03 * abs(hs["Zq"]) + 0.05, m
        assert c.I1 == pytest.approx(math.hypot(w["Iw"], w["Iv"]), rel=0.02)
    T = model.source_terms()
    hs3 = truth[0]["harmonic_sources"][3]
    assert T[3].kind == "two_source"
    assert abs(T[3].Zq - hs3["Zq"]) <= 0.03 * abs(hs3["Zq"]) and abs(T[3].Us - hs3["Us"]) <= 0.03 * abs(hs3["Us"])
    # leave-one-out on the recordings: the orders of the pre-fault source within 2 %, order 3 on the safe side
    loo = model.cross_check(mode="loo")
    r = loo[loo.order.isin([5, 7, 11])].ratio
    assert r.between(0.98, 1.02).all() and (loo[loo.order == 3].ratio > 0.99).all()
    # earth fault without fault current: Z_q and the fault current from the busbar voltages
    fd = nm.load_fault_data(pf)
    assert fd.kind == "fault" and fd.faulted_phase == "L3" and not fd.I and fd.Z_F is None
    c = model.add_fault(fd)
    for m in (5, 7, 11):
        hs = wf["harmonic_sources"][m]
        assert abs(c.orders[m].Zq - hs["Zq"]) <= 0.01 * abs(hs["Zq"]), m
        assert c.orders[m].I_estimated == pytest.approx(hs["I"], rel=0.01), m
    # forecast for the state of that earth fault (pre-fault voltages from its truth): exact for the orders of the
    # pre-fault source, on the safe side for order 3
    U = {m: abs(wf["harmonic_sources"][m]["U_pre_ll"]) for m in (3, 5, 7, 11)}
    f = model.forecast(U, Z_F=0.0)
    for m in (5, 7, 11):
        assert f.currents.loc["value", m] == pytest.approx(wf["harmonic_sources"][m]["I"], rel=0.02), m
    assert f.currents.loc["value", 3] >= 0.99 * wf["harmonic_sources"][3]["I"]
    # a test read as a recorded earth fault
    assert nm.load_fault_data(paths[2.5], 2.5, use_current=False).kind == "fault"
    assert nm.load_fault_data(paths[2.5]).kind == "fault"                   # no additional impedance given
    # default name: the measurement (result suffix of either layout removed)
    assert nm.load_fault_data(paths[2.5]).name == "NET_2_5_10_000kHz"
    assert nm.load_fault_data(paths[0.0], 0.0).name == "NET_0_10_000kHz"
    assert nm.measurement_name("x/UW_0_ergebnis.json") == "UW_0" and nm.measurement_name("a.json") == "a"


def test_result_files_contain_the_mean_fault_phasors(demo_results):
    """Busbar phasors during the fault averaged over the used windows of the steady state (the max window is a
    single window) – they agree with the max window for a stationary fault."""
    res, w, p, _ = demo_results[0.0]
    v = json.load(open(p, encoding="utf-8"))["voltage"]
    assert v["fault_mean_windows"] >= 5
    orders = v["orders"]
    k = orders.index(5)
    for key in ("U_pos", "U_neg", "U_zero", "U_L1E", "U_L2E", "U_L3E"):
        a = complex(v["fault_mean_phasor"][key][k]["re"], v["fault_mean_phasor"][key][k]["im"])
        b = complex(v["fault_phasor"][key][k]["re"], v["fault_phasor"][key][k]["im"])
        assert abs(a - b) <= 0.02 * abs(b) + 0.5, key


def test_fault_data_from_the_equivalent_source_measurement(demo_results):
    _, w, p, _ = demo_results[2.5]
    m = load_measurement(p, 2.5, "2.5 Ω")
    fd = nm.fault_data_from_measurement(m, I_C=500.0, Iv=25.0, meta={"a": 1})
    assert fd.kind == "test" and fd.I_C == 500.0 and fd.Iv == 25.0 and fd.Z_F == 2.5 and fd.meta == {"a": 1}
    assert fd.U0 == pytest.approx(abs(m.U_fault[1]["zero"]))
    model = nm.NetworkModel()
    c = model.add_test(m)                                                # a measurement directly
    assert c.name == "2.5 Ω" and set(c.orders) >= {5, 7}
    v = nm.fault_data_from_measurement(m, "fault")
    assert v.kind == "fault" and not v.I and v.Z_F is None
    with pytest.raises(ValueError, match="kind='both' ist nicht zulässig"):
        nm.fault_data_from_measurement(m, "both")


def test_load_fault_data_errors(tmp_path):
    p = tmp_path / "empty_result.json"
    p.write_text(json.dumps({"values": {}, "voltage": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="keine Sammelschienenspannungen vor und im Fehler"):
        nm.load_fault_data(str(p))


# ------------------------------------------------------------------------------------------- bounds
def test_bounds_without_calibration():
    U_LE = 20000 / math.sqrt(3)
    # tuned network: 3·U_m/|Z_0c| = U_m·(m − 1/m)·I_C/U_LE
    assert nm.classical_bound(100.0, 5, 300.0, U_LE) == pytest.approx(100.0 * (5 - 1 / 5) * 300.0 / U_LE)
    assert nm.classical_bound(100.0, 5, 300.0, U_LE, I_L=330.0) == pytest.approx(
        100.0 * (5 / 1 - 330.0 / (5 * 300.0)) * 300.0 / U_LE)
    with_ZF = nm.classical_bound(100.0, 5, 300.0, U_LE, Z_F=5.0)
    assert with_ZF < nm.classical_bound(100.0, 5, 300.0, U_LE)
    assert nm.resonance_bound(100.0, 5, 300.0, U_LE, G_max=0.5) < nm.classical_bound(100.0, 5, 300.0, U_LE)
    assert nm.resonance_bound(100.0, 5, 300.0, U_LE, G_max=1e9) == pytest.approx(
        nm.classical_bound(100.0, 5, 300.0, U_LE), rel=1e-6)


# ------------------------------------------------------------------------------------------- language and names
def test_german_labels_and_english_messages(three):
    with i18n.language("de"):
        tab = i18n.localize(three.cross_check(mode="loo"))
        assert {"Modus", "Ziel", "Modell", "I_gemessen_A", "I_Prognose_A", "Abweichung_A", "Verhaeltnis"} <= set(
            tab.columns)
        assert set(tab["Modus"]) == {"alle anderen"} and "zwei Quellen" in set(tab["Art"])
        st = i18n.localize(three.source_table())
        assert {"Ordnung", "Art", "Zq_Winkel_deg", "Us_Winkel_deg", "I_konstant_A", "Kalibrierungen"} <= set(st.columns)
        t = i18n.localize(three.table())
        assert set(t["Art"]) == {"Versuch"} and "I_geschaetzt_A" in t.columns
        f = i18n.localize(three.forecast({5: 220.0}, margin_A=1.0).table())
        assert "Zuschlag_A" in f.columns and "Vorfehlerquelle" in set(f["Art"])
    with i18n.language("en"):
        f = three.forecast({5: 220.0})
        assert any("orders 7, 11: no voltage given" in h for h in f.hints)
        with pytest.raises(ValueError, match="the network model contains no calibration"):
            nm.NetworkModel().source_terms()
        with pytest.raises(KeyError, match="no calibration named 'x'"):
            three.calibration("x")


def test_public_names():
    import groundfault
    for name in nm.__all__:
        assert hasattr(nm, name), name
    assert "forecast" in groundfault.__doc__ and "network_model" not in groundfault.__doc__


def test_import_groundfault_does_not_load_the_forecast():
    """The forecast is optional: the evaluation and ``import groundfault`` do not load it."""
    import subprocess
    import sys
    src = os.path.join(os.path.dirname(__file__), os.pardir, "src")
    code = ("import sys; sys.path.insert(0, %r); import groundfault, groundfault.evaluation, groundfault.report, "
            "groundfault.campaign, groundfault.equivalent_source; print('groundfault.forecast' in sys.modules)" % src)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "False"


# ------------------------------------------------------------------------------------------- node rule (coil currents)
def test_node_rule_gives_the_fault_current_of_a_recorded_earth_fault():
    """With coil currents in the tests and in the recording, I_F,m = 3·Y_0,net,m·ΔU_0,m + I_coil,m holds exactly –
    also at the order with the source that arises in the fault (the coil carries it)."""
    model = nm.NetworkModel("net")
    for Z, d in DRIFT.items():
        c = model.add_test(phasors("%g" % Z, Z, drift=d, coils=True))
        for m, (U, Z0, Z1, Z2, Us) in NET.items():
            close(c.orders[m].Y0_net, 1 / Z0 - 1 / (3j * m * X_COIL))        # network without the coil
    true = phasors("x", 1.0, "L2", drift=demo.polar(1.3, 40), kind="fault", keep_current=True)
    c = model.add_fault(phasors("f", 1.0, "L2", drift=demo.polar(1.3, 40), kind="fault", coils=True))
    assert set(c.currents) == {3, 5, 7, 11} and set(c.current_method.values()) == {"node_rule"}
    for m in NET:
        close(c.currents[m], true.I[m])
    assert any("Knotenregel" in h for h in c.hints) and sorted(c.orders) == [5, 7, 11]
    assert c.orders[5].I_estimated == pytest.approx(abs(true.I[5]))
    # without coil currents in the tests: the zero-sequence voltage, not at the order of the source in the fault
    plain = nm.NetworkModel()
    for Z, d in DRIFT.items():
        plain.add_test(phasors("%g" % Z, Z, drift=d))
    c2 = plain.add_fault(phasors("f", 1.0, "L2", drift=demo.polar(1.3, 40), kind="fault", coils=True))
    assert set(c2.current_method.values()) == {"zero_sequence_voltage"}
    assert any("kein Kalibrierversuch mit Spulenströmen" in h for h in c2.hints)
    for m in (5, 7, 11):
        assert abs(c2.currents[m]) == pytest.approx(abs(true.I[m]))
    # not at the order of the source in the fault: 3·ΔU_0/Z_0 would be far off there (ΔU_0 = Z_0·I_F/3 − U_s)
    assert 3 not in c2.currents
    f = phasors("f", 1.0, "L2", drift=demo.polar(1.3, 40), kind="fault", coils=True)
    Z0_3 = plain.calibration("0").orders[3].Z0
    wrong = 3 * (f.U_fault[3]["zero"] - f.U_pre[3]["zero"]) / Z0_3
    assert abs(abs(wrong) - abs(true.I[3])) > 0.05 * abs(true.I[3])


def test_fault_check_at_recorded_earth_faults():
    model = nm.NetworkModel("net")
    for Z, d in DRIFT.items():
        model.add_test(phasors("%g" % Z, Z, drift=d, coils=True))
    for k, d in enumerate((demo.polar(1.2, 20), demo.polar(0.8, -50))):
        model.add_fault(phasors("f%d" % k, 0.0, drift=d, kind="fault", coils=True))
    chk = model.fault_check()
    assert set(chk["mode"]) == {"fault_check"} and set(chk["target"]) == {"f0", "f1"}
    per = chk[chk.order.isin([5, 7, 11])]
    assert per.deviation_A.abs().max() < 1e-6                  # exact data: the pre-fault orders exactly
    assert (chk[chk.order == 3].deviation_A >= -1e-9).all()      # magnitudes of U_q and U_s added: safe side
    assert set(chk[chk.order == 5]["I_estimated_method"]) == {"node_rule"}
    with2 = model.fault_check(2.0)
    assert (with2.deviation_A - chk.deviation_A).round(9).eq(2.0).all()
    with pytest.raises(ValueError, match="Kein aufgezeichneter Erdschluss mit geschätztem Fehlerstrom"):
        nm.NetworkModel().fault_check()


def test_recorded_earth_fault_with_saturating_coils(tmp_path):
    """COMTRADE recordings whose coils carry the source of the fault: the coil currents are read (mean over the
    reference windows), oriented and summed; the node rule reproduces the fault current of a recording without
    fault-current channel at every order."""
    folder = str(tmp_path)
    truth = demo.make_substation_series(folder, harmonic_sources=H, prefix="NET", fault_source_in_coils=True,
                                        drift={0.0: 1.0, 2.5: demo.polar(1.2, 30), 5.0: demo.polar(0.9, -25)})
    model = nm.NetworkModel("NET")
    for w in truth:
        fd = nm.load_fault_data(_evaluate(folder, w, w["Z_F"]), w["Z_F"], name="%g" % w["Z_F"])
        assert set(fd.I_coil) >= {3, 5, 7, 11} and not any("gedreht" in h for h in fd.hints)
        model.add_test(fd)
    w = demo.make_substation_recording(os.path.join(folder, "NET_fault_10_000kHz.cfg"), 0.0, harmonic_sources=H,
                                       drift=demo.polar(1.1, 15), fault_current=False, seed=9,
                                       fault_source_in_coils=True)
    w["file"] = "NET_fault_10_000kHz.cfg"
    p = _evaluate(folder, w)
    v = json.load(open(p, encoding="utf-8"))["voltage"]
    assert len(v["coil_mean_phasor"]) == 2                              # two coils, mean over the same windows
    fd = nm.load_fault_data(p)
    assert fd.kind == "fault" and set(fd.I_coil) >= {3, 5, 7, 11}
    c = model.add_fault(fd)
    for m in (3, 5, 7, 11):
        assert c.current_method[m] == "node_rule"
        assert abs(c.currents[m]) == pytest.approx(w["harmonic_sources"][m]["I"], rel=0.03), m


def test_reversed_coil_channel_is_turned(tmp_path):
    folder = str(tmp_path)
    w = demo.make_substation_recording(os.path.join(folder, "R_0_10_000kHz.cfg"), 0.0, harmonic_sources=H)
    w["file"] = "R_0_10_000kHz.cfg"
    p = _evaluate(folder, w, 0.0)
    d = json.load(open(p, encoding="utf-8"))
    name = next(k for k, s in d["signals"].items() if s.get("role") == "i_coil")
    for h in d["signals"][name]["harmonics"].values():
        h["ang_deg"] += 180.0                                          # clamp reversed: every phasor of the channel
    for key in ("coil_pre_phasor", "coil_mean_phasor"):
        if name in d["voltage"].get(key, {}):
            d["voltage"][key][name] = [dict(re=-z["re"], im=-z["im"]) for z in d["voltage"][key][name]]
    q = os.path.join(folder, "R_rev_result.json")
    json.dump(d, open(q, "w", encoding="utf-8"))
    a, b = nm.load_fault_data(p, 0.0), nm.load_fault_data(q, 0.0)
    assert any("um 180° gedreht" in h and "ISp" in h for h in b.hints)
    for m in a.I_coil:
        close(a.I_coil[m], b.I_coil[m], 1e-6)


def test_coil_currents_before_the_fault_are_subtracted(tmp_path):
    """The node rule takes the change of the coil currents: the coil current before the fault (result file entry
    ``voltage.coil_pre_phasor``, mean over the pre-fault interval) is subtracted per order."""
    folder = str(tmp_path)
    w = demo.make_substation_recording(os.path.join(folder, "R_0_10_000kHz.cfg"), 0.0, harmonic_sources=H)
    w["file"] = "R_0_10_000kHz.cfg"
    p = _evaluate(folder, w, 0.0)
    d = json.load(open(p, encoding="utf-8"))
    ords = [int(o) for o in d["voltage"]["orders"]]
    name = next(iter(d["voltage"]["coil_pre_phasor"]))
    pre = {m: complex(z["re"], z["im"]) for m, z in zip(ords, d["voltage"]["coil_pre_phasor"][name])}
    d["voltage"]["coil_pre_phasor"][name] = [dict(re=0.0, im=0.0) for _ in ords]
    q = os.path.join(folder, "R_nopre_result.json")
    json.dump(d, open(q, "w", encoding="utf-8"))
    a, b = nm.load_fault_data(p, 0.0), nm.load_fault_data(q, 0.0)
    assert any(abs(pre[m]) > 0 for m in a.I_coil)
    for m in a.I_coil:
        assert abs(b.I_coil[m] - a.I_coil[m]) == pytest.approx(abs(pre[m]), rel=1e-9, abs=1e-12)


# ------------------------------------------------------------------------------------------- line (fault in the network)
def test_line_impedances_and_wavelength():
    line = nm.Line([dict(length_km=4.0, R1=0.125, X1=0.11, R0=0.5, X0=0.4, C1_uF=0.3, name="cable"),
                    nm.LineSegment(2.0, 0.3, 0.35, 0.45, 1.2, C1_uF=0.01, name="overhead")], "feeder 7")
    assert line.length_km == 6.0
    close(line.Z1(5), 4.0 * (0.125 + 0.55j) + 2.0 * (0.3 + 1.75j))
    close(line.Z0(5), 4.0 * (0.5 + 2.0j) + 2.0 * (0.45 + 6.0j))
    close(line.Zq(5), (2 * line.Z1(5) + line.Z0(5)) / 3)
    # λ/4 at order m: v = 1/√(L'·C'), λ = v/(m·50 Hz)
    v1 = 1 / math.sqrt(0.11 / (2 * math.pi * 50) * 0.3e-6)
    v2 = 1 / math.sqrt(0.35 / (2 * math.pi * 50) * 0.01e-6)
    assert line.wavelength_fraction(13) == pytest.approx(4.0 / (v1 / 650 / 4) + 2.0 / (v2 / 650 / 4))
    assert nm.Line.from_impedances(1 + 2j, 3 + 6j).wavelength_fraction(5) is None
    close(nm.Line.from_impedances(1 + 2j, 3 + 6j).Zq(5), (2 * (1 + 10j) + (3 + 30j)) / 3)
    back = nm.Line.from_dict(json.loads(json.dumps(line.to_dict())))
    close(back.Zq(7), line.Zq(7))
    assert nm.Line.from_dict(None) is None
    with pytest.raises(ValueError, match="mindestens einen Abschnitt"):
        nm.Line([])


def test_line_values_per_order(three):
    """Values of single orders replace the 50-Hz form there – per segment (R', X' at m·50 Hz) or for the whole line
    (loop contribution, e.g. measured); the forecast names the orders that use the 50-Hz values."""
    seg = dict(length_km=4.0, R1=0.125, X1=0.11, R0=0.5, X0=0.4, orders={5: dict(R1=0.14, X1=0.48, R0=0.9, X0=1.5)})
    line = nm.Line([seg, dict(length_km=2.0, R1=0.3, X1=0.35, R0=0.45, X0=1.2)], "f")
    close(line.Z1(5), 4.0 * (0.14 + 0.48j) + 2.0 * (0.3 + 1.75j))
    close(line.Z0(7), 4.0 * (0.5 + 2.8j) + 2.0 * (0.45 + 8.4j))
    assert line.source(5) == "mixed" and line.source(7) == "50Hz" and line.orders_given() == []
    line2 = nm.Line(line.segments, "f", loop={5: [3.0, 9.0], "7": {"re": 4.0, "im": 12.0}})
    close(line2.Zq(5), 3 + 9j)
    close(line2.Zq(7), 4 + 12j)
    close(line2.Zq(11), line.Zq(11))
    assert line2.source(5) == "loop" and line2.orders_given() == [5, 7]
    back = nm.Line.from_dict(json.loads(json.dumps(line2.to_dict())))
    for m in (5, 7, 11):
        close(back.Zq(m), line2.Zq(m))
    assert back.segments[0].orders == {5: dict(R1=0.14, X1=0.48, R0=0.9, X0=1.5)}
    assert "orders" not in nm.Line([dict(length_km=1, R1=1, X1=1, R0=1, X0=1)]).to_dict()["segments"][0]
    tot = nm.Line.from_impedances(1.5 + 1.8j, 6 + 4.5j, "strand", orders={5: (1.6 + 8.2j, [6.6, 15.0])})
    close(tot.Zq(5), (2 * (1.6 + 8.2j) + (6.6 + 15.0j)) / 3)
    close(tot.Zq(7), (2 * (1.5 + 12.6j) + (6 + 31.5j)) / 3)
    assert tot.source(5) == "orders" and tot.orders_given() == [5]
    U = {3: 4.0, 5: 220.0, 7: 110.0, 11: 35.0}
    f = three.forecast(U, line=tot)
    assert any("eigene Werte bei Ordnung 5" in h and "Ordnungen 3, 7, 11 aus den 50-Hz-Werten" in h for h in f.hints)
    assert any("alle Ordnungen aus den 50-Hz-Werten" in h for h in three.forecast(U, line=line).hints)
    assert not any("50-Hz" in h for h in three.forecast({5: 220.0, 7: 110.0}, orders=[5, 7], line=line2).hints)
    with pytest.raises(ValueError, match="X0 fehlt"):
        nm.LineSegment(1.0, 0.1, 0.1, 0.5, 0.4, orders={5: dict(R1=0.1, X1=0.5, R0=0.6)})
    with pytest.raises(ValueError, match="keine komplexe Zahl"):
        nm.Line([seg], loop={5: [1, 2, 3]})


def test_forecast_and_tests_behind_a_line(three):
    """Fault behind a line: the line adds (2·Z_1L + Z_0L)/3 to the loop; tests in the network calibrate the busbar
    model (and separate the source of the fault with their series impedances); verify() checks an in-network
    measurement against the busbar model."""
    line = nm.Line([dict(length_km=3.0, R1=0.2, X1=0.12, R0=0.6, X0=0.45, C1_uF=0.25)], "station A")
    U = {3: 4.0, 5: 220.0, 7: 110.0, 11: 35.0}
    f = three.forecast(U, Z_F=1.0, line=line)
    terms = three.source_terms()
    for m in (5, 7, 11):
        assert f.currents.loc["value", m] == pytest.approx(U[m] / abs(terms[m].Zq + 1.0 + line.Zq(m)))
    assert f.currents.loc["value", 3] == pytest.approx((4.0 + abs(terms[3].Us)) / abs(terms[3].Zq + 1.0 + line.Zq(3)))
    t = f.table()
    assert "Z_line_Ohm" in t.columns and t.set_index("order").loc[5, "Z_line_Ohm"] == pytest.approx(abs(line.Zq(5)))
    assert any("Leitung station A" in h and "Viertelwellenlänge" in h for h in f.hints)
    # in-network tests at different fault resistances calibrate: same busbar Z_q, source of the fault separated
    inside = nm.NetworkModel("in")
    for Z, d in DRIFT.items():
        c = inside.add_test(phasors("n%g" % Z, Z, drift=d, line=line))
        assert c.line is line
        close(c.series_impedance(5), Z + line.Zq(5))
    T = inside.source_terms()
    for m in (5, 7, 11):
        close(T[m].Zq, Zq_of(m))
    close(T[3].Zq, Zq_of(3), 1e-6)
    close(T[3].Us, NET[3][4], 1e-6)
    tab = inside.table()
    assert set(tab["line_name"]) == {"station A"}
    # verify: an in-network measurement against the busbar model (exact for the pre-fault orders)
    meas = phasors("remote", 0.5, drift=demo.polar(1.1, 25), line=line)
    chk = three.verify(meas)
    assert set(chk["mode"]) == {"verify"}
    assert chk[chk.order.isin([5, 7, 11])].deviation_A.abs().max() < 1e-6
    assert (chk[chk.order == 3].deviation_A >= -1e-9).all()
    assert "I_H" in set(chk.order)
    # without the line the in-network current is overestimated
    plain = three.verify(meas, line=None)
    assert three.verify(meas, Z_F=0.5, line=line).deviation_A.equals(chk.deviation_A)
    assert (plain[plain.order.isin([5, 7, 11])].deviation_A.values
            >= chk[chk.order.isin([5, 7, 11])].deviation_A.values - 1e-9).all()
    meas.I = {}
    with pytest.raises(ValueError, match="kein Fehlerstrom zum Vergleich"):
        three.verify(meas)


def test_constant_source_behind_a_line():
    """One test in the network: the order with the source of the fault keeps its current – a hint for a smaller
    series impedance in the forecast."""
    line = nm.Line.from_impedances(0.5 + 0.3j, 1.5 + 1.0j, "L")
    one = nm.NetworkModel()
    one.add_test(phasors("n", 0.0, line=line))
    T = one.source_terms()[3]
    assert T.kind == "constant" and T.Z_F_constant == pytest.approx(abs(line.Zq(3)))
    assert any("kleineren 0 Ω" in h for h in one.forecast({3: 4.0, 5: 220.0}).hints)
    assert not any("kleineren" in h for h in one.forecast({3: 4.0, 5: 220.0}, line=line).hints)


# ------------------------------------------------------------------------------------------- input formats
def test_fault_data_from_values():
    A = np.exp(2j * np.pi / 3)
    ref = phasors("t", 2.5, coils=True)

    def phases(block):
        return {m: {"L1": v["zero"] + v["pos"] + v["neg"], "L2": v["zero"] + A ** 2 * v["pos"] + A * v["neg"],
                    "L3": v["zero"] + A * v["pos"] + A ** 2 * v["neg"]} for m, v in block.items()}
    fd = nm.fault_data_from_values("t", phases(ref.U_pre), phases(ref.U_fault), I=ref.I, Z_F=2.5, faulted_phase="L3",
                                   I_coil=ref.I_coil, Iw=20.0, Iv=25.0, IH_sum=ref.IH_sum,
                                   line=dict(segments=[dict(length_km=1, R1=0.1, X1=0.1, R0=0.3, X0=0.3)]))
    assert fd.kind == "test" and fd.Z_F == 2.5 and fd.line is not None and fd.line.length_km == 1
    for m in ref.U_pre:
        for s in SEQ:
            close(fd.U_pre[m][s], ref.U_pre[m][s], 1e-9)
            close(fd.U_fault[m][s], ref.U_fault[m][s], 1e-9)
        close(fd.dU0_coil[m], ref.dU0_coil[m], 1e-9)
    c = nm.NetworkModel().add_test(fd)
    for m, (U, Z0, Z1, Z2, Us) in NET.items():
        close(c.orders[m].Z1, Z1, 1e-9)
    f = nm.fault_data_from_values("f", ref.U_pre, ref.U_fault)
    assert f.kind == "fault" and not f.I and f.line is None
    with pytest.raises(ValueError, match="entweder als Sequenzen"):
        nm.fault_data_from_values("x", {5: {"L1": 1, "pos": 2}}, {5: {"pos": 1}})


def test_model_file_version_1_and_2(three, tmp_path):
    three.add_fault(phasors("f", 0.0, drift=1.1, kind="fault"))
    d = three.to_dict()
    assert d["version"] == 2 and d["calibrations"][-1]["currents"] and d["calibrations"][-1]["U_q"]
    old = json.loads(json.dumps(d))
    old["version"] = 1
    for c in old["calibrations"]:
        for k in ("line", "currents", "current_method", "U_q"):
            c.pop(k, None)
        for e in c["orders"].values():
            e.pop("Y0_net", None)
    back = nm.NetworkModel.from_dict(old, "v1.json")
    assert back.names == three.names and not back.calibration("f").currents
    close(back.calibration("0").U_q[5], three.calibration("0").orders[5].U_q)
    pd.testing.assert_frame_equal(back.source_table(), three.source_table())
    # version 2 with a line and coil admittances round-trips
    m2 = nm.NetworkModel("in")
    m2.add_test(phasors("n", 2.5, coils=True, line=nm.Line.from_impedances(0.4 + 0.2j, 1.2 + 0.8j, "L")))
    m2.add_fault(phasors("g", 0.0, kind="fault", coils=True))
    back2 = nm.NetworkModel.load(m2.save(str(tmp_path / "m2.json")))
    assert back2.calibration("n").line.name == "L"
    close(back2.calibration("n").orders[5].Y0_net, m2.calibration("n").orders[5].Y0_net)
    assert back2.calibration("g").current_method == m2.calibration("g").current_method
    pd.testing.assert_frame_equal(back2.table(), m2.table())


# ------------------------------------------------------------------------------------------- campaigns as input
def test_campaign_tests_and_build_model(tmp_path):
    """German work folder with the demo campaign: the register gives the tests and their additional impedances;
    the model is built from the result files; missing result files are reported."""
    from groundfault import layout as _layout
    base = str(tmp_path)
    info = demo.make_campaign(base, layout="de", groundmeas=False)
    tests = nm.campaign_tests(base, "2026-01-15_Demo")
    assert [t["Z"] for t in tests] == [0.0, 2.5, 5.0]
    assert [t["measurement"] for t in tests] == ["UW_0_10_000kHz", "UW_2_5_10_000kHz", "UW_5_10_000kHz"]
    assert all("transformer" not in t for t in tests)
    model, msgs = nm.build_model(base, tests, name="Demo")
    assert not model.calibrations and len(msgs) == 3 and all("Ergebnisdatei fehlt" in x for x in msgs)
    lay = _layout.GERMAN
    for w in info["substation"]:
        b = w["intervals"]
        res = evaluate(open_recording(os.path.join(info["campaign"], w["cfg"])),
                       Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]), tuple(b["post_fault"])),
                       z_fault_ohm=w["Z_F"])
        res.save_json(lay.result_path(info["campaign"], os.path.splitext(w["file"])[0]))
    model, msgs = nm.build_model(base, tests, name="Demo")
    assert [c.name for c in model.tests] == ["UW_0_10_000kHz", "UW_2_5_10_000kHz", "UW_5_10_000kHz"]
    assert nm.result_path(base, "2026-01-15_Demo", "UW_0_10_000kHz").endswith("UW_0_10_000kHz_ergebnis.json")
    assert nm.forecast_folder(base, "Demo UW").endswith(os.path.join("05_Prognose", "demo_uw"))
    # a measurement to check the model with: busbar voltages of one recording, fault current of another
    fd = nm.check_data(base, dict(campaign="2026-01-15_Demo", measurement="UW_2_5_10_000kHz", Z=2.5,
                                  current="UW_2_5_10_000kHz"))
    ref = load_measurement(nm.result_path(base, "2026-01-15_Demo", "UW_2_5_10_000kHz"), 2.5)
    assert fd.Z_F == 2.5 and fd.I[5] == pytest.approx(abs(ref.I[5])) and np.isfinite(fd.IH_sum)
    chk = model.verify(fd)
    assert chk[chk.order.isin([5, 7])].ratio.between(0.97, 1.03).all()
    with pytest.raises(FileNotFoundError, match="Ergebnisdatei fehlt"):
        nm.check_data(base, dict(campaign="2026-01-15_Demo", measurement="UW_2_5_10_000kHz", current="nope"))
    with pytest.raises(ValueError, match="nicht im Messregister"):
        nm.campaign_tests(base, "1999-01-01_Nowhere")
    with pytest.raises(ValueError, match="unbekannter Schlüssel 'zf'"):
        nm.build_model(base, [dict(campaign="x", measurement="y", zf=1.0)])
    with pytest.raises(FileNotFoundError, match="Messregister nicht gefunden"):
        nm.campaign_tests(str(tmp_path / "empty"), "x")


def test_network_estimate_from_undisturbed_quantities():
    """Fault loop with Z_1 = Z_up ∥ Z_MV and the capacitive Z_0 from I_C: the limit Z_MV → 0 is the classical estimate,
    otherwise the formula of the loop; the negative-sequence impedance enters Z_2."""
    from groundfault.forecast import classical_bound, network_estimate
    U, m, I_C, U_LE = 120.0, 5, 700.0, 11547.0
    assert network_estimate(U, m, 1e-9, 9.5j, I_C, U_LE) == pytest.approx(classical_bound(U, m, I_C, U_LE), rel=1e-6)
    Zmv, Zup, Zmv2, ZF, I_L, d = 8 * np.exp(-1j * np.radians(55)), complex(0.3, 9.5), 7 * np.exp(-1j * np.radians(60)), 2.5, 710.0, 0.04
    XC0 = 3 * U_LE / I_C
    XL0 = 3 * U_LE / I_L
    Z0 = 1 / (1j * (m / XC0 - 1 / (m * XL0))) + d * XC0
    Z1 = 1 / (1 / Zup + 1 / Zmv)
    Z2 = 1 / (1 / Zup + 1 / Zmv2)
    expected = 3 * U / abs(Z0 + Z1 + Z2 + 3 * ZF)
    got = network_estimate(U, m, Zmv, Zup, I_C, U_LE, Z_F=ZF, I_L=I_L, d=d, Z_mv_neg=Zmv2)
    assert got == pytest.approx(expected, rel=1e-12)
    # more damping (smaller Z_MV at the resonance) means more current; Z_F lowers it
    assert network_estimate(U, m, 0.5 * Zmv, Zup, I_C, U_LE) > network_estimate(U, m, Zmv, Zup, I_C, U_LE)
    assert network_estimate(U, m, Zmv, Zup, I_C, U_LE, Z_F=5.0) < network_estimate(U, m, Zmv, Zup, I_C, U_LE)
