# -*- coding: utf-8 -*-
"""Equivalent-source method: active two-terminal (Thevenin) equivalent per harmonic order from a series of staged
fault tests with different additional impedances (fault resistances).

The input data are the **result files** of the single evaluations (``<name>_result.json``, German layout
``<name>_ergebnis.json``), one file per additional impedance Z_k (e.g. 0 / 2.5 / 5 Ω). Readable formats:

* result files of groundfault (format ``groundfault-result``, version 3) and of the predecessor tool
  (``erdschluss-ergebnis``, version 2),
* legacy JSON exports of earlier in-house evaluation notebooks (read for backward compatibility): exports with the
  structure of the result files but without a format tag (format code ``"legacy_notebook"``) and complex exports
  with pre-fault/fault/post-fault phasors per frequency (format code ``"legacy_complex"``).

The evaluation proceeds in six steps:

1. **Common angle reference** – every phasor X_m of order m is rotated to X_m·e^(−j·m·φ_LL1) (φ_LL1 = angle of
   the fundamental of U_L1 − U_L2 in the evaluated window).
2. **Polarity** – the active component of the fundamental must be positive (Iw > 0).
3. **Normalization of the source fluctuation** – the harmonic level of the network changes between the
   measurements (minutes apart). Each current is referred to the level measured at the same time before/after
   the fault: complex (magnitude and phase) or magnitude only. The reference quantity is the natural sequence
   voltage *at the faulted phase* (L2/L3: rotation by ±120°): physically the equivalent source U_q is the
   pre-fault voltage of the faulted phase (Thevenin), Z_q = (Z_1 + Z_2 + Z_0)/3.
4. **Two-terminal fit** – U_q = I_k·(Z_q + Z_k) for all k. Two independent estimators are compared: *equation
   error* (linear least squares, as in the predecessor tool) and *output error* (nonlinear, minimises the current
   deviation). Optionally R_q ≥ 0.
5. **Checks** – pairwise solution of every two measurements, residuals, jackknife, Monte Carlo uncertainty,
   condition number, interpolation or extrapolation.
6. **Residual current** – I_RES(Z_E) = √(I_G² + Σ|U_q,n·k_n/(Z_q,n + Z_E)|² + I_rest²) with the scaling k_n to
   the 95 % quantile of the harmonic voltage. I_rest = harmonic content not covered by the two-terminal
   equivalents (measured I_H minus the fitted orders, largest value of the series – conservative). Extension:
   fault behind a line (Z_1L, Z_0L).
"""
from __future__ import annotations

import itertools
import json
import math
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from . import i18n
from .i18n import tr
from .legacy import RESULT_FORMAT, LEGACY_RESULT_FORMAT, check_option, is_legacy_result, translate_result
from .symmetrical import A as _A, A2 as _A2

try:
    from scipy.optimize import least_squares as _least_squares
except Exception:  # pragma: no cover
    _least_squares = None

__all__ = ["SourceMeasurement", "SourceFit", "SourceSeries", "load_measurement", "load_series",
           "natural_sequence", "phase_factor", "fit_equation_error", "fit_output_error", "fit_rq0",
           "fit_equivalent_source", "ires_at_impedance", "ires_over_line", "monte_carlo", "SEQUENCES",
           "SEQUENCE_LEGACY"]

SEQUENCES = ("pos", "neg", "zero")
"""Sequence codes: positive, negative and zero sequence."""
SEQUENCE_LEGACY = {3: "zero", 5: "neg", 7: "pos"}
"""Simplified sequence assignment of earlier evaluations (``sequence="legacy"``): 3rd order zero, 5th negative, 7th
positive sequence, all other orders negative sequence."""

#: accepted spellings of the ``normalization`` parameter (lower case) → value
_NORMALIZATIONS = {"complex": "complex", "complex_": "complex", "magnitude": "magnitude", "none": None}
#: estimators of the two-terminal fit that can be selected with ``method``
_METHODS = ("equation_error", "output_error")
#: levels used for the normalization (``reference``)
_LEVELS = ("mean", "pre_fault", "post_fault")

i18n.register({
    # ---- loading result files
    "equivalent_source.roles_missing": {
        "en": "{file}: roles missing in the export: {roles}",
        "de": "{file}: Rollen fehlen im Export: {roles}"},
    "equivalent_source.pre_post_reference": {
        "en": "Pre-/post-fault phasors refer to L1-L2; another reference only for the fault window.",
        "de": "Vor-/Nachfehlerphasoren sind auf L1-L2 bezogen; anderer Bezug nur für Fehlerfenster."},
    "equivalent_source.legacy_complex": {
        "en": "Legacy complex format: angles per frequency refer to U_L12 of the same frequency; level "
              "normalization only possible with magnitudes.",
        "de": "Altformat (komplexer Export): Winkel je Frequenz auf U_L12 derselben Frequenz bezogen; "
              "Pegelnormierung nur über Beträge möglich."},
    "equivalent_source.angle_reference_per_order": {
        "en": "Angle reference per order: U_L12,m (convention of the legacy complex exports, for comparisons only)",
        "de": "Winkelbezug je Ordnung auf U_L12,m (Konvention der alten komplexen Exporte, nur für Vergleiche)"},
    "equivalent_source.unknown_format": {
        "en": "Unknown result format: {path}",
        "de": "Unbekanntes Ergebnisformat: {path}"},
    "equivalent_source.polarity_rotated": {
        "en": "Current phasors rotated by 180° (Iw < 0).",
        "de": "Stromphasoren um 180° gedreht (Iw < 0)."},
    # ---- parameters
    "equivalent_source.too_few_measurements": {
        "en": "At least two measurements with different additional impedances are needed.",
        "de": "Mindestens zwei Messungen mit verschiedener Zusatzimpedanz nötig."},
    "equivalent_source.equal_impedances": {
        "en": "The additional impedances must differ (Z1 ≠ Z2).",
        "de": "Die Zusatzimpedanzen müssen sich unterscheiden (Z1 ≠ Z2)."},
    # ---- hints of the series
    "equivalent_source.auto_orders_skipped": {
        "en": "Automatic selection: orders {orders} skipped (even order or ≥ {min_current:.1f} A in only one "
              "measurement) – specify the orders explicitly if needed",
        "de": "Auto-Auswahl: Ordnungen {orders} ausgelassen (gerade Ordnung oder nur in einer Messung "
              "≥ {min_current:.1f} A) – bei Bedarf die Ordnungen (orders) explizit angeben"},
    "equivalent_source.orders_missing": {
        "en": "Orders not in all files: {orders}",
        "de": "Ordnungen nicht in allen Dateien: {orders}"},
    "equivalent_source.phases_differ_normalized": {
        "en": "Faulted phases differ ({phases}): the normalization to the sequence voltage of the respective "
              "faulted phase (rotation by ±120°) takes this into account.",
        "de": "Fehlerleiter unterschiedlich ({phases}): Normierung auf die Sequenzspannung des jeweiligen "
              "Fehlerleiters (Drehung ±120°) berücksichtigt das."},
    "equivalent_source.phases_differ_warning": {
        "en": "WARNING: faulted phases differ ({phases}) – without complex level normalization the equivalent "
              "source rotates by ±120° between the measurements; the two-terminal equivalent is not reliable.",
        "de": "WARNUNG: Fehlerleiter unterschiedlich ({phases}) – ohne komplexe Pegelnormierung dreht die "
              "Ersatzquelle zwischen den Messungen um ±120°; Zweipol nicht belastbar."},
    "equivalent_source.phase_unknown": {
        "en": "Faulted phase not recognisable in {names} – same phase as the others assumed.",
        "de": "Fehlerleiter nicht erkennbar in {names} – gleicher Leiter wie die übrigen angenommen."},
    "equivalent_source.polarity_fallback": {
        "en": "Polarity fallback: additionally rotated → {names} (R_q ≥ 0 for more orders)",
        "de": "Polaritäts-Rückfallebene: zusätzlich gedreht → {names} (R_q ≥ 0 für mehr Ordnungen)"},
    "equivalent_source.exactly_determined": {
        "en": "Only {n} measurements → two-terminal equivalent exactly determined, no goodness of fit/jackknife "
              "possible.",
        "de": "Nur {n} Messungen → Zweipol exakt bestimmt, keine Fit-Güte/Jackknife möglich."},
    # ---- hints per order
    "equivalent_source.zero_sequence_not_normalized": {
        "en": "zero-sequence order → without level normalization",
        "de": "Nullsystem-Ordnung → ohne Pegelnormierung"},
    "equivalent_source.magnitude_only": {
        "en": "no complex levels in the export → magnitude normalization only",
        "de": "keine komplexen Pegel im Export → nur Betragsnormierung"},
    "equivalent_source.level_missing": {
        "en": "level missing/too small (< {min_level:.1f} V) → without normalization",
        "de": "Pegel fehlt/zu klein (< {min_level:.1f} V) → ohne Normierung"},
    "equivalent_source.estimators_disagree": {
        "en": "Estimators disagree on Z_q ({z_equation} Ω and {z_output} Ω) → U_q/Z_q individually uncertain; "
              "current at Z = {z_mid} Ω: {i_equation:.3g} and {i_output:.3g} A ({verdict})",
        "de": "Schätzer uneinig über Z_q ({z_equation} Ω bzw. {z_output} Ω) → U_q/Z_q einzeln unsicher; "
              "Strom bei Z = {z_mid} Ω: {i_equation:.3g} bzw. {i_output:.3g} A ({verdict})"},
    "equivalent_source.prediction_stable": {
        "en": "prediction within the measured range is stable",
        "de": "Vorhersage im Messbereich stabil"},
    "equivalent_source.prediction_uncertain": {
        "en": "the prediction is uncertain as well",
        "de": "auch die Vorhersage ist unsicher"},
    "equivalent_source.rq_negative": {
        "en": "R_q < 0 (not possible for a passive network) → boundary solution R_q = 0; current at Z = {z_mid} Ω: "
              "{i_rq0:.3g} A (R_q = 0) and {i_free:.3g} A (free) – the boundary solution is not necessarily "
              "conservative",
        "de": "R_q < 0 (für ein passives Netz nicht möglich) → Randlösung R_q = 0; Strom bei Z = {z_mid} Ω: "
              "{i_rq0:.3g} A (R_q = 0) bzw. {i_free:.3g} A (frei) – die Randlösung ist nicht zwingend konservativ"},
    "equivalent_source.ill_conditioned": {
        "en": "ill-conditioned: a magnitude error of 1 % or an angle error of 0.5° in one current changes Z_q by up "
              "to {change:.0f} % (additional impedances small compared with |Z_q|?) – U_q/Z_q of limited "
              "reliability only",
        "de": "schlecht konditioniert: 1 % Betrags- bzw. 0,5° Winkelfehler eines Stroms ändert Z_q um bis zu "
              "{change:.0f} % (Zusatzimpedanzen klein gegenüber |Z_q|?) – U_q/Z_q nur eingeschränkt belastbar"},
    "equivalent_source.thevenin_check": {
        "en": "Thevenin check: −U_q/level = {magnitude:.2f}∠{angle:.0f}° (expected ≈ 1∠0°, U_q = pre-fault "
              "voltage of the faulted phase) – check the normalization, polarity or measurement series",
        "de": "Thevenin-Kontrolle: −U_q/Pegel = {magnitude:.2f}∠{angle:.0f}° (erwartet ≈ 1∠0°, U_q = "
              "Vorfehlerspannung des Fehlerleiters) – Normierung, Polarität oder Messreihe prüfen"},
    # ---- scaling to the 95 % quantile
    "equivalent_source.thd_measured_missing": {
        "en": "The THD scaling needs the THD of the measurement series (thd_measured_percent).",
        "de": "Für die THD-Skalierung wird der THD der Messreihe benötigt (thd_measured_percent)."},
    "equivalent_source.scaling_not_possible": {
        "en": "Scaling per order not possible for {orders} (no U95 value, no level – e.g. zero sequence without "
              "normalization – or zero sequence with line-to-line values): {fallback}",
        "de": "Skalierung je Ordnung nicht möglich für {orders} (kein U95-Wert, kein Pegel – z. B. Nullsystem "
              "ohne Normierung – oder Nullsystem bei Leiter-Leiter-Werten): {fallback}"},
    "equivalent_source.scaling_thd_factor": {
        "en": "flat THD factor {factor:.3g} used",
        "de": "pauschaler THD-Faktor {factor:.3g} verwendet"},
    "equivalent_source.scaling_unscaled": {
        "en": "unscaled (factor 1) – specify thd95_percent as well if needed",
        "de": "unskaliert (Faktor 1) – ggf. thd95_percent zusätzlich angeben"},
})


