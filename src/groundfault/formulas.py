# -*- coding: utf-8 -*-
"""Closed-form formulas for the assessment of earth-fault currents in compensated (resonant-earthed) networks.

Units: currents in A, voltages in V, impedances in Ω, lengths in km, frequencies in Hz. Phasors are complex RMS
phasors.

* **Residual current** – residual earth-fault current from its components
  ([`residual_current`][groundfault.formulas.residual_current]), rough estimate from the capacitive earth-fault current
  ([`residual_current_estimate`][groundfault.formulas.residual_current_estimate]), fundamental component
  ([`fundamental_current`][groundfault.formulas.fundamental_current]).
* **Compensation and resonance** – √2 method on a measured resonance curve
  ([`sqrt2_method`][groundfault.formulas.sqrt2_method],
  [`sqrt2_active_current`][groundfault.formulas.sqrt2_active_current],
  [`sqrt2_target_voltage`][groundfault.formulas.sqrt2_target_voltage]), detuning and damping
  ([`detuning_current`][groundfault.formulas.detuning_current], [`detuning`][groundfault.formulas.detuning],
  [`damping`][groundfault.formulas.damping]), fundamental component from the minimum of the V curve
  ([`fundamental_from_v_curve`][groundfault.formulas.fundamental_from_v_curve]), angle method
  ([`angle_method`][groundfault.formulas.angle_method]), fundamental component from network data
  ([`fundamental_from_network_data`][groundfault.formulas.fundamental_from_network_data]) and the zero-sequence
  impedance of the network with its coils at a harmonic order
  ([`zero_sequence_impedance`][groundfault.formulas.zero_sequence_impedance]).
* **Measurement uncertainty** – assessment values of currents and voltages
  ([`current_with_uncertainty`][groundfault.formulas.current_with_uncertainty],
  [`voltage_with_uncertainty`][groundfault.formulas.voltage_with_uncertainty]); window length in samples
  ([`window_samples`][groundfault.formulas.window_samples]).
* **Harmonics** – harmonic content ([`harmonic_current`][groundfault.formulas.harmonic_current]), scaling to the 95 %
  quantile of the harmonic voltage ([`scaled_harmonic_current`][groundfault.formulas.scaled_harmonic_current],
  [`rms_current_forecast`][groundfault.formulas.rms_current_forecast]), conversion of harmonic voltages
  ([`thd_percent_to_volt`][groundfault.formulas.thd_percent_to_volt],
  [`sequence_voltage_from_ll`][groundfault.formulas.sequence_voltage_from_ll]).
* **Resistive approach** (after the VDE Impuls on the residual earth-fault current) – limiting resistance,
  assessment of a fault location and critical distance ([`limit_resistance`][groundfault.formulas.limit_resistance],
  [`resistive_assessment`][groundfault.formulas.resistive_assessment],
  [`limit_distance`][groundfault.formulas.limit_distance]).
* **Limits** – permissible residual current from the permissible touch voltage and the factor F given by the user
  ([`max_residual_current`][groundfault.formulas.max_residual_current]).
* **Line parameters** – zero-sequence impedance of an overhead line without earth wire
  ([`z0_overhead_line`][groundfault.formulas.z0_overhead_line],
  [`r0_overhead_line`][groundfault.formulas.r0_overhead_line],
  [`earth_return_depth`][groundfault.formulas.earth_return_depth]).
* **Equivalent source** – two-terminal (Thevenin) equivalent from two measurements
  ([`source_from_two_measurements`][groundfault.formulas.source_from_two_measurements]) and residual current at an
  earthing impedance ([`residual_current_from_sources`][groundfault.formulas.residual_current_from_sources]); the fit
  over a series of measurements is in [`groundfault.equivalent_source`][groundfault.equivalent_source].
"""
from __future__ import annotations

import math
import warnings
from typing import Dict, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

from . import i18n
from .i18n import tr

MU0 = 4e-7 * math.pi
"""Magnetic constant μ0 in Vs/(Am) (classical value 4π·10⁻⁷, accurate enough for line impedances)."""

Number = Union[float, int, np.ndarray]

__all__ = [
    "residual_current", "residual_current_estimate", "sqrt2_active_current", "sqrt2_target_voltage",
    "detuning_current", "fundamental_current", "damping", "detuning", "sqrt2_method",
    "fundamental_from_v_curve", "angle_method", "current_with_uncertainty", "voltage_with_uncertainty",
    "window_samples", "harmonic_current", "harmonic_category", "HARMONIC_CATEGORIES", "order_scaling",
    "SCALING_RULES", "scaled_harmonic_current", "rms_current_forecast", "thd_percent_to_volt",
    "sequence_voltage_from_ll", "limit_resistance", "resistive_assessment", "max_residual_current",
    "earth_return_depth", "z0_overhead_line", "r0_overhead_line", "limit_distance", "source_from_two_measurements",
    "residual_current_from_sources", "fundamental_from_network_data", "zero_sequence_impedance", "MU0",
    "typical_factor", "TYPICAL_FACTORS",
]

i18n.register({
    "formulas.too_few_points": {
        "en": "At least 3 points of the resonance curve are needed.",
        "de": "Mindestens 3 Punkte der Resonanzkurve nötig."},
    "formulas.no_zero_sequence_voltage": {
        "en": "Zero-sequence voltage U0 ≈ 0 – no angle reference (earth fault in the window?).",
        "de": "Nullspannung U0 ≈ 0 – kein Winkelbezug (Erdschluss im Fenster?)."},
    "formulas.thd_measured_not_positive": {
        "en": "U_THD,meas must be > 0.",
        "de": "U_THD,Messung muss > 0 sein."},
    "formulas.limit_reached_by_fundamental": {
        "en": "I_G ≥ I_RES,max – the limit is already reached by the fundamental component.",
        "de": "I_G ≥ I_RES,max – Grenzwert schon durch die Grundschwingung erreicht."},
    "formulas.limit_parameters": {
        "en": "R_E,max, U_Tp, F and r must be > 0.",
        "de": "R_E,max, U_Tp, F und r müssen > 0 sein."},
    "formulas.limit_not_given": {
        "en": "{names} not given – the permissible touch voltage U_Tp and the factor F are defined by the user "
              "(groundfault has no defaults).",
        "de": "{names} nicht angegeben – die zulässige Berührungsspannung U_Tp und den Faktor F legt der Anwender "
              "fest (groundfault hat keine Vorgaben)."},
    "formulas.equal_impedances": {
        "en": "The equivalent-source method with two measurements requires Z1 ≠ Z2 (additional impedances "
              "practically equal).",
        "de": "Das Ersatzquellenverfahren mit zwei Messungen verlangt Z1 ≠ Z2 (Zusatzimpedanzen praktisch gleich)."},
    "formulas.equal_currents": {
        "en": "I1 ≈ I2 – the two-terminal equivalent cannot be determined.",
        "de": "I1 ≈ I2 – Zweipol nicht bestimmbar."},
    "formulas.ill_conditioned": {
        "en": "Equivalent-source method with two measurements ill-conditioned: a current error of 1 % changes Z_q "
              "by about {change:.0f} % (additional impedances small compared with |Z_q|).",
        "de": "Ersatzquellenverfahren mit zwei Messungen schlecht konditioniert: 1 % Stromfehler ändert Z_q um ca. "
              "{change:.0f} % (Zusatzimpedanzen klein gegenüber |Z_q|)."},
})


