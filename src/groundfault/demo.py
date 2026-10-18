# -*- coding: utf-8 -*-
"""Synthetic staged earth-fault tests with a **known solution** (tests, training, plausibility checks).

The functions write COMTRADE recordings of a substation (HV/MV), a secondary substation (MV/LV station) and a
transformer measurement and return the exact values of the quantities the evaluation derives from them.

Physical model (fault on line L3 or ``faulted_phase``, 20-kV network):

* Line-to-earth voltages U_xE = E_x + U0 (E_x symmetrical, U0 = neutral displacement voltage).
* Fundamental component of the fault current in the orientation of the angle method (Iw > 0):
  I' = U0·(G + jB), G = Iw/|U0|, B = −Iv/|U0| ⇒ the angle method returns exactly (Iw, Iv).
  The fault branch (line → earth through Z_F) carries I_F = −I'; hence U_3E = Z_F·I_F and
  U0 = −E_3/(1 + Z_F·Y) (closed-form solution).
* Harmonic of order m: active two-terminal (Thevenin) equivalent I'_m = (s·U_q,m + U_s,m)/(Z_q,m + Z_F) (referred
  to L1-L2), source drift s per measurement (magnitude and phase), U_s,m a source that only exists during the fault
  (saturating coils; default 0). Before and after the fault: sequence voltage s·U_pre,m in the natural sequence of
  the order (m mod 3). During the fault the busbar sequence voltages change by ΔU_1 = Z_1·I'/(3·p_1),
  ΔU_2 = Z_2·I'/(3·p_2) (p_s = phase factor of the faulted phase) and ΔU_0 = Z_0·I'/3 − U_s with
  Z_0 = 3·Z_q − Z_1 − Z_2 (default Z_1 = Z_2 = 0: the whole change in the zero sequence).
* Coil currents I_L = U0/(jX_L) (including the harmonics U0,m/(j·m·X_L) and a decaying DC component when the
  fault starts), transient of the fault current, active residual current increase, decaying neutral
  displacement voltage after the fault clearance, noise and DC offset of the current clamps.
* Station: earth potential rise U_E = r·Z_E·I_F (reduction factor r, Z_E per order), probe shares, touch voltage
  U_T = U_E/F, shield current I_S = (1 − r)·I_F.
* Transformer: load current + harmonic powers S_m per order; during the fault the positive- and negative-
  sequence share of the fault current of every order through the upstream impedance (transformer + HV
  network) and the zero-sequence current = coil current/3.

All true values are saved as JSON next to the ``.cfg`` file (``<stem>_truth.json``).

Examples
--------
>>> from groundfault import demo, open_recording, evaluate, Intervals
>>> truth = demo.make_substation_recording("SUB_0_10_000kHz.cfg", 0.0)          # doctest: +SKIP
>>> b = truth["intervals"]                                                        # doctest: +SKIP
>>> res = evaluate(open_recording("SUB_0_10_000kHz.cfg"),
...                Intervals(b["steady_state"], b["pre_fault"], b["post_fault"]))  # doctest: +SKIP
>>> res.values["Iw"], truth["Iw"]                                                 # doctest: +SKIP
"""
from __future__ import annotations

import datetime as _dt
import glob
import json
import math
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import i18n
from .comtrade import write_comtrade
from .i18n import tr
from .symmetrical import A, A2

__all__ = ["DemoHarmonic", "DEFAULT_HARMONICS", "make_substation_recording", "make_substation_series",
           "make_station_recording", "make_transformer_recording", "make_undisturbed_transformer_recording",
           "rms_file_from_instantaneous", "make_groundmeas_db",
           "make_campaign", "GROUNDMEAS_SCHEMA", "polar", "U_PH"]

U_PH = 20000.0 / math.sqrt(3.0)
"""Phase-to-earth voltage of the 20-kV demo network in V."""

i18n.register({
    "demo.one_step": {
        "en": "Only one step per recording (active_step or reactive_step).",
        "de": "Nur eine Stufe je Aufzeichnung (active_step oder reactive_step)."},
    "demo.lv_network_impedance": {
        "en": "LV network: |Z_LV| must be larger than |Z_E| (parallel connection).",
        "de": "Ortsnetz: |Z_ON| muss größer sein als |Z_E| (Parallelschaltung)."},
})


def polar(magnitude: float, angle_deg: float) -> complex:
    """Complex number from magnitude and angle in degrees."""
    return complex(magnitude * np.exp(1j * np.deg2rad(angle_deg)))


@dataclass
class DemoHarmonic:
    """Harmonic source of the demo network (active two-terminal equivalent per order).

    Attributes
    ----------
    order : int
        Harmonic order m.
    U_pre : complex
        Sequence voltage (line-to-earth) before the fault, referred to L1-L2, in V.
    Uq : complex
        Source voltage of the two-terminal equivalent, referred to L1-L2, in V.
    Zq : complex
        Internal impedance of the two-terminal equivalent in Ω.
    Z1, Z2 : complex
        Positive- and negative-sequence impedance at the busbar in Ω (default 0: Z_0 = 3·Z_q).
    Us : complex
        Source that only exists during the fault (e.g. saturating coils), referred to L1-L2, in V (default 0).
    """

    order: int
    U_pre: complex          # sequence voltage (L-E) before the fault, referred to L1-L2 [V]
    Uq: complex             # source voltage of the two-terminal equivalent, referred to L1-L2 [V]
    Zq: complex             # internal impedance of the two-terminal equivalent [Ω]
    Z1: complex = 0j        # positive-sequence impedance at the busbar [Ω]
    Z2: complex = 0j        # negative-sequence impedance at the busbar [Ω]
    Us: complex = 0j        # source that only exists during the fault [V]


def _thevenin_harmonic(order: int, U_pre: complex, Zq: complex, faulted_phase: str = "L3", Z1: complex = 0j,
                       Z2: complex = 0j, Us: complex = 0j) -> DemoHarmonic:
    """Harmonic source whose source voltage is the pre-fault voltage of the faulted phase (Thevenin):
    U_q = −(phase factor of the natural sequence)·U_pre in the orientation of the angle method."""
    seq = {1: "pos", 2: "neg", 0: "zero"}[order % 3]
    factor = {"pos": {"L1": 1.0, "L2": A2, "L3": A}, "neg": {"L1": 1.0, "L2": A, "L3": A2},
              "zero": {"L1": 1.0, "L2": 1.0, "L3": 1.0}}[seq][faulted_phase]
    return DemoHarmonic(order, U_pre, -factor * U_pre, Zq, Z1, Z2, Us)


DEFAULT_HARMONICS: Tuple[DemoHarmonic, ...] = (
    _thevenin_harmonic(3, polar(25, 30), 6.0 - 1.5j),
    _thevenin_harmonic(5, polar(220, -35), 4.5 - 2.5j),
    _thevenin_harmonic(7, polar(110, 50), 7.0 - 3.5j),
    _thevenin_harmonic(11, polar(35, 80), 2.5 - 2.2j),
    _thevenin_harmonic(13, polar(25, -50), 5.0 - 2.8j),
)
"""Harmonic sources of the default demo network (orders 3, 5, 7, 11, 13; invented values, source voltage = pre-fault
voltage of the faulted phase L3)."""

_SEQ = {0: np.array([1, 1, 1], complex), 1: np.array([1, A2, A]), 2: np.array([1, A, A2])}


def _seq_factors(m: int) -> np.ndarray:
    """Factors (L1, L2, L3) of the natural sequence of order m."""
    return _SEQ[m % 3]


def _wave(t: np.ndarray, f: float, X: complex) -> np.ndarray:
    """√2·Re(X·e^{j2πft}) – waveform of the RMS phasor X given at t = 0."""
    return math.sqrt(2.0) * np.real(X * np.exp(2j * np.pi * f * t))


def _rotate_phase(x_ll: complex, m: int, phi_ll: float) -> complex:
    """Phasor of order m from the L1-L2 reference system into the time-origin system of the file."""
    return x_ll * np.exp(1j * m * phi_ll)


def _noise(rng, n, sigma):
    """Gaussian noise with standard deviation ``sigma`` (zeros for sigma = 0)."""
    return sigma * rng.standard_normal(n) if sigma else np.zeros(n)


def _fluctuation(rng, t: np.ndarray, tau: float = 1.0) -> np.ndarray:
    """Smooth complex random process (first-order low-pass with time constant ``tau``, RMS value 1) – for
    background levels that change slowly in magnitude and phase as at real stations."""
    dt = 0.01
    nk = int(t[-1] / dt) + 2
    w = rng.standard_normal(nk) + 1j * rng.standard_normal(nk)
    a = math.exp(-dt / tau)
    y = np.empty(nk, complex)
    y[0] = w[0]
    for i in range(1, nk):
        y[i] = a * y[i - 1] + math.sqrt(1 - a * a) * w[i]
    y /= math.sqrt(float(np.mean(np.abs(y) ** 2)))
    tk = np.arange(nk) * dt
    return np.interp(t, tk, y.real) + 1j * np.interp(t, tk, y.imag)