def natural_sequence(m: int) -> str:
    """Natural sequence of a symmetrical harmonic of order m.

    Parameters
    ----------
    m : int
        Harmonic order.

    Returns
    -------
    str
        ``"pos"`` for m mod 3 = 1, ``"neg"`` for m mod 3 = 2, ``"zero"`` for m mod 3 = 0.
    """
    return {1: "pos", 2: "neg", 0: "zero"}[int(m) % 3]


# share of the natural sequence in the voltage of the faulted phase (inverse Fortescue transformation):
# U_L1 = U0 + U1 + U2,  U_L2 = U0 + a²·U1 + a·U2,  U_L3 = U0 + a·U1 + a²·U2
_PHASE_FACTOR = {"pos": {"L1": 1.0, "L2": _A2, "L3": _A},
                 "neg": {"L1": 1.0, "L2": _A, "L3": _A2},
                 "zero": {"L1": 1.0, "L2": 1.0, "L3": 1.0}}


def phase_factor(seq: str, phase: str) -> complex:
    """Factor with which the sequence voltage ``seq`` enters the voltage of the phase ``phase``.

    Parameters
    ----------
    seq : {"pos", "neg", "zero"}
        Sequence.
    phase : {"L1", "L2", "L3"}
        Phase; an unknown phase (e.g. ``""``) gives 1.

    Returns
    -------
    complex
        1, a or a² (a = e^(j·120°)), from the inverse Fortescue transformation.
    """
    return complex(_PHASE_FACTOR.get(seq, {}).get(phase, 1.0))


def _faulted_phase_from(magnitudes: Sequence[float]) -> str:
    """Faulted phase = phase with the smallest line-to-earth fundamental voltage (unambiguous: < 30 % of the
    largest), otherwise ``""``."""
    b = np.asarray(magnitudes, float)
    if b.size != 3 or not np.all(np.isfinite(b)) or b.max() <= 0 or b.min() / b.max() >= 0.3:
        return ""
    return "L%d" % (int(np.argmin(b)) + 1)


def _seq_of(x1, x2, x3) -> Dict[str, complex]:
    """Symmetrical components of three phase quantities."""
    return {"zero": (x1 + x2 + x3) / 3, "pos": (x1 + _A * x2 + _A2 * x3) / 3,
            "neg": (x1 + _A2 * x2 + _A * x3) / 3}


def _canonical_normalization(value) -> Optional[str]:
    """``"complex"``, ``"magnitude"`` or None for a value of the ``normalization`` parameter (case-insensitive,
    ``"complex_"`` also accepted); former German values raise a ValueError naming the current value."""
    if not value or (isinstance(value, str) and not value.strip()):          # None, "", False → no normalization
        return None
    key = str(value).strip().lower()
    check_option("normalization", key, ("complex", "magnitude", "none", None), aliases=_NORMALIZATIONS)
    return _NORMALIZATIONS[key]


# -------------------------------------------------------------------------------- loading
@dataclass
class SourceMeasurement:
    """One staged fault test of the series: harmonic phasors with a common angle reference.

    Attributes
    ----------
    name : str
        Name of the measurement (labels in tables and hints).
    Z : complex
        Additional impedance (fault resistance) in Ω.
    file : str
        File name of the result file.
    format : str
        Format of the result file: ``"v3"`` (groundfault), ``"v2"`` (predecessor tool), ``"legacy_notebook"``
        (legacy JSON export of an earlier evaluation notebook, structure of the result files) or
        ``"legacy_complex"`` (legacy complex export with phasors per frequency).
    f1 : float
        Fundamental frequency in Hz.
    phi_LL1_deg : float
        Angle φ_LL1 of the fundamental of the reference line-to-line voltage in degrees.
    I : dict of int to complex
        Fault-current phasors per order in A, L1-L2 reference, polarity corrected.
    U_fault : dict of int to dict
        Sequence voltages per order in the fault window ({order: {sequence: phasor}}, L1-L2 reference).
    U_pre, U_post : dict of int to dict
        Sequence voltages per order before and after the fault (levels of the source).
    U_complex : bool
        True if the pre-/post-fault levels are available as complex phasors.
    IRES : float
        Measured RMS value (true RMS) of the residual current in A.
    Iw : float
        Active residual current in A (angle method, after the polarity correction).
    polarity : int
        +1, or −1 if the current phasors were rotated by 180°.
    time : str
        Start time of the recording.
    hints : list of str
        Hints from loading.
    faulted_phase : str
        ``"L1"``, ``"L2"``, ``"L3"`` or ``""`` (unknown).
    IH_sum : float
        Harmonic content from the phasors (Σ of the orders 2…40) in A.
    I_lf : float
        Low-frequency component (< f1/2) in the max window in A.
    """

    name: str
    Z: complex
    file: str
    format: str
    f1: float
    phi_LL1_deg: float
    I: Dict[int, complex]                                  # fault current, L1-L2 reference, polarity corrected
    U_fault: Dict[int, Dict[str, complex]]                 # sequence voltages in the fault window (L1-L2 reference)
    U_pre: Dict[int, Dict[str, complex]] = field(default_factory=dict)
    U_post: Dict[int, Dict[str, complex]] = field(default_factory=dict)
    U_complex: bool = False                                # pre-/post-fault levels available as complex phasors
    IRES: float = float("nan")
    Iw: float = float("nan")
    polarity: int = 1
    time: str = ""
    hints: List[str] = field(default_factory=list)
    faulted_phase: str = ""                                # "L1" | "L2" | "L3" | "" (unknown)
    IH_sum: float = float("nan")                           # Σ of the orders 2…40 from the phasors
    I_lf: float = float("nan")                             # low-frequency component (< f1/2) in the max window

    @property
    def orders(self) -> List[int]:
        """Harmonic orders with a current phasor (sorted)."""
        return sorted(self.I)

    def ih_rest(self, orders: Iterable[int]) -> float:
        """Harmonic content that is not contained in ``orders`` in A.

        Preferably from the phasors of the same window: √max(I_H,Σ2…40² − Σ|I_m|², 0) – numerically robust, as
        only the small orders that are not covered remain. Without I_H,Σ (legacy formats) from the true RMS
        value: √max(I_RES² − I_G² − Σ|I_m|², 0); this difference of large numbers is sensitive (an error of
        0.05 % in I_RES = 80 A already gives a "rest" of ≈ 2 A).

        Parameters
        ----------
        orders : iterable of int
            Orders covered by the two-terminal equivalents (the fundamental is ignored).

        Returns
        -------
        float
            Remaining harmonic content in A (NaN if it cannot be determined).
        """
        sel = sum(abs(self.I[m]) ** 2 for m in orders if m in self.I and m != 1)
        if np.isfinite(self.IH_sum):
            return float(math.sqrt(max(self.IH_sum ** 2 - sel, 0.0)))
        if not np.isfinite(self.IRES) or 1 not in self.I:
            return float("nan")
        return float(math.sqrt(max(self.IRES ** 2 - abs(self.I[1]) ** 2 - sel, 0.0)))

    def level(self, m: int, seq: str, reference: str = "mean", complex_: bool = True) -> complex:
        """Source level of order m in the sequence ``seq`` before/after the fault (L1-L2 reference).

        Parameters
        ----------
        m : int
            Harmonic order.
        seq : {"pos", "neg", "zero"}
            Sequence.
        reference : {"mean", "pre_fault", "post_fault"}, optional
            Level before the fault, after the fault or the mean of both.
        complex_ : bool, optional
            Average the complex phasors (only if ``U_complex``); otherwise the magnitudes.

        Returns
        -------
        complex
            Level in V (a real number if magnitudes are averaged); NaN if not available.

        Raises
        ------
        ValueError
            For an unknown ``reference``, also for a former name (``"mittel"`` …).
        """
        check_option("reference", reference, _LEVELS)
        values = []
        if reference in ("mean", "pre_fault") and m in self.U_pre and seq in self.U_pre[m]:
            values.append(self.U_pre[m][seq])
        if reference in ("mean", "post_fault") and m in self.U_post and seq in self.U_post[m]:
            values.append(self.U_post[m][seq])
        if not values:
            return complex("nan")
        if complex_ and self.U_complex:
            return complex(np.mean(values))
        return complex(np.mean(np.abs(values)))


