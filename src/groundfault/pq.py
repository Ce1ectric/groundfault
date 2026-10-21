# -*- coding: utf-8 -*-
"""Power-quality (PQ) measurements of the busbar voltage: reading device exports, 10-min values, quantiles and the
scaling of the harmonic content of staged fault tests.

A staged fault test measures the harmonic currents at the harmonic voltage level of the test day. A PQ measurement of
the same busbar in undisturbed operation shows how high this level is over weeks or a year. The assessment uses a
high quantile of it, and the harmonic currents of the test are scaled to it: the current of an order m driven by the
pre-fault voltage follows that voltage linearly (fault loop of the order m with the pre-fault voltage of the faulted
phase as source).

Steps
-----
1. **Read** the export of the PQ instrument: [`read`][groundfault.pq.read] (several files, duplicated and overlapping
   periods are recognised), [`read_winpq`][groundfault.pq.read_winpq] (CSV export of the software *WinPQ mobil* for
   the instruments *PQ-Box*) or [`from_frame`][groundfault.pq.from_frame] (any instrument, after reading its export
   with pandas).
2. **10-min values** ([`ten_minute_values`][groundfault.pq.ten_minute_values]): clock-aligned intervals, square root
   of the mean of the squares of the shorter values as in IEC 61000-4-30; intervals with missing values are left
   out (counted).
3. **Quantile** ([`assess`][groundfault.pq.assess]): per 10-min interval the largest of the three phases (line-to-earth
   per order) or loops (line-to-line THD), of these the quantile over the measuring period (default 95 %).
4. **Factor** on the quantile, from the duration of the measurement – its longest stretch of gapless values – and a
   rule of the user ([`duration_factor`][groundfault.pq.duration_factor], e.g. a factor above 1 for a measurement
   shorter than a year). Shorter than every duration of the rule, the measurement is not valid for the assessment.
   groundfault contains no such rule.
5. **Use** ([`PQAssessment`][groundfault.pq.PQAssessment]): the keyword arguments of
   [`groundfault.equivalent_source.ires_at_impedance`][groundfault.equivalent_source.ires_at_impedance]
   (``scaling``), of [`groundfault.evaluation.Settings`][groundfault.evaluation.Settings] (``settings``), the
   voltages of the forecast of the optional part [`groundfault.forecast`][groundfault.forecast] (``voltages``,
   ``series``), the position of the voltage of a fault test in the distribution of the PQ measurement
   (``comparability``) and the weekly profile (``profile``).

Scaling of the harmonic currents of a fault test
------------------------------------------------
* Orders of the positive and negative sequence (odd, not a multiple of 3: 5, 7, 11, 13, 17, 19 …): each with its own
  voltage, U_95,m/U_level,m – the 250-Hz current with the 250-Hz voltage; an order without its own value (no quantile,
  no usable level) with the THD, THD_95/THD_test.
* Orders of the zero sequence (odd multiples of 3: 3, 9, 15 …): not scaled – the zero sequence arises in the earth
  fault.
* Even orders (2, 4, 6, 8 …): not scaled, listed separately – atypical in the network, they may point to another
  cause (e.g. a DC component or saturation at the fault inception).

Conventions
-----------
* Harmonic voltages in V, phases ``L1``, ``L2``, ``L3`` (line-to-earth) or ``L12``, ``L23``, ``L31`` (line-to-line);
  THD in % of the fundamental component.
* Time stamps mark the **end** of an interval (as in the exports of the PQ instruments and in IEC 61000-4-30).
  Without ``timezone`` they are the local time of the instrument clock as exported.
* The orders of the zero sequence (3, 9, 15 …) are contained only in line-to-earth voltages.
* The PQ measurement and the fault tests must refer to the same network and switching state (busbar, transformer,
  network section).

Examples
--------
>>> from groundfault import pq
>>> data = pq.read(["Export_1.csv", "Export_2.csv"])                   # doctest: +SKIP
>>> a = pq.assess(data, factors={D_long: 1.0, D_short: k_short})       # doctest: +SKIP
>>> a.table()                                                          # doctest: +SKIP
>>> a.scaling(thd_measured_percent=0.6)    # → equivalent_source.ires_at_impedance(..., **scaling)  # doctest: +SKIP
"""
from __future__ import annotations

import hashlib
import io
import math
import os
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from . import i18n
from .i18n import tr
from .legacy import check_option

__all__ = ["PQData", "PQAssessment", "read", "read_winpq", "from_frame", "combine", "ten_minute_values",
           "duration_factor", "assess", "pre_fault_levels", "PHASES_LE", "PHASES_LL", "ZERO_SEQUENCE"]

PHASES_LE = ("L1", "L2", "L3")
"""Phase labels of line-to-earth voltages."""
PHASES_LL = ("L12", "L23", "L31")
"""Labels of the line-to-line voltages (loops)."""
ZERO_SEQUENCE = "multiple of 3"
"""Orders of the zero sequence in a symmetrical network: the multiples of 3 (3, 6, 9, 15 …)."""

_HOW = ("rms", "mean")
_LABELS = ("end", "start")