# -------------------------------------------------------------------------------- residual current
def residual_current(Iw: Number, Iv: Number, Ih: Number = 0.0) -> Number:
    """Residual earth-fault current from its components: I_RES = √(Iw² + Iv² + I_H²).

    Parameters
    ----------
    Iw : float or array_like
        Active residual current in A.
    Iv : float or array_like
        Detuning (reactive residual current) in A.
    Ih : float or array_like, optional
        Harmonic content in A (default 0).

    Returns
    -------
    float or numpy.ndarray
        Residual current I_RES in A.
    """
    return np.sqrt(np.square(Iw) + np.square(Iv) + np.square(Ih))


def residual_current_estimate(I_CE: Number) -> Number:
    """Rough estimate of the residual current: I_RES ≈ 0.1·I_CE.

    The share 10 % is the general approach of EN 50522:2022, Table 1 (relevant currents for the design of earthing
    systems): if the exact value of the residual earth-fault current of a resonant-earthed network is not available,
    10 % of the capacitive earth-fault current may be assumed – according to the same table not for a network that
    is not well compensated. The estimate does not consider the individual components (active current, detuning,
    harmonics).

    Parameters
    ----------
    I_CE : float or array_like
        Capacitive earth-fault current of the network in A.

    Returns
    -------
    float or numpy.ndarray
        Estimated residual current in A.
    """
    return 0.1 * np.asarray(I_CE, float)


# -------------------------------------------------------------------------------- compensation and resonance
def sqrt2_active_current(I_upper: Number, I_lower: Number) -> Number:
    """Active residual current from the √2 method: Iw = (I_upper − I_lower)/2.

    I_upper and I_lower are the coil currents at which the neutral displacement voltage has dropped to
    U_NE = U_max/√2 on either side of the resonance.

    Parameters
    ----------
    I_upper, I_lower : float or array_like
        Coil currents above and below the resonance in A.

    Returns
    -------
    float or numpy.ndarray
        Active residual current Iw in A.
    """
    return (np.asarray(I_upper, float) - np.asarray(I_lower, float)) / 2.0


def sqrt2_target_voltage(U_max: Number) -> Number:
    """Target voltage of the √2 method: U_target = U_max/√2.

    Parameters
    ----------
    U_max : float or array_like
        Maximum of the resonance curve (neutral displacement voltage at resonance) in V.

    Returns
    -------
    float or numpy.ndarray
        Target voltage in V.
    """
    return np.asarray(U_max, float) / math.sqrt(2.0)


def detuning_current(I_resonance: Number, I_operating: Number) -> Number:
    """Detuning (reactive residual current): Iv = I_operating − I_resonance.

    Parameters
    ----------
    I_resonance : float or array_like
        Coil current at resonance in A (equal to the capacitive earth-fault current I_C).
    I_operating : float or array_like
        Coil current in operation in A.

    Returns
    -------
    float or numpy.ndarray
        Detuning Iv in A: > 0 over-compensated (the coil current in operation exceeds the resonance), < 0
        under-compensated.

    Notes
    -----
    Iv = ΣI_coil − I_C > 0 means over-compensated – the one sign convention of groundfault, the same as that of the
    angle method ([`angle_method`][groundfault.formulas.angle_method], ``Result.values["Iv"]``).
    """
    return np.asarray(I_operating, float) - np.asarray(I_resonance, float)


def fundamental_current(Iw: Number, Iv: Number) -> Number:
    """Fundamental component of the residual current: I_G = √(Iw² + Iv²).

    Parameters
    ----------
    Iw : float or array_like
        Active residual current in A.
    Iv : float or array_like
        Detuning in A.

    Returns
    -------
    float or numpy.ndarray
        Fundamental component I_G in A.
    """
    return np.hypot(Iw, Iv)


def damping(Iw: Number, I_resonance: Number) -> Number:
    """Damping of the network: d = Iw/I_resonance.

    Parameters
    ----------
    Iw : float or array_like
        Active residual current in A.
    I_resonance : float or array_like
        Coil current at resonance in A.

    Returns
    -------
    float or numpy.ndarray
        Damping d in p.u.
    """
    return np.asarray(Iw, float) / np.asarray(I_resonance, float)


def detuning(Iv: Number, I_resonance: Number) -> Number:
    """Relative detuning: v = Iv/I_resonance (signed).

    Parameters
    ----------
    Iv : float or array_like
        Detuning in A ([`detuning_current`][groundfault.formulas.detuning_current] or ``Result.values["Iv"]`` of
        [`groundfault.evaluate`][groundfault.evaluation.evaluate]).
    I_resonance : float or array_like
        Coil current at resonance in A.

    Returns
    -------
    float or numpy.ndarray
        Relative detuning v in p.u. (> 0: over-compensated, < 0: under-compensated).
    """
    return np.asarray(Iv, float) / np.asarray(I_resonance, float)


