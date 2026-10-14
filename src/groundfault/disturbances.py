# -*- coding: utf-8 -*-
"""Disturbed states during the earth fault: active residual current increase and network changes.

While the staged fault persists, the state of the network can change:

* **Active residual current increase** (for locating the faulted feeder): for a few seconds a resistor is switched to
  the auxiliary winding of a coil. The active component Iw of the fault current rises abruptly by several amperes and
  falls back when the resistor is switched off.
* **Network change**: a network section trips or is switched. The capacitive earth-fault current – and therefore
  the detuning Iv, the fundamental component and the RMS value of the residual current – changes abruptly, and the
  new state persists.

Neither is the normal state of the network, so neither may serve as the reference of the assessment.
[`groundfault.evaluate`][groundfault.evaluation.evaluate] detects such windows in the steady-state interval and
leaves them out of the search for the max window, the statistics and the checks over the interval
(``Settings.exclude_disturbances``); the assessment uses the **undisturbed state** only. A change of the coil
current is not a disturbance in this sense – a motor-driven coil adjustment changes Iv gradually, and a coil step
is recognised by the measured coil currents (the stationarity check and the coil-current balance of the evaluation
report both).

Detection, per window of the steady-state interval:

0. Windows **without fault current** – before the fault inception or after the clearance, if the interval reaches
   beyond the fault – are no state of the fault: an RMS value of the fault current below
   [`FAULT_SHARE`][groundfault.disturbances.FAULT_SHARE] of its largest value in the interval (median of three
   consecutive windows). They get the state ``"no fault current"``, are never part of the reference and do not take
   part in the detection of steps.
1. Iw and Iv of the fundamental component by the angle method (relative to the zero-sequence voltage U0, oriented
   so that the median of Iw is positive); the sum of the coil currents (fundamental, referred to the mean |U0|) if
   measured. Without U0 (e.g. at a station without voltage measurement) only the magnitude |I_H1| is used; the
   cause of a step then remains open.
2. **Steps**: window k is the transition of a step of a quantity if the medians of the
   [`STEP_WINDOWS`][groundfault.disturbances.STEP_WINDOWS] windows before and after it differ by at least the
   threshold and by at least [`STEP_FLATNESS`][groundfault.disturbances.STEP_FLATNESS] times the spread (maximum −
   minimum) of the windows on either side – an abrupt step, not a ramp. The threshold is ``threshold``·|I_H1| of the
   undisturbed state, at least [`STEP_MIN_A`][groundfault.disturbances.STEP_MIN_A].
3. **Cause of a step of Iv**: at an active step a small simultaneous step of Iv (below
   [`ACTIVE_REACTIVE`][groundfault.disturbances.ACTIVE_REACTIVE] of the active step) belongs to the increase.
   Otherwise, since Iv = ΣI_coil − I_C: if the coil currents are measured and change by at least
   [`COIL_SHARE`][groundfault.disturbances.COIL_SHARE] of the step, it is a coil change (no disturbance); if they
   stay the same, it is a network change. Without coil currents the cause is open (``"reactive step"``) and the step
   is treated as a network change.
4. **States**: the abrupt steps of Iw are added up; a window whose level lies at least one threshold above the lowest
   level is in an active residual current increase (the increase only ever adds active current, so an interval may
   also start during one). The network steps of Iv (of |I_H1| without U0) are added up as well; a window whose level
   differs from that of the first window by at least one threshold is in a changed state – the start of the
   interval is the reference, so it should lie in the undisturbed state after the transient. Transition windows
   belong to the disturbed one of their neighbours and are never part of the reference.

[`scan`][groundfault.disturbances.scan] applies the same detection to the whole fault (from the settled fault
current after inception to the clearance) and suggests the undisturbed part as the steady-state interval.

Examples
--------
>>> import numpy as np
>>> from groundfault import disturbances
>>> t = 0.1 + 0.2 * np.arange(30)                                  # window centres in s
>>> U0 = np.full(30, 11500 + 0j)
>>> I1 = np.where((t > 3.0) & (t < 4.4), 40 - 5j, 24 - 5j)          # active component +16 A from 3.0 s to 4.4 s
>>> d = disturbances.detect(t, I1, U0)
>>> print(d.segments[["from_s", "to_s", "state", "windows", "used", "d_Iw_A"]].round(1).to_string(index=False))
 from_s  to_s           state  windows  used  d_Iw_A
    0.0   3.0       reference       15  True     0.0
    3.0   4.4 active increase        7 False    16.0
    4.4   6.0       reference        8  True     0.0

The steps fall on window boundaries here, so no window straddles them; the max window is searched among the 23
undisturbed windows. If the interval reaches beyond the clearance, the windows without fault current are left out as
well:

>>> I2 = np.where(t > 5.0, 0.02, I1)                               # fault cleared at 5.0 s
>>> print(disturbances.detect(t, I2, U0).parts_text())
active residual current increase 3.0–4.4 s (ΔIw +16.0 A); no fault current (before the fault inception or after the clearance) 5.0–6.0 s
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import i18n
from .i18n import tr

__all__ = ["Disturbances", "detect", "scan", "window_phasors", "STATES", "EVENTS", "REFERENCE", "NO_FAULT",
           "STEP_WINDOWS", "STEP_FLATNESS", "STEP_MIN_A", "COIL_SHARE", "ACTIVE_REACTIVE", "THRESHOLD", "FAULT_SHARE"]

REFERENCE = "reference"
"""State code of the undisturbed windows."""
_ACTIVE = "active increase"
_NETWORK = "network change"
_REACTIVE = "reactive step"
_FUNDAMENTAL = "fundamental step"
NO_FAULT = "no fault current"
"""State code of the windows without fault current (before the inception or after the clearance)."""
STATES = (REFERENCE, _ACTIVE, _NETWORK, _REACTIVE, _ACTIVE + " + " + _NETWORK, _ACTIVE + " + " + _REACTIVE,
          _FUNDAMENTAL, NO_FAULT)
"""State codes of the windows (column ``state`` of the segment table): ``"reference"`` (undisturbed),
``"active increase"`` (active residual current increase), ``"network change"`` (step of the reactive component with
unchanged coil currents), ``"reactive step"`` (step of the reactive component, coil currents not measured – network
or coil), combinations ``"active increase + network change"`` and ``"active increase + reactive step"``,
``"fundamental step"`` (step of |I_H1| without U0, cause open) and ``"no fault current"`` (window before the fault
inception or after the clearance)."""
EVENTS = ("active increase", "active decrease", "network change", "coil change", "reactive step", "fundamental step")
"""Kinds of steps (column ``kind`` of the event table); a ``"coil change"`` is reported but is not a disturbance."""

STEP_WINDOWS = 3
"""Windows before and after a transition window that give the levels of a step (3 windows of 200 ms = 0.6 s)."""
STEP_FLATNESS = 3.0
"""A step must be at least this many times the spread (maximum − minimum) of the windows on either side – an
abrupt change, not a ramp (a uniform ramp gives a ratio of 2)."""
STEP_MIN_A = 0.5
"""Smallest step in A that counts as a disturbance (for small fault currents)."""
COIL_SHARE = 0.25
"""A step of Iv is a coil change if the measured coil currents change by at least this share of the step (also
with a coil channel that captures only one of several conductors); below it, a network change."""
ACTIVE_REACTIVE = 0.5
"""At an active step, a simultaneous step of Iv smaller than this share of the active step is part of the active
residual current increase (its resistor shifts the reactive component a little), not a separate network change."""
THRESHOLD = 0.05
"""Default threshold of a step as a share of |I_H1| of the undisturbed state (the stationarity check of the
evaluation uses the same share)."""
FAULT_SHARE = 0.1
"""A window whose RMS value of the fault current (|I_H1| without RMS values) is below this share of the largest value
in the interval – median of three consecutive windows, so that a single outlier does not count – has no fault
current: it lies before the fault inception or after the clearance."""

i18n.register({
    "disturbances.excluded": {
        "en": "Disturbed states excluded: {parts}. Max window, statistics and checks use the undisturbed state "
              "({reference}).",
        "de": "Gestörte Zustände ausgeblendet: {parts}. Max-Fenster, Statistik und Prüfungen verwenden den "
              "ungestörten Zustand ({reference})."},
    "disturbances.not_excluded": {
        "en": "Disturbed states in the steady-state interval: {parts} – not excluded (exclude_disturbances=False); "
              "the max window may lie in a disturbed state.",
        "de": "Gestörte Zustände im stationären Bereich: {parts} – nicht ausgeblendet (exclude_disturbances=False); "
              "das Max-Fenster kann in einem gestörten Zustand liegen."},
    "disturbances.no_reference": {
        "en": "Disturbed states detected ({parts}), but no undisturbed window is left – all windows are used. Check "
              "the steady-state interval.",
        "de": "Gestörte Zustände erkannt ({parts}), aber kein ungestörtes Fenster übrig – alle Fenster werden "
              "verwendet. Stationären Bereich prüfen."},
    "disturbances.reactive_open": {
        "en": "A step of the reactive component without coil-current measurement is treated as a network change; if "
              "it was a coil change, set exclude_disturbances=False.",
        "de": "Ein Sprung im Blindanteil ohne Spulenstrommessung wird als Netzänderung behandelt; war es eine "
              "Spulenverstellung, exclude_disturbances=False setzen."},
    "disturbances.coil_change": {
        "en": "Coil change at {t} s (ΔIv {d_iv:+.1f} A, ΔΣI_coil {d_coil:+.1f} A) – part of the reference (not a "
              "disturbance).",
        "de": "Spulenverstellung bei {t} s (ΔIv {d_iv:+.1f} A, ΔΣI_Spule {d_coil:+.1f} A) – Teil der Referenz (keine "
              "Störung)."},
    "disturbances.part": {"en": "{state} {t0}–{t1} s", "de": "{state} {t0}–{t1} s"},
    "disturbances.part_from": {"en": "{state} from {t0} s", "de": "{state} ab {t0} s"},
    "disturbances.step_iw": {"en": "ΔIw {d:+.1f} A", "de": "ΔIw {d:+.1f} A"},
    "disturbances.step_iv": {"en": "ΔIv {d:+.1f} A", "de": "ΔIv {d:+.1f} A"},
    "disturbances.step_ih1": {"en": "Δ|I_H1| {d:+.1f} A", "de": "Δ|I_H1| {d:+.1f} A"},
    "disturbances.check": {"en": "Disturbed states in the steady-state interval",
                           "de": "Gestörte Zustände im stationären Bereich"},
    "disturbances.check_none": {"en": "none detected (threshold {threshold:.2f} A)",
                                "de": "keine erkannt (Schwelle {threshold:.2f} A)"},
    "disturbances.comment_none": {
        "en": "no active residual current increase, no network change",
        "de": "keine Wattreststromerhöhung, keine Netzänderung"},
    "disturbances.comment_none_u0": {
        "en": "no step of the fundamental component (without U0 active and reactive component are not separable)",
        "de": "kein Sprung der Grundschwingung (ohne U0 sind Wirk- und Blindanteil nicht trennbar)"},
    "disturbances.comment_excluded": {
        "en": "excluded – the assessment uses the undisturbed state {reference}",
        "de": "ausgeblendet – die Bewertung verwendet den ungestörten Zustand {reference}"},
    "disturbances.comment_not_excluded": {
        "en": "not excluded (exclude_disturbances=False)",
        "de": "nicht ausgeblendet (exclude_disturbances=False)"},
    "disturbances.no_fault": {
        "en": "No fault found in the recording (fault current) – nothing to scan.",
        "de": "Kein Fehler in der Aufzeichnung gefunden (Fehlerstrom) – nichts zu durchsuchen."},
    "disturbances.summary": {
        "en": "Fault {fault}, scanned {t0}–{t1} s (threshold {threshold:.2f} A). Suggestion: STEADY_STATE = "
              "{suggestion}",
        "de": "Fehler {fault}, durchsucht {t0}–{t1} s (Schwelle {threshold:.2f} A). Vorschlag: STEADY_STATE = "
              "{suggestion}"},
    "disturbances.fault_span": {"en": "{t_on}–{t_off} s", "de": "{t_on}–{t_off} s"},
    "disturbances.fault_from": {"en": "from {t_on} s (until the end of the recording)",
                                "de": "ab {t_on} s (bis zum Ende der Aufzeichnung)"},
    "disturbances.fault_until": {"en": "from the start of the recording until {t_off} s",
                                 "de": "vom Beginn der Aufzeichnung bis {t_off} s"},
    "disturbances.summary_states": {"en": "Disturbed: {parts}", "de": "Gestört: {parts}"},
    "disturbances.summary_none": {"en": "No disturbed state found.", "de": "Kein gestörter Zustand gefunden."},
    "disturbances.summary_estimated": {
        "en": "Fault current estimated from the negative-sequence current of the transformer (fault in {phase}); its "
              "steps are reliable, its level is an estimate.",
        "de": "Fehlerstrom aus dem Gegenstrom des Trafos geschätzt (Fehler in {phase}); seine Sprünge sind "
              "verlässlich, sein Pegel ist eine Schätzung."},
})
i18n.VALUES_DE["state"] = {
    REFERENCE: "Referenz (ungestört)", _ACTIVE: "Wattreststromerhöhung", _NETWORK: "Netzänderung",
    _REACTIVE: "Sprung im Blindanteil (Netz oder Spule)",
    _ACTIVE + " + " + _NETWORK: "Wattreststromerhöhung + Netzänderung",
    _ACTIVE + " + " + _REACTIVE: "Wattreststromerhöhung + Sprung im Blindanteil",
    _FUNDAMENTAL: "Sprung der Grundschwingung (Ursache offen, ohne U0)",
    NO_FAULT: "ohne Fehlerstrom (vor dem Fehlereintritt bzw. nach der Fehlerklärung)"}
i18n.VALUES_DE["kind"].update({"active increase": "Wirkanteil steigt", "active decrease": "Wirkanteil fällt",
                               "network change": "Netzänderung", "coil change": "Spulenverstellung",
                               "reactive step": "Sprung im Blindanteil", "fundamental step": "Sprung der Grundschwingung"})
i18n.COLUMNS_DE.update({"from_s": "von_s", "to_s": "bis_s", "state": "Zustand", "windows": "Fenster",
                        "used": "verwendet", "IH1_A": "IH1_A", "IRES_A": "IRES_A", "d_Iw_A": "dIw_A",
                        "d_Iv_A": "dIv_A", "d_IH1_A": "dIH1_A", "d_coil_A": "dSpule_A",
                        "steady_state_segments": "zustaende_stationaer"})


_LABELS_EN = {_ACTIVE: "active residual current increase", _NETWORK: "network change",
              _REACTIVE: "step of the reactive component (network or coil)",
              _FUNDAMENTAL: "step of the fundamental component (cause open, without U0)",
              NO_FAULT: "no fault current (before the fault inception or after the clearance)"}


def _label(code: str) -> str:
    """Display text of a state in the output language."""
    if i18n.get_language() == "de":
        return i18n.value_label("state", code, "de")
    return _LABELS_EN.get(code, code)


def _seconds(x) -> str:
    """Time in s with one decimal (decimal comma in German); ``"–"`` for None."""
    if x is None:
        return "–"
    return i18n.format_number(float(x), digits=1, mode="fixed")


@dataclass
class Disturbances:
    """Result of [`detect`][groundfault.disturbances.detect] (or [`scan`][groundfault.disturbances.scan]).

    Attributes
    ----------
    t_s : numpy.ndarray
        Window centres in s.
    state : numpy.ndarray of str
        State per window (codes [`STATES`][groundfault.disturbances.STATES]; ``""`` for windows without values).
    reference : numpy.ndarray of bool
        Window belongs to the undisturbed state and is not a transition window.
    events : pandas.DataFrame
        Steps found: ``t_s`` (centre of the transition window), ``kind`` ([`EVENTS`][groundfault.disturbances.EVENTS]),
        ``d_Iw_A``, ``d_Iv_A``, ``d_IH1_A`` and ``d_coil_A`` (step of the sum of the coil currents).
    segments : pandas.DataFrame
        Consecutive windows of the same state: ``from_s``, ``to_s``, ``state``, ``windows``, ``used`` (part of the
        reference), the medians ``Iw_A``, ``Iv_A``, ``IH1_A``, ``IRES_A`` and the differences ``d_Iw_A``,
        ``d_Iv_A``, ``d_IH1_A`` to the undisturbed state.
    threshold_A : float
        Threshold of a step in A.
    with_u0 : bool
        Active and reactive component separated (U0 available).
    with_coils : bool
        Coil currents measured (cause of a step of Iv determinable).
    T_win : float
        Window length in s.
    meta : dict
        Additional information (e.g. the scanned range of [`scan`][groundfault.disturbances.scan]).
    episodes : list of dict
        One entry per disturbance (``kind`` ``"active"``, ``"network"``, ``"fundamental"`` or ``"no_fault"``,
        ``from_s``, ``to_s``, ``until_end`` – it lasts until the end of the interval –, ``step_A`` – median step of Iw,
        Iv or |I_H1| against the undisturbed state, NaN without fault current); the basis of
        [`parts_text`][groundfault.disturbances.Disturbances.parts_text].
    """
    t_s: np.ndarray
    state: np.ndarray
    reference: np.ndarray
    events: pd.DataFrame
    segments: pd.DataFrame
    threshold_A: float
    with_u0: bool
    with_coils: bool = False
    T_win: float = 0.2
    meta: Dict[str, object] = field(default_factory=dict)
    episodes: List[dict] = field(default_factory=list)

    @property
    def found(self) -> bool:
        """True if at least one window lies in a disturbed state."""
        return bool(np.any((self.state != REFERENCE) & (self.state != "")))

    def reference_intervals(self) -> List[Tuple[float, float]]:
        """Time ranges (t0, t1) in s of the undisturbed windows."""
        return [(float(r["from_s"]), float(r["to_s"])) for _, r in self.segments.iterrows()
                if r["state"] == REFERENCE]

    def excluded_intervals(self) -> List[Tuple[float, float, str]]:
        """Time ranges (t0, t1, state) in s of the disturbed windows."""
        return [(float(r["from_s"]), float(r["to_s"]), str(r["state"])) for _, r in self.segments.iterrows()
                if r["state"] != REFERENCE]

    def suggestion(self) -> Optional[Tuple[float, float]]:
        """The first undisturbed time range (t0, t1) in s (rounded inwards to 0.1 s) – a proposal for the
        steady-state interval; None without one."""
        for t0, t1 in self.reference_intervals():
            a, b = np.ceil(t0 * 10.0 - 1e-6) / 10.0, np.floor(t1 * 10.0 + 1e-6) / 10.0
            if b - a >= self.T_win:
                return float(round(a, 1)) + 0.0, float(round(b, 1)) + 0.0
        return None

    def parts_text(self) -> str:
        """The disturbances as text in the output language, e.g. ``"active residual current increase 35.3–37.8 s
        (ΔIw +16.7 A); network change from 32.7 s (ΔIv +45.2 A)"``."""
        parts = []
        for e in self.episodes:
            if e["kind"] == "no_fault":
                parts.append(tr("disturbances.part", state=_label(NO_FAULT), t0=_seconds(e["from_s"]),
                                t1=_seconds(e["to_s"])))
                continue
            kind = {"active": _ACTIVE, "network": _NETWORK if self.with_coils else _REACTIVE,
                    "fundamental": _FUNDAMENTAL}[e["kind"]]
            step = {"active": "disturbances.step_iw", "network": "disturbances.step_iv",
                    "fundamental": "disturbances.step_ih1"}[e["kind"]]
            key = "disturbances.part_from" if e["until_end"] else "disturbances.part"
            parts.append(tr(key, state=_label(kind), t0=_seconds(e["from_s"]),
                            t1=_seconds(e["to_s"])) + " (%s)" % tr(step, d=e["step_A"]))
        return "; ".join(parts)

    def reference_text(self) -> str:
        """The undisturbed time ranges as text, e.g. ``"29.7–32.6 s"``."""
        return ", ".join("%s–%s s" % (_seconds(a), _seconds(b)) for a, b in self.reference_intervals())

    def notes(self) -> List[str]:
        """Further hints in the output language: coil changes inside the reference and steps of the reactive
        component whose cause is open."""
        out = []
        for _, r in self.events.iterrows():
            if r["kind"] == "coil change":
                out.append(tr("disturbances.coil_change", t=_seconds(r["t_s"]), d_iv=r["d_Iv_A"], d_coil=r["d_coil_A"]))
        if any(_REACTIVE in str(s) for s in self.segments["state"]):
            out.append(tr("disturbances.reactive_open"))
        return out

    def text(self) -> str:
        """Summary of a [`scan`][groundfault.disturbances.scan] in the output language: fault, scanned range,
        threshold, the suggested steady-state interval and the disturbed time ranges."""
        m = self.meta
        s = self.suggestion()
        on, off = m.get("t_fault_inception_s"), m.get("t_fault_clearance_s")
        if on is not None and off is not None:
            fault = tr("disturbances.fault_span", t_on=_seconds(on), t_off=_seconds(off))
        elif on is not None:
            fault = tr("disturbances.fault_from", t_on=_seconds(on))
        else:
            fault = tr("disturbances.fault_until", t_off=_seconds(off))
        lines = [tr("disturbances.summary", fault=fault, t0=_seconds(m.get("t_from_s")),
                    t1=_seconds(m.get("t_to_s")), threshold=self.threshold_A,
                    suggestion=("(%.1f, %.1f)" % s) if s else "–")]
        lines.append(tr("disturbances.summary_states", parts=self.parts_text()) if self.found
                     else tr("disturbances.summary_none"))
        if m.get("estimated"):
            lines.append(tr("disturbances.summary_estimated", phase=m.get("faulted_phase", "–")))
        lines += self.notes()
        return "\n".join(lines)