# =========================================================================== substation measurement
def make_substation_recording(path: str, Z_F: float = 0.0, *, fs: float = 10000.0, duration: float = 9.0,
                       f1: float = 50.02, theta0_deg: float = 70.0, Iw: float = 20.0, Iv: float = 25.0,
                       harmonic_sources: Sequence[DemoHarmonic] = DEFAULT_HARMONICS,
                       drift: complex = 1.0, faulted_phase: int = 3, t_on: float = 2.0, t_off: float = 6.0,
                       active_step: Optional[Tuple[float, float, float]] = (4.6, 5.4, 15.0),
                       reactive_step: Optional[Tuple[float, float, float]] = None,
                       network_step: Optional[Tuple[float, float]] = None,
                       dc_offset: Optional[Tuple[float, float]] = None,
                       coils_A: Sequence[float] = (300.0, 250.0), U0_pre: complex = polar(150, 60),
                       polarity: int = 1, second_ct: Optional[Tuple[float, float]] = (1.01, 0.5),
                       dc_clamp_A: float = 2.0, noise_I: float = 0.05, noise_U: float = 3.0,
                       transient: bool = True, channel_names: str = "daneo", file_format: str = "BINARY",
                       start: Optional[_dt.datetime] = None, seed: int = 0, trigger: bool = False,
                       fault_current: bool = True, fault_source_in_coils: bool = False) -> dict:
    """Write a COMTRADE recording of a staged earth-fault test in a substation (HV/MV) with known solution.

    The recording contains the three line-to-earth voltages, the fault current (one or two CTs) and the coil
    currents; the fault lasts from ``t_on`` to ``t_off``.

    Parameters
    ----------
    path : str
        Path of the ``.cfg`` file to write.
    Z_F : float, optional
        Fault resistance in Ω.
    fs : float, optional
        Sampling rate in Hz.
    duration : float, optional
        Duration of the recording in s.
    f1 : float, optional
        Mains frequency in Hz.
    theta0_deg : float, optional
        Phase angle of E_1 at t = 0 in degrees (time origin of the file).
    Iw, Iv : float, optional
        Active residual current and detuning (reactive residual current) of the fundamental component in A.
    harmonic_sources : sequence of DemoHarmonic, optional
        Two-terminal equivalents of the harmonics.
    drift : complex, optional
        Source drift s of this measurement (factor on the harmonic sources and the pre-fault harmonics).
    faulted_phase : int, optional
        Faulted line (1, 2 or 3).
    t_on, t_off : float, optional
        Fault inception and fault clearance in s.
    active_step : tuple (t_a, t_b, ΔIw), optional
        Active residual current increase by ΔIw between t_a and t_b.
    reactive_step : tuple (t_a, t_b, ΔIv), optional
        Step of the detuning current by ΔIv between t_a and t_b (coil adjustment: the current of coil 1 changes by
        ΔIv) – at most one of ``active_step`` and ``reactive_step``.
    network_step : tuple (t_a, ΔIv), optional
        Network change from t_a until the fault clearance: the detuning current changes by ΔIv while the coil
        currents stay the same (a network section trips, the capacitive earth-fault current changes); may be
        combined with ``active_step``.
    dc_offset : tuple (A, τ), optional
        DC component A·e^{−t/τ} in the fault current, decaying after the fault inception (e.g. from the coil
        current).
    coils_A : sequence of float, optional
        Coil currents in A at full displacement voltage (one coil-current channel per coil).
    U0_pre : complex, optional
        Neutral displacement voltage before and after the fault (fundamental component, referred to L1-L2).
    polarity : int, optional
        Polarity of the fault-current measurement (−1 = clamp reversed).
    second_ct : tuple (gain, phase error in degrees), optional
        Second fault-current CT; the phase error is applied as a time offset (for all orders). None: one CT only.
    dc_clamp_A : float, optional
        DC offset of the (first) fault-current clamp in A.
    noise_I, noise_U : float, optional
        Standard deviation of the noise of the currents (A) and voltages (V).
    transient : bool, optional
        Add the transients at the fault inception (fault current, healthy line voltages, DC component of the
        coil currents).
    channel_names : {"daneo", "structured"}, optional
        Channel names of a DANEO recorder export (``DANEO 1_Ströme_IF1 Inst`` …) or of the structured naming
        convention (``"structured"``: ``u_20kv_l1e_j02_vt_m01_v__raw`` …).
    file_format : str, optional
        COMTRADE data format (see [`groundfault.comtrade.write_comtrade`][groundfault.comtrade.write_comtrade]).
    start : datetime.datetime, optional
        Time of the first sample (default 2026-01-15 09:00).
    seed : int, optional
        Seed of the random generator (noise).
    trigger : bool, optional
        Add a digital trigger channel (1 from the fault inception on).
    fault_current : bool, optional
        False: no fault-current channel (an earth fault recorded at the busbar, e.g. by a disturbance recorder).
    fault_source_in_coils : bool, optional
        True: the coils carry the source that arises in the fault (saturating coils) – their currents contain
        I_Nh,m = 3·U_s,m/Z_0,m in addition to the linear part, split in proportion to ``coils_A``; False: the source
        sits elsewhere in the zero sequence (e.g. voltage transformers), the coil currents are linear.

    Returns
    -------
    dict
        True values (also saved as ``<stem>_truth.json``): the exact assessment quantities of the steady state
        (``Iw``, ``Iv``, ``IG``, ``IH``, ``IRES`` …), the harmonic sources, the voltage distortion before the
        fault and recommended analysis intervals (``intervals``).

    Raises
    ------
    ValueError
        If both ``active_step`` and ``reactive_step`` are given.
    """
    if active_step and reactive_step:
        raise ValueError(tr("demo.one_step"))
    rng = np.random.default_rng(seed)
    n = int(round(duration * fs))
    t = np.arange(n) / fs
    w1 = 2 * np.pi * f1
    th = np.deg2rad(theta0_deg)
    fl = int(faulted_phase) - 1
    # ---- fundamental component
    E = U_PH * np.exp(1j * th) * np.array([1, A2, A])           # E1, E2, E3 at t = 0
    phi_ll = float(np.angle(E[0] - E[1]))                      # reference angle L1-L2 at t = 0
    U0_pre_t = _rotate_phase(U0_pre, 1, phi_ll)

    def u0_off(Iw_, Iv_):
        # Y from Iw, Iv referred to |U0| ≈ U_PH (iterative, converges in 3 steps)
        U0 = -E[fl]
        for _ in range(5):
            Y = (Iw_ - 1j * Iv_) / abs(U0)
            U0 = -E[fl] / (1 + Z_F * Y)
        Ip = U0 * Y                                             # orientation of the angle method (Iw > 0)
        return U0, Ip, Y

    U0_f, Ip1, Y = u0_off(Iw, Iv)
    gate = ((t >= t_on) & (t < t_off)).astype(float)
    # states of the fundamental component during the fault: steady state, step of the active residual current
    # (G increases by ΔIw/|U0|) or of the detuning (coil), network change (detuning, coils unchanged)
    step_ = np.zeros(n, bool)
    if active_step or reactive_step:
        wa, wb, _d = active_step or reactive_step
        step_ = (t >= wa) & (t < wb)
    net_ = (t >= network_step[0]) if network_step else np.zeros(n, bool)
    states = {}                                        # (step, network) → (U0, I'_1, mask)
    for a_ in (False, True):
        for b_ in (False, True):
            mask = gate * ((step_ == a_) & (net_ == b_))
            if not mask.any():
                continue
            iw_ = Iw + (active_step[2] if a_ and active_step else 0.0)
            iv_ = Iv + (reactive_step[2] if a_ and reactive_step else 0.0) + (network_step[1] if b_ else 0.0)
            U0_s, Ip1_s, _ = u0_off(iw_, iv_)
            states[(a_, b_)] = (U0_s, Ip1_s, mask)
    U0_w, Ip1_w = (states[(True, False)][:2] if (True, False) in states else (U0_f, Ip1))
    # voltages (fundamental component) – states during the fault, before/after the fault
    U = np.zeros((3, n))
    for x in range(3):
        U[x] += _wave(t, f1, E[x])
        U[x] += (1 - gate) * _wave(t, f1, U0_pre_t)
        for U0_s, _, mask in states.values():
            U[x] += mask * _wave(t, f1, U0_s)
    # decaying neutral displacement voltage after the fault clearance (natural frequency ≈ 48 Hz)
    post = t >= t_off
    tau_off, f_own = 0.15, 48.0
    U0_off = U0_f * np.exp(1j * w1 * t_off)                     # instantaneous phasor at the fault clearance
    decay = np.zeros(n)
    decay[post] = math.sqrt(2) * np.real(U0_off * np.exp(2j * np.pi * f_own * (t[post] - t_off))) \
        * np.exp(-(t[post] - t_off) / tau_off)
    for x in range(3):
        U[x] += decay
    # fault current (orientation I' of the angle method, measured with ``polarity``)
    I_F = sum(mask * _wave(t, f1, Ip1_s) for _, Ip1_s, mask in states.values())
    true_h = {}
    U0_h = {}
    Ish_h = {}
    p_pos, p_neg = (1.0, A2, A)[fl], (1.0, A, A2)[fl]           # phase factors of the faulted phase
    f_pos, f_neg = (1.0, A2, A), (1.0, A, A2)                   # sequence → phase L1, L2, L3
    for h in harmonic_sources:
        m = h.order
        fm = m * f1
        Z1_, Z2_, Us_ = complex(getattr(h, "Z1", 0j)), complex(getattr(h, "Z2", 0j)), complex(getattr(h, "Us", 0j))
        I_ll = (drift * h.Uq + Us_) / (h.Zq + Z_F)               # I'_m referred to L1-L2
        Upre_ll = drift * h.U_pre
        I_t = _rotate_phase(I_ll, m, phi_ll)
        Upre_t = _rotate_phase(Upre_ll, m, phi_ll)
        fac = _seq_factors(m)
        # fault: U_flE,m = Z_F·I_F,m = −Z_F·I'_m ⇒ ΔU0,m = −Z_F·I'_m − U_fl,pre − (Z_1 + Z_2)·I'_m/3
        dU1 = Z1_ * I_ll / (3 * p_pos)
        dU2 = Z2_ * I_ll / (3 * p_neg)
        dU0 = -Z_F * I_ll - Upre_ll * fac[fl] - (Z1_ + Z2_) * I_ll / 3
        U0m_t = _rotate_phase(dU0, m, phi_ll)
        U0_h[m] = U0m_t
        Z0_ = 3 * h.Zq - Z1_ - Z2_
        if fault_source_in_coils and Us_ and Z0_:
            Ish_h[m] = _rotate_phase(3 * Us_ / Z0_, m, phi_ll)          # nonlinear coil current (angle method)
        for x in range(3):
            dUx = U0m_t if not (Z1_ or Z2_) else _rotate_phase(dU0 + f_pos[x] * dU1 + f_neg[x] * dU2, m, phi_ll)
            U[x] += _wave(t, fm, Upre_t * fac[x]) + gate * _wave(t, fm, dUx)
        I_F += gate * _wave(t, fm, I_t)
        true_h[m] = dict(I_ll=I_ll, U_pre_ll=Upre_ll, U0_fault_ll=dU0, Uq=drift * h.Uq, Zq=h.Zq,
                         Z0=3 * h.Zq - Z1_ - Z2_, Z1=Z1_, Z2=Z2_, Us=Us_,
                         sequence={1: "pos", 2: "neg", 0: "zero"}[m % 3])
    if dc_offset:
        amp, tau = dc_offset
        I_F += gate * amp * np.exp(-np.clip(t - t_on, 0, None) / tau)
    if transient:
        after_on = t >= t_on
        I_F[after_on] += (150.0 * math.sqrt(2) * np.exp(-(t[after_on] - t_on) / 0.015)
                          * np.sin(2 * np.pi * 730 * (t[after_on] - t_on)))
        for x in range(3):
            if x != fl:
                U[x][after_on] += (800.0 * np.exp(-(t[after_on] - t_on) / 0.01)
                                   * np.sin(2 * np.pi * 730 * (t[after_on] - t_on) + x))
    # coil currents (neutral point → earth): I_L = U0/(jX_L)
    coils = []
    for k, IL in enumerate(coils_A):
        XL = U_PH / IL
        i = (1 - gate) * _wave(t, f1, U0_pre_t / (1j * XL))
        for (a_, _b), (U0_s, _, mask) in states.items():
            il = U0_s / (1j * XL)
            if a_ and reactive_step and k == 0:    # coil adjustment: coil 1 changes its current by ΔIv
                il = il * (1 + reactive_step[2] / abs(il))
            i += mask * _wave(t, f1, il)
        for h in harmonic_sources:
            i += gate * _wave(t, h.order * f1, U0_h[h.order] / (1j * h.order * XL)
                              + Ish_h.get(h.order, 0j) * IL / sum(coils_A))
        if transient:
            after_on = t >= t_on
            i[after_on] += 0.4 * math.sqrt(2) * IL * np.exp(-(t[after_on] - t_on) / 0.15)       # DC at switch-on
        coils.append(i + _noise(rng, n, noise_I))
    # measured quantities
    U_meas = [U[x] + _noise(rng, n, noise_U) for x in range(3)]
    i_f1 = polarity * I_F + dc_clamp_A + _noise(rng, n, noise_I)
    signals = {}
    if channel_names == "structured":
        nm = dict(u=["u_20kv_l%de_j02_vt_m01_v__raw" % (x + 1) for x in range(3)],
                  i1="i_20kv_res_j01_ct_m01_a__raw", i2="i_20kv_res_j01_rog_m02_a__raw",
                  sp=["i_20kv_coil_esp%d_ct_m01_a__raw" % (21 + k) for k in range(len(coils))])
    else:
        nm = dict(u=["DANEO 1_System 1_V%d Inst" % (x + 1) for x in range(3)],
                  i1="DANEO 1_Ströme_IF1 Inst", i2="DANEO 1_Ströme_IF2 Inst",
                  sp=["DANEO 1_Ströme_ISp%d Inst" % (21 + k) for k in range(len(coils))])
    for x in range(3):
        signals[nm["u"][x]] = ("V", U_meas[x])
    if fault_current:
        signals[nm["i1"]] = ("A", i_f1)
    if second_ct and fault_current:
        g, dphi = second_ct
        # second CT: gain g, phase error dphi (degrees, applied to all orders as a time offset)
        dt = np.deg2rad(dphi) / w1
        i2 = np.interp(t - dt, t, polarity * I_F) * g + _noise(rng, n, noise_I)
        signals[nm["i2"]] = ("A", i2)
    for k, i in enumerate(coils):
        signals[nm["sp"][k]] = ("A", i)
    digital = {"DANEO 1_Trigger": (t >= t_on).astype(int)} if trigger else None
    start = start or _dt.datetime(2026, 1, 15, 9, 0, 0)
    write_comtrade(path, signals, fs, t_start=start, trigger_s=t_on, file_format=file_format,
                      digital=digital)
    # ---------------------------------------------------------------- true values (steady state)
    IG = abs(Ip1)
    IH = math.sqrt(sum(abs(v["I_ll"]) ** 2 for v in true_h.values()))
    U_pre_seq = {m: v["U_pre_ll"] for m, v in true_h.items()}
    # THD of the line-to-line voltages before the fault (U0 cancels out)
    uh_ll = math.sqrt(sum((abs(v) * math.sqrt(3) if m % 3 else 0.0) ** 2 for m, v in U_pre_seq.items()))
    truth = dict(
        file=os.path.basename(path), Z_F=Z_F, fs=fs, f1=f1, theta0_deg=theta0_deg, phi_LL1_deg=np.degrees(phi_ll),
        faulted_phase="L%d" % faulted_phase, polarity=polarity, drift=drift,
        Iw=Iw, Iv=Iv, IG=IG, IH=IH, IRES=math.sqrt(IG ** 2 + IH ** 2),
        IRES_active_step=(math.sqrt(abs(Ip1_w) ** 2 + IH ** 2) if active_step else None),
        IRES_step=(math.sqrt(abs(Ip1_w) ** 2 + IH ** 2) if (active_step or reactive_step) else None),
        IRES_network_step=(math.sqrt(abs(states[(False, True)][1]) ** 2 + IH ** 2)
                           if network_step and (False, True) in states else None),
        U0_fault=abs(U0_f), U0_fault_ll=U0_f * np.exp(-1j * phi_ll),
        UTHD_LL_pre_pct=100 * uh_ll / (U_PH * math.sqrt(3)), UH_LL_pre_V=uh_ll,
        UH5g_pre=abs(U_pre_seq.get(5, 0)), UH7m_pre=abs(U_pre_seq.get(7, 0)),
        coils_H1_A=[abs(U0_f) / (U_PH / IL) for IL in coils_A],
        harmonic_sources={m: dict(I=abs(v["I_ll"]), I_ll=v["I_ll"], U_pre_ll=v["U_pre_ll"], Uq=v["Uq"],
                                  Zq=v["Zq"], Z0=v["Z0"], Z1=v["Z1"], Z2=v["Z2"], Us=v["Us"],
                                  sequence=v["sequence"]) for m, v in true_h.items()},
        intervals=dict(steady_state=(t_on + 0.6, min([x[0] - 0.2 for x in (active_step, reactive_step, network_step)
                                                     if x] + [t_off - 0.2])),
                      pre_fault=(0.2, t_on - 0.2), post_fault=(t_off + 1.0, duration - 0.2)),
    )
    _save_truth(path, truth)
    return truth