def sqrt2_method(I_coil: Sequence[float], U_ne: Sequence[float],
                 I_operating: Optional[float] = None) -> Dict[str, float]:
    """√2 method on a measured resonance curve U_NE(I_coil) – two independent evaluations for comparison.

    1. **Interpolation:** the maximum of the measured points is taken as the resonance; the crossings with
       U_max/√2 to the left and to the right are found by linear interpolation → Iw = (I_upper − I_lower)/2.
    2. **Fitted curve:** the resonance curve of the parallel resonant circuit is
       U_NE = K/√(Iw² + (I_res − I_L)²) ⇔ 1/U_NE² = a·I_L² + b·I_L + c (a second-order polynomial!). A
       weighted linear least-squares fit over **all** points gives I_res = −b/(2a), Iw = √(c/a − I_res²) and
       U_max = 1/√(c − b²/(4a)). It is robust against single outliers and needs no points exactly at the √2
       crossings.

    Parameters
    ----------
    I_coil : sequence of float
        Coil currents of the measured points in A (any order; non-finite points are ignored).
    U_ne : sequence of float
        Neutral displacement voltage at these points in V (points with U_NE ≤ 0 are ignored).
    I_operating : float, optional
        Coil current in operation in A; if given, the detuning and the quantities derived from it are added.

    Returns
    -------
    dict
        Interpolation: ``I_resonance``, ``U_max``, ``U_target``, ``I_lower``, ``I_upper`` and ``Iw`` (NaN if a
        crossing is missing); fitted curve: ``I_resonance_fit``, ``Iw_fit`` and ``U_max_fit`` (NaN if the fit is
        not physical, e.g. a ≤ 0). With ``I_operating`` also ``I_operating``, ``Iv`` (Iv = I_operating −
        I_resonance, > 0: over-compensated, see [`detuning_current`][groundfault.formulas.detuning_current]),
        ``I_G``, ``d`` and ``v`` (from the interpolation results).

    Raises
    ------
    ValueError
        If fewer than 3 valid points are given.
    """
    I = np.asarray(I_coil, float); U = np.asarray(U_ne, float)
    ok = np.isfinite(I) & np.isfinite(U) & (U > 0)
    I, U = I[ok], U[ok]
    if I.size < 3:
        raise ValueError(tr("formulas.too_few_points"))
    o = np.argsort(I); I, U = I[o], U[o]
    k = int(np.argmax(U)); U_max = float(U[k]); U_target = U_max / math.sqrt(2.0)
    res: Dict[str, float] = {"I_resonance": float(I[k]), "U_max": U_max, "U_target": U_target}

    def _crossing(idx):  # first crossing of U_target along idx (from the maximum outwards)
        for a, b in zip(idx[:-1], idx[1:]):
            if (U[a] - U_target) * (U[b] - U_target) <= 0 and U[a] != U[b]:
                return float(I[a] + (U_target - U[a]) * (I[b] - I[a]) / (U[b] - U[a]))
        return float("nan")

    res["I_lower"] = _crossing(list(range(k, -1, -1)))
    res["I_upper"] = _crossing(list(range(k, I.size)))
    res["Iw"] = float(sqrt2_active_current(res["I_upper"], res["I_lower"]))
    # --- way 2: weighted least squares for 1/U² = a·I² + b·I + c (weight U² ≙ relative error in U)
    y = 1.0 / U ** 2
    w = U ** 2
    s = float(np.median(np.abs(I))) or 1.0          # scaling → well-conditioned Vandermonde matrix
    x = I / s
    M = np.column_stack([x ** 2, x, np.ones_like(x)]) * w[:, None]
    coef, *_ = np.linalg.lstsq(M, y * w, rcond=None)
    a, b, c = coef[0] / s ** 2, coef[1] / s, coef[2]
    if a > 0:
        I_res_fit = -b / (2 * a)
        iw2 = c / a - I_res_fit ** 2
        res["I_resonance_fit"] = float(I_res_fit)
        res["Iw_fit"] = float(math.sqrt(iw2)) if iw2 > 0 else float("nan")
        umin = c - b * b / (4 * a)
        res["U_max_fit"] = float(1.0 / math.sqrt(umin)) if umin > 0 else float("nan")
    else:
        res.update(I_resonance_fit=float("nan"), Iw_fit=float("nan"), U_max_fit=float("nan"))
    if I_operating is not None:
        Iv = float(detuning_current(res["I_resonance"], I_operating))
        res.update(I_operating=float(I_operating), Iv=Iv, I_G=float(fundamental_current(res["Iw"], Iv)),
                   d=float(damping(res["Iw"], res["I_resonance"])),
                   v=float(detuning(Iv, res["I_resonance"])))
    return res


def fundamental_from_v_curve(I_min_v_curve: Number, Iv: Number = 0.0) -> Number:
    """Fundamental component from the minimum of the resonance curve (V curve): I_G = √(I_min² + Iv²).

    The detuning in operation is added geometrically to the minimum of the V curve (residual current over the
    coil current).

    Parameters
    ----------
    I_min_v_curve : float or array_like
        Minimum of the V curve in A.
    Iv : float or array_like, optional
        Detuning in operation in A (default 0).

    Returns
    -------
    float or numpy.ndarray
        Fundamental component I_G in A.
    """
    return np.hypot(I_min_v_curve, Iv)


def angle_method(I1: complex, U0: complex) -> Tuple[float, float]:
    """Angle method: Iw = |I1|·cos(φ_U − φ_I), Iv = |I1|·sin(φ_U − φ_I).

    Parameters
    ----------
    I1 : complex
        Fundamental phasor of the residual earth-fault current.
    U0 : complex
        Fundamental phasor of the zero-sequence voltage (neutral displacement voltage).

    Returns
    -------
    Iw, Iv : float
        Active residual current and detuning in A. Iw < 0 physically means a current measurement with reversed polarity.
        Iv = ΣI_coil − I_C > 0 means over-compensated, as in
        [`detuning_current`][groundfault.formulas.detuning_current].

    Raises
    ------
    ValueError
        If U0 is zero or not finite (no angle reference).
    """
    if not np.isfinite(U0) or abs(U0) == 0:
        raise ValueError(tr("formulas.no_zero_sequence_voltage"))
    d = np.angle(U0) - np.angle(I1)
    return float(abs(I1) * math.cos(d)), float(abs(I1) * math.sin(d))