i18n.register({
    # ---- reading
    "pq.file_missing": {"en": "PQ export not found: {path}", "de": "PQ-Export nicht gefunden: {path}"},
    "pq.no_header": {
        "en": "{path}: no header row with the date and time columns ('Datum'/'Date', 'Zeit'/'Time') found – not a "
              "WinPQ export? Read other exports with pandas and pq.from_frame.",
        "de": "{path}: keine Kopfzeile mit den Spalten Datum und Zeit ('Datum'/'Date', 'Zeit'/'Time') gefunden – kein "
              "WinPQ-Export? Andere Exporte mit pandas lesen und pq.from_frame übergeben."},
    "pq.no_time": {
        "en": "{source}: the time stamps cannot be read (first values: {values}).",
        "de": "{source}: Zeitstempel nicht lesbar (erste Werte: {values})."},
    "pq.no_harmonics": {
        "en": "{source}: no harmonic voltages found (columns such as 'H5_UL1_[V]' or 'H5_L1'); columns: {columns}",
        "de": "{source}: keine Oberschwingungsspannungen gefunden (Spalten wie 'H5_UL1_[V]' oder 'H5_L1'); "
              "Spalten: {columns}"},
    "pq.percent_without_fundamental": {
        "en": "{source}: harmonic voltages in % of the fundamental, but no fundamental (order 1) of {phases} – "
              "they are left out.",
        "de": "{source}: Oberschwingungsspannungen in % der Grundschwingung, aber keine Grundschwingung (Ordnung 1) "
              "von {phases} – nicht verwendet."},
    "pq.ignored_columns": {
        "en": "{source}: {n} columns not used (e.g. {examples}).",
        "de": "{source}: {n} Spalten nicht verwendet (z. B. {examples})."},
    "pq.duplicate_stamps": {
        "en": "{source}: {n} duplicated time stamps (e.g. {first}) – a clock change of daylight saving time? Give "
              "timezone=… or check the instrument clock.",
        "de": "{source}: {n} doppelte Zeitstempel (z. B. {first}) – Zeitumstellung? timezone=… angeben bzw. die "
              "Geräteuhr prüfen."},
    "pq.dst_dropped": {
        "en": "{source}: {n} time stamps cannot be assigned in the time zone {timezone} (the hour skipped or repeated "
              "at a change of daylight saving time) – left out. If the instrument clock does not follow daylight "
              "saving time, give a fixed offset (e.g. 'Etc/GMT-1' for UTC+1).",
        "de": "{source}: {n} Zeitstempel lassen sich in der Zeitzone {timezone} nicht zuordnen (die bei der "
              "Zeitumstellung übersprungene oder doppelte Stunde) – nicht verwendet. Folgt die Geräteuhr der "
              "Sommerzeit nicht, einen festen Versatz angeben (z. B. 'Etc/GMT-1' für UTC+1)."},
    "pq.interval_unknown": {
        "en": "{source}: the interval cannot be determined (one time stamp, no 'Intervall:' line) – give interval_s.",
        "de": "{source}: das Intervall lässt sich nicht bestimmen (ein Zeitstempel, keine Zeile 'Intervall:') – "
              "interval_s angeben."},
    "pq.interval_header_mismatch": {
        "en": "{source}: the header names an interval of {header:g} s, the time stamps have a step of {step:g} s – "
              "the step of the time stamps is used.",
        "de": "{source}: der Kopf nennt ein Intervall von {header:g} s, die Zeitstempel haben einen Abstand von "
              "{step:g} s – der Abstand der Zeitstempel gilt."},
    "pq.empty_columns": {
        "en": "{source}: {n} columns without any value left out (e.g. {examples}).",
        "de": "{source}: {n} Spalten ohne einen Wert nicht verwendet (z. B. {examples})."},
    "pq.identical_file": {
        "en": "{file} is identical to {other} (same content) – read once.",
        "de": "{file} ist identisch mit {other} (gleicher Inhalt) – einmal gelesen."},
    "pq.same_period": {
        "en": "{file} contains the same {n} time stamps as {other} (period {start} … {end}) – used once.",
        "de": "{file} enthält dieselben {n} Zeitstempel wie {other} (Zeitraum {start} … {end}) – einmal verwendet."},
    "pq.overlap": {
        "en": "{file}: {n} time stamps overlap with {other} – the values of {other} are kept.",
        "de": "{file}: {n} Zeitstempel überschneiden sich mit {other} – die Werte von {other} gelten."},
    "pq.interval_mismatch": {
        "en": "The exports have different intervals ({intervals} s) – aggregate them to 10-min values first "
              "(pq.ten_minute_values) and combine those.",
        "de": "Die Exporte haben verschiedene Intervalle ({intervals} s) – zuerst zu 10-min-Werten zusammenfassen "
              "(pq.ten_minute_values) und diese kombinieren."},
    "pq.no_files": {"en": "No PQ export given.", "de": "Kein PQ-Export angegeben."},
    # ---- 10-min values
    "pq.interval_too_long": {
        "en": "The interval of the export ({interval:g} s) is longer than {target:g} s – 10-min values cannot be "
              "formed from it; export 10-min values or a shorter interval.",
        "de": "Das Intervall des Exports ({interval:g} s) ist länger als {target:g} s – daraus lassen sich keine "
              "10-min-Werte bilden; 10-min-Werte oder ein kürzeres Intervall exportieren."},
    "pq.interval_not_divisor": {
        "en": "The interval of the export ({interval:g} s) does not divide {target:g} s.",
        "de": "Das Intervall des Exports ({interval:g} s) teilt {target:g} s nicht."},
    "pq.incomplete_dropped": {
        "en": "{n} of {total} 10-min intervals are incomplete (fewer than {need} of {per} values) and are not used.",
        "de": "{n} von {total} 10-min-Intervallen sind unvollständig (weniger als {need} von {per} Werten) und werden "
              "nicht verwendet."},
    "pq.aggregated": {
        "en": "10-min values formed from {per} values of {interval:g} s each ({how}).",
        "de": "10-min-Werte aus je {per} Werten zu {interval:g} s gebildet ({how})."},
    "pq.how_rms": {"en": "square root of the mean of the squares", "de": "quadratischer Mittelwert"},
    "pq.how_mean": {"en": "arithmetic mean", "de": "arithmetischer Mittelwert"},
    # ---- factor
    "pq.factor_rule_invalid": {
        "en": "factors must map minimum durations in days (> 0) to factors (> 0), e.g. {{D_1: k_1, D_2: k_2}} – got "
              "{value!r}.",
        "de": "factors muss Mindestdauern in Tagen (> 0) auf Faktoren (> 0) abbilden, z. B. {{D_1: k_1, D_2: k_2}} – "
              "erhalten: {value!r}."},
    "pq.factor_invalid": {
        "en": "factor must be a number > 0 – got {value!r}.",
        "de": "factor muss eine Zahl > 0 sein – erhalten: {value!r}."},
    "pq.factor_from_rule": {
        "en": "Measurement with {days:.1f} days of gapless values (≥ {minimum:g} days) → factor {factor:g} on the "
              "quantile.",
        "de": "Messung mit {days:.1f} Tagen lückenloser Werte (≥ {minimum:g} Tage) → Faktor {factor:g} auf das "
              "Quantil."},
    "pq.factor_too_short": {
        "en": "Measurement with {days:.1f} days of gapless values is shorter than the shortest duration of the rule "
              "({minimum:g} days) – not valid for the assessment: no factor, no scaling with this measurement.",
        "de": "Messung mit {days:.1f} Tagen lückenloser Werte ist kürzer als die kürzeste Dauer der Regel "
              "({minimum:g} Tage) – für die Bewertung nicht gültig: kein Faktor, keine Skalierung mit dieser Messung."},
    "pq.not_valid": {
        "en": "The PQ measurement is not valid for the assessment ({days:.1f} days of gapless values, shortest duration "
              "of the rule {minimum:g} days) – no scaling and no forecast voltages from it.",
        "de": "Die PQ-Messung ist für die Bewertung nicht gültig ({days:.1f} Tage lückenloser Werte, kürzeste Dauer der "
              "Regel {minimum:g} Tage) – keine Skalierung und keine Prognosespannungen daraus."},
    "pq.max_gap_invalid": {
        "en": "max_gap_minutes must be a number ≥ 0 – got {value!r}.",
        "de": "max_gap_minutes muss eine Zahl ≥ 0 sein – erhalten: {value!r}."},
    "pq.factor_given": {
        "en": "Factor {factor:g} on the quantile (set; measurement over {days:.1f} days).",
        "de": "Faktor {factor:g} auf das Quantil (vorgegeben; Messung über {days:.1f} Tage)."},
    "pq.factor_none": {
        "en": "No factor on the quantile (measurement over {days:.1f} days) – set factor or factors if your rules "
              "require one for this duration.",
        "de": "Kein Faktor auf das Quantil (Messung über {days:.1f} Tage) – factor bzw. factors setzen, wenn die "
              "eigenen Regeln für diese Dauer einen verlangen."},
    "pq.factor_both": {
        "en": "Give either factor or factors, not both.",
        "de": "Entweder factor oder factors angeben, nicht beides."},
    # ---- assessment
    "pq.quantile_invalid": {
        "en": "quantile must lie between 0 and 1 (e.g. 0.95) – got {value!r}.",
        "de": "quantile muss zwischen 0 und 1 liegen (z. B. 0.95) – erhalten: {value!r}."},
    "pq.min_share_invalid": {
        "en": "min_share must lie between 0 (exclusive) and 1 – got {value!r}.",
        "de": "min_share muss größer als 0 und höchstens 1 sein – erhalten: {value!r}."},
    "pq.no_intervals": {
        "en": "No complete 10-min interval – no quantile.",
        "de": "Kein vollständiges 10-min-Intervall – kein Quantil."},
    "pq.ll_only": {
        "en": "Only line-to-line harmonic voltages: the orders of the zero sequence (3, 9, 15 …) are not contained; "
              "the quantiles are line-to-line values (reference 'LL' in the scaling and the forecast, test levels "
              "with pre_fault_levels(…, kind='LL')).",
        "de": "Nur Leiter-Leiter-Oberschwingungsspannungen: die Ordnungen des Nullsystems (3, 9, 15 …) sind nicht "
              "enthalten; die Quantile sind Leiter-Leiter-Werte (Bezug 'LL' bei Skalierung und Prognose, Pegel der "
              "Versuche mit pre_fault_levels(…, kind='LL'))."},
    "pq.gapless_less": {
        "en": "The longest stretch of gapless values covers {gapless:.1f} of the {span:.1f} days ({start} … {end}) – "
              "the duration of the rule is this stretch.",
        "de": "Die längste lückenlose Strecke umfasst {gapless:.1f} der {span:.1f} Tage ({start} … {end}) – für die "
              "Dauer der Regel zählt diese Strecke."},
    "pq.faults_excluded": {
        "en": "{n} 10-min intervals with an unbalanced fundamental (smallest line-to-earth voltage below {limit:.0%} "
              "of the largest: earth fault or voltage dip, e.g. {first}) are left out of the quantiles.",
        "de": "{n} 10-min-Intervalle mit unsymmetrischer Grundschwingung (kleinste Leiter-Erde-Spannung unter "
              "{limit:.0%} der größten: Erdschluss oder Spannungseinbruch, z. B. {first}) gehen nicht in die Quantile "
              "ein."},
    "pq.phases_missing": {
        "en": "The PQ measurement has only the phases {phases} – the largest phase per interval is taken from them.",
        "de": "Die PQ-Messung hat nur die Leiter {phases} – der größte Leiter je Intervall wird daraus bestimmt."},
    "pq.no_thd": {
        "en": "The PQ measurement has no THD (neither line-to-line nor from line-to-earth orders) – no scaling with "
              "the THD.",
        "de": "Die PQ-Messung hat keinen THD (weder Leiter-Leiter noch aus Leiter-Erde-Ordnungen) – keine "
              "Skalierung mit dem THD."},
    "pq.naive_clock": {
        "en": "The PQ time stamps have no time zone: the times of the tests ({timezone}) are compared with the "
              "instrument clock as they are – give the time zone of the instrument clock (timezone=…, PQ_TIMEZONE).",
        "de": "Die PQ-Zeitstempel haben keine Zeitzone: die Zeiten der Versuche ({timezone}) werden so, wie sie sind, "
              "mit der Geräteuhr verglichen – die Zeitzone der Geräteuhr angeben (timezone=…, PQ_TIMEZONE)."},
    "pq.gaps": {
        "en": "{n} gaps in the measurement, the longest {longest} ({start} … {end}).",
        "de": "{n} Lücken in der Messung, die längste {longest} ({start} … {end})."},
    "pq.dominant": {
        "en": "Order {order} ({f:.0f} Hz) dominates: {share:.0f} % of the harmonic voltage (largest phase, median).",
        "de": "Ordnung {order} ({f:.0f} Hz) dominiert: {share:.0f} % der Oberschwingungsspannung (größter Leiter, "
              "Median)."},
    "pq.no_ll_thd": {
        "en": "The PQ measurement has no line-to-line THD – it is formed from the line-to-earth orders of the export "
              "without the zero sequence (3, 9, 15 …), which a line-to-line voltage does not contain.",
        "de": "Die PQ-Messung hat keinen Leiter-Leiter-THD – er wird aus den Leiter-Erde-Ordnungen des Exports ohne "
              "das Nullsystem (3, 9, 15 …) gebildet, das eine Leiter-Leiter-Spannung nicht enthält."},
    # ---- comparability
    "pq.level_inside": {"en": "inside", "de": "innerhalb"},
    "pq.level_below": {"en": "below", "de": "darunter"},
    "pq.level_above": {"en": "above", "de": "darüber"},
    "pq.no_time_window": {
        "en": "time of the test unknown – percentile over the whole measurement only",
        "de": "Zeitpunkt des Versuchs unbekannt – Perzentil nur über die ganze Messung"},
    "pq.weekday_names": {"en": "Mon,Tue,Wed,Thu,Fri,Sat,Sun", "de": "Mo,Di,Mi,Do,Fr,Sa,So"},
    "pq.workdays": {"en": "Mon–Fri", "de": "Mo–Fr"},
    "report.title_pq_quantiles": {"en": "PQ measurement: quantiles per order", "de": "PQ-Messung: Quantile je Ordnung"},
    "report.title_pq_summary": {"en": "PQ measurement: characteristic values", "de": "PQ-Messung: Kennwerte"},
    "report.title_pq_tests": {"en": "Fault tests in the distribution of the PQ measurement",
                              "de": "Erdschlussversuche in der Verteilung der PQ-Messung"},
    "report.title_pq_scaling": {"en": "Residual current at Z_E with the PQ measurement",
                                "de": "Erdschlussreststrom an Z_E mit der PQ-Messung"},
    "pq.summary_line": {
        "en": "PQ measurement {start} … {end} ({days:.1f} days, {n} 10-min values, {completeness:.1f} % complete): "
              "quantile {q:g} of the largest phase per interval",
        "de": "PQ-Messung {start} … {end} ({days:.1f} Tage, {n} 10-min-Werte, {completeness:.1f} % vollständig): "
              "Quantil {q:g} des größten Leiters je Intervall"},
})

i18n.register_labels(columns={
    "U_quantile_V": "U_Quantil_V", "U_quantile_L1_V": "U_Quantil_L1_V", "U_quantile_L2_V": "U_Quantil_L2_V",
    "U_quantile_L3_V": "U_Quantil_L3_V", "U_quantile_L12_V": "U_Quantil_L12_V", "U_quantile_L23_V": "U_Quantil_L23_V",
    "U_quantile_L31_V": "U_Quantil_L31_V", "U_assessment_V": "U_Bewertung_V", "U_median_V": "U_Median_V",
    "U_max_V": "U_max_V", "share_of_U1_pct": "Anteil_U1_Proz", "n_intervals": "n_Intervalle",
    "share_of_UH_pct": "Anteil_UH_Proz", "test": "Versuch", "U_test_V": "U_Versuch_V",
    "percentile_all": "Perzentil_gesamt", "percentile_window": "Perzentil_Zeitfenster", "window": "Zeitfenster",
    "window_min_V": "Fenster_min_V", "window_max_V": "Fenster_max_V", "n_window": "n_Fenster",
    "position_in_range": "Lage_im_Bereich", "factor_to_test": "Faktor_zu_Versuch", "weekday": "Wochentag", "hour": "Stunde",
    "median_V": "Median_V", "P95_V": "P95_V", "quantity": "Groesse", "value": "Wert", "unit": "Einheit",
    "IH_A": "IH_A", "IRES_A": "IRES_A", "IRES_assessed_A": "IRES_Bewertung_A", "method": "Methode",
}, values={"position_in_range": {"inside": "innerhalb", "below": "darunter", "above": "darüber"}})