def make_substation_series(folder: str, Z_values: Sequence[float] = (0.0, 2.5, 5.0), *,
                      drift: Optional[Dict[float, complex]] = None, theta: Optional[Dict[float, float]] = None,
                      polarities: Optional[Dict[float, int]] = None, prefix: str = "SUB", **kw) -> List[dict]:
    """Series of substation recordings of one campaign (one file per fault resistance) with a common truth.

    The files are named ``<prefix>_<Z>_10_000kHz.cfg`` (e.g. ``SUB_2_5_10_000kHz.cfg`` for 2.5 Ω) and start
    15 min apart.

    Parameters
    ----------
    folder : str
        Target folder (created if necessary).
    Z_values : sequence of float, optional
        Fault resistances in Ω, one recording each.
    drift : dict, optional
        ``{Z: source drift}`` (default: drift in magnitude and phase between the measurements).
    theta : dict, optional
        ``{Z: phase angle at t = 0 in degrees}`` – different time origins of the files.
    polarities : dict, optional
        ``{Z: ±1}`` – polarity of the fault-current measurement.
    prefix : str, optional
        Prefix of the file names (``"SUB"``; e.g. ``"UW"`` for a German campaign).
    **kw
        Further arguments of [`make_substation_recording`][groundfault.demo.make_substation_recording].

    Returns
    -------
    list of dict
        True values per recording (see [`make_substation_recording`][groundfault.demo.make_substation_recording]).
    """
    os.makedirs(folder, exist_ok=True)
    drift = drift or {0.0: 1.0, 2.5: polar(1.10, 10), 5.0: polar(0.95, -8)}
    theta = theta or {0.0: 70.0, 2.5: -32.0, 5.0: 42.0}
    polarities = polarities or {}
    out = []
    for k, Z in enumerate(Z_values):
        name = "%s_%s_10_000kHz.cfg" % (prefix, ("%g" % Z).replace(".", "_"))
        out.append(make_substation_recording(os.path.join(folder, name), Z, drift=drift.get(Z, 1.0),
                                      theta0_deg=theta.get(Z, 30.0 * k), polarity=polarities.get(Z, 1),
                                      seed=k, start=_dt.datetime(2026, 1, 15, 9, 0, 0) + _dt.timedelta(minutes=15 * k),
                                      **kw))
    return out