def fundamental_from_network_data(I_CE: Number, d: Number, v: Number) -> Number:
    """Fundamental component of the residual current from network data: I_G = I_CE·√(d² + v²).

    Parameters
    ----------
    I_CE : float or array_like
        Capacitive earth-fault current in A.
    d : float or array_like
        Damping in p.u.
    v : float or array_like
        Relative detuning in p.u.

    Returns
    -------
    float or numpy.ndarray
        Fundamental component I_G in A (a float for scalar input).
    """
    r = np.asarray(I_CE, float) * np.hypot(d, v)
    return float(r) if np.ndim(r) == 0 else r


def zero_sequence_impedance(m: int, I_C: float, U_LE: float, I_L: Optional[float] = None, d: float = 0.0) -> complex:
    """Zero-sequence impedance of the network with its coils at the harmonic order m, seen from the busbar:
    Z_0,m = 1/(j·(m/X_C0 − 1/(m·X_L0))) + d·X_C0 with X_C0 = 3·U_LE/I_C and X_L0 = 3·U_LE/I_L.

    The earth capacitances (X_C0, from I_C) lie in parallel with the coils (X_L0, from the coil current I_L); the
    damping d = I_w/I_C enters as the series resistance d·X_C0 – the form of the estimates without an earth fault
    ([`network_estimate`][groundfault.forecast.bounds.network_estimate]), which the zero-sequence impedances measured
    in staged tests support at the harmonic orders.

    Parameters
    ----------
    m : int
        Harmonic order (1 = fundamental).
    I_C : float
        Capacitive earth-fault current in A.
    U_LE : float
        Line-to-earth voltage (fundamental) in V.
    I_L : float, optional
        Current of the coils in A (default I_C, tuned network).
    d : float, optional
        Damping I_w/I_C in p.u.

    Returns
    -------
    complex
        Z_0,m in Ω (per phase, sequence quantity).

    Examples
    --------
    >>> z = zero_sequence_impedance(5, I_C=650.0, U_LE=20e3 / 3 ** 0.5, I_L=680.0, d=0.04)
    >>> round(z.real, 2), round(z.imag, 2)
    (2.13, -11.12)
    """
    if not (I_C > 0 and U_LE > 0):
        raise ValueError("I_C and U_LE must be positive (I_C=%r, U_LE=%r)" % (I_C, U_LE))
    XC0 = 3.0 * U_LE / I_C
    XL0 = 3.0 * U_LE / (I_L if I_L else I_C)
    return complex(1.0 / (1j * (m / XC0 - 1.0 / (m * XL0))) + d * XC0)


# -------------------------------------------------------------------------------- measurement uncertainty
def current_with_uncertainty(I_measured: Number, m_I: float) -> Number:
    """Assessment value of a current: I_assessed = I_measured·(1 + m_I).

    The measurement-uncertainty margin always increases currents (conservative assessment).

    Parameters
    ----------
    I_measured : float or array_like
        Measured current(s) in A.
    m_I : float
        Relative measurement-uncertainty margin of currents as a fraction, defined by the user (0 = no margin).

    Returns
    -------
    float or numpy.ndarray
        Assessment value(s) in A (a float for scalar input).
    """
    return np.asarray(I_measured, float) * (1.0 + m_I) if np.ndim(I_measured) else float(I_measured) * (1.0 + m_I)


def voltage_with_uncertainty(U_measured: Number, m_U: float) -> Number:
    """Assessment value of a voltage: U_assessed = U_measured·(1 − m_U).

    The measurement-uncertainty margin decreases voltages: the measured harmonic voltage is the denominator of the
    harmonic scaling ([`scaled_harmonic_current`][groundfault.formulas.scaled_harmonic_current]), so a smaller value
    gives a larger, conservative result.

    Parameters
    ----------
    U_measured : float or array_like
        Measured voltage(s) in V (or %).
    m_U : float
        Relative measurement-uncertainty margin of voltages as a fraction, defined by the user (0 = no margin).

    Returns
    -------
    float or numpy.ndarray
        Assessment value(s) in the unit of ``U_measured`` (a float for scalar input).
    """
    return np.asarray(U_measured, float) * (1.0 - m_U) if np.ndim(U_measured) else float(U_measured) * (1.0 - m_U)


TYPICAL_FACTORS = (3.0, 2.0, 10.0, 100.0, 1000.0)
"""Factors of typical errors of a measuring chain, each also as its inverse
([`typical_factor`][groundfault.formulas.typical_factor]): 3 – a clamp around one of the three conductors of a
star-point former or of a coil connection (or around all three where one was meant), 2 – around one of two parallel
conductors, 10, 100, 1000 – the measuring range of a clamp or the ratio of a current transformer set by a power of
ten; a saturating clamp gives a ratio that is none of them."""


def typical_factor(ratio: float, tolerance: float = 0.15) -> Optional[float]:
    """The typical error of a measuring chain that explains a ratio measured/expected – one of
    [`TYPICAL_FACTORS`][groundfault.formulas.TYPICAL_FACTORS] or its inverse (3, 1/3, 2, 1/2, 10, 1/10 … 1/1000) –
    or None.

    Parameters
    ----------
    ratio : float
        Measured value divided by the expected one (e.g. a coil current against the same coil in the other tests).
    tolerance : float, optional
        Largest relative deviation of the ratio from the factor (0.15 = 15 %, on a logarithmic scale, so that 3 and
        1/3 are treated alike).

    Returns
    -------
    float or None
        The nearest typical factor within the tolerance; the correction factor of the channel is its inverse. None
        for a ratio that is no typical error (or not positive).

    Examples
    --------
    >>> typical_factor(3.02), typical_factor(0.34), typical_factor(9.7), typical_factor(1.4)
    (3.0, 0.3333333333333333, 10.0, None)
    """
    try:
        q = float(ratio)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(q) and q > 0):
        return None
    limit = math.log1p(float(tolerance))
    best = None
    for f in TYPICAL_FACTORS:
        for c in (f, 1.0 / f):
            d = abs(math.log(q / c))
            if d <= limit and (best is None or d < best[0]):
                best = (d, c)
    return None if best is None else best[1]