def _step(x: np.ndarray, k: int, m: int) -> Tuple[float, float, float]:
    """Step at window ``k`` of the series ``x``: (difference of the medians after and before, largest spread of the
    two sides, median before). Window ``k`` itself (it may straddle the step) is left out; at the first and the last
    window it is the level of its own side."""
    n = x.size
    if k == 0:
        left, right = x[:1], x[1:1 + m]
    elif k == n - 1:
        left, right = x[max(0, k - m):k], x[k:]
    else:
        left, right = x[max(0, k - m):k], x[k + 1:k + 1 + m]
    if left.size == 0 or right.size == 0:
        return float("nan"), float("nan"), float("nan")
    before = float(np.median(left))
    return float(np.median(right)) - before, float(max(np.ptp(left), np.ptp(right))), before


def _abrupt(d: float, s: float, threshold: float, flatness: float) -> bool:
    """A step of size ``d`` with the spread ``s`` beside it counts (abrupt and at least the threshold)."""
    return bool(np.isfinite(d) and abs(d) >= threshold and abs(d) >= flatness * s)


def _events(features: Dict[str, np.ndarray], threshold: float, m: int, flatness: float) -> List[Tuple[int, dict]]:
    """Windows of abrupt steps of any feature → [(k, {feature: (step, spread, level before)})] in time order."""
    n = next(iter(features.values())).size
    if n < 2:
        return []
    candidates = []
    for name, x in features.items():
        for k in range(n):
            d, s, _ = _step(x, k, m)
            if _abrupt(d, s, threshold, flatness):
                candidates.append((abs(d) / threshold, -s, k))
    # one step per change: the strongest candidate, then no further one within m windows
    chosen: List[int] = []
    for _, _, k in sorted(candidates, reverse=True):
        if all(abs(k - c) > m for c in chosen):
            chosen.append(k)
    return [(k, {name: _step(x, k, m) for name, x in features.items()}) for k in sorted(chosen)]