def _p(h: Mapping) -> complex:
    """Phasor from a harmonic entry of a result file (``mag_rms``, ``ang_deg``)."""
    return h["mag_rms"] * np.exp(1j * np.deg2rad(h["ang_deg"]))


def _load_signals(d: dict, path: str, name: str, Z: complex, reference: str,
                  angle_reference: str = "fundamental") -> SourceMeasurement:
    """Measurement from a file with per-signal harmonics: result file of groundfault (v3), of the predecessor tool
    (v2) or legacy notebook export without a format tag."""
    hints = []
    sig = d["signals"]
    per_role: Dict[str, List[Tuple[str, dict]]] = {}
    for nm, s in sig.items():
        per_role.setdefault(s.get("role"), []).append((nm, s))
    missing_ = [r for r in ("i_res", "u_l1e", "u_l2e", "u_l3e") if r not in per_role]
    if missing_:
        raise ValueError(tr("equivalent_source.roles_missing", file=os.path.basename(path), roles=missing_))
    main = (d.get("measurement", {}) or {}).get("main_channel", {}) or {}

    def choose(role):
        cand = per_role[role]
        if role in main:
            for nm, s in cand:
                if nm == main[role]:
                    return s
        return cand[0][1]

    ir = choose("i_res"); ua, ub, uc = choose("u_l1e"), choose("u_l2e"), choose("u_l3e")
    ords = sorted(int(k[1:]) for k in ir["harmonics"])
    pair = {"L1L2": (ua, ub), "L2L3": (ub, uc), "L3L1": (uc, ua)}[reference]
    phi = float(np.angle(_p(pair[0]["harmonics"]["H1"]) - _p(pair[1]["harmonics"]["H1"])))
    I, Uf = {}, {}
    for m in ords:
        k = "H%d" % m
        if k not in ua["harmonics"]:
            continue
        if angle_reference == "harmonics":
            # convention of the legacy complex exports: reference U_L12 of the same order in the fault window (for
            # comparisons only – this reference itself depends on the fault current and distorts X_q)
            rot = np.exp(-1j * np.angle(_p(pair[0]["harmonics"][k]) - _p(pair[1]["harmonics"][k])))
        else:
            rot = np.exp(-1j * m * phi)
        I[m] = complex(_p(ir["harmonics"][k]) * rot)
        Uf[m] = _seq_of(*(_p(x["harmonics"][k]) * rot for x in (ua, ub, uc)))
    f1 = float(d["measurement"].get("f1_hz", 50.0))
    # ---- levels before/after the fault
    U_pre, U_post, complex_ok = {}, {}, False
    sp = d.get("voltage") or {}
    if sp:
        if "orders" in sp:
            ord_sp = [int(o) for o in sp["orders"]]
        else:
            ord_sp = [int(round(h / f1)) for h in sp.get("harmonics_hz", [])]
        for blk, target_ in (("pre_fault", U_pre), ("post_fault", U_post)):
            if blk + "_phasor" in sp:
                complex_ok = True
                for seq in SEQUENCES:
                    key = "U_" + seq
                    if key in sp[blk + "_phasor"]:
                        for m, z in zip(ord_sp, sp[blk + "_phasor"][key]):
                            target_.setdefault(m, {})[seq] = complex(z["re"], z["im"])
            elif blk in sp:
                for seq in SEQUENCES:
                    key = "U_" + seq
                    if key in sp[blk]:
                        for m, v in zip(ord_sp, sp[blk][key]):
                            target_.setdefault(m, {})[seq] = complex(v)
        if complex_ok and reference != "L1L2":
            hints.append(tr("equivalent_source.pre_post_reference"))
    assess = d.get("assessment_quantities", {})
    meta = d.get("meta", {})
    phase = _faulted_phase_from([abs(_p(x["harmonics"]["H1"])) for x in (ua, ub, uc)])
    # no known format tag: legacy JSON export of an earlier evaluation notebook (same structure)
    fmt = {RESULT_FORMAT: "v3", LEGACY_RESULT_FORMAT: "v2"}.get(d.get("format"), "legacy_notebook")
    m_ = SourceMeasurement(name=name, Z=Z, file=os.path.basename(path), format=fmt,
                           f1=f1, phi_LL1_deg=math.degrees(phi), I=I, U_fault=Uf, U_pre=U_pre, U_post=U_post,
                           U_complex=complex_ok, IRES=float(assess.get("IRES", {}).get("measured_value", np.nan)),
                           time=str(meta.get("start_time", "")), hints=hints, faulted_phase=phase,
                           IH_sum=float(assess.get("IH_sum", {}).get("measured_value", np.nan)),
                           I_lf=float((d.get("values") or {}).get("ires_low_frequency_A", np.nan)))
    return m_


def _load_legacy_complex(d: dict, path: str, name: str, Z: complex) -> SourceMeasurement:
    """Legacy complex export of an earlier evaluation notebook (snapshots "vor/fehler/nach" =
    pre-fault/fault/post-fault; phasors per frequency referred to U_L12 of the *same* frequency)."""
    fe = d["fehler"]
    freqs = sorted({int(k.split("_")[1]) for k in fe if k.startswith("irest_") and k.endswith("_real")})
    f1 = 50.0
    I, Uf = {}, {}
    for f in freqs:
        m = int(round(f / f1))
        I[m] = complex(fe["irest_%d_real" % f], fe["irest_%d_imag" % f])
        try:
            u = [complex(fe["ul%de_%d_real" % (x, f)], fe["ul%de_%d_imag" % (x, f)]) for x in (1, 2, 3)]
            Uf[m] = _seq_of(*u)
        except KeyError:
            pass
    U_pre, U_post = {}, {}
    for blk, target_ in (("vor", U_pre), ("nach", U_post)):
        if blk not in d:
            continue
        for f in freqs:
            m = int(round(f / f1))
            for seq in SEQUENCES:
                k = "u%s_%d" % ({"pos": "Mit", "neg": "Gegen", "zero": "Null"}[seq], f)   # legacy format: German names
                if k in d[blk] and d[blk][k] is not None:
                    target_.setdefault(m, {})[seq] = complex(d[blk][k])
    try:
        phase = _faulted_phase_from([abs(complex(fe["ul%de_50_real" % x], fe["ul%de_50_imag" % x]))
                                     for x in (1, 2, 3)])
    except KeyError:
        phase = ""
    return SourceMeasurement(name=name, Z=Z, file=os.path.basename(path), format="legacy_complex", f1=f1,
                             phi_LL1_deg=0.0, I=I, U_fault=Uf, U_pre=U_pre, U_post=U_post, U_complex=False,
                             IRES=float(fe.get("i_fehler_rms", np.nan)), faulted_phase=phase,
                             hints=[tr("equivalent_source.legacy_complex")])


def load_measurement(path: str, Z: complex, name: Optional[str] = None, reference: str = "L1L2",
                     polarity: Union[str, int] = "auto", angle_reference: str = "fundamental") -> SourceMeasurement:
    """Read a result file and return its phasors referred to the line-to-line voltage L1-L2.

    Parameters
    ----------
    path : str
        Result file (formats: see the module description); result files of the predecessor tool with German
        keys are translated.
    Z : complex
        Additional impedance of this measurement in Ω.
    name : str, optional
        Name of the measurement (default: file name without extension).
    reference : {"L1L2", "L2L3", "L3L1"}, optional
        Line-to-line voltage of the common angle reference (the pre-/post-fault phasors always refer to L1-L2).
    polarity : {"auto", 1, -1}, optional
        ``"auto"``: rotate the current phasors by 180° if the active component of the fundamental is negative
        (Iw < 0, angle method); 1 or −1: fixed.
    angle_reference : {"fundamental", "harmonics"}, optional
        ``"fundamental"`` (X_m·e^(−j·m·φ_LL1), default) or ``"harmonics"`` (reference U_L12 of the same order in
        the fault window – convention of the legacy complex exports, only for comparisons with old reports).

    Returns
    -------
    SourceMeasurement
        Phasors, levels and hints of the measurement.

    Raises
    ------
    ValueError
        For an unknown file format, if the roles ``i_res``, ``u_l1e``, ``u_l2e``, ``u_l3e`` are missing, or for an
        unknown ``reference``, ``polarity`` or ``angle_reference``.
    """
    check_option("reference", reference, ("L1L2", "L2L3", "L3L1"))
    check_option("polarity", polarity, ("auto", 1, -1))
    check_option("angle_reference", angle_reference, ("fundamental", "harmonics"))
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    name = name or os.path.splitext(os.path.basename(path))[0]
    if is_legacy_result(d):
        d = translate_result(d)                         # German keys (predecessor tool, legacy notebook exports)
    if "signals" in d:
        m = _load_signals(d, path, name, complex(Z), reference, angle_reference)
        if angle_reference == "harmonics":
            m.U_complex = False
            m.hints.append(tr("equivalent_source.angle_reference_per_order"))
    elif "fehler" in d:
        m = _load_legacy_complex(d, path, name, complex(Z))
    else:
        raise ValueError(tr("equivalent_source.unknown_format", path=path))
    # ---- polarity from the active component of the fundamental (angle method)
    if 1 in m.I and 1 in m.U_fault:
        U0 = m.U_fault[1]["zero"]; I1 = m.I[1]
        if abs(U0) > 0 and abs(I1) > 0:
            m.Iw = float(abs(I1) * math.cos(np.angle(U0) - np.angle(I1)))
    pol = 1
    if not isinstance(polarity, str) and polarity in (-1, 1):
        pol = int(polarity)
    elif polarity == "auto" and np.isfinite(m.Iw) and m.Iw < 0:
        pol = -1
    if pol == -1:
        m.I = {k: -v for k, v in m.I.items()}
        m.Iw = -m.Iw if np.isfinite(m.Iw) else m.Iw
        m.hints.append(tr("equivalent_source.polarity_rotated"))
    m.polarity = pol
    return m