# ============================================================================================== data
@dataclass
class PQData:
    """Time series of a power-quality measurement of a busbar.

    Attributes
    ----------
    harmonics : pandas.DataFrame
        Harmonic voltages in V: index = time stamps (end of each interval), columns = MultiIndex (``order``,
        ``phase``) with the phases ``L1``, ``L2``, ``L3`` (line-to-earth) and/or ``L12``, ``L23``, ``L31``
        (line-to-line); order 1 is the fundamental component.
    thd : pandas.DataFrame
        THD in % per phase or loop (columns ``L12``, ``L23``, ``L31`` and/or ``L1``, ``L2``, ``L3``, ``NE``).
    rms : pandas.DataFrame
        RMS voltages in V (columns ``L12``, ``L23``, ``L31``, ``L1``, ``L2``, ``L3``, ``NE`` as exported).
    interval_s : float
        Length of an interval in s (30 s, 600 s for 10-min values …).
    meta : dict
        Instrument, serial number, measurement, files, nominal voltage, time zone, aggregation.
    maxima : pandas.DataFrame
        Largest harmonic voltage within each interval (columns as ``harmonics``), if exported.
    hints : list of str
        Hints of reading and aggregating (duplicates, gaps, columns not used …).
    """
    harmonics: pd.DataFrame
    thd: pd.DataFrame = field(default_factory=pd.DataFrame)
    rms: pd.DataFrame = field(default_factory=pd.DataFrame)
    interval_s: float = float("nan")
    meta: Dict[str, Any] = field(default_factory=dict)
    maxima: pd.DataFrame = field(default_factory=pd.DataFrame)
    hints: List[str] = field(default_factory=list)

    @property
    def orders(self) -> List[int]:
        """Harmonic orders contained (sorted, including the fundamental 1 if present)."""
        return sorted({int(m) for m in self.harmonics.columns.get_level_values(0)}) if len(self.harmonics.columns) else []

    @property
    def phases(self) -> List[str]:
        """Phases of the harmonic voltages (``L1`` … ``L31``) in the order L-E before L-L."""
        have = set(self.harmonics.columns.get_level_values(1)) if len(self.harmonics.columns) else set()
        return [p for p in PHASES_LE + PHASES_LL if p in have]

    @property
    def reference(self) -> str:
        """``"LE"`` if line-to-earth harmonic voltages are contained, otherwise ``"LL"``."""
        return "LE" if any(p in PHASES_LE for p in self.phases) else "LL"

    @property
    def start(self) -> pd.Timestamp:
        """Beginning of the first interval (first time stamp minus one interval)."""
        return self.harmonics.index[0] - pd.Timedelta(seconds=float(self.interval_s))

    @property
    def end(self) -> pd.Timestamp:
        """End of the last interval (last time stamp)."""
        return self.harmonics.index[-1]

    @property
    def span_days(self) -> float:
        """Duration of the measurement in days: from the beginning of the first to the end of the last interval."""
        if len(self.harmonics) == 0:
            return 0.0
        return float((self.end - self.start) / pd.Timedelta(days=1))

    def voltages(self, order: int, reference: Optional[str] = None) -> pd.DataFrame:
        """The phases of one order (columns = phases; line-to-earth if contained, otherwise line-to-line)."""
        ref = reference or self.reference
        phases = PHASES_LE if ref == "LE" else PHASES_LL
        cols = [(order, p) for p in phases if (order, p) in self.harmonics.columns]
        df = self.harmonics[cols].copy()
        df.columns = [p for _, p in cols]
        return df

    def largest(self, order: int, reference: Optional[str] = None) -> pd.Series:
        """Per interval the largest of the phases (``reference`` ``"LE"``) or loops (``"LL"``) of one order."""
        df = self.voltages(order, reference)
        return df.max(axis=1, skipna=True).rename(order)

    def coverage(self, max_gap_minutes: float = 0.0) -> Dict[str, Any]:
        """Start, end, duration, number of intervals, completeness, gaps and the longest gapless stretch of the
        measurement.

        Parameters
        ----------
        max_gap_minutes : float, optional
            Gaps up to this length do not interrupt a gapless stretch (0 = every missing interval interrupts it,
            default); the time of such a gap does not count as covered.

        Returns
        -------
        dict
            ``start``, ``end``, ``span_days``, ``interval_s``, ``n`` (intervals with values), ``n_expected``
            (intervals of the period), ``completeness`` (n/n_expected), ``gaps`` (list of (start, end) of the missing
            periods), ``covered_days`` (n·interval in days: the duration covered by values) and the longest stretch
            without a gap: ``gapless_days`` (its covered time in days), ``gapless_start``, ``gapless_end``.
        """
        idx = self.harmonics.index
        if len(idx) == 0:
            return dict(start=None, end=None, span_days=0.0, interval_s=self.interval_s, n=0, n_expected=0,
                        completeness=float("nan"), gaps=[], covered_days=0.0, gapless_days=0.0, gapless_start=None,
                        gapless_end=None)
        step = pd.Timedelta(seconds=float(self.interval_s))
        n_expected = int(round((self.end - self.start) / step))
        uniq = idx.unique().sort_values()
        d = uniq[1:] - uniq[:-1]
        gaps = [(uniq[i], uniq[i + 1] - step) for i in np.flatnonzero(d > step * 1.5)]
        # longest gapless stretch: consecutive time stamps at most one interval (plus the tolerated gap) apart
        cut = np.flatnonzero(d > step * 1.5 + pd.Timedelta(minutes=float(max_gap_minutes)))
        first = np.r_[0, cut + 1]
        last = np.r_[cut, len(uniq) - 1]
        size = last - first + 1
        j = int(np.argmax(size))
        return dict(start=self.start, end=self.end, span_days=self.span_days, interval_s=float(self.interval_s),
                    n=int(len(uniq)), n_expected=n_expected,
                    completeness=float(len(uniq) / n_expected) if n_expected else float("nan"), gaps=gaps,
                    covered_days=float(len(uniq) * float(self.interval_s) / 86400.0),
                    gapless_days=float(size[j] * float(self.interval_s) / 86400.0),
                    gapless_start=uniq[first[j]] - step, gapless_end=uniq[last[j]])

    def select(self, start=None, end=None) -> "PQData":
        """The intervals with time stamps in ``[start, end]`` (either bound may be None; naive bounds are in the time
        zone of the measurement)."""
        tz = self.harmonics.index.tz

        def bound(t):
            t = pd.Timestamp(t)
            if tz is not None and t.tzinfo is None:
                return t.tz_localize(tz)
            if tz is None and t.tzinfo is not None:
                return t.tz_localize(None)
            return t

        def cut(df):
            if df is None or len(df) == 0:
                return df
            m = np.ones(len(df), bool)
            if start is not None:
                m &= df.index >= bound(start)
            if end is not None:
                m &= df.index <= bound(end)
            return df[m]
        return replace(self, harmonics=cut(self.harmonics), thd=cut(self.thd), rms=cut(self.rms),
                       maxima=cut(self.maxima), hints=list(self.hints), meta=dict(self.meta))


# ============================================================================================== columns
_PHASE_TOKENS = {"L1": "L1", "UL1": "L1", "L1N": "L1", "L1E": "L1", "L2": "L2", "UL2": "L2", "L2N": "L2",
                 "L2E": "L2", "L3": "L3", "UL3": "L3", "L3N": "L3", "L3E": "L3", "L12": "L12", "U12": "L12",
                 "12": "L12", "L23": "L23", "U23": "L23", "23": "L23", "L31": "L31", "U31": "L31", "31": "L31",
                 "NE": "NE", "UNE": "NE", "N": "NE"}


def _tokens(name: str) -> List[str]:
    s = str(name).strip()
    s = re.sub(r"\[(.*?)\]", lambda m: "_[" + m.group(1) + "]", s)
    return [t for t in re.split(r"[_\s]+", s) if t]


def parse_column(name: Any) -> Optional[Tuple[str, Optional[int], str, str, str]]:
    """Meaning of a column name of a PQ export: (kind, order, phase, statistic, unit) or None.

    ``kind`` is ``"harmonic"`` (order ≥ 1), ``"thd"`` or ``"rms"``; ``phase`` one of ``L1`` … ``L31``, ``NE``;
    ``statistic`` ``"value"``, ``"max"`` or ``"min"``; ``unit`` ``"V"`` or ``"%"``. Recognised are the columns of
    WinPQ (``H5_UL1_[V]``, ``H5_UL1_max_[V]``, ``U12_[V]``, ``THD12_[%]``, ``UNE_[V]``) and short forms
    (``H5_L1``, ``U_H5_L1``, ``THD_L12``, ``U_L12``).
    """
    if isinstance(name, tuple):
        return None
    toks = _tokens(name)
    if not toks:
        return None
    unit = "V"
    stat = "value"
    kind, order, phase = None, None, None
    rest = []
    for t in toks:
        u = t.upper()
        if u in ("[V]", "V", "[KV]"):
            unit = "V" if u != "[KV]" else "kV"
        elif u in ("[%]", "%", "PCT"):
            unit = "%"
        elif u in ("MAX", "MAXIMUM"):
            stat = "max"
        elif u in ("MIN", "MINIMUM"):
            stat = "min"
        elif u in ("AVG", "MEAN", "MITTEL"):
            pass
        else:
            rest.append(u)
    for u in rest:
        m = re.fullmatch(r"H(\d{1,2})", u)
        if m and order is None:
            order = int(m.group(1)); kind = "harmonic"; continue
        m = re.fullmatch(r"THD(?:U)?(L[123]|L?12|L?23|L?31|NE|UNE|N)?", u)
        if m:
            kind = "thd"
            if m.group(1):
                phase = _PHASE_TOKENS.get(m.group(1), _PHASE_TOKENS.get("L" + m.group(1)))
            continue
        if u in _PHASE_TOKENS and phase is None:
            phase = _PHASE_TOKENS[u]; continue
        if u == "U":
            continue
        m = re.fullmatch(r"U(L[123]|12|23|31|NE)", u)
        if m and phase is None:
            phase = _PHASE_TOKENS["U" + m.group(1)] if ("U" + m.group(1)) in _PHASE_TOKENS else _PHASE_TOKENS[m.group(1)]
            if kind is None:
                kind = "rms"
            continue
        return None                                     # an unknown token: not a voltage column of interest
    if phase is None:
        return None
    if kind is None:
        kind = "rms"
    if kind == "rms" and unit == "%":
        return None
    if kind == "thd":
        unit = "%"
    return kind, order, phase, stat, unit


# ============================================================================================== reading
_TIME_FORMATS = ("%d.%m.%Y %H:%M:%S.%f", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S.%f",
                 "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S",
                 "%m/%d/%Y %H:%M:%S.%f", "%m/%d/%Y %H:%M:%S")