def _position(x: np.ndarray, k: int, j: int, m: int) -> Optional[float]:
    """Relative position (x_j − level before)/(level after − level before) of window ``j`` next to the step at
    window ``k`` (levels as in [`_step`]); None if the step of ``x`` is not significant."""
    d, s, before = _step(x, k, m)
    if not np.isfinite(d) or abs(d) <= max(3.0 * s, 1e-12) or not np.isfinite(x[j]):
        return None
    return float((x[j] - before) / d)


def _classify(events: List[Tuple[int, dict]], features: Dict[str, np.ndarray], threshold: float, flatness: float,
              with_u0: bool, with_coils: bool, rms: Optional[np.ndarray] = None, m: int = STEP_WINDOWS) -> List[dict]:
    """Kind of every step, the steps that count for the states (``active``, ``network``, ``fundamental``), the
    position of window k – ``at`` = 0 (still the state before), 1 (already the state after) or None (it straddles the
    step) – and the transition windows (``transition``: window k and neighbours that lie between the two levels).

    The position is judged from the stepping quantity and from the RMS value of the fault current: the DFT with a
    Hann window hardly sees a step near the edge of a window, the RMS value does."""
    out = []
    n = next(iter(features.values())).size
    for k, d in events:
        e = dict(k=k, active=0.0, network=0.0, fundamental=0.0, kinds=[], at=None, transition=set())
        counted = []
        if with_u0:
            dw, sw, _ = d["Iw"]
            dv, sv, _ = d["Iv"]
            if _abrupt(dw, sw, threshold, flatness):
                e["active"] = dw
                e["kinds"].append("active increase" if dw > 0 else "active decrease")
                counted.append("Iw")
            # the resistor of an active residual current increase also shifts the reactive component a little: at an
            # active step a simultaneous step of Iv counts only if it is comparable in size
            if _abrupt(dv, sv, threshold, flatness) and not (e["active"] and abs(dv) < ACTIVE_REACTIVE * abs(dw)):
                dc = d["coil"][0] if with_coils else np.nan
                if with_coils and np.isfinite(dc) and abs(dc) >= COIL_SHARE * abs(dv):
                    e["kinds"].append("coil change")
                else:
                    e["network"] = dv
                    e["kinds"].append("network change" if with_coils else "reactive step")
                    counted.append("Iv")
        else:
            dh, sh, _ = d["IH1"]
            if _abrupt(dh, sh, threshold, flatness):
                e["fundamental"] = dh
                e["kinds"].append("fundamental step")
                counted.append("IH1")
        if counted:
            name = max(counted, key=lambda c: abs(d[c][0]))
            series = [features[name]] + ([rms] if rms is not None and np.isfinite(rms).all() else [])
            if 0 < k < n - 1:
                # window k: at the level before, after or in between (straddling the step)?
                phis = [p for p in (_position(x, k, k, m) for x in series) if p is not None]
                if phis and all(p < 0.1 for p in phis):
                    e["at"] = 0
                elif phis and all(p > 0.9 for p in phis):
                    e["at"] = 1
                else:
                    e["transition"].add(k)
            else:
                e["transition"].add(k)                     # edge window: a step within the window itself
            # neighbours that do not lie at the level of their side belong to the transition as well
            for j, side in ((k - 1, 0), (k + 1, 1)):
                if 0 <= j < n:
                    phis = [p for p in (_position(x, k, j, m) for x in series) if p is not None]
                    if any((p >= 0.1) if side == 0 else (p <= 0.9) for p in phis):
                        e["transition"].add(j)
        out.append(e)
    return out