# =========================================================================== station
def make_station_recording(path: str, *, fs: float = 10000.0, duration: float = 6.0, f1: float = 49.98,
                    theta0_deg: float = -15.0, IG: float = 35.0, I_harm: Optional[Dict[int, complex]] = None,
                    R_E: float = 1.0, X_E1: float = 0.08, r: complex = polar(0.55, -8.0),
                    probes: Dict[str, float] = None, F: float = 2.6, pen_share: float = 0.05,
                    t_on: float = 1.5, t_off: float = 4.5, with_voltages: bool = True,
                    noise_U: float = 0.05, noise_I: float = 0.05, seed: int = 1,
                    background: Optional[Dict[int, complex]] = None, f1_drift_hz_s: float = 0.0,
                    background_post: Optional[Dict[int, complex]] = None,
                    background_fluctuation: float = 0.0, lv_network: Optional[dict] = None,
                    r_per_order: Optional[Dict[int, complex]] = None) -> dict:
    """Write a COMTRADE recording of an earth fault at a secondary substation (MV/LV station) with known solution.

    Recorded are the earth potential rise at the probes, the touch voltage, the fault current, the shield current
    and the PEN current(s), optionally the line-to-earth voltages. True value per order m:
    r·Z_E,m = U_E,m/I_F,m with Z_E,m = R_E + j·m·X_E1; the probe ``UE_70m`` measures the share
    ``probes["UE_70m"]`` of the earth potential.

    Parameters
    ----------
    path : str
        Path of the ``.cfg`` file to write.
    fs : float, optional
        Sampling rate in Hz.
    duration : float, optional
        Duration of the recording in s.
    f1 : float, optional
        Mains frequency in Hz (at t = 0, see ``f1_drift_hz_s``).
    theta0_deg : float, optional
        Phase angle at t = 0 in degrees.
    IG : float, optional
        Fundamental component of the fault current in A (Iw:Iv = 3:1 in the orientation of the angle method).
    I_harm : dict, optional
        ``{order: phasor in A}`` – harmonics of the fault current.
    R_E, X_E1 : float, optional
        Earthing impedance Z_E,m = R_E + j·m·X_E1 in Ω.
    r : complex, optional
        Reduction factor (all orders unless ``r_per_order`` is given).
    probes : dict, optional
        ``{probe channel: share of the earth potential}``, default ``{"UE_5m": 0.60, "UE_70m": 0.93}``.
    F : float, optional
        Ratio of the earth potential rise at the largest probe to the touch voltage (channel ``UT``).
    pen_share : float, optional
        PEN current as a share of the fault current (simple channel ``IPEN``, without ``lv_network``).
    t_on, t_off : float, optional
        Fault inception and fault clearance in s.
    with_voltages : bool, optional
        Record the three line-to-earth voltages as well.
    noise_U, noise_I : float, optional
        Standard deviation of the noise of the probe voltages (V) and of the currents (A).
    seed : int, optional
        Seed of the random generator.
    background : dict, optional
        ``{order: phasor in V}`` – earth potential already present before the fault (currents from the LV
        network), synchronous with the mains and present during the whole recording.
    f1_drift_hz_s : float, optional
        Linear change of the mains frequency in Hz/s (all signals follow the same mains phase
        θ(t) = 2π·∫f dt).
    background_post : dict, optional
        Different background level from the fault clearance on (e.g. a load change in the LV network during the
        fault) – then the superposition methods at the fault inception and at the fault clearance contradict each
        other.
    background_fluctuation : float, optional
        Relative slow fluctuation of the background level in magnitude and phase (RMS value, e.g. 0.1 = 10 %;
        time constant 1 s) as at real stations.
    lv_network : dict, optional
        Physical model of the LV network instead of the simple PEN channel (see the notes).
    r_per_order : dict, optional
        ``{order: reduction factor}`` (otherwise ``r`` for all orders).

    Returns
    -------
    dict
        True values (also saved as ``<stem>_truth.json``): r·Z_E, Z_E, I_F (and the LV network quantities)
        per order (``orders``), RMS values, ``V_per_100A``, the LV network model and recommended analysis
        intervals.

    Raises
    ------
    ValueError
        If |Z_LV| is not larger than |Z_E| (parallel connection).

    Notes
    -----
    ``lv_network`` replaces the simple PEN channel (``pen_share``) by a physical model: the total earthing
    Z_E,m = R_E + j·m·X_E1 is the parallel connection of the station earth electrode and the LV network
    Z_LV,m = ``R_LV`` + j·m·``X_LV1``; the current into the LV network is I_LV = Z_E·I_E/Z_LV (I_E = r·I_F). It
    is measured at two points: ``IPEN_v`` (LV feeders, counting direction towards the LV network) =
    load_feeders + I_LV and ``IPEN_n`` (to the main earthing busbar, counting direction from the transformer star
    point to the busbar) = load_busbar − I_LV. The load unbalance (``load_feeders``, ``load_busbar``: phasors per
    order, synchronous with the mains, ``load_fluctuation`` relative) is always present; the transformer star
    point carries load_feeders + load_busbar. ``position``: ``"both"`` (both channels), ``"feeders"`` or
    ``"busbar"``; ``sign_busbar``: −1 = clamp n applied the wrong way round; ``factor_feeders``: ratio error of
    clamp v (e.g. 10 → implausibly large current into the LV network).
    """
    rng = np.random.default_rng(seed)
    n = int(round(duration * fs)); t = np.arange(n) / fs
    th = np.deg2rad(theta0_deg)
    theta = 2 * np.pi * (f1 * t + 0.5 * f1_drift_hz_s * t ** 2)       # mains phase

    def wave(m: int, X: complex) -> np.ndarray:
        return math.sqrt(2.0) * np.real(X * np.exp(1j * m * theta))
    probes = probes or {"UE_5m": 0.60, "UE_70m": 0.93}
    I_harm = I_harm or {5: polar(30.0, 35.0), 7: polar(6.0, -20.0), 11: polar(4.0, 50.0)}
    gate = ((t >= t_on) & (t < t_off)).astype(float)
    E = U_PH * np.exp(1j * th) * np.array([1, A2, A])
    U0 = -E[2]
    I1 = IG * np.exp(1j * (np.angle(U0) - np.arctan2(10.0, 30.0)))     # Iw:Iv = 3:1 (orientation of the angle method)
    ordn = {1: I1}
    ordn.update({m: v * np.exp(1j * m * th) for m, v in I_harm.items()})
    i_f = np.zeros(n); u_epr = np.zeros(n); i_s = np.zeros(n)
    true_m = {}
    lv = dict(R_LV=4.0, X_LV1=0.4, load_feeders={1: polar(18.0, -30.0), 3: polar(9.0, 40.0)},
              load_busbar={1: polar(4.0, -20.0), 3: polar(2.5, 60.0)}, load_fluctuation=0.0, position="both", sign_busbar=1,
              factor_feeders=1.0)
    lv.update(lv_network or {})
    i_lv = np.zeros(n)
    for m, I in ordn.items():
        ZE = R_E + 1j * m * X_E1
        r_m = (r_per_order or {}).get(m, r)
        UE = r_m * ZE * I
        i_f += gate * wave(m, I)
        u_epr += gate * wave(m, UE)
        i_s += gate * wave(m, (1 - r_m) * I)
        true_m[m] = dict(I_F=abs(I), rZE=r_m * ZE, U_E_full=abs(UE), r=r_m, ZE=ZE)
        if lv_network is not None:
            Z_LV = lv["R_LV"] + 1j * m * lv["X_LV1"]
            if abs(Z_LV) <= abs(ZE):
                raise ValueError(tr("demo.lv_network_impedance"))
            I_LV = UE / Z_LV
            i_lv += gate * wave(m, I_LV)
            true_m[m].update(Z_LV=Z_LV, I_LV=I_LV, k_LV=I_LV / I, I_E=r_m * I)
    post = (t >= t_off).astype(float) if background_post is not None else np.zeros(n)
    for m, B in (background or {}).items():
        if background_fluctuation:
            B = B * (1.0 + background_fluctuation * _fluctuation(np.random.default_rng(seed + 100 + m), t))
        u_epr += (1.0 - post) * wave(m, B * np.exp(1j * m * th))
    for m, B in (background_post or {}).items():
        u_epr += post * wave(m, B * np.exp(1j * m * th))
    signals = {}
    for nm, share in probes.items():
        signals["DANEO 1_Spannungen_%s Inst" % nm] = ("V", share * u_epr + _noise(rng, n, noise_U))
    signals["DANEO 1_Spannungen_UT Inst"] = ("V", max(probes.values()) * u_epr / F + _noise(rng, n, noise_U))
    if with_voltages:
        for x in range(3):
            u = wave(1, E[x]) + gate * wave(1, U0)
            signals["DANEO 1_Spannungen_V%d Inst" % (x + 1)] = ("V", u + _noise(rng, n, 3.0))
    signals["DANEO 1_Ströme_IF1 Inst"] = ("A", i_f + 0.8 + _noise(rng, n, noise_I))
    signals["DANEO 1_Ströme_IS Inst"] = ("A", i_s + _noise(rng, n, noise_I))
    if lv_network is None:
        signals["DANEO 1_Ströme_IPEN Inst"] = ("A", pen_share * i_f + _noise(rng, n, noise_I))
    else:
        def last(ls: Dict[int, complex], s0: int) -> np.ndarray:
            x = np.zeros(n)
            for m, B in ls.items():
                if lv["load_fluctuation"]:
                    B = B * (1.0 + lv["load_fluctuation"] * _fluctuation(np.random.default_rng(seed + s0 + m), t))
                x += wave(m, B * np.exp(1j * m * th))
            return x
        pos = {"vn": "both", "v": "feeders", "n": "busbar"}.get(lv["position"], lv["position"])
        if pos in ("both", "feeders"):
            signals["DANEO 1_Ströme_IPEN_v Inst"] = ("A", lv["factor_feeders"] * (last(lv["load_feeders"], 300) + i_lv)
                                                     + _noise(rng, n, noise_I))
        if pos in ("both", "busbar"):
            signals["DANEO 1_Ströme_IPEN_n Inst"] = ("A", lv["sign_busbar"] * (last(lv["load_busbar"], 400) - i_lv)
                                                     + _noise(rng, n, noise_I))
    write_comtrade(path, signals, fs, t_start=_dt.datetime(2026, 1, 15, 11, 0, 0), trigger_s=t_on)
    I_rms = math.sqrt(sum(abs(I) ** 2 for I in ordn.values()))
    UE_rms = math.sqrt(sum(abs(true_m[m]["rZE"] * I) ** 2 for m, I in ordn.items()))
    truth = dict(file=os.path.basename(path), f1=f1, f1_drift_hz_s=f1_drift_hz_s, IF_rms=I_rms, UE_full_rms=UE_rms,
                background={m: B for m, B in (background or {}).items()}, t_on=t_on, t_off=t_off,
                probes=probes, F=F, r=r, R_E=R_E, X_E1=X_E1,
                UE_70m_rms=probes.get("UE_70m", 1.0) * UE_rms, UT_rms=max(probes.values()) * UE_rms / F,
                V_per_100A=100 * probes.get("UE_70m", 1.0) * UE_rms / I_rms,
                orders={m: dict(I_F=v["I_F"], rZE=v["rZE"], rZE_probe=v["rZE"] * probes.get("UE_70m", 1.0),
                                   r=v["r"], ZE=v["ZE"], ZE_probe=v["ZE"] * probes.get("UE_70m", 1.0),
                                   **({"Z_LV": v["Z_LV"], "Z_LV_probe": v["Z_LV"] * probes.get("UE_70m", 1.0),
                                       "I_LV": v["I_LV"], "k_LV": v["k_LV"], "I_E": v["I_E"]} if "Z_LV" in v else {}))
                           for m, v in true_m.items()},
                lv_network=(dict(lv, load_feeders=lv["load_feeders"], load_busbar=lv["load_busbar"]) if lv_network is not None else None),
                intervals=dict(steady_state=(t_on + 0.5, t_off - 0.2), pre_fault=(0.2, t_on - 0.2),
                              post_fault=(t_off + 0.3, duration - 0.2)))
    _save_truth(path, truth)
    return truth


