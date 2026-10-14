# -*- coding: utf-8 -*-
"""Earthing measurements from **groundmeas** and their comparison with the staged fault test at the same station.

groundmeas (https://github.com/Ce1ectric/groundmeas) manages earthing measurements in an SQLite database::

    Location  →  Measurement (method, asset_type, date …)  →  MeasurementItem
                                                              measurement_type, value, value_angle_deg,
                                                              unit, frequency_hz, measurement_distance_m …

This module reads the database **read-only** with the Python standard library (``sqlite3``) – groundmeas itself does not
have to be installed. Units are read as in groundmeas ≥ 1.6.1 ([`groundfault.units`][groundfault.units]): stored as
entered (``250.0`` with ``mOhm``), computed in the SI base unit (Ω, A, V, Ωm). The database is found as groundmeas finds
it: environment variable ``GROUNDMEAS_DB``, otherwise ``db_path`` in ``~/.config/groundmeas/config.json``.

The quantity compared is the voltage per ampere (V/A = Ω) over the frequency:

* earthing measurement with current injection (``injection_*``): ``earthing_impedance`` per probe distance
  (= voltage at the probe per ampere of test current), touch voltages (``prospective_touch_voltage``,
  ``touch_voltage``) per ampere of ``earthing_current``;
* staged fault test recorded in groundmeas (``staged_fault_test``): ``earth_potential_rise`` and
  ``prospective_touch_voltage`` per ampere of ``earth_fault_current`` at the same frequency;
* staged fault test evaluated with this package: table ``station_frequency`` (direct and fault-related
  component).

Export ([`export_to_groundmeas`][groundfault.earthing.export_to_groundmeas],
[`export_fault_test`][groundfault.earthing.export_fault_test]): an evaluated recording becomes a new
``staged_fault_test`` measurement – a station with the fault current, the earth potential rise / touch voltage per probe
and frequency (fault-related component) and the shield current, a substation with the fault current per harmonic order.
Location, coordinates, asset type, voltage level and distance to the substation come from the sites file of the campaign
(``notes/sites.csv``, German layout ``0_Notizen/Messorte.csv``; see [`groundfault.sites`][groundfault.sites]). The
default is a dry run; the database is written only on request, after a backup copy, in one transaction, and never over
entries made by others.
"""
from __future__ import annotations

import datetime as _dt
import difflib
import json
import math
import os
import re
import shutil
import sqlite3
import unicodedata
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import i18n
from . import units as _units
from .i18n import tr
from .legacy import check_option
from .station import MAX_PROBE

__all__ = ["default_db_path", "Database", "frequency_response", "compare", "reduction_factor", "check_lv_network",
           "reduction_hints", "export_fault_test", "export_to_groundmeas", "plan_overview", "plan_items",
           "exclude_own", "entry_tag", "entry_tags", "location_rows", "location_from_site",
           "R_IMPLAUSIBLE", "RELEVANCE_THRESHOLD_PCT", "SHIELD_SMALL", "TREND_EXPONENT",
           "METHOD_FACTOR", "ASSET_TYPES", "UNIT_CHOICES", "UNCERTAIN_MODES", "EXISTING", "COORDINATE_TOLERANCE_M",
           "ORDER_MAX", "TAG_PREFIX", "LEGACY_TAG_PREFIX", "QUANTITY_EPR", "QUANTITY_TOUCH", "SOURCE_FAULT_TEST",
           "SOURCE_INJECTION", "SOURCE_GROUNDMEAS_FAULT", "EXPORTED_HINT_KEYS"]

#: labels of the groundmeas measurement types (column ``designation`` of :meth:`Database.values`): (English, German)
_TYPE_LABELS = {
    "earthing_impedance": ("earthing impedance (probe)", "Erdungsimpedanz (Sonde)"),
    "earthing_resistance": ("earthing resistance", "Erdungswiderstand"),
    "earthing_current": ("test current", "Prüfstrom"),
    "earth_fault_current": ("earth fault current", "Erdfehlerstrom"),
    "shield_current": ("shield current", "Schirmstrom"),
    "earth_potential_rise": ("earth potential rise", "Erdungsspannung"),
    "prospective_touch_voltage": ("prosp. touch voltage", "prosp. Berührungsspannung"),
    "touch_voltage": ("touch voltage", "Berührungsspannung"),
    "step_voltage": ("step voltage", "Schrittspannung"),
    "transferred_potential": ("transferred potential", "verschleppte Spannung"),
    "soil_resistivity": ("soil resistivity", "spez. Bodenwiderstand"),
}
#: German labels of the groundmeas measurement types (kept for compatibility; the labels come from the catalog)
TYPES_DE = {k: de for k, (_, de) in _TYPE_LABELS.items()}

QUANTITY_EPR = "earth_potential_rise"
"""Value of the column ``quantity`` ([`frequency_response`][groundfault.earthing.frequency_response],
[`compare`][groundfault.earthing.compare]): earth potential rise (probe farther away than 1.5 m)."""
QUANTITY_TOUCH = "touch_voltage"
"""Value of the column ``quantity``: touch voltage (probe up to 1.5 m)."""
SOURCE_FAULT_TEST = "fault test"
"""Value of the column ``source``: rows of this evaluation ([`compare`][groundfault.earthing.compare])."""
SOURCE_INJECTION = "injection test"
"""Value of the column ``source``: earthing measurements with current injection stored in groundmeas
([`frequency_response`][groundfault.earthing.frequency_response])."""
SOURCE_GROUNDMEAS_FAULT = "fault test (groundmeas)"
"""Value of the column ``source``: staged fault tests stored in groundmeas
([`frequency_response`][groundfault.earthing.frequency_response])."""
_EPR, _TOUCH = QUANTITY_EPR, QUANTITY_TOUCH

i18n.register({"earthing.type_%s" % k: {"en": en, "de": de} for k, (en, de) in _TYPE_LABELS.items()})
i18n.register({
    # ---- database and location search
    "earthing.db_not_found": {
        "en": "groundmeas database not found: {path!r}",
        "de": "groundmeas-Datenbank nicht gefunden: {path!r}"},
    "earthing.db_not_found_config": {
        "en": "groundmeas database not found: {path!r} (GROUNDMEAS_DB or ~/.config/groundmeas/config.json)",
        "de": "groundmeas-Datenbank nicht gefunden: {path!r} (GROUNDMEAS_DB oder ~/.config/groundmeas/config.json)"},
    "earthing.not_a_database": {
        "en": "{path} is not a groundmeas database (missing tables: {tables})",
        "de": "{path} ist keine groundmeas-Datenbank (Tabellen fehlen: {tables})"},
    "earthing.location_not_in_db": {
        "en": "Location “{name}” is not in the database (check the spelling, see the list of candidates).",
        "de": "Ort „{name}“ steht nicht in der Datenbank (Schreibweise prüfen, Kandidaten siehe Liste)."},
    "earthing.location_no_match": {
        "en": "No matching location for “{name}” – set {preset} to the name in the database.",
        "de": "Kein passender Ort zu „{name}“ – {preset} mit dem Namen aus der Datenbank setzen."},
    "earthing.location_ambiguous": {
        "en": "Several locations match “{name}” about equally well ({candidates}) – set {preset}.",
        "de": "Mehrere Orte passen ähnlich gut zu „{name}“ ({candidates}) – {preset} setzen."},
    "earthing.location_similar": {
        "en": "Location “{location}” is similar to “{name}” ({similarity:.0f} %) – used for the comparison; set it "
              "exactly with {preset}.",
        "de": "Ort „{location}“ ähnlich zu „{name}“ ({similarity:.0f} %) – zum Vergleichen verwendet; genau festlegen "
              "mit {preset}."},
    # ---- comparison tables
    "earthing.order": {"en": "order {order}", "de": "Ordnung {order}"},
    "earthing.injection_measured": {"en": "measured at {f:g} Hz", "de": "gemessen bei {f:g} Hz"},
    "earthing.injection_interpolated": {"en": "interpolated {low:g}–{high:g} Hz",
                                        "de": "interpoliert {low:g}–{high:g} Hz"},
    # ---- hints on the reduction factor and the LV network
    "earthing.label_probe_maximum": {"en": "probe maximum ({probe})", "de": "Sondenmaximum ({probe})"},
    "earthing.label_pair": {"en": "{left} ↔ earthing measurement {id}{distance}",
                            "de": "{left} ↔ Erdungsmessung {id}{distance}"},
    "earthing.assessment": {
        "en": "For the assessment: at the reference current {current} A the fault test gives U_E = {u_fault} V, the "
              "earthing measurement {u_injection} V – the deviation of {deviation} V is {share} % of "
              "F·U_Tp = {limit} V",
        "de": "Für die Bewertung: beim Bezugsstrom {current} A ergibt der Erdschluss U_E = {u_fault} V, die "
              "Erdungsmessung {u_injection} V – die Abweichung von {deviation} V sind {share} % von "
              "F·U_Tp = {limit} V"},
    "earthing.assessment_negligible": {
        "en": ", negligible for the assessment of the earthing system.",
        "de": ", für die Bewertung der Erdungsanlage vernachlässigbar."},
    "earthing.assessment_unchanged_below": {
        "en": "; both are below F·U_Tp, the assessment does not change.",
        "de": "; beide liegen unter F·U_Tp, die Bewertung ändert sich nicht."},
    "earthing.assessment_unchanged_above": {
        "en": "; both are above F·U_Tp, the assessment does not change.",
        "de": "; beide liegen über F·U_Tp, die Bewertung ändert sich nicht."},
    "earthing.assessment_relevant": {
        "en": "; one is above and one below F·U_Tp – the assessment depends on the method.",
        "de": "; einer liegt über, einer unter F·U_Tp – die Bewertung hängt vom Verfahren ab."},
    "earthing.z_values": {
        "en": "Z_E from the fault test ({quantity}/I_F) {z_fault} Ω, from the earthing measurement {z_injection} Ω",
        "de": "Z_E aus dem Erdschluss ({quantity}/I_F) {z_fault} Ω, aus der Erdungsmessung {z_injection} Ω"},
    "earthing.hint_r_below": {
        "en": "Reduction factor {name}: r = {r} at 50 Hz is below the typical range {low}–{high} ({values}). The fault "
              "test gives a much smaller earth potential rise than the earthing measurement suggests. If the return "
              "paths (cable shields, PEN connections to neighbouring stations) do not explain this, a methodological "
              "error of the earthing measurement is likely – the fall-of-potential method tends to give values that "
              "are too high, e.g. due to inductive coupling of the measuring leads or the position of probe and "
              "auxiliary electrode – or the earthing measurement was made in a different switching state. {assessment}",
        "de": "Reduktionsfaktor {name}: r = {r} bei 50 Hz liegt unter dem üblichen Bereich {low}–{high} ({values}). "
              "Der Erdschluss ergibt eine viel kleinere Erdungsspannung, als die Erdungsmessung erwarten lässt. "
              "Erklären die Rückleiter (Kabelschirme, PEN-Verbindungen zu Nachbarstationen) das nicht, ist ein "
              "methodischer Fehler der Erdungsmessung wahrscheinlich – das Strom-Spannungs-Verfahren (Fall of "
              "Potential) liefert tendenziell zu hohe Werte, z. B. durch induktive Kopplung der Messleitungen oder "
              "die Lage von Sonde und Hilfserder – oder sie galt einem anderen Schaltzustand. {assessment}"},
    "earthing.hint_r_above": {
        "en": "Reduction factor {name}: r = {r} at 50 Hz is above the typical range {low}–{high} ({values}) – little "
              "current flows back through the return paths, e.g. shield interrupted, very high-resistance shield "
              "termination (poorly earthed pole) or overhead line without earth wire; or the earthing measurement is "
              "too small. {assessment}",
        "de": "Reduktionsfaktor {name}: r = {r} bei 50 Hz liegt über dem üblichen Bereich {low}–{high} ({values}) – "
              "wenig Strom fließt über die Rückleiter zurück, z. B. Schirm unterbrochen, sehr hochohmiger "
              "Schirmabschluss (schlecht geerdeter Mast) oder Freileitung ohne Erdseil; oder die Erdungsmessung ist "
              "zu klein. {assessment}"},
    "earthing.hint_r_implausible": {
        "en": "Reduction factor {name}: r = {r} at 50 Hz is greater than 1 ({values}) – the fault test measures more "
              "than the full earth potential rise of the earthing measurement: check the ratio and polarity of the "
              "channels, the position of the probe in the fault test (other potentials) and the earthing "
              "measurement. {assessment}",
        "de": "Reduktionsfaktor {name}: r = {r} bei 50 Hz ist größer als 1 ({values}) – der Erdschluss misst mehr als "
              "die volle Erdungsspannung der Erdungsmessung: Übersetzung und Polarität der Kanäle, Lage der Sonde im "
              "Erdschluss (fremde Potentiale) und die Erdungsmessung prüfen. {assessment}"},
    "earthing.relevance_not_determined": {
        "en": "Relevance of the deviation between fault test and earthing measurement for the assessment not "
              "determined – not given: {missing}. Define them yourself: arguments of earthing.reduction_factor, or "
              "Settings.ires_limits (largest limit = reference current), u_tp and f_factor of the evaluation.",
        "de": "Bedeutung der Abweichung zwischen Erdschluss und Erdungsmessung für die Bewertung nicht bestimmt – "
              "nicht angegeben: {missing}. Selbst festlegen: Argumente von earthing.reduction_factor oder "
              "Settings.ires_limits (größter Grenzwert = Bezugsstrom), u_tp und f_factor der Auswertung."},
    "earthing.r_typical_invalid": {
        "en": "r_typical must be a pair (low, high) with 0 ≤ low < high, or None – got {value!r}.",
        "de": "r_typical muss ein Paar (untere, obere Grenze) mit 0 ≤ unten < oben sein oder None – erhalten: "
              "{value!r}."},
    "earthing.hint_relevant": {
        "en": "Fault test and earthing measurement {name}: {assessment}",
        "de": "Erdschluss und Erdungsmessung {name}: {assessment}"},
    "earthing.hint_r_rising": {
        "en": "Reduction factor {name}: r rises with the frequency (r ∝ f^{exponent} over the orders {orders}) – a "
              "decrease is expected because the inductive coupling of the return paths increases with the frequency "
              "(f → ∞: r → 0). Possible causes: earthing measurement too small at higher frequencies or uncertain "
              "harmonic components of the fault test (column uncertain).",
        "de": "Reduktionsfaktor {name}: r steigt mit der Frequenz (r ∝ f^{exponent} über die Ordnungen {orders}) – "
              "erwartet ist ein Abfall, weil die induktive Kopplung der Rückleiter mit der Frequenz zunimmt "
              "(f → ∞: r → 0). Mögliche Ursachen: Erdungsmessung bei höheren Frequenzen zu klein oder unsichere "
              "Oberschwingungsanteile des Erdschlusses (Spalte unsicher)."},
    "earthing.hint_shield_zero": {
        "en": "Shield current almost zero ({share} % of the fault current, RMS). Possible causes: shield interrupted, "
              "very high-resistance shield termination (e.g. poorly earthed pole at the cable end) or the channel "
              "does not capture the feeding cable. The reduction factor from the shield current (r_S ≈ {r_shield}) "
              "then applies to this shield only.",
        "de": "Schirmstrom nahezu null ({share} % des Fehlerstroms, effektiv). Mögliche Ursachen: Schirm unterbrochen, "
              "sehr hochohmiger Schirmabschluss (z. B. schlecht geerdeter Mast am Kabelende) oder der Kanal erfasst "
              "nicht den gespeisten Kabelabgang. Der Reduktionsfaktor aus dem Schirmstrom (r_S ≈ {r_shield}) gilt "
              "dann nur für diesen Schirm."},
    "earthing.hint_shield_zero_epr": {
        "en": "The small reduction factor from the earth potential rise (r_eff = {r_eff}) is then not explained by "
              "this shield: further return paths (shields of other cables, PEN connections) or an earthing "
              "measurement that is too high.",
        "de": "Der kleine Reduktionsfaktor aus der Erdungsspannung (r_eff = {r_eff}) erklärt sich dann nicht über "
              "diesen Schirm: weitere Rückleiter (Schirme anderer Kabel, PEN-Verbindungen) oder eine zu hohe "
              "Erdungsmessung."},
    "earthing.hint_methods_differ": {
        "en": "Reduction factor {name}: from the earth potential rise r_eff = {r_eff}, from the shield current "
              "{r_shield} – Z_E from the fault test with the earth current I_E = I_F − I_S is {ratio} times the "
              "earthing measurement. Either {cause}; the cross-check from the shield current then does not apply.",
        "de": "Reduktionsfaktor {name}: aus der Erdungsspannung r_eff = {r_eff}, aus dem Schirmstrom {r_shield} – Z_E "
              "aus dem Erdschluss mit dem Erdungsstrom I_E = I_F − I_S ist das {ratio}-Fache der Erdungsmessung. "
              "Entweder {cause}; die Gegenprobe aus dem Schirmstrom gilt dann nicht."},
    "earthing.cause_more_return_paths": {
        "en": "further return paths carry current that the shield-current channel does not capture (shields of other "
              "cables, PEN connections), or the earthing measurement is too high (methodological error)",
        "de": "weitere Rückleiter führen Strom, die der Schirmstromkanal nicht erfasst (Schirme anderer Kabel, "
              "PEN-Verbindungen), oder die Erdungsmessung ist zu hoch (methodischer Fehler)"},
    "earthing.cause_shield_measures_more": {
        "en": "the shield-current channel measures more than the return current of this station (e.g. also currents "
              "of other feeders), or the earthing measurement is too low",
        "de": "der Schirmstromkanal misst mehr als den Rückstrom dieser Station (z. B. auch Ströme anderer Abgänge), "
              "oder die Erdungsmessung ist zu niedrig"},
    "earthing.lv_values": {"en": "at {f} Hz {z_lv} Ω against {z_injection} Ω",
                           "de": "bei {f} Hz {z_lv} Ω gegen {z_injection} Ω"},
    "earthing.hint_lv_below": {
        "en": "LV network {name}: Z_E,LV is below the earthing impedance of the earthing measurement at "
              "{frequencies} Hz ({values}) – impossible for a parallel branch of the total earthing if both values "
              "are correct.",
        "de": "Ortsnetz {name}: Z_E,Ortsnetz liegt bei {frequencies} Hz unter der Erdungsimpedanz der Erdungsmessung "
              "({values}) – als Parallelzweig der Gesamterdung unmöglich, wenn beide Werte stimmen."},
    "earthing.hint_lv_violated": {
        "en": "Also violated against the fault test itself (current into the LV network larger than the fault "
              "current): check the PEN clamps (ratio, position).",
        "de": "Auch gegen den Erdschluss selbst verletzt (Strom ins Ortsnetz größer als der Fehlerstrom): PEN-Zangen "
              "(Übersetzung, Lage) prüfen."},
    "earthing.hint_lv_satisfied": {
        "en": "Against the fault test itself (Z_E,fault = max(U_E)/I_F) the parallel connection is satisfied – the "
              "contradiction lies with the earthing measurement (measured value too high, e.g. a methodological error "
              "of the fall-of-potential method, or a different switching state such as disconnected PEN conductors or "
              "cable shields). Record it as a finding.",
        "de": "Gegen den Erdschluss selbst (Z_E,Erdschluss = max(U_E)/I_F) ist die Parallelschaltung erfüllt – der "
              "Widerspruch liegt bei der Erdungsmessung (zu hoher Messwert, z. B. methodischer Fehler des "
              "Strom-Spannungs-Verfahrens, oder ein anderer Schaltzustand wie getrennte PEN-Leiter oder Kabelschirme). "
              "Als Befund festhalten."},
    "earthing.hint_lv_causes": {
        "en": "Possible causes: earthing measurement too high or in a different switching state, probe in the fault "
              "test not in remote earth, or the PEN clamps measure more than the current into the LV network.",
        "de": "Mögliche Ursachen: Erdungsmessung zu hoch oder in einem anderen Schaltzustand, Sonde im Erdschluss "
              "nicht in ferner Erde, oder die PEN-Zangen messen mehr als den Strom ins Ortsnetz."},
    # ---- export: arguments and result
    "earthing.method_missing": {"en": "Method {method!r} not in the result (available: {available})",
                                "de": "Verfahren {method!r} nicht im Ergebnis (vorhanden: {available})"},
    "earthing.nothing_to_export": {
        "en": "Neither a station evaluation (table station_frequency) nor fault-current harmonics (table harmonics) "
              "in the result – nothing to enter.",
        "de": "Weder Stationsauswertung (Tabelle station_frequency) noch Fehlerstrom-Harmonische (Tabelle "
              "harmonics) im Ergebnis – nichts einzutragen."},
    "earthing.asset_type_unknown": {"en": "asset type {value!r} unknown (allowed: {allowed})",
                                    "de": "Anlagentyp {value!r} unbekannt (zulässig: {allowed})"},
    "earthing.uncertain_omitted": {"en": "{count} uncertain values omitted ({frequencies} Hz).",
                                   "de": "{count} unsichere Werte weggelassen ({frequencies} Hz)."},
    "earthing.no_voltages": {
        "en": "No voltage values for the method {method!r} (e.g. fault-related component not determinable) – only "
              "fault and shield current; the values as measured with method=\"direct\".",
        "de": "Keine Spannungswerte für das Verfahren {method!r} (z. B. fehlerbedingter Anteil nicht bestimmbar) – "
              "nur Fehler- und Schirmstrom; die direkt gemessenen Werte mit method=\"direct\"."},
    "earthing.distance_unknown": {
        "en": "Distance to the feeding substation unknown ({file}, column {column}) – "
              "distance_to_current_injection_m stays empty.",
        "de": "Entfernung zum speisenden UW unbekannt ({file}, Spalte {column}) – "
              "distance_to_current_injection_m bleibt leer."},
    "earthing.probe_distance_unknown": {
        "en": "Probe distance unknown for {channels} – measurement_distance_m stays empty; add the distance in "
              "{file} (column {column}) and evaluate again.",
        "de": "Sondenabstand unbekannt für {channels} – measurement_distance_m bleibt leer; Abstand in "
              "{file} (Spalte {column}) nachtragen und neu auswerten."},
    "earthing.no_values": {"en": "no values to enter", "de": "keine Werte zum Eintragen"},
    "earthing.fault_resistance_unknown": {
        "en": "Fault resistance unknown – fault_resistance_ohm stays empty (z_fault_ohm of the evaluation or column "
              "{column} in {file}, e.g. 0 = solid fault).",
        "de": "Fehlerwiderstand unbekannt – fault_resistance_ohm bleibt leer (z_fault_ohm der Auswertung bzw. Spalte "
              "{column} in {file}, z. B. 0 = metallisch)."},
    "earthing.voltage_level_unknown": {
        "en": "Voltage level unknown – voltage_level_kv stays empty ({file}, column {column}).",
        "de": "Spannungsebene unbekannt – voltage_level_kv bleibt leer ({file}, Spalte {column})."},
    "earthing.units_chosen": {
        "en": "Units: {units} – groundmeas converts to V/A itself from version 1.6.1 on (for older versions "
              "units=\"base\").",
        "de": "Einheiten: {units} – groundmeas rechnet ab Version 1.6.1 selbst in V/A um (für ältere Versionen "
              "units=\"base\")."},
    "earthing.unit_of_type": {"en": "{type} in {unit}", "de": "{type} in {unit}"},
    "earthing.timestamp_format": {"en": "timestamp={value!r} – format YYYY-MM-DD hh:mm:ss (UTC)",
                                  "de": "timestamp={value!r} – Format JJJJ-MM-TT hh:mm:ss (UTC)"},
    "earthing.timestamp_by_hand": {"en": "Time given by hand: {time} UTC (cfg: {cfg}).",
                                   "de": "Zeitpunkt von Hand vorgegeben: {time} UTC (cfg: {cfg})."},
    "earthing.clock_wrong": {
        "en": "Start of the recording according to the cfg ({start}) is {days} days away from the campaign date "
              "{date} – recorder clock set wrongly? Give the start in UTC (timestamp=\"{date} hh:mm:ss\")",
        "de": "Aufzeichnungsbeginn laut cfg ({start}) liegt {days} Tage neben dem Kampagnendatum {date} – Uhr des "
              "Messgeräts falsch gestellt? Beginn in UTC vorgeben (timestamp=\"{date} hh:mm:ss\")"},
    "earthing.location_without_coordinates": {
        "en": "Location “{name}” (location {id}) has no coordinates in groundmeas – it does not appear on the map; "
              "enter {coordinates} in {file}.",
        "de": "Ort „{name}“ (Ort {id}) hat in groundmeas keine Koordinaten – erscheint nicht auf der Karte; "
              "{coordinates} in {file} eintragen."},
    "earthing.coordinates_differ": {
        "en": "Coordinates from {file} are {distance:.0f} m away from the groundmeas location “{name}” (location "
              "{id}: {latitude}, {longitude}) – the existing location is used and not changed.",
        "de": "Koordinaten aus {file} liegen {distance:.0f} m vom groundmeas-Ort „{name}“ (Ort {id}: "
              "{latitude}, {longitude}) entfernt – der vorhandene Ort wird verwendet und nicht verändert."},
    "earthing.location_only_without_coordinates": {
        "en": "Location “{name}” exists in groundmeas only without coordinates – new location row with the "
              "coordinates from {file}.",
        "de": "Ort „{name}“ steht in groundmeas nur ohne Koordinaten – neue Ortszeile mit den Koordinaten aus "
              "{file}."},
    "earthing.new_location_without_coordinates": {
        "en": "new location “{name}” without coordinates (enter {coordinates} in {path})",
        "de": "neuer Ort „{name}“ ohne Koordinaten ({coordinates} in {path} eintragen)"},
    "earthing.new_location_similar": {
        "en": "Location “{name}” is new in groundmeas – similar names there: {similar}. If it is the same location: "
              "enter the name from groundmeas in {file}.",
        "de": "Ort „{name}“ ist neu in groundmeas – ähnlich heißen dort: {similar}. Falls derselbe Ort: den Namen "
              "aus groundmeas in {file} eintragen."},
    "earthing.quoted": {"en": "“{text}”", "de": "„{text}“"},
    "earthing.other_fault_tests": {
        "en": "There are already fault-test entries from another source at this location: {entries} – they remain "
              "unchanged (possibly the same fault test, e.g. from a report).",
        "de": "Am Ort stehen schon Erdschluss-Einträge aus anderer Quelle: {entries} – sie bleiben unverändert "
              "(evtl. derselbe Erdschluss, z. B. aus einem Bericht)."},
    "earthing.other_fault_test": {"en": "measurement {id} ({date}, {count} values, “{description}”)",
                                  "de": "Messung {id} ({date}, {count} Werte, „{description}“)"},
    "earthing.own_entry_renewed": {"en": "own entry (measurement {id}) is renewed",
                                   "de": "eigener Eintrag (Messung {id}) wird erneuert"},
    "earthing.already_entered": {"en": "already entered (measurement {id})",
                                 "de": "bereits eingetragen (Messung {id})"},
    "earthing.not_own_entry": {
        "en": "measurement {id} with the same timestamp was not made by this tool – it is not replaced",
        "de": "Messung {id} mit gleichem Zeitstempel stammt nicht aus diesem Werkzeug – wird nicht ersetzt"},
    "earthing.backup_missing": {"en": "Backup copy {path} is missing – nothing written.",
                                "de": "Sicherungskopie {path} fehlt – nichts geschrieben."},
    "earthing.sites_created": {
        "en": "created: {path} (pre-filled from groundmeas) – please check it and enter coordinates for new "
              "locations.",
        "de": "angelegt: {path} (aus groundmeas vorbelegt) – bitte prüfen und für neue Orte Koordinaten eintragen."},
    "earthing.site_missing": {"en": "{file}: no line for the site “{site}” – location from the folder name.",
                              "de": "{file}: keine Zeile für den Messort „{site}“ – Ort aus dem Ordnernamen."},
    "earthing.site_unknown": {
        "en": "The result names no measurement site – location from the measurement name “{name}”.",
        "de": "Das Ergebnis nennt keinen Messort – Ort aus dem Messungsnamen „{name}“."},
    "earthing.no_sites_file": {"en": "no {file} – location from the folder name.",
                               "de": "keine {file} – Ort aus dem Ordnernamen."},
    "earthing.fault_resistance_from_register": {"en": "Fault resistance {value:g} Ω from {file}.",
                                                "de": "Fehlerwiderstand {value:g} Ω aus {file}."},
    # ---- status column of plan_overview
    "earthing.status_entered": {"en": "entered: measurement {id}", "de": "eingetragen: Messung {id}"},
    "earthing.status_renewed": {"en": "renewed: measurement {id}", "de": "erneuert: Messung {id}"},
    "earthing.status_impossible": {"en": "not possible: {reasons}", "de": "nicht möglich: {reasons}"},
    "earthing.status_already_entered": {"en": "already entered (measurement {id})",
                                        "de": "schon eingetragen (Messung {id})"},
    "earthing.status_ready_renew": {"en": "ready: renews measurement {id}", "de": "bereit: erneuert Messung {id}"},
    "earthing.status_ready": {"en": "ready", "de": "bereit"},
})


