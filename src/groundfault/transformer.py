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
import os
from typing import List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import i18n
from .i18n import tr
from .symmetrical import A, A2, fortescue

__all__ = ["STATES", "SEQUENCES", "SIGNIFICANCE", "T_SETTLE_S", "NOISE_FACTOR", "sequence_windows", "state_means", "upstream_impedance",
           "polarity", "faulted_phase", "fault_current_estimate", "detection_input", "fault_times", "settled_index",
           "fault_end_index", "estimate_noise", "node_analysis", "plausibility_rows", "power_overview",
           "summary_text", "is_natural", "voltage_windows", "voltage_divider", "IV_MIN_CORRELATION",
           "IV_MAX_ANGLE_DEG", "mv_network_impedance", "mv_network_series", "ct_angle_from_reference"]

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
    "transformer.value_upstream_other": {
        "en": "X_up/m = {x1:.3f} Ω ({count} significant orders in the sequence other than the natural one, spread "
              "{spread:.0f} %)",
        "de": "X_vor/m = {x1:.3f} Ω ({count} signifikante Ordnungen im nicht natürlichen Drehsystem, Streuung "
              "{spread:.0f} %)"},
    "transformer.value_upstream_none": {"en": "no significant order", "de": "keine signifikante Ordnung"},
    "transformer.upstream_comment": {
        "en": "from the fault-related change ΔU = −Z_up·ΔI; X_up/m is about constant for an inductive impedance; the "
              "sequence other than the natural one carries hardly any pre-fault harmonic (m = 5, 11 …: positive, "
              "m = 7, 13 …: negative sequence)",
        "de": "aus der fehlerbedingten Änderung ΔU = −Z_vor·ΔI; X_vor/m ist bei induktiver Impedanz etwa konstant; "
              "das nicht natürliche Drehsystem trägt kaum Vorbelastung (m = 5, 11 …: Mitsystem, m = 7, 13 …: "
              "Gegensystem)"},
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
    "transformer.check_divider": {"en": "HV share of the upstream impedance (voltage divider)",
                                  "de": "HS-Anteil der Vorimpedanz (Spannungsteiler)"},
    "transformer.value_divider": {
        "en": "k = {k:.3f} ({count} significant orders in the sequence other than the natural one, spread "
              "{spread:.0f} %)",
        "de": "k = {k:.3f} ({count} signifikante Ordnungen im nicht natürlichen Drehsystem, Streuung {spread:.0f} %)"},
    "transformer.value_divider_x": {"en": "{base}; X_HV/m = {xh:.3f} Ω, X_T/m = {xt:.3f} Ω",
                                    "de": "{base}; X_HS/m = {xh:.3f} Ω, X_T/m = {xt:.3f} Ω"},
    "transformer.value_divider_none": {"en": "no significant order", "de": "keine signifikante Ordnung"},
    "transformer.divider_comment": {
        "en": "k = Z_HV/(Z_T + Z_HV) from the fault-related change of the HV and MV voltages – without transformer "
              "currents; with them Z_HV = k·Z_up, a second method beside Z_HV from HV voltage and current",
        "de": "k = Z_HS/(Z_T + Z_HS) aus der fehlerbedingten Änderung der HS- und MS-Spannungen – ohne Trafoströme; "
              "mit ihnen Z_HS = k·Z_vor, ein zweites Verfahren neben Z_HS aus HS-Spannung und Strom"},
    "transformer.check_hv": {"en": "HV side: ratio and vector group", "de": "HS-Seite: Übersetzung und Schaltgruppe"},
    "transformer.value_hv": {"en": "{ratio:.3f}, {shift:.0f}° (group {group})",
                             "de": "{ratio:.3f}, {shift:.0f}° (Kennzahl {group})"},
    "transformer.hv_comment": {
        "en": "from the fundamental of the positive sequence; the HV voltages are referred to the MV side with it",
        "de": "aus der Grundschwingung des Mitsystems; damit werden die HS-Spannungen auf die MS-Seite bezogen"},
    "transformer.iv_intervals": {
        "en": "{n} recordings but {k} interval lists – give one list of undisturbed ranges per recording.",
        "de": "{n} Aufzeichnungen, aber {k} Bereichslisten – je Aufzeichnung eine Liste ungestörter Bereiche angeben."},
    "transformer.iv_roles": {
        "en": "{name}: the MV network impedance needs the transformer currents (i_l1 … i_l3), the MV busbar voltages "
              "(u_l1e …) and the HV voltages (u_hv_l1e …) in one recording.",
        "de": "{name}: Die Impedanz des MS-Netzes braucht die Trafoströme (i_l1 … i_l3), die Spannungen der "
              "MS-Sammelschiene (u_l1e …) und die HS-Spannungen (u_hv_l1e …) in einer Aufzeichnung."},
    "transformer.iv_orders": {
        "en": "Orders {orders} are not computed by the window analysis – extend Settings.export_orders.",
        "de": "Die Ordnungen {orders} berechnet die Fensteranalyse nicht – Settings.export_orders erweitern."},
    "transformer.iv_no_windows": {
        "en": "No undisturbed window with all channels – check the intervals.",
        "de": "Kein ungestörtes Fenster mit allen Kanälen – Bereiche prüfen."},
    "transformer.iv_reversed": {
        "en": "Transformer currents reversed (generator reference arrow system): the MV network impedance from the HV "
              "instrument had a negative real part.",
        "de": "Trafoströme umgekehrt (Erzeugerzählpfeilsystem): Die Impedanz des MS-Netzes aus dem HS-Instrument hatte "
              "einen negativen Wirkanteil."},
    "transformer.iv_sign_unknown": {
        "en": "Polarity of the transformer currents not determinable (no order with a strong instrument) – currents "
              "taken as measured; give sign= from the evaluation of an earth fault of the same recorder.",
        "de": "Polarität der Trafoströme nicht bestimmbar (keine Ordnung mit starkem Instrument) – Ströme wie gemessen; "
              "sign= aus der Auswertung eines Erdschlusses desselben Geräts angeben."},
    "transformer.iv_inductive": {
        "en": "Orders {orders}: the estimate is inductive (above {angle:g}°) – the variation was driven from the MV side "
              "and the result is the upstream impedance, not the MV network; not reliable.",
        "de": "Ordnungen {orders}: Die Schätzung ist induktiv (über {angle:g}°) – die Schwankung kam aus dem MS-Netz, "
              "das Ergebnis ist die Vorimpedanz, nicht das MS-Netz; nicht verlässlich."},
    "transformer.iv_mv_driven": {
        "en": "Orders {orders}: the HV network drives only part of the variation of the busbar voltage ({shares}; "
              "natural sequence, below min_hv_share = {limit:g}) – the sources in the MV network dominate and the "
              "estimate is not reliable. Record at another time (e.g. at night) or use a staged fault test.",
        "de": "Ordnungen {orders}: Das HS-Netz treibt nur einen Teil der Schwankung der Sammelschienenspannung "
              "({shares}; natürliches Drehsystem, unter min_hv_share = {limit:g}) – die Quellen im MS-Netz überwiegen, "
              "die Schätzung ist nicht verlässlich. Zu einer anderen Zeit aufzeichnen (z. B. nachts) oder einen "
              "Erdschlussversuch nutzen."},
    "transformer.iv_share_needs_z": {
        "en": "min_hv_share needs the upstream impedance Z_up (transformer and HV network) and the impedance of the HV "
              "network Z_hv: the share of the HV-driven variation is computed with Z_up, and it holds only with the "
              "instrument corrected by Z_hv.",
        "de": "min_hv_share braucht die Vorimpedanz Z_up (Trafo und HS-Netz) und die Impedanz des HS-Netzes Z_hv: Der "
              "Anteil der HS-getriebenen Schwankung wird mit Z_up berechnet und gilt nur mit dem über Z_hv "
              "korrigierten Instrument."},
    "transformer.iv_impedance_missing": {
        "en": "{name} has no value for the orders {orders}.",
        "de": "{name} enthält keinen Wert für die Ordnungen {orders}."},
    "transformer.iv_ct_angle_missing": {
        "en": "No angle error of the current transformers for the orders {orders} – give one value per order or one "
              "for all.",
        "de": "Kein Winkelfehler der Stromwandler für die Ordnungen {orders} – je Ordnung einen Wert oder einen für "
              "alle angeben."},
    "transformer.channel_unknown": {
        "en": "Channel {channel!r} not found (or not unique). Channels: {names}",
        "de": "Kanal {channel!r} nicht gefunden (oder nicht eindeutig). Kanäle: {names}"},
    "transformer.iv_weak": {
        "en": "Orders {orders}: the HV voltage drives too little of the variation (correlation below {corr:g}) or the "
              "result is not passive – not reliable; longer undisturbed ranges help.",
        "de": "Ordnungen {orders}: Die HS-Spannung treibt zu wenig der Schwankung (Korrelation unter {corr:g}) oder das "
              "Ergebnis ist nicht passiv – nicht verlässlich; längere ungestörte Bereiche helfen."},
})