def _cumulative(n: int, steps: List[dict], key: str) -> np.ndarray:
    """Cumulative level of the counted steps ``key``: from the window after the step (window k itself if it already
    lies at the new level, or if it is the last window)."""
    level = np.zeros(n)
    for e in steps:
        k, v = e["k"], e[key]
        if v:
            level[k if (e["at"] == 1 or k == n - 1) else k + 1:] += v
    return level


def _flags(n: int, steps: List[dict], threshold: float, with_u0: bool) -> Tuple[Dict[str, np.ndarray], np.ndarray]:
    """Per window: flags of the disturbances (``active``, ``network`` or ``fundamental``) and the transition
    windows."""
    transition = np.zeros(n, bool)
    for e in steps:
        if e["active"] or e["network"] or e["fundamental"]:
            for j in e["transition"]:
                transition[j] = True
    steady = ~transition if (~transition).any() else np.ones(n, bool)
    tol = threshold - 1e-12
    if with_u0:
        a = _cumulative(n, steps, "active")
        r = _cumulative(n, steps, "network")
        flags = {"active": (a - a[steady].min()) >= tol,             # the increase only ever adds active current
                 "network": np.abs(r - r[steady][0]) >= tol}         # the start of the interval is the reference
    else:
        g = _cumulative(n, steps, "fundamental")
        flags = {"fundamental": np.abs(g - g[steady][0]) >= tol}
    # a transition window belongs to the disturbed one of its neighbours
    for name, f in flags.items():
        for k in np.flatnonzero(transition):
            f[k] = any(f[j] for j in (k - 1, k + 1) if 0 <= j < n and not transition[j])
    return flags, transition


