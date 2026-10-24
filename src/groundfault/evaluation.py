# -*- coding: utf-8 -*-
"""Evaluation of a single recording of a staged earth-fault test.

[`evaluate`][groundfault.evaluation.evaluate] processes one COMTRADE recording in seven steps:

1. Load the analysis intervals (steady-state fault, pre-fault, post-fault), optionally with a time offset for
   channels recorded with a different time base, and remove the DC component and slow drifts with the zero-phase
   high-pass ([`condition_blocks`][groundfault.evaluation.condition_blocks], ``Settings.dc``).
2. Estimate the network frequency f1 per interval (reference U_L1-L2, cross-checked with a second method).
3. Divide the steady-state interval into 200-ms windows (N_win = T_win·f_s samples) and compute, for *all*
   channels and from the **same** window, the true RMS value and the complex phasors of the orders 1…H (mean of the
   window removed, Hann window, DFT at the multiples m·f1).
4. Leave out disturbed states – an active residual current increase or a step of the reactive component (network or
   coil switching, [`groundfault.disturbances`][groundfault.disturbances]) – so that only the undisturbed state is
   the reference. Of its windows take the one with the largest residual earth-fault current (the *max window*) and
   derive the assessment quantities: angle method (active and reactive residual current Iw, Iv from the angle between the fault
   current and the zero-sequence voltage), polarity check (Iw > 0), harmonic content I_H = √(I_RES² − I_G²)
   with a check against the root sum of squares of the harmonics, measurement uncertainty (currents are
   increased by m_I, voltages are reduced by m_U) and, optionally, the scaling of the harmonic content to the
   95 % quantile of a power-quality measurement.
5. Voltage analysis pre-fault / fault / post-fault: line-to-earth and line-to-line voltages, zero, positive and
   negative sequence per harmonic, THD, U_H5g (5th harmonic, negative sequence), U_H7m (7th harmonic, positive
   sequence) and complex sequence phasors referred to U_L1-L2 (input of the equivalent-source method).
6. Optional: station (earth potential rise, touch voltage, r·Z_E, shield current) and transformer node (power,
   apparent and upstream impedance per order and sequence before, during and after the fault,
   [`groundfault.transformer`][groundfault.transformer]).
7. Plausibility checks and statistics over the undisturbed windows of the steady-state interval.

The [`Result`][groundfault.evaluation.Result] holds the tables, scalar values, hints and the content of the result file
(JSON without raw data, [`Result.save_json`][groundfault.evaluation.Result.save_json]), which
[`load_result`][groundfault.evaluation.load_result] reads back for campaign evaluations and report tables.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
import unicodedata
import warnings
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

from . import __version__
from . import disturbances as dist
from . import transformer as trafo
from . import dsp
from . import formulas as fml
from . import i18n
from .i18n import tr
from .layout import ENGLISH, GERMAN, detect_layout
from .legacy import (RESULT_FORMAT, RESULT_VERSION, check_keys, check_option, is_legacy_result, translate_result,
                     update_result)
from .comtrade import Recording
from .channels import RoleAssignment, canonical_role, detect_roles
from .symmetrical import fortescue, line_to_line

__all__ = ["Settings", "Intervals", "Result", "evaluate", "load_blocks", "condition_blocks", "ResultFile",
           "load_result", "rescale_harmonics"]

Interval = Tuple[float, float]

i18n.register({
    # ---- intervals and windows
    "evaluation.interval_invalid": {
        "en": "Interval {name}={interval} is not within 0 … {duration:.3f} s or t0 ≥ t1.",
        "de": "Bereich {name}={interval} liegt nicht in 0 … {duration:.3f} s bzw. t0 ≥ t1."},
    "evaluation.pre_fault_overlap": {
        "en": "The pre-fault interval ends after the start of the steady-state interval.",
        "de": "Vorfehlerbereich endet nach Beginn des stationären Bereichs."},
    "evaluation.post_fault_overlap": {
        "en": "The post-fault interval starts before the end of the steady-state interval.",
        "de": "Nachfehlerbereich beginnt vor Ende des stationären Bereichs."},
    "evaluation.interval_too_short": {
        "en": "Interval '{name}' is shorter than one window ({window_ms:.0f} ms).",
        "de": "Bereich '{name}' kürzer als ein Fenster ({window_ms:.0f} ms)."},
    "evaluation.orders_limited": {
        "en": "Sampling rate {fs:.0f} Hz limits the harmonics to order ≤ {order}.",
        "de": "Abtastrate {fs:.0f} Hz begrenzt die Harmonischen auf Ordnung ≤ {order}."},
    # ---- reference signal of the frequency estimation
    "evaluation.reference_ll": {"en": "U_L1-L2 (from L-E)", "de": "U_L1-L2 (aus L-E)"},
    "evaluation.reference_ll_hv": {"en": "U_L1-L2 HV (from L-E)", "de": "U_L1-L2 HS (aus L-E)"},
    "evaluation.reference_channel_1": {"en": "channel 1", "de": "Kanal 1"},
    # ---- evaluate()
    "evaluation.correction_applied": {
        "en": "Correction applied: {channel} × {factor:g} ({source}){remark}",
        "de": "Korrektur angewendet: {channel} × {factor:g} ({source}){remark}"},
    "evaluation.manual": {"en": "manual", "de": "manuell"},
    "evaluation.sampling_rate_too_low": {
        "en": "Sampling rate {fs:.1f} Hz is too low for a harmonic analysis – evaluate RMS recordings with "
              "`rms.evaluate_rms_recording`.",
        "de": "Abtastrate {fs:.1f} Hz zu niedrig für eine Oberschwingungsanalyse – RMS-Aufzeichnungen bitte mit "
              "`rms.evaluate_rms_recording` vergleichen."},
    "evaluation.f1_implausible": {
        "en": "f1 in interval '{interval}' implausible ({note}) – using {f1:.4f} Hz.",
        "de": "f1 im Bereich '{interval}' unplausibel ({note}) – verwendet {f1:.4f} Hz."},
    "evaluation.nan_windows": {
        "en": "{count} windows in interval '{interval}' contain gaps (NaN) and are ignored.",
        "de": "{count} Fenster im Bereich '{interval}' enthalten Lücken (NaN) und werden ignoriert."},
    "evaluation.station_failed": {
        "en": "Station: frequency-selective evaluation not possible: {error}",
        "de": "Station frequenzselektiv nicht möglich: {error}"},
    # ---- summary()
    "evaluation.summary_measurement": {"en": "Measurement: {name}  ({file})", "de": "Messung: {name}  ({file})"},
    "evaluation.summary_window": {
        "en": "Max window: {t:.3f} s  | f1 = {f1:.4f} Hz ({method})",
        "de": "Max-Fenster: {t:.3f} s  | f1 = {f1:.4f} Hz ({method})"},
    "evaluation.summary_currents": {
        "en": "IRES = {ires:.2f} A | IG = {ig:.2f} A | Iw = {iw:.2f} A | Iv = {iv:.2f} A | IH = {ih:.2f} A",
        "de": "IRES = {ires:.2f} A | IG = {ig:.2f} A | Iw = {iw:.2f} A | Iv = {iv:.2f} A | IH = {ih:.2f} A"},
    # ---- assessment quantities (column description)
    "evaluation.desc_ires": {"en": "residual earth-fault current (max 200-ms window, steady state)",
                             "de": "Erdschlussreststrom (Max-200-ms-Fenster, stationär)"},
    "evaluation.desc_iw": {"en": "active current of the fundamental component",
                           "de": "Wirkstrom der Grundschwingung"},
    "evaluation.desc_iv": {"en": "detuning current of the fundamental component (> 0: overcompensated)",
                           "de": "Verstimmungsstrom der Grundschwingung (> 0: überkompensiert)"},
    "evaluation.desc_ih1": {"en": "fundamental component (magnitude; angle referred to U_L1-L2)",
                            "de": "Grundschwingung (Betrag; Winkel bez. U_L1-L2)"},
    "evaluation.desc_harmonic": {"en": "harmonic of order {order} ({f:.0f} Hz)",
                                 "de": "{order}. Harmonische ({f:.0f} Hz)"},
    "evaluation.desc_ih_total": {"en": "total harmonic content √(IRES²−IG²)",
                                 "de": "Oberschwingungsanteil gesamt √(IRES²−IG²)"},
    "evaluation.desc_ih_sum": {"en": "harmonic content Σ orders 2…{order}",
                               "de": "Oberschwingungsanteil Σ Ordnungen 2…{order}"},
    "evaluation.desc_u0": {"en": "fundamental component of the zero sequence (neutral displacement voltage)",
                           "de": "Grundschwingung Nullsystem (Verlagerungsspannung)"},
    "evaluation.desc_uthd_meas": {"en": "THD/U_H of the measurement (reference {reference}, max. loop)",
                                  "de": "THD/U_H der Messung (Bezug {reference}, max. Schleife)"},
    "evaluation.desc_uthd_95": {"en": "95 % quantile of the PQ measurement (× safety factor {factor:.2f})",
                                "de": "95-%-Quantil PQ-Messung (× Sicherheitsfaktor {factor:.2f})"},
    "evaluation.desc_ih_scaled": {"en": "harmonic content, scaled", "de": "Oberschwingungsanteil skaliert"},
    "evaluation.desc_ih_zero": {"en": "harmonic content of the zero sequence (not scaled)",
                                "de": "Oberschwingungsanteil des Nullsystems (nicht skaliert)"},
    "evaluation.desc_ih_even": {"en": "harmonic content of the even orders (not scaled)",
                                "de": "Oberschwingungsanteil der geraden Ordnungen (nicht skaliert)"},
    "evaluation.desc_ih_other": {"en": "harmonic content not assigned to an order (not scaled)",
                                 "de": "keiner Ordnung zugeordneter Oberschwingungsanteil (nicht skaliert)"},
    "evaluation.desc_irms_forecast": {"en": "residual earth-fault current with scaled harmonic content",
                                      "de": "Erdschlussreststrom mit skaliertem OS-Anteil"},
    # ---- hints of the assessment
    "evaluation.polarity_uncertain": {
        "en": "Polarity decision uncertain: active component only {share:.0f} % of I_H1 (margin {margin:.1f}° to the "
              "±90° limit) – an angle error of the measuring chain of this size reverses the sign of Iw; check the "
              "polarity of the clamp and set correct_polarity=False if necessary.",
        "de": "Polaritätsentscheidung unsicher: Wirkanteil nur {share:.0f} % von I_H1 (Reserve {margin:.1f}° bis zur "
              "±90°-Grenze) – ein Winkelfehler der Messkette in dieser Größe kehrt das Vorzeichen von Iw um; "
              "Polarität der Zange prüfen und ggf. correct_polarity=False setzen."},
    "evaluation.polarity_corrected": {
        "en": "Iw was negative → current measurement reversed; current phasors rotated by 180° (magnitudes "
              "unchanged).",
        "de": "Iw war negativ → Strommessung verpolt; Stromzeiger um 180° gedreht (Beträge unverändert)."},
    "evaluation.polarity_negative": {
        "en": "Iw negative – physically impossible (reversed current measurement?).",
        "de": "Iw negativ – physikalisch unmöglich (verpolte Strommessung?)."},
    "evaluation.scaling_no_voltage": {
        "en": "Scaling of the harmonic content not possible: no voltage measurement in the pre-/post-fault "
              "interval.",
        "de": "Skalierung des Oberschwingungsanteils nicht möglich: keine Spannungsmessung im Vor-/Nachfehler."},
    "evaluation.scaling_no_reference": {
        "en": "Scaling of the harmonic content: reference interval '{reference}' not evaluated.",
        "de": "Skalierung des Oberschwingungsanteils: Bezugsbereich '{reference}' nicht ausgewertet."},
    # ---- station
    "evaluation.angle_atypical": {
        "en": "Angle U_E/I_F ({channel}, 50 Hz) = {angle:.0f}° – atypical for an earthing impedance (expected "
              "≈ −30…+60°): check the polarity of probe/clamp; the magnitudes (V per 100 A) are not affected.",
        "de": "Winkel U_E/I_F ({channel}, 50 Hz) = {angle:.0f}° – für eine Erdungsimpedanz untypisch (erwartet "
              "≈ −30…+60°): Polung von Sonde/Zange prüfen; Beträge (V je 100 A) sind davon unabhängig."},
    "evaluation.shield_reversed": {
        "en": "Shield current {channel} in phase opposition to the fault current → polarity reversed.",
        "de": "Schirmstrom {channel} gegenphasig zum Fehlerstrom → Polarität gedreht."},
    # ---- plausibility checks: labels (column check), values and comments
    "evaluation.check_corrections": {"en": "Corrections ({path})", "de": "Korrekturen ({path})"},
    "evaluation.corrections_comment": {
        "en": "measured values corrected when reading (CT ratio/polarity according to the notes)",
        "de": "Messwerte beim Einlesen korrigiert (Wandlerübersetzung/Polarität laut Notiz)"},
    "evaluation.check_windows": {"en": "Windows in the steady-state interval",
                                 "de": "Fenster im stationären Bereich"},
    "evaluation.windows_comment": {"en": "≥ 3 windows recommended (statistics/robustness)",
                                   "de": "≥ 3 Fenster empfohlen (Statistik/Robustheit)"},
    "evaluation.check_f1": {"en": "Network frequency f1", "de": "Netzfrequenz f1"},
    "evaluation.value_f1": {"en": "{f1:.4f} Hz (comparison {comparison:.4f} Hz)",
                            "de": "{f1:.4f} Hz (Vergleich {comparison:.4f} Hz)"},
    "evaluation.f1_consistent": {"en": "two methods consistent", "de": "zwei Verfahren konsistent"},
    "evaluation.check_f1_constant": {"en": "Network frequency constant in the interval",
                                     "de": "Netzfrequenz im Bereich konstant"},
    "evaluation.value_f1_spread": {"en": "spread {spread:.4f} Hz", "de": "Streuung {spread:.4f} Hz"},
    "evaluation.f1_spread_large": {
        "en": "f1 per window (phase progression of U_L1-L2) – spread above 0.02 Hz: magnitude errors at high orders "
              "(up to {order}) due to the fixed grid m·f1; choose a narrower interval",
        "de": "f1 je Fenster (Phasenfortschritt U_L1-L2) – über 0,02 Hz Streuung: bei hohen Ordnungen (bis {order}) "
              "Betragsfehler durch das feste Raster m·f1; Bereich enger wählen"},
    "evaluation.f1_spread_small": {"en": "one f1 for the whole interval is sufficient",
                                   "de": "ein f1 für den ganzen Bereich ausreichend"},
    "evaluation.check_rms_selection": {"en": "RMS ↔ √ΣX² (orders {orders})", "de": "RMS ↔ √ΣX² (Ordnungen {orders})"},
    "evaluation.rms_selection_comment": {
        "en": "deviation RMS ↔ √ΣX²; large → further components (higher orders/interharmonics)",
        "de": "Abweichung RMS ↔ √ΣX²; groß → weitere Anteile (höhere Ordnungen/Zwischenharmonische)"},
    "evaluation.check_rms_all": {"en": "RMS ↔ √ΣX² (orders 1…{order})", "de": "RMS ↔ √ΣX² (Ordnungen 1…{order})"},
    "evaluation.rms_all_comment": {"en": "remainder = interharmonics/noise/transients in the window",
                                   "de": "Rest = Zwischenharmonische/Rauschen/Transienten im Fenster"},
    "evaluation.value_pct": {"en": "{value:.1f} %", "de": "{value:.1f} %"},
    "evaluation.check_stationarity": {"en": "Stationarity of I_H1 in the interval",
                                      "de": "Stationarität I_H1 im Bereich"},
    "evaluation.value_span": {"en": "span {span:.1f} %", "de": "Spanne {span:.1f} %"},
    "evaluation.value_span_components": {"en": " (ΔIw {d_iw:.1f} A, ΔIv {d_iv:.1f} A)",
                                         "de": " (ΔIw {d_iw:.1f} A, ΔIv {d_iv:.1f} A)"},
    "evaluation.stationarity_ok": {"en": "fundamental component constant in the interval",
                                   "de": "Grundschwingung im Bereich konstant"},
    "evaluation.cause_reactive": {
        "en": "reactive component changes by {d_iv:.1f} A at a constant active component → coil adjustment/network "
              "switching, no active residual current increase",
        "de": "Blindanteil ändert sich um {d_iv:.1f} A bei konstantem Wirkanteil → Spulenverstellung/"
              "Netzumschaltung, keine Wattreststromerhöhung"},
    "evaluation.stationarity_reactive": {
        "en": "{cause}; the max window and Iv refer to the time of the largest I_RES",
        "de": "{cause}; Max-Fenster und Iv beziehen sich auf den Zeitpunkt des größten I_RES"},
    "evaluation.cause_active": {
        "en": "active component changes by {d_iw:.1f} A → active residual current increase in the interval?",
        "de": "Wirkanteil ändert sich um {d_iw:.1f} A → Wattreststromerhöhung im Bereich?"},
    "evaluation.stationarity_active": {"en": "{cause} – choose a narrower steady-state interval",
                                       "de": "{cause} – stationären Bereich enger wählen"},
    "evaluation.cause_both": {
        "en": "active and reactive components change (active residual current increase/coil adjustment?)",
        "de": "Wirk- und Blindanteil ändern sich (Wattreststromerhöhung/Spulenverstellung?)"},
    "evaluation.stationarity_both": {"en": "{cause} – check the steady-state interval",
                                     "de": "{cause} – stationären Bereich prüfen"},
    "evaluation.stationarity_hint": {
        "en": "The fundamental component of the fault current varies by {span:.0f} % in the steady-state interval – "
              "{cause}; the max window is at {t:.2f} s.",
        "de": "Grundschwingung des Fehlerstroms schwankt im stationären Bereich um {span:.0f} % – {cause}; "
              "Max-Fenster liegt bei {t:.2f} s."},
    "evaluation.check_coil_balance": {"en": "Coil current balance ΔIv ↔ ΔΣI_coil",
                                      "de": "Spulenstrombilanz ΔIv ↔ ΔΣI_Spule"},
    "evaluation.value_coil_balance": {"en": "slope {slope:.2f} (R² {r2:.2f}, ΔΣI_coil {d_coil:.1f} A)",
                                      "de": "Steigung {slope:.2f} (R² {r2:.2f}, ΔΣI_Spule {d_coil:.1f} A)"},
    "evaluation.coil_balance_ok": {
        "en": "the change of the coil currents explains the change of Iv (coil channels complete and correctly "
              "scaled)",
        "de": "Änderung der Spulenströme erklärt die Änderung von Iv (Spulenkanäle vollständig und richtig "
              "skaliert)"},
    "evaluation.coil_balance_high": {
        "en": "Iv changes by {slope:.1f} times the measured change of the coil currents → ratio of a coil channel "
              "too small (factor ≈ {slope:.1f}?) or not all adjusted coils measured",
        "de": "Iv ändert sich um das {slope:.1f}-Fache der gemessenen Spulenstromänderung → Übersetzung eines "
              "Spulenkanals zu klein (Faktor ≈ {slope:.1f}?) oder nicht alle verstellten Spulen gemessen"},
    "evaluation.coil_balance_low": {
        "en": "Iv changes by only {slope:.2f} times the change of the coil currents → ratio too large, or check the "
              "reference (R² = {r2:.2f})",
        "de": "Iv ändert sich nur um das {slope:.2f}-Fache der Spulenstromänderung → Übersetzung zu groß oder "
              "Bezug prüfen (R² = {r2:.2f})"},
    "evaluation.coil_balance_hint": {
        "en": "Coil current balance: {comment} – enter a correction in {path} if necessary.",
        "de": "Spulenstrombilanz: {comment} – ggf. in {path} eintragen."},
    "evaluation.check_low_frequency": {"en": "Low-frequency component of I_RES (< f1/2)",
                                       "de": "Niederfrequenter Anteil I_RES (< f1/2)"},
    "evaluation.value_low_frequency": {"en": "{lf:.2f} A (I_RES increased by {share:.1f} %)",
                                       "de": "{lf:.2f} A (I_RES dadurch +{share:.1f} %)"},
    "evaluation.low_frequency_comment": {
        "en": "decaying DC component/drift in the max window – not part of the steady-state fault current; start "
              "the steady-state interval later or remove it with dc=\"highpass\" (without this component: "
              "I_RES ≈ {without:.2f} A)",
        "de": "abklingender Gleichanteil/Drift im Max-Fenster – gehört nicht zum stationären Fehlerstrom; "
              "stationären Bereich später beginnen oder mit dc=\"highpass\" entfernen (ohne diesen Anteil: "
              "I_RES ≈ {without:.2f} A)"},
    "evaluation.low_frequency_comment_hp": {
        "en": "drift faster than the high-pass ({fc:g} Hz) in the max window – not part of the steady-state fault "
              "current (a clamp that saturates or recovers?); start the steady-state interval later (without this "
              "component: I_RES ≈ {without:.2f} A)",
        "de": "Drift schneller als der Hochpass ({fc:g} Hz) im Max-Fenster – gehört nicht zum stationären "
              "Fehlerstrom (Zange in Sättigung oder im Abklingen?); stationären Bereich später beginnen (ohne diesen "
              "Anteil: I_RES ≈ {without:.2f} A)"},
    "evaluation.low_frequency_ok": {"en": "no significant DC component/drift",
                                    "de": "kein nennenswerter Gleichanteil/Drift"},
    "evaluation.low_frequency_hint": {
        "en": "Low-frequency component (decaying DC component/drift) of {lf:.2f} A in the max window at {t:.2f} s "
              "increases I_RES by {share:.1f} % (without it ≈ {without:.2f} A) – start the steady-state interval "
              "later (DC component decayed?) or remove it with the high-pass (Settings(dc=\"highpass\")).",
        "de": "Niederfrequenter Anteil (abklingender Gleichanteil/Drift) von {lf:.2f} A im Max-Fenster bei "
              "{t:.2f} s erhöht I_RES um {share:.1f} % (ohne ihn ≈ {without:.2f} A) – stationären Bereich später "
              "beginnen (Gleichanteil abgeklungen?) oder mit dem Hochpass entfernen (Settings(dc=\"highpass\"))."},
    "evaluation.low_frequency_hint_hp": {
        "en": "Low-frequency component (drift faster than the high-pass of {fc:g} Hz) of {lf:.2f} A in the max window "
              "at {t:.2f} s increases I_RES by {share:.1f} % (without it ≈ {without:.2f} A) – start the steady-state "
              "interval later.",
        "de": "Niederfrequenter Anteil (Drift schneller als der Hochpass mit {fc:g} Hz) von {lf:.2f} A im Max-Fenster "
              "bei {t:.2f} s erhöht I_RES um {share:.1f} % (ohne ihn ≈ {without:.2f} A) – stationären Bereich später "
              "beginnen."},
    "evaluation.check_polarity": {"en": "Polarity of the fault current", "de": "Polarität Fehlerstrom"},
    "evaluation.value_margin": {"en": " (margin {margin:.1f}° to the ±90° limit)",
                                "de": " (Reserve {margin:.1f}° zur ±90°-Grenze)"},
    "evaluation.value_iw": {"en": "Iw = {iw:.2f} A{extra}", "de": "Iw = {iw:.2f} A{extra}"},
    "evaluation.polarity_rotated_comment": {"en": "current phasors rotated by 180° (clamp reversed?)",
                                            "de": "Stromzeiger um 180° gedreht (Zange verpolt?)"},
    "evaluation.polarity_ok_comment": {"en": "active component positive", "de": "Wirkanteil positiv"},
    "evaluation.check_ct_pair": {"en": "Fault-current CT {channel} ↔ {main}",
                                 "de": "Fehlerstromwandler {channel} ↔ {main}"},
    "evaluation.value_ct_pair": {"en": "RMS ratio {ratio:.3f}, Δφ(H1) {dphi:.1f}°",
                                 "de": "RMS-Verhältnis {ratio:.3f}, Δφ(H1) {dphi:.1f}°"},
    "evaluation.ct_pair_comment": {"en": "both CTs should show ≈ equal values",
                                   "de": "beide Wandler sollten ≈ gleiche Werte zeigen"},
    "evaluation.check_faulted_phase": {"en": "Faulted phase", "de": "Fehlerbehafteter Leiter"},
    "evaluation.value_faulted_phase": {"en": "L{phase}: {u:.0f} V ({ratio:.1f} % of max.)",
                                       "de": "L{phase}: {u:.0f} V ({ratio:.1f} % von max.)"},
    "evaluation.faulted_phase_comment": {"en": "line-to-earth voltage of the faulted phase drops to nearly 0 V",
                                         "de": "Leiter-Erde-Spannung des Fehlerleiters sinkt auf nahezu 0 V"},
    "evaluation.check_pre_fault": {"en": "Pre-fault {channel} ≈ 0", "de": "Vorfehler {channel} ≈ 0"},
    "evaluation.value_amps": {"en": "{value:.2f} A", "de": "{value:.2f} A"},
    "evaluation.pre_fault_comment": {
        "en": "expected ≈ 0 A without an earth fault; a larger value points to a DC offset or the clamp",
        "de": "im erdschlussfreien Betrieb erwartet ≈ 0 A; ein größerer Wert deutet auf DC-Offset oder Zange"},
    "evaluation.check_transformer": {"en": "Transformer zero-sequence current ↔ coil current/3",
                                     "de": "Trafo-Nullstrom ↔ Spulenstrom/3"},
    "evaluation.value_transformer": {"en": "3·I0 = {i0:.1f} A, ΣI_coil = {i_coil:.1f} A",
                                     "de": "3·I0 = {i0:.1f} A, ΣI_Spule = {i_coil:.1f} A"},
    "evaluation.transformer_comment": {
        "en": "equal if the measured coils are connected to the star point of this transformer",
        "de": "gleich, wenn die gemessenen Spulen am Sternpunkt dieses Trafos liegen"},
    "evaluation.check_saturation": {"en": "Saturation {channel}", "de": "Sättigung {channel}"},
    "evaluation.value_saturation": {"en": "{share:.2f} % of the samples", "de": "{share:.2f} % der Abtastwerte"},
    "evaluation.saturation_comment": {
        "en": "clipped waveform (measuring range/sensor saturated) – values distorted",
        "de": "abgeschnittene Kurvenform (Messbereich/Sensor gesättigt) – Werte verfälscht"},
    # ---- result file
    "evaluation.not_a_result_file": {"en": "{path} is not a result file of groundfault.",
                                     "de": "{path} ist keine Ergebnisdatei von groundfault."},
    # ---- user-defined limits and margins (Settings)
    "evaluation.limits_invalid": {
        "en": "ires_limits must be a sequence of residual-current limits in A > 0, e.g. (I_1, I_2), or empty – got "
              "{value!r}.",
        "de": "ires_limits muss eine Folge von Grenzwerten des Reststroms in A > 0 sein, z. B. (I_1, I_2), oder leer – "
              "erhalten: {value!r}."},
    "evaluation.pq_u95_invalid": {
        "en": "pq_u95 must be a mapping {{order: quantile in V}} or None – got {value!r}.",
        "de": "pq_u95 muss eine Zuordnung {{Ordnung: Quantil in V}} oder None sein – erhalten: {value!r}."},
    "evaluation.pq_min_level_invalid": {
        "en": "pq_min_level_V must be a number ≥ 0 in V – got {value!r}.",
        "de": "pq_min_level_V muss eine Zahl ≥ 0 in V sein – erhalten: {value!r}."},
    "evaluation.scaling_without_own": {
        "en": "Scaling: orders {orders} without their own value (no quantile or no level of at least {min_level:g} V in "
              "the test): {fallback}",
        "de": "Skalierung: Ordnungen {orders} ohne eigenen Wert (kein Quantil oder kein Pegel von mindestens "
              "{min_level:g} V im Versuch): {fallback}"},
    "evaluation.scaling_thd_used": {"en": "THD factor {factor:.3g}", "de": "THD-Faktor {factor:.3g}"},
    "evaluation.scaling_as_measured": {"en": "as measured (no THD given)", "de": "wie gemessen (kein THD angegeben)"},
    "evaluation.even_orders": {
        "en": "Even orders in the fault current: {current:.2f} A ({share:.0f} % of the harmonic content; largest order "
              "{order} with {largest:.2f} A) – included as measured, not scaled. Even harmonics are unusual for the "
              "voltage of a network: check for another cause (e.g. a DC component or saturation at the fault "
              "inception, current clamps).",
        "de": "Gerade Ordnungen im Fehlerstrom: {current:.2f} A ({share:.0f} % des Oberschwingungsanteils; größte "
              "Ordnung {order} mit {largest:.2f} A) – wie gemessen enthalten, nicht skaliert. Gerade Harmonische sind "
              "für die Spannung eines Netzes ungewöhnlich: auf eine andere Ursache prüfen (z. B. Gleichanteil oder "
              "Sättigung beim Fehlereintritt, Stromzangen)."},
    "evaluation.positive_or_none": {
        "en": "{name} must be a number > 0 or None (not set) – got {value!r}.",
        "de": "{name} muss eine Zahl > 0 oder None (nicht festgelegt) sein – erhalten: {value!r}."},
    "evaluation.uncertainty_invalid": {
        "en": "{name} must be a relative margin 0 ≤ m < 1 (0 = no margin) – got {value!r}.",
        "de": "{name} muss ein relativer Zuschlag 0 ≤ m < 1 sein (0 = kein Zuschlag) – erhalten: {value!r}."},
    "evaluation.cutoff_invalid": {
        "en": "dc_cutoff_hz must be a frequency > 0 and at most {fmax:g} Hz (a quarter of f_nominal) – got {value!r}.",
        "de": "dc_cutoff_hz muss eine Frequenz > 0 und höchstens {fmax:g} Hz (ein Viertel von f_nominal) sein – "
              "erhalten: {value!r}."},
    "evaluation.factor_invalid": {
        "en": "{name} must be a factor > 0 (1 = no factor) – got {value!r}.",
        "de": "{name} muss ein Faktor > 0 sein (1 = kein Faktor) – erhalten: {value!r}."},
    "evaluation.bool_invalid": {
        "en": "{name} must be True or False – got {value!r}.",
        "de": "{name} muss True oder False sein – erhalten: {value!r}."},
    "evaluation.share_invalid": {
        "en": "{name} must be a share between 0 and 1 (e.g. 0.05 = 5 %) – got {value!r}.",
        "de": "{name} muss ein Anteil zwischen 0 und 1 sein (z. B. 0.05 = 5 %) – erhalten: {value!r}."},
    "evaluation.sign_invalid": {
        "en": "{name} must be None (automatic), +1 or −1 – got {value!r}.",
        "de": "{name} muss None (automatisch), +1 oder −1 sein – erhalten: {value!r}."},
})

i18n.register_labels(values={"quantity": {"IH_zero": "IH_null", "IH_even": "IH_gerade", "IH_other": "IH_sonstige"}})

#: Formulas in the column ``equation`` of the table ``assessment_quantities`` (language-neutral)
_EQUATIONS = {
    "IRES": "I_RES = √(Σ i[n]²/N)",
    "Iw": "Iw = I_H1·cos(φ_U0 − φ_I1)",
    "Iv": "Iv = I_H1·sin(φ_U0 − φ_I1)",
    "IH_total": "I_H = √(I_RES² − I_G²)",
    "UTHD_meas": "U_assess = U_meas·(1 − m_U)",
    "UTHD_95": "U_95 = U_PQ,95%·k_s",
    "IH_scaled": "I_H,scaled = √(Σ (k_m·I_Hm)² + I_0² + I_even² + I_other²), k_m = U_95,m/U_m or U_95/U_meas",
    "IH_zero": "I_0 = √(Σ I_Hm²), m = 3, 9, 15 …",
    "IH_even": "I_even = √(Σ I_Hm²), m = 2, 4, 6 …",
    "IH_other": "I_other = √(I_H² − Σ I_Hm²)",
    "IRMS_forecast": "I_RMS = √(I_G² + I_H,scaled²)",
}


def _equation_harmonic(m: int) -> str:
    """Formula of the harmonic ``m`` of the fault current (``I_H5 = |I(5·f1)|``)."""
    return "I_H1 = |I(f1)|" if m == 1 else "I_H%d = |I(%d·f1)|" % (m, m)


@dataclass
class Settings:
    """Parameters of the evaluation.

    The defaults evaluate non-overlapping 200-ms windows with a Hann window after the DC removal with a high-pass and
    the mean per window, and assess the fundamental component and the harmonics 3, 5 and 7 of the fault current.

    Attributes
    ----------
    f_nominal : float
        Rated network frequency in Hz.
    T_win : float
        Window length in s.
    T_hop : float or None
        Hop between the starts of two windows in s; None = ``T_win`` (windows without overlap, the default).
    window : str
        Window function of the DFT: ``"hann"`` (symmetric, default), ``"hann_periodic"`` or ``"rectangular"``.
    dc : str
        Removal of the DC component: ``"highpass"`` (default) – a zero-phase Butterworth high-pass
        ([`groundfault.dsp.highpass`][groundfault.dsp.highpass]) on every interval before the windows (it removes also
        the DC component that decays after the fault inception and a slowly drifting offset of a current clamp), then
        the mean per window; ``"highpass_median"`` – the high-pass, then the median per window (``"highpass"`` of
        groundfault 3.4); or per window only ``"median"``, ``"mean"`` or ``"none"``. The harmonics are the same with
        every method; they differ only in the low-frequency part and with it in the true RMS value. The median of a
        waveform that is not symmetric (even harmonics) lies beside its mean, and the RMS value counts the shift – the
        reason for the mean after the high-pass ([`groundfault.dsp.window_dc`][groundfault.dsp.window_dc]).
    dc_cutoff_hz : float
        Cut-off frequency of the high-pass in Hz (``dc="highpass"``; default 5 Hz, at most a quarter of
        ``f_nominal``).
    harmonics : tuple of int
        Orders of the fault current in the table ``assessment_quantities`` (the fundamental is always included).
    export_orders : tuple of int
        Orders whose phasors are written to the result file (1…25, input of the equivalent-source method).
    voltage_harmonics : tuple of int
        Orders of the voltage levels pre-fault and post-fault (odd orders up to 25).
    thd_max_order : int
        Highest order of the THD (orders 2…40 as in IEC 61000-4-7).
    estimate_frequency : bool
        Estimate f1 per interval; False = use ``f_nominal``.
    f1_method : str
        Frequency estimation: ``"phase"`` (phase progression of the fundamental, default) or ``"spectral"``; the
        other method is used as a cross-check.
    uncertainty_I : float
        Measurement-uncertainty margin m_I of currents: assessed current = measured current·(1 + m_I). Default 0 (no
        margin); define it yourself, e.g. from the accuracy of the measuring chain. It is also the smallest
        uncertainty of a current channel in the uncertainty estimate of the LV-network checks.
    uncertainty_U : float
        Measurement-uncertainty margin m_U of voltages: assessed voltage = measured voltage·(1 − m_U). Default 0 (no
        margin); also used in the uncertainty estimate of Z_E,LV.
    correct_polarity : bool
        Iw < 0 (physically impossible) → rotate the fault-current phasors by 180°.
    max_search_hop : float or None
        Finer hop in s for the search of the max window; None = ``T_hop``.
    u_thd95_percent : float or None
        95 % quantile of the THD (line-to-line) of a power-quality (PQ) measurement in %; enables the scaling of
        the harmonic content – with the flat factor U_95/U_meas for the orders of the positive or negative sequence
        without their own quantile (alone: for all of them).
    u_thd95_volt : float or None
        Alternatively the 95 % quantile of the harmonic voltage (line-to-line) in V.
    pq_u95 : dict or None
        95 % quantile of the harmonic voltage per order in V, ``{order: U}`` (e.g. from
        [`groundfault.pq.PQAssessment.settings`][groundfault.pq.PQAssessment.settings]); enables the scaling per order:
        every order of the positive or negative sequence (5, 7, 11, 13 …) with a quantile and a level of at least
        ``pq_min_level_V`` in the test is scaled with its own voltage, k_m = k_s·U_95,m/U_m (U_m = level of the natural
        sequence of m, interval ``thd_reference``). The orders of the zero sequence (3, 9, 15 …), the even orders
        and the content not assigned to an order keep their measured value.
    pq_u95_reference : str
        Reference of ``pq_u95``: ``"seq"`` (line-to-earth, default) or ``"LL"`` (line-to-line, divided by √3).
    pq_min_level_V : float
        Smallest level of an order in the test for its own factor in V (below it: the THD factor).
    pq_safety_factor : float
        Factor k_s applied to the 95 % quantiles, U_95 = k_s·U_PQ,95% (1 = no factor).
    thd_reference : str
        Interval of the measured THD and of the levels per order the scaling refers to: ``"pre_fault"``,
        ``"post_fault"`` or ``"mean"`` (mean of both).
    transformer_voltage : str
        Side of the transformer currents, i.e. the voltage set of the transformer node: ``"mv"`` (medium voltage,
        default; with HV voltages the upstream impedance is split into HV network and transformer) or ``"hv"``.
    transformer_sign : float or None
        Polarity of the transformer currents: None (default) – from the angle of the upstream impedance during the
        fault (inductive in the consumer reference arrow system; generator reference arrow system → reversed, see
        [`groundfault.transformer`][groundfault.transformer]); +1: consumer reference arrow system as measured; −1:
        reversed (signs of P and Q and of the currents).
    ires_limits : tuple of float
        Limits of the residual current in A, defined by the user (e.g. from the operator's specification or the
        applicable standard): the station voltages are extrapolated to them, and the largest is the reference
        current of the reduction factor. Empty (default): no extrapolation.
    u_tp : float or None
        Permissible touch voltage U_Tp in V, defined by the user; with ``f_factor`` the limit F·U_Tp of the earth
        potential rise (relevance of the reduction factor for the assessment). None (default): not set.
    f_factor : float or None
        Factor F of the permissible earth potential rise F·U_Tp (ratio of the permissible earth potential rise to the
        permissible touch voltage), defined by the user. None (default): not set.
    exclude_disturbances : bool
        Leave disturbed states of the steady-state interval out of the reference (default True): windows during an
        active residual current increase or after a step of the reactive component (a network section trips, a
        coil is switched) are not searched for the max window and are not part of the statistics and the checks over
        the interval ([`groundfault.disturbances`][groundfault.disturbances]). False: they are only reported.
    disturbance_threshold : float
        Smallest step of the active or reactive component (without U0: of |I_H1|) that counts as a disturbance, as a
        share of |I_H1| of the undisturbed state (default 0.05, at least
        [`STEP_MIN_A`][groundfault.disturbances.STEP_MIN_A]).

    Raises
    ------
    ValueError
        For an unknown value of a text option (``window``, ``dc``, ``f1_method``, ``thd_reference``,
        ``transformer_voltage``), also for a value of the predecessor tool such as ``"mittel"`` (the message names
        the allowed values and the current name); for limits that are not a sequence of positive currents, a
        ``u_tp``/``f_factor`` that is not positive, an uncertainty margin outside 0 ≤ m < 1, a
        ``pq_safety_factor`` that is not > 0, an ``exclude_disturbances`` that is not a bool, a
        ``disturbance_threshold`` outside 0 < x < 1 or a ``transformer_sign`` other than None, +1 and −1.

    Notes
    -----
    groundfault contains no limits, safety factors or uncertainty margins: ``ires_limits``, ``u_tp``, ``f_factor``,
    ``uncertainty_I``, ``uncertainty_U`` and ``pq_safety_factor`` are parameters each user defines. With their
    defaults the evaluation applies no margin and no factor, and the parts that need a limit are skipped.
    """
    f_nominal: float = 50.0
    T_win: float = 0.200                       # window length [s]
    T_hop: Optional[float] = None              # hop [s]; None = T_win (no overlap, default)
    window: str = "hann"                      # window function of the DFT
    dc: str = "highpass"                       # DC removal: high-pass on the intervals + mean per window (default)
    dc_cutoff_hz: float = 5.0                  # cut-off frequency of the high-pass (dc="highpass")
    harmonics: Tuple[int, ...] = (1, 3, 5, 7)            # assessed orders of the fault current
    export_orders: Tuple[int, ...] = tuple(range(1, 26))  # phasors in the result file (1…25, equivalent sources)
    voltage_harmonics: Tuple[int, ...] = tuple(range(1, 26, 2))   # voltage levels pre/post: odd orders up to 25
    thd_max_order: int = 40                  # THD: orders 2…40 (IEC 61000-4-7)
    estimate_frequency: bool = True
    f1_method: str = "phase"                  # "phase" | "spectral"
    uncertainty_I: float = 0.0                # m_I: currents are increased by m_I (defined by the user)
    uncertainty_U: float = 0.0                # m_U: voltages are reduced by m_U (defined by the user)
    correct_polarity: bool = True        # Iw < 0 → rotate the current phasors by 180°
    max_search_hop: Optional[float] = None      # finer search for the max window [s]; None = T_hop
    # scaling of the harmonic content to the 95 % quantile of a power-quality (PQ) measurement
    u_thd95_percent: Optional[float] = None    # THD (L-L), 95 % quantile in %
    u_thd95_volt: Optional[float] = None       # alternatively harmonic voltage (L-L) in V
    pq_u95: Optional[Dict[int, float]] = None  # 95 % quantile per order in V (positive/negative sequence scaled with it)
    pq_u95_reference: str = "seq"           # reference of pq_u95: "seq" (line-to-earth) | "LL" (line-to-line)
    pq_min_level_V: float = 1.0             # smallest level of an order in the test for its own factor in V
    pq_safety_factor: float = 1.0          # factor k_s on the 95 % quantile (1 = none)
    thd_reference: str = "mean"                  # reference of the measured THD: "pre_fault"|"post_fault"|"mean"
    transformer_voltage: str = "mv"                 # side of the transformer currents: "mv" | "hv"
    transformer_sign: Optional[float] = None   # None: automatic (upstream impedance), +1 as measured, −1 reversed
    # limits – defined by the user (groundfault contains none)
    ires_limits: Tuple[float, ...] = ()          # residual-current limits in A (extrapolation); () = none
    u_tp: Optional[float] = None                 # permissible touch voltage U_Tp in V
    f_factor: Optional[float] = None             # factor F of the permissible earth potential rise F·U_Tp
    # disturbed states (active residual current increase, steps of the reactive component) are not the reference
    exclude_disturbances: bool = True
    disturbance_threshold: float = dist.THRESHOLD    # smallest step as a share of |I_H1| of the undisturbed state

    def __post_init__(self):
        _check_settings(self)
        self.ires_limits = tuple(float(x) for x in self.ires_limits)

    def current_orders(self) -> List[int]:
        """Assessed orders of the fault current, always including the fundamental (sorted)."""
        o = sorted(set(int(m) for m in self.harmonics) | {1})
        return o

    def computation_orders(self) -> List[int]:
        """All orders whose phasors are computed: THD, assessment, export and voltage orders (sorted)."""
        return sorted(set(range(1, int(self.thd_max_order) + 1)) | set(self.current_orders())
                      | set(self.export_orders) | set(self.voltage_harmonics))


# allowed values of the text options of Settings
_THD_REFERENCES = ("pre_fault", "post_fault", "mean")
_U95_REFERENCES = ("seq", "LL")
_TRANSFORMER_VOLTAGES = ("mv", "hv")


def _positive(x) -> bool:
    """True for a finite number > 0 (not a bool)."""
    try:
        return not isinstance(x, (bool, np.bool_)) and math.isfinite(float(x)) and float(x) > 0
    except (TypeError, ValueError):
        return False


def _check_settings(e: Settings) -> None:
    """Check the options of the settings (also before an evaluation, after a later change of an attribute): the text
    options, the user-defined limits, the uncertainty margins and the factor on the 95 % quantile."""
    check_option("window", str(e.window).lower(), dsp.WINDOWS, aliases=dsp._WINDOW_ALIASES)
    check_option("dc", e.dc, dsp.DC_FILTERS, aliases=(None,))
    if not _positive(e.dc_cutoff_hz) or float(e.dc_cutoff_hz) > 0.25 * float(e.f_nominal):
        raise ValueError(tr("evaluation.cutoff_invalid", value=e.dc_cutoff_hz, fmax=0.25 * float(e.f_nominal)))
    check_option("f1_method", e.f1_method, dsp.F1_METHODS)
    check_option("thd_reference", e.thd_reference, _THD_REFERENCES)
    check_option("pq_u95_reference", e.pq_u95_reference, _U95_REFERENCES)
    if e.pq_u95 is not None and not isinstance(e.pq_u95, Mapping):
        raise ValueError(tr("evaluation.pq_u95_invalid", value=e.pq_u95))
    if not (isinstance(e.pq_min_level_V, (int, float)) and not isinstance(e.pq_min_level_V, bool)
            and math.isfinite(float(e.pq_min_level_V)) and float(e.pq_min_level_V) >= 0):
        raise ValueError(tr("evaluation.pq_min_level_invalid", value=e.pq_min_level_V))
    check_option("transformer_voltage", e.transformer_voltage, _TRANSFORMER_VOLTAGES)
    limits = e.ires_limits
    if isinstance(limits, (str, bytes)) or not hasattr(limits, "__iter__") or \
            not all(_positive(x) for x in limits):
        raise ValueError(tr("evaluation.limits_invalid", value=limits))
    for name in ("u_tp", "f_factor"):
        value = getattr(e, name)
        if value is not None and not _positive(value):
            raise ValueError(tr("evaluation.positive_or_none", name=name, value=value))
    for name in ("uncertainty_I", "uncertainty_U"):
        value = getattr(e, name)
        try:
            ok = not isinstance(value, bool) and 0.0 <= float(value) < 1.0
        except (TypeError, ValueError):
            ok = False
        if not ok:
            raise ValueError(tr("evaluation.uncertainty_invalid", name=name, value=value))
    if not _positive(e.pq_safety_factor):
        raise ValueError(tr("evaluation.factor_invalid", name="pq_safety_factor", value=e.pq_safety_factor))
    if not isinstance(e.exclude_disturbances, (bool, np.bool_)):
        raise ValueError(tr("evaluation.bool_invalid", name="exclude_disturbances", value=e.exclude_disturbances))
    try:
        ok = not isinstance(e.disturbance_threshold, bool) and 0.0 < float(e.disturbance_threshold) < 1.0
    except (TypeError, ValueError):
        ok = False
    if not ok:
        raise ValueError(tr("evaluation.share_invalid", name="disturbance_threshold", value=e.disturbance_threshold))
    if e.transformer_sign is not None and (isinstance(e.transformer_sign, (bool, np.bool_)) or
                                           e.transformer_sign not in (1, -1)):
        raise ValueError(tr("evaluation.sign_invalid", name="transformer_sign", value=e.transformer_sign))


@dataclass
class Intervals:
    """Analysis intervals in seconds from the start of the recording (read off the interval plot by hand).

    Attributes
    ----------
    steady_state : (float, float) or None
        Steady-state earth fault; the assessment uses the max window inside this interval. None = the whole
        recording.
    pre_fault : (float, float) or None
        Interval before fault inception (background level, voltage harmonics without the fault).
    post_fault : (float, float) or None
        Interval after fault clearance.
    """
    steady_state: Optional[Interval] = None
    pre_fault: Optional[Interval] = None
    post_fault: Optional[Interval] = None

    def check(self, duration_s: float) -> List[str]:
        """Check the intervals against the length of the recording.

        Parameters
        ----------
        duration_s : float
            Length of the recording in s.

        Returns
        -------
        list of str
            Hints on overlapping intervals (pre-fault interval ending after the start of the steady-state
            interval, post-fault interval starting before its end).

        Raises
        ------
        ValueError
            If an interval lies outside 0 … ``duration_s`` or its start is not before its end.
        """
        hints = []
        for name in ("steady_state", "pre_fault", "post_fault"):
            b = getattr(self, name)
            if b is None:
                continue
            if not (0 <= b[0] < b[1] <= duration_s + 1e-9):
                raise ValueError(tr("evaluation.interval_invalid", name=name, interval=b, duration=duration_s))
        if self.steady_state and self.pre_fault and self.pre_fault[1] > self.steady_state[0]:
            hints.append(tr("evaluation.pre_fault_overlap"))
        if self.steady_state and self.post_fault and self.post_fault[0] < self.steady_state[1]:
            hints.append(tr("evaluation.post_fault_overlap"))
        return hints


# ====================================================================== helpers
_ALIGNMENT_KEYS = ("dt_s", "roles", "channels")


def _shift(rec: Recording, roles: RoleAssignment, alignment: Optional[dict]):
    """Sample offset per channel index from ``alignment`` (``dt_s`` and the roles/channels to shift), or None.

    Unknown keys (also the former ``rollen``/``kanaele``) and unknown roles raise a ValueError; role names of the
    predecessor tool are translated as in the role overrides."""
    if alignment:
        check_keys("alignment", alignment, _ALIGNMENT_KEYS)
    if not alignment or not alignment.get("dt_s"):
        return None
    dn = int(round(float(alignment["dt_s"]) * rec.fs))
    idx = {k.index for r in alignment.get("roles", []) for k in roles.with_role(canonical_role(r, "alignment"))}
    for nm in alignment.get("channels", []):
        idx.add(rec.index(nm))
    return {i: dn for i in idx}


def load_blocks(rec: Recording, intervals: Dict[str, Optional[Interval]],
                 shift=None) -> Dict[str, Tuple[int, np.ndarray]]:
    """Read all channels of each named interval.

    Parameters
    ----------
    rec : Recording
        The recording.
    intervals : dict
        ``{name: (t0, t1)}`` in s from the start of the recording; entries with None are skipped.
    shift : dict, optional
        Sample offset per channel index (``{index: Δn}``): these channels are read Δn samples later, which
        compensates a time offset between recorder subsystems; samples outside the file become NaN.

    Returns
    -------
    dict
        ``{name: (i0, values)}`` – index of the first sample and an array (samples × channels) of physical
        values.
    """
    out = {}
    for name, b in intervals.items():
        if b is None:
            continue
        i0 = int(round(b[0] * rec.fs)); i1 = int(round(b[1] * rec.fs))
        out[name] = (i0, rec.read(i0, i1, None, shift))
    return out


def condition_blocks(blocks: Dict[str, Tuple[int, np.ndarray]], rec: Recording,
                     settings: "Settings") -> Dict[str, Tuple[int, np.ndarray]]:
    """The intervals of [`load_blocks`][groundfault.evaluation.load_blocks] as the windows see them: with
    ``settings.dc`` in [`HIGHPASS_FILTERS`][groundfault.dsp.HIGHPASS_FILTERS] (``"highpass"``, the default, or
    ``"highpass_median"``) every interval passes the zero-phase high-pass
    [`groundfault.dsp.highpass`][groundfault.dsp.highpass] (cut-off ``settings.dc_cutoff_hz``, mirror padding); with a
    DC removal per window only, the intervals are returned unchanged. The evaluation, the scan for disturbed states
    and the suggestion of the steady-state interval use the same signals."""
    if settings.dc not in dsp.HIGHPASS_FILTERS:
        return blocks
    return {k: (i0, dsp.highpass(x, rec.fs, settings.dc_cutoff_hz, axis=0)) for k, (i0, x) in blocks.items()}


def _reference_signal(block: np.ndarray, roles: RoleAssignment):
    """Reference signal of the frequency estimation and its display name: U_L1-L2 (from the line-to-earth
    voltages), a measured line-to-line voltage, U_L1-L2 of the HV side, U_NE, U_GEN, U_E, I_RES or channel 1."""
    le = roles.line_to_earth
    if le:
        return block[:, le[0]] - block[:, le[1]], tr("evaluation.reference_ll")
    for r in ("u_l12", "u_l23", "u_l31"):
        if roles.has(r):
            return block[:, roles.index(r)], r
    hv = roles.line_to_earth_hv
    if hv:
        return block[:, hv[0]] - block[:, hv[1]], tr("evaluation.reference_ll_hv")
    for r in ("u_ne", "u_gen", "u_e", "i_res"):
        if roles.has(r):
            return block[:, roles.index(r)], r
    return block[:, 0], tr("evaluation.reference_channel_1")


@dataclass
class _BlockAnalysis:
    """Window analysis of one interval: frequency, true RMS values and phasors of all channels per window."""
    name: str
    t0: float
    f1: dict
    t_mid: np.ndarray            # (n_w,) window centres in s
    rms: np.ndarray                # (n_w, k)
    X: np.ndarray                  # (n_w, k, n_ord) complex RMS phasors
    orders: List[int]
    nan_window: np.ndarray        # (n_w,) bool: window contains NaN

    def ix(self, m: int) -> int:
        """Index of the order ``m`` in the last axis of ``X``."""
        return self.orders.index(m)


def _analyse(name: str, i0: int, block: np.ndarray, rec: Recording, roles: RoleAssignment,
                e: Settings, T_hop: Optional[float] = None) -> _BlockAnalysis:
    """Frequency estimation, window grid, true RMS values and phasors of all channels of one interval."""
    fs = rec.fs
    ref, ref_name = _reference_signal(block, roles)
    if e.estimate_frequency:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            f1 = dsp.estimate_f1(ref[np.isfinite(ref)], fs, e.f_nominal, e.f1_method)
        f1["reference"] = ref_name
        if not f1["plausible"]:
            f1["f1_used"] = e.f_nominal if abs(f1["f1"] - e.f_nominal) > 0.5 else f1["f1"]
        else:
            f1["f1_used"] = f1["f1"]
    else:
        f1 = dict(f1=e.f_nominal, f1_used=e.f_nominal, method="rated_value", plausible=True, reference="-",
                  note="", prominence=float("nan"), f1_comparison=float("nan"), deviation_hz=float("nan"))
    nwin, nhop, starts = dsp.window_grid(block.shape[0], fs, e.T_win, T_hop or e.T_hop or e.T_win)
    if len(starts) == 0:
        raise ValueError(tr("evaluation.interval_too_short", name=name, window_ms=1000 * e.T_win))
    ords = e.computation_orders()
    freqs = np.asarray(ords, float) * f1["f1_used"]
    if freqs.max() >= fs / 2:
        ok = freqs < fs / 2.2
        ords = [o for o, k in zip(ords, ok) if k]
        freqs = freqs[ok]
        warnings.warn(tr("evaluation.orders_limited", fs=fs, order=max(ords)))
    k = block.shape[1]
    X = np.empty((len(starts), k, len(ords)), complex)
    rms = np.empty((len(starts), k))
    for j in range(k):
        seg = dsp.window_view(block[:, j], nwin, nhop)
        Xj, rj = dsp.dft_phasors(seg, fs, freqs, e.window, dsp.window_dc(e.dc))
        X[:, j, :] = Xj; rms[:, j] = rj
    nanf = ~np.isfinite(rms).all(axis=1)
    t_mid = (i0 + starts + nwin / 2.0) / fs
    return _BlockAnalysis(name, i0 / fs, f1, t_mid, rms, X, ords, nanf)


def _qstat(values: np.ndarray) -> Dict[str, float]:
    """Count, mean, standard deviation, minimum, maximum and 95 % quantile of the finite values."""
    v = np.asarray(values, float); v = v[np.isfinite(v)]
    if v.size == 0:
        return dict(n=0, mean=np.nan, std=np.nan, min=np.nan, max=np.nan, p95=np.nan)
    return dict(n=int(v.size), mean=float(v.mean()), std=float(v.std(ddof=1)) if v.size > 1 else 0.0,
                min=float(v.min()), max=float(v.max()), p95=float(np.percentile(v, 95)))


def _cx(z: complex) -> Dict[str, float]:
    """Complex number as ``{"re": …, "im": …}`` (result file)."""
    return {"re": float(np.real(z)), "im": float(np.imag(z))}


def _magang(z: complex) -> Dict[str, float]:
    """Phasor as ``{"mag_rms": …, "ang_deg": …}`` (result file)."""
    return {"mag_rms": float(abs(z)), "ang_deg": float(np.degrees(np.angle(z)))}


def _corrections_file(rec) -> str:
    """Corrections file of a recording relative to its campaign folder (for messages).

    Taken from the source of the applied corrections (``"0_Notizen/Korrekturen.csv, Zeile 3"`` →
    ``0_Notizen/Korrekturen.csv``); without such a source (corrections set by hand with
    [`set_correction`][groundfault.comtrade.Recording.set_correction]) the file of the folder layout of the recording
    (``notes/corrections.csv`` or ``0_Notizen/Korrekturen.csv``).
    """
    paths = []
    for k in getattr(rec, "corrections", None) or []:
        source = str(k.get("source") or "").strip()
        path = source.split(",", 1)[0].strip().replace("\\", "/")
        if path and path not in paths:
            paths.append(path)
    if paths:
        return ", ".join(paths)
    lay = detect_layout(getattr(rec, "cfg_path", None))
    return "%s/%s" % (lay.notes, lay.corrections_file)


# ====================================================================== result
@dataclass
class Result:
    """Result of [`evaluate`][groundfault.evaluation.evaluate] for one recording.

    Attributes
    ----------
    name : str
        Name of the measurement (default: file name without extension).
    recording_info : dict
        Header information of the recording ([`info`][groundfault.comtrade.Recording.info]).
    roles : RoleAssignment
        Channel roles used.
    settings : Settings
        Evaluation parameters used.
    intervals : Intervals
        Analysis intervals used.
    steady_state, pre_fault, post_fault
        Window analyses of the intervals (true RMS values ``rms`` and phasors ``X`` per window and channel, the
        frequency estimation ``f1``); ``pre_fault`` and ``post_fault`` are None if the interval was not given.
    max_index : int
        Index of the max window (largest residual current among the undisturbed windows) in ``steady_state``.
    polarity : int
        +1, or −1 if the fault-current phasors were rotated by 180° (Iw < 0).
    tables : dict of pandas.DataFrame
        Result tables, e.g. ``assessment_quantities``, ``harmonics``, ``coil_currents``, ``voltage_metrics``,
        ``station_voltages``, ``station_currents``, ``transformer_node``, ``transformer_power_change``,
        ``transformer_impedance``, ``transformer_power``, ``plausibility`` and ``statistics``.
    values : dict
        Scalar values (``IRES``, ``IG``, ``Iw``, ``Iv``, ``IH_total`` …) and nested structures (``voltage``, ``station``
        …). ``Iv`` is the detuning current from the angle method, Iv = I_H1·sin(φ_U0 − φ_I1) = ΣI_coil − I_C, > 0
        meaning over-compensated (the sign of
        [`groundfault.formulas.detuning_current`][groundfault.formulas.detuning_current] as well).
    hints : list of str
        Hints and warnings in the output language.
    result_set : dict
        Content of the result file ([`save_json`][groundfault.evaluation.Result.save_json]).
    disturbances : Disturbances or None
        Disturbed states found in the steady-state interval
        ([`groundfault.disturbances.detect`][groundfault.disturbances.detect]); None without a fault-current channel.
    reference : numpy.ndarray of bool or None
        Windows of ``steady_state`` used as the reference (finite values, undisturbed unless
        ``Settings.exclude_disturbances`` is False); see
        [`reference_windows`][groundfault.evaluation.Result.reference_windows].
    """
    name: str
    recording_info: dict
    roles: RoleAssignment
    settings: Settings
    intervals: Intervals
    steady_state: _BlockAnalysis
    pre_fault: Optional[_BlockAnalysis]
    post_fault: Optional[_BlockAnalysis]
    max_index: int
    polarity: int
    tables: Dict[str, pd.DataFrame] = field(default_factory=dict)
    values: Dict[str, object] = field(default_factory=dict)
    hints: List[str] = field(default_factory=list)
    result_set: Dict[str, object] = field(default_factory=dict)
    disturbances: Optional[dist.Disturbances] = None
    reference: Optional[np.ndarray] = None

    # ------------------------------------------------------------- convenience
    @property
    def reference_windows(self) -> np.ndarray:
        """Boolean mask of the windows of ``steady_state`` that form the reference: finite values and – unless
        ``Settings.exclude_disturbances`` is False – no disturbed state. The max window, the statistics and the
        checks over the interval use these windows."""
        if self.reference is not None:
            return self.reference
        return ~self.steady_state.nan_window

    @property
    def t_max_window(self) -> float:
        """Centre of the max window in s from the start of the recording."""
        return float(self.steady_state.t_mid[self.max_index])

    def phasor(self, channel_index: int, order: int, block: str = "steady_state",
               window: Optional[int] = None) -> complex:
        """Complex RMS phasor of one channel and order.

        Fault-current channels (role ``i_res``) are rotated by 180° if the polarity was corrected.

        Parameters
        ----------
        channel_index : int
            Index of the channel in the recording.
        order : int
            Harmonic order (1 = fundamental).
        block : str
            ``"steady_state"``, ``"pre_fault"`` or ``"post_fault"``.
        window : int, optional
            Window index; default: the max window for ``"steady_state"``, the first window otherwise.

        Returns
        -------
        complex
        """
        b = getattr(self, block)
        w = self.max_index if (window is None and block == "steady_state") else (window or 0)
        z = b.X[w, channel_index, b.ix(order)]
        if self.polarity < 0 and self.roles.channels[channel_index].role == "i_res":
            z = -z
        return complex(z)

    def table(self, name: str) -> pd.DataFrame:
        """Result table ``name`` (see ``tables``)."""
        return self.tables[name]

    def save_json(self, path: str) -> str:
        """Write the result file (JSON without raw data, read back with
        [`load_result`][groundfault.evaluation.load_result]).

        Parameters
        ----------
        path : str
            Target file; missing folders are created.

        Returns
        -------
        str
            ``path``.
        """
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.result_set, f, indent=1, ensure_ascii=False, allow_nan=True)
        return path

    def summary(self) -> str:
        """Short text summary: measurement, max window, f1, the main currents and all hints."""
        w = self.values
        z = [tr("evaluation.summary_measurement", name=self.name, file=self.recording_info.get("file")),
             tr("evaluation.summary_window", t=self.t_max_window, f1=self.steady_state.f1["f1_used"],
                method=self.steady_state.f1.get("method"))]
        if "IRES" in w:
            z.append(tr("evaluation.summary_currents", ires=w["IRES"], ig=w.get("IG", np.nan),
                        iw=w.get("Iw", np.nan), iv=w.get("Iv", np.nan), ih=w.get("IH_total", np.nan)))
        for h in self.hints:
            z.append("⚠ " + h)
        return "\n".join(z)


# ====================================================================== main function
def evaluate(rec: Recording, intervals: Intervals, settings: Optional[Settings] = None,
              roles: Optional[RoleAssignment] = None, alignment: Optional[dict] = None,
              name: Optional[str] = None, z_fault_ohm: Optional[float] = None,
              metadata: Optional[dict] = None) -> Result:
    """Evaluate one recording of a staged earth-fault test.

    Parameters
    ----------
    rec : Recording
        The recording (instantaneous values). Corrections already applied to it (e.g. from the corrections file of
        the campaign) are documented in the hints, the plausibility table and the result file.
    intervals : Intervals
        Analysis intervals; without a steady-state interval the whole recording is used.
    settings : Settings, optional
        Evaluation parameters (default: ``Settings()``).
    roles : RoleAssignment, optional
        Channel roles; detected from the channel names and units if not given.
    alignment : dict, optional
        Time offset of channels recorded with a different time base:
        ``{"dt_s": offset in s, "roles": [...], "channels": [...]}`` – the listed channels are read ``dt_s`` later (see
        [`load_blocks`][groundfault.evaluation.load_blocks]).
    name : str, optional
        Name of the measurement (default: file name without extension).
    z_fault_ohm : float, optional
        Fault resistance (additional impedance) of this measurement in Ω, stored with the result.
    metadata : dict, optional
        Additional entries of the section ``meta`` of the result file (e.g. ``campaign``, ``site``). For a recording
        inside a campaign folder ``campaign`` and ``site`` are taken from its path unless given here.

    Returns
    -------
    Result

    Raises
    ------
    ValueError
        If an interval lies outside the recording or is shorter than one window, if the sampling rate is too
        low for a harmonic analysis (RMS recordings), for an unknown value of a text option of ``settings`` or for
        an unknown key or role in ``alignment`` (also the former keys ``rollen``/``kanaele``).

    Notes
    -----
    The processing steps are described in the module documentation. All assessment quantities come from the
    same max window, so that magnitudes and phase angles of all channels belong to the same instant.

    Examples
    --------
    >>> from groundfault import Intervals, evaluate, open_recording
    >>> rec = open_recording("SUB_0_10_000kHz.cfg")                                  # doctest: +SKIP
    >>> res = evaluate(rec, Intervals((2.6, 4.4), (0.2, 1.8), (7.0, 8.8)), z_fault_ohm=0.0)  # doctest: +SKIP
    >>> print(res.summary())                                                           # doctest: +SKIP
    """
    e = settings or Settings()
    _check_settings(e)
    roles = roles or detect_roles(rec.channel_names, rec.units)
    if intervals.steady_state is None:
        intervals = Intervals((0.0, rec.duration_s), intervals.pre_fault, intervals.post_fault)
    hints = intervals.check(rec.duration_s)
    for k in getattr(rec, "corrections", []):
        hints.append(tr("evaluation.correction_applied", channel=k["short"], factor=k["factor"],
                        source=k.get("source") or tr("evaluation.manual"),
                        remark=" – " + k["remark"] if k.get("remark") else ""))
    if rec.fs < 20 * e.f_nominal:
        raise ValueError(tr("evaluation.sampling_rate_too_low", fs=rec.fs))
    shift_ = _shift(rec, roles, alignment)
    bl = load_blocks(rec, {"steady_state": intervals.steady_state, "pre_fault": intervals.pre_fault,
                            "post_fault": intervals.post_fault}, shift_)
    bl = condition_blocks(bl, rec, e)      # high-pass on every interval (mirror padding), then the mean per window
    st = _analyse("steady_state", *bl["steady_state"], rec, roles, e)
    vf = _analyse("pre_fault", *bl["pre_fault"], rec, roles, e) if "pre_fault" in bl else None
    nf = _analyse("post_fault", *bl["post_fault"], rec, roles, e) if "post_fault" in bl else None
    for b in (st, vf, nf):
        if b is not None and not b.f1["plausible"]:
            hints.append(tr("evaluation.f1_implausible", interval=b.name, note=b.f1.get("note", ""),
                            f1=b.f1["f1_used"]))
        if b is not None and b.nan_window.any():
            hints.append(tr("evaluation.nan_windows", count=int(b.nan_window.sum()), interval=b.name))

    # ---------------------------------------------------------------- disturbed states and max window
    ires = roles.main("i_res")
    use = ~st.nan_window
    found = None
    I1w = None
    orient = True
    min_step = dist.STEP_MIN_A
    if ires is not None:
        I1w, U0w, rmsw, coilw = dist.window_phasors(st, roles)
    elif roles.capabilities()["transformer"] and roles.line_to_earth and (vf is not None or nf is not None):
        # no fault-current channel: estimate the fault current from the negative-sequence current of the transformer
        est = trafo.detection_input(st, vf if vf is not None else nf, roles, e,
                                    other_block=nf if vf is not None else None)
        if est is not None:
            I1w, U0w, coilw, ph, _ = est
            rmsw = None
            orient = False
            min_step = max(dist.STEP_MIN_A, trafo.NOISE_FACTOR * trafo.estimate_noise(I1w, U0w))
            hints.append(tr("transformer.fault_current_estimated", phase="L%d" % (ph + 1),
                            base=tr("transformer.base_pre_fault" if vf is not None else "transformer.base_post_fault")))
    if I1w is not None:
        found = dist.detect(st.t_mid, I1w, U0w, rmsw, coilw, threshold=e.disturbance_threshold, T_win=e.T_win,
                            orient=orient, min_step_A=min_step)
        if found.found:
            parts = found.parts_text()
            if not e.exclude_disturbances:
                hints.append(tr("disturbances.not_excluded", parts=parts))
                found.segments["used"] = True
            elif (use & found.reference).any():
                use = use & found.reference
                hints.append(tr("disturbances.excluded", parts=parts, reference=found.reference_text()))
            else:
                hints.append(tr("disturbances.no_reference", parts=parts))
                found.segments["used"] = True
        hints.extend(found.notes())
    if ires is not None and use.any():
        r = np.where(use, st.rms[:, ires.index], -np.inf)
        wi = int(np.argmax(r))
    else:
        wi = 0
    if e.max_search_hop and ires is not None and e.max_search_hop < (e.T_hop or e.T_win):
        fine = _analyse("steady_state", *bl["steady_state"], rec, roles, e, T_hop=e.max_search_hop)
        ok_f = ~fine.nan_window
        if (use != ~st.nan_window).any():      # disturbed states excluded: only fine windows inside the reference
            ok_f &= _covered(fine.t_mid, st.t_mid[use], e.T_win)
        r = np.where(ok_f, fine.rms[:, ires.index], -np.inf)
        wf = int(np.argmax(r))
        # the max window of the finer grid replaces the max window of the standard grid (nearest centre)
        st.X[wi] = fine.X[wf]; st.rms[wi] = fine.rms[wf]; st.t_mid[wi] = fine.t_mid[wf]
    res = Result(name=name or os.path.splitext(os.path.basename(rec.cfg_path))[0], recording_info=rec.info(),
                   roles=roles, settings=e, intervals=intervals, steady_state=st, pre_fault=vf,
                   post_fault=nf, max_index=wi, polarity=1, hints=hints, disturbances=found, reference=use)
    if found is not None:
        res.tables["steady_state_segments"] = found.segments
    _assessment_quantities(res, z_fault_ohm)
    _voltage_analysis(res)
    _harmonic_scaling(res)
    if roles.capabilities()["station"]:
        _station(res)
        from .station import frequency_selective
        try:
            frequency_selective(res, rec, shift_)
        except Exception as ex:                       # the additional evaluation must never stop the main one
            res.hints.append(tr("evaluation.station_failed", error=ex))
    if roles.capabilities()["transformer"]:
        trafo.node_analysis(res)
    if roles.line_to_earth is not None and roles.line_to_earth_hv is not None:
        trafo.voltage_divider(res)
    _plausibility(res, rec, bl)
    _statistics(res)
    _result_set(res, rec, z_fault_ohm, _campaign_metadata(rec, metadata), alignment)
    return res


def _covered(t_mid: np.ndarray, t_ref: np.ndarray, T_win: float) -> np.ndarray:
    """Windows (centres ``t_mid``, length ``T_win``) that lie completely inside the time span covered by the windows
    with the centres ``t_ref`` (union of their spans)."""
    half = T_win / 2.0
    spans = []
    for t in np.sort(np.asarray(t_ref, float)):
        if spans and t - half <= spans[-1][1] + 1e-9:
            spans[-1][1] = t + half
        else:
            spans.append([t - half, t + half])
    out = np.zeros(len(t_mid), bool)
    for a, b in spans:
        out |= (t_mid - half >= a - 1e-9) & (t_mid + half <= b + 1e-9)
    return out


def _campaign_metadata(rec: Recording, metadata: Optional[dict]) -> dict:
    """``metadata`` completed with ``campaign`` and ``site`` from the path of a recording inside a campaign folder
    (``<campaigns>/<campaign>/<raw>/<site>/…``); given values are kept."""
    md = dict(metadata or {})
    path = getattr(rec, "cfg_path", None)
    if path and ("campaign" not in md or "site" not in md):
        from .layout import campaign_root
        from .sites import site_from_path
        root = campaign_root(path)
        if root:
            md.setdefault("campaign", os.path.basename(os.path.normpath(root)))
            md.setdefault("site", site_from_path(os.path.relpath(path, root)))
    return md


# ====================================================================== partial evaluations
def _assessment_quantities(res: Result, z_fault_ohm: Optional[float]) -> None:
    """Assessment quantities in the max window (table ``assessment_quantities``), coil currents and the harmonics
    of all channels."""
    e, st, roles, wi = res.settings, res.steady_state, res.roles, res.max_index
    rows = []
    mI, mU = e.uncertainty_I, e.uncertainty_U

    def line(quantity, description, value, unit, kind="I", complex_=None, equation=""):
        assess = fml.current_with_uncertainty(value, mI) if kind == "I" else (fml.voltage_with_uncertainty(value, mU)
                                                              if kind == "U" else value)
        rows.append(dict(quantity=quantity, description=description, measured_value=value,
                           assessment=assess, unit=unit, equation=equation,
                           angle_deg=(np.degrees(np.angle(complex_)) if complex_ is not None else np.nan)))

    ires = roles.main("i_res")
    le = roles.line_to_earth
    phi_ll = None
    if le:
        u12_1 = st.X[wi, le[0], st.ix(1)] - st.X[wi, le[1], st.ix(1)]
        phi_ll = float(np.angle(u12_1))
    if ires is not None:
        j = ires.index
        I = {m: st.X[wi, j, st.ix(m)] for m in st.orders}
        IRES = float(st.rms[wi, j])
        # ---- angle method with U0 = fundamental component of the zero sequence:
        #      Iw = |I1|·cos(φU0 − φI1), Iv = |I1|·sin(φU0 − φI1)
        U0 = None
        if le:
            U0 = sum(st.X[wi, k, st.ix(1)] for k in le) / 3.0
        elif roles.has("u_ne"):
            U0 = st.X[wi, roles.index("u_ne"), st.ix(1)]
        pol = 1
        Iw = Iv = np.nan
        if U0 is not None and abs(U0) > 0 and abs(I[1]) > 0:
            dphi = np.angle(U0) - np.angle(I[1])
            Iw = abs(I[1]) * math.cos(dphi); Iv = abs(I[1]) * math.sin(dphi)
            # margin of the polarity decision: angular distance of the current phasor from the ±90° limit. With a
            # small active component (large detuning) a phase error of the measuring chain can flip the sign of Iw.
            margin = math.degrees(math.asin(min(1.0, abs(Iw) / abs(I[1]))))
            res.values["polarity_margin_deg"] = margin
            if margin < 10.0:
                res.hints.append(tr("evaluation.polarity_uncertain", share=100 * abs(Iw) / abs(I[1]), margin=margin))
            if Iw < 0:
                if e.correct_polarity:
                    pol = -1; Iw, Iv = -Iw, -Iv
                    res.hints.append(tr("evaluation.polarity_corrected"))
                else:
                    res.hints.append(tr("evaluation.polarity_negative"))
        res.polarity = pol
        I = {m: pol * z for m, z in I.items()}
        IG = abs(I[1])
        ih_all = np.array([abs(I[m]) for m in st.orders if m >= 2])
        IH_sum = float(np.sqrt(np.sum(ih_all ** 2)))
        IH_total = fml.harmonic_current(IRES, IG)
        sel = [m for m in e.current_orders()]
        plaus_sel = abs(IRES - math.sqrt(sum(abs(I[m]) ** 2 for m in sel))) / IRES if IRES > 0 else np.nan
        plaus_all = abs(IRES - math.sqrt(IG ** 2 + IH_sum ** 2)) / IRES if IRES > 0 else np.nan
        line("IRES", tr("evaluation.desc_ires"), IRES, "A", "I", equation=_EQUATIONS["IRES"])
        line("Iw", tr("evaluation.desc_iw"), Iw, "A", "I", equation=_EQUATIONS["Iw"])
        line("Iv", tr("evaluation.desc_iv"), Iv, "A", "I", equation=_EQUATIONS["Iv"])
        line("IH1", tr("evaluation.desc_ih1"), IG, "A", "I",
              complex_=(I[1] * np.exp(-1j * phi_ll) if phi_ll is not None else I[1]), equation=_equation_harmonic(1))
        for m in sel:
            if m == 1:
                continue
            line("IH%d" % m, tr("evaluation.desc_harmonic", order=m, f=m * st.f1["f1_used"]), abs(I[m]), "A", "I",
                  complex_=(I[m] * np.exp(-1j * m * phi_ll) if phi_ll is not None else I[m]),
                  equation=_equation_harmonic(m))
        line("IH_total", tr("evaluation.desc_ih_total"), IH_total, "A", "I", equation=_EQUATIONS["IH_total"])
        line("IH_sum", tr("evaluation.desc_ih_sum", order=max(st.orders)), IH_sum, "A", "I",
              equation="√(Σ I_Hm²), m = 2…%d" % max(st.orders))
        res.values["main_channel_i_res"] = ires.short
        res.values.update(IRES=IRES, IG=IG, Iw=Iw, Iv=Iv, IH_total=IH_total, IH_sum=IH_sum,
                         plaus_harmonic_selection=plaus_sel, plaus_harmonic_all=plaus_all,
                         I_phasors={m: I[m] for m in st.orders}, phi_LL1=phi_ll)
        if U0 is not None:
            res.values["U0"] = U0
            line("UH1n", tr("evaluation.desc_u0"), abs(U0), "V", "U",
                  complex_=(U0 * np.exp(-1j * phi_ll) if phi_ll is not None else U0))
        if z_fault_ohm is not None:
            res.values["Z_fault"] = float(z_fault_ohm)
    # ---- coil currents (split at 50 Hz)
    coils = []
    for k in roles.with_role("i_coil"):
        z = st.X[wi, k.index, st.ix(1)]
        coils.append(dict(channel=k.short, RMS_A=float(st.rms[wi, k.index]), H1_A=float(abs(z)),
                           H1_angle_ref_ULL_deg=float(np.degrees(np.angle(z) - (phi_ll or 0.0)))))
    res.tables["coil_currents"] = pd.DataFrame(coils)
    # ---- table of the assessment quantities (further fault-current CTs: see the plausibility checks)
    res.tables["assessment_quantities"] = pd.DataFrame(rows)
    # ---- harmonics of all channels (max window)
    hz = []
    for k in roles.channels:
        polk = res.polarity if k.role == "i_res" else 1
        for m in st.orders:
            z = polk * st.X[wi, k.index, st.ix(m)]
            zb = z * np.exp(-1j * m * phi_ll) if phi_ll is not None else z
            hz.append(dict(channel=k.short, role=k.role, order=m, f_Hz=m * st.f1["f1_used"],
                           magnitude=float(abs(z)), angle_deg=float(np.degrees(np.angle(z))),
                           angle_ref_ULL_deg=float(np.degrees(np.angle(zb))), unit=k.unit))
    res.tables["harmonics"] = pd.DataFrame(hz)


def _voltage_quantities(b: _BlockAnalysis, le: List[int], window: Optional[int] = None):
    """Phasors (windows × orders) of the nine voltage quantities (L-E, L-L, zero/positive/negative sequence) of
    all windows or of a single window."""
    sl = slice(None) if window is None else slice(window, window + 1)
    ua, ub, uc = (b.X[sl, k, :] for k in le)
    u0, u1, u2 = fortescue(ua, ub, uc)
    u12, u23, u31 = line_to_line(ua, ub, uc)
    return {"U_L1E": ua, "U_L2E": ub, "U_L3E": uc, "U_L12": u12, "U_L23": u23, "U_L31": u31,
            "U_zero": u0, "U_pos": u1, "U_neg": u2}


def _voltage_analysis(res: Result) -> None:
    """Voltage analysis per interval (pre-fault, fault = max window, post-fault): median magnitudes per order,
    complex sequence phasors referred to U_L1-L2 and the characteristic values (THD, U_H5g, U_H7m, U0)."""
    le = res.roles.line_to_earth
    if not le:
        return
    e = res.settings
    st = res.steady_state
    blocks = [("pre_fault", res.pre_fault, None), ("fault", st, res.max_index),
               ("post_fault", res.post_fault, None)]
    ords = st.orders
    sp = {"harmonics_hz": [], "orders": ords}
    tab_magnitude, tab_metrics = {}, []
    for name, b, win in blocks:
        if b is None:
            continue
        q = _voltage_quantities(b, le, win)
        ok = ~b.nan_window if win is None else np.ones(1, bool)
        mags = {k: np.median(np.abs(v[ok]), axis=0) for k, v in q.items()}         # median over the windows
        # complex sequence phasors referred to L1-L2: X_m·e^{−j m φ_LL1} per window, then averaged (complex)
        phi1 = np.angle(q["U_L12"][:, b.ix(1)])
        rot = np.exp(-1j * np.outer(phi1, np.asarray(ords, float)))
        ph = {k: np.mean((q[k] * rot)[ok], axis=0) for k in ("U_pos", "U_neg", "U_zero", "U_L1E",
                                                               "U_L2E", "U_L3E")}
        sp[name] = {k: [float(x) for x in v] for k, v in mags.items()}
        sp[name + "_phasor"] = {k: [_cx(z) for z in v] for k, v in ph.items()}
        if name == "pre_fault":
            # coil currents before the fault, same windows and reference (change of the coil current, node rule)
            coils = res.roles.with_role("i_coil")
            if coils:
                sp["coil_pre_phasor"] = {k.name: [_cx(z) for z in np.mean((b.X[:, k.index, :] * rot)[ok], axis=0)]
                                         for k in coils}
        sp["harmonics_hz"] = [float(m * b.f1["f1_used"]) for m in ords]
        tab_magnitude[name] = pd.DataFrame(mags, index=pd.Index(ords, name="order"))
        # characteristic values
        i5 = b.ix(5) if 5 in ords else None; i7 = b.ix(7) if 7 in ords else None
        oo = np.asarray(ords)
        tag = dict(interval=name, t0_s=float(b.t_mid[ok][0] - e.T_win / 2) if win is None else
                    float(b.t_mid[win] - e.T_win / 2),
                    f1_Hz=b.f1["f1_used"],
                    U_pos_H1_V=float(mags["U_pos"][b.ix(1)]),
                    UH5g_V=float(mags["U_neg"][i5]) if i5 is not None else np.nan,
                    UH7m_V=float(mags["U_pos"][i7]) if i7 is not None else np.nan)
        for k, short in (("U_L12", "12"), ("U_L23", "23"), ("U_L31", "31")):
            uh = float(np.sqrt(np.sum(mags[k][oo >= 2] ** 2)))
            tag["UTHD%s_pct" % short] = 100 * uh / float(mags[k][b.ix(1)]) if mags[k][b.ix(1)] > 0 else np.nan
            tag["UH%s_V" % short] = uh
        tag["Uzero_H1_V"] = float(mags["U_zero"][b.ix(1)])
        tab_metrics.append(tag)
    # fault: complex sequence phasors averaged over the used windows of the steady state (the max window above is a
    # single window) – busbar voltages of an earth fault for the network model
    use = res.reference_windows
    ok = (use & ~st.nan_window) if len(use) == len(st.nan_window) else ~st.nan_window
    if ok.any():
        q = _voltage_quantities(st, le, None)
        phi1 = np.angle(q["U_L12"][:, st.ix(1)])
        rot = np.exp(-1j * np.outer(phi1, np.asarray(ords, float)))
        sp["fault_mean_phasor"] = {k: [_cx(z) for z in np.mean((q[k] * rot)[ok], axis=0)]
                                   for k in ("U_pos", "U_neg", "U_zero", "U_L1E", "U_L2E", "U_L3E")}
        sp["fault_mean_windows"] = int(ok.sum())
        # coil currents averaged over the same windows (as recorded – orientation and sum are left to the user)
        coils = res.roles.with_role("i_coil")
        if coils:
            sp["coil_mean_phasor"] = {k.name: [_cx(z) for z in np.mean((st.X[:, k.index, :] * rot)[ok], axis=0)]
                                      for k in coils}
    res.values["voltage"] = sp
    res.tables["voltage_metrics"] = pd.DataFrame(tab_metrics)
    for name, df in tab_magnitude.items():
        res.tables["voltage_" + name] = df


def _harmonic_scaling(res: Result) -> None:
    """Scale the harmonic content to the 95 % quantile of a power-quality measurement (rows of the table
    ``assessment_quantities`` and the table ``harmonic_scaling`` per order): every order of the positive or negative
    sequence with its own voltage (``pq_u95``: k_m = k_s·U_95,m/U_m), without its own value with the THD
    (U_95/U_meas); the zero sequence, the even orders and the content not assigned to an order as measured.
    I_RMS = √(I_G² + I_H,scaled²)."""
    e = res.settings
    have_thd = e.u_thd95_percent is not None or e.u_thd95_volt is not None
    if "IRES" not in res.values or not (have_thd or e.pq_u95):
        return
    mI, mU = e.uncertainty_I, e.uncertainty_U
    sf = float(e.pq_safety_factor)
    choice = {"pre_fault": ["pre_fault"], "post_fault": ["post_fault"],
              "mean": ["pre_fault", "post_fault"]}[e.thd_reference]
    # ---- flat factor of the THD: U_95/U_meas (maximum of the three loops, averaged over the reference intervals)
    u_meas = u95_thd = float("nan")
    f_thd = None
    unit = "%" if e.u_thd95_percent is not None else "V"
    if have_thd:
        tag = res.tables.get("voltage_metrics")
        rows = None
        if tag is None or tag.empty:
            res.hints.append(tr("evaluation.scaling_no_voltage"))
        else:
            rows = tag[tag["interval"].isin(choice)]
            if rows.empty:
                res.hints.append(tr("evaluation.scaling_no_reference", reference=e.thd_reference))
                rows = None
        if rows is None and not e.pq_u95:
            return
        if rows is not None:
            columns = (["UTHD12_pct", "UTHD23_pct", "UTHD31_pct"] if e.u_thd95_percent is not None
                       else ["UH12_V", "UH23_V", "UH31_V"])
            u_meas = float(np.nanmean(rows[columns].max(axis=1)))
            u95_thd = (e.u_thd95_percent if e.u_thd95_percent is not None else e.u_thd95_volt) * sf
            if np.isfinite(u_meas) and u_meas > 0:
                f_thd = u95_thd / u_meas
    # ---- level of the natural sequence of every order before/after the fault (the source of its current)
    v = res.values.get("voltage") or {}
    v_orders = [int(o) for o in v.get("orders", [])]

    def level(m: int) -> float:
        if m not in v_orders:
            return float("nan")
        key = "U_" + {1: "pos", 2: "neg", 0: "zero"}[m % 3]
        vals = [float(v[b][key][v_orders.index(m)]) for b in choice if isinstance(v.get(b), dict) and key in v[b]]
        return float(np.mean(vals)) if vals else float("nan")

    u95 = {}
    for key_, val in (e.pq_u95 or {}).items():
        try:
            u95[int(key_)] = float(val) if val is not None else float("nan")
        except (TypeError, ValueError):
            continue
    ll = e.pq_u95_reference == "LL"
    ph = res.values.get("I_phasors") or {}
    ih, ig = float(res.values["IH_total"]), float(res.values["IG"])
    f1 = float(res.steady_state.f1["f1_used"]) if res.steady_state is not None else float(e.f_nominal)
    table, s_known, s2, s2a, without = [], 0.0, 0.0, 0.0, []
    for m in sorted(int(x) for x in ph):
        if m < 2:
            continue
        i_m = float(abs(ph[m]))
        lv = level(m)
        u = u95.get(m)
        k, rule = fml.order_scaling(m, u, lv, f_thd=f_thd, safety_factor=sf, from_ll=ll,
                                    min_level=float(e.pq_min_level_V))
        # assessment values: the currents + m_I, the voltages of the test − m_U (the factor grows by 1/(1 − m_U))
        ka = k / (1.0 - mU) if rule in ("own voltage", "THD") else 1.0
        if e.pq_u95 and rule in ("THD", "no information"):
            without.append(m)
        table.append(dict(order=m, f_Hz=m * f1, category=fml.harmonic_category(m), I_A=i_m, U_level_V=lv,
                          U95_V=u if u is not None else float("nan"), factor=k, rule=rule, I_scaled_A=k * i_m))
        s_known += i_m ** 2
        s2 += (k * i_m) ** 2
        s2a += (ka * i_m) ** 2
    tab = pd.DataFrame(table, columns=["order", "f_Hz", "category", "I_A", "U_level_V", "U95_V", "factor", "rule",
                                       "I_scaled_A"])
    i_other = math.sqrt(max(ih ** 2 - s_known, 0.0))         # content without a phasor of an order (as measured)
    ih_s = math.sqrt(s2 + i_other ** 2)
    ih_s_assessed = (1.0 + mI) * math.sqrt(s2a + i_other ** 2)
    irms = fml.rms_current_forecast(ig, ih_s)
    quad = lambda cat: float(math.sqrt(float((tab.loc[tab["category"] == cat, "I_A"] ** 2).sum())))
    i_zero, i_even = quad("zero"), quad("even")
    res.values.update(UTHD_meas=u_meas, UTHD95=u95_thd, IH_scaled=ih_s, IRES_scaled=irms,
                      factor_scaling=f_thd if f_thd is not None else np.nan, IH_zero=i_zero, IH_even=i_even,
                      IH_other=i_other)
    res.tables["harmonic_scaling"] = tab
    if without:
        res.hints.append(tr("evaluation.scaling_without_own", orders=without, min_level=float(e.pq_min_level_V),
                            fallback=(tr("evaluation.scaling_thd_used", factor=f_thd) if f_thd is not None
                                      else tr("evaluation.scaling_as_measured"))))
    even = tab[tab["category"] == "even"]
    if len(even) and ih > 0 and i_even >= 0.05 * ih:
        top = even.loc[even["I_A"].idxmax()]
        res.hints.append(tr("evaluation.even_orders", current=i_even, share=100 * i_even / ih, order=int(top["order"]),
                            largest=float(top["I_A"])))
    df = res.tables["assessment_quantities"]
    rows_new = []
    if np.isfinite(u_meas):
        rows_new += [
            dict(quantity="UTHD_meas", description=tr("evaluation.desc_uthd_meas", reference=e.thd_reference),
                 measured_value=u_meas, assessment=fml.voltage_with_uncertainty(u_meas, mU), unit=unit,
                 equation=_EQUATIONS["UTHD_meas"], angle_deg=np.nan),
            dict(quantity="UTHD_95", description=tr("evaluation.desc_uthd_95", factor=sf),
                 measured_value=u95_thd, assessment=u95_thd, unit=unit, equation=_EQUATIONS["UTHD_95"],
                 angle_deg=np.nan)]
    for key_, value in (("IH_zero", i_zero), ("IH_even", i_even), ("IH_other", i_other)):
        rows_new.append(dict(quantity=key_, description=tr("evaluation.desc_" + key_.lower()), measured_value=value,
                             assessment=fml.current_with_uncertainty(value, mI), unit="A", equation=_EQUATIONS[key_],
                             angle_deg=np.nan))
    rows_new += [
        dict(quantity="IH_scaled", description=tr("evaluation.desc_ih_scaled"), measured_value=ih_s,
             assessment=ih_s_assessed, unit="A", equation=_EQUATIONS["IH_scaled"], angle_deg=np.nan),
        dict(quantity="IRMS_forecast", description=tr("evaluation.desc_irms_forecast"), measured_value=irms,
             assessment=fml.rms_current_forecast(fml.current_with_uncertainty(ig, mI), ih_s_assessed),
             unit="A", equation=_EQUATIONS["IRMS_forecast"], angle_deg=np.nan)]
    res.tables["assessment_quantities"] = pd.concat([df, pd.DataFrame(rows_new)], ignore_index=True)


def rescale_harmonics(result, u95: Optional[Mapping[int, float]] = None, u95_reference: str = "seq",
                      thd95_percent: Optional[float] = None, safety_factor: float = 1.0,
                      min_level_V: Optional[float] = None, uncertainty_I: Optional[float] = None,
                      uncertainty_U: Optional[float] = None, thd_reference: Optional[str] = None) -> dict:
    """Scale the harmonic currents of an evaluated recording to other power-quality quantiles.

    The same rules per order as the evaluation with ``Settings.pq_u95`` (see
    [`groundfault.formulas.order_scaling`][groundfault.formulas.order_scaling]), applied to the currents and voltage
    levels stored in a result – e.g. to scale every test of a campaign with the PQ measurement and the factor of the
    campaign, whatever the single evaluation used. Nothing in ``result`` is changed.

    Parameters
    ----------
    result : Result or ResultFile
        Evaluated recording with the fault current, its harmonics and the voltages before/after the fault.
    u95 : mapping of int to float, optional
        Quantile of the voltage per order in V (e.g. [`groundfault.pq.PQAssessment.u95`][groundfault.pq.PQAssessment.u95]).
    u95_reference : {"seq", "LL"}
        ``"LL"``: the quantiles are line-to-line values (divided by √3).
    thd95_percent : float, optional
        Quantile of the THD in % (line-to-line) – the flat factor for the orders without their own value.
    safety_factor : float
        Factor k_s on the quantiles.
    min_level_V : float, optional
        Smallest usable level of an order in V (default: the setting stored in the result, else 1 V).
    uncertainty_I, uncertainty_U : float, optional
        Margins m_I and m_U of the assessment values (default: the settings stored in the result).
    thd_reference : {"pre_fault", "post_fault", "mean"}, optional
        Interval(s) of the voltage levels and of the measured THD (default: the setting stored in the result).

    Returns
    -------
    dict
        ``table`` (per order: ``order``, ``f_Hz``, ``category``, ``I_A``, ``U_level_V``, ``U95_V``, ``factor``,
        ``rule``, ``I_scaled_A``), ``IG``, ``IH``, ``IH_scaled``, ``IH_scaled_assessed``, ``IRES_scaled``
        (I_RMS = √(I_G² + I_H,scaled²)), ``IRES_scaled_assessed``, ``IH_zero``, ``IH_even``, ``IH_other``,
        ``f_thd`` (THD factor or NaN), ``UTHD_meas`` and ``without`` (orders of the positive or negative sequence
        without their own value).

    Notes
    -----
    With the table ``harmonic_scaling`` of a scaled evaluation the currents and levels of all its orders are used, so
    that the result with the same quantiles and factor equals the stored one. Otherwise the currents are the harmonics
    of the main channel of the fault current (in a result file: the exported orders; the rest of the harmonic content
    stays as measured) and the levels the natural sequence of each order before/after the fault.
    """
    meas = getattr(result, "measurement", None) or {}
    stored = meas.get("settings", {}) if isinstance(meas, dict) else {}
    e = getattr(result, "settings", None)

    def setting(name, default):
        if e is not None and hasattr(e, name):
            return getattr(e, name)
        return stored.get(name, default)

    mI = float(setting("uncertainty_I", 0.0) if uncertainty_I is None else uncertainty_I)
    mU = float(setting("uncertainty_U", 0.0) if uncertainty_U is None else uncertainty_U)
    min_level = float(setting("pq_min_level_V", 1.0) if min_level_V is None else min_level_V)
    reference = thd_reference or setting("thd_reference", "mean") or "mean"
    check_option("thd_reference", reference, _THD_REFERENCES)
    check_option("u95_reference", u95_reference, _U95_REFERENCES)
    choice = {"pre_fault": ["pre_fault"], "post_fault": ["post_fault"], "mean": ["pre_fault", "post_fault"]}[reference]
    sf = float(safety_factor)
    values = result.values
    ig, ih = float(values.get("IG", np.nan)), float(values.get("IH_total", np.nan))
    f_nominal = float(setting("f_nominal", 50.0))
    # ---- measured THD of the test (largest loop, mean over the reference intervals)
    u_meas = float(values.get("UTHD_meas", np.nan))
    tag = result.tables.get("voltage_metrics")
    if tag is not None and not tag.empty:
        rows = tag[tag["interval"].isin(choice)]
        if len(rows):
            u_meas = float(np.nanmean(rows[["UTHD12_pct", "UTHD23_pct", "UTHD31_pct"]].max(axis=1)))
    f_thd = sf * float(thd95_percent) / u_meas if (thd95_percent is not None and np.isfinite(u_meas)
                                                    and u_meas > 0) else None
    # ---- currents and levels per order
    v = values.get("voltage") or {}
    v_orders = [int(o) for o in v.get("orders", [])]

    def level(m: int) -> float:
        if m not in v_orders:
            return float("nan")
        key = "U_" + {1: "pos", 2: "neg", 0: "zero"}[m % 3]
        vals = [float(v[b][key][v_orders.index(m)]) for b in choice if isinstance(v.get(b), dict) and key in v[b]]
        return float(np.mean(vals)) if vals else float("nan")

    base = result.tables.get("harmonic_scaling")
    if base is not None and not base.empty and {"order", "I_A", "U_level_V"} <= set(base.columns):
        items = [(int(r["order"]), float(r["I_A"]), float(r["U_level_V"]), float(r.get("f_Hz", np.nan)))
                 for _, r in base.iterrows()]
    else:
        ph = values.get("I_phasors")
        if ph:
            mags = {int(m): float(abs(x)) for m, x in ph.items()}
        else:
            h = result.tables.get("harmonics")
            mags = {}
            if h is not None and not h.empty:
                channel = values.get("main_channel_i_res")
                sub = h[(h["role"] == "i_res") & ((h["channel"] == channel) if channel else True)]
                if channel is None and len(sub):
                    sub = sub[sub["channel"] == sub["channel"].iloc[0]]
                mags = {int(r["order"]): float(r["magnitude"]) for _, r in sub.iterrows()}
        items = [(m, mags[m], level(m), m * f_nominal) for m in sorted(mags) if m >= 2]
    u95_ = {}
    for key_, val in (u95 or {}).items():
        try:
            u95_[int(key_)] = float(val) if val is not None else float("nan")
        except (TypeError, ValueError):
            continue
    ll = u95_reference == "LL"
    table, s_known, s2, s2a, without = [], 0.0, 0.0, 0.0, []
    for m, i_m, lv, f in items:
        u = u95_.get(m)
        k, rule = fml.order_scaling(m, u, lv, f_thd=f_thd, safety_factor=sf, from_ll=ll, min_level=min_level)
        ka = k / (1.0 - mU) if rule in ("own voltage", "THD") else 1.0
        if fml.harmonic_category(m) == "pos_neg" and rule in ("THD", "no information"):
            without.append(m)
        table.append(dict(order=m, f_Hz=f if np.isfinite(f) else m * f_nominal, category=fml.harmonic_category(m),
                          I_A=i_m, U_level_V=lv, U95_V=u if u is not None else float("nan"), factor=k, rule=rule,
                          I_scaled_A=k * i_m))
        s_known += i_m ** 2
        s2 += (k * i_m) ** 2
        s2a += (ka * i_m) ** 2
    tab = pd.DataFrame(table, columns=["order", "f_Hz", "category", "I_A", "U_level_V", "U95_V", "factor", "rule",
                                       "I_scaled_A"])
    i_other = math.sqrt(max(ih ** 2 - s_known, 0.0)) if np.isfinite(ih) else float("nan")
    ih_s = math.sqrt(s2 + i_other ** 2)
    ih_s_assessed = (1.0 + mI) * math.sqrt(s2a + i_other ** 2)

    def quad(cat):
        return float(math.sqrt(float((tab.loc[tab["category"] == cat, "I_A"] ** 2).sum())))

    return dict(table=tab, IG=ig, IH=ih, IH_scaled=ih_s, IH_scaled_assessed=ih_s_assessed,
                IRES_scaled=float(fml.rms_current_forecast(ig, ih_s)),
                IRES_scaled_assessed=float(fml.rms_current_forecast(fml.current_with_uncertainty(ig, mI),
                                                                    ih_s_assessed)),
                IH_zero=quad("zero"), IH_even=quad("even"), IH_other=i_other,
                f_thd=f_thd if f_thd is not None else float("nan"), UTHD_meas=u_meas, without=without,
                safety_factor=sf, uncertainty_I=mI, uncertainty_U=mU)


def _station(res: Result) -> None:
    """Station quantities in the max window: earth potential rise and touch voltage per order, r·Z_E, ratio F,
    extrapolation to the residual-current limits and shield/PEN currents."""
    st, roles, wi, e = res.steady_state, res.roles, res.max_index, res.settings
    ires = roles.main("i_res")
    ords = [m for m in st.orders if m in set(e.current_orders()) | {1}]
    rows = []
    IF = None
    valid = {}                                  # orders with enough fault current for quotients
    if ires is not None:
        IF = {m: res.polarity * st.X[wi, ires.index, st.ix(m)] for m in st.orders}
        IF_rms = float(st.rms[wi, ires.index])
        threshold = max(0.1, 0.01 * abs(IF[1]))
        valid = {m: abs(IF[m]) >= threshold for m in st.orders}
    for k in roles.with_role("u_e") + roles.with_role("u_t"):
        z_rms = float(st.rms[wi, k.index])
        row = dict(channel=k.short, role=k.role, distance_m=k.distance_m, RMS_V=z_rms)
        for m in ords:
            u = st.X[wi, k.index, st.ix(m)]
            row["H%d_V" % m] = float(abs(u))
            if IF is not None and valid.get(m):
                zr = u / IF[m]
                row["rZE_H%d_Ohm" % m] = float(abs(zr))
                row["rZE_H%d_angle_deg" % m] = float(np.degrees(np.angle(zr)))
        if IF is not None and IF_rms > 0:
            row["rZE_RMS_Ohm"] = z_rms / IF_rms
            row["V_per_100A_RMS"] = 100.0 * z_rms / IF_rms
        rows.append(row)
    df = pd.DataFrame(rows)
    res.tables["station_voltages"] = df
    # plausibility: the earth potential rise is roughly in phase with the earth current (earthing impedance
    # resistive to inductive, angle of r·Z_E typically −30° … +60°). Clearly different angles → check the
    # polarity of probe/clamp.
    if IF is not None and valid.get(1):
        for k in roles.with_role("u_e"):
            w = float(np.degrees(np.angle(st.X[wi, k.index, st.ix(1)] / IF[1])))
            if not -45.0 <= w <= 75.0:
                res.hints.append(tr("evaluation.angle_atypical", channel=k.short, angle=w))
    # ratio of earth potential rise to touch voltage (F) and extrapolation to the residual-current limits
    ue = roles.with_role("u_e"); ut = roles.with_role("u_t")
    tag = {}
    if ue:
        ue_max = max(float(st.rms[wi, k.index]) for k in ue)
        tag["UE_max_V"] = ue_max
    if ut:
        tag["UT_V"] = float(st.rms[wi, ut[0].index])
    if ue and ut and tag.get("UT_V", 0) > 0:
        tag["F_UE_to_UT"] = tag["UE_max_V"] / tag["UT_V"]
    if IF is not None:
        tag["IF_A"] = IF_rms
        for limit in e.ires_limits:
            if "UT_V" in tag:
                tag["UT_at_%gA_V" % limit] = tag["UT_V"] * limit / IF_rms
            if "UE_max_V" in tag:
                tag["UE_at_%gA_V" % limit] = tag["UE_max_V"] * limit / IF_rms
    # shield/PEN currents: share of the fault current; for the shield current also the reduction factor
    # r = I_E/I_F with I_E = I_F − I_S (complex) or 1 − |I_S|/|I_F| (magnitudes, as in earlier test reports) and the
    # earthing impedance Z_E = U_E/I_E. Polarity of I_S: the shield current is nearly in phase with I_F; an angle
    # above 90° means a reversed clamp → I_S is rotated (hint).
    shield = []
    ue_main = ue[0] if ue else None
    for k in roles.with_role("i_shield") + roles.with_role("i_pen"):
        row = dict(channel=k.short, role=k.role, RMS_A=float(st.rms[wi, k.index]))
        pol_s = 1
        if IF is not None and k.role == "i_shield" and valid.get(1):
            if abs(np.angle(st.X[wi, k.index, st.ix(1)] / IF[1])) > np.pi / 2:
                pol_s = -1
                res.hints.append(tr("evaluation.shield_reversed", channel=k.short))
        row["polarity"] = pol_s
        for m in ords:
            i_s = pol_s * st.X[wi, k.index, st.ix(m)]
            row["H%d_A" % m] = float(abs(i_s))
            if IF is not None and valid.get(m):
                row["share_H%d" % m] = float(abs(i_s) / abs(IF[m]))
                row["angle_to_IF_H%d_deg" % m] = float(np.degrees(np.angle(i_s / IF[m])))
                if k.role == "i_shield":
                    i_e = IF[m] - i_s
                    row["r_H%d_complex" % m] = float(abs(i_e) / abs(IF[m]))
                    row["r_H%d_magnitude" % m] = float(1 - abs(i_s) / abs(IF[m]))
                    if ue_main is not None and abs(i_e) > 0:
                        ze = st.X[wi, ue_main.index, st.ix(m)] / i_e
                        row["ZE_H%d_Ohm" % m] = float(abs(ze))
                        row["ZE_H%d_angle_deg" % m] = float(np.degrees(np.angle(ze)))
        shield.append(row)
    res.tables["station_currents"] = pd.DataFrame(shield)
    res.values["station"] = tag
    res.tables["station_metrics"] = pd.DataFrame([tag]) if tag else pd.DataFrame()


def _plausibility(res: Result, rec: Recording, bl) -> None:
    """Table ``plausibility``: checks of the measurement and of the evaluation (columns ``check``, ``status`` –
    OK, NOTE, WARNING, CORRECTED, UNCERTAIN or INFO –, ``value`` and ``comment``)."""
    st, roles, wi, e = res.steady_state, res.roles, res.max_index, res.settings
    pr = []

    def p(check, status, value, comment):
        pr.append(dict(check=check, status=status, value=value, comment=comment))

    corr = getattr(rec, "corrections", [])
    if corr:
        total = {}
        for k in corr:
            total[k["short"]] = k["factor_total"]
        p(tr("evaluation.check_corrections", path=_corrections_file(rec)), "CORRECTED",
          "; ".join("%s × %s" % (kk, i18n.format_number(f, digits=6)) for kk, f in total.items()),
          tr("evaluation.corrections_comment"))
    ref_w = res.reference_windows
    p(tr("evaluation.check_windows"), "OK" if int(ref_w.sum()) >= 3 else "NOTE",
      "%d" % int(ref_w.sum()) if ref_w.sum() == len(st.t_mid) else "%d / %d" % (int(ref_w.sum()), len(st.t_mid)),
      tr("evaluation.windows_comment"))
    found = res.disturbances
    if found is not None:
        if not found.found:
            p(tr("disturbances.check"), "OK", tr("disturbances.check_none", threshold=found.threshold_A),
              tr("disturbances.comment_none" if found.with_u0 else "disturbances.comment_none_u0"))
        elif e.exclude_disturbances and (ref_w & found.reference).any():
            p(tr("disturbances.check"), "NOTE", found.parts_text(),
              tr("disturbances.comment_excluded", reference=found.reference_text()))
        else:
            p(tr("disturbances.check"), "WARNING", found.parts_text(),
              tr("disturbances.comment_not_excluded") if not e.exclude_disturbances
              else tr("disturbances.no_reference", parts=found.parts_text()))
    f1 = st.f1
    p(tr("evaluation.check_f1"), "OK" if f1["plausible"] else "WARNING",
      tr("evaluation.value_f1", f1=f1["f1"], comparison=f1.get("f1_comparison", np.nan)), f1.get("note") or
      tr("evaluation.f1_consistent"))
    # one f1 applies to the whole interval (rather than one per window). If f1 varies within the interval, the
    # analysis grid m·f1 misses the actual frequency by m·Δf, i.e. by x = m·Δf·T_win bins. The Hann window then
    # gives the magnitude W(x) = sinc(x)/(1 − x²): relative magnitude error ≈ (π²/6 − 1)·x² ≈ 0.645·x²
    # (T_win = 0.2 s: ≈ 0.0065 % at m·Δf = 0.05 Hz, ≈ 0.65 % at m·Δf = 0.5 Hz)
    sf = f1.get("spread_hz", np.nan)
    if sf is not None and np.isfinite(sf):
        m_max = max(e.export_orders)
        p(tr("evaluation.check_f1_constant"), "OK" if sf <= 0.02 else "NOTE", tr("evaluation.value_f1_spread", spread=sf),
          tr("evaluation.f1_spread_large", order=m_max) if sf > 0.02 else tr("evaluation.f1_spread_small"))
    if "plaus_harmonic_selection" in res.values:
        v = res.values["plaus_harmonic_selection"]; v2 = res.values["plaus_harmonic_all"]
        p(tr("evaluation.check_rms_selection", orders=",".join(map(str, e.current_orders()))),
          "OK" if v < 0.05 else "NOTE", tr("evaluation.value_pct", value=100 * v),
          tr("evaluation.rms_selection_comment"))
        p(tr("evaluation.check_rms_all", order=max(st.orders)), "OK" if v2 < 0.03 else "WARNING",
          tr("evaluation.value_pct", value=100 * v2), tr("evaluation.rms_all_comment"))
    # stationarity: the fundamental component of the fault current must be constant in the steady-state interval
    # (active residual current increase, coil adjustment or switching within the interval → adjust the interval)
    ires_k = roles.main("i_res")
    if ires_k is not None and int(ref_w.sum()) >= 3:
        ok = ref_w
        I1w = res.polarity * st.X[ok, ires_k.index, st.ix(1)]
        h1 = np.abs(I1w)
        if h1.size >= 3 and np.median(h1) > 0:
            sp = float((h1.max() - h1.min()) / np.median(h1))
            # active/reactive component per window (angle method) separates the causes: an active residual
            # current increase changes the active component, a coil adjustment/network switching the reactive
            # component (detuning)
            U0w = None
            le_k = roles.line_to_earth
            if le_k:
                U0w = st.X[ok][:, le_k, st.ix(1)].sum(axis=1) / 3.0
            elif roles.has("u_ne"):
                U0w = st.X[ok, roles.index("u_ne"), st.ix(1)]
            dIw = dIv = np.nan
            if U0w is not None and np.all(np.abs(U0w) > 0):
                dphi = np.angle(U0w) - np.angle(I1w)
                Iw_w, Iv_w = h1 * np.cos(dphi), h1 * np.sin(dphi)
                dIw, dIv = float(Iw_w.max() - Iw_w.min()), float(Iv_w.max() - Iv_w.min())
            value = tr("evaluation.value_span", span=100 * sp)
            if np.isfinite(dIw):
                value += tr("evaluation.value_span_components", d_iw=dIw, d_iv=dIv)
            if sp < 0.05:
                comment_, cause = tr("evaluation.stationarity_ok"), ""
            elif np.isfinite(dIw) and dIv >= 2 * dIw:
                cause = tr("evaluation.cause_reactive", d_iv=dIv)
                comment_ = tr("evaluation.stationarity_reactive", cause=cause)
            elif np.isfinite(dIw) and dIw >= 2 * dIv:
                cause = tr("evaluation.cause_active", d_iw=dIw)
                comment_ = tr("evaluation.stationarity_active", cause=cause)
            else:
                cause = tr("evaluation.cause_both")
                comment_ = tr("evaluation.stationarity_both", cause=cause)
            p(tr("evaluation.check_stationarity"), "OK" if sp < 0.05 else "WARNING", value, comment_)
            if sp >= 0.05:
                res.hints.append(tr("evaluation.stationarity_hint", span=100 * sp, cause=cause, t=res.t_max_window))
            # coil current balance: Iv = ΣI_L − I_C (both ∝ U0). If a coil is adjusted within the interval, Iv must
            # change by the same amount as the sum of the measured coil currents (slope 1, referred to the same
            # U0). Slope ≠ 1 → wrong CT ratio of a coil channel or not all adjusted coils measured (e.g. a clamp
            # around only one of three parallel coil feeders gives a slope of 3 without correction).
            coils = roles.with_role("i_coil")
            if coils and np.isfinite(dIw) and U0w is not None:
                u = np.abs(U0w) / float(np.mean(np.abs(U0w)))
                X = sum(np.abs(st.X[ok, k.index, st.ix(1)]) for k in coils) / u
                Y = Iv_w / u
                if np.ptp(X) >= 0.5 and np.ptp(Y) >= 1.0 and X.size >= 5:
                    k_, c_ = np.polyfit(X, Y, 1)
                    r2 = float(np.corrcoef(X, Y)[0, 1] ** 2)
                    ok_k = 0.8 <= k_ <= 1.25 and r2 >= 0.8
                    res.values["coil_balance_slope"] = float(k_)
                    if ok_k:
                        comment_ = tr("evaluation.coil_balance_ok")
                    elif k_ > 1.25:
                        comment_ = tr("evaluation.coil_balance_high", slope=k_)
                    else:
                        comment_ = tr("evaluation.coil_balance_low", slope=k_, r2=r2)
                    p(tr("evaluation.check_coil_balance"), "OK" if ok_k else "WARNING",
                      tr("evaluation.value_coil_balance", slope=k_, r2=r2, d_coil=float(np.ptp(X))), comment_)
                    if not ok_k:
                        res.hints.append(tr("evaluation.coil_balance_hint", comment=comment_,
                                            path=_corrections_file(rec)))
    # low-frequency component in the max window (decaying DC component after fault inception – e.g. from the coil
    # current with a time constant L/R in the range of seconds – or drift of an integrator/clamp): a DC estimate per
    # window only removes a constant offset; the remainder increases the true RMS value without belonging to the
    # steady-state residual current. Moving average over one period = components < f1/2, after removing the DC
    # estimate of the evaluation (the mean after the high-pass: a stationary waveform with even harmonics gives no
    # remainder). With the high-pass the window as evaluated (filtered) is checked.
    if ires_k is not None:
        nwin = int(round(e.T_win * rec.fs))
        i0 = int(round((float(st.t_mid[wi]) - e.T_win / 2.0) * rec.fs))
        irms = float(st.rms[wi, ires_k.index])
        i0b, blk = bl["steady_state"]
        x = None
        hp = e.dc in dsp.HIGHPASS_FILTERS
        if hp and 0 <= i0 - i0b and i0 - i0b + nwin <= blk.shape[0]:
            x = np.asarray(blk[i0 - i0b:i0 - i0b + nwin, ires_k.index], dtype=np.float64)
        elif 0 <= i0 and i0 + nwin <= rec.n:
            x = rec.read(i0, i0 + nwin, [ires_k.index])[:, 0].astype(np.float64)
        if x is not None and irms > 0 and np.isfinite(x).all():
            x = dsp.remove_dc(x, dsp.window_dc(e.dc))
            nper = max(1, int(round(rec.fs / float(st.f1["f1_used"]))))
            if x.size > 2 * nper:
                x_lf = np.convolve(x, np.ones(nper) / nper, mode="valid")
                lf_rms = float(np.sqrt(np.mean(x_lf ** 2)))
                share = 1.0 - math.sqrt(max(irms ** 2 - lf_rms ** 2, 0.0)) / irms
                without = math.sqrt(max(irms ** 2 - lf_rms ** 2, 0.0))
                res.values["ires_low_frequency_A"] = lf_rms
                res.values["IRES_without_lf"] = without
                fc = float(e.dc_cutoff_hz)
                p(tr("evaluation.check_low_frequency"), "OK" if share < 0.01 else "WARNING",
                  tr("evaluation.value_low_frequency", lf=lf_rms, share=100 * share),
                  (tr("evaluation.low_frequency_comment_hp", without=without, fc=fc) if hp
                   else tr("evaluation.low_frequency_comment", without=without))
                  if share >= 0.01 else tr("evaluation.low_frequency_ok"))
                if share >= 0.01:
                    res.hints.append(tr("evaluation.low_frequency_hint_hp" if hp else "evaluation.low_frequency_hint",
                                        lf=lf_rms, t=float(st.t_mid[wi]), share=100 * share, without=without, fc=fc))
    margin = res.values.get("polarity_margin_deg", np.nan)
    extra_ = tr("evaluation.value_margin", margin=margin) if np.isfinite(margin) else ""
    if res.polarity < 0:
        p(tr("evaluation.check_polarity"), "CORRECTED" if not margin < 10 else "UNCERTAIN", "Iw < 0" + extra_,
          tr("evaluation.polarity_rotated_comment"))
    elif "Iw" in res.values and np.isfinite(res.values["Iw"]):
        p(tr("evaluation.check_polarity"), "OK" if not margin < 10 else "UNCERTAIN",
          tr("evaluation.value_iw", iw=res.values["Iw"], extra=extra_), tr("evaluation.polarity_ok_comment"))
    # compare several fault-current CTs
    cand = roles.with_role("i_res")
    if len(cand) > 1:
        h = cand[0]
        for k in cand[1:]:
            r1 = st.rms[wi, k.index] / st.rms[wi, h.index] if st.rms[wi, h.index] > 0 else np.nan
            z1 = st.X[wi, k.index, st.ix(1)] / st.X[wi, h.index, st.ix(1)] if abs(st.X[wi, h.index, st.ix(1)]) > 0 else np.nan
            dphi = float(np.degrees(np.angle(z1))) if np.isfinite(z1) else np.nan
            dphi_n = ((dphi + 90) % 180) - 90 if np.isfinite(dphi) else np.nan    # tolerate a reversal by 180°
            ok = abs(r1 - 1) < 0.05 and abs(dphi_n) < 5
            p(tr("evaluation.check_ct_pair", channel=k.short, main=h.short), "OK" if ok else "WARNING",
              tr("evaluation.value_ct_pair", ratio=r1, dphi=dphi), tr("evaluation.ct_pair_comment"))
    # faulted phase ≈ 0 V
    le = roles.line_to_earth
    if le:
        mags = np.array([abs(st.X[wi, k, st.ix(1)]) for k in le])
        ph = int(np.argmin(mags))
        rat = mags.min() / mags.max() if mags.max() > 0 else np.nan
        p(tr("evaluation.check_faulted_phase"), "OK" if rat < 0.1 else "WARNING",
          tr("evaluation.value_faulted_phase", phase=ph + 1, u=mags.min(), ratio=100 * rat),
          tr("evaluation.faulted_phase_comment"))
        res.values["faulted_phase"] = "L%d" % (ph + 1)
    # pre-fault: fault and coil currents ≈ 0
    vf = res.pre_fault
    if vf is not None:
        for k in roles.with_role("i_res") + roles.with_role("i_coil"):
            v = float(np.nanmedian(vf.rms[:, k.index]))
            ref = float(st.rms[wi, k.index]) if st.rms[wi, k.index] > 0 else 1.0
            ok = v < max(1.0, 0.05 * ref)
            p(tr("evaluation.check_pre_fault", channel=k.short), "OK" if ok else "NOTE",
              tr("evaluation.value_amps", value=v), tr("evaluation.pre_fault_comment"))
    # transformer: zero-sequence current of the MV line currents ↔ coil current/3 (information only – the coil may
    # also be connected to another star point)
    il = roles.line_currents
    if il is not None and roles.has("i_coil"):
        i0_tr = abs(sum(st.X[wi, k, st.ix(1)] for k in il) / 3.0)
        i_sp = sum(abs(st.X[wi, k.index, st.ix(1)]) for k in roles.with_role("i_coil"))
        if i_sp > 1.0:
            p(tr("evaluation.check_transformer"), "INFO", tr("evaluation.value_transformer", i0=3 * i0_tr, i_coil=i_sp),
              tr("evaluation.transformer_comment"))
    for r in trafo.plausibility_rows(res):
        p(r["check"], r["status"], r["value"], r["comment"])
    # overload (saturation) in the steady-state block: "flat tops" – runs of identical raw values at the block
    # maximum/minimum. Recorders such as DANEO scale each file to its value range (|raw|max = 32767), so hitting
    # the limit alone is NOT proof of an overload.
    i0b, blk = bl["steady_state"]
    run_min = max(4, int(round(1e-4 * rec.fs)))
    for k in roles.channels:
        share = _flat_top_share(rec, k.index, i0b, blk.shape[0], run_min)
        if share > 1e-4:
            p(tr("evaluation.check_saturation", channel=k.short), "WARNING",
              tr("evaluation.value_saturation", share=100 * share), tr("evaluation.saturation_comment"))
    res.tables["plausibility"] = pd.DataFrame(pr)


def _flat_top_share(rec: Recording, j: int, i0: int, n: int, run_min: int) -> float:
    """Share of the samples of channel ``j`` in runs of at least ``run_min`` identical raw values at the block
    maximum/minimum (0 if the raw values cannot be read)."""
    try:
        raw = rec._raw(max(0, i0), min(rec.n, i0 + n), [j])[:, 0].astype(np.int64)
    except Exception:
        return 0.0
    if raw.size < 10:
        return 0.0
    hits = 0
    for limit_ in (raw.max(), raw.min()):
        at_edge = np.concatenate([[False], raw == limit_, [False]]).astype(np.int8)
        d = np.diff(at_edge)
        starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
        runs_ = ends - starts
        hits += int(runs_[runs_ >= run_min].sum())
    return hits / raw.size


def _statistics(res: Result) -> None:
    """Table ``statistics``: statistics of the RMS values (and of the assessed orders of currents and earth
    potentials) over the reference windows of the steady-state interval (without disturbed states), with the value
    in the max window."""
    st, roles, e = res.steady_state, res.roles, res.settings
    ok = res.reference_windows
    rows = []
    for k in roles.channels:
        s = _qstat(st.rms[ok, k.index])
        rows.append(dict(channel=k.short, role=k.role, quantity="RMS", unit=k.unit, **s))
        if k.role in ("i_res", "u_e", "u_t", "i_coil", "i_shield", "i_pen"):
            for m in e.current_orders():
                s = _qstat(np.abs(st.X[ok, k.index, st.ix(m)]))
                rows.append(dict(channel=k.short, role=k.role, quantity="H%d" % m, unit=k.unit, **s))
    df = pd.DataFrame(rows)
    df.insert(4, "value_max_window", [np.nan] * len(df))
    for i, r in df.iterrows():
        j = roles.channels[[k.short for k in roles.channels].index(r["channel"])].index
        if r["quantity"] == "RMS":
            df.at[i, "value_max_window"] = st.rms[res.max_index, j]
        else:
            df.at[i, "value_max_window"] = abs(st.X[res.max_index, j, st.ix(int(r["quantity"][1:]))])
    res.tables["statistics"] = df


def _result_set(res: Result, rec: Recording, z_fault_ohm, metadata: dict, alignment) -> None:
    """Assemble the content of the result file (``res.result_set``)."""
    st, e, wi, roles = res.steady_state, res.settings, res.max_index, res.roles
    phi_ll = res.values.get("phi_LL1")
    signals = {}
    for k in roles.channels:
        polk = res.polarity if k.role == "i_res" else 1
        harm = {}
        for m in sorted(set(e.export_orders) | set(e.current_orders())):
            if m in st.orders:
                harm["H%d" % m] = _magang(polk * st.X[wi, k.index, st.ix(m)])
        ok = res.reference_windows
        signals[k.name] = {"role": k.role, "unit": k.unit, "short": k.short,
                           "rms_window": float(st.rms[wi, k.index]),
                           "rms_max": float(np.nanmax(st.rms[ok, k.index])),
                           "rms_mean": float(np.nanmean(st.rms[ok, k.index])),
                           "fundamental_hz": float(st.f1["f1_used"]),
                           "window_t_s": float(st.t_mid[wi]), "harmonics": harm}
    assess = {}
    for _, r in res.tables["assessment_quantities"].iterrows():
        d = {"measured_value": float(r["measured_value"]), "assessed": float(r["assessment"]), "unit": r["unit"],
             "equation": r.get("equation", "")}
        if np.isfinite(r.get("angle_deg", np.nan)):
            d["angle_deg_ref_ULL"] = float(r["angle_deg"])
        assess[r["quantity"]] = d
    def _b(x):
        return [float(x[0]), float(x[1])] if x else None
    meta = {"start_time": rec.t_start.isoformat() if rec.t_start else None,
            "trigger": rec.t_trigger.isoformat() if rec.t_trigger else None,
            "station": rec.station, "revision": rec.revision, "format": rec.file_format,
            "data_mode": "raw", "created": _dt.datetime.now().isoformat(timespec="seconds"),
            "tool": "groundfault %s" % __version__, "measurement": res.name}
    meta.update({k: v for k, v in metadata.items() if v is not None})
    if getattr(rec, "corrections", None):
        meta["corrections"] = [dict(k) for k in rec.corrections]
    res.result_set = {
        "format": RESULT_FORMAT, "version": RESULT_VERSION,
        "meta": meta,
        "measurement": {"cfg_file": os.path.basename(rec.cfg_path), "fs_hz": rec.fs, "fs_source": rec.fs_source,
                    "n_samples": int(rec.n), "duration_s": rec.duration_s,
                    "steady_state_s": _b(res.intervals.steady_state), "pre_fault_s": _b(res.intervals.pre_fault),
                    "post_fault_s": _b(res.intervals.post_fault), "T_win_s": e.T_win,
                    "T_hop_s": e.T_hop or e.T_win, "harmonics": list(e.current_orders()),
                    "window": e.window, "dc_method": e.dc, "dc_window": dsp.window_dc(e.dc), "f1_hz": float(st.f1["f1_used"]),
                    "f1": {k: (v if not isinstance(v, float) or np.isfinite(v) else None) for k, v in st.f1.items()},
                    "window_t_s": float(st.t_mid[wi]), "z_fault_ohm": z_fault_ohm,
                    "polarity_i_res": res.polarity, "phi_LL1_deg": (float(np.degrees(phi_ll))
                                                                      if phi_ll is not None else None),
                    "alignment": alignment, "roles": roles.as_dict(),
                    "main_channel": {r: roles.main(r).name for r in {k.role for k in roles.channels if k.role}},
                    "settings": {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(e).items()}},
        "signals": signals,
        "assessment_quantities": assess,
        "hints": list(res.hints),
        "plausibility": res.tables["plausibility"].to_dict(orient="records"),
    }
    if "voltage" in res.values:
        res.result_set["voltage"] = res.values["voltage"]
    if res.disturbances is not None:                    # disturbed states of the steady-state interval
        d = res.disturbances
        res.result_set["disturbances"] = _json_simple(dict(
            excluded=bool(e.exclude_disturbances and d.found and bool((res.reference_windows & d.reference).any())),
            threshold_A=d.threshold_A, with_u0=d.with_u0, reference_s=[list(x) for x in d.reference_intervals()],
            disturbed_s=[list(x) for x in d.excluded_intervals()], events=d.events.to_dict(orient="records")))
    if "station_frequency" in res.values:                  # station: times, frequency sources, methods (traceability)
        res.result_set["station_frequency"] = _json_simple(res.values["station_frequency"])
    if "station_lv_network" in res.values:                  # LV network: PEN/shield channels used, counting direction
        res.result_set["station_lv_network"] = _json_simple(res.values["station_lv_network"])
    if "transformer" in res.values:                         # transformer node: polarity, voltages, X_up/m, HV side
        res.result_set["transformer"] = _json_simple(res.values["transformer"])
    if "transformer_divider" in res.values:                 # HV share from HV and MV voltages (voltage divider)
        res.result_set["transformer_divider"] = _json_simple(res.values["transformer_divider"])
    # all tables (for campaign evaluations and report tables without raw data)
    for t, df in res.tables.items():
        if df is None or df.empty:
            continue
        d = df.reset_index() if (df.index.name or not isinstance(df.index, pd.RangeIndex)) else df
        res.result_set.setdefault("tables", {})[t] = json.loads(d.to_json(orient="records"))
    res.result_set["statistics"] = json.loads(res.tables["statistics"].to_json(orient="records"))
    scalar = {}
    for k, v in res.values.items():
        if isinstance(v, (int, float, np.floating, np.integer)) and not isinstance(v, bool):
            scalar[k] = float(v) if np.isfinite(v) else None
        elif isinstance(v, str):
            scalar[k] = v
    ires = roles.main("i_res")
    if ires is not None:
        scalar["main_channel_i_res"] = ires.short
    scalar["t_max_window_s"] = float(st.t_mid[wi])
    res.result_set["values"] = scalar


def _json_simple(x):
    """Make nested values JSON-compatible (NumPy numbers → float/int, NaN → None, tuples → lists)."""
    if isinstance(x, dict):
        return {str(k): _json_simple(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, np.ndarray)):
        return [_json_simple(v) for v in x]
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return float(x) if np.isfinite(x) else None
    return x if x is None or isinstance(x, str) else str(x)


# ====================================================================== result file (without raw data)
def _numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Load columns that consist only of numbers and ``null`` in the JSON file (NaN is saved as null) as numbers
    again (NaN) – otherwise they would contain ``None`` instead of NaN."""
    for c in df.columns:
        if df[c].dtype == object:
            w = [v for v in df[c] if v is not None]
            if w and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in w):
                df[c] = pd.to_numeric(df[c], errors="coerce")
            elif not w:
                df[c] = np.nan
    return df