# =========================================================================== transformer
def make_transformer_recording(path: str, *, fs: float = 10000.0, duration: float = 6.0, f1: float = 50.0,
                  theta0_deg: float = 25.0, S1: complex = complex(8e6, 2e6),
                  S_harm: Optional[Dict[int, complex]] = None,
                  U_harm: Optional[Dict[int, complex]] = None, with_fault: bool = True,
                  I_coil: float = 300.0, t_on: float = 1.5, t_off: float = 4.5, hv: bool = True,
                  seed: int = 2, Z_transformer: complex = complex(0.05, 1.8), Z_hv: complex = complex(0.03, 0.12),
                  Iw: float = 20.0, Iv: float = 5.0, fault_harmonics: Optional[Dict[int, complex]] = None,
                  share: complex = complex(0.9, 0.0), generator_reference: bool = False,
                  active_step: Optional[Tuple[float, float, float]] = None,
                  coil_at_transformer: bool = True) -> dict:
    """Write a COMTRADE recording of a transformer measurement (MV line currents of the transformer, MV busbar and HV
    voltages, coil current) with known solution.

    Model (per order m, symmetrical components referred to U_L1-L2, consumer reference arrow system of the MV
    network):

    * Before and after the fault: busbar voltage ``U_harm`` and power ``S_harm`` per order in the natural sequence of
      the order (fundamental: load power ``S1``, positive sequence).
    * Upstream impedance (transformer and HV network seen from the MV busbar) Z_up(m) = Z_T(m) + Z_HV(m) with
      Z(m) = R + j·m·X from ``Z_transformer`` and ``Z_hv`` (values at the fundamental): the busbar voltage is
      U = U_bg − Z_up·I.
    * Fault in L3 at the busbar: fault current I_F,m (fundamental from ``Iw``, ``Iv`` relative to the voltage of the
      faulted phase; harmonics ``fault_harmonics`` referred to U_L1-L2), at the fault location I_1 = a²·I_F/3,
      I_2 = a·I_F/3. The transformer carries ``share``·I_1 and ``share``·I_2 additionally, the busbar voltage changes
      by ΔU_s = −Z_up·ΔI_s, and U0,m = −(a·U_1,m + a²·U_2,m) (U_L3E = 0). With ``coil_at_transformer`` the
      transformer also carries the coil current/3 in the zero sequence (fundamental).
    * ``active_step = (t_from, t_to, ΔIw)``: active residual current increase (fault current + ΔIw in phase with the
      voltage of the faulted phase).
    * HV voltages: U_HV = t_s·(U + Z_T·I) with the ratio 110 kV/20 kV and the phase shift of vector group 5
      (positive sequence +150°, negative sequence −150°).
    * ``generator_reference``: the currents are recorded reversed (generator reference arrow system).

    Parameters
    ----------
    path : str
        Path of the ``.cfg`` file to write.
    fs : float, optional
        Sampling rate in Hz.
    duration : float, optional
        Duration of the recording in s.
    f1 : float, optional
        Mains frequency in Hz.
    theta0_deg : float, optional
        Phase angle at t = 0 in degrees.
    S1 : complex, optional
        Complex power of the fundamental component in VA (three lines, before the fault).
    S_harm : dict, optional
        ``{order: complex power in VA}`` of the harmonics before the fault.
    U_harm : dict, optional
        ``{order: sequence voltage (line-to-earth) in V, referred to L1-L2}`` of the harmonics before the fault.
    with_fault : bool, optional
        Earth fault between ``t_on`` and ``t_off``.
    I_coil : float, optional
        Coil current in A at full displacement voltage (channel ``ISp22``).
    t_on, t_off : float, optional
        Fault inception and fault clearance in s.
    hv : bool, optional
        Record the HV line-to-earth voltages as well.
    seed : int, optional
        Seed of the random generator (noise).
    Z_transformer, Z_hv : complex, optional
        Impedance of the transformer and of the HV network (referred to the MV side) at the fundamental in Ω.
    Iw, Iv : float, optional
        Active and reactive residual current of the fault in A (Iv > 0: over-compensated).
    fault_harmonics : dict, optional
        ``{order: fault current in A, referred to L1-L2}`` of the harmonics.
    share : complex, optional
        Share of the positive- and negative-sequence fault current that flows through the transformer.
    generator_reference : bool, optional
        Record the currents in the generator reference arrow system (reversed).
    active_step : tuple, optional
        ``(t_from, t_to, ΔIw)`` – active residual current increase.
    coil_at_transformer : bool, optional
        The coil is connected to the star point of this transformer (zero-sequence current in its lines).

    Returns
    -------
    dict
        True values (also saved as ``<stem>_truth.json``): ``S`` (``P_kW``, ``Q_kvar`` per order before the fault),
        ``S_fault`` (the same during the undisturbed fault), ``dP1_fault_kW``, ``dQ1_fault_kvar``, the upstream
        impedance ``Z_up`` and its parts ``Z_transformer`` and ``Z_hv`` per order (``re``, ``im``), ``X1_up``,
        ``X1_transformer``, ``X1_hv`` (reactances at the fundamental), ``sign`` (+1, −1 with
        ``generator_reference``), the zero-sequence current and the coil current during the fault, ``active_step``
        and recommended analysis intervals.
    """
    rng = np.random.default_rng(seed)
    n = int(round(duration * fs)); t = np.arange(n) / fs
    th = np.deg2rad(theta0_deg)
    S_harm = S_harm or {5: complex(-4e3, 9e3), 7: complex(2e3, -3e3), 11: complex(-1e3, 1.5e3)}
    U_harm = U_harm or {5: polar(180, -20), 7: polar(90, 40), 11: polar(30, 75)}
    fault_harmonics = fault_harmonics if fault_harmonics is not None else {5: polar(9.0, 95), 7: polar(4.0, 80),
                                                                           11: polar(1.5, 60)}
    gate = ((t >= t_on) & (t < t_off)).astype(float) if with_fault else np.zeros(n)
    gate_a = np.zeros(n)
    if active_step is not None and with_fault:
        gate_a = ((t >= max(active_step[0], t_on)) & (t < min(active_step[1], t_off))).astype(float)
    E = U_PH * np.exp(1j * th) * np.array([1, A2, A])                 # source voltages in the file's time origin
    phi_ll = float(np.angle(E[0] - E[1]))
    E_ref = E * np.exp(-1j * phi_ll)                                  # … referred to U_L1-L2 (fundamental)
    sgn = -1.0 if generator_reference else 1.0
    kpos, kneg = A2, A                                                 # fault in L3: I_1 = a²·I_F/3, I_2 = a·I_F/3

    def z_at(Z: complex, m: int) -> complex:
        return complex(Z.real, m * Z.imag)

    # ---- phasors per order and state (referred to U_L1-L2): sequences (0, 1, 2) of U and I
    orders = sorted({1} | set(S_harm) | set(fault_harmonics))
    pre = {}
    for m in orders:
        U = np.zeros(3, complex); I = np.zeros(3, complex)
        if m == 1:
            U[1] = E_ref[0]
            I[1] = np.conj(S1 / (3 * U[1]))
        elif m in S_harm:
            q = m % 3
            U[q] = U_harm[m]
            I[q] = np.conj(S_harm[m] / (3 * U_harm[m]))
        pre[m] = (U, I)
    E3 = E_ref[2]
    I_F = {1: (Iw - 1j * Iv) * E3 / abs(E3)}
    I_F.update({m: complex(v) for m, v in fault_harmonics.items()})
    dIw = {1: (active_step[2] if active_step else 0.0) * E3 / abs(E3)}

    def fault_state(m: int, extra: complex = 0.0):
        U, I = (x.copy() for x in pre[m])
        iF = I_F.get(m, 0.0) + extra
        dI = np.array([0.0, share * kpos * iF / 3.0, share * kneg * iF / 3.0], complex)
        Zu = z_at(Z_transformer, m) + z_at(Z_hv, m)
        U = U + np.array([0.0, -Zu * dI[1], -Zu * dI[2]])
        I = I + dI
        U[0] = -(A * U[1] + A2 * U[2])                                 # U_L3E = 0 (bolted fault at the busbar)
        if m == 1 and coil_at_transformer:
            I[0] = U[0] / (1j * U_PH / I_coil) / 3.0
        return U, I

    fault = {m: fault_state(m) for m in orders}
    step = {m: fault_state(m, dIw[1] if m == 1 else 0.0) for m in orders}
    # ---- waveforms: pre-fault + gate·(fault − pre) + gate_a·(step − fault)
    seq_phase = np.array([[1, 1, 1], [1, A2, A], [1, A, A2]])          # rows: sequence 0, 1, 2; columns: L1…L3

    def phases(x):
        return x @ seq_phase                                           # sequences → phases

    U_w = [np.zeros(n) for _ in range(3)]; I_w = [np.zeros(n) for _ in range(3)]
    Uhv_w = [np.zeros(n) for _ in range(3)]
    ratio = 110000.0 / 20000.0
    fac = {0: 0.0, 1: ratio * np.exp(1j * np.deg2rad(150.0)), 2: ratio * np.exp(-1j * np.deg2rad(150.0))}
    for m in orders:
        Zt = z_at(Z_transformer, m)
        states = [(pre[m], np.ones(n)), ((fault[m][0] - pre[m][0], fault[m][1] - pre[m][1]), gate),
                  ((step[m][0] - fault[m][0], step[m][1] - fault[m][1]), gate_a)]
        for (U, I), g in states:
            Uph = phases(U); Iph = phases(I)
            Uhv = phases(np.array([fac[q] * (U[q] + Zt * I[q]) for q in range(3)]))
            for x in range(3):
                rot = np.exp(1j * m * phi_ll)
                U_w[x] += g * _wave(t, m * f1, Uph[x] * rot)
                I_w[x] += g * _wave(t, m * f1, Iph[x] * rot)
                Uhv_w[x] += g * _wave(t, m * f1, Uhv[x] * rot)
    signals = {}
    for x in range(3):
        signals["DANEO 1_System 1_V%d Inst" % (x + 1)] = ("V", U_w[x] + _noise(rng, n, 3.0))
    for x in range(3):
        signals["DANEO 1_System 2_I%d Inst" % (x + 1)] = ("A", sgn * I_w[x] + _noise(rng, n, 0.05))
    if hv:
        for x in range(3):
            signals["DANEO 1_System 3_V%dHS Inst" % (x + 1)] = ("V", Uhv_w[x] + _noise(rng, n, 20.0))
    U0f = fault[1][0][0] * np.exp(1j * phi_ll)
    coil_w = gate * _wave(t, f1, U0f / (1j * U_PH / I_coil))
    signals["DANEO 1_Ströme_ISp22 Inst"] = ("A", coil_w + _noise(rng, n, 0.05))
    write_comtrade(path, signals, fs, t_start=_dt.datetime(2026, 1, 15, 10, 0, 0), trigger_s=t_on)

    def power(st, m):
        U, I = st[m]
        return complex(np.sum(phases(U) * np.conj(phases(I))))
    z_up = {m: z_at(Z_transformer, m) + z_at(Z_hv, m) for m in orders}
    S_pre = {m: power(pre, m) for m in orders}
    S_fault = {m: power(fault, m) for m in orders}
    cx = lambda z: dict(re=float(np.real(z)), im=float(np.imag(z)))
    truth = dict(file=os.path.basename(path), f1=f1,
                S={m: dict(P_kW=s.real / 1e3, Q_kvar=s.imag / 1e3) for m, s in S_pre.items()},
                S_fault={m: dict(P_kW=s.real / 1e3, Q_kvar=s.imag / 1e3) for m, s in S_fault.items()},
                dP1_fault_kW=(S_fault[1] - S_pre[1]).real / 1e3, dQ1_fault_kvar=(S_fault[1] - S_pre[1]).imag / 1e3,
                Z_up={m: cx(z) for m, z in z_up.items()},
                Z_transformer={m: cx(z_at(Z_transformer, m)) for m in orders},
                Z_hv={m: cx(z_at(Z_hv, m)) for m in orders},
                X1_up=float(Z_transformer.imag + Z_hv.imag), X1_transformer=float(Z_transformer.imag),
                X1_hv=float(Z_hv.imag), sign=-1 if generator_reference else 1,
                I_zero_fault_A=float(abs(fault[1][1][0])), I_coil_A=float(abs(U0f) / (U_PH / I_coil)),
                active_step=list(active_step) if active_step else None,
                intervals=dict(steady_state=(t_on + 0.5, t_off - 0.2), pre_fault=(0.2, t_on - 0.2),
                              post_fault=(t_off + 0.3, duration - 0.2)))
    _save_truth(path, truth)
    return truth


