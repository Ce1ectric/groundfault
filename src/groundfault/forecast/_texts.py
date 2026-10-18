# -*- coding: utf-8 -*-
"""Messages, German table labels and report titles of the forecast package (registered at import)."""
from __future__ import annotations

from .. import i18n

i18n.register({
    # ---------------------------------------------------------------- input data
    "forecast.no_current": {
        "en": "{name}: a calibration needs the fault current and the additional impedance Z – use add_fault for an "
              "earth fault with busbar voltages only",
        "de": "{name}: Eine Kalibrierung braucht den Fehlerstrom und die Zusatzimpedanz Z – für einen Erdschluss nur "
              "mit Sammelschienenspannungen add_fault verwenden"},
    "forecast.no_voltages": {
        "en": "{name}: no busbar voltages before and during the fault (line-to-earth voltages and a pre-fault "
              "interval are needed)",
        "de": "{name}: keine Sammelschienenspannungen vor und im Fehler (Leiter-Erde-Spannungen und ein "
              "Vorfehlerbereich sind nötig)"},
    "forecast.transformer_table_missing": {
        "en": "{name}: no table transformer_impedance (evaluate the transformer recording first)",
        "de": "{name}: keine Tabelle transformer_impedance (zuerst die Trafoaufzeichnung auswerten)"},
    "forecast.coil_reversed": {
        "en": "coil current {channel} turned by 180° (a coil current lags the displacement voltage by 90° at 50 Hz)",
        "de": "Spulenstrom {channel} um 180° gedreht (ein Spulenstrom eilt der Verlagerungsspannung bei 50 Hz um 90° "
              "nach)"},
    "forecast.values_sequences": {
        "en": "{name}: give the voltages per order either as sequences (zero, pos, neg) or as phases (L1, L2, L3)",
        "de": "{name}: Spannungen je Ordnung entweder als Sequenzen (zero, pos, neg) oder als Leiter (L1, L2, L3) "
              "angeben"},
    # ---------------------------------------------------------------- model
    "forecast.duplicate": {
        "en": "a calibration named {name!r} exists already – choose another name or remove it first",
        "de": "Eine Kalibrierung mit dem Namen {name!r} gibt es schon – anderen Namen wählen oder zuerst entfernen"},
    "forecast.unknown_name": {
        "en": "no calibration named {name!r} – available: {names}",
        "de": "keine Kalibrierung mit dem Namen {name!r} – vorhanden: {names}"},
    "forecast.phase_unknown": {
        "en": "faulted phase unknown – the phase factors of L1 are used",
        "de": "Fehlerleiter unbekannt – die Phasenfaktoren von L1 werden verwendet"},
    "forecast.no_orders": {
        "en": "{name}: no harmonic order with enough current and voltage change",
        "de": "{name}: keine Ordnung mit genügend Strom und Spannungsänderung"},
    "forecast.no_reference": {
        "en": "a recorded earth fault needs Z_0 from a calibration (add_test) or z0 = {{order: Z_0}}",
        "de": "Ein aufgezeichneter Erdschluss braucht Z_0 aus einer Kalibrierung (add_test) oder z0 = {{Ordnung: Z_0}}"},
    "forecast.order_single": {"en": "order {orders}", "de": "Ordnung {orders}"},
    "forecast.order_list": {"en": "orders {orders}", "de": "Ordnungen {orders}"},
    "forecast.small_dU0": {
        "en": "{orders}: |ΔU_0| below {limit:g} V – not updated",
        "de": "{orders}: |ΔU_0| unter {limit:g} V – nicht nachgeführt"},
    "forecast.fault_source_not_updated": {
        "en": "{orders}: source that arises in the fault – Z not updated from busbar voltages",
        "de": "{orders}: im Fehler entstehende Quelle – Z aus Sammelschienenspannungen nicht nachgeführt"},
    "forecast.no_z0": {
        "en": "{orders}: no Z_0 from a calibration – not updated",
        "de": "{orders}: kein Z_0 aus einer Kalibrierung – nicht nachgeführt"},
    "forecast.node_rule": {
        "en": "fault current per order from the zero-sequence voltage and the coil currents (node rule, Y_0 of the "
              "network from {tests})",
        "de": "Fehlerstrom je Ordnung aus Nullspannung und Spulenströmen (Knotenregel, Y_0 des Netzes aus {tests})"},
    "forecast.node_rule_no_tests": {
        "en": "coil currents recorded, but no calibration test with coil currents – the fault current is estimated "
              "from the zero-sequence voltage (3·|ΔU_0|/|Z_0|)",
        "de": "Spulenströme aufgezeichnet, aber kein Kalibrierversuch mit Spulenströmen – der Fehlerstrom wird aus der "
              "Nullspannung geschätzt (3·|ΔU_0|/|Z_0|)"},
    "forecast.empty": {
        "en": "the network model contains no calibration",
        "de": "Das Netzmodell enthält keine Kalibrierung"},
    "forecast.constant_source": {
        "en": "order {order}: the source that arises in the fault cannot be separated with fewer than two tests with "
              "different additional impedances – the current measured in {name} ({current:.2f} A at {z:g} Ω) is used "
              "for every fault impedance",
        "de": "Ordnung {order}: Die im Fehler entstehende Quelle lässt sich mit weniger als zwei Versuchen "
              "verschiedener Zusatzimpedanz nicht abtrennen – der in {name} gemessene Strom ({current:.2f} A bei "
              "{z:g} Ω) gilt für jede Fehlerimpedanz"},
    "forecast.constant_smaller_zf": {
        "en": "order {order}: the current was measured with {z:g} Ω in the fault loop – for the smaller {zf:g} Ω it is "
              "underestimated",
        "de": "Ordnung {order}: Der Strom wurde mit {z:g} Ω in der Fehlerschleife gemessen – für die kleineren "
              "{zf:g} Ω wird er unterschätzt"},
    "forecast.ill_conditioned": {
        "en": "order {order}: the tests do not separate U_q and U_s (condition {cond:.0f}) – pre-fault source only",
        "de": "Ordnung {order}: Die Versuche trennen U_q und U_s nicht (Kondition {cond:.0f}) – nur Vorfehlerquelle"},
    "forecast.ll_zero_sequence": {
        "en": "{orders}: line-to-line voltages contain no zero sequence – the pre-fault voltage is set to 0 (only the "
              "source that arises in the fault remains)",
        "de": "{orders}: Leiter-Leiter-Spannungen enthalten kein Nullsystem – die Vorfehlerspannung wird 0 gesetzt "
              "(nur die im Fehler entstehende Quelle bleibt)"},
    "forecast.ll_zero_sequence_skipped": {
        "en": "{orders}: line-to-line voltages contain no zero sequence – not forecast",
        "de": "{orders}: Leiter-Leiter-Spannungen enthalten kein Nullsystem – keine Prognose"},
    "forecast.voltage_missing": {
        "en": "{orders}: no voltage given – not forecast (the current counts as rest only if rest_A covers it)",
        "de": "{orders}: keine Spannung angegeben – keine Prognose (der Strom zählt nur als Rest, wenn rest_A ihn "
              "abdeckt)"},
    "forecast.voltage_missing_source": {
        "en": "{orders}: no voltage given – only the source that arises in the fault is used",
        "de": "{orders}: keine Spannung angegeben – nur die im Fehler entstehende Quelle"},
    "forecast.fundamental_from_tests": {
        "en": "fundamental residual current {value:.2f} A = median of √(I_w² + I_v²) of the calibration tests",
        "de": "Grundschwingungsreststrom {value:.2f} A = Median von √(I_w² + I_v²) der Kalibrierversuche"},
    "forecast.fundamental_missing": {
        "en": "fundamental residual current unknown (no tests with I_w) – I_RES without it",
        "de": "Grundschwingungsreststrom unbekannt (keine Versuche mit I_w) – I_RES ohne ihn"},
    "forecast.rest_from_tests": {
        "en": "rest {value:.2f} A = largest harmonic content of the calibration tests outside the forecast orders",
        "de": "Rest {value:.2f} A = größter Oberschwingungsanteil der Kalibrierversuche außerhalb der Prognoseordnungen"},
    "forecast.upstream_missing": {
        "en": "{name}: no upstream impedance for {orders} – Z_1, Z_2 unchanged",
        "de": "{name}: keine Vorimpedanz für {orders} – Z_1, Z_2 unverändert"},
    "forecast.no_tests": {
        "en": "the check needs at least two calibration tests",
        "de": "Die Prüfung braucht mindestens zwei Kalibrierversuche"},
    "forecast.chain_needs_three": {
        "en": "the learning chain needs at least three calibration tests",
        "de": "Die Lernkette braucht mindestens drei Kalibrierversuche"},
    "forecast.not_a_model": {
        "en": "{path}: not a network model file (format {format!r})",
        "de": "{path}: keine Netzmodell-Datei (Format {format!r})"},
    "forecast.newer_version": {
        "en": "{path}: model file version {version} is newer than this groundfault ({supported})",
        "de": "{path}: Version {version} der Modelldatei ist neuer als dieses groundfault ({supported})"},
    "forecast.no_voltage_columns": {
        "en": "no harmonic order recognised in the voltage columns {columns}",
        "de": "keine Oberschwingungsordnung in den Spannungsspalten {columns} erkannt"},
    "forecast.quantile_needs_series": {
        "en": "the forecast has a single value per order – quantile() needs a time series",
        "de": "Die Prognose hat einen Wert je Ordnung – quantile() braucht eine Zeitreihe"},
    "forecast.no_fault_currents": {
        "en": "no recorded earth fault with an estimated fault current in the model",
        "de": "Kein aufgezeichneter Erdschluss mit geschätztem Fehlerstrom im Modell"},
    "forecast.verify_no_current": {
        "en": "{name}: no fault current to compare with",
        "de": "{name}: kein Fehlerstrom zum Vergleich"},
    # ---------------------------------------------------------------- line
    "forecast.line_empty": {
        "en": "a line needs at least one segment (or Line.from_impedances)",
        "de": "Eine Leitung braucht mindestens einen Abschnitt (oder Line.from_impedances)"},
    "forecast.line_wavelength": {
        "en": "line {line}: {pct:.0f} % of a quarter wavelength at order {order} – the series model (no shunt "
              "capacitance along the line) holds for a small fraction",
        "de": "Leitung {line}: {pct:.0f} % einer Viertelwellenlänge bei Ordnung {order} – das Reihenmodell (ohne "
              "Querkapazität längs der Leitung) gilt für einen kleinen Anteil"},
    "forecast.line_used": {
        "en": "fault behind the line {line}: Z_q + (2·Z_1L + Z_0L)/3, pre-fault voltage of the busbar",
        "de": "Fehler hinter der Leitung {line}: Z_q + (2·Z_1L + Z_0L)/3, Vorfehlerspannung der Sammelschiene"},
    "forecast.line_order_fields": {
        "en": "line segment, values of order {order}: {fields} missing (R1, X1, R0, X0 in Ω/km at that order)",
        "de": "Leitungsabschnitt, Werte der Ordnung {order}: {fields} fehlt (R1, X1, R0, X0 in Ω/km bei dieser "
              "Ordnung)"},
    "forecast.line_complex": {
        "en": "not a complex number: {value!r} (complex, [re, im] or {{\"re\": …, \"im\": …}})",
        "de": "keine komplexe Zahl: {value!r} (complex, [re, im] oder {{\"re\": …, \"im\": …}})"},
    "forecast.line_orders": {
        "en": "line {line}: values of their own at {given}; {rest} from the 50-Hz values (resistance constant, "
              "reactance ∝ m) – not on the safe side by construction",
        "de": "Leitung {line}: eigene Werte bei {given}; {rest} aus den 50-Hz-Werten (Widerstand konstant, "
              "Reaktanz ∝ m) – nicht von selbst auf der sicheren Seite"},
    "forecast.line_50hz_only": {
        "en": "line {line}: all orders from the 50-Hz values (resistance constant, reactance ∝ m) – not on the safe "
              "side by construction; give the values of the orders of interest (line-parameter calculation at "
              "m·50 Hz or a measurement, e.g. NetworkModel.line_from_fault)",
        "de": "Leitung {line}: alle Ordnungen aus den 50-Hz-Werten (Widerstand konstant, Reaktanz ∝ m) – nicht von "
              "selbst auf der sicheren Seite; Werte der wichtigen Ordnungen angeben (Leitungsberechnung bei m·50 Hz "
              "oder Messung, z. B. NetworkModel.line_from_fault)"},
    "forecast.line_from_fault_source": {
        "en": "{name}: line not derived at {orders} – source in the fault (the zero-sequence voltage does not give the "
              "fault current there)",
        "de": "{name}: Leitung bei {orders} nicht bestimmt – Quelle im Fehler (die Nullspannung gibt dort den "
              "Fehlerstrom nicht)"},
    "forecast.line_from_fault_active": {
        "en": "{name}: line at {orders} not resistive-inductive – left out (the fault current from the busbar does not "
              "describe these orders, e.g. a source in the fault)",
        "de": "{name}: Leitung bei {orders} nicht ohmsch-induktiv – nicht übernommen (der Fehlerstrom aus der "
              "Sammelschiene beschreibt diese Ordnungen nicht, z. B. eine Quelle im Fehler)"},
    "forecast.line_from_fault_small": {
        "en": "{name}: line not derived at {orders} – |ΔU_0| below {limit:g} V",
        "de": "{name}: Leitung bei {orders} nicht bestimmt – |ΔU_0| unter {limit:g} V"},
    "forecast.line_from_fault_none": {
        "en": "{name}: no order to derive the line from (Z_0 of the tests and the busbar voltages needed)",
        "de": "{name}: keine Ordnung, aus der sich die Leitung bestimmen lässt (Z_0 der Versuche und die "
              "Sammelschienenspannungen nötig)"},
    # ---------------------------------------------------------------- campaigns
    "forecast.no_register": {
        "en": "register not found: {path}",
        "de": "Messregister nicht gefunden: {path}"},
    "forecast.unknown_campaign": {
        "en": "campaign {campaign!r} not in the register – available: {campaigns}",
        "de": "Kampagne {campaign!r} nicht im Messregister – vorhanden: {campaigns}"},
    "forecast.no_tests_in_campaign": {
        "en": "{campaign}: no substation recording with an additional impedance in the register",
        "de": "{campaign}: keine UW-Aufzeichnung mit Zusatzimpedanz im Messregister"},
    "forecast.result_missing": {
        "en": "{name}: result file missing ({path}) – evaluate the recording first",
        "de": "{name}: Ergebnisdatei fehlt ({path}) – die Aufzeichnung zuerst auswerten"},
    "forecast.upstream_from": {
        "en": "{name}: upstream impedance from the transformer recording {transformer}",
        "de": "{name}: Vorimpedanz aus der Trafoaufzeichnung {transformer}"},
})