class ResultFile:
    """Saved result file with the interface of [`Result`][groundfault.evaluation.Result] needed by report tables and
    campaign evaluations.

    Provides ``name``, ``values``, ``tables``, ``hints``, ``settings`` (``f_nominal``, ``T_win``, ``ires_limits``,
    ``u_tp``, ``f_factor`` – the limits as stored in the file, empty or None if it has none), ``measurement`` and
    ``z_fault_ohm`` – without the raw data. Result files of the predecessor tool (German keys) are translated when
    they are read; tables of result files of groundfault 2.0 get the current column names
    ([`groundfault.legacy.update_result`][groundfault.legacy.update_result]).

    Parameters
    ----------
    path : str
        Path of the result file (written by [`Result.save_json`][groundfault.evaluation.Result.save_json]).
    name : str, optional
        Name of the measurement (default: the name stored in the file, else the file name).

    Raises
    ------
    ValueError
        If the file is not a result file of groundfault (or of its predecessor tool).
    """

    def __init__(self, path: str, name: Optional[str] = None):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if is_legacy_result(d):
            d = translate_result(d)                     # result file of the predecessor tool (German keys)
        elif d.get("format") != RESULT_FORMAT:
            raise ValueError(tr("evaluation.not_a_result_file", path=path))
        else:
            d = update_result(d)                        # names of earlier groundfault versions
        _metadata_from_path(d, path)                    # campaign and site of files that lack them (early versions)
        self.path = path
        self.data = d
        self.name = name or d.get("meta", {}).get("measurement") or os.path.splitext(os.path.basename(path))[0]
        self.hints = list(d.get("hints", []))
        self.values = {k: (np.nan if v is None else v) for k, v in d.get("values", {}).items()}
        if "voltage" in d:
            self.values["voltage"] = d["voltage"]
        if "transformer" in d:                          # transformer node (polarity, X_up/m, HV side, ΔP1)
            self.values["transformer"] = d["transformer"]
        self.tables: Dict[str, pd.DataFrame] = {}
        for t, records in (d.get("tables") or {}).items():
            self.tables[t] = _numeric_columns(pd.DataFrame(records))
        if "assessment_quantities" not in self.tables and d.get("assessment_quantities"):
            self.tables["assessment_quantities"] = pd.DataFrame(
                [dict(quantity=k, measured_value=v["measured_value"], assessment=v["assessed"], unit=v["unit"],
                      equation=v.get("equation", ""), angle_deg=v.get("angle_deg_ref_ULL", np.nan))
                 for k, v in d["assessment_quantities"].items()])
        gf = d.get("measurement", {}).get("settings", {}) or {}
        from types import SimpleNamespace

        def _optional(key):                     # a limit stored in the file; None if the file has none
            v = gf.get(key)
            return float(v) if v is not None else None

        self.settings = SimpleNamespace(f_nominal=float(gf.get("f_nominal", 50.0)),
                                        T_win=float(gf.get("T_win", 0.2)),
                                        ires_limits=tuple(float(x) for x in gf.get("ires_limits") or ()),
                                        u_tp=_optional("u_tp"), f_factor=_optional("f_factor"))
        self.measurement = d.get("measurement", {})

    @property
    def z_fault_ohm(self):
        """Fault resistance of the measurement in Ω (or None)."""
        return self.measurement.get("z_fault_ohm")

    def table(self, name: str) -> pd.DataFrame:
        """Result table ``name``."""
        return self.tables[name]

    def __repr__(self):
        return "<ResultFile %s>" % self.name