def _parse_times(values: pd.Series, source: str) -> pd.DatetimeIndex:
    s = values.astype(str).str.strip()
    for fmt in _TIME_FORMATS:
        try:
            return pd.DatetimeIndex(pd.to_datetime(s, format=fmt))
        except (ValueError, TypeError):
            continue
    try:
        return pd.DatetimeIndex(pd.to_datetime(s, dayfirst=True))
    except (ValueError, TypeError):
        raise ValueError(tr("pq.no_time", source=source, values=list(s[:3]))) from None


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")                 # pragma: no cover


def _interval_from_text(text: str) -> Optional[float]:
    m = re.search(r"([\d.,]+)\s*(ms|msec|s|sec|sek|min|h|std)\b", text.strip(), re.I)
    if not m:
        return None
    x = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    return x * {"ms": 1e-3, "msec": 1e-3, "s": 1.0, "sec": 1.0, "sek": 1.0, "min": 60.0, "h": 3600.0,
                "std": 3600.0}[unit]


def _localize(df: pd.DataFrame, timezone: Optional[str], source: str, hints: List[str]) -> pd.DataFrame:
    """Localise naive time stamps to ``timezone`` in the order of the file (the repeated hour at the end of daylight
    saving time is told apart by its order), then sort. Time stamps that cannot be assigned – the hour skipped at
    the beginning of daylight saving time, or a repeated hour out of order – are left out with a hint."""
    if timezone is None:
        return df.sort_index(kind="stable")
    if df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_convert(timezone)
        return df.sort_index(kind="stable")
    try:
        idx = df.index.tz_localize(timezone, ambiguous="infer", nonexistent="NaT")
    except Exception:                                               # e.g. a repeated hour out of order
        idx = df.index.tz_localize(timezone, ambiguous="NaT", nonexistent="NaT")
    df = df.copy()
    df.index = idx
    bad = df.index.isna()
    if bad.any():
        hints.append(tr("pq.dst_dropped", source=source, n=int(bad.sum()), timezone=timezone))
        df = df[~bad]
    return df.sort_index(kind="stable")


def _frame_to_data(df: pd.DataFrame, source: str, interval_s: Optional[float], meta: Dict[str, Any],
                   hints: List[str]) -> PQData:
    """Sort the columns of a DataFrame with a time index into harmonics, maxima, THD and RMS values."""
    harm, harm_pct, maxima, thd, rms = {}, {}, {}, {}, {}
    ignored = []
    for c in df.columns:
        p = c if isinstance(c, tuple) else parse_column(c)
        if isinstance(c, tuple) and len(c) == 2:                     # (order, phase) of a prepared frame
            try:
                harm[(int(c[0]), _PHASE_TOKENS.get(str(c[1]).upper(), str(c[1])))] = df[c]
            except (TypeError, ValueError):
                ignored.append(str(c))
            continue
        if p is None:
            ignored.append(str(c)); continue
        kind, order, phase, stat, unit = p
        values = pd.to_numeric(df[c], errors="coerce")
        if unit == "kV":
            values = values * 1000.0
        if kind == "harmonic":
            if phase == "NE" or stat == "min":
                ignored.append(str(c)); continue
            target = maxima if stat == "max" else (harm_pct if unit == "%" else harm)
            target[(order, phase)] = values
        elif kind == "thd":
            if stat != "value":
                ignored.append(str(c)); continue
            thd[phase] = values
        else:
            if stat != "value":
                ignored.append(str(c)); continue
            rms[phase] = values
    missing_fundamental = sorted({ph for (m, ph) in harm_pct if (1, ph) not in harm})
    for (m, ph), v in harm_pct.items():
        if (1, ph) in harm:
            harm[(m, ph)] = v / 100.0 * harm[(1, ph)]
    if missing_fundamental:
        hints.append(tr("pq.percent_without_fundamental", source=source, phases=", ".join(missing_fundamental)))
    if not [k for k in harm if k[0] >= 2]:
        raise ValueError(tr("pq.no_harmonics", source=source, columns=[str(c) for c in df.columns][:12]))
    if ignored:
        hints.append(tr("pq.ignored_columns", source=source, n=len(ignored), examples=", ".join(ignored[:4])))

    def frame(d, multi):
        if not d:
            return pd.DataFrame(index=df.index)
        out = pd.DataFrame(d, index=df.index)
        if multi:
            out.columns = pd.MultiIndex.from_tuples(list(d), names=["order", "phase"])
            out = out[sorted(out.columns, key=lambda k: (k[0], (PHASES_LE + PHASES_LL).index(k[1])
                                                         if k[1] in PHASES_LE + PHASES_LL else 99))]
        return out.astype(float)
    H = frame(harm, True)
    empty = [c for c in H.columns if not H[c].notna().any()]
    if empty and len(empty) < len(H.columns):
        hints.append(tr("pq.empty_columns", source=source, n=len(empty),
                        examples=", ".join("H%d_%s" % c for c in empty[:4])))
        H = H.drop(columns=empty)
    d = H.index.to_series().diff().dropna().dt.total_seconds()
    d = d[d > 0]
    step = float(d.median()) if len(d) else float("nan")
    if interval_s is None or not np.isfinite(interval_s):
        interval_s = step
    elif np.isfinite(step) and abs(step - interval_s) > 0.01 * interval_s:
        hints.append(tr("pq.interval_header_mismatch", source=source, header=float(interval_s), step=step))
        interval_s = step
    if not np.isfinite(interval_s) or interval_s <= 0:
        raise ValueError(tr("pq.interval_unknown", source=source))
    dup = H.index.duplicated()
    if dup.any():
        hints.append(tr("pq.duplicate_stamps", source=source, n=int(dup.sum()), first=H.index[dup][0]))
    return PQData(harmonics=H, thd=frame(thd, False), rms=frame(rms, False), interval_s=float(interval_s),
                  meta=meta, maxima=frame(maxima, True), hints=hints)


def from_frame(frame: pd.DataFrame, interval_s: Optional[float] = None, timezone: Optional[str] = None,
               meta: Optional[Mapping[str, Any]] = None) -> PQData:
    """A PQ measurement from a pandas DataFrame (exports of other instruments, read with pandas).

    Parameters
    ----------
    frame : pandas.DataFrame
        Index: time stamps (end of each interval) – or a column ``time``/``timestamp``. Columns: harmonic voltages
        per order and phase (``H5_L1``, ``H5_UL1_[V]``, ``U_H5_L12`` … or a MultiIndex (order, phase)), optionally
        THD (``THD_L12``, ``THD12_[%]`` …) and RMS values (``U_L12``, ``U12_[V]`` …). Harmonic voltages in % of the
        fundamental (``H5_L1_[%]``) are converted with the fundamental ``H1`` of the same phase.
    interval_s : float, optional
        Interval in s (default: the median step of the time stamps).
    timezone : str, optional
        Time zone of naive time stamps (e.g. ``"Europe/Berlin"``) – needed to compare with a recording whose
        time is UTC and around a clock change of daylight saving time.
    meta : mapping, optional
        Description (instrument, measurement …).

    Returns
    -------
    PQData

    Raises
    ------
    ValueError
        If the time stamps cannot be read or no harmonic voltage is found.
    """
    df = frame.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        tcol = next((c for c in df.columns if str(c).strip().lower() in ("time", "timestamp", "zeit", "datetime")),
                    None)
        if tcol is None:
            raise ValueError(tr("pq.no_time", source="DataFrame", values=list(df.index[:3])))
        df.index = _parse_times(df[tcol], "DataFrame")
        df = df.drop(columns=[tcol])
    m = dict(meta or {})
    m.setdefault("source", "DataFrame")
    m["timezone"] = timezone
    hints: List[str] = []
    df = _localize(df, timezone, m["source"], hints)
    return _frame_to_data(df, m["source"], interval_s, m, hints)