def _state_codes(flags: Dict[str, np.ndarray], n: int, with_coils: bool) -> np.ndarray:
    """State code per window from the flags."""
    state = np.full(n, REFERENCE, dtype=object)
    if "fundamental" in flags:
        state[flags["fundamental"]] = _FUNDAMENTAL
        return state
    a, r = flags["active"], flags["network"]
    name = _NETWORK if with_coils else _REACTIVE
    state[a & ~r] = _ACTIVE
    state[r & ~a] = name
    state[a & r] = _ACTIVE + " + " + name
    return state


def _runs(mask: np.ndarray) -> List[Tuple[int, int]]:
    """Runs of True as (first, last) index pairs."""
    out, start = [], None
    for j, v in enumerate(list(mask) + [False]):
        if v and start is None:
            start = j
        elif not v and start is not None:
            out.append((start, j - 1))
            start = None
    return out


def detect(t_s: Sequence[float], I1: Sequence[complex], U0: Optional[Sequence[complex]] = None,
           ires_rms: Optional[Sequence[float]] = None, coil: Optional[Sequence[float]] = None, *,
           threshold: float = THRESHOLD, T_win: float = 0.2, windows: int = STEP_WINDOWS,
           flatness: float = STEP_FLATNESS, min_step_A: float = STEP_MIN_A, orient: bool = True) -> Disturbances:
    """Detect active residual current increases and network changes in a series of windows.

    Parameters
    ----------
    t_s : sequence of float
        Window centres in s.
    I1 : sequence of complex
        Phasor of the fundamental component of the fault current per window.
    U0 : sequence of complex, optional
        Phasor of the zero-sequence voltage (fundamental) per window; without it only steps of |I_H1| are found and
        their cause remains open.
    ires_rms : sequence of float, optional
        RMS value of the fault current per window (column ``IRES_A`` of the segment table).
    coil : sequence of float, optional
        Sum of the coil currents (fundamental, referred to the mean |U0|) per window; with it a step of Iv is
        attributed to the coil or to the network.
    threshold : float, optional
        Smallest step as a share of |I_H1| of the undisturbed state.
    T_win : float, optional
        Window length in s (time ranges of the segments).
    windows : int, optional
        Windows before and after a step that give its levels.
    flatness : float, optional
        A step must be at least ``flatness`` times the spread of the windows on either side.
    min_step_A : float, optional
        Smallest step in A.
    orient : bool, optional
        Orient the angle method by the fault current itself: if the median active component is negative, all
        phasors are rotated by 180° (default). False: ``I1`` is already oriented (positive active component = the
        active current of the earth-fault circuit), e.g. a fault current estimated from other quantities.

    Returns
    -------
    Disturbances
        Windows without finite values (NaN) get the state ``""`` and are not part of the reference.

    Notes
    -----
    The threshold is first taken from the median |I_H1| of all windows, then – once the undisturbed state is known –
    from the median |I_H1| of the undisturbed windows, and the detection is repeated with it.
    """
    t = np.asarray(t_s, float)
    I1 = np.asarray(I1, complex)
    n_all = t.size
    ok = np.isfinite(I1)
    with_u0 = U0 is not None
    if with_u0:
        U0 = np.asarray(U0, complex)
        ok &= np.isfinite(U0) & (np.abs(U0) > 0)
    with_coils = with_u0 and coil is not None
    if with_coils:
        coil = np.asarray(coil, float)
        ok &= np.isfinite(coil)
    rms = np.asarray(ires_rms, float) if ires_rms is not None else np.full(n_all, np.nan)
    idx_ok = np.flatnonzero(ok)
    # windows without fault current (before the inception, after the clearance) are no state of the fault: they take
    # no part in the detection and are never part of the reference
    mag_ok = np.abs(I1[idx_ok])
    no_fault = _without_fault(mag_ok, rms[idx_ok])
    fault_pos = np.flatnonzero(~no_fault)                     # positions of the fault windows within idx_ok
    idx = idx_ok[fault_pos]
    n = idx.size
    Iw_ok = Iv_ok = np.full(idx_ok.size, np.nan)
    if with_u0:
        dphi = np.angle(U0[idx_ok]) - np.angle(I1[idx_ok])
        Iw_ok, Iv_ok = mag_ok * np.cos(dphi), mag_ok * np.sin(dphi)
        if orient and n and np.median(Iw_ok[fault_pos]) < 0:  # orientation of the angle method (Iw > 0)
            Iw_ok, Iv_ok = -Iw_ok, -Iv_ok
    mag, Iw, Iv = mag_ok[fault_pos], Iw_ok[fault_pos], Iv_ok[fault_pos]
    features = {"Iw": Iw, "Iv": Iv} if with_u0 else {"IH1": mag}
    coil_v = coil[idx] if with_coils else None
    steps: List[dict] = []
    events: List[Tuple[int, dict]] = []
    flags: Dict[str, np.ndarray] = {}
    transition = np.zeros(n, bool)
    thr = min_step_A
    if n:
        thr = max(min_step_A, threshold * float(np.median(mag)))
        for _ in range(3):
            events = _events(features, thr, windows, flatness)
            if with_coils:
                events = [(k, {**d, "coil": _step(coil_v, k, windows)}) for k, d in events]
            steps = _classify(events, features, thr, flatness, with_u0, with_coils, rms[idx], windows)
            flags, transition = _flags(n, steps, thr, with_u0)
            disturbed = np.any(np.stack(list(flags.values())), axis=0) | transition
            thr_new = max(min_step_A, threshold * float(np.median(mag[~disturbed]))) if (~disturbed).any() else thr
            if abs(thr_new - thr) <= 1e-9 * max(1.0, thr):
                break
            thr = thr_new
    state_v = _state_codes(flags, n, with_coils) if n else np.full(0, REFERENCE, dtype=object)
    core = (state_v == REFERENCE) & ~transition
    state_ok = np.full(idx_ok.size, NO_FAULT, dtype=object)  # all valid windows in time order
    state_ok[fault_pos] = state_v
    core_ok = np.zeros(idx_ok.size, bool)
    core_ok[fault_pos] = core
    state = np.full(n_all, "", dtype=object)
    state[idx_ok] = state_ok
    reference = np.zeros(n_all, bool)
    reference[idx_ok] = core_ok
    # ---- events (also the coil changes, which are no disturbance)
    rows_e = []
    for (k, d), e in zip(events, steps):
        if not e["kinds"]:
            continue
        rows_e.append(dict(t_s=float(t[idx[k]]), kind=", ".join(e["kinds"]),
                           d_Iw_A=float(d["Iw"][0]) if with_u0 else np.nan,
                           d_Iv_A=float(d["Iv"][0]) if with_u0 else np.nan,
                           d_IH1_A=float(_step(mag, k, windows)[0]),
                           d_coil_A=float(d["coil"][0]) if with_coils else np.nan))
    events_df = pd.DataFrame(rows_e, columns=["t_s", "kind", "d_Iw_A", "d_Iv_A", "d_IH1_A", "d_coil_A"])
    # ---- medians of the undisturbed state, segments (consecutive windows of the same state) and episodes
    base = dict(Iw=float(np.median(Iw_ok[core_ok])) if with_u0 and core_ok.any() else np.nan,
                Iv=float(np.median(Iv_ok[core_ok])) if with_u0 and core_ok.any() else np.nan,
                IH1=float(np.median(mag_ok[core_ok])) if core_ok.any() else np.nan)

    def medians(sl, w_iw, w_iv, w_mag):
        return dict(Iw=float(np.median(w_iw[sl])) if with_u0 else np.nan,
                    Iv=float(np.median(w_iv[sl])) if with_u0 else np.nan, IH1=float(np.median(w_mag[sl])))
    rows_s = []
    start = 0
    for j in range(1, idx_ok.size + 1):
        if j == idx_ok.size or state_ok[j] != state_ok[start]:
            sl = slice(start, j)
            w = idx_ok[sl]
            med = medians(sl, Iw_ok, Iv_ok, mag_ok)
            r_ok = rms[w][np.isfinite(rms[w])]
            rows_s.append(dict(from_s=round(float(t[w[0]] - T_win / 2.0), 9), to_s=round(float(t[w[-1]] + T_win / 2.0), 9),
                               state=str(state_ok[start]), windows=int(j - start),
                               used=bool(state_ok[start] == REFERENCE),
                               Iw_A=med["Iw"], Iv_A=med["Iv"], IH1_A=med["IH1"],
                               IRES_A=float(np.median(r_ok)) if r_ok.size else np.nan,
                               d_Iw_A=med["Iw"] - base["Iw"], d_Iv_A=med["Iv"] - base["Iv"],
                               d_IH1_A=med["IH1"] - base["IH1"]))
            start = j
    segments = pd.DataFrame(rows_s, columns=["from_s", "to_s", "state", "windows", "used", "Iw_A", "Iv_A", "IH1_A",
                                             "IRES_A", "d_Iw_A", "d_Iv_A", "d_IH1_A"])
    episodes = []
    for name, f in flags.items():
        for a, b in _runs(f):
            inner = f.copy()
            inner[:a] = False
            inner[b + 1:] = False
            inner &= ~transition
            sl = inner if inner.any() else slice(a, b + 1)
            med = medians(sl, Iw, Iv, mag)
            key = {"active": "Iw", "network": "Iv", "fundamental": "IH1"}[name]
            # size: the step at the start of the episode (else – an interval starting in it – its median level)
            onset = [e[name] for e in steps if e[name] and a - 1 <= e["k"] <= a + 1]
            size = float(onset[0]) if onset else med[key] - base[key]
            episodes.append(dict(kind=name, from_s=round(float(t[idx[a]] - T_win / 2.0), 9),
                                 to_s=round(float(t[idx[b]] + T_win / 2.0), 9), until_end=bool(b == n - 1), step_A=size))
    for a, b in _runs(no_fault):
        episodes.append(dict(kind="no_fault", from_s=round(float(t[idx_ok[a]] - T_win / 2.0), 9),
                             to_s=round(float(t[idx_ok[b]] + T_win / 2.0), 9), until_end=bool(b == idx_ok.size - 1),
                             step_A=float("nan")))
    episodes.sort(key=lambda e: e["from_s"])
    return Disturbances(t_s=t, state=state, reference=reference, events=events_df, segments=segments,
                        threshold_A=float(thr), with_u0=with_u0, with_coils=with_coils, T_win=float(T_win),
                        episodes=episodes)


