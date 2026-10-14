# -*- coding: utf-8 -*-
"""Frequency-selective station evaluation: earth potential rise and touch voltage, as measured and fault-related.

At a secondary substation (MV/LV station) an earth potential rise is present even *before* the earth fault (the
"background": currents from the low-voltage network via the PEN conductor and the earth electrode, mainly at 50 and
150 Hz). During the fault, the component caused by the fault current adds to it as a phasor:
U(fault) = U(background) + Z·I_F. An earthing measurement with current injection measures only Z, frequency by
frequency – the comparable quantity is therefore the **fault-related component** ΔU = U(fault) − U(background).

For every probe (earth potential rise ``u_e``, touch voltage ``u_t``) and every order m with an appreciable fault
current, [`frequency_selective`][groundfault.station.frequency_selective] determines the transfer ratio Z_m = U_m/I_F,m
in V/A (columns ``Z_<method>_Ohm``) in several independent ways. For an earth-potential probe it is r·Z_E – the
earthing impedance times the reduction factor, because only the earth current I_E = r·I_F flows into the earthing
system; the reduction factor r follows from the comparison with an earthing measurement
([`groundfault.earthing.reduction_factor`][groundfault.earthing.reduction_factor]):

``direct``
    U_m/I_F,m in the max window of the evaluation – as measured, *including* the background.
``inception`` / ``clearance``  (superposition, time reference – possible without a voltage measurement)
    Phasors shortly before and shortly after fault inception or fault clearance. The phase reference is the network
    phase: every window is rotated back to the instant of fault inception (or clearance) with e^{−j·m·Δθ},
    Δθ = 2π·∫f dt. The network frequency is estimated separately on both sides – from the line-to-line voltage,
    otherwise during the fault from the fault current and before/after it from the most distinct
    network-synchronous background (at probes often 150 Hz) – and assumed to be linear in between (frequency drift
    → quadratic phase); every window is evaluated at its own frequency. All windows lie at most about 2.5 s from
    the reference instant.
``voltage``  (superposition, voltage reference – only with a voltage measurement)
    The phase reference is the fundamental component of U_L1-L2 of each window; the background comes from the
    pre-fault and post-fault intervals of the evaluation, the fault component from a least-squares fit over the
    undisturbed windows of the steady-state interval (see [`groundfault.disturbances`][groundfault.disturbances]).

The time-reference methods use the windows next to fault inception and clearance, independently of the steady-state
interval. An active residual current increase or a network switching during these windows does not bias them: the
ratio ΔU/I_F of a linear earthing system stays the same when the fault current changes.

The result (``fault``) is the mean of the available superposition methods. How reliable it is follows from two
independent checks and an estimate of the error of the frequency reference:

* The methods check each other (``method_spread_pct``, as phasors).
* Null test: in the fault-free sections of the recording the same calculation is carried out, checking how
  accurately the background can be predicted across the same gap (``background_forecast_error_pct``). Multiplied by
  the ratio background/fault-related component, this gives the first part of the estimated uncertainty.
* Frequency reference: without a voltage measurement, the network frequency during the fault follows the fault
  current, whose frequency can deviate from the network frequency by a few mHz. An assumed deviation of 3 mHz
  (``DF_FAULT_CURRENT_HZ``) gives the second part (``frequency_uncertainty_pct``); both together (added in
  quadrature) are ``uncertainty_pct`` – a typical value (median), not a bound.

If one of them exceeds 20 %, the row is marked ``uncertain`` – typically at frequencies at which the background is
larger than the fault-related component (often 150 Hz). The large, steady background at 50 and 150 Hz can usually
be predicted across the gap more accurately than the small and more strongly fluctuating background at higher
orders, so the forecast error is typically larger at the higher orders.

The same superposition gives, for PEN and shield currents, the fault-related current ΔI = k·I_F (the load unbalance,
present before the fault already, drops out). From the PEN currents follow the current into the LV network I_LV, the
earthing impedance of the LV network Z_E,LV = ΔU_E/I_LV and the parallel-branch checks: the LV network is one branch of
the total earthing, so |I_LV| ≤ |I_F| and, with shield currents, |I_LV| ≤ |I_E| with I_E = I_F − I_S. Rows with
``channel`` = [`MAX_PROBE`][groundfault.station.MAX_PROBE] (probe maximum) use, per order, the probe with the highest
fault-related voltage.

Examples
--------
[`groundfault.evaluate`][groundfault.evaluation.evaluate] calls
[`frequency_selective`][groundfault.station.frequency_selective] for station recordings::

    res = groundfault.evaluate(groundfault.open_recording("Station_A_10_000kHz.cfg"), intervals)
    res.table("station_frequency")          # per probe and order: direct, inception, clearance, voltage, fault
    res.table("station_lv_network_eff")     # current into the LV network and Z_E,LV (RMS values)
"""
from __future__ import annotations

import math
import warnings
from collections.abc import Mapping
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import dsp
from . import i18n
from .i18n import tr

__all__ = ["fault_times", "settled_from", "frequency_selective", "MAX_PROBE", "METHODS", "T_TRANSIENT_S",
           "T_WINDOW_SEQUENCE_S", "UNCERTAIN_PCT", "T_TRANSIENT_MAX_S", "T_EDGE_S", "DF_SIDES_MAX_HZ",
           "DF_FAULT_CURRENT_HZ", "F_SIGMA_MAX_HZ", "FREQUENCY_ORDERS", "T_NULL_TEST_MAX_S", "NULL_TEST_POSITIONS"]

