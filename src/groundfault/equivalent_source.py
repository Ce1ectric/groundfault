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
   the 95 % quantile of the harmonic voltage: an order of the positive or negative sequence with its own voltage
   (otherwise with the THD), the zero sequence and the even orders as measured. I_rest = harmonic content not covered
   by the two-terminal equivalents (measured I_H minus the fitted orders, largest value of the series –
   conservative), scaled with the same rules per order. Extension: fault behind a line (Z_1L, Z_0L).

**Measured source** ([`measured_source`][groundfault.equivalent_source.measured_source]): instead of estimating U_q
from the currents, U_q is taken as measured – the pre-fault voltage of the faulted phase – and Z_q = U_q/I_k − Z_k
follows from the tests (one test suffices, the others check it). Within the range of the additional impedances both
give the same currents; beyond it (larger Z_E, fault behind a line) the measured source is the more reliable one,
because the fitted U_q rests on the small differences between the currents of the tests. The orders of the zero
sequence keep the fitted equivalent: their source arises in the fault.
"""
from __future__ import annotations

import itertools
import json
import math
import os
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from . import formulas as fml
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
           "fit_equivalent_source", "measured_source", "compare_sources", "ires_at_impedance", "ires_over_time",
           "ires_over_line", "monte_carlo", "SEQUENCES", "SEQUENCE_LEGACY", "THEVENIN_TOLERANCE"]

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
#: source impedance of the measured source (``impedance`` of ``measured_source``)
_IMPEDANCES = ("median", "smallest")

THEVENIN_TOLERANCE = (0.10, 10.0)
"""Tolerance (relative magnitude, angle in degrees) of the Thevenin check −U_q/level ≈ 1∠0° of a fitted equivalent
source: beyond it a hint says that the fitted source voltage deviates from the measured one – within the tested
additional impedances the model current stays reliable, beyond them the measured source
([`measured_source`][groundfault.equivalent_source.measured_source]) is the better basis. A diagnostic threshold, not
an assessment value; ``fit_equivalent_source(thevenin_tolerance=…)`` changes it."""

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
              "voltage of the faulted phase) – check the normalization, polarity or measurement series; if they are "
              "right, the fitted source has absorbed changes of the network between the tests: beyond the additional "
              "impedances of the tests use the measured source (measured_source)",
        "de": "Thevenin-Kontrolle: −U_q/Pegel = {magnitude:.2f}∠{angle:.0f}° (erwartet ≈ 1∠0°, U_q = "
              "Vorfehlerspannung des Fehlerleiters) – Normierung, Polarität oder Messreihe prüfen; stimmen sie, "
              "enthält die geschätzte Quelle Änderungen des Netzes zwischen den Versuchen: über die Zusatzimpedanzen "
              "der Versuche hinaus die gemessene Quelle verwenden (measured_source)"},
    "equivalent_source.thevenin_deviation": {
        "en": "Thevenin check: −U_q/level = {magnitude:.2f}∠{angle:.0f}° deviates by more than {tol_pct:.0f} % or "
              "{tol_deg:.0f}° from the pre-fault voltage of the faulted phase – the fitted source has absorbed changes "
              "of the network between the tests: within the additional impedances of the tests ({z_min}–{z_max} Ω) "
              "the model current is reliable, beyond them (larger Z_E, fault behind a line) the measured source "
              "(measured_source) is the better basis",
        "de": "Thevenin-Kontrolle: −U_q/Pegel = {magnitude:.2f}∠{angle:.0f}° weicht um mehr als {tol_pct:.0f} % "
              "bzw. {tol_deg:.0f}° von der Vorfehlerspannung des Fehlerleiters ab – die geschätzte Quelle enthält "
              "Änderungen des Netzes zwischen den Versuchen: im Bereich der Zusatzimpedanzen der Versuche "
              "({z_min}–{z_max} Ω) ist der Modellstrom belastbar, darüber hinaus (größeres Z_E, Fehler hinter einer "
              "Leitung) ist die gemessene Quelle (measured_source) die bessere Grundlage"},
    # ---- measured source
    "equivalent_source.measured_summary": {
        "en": "Measured source for the orders {orders}: U_q = pre-fault voltage of the faulted phase (level of the "
              "series), Z_q {how}",
        "de": "Gemessene Quelle für die Ordnungen {orders}: U_q = Vorfehlerspannung des Fehlerleiters (Pegel der "
              "Reihe), Z_q {how}"},
    "equivalent_source.measured_how_median": {
        "en": "= median of U_q/I_k − Z_k over the tests",
        "de": "= Median von U_q/I_k − Z_k über die Versuche"},
    "equivalent_source.loo_limit": {
        "en": "{name}={limit!r} is not permissible – a deviation ≥ 0 or None",
        "de": "{name}={limit!r} ist nicht zulässig – eine Abweichung ≥ 0 oder None"},
    "equivalent_source.measured_how_smallest": {
        "en": "= U_q/I_k − Z_k of the test with the smallest additional impedance (the others check it)",
        "de": "= U_q/I_k − Z_k des Versuchs mit der kleinsten Zusatzimpedanz (die übrigen prüfen es)"},
    "equivalent_source.measured_none": {
        "en": "Measured source for no order – it needs the complex level of the faulted phase (complex "
              "normalization) and an order outside the zero sequence; the fitted equivalent sources are kept",
        "de": "Gemessene Quelle für keine Ordnung – sie braucht den komplexen Pegel des Fehlerleiters (komplexe "
              "Normierung) und eine Ordnung außerhalb des Nullsystems; die geschätzten Ersatzquellen bleiben"},
    "equivalent_source.measured_zero_sequence": {
        "en": "zero-sequence order: the source arises in the fault, the pre-fault voltage does not drive the current "
              "→ fitted equivalent source kept",
        "de": "Nullsystem-Ordnung: die Quelle entsteht im Fehler, die Vorfehlerspannung treibt den Strom nicht → "
              "geschätzte Ersatzquelle beibehalten"},
    "equivalent_source.measured_no_complex_level": {
        "en": "no complex level of the faulted phase → fitted equivalent source kept",
        "de": "kein komplexer Pegel des Fehlerleiters → geschätzte Ersatzquelle beibehalten"},
    "equivalent_source.measured_in_rest": {
        "en": "Orders {orders} without a measured source (zero sequence – the source arises in the fault – or no "
              "complex level): without a fitted equivalent they stay in the remainder I_rest, with their largest "
              "current of the tests and independent of Z_E (on the safe side)",
        "de": "Ordnungen {orders} ohne gemessene Quelle (Nullsystem – die Quelle entsteht im Fehler – oder kein "
              "komplexer Pegel): ohne geschätzte Ersatzquelle bleiben sie im Rest I_rest, mit ihrem größten Strom der "
              "Versuche und unabhängig von Z_E (auf der sicheren Seite)"},
    "equivalent_source.no_measurement": {
        "en": "At least one measurement is needed.",
        "de": "Mindestens eine Messung nötig."},
    "equivalent_source.measured_not_selected": {
        "en": "not in the selected orders → fitted equivalent source kept",
        "de": "nicht unter den gewählten Ordnungen → geschätzte Ersatzquelle beibehalten"},
    "equivalent_source.measured_rq_negative": {
        "en": "R_q < 0 with the measured source (Z_q = {z} Ω – not a pure network impedance, e.g. a network state "
              "that changed between the tests or a source arising in the fault) → R_q = 0 with |Z_q| kept: "
              "I(Z_E) = |U_q|/√(|Z_q|² + Z_E²), on the safe side for an ohmic Z_E",
        "de": "R_q < 0 mit gemessener Quelle (Z_q = {z} Ω – keine reine Netzimpedanz, z. B. ein zwischen den "
              "Versuchen geänderter Netzzustand oder eine im Fehler entstehende Quelle) → R_q = 0 mit |Z_q| "
              "beibehalten: I(Z_E) = |U_q|/√(|Z_q|² + Z_E²), für ein ohmsches Z_E auf der sicheren Seite"},
    "equivalent_source.measured_vs_fitted": {
        "en": "fitted equivalent source: −U_q/level = {magnitude:.2f}∠{angle:.0f}°; current fitted/measured source "
              "{ratio_in:.2f} at Z = {z_in} Ω (tested range), {ratio_out:.2f} at Z = {z_out} Ω",
        "de": "geschätzte Ersatzquelle: −U_q/Pegel = {magnitude:.2f}∠{angle:.0f}°; Strom geschätzte/gemessene "
              "Quelle {ratio_in:.2f} bei Z = {z_in} Ω (Messbereich), {ratio_out:.2f} bei Z = {z_out} Ω"},
    # ---- scaling to the 95 % quantile
    "equivalent_source.thd_measured_missing": {
        "en": "The THD scaling needs the THD of the measurement series (thd_measured_percent).",
        "de": "Für die THD-Skalierung wird der THD der Messreihe benötigt (thd_measured_percent)."},
    "equivalent_source.scaling_not_possible": {
        "en": "Orders {orders} without their own value (no U95 value or no level of at least {min_level:g} V in the "
              "tests): {fallback}",
        "de": "Ordnungen {orders} ohne eigenen Wert (kein U95-Wert oder kein Pegel von mindestens {min_level:g} V in "
              "den Versuchen): {fallback}"},
    "equivalent_source.scaling_thd_factor": {
        "en": "flat THD factor {factor:.3g} used",
        "de": "pauschaler THD-Faktor {factor:.3g} verwendet"},
    "equivalent_source.scaling_thd_per_step": {
        "en": "the THD factor of every time step (THD(t)/THD of the tests × safety factor) used",
        "de": "der THD-Faktor jedes Zeitschritts (THD(t)/THD der Versuche × Sicherheitsfaktor) verwendet"},
    "equivalent_source.scaling_unscaled": {
        "en": "as measured (factor 1) – give thd95_percent as well if needed",
        "de": "wie gemessen (Faktor 1) – ggf. thd95_percent zusätzlich angeben"},
    "equivalent_source.scaling_zero_measured": {
        "en": "Orders of the zero sequence {orders} as measured (not scaled) – the zero sequence arises in the earth "
              "fault and does not follow the voltage of undisturbed operation.",
        "de": "Ordnungen des Nullsystems {orders} wie gemessen (nicht skaliert) – das Nullsystem entsteht im "
              "Erdschluss und folgt nicht der Spannung des ungestörten Betriebs."},
    "equivalent_source.scaling_other": {
        "en": "{current:.2f} A of the remainder are not assigned to an order (e.g. orders without a phasor in the "
              "result file) – as measured.",
        "de": "{current:.2f} A des Rests sind keiner Ordnung zugeordnet (z. B. Ordnungen ohne Zeiger in der "
              "Ergebnisdatei) – wie gemessen."},
    "equivalent_source.even_orders": {
        "en": "Even orders {orders}: {current:.2f} A ({share:.0f} % of the harmonic content; largest order {order} with "
              "{largest:.2f} A) – included as measured, not scaled. Even harmonics are unusual for the voltage of a "
              "network: check for another cause (e.g. a DC component or saturation at the fault inception, current "
              "clamps).",
        "de": "Gerade Ordnungen {orders}: {current:.2f} A ({share:.0f} % des Oberschwingungsanteils; größte Ordnung "
              "{order} mit {largest:.2f} A) – wie gemessen enthalten, nicht skaliert. Gerade Harmonische sind für die "
              "Spannung eines Netzes ungewöhnlich: auf eine andere Ursache prüfen (z. B. Gleichanteil oder Sättigung beim "
              "Fehlereintritt, Stromzangen)."},
    "equivalent_source.voltages_no_orders": {
        "en": "ires_over_time: no column of the voltages matches an order of the series ({orders}).",
        "de": "ires_over_time: keine Spalte der Spannungen passt zu einer Ordnung der Reihe ({orders})."},
    "equivalent_source.voltages_missing": {
        "en": "ires_over_time: {n} of {total} time steps lack the voltage of an order of the model – they are "
              "left out (NaN).",
        "de": "ires_over_time: {n} von {total} Zeitschritten fehlt die Spannung einer Ordnung des Modells – nicht "
              "verwendet (NaN)."},
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


def _measured_zq(I: np.ndarray, Z: np.ndarray, Uq: complex, impedance: str) -> complex:
    """Source impedance with the measured source voltage: Z_q,k = U_q/I_k − Z_k per test, then the median over the
    tests (real and imaginary part) or the value of the test with the smallest additional impedance (median if
    several tests share it)."""
    I = np.asarray(I, complex); Z = np.asarray(Z, complex)
    zk = Uq / I - Z
    if impedance == "smallest":
        a = np.abs(Z)
        zk = zk[a <= a.min() + 1e-9]
    return complex(float(np.median(zk.real)), float(np.median(zk.imag)))


def _rq_boundary(Zq: complex) -> complex:
    """Boundary R_q = 0 of the measured source with |Z_q| kept – the current at Z = 0 stays the measured one, and for
    an ohmic Z_E the current becomes |U_q|/√(|Z_q|² + Z_E²): j·sign(X_q)·|Z_q|."""
    return complex(0.0, math.copysign(abs(Zq), Zq.imag if Zq.imag != 0 else -1.0))


def _measured_impedance(I: np.ndarray, Z: np.ndarray, Uq: complex, impedance: str,
                        rq_non_negative: bool) -> Tuple[complex, bool]:
    """Z_q of the measured source and whether the boundary R_q = 0 was applied."""
    Zq = _measured_zq(I, Z, Uq, impedance)
    if rq_non_negative and Zq.real < 0:
        return _rq_boundary(Zq), True
    return Zq, False


def _sensitivity_measured(I: np.ndarray, Z: np.ndarray, Uq: complex, Zq: complex, impedance: str,
                          rq_non_negative: bool) -> float:
    """As ``_sensitivity`` for the measured source: largest relative change of Z_q if a single current is falsified
    by ±1 % in magnitude or ±0.5° in angle."""
    best = 0.0
    for k in range(len(I)):
        for f in (1.01, 0.99, np.exp(1j * np.deg2rad(0.5)), np.exp(-1j * np.deg2rad(0.5))):
            I2 = np.array(I, complex)
            I2[k] *= f
            Zq2, _ = _measured_impedance(I2, Z, Uq, impedance, rq_non_negative)
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
        Source voltage in V (L1-L2 reference; with complex normalization in the frame of the normalized currents).
    Zq : complex
        Source impedance in Ω.
    method : {"equation_error", "output_error", "rq0", "measured"}
        Estimator of the result (``"rq0"``: boundary solution R_q = 0; ``"measured"``: measured source voltage,
        [`measured_source`][groundfault.equivalent_source.measured_source]).
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
        Condition number of the linear fit (NaN for the measured source).
    Rq_fixed : bool
        True if the boundary solution R_q = 0 was used.
    comparison : dict
        Results of the estimators: {method: (U_q, Z_q, relative residual)}; with the measured source also
        ``"measured"``.
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
        ``min_current_A``, ``thevenin_tolerance``) and ``source``: ``"fitted"`` (source voltage estimated from the
        currents) or ``"measured"`` (measured source, then also ``impedance``).
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
                       Uq_angle_ref_faulted_phase_deg=(math.degrees(np.angle(F.thevenin)) + 0.0
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

    def single_test_table(self) -> pd.DataFrame:
        """Source impedance of every single test with the measured source voltage – the calibration with one test
        each: Z_q,k = U_q/I_k − Z_k with U_q = −level of the series (the pre-fault voltage of the faulted phase in
        the frame of the normalized currents).

        The spread between the tests shows how much the network changed between them; the normalization removes the
        change of the source level, not that of Z_q. A fitted equivalent source absorbs this spread into U_q (see
        [`measured_source`][groundfault.equivalent_source.measured_source]). Only orders with complex normalization
        outside the zero sequence.

        Returns
        -------
        pandas.DataFrame
            ``order``, ``measurement``, ``Z_Ohm`` (text), ``Rq_Ohm``, ``Xq_Ohm``, ``Zq_Ohm``, ``Zq_angle_deg``,
            ``Zq_deviation_pct`` (|Z_q,k| against the median of the tests) and ``Zq_angle_deviation_deg``.
        """
        columns = ["order", "measurement", "Z_Ohm", "Rq_Ohm", "Xq_Ohm", "Zq_Ohm", "Zq_angle_deg", "Zq_deviation_pct",
                   "Zq_angle_deviation_deg"]
        z = []
        for m, F in sorted(self.fits.items()):
            if F.sequence == "zero" or F.normalization != "complex" or not F.level_reference > 0:
                continue
            zk = -F.level_reference / F.I_fit - F.Z
            med = complex(float(np.median(zk.real)), float(np.median(zk.imag)))
            for k, mm in enumerate(self.measurements):
                z.append(dict(order=m, measurement=mm.name, Z_Ohm=_fmt_z(F.Z[k]), Rq_Ohm=zk[k].real, Xq_Ohm=zk[k].imag,
                              Zq_Ohm=abs(zk[k]), Zq_angle_deg=math.degrees(np.angle(zk[k])),
                              Zq_deviation_pct=100 * (abs(zk[k]) / abs(med) - 1) if abs(med) > 0 else np.nan,
                              Zq_angle_deviation_deg=math.degrees(np.angle(zk[k] / med)) if abs(med) > 0 else np.nan))
        return pd.DataFrame(z, columns=columns)

    def jackknife_table(self, Z_E: complex) -> pd.DataFrame:
        """Jackknife: current at Z_E per order when the fit is repeated without one measurement at a time.

        With the measured source ([`measured_source`][groundfault.equivalent_source.measured_source]) Z_q is
        determined again from the remaining tests with the same rule (median, or the test with the smallest
        additional impedance among them) and U_q stays the measured one.

        Parameters
        ----------
        Z_E : complex
            Earthing impedance in Ω.

        Returns
        -------
        pandas.DataFrame
            ``order``, ``I_at_ZE_A`` (all measurements), ``min_A``, ``max_A`` and ``span_pct``
            (= (max − min)/(2·I_at_ZE)); NaN with fewer than three measurements (measured source: fewer than two).
        """
        z = []
        n = len(self.measurements)
        rq = bool(self.settings.get("rq_non_negative"))
        for m, F in sorted(self.fits.items()):
            best = F.current(Z_E)
            measured = F.method == "measured"
            if n < (2 if measured else 3):
                z.append(dict(order=m, I_at_ZE_A=best, min_A=np.nan, max_A=np.nan, span_pct=np.nan))
                continue
            values = []
            for removed in range(n):
                sel = [j for j in range(n) if j != removed]
                if measured:
                    Uq = F.Uq
                    Zq, _ = _measured_impedance(F.I_fit[sel], F.Z[sel], Uq, self.settings.get("impedance", "median"),
                                                rq)
                else:
                    Uq, Zq = _fit(F.I_fit[sel], F.Z[sel], F.method if F.method != "rq0" else "equation_error")
                    if rq and Zq.real < 0:
                        Uq, Zq = fit_rq0(F.I_fit[sel], F.Z[sel])
                values.append(abs(Uq / (Zq + Z_E)))
            v = np.array(values)
            z.append(dict(order=m, I_at_ZE_A=best, min_A=v.min(), max_A=v.max(),
                          span_pct=100 * (v.max() - v.min()) / (2 * best) if best > 0 else np.nan))
        return pd.DataFrame(z)

    def loo_table(self, limit_pct: Optional[float] = None, limit_A: Optional[float] = None) -> pd.DataFrame:
        """Leave-one-out check: every measurement forecast with the model of the other measurements.

        The model is built again without the measurement and with the same rule – the measured source
        ([`measured_source`][groundfault.equivalent_source.measured_source]) keeps U_q and takes Z_q from the others
        (median, or the test with the smallest additional impedance among them), the fitted source is fitted again
        with the same estimator – and gives the current at the additional impedance of the left-out measurement, in the
        frame of the normalized currents as in ``forecast_table`` (i.e. with the source level of that measurement).
        Large deviations show that the network changed between the tests: a model from these tests is then less
        reliable than their spread within the tested range suggests.

        Parameters
        ----------
        limit_pct : float, optional
            Permissible deviation in % – your choice (e.g. from the operator's specification).
        limit_A : float, optional
            Permissible deviation in A – for the small currents of the higher orders, where a few tenths of an ampere
            are many per cent. Given one or both, the column ``within_limit`` says whether the deviation stays within
            one of them. Not given: the deviations without assessment.

        Returns
        -------
        pandas.DataFrame
            ``order``, ``measurement``, ``Z_Ohm`` (text), ``I_measured_A``, ``I_from_others_A``, ``deviation_pct``,
            ``deviation_A`` (model of the others against the measurement; NaN with fewer than two measurements for the
            measured source, or fewer than two different additional impedances among the others for the fitted source)
            and, with ``limit_pct`` or ``limit_A``, ``within_limit``.

        Raises
        ------
        ValueError
            For a negative ``limit_pct`` or ``limit_A``.
        """
        for name, value in (("limit_pct", limit_pct), ("limit_A", limit_A)):
            if value is not None and not float(value) >= 0:
                raise ValueError(tr("equivalent_source.loo_limit", name=name, limit=value))
        columns = ["order", "measurement", "Z_Ohm", "I_measured_A", "I_from_others_A", "deviation_pct", "deviation_A"]
        z = []
        n = len(self.measurements)
        rq = bool(self.settings.get("rq_non_negative"))
        impedance = self.settings.get("impedance", "median")
        for m, F in sorted(self.fits.items()):
            measured = F.method == "measured"
            for k, mm in enumerate(self.measurements):
                sel = [j for j in range(n) if j != k]
                ip = np.nan
                if measured and sel:
                    Zq, _ = _measured_impedance(F.I_fit[sel], F.Z[sel], F.Uq, impedance, rq)
                    ip = abs(F.Uq / (Zq + F.Z[k]))
                elif not measured and len(set(np.round(F.Z[sel], 9))) >= 2:
                    Uq, Zq = _fit(F.I_fit[sel], F.Z[sel], "equation_error" if F.method == "rq0" else F.method)
                    if rq and Zq.real < 0:
                        Uq, Zq = fit_rq0(F.I_fit[sel], F.Z[sel])
                    ip = abs(Uq / (Zq + F.Z[k]))
                im = abs(F.I_fit[k])
                z.append(dict(order=m, measurement=mm.name, Z_Ohm=_fmt_z(F.Z[k]), I_measured_A=im, I_from_others_A=ip,
                              deviation_pct=100 * (ip - im) / im if im > 0 else np.nan, deviation_A=ip - im))
        out = pd.DataFrame(z, columns=columns)
        if limit_pct is not None or limit_A is not None:
            within = []
            for dp, da in zip(out["deviation_pct"], out["deviation_A"]):
                if not np.isfinite(da):
                    within.append(None)
                    continue
                ok = limit_A is not None and abs(da) <= float(limit_A)
                ok = ok or (limit_pct is not None and np.isfinite(dp) and abs(dp) <= float(limit_pct))
                within.append(bool(ok))
            out["within_limit"] = within
        return out

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


def _select_orders(measurements: Sequence[SourceMeasurement], orders: Union[str, Sequence[int]],
                   min_current_A: float, hints: List[str]) -> List[int]:
    """Orders of the series: ``"auto"`` = odd orders > 1 with ≥ ``min_current_A`` in at least two measurements (one,
    if the series has only one), otherwise the given orders that are in every file; hints in ``hints``."""
    common = sorted(set.intersection(*[set(m.orders) for m in measurements]) - {1})
    if orders == "auto":
        # odd orders with ≥ min_current_A in at least two measurements: the two-terminal equivalent (two complex
        # unknowns) needs two meaningful currents; even orders in staged fault tests mostly stem from transients/
        # DC saturation of the clamps and follow no two-terminal model
        need = min(2, len(measurements))
        n_ok = {o: sum(abs(m.I[o]) >= min_current_A for m in measurements) for o in common}
        ords = [o for o in common if o % 2 == 1 and n_ok[o] >= need]
        removed = [o for o in common if o not in ords and n_ok[o] >= 1]
        if removed:
            hints.append(tr("equivalent_source.auto_orders_skipped", orders=removed, min_current=min_current_A))
    else:
        ords = [int(o) for o in orders if int(o) in common]
        missing = sorted(set(int(o) for o in orders) - set(ords))
        if missing:
            hints.append(tr("equivalent_source.orders_missing", orders=missing))
    return ords


def _phase_hints(measurements: Sequence[SourceMeasurement], normalization: Optional[str],
                 hints: List[str]) -> List[str]:
    """Faulted phases of the series (sorted, without unknown ones); hints on differing or unknown phases."""
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
    return phase


def _normalize_order(measurements: Sequence[SourceMeasurement], m: int, sq: str, sign: Sequence[int],
                     normalization: Optional[str], reference: str, min_level_V: float, normalize_zero: bool,
                     phase: Sequence[str]) -> Tuple[np.ndarray, np.ndarray, Optional[str], Optional[str], np.ndarray]:
    """Currents of order m and their normalization: (I_k, levels used, normalization applied, message key of a
    deviation from ``normalization`` or None, normalized currents)."""
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
    if norm == "complex":
        # level of the natural sequence at the faulted phase (L2/L3: ±120°); unknown phase → as the others
        faulted = [mm.faulted_phase or (phase[0] if len(phase) == 1 else "") for mm in measurements]
        U_ref = U_ref * np.array([phase_factor(sq, x) for x in faulted])
        I_fit = Ik * (np.median(np.abs(U_ref)) / U_ref)
    elif norm == "magnitude":
        I_fit = Ik * (np.median(np.abs(U_ref)) / np.abs(U_ref))
    else:
        I_fit = Ik.copy()
    return Ik, U_ref, norm, note, I_fit


def fit_equivalent_source(measurements: Sequence[SourceMeasurement], orders: Union[str, Sequence[int]] = "auto",
                          normalization: Optional[str] = "complex", reference: str = "mean",
                          sequence: Union[str, Mapping[int, str]] = "natural", method: str = "equation_error",
                          rq_non_negative: bool = True, min_current_A: float = 0.5, min_level_V: float = 1.0,
                          polarity_brute_force: bool = False, normalize_zero: bool = False,
                          thevenin_tolerance: Tuple[float, float] = THEVENIN_TOLERANCE) -> SourceSeries:
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
    thevenin_tolerance : tuple of float, optional
        (relative magnitude, angle in degrees) of the Thevenin check −U_q/level ≈ 1∠0°: beyond it a hint per order
        says that the fitted source voltage deviates from the measured one
        ([`THEVENIN_TOLERANCE`][groundfault.equivalent_source.THEVENIN_TOLERANCE]); beyond 0.5…2 or ±45° the hint
        asks to check normalization, polarity or the series.

    Returns
    -------
    SourceSeries
        Two-terminal equivalent per order with tables, checks and hints. The measured source for the same series:
        [`measured_source`][groundfault.equivalent_source.measured_source].

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
    tol_mag, tol_deg = (float(v) for v in thevenin_tolerance)
    z_lo, z_hi = float(np.abs(Z).min()), float(np.abs(Z).max())        # tested range (hint of the Thevenin check)
    hints = []
    ords = _select_orders(measurements, orders, min_current_A, hints)
    IG = np.array([abs(m.I.get(1, np.nan)) for m in measurements])
    phase = _phase_hints(measurements, normalization, hints)

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
            Ik, U_ref, norm, note, I_fit = _normalize_order(measurements, m, sq, sign, normalization, reference,
                                                            min_level_V, normalize_zero, phase)
            hint = [tr(note, min_level=min_level_V)] if note else []
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
            elif (np.isfinite(th) and sq != "zero"
                  and (abs(abs(th) - 1) > tol_mag or abs(np.angle(th, deg=True)) > tol_deg)):
                hint.append(tr("equivalent_source.thevenin_deviation", magnitude=abs(th), angle=np.angle(th, deg=True),
                               tol_pct=100 * tol_mag, tol_deg=tol_deg, z_min=_fmt_z(z_lo), z_max=_fmt_z(z_hi)))
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
                             rq_non_negative=rq_non_negative, min_current_A=min_current_A, min_level_V=min_level_V,
                             thevenin_tolerance=(tol_mag, tol_deg), source="fitted"), hints)


def measured_source(series: Union[SourceSeries, Sequence[SourceMeasurement]], impedance: str = "median",
                    orders: Union[str, Sequence[int]] = "auto", rq_non_negative: Optional[bool] = None,
                    reference: str = "mean", min_current_A: float = 0.5, min_level_V: float = 1.0) -> SourceSeries:
    """Equivalent sources with the **measured** source voltage instead of the one estimated from the currents.

    Physically the source voltage of the two-terminal equivalent is the pre-fault voltage of the faulted phase
    (Thevenin) – the voltage a power-quality measurement records in undisturbed operation. Here it is taken as
    measured: in the frame of the complex-normalized currents of ``series`` U_q = −Ũ (Ũ = level of the natural
    sequence at the faulted phase, median of the series; the minus sign is the current orientation of the angle
    method), and every test gives the source impedance

        Z_q,k = U_q/I_k − Z_k

    – for the test without additional impedance "open-circuit voltage divided by short-circuit current". One test
    suffices; ``impedance`` takes the median over the tests (default) or the test with the smallest additional
    impedance, and [`loo_table`][groundfault.equivalent_source.SourceSeries.loo_table] checks every test against the
    model of the others. The fitted source of
    [`fit_equivalent_source`][groundfault.equivalent_source.fit_equivalent_source] instead takes U_q from the slope of
    1/I_k over Z_k; when the additional impedances are small compared with |Z_q|, a small change of the network
    between the tests changes this slope noticeably. Within the tested range both give the same currents (the fitted
    Z_q compensates the error of U_q), beyond it – larger Z_E, fault behind a line – the measured source is the more
    reliable one. The orders of the zero sequence keep the fitted equivalent: their source arises in the fault, the
    pre-fault voltage does not drive their current.

    Parameters
    ----------
    series : SourceSeries or sequence of SourceMeasurement
        Result of [`fit_equivalent_source`][groundfault.equivalent_source.fit_equivalent_source] (complex normalization
        needed for the orders that get the measured source) – or the measurements themselves
        ([`load_series`][groundfault.equivalent_source.load_series]): with two or more different additional
        impedances they are fitted first (complex normalization), with **one test only** (or equal additional
        impedances) the measured source is the only equivalent; the zero-sequence orders then stay in the
        remainder I_rest (largest current of the tests, independent of Z_E – on the safe side).
    impedance : {"median", "smallest"}, optional
        Z_q from the median of Z_q,k over the tests (default; real and imaginary part – a change of the network
        between the tests enters as the middle state) or from the test with the smallest additional impedance
        (normally the 0-Ω test – the model then reproduces the largest measured current, and the other tests are a
        genuine check in ``forecast_table``; median if several tests share the smallest additional impedance).
        [`loo_table`][groundfault.equivalent_source.SourceSeries.loo_table] checks either rule test by test.
    orders : "auto" or sequence of int, optional
        ``"auto"``: every order with complex normalization outside the zero sequence; or a list of these orders (the
        others keep the fitted equivalent, with a hint).
    rq_non_negative : bool, optional
        If Z_q has a negative real part (not a pure network impedance), use R_q = 0 with |Z_q| kept – the current at
        Z_E = 0 stays the measured one and for an ohmic Z_E the current becomes |U_q|/√(|Z_q|² + Z_E²), on the safe
        side. Default: the setting of ``series`` (True for measurements).
    reference : {"mean", "pre_fault", "post_fault"}, optional
        Level of the source (measurements only; a series keeps its own).
    min_current_A, min_level_V : float, optional
        Current threshold of ``orders="auto"`` and smallest usable level (measurements only, see
        [`fit_equivalent_source`][groundfault.equivalent_source.fit_equivalent_source]).

    Returns
    -------
    SourceSeries
        The same series with ``method == "measured"`` for these orders (``settings["source"] == "measured"``); every
        table, [`ires_at_impedance`][groundfault.equivalent_source.ires_at_impedance],
        [`ires_over_line`][groundfault.equivalent_source.ires_over_line] and
        [`monte_carlo`][groundfault.equivalent_source.monte_carlo] work with it. ``comparison`` of each order keeps the
        fitted estimators and adds ``"measured"``. A hint per order compares the fitted source when it deviates by
        more than ``settings["thevenin_tolerance"]``.

    Raises
    ------
    ValueError
        For an unknown ``impedance``, ``orders`` or ``reference``, or without a measurement.

    Examples
    --------
    >>> fitted = fit_equivalent_source(load_series(entries))              # doctest: +SKIP
    >>> measured = measured_source(fitted)                                # doctest: +SKIP
    >>> compare_sources(measured, fitted, [0.0, 5.0, 10.0])               # doctest: +SKIP
    """
    check_option("impedance", impedance, _IMPEDANCES)
    if isinstance(orders, str):
        check_option("orders", orders, ("auto",))
    if not isinstance(series, SourceSeries):                          # measurements: fit first, or one test only
        measurements = list(series)
        check_option("reference", reference, _LEVELS)
        if not measurements:
            raise ValueError(tr("equivalent_source.no_measurement"))
        rq = True if rq_non_negative is None else bool(rq_non_negative)
        if len(set(np.round([complex(mm.Z) for mm in measurements], 9))) < 2:
            return _measured_only(measurements, impedance, orders, rq, reference, min_current_A, min_level_V)
        series = fit_equivalent_source(measurements, orders=orders, normalization="complex", reference=reference,
                                       rq_non_negative=rq, min_current_A=min_current_A, min_level_V=min_level_V)
    rq = bool(series.settings.get("rq_non_negative", True)) if rq_non_negative is None else bool(rq_non_negative)
    selected = None if isinstance(orders, str) else {int(o) for o in orders}
    tol_mag, tol_deg = series.settings.get("thevenin_tolerance", THEVENIN_TOLERANCE)
    z_lo, z_hi = series.Z_range
    z_out = 2 * z_hi if z_hi > 0 else 10.0
    fits, used = {}, []
    for m, F in sorted(series.fits.items()):
        note = None
        if F.sequence == "zero":
            note = "equivalent_source.measured_zero_sequence"
        elif F.normalization != "complex" or not F.level_reference > 0:
            note = "equivalent_source.measured_no_complex_level"
        elif selected is not None and m not in selected:
            note = "equivalent_source.measured_not_selected"
        if note:
            fits[m] = replace(F, hints=list(F.hints) + [tr(note)])            # the fitted equivalent stays
            continue
        Uq = complex(-F.level_reference)
        Zq, fixed = _measured_impedance(F.I_fit, F.Z, Uq, impedance, rq)
        hint = []
        if fixed:
            hint.append(tr("equivalent_source.measured_rq_negative", z=_fmt_z(_measured_zq(F.I_fit, F.Z, Uq, impedance))))
        th = F.thevenin                                                         # of the fitted source
        if np.isfinite(th) and (abs(abs(th) - 1) > tol_mag or abs(np.angle(th, deg=True)) > tol_deg):
            r_in, r_out = (abs(F.Uq / (F.Zq + z)) / abs(Uq / (Zq + z)) for z in (z_hi, z_out))
            hint.append(tr("equivalent_source.measured_vs_fitted", magnitude=abs(th), angle=np.angle(th, deg=True),
                           ratio_in=r_in, z_in=_fmt_z(z_hi), ratio_out=r_out, z_out=_fmt_z(z_out)))
        resid = _relres(F.I_fit, Uq, Zq, F.Z)
        comparison = dict(F.comparison)
        comparison["measured"] = (Uq, Zq, resid)
        fits[m] = SourceFit(order=m, f_Hz=F.f_Hz, sequence=F.sequence, Uq=Uq, Zq=Zq, method="measured", Z=F.Z,
                            I_raw=F.I_raw, I_fit=F.I_fit, U_ref=F.U_ref, normalization=F.normalization,
                            resid_rel=resid, condition_number=float("nan"), Rq_fixed=fixed, comparison=comparison,
                            hints=hint, sensitivity=_sensitivity_measured(F.I_fit, F.Z, Uq, Zq, impedance, fixed))
        used.append(m)
    # the hints of the series stay, except the one on the exactly determined fit: one test calibrates the measured
    # source, a second one checks it
    hints = [h for h in series.hints if h != tr("equivalent_source.exactly_determined", n=len(series.measurements))]
    hints.append(tr("equivalent_source.measured_summary", orders=used, how=tr("equivalent_source.measured_how_" + impedance))
                 if used else tr("equivalent_source.measured_none"))
    settings = dict(series.settings, source="measured", impedance=impedance, rq_non_negative=rq)
    return SourceSeries(list(series.measurements), fits, series.IG_measured, settings, hints)


def _measured_only(measurements: Sequence[SourceMeasurement], impedance: str, orders: Union[str, Sequence[int]],
                   rq: bool, reference: str, min_current_A: float, min_level_V: float) -> SourceSeries:
    """Measured source without a fitted series (one additional impedance): every order of the positive or negative
    sequence with a complex level gets U_q = −level and Z_q from the tests; the others stay in the remainder."""
    hints: List[str] = []
    ords = _select_orders(measurements, orders, min_current_A, hints)
    phase = _phase_hints(measurements, "complex", hints)
    Z = np.array([mm.Z for mm in measurements], complex)
    f1 = float(np.mean([mm.f1 for mm in measurements]))
    fits, used, rest = {}, [], []
    for m in ords:
        sq = natural_sequence(m)
        Ik, U_ref, norm, _, I_fit = _normalize_order(measurements, m, sq, [1] * len(measurements), "complex",
                                                     reference, min_level_V, False, phase)
        if sq == "zero" or norm != "complex":
            rest.append(m)
            continue
        Uq = complex(-float(np.median(np.abs(U_ref))))
        Zq, fixed = _measured_impedance(I_fit, Z, Uq, impedance, rq)
        hint = ([tr("equivalent_source.measured_rq_negative", z=_fmt_z(_measured_zq(I_fit, Z, Uq, impedance)))]
                if fixed else [])
        resid = _relres(I_fit, Uq, Zq, Z)
        fits[m] = SourceFit(order=m, f_Hz=m * f1, sequence=sq, Uq=Uq, Zq=Zq, method="measured", Z=Z, I_raw=Ik,
                            I_fit=I_fit, U_ref=U_ref, normalization="complex", resid_rel=resid,
                            condition_number=float("nan"), Rq_fixed=fixed, comparison={"measured": (Uq, Zq, resid)},
                            hints=hint, sensitivity=_sensitivity_measured(I_fit, Z, Uq, Zq, impedance, fixed))
        used.append(m)
    if rest:
        hints.append(tr("equivalent_source.measured_in_rest", orders=rest))
    hints.append(tr("equivalent_source.measured_summary", orders=used, how=tr("equivalent_source.measured_how_" + impedance))
                 if used else tr("equivalent_source.measured_none"))
    IG = np.array([abs(mm.I.get(1, np.nan)) for mm in measurements])
    settings = dict(normalization="complex", reference=reference, sequence="natural", method="measured",
                    rq_non_negative=rq, min_current_A=min_current_A, min_level_V=min_level_V,
                    thevenin_tolerance=THEVENIN_TOLERANCE, source="measured", impedance=impedance)
    return SourceSeries(list(measurements), fits, IG, settings, hints)


def compare_sources(measured: SourceSeries, fitted: SourceSeries, Z_E: Union[complex, Sequence[complex]],
                    IG: Union[str, float] = "max") -> pd.DataFrame:
    """Current per order and I_RES at one or more earthing impedances with the measured and with the fitted source.

    Within the range of the additional impedances of the tests both agree; beyond it the ratio shows how far the
    fitted source voltage (which has absorbed the changes of the network between the tests) carries.

    Parameters
    ----------
    measured : SourceSeries
        Result of [`measured_source`][groundfault.equivalent_source.measured_source].
    fitted : SourceSeries
        Result of [`fit_equivalent_source`][groundfault.equivalent_source.fit_equivalent_source] for the same
        measurements.
    Z_E : complex or sequence of complex
        Earthing impedance(s) in Ω.
    IG : {"max", "median"} or float, optional
        Fundamental component for the rows ``I_RES`` (see
        [`ires_at_impedance`][groundfault.equivalent_source.ires_at_impedance]; unscaled, with the remainder).

    Returns
    -------
    pandas.DataFrame
        One row per Z_E and order and one row ``I_RES`` per Z_E: ``Z_E_Ohm`` (text), ``order``, ``f_Hz``,
        ``sequence``, ``method`` (of ``measured``; zero-sequence orders keep the fitted estimator),
        ``Uq_fitted_to_measured`` and ``Uq_fitted_angle_deg`` (fitted U_q relative to the measured one, = Thevenin
        check), ``I_measured_source_A``, ``I_fitted_source_A``, ``fitted_to_measured`` (ratio of the currents) and
        ``interpolation`` (Z_E within the range of the additional impedances).
    """
    zs = [Z_E] if np.isscalar(Z_E) else list(Z_E)
    zmin, zmax = measured.Z_range
    z = []
    for ze in zs:
        inside = bool(zmin - 1e-9 <= abs(ze) <= zmax + 1e-9)
        for m, F in sorted(measured.fits.items()):
            G = fitted.fits.get(m)
            if G is None:
                continue
            i_m, i_f = F.current(ze), G.current(ze)
            u = G.Uq / F.Uq if abs(F.Uq) > 0 else complex("nan")
            z.append(dict(Z_E_Ohm=_fmt_z(ze), order=m, f_Hz=F.f_Hz, sequence=F.sequence, method=F.method,
                          Uq_fitted_to_measured=abs(u), Uq_fitted_angle_deg=float(np.angle(u, deg=True)) + 0.0,
                          I_measured_source_A=i_m, I_fitted_source_A=i_f,
                          fitted_to_measured=i_f / i_m if i_m > 0 else np.nan, interpolation=inside))
        r_m, r_f = ires_at_impedance(measured, ze, IG=IG)["IRES"], ires_at_impedance(fitted, ze, IG=IG)["IRES"]
        z.append(dict(Z_E_Ohm=_fmt_z(ze), order="I_RES", f_Hz=np.nan, sequence="", method="",
                      Uq_fitted_to_measured=np.nan, Uq_fitted_angle_deg=np.nan, I_measured_source_A=r_m,
                      I_fitted_source_A=r_f, fitted_to_measured=r_f / r_m if r_m > 0 else np.nan, interpolation=inside))
    return pd.DataFrame(z)


# -------------------------------------------------------------------------------- residual current
# rules of the scaling per order (column ``rule`` of the table of ires_at_impedance, see formulas.order_scaling)
_RULE_OWN, _RULE_THD, _RULE_MEASURED, _RULE_NONE = fml.SCALING_RULES
#: share of the harmonic content from which the even orders get a hint (diagnostic, not an assessment value)
_EVEN_HINT_SHARE = 0.05


def _u95_of(u95: Optional[Mapping[int, float]], m: int) -> Optional[float]:
    """The quantile of order m from ``u95`` (None if missing or not a finite number)."""
    if not u95:
        return None
    u = u95.get(m)
    try:
        u = float(u) if u is not None else None
    except (TypeError, ValueError):
        return None
    return u if u is not None and np.isfinite(u) else None


def _order_factor(m: int, u: Optional[float], level: float, f_thd: Optional[float], safety_factor: float, ll: bool,
                  min_level: float) -> Tuple[float, str]:
    """Scaling factor and rule of one order ([`groundfault.formulas.order_scaling`])."""
    return fml.order_scaling(m, u, level, f_thd=f_thd, safety_factor=safety_factor, from_ll=ll, min_level=min_level)


def _scaling(series: SourceSeries, u95: Optional[Mapping[int, float]], u95_reference: str,
             thd95_percent: Optional[float], thd_measured_percent: Optional[float],
             safety_factor: float) -> Tuple[Dict[int, float], Dict[int, str], Optional[float], bool, bool]:
    """Factors and rules of the orders of the model, the flat THD factor (None without THD values), whether the
    quantiles are line-to-line and whether anything is scaled at all."""
    u95_reference = {"ll": "LL", "seq": "seq"}.get(str(u95_reference).lower(), u95_reference)
    check_option("u95_reference", u95_reference, ("seq", "LL"))
    f_thd = None
    if thd95_percent is not None:
        if not thd_measured_percent or thd_measured_percent <= 0:
            raise ValueError(tr("equivalent_source.thd_measured_missing"))
        f_thd = safety_factor * thd95_percent / thd_measured_percent
    ll = u95_reference == "LL"
    scaled = bool(u95) or f_thd is not None
    min_level = float(series.settings.get("min_level_V", 1.0))
    k, rules = {}, {}
    for m, F in series.fits.items():
        if scaled:
            k[m], rules[m] = _order_factor(m, _u95_of(u95, m), F.level_reference, f_thd, safety_factor, ll, min_level)
        else:
            k[m], rules[m] = 1.0, _RULE_MEASURED
    return k, rules, f_thd, ll, scaled


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


def _rest_terms(series: SourceSeries) -> List[dict]:
    """The remainder of every test split into its orders: ``name``, ``rest`` (total in A), ``terms`` [(m, |I_m|,
    level of the natural sequence of m in V)] of the orders with a phasor outside the model, and ``other`` (content
    not assigned to an order, e.g. orders without a phasor in the result file)."""
    fitted = set(series.fits)
    reference = series.settings.get("reference", "mean")
    reference = reference if reference in _LEVELS else "mean"
    out = []
    for mm, r in zip(series.measurements, series.ih_rest()):
        terms, s2 = [], 0.0
        for m in sorted(mm.I):
            if m < 2 or m in fitted:
                continue
            i = float(abs(mm.I[m]))
            level = float(abs(mm.level(m, natural_sequence(m), reference, complex_=False)))
            terms.append((int(m), i, level))
            s2 += i * i
        other = math.sqrt(max(r * r - s2, 0.0)) if np.isfinite(r) else float("nan")
        out.append(dict(name=mm.name, rest=float(r), terms=terms, other=other))
    return out


def _rest_largest(terms: Sequence[dict], u95: Optional[Mapping[int, float]], ll: bool, f_thd: Optional[float],
                  safety_factor: float, min_level: float, scaled: bool) -> Optional[dict]:
    """The remainder of the test with the largest (scaled) remainder: ``total`` in A, ``index``, ``name``, ``rows``
    [(m, |I_m|, level, factor, rule)] and ``other``; None if no test has a remainder."""
    best = None
    for j, t in enumerate(terms):
        if not np.isfinite(t["rest"]):
            continue
        rows, s2 = [], 0.0
        for m, i, level in t["terms"]:
            k, rule = (_order_factor(m, _u95_of(u95, m), level, f_thd, safety_factor, ll, min_level) if scaled
                       else (1.0, _RULE_MEASURED))
            rows.append((m, i, level, k, rule))
            s2 += (k * i) ** 2
        other = t["other"] if np.isfinite(t["other"]) else 0.0
        total = math.sqrt(s2 + other ** 2)
        if best is None or total > best["total"]:
            best = dict(total=total, index=j, name=t["name"], rows=rows, other=other)
    return best


def _ires(series: SourceSeries, Z_E: complex, IG: Union[str, float], u95: Optional[Mapping[int, float]],
          u95_reference: str, thd95_percent: Optional[float], thd_measured_percent: Optional[float],
          safety_factor: float, rest: bool, uncertainty_I: float, terms: Optional[List[dict]] = None,
          table: bool = True, thd_text: Optional[str] = None) -> Dict[str, object]:
    """Residual current at Z_E with the scaling rules (see ires_at_impedance); ``terms`` = precomputed
    ``_rest_terms`` (time series), ``table`` = build the table and the hints, ``thd_text`` = text of the THD
    fallback in the hint (time series: a factor per time step)."""
    ig = _ig_choice(series, IG)
    k, rules, f_thd, ll, scaled = _scaling(series, u95, u95_reference, thd95_percent, thd_measured_percent,
                                           safety_factor)
    min_level = float(series.settings.get("min_level_V", 1.0))
    parts, parts_s = {}, {}
    for m, F in sorted(series.fits.items()):
        parts[m] = F.current(Z_E)
        parts_s[m] = F.current(Z_E, k[m])
    r = _rest(series, rest)
    best = None
    if rest:
        best = _rest_largest(terms if terms is not None else _rest_terms(series), u95, ll, f_thd, safety_factor,
                             min_level, scaled)
    r_s = (best["total"] if best is not None else r) if scaled else r
    IH = math.sqrt(sum(v * v for v in parts.values()) + r * r)
    IHs = math.sqrt(sum(v * v for v in parts_s.values()) + r_s * r_s)
    IRES = math.sqrt(ig ** 2 + IH ** 2)
    IRESs = math.sqrt(ig ** 2 + IHs ** 2)
    zmin, zmax = series.Z_range
    out = dict(Z_E=Z_E, IG=ig, IH=IH, IRES=IRES, parts=parts, factors=k, rules=rules, IH_rest=r, IH_rest_scaled=r_s,
               IH_scaled=IHs, IRES_scaled=IRESs,
               IRES_assessed=IRES * (1 + uncertainty_I), IRES_scaled_assessed=IRESs * (1 + uncertainty_I),
               interpolation=bool(zmin - 1e-9 <= abs(Z_E) <= zmax + 1e-9))
    if not table:
        return out
    # ---- the result per order: the orders of the model at Z_E and the remainder of the test with the largest one
    f1 = float(np.mean([mm.f1 for mm in series.measurements])) if series.measurements else 50.0
    rows = []
    for m, F in sorted(series.fits.items()):
        rows.append(dict(order=m, f_Hz=F.f_Hz, category=fml.harmonic_category(m), part="model", test="",
                         I_A=parts[m], U_level_V=F.level_reference,
                         U95_V=_u95_of(u95, m) if _u95_of(u95, m) is not None else np.nan, factor=k[m],
                         rule=rules[m], I_scaled_A=parts_s[m]))
    if best is not None:
        for m, i, level, kk, rule in best["rows"]:
            rows.append(dict(order=m, f_Hz=m * f1, category=fml.harmonic_category(m), part="remainder",
                             test=best["name"], I_A=i, U_level_V=level,
                             U95_V=_u95_of(u95, m) if _u95_of(u95, m) is not None else np.nan, factor=kk, rule=rule,
                             I_scaled_A=kk * i))
    columns = ["order", "f_Hz", "category", "part", "test", "I_A", "U_level_V", "U95_V", "factor", "rule",
               "I_scaled_A"]
    tab = pd.DataFrame(rows, columns=columns).sort_values(["order", "part"], kind="stable").reset_index(drop=True)
    other = best["other"] if best is not None else 0.0
    tab.attrs["other_A"] = other
    tab.attrs["test"] = best["name"] if best is not None else ""
    out["table"] = tab
    out["rest_test"] = best["name"] if best is not None else ""
    quad = lambda cat: float(math.sqrt(float((tab.loc[tab["category"] == cat, "I_scaled_A"] ** 2).sum())))
    out.update(IH_zero=quad("zero"), IH_even=quad("even"), IH_other=float(other))
    hints: List[str] = []
    if scaled:
        without = sorted({int(m) for m, rl in zip(tab["order"], tab["rule"]) if rl in (_RULE_THD, _RULE_NONE)})
        if without:
            fallback = (tr("equivalent_source.scaling_unscaled") if f_thd is None else
                        thd_text or tr("equivalent_source.scaling_thd_factor", factor=f_thd))
            hints.append(tr("equivalent_source.scaling_not_possible", orders=without, min_level=min_level,
                            fallback=fallback))
        zero = sorted({int(m) for m in tab.loc[tab["category"] == "zero", "order"]})
        if zero:
            hints.append(tr("equivalent_source.scaling_zero_measured", orders=zero))
        if other > 0.01 * IH:                     # content without an order: a hint from 1 % of the harmonic content
            hints.append(tr("equivalent_source.scaling_other", current=other))
    even = tab[tab["category"] == "even"]
    if len(even) and IH > 0 and out["IH_even"] >= _EVEN_HINT_SHARE * IH:
        top = even.loc[even["I_A"].idxmax()]
        hints.append(tr("equivalent_source.even_orders", orders=sorted(int(m) for m in even["order"]),
                        current=out["IH_even"], share=100 * out["IH_even"] / IH, order=int(top["order"]),
                        largest=float(top["I_A"])))
    out["hints"] = hints
    return out


def ires_at_impedance(series: SourceSeries, Z_E: complex, IG: Union[str, float] = "max",
                      u95: Optional[Mapping[int, float]] = None, u95_reference: str = "seq",
                      thd95_percent: Optional[float] = None, thd_measured_percent: Optional[float] = None,
                      safety_factor: float = 1.0, rest: bool = True,
                      uncertainty_I: float = 0.0) -> Dict[str, object]:
    """Residual earth-fault current at the earthing impedance Z_E from the equivalent sources.

    I_RES(Z_E) = √(I_G² + Σ_n |k_n·U_q,n/(Z_q,n + Z_E)|² + I_rest²)

    Scaling to a power-quality quantile (``u95`` and/or ``thd95_percent``), per order
    ([`groundfault.formulas.harmonic_category`][groundfault.formulas.harmonic_category]):

    * orders of the positive or negative sequence (5, 7, 11, 13, 17, 19 …): with their own voltage,
      k_m = safety_factor·U_95,m/U_level,m (U_level,m = level of the natural sequence of m in the tests); an order
      without its own value (no ``u95`` value, no level of at least ``settings["min_level_V"]``) with the flat THD
      factor safety_factor·THD_95/THD_test, without a THD as measured (with a hint);
    * orders of the zero sequence (3, 9, 15 …): as measured – the zero sequence arises in the earth fault;
    * even orders (2, 4, 6 …): as measured, listed separately (a hint if they carry 5 % of the harmonic content or
      more – atypical, they may point to another cause);
    * the remainder I_rest outside the orders of the model: the same rules for each of its orders, with the levels of
      the test it comes from (the test with the largest scaled remainder); content not assigned to an order as
      measured.

    Parameters
    ----------
    series : SourceSeries
        Result of [`fit_equivalent_source`][groundfault.equivalent_source.fit_equivalent_source] or
        [`measured_source`][groundfault.equivalent_source.measured_source].
    Z_E : complex
        Earthing impedance in Ω.
    IG : {"max", "median"} or float, optional
        Fundamental component: ``"max"`` (largest measured value, conservative), ``"median"`` or a number in A (e.g.
        from network data,
        [`groundfault.formulas.fundamental_from_network_data`][groundfault.formulas.fundamental_from_network_data]).
    u95 : mapping of int to float, optional
        95 % quantile of the harmonic voltage per order in V for the scaling per order.
    u95_reference : {"seq", "LL"}, optional
        Reference of ``u95``: ``"seq"`` = sequence voltage line-to-earth (e.g. the largest phase of a PQ
        measurement), ``"LL"`` = line-to-line (divided by √3).
    thd95_percent, thd_measured_percent : float, optional
        Flat factor with the THD: 95 % quantile of the THD and THD of the measurement series in % – for the orders of
        the positive or negative sequence without their own value (alone: for all of them).
    safety_factor : float, optional
        Additional factor applied to the scaling factors (1 = none).
    rest : bool, optional
        Add the harmonic content not covered by the two-terminal equivalents (largest value of the series,
        independent of Z_E – conservative) quadratically.
    uncertainty_I : float, optional
        Measurement-uncertainty margin m_I of currents for the assessment values ``IRES_assessed`` =
        I_RES·(1 + m_I), defined by the user; default 0 (no margin).

    Returns
    -------
    dict
        ``Z_E``, ``IG``, ``IH``, ``IRES``, ``parts`` ({order: current in A}, unscaled), ``factors`` ({order: scaling
        factor}), ``rules`` ({order: rule}), ``IH_rest``, ``IH_rest_scaled``, ``IH_scaled``, ``IRES_scaled``,
        ``IRES_assessed``, ``IRES_scaled_assessed``, ``IH_zero``, ``IH_even`` and ``IH_other`` (not scaled parts of
        the scaled result), ``rest_test`` (test of the remainder), ``table`` (the result per order: ``order``,
        ``f_Hz``, ``category``, ``part`` = ``"model"``/``"remainder"``, ``test``, ``I_A``, ``U_level_V``, ``U95_V``,
        ``factor``, ``rule`` = ``"own voltage"``/``"THD"``/``"as measured"``/``"no information"``, ``I_scaled_A``),
        ``interpolation`` (True if |Z_E| lies within the range of the additional impedances) and ``hints``.

    Raises
    ------
    ValueError
        If ``thd95_percent`` is given without a positive ``thd_measured_percent``, or for an unknown ``IG`` or
        ``u95_reference``.
    """
    return _ires(series, Z_E, IG, u95, u95_reference, thd95_percent, thd_measured_percent, safety_factor, rest,
                 uncertainty_I)


def ires_over_time(series: SourceSeries, Z_E: complex, voltages: pd.DataFrame, IG: Union[str, float] = "max",
                   u95_reference: str = "seq", thd_percent: Optional[pd.Series] = None,
                   thd_measured_percent: Optional[float] = None, safety_factor: float = 1.0, rest: bool = True,
                   uncertainty_I: float = 0.0) -> pd.DataFrame:
    """Residual current at Z_E for every time step of a series of harmonic voltages (e.g. the 10-min values of a
    power-quality measurement).

    Per time step t the harmonic voltages U_m(t) take the place of ``u95`` in
    [`ires_at_impedance`][groundfault.equivalent_source.ires_at_impedance] (and ``thd_percent(t)`` that of
    ``thd95_percent``), with the same rules per order. A quantile of the result is the quantile of the residual current
    itself – smaller than the residual current from the quantiles of the voltages when the orders do not reach their
    high values at the same time.

    Parameters
    ----------
    series : SourceSeries
        Equivalent sources (fitted or measured).
    Z_E : complex
        Earthing impedance in Ω.
    voltages : pandas.DataFrame
        One row per time step, one column per order (int) – harmonic voltage in V with the reference
        ``u95_reference`` (e.g. the largest phase per interval, line-to-earth).
    IG, u95_reference, safety_factor, rest, uncertainty_I
        As in [`ires_at_impedance`][groundfault.equivalent_source.ires_at_impedance].
    thd_percent : pandas.Series, optional
        THD per time step in % (same index) for the flat factor of the orders without their own voltage.
    thd_measured_percent : float, optional
        THD of the series of fault tests in % (needed with ``thd_percent``).

    Returns
    -------
    pandas.DataFrame
        Index of ``voltages``; columns ``IG``, ``IH``, ``IRES``, ``IRES_assessed``, ``IH_rest`` and ``I_<m>_A`` per
        order of the series (scaled). A time step without the voltage of an order of the model that is scaled with
        its own voltage is NaN (it does not enter a quantile). ``attrs["hints"]`` holds the hints (once each).

    Raises
    ------
    ValueError
        If no column of ``voltages`` is an order of the series, or as in ``ires_at_impedance``.
    """
    cols = {}
    for c in voltages.columns:
        try:
            cols[int(c)] = c
        except (TypeError, ValueError):
            continue
    if not set(cols) & set(series.fits):
        raise ValueError(tr("equivalent_source.voltages_no_orders", orders=sorted(series.fits)))
    rows, hints = [], []
    values = voltages[[cols[m] for m in sorted(cols)]].to_numpy(float)
    orders = sorted(cols)
    thd = thd_percent.reindex(voltages.index).to_numpy(float) if thd_percent is not None else None
    # a time step without the voltage of an order of the model scaled with its own voltage is left out (not the
    # unscaled test level)
    needed = [j for j, m in enumerate(orders) if m in series.fits and fml.harmonic_category(m) == "pos_neg"]
    empty = dict(IG=np.nan, IH=np.nan, IRES=np.nan, IRES_assessed=np.nan, IH_rest=np.nan,
                 **{"I_%d_A" % m: np.nan for m in sorted(series.fits)})
    terms = _rest_terms(series)
    n_missing, first = 0, True
    for i, t in enumerate(voltages.index):
        if needed and not np.all(np.isfinite(values[i, needed])):
            n_missing += 1
            rows.append(dict(empty))
            continue
        u = {m: float(values[i, j]) for j, m in enumerate(orders) if np.isfinite(values[i, j])}
        kw = dict(thd95_percent=float(thd[i]), thd_measured_percent=thd_measured_percent) \
            if thd is not None and np.isfinite(thd[i]) else dict(thd95_percent=None, thd_measured_percent=None)
        r = _ires(series, Z_E, IG, u, u95_reference, kw["thd95_percent"], kw["thd_measured_percent"], safety_factor,
                  rest, uncertainty_I, terms=terms, table=first, thd_text=tr("equivalent_source.scaling_thd_per_step"))
        if first:                                  # the hints of the first time step (the rules are the same)
            hints.extend(h for h in r["hints"] if h not in hints)
            first = False
        row = dict(IG=r["IG"], IH=r["IH_scaled"], IRES=r["IRES_scaled"], IRES_assessed=r["IRES_scaled_assessed"],
                   IH_rest=r["IH_rest_scaled"])
        row.update({"I_%d_A" % m: r["parts"][m] * r["factors"][m] for m in sorted(series.fits)})
        rows.append(row)
    if n_missing:
        hints.append(tr("equivalent_source.voltages_missing", n=n_missing, total=len(voltages)))
    out = pd.DataFrame(rows, index=voltages.index)
    out.attrs["hints"] = hints
    return out


def ires_over_line(series: SourceSeries, Z_E: complex, Z1L: Union[complex, Callable[[int], complex]],
                   Z0L: Union[complex, Callable[[int], complex]], IG: Union[str, float] = "max",
                   factors: Optional[Mapping[int, float]] = None, rest: bool = True,
                   rest_A: Optional[float] = None) -> Dict[str, object]:
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
        Scaling factor k_m per order (default 1), e.g. ``factors`` of
        [`ires_at_impedance`][groundfault.equivalent_source.ires_at_impedance].
    rest : bool, optional
        Add the harmonic content not covered by the two-terminal equivalents (independent of the line –
        conservative).
    rest_A : float, optional
        The remainder in A instead of the largest unscaled one of the series – e.g. ``IH_rest_scaled`` of
        ``ires_at_impedance`` with the same scaling.

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
    r = (float(rest_A) if rest_A is not None else _rest(series, True)) if rest else 0.0   # independent of the line
    IH = math.sqrt(sum(v * v for v in parts.values()) + r * r)
    return dict(IG=ig, IH=IH, IRES=math.sqrt(ig ** 2 + IH ** 2), parts=parts, IH_rest=r)


def monte_carlo(series: SourceSeries, Z_E: complex, n: int = 2000, sigma_magnitude: float = 0.01,
                sigma_phase_deg: float = 0.5, sigma_Z: float = 0.02, sigma_level: float = 0.0,
                IG: Union[str, float] = "max", seed: int = 0, model_error: bool = True) -> Dict[str, object]:
    """Uncertainty of I_RES(Z_E) due to random measurement errors (Monte Carlo).

    The errors are normally distributed (1σ). Every run repeats the fit with the same estimator (and the
    boundary solution R_q = 0 if the series was fitted with ``rq_non_negative``); with the measured source
    ([`measured_source`][groundfault.equivalent_source.measured_source]) it determines Z_q again from the falsified
    currents with the same rule and keeps the measured U_q (a level error enters through the normalized currents).

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
    rq = bool(series.settings.get("rq_non_negative"))
    impedance = series.settings.get("impedance", "median")
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
            if F.method == "measured":
                Uq = F.Uq
                Zq, _ = _measured_impedance(I, Zs, Uq, impedance, rq)
            else:
                meth = "equation_error" if F.method == "rq0" else F.method
                Uq, Zq = _fit(I, Zs, meth)
                if rq and Zq.real < 0:
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