def make_undisturbed_transformer_recording(path: str, *, fs: float = 10000.0, duration: float = 60.0,
                                           f1: float = 50.0, theta0_deg: float = 25.0,
                                           Z_mv: Optional[Dict[int, complex]] = None,
                                           Z_transformer: complex = complex(0.05, 1.8),
                                           Z_hv: complex = complex(0.03, 0.12),
                                           E_hv: Optional[Dict[int, Tuple[complex, complex]]] = None,
                                           J_mv: Optional[Dict[int, Tuple[complex, complex]]] = None,
                                           hv_fluctuation: float = 0.08, mv_fluctuation: float = 0.08,
                                           tau: float = 0.3, generator_reference: bool = False,
                                           ct_angle_deg=None, reference_clamp: bool = False,
                                           start: Optional[_dt.datetime] = None, seed: int = 5) -> dict:
    """Write a COMTRADE recording of a transformer node in undisturbed operation (no earth fault): MV line currents
    of the transformer, MV busbar and HV voltages, with harmonic sources on both sides that fluctuate independently.

    Model per order m and sequence (positive, negative; MV side, consumer reference arrow system of the MV network):
    the HV network is a source E(t) behind the upstream impedance Z_up(m) = Z_T(m) + Z_HV(m) (Z(m) = R + j·m·X from the
    values at the fundamental), the MV network an impedance ``Z_mv`` (the quantity to identify) parallel to a current
    source J(t) (its harmonic sources):

        U = (E/Z_up + J) / (1/Z_up + 1/Z_mv),   I = (E − U)/Z_up (from the HV into the MV network),
        U_HV = t_s·(U + Z_T·I)

    with t_s the ratio 110 kV/20 kV and the phase shift of vector group 5 (positive sequence +150°, negative −150°).
    E and J vary as E₀·(1 + ``hv_fluctuation``·ξ_E(t)) and J₀·(1 + ``mv_fluctuation``·ξ_J(t)) with independent smooth
    random processes ξ (time constant ``tau``). Then ΔU = Z_mv·ΔI for the HV-driven part of the variation and
    ΔU = −Z_up·ΔI for the MV-driven part.

    Parameters
    ----------
    path : str
        Path of the ``.cfg`` file to write.
    fs, duration, f1, theta0_deg : float, optional
        Sampling rate in Hz, duration in s, mains frequency in Hz, phase angle at t = 0 in degrees.
    Z_mv : dict, optional
        ``{order: impedance of the MV network in Ω}`` (positive and negative sequence alike).
    Z_transformer, Z_hv : complex, optional
        Impedance of the transformer and of the HV network (referred to the MV side) at the fundamental in Ω.
    E_hv, J_mv : dict, optional
        ``{order: (positive, negative sequence)}`` – HV source voltage in V and MV source current in A (mean values).
    hv_fluctuation, mv_fluctuation : float, optional
        Relative RMS fluctuation of the HV and MV sources.
    tau : float, optional
        Time constant of the fluctuations in s.
    generator_reference : bool, optional
        Record the currents reversed (generator reference arrow system).
    ct_angle_deg : float or dict, optional
        Angle error of the current transformers of the transformer currents in degrees (phase of the recorded minus
        phase of the true current): one value for all harmonic orders or ``{order: angle}`` (order 1 for the
        fundamental). None: no angle error.
    reference_clamp : bool, optional
        Add a reference current clamp on L1 without angle error (channel ``IRef``, same orientation as the
        transformer current channels) – for [`ct_angle_from_reference`][groundfault.transformer.ct_angle_from_reference].
    start : datetime.datetime, optional
        Start time of the recording (default 15 January 2026, 11:00).
    seed : int, optional
        Seed of the random generator.

    Returns
    -------
    dict
        True values (also saved as ``<stem>_truth.json``): ``Z_mv`` and ``Z_up`` per order (``re``, ``im``),
        ``hv_share`` per order and sequence (``pos``, ``neg``: share of the HV-driven variation in the variance of the
        busbar voltage, from the fluctuation settings), ``ct_angle_deg`` per order and ``sign`` (+1, −1 with
        ``generator_reference``).
    """
    rng = np.random.default_rng(seed)
    n = int(round(duration * fs)); t = np.arange(n) / fs
    th = np.deg2rad(theta0_deg)
    Z_mv = Z_mv or {5: polar(8.0, -55.0), 7: polar(6.0, -40.0)}
    E_hv = E_hv or {5: (polar(8.0, 30.0), polar(60.0, -10.0)), 7: (polar(25.0, 70.0), polar(4.0, 20.0))}
    J_mv = J_mv or {5: (polar(1.0, 120.0), polar(6.0, 100.0)), 7: (polar(3.0, -80.0), polar(0.5, 60.0))}

    def z_at(Z: complex, m: int) -> complex:
        return complex(Z.real, m * Z.imag)

    if isinstance(ct_angle_deg, dict):
        ct = {int(m): float(a) for m, a in ct_angle_deg.items()}
    else:
        ct = {m: float(ct_angle_deg or 0.0) for m in Z_mv}
    ct_rot = lambda m: np.exp(1j * np.deg2rad(ct.get(m, 0.0)))
    ref_w = np.zeros(n)
    hv_share = {}
    ratio = 110000.0 / 20000.0
    fac = {1: ratio * np.exp(1j * np.deg2rad(150.0)), 2: ratio * np.exp(-1j * np.deg2rad(150.0))}
    seq_phase = {1: np.array([1, A2, A]), 2: np.array([1, A, A2])}
    U_w = [np.zeros(n) for _ in range(3)]; I_w = [np.zeros(n) for _ in range(3)]; H_w = [np.zeros(n) for _ in range(3)]
    # fundamental: positive sequence, load current (HV → MV)
    U1 = U_PH * np.exp(1j * th)
    I1 = np.conj(complex(8e6, 2e6) / (3 * U1))
    for x in range(3):
        p = seq_phase[1][x]
        U_w[x] += _wave(t, f1, U1 * p)
        I_w[x] += _wave(t, f1, I1 * ct_rot(1) * p)
        H_w[x] += _wave(t, f1, fac[1] * (U1 + z_at(Z_transformer, 1) * I1) * p)
    ref_w += _wave(t, f1, I1)
    k = 0
    for m in sorted(Z_mv):
        Zup = z_at(Z_transformer, m) + z_at(Z_hv, m)
        Zt = z_at(Z_transformer, m)
        Y = 1.0 / Zup + 1.0 / Z_mv[m]
        hv_share[m] = {}
        for s in (1, 2):
            var_h = abs(Z_mv[m] / (Zup + Z_mv[m]) * E_hv[m][s - 1] * hv_fluctuation) ** 2
            var_m = abs(J_mv[m][s - 1] * mv_fluctuation / Y) ** 2
            hv_share[m]["pos" if s == 1 else "neg"] = float(var_h / (var_h + var_m)) if var_h + var_m > 0 else 0.0
            k += 1
            E = E_hv[m][s - 1] * (1.0 + hv_fluctuation * _fluctuation(np.random.default_rng(seed + 10 * k), t, tau))
            J = J_mv[m][s - 1] * (1.0 + mv_fluctuation * _fluctuation(np.random.default_rng(seed + 10 * k + 5), t, tau))
            U = (E / Zup + J) / Y
            I = (E - U) / Zup
            H = fac[s] * (U + Zt * I)
            carrier = np.exp(2j * np.pi * m * f1 * t + 1j * m * th)
            for x in range(3):
                p = seq_phase[s][x]
                U_w[x] += math.sqrt(2.0) * np.real(U * p * carrier)
                I_w[x] += math.sqrt(2.0) * np.real(I * ct_rot(m) * p * carrier)
                H_w[x] += math.sqrt(2.0) * np.real(H * p * carrier)
            ref_w += math.sqrt(2.0) * np.real(I * carrier)
    sgn = -1.0 if generator_reference else 1.0
    signals = {}
    for x in range(3):
        signals["DANEO 1_System 1_V%d Inst" % (x + 1)] = ("V", U_w[x] + _noise(rng, n, 1.0))
    for x in range(3):
        signals["DANEO 1_System 2_I%d Inst" % (x + 1)] = ("A", sgn * I_w[x] + _noise(rng, n, 0.02))
    for x in range(3):
        signals["DANEO 1_System 3_V%dHS Inst" % (x + 1)] = ("V", H_w[x] + _noise(rng, n, 5.0))
    if reference_clamp:
        signals["DANEO 1_System 4_IRef Inst"] = ("A", sgn * ref_w + _noise(rng, n, 0.02))
    write_comtrade(path, signals, fs, t_start=start or _dt.datetime(2026, 1, 15, 11, 0, 0), trigger_s=0.0)
    cx = lambda z: dict(re=float(np.real(z)), im=float(np.imag(z)))
    truth = dict(file=os.path.basename(path), f1=f1, Z_mv={m: cx(z) for m, z in Z_mv.items()},
                 Z_up={m: cx(z_at(Z_transformer, m) + z_at(Z_hv, m)) for m in Z_mv},
                 hv_share=hv_share, ct_angle_deg={m: ct.get(m, 0.0) for m in [1] + sorted(Z_mv)},
                 sign=-1 if generator_reference else 1)
    _save_truth(path, truth)
    return truth