def _without_fault(mag: np.ndarray, rms: np.ndarray) -> np.ndarray:
    """Windows without fault current: RMS value (|I_H1| without RMS values) below
    [`FAULT_SHARE`][groundfault.disturbances.FAULT_SHARE] of the largest median of three consecutive windows."""
    x = rms if rms.size and np.isfinite(rms).all() else mag
    if x.size == 0:
        return np.zeros(0, bool)
    smooth = np.array([np.median(x[max(0, j - 1):j + 2]) for j in range(x.size)]) if x.size >= 3 else x
    level = float(np.max(smooth))
    if not np.isfinite(level) or level <= 0:
        return np.zeros(x.size, bool)
    return x < FAULT_SHARE * level


def window_phasors(block, roles, polarity: int = 1):
    """Per window of a block of the evaluation: fundamental phasor of the fault current, of U0, the RMS value of the
    fault current and the sum of the coil currents referred to the mean |U0| → (I1, U0, rms, coil).

    U0 is None without line-to-earth voltages and without a neutral displacement voltage, ``coil`` None without coil
    currents or without U0; everything is None without a fault-current channel. Windows without finite values give
    NaN."""
    ires = roles.main("i_res")
    if ires is None:
        return None, None, None, None
    I1 = polarity * block.X[:, ires.index, block.ix(1)]
    le = roles.line_to_earth
    U0 = None
    if le:
        U0 = block.X[:, le, block.ix(1)].sum(axis=1) / 3.0
    elif roles.has("u_ne"):
        U0 = block.X[:, roles.index("u_ne"), block.ix(1)]
    coil = None
    coils = roles.with_role("i_coil")
    if coils and U0 is not None:
        u = np.abs(U0)
        mean_u = float(np.nanmean(u[~block.nan_window])) if (~block.nan_window).any() else float("nan")
        coil = sum(np.abs(block.X[:, k.index, block.ix(1)]) for k in coils) / np.where(u > 0, u / mean_u, np.nan)
    nan = block.nan_window
    return (np.where(nan, np.nan, I1), U0, np.where(nan, np.nan, block.rms[:, ires.index]),
            None if coil is None else np.where(nan, np.nan, coil))