def _metadata_from_path(d: dict, path: str) -> None:
    """Complete ``meta`` of a result file inside a campaign folder (``<campaign>/<results>/<measurement>/…``) with
    ``campaign`` (name of the campaign folder) and ``site`` (folder of the recording ``cfg_file`` in the raw-data folder
    of the campaign, if it is found there exactly once) – as [`evaluate`][groundfault.evaluation.evaluate] does for a
    recording inside a campaign. Values in the file are kept; nothing is added for a file outside a campaign."""
    meta = d.get("meta") or {}
    if meta.get("campaign") and meta.get("site"):
        return
    from .layout import campaign_root
    from .sites import site_from_path
    root = campaign_root(path)
    if not root:
        return
    d["meta"] = meta
    if not meta.get("campaign"):
        meta["campaign"] = os.path.basename(os.path.normpath(root))
    cfg = unicodedata.normalize("NFC", str((d.get("measurement") or {}).get("cfg_file") or ""))
    if meta.get("site") or not cfg:
        return
    found = set()
    for folder in dict.fromkeys((detect_layout(root).raw, ENGLISH.raw, GERMAN.raw)):
        for dirpath, _, files in os.walk(os.path.join(root, folder)):
            if any(unicodedata.normalize("NFC", f) == cfg for f in files):
                found.add(site_from_path(os.path.relpath(os.path.join(dirpath, cfg), root)))
    if len(found) == 1:
        meta["site"] = found.pop()


def load_result(path: str, name: Optional[str] = None) -> ResultFile:
    """Load a result file (for campaign evaluations and report tables without the raw data).

    Parameters
    ----------
    path : str
        Path of the result file (written by [`Result.save_json`][groundfault.evaluation.Result.save_json]).
    name : str, optional
        Name of the measurement (default: the name stored in the file).

    Returns
    -------
    ResultFile

    Raises
    ------
    ValueError
        If the file is not a result file of groundfault (or of its predecessor tool).
    """
    return ResultFile(path, name)
