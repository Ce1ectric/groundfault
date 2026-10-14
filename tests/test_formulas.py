# -*- coding: utf-8 -*-
"""Closed-form formulas: synthetic examples, limiting cases and comparisons with a second method."""
import inspect
import math

import numpy as np
import pytest

from groundfault import formulas as fml
from groundfault import i18n


# Synthetic network for the examples of this file: resonance at 480 A, active residual current 11 A, operating point
# 470 A (under-compensated by 10 A), maximum of the resonance curve 250 V.
I_RES, IW, I_OP, U_MAX = 480.0, 11.0, 470.0, 250.0


def _resonance_curve(I_L):
    """Neutral displacement voltage over the coil current: U = U_max·Iw/√(Iw² + (I_res − I_L)²)."""
    return U_MAX * IW / np.sqrt(IW ** 2 + (I_RES - np.asarray(I_L, float)) ** 2)


def test_sqrt2_method_example():
    """At I_L = I_res ± Iw the resonance curve has dropped to U_max/√2 – the √2 method reads Iw from these two
    coil currents."""
    upper, lower = I_RES + IW, I_RES - IW
    assert _resonance_curve([upper, lower]) == pytest.approx([fml.sqrt2_target_voltage(U_MAX)] * 2)
    assert fml.sqrt2_target_voltage(U_MAX) == pytest.approx(176.78, abs=0.01)
    assert fml.sqrt2_active_current(upper, lower) == pytest.approx(IW)
    assert fml.detuning_current(I_RES, I_OP) == pytest.approx(-10.0)                # under-compensated
    assert fml.detuning_current(I_RES, 492.0) == pytest.approx(12.0)                # over-compensated
    assert fml.fundamental_current(IW, -10.0) == pytest.approx(math.hypot(11.0, 10.0))
    assert fml.fundamental_current(IW, -10.0) == pytest.approx(14.87, abs=0.01)
    assert fml.damping(IW, I_RES) == pytest.approx(0.0229, abs=1e-4)                # ≈ 2.3 %
    assert fml.detuning(-10.0, I_RES) == pytest.approx(-10.0 / 480.0)


@pytest.mark.parametrize("I_operating", [470.0, 492.0])
def test_one_sign_convention_of_the_detuning(I_operating):
    """The angle method and the resonance-curve functions give the same sign: Iv = ΣI_coil − I_C > 0 over-compensated.

    Parallel resonant circuit of the zero-sequence system: the residual current at the fault is
    I_1 = (U0/|U0|)·(Iw + j·(I_C − I_L)) with the capacitive current I_C (= coil current at resonance) and the coil
    current I_L in operation. Two independent ways to the detuning: the angle method on this phasor and
    ``detuning_current``/``sqrt2_method`` from the coil currents."""
    U0 = 11547.0 * np.exp(0.4j)
    I1 = U0 / abs(U0) * (IW + 1j * (I_RES - I_operating))
    Iw, Iv = fml.angle_method(I1, U0)
    assert Iw == pytest.approx(IW)
    assert Iv == pytest.approx(fml.detuning_current(I_RES, I_operating))
    assert Iv == pytest.approx(I_operating - I_RES)
    assert (Iv > 0) == (I_operating > I_RES)                                      # over-compensated ↔ Iv > 0
    IL = np.linspace(440, 520, 17)                                                # resonance on the grid (480 A)
    e = fml.sqrt2_method(IL, _resonance_curve(IL), I_operating=I_operating)
    assert e["Iv"] == pytest.approx(Iv)
    assert e["v"] == pytest.approx(fml.detuning(Iv, I_RES))