def window_samples(T_win: float, fs: float) -> int:
    """Window length in samples: N_win = T_win·f_s (rounded).

    Parameters
    ----------
    T_win : float
        Window length in s.
    fs : float
        Sampling rate in Hz.

    Returns
    -------
    int
        Number of samples per window.
    """
    return int(round(T_win * fs))


# -------------------------------------------------------------------------------- harmonics
def harmonic_current(I_rms: Number, I_G: Number) -> Number:
    """Harmonic content of the residual current: I_H = √(I_RMS² − I_G²).

    A negative radicand (measurement noise) is clipped to 0.

    Parameters
    ----------
    I_rms : float or array_like
        RMS value (true RMS) of the residual current in A.
    I_G : float or array_like
        Fundamental component in A.

    Returns
    -------
    float or numpy.ndarray
        Harmonic content I_H in A.
    """
    d = np.square(I_rms) - np.square(I_G)
    return np.sqrt(np.maximum(d, 0.0)) if np.ndim(d) else math.sqrt(max(float(d), 0.0))


HARMONIC_CATEGORIES = ("fundamental", "pos_neg", "zero", "even")
"""Categories of the harmonic orders for the scaling to a power-quality quantile
([`harmonic_category`][groundfault.formulas.harmonic_category])."""


def harmonic_category(m: int) -> str:
    """Category of a harmonic order for the scaling to a power-quality quantile.

    * ``"pos_neg"`` – odd orders that are not a multiple of 3 (5, 7, 11, 13, 17, 19 …): positive or negative sequence;
      the current of such an order follows its own voltage and is scaled with it (the 250-Hz current with the 250-Hz
      voltage), without a value of its own with the THD.
    * ``"zero"`` – odd multiples of 3 (3, 9, 15 …): zero sequence; not scaled – the zero sequence arises in the earth
      fault and does not follow the voltage of undisturbed operation.
    * ``"even"`` – even orders (2, 4, 6, 8 …, the even multiples of 3 included): not scaled and listed separately –
      atypical for the voltage of a network, they may point to another cause (e.g. a DC component or saturation at
      the fault inception, current clamps).
    * ``"fundamental"`` – order 1.

    Parameters
    ----------
    m : int
        Harmonic order (≥ 1).

    Returns
    -------
    str
        One of [`HARMONIC_CATEGORIES`][groundfault.formulas.HARMONIC_CATEGORIES].

    Examples
    --------
    >>> [harmonic_category(m) for m in (1, 2, 3, 5, 6, 7, 9)]
    ['fundamental', 'even', 'zero', 'pos_neg', 'even', 'pos_neg', 'zero']
    """
    m = int(m)
    if m == 1:
        return "fundamental"
    if m % 2 == 0:
        return "even"
    return "zero" if m % 3 == 0 else "pos_neg"


SCALING_RULES = ("own voltage", "THD", "as measured", "no information")
"""Rules of the scaling of one order ([`order_scaling`][groundfault.formulas.order_scaling]): with its own voltage,
with the THD, as measured (zero sequence, even orders), as measured for lack of a value (positive or negative sequence
without its own value and without a THD)."""

i18n.register_labels(columns={"category": "Kategorie", "rule": "Regel", "part": "Teil", "U_level_V": "U_Pegel_V",
                              "U95_V": "U95_V", "I_A": "I_A", "I_scaled_A": "I_skaliert_A"},
                     values={"category": {"fundamental": "Grundschwingung", "pos_neg": "Mit-/Gegensystem",
                                          "zero": "Nullsystem", "even": "gerade"},
                             "rule": {"own voltage": "eigene Spannung", "THD": "THD", "as measured": "wie gemessen",
                                      "no information": "keine Angabe"},
                             "part": {"model": "Modell", "remainder": "Rest"}})


def order_scaling(m: int, U_95: Optional[float], U_level: float, f_thd: Optional[float] = None,
                  safety_factor: float = 1.0, from_ll: bool = False, min_level: float = 0.0) -> Tuple[float, str]:
    """Scaling factor of the current of one harmonic order to a power-quality quantile, and its rule.

    * Positive or negative sequence ([`harmonic_category`][groundfault.formulas.harmonic_category] ``"pos_neg"``):
      with its own voltage, k_m = k_s·U_95,m/U_level,m (a line-to-line quantile divided by √3) – if ``U_95`` is a
      number above 0 and ``U_level`` at least ``min_level``; otherwise with the THD factor ``f_thd``; without one 1
      (``"no information"``). A quantile of 0 V is no level: the order lies below the resolution of the instrument
      (its own factor would remove the measured current).
    * Zero sequence and even orders: 1 (``"as measured"``).

    Parameters
    ----------
    m : int
        Harmonic order (≥ 2).
    U_95 : float or None
        Quantile of the voltage of order m in V (None, NaN or ≤ 0: no value).
    U_level : float
        Level of the voltage of order m during the test in V (the natural sequence of m).
    f_thd : float, optional
        Flat THD factor k_s·THD_95/THD_test (None: none).
    safety_factor : float, optional
        Factor k_s on the quantile.
    from_ll : bool, optional
        ``U_95`` is a line-to-line value (divided by √3).
    min_level : float, optional
        Smallest usable level in V.

    Returns
    -------
    (float, str)
        Factor and rule (one of [`SCALING_RULES`][groundfault.formulas.SCALING_RULES]).

    Examples
    --------
    >>> order_scaling(5, 300.0, 100.0, safety_factor=1.2)
    (3.6, 'own voltage')
    >>> order_scaling(3, 30.0, 10.0)
    (1.0, 'as measured')
    >>> order_scaling(17, None, 2.0, f_thd=4.0)
    (4.0, 'THD')
    >>> order_scaling(17, 0.0, 2.0, f_thd=4.0)          # 0 V: below the resolution of the instrument, not a level
    (4.0, 'THD')
    """
    if harmonic_category(m) != "pos_neg":
        return 1.0, "as measured"
    u = None if U_95 is None or not np.isfinite(float(U_95)) or float(U_95) <= 0 else float(U_95)
    level = float(U_level) if U_level is not None else float("nan")
    if u is not None and np.isfinite(level) and level > 0 and level >= float(min_level):
        return float(safety_factor) * (u / math.sqrt(3) if from_ll else u) / level, "own voltage"
    if f_thd is not None and np.isfinite(float(f_thd)):
        return float(f_thd), "THD"
    return 1.0, "no information"