# ---------------------------------------------------------------------------------------------- path
def default_db_path() -> Optional[str]:
    """Path of the groundmeas database, found as groundmeas finds it.

    Returns
    -------
    str or None
        The environment variable ``GROUNDMEAS_DB`` (with ``~`` expanded), otherwise ``db_path`` in
        ``~/.config/groundmeas/config.json``; None if neither is set or the configuration cannot be read.
    """
    p = os.environ.get("GROUNDMEAS_DB")
    if p:
        return os.path.expanduser(p)
    cfg = os.path.join(os.path.expanduser("~"), ".config", "groundmeas", "config.json")
    try:
        with open(cfg, encoding="utf-8") as f:
            p = json.load(f).get("db_path")
        return os.path.expanduser(p) if p else None
    except (OSError, ValueError):
        return None


#: words for the kind of installation in location names (English, German and common abbreviations) → kind
_TYPE_WORDS = {"sst": "station", "ost": "station", "ons": "station", "station": "station",
               "ortsnetzstation": "station", "uw": "uw", "umspannwerk": "uw", "substation": "uw", "sub": "uw"}


def _norm_name(s: str) -> str:
    """Location name for the fuzzy search: ASCII, lower case, without the words for the kind of installation."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = s.replace("_", " ").replace("-", " ")
    s = re.sub(r"\b(sst|ost|station|ons|uw|umspannwerk|ortsnetzstation|substation|sub)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _kind_from_name(s: str) -> set:
    """Kind of installation from the name: {"station"}, {"uw"} (substation) or empty."""
    w = re.split(r"[\s_\-]+", unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower())
    return {_TYPE_WORDS[x] for x in w if x in _TYPE_WORDS}


def _numbers(s: str) -> set:
    """Numbers in a name (``"SSt Bärenfeld 2"`` → ``{"2"}``)."""
    return set(re.findall(r"\d+", str(s)))


def _norm_umlaut(s: str) -> str:
    """German umlauts and ß written as ae/oe/ue/ss."""
    return (str(s).replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("Ä", "Ae").replace("Ö", "Oe")
            .replace("Ü", "Ue").replace("ß", "ss"))


def location_from_site(site: str) -> str:
    """Location name from the folder name of a site (folder in ``raw``).

    The prefix ``Station``, ``Substation``, ``SUB``/``UW`` (also with ``_Trafo``) and a sampling-rate suffix such as
    ``_40_000kHz`` are removed,
    underscores become spaces: ``Station_Elm_Road`` → ``Elm Road``, ``Station_Lindenweg`` → ``Lindenweg``. If nothing
    remains, the folder name is returned unchanged.

    Examples
    --------
    >>> location_from_site("Station_Elm_Road_10_000kHz")
    'Elm Road'
    """
    s = re.sub(r"_\d+_\d+k?Hz$", "", str(site))
    s = re.sub(r"^(Substation|Station|UW_Trafo|UW|SUB_Trafo|SUB)_?", "", s).replace("_", " ").strip()
    return s or str(site)


def _unit(unit, type_: Optional[str] = None) -> Tuple[str, float, Optional[str]]:
    """Stored unit of a value → (base unit, factor, note) as in groundmeas ≥ 1.6.1: without a unit the base unit of
    the type; an unknown unit or one that does not fit the type → factor 1 (value as stored) with a note."""
    if unit is None or not str(unit).strip():
        return _units.base_unit(type_) if type_ else "", 1.0, None
    try:
        e = _units.parse_unit(str(unit), _units.quantities(type_))
    except _units.UnitError as ex:
        return str(unit), 1.0, str(ex)
    return e.base, e.factor, None


def _type_label(type_) -> str:
    """Label of a groundmeas measurement type in the active language (the type itself if it is unknown)."""
    key = "earthing.type_%s" % type_
    return tr(key) if i18n.has_message(key) else type_


# ---------------------------------------------------------------------------------------------- database
class Database:
    """groundmeas database, opened read-only.

    Parameters
    ----------
    path : str, optional
        Database file; default: [`default_db_path`][groundfault.earthing.default_db_path].

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If the file is not a groundmeas database (tables ``location``, ``measurement`` or ``measurementitem``
        missing).

    Notes
    -----
    The file is opened through an SQLite URI with ``mode=ro``: every write attempt fails with
    ``sqlite3.OperationalError``. Special characters in the path (``#``, ``%``, ``?``) are percent-encoded. The
    object is a context manager (``with Database(path) as db: ...``).
    """

    def __init__(self, path: Optional[str] = None):
        path = path or default_db_path()
        if not path or not os.path.exists(path):
            raise FileNotFoundError(tr("earthing.db_not_found_config", path=path))
        self.path = path
        uri = Path(path).resolve().as_uri() + "?mode=ro"            # special characters (#, %, ?) percent-encoded
        self.con = sqlite3.connect(uri, uri=True)
        try:
            tables = {r[0] for r in self.con.execute("select name from sqlite_master where type='table'")}
        except sqlite3.Error:
            self.con.close()
            raise
        missing_ = {"location", "measurement", "measurementitem"} - tables
        if missing_:
            self.con.close()                                         # the object is not returned: close here
            raise ValueError(tr("earthing.not_a_database", path=path, tables=", ".join(sorted(missing_))))

    def close(self) -> None:
        """Close the connection."""
        self.con.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def __repr__(self):
        return "<groundmeas database %s>" % self.path

    # ------------------------------------------------------------------ overviews
    def locations(self) -> pd.DataFrame:
        """All locations with the number of their measurements and the methods.

        Returns
        -------
        pandas.DataFrame
            Columns ``location_id``, ``location``, ``latitude``, ``longitude``, ``measurements`` (count) and
            ``methods`` (comma-separated), sorted by name and id.
        """
        q = """select l.id, l.name, l.latitude, l.longitude, count(m.id), group_concat(distinct m.method)
               from location l left join measurement m on m.location_id = l.id group by l.id order by l.name, l.id"""
        return pd.DataFrame(self.con.execute(q).fetchall(),
                            columns=["location_id", "location", "latitude", "longitude", "measurements", "methods"])

    def measurements(self, location: Optional[str] = None, method: Optional[str] = None) -> pd.DataFrame:
        """Measurements, optionally only those of one location and/or method.

        Parameters
        ----------
        location : str, optional
            Location name: the exact name, otherwise all locations found by
            [`find_location`][groundfault.earthing.Database.find_location].
        method : str, optional
            Part of the groundmeas method (``"injection"``, ``"staged_fault_test"`` …).

        Returns
        -------
        pandas.DataFrame
            One row per measurement: ``measurement_id``, ``location``, ``method``, ``asset_type``, ``date``,
            ``fault_resistance_Ohm``, ``voltage_level_kV``, ``description``, ``values`` (number of values),
            ``measurement_types`` (comma-separated) and ``frequencies_Hz``; sorted by location and time.
        """
        q = """select m.id, l.name, m.method, m.asset_type, m.timestamp, m.fault_resistance_ohm, m.voltage_level_kv,
                      m.description, count(i.id), group_concat(distinct i.measurement_type),
                      group_concat(distinct i.frequency_hz)
               from measurement m left join location l on l.id = m.location_id
               left join measurementitem i on i.measurement_id = m.id group by m.id order by l.name, m.timestamp"""
        df = pd.DataFrame(self.con.execute(q).fetchall(),
                          columns=["measurement_id", "location", "method", "asset_type", "date", "fault_resistance_Ohm",
                                   "voltage_level_kV", "description", "values", "measurement_types",
                                   "frequencies_Hz"])
        df["date"] = df["date"].astype(str).str[:10]
        df["frequencies_Hz"] = df["frequencies_Hz"].fillna("").map(
            lambda s: ", ".join("%g" % f for f in sorted({float(x) for x in s.split(",") if x})))
        if location is not None:
            names = ({n for n in self.find_location(location)["location"]} if location not in set(df["location"])
                     else {location})
            df = df[df["location"].isin(names)]
        if method is not None:
            df = df[df["method"].str.contains(method)]
        return df.reset_index(drop=True)

    def find_location(self, name: str, minimum: float = 0.6) -> pd.DataFrame:
        """Locations whose name matches ``name`` (fuzzy search).

        Case, umlauts (ä = ae) and the words for the kind of installation (``SSt``, ``Station``, ``UW`` …) are
        ignored; small typing errors such as *Lindemweg* ↔ *Lindenweg* are found. A different kind of installation
        (SSt ↔ UW) or different numbers (“Bärenfeld 2” ↔ “Bärenfeld”) lower the similarity considerably.

        Parameters
        ----------
        name : str
            Name searched for – a location name or a folder name such as ``Station_Lindemweg``.
        minimum : float
            Smallest similarity (0…1) included.

        Returns
        -------
        pandas.DataFrame
            Columns ``location_id``, ``location`` and ``similarity``, best match first.

        Notes
        -----
        The similarity is the largest of: the ``difflib.SequenceMatcher`` ratio of the normalised names; 0.9 if
        one normalised name contains the other; 0.95 × the smallest word-by-word ratio (every word of ``name`` with
        the most similar word of the location name; words shorter than three characters do not count). It is then
        multiplied by 0.7 for a different kind of installation and by 0.8 for different numbers.
        """
        target_ = _norm_name(_norm_umlaut(name))
        type_target, numbers_target = _kind_from_name(name), _numbers(name)
        rows = []
        for oid, oname in self.con.execute("select id, name from location"):
            n = _norm_name(_norm_umlaut(oname))
            if not n or not target_:
                continue
            s = difflib.SequenceMatcher(None, target_, n).ratio()
            if target_ in n or n in target_:
                s = max(s, 0.9)
            # word by word: every word of the search term with the most similar word of the location name (the
            # search term "Lindemweg" finds "Lindenweg Nord"); short words (< 3 characters) do not count
            words = [x for x in target_.split() if len(x) >= 3]
            candidates = [x for x in n.split() if len(x) >= 3]
            if words and candidates:
                per_word = [max(difflib.SequenceMatcher(None, x, y).ratio() for y in candidates) for x in words]
                s = max(s, 0.95 * min(per_word))
            type_location = _kind_from_name(oname)
            # different kind of installation, e.g. "SSt Hillcrest" ↔ "UW Hillcrest"
            if type_target and type_location and not (type_target & type_location):
                s *= 0.7
            if numbers_target != _numbers(oname):                          # e.g. "Bärenfeld 2" ↔ "Bärenfeld"
                s *= 0.8
            if s >= minimum:
                rows.append(dict(location_id=oid, location=oname, similarity=round(s, 3)))
        df = pd.DataFrame(rows, columns=["location_id", "location", "similarity"])
        return df.sort_values(["similarity", "location_id"], ascending=[False, True]).reset_index(drop=True)

    def choose_location(self, name: str, exact_only: bool = False, minimum: float = 0.85,
                        preset: str = 'location="{}"') -> Dict[str, object]:
        """Choose the groundmeas location for ``name``.

        A location is *exact* if the name is in the database as given (ignoring case, umlauts written as ae/oe/ue)
        – only then may a fault test be exported to it. Otherwise – unless ``exact_only`` (a location given
        explicitly is not “guessed”) – the most similar location is chosen if its similarity reaches ``minimum``
        and no other name matches about equally well (within 0.05). That is good enough for a read-only comparison,
        not for writing.

        Parameters
        ----------
        name : str
            Location name or folder name.
        exact_only : bool
            Accept only an exact match.
        minimum : float
            Smallest similarity of a non-exact match.
        preset : str
            How the caller sets the location exactly – used in the note, ``{}`` is replaced by the location name. The
            default names the argument ``location`` of
            [`export_to_groundmeas`][groundfault.earthing.export_to_groundmeas]; a notebook can pass the name of its own
            variable instead (e.g. ``'LOCATION = "{}"'``).

        Returns
        -------
        dict
            ``location`` (name, or None if none is chosen), ``exact``, ``unique``, ``similarity``, ``candidates`` (table
            of [`find_location`][groundfault.earthing.Database.find_location] with a minimum of 0.5) and ``note`` (empty
            for an exact match).
        """
        def key(x):
            return re.sub(r"\s+", " ", _norm_umlaut(str(x)).lower().replace("_", " ")).strip()
        locations = [r[0] for r in self.con.execute("select distinct name from location")]
        equal = [o for o in locations if key(o) == key(name)]
        cand = self.find_location(name, 0.5)
        if equal:
            return dict(location=equal[0], exact=True, unique=True, similarity=1.0, candidates=cand, note="")
        if exact_only:
            return dict(location=None, exact=False, unique=False, similarity=np.nan, candidates=cand,
                        note=tr("earthing.location_not_in_db", name=name))
        if cand.empty or cand["similarity"].iloc[0] < minimum:
            return dict(location=None, exact=False, unique=False, similarity=float(cand["similarity"].iloc[0])
                        if len(cand) else np.nan, candidates=cand,
                        note=tr("earthing.location_no_match", name=name, preset=preset.format("…")))
        best = cand["similarity"].iloc[0]
        others = cand[(cand["location"] != cand["location"].iloc[0]) & (cand["similarity"] >= best - 0.05)]
        if len(others):
            return dict(location=None, exact=False, unique=False, similarity=float(best), candidates=cand,
                        note=tr("earthing.location_ambiguous", name=name,
                                candidates=", ".join(dict.fromkeys(cand["location"].head(4))),
                                preset=preset.format("…")))
        return dict(location=cand["location"].iloc[0], exact=False, unique=True, similarity=float(best),
                    candidates=cand,
                    note=tr("earthing.location_similar", location=cand["location"].iloc[0], name=name,
                            similarity=100 * best, preset=preset.format(cand["location"].iloc[0])))

    def units(self) -> pd.DataFrame:
        """All stored units per measurement type, checked as groundmeas ≥ 1.6.1 converts them.

        Returns
        -------
        pandas.DataFrame
            Columns ``type``, ``unit`` (as stored), ``count``, ``base_unit``, ``factor``, ``note`` (the reason if
            the unit cannot be converted, otherwise empty) and ``measurements`` (ids, comma-separated).
        """
        rows = []
        for type_, unit, n, mids in self.con.execute(
                "select measurement_type, unit, count(*), group_concat(distinct measurement_id) from measurementitem "
                "group by measurement_type, unit order by measurement_type, unit"):
            base, k, problem = _unit(unit, type_)
            rows.append(dict(type=type_, unit=unit, count=n, base_unit=base, factor=k,
                             note=problem or "", measurements=mids))
        return pd.DataFrame(rows, columns=["type", "unit", "count", "base_unit", "factor", "note",
                                           "measurements"])

    # ------------------------------------------------------------------ values
    def values(self, measurement_ids: Iterable[int]) -> pd.DataFrame:
        """All values of the given measurements in SI base units.

        Values are converted as in groundmeas ≥ 1.6.1 (Ω, V, A, Ωm). Values stored only as real and imaginary part
        are converted into magnitude and angle.

        Parameters
        ----------
        measurement_ids : iterable of int
            groundmeas measurement ids.

        Returns
        -------
        pandas.DataFrame
            One row per value: ``measurement_id``, ``item_id``, ``location``, ``method``, ``date``, ``type``,
            ``designation`` (label of the type in the active language), ``magnitude`` (base unit), ``angle_deg``
            (NaN if not recorded), ``unit`` (base unit), ``unit_stored`` (as entered), ``unit_note`` (the reason if
            the unit cannot be converted – the value is then as stored), ``f_Hz``, ``distance_m`` (probe distance),
            ``distance_injection_m``, ``additional_resistance_Ohm``, ``input_impedance_Ohm`` and ``description``.
            Empty if no ids are given.
        """
        ids = [int(i) for i in measurement_ids]
        if not ids:
            return pd.DataFrame()
        q = """select i.measurement_id, i.id, i.measurement_type, i.value, i.value_real, i.value_imag,
                      i.value_angle_deg, i.unit, i.frequency_hz, i.measurement_distance_m,
                      i.distance_to_current_injection_m, i.additional_resistance_ohm, i.input_impedance_ohm,
                      i.description, m.method, l.name, m.timestamp
               from measurementitem i join measurement m on m.id = i.measurement_id
               left join location l on l.id = m.location_id
               where i.measurement_id in (%s) order by i.measurement_id, i.measurement_type, i.frequency_hz,
               i.measurement_distance_m""" % ",".join("?" * len(ids))
        rows = []
        for (mid, iid, type_, val, re_, im_, ang, unit, f, d, dinj, radd, rin, descr, meth, location, time) in \
                self.con.execute(q, ids):
            base, k, problem = _unit(unit, type_)
            if val is None and (re_ is not None or im_ is not None):
                z = complex(re_ or 0.0, im_ or 0.0)
                val, ang = abs(z), math.degrees(math.atan2(z.imag, z.real))
            magnitude = float(val) * k if val is not None else np.nan
            rows.append(dict(measurement_id=mid, item_id=iid, location=location, method=meth, date=str(time or "")[:10],
                             type=type_, designation=_type_label(type_), magnitude=magnitude,
                             angle_deg=float(ang) if ang is not None else np.nan, unit=base,
                             unit_stored=unit, unit_note=problem,
                             f_Hz=float(f) if f is not None else np.nan,
                             distance_m=float(d) if d is not None else np.nan,
                             distance_injection_m=float(dinj) if dinj is not None else np.nan,
                             additional_resistance_Ohm=radd, input_impedance_Ohm=rin, description=descr or ""))
        return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------- comparison
def _phasor(magnitude, angle):
    """Complex phasor; without a finite angle the magnitude as a real number."""
    return magnitude * np.exp(1j * np.deg2rad(angle)) if np.isfinite(angle) else complex(magnitude, 0.0)


def frequency_response(db: Database, measurement_ids: Iterable[int]) -> pd.DataFrame:
    """Voltage per ampere over the frequency for measurements in groundmeas.

    Earthing measurement with current injection: ``earthing_impedance`` already is V/A; touch voltages are divided
    by the test current (``earthing_current``) of the same frequency. At the injection the touch voltage per ampere
    is the same quantity as the earthing impedance at the 1-m probe, so it is taken only once (the impedance) – no
    double counting in figures and ratios. Staged fault test in groundmeas: voltages divided by the
    ``earth_fault_current`` of the same frequency; the angle is given only if both angles are recorded (0° and 0°
    of a fault test count as not recorded).

    Parameters
    ----------
    db : Database
        The groundmeas database.
    measurement_ids : iterable of int
        Measurements to read.

    Returns
    -------
    pandas.DataFrame
        One row per value: ``source`` (``"injection test"``, ``"fault test (groundmeas)"`` or the method),
        ``measurement_id``, ``location``, ``method``, ``date``, ``quantity`` (``"earth_potential_rise"`` or
        ``"touch_voltage"``, i.e. a touch-voltage type or an earthing impedance at a probe up to 1.5 m), ``type``
        (groundmeas measurement type), ``distance_m``, ``f_Hz``, ``Z_Ohm`` (V/A), ``angle_deg`` (NaN if not recorded),
        ``reference_current_A`` (current the voltage was divided by), ``additional_resistance_Ohm`` and ``description``.
        Empty if there are no values.
    """
    w = db.values(measurement_ids)
    if w.empty:
        return pd.DataFrame()
    rows = []
    for mid, g in w.groupby("measurement_id"):
        method = g["method"].iloc[0]
        injection = method.startswith("injection")
        source = SOURCE_INJECTION if injection else (SOURCE_GROUNDMEAS_FAULT if method == "staged_fault_test"
                                                     else method)
        current_type = "earthing_current" if injection else "earth_fault_current"
        currents = {round(r["f_Hz"], 3): r for _, r in g[g["type"] == current_type].iterrows()
                    if np.isfinite(r["f_Hz"])}
        # At the injection the touch voltage per ampere is the same quantity as the earthing impedance at the
        # 1-m probe – take it only once (the impedance), so that figures and ratios do not count it twice.
        z_near = {round(r["f_Hz"], 3) for _, r in g[(g["type"] == "earthing_impedance") & (g["distance_m"] <= 1.5)]
                  .iterrows() if np.isfinite(r["f_Hz"])} if injection else set()
        for _, r in g.iterrows():
            type_, f = r["type"], r["f_Hz"]
            if not np.isfinite(f) or not np.isfinite(r["magnitude"]):
                continue
            if injection and type_ == "prospective_touch_voltage" and round(f, 3) in z_near:
                continue
            if type_ == "earthing_impedance":
                z, ang, i_ref = r["magnitude"], r["angle_deg"], np.nan
                quantity = _TOUCH if (np.isfinite(r["distance_m"]) and r["distance_m"] <= 1.5) else _EPR
            elif type_ in ("earth_potential_rise", "prospective_touch_voltage", "touch_voltage"):
                s = currents.get(round(f, 3))
                if s is None or not (s["magnitude"] > 0):
                    continue
                zz = _phasor(r["magnitude"], r["angle_deg"]) / _phasor(s["magnitude"], s["angle_deg"])
                both = np.isfinite(r["angle_deg"]) and np.isfinite(s["angle_deg"]) and \
                    not (r["angle_deg"] == 0 and s["angle_deg"] == 0 and not injection)
                z, ang, i_ref = abs(zz), (math.degrees(np.angle(zz)) if both else np.nan), s["magnitude"]
                quantity = _EPR if type_ == "earth_potential_rise" else _TOUCH
            else:
                continue
            rows.append(dict(source=source, measurement_id=int(mid), location=r["location"], method=method,
                             date=r["date"], quantity=quantity, type=type_, distance_m=r["distance_m"], f_Hz=float(f),
                             Z_Ohm=float(z), angle_deg=float(ang) if np.isfinite(ang) else np.nan,
                             reference_current_A=i_ref, additional_resistance_Ohm=r["additional_resistance_Ohm"],
                             description=r["description"]))
    return pd.DataFrame(rows)


def _distance(x) -> float:
    """Probe distance in m; NaN if missing, not a number or not positive."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return v if np.isfinite(v) and v > 0 else float("nan")


def _choose_probe(cand: pd.DataFrame, distance: float, touch: bool) -> Tuple[pd.DataFrame, str]:
    """Matching probe of the earthing measurement → (rows, distance match).

    Touch voltage: probes up to 1.5 m. Earth potential rise: the probe with the (logarithmically) nearest distance,
    rated ``"equal"`` (factor ≤ 1.25), ``"similar"`` (≤ 2) or ``"different"``; without a distance of the fault-test
    probe the largest distance of the earthing measurement (``"unknown"``); touch voltage: ``"touch"``."""
    if touch:
        return cand[cand["distance_m"] <= 1.5], "touch"
    k = cand[cand["quantity"] == _EPR]
    d = pd.to_numeric(k["distance_m"], errors="coerce")
    if k.empty or not d.notna().any():
        return k, "unknown"
    if not np.isfinite(distance):
        return k[d == d.max()], "unknown"
    j = np.abs(np.log(d / distance))
    best = float(d[j == j.min()].iloc[0])
    q = max(best / distance, distance / best)
    return k[d == best], ("equal" if q <= 1.25 else "similar" if q <= 2.0 else "different")


def _yes(x) -> bool:
    """Truth value of a table cell (bool, 0/1, "True"/"yes"/"ja"; empty or NaN → False)."""
    if isinstance(x, str):
        return x.strip().lower() in ("true", "yes", "y", "1", "x", "ja", "wahr")
    try:
        return bool(x) and not (isinstance(x, float) and np.isnan(x))
    except (TypeError, ValueError):
        return False


def compare(station_frequency: pd.DataFrame, db_response: Optional[pd.DataFrame] = None,
            measurement: str = "", tolerance_hz: float = 5.0) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Combine the evaluation of the staged fault test with values from groundmeas and form the ratio per frequency.

    Parameters
    ----------
    station_frequency : pandas.DataFrame
        Table ``station_frequency`` of a station evaluation.
    db_response : pandas.DataFrame, optional
        Values from groundmeas ([`frequency_response`][groundfault.earthing.frequency_response]).
    measurement : str
        Name of the measurement (column ``measurement`` of the fault-test rows).
    tolerance_hz : float
        Largest frequency difference between the fault test and the earthing measurement.

    Returns
    -------
    long, ratio : pandas.DataFrame
        ``long``: one row per source/method, probe and frequency (columns as
        [`frequency_response`][groundfault.earthing.frequency_response]). The fault-test rows have the ``source``
        ``"fault test"``, the ``type`` ``"fault"`` (fault-related component) or ``"direct"`` (as measured),
        ``measurement``, ``channel``, ``order`` and – for the fault-related component – ``Z_min_Ohm``/``Z_max_Ohm``
        (range of the single superposition methods: inception, clearance, voltage), ``method_spread_pct``,
        ``uncertainty_pct`` and ``uncertain``; the rows of ``db_response`` follow.

        ``ratio``: per probe and harmonic order of the fault test, Z fault-related (``ratio_fault``) and direct
        (``ratio_direct``) divided by the earthing measurement at the same frequency (± ``tolerance_hz``) and a
        comparable probe distance – touch voltage: probe up to 1.5 m; earth potential rise: the nearest distance (column
        ``distance_match``: ``"equal"``, ``"similar"``, ``"different"``; ``"touch"`` for the touch voltage), without a
        distance the largest (``"unknown"``). The rows of the probe maximum come first (``channel`` = ``max(UE)``,
        column ``probe``, ``distance_match`` = ``"maximum"``): per order the highest voltage per ampere of all probes
        against the farthest probe of the earthing measurement – as in
        [`reduction_factor`][groundfault.earthing.reduction_factor]. Both tables take over the column ``uncertain`` of
        the station evaluation (fault-related component uncertain because of a large, fluctuating background or
        disagreeing methods).

    Notes
    -----
    For the earth potential rise at a remote probe the ratio is the effective reduction factor r = (r·Z_E)/Z_E; rows
    with ``distance_match == "different"`` must not be interpreted that way.
    """
    rows = []
    sf = station_frequency if station_frequency is not None else pd.DataFrame()
    for _, r in sf.iterrows():
        quantity = _TOUCH if r["role"] == "u_t" else _EPR
        for meth_ in ("fault", "direct"):
            z = r.get("Z_%s_Ohm" % meth_, np.nan)
            if not np.isfinite(z):
                continue
            single = [r.get("Z_%s_Ohm" % v, np.nan) for v in ("inception", "clearance", "voltage")]
            single = [x for x in single if np.isfinite(x)]
            fb = meth_ == "fault"
            rows.append(dict(source=SOURCE_FAULT_TEST, measurement=measurement, measurement_id=np.nan, location="",
                             method="staged_fault_test",
                             quantity=quantity, type=meth_, channel=r["channel"],
                             distance_m=_distance(r.get("distance_m")),
                             f_Hz=float(r["f_Hz"]), order=int(r["order"]), Z_Ohm=float(z),
                             angle_deg=r.get("Z_%s_angle_deg" % meth_, np.nan), reference_current_A=r.get("I_F_A"),
                             Z_min_Ohm=min(single) if (fb and single) else np.nan,
                             Z_max_Ohm=max(single) if (fb and single) else np.nan,
                             method_spread_pct=r.get("method_spread_pct", np.nan) if fb else np.nan,
                             uncertainty_pct=r.get("uncertainty_pct", np.nan) if fb else np.nan,
                             uncertain=_yes(r.get("uncertain")) if fb else False,
                             description=tr("earthing.order", order=int(r["order"]))))
    long_df = pd.concat([pd.DataFrame(rows), db_response if db_response is not None else pd.DataFrame()],
                        ignore_index=True)
    rat = []
    inj = db_response[db_response["source"] == SOURCE_INJECTION] if db_response is not None and \
        not db_response.empty else pd.DataFrame()
    if not inj.empty and not sf.empty:
        probes = sf[sf["role"].isin(["u_e", "u_t"])]
        remote = _farthest_injection(inj) if len(probes) else {}
        for p in (_max_series(probes) if remote else []):          # probe maximum ↔ farthest probe of the measurement
            for mid, (rows, d_inj, distance_match) in remote.items():
                j = (rows["f_Hz"] - p["f"]).abs()
                if j.min() > tolerance_hz:
                    continue
                k = rows.loc[j.idxmin()]
                d = dict(channel=MAX_PROBE, probe=p["probe"], role="u_e", distance_fault_m=p["distance"],
                         order=p["m"], f_Hz=p["f"], injection_id=int(mid), distance_injection_m=d_inj,
                         distance_match=distance_match, Z_injection_Ohm=k["Z_Ohm"],
                         injection_angle_deg=k["angle_deg"], uncertain=p["uncertain"])
                for meth_, z in (("fault", p["z_fault"]), ("direct", p["z_d"])):
                    d["Z_%s_Ohm" % meth_] = z
                    d["ratio_%s" % meth_] = z / k["Z_Ohm"] if k["Z_Ohm"] > 0 else np.nan
                rat.append(d)
        for _, r in sf.iterrows():
            ut = r["role"] == "u_t"
            dist = _distance(r.get("distance_m"))
            cand = inj[(inj["f_Hz"] - r["f_Hz"]).abs() <= tolerance_hz]
            cand, distance_match = _choose_probe(cand, dist, ut)
            for _, k in cand.iterrows():
                d = dict(channel=r["channel"], probe=r["channel"], role=r["role"], distance_fault_m=dist,
                         order=int(r["order"]), f_Hz=float(r["f_Hz"]), injection_id=int(k["measurement_id"]),
                         distance_injection_m=k["distance_m"], distance_match=distance_match,
                         Z_injection_Ohm=k["Z_Ohm"], injection_angle_deg=k["angle_deg"],
                         uncertain=_yes(r.get("uncertain")))
                for meth_ in ("fault", "direct"):
                    z = r.get("Z_%s_Ohm" % meth_, np.nan)
                    d["Z_%s_Ohm" % meth_] = z
                    d["ratio_%s" % meth_] = z / k["Z_Ohm"] if k["Z_Ohm"] > 0 else np.nan
                rat.append(d)
    return long_df, pd.DataFrame(rat)


# ---------------------------------------------------------------------------------------------- reduction factor
UNCERTAIN_PCT = 20.0            #: as in the station evaluation: from this uncertainty on a value counts as uncertain
R_IMPLAUSIBLE = 1.1
"""Reduction factor above which the fault test measures more than the full EPR of the earthing measurement
(implausible)."""
RELEVANCE_THRESHOLD_PCT = 10.0
"""A deviation between fault test and earthing measurement up to this share of F·U_Tp (in %) counts as negligible for
the assessment."""
SHIELD_SMALL = 0.1
"""A shield current below this share of the fault current counts as “almost zero”."""
TREND_EXPONENT = 0.1
"""Magnitude of the exponent b in r ∝ f^b from which r counts as falling or rising."""
METHOD_FACTOR = 2.0
"""If the reduction factors from the EPR and from the shield current differ by more than this factor, a hint is
given."""


def _injection_probes(inj: pd.DataFrame, distance: float, touch: bool) -> Dict[int, tuple]:
    """Per earthing measurement (``measurement_id``) the probe matching the probe distance → {id: (rows sorted by f,
    distance, distance match)} – chosen as in [`compare`][groundfault.earthing.compare] (nearest distance,
    logarithmically; for a distance ``NaN`` the farthest probe)."""
    out = {}
    for mid, g in inj.groupby("measurement_id"):
        rows, comparison = _choose_probe(g, distance, touch)
        rows = rows[np.isfinite(pd.to_numeric(rows["f_Hz"], errors="coerce"))
                    & np.isfinite(pd.to_numeric(rows["Z_Ohm"], errors="coerce"))]
        if rows.empty:
            continue
        out[int(mid)] = (rows.sort_values("f_Hz"), _distance(rows["distance_m"].iloc[0]), comparison)
    return out


def _farthest_injection(inj: pd.DataFrame) -> Dict[int, tuple]:
    """Per earthing measurement the farthest earth-potential probe (reference for the probe maximum of the fault
    test)."""
    return {mid: (z, d, "maximum") for mid, (z, d, _) in _injection_probes(inj, float("nan"), False).items()}


def _z_at(rows: pd.DataFrame, f: float, tolerance_hz: float, interpolate: bool) -> Tuple[float, str, bool]:
    """|Z| of the earthing measurement at the frequency ``f`` → (V/A, origin text, measured): measured
    (± ``tolerance_hz``), otherwise – if ``interpolate`` – linearly between the neighbouring measured frequencies;
    never extrapolated (NaN, ``""``, False)."""
    ff = rows["f_Hz"].to_numpy(float)
    zz = rows["Z_Ohm"].to_numpy(float)
    j = np.abs(ff - f)
    if j.size and j.min() <= tolerance_hz:
        k = int(np.argmin(j))
        return float(zz[k]), tr("earthing.injection_measured", f=ff[k]), True
    if interpolate and ff.size >= 2:
        u = np.unique(ff)
        if u[0] < f < u[-1]:
            zm = np.array([zz[ff == x].mean() for x in u])
            lo, hi = u[u < f].max(), u[u > f].min()
            return float(np.interp(f, u, zm)), tr("earthing.injection_interpolated", low=lo, high=hi), False
    return float("nan"), "", False


def _shield_ratio(currents: Optional[pd.DataFrame]) -> Dict[int, complex]:
    """Sum of the fault-related shield currents per order as a ratio to I_F (complex, I_F at 0°); every channel is
    turned into the direction of I_F (real part at the fundamental ≥ 0)."""
    if currents is None or currents.empty or "share_fault" not in currents:
        return {}
    shield_ = currents[currents["role"] == "i_shield"]
    total_: Dict[int, complex] = {}
    for _, g in shield_.groupby("channel"):
        k = {int(r["order"]): _phasor(r["share_fault"], r["share_fault_angle_deg"])
             for _, r in g.iterrows() if np.isfinite(r["share_fault"])}
        if not k:
            continue
        reference = k.get(1, max(k.values(), key=abs))
        s_ = -1 if np.real(reference) < 0 else 1
        for m, x in k.items():
            total_[m] = total_.get(m, 0j) + s_ * x
    return total_


def _source_tables(tables) -> Tuple[dict, object]:
    """``res.tables`` or a result (with ``tables`` and ``settings``) → (tables, settings or None)."""
    if hasattr(tables, "tables"):
        return tables.tables, getattr(tables, "settings", None)
    return (tables if hasattr(tables, "get") else {}), None


def _reference_values(settings_, reference_current_A: Optional[float], U_Tp: Optional[float],
                      F: Optional[float]) -> Tuple[float, float, float]:
    """Reference current, U_Tp and F of the relevance for the assessment: the arguments, otherwise the settings of the
    evaluation (largest limit ``ires_limits``, ``u_tp``, ``f_factor``); NaN for a value given nowhere – groundfault
    has no defaults for them."""
    if reference_current_A is None:
        g = tuple(getattr(settings_, "ires_limits", ()) or ())
        reference_current_A = max(g) if g else None
    if U_Tp is None:
        U_Tp = getattr(settings_, "u_tp", None)
    if F is None:
        F = getattr(settings_, "f_factor", None)
    return tuple(float(x) if x is not None else float("nan") for x in (reference_current_A, U_Tp, F))


def _check_r_typical(r_typical) -> Optional[Tuple[float, float]]:
    """``r_typical`` as (low, high) with 0 ≤ low < high, or None; ValueError otherwise."""
    if r_typical is None:
        return None
    try:
        low, high = (float(x) for x in r_typical)
        ok = 0.0 <= low < high and math.isfinite(high)
    except (TypeError, ValueError):
        ok = False
    if not ok:
        raise ValueError(tr("earthing.r_typical_invalid", value=r_typical))
    return low, high


def _probe_series(g: pd.DataFrame) -> List[dict]:
    """Rows of one probe of ``station_frequency`` → per order: probe, distance, I_F, V/A (fault-related, direct),
    uncertainty."""
    return [dict(m=int(r["order"]), f=float(r["f_Hz"]), i_f=_num_(r.get("I_F_A")),
                 z_fault=_num_(r.get("Z_fault_Ohm")), z_d=_num_(r.get("Z_direct_Ohm")), probe=str(r["channel"]),
                 role=str(r.get("role", "")), distance=_distance(r.get("distance_m")),
                 unc_=_num_(r.get("uncertainty_pct")), spread=_num_(r.get("method_spread_pct")),
                 uncertain=_yes(r.get("uncertain")))
            for _, r in g.sort_values("order").iterrows()]


def _max_series(probes: pd.DataFrame) -> List[dict]:
    """Probe maximum: per order the probe with the highest fault-related voltage per ampere (all probes against the
    station earth – earth potential rise and touch voltage; none measures more than the full earth potential
    rise)."""
    out = []
    for _, g in probes.groupby("order", sort=True):
        z = pd.to_numeric(g["Z_fault_Ohm"], errors="coerce")
        out += _probe_series(g.loc[[z.idxmax()]] if z.notna().any() else g.iloc[[0]])
    return out


def _exponent(f, y) -> float:
    """Exponent b of the regression line log y = a + b·log f (y ∝ f^b); NaN with fewer than two frequencies."""
    f = np.asarray(f, float); y = np.asarray(y, float)
    ok = np.isfinite(f) & np.isfinite(y) & (f > 0) & (y > 0)
    if np.unique(f[ok]).size < 2:
        return float("nan")
    return float(np.polyfit(np.log(f[ok]), np.log(y[ok]), 1)[0])


def _number(x, digits: int = 3) -> str:
    """Number for hint texts: ``digits`` significant digits, without exponent (from 10**digits on as an integer);
    decimal comma in German; ``"–"`` for a missing or non-finite value."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "–"
    if not np.isfinite(v):
        return "–"
    s = "%.*g" % (digits, v)
    if "e" in s:
        s = "%.0f" % v if abs(v) >= 1 else "%.*f" % (digits + 3, v)
    return s.replace(".", ",") if i18n.get_language() == "de" else s


def _classify_r(r: float, r_typical: Optional[Tuple[float, float]] = None) -> str:
    """Reduction factor at 50 Hz against the typical range of the user → ``"below"``, ``"typical"``, ``"above"``,
    ``"implausible"`` (above [`R_IMPLAUSIBLE`][groundfault.earthing.R_IMPLAUSIBLE], with or without a range) or
    ``"–"`` (not finite, or no range given)."""
    if not np.isfinite(r):
        return "–"
    if r > R_IMPLAUSIBLE:
        return "implausible"
    if r_typical is None:
        return "–"
    if r < r_typical[0]:
        return "below"
    if r > r_typical[1]:
        return "above"
    return "typical"


def _relevance(u_fault: float, u_injection: float, limit_: float, threshold_pct: float) -> Tuple[float, str]:
    """Relevance of the deviation fault test ↔ earthing measurement for the assessment of the earthing system →
    (deviation in % of F·U_Tp, code): ``"negligible"`` (below ``threshold_pct``), ``"unchanged"`` (both earth
    potential rises on the same side of F·U_Tp), ``"relevant"`` (one above, one below) or ``"–"``."""
    if not (np.isfinite(u_fault) and np.isfinite(u_injection)) or not limit_ > 0:
        return float("nan"), "–"
    p = 100.0 * abs(u_injection - u_fault) / limit_
    if p < threshold_pct:
        return p, "negligible"
    if (u_fault <= limit_) == (u_injection <= limit_):
        return p, "unchanged"
    return p, "relevant"


def _rf_spectrum(channel: str, series: List[dict], mid: int, rows: pd.DataFrame, d_inj: float, comparison: str, *,
                 k_s: Dict[int, complex], tolerance_hz: float, interpolate: bool, reference_current: float,
                 limit_: float) -> List[dict]:
    """Rows per order: one probe (or the probe maximum) against one earthing measurement. The private key
    ``_measured`` (value of the earthing measurement measured at this frequency) is used by ``_classify``."""
    i_f_all = math.sqrt(float(np.nansum([p["i_f"] ** 2 for p in series])))
    s_ref = reference_current / i_f_all if i_f_all > 0 else float("nan")     # spectrum as measured, scaled to I_ref
    out = []
    for p in series:
        z_inj, origin, measured = _z_at(rows, p["f"], tolerance_hz, interpolate)
        ok = np.isfinite(z_inj) and z_inj > 0
        r = p["z_fault"] / z_inj if ok else np.nan
        ks = k_s.get(p["m"])
        r_s = abs(1.0 - ks) if ks is not None else np.nan
        with_s = bool(np.isfinite(r_s) and r_s > 0)
        u_f = p["z_fault"] * p["i_f"] * s_ref
        u_m = z_inj * p["i_f"] * s_ref if ok else np.nan
        out.append(dict(channel=channel, probe=p["probe"], distance_fault_m=p["distance"], injection_id=mid,
                        distance_injection_m=d_inj, distance_match=comparison, order=p["m"], f_Hz=p["f"],
                        I_F_A=p["i_f"], UE_per_A_fault=p["z_fault"],
                        UE_per_A_direct=p["z_d"], UE_per_A_injection=z_inj,
                        injection_frequency=origin, r=r, r_direct=p["z_d"] / z_inj if ok else np.nan,
                        r_to_r_50Hz=np.nan,
                        share_shield=abs(ks) if ks is not None else np.nan, r_shield=r_s,
                        UE_per_A_earth_current=p["z_fault"] / r_s if with_s else np.nan,
                        Z_E_fault_to_injection=r / r_s if with_s else np.nan,
                        U_E_fault_at_reference_current_V=u_f, U_E_injection_at_reference_current_V=u_m,
                        deviation_at_reference_current_V=u_m - u_f,
                        assessment_relevance_pct=100.0 * abs(u_m - u_f) / limit_ if limit_ > 0 else np.nan,
                        uncertainty_pct=p["unc_"], method_spread_pct=p["spread"], uncertain=p["uncertain"],
                        _measured=measured))
    r1 = next((a["r"] for a in out if a["order"] == 1 and np.isfinite(a["r"])), np.nan)
    for a in out:
        a["r_to_r_50Hz"] = a["r"] / r1 if np.isfinite(r1) and r1 > 0 else np.nan
    return out


def _rf_effective(channel: str, series: List[dict], mid: int, rows: pd.DataFrame, d_inj: float, comparison: str,
                  sp: Optional[pd.DataFrame], *, k_s: Dict[int, complex], tolerance_hz: float,
                  interpolate: bool) -> Optional[dict]:
    """RMS row of one probe against one earthing measurement (sum over the orders with both values); None without
    such orders."""
    i_f_all = math.sqrt(float(np.nansum([p["i_f"] ** 2 for p in series])))
    s = dict(u=0.0, u_d=0.0, z=0.0, f=0.0, s=0.0, e=0.0, k=0.0, z_unc=0.0)
    ords = []
    for p in series:
        z_inj, _, _ = _z_at(rows, p["f"], tolerance_hz, interpolate)
        z_fault, z_d, i_f = p["z_fault"], p["z_d"], p["i_f"]
        if not (np.isfinite(z_inj) and z_inj > 0 and np.isfinite(z_fault) and np.isfinite(i_f) and i_f > 0):
            continue
        ks = k_s.get(p["m"])
        r_s = abs(1.0 - ks) if ks is not None else np.nan
        ords.append(p["m"])
        w = (z_inj * i_f) ** 2
        s["u"] += (z_fault * i_f) ** 2
        s["u_d"] += (z_d * i_f) ** 2 if np.isfinite(z_d) else np.nan
        s["z"] += w
        s["f"] += i_f ** 2
        s["s"] += (r_s * z_inj * i_f) ** 2 if np.isfinite(r_s) else np.nan
        s["e"] += (r_s * i_f) ** 2 if np.isfinite(r_s) else np.nan
        s["k"] += (abs(ks) * i_f) ** 2 if ks is not None else np.nan
        if p["uncertain"]:
            s["z_unc"] += w
    if not ords:
        return None
    f1 = next((p["f"] for p in series if p["m"] == 1), 50.0)
    z50, _, _ = _z_at(rows, f1, tolerance_hz, False)
    r_b = np.nan
    if sp is not None and not sp.empty and "rZE_RMS_Ohm" in sp and np.isfinite(z50) and z50 > 0:
        line = sp[sp["channel"] == series[0]["probe"]]
        if not line.empty:
            r_b = float(line["rZE_RMS_Ohm"].iloc[0]) / z50
    f_eff = math.sqrt(s["f"])
    with_s = bool(k_s) and np.isfinite(s["s"]) and s["s"] > 0
    r_eff = math.sqrt(s["u"] / s["z"])
    r_eff_s = math.sqrt(s["s"] / s["z"]) if with_s else np.nan
    return dict(channel=channel, probe=series[0]["probe"], distance_fault_m=series[0]["distance"], injection_id=mid,
                distance_injection_m=d_inj, distance_match=comparison, orders=", ".join(str(m) for m in ords),
                I_F_coverage_pct=100.0 * s["f"] / i_f_all ** 2 if i_f_all > 0 else np.nan,
                UE_per_A_fault_eff=math.sqrt(s["u"]) / f_eff, UE_per_A_injection_eff=math.sqrt(s["z"]) / f_eff,
                r_eff=r_eff, r_eff_direct=math.sqrt(s["u_d"] / s["z"]) if np.isfinite(s["u_d"]) else np.nan,
                r_eff_rms=r_b, r_eff_shield=r_eff_s,
                share_shield_eff=math.sqrt(s["k"]) / f_eff if bool(k_s) and np.isfinite(s["k"]) else np.nan,
                UE_per_A_earth_current_eff=math.sqrt(s["u"] / s["e"]) if with_s and s["e"] > 0 else np.nan,
                Z_E_fault_to_injection_eff=r_eff / r_eff_s if with_s else np.nan,
                uncertain_share_pct=100.0 * s["z_unc"] / s["z"])


def _classify(g: pd.DataFrame, r_typical: Optional[Tuple[float, float]]) -> dict:
    """Classification of the rows of one probe against one earthing measurement: reduction factor at 50 Hz against
    the typical range of the user (None: no classification, only ``"implausible"``) and its trend over the frequency.
    Trend: regression line log r over log f at the reliable orders (earthing measurement measured at this frequency,
    fault-test value not uncertain; with fewer than two of them all orders with r)."""
    low, high = r_typical if r_typical is not None else (np.nan, np.nan)
    out = dict(r_50Hz=np.nan, Z_E_fault_50Hz_Ohm=np.nan, Z_E_injection_50Hz_Ohm=np.nan,
               classification_r_50Hz="–", r_typical_min=float(low), r_typical_max=float(high),
               trend_r_vs_f="–", exponent_r_vs_f=np.nan, exponent_Z_fault=np.nan, exponent_Z_injection=np.nan,
               trend_orders="")
    if g.empty:
        return out
    r = pd.to_numeric(g["r"], errors="coerce")
    g1 = g[(g["order"] == 1) & np.isfinite(r)]
    if len(g1):
        x = g1.iloc[0]
        out.update(r_50Hz=float(x["r"]), Z_E_fault_50Hz_Ohm=float(x["UE_per_A_fault"]),
                   Z_E_injection_50Hz_Ohm=float(x["UE_per_A_injection"]),
                   classification_r_50Hz=_classify_r(float(x["r"]), r_typical))
    measured = g["_measured"].map(_yes).astype(bool) if "_measured" in g else pd.Series(False, index=g.index)
    certain = ~g["uncertain"].map(_yes).astype(bool)
    choice = g[np.isfinite(r) & (r > 0) & measured & certain]
    if choice["f_Hz"].nunique() < 2:
        choice = g[np.isfinite(r) & (r > 0)]
    if choice["f_Hz"].nunique() >= 2:
        b = _exponent(choice["f_Hz"], choice["r"])
        out.update(exponent_r_vs_f=b,
                   exponent_Z_fault=_exponent(choice["f_Hz"], choice["UE_per_A_fault"]),
                   exponent_Z_injection=_exponent(choice["f_Hz"], choice["UE_per_A_injection"]),
                   trend_orders=", ".join(str(int(m)) for m in sorted(choice["order"])),
                   trend_r_vs_f=("falling" if b <= -TREND_EXPONENT else
                                 "rising" if b >= TREND_EXPONENT else "constant"))
    return out


def reduction_factor(tables, db_response: Optional[pd.DataFrame], tolerance_hz: float = 5.0,
                     interpolate: bool = True, *, reference_current_A: Optional[float] = None,
                     F: Optional[float] = None, U_Tp: Optional[float] = None,
                     relevance_threshold_pct: float = RELEVANCE_THRESHOLD_PCT,
                     r_typical: Optional[Tuple[float, float]] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Reduction factor from the staged fault test and the earthing measurement of the same station.

    1. Normalise the earth potential rise to 1 A: fault test ΔU_E,m/I_F,m (fault-related component, table
       ``station_frequency``), earthing measurement U_E/I_test = ``earthing_impedance`` at the same frequency
       (measured ± ``tolerance_hz`` or interpolated linearly between two measured frequencies, never
       extrapolated).
    2. r_m = |ΔU_E,m/I_F,m| / |U_E,m/I_test,m| – magnitudes only (the phasors of step 1 carry the angle, it does not
       count for r). Column ``r_to_r_50Hz``: trend over the frequency referred to 50 Hz.
    3. RMS value over all harmonics with both values (spectrally weighted with the fault current):
       r_eff = √Σ|ΔU_E,m|² / √Σ(|Z_test,m|·|I_F,m|)². Second method for comparison (``r_eff_rms``): RMS values as
       measured (U_E,eff/I_F,eff in the max window, table ``station_voltages``) divided by |Z_test| at 50 Hz – it
       contains the background and assumes a frequency-independent earthing impedance.
    4. Cross-check from the shield current (if measured): share |ΔI_S,m|/|I_F,m| and
       r_S,m = |I_F,m − ΔI_S,m|/|I_F,m| – valid only if the shield-current channels capture all return
       conductors. With it, Z_E from the fault test with the earth current (``UE_per_A_earth_current`` =
       |ΔU_E|/|I_E|, I_E = I_F − I_S) and its ratio to the earthing measurement (``Z_E_fault_to_injection`` =
       r/r_S; 1 = both methods agree, smaller = earthing measurement higher, e.g. a methodological error of the
       fall-of-potential method).

    Parameters
    ----------
    tables : Result or dict
        Result of a station evaluation or its tables (``res.tables``: ``station_frequency``, optionally
        ``station_currents_frequency`` and ``station_voltages``). With a result, the reference current, U_Tp and F
        default to its settings (``ires_limits``, ``u_tp``, ``f_factor``).
    db_response : pandas.DataFrame or None
        Values from groundmeas ([`frequency_response`][groundfault.earthing.frequency_response]); the rows of earthing
        measurements (``source == "injection test"``) are used.
    tolerance_hz : float
        Largest frequency difference for a measured value of the earthing measurement.
    interpolate : bool
        Interpolate the earthing measurement linearly between two measured frequencies.
    reference_current_A : float, optional
        Reference current for the assessment in A, defined by the user; default: the largest limit ``ires_limits``
        of the evaluation settings.
    F : float, optional
        Factor F of the limit F·U_Tp, defined by the user; default: ``f_factor`` of the evaluation settings.
    U_Tp : float, optional
        Permissible touch voltage in V, defined by the user; default: ``u_tp`` of the evaluation settings.
    relevance_threshold_pct : float
        Deviation in % of F·U_Tp below which it is negligible for the assessment.
    r_typical : (float, float), optional
        Range (low, high) of the reduction factor at 50 Hz that the user expects as typical, e.g. from their own
        experience with comparable installations. None (default): no classification.

    Returns
    -------
    spectrum, effective : pandas.DataFrame
        ``spectrum``: one row per probe, earthing measurement and harmonic order – ``r``, ``r_direct``,
        ``r_to_r_50Hz``, ``injection_frequency`` (how the value of the earthing measurement was obtained: measured
        at …/interpolated …), ``share_shield``, ``r_shield``, ``UE_per_A_earth_current``,
        ``Z_E_fault_to_injection``, the voltages at the reference current and ``assessment_relevance_pct`` per
        order. ``effective``: one row per probe and earthing measurement with the RMS values (``r_eff``,
        ``r_eff_direct``, ``r_eff_rms``, ``r_eff_shield`` …), the classification, the trend and the relevance for
        the assessment with the parameters used (``reference_current_A``, ``U_Tp_V``, ``F_factor``,
        ``F_times_U_Tp_V``; see Notes). Both are empty without a station evaluation, probes or an earthing measurement.

    Raises
    ------
    ValueError
        If ``r_typical`` is not a pair (low, high) with 0 ≤ low < high.

    Notes
    -----
    **Which probe:** rows with ``channel`` = ``max(UE)``
    ([`groundfault.station.MAX_PROBE`][groundfault.station.MAX_PROBE]) compare the probe maximum of the fault test – per
    order the highest voltage of all probes against the station earth (column ``probe``), in the effective table the
    probe with the highest RMS value – with the farthest probe of each earthing measurement: the potentials spread
    differently in the fault test and at the injection, and every probe measures at most the full earth potential rise
    (U_E,fault = max(all U_E)). These rows are the result. In addition, every earth-potential probe (``u_e``) is
    compared with the probe of comparable distance of each earthing measurement (column ``distance_match``: ``"equal"``,
    ``"similar"`` or ``"different"``).

    **Classification** (effective table): r at 50 Hz against the range ``r_typical`` given by the user –
    ``classification_r_50Hz`` is ``"below"``, ``"typical"``, ``"above"``, ``"implausible"`` (above
    [`R_IMPLAUSIBLE`][groundfault.earthing.R_IMPLAUSIBLE], also without a range) or ``"–"`` (no range given); the
    range used is in ``r_typical_min`` and ``r_typical_max``. Trend over the frequency as the exponent b in r ∝ f^b (``exponent_r_vs_f``,
    likewise for both impedances), fitted at the reliable orders (``trend_orders``: earthing measurement measured at
    that frequency, fault-test value not uncertain; with fewer than two of them all orders with r) – ``trend_r_vs_f`` is
    ``"falling"`` (b ≤ −[`TREND_EXPONENT`][groundfault.earthing.TREND_EXPONENT]; expected, because the inductive
    coupling of the return conductors increases with the frequency, f → ∞: r → 0), ``"constant"``, ``"rising"`` or
    ``"–"``.

    **Relevance for the assessment:** with small impedances relative deviations look large, while the assessment of
    the earthing system depends on the voltage. Both impedances are therefore converted to the reference current
    with the measured spectrum of the fault current (U_E at I_ref), and their difference is referred to F·U_Tp
    (``assessment_relevance_pct``). ``assessment_relevance`` is ``"negligible"`` (below ``relevance_threshold_pct``),
    ``"unchanged"`` (both earth potential rises on the same side of F·U_Tp), ``"relevant"`` (one above, one below)
    or ``"–"``. Without a reference current, U_Tp or F (groundfault has no defaults for them) these columns are NaN
    and ``"–"``; [`reduction_hints`][groundfault.earthing.reduction_hints] names the missing parameters.

    For the touch voltage alone the ratio is not a reduction factor (compare it with
    [`compare`][groundfault.earthing.compare]).
    """
    tab, settings_ = _source_tables(tables)
    sf = tab.get("station_frequency")
    empty = (pd.DataFrame(), pd.DataFrame())
    if sf is None or sf.empty or db_response is None or db_response.empty:
        return empty
    inj = db_response[db_response["source"] == SOURCE_INJECTION]
    probes = sf[sf["role"].isin(["u_e", "u_t"])]
    if inj.empty or probes.empty:
        return empty
    r_typical = _check_r_typical(r_typical)
    i_ref, u_tp, f_ = _reference_values(settings_, reference_current_A, U_Tp, F)
    limit_ = f_ * u_tp                                          # NaN if U_Tp or F is not given
    sp = tab.get("station_voltages")
    kw = dict(k_s=_shield_ratio(tab.get("station_currents_frequency")), tolerance_hz=tolerance_hz,
              interpolate=interpolate)
    spec, eff = [], []
    series_max = _max_series(probes)
    for mid, (rows, d_inj, comparison) in _farthest_injection(inj).items():
        spec += _rf_spectrum(MAX_PROBE, series_max, mid, rows, d_inj, comparison, reference_current=i_ref,
                             limit_=limit_, **kw)
        cand = [_rf_effective(MAX_PROBE, _probe_series(g), mid, rows, d_inj, comparison, sp, **kw)
                for _, g in probes.groupby("channel", sort=False)]
        cand = [e for e in cand if e is not None]
        if cand:
            eff.append(max(cand, key=lambda e: e["UE_per_A_fault_eff"]))
    for channel, g in sf[sf["role"] == "u_e"].groupby("channel", sort=False):
        series = _probe_series(g)
        for mid, (rows, d_inj, comparison) in _injection_probes(inj, series[0]["distance"], False).items():
            spec += _rf_spectrum(channel, series, mid, rows, d_inj, comparison, reference_current=i_ref,
                                 limit_=limit_, **kw)
            e = _rf_effective(channel, series, mid, rows, d_inj, comparison, sp, **kw)
            if e is not None:
                eff.append(e)
    spec = pd.DataFrame(spec)
    for e in eff:
        g = spec[(spec["channel"] == e["channel"]) & (spec["injection_id"] == e["injection_id"])]
        e.update(_classify(g, r_typical))
        u_f, u_m = e["UE_per_A_fault_eff"] * i_ref, e["UE_per_A_injection_eff"] * i_ref
        p, step_ = _relevance(u_f, u_m, limit_, relevance_threshold_pct)
        e.update(reference_current_A=i_ref, U_E_fault_at_reference_current_V=u_f,
                 U_E_injection_at_reference_current_V=u_m, deviation_at_reference_current_V=u_m - u_f,
                 U_Tp_V=u_tp, F_factor=f_, F_times_U_Tp_V=limit_, assessment_relevance_pct=p,
                 assessment_relevance=step_)
    return spec.drop(columns=["_measured"], errors="ignore"), pd.DataFrame(eff)


def check_lv_network(tables, db_response: Optional[pd.DataFrame], tolerance_hz: float = 5.0,
                     interpolate: bool = True, injection_uncertainty_pct: float = 5.0
                     ) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Earthing impedance of the LV network compared with the earthing measurement.

    The plausibility check of the parallel connection is made in the station evaluation against the fault test
    itself (|Z_E,LV| ≥ |max(U_E)/I_F|, table ``station_lv_network``, column ``parallel_check`` – taken over here);
    it depends on the currents only. In addition, this function compares with the earthing measurement (Z_E): as a
    parallel branch of the total earthing, |Z_E,LV| ≥ |Z_E| must hold if both methods measure the same earthing
    system correctly (column ``injection_comparison``: ``"satisfied"``, ``"borderline"`` – within the uncertainty –
    or ``"below"``). If the check against the fault test is satisfied but the comparison with the earthing
    measurement is not, the contradiction lies with the earthing measurement (measured value too high, different
    switching state) – a finding, not an error of the LV-network evaluation.

    Parameters
    ----------
    tables : Result or dict
        Result of a station evaluation or its tables (``station_lv_network``).
    db_response : pandas.DataFrame or None
        Values from groundmeas ([`frequency_response`][groundfault.earthing.frequency_response]).
    tolerance_hz : float
        Largest frequency difference for a measured value of the earthing measurement.
    interpolate : bool
        Interpolate the earthing measurement linearly between two measured frequencies.
    injection_uncertainty_pct : float
        Estimated uncertainty of the earthing measurement in %.

    Returns
    -------
    per_order, effective : pandas.DataFrame
        ``per_order``: one row per probe, earthing measurement and order (``Z_E_LV_Ohm``, ``Z_E_injection_Ohm``,
        ``injection_frequency``, ``Z_LV_to_Z_E``, ``injection_comparison``, ``comparison_uncertainty_pct``,
        ``Z_E_fault_Ohm``, ``parallel_check``, ``uncertain``). ``effective``: RMS values per probe and earthing
        measurement (``Z_E_LV_eff_Ohm``, ``Z_E_injection_eff_Ohm``, ``Z_LV_to_Z_E_eff``, ``injection_comparison``:
        ``"satisfied"`` or ``"below (see orders)"``). Both are empty without the LV-network table or an earthing
        measurement.

    Notes
    -----
    Compared are the probe maximum (``channel`` = ``max(UE)``) with the farthest probe of each earthing measurement and
    every earth-potential probe with the probe of comparable distance (as in
    [`reduction_factor`][groundfault.earthing.reduction_factor]). The comparison counts as ``"below"`` only if
    |Z_E,LV|/|Z_E| is below 1 by more than the estimated uncertainty (the uncertainty of the LV-network value and
    ``injection_uncertainty_pct`` added in quadrature). RMS value: Z_E,LV,eff = √Σ|ΔU_E,m|²/√Σ|I_LV,m|² against
    √Σ(|Z_E,m|·|I_LV,m|)²/√Σ|I_LV,m|² (the same current spectrum).
    """
    tab, _ = _source_tables(tables)
    so = tab.get("station_lv_network")
    empty = (pd.DataFrame(), pd.DataFrame())
    if so is None or so.empty or db_response is None or db_response.empty:
        return empty
    inj = db_response[db_response["source"] == SOURCE_INJECTION]
    if inj.empty:
        return empty
    rows_from, eff = [], []
    for channel, g in so.groupby("channel", sort=False):
        dist = _distance(g["distance_m"].iloc[0])
        pairs = _farthest_injection(inj) if channel == MAX_PROBE else _injection_probes(inj, dist, False)
        for mid, (rows, d_inj, comparison) in pairs.items():
            s_u = s_lv = s_z = 0.0
            ords = []
            for _, r in g.sort_values("order").iterrows():
                f = float(r["f_Hz"])
                z_inj, origin, _ = _z_at(rows, f, tolerance_hz, interpolate)
                z_lv = _num_(r.get("Z_E_LV_Ohm"))
                u_lv = _num_(r.get("Z_E_LV_uncertainty_pct"))
                u = math.sqrt((u_lv if np.isfinite(u_lv) else 0.0) ** 2 + injection_uncertainty_pct ** 2)
                rat = z_lv / z_inj if np.isfinite(z_lv) and np.isfinite(z_inj) and z_inj > 0 else np.nan
                if not np.isfinite(rat):
                    status = "–"
                elif rat >= 1.0:
                    status = "satisfied"
                elif 100.0 * (1.0 - rat) <= u:
                    status = "borderline"
                else:
                    status = "below"
                rows_from.append(dict(channel=channel, probe=r.get("probe", channel), distance_fault_m=_distance(
                    r.get("distance_m")), injection_id=mid, distance_injection_m=d_inj,
                    distance_match=comparison, order=int(r["order"]), f_Hz=f, Z_E_LV_Ohm=z_lv,
                    Z_E_injection_Ohm=z_inj, injection_frequency=origin, Z_LV_to_Z_E=rat,
                    injection_comparison=status, comparison_uncertainty_pct=u,
                    Z_E_fault_Ohm=_num_(r.get("Z_E_fault_Ohm")),
                    parallel_check=r.get("parallel_check", "–"),
                    uncertain=_yes(r.get("uncertain"))))
                i_lv = _num_(r.get("I_LV_A"))
                du = _num_(r.get("U_E_fault_V"))
                if np.isfinite(rat) and np.isfinite(i_lv) and np.isfinite(du):
                    ords.append(int(r["order"]))
                    s_u += du ** 2; s_lv += i_lv ** 2; s_z += (z_inj * i_lv) ** 2
            if ords and s_lv > 0:
                z_lv_eff, z_e_eff = math.sqrt(s_u / s_lv), math.sqrt(s_z / s_lv)
                rat = z_lv_eff / z_e_eff if z_e_eff > 0 else np.nan
                probes = sorted({str(x) for x in g["probe"].dropna()}) if "probe" in g else [channel]
                eff.append(dict(channel=channel, probe=", ".join(probes), distance_fault_m=dist, injection_id=mid,
                                distance_injection_m=d_inj, distance_match=comparison,
                                orders=", ".join(str(m) for m in ords), Z_E_LV_eff_Ohm=z_lv_eff,
                                Z_E_injection_eff_Ohm=z_e_eff, Z_LV_to_Z_E_eff=rat,
                                injection_comparison=("satisfied" if rat >= 1.0 else "below (see orders)")
                                if np.isfinite(rat) else "–"))
    return pd.DataFrame(rows_from), pd.DataFrame(eff)


def _main_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Rows for hints and figures: the probe maximum, otherwise the probes of comparable distance, otherwise all."""
    if "channel" in df and (df["channel"] == MAX_PROBE).any():
        return df[df["channel"] == MAX_PROBE]
    return _remote_probes_df(df)


def _label(r) -> str:
    """“probe maximum (UE_10m) ↔ earthing measurement ID 3 (40 m)” or “UE_40m ↔ earthing measurement ID 3 (40 m)”
    in the active language."""
    try:
        mid = "ID %d" % int(r.get("injection_id"))
    except (TypeError, ValueError):
        mid = ""
    d = _num_(r.get("distance_injection_m"))
    left = (tr("earthing.label_probe_maximum", probe=r.get("probe", "")) if r.get("channel") == MAX_PROBE
            else str(r.get("channel", "")))
    return tr("earthing.label_pair", left=left, id=mid, distance=" (%s m)" % _number(d) if np.isfinite(d) else "")


def _assessment_text(r) -> str:
    """Sentence on the relevance of the deviation for the assessment (from an effective row of
    [`reduction_factor`][groundfault.earthing.reduction_factor]); empty without a relevance code."""
    step_ = r.get("assessment_relevance")
    if not isinstance(step_, str) or step_ == "–":
        return ""
    i, u_f, u_m = (_num_(r.get(k)) for k in ("reference_current_A", "U_E_fault_at_reference_current_V",
                                             "U_E_injection_at_reference_current_V"))
    limit_, p = _num_(r.get("F_times_U_Tp_V")), _num_(r.get("assessment_relevance_pct"))
    s = tr("earthing.assessment", current=_number(i), u_fault=_number(u_f, 2), u_injection=_number(u_m, 2),
           deviation=_number(abs(u_m - u_f), 2), share=_number(p, 2), limit=_number(limit_))
    if step_ == "negligible":
        return s + tr("earthing.assessment_negligible")
    if step_ == "unchanged":
        return s + tr("earthing.assessment_unchanged_below" if u_m <= limit_ else "earthing.assessment_unchanged_above")
    return s + tr("earthing.assessment_relevant")


def _typical_range(r) -> Optional[Tuple[str, str]]:
    """Typical range of r of an effective row as text (columns ``r_typical_min``/``r_typical_max``); None if the row
    names no range (no range given, or an older table without these columns)."""
    low, high = _num_(r.get("r_typical_min")), _num_(r.get("r_typical_max"))
    if not (np.isfinite(low) and np.isfinite(high)):
        return None
    return _number(low, 2), _number(high, 2)


#: parameters of the relevance for the assessment: column of the effective table → argument of reduction_factor
_RELEVANCE_PARAMETERS = (("reference_current_A", "reference_current_A"), ("U_Tp_V", "U_Tp"), ("F_factor", "F"))


def _missing_parameters(rows: pd.DataFrame) -> List[str]:
    """Arguments of [`reduction_factor`][groundfault.earthing.reduction_factor] that were not given for rows with a
    reduction factor (NaN in the columns of the parameters; older tables: ``F_times_U_Tp_V`` → U_Tp and F)."""
    if "r_eff" in rows:
        rows = rows[np.isfinite(pd.to_numeric(rows["r_eff"], errors="coerce"))]
    if rows.empty:
        return []
    missing = []
    for column, name in _RELEVANCE_PARAMETERS:
        if column in rows and pd.to_numeric(rows[column], errors="coerce").isna().any():
            missing.append(name)
    if "U_Tp_V" not in rows and "F_times_U_Tp_V" in rows and \
            pd.to_numeric(rows["F_times_U_Tp_V"], errors="coerce").isna().any():
        missing += ["U_Tp", "F"]
    return missing


def reduction_hints(reduction_eff: Optional[pd.DataFrame] = None,
                    lv_check: Optional[pd.DataFrame] = None) -> list:
    """Hints on [`reduction_factor`][groundfault.earthing.reduction_factor] and
    [`check_lv_network`][groundfault.earthing.check_lv_network] (for notebook and report).

    The hints refer to the probe maximum (otherwise to the probes of comparable distance):

    * r at 50 Hz outside the typical range given by the user (``r_typical`` of
      [`reduction_factor`][groundfault.earthing.reduction_factor]; no hint without a range) – below: earthing
      measurement probably too high (methodological error of the fall-of-potential method) or further return paths;
      above: little reduction, e.g. shield interrupted; above 1: implausible – each with the relevance of the deviation
      for the assessment (voltage at the reference current against F·U_Tp); within the typical range only if the
      deviation is relevant for the assessment;
    * the relevance for the assessment not determined: the missing parameters (reference current, U_Tp, F), once;
    * r rises with the frequency (a decrease is expected);
    * shield current almost zero (possible causes), or r from the earth potential rise and from the shield current
      differ by more than the factor [`METHOD_FACTOR`][groundfault.earthing.METHOD_FACTOR];
    * Z_E,LV below the earthing impedance of the earthing measurement – with the result of the check against the
      fault test.

    Parameters
    ----------
    reduction_eff : pandas.DataFrame, optional
        Effective table of [`reduction_factor`][groundfault.earthing.reduction_factor]. Tables of older notebooks
        without the newer columns are accepted (the shield-current share is then approximated from r_S).
    lv_check : pandas.DataFrame, optional
        Per-order table of [`check_lv_network`][groundfault.earthing.check_lv_network] (or an older table with
        ``parallel_check`` only).

    Returns
    -------
    list of str
        Hints in the active language.
    """
    out = []
    if reduction_eff is not None and len(reduction_eff):
        missing = _missing_parameters(_main_rows(reduction_eff))
        if missing:
            out.append(tr("earthing.relevance_not_determined", missing=", ".join(missing)))
        for _, r in _main_rows(reduction_eff).iterrows():
            name = _label(r)
            r50, classification = _num_(r.get("r_50Hz")), r.get("classification_r_50Hz", "–")
            range_ = _typical_range(r)
            if range_ is None and classification in ("below", "above"):
                classification = "–"                  # no range in the row: no hint about the range
            low, high = range_ or ("–", "–")
            assess = _assessment_text(r)
            z_f, z_m = _num_(r.get("Z_E_fault_50Hz_Ohm")), _num_(r.get("Z_E_injection_50Hz_Ohm"))
            values = tr("earthing.z_values", quantity="max(U_E)" if r.get("channel") == MAX_PROBE else "U_E",
                        z_fault=_number(z_f), z_injection=_number(z_m))
            if classification == "below":
                out.append(tr("earthing.hint_r_below", name=name, r=_number(r50, 2), low=low, high=high,
                              values=values, assessment=assess))
            elif classification == "above":
                out.append(tr("earthing.hint_r_above", name=name, r=_number(r50, 2), low=low, high=high,
                              values=values, assessment=assess))
            elif classification == "implausible":
                out.append(tr("earthing.hint_r_implausible", name=name, r=_number(r50, 2), values=values,
                              assessment=assess))
            elif r.get("assessment_relevance") == "relevant":
                out.append(tr("earthing.hint_relevant", name=name, assessment=assess))
            if r.get("trend_r_vs_f") == "rising":
                out.append(tr("earthing.hint_r_rising", name=name, exponent=_number(r.get("exponent_r_vs_f"), 2),
                              orders=r.get("trend_orders", "")))
            a, b = _num_(r.get("r_eff")), _num_(r.get("r_eff_shield"))
            share = _num_(r.get("share_shield_eff"))
            if not np.isfinite(share) and np.isfinite(b):
                share = max(0.0, 1.0 - b)                           # older tables: approximation from r_S
            if np.isfinite(share) and share < SHIELD_SMALL:
                txt = tr("earthing.hint_shield_zero", share=_number(100 * share, 2), r_shield=_number(b, 2))
                if np.isfinite(a) and np.isfinite(b) and a > 0 and b / a > METHOD_FACTOR:
                    txt += " " + tr("earthing.hint_shield_zero_epr", r_eff=_number(a))
                out.append(txt)
            elif np.isfinite(a) and np.isfinite(b) and a > 0 and b > 0 and max(a / b, b / a) > METHOD_FACTOR:
                cause = tr("earthing.cause_more_return_paths" if a < b else "earthing.cause_shield_measures_more")
                out.append(tr("earthing.hint_methods_differ", name=name, r_eff=_number(a), r_shield=_number(b),
                              ratio=_number(a / b, 2), cause=cause))
    if lv_check is not None and len(lv_check):
        v = _main_rows(lv_check)
        column = "injection_comparison" if "injection_comparison" in v else "parallel_check"
        below_ = v[v[column].isin(["below", "violated"])]
        key = ["channel"] + (["injection_id"] if "injection_id" in v else [])
        for value, g in below_.groupby(key, sort=False):
            value = value if isinstance(value, tuple) else (value,)
            all_ = v[np.logical_and.reduce([v[k] == x for k, x in zip(key, value)])]
            r1 = all_[all_["order"] == 1] if "order" in all_ else all_.iloc[0:0]
            x = (r1 if len(r1) else g).iloc[0]
            values = tr("earthing.lv_values", f=_number(round(x["f_Hz"])), z_lv=_number(x.get("Z_E_LV_Ohm")),
                        z_injection=_number(x.get("Z_E_injection_Ohm")))
            txt = tr("earthing.hint_lv_below", name=_label(x),
                     frequencies=", ".join("%g" % round(f) for f in sorted(g["f_Hz"])), values=values)
            pe = all_["parallel_check"] if "parallel_check" in all_ and \
                column == "injection_comparison" else pd.Series(dtype=object)
            if len(pe) and (pe == "violated").any():
                txt += " " + tr("earthing.hint_lv_violated")
            elif len(pe) and pe.isin(["satisfied", "borderline"]).all():
                txt += " " + tr("earthing.hint_lv_satisfied")
            else:
                txt += " " + tr("earthing.hint_lv_causes")
            out.append(txt)
    return out


def _remote_probes_df(df: pd.DataFrame) -> pd.DataFrame:
    """Rows with a comparable probe distance (``"equal"``/``"similar"``); all rows if there are none."""
    if "distance_match" not in df:
        return df
    remote = df[df["distance_match"].isin(["equal", "similar"])]
    return remote if len(remote) else df


def _num_(x) -> float:
    """Float of a table cell; NaN if it is not a number."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


# ---------------------------------------------------------------------------------------------- export
ASSET_TYPES = ("substation", "overhead_line_tower", "cable", "cable_cabinet", "house", "pole_mounted_transformer",
               "mv_lv_earthing_system")
"""Allowed ``asset_type`` values of groundmeas (core/models.py, AssetType)."""
UNCERTAIN_MODES = ("mark", "omit")
"""Values of ``uncertain_mode``: ``"mark"`` enters uncertain fault-related values with a remark, ``"omit"`` leaves
them out."""
UNIT_CHOICES = ("suitable", "base")
"""Values of ``units``: ``"suitable"`` writes a well readable unit per measurement type (mV, mA …), ``"base"`` the
base units (V, A)."""
EXISTING = ("skip", "replace")
"""Values of ``existing`` when an entry of the same recording is in groundmeas: ``"skip"`` it, or ``"replace"``
(renew) an own entry."""
COORDINATE_TOLERANCE_M = 100.0
"""Distance in m between the coordinates of the sites file and of the groundmeas location from which a warning is
given."""
ORDER_MAX = 25
"""Highest order of the fault current in a substation entry (as in the station)."""

TAG_PREFIX = "groundfault"
"""Prefix of the tag at the end of the description of own entries."""
LEGACY_TAG_PREFIX = "erdschluss"
"""Tag prefix of entries made by the predecessor tool (recognised as own)."""


def entry_tag(campaign, measurement, prefix: str = TAG_PREFIX) -> str:
    """Tag of an entry made by this package, placed at the end of its description.

    Own entries are recognised by the tag: they are not entered twice, renewed on request and hidden in comparisons.
    Entries of the predecessor tool (``[erdschluss …]``) count as own entries as well (see
    [`entry_tags`][groundfault.earthing.entry_tags]).

    Parameters
    ----------
    campaign, measurement : str
        Campaign and measurement name (``"-"`` if empty).
    prefix : str
        Tag prefix.

    Returns
    -------
    str
        e.g. ``[groundfault 2026-01-15_Demo/Station_Elm_Road_10_000kHz]``.
    """
    return "[%s %s/%s]" % (prefix, campaign or "-", measurement or "-")


def entry_tags(campaign, measurement) -> tuple:
    """Current and legacy tag of a recording (see [`entry_tag`][groundfault.earthing.entry_tag])."""
    return tuple(entry_tag(campaign, measurement, p) for p in (TAG_PREFIX, LEGACY_TAG_PREFIX))


def _key(s) -> str:
    """Name key: lower case, umlauts as ae/oe/ue, underscores and repeated blanks as one blank."""
    return re.sub(r"\s+", " ", _norm_umlaut(str(s)).lower().replace("_", " ")).strip()


def _geo_distance_m(b1, l1, b2, l2) -> float:
    """Distance between two WGS84 points in m (haversine formula, earth radius 6371 km)."""
    p1, p2 = math.radians(b1), math.radians(b2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(l2 - l1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(min(1.0, math.sqrt(a)))


def location_rows(con, name: str) -> list:
    """All location rows in groundmeas with this name, the best suited first.

    groundmeas creates a location row of its own with every new measurement, so one place can have several rows.
    Names are compared ignoring case and with umlauts written as ae/oe/ue.

    Parameters
    ----------
    con : sqlite3.Connection
        Connection to the groundmeas database.
    name : str
        Location name.

    Returns
    -------
    list of dict
        ``id``, ``name``, ``latitude``, ``longitude``, ``coordinates`` (both given), ``exact`` (same spelling),
        ``injection`` (an earthing measurement with current injection belongs to the row), ``last`` (latest
        timestamp of those measurements, otherwise of all measurements of the row) and ``all_ids`` (ids of all rows
        with the name). Sorted by suitability for a new entry: with coordinates before without, same spelling,
        location of an earthing measurement, latest measurement, latest row – so the fault test appears in the
        dashboard at the same map point as the earthing measurement. Empty if the name is not found.
    """
    k = _key(name)
    if not k:
        return []
    locations = [r for r in con.execute("select id, name, latitude, longitude from location") if _key(r[1]) == k]
    if not locations:
        return []
    ids = [int(r[0]) for r in locations]
    meas = con.execute("select location_id, method, timestamp from measurement where location_id in (%s)"
                       % ",".join("?" * len(ids)), ids).fetchall()
    rows = []
    for oid, oname, b, l in locations:
        m = [x for x in meas if x[0] == oid]
        inj = [x for x in m if str(x[1]).startswith("injection")]
        rows.append(dict(id=int(oid), name=oname, latitude=b, longitude=l, coordinates=b is not None and l is not None,
                         exact=oname == name, injection=bool(inj),
                         last=max((str(x[2]) for x in (inj or m)), default=""), all_ids=ids))
    rows.sort(key=lambda z: (z["coordinates"], z["exact"], z["injection"], z["last"], z["id"]), reverse=True)
    return rows


def _data(result) -> dict:
    """Content of the result file (``data`` of a loaded file or ``result_set`` of a result)."""
    return getattr(result, "data", None) or getattr(result, "result_set", None) or {}


def _f_nominal(result) -> float:
    """Nominal frequency of the evaluation (50 Hz if not set)."""
    try:
        return float(getattr(getattr(result, "settings", None), "f_nominal", 50.0) or 50.0)
    except (TypeError, ValueError):
        return 50.0


def _finite(x) -> bool:
    """True for a finite number."""
    try:
        return x is not None and np.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _measured_value(result, quantity: str) -> float:
    """Measured value of an assessment quantity (``IRES``, ``Iw`` …) of the result; NaN if missing."""
    b = (getattr(result, "tables", None) or {}).get("assessment_quantities")
    if b is None or b.empty or "quantity" not in b:
        return float("nan")
    z = b[b["quantity"] == quantity]
    return float(z["measured_value"].iloc[0]) if len(z) else float("nan")


def _main_ires_channel(result) -> str:
    """Name of the main channel of the residual current (``""`` if unknown)."""
    w = getattr(result, "values", None) or {}
    k = w.get("main_channel_i_res")
    return k if isinstance(k, str) else ""


def _significant(x: float, digits: int = 6) -> float:
    """Value rounded to ``digits`` significant digits."""
    return float("%.*g" % (digits, x)) if x and math.isfinite(x) else x


def _set_units(items, choice: str) -> Dict[str, str]:
    """Set one unit per measurement type (the values come in V and A): ``"suitable"`` = a well readable unit per type
    ([`groundfault.units.suitable_unit`][groundfault.units.suitable_unit]), ``"base"`` = base unit. → {type: unit}"""
    out = {}
    for type_ in dict.fromkeys(it["measurement_type"] for it in items):
        group = [it for it in items if it["measurement_type"] == type_]
        if choice == "suitable":
            symbol, f = _units.suitable_unit([it["value"] for it in group], type_)
        else:
            symbol, f = _units.base_unit(type_), 1.0
        for it in group:
            it["value"] = _significant(it["value"] / f)
            it["unit"] = symbol
        out[type_] = symbol
    return out


def _pct(x) -> str:
    """Percentage for the English item descriptions (``"49 %"``, ``"0.3 %"``, ``"< 0.1 %"``)."""
    x = float(x)
    return "%.0f %%" % x if x >= 1 else ("%.1f %%" % x if x >= 0.1 else "< 0.1 %")


def _station_items(result, sf, method, f_nominal, uncertain_mode, distance_):
    """Items of a station measurement → (items, uncertain frequencies, number omitted). The item descriptions are
    database content and stay English."""
    column = "Z_%s_Ohm" % method
    channel = _main_ires_channel(result)
    items, uncertain_f, removed = [], [], 0
    first = sf.drop_duplicates("order")
    for _, r in first.iterrows():
        items.append(dict(measurement_type="earth_fault_current", value=float(r["I_F_A"]), value_angle_deg=0.0,
                          unit="A", frequency_hz=int(r["order"]) * f_nominal, distance_to_current_injection_m=distance_,
                          description="earth fault current at the station%s; angle reference"
                                      % (" (channel %s)" % channel if channel else "")))
    for _, r in sf.iterrows():
        z, ang = r.get(column, np.nan), r.get("Z_%s_angle_deg" % method, np.nan)
        if not _finite(z):
            continue
        m = int(r["order"])
        dist = _distance(r.get("distance_m"))
        touch = r["role"] == "u_t" and not (np.isfinite(dist) and dist > 1.5)
        unc = method == "fault" and _yes(r.get("uncertain"))
        if unc:
            uncertain_f.append(m * f_nominal)
            if uncertain_mode == "omit":
                removed += 1
                continue
        text = "probe %s (%s)" % (r["channel"], ("%g m" % dist) if np.isfinite(dist) else "distance unknown")
        if r["role"] == "u_t" and not touch:
            text += ", shortest probe (used as touch voltage approximation)"
        text += ", fault-related part" if method == "fault" else (
            ", as measured" if method == "direct" else ", method %s" % method)
        if unc:
            parts = []
            if _finite(r.get("method_spread_pct")):
                parts.append("superposition methods differ by %s" % _pct(r["method_spread_pct"]))
            if _finite(r.get("uncertainty_pct")):
                parts.append("est. uncertainty %s" % _pct(r["uncertainty_pct"]))
            text += "; UNCERTAIN" + (" (%s)" % ", ".join(parts) if parts else "")
        items.append(dict(measurement_type="prospective_touch_voltage" if touch else "earth_potential_rise",
                          value=float(z * r["I_F_A"]), value_angle_deg=float(ang) if _finite(ang) else None,
                          unit="V", frequency_hz=m * f_nominal,
                          measurement_distance_m=dist if np.isfinite(dist) else None,
                          distance_to_current_injection_m=distance_, description=text))
    items += _shield_items(result, [int(m) for m in first["order"]], f_nominal, distance_)
    return items, sorted(set(uncertain_f)), removed


def _shield_items(result, orders, f_nominal, distance_):
    """Shield current per order as measured (max window; angle relative to I_F) at the same ``orders`` as the
    voltages.

    Source: the table ``station_currents_frequency`` (all orders of the frequency-selective evaluation) with the
    polarity of the table ``station_currents`` (a reversed shield clamp is rotated by 180° there); result files
    without that table: ``station_currents``, which has the orders of ``Settings.harmonics`` only.
    """
    tables = getattr(result, "tables", None) or {}
    ss, sc = tables.get("station_currents"), tables.get("station_currents_frequency")
    polarity = {}
    if ss is not None and not ss.empty and "role" in ss and "polarity" in ss:
        polarity = {c: p for c, p in zip(ss["channel"], ss["polarity"]) if _finite(p)}
    rows = []                                                   # (channel, order, magnitude in A, angle in °)
    if sc is not None and not sc.empty and {"role", "channel", "order", "I_during_fault_A"} <= set(sc.columns):
        shield = sc[sc["role"] == "i_shield"]
        for channel in dict.fromkeys(shield["channel"]):
            g = shield[shield["channel"] == channel]
            by_order = {int(o): r for o, r in zip(g["order"], g.to_dict("records"))}
            for m in orders:
                r = by_order.get(m)
                if r is None:
                    continue
                w = r.get("share_direct_angle_deg", np.nan)
                if _finite(w) and polarity.get(channel, 1) < 0:        # rotated as in station_currents
                    w = float(np.degrees(np.angle(-np.exp(1j * np.radians(w)))))
                rows.append((channel, m, r["I_during_fault_A"], w))
    elif ss is not None and not ss.empty and "role" in ss:
        for _, r in ss[ss["role"] == "i_shield"].iterrows():
            for m in orders:
                rows.append((r["channel"], m, r.get("H%d_A" % m), r.get("angle_to_IF_H%d_deg" % m, np.nan)))
    return [dict(measurement_type="shield_current", value=float(value),
                 value_angle_deg=float(w) if _finite(w) else None, unit="A", frequency_hz=m * f_nominal,
                 distance_to_current_injection_m=distance_,
                 description="shield current %s; angle relative to I_F" % channel)
            for channel, m, value, w in rows if _finite(value)]


def _substation_items(result, f_nominal, distance_):
    """Earth fault current per order from the table ``harmonics`` (main channel i_res) → (items, channel)."""
    h = (getattr(result, "tables", None) or {}).get("harmonics")
    if h is None or h.empty or "role" not in h:
        return [], ""
    channel = _main_ires_channel(result)
    g = h[h["channel"] == channel] if channel else h.iloc[0:0]
    if g.empty:
        ires = h[h["role"] == "i_res"]
        if ires.empty:
            return [], ""
        channel = ires["channel"].iloc[0]
        g = ires[ires["channel"] == channel]
    h1 = g.loc[g["order"] == 1, "magnitude"]
    if h1.empty or not _finite(h1.iloc[0]):
        return [], channel
    threshold = max(0.1, 0.01 * float(h1.iloc[0]))            # as the station evaluation (station.frequency_selective)
    items = []
    for _, r in g.sort_values("order").iterrows():
        m = int(r["order"])
        if m > ORDER_MAX or not _finite(r["magnitude"]) or (m != 1 and float(r["magnitude"]) < threshold):
            continue
        items.append(dict(measurement_type="earth_fault_current", value=float(r["magnitude"]), value_angle_deg=0.0,
                          unit="A", frequency_hz=m * f_nominal, distance_to_current_injection_m=distance_,
                          description="earth fault current (channel %s), max. 200 ms window of the stationary fault"
                                      % channel))
    return items, channel


def _fmt_hz(fs) -> str:
    """Frequencies as text (``"50, 150"``)."""
    return ", ".join("%g" % f for f in fs)


def _description(result, kind, location, method, rf, uncertain_f, uncertain_mode, injections, channel, extra,
                 tag) -> str:
    """Description of a new groundmeas measurement (``kind`` ``"station"`` or ``"substation"``). Database content:
    always English, with the entry tag at the end."""
    d = _data(result)
    meta, measurement = d.get("meta", {}) or {}, d.get("measurement", {}) or {}
    name = meta.get("measurement") or getattr(result, "name", "")
    source = "campaign %s, recording %s" % (meta.get("campaign") or "-", name)
    parts = [extra.strip().rstrip(".") + "."] if extra and extra.strip() else []
    if kind == "station":
        meth_ = {"fault": "fault-related part (background before the fault removed by superposition)",
                 "direct": "as measured during the fault (incl. background)"}.get(method, method)
        parts.append("Staged earth fault test at %s (%s): earth fault current per harmonic order and earth potential "
                     "rise / touch voltage per probe, %s; angles relative to I_F." % (location, source, meth_))
        if uncertain_f:
            parts.append("Uncertain fault-related part at %s Hz (%s)." % (
                _fmt_hz(uncertain_f), "marked in the items" if uncertain_mode == "mark" else "omitted"))
        if injections:
            parts.append("Injection measurement%s at this site: %s." % (
                "s" if len(injections) > 1 else "", ", ".join(map(str, injections))))
    else:
        rf_txt = (", R_F = %g Ohm" % rf) if rf is not None else ""
        parts.append("Staged earth fault test at %s%s (%s): earth fault current per harmonic order (channel %s, max. "
                     "200 ms window of the stationary fault)." % (location, rf_txt, source, channel or "-"))
        values = [("I_RES", _measured_value(result, "IRES"), "A"), ("I_w", _measured_value(result, "Iw"), "A"),
                  ("I_v", _measured_value(result, "Iv"), "A")]
        txt = ", ".join("%s = %.1f %s" % (n, v, e) for n, v, e in values if np.isfinite(v))
        iv = _measured_value(result, "Iv")
        if np.isfinite(iv) and abs(iv) > 0.5:
            txt += " (%s)" % ("overcompensated" if iv > 0 else "undercompensated")
        une = _measured_value(result, "UH1n")
        if np.isfinite(une):
            txt += (", " if txt else "") + "U_NE = %.2f kV" % (une / 1000.0)
        if txt:
            parts.append(txt + ".")
    f1 = measurement.get("f1_hz")
    if _finite(f1):
        parts.append("f1 = %.3f Hz (frequencies stored as nominal harmonic frequencies)." % float(f1))
    parts.append("Evaluated with %s %s" % (meta.get("tool") or meta.get("werkzeug") or "groundfault", tag))
    return " ".join(parts)


def _groundmeas_time(text: Optional[str], timezone: Optional[str] = None) -> str:
    """Timestamp in the format of the groundmeas database (SQLAlchemy/SQLite): ``YYYY-MM-DD hh:mm:ss.ffffff``.

    ``timezone`` (e.g. ``"Europe/Berlin"``): time zone of the recorder clock – the time is then converted to UTC (as
    groundmeas stores new entries). Without it the time of the COMTRADE file stays unchanged; without a readable
    time the current time (UTC) is used."""
    try:
        t = _dt.datetime.fromisoformat(str(text)) if text else None
    except ValueError:
        t = None
    if t is None:                                          # no timestamp: now (already UTC)
        return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f")
    if t.tzinfo is None and timezone:
        from zoneinfo import ZoneInfo
        t = t.replace(tzinfo=ZoneInfo(timezone))
    if t.tzinfo is not None:
        t = t.astimezone(_dt.timezone.utc).replace(tzinfo=None)
    return t.strftime("%Y-%m-%d %H:%M:%S.%f")


def _backup(db_path: str) -> str:
    """Backup copy next to the database (byte-identical copy; through the SQLite backup API if a WAL file
    exists) → path of the copy."""
    target_ = "%s_before_groundfault_%s.db" % (os.path.splitext(db_path)[0],
                                               _dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    wal = db_path + "-wal"
    if os.path.exists(wal) and os.path.getsize(wal) > 0:
        # sqlite3's own context manager only commits; closing() also closes both connections
        with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)) as src, \
                closing(sqlite3.connect(target_)) as dst:
            src.backup(dst)
    else:
        shutil.copy2(db_path, target_)
    return target_


def _deg(x) -> str:
    """Coordinate in degrees with five decimals (``"–"`` if missing)."""
    return ("%.5f" % float(x)) if _finite(x) else "–"


def _campaign_files(result, campaign_folder=None) -> Dict[str, str]:
    """Names of the campaign files and columns that the export hints refer to, in the folder layout of the campaign.

    The layout is detected from the campaign folder, the path of the result file or the path of the recording
    ([`groundfault.layout`][groundfault.layout]); only without such a path (or outside any campaign) the layout of the
    output language is used. Keys: ``sites`` (file name), ``sites_path`` (notes folder/file), ``coordinates``
    (latitude/longitude columns), ``distance``, ``voltage_level`` (columns of the sites file), ``corrections``,
    ``probe_distance`` (file and column of the corrections), ``register`` and ``fault_resistance`` (file and column of
    the register).
    """
    from .corrections import HEADERS as corrections_headers
    from .layout import _find_layout, get_layout
    from .register import REGISTER_COLUMNS, REGISTER_HEADERS_DE
    from .sites import HEADERS as sites_headers
    lay = None
    for p in (campaign_folder, getattr(result, "path", None),
              (getattr(result, "recording_info", None) or {}).get("path")):
        if p:
            lay = _find_layout(p)
            if lay is not None:
                break
    lay = lay or get_layout(i18n.get_language())
    s, c = sites_headers[lay.language], corrections_headers[lay.language]
    register_ = dict(zip(REGISTER_COLUMNS, REGISTER_HEADERS_DE if lay.language == "de" else REGISTER_COLUMNS))
    return dict(sites=lay.sites_file, sites_path="%s/%s" % (lay.notes, lay.sites_file),
                coordinates="%s/%s" % (s[2], s[3]), distance=s[6], voltage_level=s[5],
                corrections=lay.corrections_file, probe_distance=c[5], register=lay.register_file,
                fault_resistance=register_["fault_resistance_Ohm"])


EXPORTED_HINT_KEYS = ("evaluation.angle_atypical", "evaluation.station_failed", "station.uncertain_values",
                      "station.frequency_not_estimable_inception", "station.frequency_not_estimable_clearance",
                      "station.background_large", "station.fault_component_unavailable", "station.single_method")
"""Message keys of the evaluation hints that [`export_fault_test`][groundfault.earthing.export_fault_test] passes on as
warnings: the hints of the frequency-selective station evaluation and the atypical angle U_E/I_F. They are recognised in
either output language by [`groundfault.i18n.message_key`][groundfault.i18n.message_key]."""


def export_fault_test(db_path: str, result, location: Optional[str] = None, *, site=None,
                      method: str = "fault", asset_type: Optional[str] = None,
                      voltage_level_kv: Optional[float] = None, fault_resistance_ohm: Optional[float] = None,
                      operator: Optional[str] = None, distance_to_substation_m: Optional[float] = None,
                      latitude: Optional[float] = None, longitude: Optional[float] = None, description: str = "",
                      timezone: Optional[str] = None, timestamp: Optional[str] = None,
                      uncertain_mode: str = "mark",
                      existing: str = "skip", dry_run: bool = True, backup=True,
                      units: str = "suitable", editor: Optional[str] = None,
                      campaign_folder=None) -> Dict[str, object]:
    """Plan the export of an evaluated staged fault test as a new groundmeas measurement ``staged_fault_test`` and –
    only with ``dry_run=False`` – write it.

    **Station** (table ``station_frequency``): per order m an ``earth_fault_current`` (I_F, angle 0° = reference),
    an ``earth_potential_rise`` per earth-potential probe with its distance (``measurement_distance_m``; this also
    applies to the shortest probe > 1.5 m that serves as an approximation of the touch voltage – all probe
    distances are kept) and a ``prospective_touch_voltage`` per probe up to 1.5 m; with a shield-current measurement
    also ``shield_current``. Angles are referred to I_F. Uncertain fault-related values (column ``uncertain``) are
    entered with “UNCERTAIN …” in their description (``uncertain_mode="mark"``) or left out (``"omit"``; the fault
    current remains).

    **Substation** (no station evaluation): ``earth_fault_current`` per order (main channel, ≥ 0.1 A and ≥ 1 % of
    H1, up to the 25th order) – like the existing substation entries; ``fault_resistance_ohm`` = additional
    impedance.

    Parameters
    ----------
    db_path : str
        groundmeas database.
    result : Result or ResultFile
        Evaluation of the recording ([`groundfault.evaluate`][groundfault.evaluation.evaluate] or
        [`groundfault.load_result`][groundfault.evaluation.load_result]).
    location : str, optional
        Location name in groundmeas; default: ``site.location``, otherwise derived from the site folder of the
        result ([`location_from_site`][groundfault.earthing.location_from_site]).
    site : groundfault.sites.Site, optional
        Line of the sites file of the campaign; supplies coordinates, asset type, voltage level, operator and
        distance to the substation (explicit arguments take precedence).
    method : str
        ``"fault"`` (fault-related component: without the background before the fault, default) or ``"direct"``
        (as measured).
    asset_type : str, optional
        groundmeas ``asset_type`` ([`ASSET_TYPES`][groundfault.earthing.ASSET_TYPES]); default: from ``site``, otherwise
        ``"mv_lv_earthing_system"`` for a station and ``"substation"`` otherwise.
    voltage_level_kv, fault_resistance_ohm, operator : optional
        Header data of the measurement (default: from ``site`` or the result; ``fault_resistance_ohm`` from the
        additional impedance ``z_fault_ohm`` of the evaluation).
    distance_to_substation_m : float, optional
        Line length from the feeding substation; becomes ``distance_to_current_injection_m`` of the values.
    latitude, longitude : float, optional
        WGS84 coordinates in degrees – needed for a new location, a cross-check for an existing one.
    description : str
        Text placed before the automatic description (English, like the existing entries).
    timezone : str, optional
        Time zone of the recorder clock (e.g. ``"Europe/Berlin"``); the time is then converted to UTC. DANEO
        recorders already write UTC (as groundmeas stores it).
    timestamp : str, optional
        Start of the recording in UTC (e.g. ``"2025-01-15 10:15:00"``), given by hand if the recorder clock was set
        wrongly.
    uncertain_mode : {"mark", "omit"}
        Treatment of uncertain fault-related values.
    existing : {"skip", "replace"}
        If the recording has been entered already: skip it, or renew an own entry.
    dry_run : bool
        True (default): write nothing and return the plan.
    backup : bool or str
        True: create a backup copy before writing; the path of a copy made earlier in the same run (several
        measurements entered one after another); False: no copy.
    units : {"suitable", "base"}
        Units of the values (see Notes).
    editor : str, optional
        Fallback for ``operator``.
    campaign_folder : str or path-like, optional
        Folder of the campaign – only for the hints, which name the sites, corrections and register files and
        their columns in the folder layout of the campaign; default: detected from the path of the result file or
        of the recording, otherwise the layout of the output language.

    Returns
    -------
    dict
        The plan: ``location``, ``location_id``, ``location_new``, ``latitude``, ``longitude``, ``entry_tag``, ``kind``
        (``"station"`` or ``"substation"``), ``measurement`` (header data incl. ``description``), ``values`` (the
        items), ``uncertain_hz``, ``injections`` (ids of earthing measurements at the location), ``reasons`` (why
        nothing can be written), ``warnings`` and ``hints`` (read before writing), ``existing_id``, ``own_id``,
        ``reason``, ``writable`` and ``written``; after writing also ``measurement_id``, ``backup`` and ``renewed``.

    Raises
    ------
    ValueError
        For an invalid ``uncertain_mode``, ``existing``, ``units`` or ``timestamp``, a method that is not in the
        result, or a result with neither a station evaluation nor fault-current harmonics.
    FileNotFoundError
        If the database or the given backup copy does not exist.

    Notes
    -----
    **Units:** ``units="suitable"`` (default) writes per measurement type one well readable unit with which the
    largest magnitude lies between 1 and 1000 (e.g. earth potential rises in mV, fault current in A) – groundmeas
    stores values as entered and converts them into the base unit itself from version 1.6.1 on; ``"base"`` writes V
    and A (for older groundmeas versions). Unit symbols as in groundmeas (``mV``, ``mA``, ``μV``), six significant
    digits.

    **Conventions** as in the existing fault-test entries: values as measured (not per ampere); frequencies as nominal
    frequencies m·50 Hz (so groundmeas queries for “50 Hz” find the value; the measured network frequency is given in
    the description); ``distance_to_current_injection_m`` = distance to the feeding substation; the description in
    English with [`entry_tag`][groundfault.earthing.entry_tag] at the end. The timestamp is the start of the recording
    according to the COMTRADE file. If it is more than one day away from the date in the campaign name (recorder clock
    set wrongly), nothing is written until ``timestamp`` is given.

    **Location:** if the name exists in groundmeas, the location is **reused and not changed** (preferably the location
    row of the earthing measurement, see [`location_rows`][groundfault.earthing.location_rows]); a new location needs
    latitude and longitude, otherwise nothing is written.

    **Writing** (``dry_run=False``, only if the plan is ``writable``): first a backup copy
    ``<db>_before_groundfault_<time>.db`` (see ``backup``), then everything in **one** transaction. If the same
    recording has been entered already (entry tag, or same location and timestamp), nothing is written – except
    with ``existing="replace"`` for an own entry: its header data and values are renewed (the measurement id
    stays). Other entries are never changed.
    """
    check_option("uncertain_mode", uncertain_mode, UNCERTAIN_MODES)
    check_option("existing", existing, EXISTING)
    check_option("units", units, UNIT_CHOICES)
    tab = getattr(result, "tables", None) or {}
    sf = tab.get("station_frequency")
    station = sf is not None and not sf.empty
    if station:
        if "Z_%s_Ohm" % method not in sf:
            raise ValueError(tr("earthing.method_missing", method=method,
                                available=[c[2:-4] for c in sf.columns if c.startswith("Z_") and c.endswith("_Ohm")]))
    elif tab.get("harmonics") is None or tab.get("harmonics").empty:
        raise ValueError(tr("earthing.nothing_to_export"))
    d = _data(result)
    meta = d.get("meta", {}) or {}
    name = meta.get("measurement") or getattr(result, "name", "")
    tag = entry_tag(meta.get("campaign"), name)
    f_nominal = _f_nominal(result)
    site_ = site

    def from_site(value, field_):
        return value if value is not None else (getattr(site_, field_, None) if site_ is not None else None)
    location_name = (location or (site_.location if site_ is not None and site_.location else None)
                     or location_from_site(meta.get("site") or name))
    latitude, longitude = from_site(latitude, "latitude"), from_site(longitude, "longitude")
    distance_ = from_site(distance_to_substation_m, "distance_to_substation_m")
    level_ = from_site(voltage_level_kv, "voltage_level_kv")
    operator = operator or editor or (site_.operator if site_ is not None and site_.operator else None)
    type_ = asset_type or (site_.asset_type if site_ is not None and site_.asset_type else None) or \
        ("mv_lv_earthing_system" if station else "substation")
    rf = (fault_resistance_ohm if fault_resistance_ohm is not None
          else (d.get("measurement", {}) or {}).get("z_fault_ohm"))
    reasons, warnings, hints = [], [], []
    files = _campaign_files(result, campaign_folder)            # file/column names in the campaign's layout
    if type_ not in ASSET_TYPES:
        reasons.append(tr("earthing.asset_type_unknown", value=type_, allowed=", ".join(ASSET_TYPES)))
    if station:
        items, uncertain_f, removed = _station_items(result, sf, method, f_nominal, uncertain_mode, distance_)
        channel = _main_ires_channel(result)
        # hints of the station evaluation and the atypical angle U_E/I_F are passed on as warnings – recognised by
        # their message key (catalogue templates in English and German), whatever the language of the evaluation
        warnings += [h for h in getattr(result, "hints", []) if i18n.message_key(h, EXPORTED_HINT_KEYS)]
        if removed:
            hints.append(tr("earthing.uncertain_omitted", count=removed, frequencies=_fmt_hz(uncertain_f)))
        if not any(w["unit"] == "V" for w in items) and not removed:
            hints.append(tr("earthing.no_voltages", method=method))
        if distance_ is None:
            hints.append(tr("earthing.distance_unknown", file=files["sites"], column=files["distance"]))
        without = [k for k in dict.fromkeys(sf["channel"]) if not np.isfinite(_distance(sf.loc[sf["channel"] == k,
                                                                                          "distance_m"].iloc[0]))]
        if without:
            hints.append(tr("earthing.probe_distance_unknown", channels=", ".join(without),
                            file=files["corrections"], column=files["probe_distance"]))
    else:
        items, channel = _substation_items(result, f_nominal, distance_)
        uncertain_f = []
    if not items:
        reasons.append(tr("earthing.no_values"))
    if rf is None:
        hints.append(tr("earthing.fault_resistance_unknown", file=files["register"],
                        column=files["fault_resistance"]))
    if level_ is None:
        hints.append(tr("earthing.voltage_level_unknown", file=files["sites"], column=files["voltage_level"]))
    chosen = _set_units(items, units)
    if any(sym != _units.base_unit(t) for t, sym in chosen.items()):
        hints.append(tr("earthing.units_chosen", units=", ".join(tr("earthing.unit_of_type", type=t, unit=u)
                                                                 for t, u in chosen.items())))
    for it in items:                                          # both representations, as the groundmeas model
        if it.get("value_angle_deg") is not None:
            a = math.radians(it["value_angle_deg"])
            it["value_real"], it["value_imag"] = it["value"] * math.cos(a), it["value"] * math.sin(a)
    if timestamp:                                             # given by hand (recorder clock set wrongly)
        try:
            _dt.datetime.fromisoformat(str(timestamp))
        except ValueError:
            raise ValueError(tr("earthing.timestamp_format", value=timestamp))
        timestamp = _groundmeas_time(timestamp, timezone)
        hints.append(tr("earthing.timestamp_by_hand", time=timestamp[:19], cfg=meta.get("start_time")))
    else:
        timestamp = _groundmeas_time(meta.get("start_time"), timezone)
        km = re.match(r"(\d{4}-\d{2}-\d{2})_", str(meta.get("campaign") or ""))
        if km and meta.get("start_time"):
            days = abs((_dt.date.fromisoformat(timestamp[:10]) - _dt.date.fromisoformat(km.group(1))).days)
            if days > 1:
                reasons.append(tr("earthing.clock_wrong", start=timestamp[:16], days=days, date=km.group(1)))
    # ------------------------------------------------------------ location and existing entries (read-only)
    location_id, location_new, injections, own_id, existing_id = None, False, [], None, None
    db = Database(db_path)
    try:
        rows = location_rows(db.con, location_name)
        if rows and (rows[0]["coordinates"] or latitude is None):
            o = rows[0]
            location_id, location_name = o["id"], o["name"]
            if not o["coordinates"]:
                hints.append(tr("earthing.location_without_coordinates", name=location_name, id=location_id,
                                coordinates=files["coordinates"], file=files["sites"]))
            elif latitude is not None:
                a = _geo_distance_m(latitude, longitude, o["latitude"], o["longitude"])
                if a > COORDINATE_TOLERANCE_M:
                    warnings.append(tr("earthing.coordinates_differ", distance=a, name=location_name, id=location_id,
                                       latitude=_deg(o["latitude"]), longitude=_deg(o["longitude"]),
                                       file=files["sites"]))
            latitude, longitude = o["latitude"], o["longitude"]
        else:
            location_new = True
            if rows:                                    # existing rows without coordinates, the new one with them
                location_name = rows[0]["name"]
                hints.append(tr("earthing.location_only_without_coordinates", name=location_name,
                                file=files["sites"]))
            elif latitude is None:
                reasons.append(tr("earthing.new_location_without_coordinates", name=location_name,
                                  coordinates=files["coordinates"], path=files["sites_path"]))
            if not rows:
                similar = [o for o in db.find_location(location_name, 0.75)["location"]
                           if _key(o) != _key(location_name)]
                if similar:
                    warnings.append(tr("earthing.new_location_similar", name=location_name,
                                       similar=", ".join(tr("earthing.quoted", text=a)
                                                         for a in dict.fromkeys(similar)), file=files["sites"]))
        ids = rows[0]["all_ids"] if rows else []
        meas = db.con.execute("select id, method, timestamp, description from measurement where location_id in (%s)"
                              % ",".join("?" * len(ids)), ids).fetchall() if ids else []
        injections = sorted(int(m[0]) for m in meas if str(m[1]).startswith("injection"))
        own = db.con.execute("select id from measurement where method = 'staged_fault_test' and "
                             "(instr(description, ?) > 0 or instr(description, ?) > 0) order by id",
                             entry_tags(meta.get("campaign"), name)).fetchall()
        if own:
            own_id = existing_id = int(own[0][0])
        else:
            equal = [int(m[0]) for m in meas if m[1] == "staged_fault_test" and str(m[2]) == timestamp]
            existing_id = equal[0] if equal else None
        others = [m for m in meas if m[1] == "staged_fault_test" and int(m[0]) != existing_id]
        if others:
            n_values = dict(db.con.execute("select measurement_id, count(*) from measurementitem where measurement_id "
                                           "in (%s) group by measurement_id" % ",".join("?" * len(others)),
                                           [m[0] for m in others]).fetchall())
            hints.append(tr("earthing.other_fault_tests", entries="; ".join(
                tr("earthing.other_fault_test", id=m[0], date=str(m[2])[:10], count=n_values.get(m[0], 0),
                   description=(m[3] or "")[:50]) for m in others)))
    finally:
        db.close()
    text = _description(result, "station" if station else "substation", location_name, method, rf, uncertain_f,
                        uncertain_mode, injections, channel, description, tag)
    plan = dict(location=location_name, location_id=location_id, location_new=location_new, latitude=latitude,
                longitude=longitude, entry_tag=tag, kind="station" if station else "substation",
                measurement=dict(timestamp=timestamp, method="staged_fault_test", asset_type=type_,
                                 voltage_level_kv=level_, fault_resistance_ohm=float(rf) if rf is not None else None,
                                 operator=operator, description=text),
                values=items, uncertain_hz=uncertain_f, injections=injections, written=False,
                reasons=reasons, warnings=warnings, hints=hints, existing_id=existing_id, own_id=own_id)
    if existing_id is not None:
        if existing == "replace" and own_id is not None:
            plan["reason"] = tr("earthing.own_entry_renewed", id=own_id)
        else:
            plan["reason"] = tr("earthing.already_entered", id=existing_id)
            if own_id is None and existing == "replace":
                reasons.append(tr("earthing.not_own_entry", id=existing_id))
    plan["writable"] = not reasons and (existing_id is None or (existing == "replace" and own_id is not None))
    if dry_run or not plan["writable"]:
        return plan
    # ------------------------------------------------------------ write (backup copy, one transaction)
    if isinstance(backup, str):
        if not os.path.exists(backup):
            raise FileNotFoundError(tr("earthing.backup_missing", path=backup))
    else:
        backup = _backup(db_path) if backup else None
    con = sqlite3.connect(db_path, timeout=30)
    try:
        with con:
            if location_new:
                location_id = con.execute("insert into location (name, latitude, longitude) values (?, ?, ?)",
                                          (location_name, latitude, longitude)).lastrowid
            m = plan["measurement"]
            header = (m["timestamp"], location_id, m["method"], m["voltage_level_kv"], m["asset_type"],
                      m["fault_resistance_ohm"], m["operator"], m["description"])
            if own_id is not None and existing == "replace":
                mid = own_id
                con.execute("""update measurement set timestamp = ?, location_id = ?, method = ?, voltage_level_kv = ?,
                               asset_type = ?, fault_resistance_ohm = ?, operator = ?, description = ? where id = ?""",
                            header + (mid,))
                con.execute("delete from measurementitem where measurement_id = ?", (mid,))
            else:
                mid = con.execute("""insert into measurement (timestamp, location_id, method, voltage_level_kv,
                                     asset_type, fault_resistance_ohm, operator, description)
                                     values (?, ?, ?, ?, ?, ?, ?, ?)""", header).lastrowid
            for it in items:
                con.execute("""insert into measurementitem (measurement_type, value, value_real, value_imag,
                               value_angle_deg, unit, description, frequency_hz, measurement_distance_m,
                               distance_to_current_injection_m, measurement_id)
                               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (it["measurement_type"], it["value"], it.get("value_real"), it.get("value_imag"),
                             it.get("value_angle_deg"), it["unit"], it.get("description"), it.get("frequency_hz"),
                             it.get("measurement_distance_m"), it.get("distance_to_current_injection_m"), mid))
    finally:
        con.close()
    plan.update(written=True, measurement_id=int(mid), location_id=int(location_id), backup=backup,
                renewed=own_id is not None and existing == "replace")
    return plan


# ---------------------------------------------------------------------------------------------- notebook helpers
def exclude_own(measurements: pd.DataFrame, campaign, measurement) -> pd.DataFrame:
    """List of measurements ([`Database.measurements`][groundfault.earthing.Database.measurements]) without the own
    entry of this recording.

    The own entry is recognised by its tag ([`entry_tags`][groundfault.earthing.entry_tags]) – otherwise the fault test
    would be compared with itself.
    """
    if measurements is None or measurements.empty:
        return measurements
    desc = measurements["description"].fillna("")
    own = np.zeros(len(measurements), bool)
    for k in entry_tags(campaign, measurement):
        own |= desc.str.contains(k, regex=False).to_numpy()
    return measurements[~((measurements["method"] == "staged_fault_test").to_numpy() & own)]


def export_to_groundmeas(result, campaign_folder, db_path: Optional[str] = None, *, location: Optional[str] = None,
                         write: bool = False, template: bool = True, **options) -> Dict[str, object]:
    """Plan (dry run) or – with ``write=True`` – carry out the export of an evaluated recording to groundmeas, with
    the data of its campaign.

    * Sites file (``notes/sites.csv``, German layout ``0_Notizen/Messorte.csv``): location, coordinates, asset type,
      voltage level, distance to the substation and operator. If the file is missing, it is created with
      ``template=True`` and pre-filled from groundmeas (an existing file is never overwritten).
    * Fault resistance: additional impedance of the result (``z_fault_ohm``), otherwise the column
      ``fault_resistance_Ohm`` of the recording in the register of the working folder (``register.csv`` or
      ``Messregister.csv``).

    Parameters
    ----------
    result : Result or ResultFile
        Evaluation of the recording.
    campaign_folder : str or path-like
        Folder of the campaign; the register is searched in the working folder two levels above.
    db_path : str, optional
        groundmeas database; default: [`default_db_path`][groundfault.earthing.default_db_path].
    location : str, optional
        Exact groundmeas location name; takes precedence over the sites file.
    write : bool
        Write (after a backup copy) instead of a dry run.
    template : bool
        Create a missing sites file, pre-filled from groundmeas.
    **options
        Further arguments of [`export_fault_test`][groundfault.earthing.export_fault_test] (``existing``,
        ``uncertain_mode``, ``method``, ``timezone``, ``description`` …).

    Returns
    -------
    dict
        Plan as [`export_fault_test`][groundfault.earthing.export_fault_test]; its hints start with the remarks of this
        step, and ``sites_path`` is the path of the sites file (None if there is none).

    Raises
    ------
    FileNotFoundError
        If the database is not found.
    """
    from . import sites as _sites
    from .register import fault_resistance as _rf_register, register_path as _register_path
    db_path = db_path or default_db_path()
    if not db_path or not os.path.exists(db_path):
        raise FileNotFoundError(tr("earthing.db_not_found", path=db_path))
    beforehand = []
    if template:
        new = _sites.write_template(campaign_folder, db_path)
        if new:
            beforehand.append(tr("earthing.sites_created", path=os.path.relpath(new, str(campaign_folder))))
    locations = _sites.load(campaign_folder)
    d = _data(result)
    meta, meas = d.get("meta", {}) or {}, d.get("measurement", {}) or {}
    entry_ = locations.for_site(meta.get("site"))
    if not meta.get("site"):
        beforehand.append(tr("earthing.site_unknown", name=meta.get("measurement") or getattr(result, "name", "")))
    elif entry_ is None and locations.path:
        beforehand.append(tr("earthing.site_missing", file=os.path.basename(locations.path), site=meta.get("site")))
    elif locations.path is None:
        beforehand.append(tr("earthing.no_sites_file",
                             file=os.path.relpath(_sites.path_for(campaign_folder), str(campaign_folder))))
    if options.get("fault_resistance_ohm") is None and meas.get("z_fault_ohm") is None:
        base = Path(campaign_folder).resolve().parent.parent
        rf = _rf_register(str(base), Path(campaign_folder).name, meas.get("cfg_file") or "")
        if rf is not None:
            options["fault_resistance_ohm"] = rf
            beforehand.append(tr("earthing.fault_resistance_from_register", value=rf,
                                 file=os.path.basename(_register_path(str(base)))))
    options.setdefault("campaign_folder", campaign_folder)
    plan = export_fault_test(db_path, result, location, site=entry_, dry_run=not write, **options)
    plan["hints"] = beforehand + plan["hints"]
    plan["sites_path"] = locations.path
    return plan


def _status(plan) -> str:
    """Status of a plan as text in the active language (column ``status`` of
    [`plan_overview`][groundfault.earthing.plan_overview])."""
    if plan.get("written"):
        return tr("earthing.status_renewed" if plan.get("renewed") else "earthing.status_entered",
                  id=plan["measurement_id"])
    if plan.get("reasons"):
        return tr("earthing.status_impossible", reasons="; ".join(plan["reasons"]))
    if plan.get("existing_id") is not None and not plan.get("writable"):
        return tr("earthing.status_already_entered", id=plan["existing_id"])
    if plan.get("own_id") is not None:
        return tr("earthing.status_ready_renew", id=plan["own_id"])
    return tr("earthing.status_ready")


def plan_overview(plans: Dict[str, dict]) -> pd.DataFrame:
    """One row per planned or written entry.

    Parameters
    ----------
    plans : dict
        ``{name: plan}`` with plans of [`export_fault_test`][groundfault.earthing.export_fault_test] or
        [`export_to_groundmeas`][groundfault.earthing.export_to_groundmeas].

    Returns
    -------
    pandas.DataFrame
        Columns ``measurement``, ``kind``, ``location``, ``location_id`` (``"new"`` for a location still to be
        created), ``latitude``, ``longitude``, ``time_UTC``, ``asset_type``, ``voltage_level_kV``,
        ``fault_resistance_Ohm``, ``operator``, ``values`` (number), ``of_which`` (number per measurement type and
        unit), ``uncertain_Hz`` and ``status`` (text in the active language).
    """
    rows = []
    for n, p in plans.items():
        m = p["measurement"]
        types_ = Counter("%s [%s]" % (w["measurement_type"], w["unit"]) for w in p["values"])
        rows.append(dict(measurement=n, kind=p.get("kind", ""), location=p["location"],
                         location_id=("new" if p.get("location_new") and not p.get("written")
                                      else p.get("location_id")),
                         latitude=_deg(p.get("latitude")), longitude=_deg(p.get("longitude")),
                         time_UTC=m["timestamp"][:19], asset_type=m["asset_type"],
                         voltage_level_kV=m["voltage_level_kv"],
                         fault_resistance_Ohm=m["fault_resistance_ohm"], operator=m["operator"],
                         values=len(p["values"]), of_which=", ".join("%d %s" % (v, k) for k, v in types_.items()),
                         uncertain_Hz=_fmt_hz(p.get("uncertain_hz", [])), status=_status(p)))
    return pd.DataFrame(rows)


def plan_items(plan: dict) -> pd.DataFrame:
    """Planned values of a plan as a table with the groundmeas columns ``measurement_type``, ``frequency_hz``,
    ``value``, ``unit``, ``value_angle_deg``, ``measurement_distance_m``, ``distance_to_current_injection_m`` and
    ``description``."""
    sp = ["measurement_type", "frequency_hz", "value", "unit", "value_angle_deg", "measurement_distance_m",
          "distance_to_current_injection_m", "description"]
    return pd.DataFrame([{k: w.get(k) for k in sp} for w in plan["values"]], columns=sp)