# =========================================================================== RMS file (10 Hz)
def rms_file_from_instantaneous(cfg_inst: str, cfg_rms: str, window_s: float = 0.1) -> str:
    """Write an RMS recording computed from an instantaneous-value recording (like the ``… RMS`` exports of DANEO
    recorders, 10 Hz).

    Parameters
    ----------
    cfg_inst : str
        ``.cfg`` file of the instantaneous-value recording.
    cfg_rms : str
        ``.cfg`` file of the RMS recording to write; the channel names get the suffix ``RMS`` instead of
        ``Inst``.
    window_s : float, optional
        RMS window in s (non-overlapping, DC removed by the mean); the RMS recording has the rate 1/window_s.

    Returns
    -------
    str
        ``cfg_rms``.
    """
    from .comtrade import open_recording
    with open_recording(cfg_inst, emit_warnings=False) as rec:
        t, rms = rec.rms_trend(window_s=window_s, dc="mean")
        names = [nm.replace(" Inst", " RMS") for nm in rec.channel_names]
        signals = {nm: (eh, rms[:, j]) for j, (nm, eh) in enumerate(zip(names, rec.units))}
        write_comtrade(cfg_rms, signals, 1.0 / window_s, t_start=rec.t_start,
                          trigger_s=rec.trigger_s or 0.0, timemult=1.0)
    return cfg_rms


# =========================================================================== groundmeas database
GROUNDMEAS_SCHEMA = (
    """CREATE TABLE location (id INTEGER NOT NULL, name VARCHAR NOT NULL, latitude FLOAT, longitude FLOAT,
       altitude FLOAT, PRIMARY KEY (id))""",
    """CREATE TABLE measurement (id INTEGER NOT NULL, timestamp DATETIME NOT NULL, location_id INTEGER,
       method VARCHAR NOT NULL, voltage_level_kv FLOAT, asset_type VARCHAR NOT NULL, fault_resistance_ohm FLOAT,
       operator VARCHAR, description VARCHAR, PRIMARY KEY (id), FOREIGN KEY(location_id) REFERENCES location (id))""",
    """CREATE TABLE measurementitem (id INTEGER NOT NULL, measurement_type VARCHAR NOT NULL, value FLOAT,
       value_real FLOAT, value_imag FLOAT, value_angle_deg FLOAT, unit VARCHAR NOT NULL, description VARCHAR,
       frequency_hz FLOAT, additional_resistance_ohm FLOAT, input_impedance_ohm FLOAT, measurement_distance_m FLOAT,
       distance_to_current_injection_m FLOAT, measurement_id INTEGER, PRIMARY KEY (id),
       FOREIGN KEY(measurement_id) REFERENCES measurement (id))""",
)
"""Tables of a groundmeas database (SQLModel schema of groundmeas 1.x) as far as groundfault reads and writes them."""