def load_series(entries: Sequence[Mapping], reference: str = "L1L2",
                polarity: Union[str, Sequence[int]] = "auto",
                angle_reference: str = "fundamental") -> List[SourceMeasurement]:
    """Read the result files of a measurement series.

    Parameters
    ----------
    entries : sequence of mapping
        One ``dict(file=..., Z=..., name=...)`` per measurement (``name`` optional).
    reference : str, optional
        See [`load_measurement`][groundfault.equivalent_source.load_measurement].
    polarity : {"auto", 1, -1} or list of int, optional
        Polarity for all measurements or one value per entry (list or tuple).
    angle_reference : str, optional
        See [`load_measurement`][groundfault.equivalent_source.load_measurement].

    Returns
    -------
    list of SourceMeasurement
        The measurements in the order of ``entries``.
    """
    out = []
    for k, e in enumerate(entries):
        pol = polarity[k] if isinstance(polarity, (list, tuple)) else polarity
        out.append(load_measurement(e["file"], e["Z"], e.get("name"), reference, pol, angle_reference))
    return out


# -------------------------------------------------------------------------------- fit methods
def fit_equation_error(I: np.ndarray, Z: np.ndarray, weights: Optional[np.ndarray] = None
                       ) -> Tuple[complex, complex, float]:
    """Linear least-squares fit of I_k·Z_q − U_q = −I_k·Z_k (equation error).

    The columns are normalised before solving (scale-invariant condition number).

    Parameters
    ----------
    I : array_like of complex
        Currents of one order per measurement in A.
    Z : array_like of complex
        Additional impedances in Ω.
    weights : array_like of float, optional
        Weights per measurement.

    Returns
    -------
    Uq : complex
        Source voltage in V.
    Zq : complex
        Source impedance in Ω.
    condition_number : float
        Condition number of the system matrix with columns scaled to unit norm.
    """
    I = np.asarray(I, complex); Z = np.asarray(Z, complex)
    s = float(np.median(np.abs(I))) or 1.0
    A = np.column_stack([I / s, -np.ones_like(I)])
    b = -I * Z / s
    if weights is not None:
        w = np.sqrt(np.asarray(weights, float))
        A = A * w[:, None]; b = b * w
    x, *_ = np.linalg.lstsq(A, b, rcond=None)
    Zq = x[0]               # column 1 = I/s, right-hand side /s → Z_q directly, U_q = s·x1
    Uq = x[1] * s
    # condition number of the matrix with columns scaled to unit norm
    An = A / np.linalg.norm(A, axis=0)
    cond = float(np.linalg.cond(An))
    return complex(Uq), complex(Zq), cond


def fit_output_error(I: np.ndarray, Z: np.ndarray, start: Optional[Tuple[complex, complex]] = None
                     ) -> Tuple[complex, complex]:
    """Nonlinear least-squares fit min Σ|I_k − U_q/(Z_q + Z_k)|² (output error).

    Starts from the equation-error estimate. Without SciPy: Gauss–Newton with step-size control.

    Parameters
    ----------
    I : array_like of complex
        Currents of one order per measurement in A.
    Z : array_like of complex
        Additional impedances in Ω.
    start : tuple of complex, optional
        Start values (U_q, Z_q); default [`fit_equation_error`][groundfault.equivalent_source.fit_equation_error].

    Returns
    -------
    Uq, Zq : complex
        Source voltage in V and source impedance in Ω.
    """
    I = np.asarray(I, complex); Z = np.asarray(Z, complex)
    if start is None:
        Uq0, Zq0, _ = fit_equation_error(I, Z)
    else:
        Uq0, Zq0 = start
    sU = max(abs(Uq0), 1e-9); sZ = max(abs(Zq0), 1.0); sI = max(float(np.median(np.abs(I))), 1e-12)

    def res(p):
        Uq = complex(p[0], p[1]) * sU; Zq = complex(p[2], p[3]) * sZ
        r = (I - Uq / (Zq + Z)) / sI
        return np.concatenate([r.real, r.imag])

    p0 = np.array([Uq0.real / sU, Uq0.imag / sU, Zq0.real / sZ, Zq0.imag / sZ])
    if _least_squares is not None:
        sol = _least_squares(res, p0, method="lm" if 2 * len(I) >= 4 else "trf", xtol=1e-14, ftol=1e-14,
                             gtol=1e-14, max_nfev=2000)
        p = sol.x
    else:  # pragma: no cover - Gauss–Newton
        p = p0.copy()
        for _ in range(100):
            r = res(p); J = np.empty((r.size, 4)); h = 1e-7
            for j in range(4):
                dp = np.zeros(4); dp[j] = h
                J[:, j] = (res(p + dp) - r) / h
            step, *_ = np.linalg.lstsq(J, -r, rcond=None)
            lam = 1.0
            while lam > 1e-6 and np.sum(res(p + lam * step) ** 2) > np.sum(r ** 2):
                lam /= 2
            p = p + lam * step
            if np.linalg.norm(lam * step) < 1e-13:
                break
    return complex(p[0], p[1]) * sU, complex(p[2], p[3]) * sZ


def fit_rq0(I: np.ndarray, Z: np.ndarray) -> Tuple[complex, complex]:
    """Least-squares fit with the constraint R_q = 0 (boundary of the physically admissible region, as in the
    predecessor tool).

    Unknowns X (real) and U_q (complex): U_q − j·X·I_k = I_k·Z_k.

    Parameters
    ----------
    I : array_like of complex
        Currents of one order per measurement in A.
    Z : array_like of complex
        Additional impedances in Ω.

    Returns
    -------
    Uq, Zq : complex
        Source voltage in V and source impedance j·X in Ω.
    """
    I = np.asarray(I, complex); Z = np.asarray(Z, complex)
    rows, rhs = [], []
    for Ik, Zk in zip(I, Z):
        c = -1j * Ik
        rows.append([c.real, 1.0, 0.0]); rhs.append((Ik * Zk).real)
        rows.append([c.imag, 0.0, 1.0]); rhs.append((Ik * Zk).imag)
    s, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
    return complex(s[1], s[2]), complex(0.0, s[0])


def _relres(I, Uq, Zq, Z) -> float:
    """Relative RMS residual of the currents: ‖I − U_q/(Z_q + Z)‖/‖I‖."""
    pred = Uq / (Zq + Z)
    return float(np.sqrt(np.mean(np.abs(I - pred) ** 2)) / max(float(np.sqrt(np.mean(np.abs(I) ** 2))), 1e-12))


def _fit(I, Z, method: str):
    """Two-terminal fit with the estimator ``method`` → (U_q, Z_q)."""
    check_option("method", method, _METHODS, aliases=("rq0",))
    if method == "equation_error":
        Uq, Zq, _ = fit_equation_error(I, Z)
    elif method == "output_error":
        Uq, Zq = fit_output_error(I, Z)
    else:
        Uq, Zq = fit_rq0(I, Z)
    return Uq, Zq


def _sensitivity(I: np.ndarray, Z: np.ndarray, Zq: complex, method: str, rq0: bool) -> float:
    """Largest relative change of Z_q if a single current is falsified by ±1 % in magnitude or ±0.5° in angle (local
    sensitivity; for two measurements as in
    [`groundfault.formulas.source_from_two_measurements`][groundfault.formulas.source_from_two_measurements])."""
    best = 0.0
    for k in range(len(I)):
        for f in (1.01, 0.99, np.exp(1j * np.deg2rad(0.5)), np.exp(-1j * np.deg2rad(0.5))):
            I2 = np.array(I, complex)
            I2[k] *= f
            try:
                _, Zq2 = fit_rq0(I2, Z) if rq0 else _fit(I2, Z, method)
            except Exception:                      # pragma: no cover - numerically degenerate
                return float("inf")
            best = max(best, abs(Zq2 - Zq) / max(abs(Zq), 1e-9))
    return float(best)