def test_sqrt2_method_from_resonance_curve_two_ways():
    """Analytical resonance curve U = K/√(Iw² + (I_res − I_L)²): way 1 (interpolation) and way 2 (fitted parabola
    in 1/U²) must both give I_res and Iw; way 2 exactly, way 1 within the error of the grid."""
    IL = np.linspace(440, 520, 17)
    U = _resonance_curve(IL)
    e = fml.sqrt2_method(IL, U, I_operating=I_OP)
    assert e["I_resonance_fit"] == pytest.approx(I_RES, abs=1e-6)
    assert e["Iw_fit"] == pytest.approx(IW, abs=1e-6)
    assert e["U_max_fit"] == pytest.approx(U_MAX, rel=1e-9)
    assert e["Iw"] == pytest.approx(IW, abs=0.2)          # linear interpolation on a 5-A grid
    assert e["Iv"] == pytest.approx(-10.0)                # operating point below the resonance: under-compensated
    # with measurement noise (1 %) the fitted parabola stays robust
    rng = np.random.default_rng(1)
    e2 = fml.sqrt2_method(IL, U * (1 + 0.01 * rng.standard_normal(IL.size)))
    assert e2["Iw_fit"] == pytest.approx(IW, rel=0.05)


def test_angle_method():
    U0 = 11547 * np.exp(1j * 0.3)
    I = (20 - 25j) * np.exp(1j * 0.3)       # orientation of the angle method: I = (Iw − jIv)·U0/|U0|
    Iw, Iv = fml.angle_method(I, U0)
    assert Iw == pytest.approx(20.0) and Iv == pytest.approx(25.0)
    with pytest.raises(ValueError, match="kein Winkelbezug"):
        fml.angle_method(I, 0j)


def test_measurement_uncertainty():
    assert fml.current_with_uncertainty(100.0, 0.05) == pytest.approx(105.0)
    assert fml.voltage_with_uncertainty(100.0, 0.05) == pytest.approx(95.0)
    assert np.allclose(fml.current_with_uncertainty(np.array([1.0, 2.0]), 0.1), [1.1, 2.2])


def test_harmonic_content_and_scaling():
    assert fml.harmonic_current(50.0, 30.0) == pytest.approx(40.0)
    assert fml.harmonic_current(30.0, 30.0000001) == 0.0            # noise → not negative
    assert fml.scaled_harmonic_current(40.0, 3.0, 2.0) == pytest.approx(60.0)
    assert fml.rms_current_forecast(30.0, 40.0) == pytest.approx(50.0)
    with pytest.raises(ValueError):
        fml.scaled_harmonic_current(1.0, 1.0, 0.0)


# Synthetic network for the resistive approach (invented values): I_CE = 500 A, d = 4.8 %, v = 3.6 % → I_G = 30 A;
# U_THD,95 = 180 V, R_E,max = 2 Ω, U_Tp = 100 V and F = 1.5 (I_RES,max = F·U_Tp/R_E = 75 A); line R1' = 0.25 Ω/km,
# R0' = 0.75 Ω/km
U_THD, R_E, R1, R0, U_TP, F = 180.0, 2.0, 0.25, 0.75, 100.0, 1.5


def test_resistive_approach_example():
    """Limiting resistance and critical distance; second method: a fault at the critical distance drives exactly
    the permissible residual current through the fault circuit (line resistances plus 3·R_E)."""
    IG = fml.fundamental_from_network_data(500, 0.048, 0.036)
    assert IG == pytest.approx(30.0)
    I_max = fml.max_residual_current(R_E, U_TP, F)
    assert I_max == pytest.approx(75.0)
    Rg = fml.limit_resistance(U_THD, I_max, IG, R_E)
    assert Rg == pytest.approx(1.856, abs=0.001)
    lg = fml.limit_distance(Rg, R1, R0)
    assert lg == pytest.approx(1.485, abs=0.001)
    I_H = 3 * U_THD / (lg * (R1 + R1 + R0) + 3 * R_E)           # harmonic current of a fault at l_lim
    assert math.hypot(IG, I_H) == pytest.approx(I_max)
    assert fml.resistive_assessment(Rg, 0.5, 0.5, 0.5) == "countermeasures"
    assert fml.resistive_assessment(Rg, 0.5, 0.5, 1.0) == "uncritical"