def scan(rec, roles=None, settings=None, *, threshold: Optional[float] = None) -> Disturbances:
    """Detect the disturbed states during the whole fault and suggest the undisturbed part as the steady-state
    interval.

    The fault is found from the RMS trend of the fault current
    ([`groundfault.station.fault_times`][groundfault.station.fault_times]); the scan starts 0.1 s after the fault
    current has settled ([`groundfault.station.settled_from`][groundfault.station.settled_from]) and ends 0.1 s
    before the clearance. A transformer recording without a fault-current channel is scanned with the fault current
    estimated from the negative-sequence current of the transformer
    ([`groundfault.transformer`][groundfault.transformer]): the fault from the zero-sequence voltage
    ([`fault_times`][groundfault.transformer.fault_times]), the reference of the estimate before (else after) the
    fault, the start once the estimate has settled (at least
    [`T_SETTLE_S`][groundfault.transformer.T_SETTLE_S] after the inception); ``meta`` then also holds ``estimated`` (True),
    ``faulted_phase`` and ``transformer_sign``.

    Parameters
    ----------
    rec : Recording
        Instantaneous-value recording.
    roles : RoleAssignment, optional
        Channel roles (detected from the channel names if omitted).
    settings : Settings, optional
        Evaluation parameters (window length, ``disturbance_threshold``).
    threshold : float, optional
        Threshold as a share of |I_H1| (default: ``settings.disturbance_threshold``).

    Returns
    -------
    Disturbances
        ``meta`` holds the fault inception and clearance (``t_fault_inception_s``, ``t_fault_clearance_s``) and the
        scanned range (``t_from_s``, ``t_to_s``);
        [`suggestion`][groundfault.disturbances.Disturbances.suggestion] gives the proposal for the steady-state
        interval and [`text`][groundfault.disturbances.Disturbances.text] a summary.

    Raises
    ------
    ValueError
        Without a fault-current channel (and without the line currents and line-to-earth voltages of a transformer)
        or if no fault is found in the recording.
    """
    from .channels import detect_roles
    from .evaluation import Settings, _analyse, load_blocks
    from .station import fault_times, settled_from
    roles = roles or detect_roles(rec.channel_names, rec.units)
    e = settings or Settings()
    ires = roles.main("i_res")
    if ires is None:
        if roles.capabilities()["transformer"] and roles.line_to_earth:
            return _scan_transformer(rec, roles, e, threshold)
        raise ValueError(tr("rms.no_fault_current_channel"))
    t_on, t_off = fault_times(rec, ires.index)
    if t_on is None and t_off is None:
        raise ValueError(tr("disturbances.no_fault"))
    t_from = (settled_from(rec, ires.index, t_on, t_off) if t_on is not None else 0.0) + 0.1
    t_to = (t_off - 0.1) if t_off is not None else rec.duration_s
    if t_to - t_from < 2 * e.T_win:
        raise ValueError(tr("disturbances.no_fault"))
    bl = load_blocks(rec, {"steady_state": (t_from, t_to)}, None)
    st = _analyse("steady_state", *bl["steady_state"], rec, roles, e)
    I1, U0, rms, coil = window_phasors(st, roles)
    d = detect(st.t_mid, I1, U0, rms, coil,
               threshold=threshold if threshold is not None else e.disturbance_threshold, T_win=e.T_win)
    d.meta.update(t_fault_inception_s=t_on, t_fault_clearance_s=t_off, t_from_s=float(t_from), t_to_s=float(t_to))
    return d


