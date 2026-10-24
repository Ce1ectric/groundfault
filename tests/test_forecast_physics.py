# -*- coding: utf-8 -*-
"""Physical plausibility of the network model against an independent three-phase nodal calculation.

The reference is a synthetic 20-kV network – no data of a real network – solved per harmonic order in phase
quantities: the busbar L1–L3 behind the upstream impedance (delta winding on the MV side: no zero sequence), earth
capacitances with losses, loads, a Petersen coil in the neutral with an optional nonlinear current that arises with
the fault, harmonic sources, and an optional line to a fault location (π section). It does not use groundfault.
First its limit cases (the fault impedance lies in series with the zero-sequence admittance), then the methods of the
model against it: calibration (B method), forecast, update with a recorded earth fault, node rule, two-source fit, a
fault behind a line, the line from a recorded earth fault, and the classical estimate.
"""
import math
from dataclasses import replace

import numpy as np
import pytest

from groundfault import forecast as fc

W = 2 * math.pi * 50.0
U_LE = 20e3 / math.sqrt(3)
CE = 60e-6                                   # earth capacitance per phase in F (I_C ≈ 650 A)
X_N = 1 / (3 * W * CE) / 1.05                # coil in the neutral, 5 % overcompensated, Ω at 50 Hz
_a = np.exp(2j * np.pi / 3)
_A = np.array([[1, 1, 1], [1, _a * _a, _a], [1, _a, _a * _a]])     # (L1, L2, L3) = A·(zero, pos, neg)
_AI = np.linalg.inv(_A)


def _sym(y0, y1, y2):
    """Phase matrix of a symmetrical element from its sequence values."""
    return _A @ np.diag([y0, y1, y2]) @ _AI


class Grid:
    """Reference network at one order m. Nodes 0–2: busbar L1–L3; 3–5: fault location behind ``line``
    = (Z_1L, Z_0L, C_L in F per phase)."""

    def __init__(self, m, *, C_E=CE, G_frac=0.03, coil=True, X_coil=X_N, Z_up1=0.1 + 1.8j, G_load=0.05,
                 E_seq=(0, 0, 0), I_mv_seq=(0, 0, 0), line=None):
        n = 6 if line else 3
        Y = np.zeros((n, n), complex)
        I = np.zeros(n, complex)
        Z_up = complex(Z_up1.real, m * Z_up1.imag)
        Ys = _sym(0, 1 / Z_up, 1 / Z_up)
        Y[:3, :3] += Ys
        I[:3] += Ys @ (_A @ np.asarray(E_seq, complex))               # background behind the upstream impedance
        Y[:3, :3] += np.eye(3) * (G_frac * W * C_E + 1j * m * W * C_E)
        Y[:3, :3] += _sym(0, G_load, G_load)                          # loads, unearthed star
        self.Z_N = 1j * m * X_coil if coil else None
        if coil:
            Y[:3, :3] += _sym(1 / (3 * self.Z_N), 0, 0)
        I[:3] += _A @ np.asarray(I_mv_seq, complex)                   # harmonic sources of the MV network
        if line:
            Yl = np.linalg.inv(_sym(line[1], line[0], line[0]))
            Y[:3, :3] += Yl
            Y[3:, 3:] += Yl
            Y[:3, 3:] -= Yl
            Y[3:, :3] -= Yl
            yc = 1j * m * W * line[2] / 2
            Y[:3, :3] += np.eye(3) * yc
            Y[3:, 3:] += np.eye(3) * yc
        self.Y, self.I, self.f = Y, I, (3 if line else 0)

    def solve(self, Z_F=None, I_Nh=0.0, at_busbar=False):
        """Node voltages, fault current (earth → faulted phase L1), coil current (neutral → earth). ``Z_F=None``: no
        fault; ``I_Nh``: nonlinear coil current that arises with the fault; ``at_busbar``: fault at the busbar also
        with a line."""
        Y, I = self.Y.copy(), self.I.copy()
        I[:3] -= I_Nh / 3
        f = 0 if at_busbar else self.f
        y_f = 0.0 if Z_F is None else (1e12 if Z_F == 0 else 1 / Z_F)
        Y[f, f] += y_f
        V = np.linalg.solve(Y, I)
        U0 = (_AI @ V[:3])[0]
        I_coil = (U0 / self.Z_N if self.Z_N is not None else 0.0) + I_Nh
        return V, complex(-V[f] * y_f), complex(I_coil)

    def thevenin(self):
        """Sequence impedances (Z_0, Z_1, Z_2) seen from the busbar."""
        return np.diag(_AI @ np.linalg.inv(self.Y)[:3, :3] @ _A)

    def U_pre_L1(self):
        return complex(self.solve()[0][0])