# German column names of the tables of the MV network from undisturbed operation
i18n.register_labels(
    columns={"Z_low_Ohm": "Z_unten_Ohm", "Z_high_Ohm": "Z_oben_Ohm", "angle_low_deg": "Winkel_unten_deg",
             "angle_high_deg": "Winkel_oben_deg", "corr_I_hv": "Korrelation_I_HS", "corr_U_hv": "Korrelation_U_HS",
             "hv_share": "HS_Anteil", "instrument": "Instrument", "reliable": "verlaesslich",
             "recording": "Aufzeichnung", "start": "Beginn", "recordings": "Aufzeichnungen", "names": "Namen",
             "angle_deg": "Winkel_deg", "I_reference_A": "I_Referenz_A", "reference_reversed": "Referenz_umgekehrt"},
    values={"instrument": {"U_hv": "U_HS", "E_hv": "E_HS (korrigiert)"}})


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


def is_natural(m: int, sequence: str) -> bool:
    """True if ``sequence`` is the natural sequence of order m (m mod 3 = 1: positive, m mod 3 = 2: negative, m mod 3
    = 0: zero sequence) – the sequence in which the harmonic of a symmetrical source appears in normal operation and
    in which the pre-fault harmonic voltage is large."""
    return sequence == ("zero", "pos", "neg")[int(m) % 3]


def _summary_rows(z: dict, orders: Sequence[int]) -> Tuple[List[Tuple[int, int]], bool]:
    """Entries of the summary value X_up/m: the significant entries of the sequence other than the natural one
    (m = 5, 11 …: positive, m = 7, 13 …: negative sequence; ``True``) – the pre-fault harmonic of the natural
    sequence is ten to a hundred times larger, and its drift between the states enters ΔU and ΔI –, without such
    an entry all entries of the polarity decision, both sequences (``False``)."""
    rows = _decision_rows(z, orders)
    other = [(s, j) for s, j in rows if not is_natural(orders[j], SEQUENCES[s])]
    return (other, True) if other else (rows, False)


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


# ====================================================================== voltage divider (HV and MV voltages)
def voltage_windows(block, roles, orders: Sequence[int], windows: Optional[np.ndarray] = None) -> Optional[dict]:
    """Per window of an interval: symmetrical components of the MV and the HV line-to-earth voltages per order,
    referred to the fundamental of U_L1-L2 of the MV voltages of the window.

    Returns
    -------
    dict or None
        ``mv`` and ``hv`` – arrays (windows × 3 sequences × orders) – and ``t`` (window centres in s); None without
        both voltage sets or without a window.
    """
    mv, hv = roles.line_to_earth, roles.line_to_earth_hv
    if block is None or mv is None or hv is None:
        return None
    ok = ~block.nan_window if windows is None else (np.asarray(windows, bool) & ~block.nan_window)
    if not ok.any():
        return None
    ix = [block.ix(int(m)) for m in orders]
    X = block.X[ok]
    ref = X[:, mv[0], block.ix(1)] - X[:, mv[1], block.ix(1)]
    rot = np.exp(-1j * np.outer(np.angle(ref), np.asarray(orders, float)))[:, None, :]
    out = dict(t=block.t_mid[ok])
    for name, ch in (("mv", mv), ("hv", hv)):
        U = X[:, ch, :][:, :, ix] * rot
        out[name] = np.stack(fortescue(U[:, 0], U[:, 1], U[:, 2]), axis=1)
    return out


def _voltage_means(w: dict) -> dict:
    n = int(w["mv"].shape[0])
    dof = max(n - 1, 1) * n
    out = dict(n=n)
    for name in ("mv", "hv"):
        U = w[name].mean(axis=0)
        out[name] = U
        out["se_" + name] = np.sqrt((np.abs(w[name] - U) ** 2).sum(axis=0) / dof)
    return out