def _scan_transformer(rec, roles, e, threshold: Optional[float]) -> Disturbances:
    """[`scan`][groundfault.disturbances.scan] of a transformer recording without a fault-current channel: the fault
    from the zero-sequence voltage, the fault current estimated from the negative-sequence current of the
    transformer ([`groundfault.transformer`][groundfault.transformer]) against the pre-fault (else the post-fault)
    state; the scan starts once the estimate has settled."""
    from . import transformer as trafo
    from .evaluation import _analyse, load_blocks
    from .station import T_TRANSIENT_S
    t_on, t_off = trafo.fault_times(rec, roles)
    if t_on is None and t_off is None:
        raise ValueError(tr("disturbances.no_fault"))
    t_from = (t_on if t_on is not None else 0.0) + 0.2
    t_to = (t_off - 0.1) if t_off is not None else rec.duration_s
    base = None
    if t_on is not None and t_on - 0.2 - max(0.0, t_on - 10.2) >= 2 * e.T_win:
        base = (max(0.0, t_on - 10.2), t_on - 0.2)
    elif t_off is not None and min(rec.duration_s, t_off + 10.5) - (t_off + 0.5) >= 2 * e.T_win:
        base = (t_off + 0.5, min(rec.duration_s, t_off + 10.5))
    if base is None or t_to - t_from < 3 * e.T_win:
        raise ValueError(tr("disturbances.no_fault"))
    bl = load_blocks(rec, {"steady_state": (t_from, t_to), "base": base}, None)
    st = _analyse("steady_state", *bl["steady_state"], rec, roles, e)
    bb = _analyse("base", *bl["base"], rec, roles, e)
    first = trafo.fault_current_estimate(st, bb, roles, 1.0)
    if first is None:
        raise ValueError(tr("disturbances.no_fault"))
    mag = np.abs(first[0])
    k1 = trafo.fault_end_index(mag)                      # windows straddling the clearance are left out
    k0 = trafo.settled_index(mag[:k1])
    k0 = max(k0, int(np.searchsorted(st.t_mid, t_from - 0.2 + max(T_TRANSIENT_S, trafo.T_SETTLE_S))))
    if k1 - k0 < 3:
        raise ValueError(tr("disturbances.no_fault"))
    use = np.zeros(len(st.t_mid), bool)
    use[k0:k1] = True
    I1, U0, coil, phase, sign = trafo.detection_input(st, bb, roles, e, windows=use)
    sl = slice(k0, k1)
    noise = trafo.estimate_noise(I1[sl], U0[sl])
    d = detect(st.t_mid[sl], I1[sl], U0[sl], None, None if coil is None else coil[sl],
               threshold=threshold if threshold is not None else e.disturbance_threshold, T_win=e.T_win, orient=False,
               min_step_A=max(STEP_MIN_A, trafo.NOISE_FACTOR * noise))
    d.meta.update(t_fault_inception_s=t_on, t_fault_clearance_s=t_off,
                  t_from_s=float(st.t_mid[k0] - e.T_win / 2.0), t_to_s=float(st.t_mid[k1 - 1] + e.T_win / 2.0),
                  estimated=True, faulted_phase="L%d" % (phase + 1), transformer_sign=sign, noise_A=noise)
    return d