def record(grids, name, Z_F, kind="test", I_Nh=None, coils=False, line=None, at_busbar=False):
    """Fault data of one fault with fault impedance Z_F at all orders of ``grids``; returns (FaultData, true I_F)."""
    U_pre, U_fault, I, I_coil = {}, {}, {}, {}
    for m, g in grids.items():
        Vp, _, Icp = g.solve()
        Vf, IF, Icf = g.solve(Z_F, (I_Nh or {}).get(m, 0.0), at_busbar=at_busbar)
        sp, sf = _AI @ Vp[:3], _AI @ Vf[:3]
        U_pre[m] = dict(zero=sp[0], pos=sp[1], neg=sp[2])
        U_fault[m] = dict(zero=sf[0], pos=sf[1], neg=sf[2])
        I[m] = IF
        I_coil[m] = Icf - Icp
    test = kind == "test"
    fd = fc.fault_data_from_values(name, U_pre, U_fault, I=I if test else None, Z_F=Z_F if test else None,
                                   faulted_phase="L1", I_coil=I_coil if coils else None, line=line)
    return fd, I


def close(a, b, tol=1e-9):
    assert abs(complex(a) - complex(b)) <= tol * max(abs(complex(b)), 1e-12), (a, b)


BACKGROUND = {3: (0.5, 0, 0), 5: (0, 0, 90.0), 7: (0, 40.0, 0), 11: (0, 0, 15.0)}   # natural sequence per order


def grids(orders=(5, 7, 11), **kw):
    return {m: Grid(m, E_seq=BACKGROUND[m], I_mv_seq=(0, 0.4, 0) if m == 7 else (0, 0, 0), **kw) for m in orders}


# ------------------------------------------------------------------------------------------- the reference itself
def test_reference_limit_cases():
    """The fault impedance lies in series with the zero-sequence admittance of network and coils: without both no
    fault current flows, however small Z_F."""
    for m, E in ((1, (0, U_LE, 0)), (5, (0, 0, 100.0))):
        g = Grid(m, C_E=1e-15, G_frac=0.0, coil=False, E_seq=E)
        assert abs(g.solve(0.0)[1]) < 1e-6
    assert abs(Grid(1, E_seq=(0, U_LE, 0)).solve(1e9)[1]) < 1e-3           # Z_F → ∞
    # stiff source, no coil, no losses: the capacitive earth-fault current 3·ω·C_E·U_LE, full displacement
    g = Grid(1, coil=False, G_frac=0.0, Z_up1=1e-6j, E_seq=(0, U_LE, 0))
    V, IF, _ = g.solve(0.0)
    assert abs(IF) == pytest.approx(3 * W * CE * U_LE, rel=1e-4)
    assert abs((_AI @ V[:3])[0]) == pytest.approx(U_LE, rel=1e-4)
    # tuned coil without losses: no fault current at 50 Hz; detuned by 5 %: the detuning current
    g = Grid(1, G_frac=0.0, X_coil=1 / (3 * W * CE), Z_up1=1e-6j, E_seq=(0, U_LE, 0))
    assert abs(g.solve(0.0)[1]) < 1e-4 * 3 * W * CE * U_LE
    g = Grid(1, G_frac=0.0, Z_up1=1e-6j, E_seq=(0, U_LE, 0))
    assert abs(g.solve(0.0)[1]) == pytest.approx(0.05 * 3 * W * CE * U_LE, rel=1e-4)