def make_groundmeas_db(path: str, location: str = "Station Elm Road", *, R_E: float = 1.0, X_E1: float = 0.08,
                       orders: Sequence[int] = (1, 3, 5, 7, 11), probe_m: float = 70.0, probe_share: float = 0.93,
                       touch_share: Optional[float] = 0.35, current_A: float = 10.0, factor: float = 1.0,
                       latitude: float = 51.1, longitude: float = 10.2, voltage_level_kv: float = 20.0,
                       timestamp: str = "2026-01-10 10:00:00") -> str:
    """Write a small groundmeas database with one earthing measurement (current injection) of a station.

    The measurement matches [`make_station_recording`][groundfault.demo.make_station_recording] with the same
    ``R_E``/``X_E1``: per order m the test current ``current_A`` and the earthing impedance at the probe
    ``probe_share``·Z_E,m (Z_E,m = R_E + j·m·X_E1) at ``probe_m`` (default: the probe ``UE_70m`` of the station demo),
    optionally the impedance at the 1-m probe (``touch_share``·Z_E,m). The reduction factor of the fault test against
    this measurement is then the ``r`` of the station recording. ``factor`` scales the measured impedances (e.g. 10 = a
    measurement ten times too high).

    Parameters
    ----------
    path : str
        Database file to create (an existing file is replaced).
    location : str, optional
        Name of the location in the database.
    R_E, X_E1 : float, optional
        Earthing impedance Z_E,m = R_E + j·m·X_E1 in Ω.
    orders : sequence of int, optional
        Harmonic orders of the injection frequencies (50·m Hz).
    probe_m, probe_share : float, optional
        Distance of the remote probe in m and share of the earth potential it measures.
    touch_share : float or None, optional
        Share of the earth potential at a probe at 1 m (touch voltage); None: no 1-m probe.
    current_A : float, optional
        Test current in A.
    factor : float, optional
        Factor applied to all measured impedances.
    latitude, longitude : float, optional
        Coordinates of the location (invented).
    voltage_level_kv : float, optional
        Voltage level of the measurement in kV.
    timestamp : str, optional
        Time of the measurement (UTC).

    Returns
    -------
    str
        ``path``.
    """
    import sqlite3
    if os.path.exists(path):
        os.remove(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    con = sqlite3.connect(path)
    try:
        for ddl in GROUNDMEAS_SCHEMA:
            con.execute(ddl)
        con.execute("insert into location (id, name, latitude, longitude) values (1, ?, ?, ?)",
                    (location, latitude, longitude))
        con.execute("insert into measurement (id, timestamp, location_id, method, voltage_level_kv, asset_type, "
                    "operator, description) values (1, ?, 1, 'injection_earth_electrode', ?, 'mv_lv_earthing_system', "
                    "'Demo Grid GmbH', 'Synthetic earthing measurement (groundfault demo)')",
                    (timestamp, voltage_level_kv))
        items = []
        for m in orders:
            f = 50.0 * m
            ze = complex(R_E, m * X_E1) * factor
            items.append(("earthing_current", current_A, 0.0, "A", f, None))
            items.append(("earthing_impedance", abs(ze) * probe_share * 1000.0, math.degrees(np.angle(ze)), "mΩ", f,
                          probe_m))
            if touch_share is not None:
                items.append(("earthing_impedance", abs(ze) * touch_share * 1000.0, math.degrees(np.angle(ze)), "mΩ",
                              f, 1.0))
        con.executemany("insert into measurementitem (measurement_type, value, value_angle_deg, unit, frequency_hz, "
                        "measurement_distance_m, measurement_id) values (?, ?, ?, ?, ?, ?, 1)", items)
        con.commit()
    finally:
        con.close()
    return path


# =========================================================================== campaign
def make_campaign(base: str, name: str = "2026-01-15_Demo", layout: str = "en", *, station: str = "Station_Elm_Road",
                  location: str = "Station Elm Road", groundmeas: bool = True) -> dict:
    """Write a complete demo campaign: a substation series, a station recording with its RMS file, the notes
    folder and the read-me – and a groundmeas database with the earthing measurement of the station.

    The demo never changes a file outside its own campaign folder, so it can be tried in a real work folder: the
    database ``demo_groundmeas.db`` and the register of the work folder are only created if they do not exist yet –
    the register only in a work folder without other campaigns (a work folder that already holds campaigns keeps its
    register as it is; ``tools/update_register.py`` adds the demo on request). Inside the campaign folder the
    recordings are (re)written, the notes, corrections and sites files only created if they are missing.

    Parameters
    ----------
    base : str
        Work folder; the campaign is written to ``<base>/<campaigns>/<name>`` (folder names of the layout) and the
        database to ``<base>/demo_groundmeas.db``.
    name : str, optional
        Name of the campaign folder (``<date>_<place>``).
    layout : {"en", "de"}, optional
        Folder layout (see [`groundfault.layout`][groundfault.layout]); the substation folder and file prefix are
        ``SUB`` (English) or ``UW`` (German).
    station : str, optional
        Folder of the station recording in the raw-data folder.
    location : str, optional
        Name of the station in the groundmeas database.
    groundmeas : bool, optional
        Use the groundmeas database (created if it does not exist) and pre-fill the sites file from it.

    Returns
    -------
    dict
        ``base``, ``campaign`` (folder), ``db`` (database path or None), ``substation`` (list of the truths of
        [`make_substation_series`][groundfault.demo.make_substation_series], with ``cfg`` = path relative to the
        campaign folder), ``station`` (truth of [`make_station_recording`][groundfault.demo.make_station_recording],
        with ``cfg`` and ``rms_cfg``) and ``register`` (path of the register written for the demo; None if the register
        of the work folder was left as it is).
    """
    from . import corrections, register, sites
    from .layout import ENGLISH, GERMAN, get_layout
    lay = get_layout(layout)
    campaign = os.path.join(base, lay.campaigns, name)
    # other campaigns and an existing register of the work folder (either layout): left alone
    own = os.path.normcase(os.path.abspath(campaign))
    others = [c for other in dict.fromkeys((lay, ENGLISH, GERMAN))
              for c in glob.glob(os.path.join(base, other.campaigns, "*"))
              if os.path.isdir(c) and os.path.normcase(os.path.abspath(c)) != own]
    own_register = not others and not any(os.path.exists(os.path.join(base, other.register_file))
                                          for other in (ENGLISH, GERMAN))
    sub = "SUB" if lay.language == "en" else "UW"
    sub_folder = os.path.join(campaign, lay.raw, sub)
    series = make_substation_series(sub_folder, prefix=sub)
    for w in series:
        w["cfg"] = "/".join((lay.raw, sub, w["file"]))
    st_folder = os.path.join(campaign, lay.raw, station)
    os.makedirs(st_folder, exist_ok=True)
    st_cfg = os.path.join(st_folder, station + "_10_000kHz.cfg")
    st = make_station_recording(st_cfg, duration=8.0, t_on=2.0, t_off=5.5, with_voltages=True,
                                lv_network=dict(R_LV=4.0, X_LV1=0.4),
                                r_per_order={1: polar(0.5, -10.0), 3: polar(0.45, -15.0), 5: polar(0.4, -20.0),
                                             7: polar(0.35, -25.0), 11: polar(0.3, -30.0)})
    rms_cfg = rms_file_from_instantaneous(st_cfg, os.path.join(st_folder, station + "_10_000Hz.cfg"))
    st["cfg"] = "/".join((lay.raw, station, os.path.basename(st_cfg)))
    st["rms_cfg"] = "/".join((lay.raw, station, os.path.basename(rms_cfg)))
    db = None
    if groundmeas:
        db = os.path.join(base, "demo_groundmeas.db")
        if not os.path.exists(db):                      # an existing database is used as it is
            make_groundmeas_db(db, location)
    # corrections: the touch-voltage channel UT carries no distance in its name
    path = corrections.write_template(campaign, layout=lay)
    if path:
        remark = "touch-voltage probe at 1 m (demo)" if lay.language == "en" else "Berührungsspannungssonde in 1 m (Demo)"
        with open(path, "a", encoding="utf-8") as f:
            f.write("%s_*;UT;;;;1;%s\n" % (station, remark))
    # sites: line length from the feeding substation to the station
    path = sites.write_template(campaign, db_path=db or os.path.join(base, "no_groundmeas.db"), layout=lay)
    if path:
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
        for i, line in enumerate(lines):
            fields = line.split(";")
            if fields[0] == station and len(fields) > 6:
                fields[6] = "2400"
                lines[i] = ";".join(fields)
        with open(path, "w", encoding="utf-8-sig") as f:
            f.write("\n".join(lines) + "\n")
    register.create_notes_folder(campaign, db, lay)
    rows = register.scan(base, layout=lay, campaigns=[name])
    reg = register.write_register(base, df=rows, layout=lay) if own_register else None
    with open(os.path.join(campaign, lay.readme_file), "w", encoding="utf-8") as f:
        f.write(register.campaign_readme(campaign, rows, lay))
    return dict(base=base, campaign=campaign, db=db, substation=series, station=st, register=reg)


# =========================================================================== helpers
def _json_ready(o):
    """JSON form of complex numbers (``re``, ``im``, ``magnitude``, ``angle_deg``), numpy values and tuples."""
    if isinstance(o, complex):
        return {"re": o.real, "im": o.imag, "magnitude": abs(o), "angle_deg": math.degrees(math.atan2(o.imag, o.real))}
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, tuple):
        return list(o)
    raise TypeError(type(o))


def _save_truth(path: str, truth: dict) -> None:
    """Save the true values as ``<stem>_truth.json`` next to the recording."""
    stem = os.path.splitext(path)[0]
    with open(stem + "_truth.json", "w", encoding="utf-8") as f:
        json.dump(truth, f, indent=1, ensure_ascii=False, default=_json_ready)