def scaled_harmonic_current(I_H: Number, U_95: Number, U_measured: Number, I_unscaled: Optional[Number] = None) -> Number:
    """Harmonic content scaled to the 95 % quantile of the harmonic voltage with one flat factor:
    I_H,scaled = I_H·U_THD,95%/U_THD,meas.

    Both voltages must have the same reference (% with %, V with V!). With ``I_unscaled`` the part of the harmonic
    content that is not scaled – the zero sequence, the even orders and the content not assigned to an order (see
    [`harmonic_category`][groundfault.formulas.harmonic_category]) – keeps its measured value:

        I_H,scaled = √((I_H² − I_u²)·(U_95/U_meas)² + I_u²)

    Parameters
    ----------
    I_H : float or array_like
        Harmonic content during the fault test in A.
    U_95 : float or array_like
        95 % quantile of the harmonic voltage (THD) of the network.
    U_measured : float or array_like
        Harmonic voltage (THD) during the fault test, same reference as ``U_95``.
    I_unscaled : float or array_like, optional
        Part I_u of the harmonic content in A that keeps its measured value (at most ``I_H``); None (default): every
        order is scaled.

    Returns
    -------
    float or numpy.ndarray
        Scaled harmonic content in A.

    Raises
    ------
    ValueError
        If ``U_measured`` is not > 0.

    Examples
    --------
    >>> scaled_harmonic_current(10.0, 3.0, 1.5)
    20.0
    >>> round(scaled_harmonic_current(10.0, 3.0, 1.5, I_unscaled=6.0), 3)      # √(64·4 + 36)
    17.088
    """
    U_measured = np.asarray(U_measured, float)
    if np.any(U_measured <= 0):
        raise ValueError(tr("formulas.thd_measured_not_positive"))
    f = np.asarray(U_95, float) / U_measured
    ih = np.asarray(I_H, float)
    if I_unscaled is None:
        r = ih * f
    else:
        iu = np.minimum(np.asarray(I_unscaled, float), ih)
        r = np.sqrt((ih ** 2 - iu ** 2) * f ** 2 + iu ** 2)
    return float(r) if np.ndim(r) == 0 else r


def rms_current_forecast(I_G: Number, I_H_scaled: Number) -> Number:
    """Forecast RMS value of the residual current with scaled harmonics: I_RMS = √(I_G² + I_H,scaled²).

    Parameters
    ----------
    I_G : float or array_like
        Fundamental component in A.
    I_H_scaled : float or array_like
        Scaled harmonic content in A ([`scaled_harmonic_current`][groundfault.formulas.scaled_harmonic_current]).

    Returns
    -------
    float or numpy.ndarray
        Forecast RMS value in A (a float for scalar input).
    """
    r = np.hypot(I_G, I_H_scaled)
    return float(r) if np.ndim(r) == 0 else r


def thd_percent_to_volt(thd_percent: Number, U1: Number) -> Number:
    """Harmonic voltage from a THD in percent: U_H = THD·U_1/100.

    Changes the reference of a harmonic voltage (% → V), e.g. for the harmonic scaling or the limiting resistance.

    Parameters
    ----------
    thd_percent : float or array_like
        Total harmonic distortion in %.
    U1 : float or array_like
        Fundamental voltage in V.

    Returns
    -------
    float or numpy.ndarray
        Harmonic voltage U_H in V.
    """
    return np.asarray(thd_percent, float) / 100.0 * np.asarray(U1, float)


def sequence_voltage_from_ll(U_ll_max: Number) -> Number:
    """Positive/negative-sequence value from line-to-line values: U = U_LL,max/√3.

    Parameters
    ----------
    U_ll_max : float or array_like
        Largest of the three line-to-line values (loops) in V.

    Returns
    -------
    float or numpy.ndarray
        Sequence voltage (line-to-earth reference) in V.
    """
    return np.asarray(U_ll_max, float) / math.sqrt(3.0)


# -------------------------------------------------------------------------------- resistive approach and limits
def limit_resistance(U_thd95_V: float, I_res_max: float, I_G: float, R_E_max: float) -> float:
    """Limiting resistance of the resistive approach: R_lim = 3·U_THD,95%/√(I_RES,max² − I_G²) − 3·R_E,max.

    The harmonic voltage drives the harmonic current through the fault circuit (line resistances plus 3·R_E). A fault
    behind a line with R1 + R2 + R0 ≥ R_lim keeps the residual current below I_RES,max
    ([`resistive_assessment`][groundfault.formulas.resistive_assessment],
    [`limit_distance`][groundfault.formulas.limit_distance]).

    Parameters
    ----------
    U_thd95_V : float
        Harmonic voltage of all orders above the fundamental (a high quantile of a long-term measurement, e.g. the 95 %
        quantile) in the positive/negative sequence in V, line-to-earth reference (from line-to-line values with
        [`sequence_voltage_from_ll`][groundfault.formulas.sequence_voltage_from_ll]).
    I_res_max : float
        Permissible residual current in A, defined by the user (e.g. with
        [`max_residual_current`][groundfault.formulas.max_residual_current]).
    I_G : float
        Fundamental component of the residual current in A, I_G = √(Iw² + Iv²).
    R_E_max : float
        Largest earthing resistance in Ω.

    Returns
    -------
    float
        R_lim in Ω. If I_G ≥ I_RES,max, no budget is left for harmonics → R_lim = +∞ (countermeasures regardless
        of the line).

    Warns
    -----
    UserWarning
        If I_G ≥ I_RES,max.

    Notes
    -----
    This is the limiting resistance R_Grenz of the resistive approach of the VDE Impuls on the residual earth-fault
    current (see References). Its worst case: a series resonance of the positive-, negative- and zero-sequence systems
    (all reactances and the source impedance neglected), a fault resistance of 0, the harmonic sources as voltage
    sources taken from the measured busbar voltages, and the largest earthing resistance R_E,max of the network. There
    R_Grenz = 3·√Σ_{ν>1} U_q,max(ν)²/√(I_RES,max² − I_rw,max² − I_rb,max²) − 3·R_E,max: ``U_thd95_V`` is
    √Σ_{ν>1} U_q,max(ν)², and I_G² = I_rw² + I_rb² (active and reactive residual current at the fundamental). The
    factor 3 comes from the series connection of the three sequence systems in the fault circuit (fault current
    3·I_0); it is not the √3 of line-to-line voltages, which only converts the input
    ([`sequence_voltage_from_ll`][groundfault.formulas.sequence_voltage_from_ll]). groundfault adds the critical
    distance ([`limit_distance`][groundfault.formulas.limit_distance]) and, in
    [`groundfault.campaign.resistive_approach`][groundfault.campaign.resistive_approach], the factor F and the
    reduction factor r as parameters.

    References
    ----------
    VDE ETG: *VDE Impuls „Erdschluss-Reststrom in Mittelspannungsnetzen: Eine (überschätzte) Gefahr?“* VDE Verband der
    Elektrotechnik Elektronik Informationstechnik e. V., Energietechnische Gesellschaft (ETG), Frankfurt am Main,
    October 2021. <https://www.vde.com/resource/blob/2091758/8372514d5f581c4f86fd14aaffe4cfa2/vde-impuls-erdschlussreststrom-in-mittelspannungsnetzen-eine-ueberschaetzte-gefahr--data.pdf>
    """
    budget = I_res_max ** 2 - I_G ** 2
    if budget <= 0:
        warnings.warn(tr("formulas.limit_reached_by_fundamental"))
        return float("inf")
    return 3.0 * U_thd95_V / math.sqrt(budget) - 3.0 * R_E_max