def test_reduced_loop_is_the_nodal_solution():
    """I_F = (U_q + U_s)/(Z_q + Z_qL + Z_F) with U_q the pre-fault voltage of the faulted phase, Z_q =
    (Z_0 + Z_1 + Z_2)/3 and U_s = Z_0·I_Nh/3 – Thevenin at the fault location, exact for the linear network."""
    for m in (1, 3, 5, 7, 11):
        g = Grid(m, E_seq=BACKGROUND.get(m, (0, U_LE, 0)))
        Z0, Z1, Z2 = g.thevenin()
        for Z_F, I_Nh in ((0.0, 0.0), (2.5, 0.0), (5.0, 2.0), (0.0, 2.0)):
            close(g.solve(Z_F, I_Nh)[1], (-g.U_pre_L1() + Z0 * I_Nh / 3) / ((Z0 + Z1 + Z2) / 3 + Z_F), 1e-9)


# ------------------------------------------------------------------------------------------- the model against it
def test_calibration_forecast_and_update_reproduce_the_reference():
    G = grids()
    model = fc.NetworkModel("reference")
    for Z_F in (0.0, 2.5, 5.0):
        c = model.add_test(record(G, "%g" % Z_F, Z_F)[0])
        for m, g in G.items():                                          # B method: Z_k = 3·p_k·ΔU_k/I_F
            Z0, Z1, Z2 = g.thevenin()
            close(c.orders[m].Z0, Z0)
            close(c.orders[m].Z1, Z1)
            close(c.orders[m].Z2, Z2)
    T = model.source_terms()
    for m, g in G.items():
        close(T[m].Zq, sum(g.thevenin()) / 3)
    # forecast at a fault impedance that no test had
    U = {m: abs(g.U_pre_L1()) for m, g in G.items()}
    f = model.forecast(U, Z_F=1.2)
    for m, g in G.items():
        assert f.currents.loc["value", m] == pytest.approx(abs(g.solve(1.2)[1]), rel=1e-9)
    # recorded earth fault in another load and HV state (same zero sequence): ratios give Z_1, Z_2 of that state,
    # the zero-sequence voltage the fault current
    G2 = grids(G_load=0.08, Z_up1=0.12 + 2.1j)
    fd, I_true = record(G2, "fault", 0.0, kind="fault")
    c = model.add_fault(fd)
    for m, g in G2.items():
        Z0, Z1, Z2 = g.thevenin()
        close(c.orders[m].Z1, Z1, 1e-8)
        close(c.orders[m].Z2, Z2, 1e-8)
        close(c.currents[m], I_true[m], 1e-8)
        assert c.current_method[m] == "zero_sequence_voltage"
    T2 = model.subset(names=["fault"]).source_terms()
    for m, g in G2.items():                     # its own Z_q forecasts it exactly; the tests' Z_q is another state
        close(T2[m].Zq, sum(g.thevenin()) / 3, 1e-8)
        assert T2[m].current(abs(g.U_pre_L1())) == pytest.approx(abs(I_true[m]), rel=1e-8)


def test_node_rule_and_source_in_the_fault():
    """A nonlinear coil current that arises with the fault (order 3): the two-source fit separates Z_q and
    U_s = Z_0·I_Nh/3; the node rule gives the fault current of a recorded earth fault at every order, while 3·ΔU_0/Z_0
    and the ratios are not valid at the order of the source."""
    G = grids((3, 5, 7))
    I_Nh = {3: 2.0}
    model = fc.NetworkModel("reference")
    for Z_F in (0.0, 2.5, 5.0):
        c = model.add_test(record(G, "%g" % Z_F, Z_F, I_Nh=I_Nh, coils=True)[0])
        for m in G:
            close(c.orders[m].Y0_net, 0.03 * W * CE + 1j * m * W * CE, 1e-8)     # network without the coil
    T = model.source_terms()
    Z0_3 = G[3].thevenin()[0]
    close(T[3].Zq, sum(G[3].thevenin()) / 3, 1e-8)
    close(T[3].Us, Z0_3 * I_Nh[3] / 3, 1e-8)
    assert T[3].kind == "two_source" and T[3].residual < 1e-8
    fd, I_true = record(grids((3, 5, 7), G_load=0.07), "fault", 0.0, kind="fault", I_Nh=I_Nh, coils=True)
    c = model.add_fault(fd)
    for m in (3, 5, 7):
        assert c.current_method[m] == "node_rule"
        close(c.currents[m], I_true[m], 1e-8)
    assert 3 not in c.orders                                       # Z not updated at the order of the source
    # a fault at the busbar has no line: line_from_fault gives Z_qL ≈ 0 – with the node rule also at the order 3
    for m, z in model.line_from_fault(fd).items():
        assert abs(z) < 1e-6, (m, z)
    # without coil currents: no estimate at the order of the source (ΔU_0 = Z_0·I_F/3 − U_s there)
    fd.I_coil, fd.dU0_coil = {}, {}
    c2 = model.add_fault(fd, name="plain")
    assert 3 not in c2.currents and c2.current_method[5] == "zero_sequence_voltage"
    with pytest.warns(UserWarning, match="Leitung bei Ordnung 3 nicht bestimmt – Quelle im Fehler"):
        assert set(model.line_from_fault(fd)) == {5, 7}