# German table labels (columns and codes) of the tables of this package
i18n.register_labels(
    columns={
        "Z0_angle_deg": "Z0_Winkel_deg", "Z1_angle_deg": "Z1_Winkel_deg", "Z2_angle_deg": "Z2_Winkel_deg",
        "Zq_angle_deg": "Zq_Winkel_deg", "Us_angle_deg": "Us_Winkel_deg", "I_estimated_A": "I_geschaetzt_A",
        "I_estimated_method": "I_geschaetzt_Verfahren", "Y0_net_S": "Y0_Netz_S", "Y0_net_angle_deg": "Y0_Netz_Winkel_deg",
        "Z_down_Ohm": "Z_MS_Ohm", "Z_down_angle_deg": "Z_MS_Winkel_deg", "G_down_S": "G_MS_S", "B_down_S": "B_MS_S",
        "I_constant_A": "I_konstant_A", "calibrations": "Kalibrierungen", "mode": "Modus", "target": "Ziel",
        "model": "Modell", "I_forecast_A": "I_Prognose_A", "deviation_A": "Abweichung_A", "ratio": "Verhaeltnis",
        "margin_A": "Zuschlag_A", "deviation_min_A": "Abweichung_min_A", "deviation_max_A": "Abweichung_max_A",
        "ratio_min": "Verhaeltnis_min", "ratio_max": "Verhaeltnis_max", "line_name": "Leitung",
        "Z_line_Ohm": "Z_Leitung_Ohm", "Z_loop_Ohm": "Z_Schleife_Ohm", "Zq_ZF_Ohm": "Zq_ZF_Ohm",
        "I_C_ratio": "I_C_Verhaeltnis", "line_values": "Leitungswerte", "R_measured_Ohm": "R_gemessen_Ohm",
        "X_measured_Ohm": "X_gemessen_Ohm", "Z_measured_Ohm": "Z_gemessen_Ohm",
    },
    values={
        "kind": {"test": "Versuch", "fault": "Erdschluss", "pre_fault": "Vorfehlerquelle",
                 "two_source": "zwei Quellen", "constant": "konstant"},
        "mode": {"loo": "alle anderen", "pairwise": "paarweise", "chain": "Lernkette", "verify": "Prüfmessung",
                 "fault_check": "Erdschlussprüfung"},
        "I_estimated_method": {"node_rule": "Knotenregel (Spulenströme)",
                               "zero_sequence_voltage": "Nullspannung (3·|ΔU0|/|Z0|)"},
        "line_values": {"loop": "Schleife je Ordnung", "orders": "Beläge je Ordnung", "mixed": "teils je Ordnung",
                        "50Hz": "50 Hz, X ∝ m"},
    })