# -------------------------------------------------------------------------------- evaluation of the series
@dataclass
class SourceFit:
    """Two-terminal equivalent of one harmonic order.

    Attributes
    ----------
    order : int
        Harmonic order m.
    f_Hz : float
        Frequency in Hz (m times the mean fundamental frequency of the series).
    sequence : {"pos", "neg", "zero"}
        Sequence used for the level normalization.
    Uq : complex
        Source voltage in V (L1-L2 reference).
    Zq : complex
        Source impedance in Ω.
    method : {"equation_error", "output_error", "rq0"}
        Estimator of the result (``"rq0"``: boundary solution R_q = 0).
    Z : numpy.ndarray
        Additional impedances (n,) in Ω.
    I_raw : numpy.ndarray
        Currents (n,) in A, L1-L2 reference.
    I_fit : numpy.ndarray
        Normalized currents (n,) in A used for the fit.
    U_ref : numpy.ndarray
        Levels used for the normalization (n,), complex or magnitude; NaN without normalization.
    normalization : {"complex", "magnitude", "none"}
        Normalization actually applied to this order.
    resid_rel : float
        Relative RMS residual of the currents.
    condition_number : float
        Condition number of the linear fit.
    Rq_fixed : bool
        True if the boundary solution R_q = 0 was used.
    comparison : dict
        Results of the estimators: {method: (U_q, Z_q, relative residual)}.
    hints : list of str
        Hints for this order.
    sensitivity : float
        Largest relative change of Z_q for an error of 1 %/0.5° in a single current.
    """

    order: int
    f_Hz: float
    sequence: str
    Uq: complex
    Zq: complex
    method: str
    Z: np.ndarray                  # additional impedances (n,)
    I_raw: np.ndarray              # currents, L1-L2 reference (n,)
    I_fit: np.ndarray              # normalized currents (n,)
    U_ref: np.ndarray              # levels used (n,) (complex or magnitude)
    normalization: str
    resid_rel: float
    condition_number: float
    Rq_fixed: bool = False
    comparison: Dict[str, Tuple[complex, complex, float]] = field(default_factory=dict)
    hints: List[str] = field(default_factory=list)
    sensitivity: float = float("nan")    # largest rel. change of Z_q for a 1 %/0.5° error of one current

    def current(self, Z_E: complex, factor: float = 1.0) -> float:
        """Current of this order at the earthing impedance Z_E: |factor·U_q/(Z_q + Z_E)|.

        Parameters
        ----------
        Z_E : complex
            Earthing impedance in Ω.
        factor : float, optional
            Scaling factor of the source voltage (e.g. to the 95 % quantile of the harmonic voltage).

        Returns
        -------
        float
            Current in A.
        """
        return float(abs(factor * self.Uq / (self.Zq + Z_E)))

    @property
    def level_reference(self) -> float:
        """Median of the source level of the series in V (reference for the scaling to the 95 % quantile)."""
        v = np.abs(self.U_ref[np.isfinite(self.U_ref)])
        return float(np.median(v)) if v.size else float("nan")

    @property
    def thevenin(self) -> complex:
        """Check U_q ↔ pre-fault voltage of the faulted phase: −U_q/level (expected ≈ 1∠0°).

        Physically the equivalent source is the pre-fault voltage U_x,pre,m of the faulted phase; with the current
        orientation used here (Iw > 0 with respect to U0 ≈ −E_x), I' = −I_F and thus U_q = −U_x,pre,m. Only
        defined for complex normalization (otherwise NaN).
        """
        if self.normalization != "complex" or not np.isfinite(self.level_reference) or self.level_reference <= 0:
            return complex("nan")
        return complex(-self.Uq / self.level_reference)


@dataclass
class SourceSeries:
    """Result of [`fit_equivalent_source`][groundfault.equivalent_source.fit_equivalent_source]: the measurements and
    the two-terminal equivalent per order.

    Attributes
    ----------
    measurements : list of SourceMeasurement
        The measurements of the series.
    fits : dict of int to SourceFit
        Two-terminal equivalent per order.
    IG_measured : numpy.ndarray
        Measured fundamental component per measurement in A.
    settings : dict
        Settings of the fit (``normalization``, ``reference``, ``sequence``, ``method``, ``rq_non_negative``,
        ``min_current_A``).
    hints : list of str
        Hints for the whole series (hints per order: ``SourceFit.hints``).
    """

    measurements: List[SourceMeasurement]
    fits: Dict[int, SourceFit]
    IG_measured: np.ndarray
    settings: dict
    hints: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------ tables
    def measurements_table(self) -> pd.DataFrame:
        """Overview of the measurements.

        Returns
        -------
        pandas.DataFrame
            One row per measurement: ``measurement``, ``Z_Ohm`` (text), ``file``, ``format``, ``f1_Hz``,
            ``phi_LL1_deg``, ``I_H1_A``, ``Iw_A``, ``IRES_A``, ``polarity`` (``"rotated"`` or ``"as measured"``)
            and ``level_complex``.
        """
        z = []
        for m in self.measurements:
            z.append(dict(measurement=m.name, Z_Ohm=_fmt_z(m.Z), file=m.file, format=m.format, f1_Hz=m.f1,
                          phi_LL1_deg=m.phi_LL1_deg, I_H1_A=abs(m.I.get(1, np.nan)), Iw_A=m.Iw,
                          IRES_A=m.IRES, polarity="rotated" if m.polarity < 0 else "as measured",
                          level_complex=m.U_complex))
        return pd.DataFrame(z)

    def source_table(self) -> pd.DataFrame:
        """Two-terminal parameters per order.

        Returns
        -------
        pandas.DataFrame
            One row per order: ``order``, ``f_Hz``, ``sequence``, ``method``, ``Uq_V``, ``Uq_angle_deg``,
            ``Rq_Ohm``, ``Xq_Ohm``, ``Zq_Ohm``, ``I_short_circuit_A`` (|U_q/Z_q|), ``residual_pct``,
            ``condition_number``, ``dZq_rel_per_1pct`` (sensitivity), ``Rq_fixed``, ``normalization``,
            ``level_reference_V``, ``Uq_ref_faulted_phase`` and ``Uq_angle_ref_faulted_phase_deg`` (Thevenin
            check, expected ≈ 1 and 0°) and per estimator ``Zq_<method>`` (text) and ``Uq_<method>_V``.
        """
        z = []
        for m, F in sorted(self.fits.items()):
            row = dict(order=m, f_Hz=F.f_Hz, sequence=F.sequence, method=F.method,
                       Uq_V=abs(F.Uq), Uq_angle_deg=math.degrees(np.angle(F.Uq)),
                       Rq_Ohm=F.Zq.real, Xq_Ohm=F.Zq.imag, Zq_Ohm=abs(F.Zq),
                       I_short_circuit_A=abs(F.Uq / F.Zq) if abs(F.Zq) > 0 else np.inf,
                       residual_pct=100 * F.resid_rel, condition_number=F.condition_number,
                       dZq_rel_per_1pct=F.sensitivity,
                       Rq_fixed=F.Rq_fixed, normalization=F.normalization, level_reference_V=F.level_reference,
                       Uq_ref_faulted_phase=abs(F.thevenin),
                       Uq_angle_ref_faulted_phase_deg=(math.degrees(np.angle(F.thevenin))
                                                       if np.isfinite(F.thevenin) else np.nan))
            for meth, (Uq, Zq, r) in F.comparison.items():
                row["Zq_%s" % meth] = _fmt_z(Zq)
                row["Uq_%s_V" % meth] = abs(Uq)
            z.append(row)
        return pd.DataFrame(z)

    def pairwise_table(self) -> pd.DataFrame:
        """Two-measurement solution for every pair of measurements – consistency of the model assumption.

        Returns
        -------
        pandas.DataFrame
            One row per order and pair: ``order``, ``pair``, ``Rq_Ohm``, ``Xq_Ohm``, ``Uq_V``,
            ``dZq_rel_per_1pct`` (relative change of Z_q per 1 % current error) and ``assessment`` (``"ok"`` or
            ``"R_q < 0"``).
        """
        z = []
        for m, F in sorted(self.fits.items()):
            for a, b in itertools.combinations(range(len(F.Z)), 2):
                I1, I2, Z1, Z2 = F.I_fit[a], F.I_fit[b], F.Z[a], F.Z[b]
                if abs(I1 - I2) < 1e-12 * max(abs(I1), 1e-300) or Z1 == Z2:
                    continue
                Zq = (I2 * Z2 - I1 * Z1) / (I1 - I2); Uq = I1 * (Zq + Z1)
                # sensitivity: relative change of Z_q per 1 % current error
                sens = abs(I1) / abs(I1 - I2) * 0.01 * abs(Zq + Z1) / max(abs(Zq), 1e-9)
                z.append(dict(order=m, pair="%s / %s" % (self.measurements[a].name, self.measurements[b].name),
                              Rq_Ohm=Zq.real, Xq_Ohm=Zq.imag, Uq_V=abs(Uq),
                              dZq_rel_per_1pct=sens, assessment="ok" if Zq.real >= 0 else "R_q < 0"))
        return pd.DataFrame(z)

    def forecast_table(self) -> pd.DataFrame:
        """Model current against the (normalized) measured current per order and measurement.

        Returns
        -------
        pandas.DataFrame
            ``order``, ``measurement``, ``Z_Ohm`` (text), ``I_measured_A``, ``I_model_A``, ``deviation_pct`` and
            ``P_additional_impedance_kW`` (power of this order in the additional impedance).
        """
        z = []
        for m, F in sorted(self.fits.items()):
            pred = F.Uq / (F.Zq + F.Z)
            for k, mm in enumerate(self.measurements):
                im = abs(F.I_fit[k]); ip = abs(pred[k])
                z.append(dict(order=m, measurement=mm.name, Z_Ohm=_fmt_z(F.Z[k]), I_measured_A=im,
                              I_model_A=ip, deviation_pct=100 * (ip - im) / im if im > 0 else np.nan,
                              P_additional_impedance_kW=abs(F.I_raw[k]) ** 2 * F.Z[k].real / 1e3))
        return pd.DataFrame(z)

    def ih_rest(self) -> np.ndarray:
        """Harmonic content not covered by the two-terminal equivalents (see
        [`SourceMeasurement.ih_rest`][groundfault.equivalent_source.SourceMeasurement.ih_rest]).

        Returns
        -------
        numpy.ndarray
            One value per measurement in A (NaN if it cannot be determined).
        """
        return np.array([mm.ih_rest(self.fits.keys()) for mm in self.measurements])

    def check_table(self) -> pd.DataFrame:
        """Residual current of the model at the measured impedances against the measured true RMS value.

        The model uses the level and the I_G of each measurement and the rest of this measurement; the table
        checks the model, the normalization and the completeness. Negative deviations together with a large
        ``I_low_frequency_A`` (decaying DC component in the max window) are due to the true RMS value, not to the
        model.

        Returns
        -------
        pandas.DataFrame
            ``measurement``, ``Z_Ohm`` (text), ``IRES_measured_A``, ``IRES_sources_A``, ``deviation_pct``,
            ``IH_rest_A``, ``I_low_frequency_A`` and ``faulted_phase``.
        """
        z = []
        rest = self.ih_rest()
        for k, mm in enumerate(self.measurements):
            s = 0.0
            for m, F in self.fits.items():
                I_mod = F.Uq / (F.Zq + F.Z[k])
                if F.normalization in ("complex", "magnitude") and np.isfinite(F.U_ref[k]):
                    ref = F.U_ref[k] if F.normalization == "complex" else abs(F.U_ref[k])
                    I_mod = I_mod * ref / F.level_reference          # back to the level of this measurement
                s += abs(I_mod) ** 2
            ig = abs(mm.I.get(1, np.nan))
            r = rest[k] if np.isfinite(rest[k]) else 0.0
            ires_mod = math.sqrt(ig ** 2 + s + r ** 2)
            z.append(dict(measurement=mm.name, Z_Ohm=_fmt_z(mm.Z), IRES_measured_A=mm.IRES, IRES_sources_A=ires_mod,
                          deviation_pct=100 * (ires_mod / mm.IRES - 1) if mm.IRES > 0 else np.nan,
                          IH_rest_A=rest[k], I_low_frequency_A=mm.I_lf, faulted_phase=mm.faulted_phase or "?"))
        return pd.DataFrame(z)

    def level_table(self, reference: str = "mean") -> pd.DataFrame:
        """Source level before and after every fault and its drift within the measurement.

        Parameters
        ----------
        reference : str, optional
            Not used (both levels are always listed); kept for compatibility.

        Returns
        -------
        pandas.DataFrame
            ``order``, ``sequence``, ``measurement``, ``U_pre_V``, ``U_post_V`` and ``drift_in_measurement_pct``.
        """
        z = []
        for m, F in sorted(self.fits.items()):
            for mm in self.measurements:
                pre = abs(mm.level(m, F.sequence, "pre_fault", False))
                post = abs(mm.level(m, F.sequence, "post_fault", False))
                z.append(dict(order=m, sequence=F.sequence, measurement=mm.name, U_pre_V=pre, U_post_V=post,
                              drift_in_measurement_pct=100 * (post / pre - 1) if pre > 0 else np.nan))
        return pd.DataFrame(z)

    def jackknife_table(self, Z_E: complex) -> pd.DataFrame:
        """Jackknife: current at Z_E per order when the fit is repeated without one measurement at a time.

        Parameters
        ----------
        Z_E : complex
            Earthing impedance in Ω.

        Returns
        -------
        pandas.DataFrame
            ``order``, ``I_at_ZE_A`` (all measurements), ``min_A``, ``max_A`` and ``span_pct``
            (= (max − min)/(2·I_at_ZE)); NaN with fewer than three measurements.
        """
        z = []
        n = len(self.measurements)
        for m, F in sorted(self.fits.items()):
            best = F.current(Z_E)
            if n < 3:
                z.append(dict(order=m, I_at_ZE_A=best, min_A=np.nan, max_A=np.nan, span_pct=np.nan))
                continue
            values = []
            for removed in range(n):
                sel = [j for j in range(n) if j != removed]
                Uq, Zq = _fit(F.I_fit[sel], F.Z[sel], F.method if F.method != "rq0" else "equation_error")
                if self.settings.get("rq_non_negative") and Zq.real < 0:
                    Uq, Zq = fit_rq0(F.I_fit[sel], F.Z[sel])
                values.append(abs(Uq / (Zq + Z_E)))
            v = np.array(values)
            z.append(dict(order=m, I_at_ZE_A=best, min_A=v.min(), max_A=v.max(),
                          span_pct=100 * (v.max() - v.min()) / (2 * best) if best > 0 else np.nan))
        return pd.DataFrame(z)

    @property
    def Z_range(self) -> Tuple[float, float]:
        """Smallest and largest magnitude of the additional impedances in Ω."""
        zz = np.abs(np.array([m.Z for m in self.measurements]))
        return float(zz.min()), float(zz.max())