def test_fault_behind_a_line_and_the_line_from_the_fault():
    """A fault 8 km behind the busbar: with the line values of each order the forecast from the busbar is exact
    without shunt capacitance; with that of 8 km of cable it deviates by 0.3 % at 250 Hz, 2 % at 350 Hz and 4 % at
    550 Hz. line_from_fault measures the loop contribution of the line from the busbar voltages alone (with the
    capacitance 3–7 % too small)."""
    def zl(m):                                    # line values per order, not ∝ m (as a line-parameter calculation)
        return 8 * complex(0.05 + 0.002 * m, 0.093 * m ** 0.95), 8 * complex(0.54 + 0.03 * m, 0.18 * m ** 0.75)

    orders = (5, 7, 11)
    per_order = {m: zl(m) for m in orders}
    line = fc.Line.from_impedances(*zl(1), "8 km", orders=per_order)
    for C_L, tol, tol_line in ((0.0, 1e-8, 1e-8), (4.1e-6, 0.05, 0.08)):    # 4.1 µF: 8 km of cable
        GL = {m: Grid(m, E_seq=BACKGROUND[m], I_mv_seq=(0, 0.4, 0) if m == 7 else (0, 0, 0),
                      line=(per_order[m][0], per_order[m][1], C_L)) for m in orders}
        model = fc.NetworkModel("busbar")                    # tests at the busbar, the feeder connected
        for Z_F in (0.0, 2.5, 5.0):
            model.add_test(record(GL, "%g" % Z_F, Z_F, at_busbar=True)[0])
        fd, I_true = record(GL, "remote", 0.0, line=line)
        chk = model.verify(fd, conservative=False)
        for m in orders:
            row = chk[chk.order == m].iloc[0]
            assert row.I_forecast_A == pytest.approx(abs(I_true[m]), rel=tol), (C_L, m)
        fault, _ = record(GL, "remote fault", 0.0, kind="fault")
        Zl = model.line_from_fault(fault)
        for m in orders:
            close(Zl[m], line.Zq(m), tol_line)
    # a result that is not resistive-inductive is left out: the busbar does not describe that order
    Z0_5 = model.calibration("0").orders[5].Z0
    dU0 = 10.0 + 0j
    I_F = 3 * dU0 / Z0_5
    bad = fc.fault_data_from_values("odd", {5: dict(zero=0j, pos=0j, neg=0j)},
                                    {5: dict(zero=dU0, pos=-(2 - 3j) * I_F - dU0, neg=0j)}, faulted_phase="L1")
    with pytest.warns(UserWarning, match="nicht ohmsch-induktiv"), pytest.raises(ValueError, match="keine Ordnung"):
        model.line_from_fault(bad)
    # the 50-Hz form (reactance ∝ m) misses the line at the harmonic orders – and the forecast says so
    plain = fc.Line.from_impedances(*zl(1), "8 km")
    assert abs(plain.Zq(5)) > 1.1 * abs(line.Zq(5))
    f = model.forecast({m: 100.0 for m in orders}, line=plain)
    assert any("alle Ordnungen aus den 50-Hz-Werten" in h for h in f.hints)
    f = model.forecast({m: 100.0 for m in orders}, line=fc.Line.from_impedances(*zl(1), orders={5: zl(5)}))
    assert any("eigene Werte bei Ordnung 5" in h and "Ordnungen 7, 11 aus den 50-Hz-Werten" in h for h in f.hints)