# columns of the estimates without an earth fault (V0 to V3)
i18n.register_labels(columns={
    "m_over_mr": "m_zu_mr", "Z_F_Ohm": "Z_F_Ohm", "U_V": "U_V", "V2_envelope_A": "V2_Huellkurve_A",
    "G_envelope_S": "G_Huellkurve_S", "X_T_Ohm": "X_T_Ohm", "X_Q_Ohm": "X_Q_Ohm", "X_up_Ohm": "X_vor_Ohm",
    "C_E_uF": "C_E_uF", "C_1_uF": "C_1_uF", "m_r": "m_r", "V0_rule_A": "V0_Regel_A",
})

# report titles of the tables of this package (groundfault.report.table_title finds them by their key)
i18n.register({
    "report.title_forecast_network_data": {"en": "Network data and resonance of the busbar",
                                           "de": "Netzdaten und Resonanz der Sammelschiene"},
    "report.title_forecast_ct_angle": {"en": "Angle error of the current transformers against the reference clamp",
                                       "de": "Winkelfehler der Stromwandler gegen die Referenzzange"},
    "report.title_forecast_v3_recordings": {
        "en": "V3: MV network per undisturbed recording (natural sequence) and checks",
        "de": "V3: MS-Netz je ungestörter Aufzeichnung (natürliches Drehsystem) und Prüfwerte"},
    "report.title_forecast_v3": {"en": "V3: pooled estimate of the reliable recordings",
                                 "de": "V3: zusammengefasste Schätzung der verlässlichen Aufzeichnungen"},
    "report.title_forecast_without_fault": {"en": "Forecast without an earth fault: V0 to V3 side by side",
                                            "de": "Prognose ohne Erdschluss: V0 bis V3 nebeneinander"},
    "report.title_forecast_calibrations": {
        "en": "Network model: sequence impedances per earth fault and order",
        "de": "Netzmodell: Sequenzimpedanzen je Erdschluss und Ordnung"},
    "report.title_forecast_model": {"en": "Network model per order", "de": "Netzmodell je Ordnung"},
    "report.title_forecast_checks": {"en": "Network model: checks between the tests",
                                     "de": "Netzmodell: Prüfung zwischen den Versuchen"},
    "report.title_forecast_faults": {"en": "Network model: recorded earth faults – estimated current and forecast",
                                     "de": "Netzmodell: aufgezeichnete Erdschlüsse – geschätzter Strom und Prognose"},
    "report.title_forecast": {"en": "Forecast of the harmonic residual current",
                              "de": "Prognose des Oberschwingungsreststroms"},
})