def voltage_divider(res) -> None:
    """Share of the HV network in the upstream impedance from the HV and MV voltages of the same recording – table
    ``transformer_divider`` and ``res.values["transformer_divider"]``.

    Per order m ≥ 2 not divisible by 3 and sequence s (positive, negative) the fault-related changes of the MV
    voltage and of the HV voltage referred to the MV side form a voltage divider,

        k_s,m = (ΔU_HV,s,m / (t·e^{±jk·30°})) / ΔU_MV,s,m = Z_HV,m / (Z_T,m + Z_HV,m),

    with the ratio t and the vector group k from the fundamental of the positive sequence (negative sequence: −k).
    It needs no transformer currents: a recording of the HV and MV busbar voltages alone gives the share of the HV
    network. With the transformer currents in the recording ([`node_analysis`][groundfault.transformer.node_analysis]
    first) the table also gives Z_HV = k·Z_up and Z_T = (1 − k)·Z_up – a second method beside Z_HV from the HV
    voltage and the transformer current.

    Columns: ``order``, ``f_Hz``, ``sequence``, ``natural_sequence``, ``dU_V`` (MV), ``dU_hv_V`` (HV referred to the
    MV side), ``k``, ``k_angle_deg``, ``uncertainty_pct`` (from the spread of the windows and, with a pre- and a
    post-fault interval, the null test of both voltages), ``significant`` (≤
    [`SIGNIFICANCE`][groundfault.transformer.SIGNIFICANCE]); with Z_up also ``Z_hv_Ohm``, ``Z_hv_angle_deg``,
    ``X_hv_per_order_Ohm``, ``Z_transformer_Ohm``, ``Z_transformer_angle_deg``, ``X_transformer_per_order_Ohm``.
    The summary value ``k`` (and ``X1_hv_Ohm``, ``X1_transformer_Ohm`` with Z_up) is the 1/uncertainty²-weighted
    mean over the significant orders in the sequence other than the natural one, as for X_up/m.

    Parameters
    ----------
    res : Result
        Evaluation result with the line-to-earth voltages of the MV and of the HV side.
    """
    roles, e = res.roles, res.settings
    if roles.line_to_earth is None or roles.line_to_earth_hv is None:
        return
    st = res.steady_state
    orders = [m for m in sorted(set(int(x) for x in e.export_orders) | {1}) if m in st.orders]
    blocks = {"pre_fault": res.pre_fault, "fault": st, "post_fault": res.post_fault}
    masks = {"fault": res.reference_windows}
    means = {}
    for s_name, b in blocks.items():
        w = voltage_windows(b, roles, orders, masks.get(s_name))
        if w is not None:
            means[s_name] = _voltage_means(w)
    base_name = "pre_fault" if "pre_fault" in means else ("post_fault" if "post_fault" in means else None)
    if "fault" not in means or base_name is None:
        return
    ref = means[base_name]
    t = ref["hv"][1, 0] / ref["mv"][1, 0]
    if not (np.isfinite(t) and abs(t) > 0):
        return
    ratio, group = float(abs(t)), int(round(np.degrees(np.angle(t)) / 30.0)) % 12
    f, b = means["fault"], means[base_name]
    post = means.get("post_fault") if base_name == "pre_fault" else None
    zup = {}
    zi = res.tables.get("transformer_impedance")
    if zi is not None and not zi.empty:
        for _, r in zi.iterrows():
            z = r["Z_up_Ohm"] * np.exp(1j * np.radians(r["Z_up_angle_deg"]))
            if np.isfinite(z):
                zup[(int(r["order"]), r["sequence"])] = complex(z)
    f1 = st.f1["f1_used"]
    rows, est = [], []
    for j, m in enumerate(orders):
        if m < 2 or m % 3 == 0:
            continue
        for q in (1, 2):
            fac = _hv_factor(q, ratio, group)
            dmv = f["mv"][q, j] - b["mv"][q, j]
            dhv = (f["hv"][q, j] - b["hv"][q, j]) / fac
            d_mv = np.hypot(f["se_mv"][q, j], b["se_mv"][q, j])
            d_hv = np.hypot(f["se_hv"][q, j], b["se_hv"][q, j]) / ratio
            if post is not None:
                d_mv = max(d_mv, abs(post["mv"][q, j] - b["mv"][q, j]))
                d_hv = max(d_hv, abs(post["hv"][q, j] - b["hv"][q, j]) / ratio)
            with np.errstate(divide="ignore", invalid="ignore"):
                k = dhv / dmv
                u = float(np.hypot(d_mv / abs(dmv), d_hv / abs(dhv)))
            seq = SEQUENCES[q]
            sig = bool(np.isfinite(u) and u <= SIGNIFICANCE and np.isfinite(k))
            r = dict(order=m, f_Hz=m * f1, sequence=seq, natural_sequence=is_natural(m, seq), dU_V=_f(abs(dmv)),
                     dU_hv_V=_f(abs(dhv)), k=_f(abs(k)), k_angle_deg=_deg(k), uncertainty_pct=_f(100 * u),
                     significant=sig)
            z = zup.get((m, seq))
            if z is not None:
                zh, zt = k * z, (1 - k) * z
                r.update(Z_hv_Ohm=_f(abs(zh)), Z_hv_angle_deg=_deg(zh), X_hv_per_order_Ohm=_f(zh.imag / m),
                         Z_transformer_Ohm=_f(abs(zt)), Z_transformer_angle_deg=_deg(zt),
                         X_transformer_per_order_Ohm=_f(zt.imag / m))
            rows.append(r)
            if sig:
                est.append((m, seq, k, u, z))
    res.tables["transformer_divider"] = pd.DataFrame(rows)
    other = [x for x in est if not is_natural(x[0], x[1])]
    use = other or est
    vals = dict(ratio=ratio, group=group, shift_deg=30.0 * group, k_count=len(use), k_other_sequence=bool(other))
    if use:
        wgt = np.array([1.0 / max(x[3], 1e-3) ** 2 for x in use])
        kk = np.array([abs(x[2]) for x in use])
        k1 = float(np.sum(wgt * kk) / np.sum(wgt))
        vals.update(k=k1, k_spread=float(np.sqrt(np.sum(wgt * (kk - k1) ** 2) / np.sum(wgt)) / k1) if k1 else
                    float("nan"))
        withz = [(x, wi) for x, wi in zip(use, wgt) if x[4] is not None]
        if withz:
            ww = np.array([wi for _, wi in withz])
            xh = np.array([(x[2] * x[4]).imag / x[0] for x, _ in withz])
            xt = np.array([((1 - x[2]) * x[4]).imag / x[0] for x, _ in withz])
            vals.update(X1_hv_Ohm=float(np.sum(ww * xh) / np.sum(ww)), X1_transformer_Ohm=float(np.sum(ww * xt) / np.sum(ww)))
    res.values["transformer_divider"] = vals