def test_resistive_approach_limiting_cases():
    with pytest.warns(UserWarning):
        assert math.isinf(fml.limit_resistance(200.0, 30.0, 35.0, 2.5))               # I_G ≥ I_RES,max
    assert fml.limit_distance(-1.0, R1, R0) == 0.0                                   # uncritical even at the substation
    assert math.isinf(fml.limit_distance(float("inf"), R1, R0))


def test_zero_sequence_impedance_overhead_line():
    """The real part grows with 3ωμ0/8 (earth return, ≈ 0.148 Ω/km at 50 Hz, independent of the line); the depth of
    the earth return and the reactance agree with a second evaluation in the engineering form δ_E = 658·√(ρ_E/f)
    (invented conductor and soil data)."""
    R_L, r_L, d, rho = 0.25, 0.006, 1.2, 250.0
    earth = 3 * 2 * math.pi * 50 * (4e-7 * math.pi) / 8 * 1000          # Ω/km at 50 Hz
    assert earth == pytest.approx(0.148, abs=0.0005)
    assert fml.r0_overhead_line(50, R_L) == pytest.approx(R_L + earth)
    assert fml.r0_overhead_line(250, R_L) == pytest.approx(R_L + 5 * earth)
    for f in (50.0, 250.0):
        delta = 658.4 * math.sqrt(rho / f)                              # m
        assert fml.earth_return_depth(f, rho) == pytest.approx(delta, rel=1e-3)
        z = fml.z0_overhead_line(f, R_L, r_L, d, rho)
        x0 = 2 * math.pi * f * 4e-7 * math.pi / (2 * math.pi) * (0.25 + 3 * math.log(delta / (r_L * d * d) ** (1 / 3)))
        assert z.real == pytest.approx(fml.r0_overhead_line(f, R_L))
        assert z.imag == pytest.approx(1000 * x0, rel=1e-3)
    with pytest.raises(TypeError):                                      # the soil resistivity has no default
        fml.earth_return_depth(50.0)
    with pytest.raises(TypeError):
        fml.z0_overhead_line(50.0, R_L, r_L, d)


def test_max_residual_current():
    """I_RES,max = F·U_Tp/(r·R_E,max) – U_Tp and F are given by the user (invented here), there are no defaults."""
    assert fml.max_residual_current(2.0, U_TP, F) == pytest.approx(75.0)
    assert fml.max_residual_current(2.0, U_Tp=U_TP, F=F, r=0.5) == pytest.approx(150.0)
    assert fml.max_residual_current(1.6, U_Tp=96.0, F=2.5) == pytest.approx(150.0)
    with pytest.raises(TypeError):
        fml.max_residual_current(2.0)
    with pytest.raises(ValueError, match="U_Tp, F nicht angegeben"):
        fml.max_residual_current(2.0, None, None)
    for args in ((0.0, U_TP, F), (2.0, 0.0, F), (2.0, U_TP, -1.0), (2.0, U_TP, F, 0.0)):
        with pytest.raises(ValueError, match="müssen > 0 sein"):
            fml.max_residual_current(*args)


# Synthetic equivalent sources per harmonic order: U_q in V, Z_q in Ω
SOURCES = {5: (200.0 * np.exp(0.35j), 4.0 - 2.5j), 7: (70.0 * np.exp(-0.6j), 6.0 - 3.0j),
           11: (40.0 * np.exp(0.9j), 2.5 - 1.5j)}


def _rounded(x):
    """Current phasor as read from a table: magnitude to 0.1 A, angle to 1°."""
    return round(abs(x), 1) * np.exp(1j * np.deg2rad(round(np.degrees(np.angle(x)))))


@pytest.mark.parametrize("m", sorted(SOURCES))
def test_source_from_two_measurements(m):
    """Two-measurement solution (Z1 = 1 Ω, Z2 = 10 Ω): exact currents → exact U_q, Z_q; currents rounded as in a
    table → U_q, Z_q within the rounding error."""
    Uq, Zq = SOURCES[m]
    I1, I2 = Uq / (Zq + 1.0), Uq / (Zq + 10.0)
    Uq_b, Zq_b = fml.source_from_two_measurements(I1, 1.0, I2, 10.0)
    assert Uq_b == pytest.approx(Uq) and Zq_b == pytest.approx(Zq)
    Uq_r, Zq_r = fml.source_from_two_measurements(_rounded(I1), 1.0, _rounded(I2), 10.0)
    assert abs(Uq_r) == pytest.approx(abs(Uq), rel=0.03)
    assert abs(Zq_r - Zq) < 0.3
    # consistency: both equations give the same U_q
    assert _rounded(I2) * (Zq_r + 10.0) == pytest.approx(Uq_r)