i18n.register({
    # ---- labels of the methods (METHODS)
    "station.method_direct": {
        "en": "direct (as measured, including background)",
        "de": "direkt (wie gemessen, mit Grundlast)"},
    "station.method_inception": {
        "en": "superposition at fault inception (time reference)",
        "de": "Überlagerung am Fehlereintritt (Zeitbezug)"},
    "station.method_clearance": {
        "en": "superposition at fault clearance (time reference)",
        "de": "Überlagerung am Fehlerende (Zeitbezug)"},
    "station.method_voltage": {
        "en": "superposition with voltage reference",
        "de": "Überlagerung mit Spannungsbezug"},
    "station.method_fault": {
        "en": "fault-related component (mean of the superposition methods)",
        "de": "fehlerbedingter Anteil (Mittel der Überlagerungsverfahren)"},
    # ---- sources of the network frequency (res.values["station_frequency"])
    "station.frequency_source_order": {
        "en": "{channel} at {f:g} Hz",
        "de": "{channel} bei {f:g} Hz"},
    "station.fault_source_background": {
        "en": "as before/after the fault (fault current not evaluable)",
        "de": "wie vor/nach dem Fehler (Fehlerstrom nicht auswertbar)"},
    "station.fault_source_steady_state": {
        "en": "f1 of the steady-state interval (fault current not evaluable)",
        "de": "f1 des stationären Bereichs (Fehlerstrom nicht auswertbar)"},
    "station.background_source_missing": {
        "en": "not estimable ({reason}) – frequency during the fault continued",
        "de": "nicht schätzbar ({reason}) – Frequenz im Fehler fortgesetzt"},
    "station.reason_too_short": {"en": "too short", "de": "zu kurz"},
    "station.reason_no_background": {"en": "no background", "de": "keine Grundlast"},
    "station.reason_implausible": {
        "en": "implausible ({df_mhz:+.0f} mHz)",
        "de": "unplausibel ({df_mhz:+.0f} mHz)"},
    # ---- LV network: reference of the total earthing (column total_earthing_reference)
    "station.reference_shield": {
        "en": "I_E = I_F − I_S (shield current {channels})",
        "de": "I_E = I_F − I_S (Schirmstrom {channels})"},
    "station.reference_no_shield": {
        "en": "I_F (without shield current – weaker condition)",
        "de": "I_F (ohne Schirmstrom – schwächere Bedingung)"},
    # ---- LV network: hints
    "station.lv_several_pen": {
        "en": "LV network: several PEN channels with position {position} ({channels}) – using {channel}.",
        "de": "Ortsnetz: mehrere PEN-Kanäle mit Lage {position} ({channels}) – verwendet {channel}."},
    "station.lv_kcl_violated": {
        "en": "LV network: the fault-related PEN currents before ({feeders}) and after the transformer star point "
              "({busbar}) differ by {deviation:.0f} % at 50 Hz – more than their uncertainties explain "
              "({expected:.0f} %); Kirchhoff's current law expects equal magnitudes: check the clamps, the ratio and "
              "a load change during the fault.",
        "de": "Ortsnetz: Die fehlerbedingten PEN-Ströme vor ({feeders}) und nach dem Trafoknoten ({busbar}) weichen "
              "bei 50 Hz um {deviation:.0f} % voneinander ab – mehr, als ihre Unsicherheiten erklären "
              "({expected:.0f} %); die Knotenregel erwartet gleiche Beträge: Zangen, Übersetzung und eine Laständerung "
              "während des Fehlers prüfen."},
    "station.lv_kcl_explained": {
        "en": "LV network: PEN currents before ({feeders}) and after the transformer star point ({busbar}) differ by "
              "{deviation:.0f} % at 50 Hz – explained by their uncertainties (load unbalance, spread of the methods: "
              "{u_feeders:.0f} % and {u_busbar:.0f} %); I_LV relies on {channel} with a weight of {weight:.0f} %.",
        "de": "Ortsnetz: PEN-Ströme vor ({feeders}) und nach dem Trafoknoten ({busbar}) weichen bei 50 Hz um "
              "{deviation:.0f} % ab – erklärt durch ihre Unsicherheiten (Unsymmetrie der Last, Streuung der Verfahren: "
              "{u_feeders:.0f} % bzw. {u_busbar:.0f} %); I_ON stützt sich zu {weight:.0f} % auf {channel}."},
    "station.lv_exceeds_earth_current": {
        "en": "LV network: current into the LV network larger than the earth current ({reference}) at {frequencies} Hz "
              "– beyond the measurement uncertainty; impossible for a parallel connection: check the PEN and "
              "shield-current clamps (ratio, position).",
        "de": "Ortsnetz: Strom ins Ortsnetz größer als der Erdungsstrom ({reference}) bei {frequencies} Hz – über die "
              "Messunsicherheit hinaus; für eine Parallelschaltung unmöglich: PEN- und Schirmstromzangen "
              "(Übersetzung, Lage) prüfen."},
    # ---- hints of the frequency-selective evaluation
    "station.uncertain_values": {
        "en": "Station: uncertain values – {parts}. The superposition methods contradict each other there, or the "
              "background is large compared with the fault-related component and fluctuates; compare these "
              "frequencies with earthing measurements only with caution (column 'uncertain' in station_frequency).",
        "de": "Station: unsichere Werte – {parts}. Die Überlagerungsverfahren widersprechen sich dort oder die "
              "Grundlast ist groß gegenüber dem fehlerbedingten Anteil und schwankt; diese Frequenzen nur mit Vorsicht "
              "mit Erdungsmessungen vergleichen (Spalte „unsicher“ in station_frequency)."},
    "station.uncertain_frequency": {"en": "{f:g} Hz ({reasons})", "de": "{f:g} Hz ({reasons})"},
    "station.uncertain_spread": {
        "en": "methods differ by {spread:.0f} %",
        "de": "Verfahren weichen {spread:.0f} % ab"},
    "station.uncertain_uncertainty": {
        "en": "uncertainty ≈ {uncertainty:.0f} %",
        "de": "Unsicherheit ≈ {uncertainty:.0f} %"},
    "station.uncertain_uncertainty_frequency": {
        "en": "uncertainty ≈ {uncertainty:.0f} %, mainly frequency reference without voltage measurement",
        "de": "Unsicherheit ≈ {uncertainty:.0f} %, v. a. Frequenzbezug ohne Spannungsmessung"},
    "station.uncertain_background": {
        "en": "background {ratio:.1f} times as large",
        "de": "Grundlast {ratio:.1f}-mal so groß"},
    "station.uncertain_more": {
        "en": "{count} more with little fault current",
        "de": "{count} weitere mit wenig Fehlerstrom"},
    "station.frequency_not_estimable_inception": {
        "en": "Station (fault inception): network frequency before the fault not estimable ({cause}) – frequency "
              "during the fault assumed; irrelevant if the background is small.",
        "de": "Station (Fehlereintritt): Netzfrequenz vor dem Fehler nicht schätzbar ({cause}) – Frequenz im Fehler "
              "angenommen; bei kleiner Grundlast unerheblich."},
    "station.frequency_not_estimable_clearance": {
        "en": "Station (fault clearance): network frequency after the fault not estimable ({cause}) – frequency "
              "during the fault assumed; irrelevant if the background is small.",
        "de": "Station (Fehlerende): Netzfrequenz nach dem Fehler nicht schätzbar ({cause}) – Frequenz im Fehler "
              "angenommen; bei kleiner Grundlast unerheblich."},
    "station.cause_too_short_inception": {
        "en": "section before the fault too short",
        "de": "Abschnitt vor dem Fehler zu kurz"},
    "station.cause_too_short_clearance": {
        "en": "section after the fault too short",
        "de": "Abschnitt nach dem Fehler zu kurz"},
    "station.cause_no_background": {
        "en": "no distinct network-synchronous background",
        "de": "keine deutliche netzsynchrone Grundlast"},
    "station.cause_estimate": {"en": "estimate {reason}", "de": "Schätzung {reason}"},
    "station.background_large": {
        "en": "Station: background before the fault up to {share:.0f} % of the earth potential rise/touch voltage "
              "during the fault (50 Hz) – use the fault-related component for comparisons with earthing measurements "
              "(table station_frequency).",
        "de": "Station: Grundlast vor dem Fehler bis {share:.0f} % der Erdungs-/Berührungsspannung im Fehler (50 Hz) – "
              "für den Vergleich mit Erdungsmessungen den fehlerbedingten Anteil verwenden (Tabelle "
              "station_frequency)."},
    "station.touch_voltage_approximation": {
        "en": "Touch voltage from the shortest probe {probe} ({distance:g} m) – approximation, not a 1-m measurement.",
        "de": "Berührungsspannung aus der kürzesten Sonde {probe} ({distance:g} m) – Näherung, keine 1-m-Messung."},
    "station.fault_component_unavailable": {
        "en": "Station: fault-related component not determinable ({reason}, no voltage measurement with intervals "
              "before/after the fault) – direct values only.",
        "de": "Station: fehlerbedingter Anteil nicht bestimmbar ({reason}, keine Spannungsmessung mit Bereichen "
              "vor/nach dem Fehler) – nur direkte Werte."},
    "station.reason_fault_too_short": {
        "en": "fault too short for window sequences before/after inception and clearance (≥ 0.4 s needed per side)",
        "de": "Fehler zu kurz für Fensterfolgen vor/nach Eintritt und Ende (je Seite ≥ 0,4 s nötig)"},
    "station.reason_no_fault_times": {
        "en": "fault inception/clearance not in the recording",
        "de": "Fehlereintritt/-ende nicht in der Aufzeichnung"},
    "station.no_limits": {
        "en": "No extrapolation of the station voltages to limits of the residual current: Settings.ires_limits is "
              "empty (the limits are defined by the user).",
        "de": "Keine Hochrechnung der Stationsspannungen auf Grenzwerte des Reststroms: Settings.ires_limits ist leer "
              "(die Grenzwerte legt der Anwender fest)."},
    "station.single_method": {
        "en": "Station: only one superposition method available ({method}) – no mutual check, spread not "
              "determinable.",
        "de": "Station: nur ein Überlagerungsverfahren verfügbar ({method}) – keine gegenseitige Kontrolle, Streuung "
              "nicht bestimmbar."},
})


class _Labels(Mapping):
    """Read-only mapping code → display label, rendered with [`tr`][groundfault.i18n.tr] in the active language
    on every access (message key ``prefix + code``)."""

    def __init__(self, prefix: str, codes: Sequence[str]):
        self._prefix = prefix
        self._codes = tuple(codes)

    def __getitem__(self, code: str) -> str:
        if code not in self._codes:
            raise KeyError(code)
        return tr(self._prefix + code)

    def __iter__(self) -> Iterator[str]:
        return iter(self._codes)

    def __len__(self) -> int:
        return len(self._codes)

    def __repr__(self) -> str:
        return repr(dict(self))


METHODS = _Labels("station.method_", ("direct", "inception", "clearance", "voltage", "fault"))
"""Display labels of the methods in tables and figures: method code (``direct``, ``inception``, ``clearance``,
``voltage``, ``fault``) → label in the active output language (read-only mapping)."""

T_TRANSIENT_S = 0.5
"""Distance from fault inception/clearance in s (settling, decaying DC component, decay after clearance)."""
T_TRANSIENT_MAX_S = 1.5
"""Latest start of the fault windows after inception in s (keeps the phase reference short)."""
T_WINDOW_SEQUENCE_S = 1.2
"""Length of the window sequence per side in s."""
T_EDGE_S = 0.06
"""Safety margin of the background windows from the switching instant in s."""
DF_SIDES_MAX_HZ = 0.05
"""Largest plausible frequency change between the background side and the fault side in Hz (≈ 20 mHz/s)."""
DF_FAULT_CURRENT_HZ = 0.003
"""Assumed deviation of the fault-current frequency from the network frequency in Hz (a few mHz are possible when
the frequency reference has to be taken from the fault current)."""
F_SIGMA_MAX_HZ = 0.002
"""A frequency estimate counts as reliable up to this standard deviation in Hz."""
FREQUENCY_ORDERS = (1, 2, 3, 4, 5, 6, 7)
"""Orders whose phase trend is used to estimate the network frequency."""
T_NULL_TEST_MAX_S = 20.0
"""Fault-free recording per side (closest to the fault) used for the null test, in s."""
NULL_TEST_POSITIONS = 15
"""At most this many positions per fault-free section in the null test."""
UNCERTAIN_PCT = 20.0
"""Spread of the methods or estimated uncertainty (%) above which a value is marked ``uncertain``."""
_UNCERTAINTY_FLOOR_PCT = 1e-6
"""Smallest uncertainty (%) of a PEN measuring point in the weighted mean (1/u²) – only a guard against a division by
zero when neither the methods nor the measurement-uncertainty margin m_I give an uncertainty."""
MAX_PROBE = "max(UE)"
"""Channel name of the rows with the highest earth potential rise of all probes (probe maximum) – a code, not a
message."""
#: Former name of :data:`UNCERTAIN_PCT` (deprecated alias).
SPREAD_WARNING_PCT = UNCERTAIN_PCT

#: Words in the role source (column ``source`` of the role table, German or English) that mark the touch voltage
#: taken from the shortest probe as an approximation (see :mod:`groundfault.channels`).
_APPROXIMATION_MARKERS = ("Näherung", "approximation")


# ---------------------------------------------------------------------------------------------- instants
def fault_times(rec, channel_index: int, window_s: float = 0.02,
                t_inside: Optional[float] = None) -> Tuple[Optional[float], Optional[float]]:
    """Fault inception and fault clearance from the RMS trend of the fault current.

    A section counts as active where the moving median of the RMS trend exceeds 10 % of its maximum.

    Parameters
    ----------
    rec : Recording
        The recording.
    channel_index : int
        Index of the fault-current channel.
    window_s : float, optional
        Length of the RMS windows in s.
    t_inside : float, optional
        An instant during the fault (e.g. the middle of the steady-state interval). Then the active section
        containing it is used (gaps shorter than 1 s are bridged), so a short transient fault or a second fault
        elsewhere in the recording does not shift inception and clearance. Without it, the first and the last
        active instant of the recording are used.

    Returns
    -------
    t_on, t_off : float or None
        Fault inception and fault clearance in s. ``t_on`` is None if the fault current is active from the start of
        the recording (inception not recorded), ``t_off`` is None if the fault lasts until the end of the recording;
        both are None if no active section is found.
    """
    from .diagnostics import _active_section, _active_range
    t, R = rec.rms_trend(channels=[channel_index], window_s=window_s)
    from_, until = (_active_range(t, R[:, 0]) if t_inside is None else _active_section(t, R[:, 0], t_inside))
    if not np.isfinite(from_):
        return None, None
    t_off = float(until) if until < rec.duration_s - 3 * window_s else None
    t_on = float(from_) if from_ > 5 * window_s else None              # active from the file start → no inception
    return t_on, t_off