def _fmt_z(z: complex) -> str:
    """Impedance as short text (``"2.5"``, ``"4 − j2"``) with the decimal separator of the output language."""
    z = complex(z)
    if abs(z.imag) < 1e-12:
        s = "%.4g" % z.real
    else:
        s = "%.3g %s j%.3g" % (z.real, "+" if z.imag >= 0 else "−", abs(z.imag))
    return s.replace(".", ",") if i18n.get_language() == "de" else s


def fit_equivalent_source(measurements: Sequence[SourceMeasurement], orders: Union[str, Sequence[int]] = "auto",
                          normalization: Optional[str] = "complex", reference: str = "mean",
                          sequence: Union[str, Mapping[int, str]] = "natural", method: str = "equation_error",
                          rq_non_negative: bool = True, min_current_A: float = 0.5, min_level_V: float = 1.0,
                          polarity_brute_force: bool = False, normalize_zero: bool = False) -> SourceSeries:
    """Two-terminal (Thevenin) equivalent per harmonic order from a measurement series.

    Both estimators (equation error and output error) are always computed and stored in
    ``SourceFit.comparison``; ``method`` selects the result.

    Parameters
    ----------
    measurements : sequence of SourceMeasurement
        At least two measurements with different additional impedances
        ([`load_series`][groundfault.equivalent_source.load_series]).
    orders : "auto" or sequence of int, optional
        ``"auto"``: odd orders > 1 whose current is ≥ ``min_current_A`` in at least two measurements (with a hint
        on the skipped orders); otherwise a list, e.g. ``[3, 5, 7, 11, 13]`` (orders missing in a file are
        skipped with a hint).
    normalization : {"complex", "magnitude", None}, optional
        Normalization of the source fluctuation: ``"complex"`` (magnitude and phase, recommended),
        ``"magnitude"`` or None (also ``"none"``). Without complex levels in the export ``"complex"`` falls back to
        ``"magnitude"``, without usable levels to no normalization (with a hint per order).
    reference : {"mean", "pre_fault", "post_fault"}, optional
        Level used for the normalization.
    sequence : {"natural", "legacy"} or mapping, optional
        Sequence of each order: ``"natural"`` (m mod 3), ``"legacy"`` (simplified assignment of earlier evaluations: 3rd
        order zero, 5th negative, 7th positive, all other orders negative sequence,
        [`SEQUENCE_LEGACY`][groundfault.equivalent_source.SEQUENCE_LEGACY]) or a mapping order →
        ``"pos"``/``"neg"``/``"zero"``.
    method : {"equation_error", "output_error"}, optional
        Estimator of the result: ``"equation_error"`` (linear, as in the predecessor tool) or ``"output_error"``
        (nonlinear).
    rq_non_negative : bool, optional
        If the free fit gives R_q < 0 (impossible for a passive network), use the boundary solution R_q = 0.
    min_current_A : float, optional
        Current threshold of the automatic order selection in A.
    min_level_V : float, optional
        Smallest usable level in V; smaller or missing levels → no normalization for this order.
    polarity_brute_force : bool, optional
        Polarity fallback for ≥ 3 measurements: try all sign combinations (first measurement fixed) if R_q < 0
        for some orders; criterion: R_q ≥ 0 for as many orders as possible, then the smallest residual (as in
        the predecessor tool).
    normalize_zero : bool, optional
        Also normalize the orders of the zero sequence (3, 9, 15 …). Default False: their current only arises
        during the earth fault (saturation of coils/transformers at full displacement), the tiny pre-fault level
        U0,m is no reference for it.

    Returns
    -------
    SourceSeries
        Two-terminal equivalent per order with tables, checks and hints.

    Raises
    ------
    ValueError
        For fewer than two measurements, equal additional impedances or an unknown ``normalization``,
        ``reference``, ``sequence`` or ``method`` – also for a former German value of the predecessor tool
        (``"komplex"``, ``"mittel"``, ``"natuerlich"``, ``"gleichungsfehler"`` …), whose current name the message
        gives.
    """
    normalization = _canonical_normalization(normalization)
    if isinstance(orders, str):
        check_option("orders", orders, ("auto",))
    check_option("reference", reference, _LEVELS)
    check_option("method", method, _METHODS)
    if isinstance(sequence, Mapping):
        for m, sq in sequence.items():
            check_option("sequence", sq, SEQUENCES)
    else:
        check_option("sequence", sequence, ("natural", "legacy"))
    if len(measurements) < 2:
        raise ValueError(tr("equivalent_source.too_few_measurements"))
    Z = np.array([m.Z for m in measurements], complex)
    if len(set(np.round(Z, 9))) < 2:
        raise ValueError(tr("equivalent_source.equal_impedances"))
    hints = []
    common = sorted(set.intersection(*[set(m.orders) for m in measurements]) - {1})
    if orders == "auto":
        # odd orders with ≥ min_current_A in at least two measurements: the two-terminal equivalent (two complex
        # unknowns) needs two meaningful currents; even orders in staged fault tests mostly stem from transients/
        # DC saturation of the clamps and follow no two-terminal model
        n_ok = {o: sum(abs(m.I[o]) >= min_current_A for m in measurements) for o in common}
        ords = [o for o in common if o % 2 == 1 and n_ok[o] >= 2]
        removed = [o for o in common if o not in ords and n_ok[o] >= 1]
        if removed:
            hints.append(tr("equivalent_source.auto_orders_skipped", orders=removed, min_current=min_current_A))
    else:
        ords = [int(o) for o in orders if int(o) in common]
        missing = sorted(set(int(o) for o in orders) - set(ords))
        if missing:
            hints.append(tr("equivalent_source.orders_missing", orders=missing))
    IG = np.array([abs(m.I.get(1, np.nan)) for m in measurements])
    phase = sorted({mm.faulted_phase for mm in measurements if mm.faulted_phase})
    complex_all = normalization == "complex" and all(mm.U_complex for mm in measurements)
    if len(phase) > 1:
        if complex_all:
            hints.append(tr("equivalent_source.phases_differ_normalized", phases=", ".join(
                "%s: %s" % (mm.name, mm.faulted_phase or "?") for mm in measurements)))
        else:
            hints.append(tr("equivalent_source.phases_differ_warning", phases=", ".join(phase)))
    unknown = [mm.name for mm in measurements if not mm.faulted_phase]
    if unknown and phase:
        hints.append(tr("equivalent_source.phase_unknown", names=", ".join(unknown)))

    def seq_for(m: int) -> str:
        if isinstance(sequence, Mapping):
            return sequence.get(m, natural_sequence(m))
        if sequence == "legacy":
            return SEQUENCE_LEGACY.get(m, "neg")
        return natural_sequence(m)

    def single(sign: Sequence[int]) -> Dict[int, SourceFit]:
        fits = {}
        for m in ords:
            sq = seq_for(m)
            Ik = np.array([mm.I[m] * s for mm, s in zip(measurements, sign)], complex)
            complex_ok = normalization == "complex" and all(mm.U_complex for mm in measurements)
            U_ref = np.array([mm.level(m, sq, reference, complex_=complex_ok) for mm in measurements], complex)
            # normalization actually applied to this order; ``note`` = message key explaining a deviation
            norm, note = normalization, None
            if sq == "zero" and normalization and not normalize_zero:
                norm, note = None, "equivalent_source.zero_sequence_not_normalized"
            elif normalization == "complex" and not complex_ok:
                norm, note = "magnitude", "equivalent_source.magnitude_only"
            if norm and (not np.all(np.isfinite(U_ref)) or np.any(np.abs(U_ref) < min_level_V)):
                # missing levels supersede the magnitude-only fallback: no normalization at all
                norm, note = None, "equivalent_source.level_missing"
            hint = [tr(note, min_level=min_level_V)] if note else []
            if norm == "complex":
                # level of the natural sequence at the faulted phase (L2/L3: ±120°); unknown phase → as the others
                faulted = [mm.faulted_phase or (phase[0] if len(phase) == 1 else "") for mm in measurements]
                U_ref = U_ref * np.array([phase_factor(sq, x) for x in faulted])
                I_fit = Ik * (np.median(np.abs(U_ref)) / U_ref)
            elif norm == "magnitude":
                I_fit = Ik * (np.median(np.abs(U_ref)) / np.abs(U_ref))
            else:
                I_fit = Ik.copy()
            comparison = {}
            for meth in _METHODS:
                Uq_, Zq_ = _fit(I_fit, Z, meth)
                comparison[meth] = (Uq_, Zq_, _relres(I_fit, Uq_, Zq_, Z))
            Uq, Zq, _ = comparison[method]
            # identifiability: if the two estimators give very different Z_q, U_q and Z_q are individually
            # uncertain (they scale together); the current within the measured range usually stays stable
            (Ug_, Zg_, _), (Ua_, Za_, _) = comparison["equation_error"], comparison["output_error"]
            if abs(Za_ - Zg_) > 0.2 * max(abs(Zg_), 1e-9):
                zm = 0.5 * (Z[np.argmin(np.abs(Z))] + Z[np.argmax(np.abs(Z))])
                ig, ia = abs(Ug_ / (Zg_ + zm)), abs(Ua_ / (Za_ + zm))
                verdict = tr("equivalent_source.prediction_stable" if abs(ig - ia) <= 0.05 * max(ig, ia)
                             else "equivalent_source.prediction_uncertain")
                hint.append(tr("equivalent_source.estimators_disagree", z_equation=_fmt_z(Zg_),
                               z_output=_fmt_z(Za_), z_mid=_fmt_z(zm), i_equation=ig, i_output=ia, verdict=verdict))
            _, _, cond = fit_equation_error(I_fit, Z)
            fix = False
            if rq_non_negative and Zq.real < 0:
                Uq_free, Zq_free = Uq, Zq
                Uq, Zq = fit_rq0(I_fit, Z); fix = True
                comparison["rq0"] = (Uq, Zq, _relres(I_fit, Uq, Zq, Z))
                zm = 0.5 * (Z[np.argmin(np.abs(Z))] + Z[np.argmax(np.abs(Z))])
                hint.append(tr("equivalent_source.rq_negative", z_mid=_fmt_z(zm), i_rq0=abs(Uq / (Zq + zm)),
                               i_free=abs(Uq_free / (Zq_free + zm))))
            sens = _sensitivity(I_fit, Z, Zq, method, fix)
            if sens > 0.10:
                hint.append(tr("equivalent_source.ill_conditioned", change=100 * sens))
            F_ = SourceFit(order=m, f_Hz=m * float(np.mean([mm.f1 for mm in measurements])), sequence=sq,
                           Uq=Uq, Zq=Zq, method="rq0" if fix else method, Z=Z, I_raw=Ik, I_fit=I_fit,
                           U_ref=(U_ref if norm else np.full(len(Z), np.nan, complex)),
                           normalization=norm or "none", resid_rel=_relres(I_fit, Uq, Zq, Z),
                           condition_number=cond, Rq_fixed=fix, comparison=comparison, hints=hint,
                           sensitivity=sens)
            th = F_.thevenin
            if np.isfinite(th) and (abs(np.angle(th, deg=True)) > 45 or not 0.5 <= abs(th) <= 2.0):
                hint.append(tr("equivalent_source.thevenin_check", magnitude=abs(th), angle=np.angle(th, deg=True)))
            fits[m] = F_
        return fits

    signs = [1] * len(measurements)
    fits = single(signs)
    # polarity fallback: all sign combinations (first measurement fixed); criterion: R_q ≥ 0 for as many orders
    # as possible, then the smallest residual (as in the predecessor tool)
    if polarity_brute_force and len(measurements) >= 3 and ords:
        def quality(f):
            return (sum(1 for F in f.values() if F.comparison[method][1].real >= 0),
                    -float(np.mean([F.comparison[method][2] for F in f.values()])))
        best_ = (signs, fits, quality(fits))
        if best_[2][0] < len(ords):
            for combo in itertools.product([1, -1], repeat=len(measurements) - 1):
                v = [1] + list(combo)
                if v == signs:
                    continue
                f = single(v); g = quality(f)
                if g > best_[2]:
                    best_ = (v, f, g)
            if best_[0] != signs:
                fits = best_[1]
                rotated = [measurements[k].name for k, s in enumerate(best_[0]) if s < 0]
                hints.append(tr("equivalent_source.polarity_fallback", names=", ".join(rotated)))
    if len(measurements) < 3:
        hints.append(tr("equivalent_source.exactly_determined", n=len(measurements)))
    return SourceSeries(list(measurements), fits, IG,
                        dict(normalization=normalization, reference=reference, sequence=sequence, method=method,
                             rq_non_negative=rq_non_negative, min_current_A=min_current_A), hints)