def test_classical_estimate_is_no_upper_bound_below_the_resonance():
    """Below the parallel resonance of the busbar (here m_r ≈ 5.4) Z_1 + Z_2 is inductive and partly cancels the
    capacitive Z_0 – a series resonance of the fault loop near m ≈ 3 – so the current exceeds the classical estimate
    with Z_1 = Z_2 = 0; above the resonance the estimate lies above the current."""
    I_C, I_L = 3 * W * CE * U_LE, U_LE / X_N
    for m, above in ((3, False), (7, True)):
        g = Grid(m, E_seq=(0, 50.0, 0))
        I = abs(g.solve(0.0)[1])
        est = fc.classical_bound(abs(g.U_pre_L1()), m, I_C, U_LE, I_L=I_L)
        assert (est > I) if above else (I > 1.5 * est), (m, I, est)


def test_estimates_from_network_data_against_the_reference():
    """V2: with the true damping and operating capacitance the fault loop from network data is the nodal solution;
    the envelope over a range of the damping is the largest nodal current over the same range – it is not always at
    one end of the range, so it is searched, not assumed."""
    I_C, I_L = 3 * W * CE * U_LE, U_LE / X_N
    assert fc.earth_capacitance(I_C, U_LE) == pytest.approx(CE)
    for m in (5, 7, 11):
        Z_up = complex(0.1, m * 1.8)
        g = Grid(m, G_frac=0.0, G_load=0.05, E_seq=(0, 50.0, 0))
        I_ref = abs(g.solve(0.0)[1])
        U_pre = abs(g.U_pre_L1())
        I_v2 = fc.network_data_estimate(U_pre, m, 0.05, CE, Z_up, I_C, U_LE, I_L=I_L)
        assert I_v2 == pytest.approx(I_ref, rel=1e-6)
        # the same with Z_MV built by hand (second method: network_estimate)
        Z_mv = fc.mv_network_from_data(m, 0.05, CE)
        assert Z_mv == pytest.approx(1 / complex(0.05, m * W * CE))
        assert fc.network_estimate(U_pre, m, Z_mv, Z_up, I_C, U_LE, I_L=I_L) == pytest.approx(I_v2, rel=1e-12)
        # envelope over G at the same busbar voltage: the nodal model with each G gives the same maximum (the
        # fault current is proportional to the pre-fault voltage of its own grid)
        G = np.linspace(0.01, 0.2, 39)
        nodal = []
        for x in G:
            gx = Grid(m, G_frac=0.0, G_load=x, E_seq=(0, 50.0, 0))
            nodal.append(abs(gx.solve(0.0)[1]) / abs(gx.U_pre_L1()) * U_pre)
        I_max, G_max = fc.network_data_envelope(U_pre, m, 0.01, 0.2, CE, Z_up, I_C, U_LE, I_L=I_L, points=39)
        assert I_max == pytest.approx(max(nodal), rel=1e-6) and G_max == pytest.approx(G[int(np.argmax(nodal))])
    # near the resonance (m_r ≈ 5.4) a larger damping raises the current – the largest G gives the maximum; below it
    # (m = 3) the smallest
    m_r = fc.resonance_order(1.8, CE)
    assert m_r == pytest.approx(math.sqrt(1 / (W * CE) / 1.8)) and 5.3 < m_r < 5.5
    for m, end in ((5, 0.3), (3, 0.01)):
        Z_up = complex(0.1, m * 1.8)
        I_max, G_max = fc.network_data_envelope(100.0, m, 0.01, 0.3, CE, Z_up, I_C, U_LE, I_L=I_L)
        assert G_max == pytest.approx(end)
        assert I_max == pytest.approx(fc.network_data_estimate(100.0, m, end, CE, Z_up, I_C, U_LE, I_L=I_L))


def test_network_data_helpers():
    """Rating plate and short-circuit power give the upstream impedance; R/X is a choice of the user."""
    assert fc.transformer_reactance(0.14, 40e6, 20e3) == pytest.approx(1.4)
    assert fc.hv_network_reactance(2.5e9, 20e3) == pytest.approx(0.176)
    assert fc.hv_network_reactance(2.5e9, 20e3, c=1.0) == pytest.approx(0.16)
    assert fc.at_order(1.576, 5, 0.03) == pytest.approx(complex(0.2364, 7.88))