def settled_from(rec, channel_index: int, t_on: float, t_to: Optional[float] = None,
                 tolerance: float = 0.03, duration_s: float = 0.5) -> float:
    """Instant from which the fault current has settled after fault inception.

    After inception the fault current settles (decaying DC component, CT saturation). It counts as settled once its
    RMS value (100-ms windows, the median of each window removed) changes by less than ``tolerance`` over
    ``duration_s``. The search starts 0.2 s after inception.

    Parameters
    ----------
    rec : Recording
        The recording.
    channel_index : int
        Index of the fault-current channel.
    t_on : float
        Fault inception in s.
    t_to : float, optional
        End of the search range in s (default: end of the recording); at most 8 s after ``t_on`` are searched.
    tolerance : float, optional
        Permissible relative change of the RMS value.
    duration_s : float, optional
        Duration in s over which the RMS value has to stay within ``tolerance``.

    Returns
    -------
    float
        Settling instant in s, at least ``t_on`` + [`T_TRANSIENT_S`][groundfault.station.T_TRANSIENT_S]; ``t_on`` +
        [`T_TRANSIENT_S`][groundfault.station.T_TRANSIENT_S] if no settled section is found or the search range is
        shorter than three windows.
    """
    t_to = min(t_to if t_to is not None else rec.duration_s, t_on + 8.0)
    i0 = int(round((t_on + 0.2) * rec.fs)); i1 = int(round(t_to * rec.fs))
    nw = int(round(0.1 * rec.fs))
    if i1 - i0 < 3 * nw:
        return t_on + T_TRANSIENT_S
    x = rec.read(i0, i1, [channel_index])[:, 0]
    k = (len(x) // nw)
    x = x[:k * nw].reshape(k, nw)
    r = np.sqrt(np.mean((x - np.median(x, axis=1, keepdims=True)) ** 2, axis=1))
    n = max(1, int(round(duration_s / 0.1)))
    for j in range(0, k - n):
        ref = r[j]
        if ref > 0 and np.all(np.abs(r[j:j + n + 1] - ref) <= tolerance * ref):
            return max(t_on + T_TRANSIENT_S, t_on + 0.2 + j * 0.1)
    return t_on + T_TRANSIENT_S


# ---------------------------------------------------------------------------------------------- phasors
def _windows(rec, channels: Sequence[int], t_from: float, t_to: float, f_hz, orders: Sequence[int],
             T_win: float, shift=None):
    """Phasors of consecutive windows in [t_from, t_to) at m·f → (X (n_w, k, n_ord), t0 (n_w,)).

    ``f_hz`` is a fixed frequency or a function f(t); with a function, every window is evaluated at the frequency of
    its centre. The phase reference is the first sample of each window (time ``t0``)."""
    fs = rec.fs
    i0 = max(0, int(round(t_from * fs)))
    i1 = min(rec.n, int(round(t_to * fs)))
    nwin, nhop, starts = dsp.window_grid(max(0, i1 - i0), fs, T_win, T_win)
    if len(starts) == 0:
        return np.zeros((0, len(channels), len(orders)), complex), np.zeros(0)
    blk = rec.read(i0, i1, list(channels), shift)
    if callable(f_hz):
        t_mid = (i0 + starts + nwin / 2.0) / fs
        freqs = np.outer([f_hz(t) for t in t_mid], np.asarray(orders, float))     # (n_w, n_ord)
    else:
        freqs = np.asarray(orders, float) * f_hz
    X = np.empty((len(starts), len(channels), len(orders)), complex)
    for j in range(len(channels)):
        Xj, _ = dsp.dft_phasors(dsp.window_view(blk[:, j], nwin, nhop), fs, freqs, "hann", "median")
        X[:, j, :] = Xj
    t0 = (i0 + starts) / fs
    return X, t0


def _to_instant(X: np.ndarray, t0: np.ndarray, f_hz, orders: Sequence[int], t_ref: float):
    """Rotate every window back to the network phase at ``t_ref``: factor e^{−j·m·Δθ} with
    Δθ = 2π·∫_{t_ref}^{t0} f dt. ``f_hz`` is a fixed frequency or a linear function f(t) (the trapezoidal rule is
    then exact)."""
    if callable(f_hz):
        integral = (t0 - t_ref) * 0.5 * (np.array([f_hz(t) for t in t0]) + f_hz(t_ref))
    else:
        integral = (t0 - t_ref) * f_hz
    rot = np.exp(-1j * 2 * np.pi * np.outer(integral, np.asarray(orders, float)))
    return X * rot[:, None, :]


def _ll_reference(roles) -> List[Tuple[int, Optional[int], str]]:
    """Line-to-line voltages as frequency reference (unaffected by the earth fault): measured (``u_l12`` …) or as the
    difference of two line-to-earth voltages → [(channel a, channel b or None, name)]."""
    out = []
    for r, nm in (("u_l12", "U_L1-L2"), ("u_l23", "U_L2-L3"), ("u_l31", "U_L3-L1")):
        i = roles.index(r)
        if i is not None:
            out.append((i, None, nm))
    le = [(roles.index(r), n) for r, n in (("u_l1e", 1), ("u_l2e", 2), ("u_l3e", 3))]
    le = [(i, n) for i, n in le if i is not None]
    if len(le) >= 2:
        out.append((le[0][0], le[1][0], "U_L%d-L%d" % (le[0][1], le[1][1])))
    return out


def _system_frequency(rec, roles, t_from: float, t_to: float, f_nominal: float, shift=None,
                      candidates: Optional[Sequence[Tuple[int, int]]] = None) -> Optional[dict]:
    """Mean network frequency of a section from the phase trend (regression over 100-ms windows,
    [`groundfault.dsp.f1_regression`][groundfault.dsp.f1_regression]).

    The reference is the line-to-line voltage if it is measured (independent of the earth fault and of the
    background). Otherwise the ``candidates`` [(channel, order), …] count – default: all channels, orders 1…7; before
    the fault, probes, PEN and shield currents often carry the network phase most distinctly at 150 Hz. Per order the
    most reliable channel counts; across the orders the weighted median (weight 1/σ²) – σ only describes how smooth
    the phase trend is, not whether it follows the network phase; a single order with a phase trend of its own
    (interharmonic, fluctuating harmonic) therefore cannot determine the result on its own.

    Returns ``dict(f, sigma, source, orders, span_hz)`` – ``source`` is the reference (channel, with the frequency if it
    is not the fundamental), ``orders`` the number of usable orders, ``span_hz`` the distance between the estimates of
    the orders – or None if no estimate is reliable enough (σ > [`F_SIGMA_MAX_HZ`][groundfault.station.F_SIGMA_MAX_HZ])
    or the section is shorter than 0.5 s."""
    i0 = max(0, int(round(t_from * rec.fs)))
    i1 = min(rec.n, int(round(t_to * rec.fs)))
    if i1 - i0 < int(0.5 * rec.fs):
        return None
    ll = _ll_reference(roles)
    if candidates is None:
        candidates = [(j, m) for j in range(len(roles.channels)) for m in FREQUENCY_ORDERS]
    chan = sorted({j for a, b, _ in ll for j in (a, b) if j is not None} | {j for j, _ in candidates})
    X = rec.read(i0, i1, chan, shift)
    sp = {j: n for n, j in enumerate(chan)}

    def _regression(x, ords):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            f, s_ = dsp.f1_regression(x, rec.fs, f_nominal, ords, T=0.1)
        ok = np.isfinite(f) & np.isfinite(s_) & (s_ <= F_SIGMA_MAX_HZ) & (np.abs(f - f_nominal) <= 0.5)
        return f, s_, ok
    for a, b, nm in ll:
        f, s_, ok = _regression(X[:, sp[a]] - (X[:, sp[b]] if b is not None else 0.0), [1])
        if ok[0]:
            return dict(f=float(f[0]), sigma=float(s_[0]), source=nm, orders=1, span_hz=0.0)
    per_channel: Dict[int, List[int]] = {}
    for j, m in candidates:
        per_channel.setdefault(j, []).append(m)
    per_order: Dict[int, Tuple[float, float, str]] = {}
    for j, ords in per_channel.items():
        f, s_, ok = _regression(X[:, sp[j]], ords)
        for k, m in enumerate(ords):
            if ok[k] and (m not in per_order or s_[k] < per_order[m][1]):
                per_order[m] = (float(f[k]), float(s_[k]), roles.channels[j].short)
    if not per_order:
        return None
    series = sorted(per_order.items(), key=lambda kv: kv[1][0])            # sorted by frequency
    w = np.array([1.0 / v[1] ** 2 for _, v in series])
    i = int(np.searchsorted(np.cumsum(w) / w.sum(), 0.5))                 # weighted median
    m, (f, s_, name) = series[min(i, len(series) - 1)]
    fr = [v[0] for _, v in series]
    return dict(f=f, sigma=s_,
                source=name if m == 1 else tr("station.frequency_source_order", channel=name, f=round(m * f_nominal)),
                orders=len(series), span_hz=float(max(fr) - min(fr)))


def _side(rec, roles, chan_u: List[int], ires: int, t_background: Tuple[float, float], t_fault: Tuple[float, float],
          t_ref: float, orders: Sequence[int], f_fallback: float, f_nominal: float,
          T_win: float, polarity: int, shift=None) -> Optional[dict]:
    """Background and fault phasors of one side (inception or clearance), both referred to the network phase at
    ``t_ref``.

    The network frequency during the fault comes from U_L-L (otherwise from the fault current), before or after the
    fault from U_L-L (otherwise from the most distinct network-synchronous background, ``_system_frequency``); in
    between it is assumed to be linear. If it cannot be estimated on the background side (background only noise),
    the frequency during the fault is used – but then the background is also so small that a phase error hardly
    matters. Extrapolating a drift from the fault current instead would be less accurate, because the fault-current
    frequency can deviate from the network frequency. ``phase_error_rad``: possible phase error per order if the
    frequency during the fault comes from the fault current. ``reason_missing``: why the background frequency was
    not estimable (``"too_short"``, ``"no_background"``, ``"implausible"`` with ``df_background_mhz``) or None.

    Returns None if one of the two intervals is shorter than two windows."""
    if t_background[1] - t_background[0] < 2 * T_win or t_fault[1] - t_fault[0] < 2 * T_win:
        return None
    est_bg = _system_frequency(rec, roles, *t_background, f_nominal, shift)
    est_fault = _system_frequency(rec, roles, *t_fault, f_nominal, shift, candidates=[(ires, 1)])
    if est_fault is not None:
        f_fault, source_fault = est_fault["f"], est_fault["source"]
    elif est_bg is not None:                                # fault current unusable: continue the background side
        f_fault, source_fault = est_bg["f"], tr("station.fault_source_background")
    else:
        f_fault, source_fault = f_fallback, tr("station.fault_source_steady_state")
    reason_missing, df_background_mhz = None, None
    if est_bg is not None and abs(est_bg["f"] - f_fault) <= DF_SIDES_MAX_HZ:
        f_bg, source_bg = est_bg["f"], est_bg["source"]
    else:
        f_bg, source_bg = f_fault, None                           # not estimable → continue the frequency
        if t_background[1] - t_background[0] < 0.5:
            reason_missing = "too_short"
        elif est_bg is None:
            reason_missing = "no_background"
        else:
            reason_missing, df_background_mhz = "implausible", 1e3 * (est_bg["f"] - f_fault)
    # network frequency linear between the centres of both window sequences (drift) – quadratic phase
    t_bg_mid, t_fault_mid = 0.5 * (t_background[0] + t_background[1]), 0.5 * (t_fault[0] + t_fault[1])
    slope = (f_fault - f_bg) / (t_fault_mid - t_bg_mid) if abs(t_fault_mid - t_bg_mid) > 1e-9 else 0.0

    def f_t(t):
        return f_bg + slope * (t - t_bg_mid)
    chan = list(chan_u) + [ires]
    X_bg, t0_bg = _windows(rec, chan, *t_background, f_t, orders, T_win, shift)
    X_fault, t0_fault = _windows(rec, chan, *t_fault, f_t, orders, T_win, shift)
    if len(t0_bg) < 2 or len(t0_fault) < 2:
        return None
    X_bg = _to_instant(X_bg, t0_bg, f_t, orders, t_ref)
    X_fault = _to_instant(X_fault, t0_fault, f_t, orders, t_ref)
    X_fault[:, -1, :] *= polarity
    u_bg = np.nanmean(X_bg[:, :-1, :], axis=0)                     # (k, n_ord)
    u_fault = np.nanmean(X_fault[:, :-1, :], axis=0)
    i_fault = np.nanmean(X_fault[:, -1, :], axis=0)                # (n_ord,)
    # Without a voltage measurement f_fault follows the fault current, whose phase can drift against the network
    # (by a few mHz): phase error between background and fault windows ≈ π·m·δf·Δt (linear model, δf at
    # t_fault_mid)
    from_current = not (est_fault is not None and est_fault["source"].startswith("U_L"))
    phase_error = (np.pi * np.asarray(orders, float) * DF_FAULT_CURRENT_HZ * abs(t_fault_mid - t_bg_mid)
                   if from_current else np.zeros(len(orders)))
    return dict(U_background=u_bg, U_fault=u_fault, I_fault=i_fault, f_background=f_bg, f_fault=f_fault,
                df_dt=slope, t_ref=t_ref, source_background=source_bg, source_fault=source_fault,
                reason_missing=reason_missing, df_background_mhz=df_background_mhz,
                span_background_hz=(est_bg or {}).get("span_hz"), phase_error_rad=phase_error,
                n_background=len(t0_bg), n_fault=len(t0_fault), t_background=t_background, t_fault=t_fault)


def _reason_missing_text(side: dict) -> str:
    """Why the background frequency of a side was not estimable, as text in the active language."""
    if side.get("reason_missing") is None:
        return "–"
    return tr("station.reason_" + side["reason_missing"], df_mhz=side.get("df_background_mhz"))


def _forecast_error(rec, roles, chan_u: List[int], orders: Sequence[int], f_nominal: float, T_win: float,
                    regions: Sequence[Tuple[float, float]], background_rel: Tuple[float, float],
                    fault_rel: Tuple[float, float], shift=None) -> Optional[np.ndarray]:
    """Null test: how accurately can the background be predicted across the gap between the background and the fault
    windows?

    In fault-free sections (``regions``) the superposition is calculated at several positions t* exactly as in the
    evaluation – network frequency estimated on both sides and linear in between, phasors rotated to t* and averaged
    – and the background of the "background windows" (``background_rel`` relative to t*) is compared with the phasors
    actually measured in the "fault windows" (``fault_rel``); there is no fault there, after all. Result: median of
    the relative error |ΔU|/|U| per probe and order (k, n_ord), or None if no section is long enough. It contains
    fluctuations of the background itself as well as errors of the frequency estimation."""
    lo, hi = min(background_rel[0], fault_rel[0]), max(background_rel[1], fault_rel[1])
    errors = []
    for r0, r1 in regions:
        pos = np.arange(r0 - lo, r1 - hi + 1e-9, 0.4)
        if len(pos) > NULL_TEST_POSITIONS:
            pos = pos[np.round(np.linspace(0, len(pos) - 1, NULL_TEST_POSITIONS)).astype(int)]
        for ts in pos:
            g0, g1, f0, f1 = ts + background_rel[0], ts + background_rel[1], ts + fault_rel[0], ts + fault_rel[1]
            est_bg = _system_frequency(rec, roles, g0, g1, f_nominal, shift)
            if est_bg is None:
                continue
            est_fault = _system_frequency(rec, roles, f0, f1, f_nominal, shift)    # like f_fault of the evaluation
            f_bg = est_bg["f"]
            f_fault = (est_fault["f"] if est_fault is not None and abs(est_fault["f"] - f_bg) <= DF_SIDES_MAX_HZ
                       else f_bg)
            t_bg_mid, t_fault_mid = 0.5 * (g0 + g1), 0.5 * (f0 + f1)
            k = (f_fault - f_bg) / (t_fault_mid - t_bg_mid)

            def f_t(t, f_bg=f_bg, k=k, t_bg_mid=t_bg_mid):
                return f_bg + k * (t - t_bg_mid)
            X_bg, t0_bg = _windows(rec, chan_u, g0, g1, f_t, orders, T_win, shift)
            X_fault, t0_fault = _windows(rec, chan_u, f0, f1, f_t, orders, T_win, shift)
            if len(t0_bg) < 2 or len(t0_fault) < 2:
                continue
            u_bg = np.nanmean(_to_instant(X_bg, t0_bg, f_t, orders, ts), axis=0)
            u_fault = np.nanmean(_to_instant(X_fault, t0_fault, f_t, orders, ts), axis=0)
            errors.append(np.abs(u_fault - u_bg) / np.maximum(np.nanmean(np.abs(X_fault), axis=0), 1e-12))
    if not errors:
        return None
    return np.nanmedian(np.stack(errors), axis=0)


def _voltage_reference(res, chan_u: List[int], ires: int, orders: Sequence[int]) -> Optional[dict]:
    """Superposition with the phase reference U_L1-L2 of each window (blocks of the evaluation).

    Background from the pre-fault and the post-fault interval (mean of the available ones), fault component from a
    least-squares fit over the reference windows of the steady-state interval (without disturbed states). None
    without line-to-earth voltages, without pre-/post-fault interval or if an order is missing in the blocks."""
    le = res.roles.line_to_earth
    if not le or res.pre_fault is None and res.post_fault is None:
        return None
    st = res.steady_state

    def _rotated(b, chan):
        u12 = b.X[:, le[0], b.ix(1)] - b.X[:, le[1], b.ix(1)]
        phi = np.angle(u12)
        rot = np.exp(-1j * np.outer(phi, np.asarray([float(m) for m in orders])))
        ix = [b.ix(m) for m in orders]
        X = b.X[:, chan, :][:, :, ix] * rot[:, None, :]
        # steady state: the reference windows (without disturbed states), otherwise all windows with values
        ok = res.reference_windows if b is st and hasattr(res, "reference_windows") else ~b.nan_window
        return X[ok]

    background = {}                                                   # interval name → mean background phasors
    for name in ("pre_fault", "post_fault"):
        b = getattr(res, name)
        if b is not None and all(m in b.orders for m in orders):
            G = _rotated(b, chan_u)
            if len(G):
                background[name] = np.mean(G, axis=0)
    if not background or not all(m in st.orders for m in orders):
        return None
    U = _rotated(st, chan_u)                                          # (n_w, k, n_ord)
    I = _rotated(st, [ires])[:, 0, :] * res.polarity               # (n_w, n_ord)
    u_bg = np.mean(list(background.values()), axis=0)
    # least-squares fit over the windows: U_w − U_background = Z·I_w  →  Z = Σ(ΔU·I*)/Σ|I|²
    num = np.sum((U - u_bg[None]) * np.conj(I)[:, None, :], axis=0)
    den = np.sum(np.abs(I) ** 2, axis=0)
    Z = num / np.where(den > 0, den, np.nan)[None, :]
    return dict(Z=Z, U_background=u_bg, U_background_single=background, I_mean=np.mean(I, axis=0), n=len(I))


def _reliability(results: Dict[str, np.ndarray], n: int, jm: int, magnitude_fault: float, magnitude_background: float,
                 forecast: Optional[np.ndarray], phase_error: Optional[np.ndarray]) -> dict:
    """Characteristic values of the reliability of a fault-related component (row ``n``, order ``jm``) – the same for
    probes and current channels: spread of the superposition methods (as phasors), background/fault-related
    component, null test, frequency reference, estimated uncertainty and ``uncertain``."""
    phasor = [results[v][n, jm] for v in results if v not in ("direct", "fault")]
    phasor = [w for w in phasor if np.isfinite(w)]
    mean = abs(results["fault"][n, jm])
    # largest deviation between two methods as phasors (magnitude and angle), referred to the mean
    spread = (100.0 * max(abs(a - b) for a in phasor for b in phasor) / mean
              if len(phasor) > 1 and mean > 0 else np.nan)
    # sensitivity: background relative to the fault-related component; times the forecast error of the background
    # (null test) = estimated uncertainty of the fault-related component
    ratio = (float(magnitude_background / magnitude_fault) if np.isfinite(magnitude_background) and magnitude_fault > 0
             else np.nan)
    forecast_err = float(forecast[n, jm]) if forecast is not None else np.nan
    u_null_test = 100.0 * forecast_err * ratio                                  # null test (background fluctuates)
    u_frequency = (100.0 * 2 * math.sin(min(phase_error[jm], np.pi) / 2) * ratio
                   if phase_error is not None and phase_error[jm] > 0 else np.nan)
    parts = [u for u in (u_null_test, u_frequency) if np.isfinite(u)]
    uncertainty = math.sqrt(sum(u * u for u in parts)) if parts else np.nan
    uncertain = bool((np.isfinite(spread) and spread > UNCERTAIN_PCT)
                     or (np.isfinite(uncertainty) and uncertainty > UNCERTAIN_PCT)
                     or (not np.isfinite(spread) and not np.isfinite(uncertainty) and np.isfinite(ratio)
                         and ratio > 1.0))
    return dict(method_spread_pct=spread, background_to_fault=ratio,
                background_forecast_error_pct=100.0 * forecast_err, frequency_uncertainty_pct=u_frequency,
                uncertainty_pct=uncertainty, uncertain=uncertain)


def _row_uncertainty(df: pd.DataFrame, channel: str, m: int) -> Tuple[float, bool]:
    """Uncertainty (%) of a row of the station tables – the larger of the estimated uncertainty and the spread of the
    methods (0 if neither can be determined) – and its ``uncertain`` flag."""
    rows = df[(df["channel"] == channel) & (df["order"] == m)]
    if rows.empty:
        return 0.0, False
    values = [float(rows[c].iloc[0]) for c in ("uncertainty_pct", "method_spread_pct") if c in rows]
    values = [x for x in values if np.isfinite(x)]
    return (max(values) if values else 0.0), bool(rows["uncertain"].iloc[0]) if "uncertain" in rows else False


def _align(k_ref: np.ndarray, k: np.ndarray) -> Tuple[np.ndarray, int]:
    """Rotate the current phasors ``k`` (per order) to the counting direction of ``k_ref`` (±1), decided at the order
    at which both are largest (mostly 50 Hz) → (aligned phasors, sign)."""
    w = np.abs(k_ref) * np.abs(k)
    w = np.where(np.isfinite(w), w, -1.0)
    j = int(np.argmax(w))
    if w[j] <= 0:
        return k, 1
    s = -1 if np.real(k_ref[j] * np.conj(k[j])) < 0 else 1
    return s * k, s


def _is_touch_voltage_approximation(channel) -> bool:
    """True if the touch voltage of ``channel`` was taken from the shortest probe as an approximation.

    Uses ``touch_approximation``; the text of the role source is only checked
    for channel objects without that flag."""
    flag = getattr(channel, "touch_approximation", None)
    if flag is not None:
        return bool(flag)
    source = channel.source or ""
    return any(marker in source for marker in _APPROXIMATION_MARKERS)


def _lv_network(res, probes, currents, orders: Sequence[int], results: Dict[str, np.ndarray], I_win: np.ndarray,
                f_steady: float) -> None:
    """Current into the LV network and earthing impedance of the LV network from the PEN currents →
    ``station_lv_network`` (per probe and order) and ``station_lv_network_eff`` (RMS values over the orders).

    Fault-related current into the LV network I_LV = ΔI_PEN (superposition: fault minus background – the load
    unbalance drops out). With both measuring points (``feeders`` before, ``busbar`` after the transformer star
    point) Kirchhoff's current law applies: ΔI_feeders = −ΔI_busbar, because the current of the transformer star
    point does not change due to the earth fault. Result per order: mean of both measuring points, weighted with 1/u²
    (u = uncertainty or spread of the methods per channel, at least m_I) – at the measuring point with a large load
    unbalance the fault-related component is less certain. If the two differ by more than their uncertainties
    explain, the excess enters the uncertainty. Z_E,LV = ΔU_E/I_LV per probe and order.

    Probe maximum (rows with ``channel`` = [`MAX_PROBE`][groundfault.station.MAX_PROBE], column ``probe``): per order
    the probe with the highest fault-related voltage, in the RMS table the probe with the highest RMS value – over all
    probes against the station earth (earth potential rise and touch voltage). The potentials spread differently; every
    probe measures at most the full earth potential rise, the highest comes closest to it (U_E,fault = max(all U_E)).
    Rows per probe exist for the earth-potential probes (``u_e``).

    Parallel-branch check (column ``parallel_check``): the LV network is one branch of the total earthing, so
    |Z_E,LV| ≥ |r·Z_E| = |ΔU_E/I_F| (naive, with the fault current) – equivalent to |I_LV| ≤ |I_F|, independent
    of the probe. With shield currents, additionally the stricter condition against the earth current
    (``earth_current_check``): |Z_E,LV| ≥ |ΔU_E/I_E|, I_E = I_F − I_S (sum of all shield-current channels, each
    rotated to the direction of I_F), equivalent to |I_LV| ≤ |I_E|. A condition only counts as violated if the
    deviation is larger than the estimated uncertainty (superposition, spread of the methods, measurement
    uncertainty m_I per current). The comparison with an earthing measurement follows in
    [`groundfault.earthing.check_lv_network`][groundfault.earthing.check_lv_network]."""
    if "fault" not in results:
        return
    K = results["fault"]               # probes: ΔU/I_F (V/A) – currents: ΔI/I_F
    pen = [(len(probes) + i, k) for i, k in enumerate(currents) if k.role == "i_pen"]
    shield = [(len(probes) + i, k) for i, k in enumerate(currents) if k.role == "i_shield"]
    ue = [(n, k) for n, k in enumerate(probes) if k.role == "u_e"]
    if not pen:
        return
    df_u = res.tables.get("station_frequency", pd.DataFrame())
    df_i = res.tables.get("station_currents_frequency", pd.DataFrame())
    m_I = 100.0 * float(getattr(res.settings, "uncertainty_I", 0.0) or 0.0)    # measurement-uncertainty margins
    m_U = 100.0 * float(getattr(res.settings, "uncertainty_U", 0.0) or 0.0)    # of the user (%)
    # PEN measuring points: the first channel per position; without a position the first PEN channel (the
    # fault-related component is the same at both points)
    sources = []
    for position in ("feeders", "busbar"):
        cand = [x for x in pen if x[1].position == position]
        if cand:
            sources.append((position, cand[0]))
            if len(cand) > 1:
                res.hints.append(tr("station.lv_several_pen", position=i18n.value_label("position", position),
                                    channels=", ".join(k.short for _, k in cand), channel=cand[0][1].short))
    if not sources:
        sources.append(("", pen[0]))
    k_ref = K[sources[0][1][0]]
    ks = {}
    for position, (row, kinfo) in sources:
        k, sgn = (K[row], 1) if not ks else _align(k_ref, K[row])
        ks[position] = (k, kinfo, sgn)
    # uncertainty per measuring point and order (at least m_I) → weighted mean (1/u²)
    u_chan = {position: np.array([max(_row_uncertainty(df_i, kinfo.short, m)[0], m_I, _UNCERTAINTY_FLOOR_PCT)
                                  for m in orders])
              for position, (k, kinfo, _) in ks.items()}
    unc_chan = {position: np.array([_row_uncertainty(df_i, kinfo.short, m)[1] for m in orders])
                for position, (k, kinfo, _) in ks.items()}
    K_st = np.stack([v[0] for v in ks.values()])                       # (measuring points, n_ord)
    W = np.stack([1.0 / u_chan[p] ** 2 for p in ks])
    W = np.where(np.isfinite(K_st), W, 0.0)
    k_lv = np.where(W.sum(axis=0) > 0, np.nansum(np.where(np.isfinite(K_st), K_st, 0) * W, axis=0)
                    / np.maximum(W.sum(axis=0), 1e-300), np.nan)
    u_w = np.where(W.sum(axis=0) > 0, 1.0 / np.sqrt(np.maximum(W.sum(axis=0), 1e-300)), np.nan)
    kcl = None                                                         # deviation from Kirchhoff's current law (%)
    u_lv_arr = u_w.copy()
    if "feeders" in ks and "busbar" in ks:
        kv, kn = ks["feeders"][0], ks["busbar"][0]
        kcl = 100.0 * np.abs(kv - kn) / np.maximum(0.5 * (np.abs(kv) + np.abs(kn)), 1e-12)
        expected = np.sqrt(u_chan["feeders"] ** 2 + u_chan["busbar"] ** 2)
        over = np.where(np.isfinite(kcl), np.maximum(0.0, kcl - expected), 0.0)
        u_lv_arr = np.sqrt(u_w ** 2 + (0.5 * over) ** 2)
    # earth current I_E = I_F − ΣI_S (shield currents rotated to the direction of I_F: Re(k_S) ≥ 0 at 50 Hz)
    j1 = orders.index(1) if 1 in orders else int(np.nanargmax(np.abs(I_win)))
    k_s = None
    for row, kinfo in shield:
        k = K[row]
        s_ = -1 if (np.isfinite(k[j1]) and np.real(k[j1]) < 0) else 1
        k_s = s_ * k if k_s is None else k_s + s_ * k
    k_e = (1.0 - k_s) if k_s is not None else np.ones(len(orders), complex)
    # the formula before " (" is the same in both languages (figures test startswith("I_E"))
    reference = (tr("station.reference_shield", channels=", ".join(k.short for _, k in shield)) if shield
                 else tr("station.reference_no_shield"))

    def u_shield(m: int) -> float:
        parts = [_row_uncertainty(df_i, k.short, m)[0] for _, k in shield]
        return max(parts) if parts else 0.0

    def check_status(ratio: float, u: float) -> str:
        """Parallel branch: ratio I_LV/I_ref ≤ 1 (equivalent to Z_E,LV ≥ Z_E,ref) → status code."""
        if not np.isfinite(ratio):
            return "–"
        if ratio <= 1.0:
            return "satisfied"
        if 100.0 * (ratio - 1.0) <= u:
            return "borderline"
        return "violated"

    def lv_rows(channel: str, z_fault_per_order: np.ndarray,
                probe_per_order: Sequence) -> Tuple[List[dict], Optional[dict]]:
        """Rows per order and the RMS row for one probe or for the probe maximum (``probe_per_order``: probe per
        order)."""
        out = []
        sum_u = sum_lv = sum_e = sum_f = sum_lv_unc = 0.0
        ords_eff = []
        for jm, m in enumerate(orders):
            z_fault, k_lv_m, k_e_m = z_fault_per_order[jm], k_lv[jm], k_e[jm]
            probe = probe_per_order[jm]
            i_f = float(abs(I_win[jm]))
            u_probe, uncertain_probe = _row_uncertainty(df_u, probe.short, m) if probe is not None else (np.nan, False)
            kcl_m = float(kcl[jm]) if kcl is not None and np.isfinite(kcl[jm]) else np.nan
            u_lv = float(u_lv_arr[jm]) if np.isfinite(u_lv_arr[jm]) else m_I
            z_lv = z_fault / k_lv_m if np.isfinite(z_fault) and np.isfinite(k_lv_m) and abs(k_lv_m) > 0 else np.nan
            z_total = z_fault / k_e_m if np.isfinite(z_fault) and np.isfinite(k_e_m) and abs(k_e_m) > 0 else np.nan
            ratio = (float(abs(k_lv_m) / abs(k_e_m)) if np.isfinite(k_lv_m) and np.isfinite(k_e_m) and abs(k_e_m) > 0
                     else np.nan)
            ratio_naive = float(abs(k_lv_m)) if np.isfinite(k_lv_m) else np.nan     # I_LV/I_F = r·Z_E/Z_E,LV
            u_naive = math.sqrt(u_lv ** 2 + 2 * m_I ** 2)
            u_check = math.sqrt(u_lv ** 2 + u_shield(m) ** 2 + 2 * m_I ** 2)
            row = dict(channel=channel, probe=probe.short if probe is not None else "",
                       distance_m=(probe.distance_m if probe is not None and probe.distance_m is not None else np.nan),
                       order=m, f_Hz=m * f_steady, I_F_A=i_f,
                       I_LV_A=float(abs(k_lv_m)) * i_f if np.isfinite(k_lv_m) else np.nan,
                       share_I_LV=float(abs(k_lv_m)) if np.isfinite(k_lv_m) else np.nan)
            for position, (k, kinfo, sgn) in ks.items():
                row["I_LV_%s_A" % (position or "PEN")] = float(abs(k[jm])) * i_f if np.isfinite(k[jm]) else np.nan
                if len(ks) > 1:
                    row["weight_%s" % position] = float(W[list(ks).index(position), jm] / W[:, jm].sum()) \
                        if W[:, jm].sum() > 0 else np.nan
            if kcl is not None:
                row["kcl_deviation_pct"] = kcl_m
            row["I_LV_uncertainty_pct"] = u_lv
            row.update(U_E_fault_V=float(abs(z_fault)) * i_f if np.isfinite(z_fault) else np.nan,
                       Z_E_LV_Ohm=float(abs(z_lv)) if np.isfinite(z_lv) else np.nan,
                       Z_E_LV_angle_deg=float(np.degrees(np.angle(z_lv))) if np.isfinite(z_lv) else np.nan,
                       Z_E_LV_uncertainty_pct=math.sqrt(u_probe ** 2 + u_lv ** 2 + m_U ** 2 + m_I ** 2)
                       if np.isfinite(u_probe) else math.sqrt(u_lv ** 2 + m_U ** 2 + m_I ** 2),
                       rZE_fault_Ohm=float(abs(z_fault)) if np.isfinite(z_fault) else np.nan,
                       Z_LV_to_rZE_fault=1.0 / ratio_naive if np.isfinite(ratio_naive) and ratio_naive > 0 else np.nan,
                       parallel_check=check_status(ratio_naive, u_naive),
                       total_earthing_reference=reference,
                       Z_E_earth_current_Ohm=float(abs(z_total)) if np.isfinite(z_total) else np.nan,
                       I_LV_to_I_E=ratio, earth_current_check=check_status(ratio, u_check),
                       check_uncertainty_pct=u_check,
                       uncertain=bool(uncertain_probe or u_lv > UNCERTAIN_PCT
                                      or (len(ks) == 1 and bool(next(iter(unc_chan.values()))[jm]))))
            out.append(row)
            if np.isfinite(z_fault) and np.isfinite(k_lv_m) and np.isfinite(k_e_m):
                ords_eff.append(m)
                sum_u += abs(z_fault * I_win[jm]) ** 2
                sum_lv += abs(k_lv_m * I_win[jm]) ** 2
                sum_e += abs(k_e_m * I_win[jm]) ** 2
                sum_f += abs(I_win[jm]) ** 2
                if row["uncertain"]:
                    sum_lv_unc += abs(k_lv_m * I_win[jm]) ** 2
        if not ords_eff:
            return out, None
        u_eff, lv_eff, e_eff, f_eff = (math.sqrt(x) for x in (sum_u, sum_lv, sum_e, sum_f))
        ratio = lv_eff / e_eff if e_eff > 0 else np.nan
        ratio_naive = lv_eff / f_eff if f_eff > 0 else np.nan
        probes_eff = sorted({k.short for k in probe_per_order if k is not None})
        eff_row = dict(channel=channel, probe=", ".join(probes_eff),
                       distance_m=(probe_per_order[0].distance_m
                                   if len(probes_eff) == 1 and probe_per_order[0] is not None
                                   and probe_per_order[0].distance_m is not None else np.nan),
                       orders=", ".join(str(m) for m in ords_eff), I_F_eff_A=f_eff, I_LV_eff_A=lv_eff,
                       share_I_LV_eff=ratio_naive, U_E_fault_eff_V=u_eff,
                       Z_E_LV_eff_Ohm=u_eff / lv_eff if lv_eff > 0 else np.nan,
                       rZE_fault_eff_Ohm=u_eff / f_eff if f_eff > 0 else np.nan,
                       parallel_check=("satisfied" if ratio_naive <= 1.0 else "violated (see orders)")
                       if np.isfinite(ratio_naive) else "–",
                       total_earthing_reference=reference,
                       Z_E_earth_current_eff_Ohm=u_eff / e_eff if e_eff > 0 else np.nan,
                       I_LV_to_I_E_eff=ratio,
                       earth_current_check=("satisfied" if ratio <= 1.0 else "violated (see orders)")
                       if np.isfinite(ratio) else "–",
                       uncertain_share_pct=100.0 * sum_lv_unc / sum_lv if sum_lv > 0 else np.nan)
        return out, eff_row

    rows, eff = [], []
    # Probe maximum (earth potential rise of the earth fault = highest probe, per order or as RMS value): the
    # potentials spread differently; every probe against the station earth (the touch-voltage probe as well) measures
    # at most the full earth potential rise – the highest comes closest to it
    all_probes = [(n, k) for n, k in enumerate(probes) if k.role in ("u_e", "u_t")]
    with_max = len(all_probes) > 1 or (len(all_probes) == 1 and not ue)
    if with_max:
        magnitudes = np.array([[abs(K[n, jm]) if np.isfinite(K[n, jm]) else -1.0 for jm in range(len(orders))]
                               for n, _ in all_probes])
        j_max = np.argmax(magnitudes, axis=0)
        z_max = np.array([K[all_probes[j][0], jm] if magnitudes[j, jm] >= 0 else np.nan for jm, j in enumerate(j_max)])
        probe_max = [all_probes[j][1] if magnitudes[j, jm] >= 0 else None for jm, j in enumerate(j_max)]
        z, _ = lv_rows(MAX_PROBE, z_max, probe_max)
        rows += z
    eff_all = []
    for n, probe in all_probes:
        z, e = lv_rows(probe.short, K[n], [probe] * len(orders))
        if probe.role == "u_e":                  # table rows per probe only for the earth-potential probes
            rows += z
            if e is not None:
                eff.append(e)
        if e is not None:
            eff_all.append(e)
    if with_max and eff_all:
        best = max(eff_all, key=lambda e: e["U_E_fault_eff_V"])
        eff.insert(0, dict(best, channel=MAX_PROBE))
    res.tables["station_lv_network"] = pd.DataFrame(rows)
    res.tables["station_lv_network_eff"] = pd.DataFrame(eff)
    res.values["station_lv_network"] = dict(pen=[{"channel": v[1].short, "position": k or None, "sign": v[2]}
                                                 for k, v in ks.items()],
                                            shield=[k.short for _, k in shield], reference=reference)
    # hints
    if kcl is not None and np.isfinite(kcl[j1]) and kcl[j1] > UNCERTAIN_PCT:
        expected = float(np.sqrt(u_chan["feeders"][j1] ** 2 + u_chan["busbar"][j1] ** 2))
        name_feeders, name_busbar = ks["feeders"][1].short, ks["busbar"][1].short
        if kcl[j1] - expected > UNCERTAIN_PCT:
            res.hints.append(tr("station.lv_kcl_violated", feeders=name_feeders, busbar=name_busbar,
                                deviation=kcl[j1], expected=expected))
        else:
            safer = name_feeders if u_chan["feeders"][j1] < u_chan["busbar"][j1] else name_busbar
            w = float(W[list(ks).index("feeders" if safer == name_feeders else "busbar"), j1] / W[:, j1].sum())
            res.hints.append(tr("station.lv_kcl_explained", feeders=name_feeders, busbar=name_busbar,
                                deviation=kcl[j1], u_feeders=u_chan["feeders"][j1], u_busbar=u_chan["busbar"][j1],
                                weight=100 * w, channel=safer))
    df = res.tables["station_lv_network"]
    if not df.empty and (df["earth_current_check"] == "violated").any():
        freqs = sorted({round(x) for x in df.loc[df["earth_current_check"] == "violated", "f_Hz"]})
        # whole numbers (rounded frequencies): no decimal separator involved
        res.hints.append(tr("station.lv_exceeds_earth_current", reference=reference.split(" (")[0],
                            frequencies=", ".join("%g" % x for x in freqs)))


# ---------------------------------------------------------------------------------------------- evaluation
def frequency_selective(res, rec, shift=None, orders: Optional[Sequence[int]] = None) -> None:
    """Frequency-selective station evaluation: earth potential rise and touch voltage per order.

    Determines, per probe and order, the ratio U/I_F as measured and as the fault-related component (superposition
    methods, see the module description for the methods and the reliability checks), the fault-related PEN and shield
    currents, the current into the LV network and the extrapolation to the limit currents. Called by
    [`groundfault.evaluate`][groundfault.evaluation.evaluate] for recordings with station channels; adds tables, values
    and hints to ``res``.

    Parameters
    ----------
    res : Result
        Result of the evaluation of a station recording (fault-current channel ``i_res`` and probes ``u_e``/``u_t``
        or PEN/shield currents ``i_pen``/``i_shield``); extended in place. Without a fault-current channel or without
        probes and currents nothing is added.
    rec : Recording
        The evaluated recording.
    shift : dict, optional
        ``{channel index: Δn}`` – time offset in samples per channel (the channel is read from [i0+Δn, i1+Δn)), as
        used by the evaluation for channels recorded with a different time base.
    orders : sequence of int, optional
        Orders to evaluate. Default: the orders ≤ 25 of the evaluation whose fault current in the max window is at
        least max(0.1 A, 1 % of the fundamental component). Order 1 is always included.

    Notes
    -----
    Tables added to ``res.tables``:

    ``station_frequency``
        Per probe and order: voltage during the fault and background, fault current, U/I_F by every method
        (magnitude in Ω = V/A, angle referred to I_F), V per 100 A, F = U_E/U_T, spread of the methods, null test,
        uncertainty and ``uncertain``.
    ``station_currents_frequency``
        The same for PEN and shield currents: ratio ΔI/I_F by every method (columns ``share_<method>``),
        fault-related current and its reliability.
    ``station_lv_network``, ``station_lv_network_eff``
        Only with PEN currents: current into the LV network, earthing impedance of the LV network and the
        parallel-branch checks, per probe (and probe maximum [`MAX_PROBE`][groundfault.station.MAX_PROBE]) and order,
        and as RMS values.
    ``station_extrapolation``
        Earth potential rise/touch voltage at the limit currents (``Settings.ires_limits``, defined by the user):
        proportional (``U_proportional_V``, as before), fault-related component only (``U_fault_V``), background plus
        fault-related component with the phase relation of the test (``U_background_plus_fault_V``) and as an upper
        bound with both in phase at every order (``U_background_plus_fault_in_phase_V`` = √Σ(|U_bg,m| +
        k·|ΔU_m|)² – at a real fault the phase relation differs: another faulted line turns the fault current by
        ±120° against the network voltage, the load is another). Empty without limits (with a hint).

    ``res.values["station_frequency"]`` records the instants of fault inception and clearance, the frequencies and
    their sources and the window counts of the methods; ``res.values["station_lv_network"]`` the PEN and shield
    channels used and the reference of the total earthing. Station hints start with ``Station`` (except the hints
    on a touch voltage taken from the shortest probe and on missing limits of the residual current), LV-network hints
    with ``LV network:`` (German output: ``Ortsnetz:``).
    """
    roles, settings, st, wi = res.roles, res.settings, res.steady_state, res.max_index
    ires_channel = roles.main("i_res")
    probes = roles.with_role("u_e") + roles.with_role("u_t")
    currents = roles.with_role("i_pen") + roles.with_role("i_shield")     # same superposition as the probes
    if ires_channel is None or not (probes or currents):
        return
    ires = ires_channel.index
    channels = probes + currents                     # rows of the method matrices: probes first, then currents
    chan_u = [k.index for k in channels]
    if orders is None:
        IF1 = abs(st.X[wi, ires, st.ix(1)])
        threshold = max(0.1, 0.01 * IF1)
        orders = [m for m in st.orders if m <= 25 and abs(st.X[wi, ires, st.ix(m)]) >= threshold]
    orders = [int(m) for m in orders if m in st.orders]
    if 1 not in orders:
        orders = [1] + orders
    pol = res.polarity
    f_steady = float(st.f1["f1_used"])

    # ------------------------------------------------------------------ methods
    results: Dict[str, np.ndarray] = {}        # method → Z (k, n_ord)
    info: Dict[str, dict] = {}
    # direct (max window)
    I_win = pol * np.array([st.X[wi, ires, st.ix(m)] for m in orders])
    U_win = np.array([[st.X[wi, j, st.ix(m)] for m in orders] for j in chan_u])
    results["direct"] = U_win / np.where(np.abs(I_win) > 0, I_win, np.nan)[None, :]
    info["direct"] = dict(t_s=float(st.t_mid[wi]))
    # time reference at fault inception and clearance
    dt = float((shift or {}).get(ires, 0)) / rec.fs          # time offset of the fault-current channel (alignment)
    b_st = getattr(getattr(res, "intervals", None), "steady_state", None)
    t_inside = (0.5 * (b_st[0] + b_st[1]) + dt) if b_st else None       # during the fault: around the steady state
    t_on, t_off = fault_times(rec, ires, t_inside=t_inside)
    t_quiet = settled_from(rec, ires, t_on, t_off) if t_on is not None else None
    if dt:
        t_on, t_off, t_quiet = (None if x is None else x - dt for x in (t_on, t_off, t_quiet))
    T = settings.T_win
    sides = {}
    if t_on is not None:
        t_quiet = min(t_quiet, t_on + T_TRANSIENT_MAX_S)          # keep the phase reference short (frequency drift)
        fault_to = min(t_quiet + T_WINDOW_SEQUENCE_S, (t_off - 2 * T_EDGE_S) if t_off else rec.duration_s)
        sides["inception"] = _side(rec, roles, chan_u, ires,
                                   (max(0.0, t_on - T_WINDOW_SEQUENCE_S - T_EDGE_S), t_on - T_EDGE_S),
                                   (t_quiet, fault_to), t_on, orders, f_steady, settings.f_nominal, T, pol, shift)
    if t_off is not None:
        # before clearance the fault current is steady (a short margin suffices); afterwards U0 decays (settling)
        fault_from = max(t_off - 2 * T_EDGE_S - T_WINDOW_SEQUENCE_S, (t_on or 0.0) + T_TRANSIENT_S)
        sides["clearance"] = _side(rec, roles, chan_u, ires,
                                   (t_off + T_TRANSIENT_S,
                                    min(rec.duration_s, t_off + T_TRANSIENT_S + T_WINDOW_SEQUENCE_S)),
                                   (fault_from, t_off - 2 * T_EDGE_S), t_off, orders, f_steady, settings.f_nominal, T,
                                   pol, shift)
    # fault-free sections for the null test (at most T_NULL_TEST_MAX_S each, closest to the fault)
    regions = []
    if t_on is not None and t_on - T_EDGE_S > 0.5:
        regions.append((max(0.0, t_on - T_EDGE_S - T_NULL_TEST_MAX_S), t_on - T_EDGE_S))
    if t_off is not None and rec.duration_s - t_off - T_TRANSIENT_S > 0.5:
        regions.append((t_off + T_TRANSIENT_S, min(rec.duration_s, t_off + T_TRANSIENT_S + T_NULL_TEST_MAX_S)))
    for name, s in sides.items():
        if s is None:
            continue
        dU = s["U_fault"] - s["U_background"]
        results[name] = dU / np.where(np.abs(s["I_fault"]) > 0, s["I_fault"], np.nan)[None, :]
        t_ref = s["t_ref"]
        s["forecast_error"] = _forecast_error(
            rec, roles, chan_u, orders, settings.f_nominal, T, regions,
            (s["t_background"][0] - t_ref, s["t_background"][1] - t_ref),
            (s["t_fault"][0] - t_ref, s["t_fault"][1] - t_ref), shift) if regions else None
        info[name] = s
    vref = _voltage_reference(res, chan_u, ires, orders)
    if vref is not None:
        results["voltage"] = vref["Z"]
        info["voltage"] = vref
    superposition = [v for k, v in results.items() if k != "direct"]
    if superposition:
        results["fault"] = np.nanmean(np.stack(superposition), axis=0)

    # ------------------------------------------------------------------ background and fault-related component
    # Background as a phasor relative to the fault current (I_F at 0°): only then can it be added to the
    # fault-related component (extrapolation). Source: fault inception, otherwise clearance, otherwise voltage
    # reference.
    U_background = None
    for source in ("inception", "clearance"):
        s = info.get(source)
        if s is not None:
            U_background = (s["U_background"]
                            * (np.conj(s["I_fault"]) / np.maximum(np.abs(s["I_fault"]), 1e-12))[None, :])
            break
    if U_background is None and vref is not None:
        U_background = (vref["U_background"]
                        * (np.conj(vref["I_mean"]) / np.maximum(np.abs(vref["I_mean"]), 1e-12))[None, :])
    # forecast error of the background (null test) – mean of the time-reference methods used
    forecast_sides = [info[s]["forecast_error"] for s in ("inception", "clearance")
                      if s in info and info[s].get("forecast_error") is not None]
    forecast = np.mean(np.stack(forecast_sides), axis=0) if forecast_sides else None
    # possible phase error of the frequency reference "fault current" (without voltage measurement) – mean of the sides
    phase_error_sides = [info[s]["phase_error_rad"] for s in ("inception", "clearance") if s in info]
    phase_error = np.mean(np.stack(phase_error_sides), axis=0) if phase_error_sides else None
    rows = []
    ue_rows = [n for n, k in enumerate(probes) if k.role == "u_e"]
    for n, k in enumerate(probes):
        for jm, m in enumerate(orders):
            row = dict(channel=k.short, role=k.role, distance_m=(k.distance_m if k.distance_m is not None else np.nan),
                       order=m, f_Hz=m * f_steady,
                       I_F_A=float(abs(I_win[jm])), U_during_fault_V=float(abs(U_win[n, jm])),
                       U_background_V=float(abs(U_background[n, jm])) if U_background is not None else np.nan)
            for method, Z in results.items():
                zz = Z[n, jm]
                row["Z_%s_Ohm" % method] = float(abs(zz)) if np.isfinite(zz) else np.nan
                row["Z_%s_angle_deg" % method] = float(np.degrees(np.angle(zz))) if np.isfinite(zz) else np.nan
            if "fault" in results:
                row["U_fault_V"] = float(abs(results["fault"][n, jm] * I_win[jm]))
                row.update(_reliability(results, n, jm, row["U_fault_V"],
                                        abs(U_background[n, jm]) if U_background is not None else np.nan,
                                        forecast, phase_error))
            row["V_per_100A_direct"] = 100.0 * row["Z_direct_Ohm"]
            row["V_per_100A_fault"] = 100.0 * row.get("Z_fault_Ohm", np.nan)
            if k.role == "u_t" and ue_rows:
                ue = ue_rows[0]
                row["F_direct"] = float(abs(U_win[ue, jm]) / abs(U_win[n, jm])) if abs(U_win[n, jm]) > 0 else np.nan
                if "fault" in results:
                    a, b = results["fault"][ue, jm], results["fault"][n, jm]
                    row["F_fault"] = float(abs(a) / abs(b)) if abs(b) > 0 else np.nan
            rows.append(row)
    res.tables["station_frequency"] = pd.DataFrame(rows)

    # ------------------------------------------------------------------ PEN and shield currents (fault-related)
    # For a current channel the same methods give the ratio k = ΔI/I_F (complex, I_F at 0°): ΔI is the component
    # caused by the fault current – the load unbalance (already present before the fault) drops out.
    rows_i = []
    for n_i, k in enumerate(currents):
        n = len(probes) + n_i
        for jm, m in enumerate(orders):
            row = dict(channel=k.short, role=k.role, position=k.position or "", order=m, f_Hz=m * f_steady,
                       I_F_A=float(abs(I_win[jm])), I_during_fault_A=float(abs(U_win[n, jm])),
                       I_background_A=float(abs(U_background[n, jm])) if U_background is not None else np.nan)
            for method, Z in results.items():
                kk = Z[n, jm]
                row["share_%s" % method] = float(abs(kk)) if np.isfinite(kk) else np.nan
                row["share_%s_angle_deg" % method] = float(np.degrees(np.angle(kk))) if np.isfinite(kk) else np.nan
            if "fault" in results:
                row["I_fault_A"] = float(abs(results["fault"][n, jm] * I_win[jm]))
                row.update(_reliability(results, n, jm, row["I_fault_A"],
                                        abs(U_background[n, jm]) if U_background is not None else np.nan,
                                        forecast, phase_error))
            rows_i.append(row)
    res.tables["station_currents_frequency"] = pd.DataFrame(rows_i)
    _lv_network(res, probes, currents, orders, results, I_win, f_steady)

    # ------------------------------------------------------------------ extrapolation to the limit currents
    I_rms = float(st.rms[wi, ires])
    if not probes:
        res.tables["station_extrapolation"] = pd.DataFrame()
    elif not tuple(settings.ires_limits or ()):
        res.hints.append(tr("station.no_limits"))              # the limits are defined by the user
    extrapolation = []
    for n, k in enumerate(probes):
        u_rms = float(st.rms[wi, k.index])
        for limit in settings.ires_limits:
            scale = limit / I_rms if I_rms > 0 else np.nan
            row = dict(channel=k.short, role=k.role, I_limit_A=limit, U_proportional_V=u_rms * scale)
            if "fault" in results:
                dU = results["fault"][n] * np.abs(I_win)                # fault-related phasors, I_F at 0°
                ok = np.isfinite(dU)
                row["U_fault_V"] = float(np.sqrt(np.sum(np.abs(scale * dU[ok]) ** 2)))
                if U_background is not None:
                    total_sq = float(np.sum(np.abs(U_background[n][ok] + scale * dU[ok]) ** 2))
                    # upper bound: background and fault-related component in phase at every order (at a real fault
                    # their phase relation differs from the test – another faulted line, another load)
                    upper_sq = float(np.sum((np.abs(U_background[n][ok]) + scale * np.abs(dU[ok])) ** 2))
                    # the background at the remaining frequencies (orders without appreciable fault current,
                    # interharmonics) is added unchanged: RMS value before the fault minus the orders covered
                    pre = res.pre_fault
                    if pre is not None and (~pre.nan_window).any():
                        pre_ms = float(np.nanmean(pre.rms[~pre.nan_window, k.index] ** 2))
                        rest = max(0.0, pre_ms - float(np.sum(np.abs(U_background[n][ok]) ** 2)))
                        total_sq += rest
                        upper_sq += rest
                    row["U_background_plus_fault_V"] = math.sqrt(total_sq)
                    row["U_background_plus_fault_in_phase_V"] = math.sqrt(upper_sq)
            extrapolation.append(row)
    res.tables["station_extrapolation"] = pd.DataFrame(extrapolation)

    # ------------------------------------------------------------------ characteristic values and hints
    meta = dict(orders=list(orders), t_fault_inception_s=t_on, t_fault_clearance_s=t_off,
                method=[v for v in results])
    for name in ("inception", "clearance"):
        s = info.get(name)
        if s:
            meta[name] = dict(f_background_hz=s["f_background"], f_fault_hz=s["f_fault"],
                              n_background=s["n_background"], n_fault=s["n_fault"],
                              t_background_s=list(s["t_background"]), t_fault_s=list(s["t_fault"]),
                              f_background_source=s["source_background"]
                              or tr("station.background_source_missing", reason=_reason_missing_text(s)),
                              f_background_span_mhz=(1e3 * s["span_background_hz"]
                                                     if s["span_background_hz"] is not None else None),
                              f_fault_source=s["source_fault"], null_test=s.get("forecast_error") is not None)
    if vref is not None:
        meta["voltage"] = dict(window_samples=int(vref["n"]), background_from=list(vref["U_background_single"]))
    res.values["station_frequency"] = meta
    df = res.tables["station_frequency"]
    if not df.empty and "uncertain" in df and df["uncertain"].any():
        parts = []
        unc_rows = df[df["uncertain"]]
        # name at most six frequencies – those with the most fault current (most important for the comparison)
        important = unc_rows.groupby("order")["I_F_A"].max().sort_values(ascending=False)
        rest = max(0, len(important) - 6)
        for m, g in unc_rows[unc_rows["order"].isin(important.index[:6])].groupby("order"):
            spread_max, unc_max = g["method_spread_pct"].max(), g["uncertainty_pct"].max()
            freq_unc_max = g["frequency_uncertainty_pct"].max() if "frequency_uncertainty_pct" in g else np.nan
            reasons = []
            if np.isfinite(spread_max) and spread_max > UNCERTAIN_PCT:
                reasons.append(tr("station.uncertain_spread", spread=spread_max))
            if np.isfinite(unc_max) and unc_max > UNCERTAIN_PCT:
                mainly_frequency = np.isfinite(freq_unc_max) and freq_unc_max >= 0.7 * unc_max
                reasons.append(tr("station.uncertain_uncertainty_frequency" if mainly_frequency
                                  else "station.uncertain_uncertainty", uncertainty=unc_max))
            if not reasons:
                reasons.append(tr("station.uncertain_background", ratio=g["background_to_fault"].max()))
            parts.append(tr("station.uncertain_frequency", f=round(m * f_steady), reasons=", ".join(reasons)))
        if rest:
            parts.append(tr("station.uncertain_more", count=rest))
        res.hints.append(tr("station.uncertain_values", parts="; ".join(parts)))
    for name in ("inception", "clearance"):
        s = info.get(name)
        if s and s["source_background"] is None:
            if s["reason_missing"] == "too_short":
                cause = tr("station.cause_too_short_" + name)
            elif s["reason_missing"] == "no_background":
                cause = tr("station.cause_no_background")
            else:
                cause = tr("station.cause_estimate", reason=_reason_missing_text(s))
            res.hints.append(tr("station.frequency_not_estimable_" + name, cause=cause))
    if U_background is not None and not df.empty:
        g1 = df[df["order"] == 1]
        share = (g1["U_background_V"] / g1["U_during_fault_V"]).replace([np.inf], np.nan)
        if len(share) and float(np.nanmax(share)) > 0.25:
            res.hints.append(tr("station.background_large", share=100 * float(np.nanmax(share))))
    for k in probes:
        if k.role == "u_t" and _is_touch_voltage_approximation(k):
            res.hints.append(tr("station.touch_voltage_approximation", probe=k.short, distance=k.distance_m))
    if not superposition:
        reason = tr("station.reason_fault_too_short" if t_on is not None and t_off is not None
                    else "station.reason_no_fault_times")
        res.hints.append(tr("station.fault_component_unavailable", reason=reason))
    elif len(superposition) == 1:
        only = [METHODS[k].split(" (")[0] for k in results if k not in ("direct", "fault")][0]
        res.hints.append(tr("station.single_method", method=only))