# -------------------------------------------------------------------------------- residual current
def _scaling(series: SourceSeries, u95: Optional[Mapping[int, float]], u95_reference: str,
             thd95_percent: Optional[float], thd_measured_percent: Optional[float],
             safety_factor: float, hints: Optional[List[str]] = None) -> Dict[int, float]:
    """Scaling factors to the 95 % quantile per order.

    Orders that cannot be scaled individually (no level, zero sequence with line-to-line values, no U95 value) get
    the flat THD factor if given, otherwise 1 (with a hint)."""
    hints = hints if hints is not None else []
    u95_reference = {"ll": "LL", "seq": "seq"}.get(str(u95_reference).lower(), u95_reference)
    check_option("u95_reference", u95_reference, ("seq", "LL"))
    k = {m: 1.0 for m in series.fits}
    f_thd = None
    if thd95_percent is not None:
        if not thd_measured_percent or thd_measured_percent <= 0:
            raise ValueError(tr("equivalent_source.thd_measured_missing"))
        f_thd = safety_factor * thd95_percent / thd_measured_percent
    if u95:
        without = []
        for m, F in series.fits.items():
            u = u95.get(m)
            ll = u95_reference == "LL"
            if (u is None or not (np.isfinite(F.level_reference) and F.level_reference > 0)
                    or (ll and F.sequence == "zero")):
                without.append(m)
                if f_thd is not None:
                    k[m] = f_thd
                continue
            u_seq = u / math.sqrt(3) if ll else u
            k[m] = safety_factor * u_seq / F.level_reference
        if without:
            fallback = (tr("equivalent_source.scaling_thd_factor", factor=f_thd) if f_thd is not None
                        else tr("equivalent_source.scaling_unscaled"))
            hints.append(tr("equivalent_source.scaling_not_possible", orders=without, fallback=fallback))
    elif f_thd is not None:
        k = {m: f_thd for m in series.fits}
    return k


def _ig_choice(series: SourceSeries, IG: Union[str, float]) -> float:
    """Fundamental component for the assessment: largest or median measured value, or the given number."""
    if isinstance(IG, str):
        check_option("IG", IG, ("max", "median"))
    return (float(np.nanmax(series.IG_measured)) if IG == "max" else
            float(np.nanmedian(series.IG_measured)) if IG == "median" else float(IG))


def _rest(series: SourceSeries, rest: bool) -> float:
    """Harmonic content not covered by the fitted orders: largest value of the series (0 if ``rest`` is False)."""
    if not rest:
        return 0.0
    r = series.ih_rest()
    r = r[np.isfinite(r)]
    return float(r.max()) if r.size else 0.0