def resistive_assessment(R_limit_ohm: float, R1_line: float, R2_line: Optional[float] = None,
                         R0_line: float = 0.0) -> str:
    """Assessment of a fault location with the resistive approach: R_lim ≤ R1 + R2 + R0 → uncritical.

    Parameters
    ----------
    R_limit_ohm : float
        Limiting resistance R_lim in Ω ([`limit_resistance`][groundfault.formulas.limit_resistance]).
    R1_line : float
        Positive-sequence resistance of the line between the substation and the fault location in Ω.
    R2_line : float, optional
        Negative-sequence resistance in Ω (None → R2 = R1).
    R0_line : float, optional
        Zero-sequence resistance in Ω (default 0).

    Returns
    -------
    str
        ``"uncritical"`` if R_lim ≤ R1 + R2 + R0, otherwise ``"countermeasures"``.

    Notes
    -----
    The criterion of the VDE Impuls on the residual earth-fault current (see
    [`limit_resistance`][groundfault.formulas.limit_resistance]): a node is uncritical if the resistances of its fault
    path in the positive-, negative- and zero-sequence system reach at least R_Grenz; otherwise it is checked
    individually (e.g. with the equivalent-source method) or countermeasures are taken.
    """
    R2_line = R1_line if R2_line is None else R2_line
    return "uncritical" if R_limit_ohm <= R1_line + R2_line + R0_line else "countermeasures"


def limit_distance(R_limit_ohm: float, R1_km: float, R0_km: float, R2_km: Optional[float] = None) -> float:
    """Critical distance of the resistive approach: l_lim = R_lim/(R1' + R2' + R0') in km.

    Faults farther from the substation than l_lim are uncritical.

    Parameters
    ----------
    R_limit_ohm : float
        Limiting resistance R_lim in Ω ([`limit_resistance`][groundfault.formulas.limit_resistance]).
    R1_km, R0_km : float
        Positive- and zero-sequence resistance per unit length in Ω/km.
    R2_km : float, optional
        Negative-sequence resistance per unit length in Ω/km (None → R2' = R1').

    Returns
    -------
    float
        l_lim in km: 0 for R_lim ≤ 0 (uncritical even at the substation), ∞ for R_lim = ∞ (no finite critical
        distance).

    Notes
    -----
    An extension of the VDE Impuls on the residual earth-fault current (see
    [`limit_resistance`][groundfault.formulas.limit_resistance]), which compares the total resistance of each fault
    path – e.g. from a network calculation – with R_Grenz: with uniform resistances per unit length the limiting
    resistance becomes a line length.
    """
    R2_km = R1_km if R2_km is None else R2_km
    if not math.isfinite(R_limit_ohm):
        return float("inf")
    return max(R_limit_ohm, 0.0) / (R1_km + R2_km + R0_km)


def max_residual_current(R_E_max: float, U_Tp: float, F: float, r: float = 1.0) -> float:
    """Limit of the residual current from the permissible touch voltage: I_RES,max = F·U_Tp/(r·R_E,max).

    The earth potential rise U_E = r·R_E,max·I_RES must not exceed F·U_Tp. U_Tp and F are defined by the user (e.g.
    from the applicable standard or the operator's specification) – groundfault has no defaults for them.

    Parameters
    ----------
    R_E_max : float
        Largest earthing impedance in Ω.
    U_Tp : float
        Permissible touch voltage in V.
    F : float
        Ratio of the permissible earth potential rise to the permissible touch voltage.
    r : float, optional
        Reduction factor (default 1: no reduction).

    Returns
    -------
    float
        I_RES,max in A.

    Raises
    ------
    ValueError
        If U_Tp or F is None, or if R_E,max, U_Tp, F or r is not > 0.

    Notes
    -----
    The VDE Impuls on the residual earth-fault current (VDE ETG, October 2021; see
    [`limit_resistance`][groundfault.formulas.limit_resistance]) limits the residual current by
    I_RES,max ≤ 2·U_Tp/R_E,max; here the factor 2 is the parameter F, and the reduction factor r is added (r = 1
    there).

    Examples
    --------
    With illustrative values U_Tp = 100 V and F = 2.5 (define your own):

    >>> max_residual_current(2.0, U_Tp=100.0, F=2.5)
    125.0
    >>> max_residual_current(2.0, U_Tp=100.0, F=2.5, r=0.5)
    250.0
    """
    missing = [n for n, v in (("U_Tp", U_Tp), ("F", F)) if v is None]
    if missing:
        raise ValueError(tr("formulas.limit_not_given", names=", ".join(missing)))
    if R_E_max <= 0 or r <= 0 or U_Tp <= 0 or F <= 0:
        raise ValueError(tr("formulas.limit_parameters"))
    return F * U_Tp / (r * R_E_max)


