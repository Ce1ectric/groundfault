# -*- coding: utf-8 -*-
"""Transformer node: power flow and impedance at the HV/MV transformer per harmonic order – before, during and
after the earth fault.

A recording with the three line currents of the transformer (roles ``i_l1`` … ``i_l3``, MV side) and the
line-to-earth voltages of the MV busbar (``u_l1e`` … ``u_l3e``; optionally also of the HV side, ``u_hv_l1e`` …)
shows how the harmonic sources of the network – bundled at the transformer – behave before, during and after the
earth fault.

States
------
``pre_fault`` and ``post_fault`` (all windows of these intervals) and ``fault`` (the reference windows of the
steady-state interval, i.e. without disturbed states, see [`groundfault.disturbances`][groundfault.disturbances]).
Every quantity is the mean over the windows of its state.

Quantities per state, order m and sequence s (zero, positive, negative)
-----------------------------------------------------------------------
* ``U_s,m``, ``I_s,m`` – symmetrical components of the busbar voltages and of the transformer currents, referred to
  the fundamental of U_L1-L2 of each window (X̂_m = X_m·e^{−j·m·φ}, common angle reference): phasors of different
  windows and states can be averaged and subtracted;
* ``S_s,m = 3·U_s,m·I_s,m* = P + jQ``; the sum over the sequences equals the sum over the phases,
  S_m = Σ_x U_x,m·I_x,m*;
* the apparent impedance ``U_s,m/I_s,m``.

Reference arrow system: consumer reference arrow system of the MV network – P > 0 is power flowing through the
transformer from the HV network into the MV network. A harmonic P_m < 0 means that the MV network as a whole feeds
power of this order into the HV network (the dominant source of the order lies in the MV network), P_m > 0 that it
comes from the HV network.

Upstream impedance from the fault-related change
------------------------------------------------
At the fault location the earth fault draws I1 = I2 = I0 = I_F/3 (fault in L1; phase factors for L2 and L3) of every
order. The positive- and negative-sequence parts flow (mostly) through the transformer, and the busbar voltage
changes by

    ΔU_s,m = −Z_up,s,m·ΔI_s,m

as long as the harmonic voltages of the HV network stay unchanged: Z_up = R + jX is the impedance of the transformer
and the HV network seen from the MV busbar (inductive, X ≈ m·X_1). Two estimates – fault − pre-fault and
fault − post-fault – and the null test post-fault − pre-fault (drift of the background during the fault) give its
uncertainty. With the HV voltages, ΔU_HV referred to the MV side (ratio and phase shift k·30° of the vector group from
the fundamental; positive sequence +k·30°, negative sequence −k·30°) gives the share of the HV network
Z_HV = −ΔU_HV/ΔI and that of the transformer Z_T = Z_up − Z_HV.

Polarity of the current transformers
------------------------------------
Z_up of transformer and HV network is inductive (0° < φ < 180°). A capacitive Z_up at the significant orders means
that the currents were measured in the generator reference arrow system: with ``Settings.transformer_sign = None``
(default) they are reversed automatically and the hints say so; ``transformer_sign = +1`` or ``−1`` fixes the sign.
Orders divisible by 3 (strongly excited in the zero sequence during the fault) and the fundamental (load changes)
do not take part in this decision.

Fault current estimated from the transformer currents
-----------------------------------------------------
Without a fault-current channel, I_F ≈ 3·c·ΔI_2,1 (c = 1, a, a² for a fault in L1, L2, L3) – the change of the
negative-sequence current of the transformer against the pre-fault (or post-fault) state – serves the detection of
disturbed states (active residual current increase, network change). Its steps are reliable, its level less so:
loads, generators and a parallel transformer take part of the negative-sequence current as well.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import i18n
from .i18n import tr
from .symmetrical import A, A2, fortescue

__all__ = ["STATES", "SEQUENCES", "SIGNIFICANCE", "T_SETTLE_S", "NOISE_FACTOR", "sequence_windows", "state_means", "upstream_impedance",
           "polarity", "faulted_phase", "fault_current_estimate", "detection_input", "fault_times", "settled_index",
           "fault_end_index", "estimate_noise", "node_analysis", "plausibility_rows", "power_overview",
           "summary_text"]

STATES = ("pre_fault", "fault", "post_fault")
"""States of the transformer node: before, during (reference windows of the steady-state interval) and after the
fault."""
SEQUENCES = ("zero", "pos", "neg")
"""Symmetrical components in the order of [`fortescue`][groundfault.symmetrical.fortescue] (index 0, 1, 2)."""
SIGNIFICANCE = 0.2
"""Largest relative uncertainty of a significant upstream impedance (from the spread of the windows and the null
test)."""
T_SETTLE_S = 1.5
"""Shortest time in s after the fault inception before the scan of a transformer recording starts: the estimated fault
current settles more slowly than a measured one (coils, loads and generators after the inception)."""
NOISE_FACTOR = 4.0
"""A step of the estimated fault current counts as a disturbance only if it is at least this multiple of the
window-to-window noise of its active and reactive component ([`estimate_noise`][groundfault.transformer.estimate_noise])
– the estimate fluctuates with the load unbalance much more than a measured fault current."""

i18n.register({
    "transformer.polarity_reversed": {
        "en": "Transformer currents measured in the generator reference arrow system (upstream impedance capacitive, "
              "mean angle {angle:.0f}° over {count} orders/sequences) – reversed for P, Q and the impedances.",
        "de": "Trafoströme im Erzeugerzählpfeilsystem gemessen (Vorimpedanz kapazitiv, mittlerer Winkel {angle:.0f}° "
              "über {count} Ordnungen/Systeme) – für P, Q und die Impedanzen umgekehrt."},
    "transformer.polarity_conflict": {
        "en": "transformer_sign = {sign:+g} contradicts the angle of the upstream impedance ({angle:.0f}° over "
              "{count} orders/sequences, which suggests {auto:+d}) – check the current transformers.",
        "de": "transformer_sign = {sign:+g} widerspricht dem Winkel der Vorimpedanz ({angle:.0f}° über {count} "
              "Ordnungen/Systeme, das spricht für {auto:+d}) – Stromwandler prüfen."},
    "transformer.fault_current_estimated": {
        "en": "No fault-current channel: for the detection of disturbed states the fault current is estimated from "
              "the change of the negative-sequence current of the transformer (3·ΔI₂, fault in {phase}, reference "
              "{base}); its steps are reliable, its level is an estimate.",
        "de": "Kein Fehlerstromkanal: für die Erkennung gestörter Zustände wird der Fehlerstrom aus der Änderung des "
              "Gegenstroms des Trafos geschätzt (3·ΔI₂, Fehler in {phase}, Bezug {base}); seine Sprünge sind "
              "verlässlich, sein Pegel ist eine Schätzung."},
    "transformer.base_pre_fault": {"en": "pre-fault", "de": "Vorfehler"},
    "transformer.base_post_fault": {"en": "post-fault", "de": "Nachfehler"},
    "transformer.check_polarity": {"en": "Polarity of the transformer currents",
                                   "de": "Polarität der Trafoströme"},
    "transformer.polarity_consumer": {"en": "consumer reference arrow system ({source})",
                                      "de": "Verbraucherzählpfeilsystem ({source})"},
    "transformer.polarity_generator": {"en": "generator reference arrow system – reversed ({source})",
                                       "de": "Erzeugerzählpfeilsystem – umgekehrt ({source})"},
    "transformer.source_automatic": {"en": "from Z_up, {angle:.0f}° over {count} orders/sequences",
                                     "de": "aus Z_vor, {angle:.0f}° über {count} Ordnungen/Systeme"},
    "transformer.source_setting": {"en": "transformer_sign = {sign:+g}", "de": "transformer_sign = {sign:+g}"},
    "transformer.source_default": {"en": "not determinable, as measured", "de": "nicht bestimmbar, wie gemessen"},
    "transformer.polarity_comment": {
        "en": "the impedance of transformer and HV network seen from the MV busbar is inductive",
        "de": "die Impedanz von Trafo und HS-Netz von der MS-Sammelschiene aus ist induktiv"},
    "transformer.check_upstream": {"en": "Upstream impedance (transformer + HV network)",
                                   "de": "Vorimpedanz (Trafo + HS-Netz)"},
    "transformer.value_upstream": {
        "en": "X_up/m = {x1:.3f} Ω ({count} significant orders/sequences, spread {spread:.0f} %)",
        "de": "X_vor/m = {x1:.3f} Ω ({count} signifikante Ordnungen/Systeme, Streuung {spread:.0f} %)"},
    "transformer.value_upstream_none": {"en": "no significant order", "de": "keine signifikante Ordnung"},
    "transformer.upstream_comment": {
        "en": "from the fault-related change ΔU = −Z_up·ΔI; X_up/m is about constant for an inductive impedance",
        "de": "aus der fehlerbedingten Änderung ΔU = −Z_vor·ΔI; X_vor/m ist bei induktiver Impedanz etwa konstant"},
    "transformer.summary_polarity": {"en": "currents: {system}", "de": "Ströme: {system}"},
    "transformer.system_consumer": {"en": "consumer reference arrow system", "de": "Verbraucherzählpfeilsystem"},
    "transformer.system_generator": {"en": "generator reference arrow system (reversed)",
                                     "de": "Erzeugerzählpfeilsystem (umgekehrt)"},
    "transformer.summary_x1": {"en": "X_up/m = {x1:.3f} Ω ({count} orders/sequences)",
                               "de": "X_vor/m = {x1:.3f} Ω ({count} Ordnungen/Systeme)"},
    "transformer.summary_split": {"en": "transformer {xt:.3f} Ω, HV network {xh:.3f} Ω (ratio {ratio:.3f}, group {group})",
                                  "de": "Trafo {xt:.3f} Ω, HS-Netz {xh:.3f} Ω (Übersetzung {ratio:.3f}, Kennzahl {group})"},
    "transformer.summary_dp1": {"en": "fault − pre-fault at 50 Hz: ΔP = {dp:+.0f} kW, ΔQ = {dq:+.0f} kvar",
                                "de": "Erdschluss − Vorfehler bei 50 Hz: ΔP = {dp:+.0f} kW, ΔQ = {dq:+.0f} kvar"},
    "transformer.check_hv": {"en": "HV side: ratio and vector group", "de": "HS-Seite: Übersetzung und Schaltgruppe"},
    "transformer.value_hv": {"en": "{ratio:.3f}, {shift:.0f}° (group {group})",
                             "de": "{ratio:.3f}, {shift:.0f}° (Kennzahl {group})"},
    "transformer.hv_comment": {
        "en": "from the fundamental of the positive sequence; the HV voltages are referred to the MV side with it",
        "de": "aus der Grundschwingung des Mitsystems; damit werden die HS-Spannungen auf die MS-Seite bezogen"},
})


# ====================================================================== windows and states
def sequence_windows(block, roles, orders: Sequence[int], voltages: str = "mv",
                     windows: Optional[np.ndarray] = None) -> Optional[dict]:
    """Per window of an interval: symmetrical components of the voltages and of the transformer currents per order,
    referred to the fundamental of U_L1-L2 of the window.

    Parameters
    ----------
    block : object
        Window analysis of an interval (``Result.steady_state``, ``Result.pre_fault`` …).
    roles : RoleAssignment
        Channel roles (line currents ``i_l1`` … ``i_l3`` and line-to-earth voltages).
    orders : sequence of int
        Orders (computed in ``block``).
    voltages : {"mv", "hv"}, optional
        Voltage set: MV busbar (``u_l1e`` …) or HV side (``u_hv_l1e`` …). The angle reference is U_L1-L2 of the MV
        voltages if they were recorded, else of the HV voltages.
    windows : numpy.ndarray of bool, optional
        Windows to use (default: all with finite values).

    Returns
    -------
    dict or None
        ``U`` and ``I`` – arrays (windows × 3 sequences × orders, sequences in the order of
        [`SEQUENCES`][groundfault.transformer.SEQUENCES]), ``S`` = 3·U·I* (same shape), ``S_phases`` = Σ_x U_x·I_x*
        (windows × orders) and ``t`` (window centres in s); None if a role is missing or no window is left.
    """
    il = roles.line_currents
    ul = roles.line_to_earth if voltages == "mv" else roles.line_to_earth_hv
    le_ref = roles.line_to_earth or roles.line_to_earth_hv
    if block is None or il is None or ul is None or le_ref is None:
        return None
    ok = ~block.nan_window if windows is None else (np.asarray(windows, bool) & ~block.nan_window)
    if not ok.any():
        return None
    ix = [block.ix(int(m)) for m in orders]
    X = block.X[ok]
    ref = X[:, le_ref[0], block.ix(1)] - X[:, le_ref[1], block.ix(1)]
    rot = np.exp(-1j * np.outer(np.angle(ref), np.asarray(orders, float)))[:, None, :]       # (n_w, 1, n_o)
    U = X[:, ul, :][:, :, ix] * rot
    I = X[:, il, :][:, :, ix] * rot
    Us = np.stack(fortescue(U[:, 0], U[:, 1], U[:, 2]), axis=1)
    Is = np.stack(fortescue(I[:, 0], I[:, 1], I[:, 2]), axis=1)
    return dict(U=Us, I=Is, S=3.0 * Us * np.conj(Is), S_phases=(U * np.conj(I)).sum(axis=1), t=block.t_mid[ok])


def state_means(w: dict) -> dict:
    """Mean values of one state from [`sequence_windows`][groundfault.transformer.sequence_windows].

    Returns
    -------
    dict
        ``n`` (windows), complex means ``U``, ``I`` (3 sequences × orders), their standard errors ``se_U``, ``se_I``
        (from the spread of the windows), RMS values over the windows ``U_rms``, ``I_rms`` and the mean powers ``S``
        (3 × orders) and ``S_phases`` (orders).
    """
    n = int(w["U"].shape[0])
    U = w["U"].mean(axis=0)
    I = w["I"].mean(axis=0)
    dof = max(n - 1, 1) * n
    return dict(n=n, U=U, I=I,
                se_U=np.sqrt((np.abs(w["U"] - U) ** 2).sum(axis=0) / dof),
                se_I=np.sqrt((np.abs(w["I"] - I) ** 2).sum(axis=0) / dof),
                U_rms=np.sqrt((np.abs(w["U"]) ** 2).mean(axis=0)),
                I_rms=np.sqrt((np.abs(w["I"]) ** 2).mean(axis=0)),
                S=w["S"].mean(axis=0), S_phases=w["S_phases"].mean(axis=0))


def upstream_impedance(fault: dict, pre: Optional[dict] = None, post: Optional[dict] = None,
                       sign: float = 1.0) -> Optional[dict]:
    """Upstream impedance Z_up = −ΔU/ΔI per sequence and order from the fault-related change.

    Parameters
    ----------
    fault, pre, post : dict
        States from [`state_means`][groundfault.transformer.state_means]; ``pre`` or ``post`` may be None (not both).
    sign : float, optional
        Factor of the currents (+1 as measured, −1 reversed).

    Returns
    -------
    dict or None
        Arrays (3 sequences × orders): ``dU``, ``dI`` (fault − pre-fault, without a pre-fault state fault − post-fault),
        ``Z`` (= −dU/dI), ``Z_post`` (fault − post-fault if both states exist, else NaN), the null test ``dU_null``,
        ``dI_null`` (|post-fault − pre-fault|, NaN without one of them), ``u_rel`` – the relative uncertainty
        √((δU/|ΔU|)² + (δI/|ΔI|)²) with δ = max(standard error of the difference, null test), the absolute values
        δU, δI as ``dU_unc``, ``dI_unc`` – and ``deviation`` = |Z − Z_post|/|Z|; None without a state to compare
        with.
    """
    base = pre if pre is not None else post
    if fault is None or base is None:
        return None
    dU = fault["U"] - base["U"]
    dI = sign * (fault["I"] - base["I"])
    with np.errstate(divide="ignore", invalid="ignore"):
        Z = -dU / dI
        nan = np.full(dU.shape, np.nan)
        if pre is not None and post is not None:
            Z_post = -(fault["U"] - post["U"]) / (sign * (fault["I"] - post["I"]))
            dU_null = np.abs(post["U"] - pre["U"])
            dI_null = np.abs(post["I"] - pre["I"])
        else:
            Z_post, dU_null, dI_null = nan + 0j, nan, nan
        dU_se = np.hypot(fault["se_U"], base["se_U"])
        dI_se = np.hypot(fault["se_I"], base["se_I"])
        dUu = np.fmax(dU_se, dU_null)                  # fmax: NaN of the null test is ignored
        dIu = np.fmax(dI_se, dI_null)
        u_rel = np.hypot(dUu / np.abs(dU), dIu / np.abs(dI))
        deviation = np.abs(Z - Z_post) / np.abs(Z)
    return dict(dU=dU, dI=dI, Z=Z, Z_post=Z_post, dU_null=dU_null, dI_null=dI_null, u_rel=u_rel,
                deviation=deviation, dU_unc=dUu, dI_unc=dIu)


def _decision_rows(z: dict, orders: Sequence[int]) -> List[Tuple[int, int]]:
    """(sequence, order index) of the significant entries that take part in the polarity decision and in X_up/m:
    positive and negative sequence, orders ≥ 2 not divisible by 3."""
    out = []
    for s in (1, 2):
        for j, m in enumerate(orders):
            if m < 2 or m % 3 == 0:
                continue
            u = z["u_rel"][s, j]
            if np.isfinite(u) and u <= SIGNIFICANCE and np.isfinite(z["Z"][s, j]):
                out.append((s, j))
    return out


def polarity(fault: Optional[dict], pre: Optional[dict], post: Optional[dict],
             orders: Sequence[int]) -> Tuple[Optional[int], float, int]:
    """Polarity of the transformer currents from the angle of the upstream impedance.

    Parameters
    ----------
    fault, pre, post : dict or None
        States from [`state_means`][groundfault.transformer.state_means] (as measured).
    orders : sequence of int
        Orders of the states.

    Returns
    -------
    sign : int or None
        +1: consumer reference arrow system as measured (Z_up inductive), −1: generator reference arrow system (the
        currents are to be reversed), None: no significant order.
    angle_deg : float
        Mean angle of Z_up as measured, weighted with |ΔI| (NaN without a significant order).
    count : int
        Number of orders/sequences used (positive and negative sequence, orders ≥ 2 not divisible by 3, relative
        uncertainty ≤ [`SIGNIFICANCE`][groundfault.transformer.SIGNIFICANCE]).
    """
    z = upstream_impedance(fault, pre, post) if fault is not None else None
    if z is None:
        return None, float("nan"), 0
    rows = _decision_rows(z, orders)
    if not rows:
        return None, float("nan"), 0
    w = np.array([abs(z["dI"][s, j]) for s, j in rows])
    ph = np.array([np.angle(z["Z"][s, j]) for s, j in rows])
    mean = complex(np.sum(w * np.exp(1j * ph)))
    sign = 1 if mean.imag > 0 else -1
    return sign, float(np.degrees(np.angle(mean))), len(rows)


def faulted_phase(block, roles) -> Optional[int]:
    """Index 0, 1, 2 of the faulted phase (smallest median line-to-earth voltage of the fundamental) or None."""
    le = roles.line_to_earth
    if block is None or not le:
        return None
    ok = ~block.nan_window
    if not ok.any():
        return None
    mag = [float(np.median(np.abs(block.X[ok, k, block.ix(1)]))) for k in le]
    return int(np.argmin(mag))


def fault_current_estimate(fault_block, base_block, roles, sign: float = 1.0):
    """Fault current per window estimated from the change of the negative-sequence current of the transformer – the
    input of [`groundfault.disturbances.detect`][groundfault.disturbances.detect] without a fault-current channel.

    I_F ≈ 3·c·sign·(I_2 − Ī_2,base) with c = 1, a, a² for a fault in L1, L2, L3 (at the fault location
    I_2 = I_F/3·(1, a², a)); the transformer carries most of the negative-sequence current of the fault, loads,
    generators and a parallel transformer the rest.

    Parameters
    ----------
    fault_block : object
        Window analysis of the steady-state interval.
    base_block : object
        Window analysis of the pre-fault (or post-fault) interval: reference level of I_2.
    roles : RoleAssignment
        Channel roles (line currents, MV line-to-earth voltages, coil currents).
    sign : float, optional
        Polarity of the transformer currents (+1 consumer reference arrow system as measured, −1 reversed;
        [`polarity`][groundfault.transformer.polarity]).

    Returns
    -------
    tuple or None
        ``(I1, U0, coil, phase)`` – per window the fundamental phasor oriented for
        [`detect`][groundfault.disturbances.detect] with ``orient=False`` (−I_F: its active component relative to U0
        is the active current of the earth-fault circuit), U0, the sum of the coil currents referred to the mean |U0|
        (None without coil currents) – all in the common angle reference of U_L1-L2 – and the index of the faulted
        phase; None without line currents, MV line-to-earth voltages or windows.
    """
    il, le = roles.line_currents, roles.line_to_earth
    if fault_block is None or base_block is None or il is None or not le:
        return None
    ph = faulted_phase(fault_block, roles)
    ok_b = ~base_block.nan_window
    if ph is None or not ok_b.any():
        return None

    def i2_u0(b):
        X1 = b.X[:, :, b.ix(1)]
        rot = np.exp(-1j * np.angle(X1[:, le[0]] - X1[:, le[1]]))
        i2 = fortescue(*(X1[:, k] * rot for k in il))[2]
        u0 = sum(X1[:, k] * rot for k in le) / 3.0
        return i2, u0
    i2, u0 = i2_u0(fault_block)
    i2b, _ = i2_u0(base_block)
    c = (1.0, A, A2)[ph]
    I_F = 3.0 * c * sign * (i2 - np.mean(i2b[ok_b]))
    nan = fault_block.nan_window
    I1 = np.where(nan, np.nan, -I_F)
    coil = None
    coils = roles.with_role("i_coil")
    if coils:
        u = np.abs(u0)
        mean_u = float(np.nanmean(u[~nan])) if (~nan).any() else float("nan")
        with np.errstate(divide="ignore", invalid="ignore"):
            coil = sum(np.abs(fault_block.X[:, k.index, fault_block.ix(1)]) for k in coils) / np.where(
                u > 0, u / mean_u, np.nan)
        coil = np.where(nan, np.nan, coil)
    return I1, u0, coil, ph


def detection_input(fault_block, base_block, roles, settings, windows: Optional[np.ndarray] = None,
                    other_block=None):
    """Input of [`disturbances.detect`][groundfault.disturbances.detect] for a recording without a fault-current
    channel: the polarity of the transformer currents and the estimated fault current.

    Parameters
    ----------
    fault_block : object
        Window analysis of the steady-state interval.
    base_block : object
        Window analysis of the pre-fault (or post-fault) interval: reference of the estimate.
    roles : RoleAssignment
        Channel roles.
    settings : Settings
        ``transformer_sign`` (None: polarity from the upstream impedance) and ``export_orders``.
    windows : numpy.ndarray of bool, optional
        Windows of ``fault_block`` for the polarity decision (default: all with finite values).
    other_block : object, optional
        Window analysis of the other fault-free interval (second estimate of the upstream impedance).

    Returns
    -------
    tuple or None
        ``(I1, U0, coil, phase, sign)`` – see [`fault_current_estimate`][groundfault.transformer.fault_current_estimate]
        – and the polarity used; None if the estimate is not possible.
    """
    sign = settings.transformer_sign
    if sign is None:
        orders = [m for m in sorted(set(int(x) for x in settings.export_orders) | {1}) if m in fault_block.orders]
        ms = {}
        for name, b, w in (("fault", fault_block, windows), ("base", base_block, None), ("other", other_block, None)):
            sw = sequence_windows(b, roles, orders, windows=w) if b is not None else None
            if sw is not None:
                ms[name] = state_means(sw)
        sign = polarity(ms.get("fault"), ms.get("base"), ms.get("other"), orders)[0] or 1
    est = fault_current_estimate(fault_block, base_block, roles, sign)
    if est is None:
        return None
    return est + (float(sign),)


def fault_times(rec, roles, window_s: float = 0.02) -> Tuple[Optional[float], Optional[float]]:
    """Fault inception and fault clearance from the RMS trend of the zero-sequence voltage (mean of the three MV
    line-to-earth voltages) – for recordings without a fault-current channel.

    A section counts as active where the moving median of the RMS trend exceeds 10 % of its maximum (as
    [`station.fault_times`][groundfault.station.fault_times] does with the fault current).

    Parameters
    ----------
    rec : Recording
        The recording.
    roles : RoleAssignment
        Channel roles (MV line-to-earth voltages).
    window_s : float, optional
        Length of the RMS windows in s.

    Returns
    -------
    t_on, t_off : float or None
        Fault inception and fault clearance in s; ``t_on`` is None if the fault is active from the start of the
        recording, ``t_off`` None if it lasts until its end; both None without a fault or without the voltages.
    """
    from .diagnostics import _active_range
    le = roles.line_to_earth
    if not le:
        return None, None
    nw = max(2, int(round(window_s * rec.fs)))
    n_w = rec.n // nw
    if n_w < 3:
        return None, None
    per_block = max(1, int(20.0 * rec.fs) // nw)
    r = np.empty(n_w)
    for f0 in range(0, n_w, per_block):
        f1 = min(n_w, f0 + per_block)
        x = rec.read(f0 * nw, f1 * nw, list(le)).mean(axis=1).reshape(f1 - f0, nw)
        r[f0:f1] = np.sqrt(np.mean((x - np.median(x, axis=1, keepdims=True)) ** 2, axis=1))
    t = (np.arange(n_w) + 0.5) * nw / rec.fs
    from_, until = _active_range(t, r)
    if not np.isfinite(from_):
        return None, None
    t_off = float(until) if until < rec.duration_s - 3 * window_s else None
    t_on = float(from_) if from_ > 5 * window_s else None
    return t_on, t_off


def settled_index(magnitude: np.ndarray, windows: int = 8, drift: float = 0.1) -> int:
    """Index of the first window from which the estimated fault current has settled after the inception: the straight
    line fitted to the next ``windows`` magnitudes changes by at most ``drift`` of their mean (a decaying transient is
    not settled, the window-to-window noise of the estimate does not delay the decision, and a later step – a
    disturbance – stays inside the scanned range). 0 for a series shorter than three windows, the last possible start
    if no such range exists."""
    m = np.asarray(magnitude, float)
    if m.size < 3 or not np.isfinite(m).any():
        return 0
    n = min(windows, m.size)
    x = np.arange(n, dtype=float)
    for k in range(0, m.size - n + 1):
        part = m[k:k + n]
        mean = float(part.mean())
        if not np.isfinite(part).all() or mean <= 0:
            continue
        if abs(float(np.polyfit(x, part, 1)[0])) * (n - 1) <= drift * mean:
            return k
    return m.size - n


def estimate_noise(I1: np.ndarray, U0: np.ndarray) -> float:
    """Window-to-window noise (standard deviation) of the active and reactive component of an estimated fault current,
    the larger of both: 1.4826·median|Δx|/√2 of successive windows – robust against the few steps of disturbances.

    Parameters
    ----------
    I1, U0 : numpy.ndarray of complex
        Estimated fault current and zero-sequence voltage per window
        ([`fault_current_estimate`][groundfault.transformer.fault_current_estimate]).

    Returns
    -------
    float
        Noise in A (0 for fewer than three finite windows).
    """
    I1 = np.asarray(I1, complex); U0 = np.asarray(U0, complex)
    ok = np.isfinite(I1) & np.isfinite(U0) & (np.abs(U0) > 0)
    if ok.sum() < 3:
        return 0.0
    rel = I1[ok] * np.exp(-1j * np.angle(U0[ok]))
    out = 0.0
    for x in (rel.real, rel.imag):
        dx = np.diff(x)
        out = max(out, 1.4826 * float(np.median(np.abs(dx))) / math.sqrt(2.0))
    return out


def fault_end_index(magnitude: np.ndarray, share: float = 0.8) -> int:
    """Index after the last window whose magnitude reaches ``share`` of the median of the series – the windows after
    it straddle the fault clearance or follow it (the zero-sequence voltage decays more slowly than the fault
    current)."""
    m = np.asarray(magnitude, float)
    if not np.isfinite(m).any():
        return m.size
    level = float(np.nanmedian(m))
    full = np.flatnonzero(m >= share * level)
    return int(full[-1]) + 1 if full.size else m.size


# ====================================================================== tables
def _deg(z) -> float:
    return float(np.degrees(np.angle(z))) if np.isfinite(z) else float("nan")


def _f(x) -> float:
    x = float(x)
    return x if math.isfinite(x) else float("nan")


def _hv_factor(seq: int, ratio: float, k: int) -> complex:
    """Factor HV → MV of a sequence: positive sequence ratio·e^{+jk·30°}, negative ratio·e^{−jk·30°}."""
    return ratio * np.exp((1j if seq == 1 else -1j) * np.radians(30.0 * k))


def node_analysis(res) -> None:
    """Transformer node of an evaluation result: tables ``transformer_node``, ``transformer_power_change``,
    ``transformer_impedance`` and ``transformer_power``, the values ``res.values["transformer"]`` and hints.

    ``transformer_node`` – per state, order and sequence (``zero``, ``pos``, ``neg``, ``total``): ``U_V``, ``I_A``
    (RMS over the windows; ``total``: √Σ_s), ``P_kW``, ``Q_kvar``, the apparent impedance ``Z_Ohm``,
    ``Z_angle_deg`` (complex means U/I) and ``windows``.

    ``transformer_power_change`` – per order and sequence: ``dP_fault_kW``, ``dQ_fault_kvar`` (fault − pre-fault)
    and ``dP_post_kW``, ``dQ_post_kvar`` (post-fault − pre-fault, the null test); without a pre-fault state relative
    to the post-fault state.

    ``transformer_impedance`` – per order, positive and negative sequence: ``dU_V``, ``dI_A`` (fault-related change),
    the upstream impedance ``Z_up_Ohm``, ``Z_up_angle_deg``, ``R_up_Ohm``, ``X_up_Ohm``, ``X_up_per_order_Ohm``
    (X_up/m), the second estimate ``Z_up_post_Ohm``, ``Z_up_post_angle_deg``, ``deviation_pct``, the deviation
    between positive and negative sequence ``pos_neg_deviation_pct`` (equal for a symmetrical passive upstream
    network), the null test ``dU_null_V``, ``dI_null_A``, ``uncertainty_pct`` and ``significant``; with HV voltages
    also ``Z_hv_Ohm``,
    ``Z_hv_angle_deg``, ``X_hv_Ohm``, ``uncertainty_hv_pct`` (HV network) and ``Z_transformer_Ohm``,
    ``Z_transformer_angle_deg``, ``X_transformer_Ohm`` (transformer).

    ``transformer_power`` – P, Q (sum of the sequences) and the sequence currents per state for the orders ≤ 13
    (the table of version 2; the fault state is now the mean over the reference windows).

    Parameters
    ----------
    res : Result
        Evaluation result of a recording with the transformer capability
        ([`RoleAssignment.capabilities`][groundfault.channels.RoleAssignment.capabilities]).
    """
    roles, e = res.roles, res.settings
    if not roles.capabilities()["transformer"]:
        return
    near = "hv" if (e.transformer_voltage == "hv" and roles.line_to_earth_hv) or not roles.line_to_earth else "mv"
    far = "hv" if near == "mv" and roles.line_to_earth_hv else None
    st = res.steady_state
    orders = [m for m in sorted(set(int(x) for x in e.export_orders) | {1}) if m in st.orders]
    blocks = {"pre_fault": res.pre_fault, "fault": st, "post_fault": res.post_fault}
    masks = {"fault": res.reference_windows}
    win = {s: sequence_windows(b, roles, orders, near, masks.get(s)) for s, b in blocks.items()}
    means = {s: state_means(w) for s, w in win.items() if w is not None}
    if "fault" not in means:
        return
    f1 = {s: blocks[s].f1["f1_used"] for s in means}
    # ---- polarity
    auto, angle, count = polarity(means.get("fault"), means.get("pre_fault"), means.get("post_fault"), orders)
    if e.transformer_sign is None:
        sign = float(auto or 1)
        source = "automatic" if auto else "default"
        if auto == -1:
            res.hints.append(tr("transformer.polarity_reversed", angle=angle, count=count))
    else:
        sign = float(e.transformer_sign)
        source = "setting"
        if auto is not None and auto != int(np.sign(sign)):
            res.hints.append(tr("transformer.polarity_conflict", sign=sign, angle=angle, count=count, auto=auto))
    # ---- node table
    rows = []
    for s_name in STATES:
        if s_name not in means:
            continue
        mm = means[s_name]
        for j, m in enumerate(orders):
            for q, seq in enumerate(SEQUENCES):
                S = sign * mm["S"][q, j]
                with np.errstate(divide="ignore", invalid="ignore"):
                    Z = mm["U"][q, j] / (sign * mm["I"][q, j])
                rows.append(dict(interval=s_name, order=m, f_Hz=m * f1[s_name], sequence=seq,
                                 U_V=_f(mm["U_rms"][q, j]), I_A=_f(mm["I_rms"][q, j]),
                                 P_kW=_f(S.real / 1e3), Q_kvar=_f(S.imag / 1e3),
                                 Z_Ohm=_f(abs(Z)), Z_angle_deg=_deg(Z), windows=mm["n"]))
            S = sign * mm["S_phases"][j]
            rows.append(dict(interval=s_name, order=m, f_Hz=m * f1[s_name], sequence="total",
                             U_V=_f(np.sqrt(np.sum(mm["U_rms"][:, j] ** 2))),
                             I_A=_f(np.sqrt(np.sum(mm["I_rms"][:, j] ** 2))),
                             P_kW=_f(S.real / 1e3), Q_kvar=_f(S.imag / 1e3), Z_Ohm=np.nan, Z_angle_deg=np.nan,
                             windows=mm["n"]))
    node = pd.DataFrame(rows)
    res.tables["transformer_node"] = node
    # ---- power change
    base_name = "pre_fault" if "pre_fault" in means else ("post_fault" if "post_fault" in means else None)
    if base_name is not None:
        pv = node.set_index(["interval", "order", "sequence"])
        ch = []
        for m in orders:
            for seq in SEQUENCES + ("total",):
                b = pv.loc[(base_name, m, seq)]
                f = pv.loc[("fault", m, seq)]
                r = dict(order=m, f_Hz=m * f1["fault"], sequence=seq,
                         dP_fault_kW=f["P_kW"] - b["P_kW"], dQ_fault_kvar=f["Q_kvar"] - b["Q_kvar"],
                         dP_post_kW=np.nan, dQ_post_kvar=np.nan)
                if base_name == "pre_fault" and "post_fault" in means:
                    q = pv.loc[("post_fault", m, seq)]
                    r.update(dP_post_kW=q["P_kW"] - b["P_kW"], dQ_post_kvar=q["Q_kvar"] - b["Q_kvar"])
                ch.append(r)
        res.tables["transformer_power_change"] = pd.DataFrame(ch)
    # ---- upstream impedance (positive and negative sequence)
    z = upstream_impedance(means["fault"], means.get("pre_fault"), means.get("post_fault"), sign)
    hv = None
    if z is not None and far is not None:
        win_f = {s: sequence_windows(b, roles, orders, far, masks.get(s)) for s, b in blocks.items()}
        means_f = {s: state_means(w) for s, w in win_f.items() if w is not None}
        ref_state = next((s for s in ("pre_fault", "post_fault", "fault") if s in means and s in means_f), None)
        t = means_f[ref_state]["U"][1, 0] / means[ref_state]["U"][1, 0] if ref_state else np.nan
        if np.isfinite(t) and abs(t) > 0:
            k = int(round(np.degrees(np.angle(t)) / 30.0)) % 12
            zf = upstream_impedance(means_f["fault"], means_f.get("pre_fault"), means_f.get("post_fault"), sign)
            if zf is not None:
                hv = dict(ratio=float(abs(t)), group=k, shift_deg=30.0 * k, z=zf)
    out = []
    if z is not None:
        for j, m in enumerate(orders):
            for q in (1, 2):
                Zu = z["Z"][q, j]
                r = dict(order=m, f_Hz=m * f1["fault"], sequence=SEQUENCES[q], dU_V=_f(abs(z["dU"][q, j])),
                         dI_A=_f(abs(z["dI"][q, j])), Z_up_Ohm=_f(abs(Zu)), Z_up_angle_deg=_deg(Zu),
                         R_up_Ohm=_f(Zu.real), X_up_Ohm=_f(Zu.imag), X_up_per_order_Ohm=_f(Zu.imag / m),
                         Z_up_post_Ohm=_f(abs(z["Z_post"][q, j])), Z_up_post_angle_deg=_deg(z["Z_post"][q, j]),
                         deviation_pct=_f(100 * z["deviation"][q, j]), dU_null_V=_f(z["dU_null"][q, j]),
                         dI_null_A=_f(z["dI_null"][q, j]), uncertainty_pct=_f(100 * z["u_rel"][q, j]),
                         significant=bool(np.isfinite(z["u_rel"][q, j]) and z["u_rel"][q, j] <= SIGNIFICANCE))
                if hv is not None:
                    zf = hv["z"]
                    fac = _hv_factor(q, hv["ratio"], hv["group"])
                    with np.errstate(divide="ignore", invalid="ignore"):
                        Zh = -(zf["dU"][q, j] / fac) / z["dI"][q, j]
                        uh = np.hypot(zf["dU_unc"][q, j] / abs(zf["dU"][q, j]), z["dI_unc"][q, j] / abs(z["dI"][q, j]))
                    Zt = Zu - Zh
                    r.update(Z_hv_Ohm=_f(abs(Zh)), Z_hv_angle_deg=_deg(Zh), X_hv_Ohm=_f(Zh.imag),
                             uncertainty_hv_pct=_f(100 * uh), Z_transformer_Ohm=_f(abs(Zt)),
                             Z_transformer_angle_deg=_deg(Zt), X_transformer_Ohm=_f(Zt.imag))
                out.append(r)
        zi = pd.DataFrame(out)
        # positive and negative sequence of transformer and HV network are equal (symmetrical, passive): their
        # deviation per order is a check of the estimate (non-linear voltage transformers at the raised voltages of
        # the healthy phases, sources with sequence-dependent behaviour)
        piv = zi.pivot(index="order", columns="sequence", values="Z_up_Ohm") if not zi.empty else None
        if piv is not None and {"pos", "neg"} <= set(piv.columns):
            dev = (100 * (piv["pos"] - piv["neg"]).abs() / piv[["pos", "neg"]].mean(axis=1)).to_dict()
            zi.insert(zi.columns.get_loc("deviation_pct") + 1, "pos_neg_deviation_pct", zi["order"].map(dev))
        res.tables["transformer_impedance"] = zi
    # ---- table of version 2 (orders ≤ 13)
    pw = []
    for s_name in STATES:
        if s_name not in means:
            continue
        mm = means[s_name]
        for j, m in enumerate(orders):
            if m > 13:
                continue
            S = sign * mm["S_phases"][j]
            pw.append(dict(interval=s_name, order=m, f_Hz=m * f1[s_name], P_kW=_f(S.real / 1e3),
                           Q_kvar=_f(S.imag / 1e3), I_pos_A=_f(mm["I_rms"][1, j]), I_neg_A=_f(mm["I_rms"][2, j]),
                           I_zero_A=_f(mm["I_rms"][0, j])))
    res.tables["transformer_power"] = pd.DataFrame(pw)
    # ---- summary values
    vals = dict(sign=sign, polarity_source=source, polarity_auto=auto, polarity_angle_deg=angle,
                polarity_count=count, voltages=near, orders=list(orders))
    if z is not None:
        rows_d = _decision_rows(z, orders)
        if rows_d:
            x = np.array([z["Z"][s, j].imag / orders[j] for s, j in rows_d])
            wgt = np.array([1.0 / max(z["u_rel"][s, j], 1e-3) ** 2 for s, j in rows_d])
            x1 = float(np.sum(wgt * x) / np.sum(wgt))
            spread = float(np.sqrt(np.sum(wgt * (x - x1) ** 2) / np.sum(wgt)) / abs(x1)) if x1 else float("nan")
            vals.update(X1_up_Ohm=x1, X1_up_spread=spread, X1_up_count=len(rows_d))
            if hv is not None:
                zf = hv["z"]
                xh = []
                for s, j in rows_d:
                    with np.errstate(divide="ignore", invalid="ignore"):
                        Zh = -(zf["dU"][s, j] / _hv_factor(s, hv["ratio"], hv["group"])) / z["dI"][s, j]
                    xh.append(Zh.imag / orders[j])
                xh = np.array(xh)
                vals.update(X1_hv_Ohm=float(np.sum(wgt * xh) / np.sum(wgt)),
                            X1_transformer_Ohm=float(np.sum(wgt * (x - xh)) / np.sum(wgt)))
        else:
            vals.update(X1_up_Ohm=float("nan"), X1_up_count=0)
    if hv is not None:
        vals.update(hv_ratio=hv["ratio"], hv_group=hv["group"], hv_shift_deg=hv["shift_deg"])
    if "pre_fault" in means:
        p1 = node[(node["order"] == 1) & (node["sequence"] == "total")].set_index("interval")["P_kW"]
        q1 = node[(node["order"] == 1) & (node["sequence"] == "total")].set_index("interval")["Q_kvar"]
        vals.update(dP1_fault_kW=float(p1["fault"] - p1["pre_fault"]), dQ1_fault_kvar=float(q1["fault"] - q1["pre_fault"]))
    res.values["transformer"] = vals


def plausibility_rows(res) -> List[dict]:
    """Rows of the plausibility table for the transformer node (polarity, upstream impedance, HV side)."""
    v = res.values.get("transformer")
    if not v:
        return []
    out = []
    if v["polarity_source"] == "automatic":
        src = tr("transformer.source_automatic", angle=v["polarity_angle_deg"], count=v["polarity_count"])
    elif v["polarity_source"] == "setting":
        src = tr("transformer.source_setting", sign=v["sign"])
    else:
        src = tr("transformer.source_default")
    key = "transformer.polarity_consumer" if v["sign"] > 0 else "transformer.polarity_generator"
    conflict = v["polarity_source"] == "setting" and v["polarity_auto"] is not None and \
        v["polarity_auto"] != int(np.sign(v["sign"]))
    out.append(dict(check=tr("transformer.check_polarity"),
                    status="WARNING" if conflict else ("CORRECTED" if v["sign"] < 0 and
                                                       v["polarity_source"] == "automatic" else "INFO"),
                    value=tr(key, source=src), comment=tr("transformer.polarity_comment")))
    if "X1_up_Ohm" in v:
        if v.get("X1_up_count"):
            val = tr("transformer.value_upstream", x1=v["X1_up_Ohm"], count=v["X1_up_count"],
                     spread=100 * v.get("X1_up_spread", float("nan")))
        else:
            val = tr("transformer.value_upstream_none")
        out.append(dict(check=tr("transformer.check_upstream"), status="INFO", value=val,
                        comment=tr("transformer.upstream_comment")))
    if "hv_ratio" in v:
        out.append(dict(check=tr("transformer.check_hv"), status="INFO",
                        value=tr("transformer.value_hv", ratio=v["hv_ratio"], shift=v["hv_shift_deg"],
                                 group=v["hv_group"]), comment=tr("transformer.hv_comment")))
    return out


def power_overview(res, sequence: str = "total") -> pd.DataFrame:
    """P and Q per order (rows) before, during and after the fault (columns) – a compact view of
    ``transformer_node``.

    Parameters
    ----------
    res : Result
        Evaluation result with the transformer node.
    sequence : {"total", "pos", "neg", "zero"}, optional
        Sum of the sequences (default) or one sequence.

    Returns
    -------
    pandas.DataFrame
        Columns ``order``, ``f_Hz`` and ``P_<state>_kW``, ``Q_<state>_kvar`` for the states present (``pre_fault``,
        ``fault``, ``post_fault``); empty without a transformer node.
    """
    node = res.tables.get("transformer_node")
    if node is None or node.empty:
        return pd.DataFrame()
    d = node[node["sequence"] == sequence]
    out = d[d["interval"] == "fault"][["order", "f_Hz"]].reset_index(drop=True)
    for q, unit in (("P", "kW"), ("Q", "kvar")):
        for s_name in STATES:
            sub = d[d["interval"] == s_name].set_index("order")
            if not sub.empty:
                out["%s_%s_%s" % (q, s_name, unit)] = out["order"].map(sub["%s_%s" % (q, unit)])
    return out


def summary_text(res) -> str:
    """One line on the transformer node: polarity, X_up/m (with HV voltages split into transformer and HV network)
    and the change of the fundamental power during the fault – in the output language; empty without a transformer
    node."""
    v = res.values.get("transformer")
    if not v:
        return ""
    parts = [tr("transformer.summary_polarity", system=tr("transformer.system_consumer" if v["sign"] > 0
                                                         else "transformer.system_generator"))]
    if v.get("X1_up_count"):
        parts.append(tr("transformer.summary_x1", x1=v["X1_up_Ohm"], count=v["X1_up_count"]))
        if "X1_transformer_Ohm" in v:
            parts.append(tr("transformer.summary_split", xt=v["X1_transformer_Ohm"], xh=v["X1_hv_Ohm"],
                            ratio=v["hv_ratio"], group=v["hv_group"]))
    if "dP1_fault_kW" in v:
        parts.append(tr("transformer.summary_dp1", dp=v["dP1_fault_kW"], dq=v["dQ1_fault_kvar"]))
    return " · ".join(parts)