# ====================================================================== MV network from undisturbed operation
IV_MIN_CORRELATION = 0.3
"""Smallest correlation between the transformer current and the HV voltage (the instrument) for which
[`mv_network_impedance`][groundfault.transformer.mv_network_impedance] marks an estimate as reliable – below it the
HV side drives too little of the variation."""
IV_MAX_ANGLE_DEG = 45.0
"""Largest angle of a plausible MV network impedance in
[`mv_network_impedance`][groundfault.transformer.mv_network_impedance]: the cables make the MV network capacitive at
the harmonic orders, the loads add damping. A strongly inductive result is the upstream impedance – the variation was
driven from the MV side, and the HV voltage only followed it through the HV network."""


def _iv_estimate(U: np.ndarray, I: np.ndarray, H: np.ndarray) -> np.ndarray:
    """Z = Σ ΔU·ΔH* / Σ ΔI·ΔH* over the first axis (windows)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return (U * np.conj(H)).sum(axis=0) / (I * np.conj(H)).sum(axis=0)


def _impedance_per_order(Z, orders: Sequence[int], name: str) -> np.ndarray:
    """Impedance per order from ``{order: Z}`` or from one value at the fundamental, Z(m) = R + j·m·X."""
    if isinstance(Z, dict):
        table = {int(m): complex(v) for m, v in Z.items()}
        missing = [m for m in orders if m not in table]
        if missing:
            raise ValueError(tr("transformer.iv_impedance_missing", name=name, orders=missing))
        return np.array([table[m] for m in orders])
    z = complex(Z)
    return np.array([complex(z.real, m * z.imag) for m in orders])


def _angles_per_order(angle_deg, orders: Sequence[int]) -> np.ndarray:
    """Angle error of the current transformers per order in degrees: one value for all orders, ``{order: angle}``
    or the table of [`ct_angle_from_reference`][groundfault.transformer.ct_angle_from_reference]."""
    if angle_deg is None:
        return np.zeros(len(orders))
    if isinstance(angle_deg, pd.DataFrame):
        table = {int(m): float(a) for m, a in zip(angle_deg["order"], angle_deg["angle_deg"])}
    elif isinstance(angle_deg, (dict, pd.Series)):
        table = {int(m): float(a) for m, a in angle_deg.items()}
    else:
        return np.full(len(orders), float(angle_deg))
    missing = [m for m in orders if m not in table or not math.isfinite(table[m])]
    if missing:
        raise ValueError(tr("transformer.iv_ct_angle_missing", orders=missing))
    return np.array([table[m] for m in orders])


def mv_network_impedance(recordings, orders: Sequence[int] = (5, 7), intervals=None, settings=None, roles=None,
                         sign: Optional[float] = None, Z_hv=None, Z_up=None, ct_angle_deg=None, n_boot: int = 1000,
                         block_windows: int = 10, seed: int = 0, min_correlation: float = IV_MIN_CORRELATION,
                         max_angle_deg: float = IV_MAX_ANGLE_DEG,
                         min_hv_share: Optional[float] = None) -> pd.DataFrame:
    """Impedance of the MV network seen from the busbar per order, Z_MV = ΔU/ΔI, from undisturbed operation – with
    the HV voltage as instrumental variable.

    In undisturbed operation the harmonic voltages of the busbar vary because the sources on both sides vary: those
    of the HV network (behind the upstream impedance Z_up) and those of the MV network. A variation driven from the HV
    side changes busbar voltage and transformer current by ΔU = Z_MV·ΔI (current from the HV into the MV network),
    one driven from the MV side by ΔU = −Z_up·ΔI. The ratio U/I of the undisturbed transformer node mixes both and
    shows neither. The HV voltage follows the HV sources – the MV sources change it only through the small HV
    share of Z_up – and serves as instrument: with the deviations of the windows from the mean of their interval,

        Z_MV = Σ ΔU·ΔU_HV* / Σ ΔI·ΔU_HV*

    per order and sequence. Z_MV is the MV network with its damping – the quantity that sets the harmonic fault
    current near the parallel resonance of the busbar and that the earth fault otherwise gives (Y_MV = 1/Z_1 −
    1/Z_up). G and B are the conductance and susceptance of Y_MV = 1/Z_MV.

    The MV sources still reach the HV voltage through the HV network: ΔU_HV = −Z_HV·ΔI for a variation driven from
    the MV side (referred to the MV side). Where they dominate the variation, this biases the estimate. With the
    impedance of the HV network ``Z_hv`` (from S″_k or from the fault evaluation of the same transformer) the
    instrument becomes the voltage of the HV source, E = U_HV/(t·e^{±jk·30°}) + Z_HV·I, which the MV sources do not
    change; the ratio t and the vector group k come from the fundamental.

    **Share of the HV-driven variation.** The estimate holds only if the HV network drives a fair share of the
    variation. With the upstream impedance ``Z_up`` the recording itself shows that share: ΔU + Z_up·ΔI is the
    variation of the HV source referred to the MV side, and Z_MV/(Z_up + Z_MV) of it reaches the busbar, so

        s_HV = |Z_MV/(Z_up + Z_MV)|²·Σ|ΔU + Z_up·ΔI|² / Σ|ΔU|²

    is the share of the HV-driven variation in the variance of the busbar voltage (column ``hv_share``). The square of
    ``corr_U_hv`` estimates the same share without Z_up (the part of the busbar voltage that varies with the
    instrument). Both hold only with the corrected instrument (``Z_hv``): with the HV voltage itself as instrument
    the MV variations that reach it through the HV network make the estimate drift towards −Z_up where the MV side
    dominates, and the share is then overestimated. Neither the mean harmonic power flow through the transformer nor
    its direction shows the share: the level may come mainly from either side, and the active power of the
    variation flows into the MV network as long as the MV network carries most of the damping.

    **Angle error of the current transformers.** Z_MV is capacitive with a damping that is small against its
    susceptance near the resonance, so a few degrees of angle error of the transformer current change G
    noticeably (about 1–2.5 % of the forecast current per degree). ``ct_angle_deg`` – e.g. from a reference clamp,
    [`ct_angle_from_reference`][groundfault.transformer.ct_angle_from_reference] – rotates the current phasors back
    before the estimate.

    Parameters
    ----------
    recordings : Recording, str or sequence
        Recording(s) with the transformer line currents (``i_l1`` … ``i_l3``, MV side), the MV busbar voltages
        (``u_l1e`` …) and the HV voltages (``u_hv_l1e`` …) in one device; a path opens the ``.cfg`` file. Several
        recordings are pooled (same transformer, same polarity of the current transformers).
    orders : sequence of int, optional
        Orders (computed by the window analysis of ``settings``).
    intervals : list, optional
        Undisturbed time ranges in s, ``[(t0, t1), …]`` for one recording or one such list per recording; None = the
        whole recording. For a recording of an earth fault: the pre-fault and post-fault ranges.
    settings : Settings, optional
        Window analysis (window length, frequency estimation); default ``Settings()``.
    roles : RoleAssignment, optional
        Channel roles (default: detected from the channel names of each recording).
    sign : float, optional
        Factor of the currents to the consumer reference arrow system of the MV network (+1 as measured, −1
        reversed). None: from the passivity of the result – Z_MV has a positive real part; the hints say so.
    Z_hv : complex or dict, optional
        Impedance of the HV network referred to the MV side: a value at the fundamental (Z(m) = R + j·m·X) or
        ``{order: Z in Ω}``. None: the HV voltage itself is the instrument.
    Z_up : complex or dict, optional
        Upstream impedance (transformer and HV network) referred to the MV side, as ``Z_hv``: a value at the
        fundamental or ``{order: Z in Ω}``. Needed for the share of the HV-driven variation (``hv_share``).
    ct_angle_deg : float, dict or pandas.DataFrame, optional
        Angle error of the current transformers of the transformer currents in degrees – phase of the measured minus
        phase of the true current: one value for all orders, ``{order: angle}`` or the table of
        [`ct_angle_from_reference`][groundfault.transformer.ct_angle_from_reference]. The current phasors are rotated
        back by it. None: no correction.
    n_boot : int, optional
        Bootstrap replications for the 5–95 % range (blocks of ``block_windows`` consecutive windows).
    block_windows : int, optional
        Block length of the bootstrap in windows (the variations are correlated over neighbouring windows).
    seed : int, optional
        Seed of the bootstrap.
    min_correlation : float, optional
        Smallest correlation between transformer current and HV voltage of a reliable estimate.
    max_angle_deg : float, optional
        Largest angle of a reliable estimate (see [`IV_MAX_ANGLE_DEG`][groundfault.transformer.IV_MAX_ANGLE_DEG]).
    min_hv_share : float, optional
        Smallest share of the HV-driven variation (``hv_share``) of a reliable estimate – a value you define; needs
        ``Z_up`` and ``Z_hv``. None: the share is listed but not assessed.

    Returns
    -------
    pandas.DataFrame
        One row per order and sequence (``pos``, ``neg``): ``order``, ``sequence``, ``natural_sequence``,
        ``windows``, ``Z_Ohm``, ``Z_angle_deg``, ``R_Ohm``, ``X_Ohm``, ``G_S``, ``B_S``, the bootstrap ranges
        ``Z_low_Ohm``, ``Z_high_Ohm``, ``angle_low_deg``, ``angle_high_deg``, the correlations ``corr_I_hv`` (strength
        of the instrument) and ``corr_U_hv``, ``hv_share`` (NaN without ``Z_up``), ``instrument`` (``U_hv`` or
        ``E_hv``) and ``reliable``. ``df.attrs`` holds ``sign``, ``ratio``, ``group``, ``ct_angle_deg`` (per order),
        ``min_hv_share`` and ``hints``.

    Raises
    ------
    ValueError
        If a recording lacks transformer currents, MV or HV voltages, if an order is not computed, if no window is
        left, if ``ct_angle_deg``, ``Z_hv`` or ``Z_up`` lack an order, or if ``min_hv_share`` is given without
        ``Z_up`` and ``Z_hv``.

    Notes
    -----
    The estimate needs variations driven from the HV side. If the MV side drives nearly all of them, the HV voltage
    only follows the current through the HV network, the correlation stays high and the estimate becomes the upstream
    impedance −Z_up: inductive instead of capacitive – such rows are not reliable (``max_angle_deg``), and the
    polarity is best taken from the evaluation of an earth fault of the same recorder (``sign``). Between these
    limits the correlation and the angle do not show a dominant MV side; ``hv_share`` does. The precision grows with
    the duration: roughly (MV-driven/HV-driven variation)/√(number of independent fluctuations); minutes of
    undisturbed operation give about ±10 % at the dominant order, seconds are not enough – the bootstrap range shows
    it. Evaluate the natural sequence of an order (column ``natural_sequence``): the other sequence varies little.
    Systematic limits: an MV source whose emission follows the HV voltage is treated as part of the MV network, and
    without ``Z_hv`` the HV share of Z_up couples the MV variations weakly into the instrument.
    """
    from .channels import detect_roles
    from .comtrade import open_recording
    from .evaluation import Settings, _analyse, load_blocks

    e = settings or Settings()
    recs = list(recordings) if isinstance(recordings, (list, tuple)) else [recordings]
    if intervals is None:
        ivs = [None] * len(recs)
    elif len(recs) == 1 and len(intervals) and np.ndim(intervals[0]) == 1 and not isinstance(intervals[0][0],
                                                                                              (list, tuple)):
        ivs = [list(intervals)]
    else:
        ivs = list(intervals)
    if len(ivs) != len(recs):
        raise ValueError(tr("transformer.iv_intervals", n=len(recs), k=len(ivs)))
    orders = [int(m) for m in orders]
    if min_hv_share is not None and (Z_up is None or Z_hv is None):
        raise ValueError(tr("transformer.iv_share_needs_z"))
    ct_angles = _angles_per_order(ct_angle_deg, orders)
    z_up = _impedance_per_order(Z_up, orders, "Z_up") if Z_up is not None else None
    z_hv = _impedance_per_order(Z_hv, orders, "Z_hv") if Z_hv is not None else None
    rot = np.exp(-1j * np.radians(ct_angles))[None, None, :]
    parts = {"U": [], "I": [], "H": []}
    t_ratio = []
    for r, iv in zip(recs, ivs):
        rec = open_recording(r, emit_warnings=False) if isinstance(r, str) else r
        ro = roles if roles is not None else detect_roles(rec.channel_names, rec.units)
        if ro.line_currents is None or ro.line_to_earth is None or ro.line_to_earth_hv is None:
            raise ValueError(tr("transformer.iv_roles", name=os.path.basename(rec.cfg_path)))
        for t0, t1 in (iv or [(0.0, rec.duration_s)]):
            bl = load_blocks(rec, {"u": (float(t0), float(t1))})
            b = _analyse("undisturbed", *bl["u"], rec, ro, e)
            missing = [m for m in orders if m not in b.orders]
            if missing:
                raise ValueError(tr("transformer.iv_orders", orders=missing))
            mv = sequence_windows(b, ro, orders, "mv")
            hv = sequence_windows(b, ro, orders, "hv")
            if mv is None or hv is None or mv["U"].shape[0] < 2:
                continue
            parts["U"].append(mv["U"] - mv["U"].mean(axis=0))
            parts["I"].append((mv["I"] - mv["I"].mean(axis=0)) * rot)
            parts["H"].append(hv["U"] - hv["U"].mean(axis=0))
            f = voltage_windows(b, ro, [1])
            if f is not None:
                t_ratio.append(complex(np.mean(f["hv"][:, 1, 0] / f["mv"][:, 1, 0])))
    if not parts["U"]:
        raise ValueError(tr("transformer.iv_no_windows"))
    U, I, H = (np.concatenate(parts[k]) for k in ("U", "I", "H"))
    n = U.shape[0]
    tt = complex(np.median(np.real(t_ratio)), np.median(np.imag(t_ratio))) if t_ratio else complex("nan")
    ratio = float(abs(tt))
    group = int(round(np.degrees(np.angle(tt)) / 30.0)) % 12 if np.isfinite(tt) else 0

    def correlations(H_):
        with np.errstate(divide="ignore", invalid="ignore"):
            hh = (np.abs(H_) ** 2).sum(axis=0)
            c_i = np.abs((I * np.conj(H_)).sum(axis=0)) / np.sqrt((np.abs(I) ** 2).sum(axis=0) * hh)
            c_u = np.abs((U * np.conj(H_)).sum(axis=0)) / np.sqrt((np.abs(U) ** 2).sum(axis=0) * hh)
        return c_i, c_u

    Z = _iv_estimate(U, I, H)
    c_ih, c_uh = correlations(H)
    hints = []
    if sign is None:
        use = [(s, j) for s in (1, 2) for j, m in enumerate(orders)
               if m % 3 and np.isfinite(Z[s, j]) and c_ih[s, j] >= min_correlation]
        if use:
            c = sum(c_ih[s, j] * math.cos(np.angle(Z[s, j])) for s, j in use) / sum(c_ih[s, j] for s, j in use)
            sign = -1.0 if c < 0 else 1.0
            if sign < 0:
                hints.append(tr("transformer.iv_reversed"))
        else:
            sign = 1.0
            hints.append(tr("transformer.iv_sign_unknown"))
    sign = float(sign)
    instrument = "U_hv"
    if z_hv is not None and np.isfinite(ratio) and ratio > 0:
        fac = np.array([1.0, _hv_factor(1, ratio, group), _hv_factor(2, ratio, group)])[:, None]
        H = H / fac + z_hv[None, None, :] * sign * I        # voltage of the HV source, referred to the MV side
        instrument = "E_hv"
        Z = _iv_estimate(U, I, H)
        c_ih, c_uh = correlations(H)
    Z = Z / sign
    share = np.full(Z.shape, np.nan)
    if z_up is not None:
        with np.errstate(divide="ignore", invalid="ignore"):
            E_up = U + z_up[None, None, :] * sign * I            # HV source behind Z_up, from the MV side
            share = (np.abs(Z / (z_up[None, :] + Z)) ** 2 * (np.abs(E_up) ** 2).sum(axis=0)
                     / (np.abs(U) ** 2).sum(axis=0))
    # moving-block bootstrap over the windows
    rng = np.random.default_rng(seed)
    L = max(1, min(int(block_windows), n))
    nb = max(1, n // L)
    boot = np.empty((int(n_boot),) + Z.shape, complex)
    for k in range(int(n_boot)):
        starts = rng.integers(0, n - L + 1, nb)
        idx = (starts[:, None] + np.arange(L)[None, :]).ravel()
        boot[k] = _iv_estimate(U[idx], I[idx], H[idx]) / sign
    rows = []
    for s, s_name in ((1, "pos"), (2, "neg")):
        for j, m in enumerate(orders):
            z = complex(Z[s, j])
            zb = boot[:, s, j]
            zb = zb[np.isfinite(zb)]
            y = 1.0 / z if z != 0 and np.isfinite(z) else complex("nan")
            lo, hi = (np.percentile(np.abs(zb), [5, 95]) if zb.size else (np.nan, np.nan))
            alo, ahi = (np.percentile(np.degrees(np.angle(zb / z)), [5, 95]) + _deg(z) if zb.size and np.isfinite(z)
                        else (np.nan, np.nan))
            sh = _f(share[s, j])
            share_ok = min_hv_share is None or (math.isfinite(sh) and sh >= min_hv_share)
            ok = bool(np.isfinite(z) and c_ih[s, j] >= min_correlation and z.real > 0
                      and _deg(z) <= max_angle_deg and share_ok)
            rows.append(dict(order=m, sequence=s_name, natural_sequence=is_natural(m, s_name), windows=n,
                             Z_Ohm=abs(z), Z_angle_deg=_deg(z), R_Ohm=z.real, X_Ohm=z.imag, G_S=y.real, B_S=y.imag,
                             Z_low_Ohm=float(lo), Z_high_Ohm=float(hi), angle_low_deg=float(alo),
                             angle_high_deg=float(ahi), corr_I_hv=float(c_ih[s, j]), corr_U_hv=float(c_uh[s, j]),
                             hv_share=sh, instrument=instrument, reliable=ok))
    inductive = [r["order"] for r in rows if r["Z_angle_deg"] > max_angle_deg and r["order"] % 3]
    weak = [r["order"] for r in rows if r["order"] % 3 and r["order"] not in inductive
            and not (r["corr_I_hv"] >= min_correlation and r["R_Ohm"] > 0)]
    if inductive:
        hints.append(tr("transformer.iv_inductive", orders=sorted(set(inductive)), angle=max_angle_deg))
    if weak:
        hints.append(tr("transformer.iv_weak", orders=sorted(set(weak)), corr=min_correlation))
    if min_hv_share is not None:
        low = sorted((r["order"], r["hv_share"]) for r in rows if r["natural_sequence"] and r["order"] % 3
                     and r["order"] not in inductive and not (r["hv_share"] >= min_hv_share))
        if low:
            shares = ", ".join("m = %d: %s" % (m, i18n.format_number(v, 2, "decimals")) for m, v in low)
            hints.append(tr("transformer.iv_mv_driven", orders=[m for m, _ in low], shares=shares,
                            limit=min_hv_share))
    df = pd.DataFrame(rows)
    df.attrs["sign"] = sign
    df.attrs["ratio"] = ratio
    df.attrs["group"] = group
    df.attrs["ct_angle_deg"] = {m: float(a) for m, a in zip(orders, ct_angles)}
    df.attrs["min_hv_share"] = min_hv_share
    df.attrs["hints"] = hints
    return df


_IV_COLUMNS = ("order", "sequence", "natural_sequence", "windows", "Z_Ohm", "Z_angle_deg", "R_Ohm", "X_Ohm", "G_S", "B_S",
               "Z_low_Ohm", "Z_high_Ohm", "angle_low_deg", "angle_high_deg", "corr_I_hv", "corr_U_hv", "hv_share",
               "instrument", "reliable")


def mv_network_series(recordings, orders: Sequence[int] = (5, 7), intervals=None, settings=None, roles=None,
                      sign: Optional[float] = None, Z_hv=None, Z_up=None, ct_angle_deg=None, n_boot: int = 200,
                      block_windows: int = 10, seed: int = 0, min_correlation: float = IV_MIN_CORRELATION,
                      max_angle_deg: float = IV_MAX_ANGLE_DEG,
                      min_hv_share: Optional[float] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """A series of undisturbed recordings of the same transformer node – e.g. one every hour of a measuring day –
    each evaluated on its own, and the pooled estimate of the reliable ones.

    Every recording gives the impedance of the MV network with
    [`mv_network_impedance`][groundfault.transformer.mv_network_impedance] and its checks, in the natural sequence of
    each order. Whether a recording is reliable depends on who drove the variation during it, so it changes over the
    day; the share of the HV-driven variation (``hv_share``) shows it. The reliable recordings of an order are then
    pooled (the sums of all their windows, like one long recording) – the estimate for the forecast. Without ``sign``
    the polarity of the currents is taken once from all recordings together, so a recording driven from the MV side
    cannot turn it.

    Parameters
    ----------
    recordings : sequence
        Recordings or paths of ``.cfg`` files.
    orders, settings, roles, sign, Z_hv, Z_up, ct_angle_deg, n_boot, block_windows, seed, min_correlation, \