def test_estimates_without_fault_side_by_side():
    """The table of the estimates without an earth fault: every column is the single function, I_H is √Σ I_m² over
    the orders of the table, columns without their inputs are left out."""
    I_C, I_L = 3 * W * CE * U_LE, U_LE / X_N
    U = {5: 150.0, 7: 80.0}
    Z_up = {m: fc.at_order(1.9, m, 0.03) for m in U}
    Z_mv = {m: fc.mv_network_from_data(m, 0.06, CE) for m in U}
    m_r = fc.resonance_order(1.9, CE)
    t = fc.estimates_without_fault(U, I_C, U_LE, Z_up, Z_F=(0.0, 5.0), I_L=I_L, d=0.02, C_1=CE, m_r=m_r,
                                   G_max=0.15, G=0.06, G_range=(0.02, 0.15), Z_mv=Z_mv)
    assert list(t.columns) == ["order", "f_Hz", "m_over_mr", "Z_F_Ohm", "U_V", "V0_A", "V1_A", "V2_A",
                               "V2_envelope_A", "G_envelope_S", "V3_A"]
    assert len(t) == 6 and list(t.order) == [5, 7, "I_H", 5, 7, "I_H"]
    r = t[(t.order == 5) & (t.Z_F_Ohm == 5.0)].iloc[0]
    assert r.V0_A == pytest.approx(fc.classical_bound(150.0, 5, I_C, U_LE, Z_F=5.0, I_L=I_L))
    assert r.V1_A == pytest.approx(fc.resonance_bound(150.0, 5, I_C, U_LE, 0.15, Z_F=5.0, I_L=I_L))
    assert r.V2_A == pytest.approx(fc.network_data_estimate(150.0, 5, 0.06, CE, Z_up[5], I_C, U_LE, Z_F=5.0, I_L=I_L,
                                                            d=0.02))
    assert (r.V2_envelope_A, r.G_envelope_S) == pytest.approx(fc.network_data_envelope(150.0, 5, 0.02, 0.15, CE, Z_up[5],
                                                                                       I_C, U_LE, Z_F=5.0, I_L=I_L))
    assert r.V3_A == pytest.approx(r.V2_A)                      # the same MV network, measured or from data
    assert r.m_over_mr == pytest.approx(5 / m_r)
    h = t[(t.order == "I_H") & (t.Z_F_Ohm == 0.0)].iloc[0]
    part = t[(t.order != "I_H") & (t.Z_F_Ohm == 0.0)]
    assert h.V0_A == pytest.approx(float(np.sqrt((part.V0_A ** 2).sum())))
    only = fc.estimates_without_fault(U, I_C, U_LE, Z_up, I_L=I_L)
    assert list(only.columns) == ["order", "f_Hz", "Z_F_Ohm", "U_V", "V0_A"]


# ------------------------------------------------------------------------------------------- network expansion
def _series(G, I_Nh, Z_values=(0.0, 2.5, 5.0), IG=30.0, Iw=20.0):
    """Equivalent sources (measured source; fitted for the zero sequence) of staged tests on the reference."""
    from groundfault import equivalent_source as es
    meas = []
    for Z_F in Z_values:
        I, U_pre, U_fault = {1: complex(IG)}, {1: {"zero": 0j, "pos": complex(U_LE)}}, {1: {"zero": complex(U_LE)}}
        for m, g in G.items():
            sp = _AI @ g.solve()[0][:3]
            U_pre[m] = dict(zero=sp[0], pos=sp[1], neg=sp[2])
            V, I[m], _ = g.solve(Z_F, I_Nh.get(m, 0.0))
            sf = _AI @ V[:3]
            U_fault[m] = dict(zero=sf[0], pos=sf[1], neg=sf[2])
        ih = math.sqrt(sum(abs(v) ** 2 for k, v in I.items() if k > 1))
        meas.append(es.SourceMeasurement("Z %g" % Z_F, complex(Z_F), "", "v2", 50.0, 0.0, I, U_fault,
                                         U_pre=U_pre, U_post=U_pre, U_complex=True, IRES=math.hypot(IG, ih), Iw=Iw,
                                         faulted_phase="L1", IH_sum=ih))
    return es.measured_source(meas)