def ires_at_impedance(series: SourceSeries, Z_E: complex, IG: Union[str, float] = "max",
                      u95: Optional[Mapping[int, float]] = None, u95_reference: str = "seq",
                      thd95_percent: Optional[float] = None, thd_measured_percent: Optional[float] = None,
                      safety_factor: float = 1.0, rest: bool = True,
                      uncertainty_I: float = 0.0) -> Dict[str, object]:
    """Residual earth-fault current at the earthing impedance Z_E from the equivalent sources.

    I_RES(Z_E) = √(I_G² + Σ_n |k_n·U_q,n/(Z_q,n + Z_E)|² + I_rest²)

    Parameters
    ----------
    series : SourceSeries
        Result of [`fit_equivalent_source`][groundfault.equivalent_source.fit_equivalent_source].
    Z_E : complex
        Earthing impedance in Ω.
    IG : {"max", "median"} or float, optional
        Fundamental component: ``"max"`` (largest measured value, conservative), ``"median"`` or a number in A (e.g.
        from network data,
        [`groundfault.formulas.fundamental_from_network_data`][groundfault.formulas.fundamental_from_network_data]).
    u95 : mapping of int to float, optional
        95 % quantile of the harmonic voltage per order in V for the scaling per order.
    u95_reference : {"seq", "LL"}, optional
        Reference of ``u95``: ``"seq"`` = sequence voltage line-to-earth, ``"LL"`` = line-to-line (divided by √3;
        zero-sequence orders cannot be scaled with it).
    thd95_percent, thd_measured_percent : float, optional
        Flat scaling with the THD: 95 % quantile of the THD and THD of the measurement series in %. Used for all
        orders without ``u95`` and for the orders that cannot be scaled individually.
    safety_factor : float, optional
        Additional factor applied to the scaling factors (1 = none).
    rest : bool, optional
        Add the harmonic content not covered by the two-terminal equivalents (largest value of the series,
        independent of Z_E – conservative) quadratically; when scaling, with the largest factor.
    uncertainty_I : float, optional
        Measurement-uncertainty margin m_I of currents for the assessment values ``IRES_assessed`` =
        I_RES·(1 + m_I), defined by the user; default 0 (no margin).

    Returns
    -------
    dict
        ``Z_E``, ``IG``, ``IH``, ``IRES``, ``parts`` ({order: current in A}, unscaled), ``factors``
        ({order: scaling factor}), ``IH_rest``, ``IH_scaled``, ``IRES_scaled``, ``IRES_assessed``,
        ``IRES_scaled_assessed``, ``interpolation`` (True if |Z_E| lies within the range of the additional
        impedances) and ``hints``.

    Raises
    ------
    ValueError
        If ``thd95_percent`` is given without a positive ``thd_measured_percent``.
    """
    ig = _ig_choice(series, IG)
    hints: List[str] = []
    k = _scaling(series, u95, u95_reference, thd95_percent, thd_measured_percent, safety_factor, hints)
    parts, parts_s = {}, {}
    for m, F in sorted(series.fits.items()):
        parts[m] = F.current(Z_E)
        parts_s[m] = F.current(Z_E, k[m])
    r = _rest(series, rest)
    r_s = r * max(k.values()) if k else r
    IH = math.sqrt(sum(v * v for v in parts.values()) + r * r)
    IHs = math.sqrt(sum(v * v for v in parts_s.values()) + r_s * r_s)
    zmin, zmax = series.Z_range
    IRES = math.sqrt(ig ** 2 + IH ** 2)
    IRESs = math.sqrt(ig ** 2 + IHs ** 2)
    return dict(Z_E=Z_E, IG=ig, IH=IH, IRES=IRES, parts=parts, factors=k, IH_rest=r,
                IH_scaled=IHs, IRES_scaled=IRESs,
                IRES_assessed=IRES * (1 + uncertainty_I), IRES_scaled_assessed=IRESs * (1 + uncertainty_I),
                interpolation=bool(zmin - 1e-9 <= abs(Z_E) <= zmax + 1e-9), hints=hints)


def ires_over_line(series: SourceSeries, Z_E: complex, Z1L: Union[complex, Callable[[int], complex]],
                   Z0L: Union[complex, Callable[[int], complex]], IG: Union[str, float] = "max",
                   factors: Optional[Mapping[int, float]] = None, rest: bool = True) -> Dict[str, object]:
    """Residual current for a fault behind a line (e.g. at a secondary substation).

    I_m = 3·k_m·U_q,m/(3·Z_q,m + Z_1L,m + Z_2L,m + Z_0L,m + 3·Z_E) with Z_2L = Z_1L.

    For Z1L = Z0L = 0 this is identical to [`ires_at_impedance`][groundfault.equivalent_source.ires_at_impedance]
    (unscaled). With purely resistive lines and X_q → 0 it becomes the resistive approach
    ([`groundfault.formulas.limit_resistance`][groundfault.formulas.limit_resistance]).

    Parameters
    ----------
    series : SourceSeries
        Result of [`fit_equivalent_source`][groundfault.equivalent_source.fit_equivalent_source].
    Z_E : complex
        Earthing impedance at the fault location in Ω.
    Z1L, Z0L : complex or callable
        Positive- and zero-sequence impedance of the whole line in Ω, or a function of the order m.
    IG : {"max", "median"} or float, optional
        Fundamental component (see [`ires_at_impedance`][groundfault.equivalent_source.ires_at_impedance]).
    factors : mapping of int to float, optional
        Scaling factor k_m per order (default 1).
    rest : bool, optional
        Add the harmonic content not covered by the two-terminal equivalents (independent of the line –
        conservative).

    Returns
    -------
    dict
        ``IG``, ``IH``, ``IRES``, ``parts`` ({order: current in A}) and ``IH_rest``.
    """
    ig = _ig_choice(series, IG)
    parts = {}
    for m, F in sorted(series.fits.items()):
        z1 = Z1L(m) if callable(Z1L) else complex(Z1L)
        z0 = Z0L(m) if callable(Z0L) else complex(Z0L)
        k = (factors or {}).get(m, 1.0)
        parts[m] = float(abs(3 * k * F.Uq / (3 * F.Zq + 2 * z1 + z0 + 3 * Z_E)))
    r = _rest(series, rest)                     # rest independent of the line (conservative)
    IH = math.sqrt(sum(v * v for v in parts.values()) + r * r)
    return dict(IG=ig, IH=IH, IRES=math.sqrt(ig ** 2 + IH ** 2), parts=parts, IH_rest=r)


def monte_carlo(series: SourceSeries, Z_E: complex, n: int = 2000, sigma_magnitude: float = 0.01,
                sigma_phase_deg: float = 0.5, sigma_Z: float = 0.02, sigma_level: float = 0.0,
                IG: Union[str, float] = "max", seed: int = 0, model_error: bool = True) -> Dict[str, object]:
    """Uncertainty of I_RES(Z_E) due to random measurement errors (Monte Carlo).

    The errors are normally distributed (1σ). Every run repeats the fit with the same estimator (and the
    boundary solution R_q = 0 if the series was fitted with ``rq_non_negative``).

    Parameters
    ----------
    series : SourceSeries
        Result of [`fit_equivalent_source`][groundfault.equivalent_source.fit_equivalent_source].
    Z_E : complex
        Earthing impedance in Ω.
    n : int, optional
        Number of runs.
    sigma_magnitude : float, optional
        Relative error of the current magnitudes.
    sigma_phase_deg : float, optional
        Error of the current angles in degrees.
    sigma_Z : float, optional
        Relative error of the additional impedances.
    sigma_level : float, optional
        Relative error of the level normalization.
    IG : {"max", "median"} or float, optional
        Fundamental component (see [`ires_at_impedance`][groundfault.equivalent_source.ires_at_impedance]).
    seed : int, optional
        Seed of the random number generator (reproducible results).
    model_error : bool, optional
        Add the relative residual of the fit per order to the magnitude error (represents the deviation of the
        measurement series from the two-terminal model – source drift, network changes).

    Returns
    -------
    dict
        ``IRES`` and ``IH``: quantiles {5: P5, 50: P50, 95: P95} in A; ``n``; ``Zq``: spread of Z_q per order
        ({order: {``Rq_P5``, ``Rq_P95``, ``Xq_P5``, ``Xq_P95``}}); ``ires_sample``: all simulated values of I_RES.
    """
    rng = np.random.default_rng(seed)
    ig = _ig_choice(series, IG)
    r_rest = _rest(series, True)
    ires = np.empty(n); ih = np.empty(n)
    zq = {m: np.empty(n, complex) for m in series.fits}
    for r in range(n):
        s = 0.0
        for m, F in series.fits.items():
            k = len(F.Z)
            sb = math.hypot(sigma_magnitude, F.resid_rel) if model_error else sigma_magnitude
            error = (1 + sb * rng.standard_normal(k)) * np.exp(
                1j * np.deg2rad(sigma_phase_deg) * rng.standard_normal(k))
            if sigma_level:
                error *= 1 + sigma_level * rng.standard_normal(k)
            I = F.I_fit * error
            Zs = F.Z * (1 + sigma_Z * rng.standard_normal(k))
            meth = "equation_error" if F.method == "rq0" else F.method
            Uq, Zq = _fit(I, Zs, meth)
            if series.settings.get("rq_non_negative") and Zq.real < 0:
                Uq, Zq = fit_rq0(I, Zs)
            zq[m][r] = Zq
            s += abs(Uq / (Zq + Z_E)) ** 2
        s += r_rest ** 2
        ih[r] = math.sqrt(s)
        ires[r] = math.sqrt(ig ** 2 + s)
    q = lambda v: {p: float(np.percentile(v, p)) for p in (5, 50, 95)}
    return dict(IRES=q(ires), IH=q(ih), n=n,
                Zq={m: dict(Rq_P5=float(np.percentile(v.real, 5)), Rq_P95=float(np.percentile(v.real, 95)),
                            Xq_P5=float(np.percentile(v.imag, 5)), Xq_P95=float(np.percentile(v.imag, 95)))
                    for m, v in zq.items()},
                ires_sample=ires)