def read_winpq(path: str, timezone: Optional[str] = None) -> PQData:
    """Read a CSV export of *WinPQ mobil* (A. Eberle, instruments *PQ-Box*).

    The export starts with lines of metadata (instrument and serial number, ``Messung:``/measurement, ``Intervall:``
    /interval, ``Spannung:``/nominal voltage of the instrument, ``Datum/Zeit:``/period), followed by the header row
    ``Datum,Zeit,…`` and one row per interval. Columns used: harmonic voltages per order and phase
    ``H<m>_UL<k>_[V]`` (mean value of the interval) and ``H<m>_UL<k>_max_[V]`` (largest value in the interval),
    RMS values ``U12_[V]`` …, ``UNE_[V]`` and THD ``THD12_[%]`` …. Comma or semicolon as separator, decimal point
    or comma, UTF-8 or Windows encoding are recognised.

    Parameters
    ----------
    path : str
        CSV file.
    timezone : str, optional
        Time zone of the instrument clock (e.g. ``"Europe/Berlin"``); default: naive local time as exported.

    Returns
    -------
    PQData
        ``meta`` with ``instrument``, ``serial``, ``measurement``, ``interval_text``, ``nominal_voltage_V`` (setting of
        the instrument, usually secondary), ``period_text``, ``file`` and ``md5``.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If no header row, no readable time stamps or no harmonic voltages are found.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(tr("pq.file_missing", path=path))
    with open(path, "rb") as f:
        raw = f.read()
    text = _decode(raw)
    lines = text.splitlines()
    header = None
    for i, line in enumerate(lines):
        first = re.split(r"[;,\t]", line.strip(), maxsplit=1)[0].strip().strip('"').lower()
        if first in ("datum", "date"):
            header = i
            break
    if header is None:
        raise ValueError(tr("pq.no_header", path=path))
    head = lines[header]
    sep = max((";", ",", "\t"), key=head.count)
    meta: Dict[str, Any] = dict(file=os.path.basename(path), path=os.path.abspath(path),
                                md5=hashlib.md5(raw).hexdigest(), format="winpq")
    interval = None
    for line in lines[:header]:
        s = line.strip()
        if not s:
            continue
        if "pq-box" in s.lower() or "messdaten" in s.lower() or "measurement data" in s.lower():
            parts = [p.strip() for p in re.split(r"[;,]", s) if p.strip()]
            meta["instrument"] = next((p.replace("Messdaten Export", "").replace("Measurement data export", "").strip()
                                       for p in parts if "pq" in p.lower()), parts[0] if parts else "")
            serial = re.search(r"(?:Seriennummer|Serial number|S/N)\s*:?\s*([\w\-/.]+)", s, re.I)
            if serial:
                meta["serial"] = serial.group(1)
            continue
        key, _, value = s.partition(":")
        k = key.strip().lower()
        v = value.strip().strip(",;").strip()
        if k in ("messung", "measurement"):
            meta["measurement"] = ", ".join(p.strip() for p in re.split(r"[,;]", v) if p.strip())
        elif k in ("intervall", "interval"):
            meta["interval_text"] = v
            interval = _interval_from_text(v)
        elif k in ("spannung", "voltage", "nennspannung", "nominal voltage"):
            meta["nominal_voltage_text"] = v
            m = re.search(r"([\d.,]+)\s*(k?V)", v)
            if m:
                meta["nominal_voltage_V"] = float(m.group(1).replace(",", ".")) * (1e3 if m.group(2) == "kV" else 1.0)
        elif k in ("datum/zeit", "date/time", "zeitraum", "period"):
            meta["period_text"] = re.sub(r"\s*,\s*", " ", v)
    body = "\n".join(lines[header:])
    sample = next((l for l in lines[header + 1:header + 50] if l.strip()), "")
    decimal = "," if sep == ";" and re.search(r"\d,\d", sample) else "."
    names = [c.strip().strip('"') for c in head.split(sep)]
    date_col = next(c for c in names if c.lower() in ("datum", "date"))
    time_col = next((c for c in names if c.lower() in ("zeit", "time", "uhrzeit")), None)
    df = pd.read_csv(io.StringIO(body), sep=sep, decimal=decimal, skipinitialspace=True,
                     dtype={c: str for c in (date_col, time_col) if c})
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all")
    stamps = df[date_col].astype(str).str.strip() + ((" " + df[time_col].astype(str).str.strip()) if time_col else "")
    ok = stamps.str.match(r"^\s*\d")
    df = df[ok.to_numpy()]
    stamps = stamps[ok]
    idx = _parse_times(stamps, meta["file"])
    df = df.drop(columns=[c for c in (date_col, time_col) if c])
    for c in df.columns:
        if df[c].dtype.kind not in "fiu":                          # text in a column (e.g. a marker): not a number
            s = df[c].astype(str)
            df[c] = pd.to_numeric(s.str.replace(",", ".") if decimal == "," else s, errors="coerce")
    df.index = idx
    hints: List[str] = []
    df = _localize(df, timezone, meta["file"], hints)
    meta["timezone"] = timezone
    meta["timestamps"] = "end"
    return _frame_to_data(df, meta["file"], interval, meta, hints)


def _is_winpq(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = _decode(f.read(4096)).lower()
    except OSError:
        return False
    return ("pq-box" in head or "messdaten export" in head or "measurement data export" in head
            or re.search(r"^\s*(datum|date)\s*[,;\t]\s*(zeit|time)", head, re.M) is not None)


def read(paths: Union[str, Sequence[str]], timezone: Optional[str] = None) -> PQData:
    """Read one or several exports of a PQ measurement and combine them in time.

    WinPQ exports are recognised by their header ([`read_winpq`][groundfault.pq.read_winpq]); other CSV files are read
    with pandas (time in the first column, one column per order and phase as in
    [`from_frame`][groundfault.pq.from_frame]). Files with identical content are read once, files with the same period
    used once, and overlapping periods keep the values of the earlier file (hints).

    Parameters
    ----------
    paths : str or sequence of str
        Export file(s).
    timezone : str, optional
        Time zone of the instrument clock (e.g. ``"Europe/Berlin"``).

    Returns
    -------
    PQData
        ``meta["files"]`` lists the files, ``hints`` names duplicates and overlaps.

    Raises
    ------
    ValueError
        Without a file, or if the exports have different intervals.
    """
    if isinstance(paths, (str, os.PathLike)):
        paths = [paths]
    paths = [str(p) for p in paths]
    if not paths:
        raise ValueError(tr("pq.no_files"))
    items, hints, seen = [], [], {}
    for p in paths:
        if not os.path.isfile(p):
            raise FileNotFoundError(tr("pq.file_missing", path=p))
        with open(p, "rb") as f:
            digest = hashlib.md5(f.read()).hexdigest()
        if digest in seen:
            hints.append(tr("pq.identical_file", file=os.path.basename(p), other=os.path.basename(seen[digest])))
            continue
        seen[digest] = p
        if _is_winpq(p):
            items.append(read_winpq(p, timezone=timezone))
        else:
            with open(p, "rb") as f:
                lines = _decode(f.read(65536)).splitlines()
            head = next((x for x in lines if x.strip()), "")
            sep = max((";", ",", "\t"), key=head.count)
            sample = next((x for x in lines[1:50] if x.strip()), "")
            decimal = "," if sep != "," and re.search(r"\d,\d", sample) else "."
            df = pd.read_csv(p, sep=sep, decimal=decimal, encoding_errors="replace")
            first = df.columns[0]
            df.index = _parse_times(df[first], os.path.basename(p))
            df = df.drop(columns=[first])
            items.append(from_frame(df, timezone=timezone, meta=dict(file=os.path.basename(p), source=os.path.basename(p),
                                                                     path=os.path.abspath(p), md5=digest)))
    out = combine(items)
    out.hints[:0] = hints
    return out


def combine(items: Sequence[PQData]) -> PQData:
    """Combine PQ measurements of the same busbar in time (e.g. several exports of one instrument).

    The time stamps are sorted; a time stamp that occurs in several items keeps the values of the first item that
    contains it. Items with the same time stamps (e.g. the same period exported twice) are named in a hint and used
    once, partial overlaps likewise.

    Parameters
    ----------
    items : sequence of PQData
        Measurements with the same interval.

    Returns
    -------
    PQData

    Raises
    ------
    ValueError
        Without an item, or for different intervals.
    """
    items = list(items)
    if not items:
        raise ValueError(tr("pq.no_files"))
    intervals = sorted({round(float(x.interval_s), 6) for x in items})
    if len(intervals) > 1:
        raise ValueError(tr("pq.interval_mismatch", intervals=", ".join("%g" % x for x in intervals)))
    if len(items) == 1:
        x = items[0]
        meta = dict(x.meta)
        meta.setdefault("files", [x.meta.get("file", x.meta.get("source", ""))])
        return replace(x, meta=meta, hints=list(x.hints))
    hints: List[str] = []
    name = lambda x, i: x.meta.get("file") or x.meta.get("source") or "#%d" % (i + 1)
    used: List[Tuple[pd.Index, str]] = []
    parts = {k: [] for k in ("harmonics", "thd", "rms", "maxima")}
    for i, x in enumerate(items):
        hints.extend(x.hints)
        idx = x.harmonics.index
        keep = np.ones(len(idx), bool)
        for other_idx, other_name in used:
            common = idx.isin(other_idx)
            if common.all() and len(idx) == len(other_idx):
                hints.append(tr("pq.same_period", file=name(x, i), other=other_name, n=len(idx), start=idx[0],
                                end=idx[-1]))
            elif common.any():
                hints.append(tr("pq.overlap", file=name(x, i), other=other_name, n=int(common.sum())))
            keep &= ~common
        used.append((idx, name(x, i)))
        if not keep.any():
            continue
        for k in parts:
            df = getattr(x, k)
            if df is not None and len(df):
                parts[k].append(df[keep])
    out = {k: (pd.concat(v).sort_index(kind="stable") if v else pd.DataFrame()) for k, v in parts.items()}
    first = items[0]
    meta = dict(first.meta)
    meta["files"] = [name(x, i) for i, x in enumerate(items)]
    meta["measurements"] = list(dict.fromkeys(x.meta.get("measurement", "") for x in items if x.meta.get("measurement")))
    return PQData(harmonics=out["harmonics"], thd=out["thd"], rms=out["rms"], interval_s=float(first.interval_s),
                  meta=meta, maxima=out["maxima"], hints=hints)


# ============================================================================================== 10-min values
def _aggregate(df: pd.DataFrame, rule: str, how: str, label: str) -> Tuple[pd.DataFrame, pd.Series]:
    if df is None or len(df) == 0 or len(df.columns) == 0:
        return pd.DataFrame(), pd.Series(dtype=float)
    closed = "right" if label == "end" else "left"
    lab = "right" if label == "end" else "left"
    grouper = pd.Grouper(freq=rule, closed=closed, label=lab)
    if how == "rms":
        agg = np.sqrt((df ** 2).groupby(grouper).mean())
    elif how == "max":
        agg = df.groupby(grouper).max()
    else:
        agg = df.groupby(grouper).mean()
    count = df.notna().any(axis=1).groupby(grouper).sum()      # a short interval with values (columns may be empty)
    return agg, count


def ten_minute_values(data: PQData, minutes: float = 10.0, how: str = "rms", min_share: float = 1.0,
                      label: str = "end") -> PQData:
    """10-min values (or another aggregation period) from shorter intervals.

    The intervals are aligned to the clock (00:00, 00:10 …). An aggregated value is the square root of the mean of
    the squares of the shorter values (``how="rms"``, as in IEC 61000-4-30) or their arithmetic mean
    (``"mean"``); the maxima are the largest value. An interval with fewer than ``min_share`` of its values (a
    short interval without any value counts as missing) is left out.

    Parameters
    ----------
    data : PQData
        Measurement with an interval that divides the aggregation period (e.g. 3 s, 30 s, 1 min).
    minutes : float, optional
        Aggregation period in minutes.
    how : {"rms", "mean"}, optional
        Aggregation of the values.
    min_share : float, optional
        Share of the values an interval needs (1.0 = all, default).
    label : {"end", "start"}, optional
        What the time stamps of ``data`` mark: the end (default, as in the exports) or the beginning of each
        interval. The result is always labelled with the end of each interval (the convention of this module).

    Returns
    -------
    PQData
        Interval ``60·minutes`` s; ``meta["aggregation"]`` = dict(source_interval_s, how, per, min_share, n_total,
        n_incomplete). A measurement with this interval already is returned unchanged.

    Raises
    ------
    ValueError
        If the interval of ``data`` is longer than the period or does not divide it, or for an invalid option.
    """
    check_option("how", how, _HOW)
    check_option("label", label, _LABELS)
    target = 60.0 * float(minutes)
    dt = float(data.interval_s)
    if label == "start":                    # time stamps at the beginning → the end of each interval
        shift = pd.Timedelta(seconds=dt)

        def moved(df):
            if df is None or len(df) == 0:
                return df
            df = df.copy()
            df.index = df.index + shift
            return df
        data = replace(data, harmonics=moved(data.harmonics), thd=moved(data.thd), rms=moved(data.rms),
                       maxima=moved(data.maxima), meta=dict(data.meta, timestamps="end"), hints=list(data.hints))
        label = "end"
    if abs(dt - target) < 1e-6:
        return data
    if dt > target + 1e-6:
        raise ValueError(tr("pq.interval_too_long", interval=dt, target=target))
    per = target / dt
    if abs(per - round(per)) > 1e-6:
        raise ValueError(tr("pq.interval_not_divisor", interval=dt, target=target))
    per = int(round(per))
    if not (0 < float(min_share) <= 1.0):
        raise ValueError(tr("pq.min_share_invalid", value=min_share))
    rule = "%gmin" % minutes
    H, count = _aggregate(data.harmonics, rule, how, label)
    need = int(math.ceil(float(min_share) * per - 1e-9))
    ok = count.reindex(H.index).fillna(0) >= need
    n_bad = int((~ok).sum())
    # intervals of the clock without any value (gaps) are not intervals of the measurement
    present = count.reindex(H.index).fillna(0) > 0
    n_bad_present = int((~ok & present).sum())
    hints = list(data.hints)
    hints.append(tr("pq.aggregated", per=per, interval=dt, how=tr("pq.how_" + how)))
    if n_bad_present:
        hints.append(tr("pq.incomplete_dropped", n=n_bad_present, total=int(present.sum()), need=need, per=per))
    keep = H.index[ok.to_numpy()]
    thd = _aggregate(data.thd, rule, how, label)[0]
    rms = _aggregate(data.rms, rule, how, label)[0]
    mx = _aggregate(data.maxima, rule, "max", label)[0]
    sel = lambda df: df.reindex(keep) if len(df) else df
    meta = dict(data.meta)
    meta["aggregation"] = dict(source_interval_s=dt, how=how, per=per, min_share=float(min_share),
                               n_total=int(present.sum()), n_incomplete=n_bad_present, n_empty=n_bad - n_bad_present)
    return PQData(harmonics=H.loc[keep], thd=sel(thd), rms=sel(rms), interval_s=target, meta=meta, maxima=sel(mx),
                  hints=hints)


# ============================================================================================== factor
def _check_rule(factors) -> Dict[float, float]:
    try:
        rule = {float(k): float(v) for k, v in dict(factors).items()}
    except (TypeError, ValueError):
        raise ValueError(tr("pq.factor_rule_invalid", value=factors)) from None
    if not rule or any(not (math.isfinite(k) and k > 0 and math.isfinite(v) and v > 0) for k, v in rule.items()):
        raise ValueError(tr("pq.factor_rule_invalid", value=factors))
    return rule


def duration_factor(days: float, factors: Mapping[float, float]) -> Tuple[float, str, bool]:
    """Factor on the quantile from the duration of the measurement and a rule of the user.

    Parameters
    ----------
    days : float
        Duration of the measurement in days – in [`assess`][groundfault.pq.assess] the longest stretch of gapless
        values (``PQData.coverage()["gapless_days"]``).
    factors : mapping
        Rule ``{minimum duration in days: factor}``: the factor of the longest minimum duration the measurement
        reaches applies – e.g. ``{D_long: 1.0, D_short: k}`` gives 1.0 from ``D_long`` days on and ``k`` from
        ``D_short`` days on. A measurement shorter than every duration of the rule is not valid. groundfault contains
        no such rule; take it from your operator's specification or the applicable standard.

    Returns
    -------
    (float, str, bool)
        The factor, a hint text and ``True`` if the measurement reaches a duration of the rule – ``False``: shorter
        than every duration, not valid (the factor is NaN).

    Raises
    ------
    ValueError
        For a rule that does not map positive durations to positive factors.

    Examples
    --------
    >>> duration_factor(40.0, {360.0: 1.0, 20.0: 1.5})[0]       # invented rule
    1.5
    >>> duration_factor(400.0, {360.0: 1.0, 20.0: 1.5})[0]
    1.0
    >>> duration_factor(10.0, {360.0: 1.0, 20.0: 1.5})[2]       # shorter than every duration: not valid
    False
    """
    rule = _check_rule(factors)
    reached = [d for d in rule if days + 1e-9 >= d]
    if reached:
        d = max(reached)
        return rule[d], tr("pq.factor_from_rule", days=days, minimum=d, factor=rule[d]), True
    return float("nan"), tr("pq.factor_too_short", days=days, minimum=min(rule)), False


# ============================================================================================== assessment
def _check_quantile(q) -> float:
    try:
        q = float(q)
    except (TypeError, ValueError):
        raise ValueError(tr("pq.quantile_invalid", value=q)) from None
    if not (0.0 < q < 1.0) or isinstance(q, bool):
        raise ValueError(tr("pq.quantile_invalid", value=q))
    return q


def _thd_le(data: PQData, zero: bool = True) -> pd.DataFrame:
    """THD of the line-to-earth voltages from the orders of the export (2 … highest), per phase in %; without the
    orders of the zero sequence (``zero=False``) the line-to-line equivalent."""
    out = {}
    for ph in PHASES_LE:
        if (1, ph) not in data.harmonics.columns:
            continue
        cols = [(m, ph) for m in data.orders if m >= 2 and (zero or m % 3) and (m, ph) in data.harmonics.columns]
        if not cols:
            continue
        uh = np.sqrt((data.harmonics[cols] ** 2).sum(axis=1, min_count=1))
        out[ph] = 100.0 * uh / data.harmonics[(1, ph)]
    return pd.DataFrame(out)


def _uh_ll(data: PQData) -> pd.DataFrame:
    """Harmonic voltage of the loops in V: U_H = U·THD/√(1 + THD²) from RMS value and THD."""
    out = {}
    for ph in PHASES_LL:
        if ph in data.thd.columns and ph in data.rms.columns:
            t = data.thd[ph] / 100.0
            out[ph] = data.rms[ph] * t / np.sqrt(1.0 + t ** 2)
    return pd.DataFrame(out)


def _weekday_names() -> List[str]:
    return tr("pq.weekday_names").split(",")


@dataclass
class PQAssessment:
    """Quantiles of a PQ measurement for the assessment ([`assess`][groundfault.pq.assess]).

    Attributes
    ----------
    quantile : float
        Quantile (e.g. 0.95).
    factor : float
        Factor on the quantile (1 = none; NaN if the measurement is not valid).
    factor_hint : str
        How the factor was chosen.
    factor_rule : dict or None
        The rule ``{minimum days: factor}`` used.
    valid : bool
        False if the gapless values are shorter than every duration of the rule: then the measurement is not used for
        the assessment – ``scaling``, ``settings``, ``voltages`` and ``series`` (with the factor) raise a ValueError.
    data : PQData
        The 10-min values.
    orders_table : pandas.DataFrame
        Per order: ``order``, ``f_Hz``, the quantile per phase (``U_quantile_L1_V`` …), of the largest phase per
        interval (``U_quantile_V``), the same times the factor (``U_assessment_V``), ``U_median_V``, ``U_max_V``,
        ``share_of_U1_pct`` (quantile of the order in % of the median of the fundamental), ``share_of_UH_pct``
        (median share of the order in the harmonic voltage of the largest phase) and ``n_intervals``.
    thd95_ll, thd95_le : float
        Quantile of the largest THD per interval in %: line-to-line loops (from the instrument; without them from
        the line-to-earth orders of the export without the zero sequence) and line-to-earth phases (from all orders
        of the export). NaN if not available.
    uh95_ll : float
        Quantile of the largest harmonic voltage of the loops in V (line-to-line, from RMS value and THD).
    coverage : dict
        See [`PQData.coverage`][groundfault.pq.PQData.coverage].
    f1 : float
        Nominal frequency in Hz (for ``f_Hz``).
    hints : list of str
    """
    quantile: float
    factor: float
    factor_hint: str
    factor_rule: Optional[Dict[float, float]]
    valid: bool
    data: PQData
    orders_table: pd.DataFrame
    thd95_ll: float
    thd95_le: float
    uh95_ll: float
    coverage: Dict[str, Any]
    f1: float = 50.0
    hints: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------------------------ values
    @property
    def reference(self) -> str:
        """``"LE"`` (line-to-earth harmonic voltages) or ``"LL"``."""
        return self.data.reference

    @property
    def dominant_order(self) -> Optional[int]:
        """Order with the largest quantile (above the fundamental)."""
        t = self.orders_table
        t = t[t["order"] >= 2]
        return int(t.loc[t["U_quantile_V"].idxmax(), "order"]) if len(t) else None

    def u95(self, factored: bool = False, orders: Optional[Iterable[int]] = None) -> Dict[int, float]:
        """Quantile per order in V – of the largest phase per interval (line-to-earth; with line-to-line data the
        largest loop).

        Parameters
        ----------
        factored : bool, optional
            Multiplied by ``factor``.
        orders : iterable of int, optional
            Orders (default: all ≥ 2).
        """
        t = self.orders_table.set_index("order")
        sel = [m for m in (orders if orders is not None else t.index) if m in t.index and m >= 2]
        k = self.factor if factored else 1.0
        return {int(m): float(t.loc[m, "U_quantile_V"]) * k for m in sel}

    def thd95(self, factored: bool = False) -> float:
        """Quantile of the line-to-line THD in % (largest loop per interval; NaN without a THD)."""
        return float(self.thd95_ll) * (self.factor if factored else 1.0)

    def _hint(self, text: str) -> None:
        if text not in self.hints:
            self.hints.append(text)

    def _require_valid(self) -> None:
        """ValueError if the measurement is not valid for the assessment (shorter than every duration of the rule)."""
        if not self.valid:
            rule = self.factor_rule or {}
            raise ValueError(tr("pq.not_valid", days=float(self.coverage.get("gapless_days", 0.0)),
                                minimum=min(rule) if rule else float("nan")))

    # ------------------------------------------------------------------------------------ use
    def scaling(self, thd_measured_percent: Optional[float] = None,
                orders: Optional[Iterable[int]] = None) -> Dict[str, Any]:
        """Keyword arguments of
        [`groundfault.equivalent_source.ires_at_impedance`][groundfault.equivalent_source.ires_at_impedance] (also
        ``scaling`` of [`groundfault.report.ires_over_ze`][groundfault.report.ires_over_ze] and
        [`groundfault.interactive.ires_ze`][groundfault.interactive.ires_ze]).

        Every order of the positive or negative sequence (5, 7, 11, 13 …) is scaled with its own factor
        U_95,m/U_level,m (``u95`` with the line-to-earth quantile of the largest phase – at least the magnitude of its
        sequence component, on the safe side); the factor of this assessment is passed as ``safety_factor``. With
        ``thd_measured_percent`` the THD quantile is added as the flat factor for these orders without their own
        value. The orders of the zero sequence and the even orders are not scaled.

        Parameters
        ----------
        thd_measured_percent : float, optional
            THD of the series of fault tests in % (line-to-line, e.g. the mean before/after the fault of the largest
            loop) for the flat THD factor.
        orders : iterable of int, optional
            Orders of ``u95`` (default: all).

        Returns
        -------
        dict
            ``u95``, ``u95_reference``, ``safety_factor`` and – with ``thd_measured_percent`` – ``thd95_percent``,
            ``thd_measured_percent``.

        Raises
        ------
        ValueError
            If the measurement is not valid (``valid`` is False).
        """
        self._require_valid()
        out = dict(u95=self.u95(False, orders), u95_reference="seq" if self.reference == "LE" else "LL",
                   safety_factor=float(self.factor))
        if thd_measured_percent is not None and np.isfinite(self.thd95()):
            out.update(thd95_percent=self.thd95(), thd_measured_percent=float(thd_measured_percent))
        elif thd_measured_percent is not None:
            self._hint(tr("pq.no_thd"))
        return out

    def settings(self) -> Dict[str, Any]:
        """Fields of [`groundfault.evaluation.Settings`][groundfault.evaluation.Settings] for the scaling of the
        harmonic content of a single test (``dataclasses.replace(settings, **a.settings())``): every order of the
        positive or negative sequence with its own quantile, the others of them with the THD; the zero sequence and
        the even orders are not scaled.

        Returns
        -------
        dict
            ``u_thd95_percent`` (quantile of the line-to-line THD, without the factor; None without a THD, with a
            hint), ``u_thd95_volt`` (None), ``pq_safety_factor``, ``pq_u95`` (quantile per order in V, without the
            factor) and ``pq_u95_reference`` (``"seq"`` for line-to-earth data, ``"LL"`` for line-to-line data).

        Raises
        ------
        ValueError
            If the measurement is not valid (``valid`` is False).
        """
        self._require_valid()
        thd = self.thd95()
        if not np.isfinite(thd):
            self._hint(tr("pq.no_thd"))
        return dict(u_thd95_percent=thd if np.isfinite(thd) else None, u_thd95_volt=None,
                    pq_safety_factor=float(self.factor), pq_u95=self.u95(False),
                    pq_u95_reference="seq" if self.reference == "LE" else "LL")

    def voltages(self, factored: bool = True, orders: Optional[Iterable[int]] = None) -> Dict[int, float]:
        """Harmonic voltages for the forecast ([`groundfault.forecast`][groundfault.forecast],
        ``NetworkModel.forecast(voltages, reference=a.reference)``): the quantile per order in V of the largest
        phase (line-to-earth) or loop (line-to-line data), times the factor (default; then a ValueError if the
        measurement is not valid)."""
        if factored:
            self._require_valid()
        return self.u95(factored, orders)

    def series(self, factored: bool = True,
               orders: Optional[Iterable[int]] = None) -> Union[Dict[str, pd.DataFrame], pd.DataFrame]:
        """The 10-min values for a forecast as a time series (times the factor by default – then a ValueError if the
        measurement is not valid; columns = orders): line-to-earth per phase ``{"L1": DataFrame, …}``;
        line-to-line data as one DataFrame of the largest loop per interval
        (``NetworkModel.forecast(series, reference=a.reference)``)."""
        if factored:
            self._require_valid()
        k = self.factor if factored else 1.0
        sel = [m for m in (orders if orders is not None else self.data.orders) if m >= 2]
        if self.reference == "LL":
            return pd.DataFrame({m: self.data.largest(m) * k for m in sel if m in self.data.orders})
        out = {}
        for ph in PHASES_LE:
            cols = [(m, ph) for m in sel if (m, ph) in self.data.harmonics.columns]
            if cols:
                df = self.data.harmonics[cols] * k
                df.columns = [m for m, _ in cols]
                out[ph] = df
        return out

    def largest(self, order: int, factored: bool = False) -> pd.Series:
        """10-min values of the largest phase of one order (V)."""
        return self.data.largest(order) * (self.factor if factored else 1.0)

    # ------------------------------------------------------------------------------------ tables
    def table(self) -> pd.DataFrame:
        """Quantiles per order (copy of ``orders_table``)."""
        return self.orders_table.copy()

    def summary_table(self) -> pd.DataFrame:
        """Characteristic values: period, duration, intervals, completeness, longest gapless stretch, quantile, factor,
        validity, THD and the dominant order."""
        c = self.coverage
        dom = self.dominant_order
        rows = [("start", c.get("start"), ""), ("end", c.get("end"), ""), ("span_days", c.get("span_days"), "d"),
                ("n_intervals", c.get("n"), ""), ("completeness_pct", 100 * c.get("completeness", np.nan), "%"),
                ("gapless_days", c.get("gapless_days"), "d"), ("quantile", self.quantile, ""),
                ("factor", self.factor, ""), ("valid", bool(self.valid), ""),
                ("THD_quantile_LL_pct", self.thd95_ll, "%"), ("THD_quantile_LE_pct", self.thd95_le, "%"),
                ("UH_quantile_LL_V", self.uh95_ll, "V")]
        if dom is not None:
            rows.append(("dominant_order", dom, ""))
            rows.append(("U_quantile_dominant_V", self.u95()[dom], "V"))
        return pd.DataFrame(rows, columns=["quantity", "value", "unit"])

    def summary(self) -> str:
        """One line: period, duration, number of 10-min values and completeness."""
        c = self.coverage
        return tr("pq.summary_line", start=c.get("start"), end=c.get("end"), days=c.get("span_days", 0.0),
                  n=c.get("n", 0), completeness=100 * c.get("completeness", float("nan")), q=self.quantile)

    def profile(self, order: Optional[int] = None, factored: bool = False) -> pd.DataFrame:
        """Weekly profile of one order (default: the dominant one): median and 95 % quantile of the largest phase per
        weekday and hour of the day (local time of the time stamps).

        Returns
        -------
        pandas.DataFrame
            ``weekday`` (0 = Monday), ``hour``, ``median_V``, ``P95_V``, ``n``.
        """
        order = self.dominant_order if order is None else int(order)
        s = self.largest(order, factored)
        # the time stamp marks the end of the interval: its beginning gives the hour it belongs to
        t = s.index - pd.Timedelta(seconds=float(self.data.interval_s))
        g = s.groupby([t.dayofweek, t.hour])
        out = pd.DataFrame({"median_V": g.median(), "P95_V": g.quantile(0.95), "n": g.size()})
        out.index.names = ["weekday", "hour"]
        return out.reset_index()

    def comparability(self, levels: Mapping[str, Mapping[int, float]],
                      times: Optional[Mapping[str, Any]] = None, orders: Optional[Iterable[int]] = None,
                      window_h: float = 1.0, times_timezone: Optional[str] = "UTC") -> pd.DataFrame:
        """Position of the pre-fault voltages of fault tests in the distribution of the PQ measurement.

        The scaling assumes that the network of the tests and of the PQ measurement are comparable (switching state,
        capacitances, transformer). A test level far outside the PQ values – e.g. above their maximum – points to a
        different state. A test level at a low percentile is normal when the test took place at a time of low
        harmonic voltage (night, weekend); the time window (the same time of the week, ± ``window_h`` hours around
        the time of the test) shows this.

        Parameters
        ----------
        levels : mapping
            ``{test: {order: U}}`` – pre-fault voltage of the largest phase in V with the reference of the PQ
            measurement (line-to-earth; for line-to-line data the largest loop), e.g. from
            [`pre_fault_levels`][groundfault.pq.pre_fault_levels] (``kind=a.reference``).
        times : mapping, optional
            ``{test: time}`` of the tests (e.g. the start of the recording).
        orders : iterable of int, optional
            Orders (default: those of ``levels`` with a PQ quantile).
        window_h : float, optional
            Half width of the time window in hours.
        times_timezone : str or None, optional
            Time zone of naive ``times`` (default ``"UTC"``, the time base of most recorders); converted into the
            time zone of the PQ measurement if it has one. None: same clock as the PQ measurement.

        Returns
        -------
        pandas.DataFrame
            ``test``, ``order``, ``U_test_V``, ``percentile_all`` (share of the 10-min values below the test level in
            %), ``window`` (weekday and hours), ``percentile_window``, ``window_min_V``, ``window_max_V``,
            ``n_window``, ``position_in_range`` (``inside``/``below``/``above`` the range of the whole measurement) and
            ``factor_to_test`` (quantile/test level). ``attrs["hints"]``: e.g. that the PQ clock has no time zone.
        """
        rows, hints = [], []
        tz = self.data.harmonics.index.tz
        names = _weekday_names()
        for test, lv in levels.items():
            t0 = None
            if times is not None and times.get(test) is not None:
                t0 = pd.Timestamp(times[test])
                if tz is None and times_timezone is not None and not hints:
                    hints.append(tr("pq.naive_clock", timezone=times_timezone))
                if t0.tzinfo is None and times_timezone is not None and tz is not None:
                    t0 = t0.tz_localize(times_timezone).tz_convert(tz)
                elif t0.tzinfo is not None and tz is None:
                    t0 = t0.tz_convert(None) if times_timezone is None else t0.tz_convert(times_timezone).tz_localize(None)
                elif t0.tzinfo is not None and tz is not None:
                    t0 = t0.tz_convert(tz)
            for m in sorted(int(x) for x in lv):
                if orders is not None and m not in set(orders):
                    continue
                if m not in self.data.orders or m < 2:
                    continue
                s = self.largest(m).dropna()
                if not len(s):
                    continue
                u = float(lv[m])
                row = dict(test=test, order=m, U_test_V=u, percentile_all=100.0 * float((s < u).mean()))
                if t0 is not None:
                    ts = s.index - pd.Timedelta(seconds=float(self.data.interval_s) / 2)   # middle of the interval
                    # hours of the week (Monday 00:00 = 0) – a window around midnight reaches into the other day
                    week = np.asarray(ts.dayofweek * 24.0 + ts.hour + ts.minute / 60.0 + ts.second / 3600.0)
                    week0 = t0.dayofweek * 24.0 + t0.hour + t0.minute / 60.0 + t0.second / 3600.0
                    hours = (week - week0 + 84.0) % 168.0 - 84.0
                    w = np.abs(hours) <= window_h
                    sw = s[w]
                    row.update(window="%s %02d:%02d ± %g h" % (names[t0.dayofweek], t0.hour, t0.minute, window_h),
                               percentile_window=100.0 * float((sw < u).mean()) if len(sw) else np.nan,
                               window_min_V=float(sw.min()) if len(sw) else np.nan,
                               window_max_V=float(sw.max()) if len(sw) else np.nan, n_window=int(len(sw)))
                else:
                    row.update(window=tr("pq.no_time_window"), percentile_window=np.nan, window_min_V=np.nan,
                               window_max_V=np.nan, n_window=0)
                row["position_in_range"] = "below" if u < s.min() else ("above" if u > s.max() else "inside")
                q = self.u95().get(m, np.nan)
                row["factor_to_test"] = q / u if u > 0 else np.nan
                rows.append(row)
        out = pd.DataFrame(rows, columns=["test", "order", "U_test_V", "percentile_all", "window", "percentile_window",
                                          "window_min_V", "window_max_V", "n_window", "position_in_range",
                                          "factor_to_test"])
        for h in hints:
            self._hint(h)
        out.attrs["hints"] = hints
        return out


def assess(data: PQData, quantile: float = 0.95, factor: Optional[float] = None,
           factors: Optional[Mapping[float, float]] = None, minutes: float = 10.0, how: str = "rms",
           min_share: float = 1.0, f1: float = 50.0, fault_threshold: Optional[float] = 0.8,
           max_gap_minutes: float = 0.0) -> PQAssessment:
    """Quantiles of a PQ measurement per order and of the THD for the assessment.

    Per interval of ``minutes`` (10-min values – formed with [`ten_minute_values`][groundfault.pq.ten_minute_values]
    if the export has a shorter interval) the largest of the three phases (line-to-earth harmonic voltage per
    order) or loops (line-to-line THD) is taken, and of these values the quantile over the whole measurement.

    The duration of the measurement for the rule ``factors`` is its longest stretch of **gapless** values: an interval
    without a value (also an incomplete 10-min interval) interrupts it. Shorter than every duration of the rule, the
    measurement is not valid for the assessment (``valid`` False, no factor).

    Parameters
    ----------
    data : PQData
        The measurement ([`read`][groundfault.pq.read]).
    quantile : float, optional
        Quantile, 0 < q < 1 (default 0.95).
    factor : float, optional
        Factor on the quantile, set directly (e.g. from your rules for the duration of this measurement).
    factors : mapping, optional
        Rule ``{minimum duration in days: factor}`` ([`duration_factor`][groundfault.pq.duration_factor]) – instead of
        ``factor``. Neither given: no factor (1.0, with a hint).
    minutes, how, min_share : optional
        Aggregation ([`ten_minute_values`][groundfault.pq.ten_minute_values]).
    f1 : float, optional
        Nominal frequency in Hz (only for the column ``f_Hz``).
    fault_threshold : float or None, optional
        Intervals whose smallest line-to-earth fundamental voltage is below ``fault_threshold`` times the largest
        are left out of the quantiles (with a hint): an earth fault or a voltage dip of one phase is not
        undisturbed operation. The unbalance of a resonant-earthed network in operation is a few per cent. None
        keeps every interval; without line-to-earth fundamentals nothing is left out. The intervals left out do not
        interrupt the gapless stretch (the instrument measured).
    max_gap_minutes : float, optional
        Gaps up to this length do not interrupt the gapless stretch (their time does not count); 0 (default): every
        missing interval interrupts it.

    Returns
    -------
    PQAssessment

    Raises
    ------
    ValueError
        For an invalid quantile, factor, rule or ``max_gap_minutes``, both ``factor`` and ``factors``, or without a
        complete interval.
    """
    q = _check_quantile(quantile)
    if factor is not None and factors is not None:
        raise ValueError(tr("pq.factor_both"))
    try:
        max_gap = float(max_gap_minutes)
    except (TypeError, ValueError):
        raise ValueError(tr("pq.max_gap_invalid", value=max_gap_minutes)) from None
    if not (math.isfinite(max_gap) and max_gap >= 0) or isinstance(max_gap_minutes, bool):
        raise ValueError(tr("pq.max_gap_invalid", value=max_gap_minutes))
    d10 = ten_minute_values(data, minutes=minutes, how=how, min_share=min_share)
    if len(d10.harmonics) == 0 or not d10.harmonics[[c for c in d10.harmonics.columns if c[0] >= 2]].notna().any().any():
        raise ValueError(tr("pq.no_intervals"))
    hints = list(d10.hints)
    cov = d10.coverage(max_gap)
    if cov["gaps"]:
        longest = max(cov["gaps"], key=lambda g: g[1] - g[0])
        hints.append(tr("pq.gaps", n=len(cov["gaps"]), longest=str(longest[1] - longest[0]), start=longest[0],
                        end=longest[1]))
    # earth faults and dips of one phase: not undisturbed operation
    cov["n_excluded"] = 0
    if fault_threshold is not None:
        h1 = [(1, p) for p in PHASES_LE if (1, p) in d10.harmonics.columns]
        if len(h1) >= 2:
            u1 = d10.harmonics[h1]
            ratio = u1.min(axis=1) / u1.max(axis=1)
            bad = (ratio < float(fault_threshold)).to_numpy()
            if bad.any():
                hints.append(tr("pq.faults_excluded", n=int(bad.sum()), limit=float(fault_threshold),
                                first=d10.harmonics.index[bad][0]))
                keep = d10.harmonics.index[~bad]
                sel = lambda df: df.reindex(keep) if df is not None and len(df) else df
                d10 = replace(d10, harmonics=d10.harmonics.loc[keep], thd=sel(d10.thd), rms=sel(d10.rms),
                              maxima=sel(d10.maxima))
                cov["n_excluded"] = int(bad.sum())
                if len(d10.harmonics) == 0:
                    raise ValueError(tr("pq.no_intervals"))
    days = cov["gapless_days"]
    if days < cov["span_days"] - 1e-9:
        hints.append(tr("pq.gapless_less", gapless=days, span=cov["span_days"], start=cov["gapless_start"],
                        end=cov["gapless_end"]))
    valid = True
    rule = None
    if factors is not None:
        rule = _check_rule(factors)
        k, fh, valid = duration_factor(days, rule)
    elif factor is not None:
        try:
            k = float(factor)
        except (TypeError, ValueError):
            raise ValueError(tr("pq.factor_invalid", value=factor)) from None
        if not (math.isfinite(k) and k > 0) or isinstance(factor, bool):
            raise ValueError(tr("pq.factor_invalid", value=factor))
        fh = tr("pq.factor_given", factor=k, days=days)
    else:
        k, fh = 1.0, tr("pq.factor_none", days=days)
    hints.append(fh)
    ref = d10.reference
    if ref == "LL":
        hints.append(tr("pq.ll_only"))
    phases = [p for p in (PHASES_LE if ref == "LE" else PHASES_LL) if p in d10.phases]
    if len(phases) < 3:
        hints.append(tr("pq.phases_missing", phases=", ".join(phases)))
    u1 = d10.largest(1).median() if 1 in d10.orders else np.nan
    # harmonic voltage of the largest phase per interval (orders of the export) for the share of each order
    uh = None
    if [m for m in d10.orders if m >= 2]:
        per_phase = []
        for ph in phases:
            cols = [(m, ph) for m in d10.orders if m >= 2 and (m, ph) in d10.harmonics.columns]
            per_phase.append(np.sqrt((d10.harmonics[cols] ** 2).sum(axis=1, min_count=1)))
        uh = pd.concat(per_phase, axis=1).max(axis=1)
    rows = []
    for m in d10.orders:
        df = d10.voltages(m)
        if df.empty:
            continue
        big = df.max(axis=1, skipna=True)
        row = dict(order=int(m), f_Hz=float(m * f1))
        for ph in phases:
            row["U_quantile_%s_V" % ph] = float(df[ph].quantile(q)) if ph in df.columns else np.nan
        uq = float(big.quantile(q))
        row.update(U_quantile_V=uq, U_assessment_V=uq * k if m >= 2 else np.nan, U_median_V=float(big.median()),
                   U_max_V=float(big.max()),
                   share_of_U1_pct=100.0 * uq / u1 if m >= 2 and np.isfinite(u1) and u1 > 0 else np.nan,
                   share_of_UH_pct=(100.0 * float((big / uh).median()) if uh is not None and m >= 2 else np.nan),
                   n_intervals=int(big.notna().sum()))
        rows.append(row)
    cols = ["order", "f_Hz"] + ["U_quantile_%s_V" % ph for ph in phases] + [
        "U_quantile_V", "U_assessment_V", "U_median_V", "U_max_V", "share_of_U1_pct", "share_of_UH_pct", "n_intervals"]
    table = pd.DataFrame(rows, columns=cols)
    thd_ll = [p for p in PHASES_LL if p in d10.thd.columns and d10.thd[p].notna().any()]
    thd95_ll = float(d10.thd[thd_ll].max(axis=1).quantile(q)) if thd_ll else float("nan")
    tle = _thd_le(d10)
    thd95_le = float(tle.max(axis=1).quantile(q)) if len(tle.columns) else float("nan")
    if not thd_ll:
        tll = _thd_le(d10, zero=False)               # line-to-line equivalent: without the zero sequence
        if len(tll.columns) and tll.notna().any().any():
            thd95_ll = float(tll.max(axis=1).quantile(q))
            hints.append(tr("pq.no_ll_thd"))
        else:
            hints.append(tr("pq.no_thd"))
    uhl = _uh_ll(d10)
    uh95_ll = float(uhl.max(axis=1).quantile(q)) if len(uhl.columns) else float("nan")
    a = PQAssessment(quantile=q, factor=float(k), factor_hint=fh, factor_rule=rule, valid=valid, data=d10,
                     orders_table=table, thd95_ll=thd95_ll, thd95_le=thd95_le, uh95_ll=uh95_ll, coverage=cov,
                     f1=float(f1), hints=hints)
    dom = a.dominant_order
    if dom is not None:
        share = table.set_index("order").loc[dom, "share_of_UH_pct"]
        if np.isfinite(share):
            hints.append(tr("pq.dominant", order=dom, f=dom * f1, share=share))
    return a


# ============================================================================================== fault tests
def pre_fault_levels(result, reference: str = "pre_fault",
                     kind: str = "LE") -> Tuple[Dict[int, float], Optional[pd.Timestamp]]:
    """Pre-fault voltage per order of a fault test – the largest of the three line-to-earth voltages (or line-to-line
    loops; median over the windows of the interval) – and the start of its recording.

    Parameters
    ----------
    result : Result or ResultFile
        Result of [`groundfault.evaluation.evaluate`][groundfault.evaluation.evaluate] or
        [`groundfault.evaluation.load_result`][groundfault.evaluation.load_result].
    reference : {"pre_fault", "post_fault", "mean"}, optional
        Interval: before or after the fault, or the mean of both.
    kind : {"LE", "LL"}, optional
        The largest line-to-earth voltage (default) or line-to-line loop – the reference of the PQ measurement
        (``PQAssessment.reference``).

    Returns
    -------
    (dict, Timestamp or None)
        ``{order: U in V}`` and the start time of the recording (as stored, usually UTC).
    """
    check_option("reference", reference, ("pre_fault", "post_fault", "mean"))
    check_option("kind", kind, ("LE", "LL"))
    keys = ("U_L1E", "U_L2E", "U_L3E") if kind == "LE" else ("U_L12", "U_L23", "U_L31")
    values = getattr(result, "values", {}) or {}
    v = values.get("voltage") or {}
    orders = v.get("orders") or []
    blocks = [b for b in (("pre_fault", "post_fault") if reference == "mean" else (reference,)) if v.get(b)]
    out: Dict[int, float] = {}
    for i, m in enumerate(orders):
        vals = []
        for b in blocks:
            try:
                vals.append(max(float(v[b][k][i]) for k in keys))
            except (KeyError, IndexError, TypeError, ValueError):
                continue
        if vals:
            out[int(m)] = float(np.mean(vals))
    data = getattr(result, "data", {}) or {}
    start = ((data.get("meta") or {}).get("start_time")
             or (getattr(result, "recording_info", {}) or {}).get("start"))
    try:
        start = pd.Timestamp(start) if start else None
    except (TypeError, ValueError):
        start = None
    return out, start