def test_network_expansion_against_the_reference():
    """More cable at the busbar – earth and operating capacitance +30 %, its damping that of the network – and the
    coil retuned to the same detuning: the equivalent sources of the expanded network follow from those of today.
    With Z_0 and Z_1 of the busbar (B method) the currents of the expanded network are reproduced exactly – the
    background behind the upstream impedance and a source of the MV network move with Z_1, the source of the
    zero sequence in the fault with Z_0 and the coil current; with Z_0 from network data (damping as a series
    resistance, the reference has a conductance) within a few per cent."""
    from groundfault import equivalent_source as es
    k, Z_E, orders = 1.3, 2.5, (3, 5, 7, 11, 13)
    E = {**BACKGROUND, 13: (0, 60.0, 0)}
    I_Nh = {3: 4.0}
    today = {m: Grid(m, E_seq=E[m], I_mv_seq=(0, 0.4, 0) if m == 7 else (0, 0, 0)) for m in orders}
    later = {m: Grid(m, C_E=k * CE, X_coil=X_N / k, E_seq=E[m], I_mv_seq=(0, 0.4, 0) if m == 7 else (0, 0, 0))
             for m in orders}
    S = _series(today, I_Nh)
    for m, g in today.items():                                          # the equivalent sources are exact
        close(S.fits[m].Zq, sum(g.thevenin()) / 3, 1e-8)
    I_C, I_L = 3 * W * CE * U_LE, U_LE / X_N
    Z0 = {m: g.thevenin()[0] for m, g in today.items()}
    Z1 = {m: g.thevenin()[1] for m, g in today.items()}
    x = es.network_expansion(S, I_C, k * I_C, I_L=I_L, U_LE=U_LE, damping=0.03, Z0=Z0, Z1=Z1)
    assert x.I_L_new == pytest.approx(k * I_L) and set(x.table["split"]) == {"given"}
    truth = {m: abs(g.solve(Z_E, k * I_Nh.get(m, 0.0))[1]) for m, g in later.items()}     # I_Nh ∝ coil current
    for m in orders:
        assert x.series.fits[m].current(Z_E) == pytest.approx(truth[m], rel=1e-8), m
        Z0n, Z1n, _ = later[m].thevenin()
        close(x.table.set_index("order").loc[m, "Z0_new"], Z0n, 1e-8)
        close(x.table.set_index("order").loc[m, "Z1_new"], Z1n, 1e-8)
    # without the expansion nothing changes; the fundamental grows with I_C (active current d·I_C)
    same = es.network_expansion(S, I_C, I_C, I_L=I_L, U_LE=U_LE, Z0=Z0, Z1=Z1)
    for m, F in S.fits.items():
        close(same.series.fits[m].Zq, F.Zq, 1e-12)
        close(same.series.fits[m].Uq, F.Uq, 1e-12)
    assert x.IG_factor == pytest.approx(math.hypot(20.0 + 0.03 * (k - 1) * I_C, math.sqrt(30 ** 2 - 20 ** 2) * k) / 30)
    # Z_0 from network data, Z_1 = (3·Z_q − Z_0)/2: an estimate. The damping as a series resistance d·X_C0 (the
    # reference has a conductance) matters most at the order of the zero sequence, whose source U_s = Z_0·I_Nh/3
    # moves with Z_0: there the estimate is about 7 % high, at the other orders within 2 %.
    y = es.network_expansion(S, I_C, k * I_C, I_L=I_L, U_LE=U_LE, damping=0.03)
    assert set(y.table["split"]) == {"sources"}
    for m in orders:
        assert y.series.fits[m].current(Z_E) == pytest.approx(truth[m], rel=0.1 if m == 3 else 0.025), m
    assert y.series.fits[3].current(Z_E) > truth[3]
    # Z_0 and Z_1 from the busbar voltages of the tests (B method; at the zero sequence Z_0 = 3·Z_q − 2·Z_1): exact
    b = es.busbar_impedances(S).set_index("order")
    assert list(b.index) == list(orders) and set(b["n"]) == {3}
    assert list(b["Z0_from"]) == ["equivalent_source", "busbar", "busbar", "busbar", "busbar"]
    assert list(b["Z1_from"]) == ["pos/neg", "pos", "neg", "pos", "neg"]
    for m in orders:
        close(b.loc[m, "Z0"], Z0[m], 1e-8)
        close(b.loc[m, "Z1"], Z1[m], 1e-8)
    z = es.network_expansion(S, I_C, k * I_C, I_L=I_L, U_LE=U_LE, damping=0.03, split="busbar")
    assert set(z.table["split"]) == {"busbar"} and not z.hints
    for m in orders:
        assert z.series.fits[m].current(Z_E) == pytest.approx(truth[m], rel=1e-8), m
    # without busbar voltages of the harmonics: the network data, with a hint per order
    bare = es.measured_source([replace(mm, U_fault={1: mm.U_fault[1]}) for mm in S.measurements])
    assert es.busbar_impedances(bare).empty
    w = es.network_expansion(bare, I_C, k * I_C, I_L=I_L, U_LE=U_LE, damping=0.03, split="busbar")
    assert set(w.table["split"]) == {"sources"} and len(w.hints) == len(orders)
    # residual current over I_C and where it reaches a limit
    curve = es.expansion_curve(S, Z_E, I_C, [I_C, 1.15 * I_C, k * I_C], IG="median", I_L=I_L, U_LE=U_LE,
                               damping=0.03, Z0=Z0, Z1=Z1)
    assert list(curve["I_C_A"]) == pytest.approx([I_C, 1.15 * I_C, k * I_C])
    assert curve["I_5_A"].iloc[-1] == pytest.approx(truth[5], rel=1e-8)
    ires = curve["IRES_A"].to_numpy()
    assert es.expansion_limit(curve, ires[0] - 1)["status"] == "exceeded"
    lim = es.expansion_limit(curve, (ires[1] + ires[2]) / 2)
    assert lim["status"] == "reached" and 1.15 * I_C < lim["I_C_A"] < k * I_C
    assert es.expansion_limit(curve, ires[-1] + 1)["status"] == "not_reached"
    bus = es.expansion_curve(S, Z_E, I_C, [I_C, k * I_C], IG="median", I_L=I_L, U_LE=U_LE, damping=0.03,
                             split="busbar")
    assert bus["I_5_A"].iloc[-1] == pytest.approx(truth[5], rel=1e-8)
    assert bus["IRES_A"].iloc[0] == pytest.approx(curve["IRES_A"].iloc[0], rel=1e-12)     # today: the same
    with pytest.raises(ValueError):
        es.network_expansion(S, I_C, k * I_C, U_LE=U_LE, zero_sequence="coils")
    with pytest.raises(ValueError):
        es.network_expansion(S, I_C, k * I_C, U_LE=U_LE, split="model")
    with pytest.raises(ValueError):
        es.network_expansion(S, 0.0, k * I_C, U_LE=U_LE)
    with pytest.raises(TypeError):
        es.expansion_curve(S, Z_E, I_C, [I_C], I_LE=U_LE)