# -------------------------------------------------------------------------------- line parameters
def earth_return_depth(f: Number, rho_E: float) -> Number:
    """Equivalent depth of the earth return path: δ_E = 1.85/√(ω·μ0/ρ_E) in m (Carson/Rüdenberg).

    Parameters
    ----------
    f : float or array_like
        Frequency in Hz.
    rho_E : float
        Soil resistivity of the site in Ωm (e.g. from a measurement).

    Returns
    -------
    float or numpy.ndarray
        δ_E in m.
    """
    w = 2 * math.pi * np.asarray(f, float)
    return 1.85 / np.sqrt(w * MU0 / rho_E)


def z0_overhead_line(f: Number, R_L_km: float, r_L_m: float, d_m: float, rho_E: float,
                     mu_r: float = 1.0) -> Number:
    """Zero-sequence impedance per unit length of an overhead line without earth wire in Ω/km.

    Z0' = R_L' + 3ωμ0/8 + jωμ0/(2π)·(μr/4 + 3·ln(δ_E/∛(r_L·d²)))

    The real part grows linearly with f (3ωμ0/8 = earth return, ≈ 0.148 Ω/km at 50 Hz and ≈ 0.740 Ω/km at 250 Hz,
    independent of the line) – this is why the zero-sequence resistance is higher at harmonic frequencies.

    Parameters
    ----------
    f : float or array_like
        Frequency in Hz.
    R_L_km : float
        Conductor resistance in Ω/km.
    r_L_m : float
        Conductor radius in m.
    d_m : float
        Geometric mean distance between the conductors in m.
    rho_E : float
        Soil resistivity of the site in Ωm, see [`earth_return_depth`][groundfault.formulas.earth_return_depth].
    mu_r : float, optional
        Relative permeability of the conductors (default 1).

    Returns
    -------
    complex or numpy.ndarray
        Z0' in Ω/km (a complex number for scalar ``f``).
    """
    f = np.asarray(f, float)
    w = 2 * math.pi * f
    delta = earth_return_depth(f, rho_E)
    r_ers = (r_L_m * d_m ** 2) ** (1.0 / 3.0)
    z = R_L_km / 1000.0 + 3 * w * MU0 / 8 + 1j * w * MU0 / (2 * math.pi) * (mu_r / 4.0 + 3 * np.log(delta / r_ers))
    z = z * 1000.0
    return complex(z) if np.ndim(z) == 0 else z


def r0_overhead_line(f: Number, R_L_km: float) -> Number:
    """Zero-sequence resistance per unit length of an overhead line: R0' = R_L' + 3ωμ0/8 in Ω/km.

    This is the real part of [`z0_overhead_line`][groundfault.formulas.z0_overhead_line]; it depends neither on the
    geometry nor on ρ_E.

    Parameters
    ----------
    f : float or array_like
        Frequency in Hz.
    R_L_km : float
        Conductor resistance in Ω/km.

    Returns
    -------
    float or numpy.ndarray
        R0' in Ω/km (a float for scalar ``f``).
    """
    r = R_L_km + 3 * 2 * math.pi * np.asarray(f, float) * MU0 / 8 * 1000.0
    return float(r) if np.ndim(r) == 0 else r


# -------------------------------------------------------------------------------- equivalent source
def source_from_two_measurements(I1: complex, Z1: complex, I2: complex, Z2: complex) -> Tuple[complex, complex]:
    """Active two-terminal (Thevenin) equivalent from two measurements with Z1 ≠ Z2.

    Z_q = (I2·Z2 − I1·Z1)/(I1 − I2);  U_q = I1·(Z_q + Z1) = I2·(Z_q + Z2).

    Parameters
    ----------
    I1, Z1 : complex
        First measurement: phasor of one harmonic order of the fault current in A and additional impedance in Ω.
    I2, Z2 : complex
        Second measurement (same angle reference as ``I1``).

    Returns
    -------
    Uq, Zq : complex
        Source voltage in V and source impedance in Ω.

    Raises
    ------
    ValueError
        If the additional impedances are practically equal.
    ZeroDivisionError
        If I1 ≈ I2.

    Warns
    -----
    UserWarning
        If the problem is ill-conditioned (a current error of 1 % changes Z_q by more than 10 %).

    Notes
    -----
    For I1 ≈ I2 (additional impedances too similar, or Z_q ≫ Z) the problem is ill-conditioned – the relative
    uncertainty of Z_q grows with |I1|/|I1 − I2|.
    """
    if abs(Z1 - Z2) <= 1e-6 * max(abs(Z1), abs(Z2), 1.0):
        raise ValueError(tr("formulas.equal_impedances"))
    den = I1 - I2
    if abs(den) <= 1e-12 * max(abs(I1), abs(I2), 1e-300):
        raise ZeroDivisionError(tr("formulas.equal_currents"))
    Zq = (I2 * Z2 - I1 * Z1) / den
    Uq = I1 * (Zq + Z1)
    # sensitivity: relative change of Z_q per 1 % error in I1 (derivative of the Z_q formula)
    sens = 0.01 * abs(I1) / abs(den) * abs(Zq + Z1) / max(abs(Zq), 1e-12)
    if sens > 0.10:
        warnings.warn(tr("formulas.ill_conditioned", change=100 * sens))
    return complex(Uq), complex(Zq)


def residual_current_from_sources(I_G: float, Uq: Mapping[int, complex], Zq: Mapping[int, complex],
                                  Z_E: complex) -> Tuple[float, Dict[int, float]]:
    """Residual current at the earthing impedance Z_E from the equivalent sources of the harmonic orders.

    I_RES = √(I_G² + Σ_n |U_q,n/(Z_q,n + Z_E)|²)

    Parameters
    ----------
    I_G : float
        Fundamental component in A.
    Uq, Zq : mapping of int to complex
        Source voltage in V and source impedance in Ω per harmonic order n.
    Z_E : complex
        Earthing impedance in Ω.

    Returns
    -------
    I_RES : float
        Residual current in A.
    parts : dict of int to float
        Harmonic current |I_n| per order in A.
    """
    part = {}
    for n in sorted(Uq):
        part[n] = float(abs(Uq[n] / (Zq[n] + Z_E)))
    return float(math.sqrt(I_G ** 2 + sum(v * v for v in part.values()))), part