def test_residual_current_from_sources():
    """I_RES(Z_E) = √(I_G² + Σ|U_q/(Z_q + Z_E)|²), checked against the explicit sum."""
    Uq = {m: u for m, (u, _) in SOURCES.items()}; Zq = {m: z for m, (_, z) in SOURCES.items()}
    for Z_E in (0.0, 2.0):
        I, parts = fml.residual_current_from_sources(30.0, Uq, Zq, Z_E)
        expected = {m: abs(Uq[m] / (Zq[m] + Z_E)) for m in Uq}
        assert parts == pytest.approx(expected)
        assert I == pytest.approx(math.sqrt(30.0 ** 2 + sum(v ** 2 for v in expected.values())))
    I2, parts2 = fml.residual_current_from_sources(30.0, Uq, Zq, 2.0)
    assert [round(parts2[m], 1) for m in (5, 7, 11)] == [30.8, 8.2, 8.4]
    assert I2 == pytest.approx(44.55, abs=0.01)


def test_source_from_two_measurements_errors():
    with pytest.raises(ValueError):
        fml.source_from_two_measurements(1 + 1j, 2.0, 2 + 1j, 2.0)
    with pytest.raises(ZeroDivisionError):
        fml.source_from_two_measurements(1 + 1j, 0.0, 1 + 1j, 5.0)


def test_messages_in_both_languages():
    """Every message has an English and a German text; errors and warnings follow the output language (the
    suite runs in German)."""
    assert [k for k in i18n.missing_keys("en") + i18n.missing_keys("de") if k.startswith("formulas.")] == []
    Zq, Uq = 30 - 30j, 300.0                        # |Z_q| ≫ additional impedances → ill-conditioned
    I1, I2 = Uq / (Zq + 0.0), Uq / (Zq + 2.5)
    with pytest.raises(ValueError, match="Mindestens 3 Punkte der Resonanzkurve"):
        fml.sqrt2_method([1.0, 2.0], [1.0, 2.0])
    with pytest.warns(UserWarning, match=r"schlecht konditioniert: 1 % Stromfehler ändert Z_q um ca\. \d+ %"):
        fml.source_from_two_measurements(I1, 0.0, I2, 2.5)
    with i18n.language("en"):
        with pytest.raises(ValueError, match="At least 3 points of the resonance curve"):
            fml.sqrt2_method([1.0, 2.0], [1.0, 2.0])
        with pytest.raises(ValueError, match="no angle reference"):
            fml.angle_method(1 + 1j, 0j)
        with pytest.raises(ValueError, match="U_THD,meas must be > 0"):
            fml.scaled_harmonic_current(1.0, 1.0, 0.0)
        with pytest.warns(UserWarning, match="already reached by the fundamental component"):
            fml.limit_resistance(200.0, 30.0, 35.0, 2.5)
        with pytest.warns(UserWarning, match=r"ill-conditioned: a current error of 1 % changes Z_q by about \d+ %"):
            fml.source_from_two_measurements(I1, 0.0, I2, 2.5)
        with pytest.raises(ValueError, match="requires Z1 ≠ Z2"):
            fml.source_from_two_measurements(1 + 1j, 2.0, 2 + 1j, 2.0)


def test_public_names():
    """``__all__`` lists every public function of the module and only names that exist."""
    functions = {n for n, v in vars(fml).items()
                 if inspect.isfunction(v) and v.__module__ == fml.__name__ and not n.startswith("_")}
    assert functions <= set(fml.__all__)
    assert all(hasattr(fml, n) for n in fml.__all__)