def test_network_expansion_rejects_a_busbar_split_with_negative_resistance():
    """A busbar split with a negative real part (no passive network – phase errors of the measurement) would give a
    computed parallel resonance that does not exist: the order uses the network data instead, with a hint, and the
    table marks it."""
    from groundfault import equivalent_source as es
    orders = (3, 5, 7)
    S = _series({m: Grid(m, E_seq=BACKGROUND[m]) for m in orders}, {3: 4.0})
    I_C, I_L = 3 * W * CE * U_LE, U_LE / X_N
    bus = {int(r.order): (complex(r.Z0), complex(r.Z1)) for r in es.busbar_impedances(S).itertuples()}
    z0, z1 = bus[5]
    bus[5] = (z0, complex(-0.2 - abs(z1.real), z1.imag))                  # negative real part at the 5th
    x = es._expand(S, I_C, 1.3 * I_C, bus, I_L=I_L, U_LE=U_LE, damping=0.03, damping_added=None, c1_ratio=1.0,
                   Z0=None, Z1=None, zero_sequence="coil")
    t = x.table.set_index("order")
    assert t.loc[5, "split"] == "sources" and bool(t.loc[5, "busbar_rejected"])
    assert t.loc[7, "split"] == "busbar" and not bool(t.loc[7, "busbar_rejected"])
    ref = es.network_expansion(S, I_C, 1.3 * I_C, I_L=I_L, U_LE=U_LE, damping=0.03)          # network data
    close(x.series.fits[5].Zq, ref.series.fits[5].Zq, 1e-12)
    assert any("Order 5" in h or "Ordnung 5" in h for h in x.hints)