max_angle_deg, min_hv_share
        As in [`mv_network_impedance`][groundfault.transformer.mv_network_impedance].
    intervals : list, optional
        One list of undisturbed time ranges per recording (None = the whole recordings).

    Returns
    -------
    (pandas.DataFrame, pandas.DataFrame)
        Per recording and order (natural sequence): ``recording``, ``start`` (time of the recording if known) and the
        columns of [`mv_network_impedance`][groundfault.transformer.mv_network_impedance]; and per order the pooled
        estimate of the reliable recordings with ``recordings`` (their number) and ``names`` – NaN where no recording
        of the order is reliable. The first table's ``attrs`` hold ``sign`` and the ``hints`` per recording.

    Raises
    ------
    ValueError
        As [`mv_network_impedance`][groundfault.transformer.mv_network_impedance]; also if ``intervals`` does not
        have one entry per recording.
    """
    from .comtrade import open_recording

    recs = [open_recording(r, emit_warnings=False) if isinstance(r, str) else r for r in recordings]
    ivs = [None] * len(recs) if intervals is None else list(intervals)
    if len(ivs) != len(recs):
        raise ValueError(tr("transformer.iv_intervals", n=len(recs), k=len(ivs)))
    orders = [int(m) for m in orders]
    common = dict(settings=settings, roles=roles, Z_hv=Z_hv, Z_up=Z_up, ct_angle_deg=ct_angle_deg,
                  block_windows=block_windows, seed=seed, min_correlation=min_correlation,
                  max_angle_deg=max_angle_deg, min_hv_share=min_hv_share)
    if sign is None:
        sign = mv_network_impedance(recs, orders, intervals=ivs, n_boot=1, **common).attrs["sign"]
    rows, hints = [], {}
    for rec, iv in zip(recs, ivs):
        name = os.path.splitext(os.path.basename(rec.cfg_path))[0]
        df = mv_network_impedance(rec, orders, intervals=iv, sign=sign, n_boot=n_boot, **common)
        hints[name] = df.attrs["hints"]
        start = rec.t_start.isoformat(sep=" ") if getattr(rec, "t_start", None) else None
        for _, r in df[df.natural_sequence].sort_values("order").iterrows():
            rows.append(dict(recording=name, start=start, **r.to_dict()))
    table = pd.DataFrame(rows)
    pooled = []
    for m in orders:
        ok = table[(table.order == m) & table.reliable] if len(table) else table
        use = [rec for rec in recs if os.path.splitext(os.path.basename(rec.cfg_path))[0] in set(ok.recording)]
        if use:
            sel = [iv for rec, iv in zip(recs, ivs) if rec in use]
            df = mv_network_impedance(use, [m], intervals=sel, sign=sign, n_boot=n_boot, **common)
            row = df[df.natural_sequence].iloc[0].to_dict()
        else:
            row = {c: float("nan") for c in _IV_COLUMNS}
            row.update(order=m, sequence="pos" if is_natural(m, "pos") else "neg", natural_sequence=True, windows=0,
                       instrument="", reliable=False)
        row.update(recordings=len(use), names=", ".join(os.path.splitext(os.path.basename(r.cfg_path))[0] for r in use))
        pooled.append(row)
    pooled = pd.DataFrame(pooled)
    table.attrs["sign"] = float(sign)
    table.attrs["hints"] = hints
    return table, pooled


def _channel_index(rec, channel) -> int:
    """Index of a channel given by its index, its full name, its short name or a unique part of its name."""
    try:
        return rec.index(channel)
    except (IndexError, KeyError):
        raise ValueError(tr("transformer.channel_unknown", channel=channel,
                            names=", ".join(rec.channel_names))) from None


def ct_angle_from_reference(recording, channel, reference, orders: Sequence[int] = (5, 7), interval=None,
                            settings=None) -> pd.DataFrame:
    """Angle and ratio error of a current channel per order against a reference clamp on the same conductor.

    Record the channel (e.g. the transformer current of L1 through its current transformer) and a reference current
    clamp with a known small angle error on the same conductor in one device for a few minutes. Per 200-ms window and
    order the ratio of the two phasors is the error of the channel against the reference; over the windows

        φ_m = arg Σ I_channel,m·I_reference,m*,   ratio_m = |Σ I_channel,m·I_reference,m*| / Σ |I_reference,m|²

    (each window weighted with its current). Give the result to
    [`mv_network_impedance`][groundfault.transformer.mv_network_impedance] as ``ct_angle_deg``. A reference clamp
    connected the other way round is recognised from the fundamental (column ``reference_reversed``).

    Parameters
    ----------
    recording : Recording or str
        Recording with both channels; a path opens the ``.cfg`` file.
    channel, reference : int or str
        The channel to check and the reference: index, full channel name or short name (e.g. ``"I1"``).
    orders : sequence of int, optional
        Orders (computed by the window analysis of ``settings``).
    interval : tuple, optional
        Time range ``(t0, t1)`` in s; None = the whole recording.
    settings : Settings, optional
        Window analysis; default ``Settings()``.

    Returns
    -------
    pandas.DataFrame
        One row per order: ``order``, ``f_Hz``, ``windows``, ``angle_deg`` (channel minus reference), the 5–95 % range
        of the window angles ``angle_low_deg`` and ``angle_high_deg`` (windows with at least half the median current),
        ``ratio``, ``I_reference_A`` (mean RMS value of the order) and ``reference_reversed``.

    Raises
    ------
    ValueError
        If a channel is unknown or an order is not computed.
    """
    from .comtrade import open_recording
    from .evaluation import Settings, _analyse, load_blocks
    from .channels import detect_roles

    e = settings or Settings()
    rec = open_recording(recording, emit_warnings=False) if isinstance(recording, str) else recording
    j_ch, j_ref = _channel_index(rec, channel), _channel_index(rec, reference)
    t0, t1 = interval if interval is not None else (0.0, rec.duration_s)
    ro = detect_roles(rec.channel_names, rec.units)
    bl = load_blocks(rec, {"u": (float(t0), float(t1))})
    b = _analyse("reference", *bl["u"], rec, ro, e)
    orders = [int(m) for m in orders]
    missing = [m for m in orders if m not in b.orders]
    if missing:
        raise ValueError(tr("transformer.iv_orders", orders=missing))
    ok = ~b.nan_window
    X = b.X[ok]
    x1 = (X[:, j_ch, b.ix(1)] * np.conj(X[:, j_ref, b.ix(1)])).sum()
    reversed_ = bool(np.isfinite(x1) and np.cos(np.angle(x1)) < 0)
    pol = -1.0 if reversed_ else 1.0
    f1 = b.f1["f1_used"]
    rows = []
    for m in orders:
        a = X[:, j_ch, b.ix(m)]
        r = pol * X[:, j_ref, b.ix(m)]
        cross = (a * np.conj(r)).sum()
        mag = np.abs(r)
        big = mag >= 0.5 * np.median(mag) if mag.size else mag.astype(bool)
        ang = np.degrees(np.angle(a[big] / r[big])) if big.any() else np.array([np.nan])
        phi = float(np.degrees(np.angle(cross)))
        ang = (ang - phi + 180.0) % 360.0 - 180.0 + phi                      # unwrap around the mean
        rows.append(dict(order=m, f_Hz=m * f1, windows=int(ok.sum()), angle_deg=phi,
                         angle_low_deg=float(np.percentile(ang, 5)), angle_high_deg=float(np.percentile(ang, 95)),
                         ratio=_f(abs(cross) / (mag ** 2).sum()), I_reference_A=_f(np.sqrt(np.mean(mag ** 2))),
                         reference_reversed=reversed_))
    return pd.DataFrame(rows)


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

    ``transformer_impedance`` – per order, positive and negative sequence (``natural_sequence``: True for the
    natural sequence of the order, see [`is_natural`][groundfault.transformer.is_natural]): ``dU_V``, ``dI_A``
    (fault-related change),
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
                r = dict(order=m, f_Hz=m * f1["fault"], sequence=SEQUENCES[q], natural_sequence=is_natural(m, SEQUENCES[q]),
                         dU_V=_f(abs(z["dU"][q, j])),
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
        rows_d, other = _summary_rows(z, orders)
        if rows_d:
            x = np.array([z["Z"][s, j].imag / orders[j] for s, j in rows_d])
            wgt = np.array([1.0 / max(z["u_rel"][s, j], 1e-3) ** 2 for s, j in rows_d])
            x1 = float(np.sum(wgt * x) / np.sum(wgt))
            spread = float(np.sqrt(np.sum(wgt * (x - x1) ** 2) / np.sum(wgt)) / abs(x1)) if x1 else float("nan")
            vals.update(X1_up_Ohm=x1, X1_up_spread=spread, X1_up_count=len(rows_d), X1_up_other_sequence=other)
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
    """Rows of the plausibility table for the transformer node (polarity, upstream impedance, HV side) and the
    voltage divider of HV and MV voltages."""
    out = _node_rows(res)
    d = res.values.get("transformer_divider")
    if d:
        if d.get("k_count"):
            val = tr("transformer.value_divider", k=d["k"], count=d["k_count"], spread=100 * d.get("k_spread", np.nan))
            if "X1_hv_Ohm" in d:
                val = tr("transformer.value_divider_x", base=val, xh=d["X1_hv_Ohm"], xt=d["X1_transformer_Ohm"])
        else:
            val = tr("transformer.value_divider_none")
        out.append(dict(check=tr("transformer.check_divider"), status="INFO", value=val,
                        comment=tr("transformer.divider_comment")))
    return out


def _node_rows(res) -> List[dict]:
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
            val = tr("transformer.value_upstream_other" if v.get("X1_up_other_sequence") else
                     "transformer.value_upstream", x1=v["X1_up_Ohm"], count=v["X1_up_count"],
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
