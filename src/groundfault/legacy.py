# -*- coding: utf-8 -*-
"""Reading files written by the predecessor tool ``erdschluss`` (German keys, codes and column names).

The tool started as a German in-house project. Its result files (``*_ergebnis.json``, format ``erdschluss-ergebnis``)
and the campaign CSV files (``Korrekturen.csv``, ``Messorte.csv``, ``Messregister.csv``) use German keys.
[`translate_result`][groundfault.legacy.translate_result] converts such a result file into the current (English)
structure, [`translate_columns`][groundfault.legacy.translate_columns] renames German column headers. Nothing here is
needed for files written by groundfault itself.

Options of functions and notebooks, on the other hand, are always given with their English values. A former German value
(``"mittel"``, ``"spektral"``, ``"ersetzen"`` …) or key (``rollen``, ``aus_ll`` …) is not translated but rejected with a
clear error that names the allowed values and the current name ([`check_option`][groundfault.legacy.check_option],
[`check_keys`][groundfault.legacy.check_keys]), so that settings copied by hand from the predecessor are neither ignored
nor misread.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from . import i18n
from .i18n import tr

__all__ = ["LEGACY_RESULT_FORMAT", "RESULT_FORMAT", "RESULT_VERSION", "is_legacy_result", "translate_result",
           "translate_key", "translate_columns", "update_result", "KEYS", "VALUES", "PREFIX_VALUES", "RENAMED",
           "FORMER_OPTION_VALUES", "FORMER_OPTION_KEYS", "check_option", "check_keys"]

i18n.register({
    "legacy.invalid_option": {"en": "{option}={value} is not allowed – allowed: {allowed}{former}",
                              "de": "{option}={value} ist nicht zulässig – zulässig: {allowed}{former}"},
    "legacy.unknown_key": {"en": "{option}: unknown key {name} – allowed: {allowed}{former}",
                           "de": "{option}: unbekannter Schlüssel {name} – zulässig: {allowed}{former}"},
    "legacy.former_name": {"en": " ({old} is the former name of {new})",
                           "de": " ({old} ist der frühere Name von {new})"},
})

LEGACY_RESULT_FORMAT = "erdschluss-ergebnis"
"""``format`` field of result files written by the predecessor tool."""
RESULT_FORMAT = "groundfault-result"
"""``format`` field of result files written by groundfault."""
RESULT_VERSION = 4
"""``version`` field of the result files written by this version of groundfault (3.0: 4; 2.0: 3)."""

RENAMED: Dict[str, str] = {
    # station evaluation, LV network: the fault test gives r·Z_E = U_E/I_F, not the earthing impedance itself
    "Z_E_fault_Ohm": "rZE_fault_Ohm", "Z_E_fault_eff_Ohm": "rZE_fault_eff_Ohm",
    "Z_LV_to_Z_E_fault": "Z_LV_to_rZE_fault",
    "Z_total_fault_Ohm": "Z_E_earth_current_Ohm", "Z_total_fault_eff_Ohm": "Z_E_earth_current_eff_Ohm",
    # reduction factor and comparison with the earthing measurement
    "UE_per_A_fault": "rZE_fault_Ohm", "UE_per_A_direct": "rZE_direct_Ohm", "UE_per_A_fault_eff": "rZE_fault_eff_Ohm",
    "UE_per_A_injection": "Z_E_injection_Ohm", "UE_per_A_injection_eff": "Z_E_injection_eff_Ohm",
    "UE_per_A_earth_current": "Z_E_earth_current_Ohm", "UE_per_A_earth_current_eff": "Z_E_earth_current_eff_Ohm",
    "Z_E_fault_to_injection": "Z_E_earth_current_to_injection",
    "Z_E_fault_to_injection_eff": "Z_E_earth_current_to_injection_eff",
    "Z_E_fault_50Hz_Ohm": "rZE_fault_50Hz_Ohm", "exponent_Z_fault": "exponent_rZE_fault",
    "exponent_Z_injection": "exponent_Z_E_injection", "Z_injection_Ohm": "Z_E_injection_Ohm",
}
"""Column names of groundfault 2.0 (result format version 3) → current name (3.0). The ratio U_E/I_F of the fault
test contains the reduction factor and is therefore called r·Z_E (``rZE_…``); Z_E from the fault test with the earth
current I_E = I_F − I_S is ``Z_E_earth_current…``. [`update_result`][groundfault.legacy.update_result] applies it
when an older result file is read."""

KEYS: Dict[str, str] = {'Abdeckung_I_F_proz': 'I_F_coverage_pct',
 'Abstand_Einspeisung_m': 'distance_injection_m',
 'Abstand_Erdschluss_m': 'distance_fault_m',
 'Abstand_Erdungsmessung_m': 'distance_injection_m',
 'Abstand_m': 'distance_m',
 'Abstandsvergleich': 'distance_match',
 'Abweichung_Median_proz': 'deviation_median_pct',
 'Abweichung_P95_proz': 'deviation_P95_pct',
 'Abweichung_inkl_DC_proz': 'deviation_incl_dc_pct',
 'Abweichung_proz': 'deviation_pct',
 'Aehnlichkeit': 'similarity',
 'Anlagentyp': 'asset_type',
 'Anteil_%s': 'share_%s',
 'Anteil_%s_Winkel_deg': 'share_%s_angle_deg',
 'Anteil_H%d': 'share_H%d',
 'Anteil_H1_proz': 'share_H1_pct',
 'Anteil_I_ON': 'share_I_LV',
 'Anteil_I_ON_eff': 'share_I_LV_eff',
 'Anteil_fehlerbedingt': 'share_fault',
 'Anteil_fehlerbedingt_Winkel_deg': 'share_fault_angle_deg',
 'Anteil_unsicher_proz': 'uncertain_share_pct',
 'Anzahl': 'count',
 'Art': 'kind',
 'Basiseinheit': 'base_unit',
 'Bedeutung': 'meaning',
 'Bemerkung': 'remark',
 'Beschreibung': 'description',
 'Betrag': 'magnitude',
 'Betreiber': 'operator',
 'Bewertung': 'assessment',
 'Bezeichnung': 'designation',
 'Bezug_Gesamterdung': 'total_earthing_reference',
 'Bezugsstrom_A': 'reference_current_A',
 'Breite': 'latitude',
 'Datei': 'file',
 'Datum': 'date',
 'Dauer': 'duration',
 'Dauer_s': 'duration_s',
 'Drift_in_Messung_proz': 'drift_in_measurement_pct',
 'Effektivwert': 'rms',
 'Eingangsimpedanz_Ohm': 'input_impedance_Ohm',
 'Einheit': 'unit',
 'Einheit_Hinweis': 'unit_note',
 'Einheit_gespeichert': 'unit_stored',
 'Entfernung_UW_m': 'distance_to_substation_m',
 'Erdschluss': 'fault test',
 'Erdschluss (groundmeas)': 'fault test (groundmeas)',
 'Erdungsmessung': 'injection test',
 'Erdungsmessung_Frequenz': 'injection_frequency',
 'Erdungsmessung_id': 'injection_id',
 'Ereignis_s': 'event_s',
 'Ersatzmaßnahmen': 'countermeasures',
 'F_UE_zu_UT': 'F_UE_to_UT',
 'F_direkt': 'F_direct',
 'F_fehlerbedingt': 'F_fault',
 'Faktor': 'factor',
 'Faktor_gesamt': 'factor_total',
 'Fehlereintritt': 'fault inception',
 'Fehlerende': 'fault clearance',
 'Fehlerleiter': 'faulted_phase',
 'Fehlerort': 'fault_location',
 'Fehlerwiderstand_Ohm': 'fault_resistance_Ohm',
 'Format': 'format',
 'Frequenz': 'frequency',
 'Frequenzen_Hz': 'frequencies_Hz',
 'Gegen': 'neg',
 'Gewicht_%s': 'weight_%s',
 'Gewicht_n': 'weight_busbar',
 'Gewicht_v': 'weight_feeders',
 'Gleichanteil': 'dc',
 'Gleichung': 'equation',
 'Grenzfall (innerhalb der Unsicherheit)': 'borderline',
 'Groesse': 'quantity',
 'Grundlast_Vorhersagefehler_proz': 'background_forecast_error_pct',
 'Grundlast_zu_fehlerbedingt': 'background_to_fault',
 'Größe': 'quantity',
 'H1_Winkel_bez_ULL_deg': 'H1_angle_ref_ULL_deg',
 'H1_Winkel_deg': 'H1_angle_deg',
 'HINWEIS': 'NOTE',
 'Hauptkanal': 'main_channel',
 'Hinweis': 'note',
 'Hinweise': 'notes',
 'IH_ges': 'IH_total',
 'IH_skaliert': 'IH_scaled',
 'IRES_bewertung': 'IRES_assessed',
 'IRES_ohne_nf': 'IRES_without_lf',
 'IRES_skaliert': 'IRES_scaled',
 'IRMS_prognose': 'IRMS_forecast',
 'I_Fehler_A': 'I_during_fault_A',
 'I_Gegen_A': 'I_neg_A',
 'I_Grenz_A': 'I_limit_A',
 'I_Grundlast_A': 'I_background_A',
 'I_H_zulaessig_A': 'I_H_permissible_A',
 'I_Mit_A': 'I_pos_A',
 'I_Null_A': 'I_zero_A',
 'I_Null_fehler_A': 'I_zero_fault_A',
 'I_ON': 'I_LV',
 'I_ON_%s_A': 'I_LV_%s_A',
 'I_ON_A': 'I_LV_A',
 'I_ON_Unsicherheit_proz': 'I_LV_uncertainty_pct',
 'I_ON_eff_A': 'I_LV_eff_A',
 'I_ON_n_A': 'I_LV_busbar_A',
 'I_ON_v_A': 'I_LV_feeders_A',
 'I_ON_zu_I_E': 'I_LV_to_I_E',
 'I_ON_zu_I_E_eff': 'I_LV_to_I_E_eff',
 'I_fehlerbedingt_A': 'I_fault_A',
 'I_oben': 'I_upper',
 'I_resonanz': 'I_resonance',
 'I_resonanz_fit': 'I_resonance_fit',
 'I_unten': 'I_lower',
 'Index': 'index',
 'KORRIGIERT': 'CORRECTED',
 'Kampagne': 'campaign',
 'Kanaele': 'channels',
 'Kanal': 'channel',
 'Kanäle': 'channels',
 'Knotenregel_Abweichung_proz': 'kcl_deviation_pct',
 'Kommentar': 'comment',
 'Konditionszahl': 'condition_number',
 'Kurz': 'short',
 'Laenge': 'longitude',
 'Lage': 'position',
 'Max': 'max',
 'Max-Fenster': 'max window',
 'Messart': 'measurement_kind',
 'Messbereich': 'range',
 'Messort': 'site',
 'Messung': 'measurement',
 'Messung_Nr': 'measurement_no',
 'Messung_id': 'measurement_id',
 'Messungen': 'measurements',
 'Messwert': 'measured_value',
 'Methode': 'method',
 'Methoden': 'methods',
 'Min': 'min',
 'Mit': 'pos',
 'Mittel': 'mean',
 'Mittel_Geraet': 'mean_device',
 'Mittel_eigen': 'mean_own',
 'Momentanwerte': 'instantaneous',
 'NEIN': 'NO',
 'Nachfehler': 'post-fault',
 'Nachfehler_s': 'post_fault_s',
 'Nennwert': 'rated_value',
 'Normierung': 'normalization',
 'Nr': 'no',
 'Null': 'zero',
 'Ordnung': 'order',
 'Ordnungen': 'orders',
 'Ort': 'location',
 'Ort_groundmeas': 'location_groundmeas',
 'Ort_id': 'location_id',
 'Ortsnetz': 'lv_network',
 'P_Zusatzimpedanz_kW': 'P_additional_impedance_kW',
 'Paar': 'pair',
 'Pegel_Bezug_V': 'level_reference_V',
 'Pegel_komplex': 'level_complex',
 'Pfad': 'path',
 'Phase': 'phase',
 'Polaritaet': 'polarity',
 'Pruefung': 'check',
 'Pruefung_Parallelschaltung': 'parallel_check',
 'Pruefung_Unsicherheit_proz': 'check_uncertainty_pct',
 'Quelle': 'source',
 'RMS_ac': 'rms_ac',
 'R_E_wirksam_Ohm': 'R_E_effective_Ohm',
 'R_Grenz_Ohm': 'R_limit_Ohm',
 'R_ON': 'R_LV',
 'Residuum_proz': 'residual_pct',
 'Rolle': 'role',
 'Saettigung_proz': 'saturation_pct',
 'Scheitelfaktor': 'crest_factor',
 'Scheitelwert': 'peak',
 'Sequenz': 'sequence',
 'Spanne_proz': 'span_pct',
 'Spannungsebene_kV': 'voltage_level_kV',
 'Spitze_RMS': 'peak_rms',
 'Start_cfg': 'start_cfg',
 'Stationaer_s': 'steady_state_s',
 'Status': 'status',
 'Streuung_Verfahren_proz': 'method_spread_pct',
 'Sättigung': 'saturation',
 'THD_proz': 'THD_pct',
 'Trigger_s': 'trigger_s',
 'Typ': 'type',
 'UE_bei_%gA_V': 'UE_at_%gA_V',
 'UE_je_A_Erdschluss_direkt': 'rZE_direct_Ohm',
 'UE_je_A_Erdschluss_eff': 'rZE_fault_eff_Ohm',
 'UE_je_A_Erdschluss_fehlerbedingt': 'rZE_fault_Ohm',
 'UE_je_A_Erdungsmessung': 'Z_E_injection_Ohm',
 'UE_je_A_Erdungsmessung_eff': 'Z_E_injection_eff_Ohm',
 'UH5g_vor': 'UH5g_pre',
 'UH7m_vor': 'UH7m_pre',
 'UH_LL_vor_V': 'UH_LL_pre_V',
 'UNSICHER': 'UNCERTAIN',
 'UNull_H1_V': 'Uzero_H1_V',
 'UTHD%s_proz': 'UTHD%s_pct',
 'UTHD12_proz': 'UTHD12_pct',
 'UTHD23_proz': 'UTHD23_pct',
 'UTHD31_proz': 'UTHD31_pct',
 'UTHD_LL_vor_proz': 'UTHD_LL_pre_pct',
 'UTHD_mess': 'UTHD_meas',
 'UT_bei_%gA_V': 'UT_at_%gA_V',
 'U_E_fehlerbedingt_V': 'U_E_fault_V',
 'U_E_fehlerbedingt_eff_V': 'U_E_fault_eff_V',
 'U_Fehler_V': 'U_during_fault_V',
 'U_Gegen': 'U_neg',
 'U_Grundlast_V': 'U_background_V',
 'U_Grundlast_plus_Fehler_V': 'U_background_plus_fault_V',
 'U_Mit': 'U_pos',
 'U_Mit_H1_V': 'U_pos_H1_V',
 'U_Null': 'U_zero',
 'U_fehlerbedingt_V': 'U_fault_V',
 'U_nach_V': 'U_post_V',
 'U_vor_V': 'U_pre_V',
 'U_vor_ll': 'U_pre_ll',
 'U_ziel': 'U_target',
 'Unsicherheit_Frequenz_proz': 'frequency_uncertainty_pct',
 'Unsicherheit_proz': 'uncertainty_pct',
 'Uq_Winkel_bez_Fehlerleiter_deg': 'Uq_angle_ref_faulted_phase_deg',
 'Uq_Winkel_deg': 'Uq_angle_deg',
 'Uq_bez_Fehlerleiter': 'Uq_ref_faulted_phase',
 'V_je_100A_direkt': 'V_per_100A_direct',
 'V_je_100A_fehlerbedingt': 'V_per_100A_fault',
 'V_pro_100A': 'V_per_100A',
 'V_pro_100A_RMS': 'V_per_100A_RMS',
 'Verhaeltnis_%s': 'ratio_%s',
 'Verhaeltnis_direkt': 'ratio_direct',
 'Verhaeltnis_fehlerbedingt': 'ratio_fault',
 'Vorfehler': 'pre-fault',
 'Vorfehler_s': 'pre_fault_s',
 'WARNUNG': 'WARNING',
 'Wert': 'value',
 'Wert_Max_Fenster': 'value_max_window',
 'Wert_id': 'item_id',
 'Werte': 'values',
 'Wertebereich': 'value_range',
 'Winkel_Erdungsmessung_deg': 'injection_angle_deg',
 'Winkel_bez_ULL_deg': 'angle_ref_ULL_deg',
 'Winkel_deg': 'angle_deg',
 'Winkel_zu_IF_H%d_deg': 'angle_to_IF_H%d_deg',
 'Winkel_zu_IF_H1_deg': 'angle_to_IF_H1_deg',
 'X_ON1': 'X_LV1',
 'ZE_H%d_Winkel_deg': 'ZE_H%d_angle_deg',
 'ZE_sonde': 'ZE_probe',
 'Z_%s_Winkel_deg': 'Z_%s_angle_deg',
 'Z_E_Erdungsmessung_Ohm': 'Z_E_injection_Ohm',
 'Z_E_Erdungsmessung_eff_Ohm': 'Z_E_injection_eff_Ohm',
 'Z_E_Ortsnetz_Ohm': 'Z_E_LV_Ohm',
 'Z_E_Ortsnetz_Unsicherheit_proz': 'Z_E_LV_uncertainty_pct',
 'Z_E_Ortsnetz_Winkel_deg': 'Z_E_LV_angle_deg',
 'Z_E_Ortsnetz_eff_Ohm': 'Z_E_LV_eff_Ohm',
 'Z_Erdungsmessung_Ohm': 'Z_E_injection_Ohm',
 'Z_ON': 'Z_LV',
 'Z_ON_sonde': 'Z_LV_probe',
 'Z_Ortsnetz_zu_Z_E': 'Z_LV_to_Z_E',
 'Z_Ortsnetz_zu_Z_E_eff': 'Z_LV_to_Z_E_eff',
 'Z_direkt_Ohm': 'Z_direct_Ohm',
 'Z_direkt_Winkel_deg': 'Z_direct_angle_deg',
 'Z_eintritt_Ohm': 'Z_inception_Ohm',
 'Z_ende_Ohm': 'Z_clearance_Ohm',
 'Z_fehler': 'Z_fault',
 'Z_fehlerbedingt_Ohm': 'Z_fault_Ohm',
 'Z_fehlerbedingt_Winkel_deg': 'Z_fault_angle_deg',
 'Z_gesamt_Erdschluss_Ohm': 'Z_E_earth_current_Ohm',
 'Z_gesamt_Erdschluss_eff_Ohm': 'Z_E_earth_current_eff_Ohm',
 'Z_spannung_Ohm': 'Z_voltage_Ohm',
 'Zeile': 'line',
 'Zeit': 'time',
 'Zeit_UTC': 'time_UTC',
 'Zeitpunkt': 'timestamp',
 'Zeitstempel': 'timestamp',
 'Zusatzwiderstand_Ohm': 'additional_resistance_Ohm',
 '_korrekturen_angewendet': '_corrections_applied',
 'abstand_m': 'distance_m',
 'abtastwerte': 'samples',
 'abweichend': 'different',
 'abweichung_hz': 'deviation_hz',
 'aktiv': 'active',
 'alle_ids': 'all_ids',
 'andere': 'other',
 'angelegt': 'created',
 'anlagentyp': 'asset_type',
 'aufteilung_50hz': 'split_50hz',
 'ausgangsfehler': 'output_error',
 'ausrichtung': 'alignment',
 'ausschnitte': 'excerpts',
 'automatisch': 'automatic',
 'basis': 'base',
 'basiseinheit': 'base_unit',
 'bemerkung': 'remark',
 'bereiche': 'intervals',
 'bereit': 'ready',
 'betreiber': 'operator',
 'bewertungsgroessen': 'assessment_quantities',
 'bezug': 'reference',
 'cfg_datei': 'cfg_file',
 'cfg_pfad': 'cfg_path',
 'datei': 'file',
 'datei_': 'file_',
 'dauer': 'duration',
 'dauer_s': 'duration_s',
 'direkt': 'direct',
 'effektivwertverlauf': 'rms_trend',
 'eigen_id': 'own_id',
 'eingeschwungen_ab': 'settled_from',
 'einheit': 'unit',
 'einstellungen': 'settings',
 'eintritt': 'inception',
 'ende': 'clearance',
 'entfernung_uw_m': 'distance_to_substation_m',
 'erdung_vergleich': 'earthing_comparison',
 'erdungsspannungen_': 'epr_',
 'ereigniszeiten': 'event_times',
 'erfüllt': 'satisfied',
 'ergebnis_set': 'result_set',
 'erneuert': 'renewed',
 'ersatzquellen': 'equivalent_sources',
 'ersetzen': 'replace',
 'erstellt': 'created',
 'exakt': 'exact',
 'export_ordnungen': 'export_orders',
 'f1_methode': 'f1_method',
 'f1_schaetzen': 'estimate_frequency',
 'f1_vergleich': 'f1_comparison',
 'f1_verwendet': 'f1_used',
 'f_fehler_hz': 'f_fault_hz',
 'f_fehler_quelle': 'f_fault_source',
 'f_grundlast_hz': 'f_background_hz',
 'f_grundlast_quelle': 'f_background_source',
 'f_grundlast_spanne_mhz': 'f_background_span_mhz',
 'f_nenn': 'f_nominal',
 'faktor': 'factor',
 'faktor_gesamt': 'factor_total',
 'faktor_v': 'factor_feeders',
 'faktoren': 'factors',
 'fehlerbedingt': 'fault',
 'fehlerleiter': 'faulted_phase',
 'fehlerstrom': 'fault_current',
 'fehlerwiderstand_ohm': 'fault_resistance_ohm',
 'fehlerzeiten': 'fault_times',
 'fehlt': 'missing',
 'fenster': 'window',
 'fest': 'fixed',
 'fs_herkunft': 'fs_source',
 'fs_zeitstempel': 'fs_timestamps',
 'gedreht': 'rotated',
 'geschrieben': 'written',
 'gleich': 'equal',
 'gleichung': 'equation',
 'gleichungsfehler': 'equation_error',
 'grenzwerte_ires': 'ires_limits',
 'groessen': 'quantities',
 'gruende': 'reasons',
 'grund': 'reason',
 'grundfrequenz_hz': 'fundamental_hz',
 'grundlast_aus': 'background_from',
 'halb': 'half',
 'hann_periodisch': 'hann_periodic',
 'harmonische': 'harmonics',
 'hauptkanal': 'main_channel',
 'hauptkanal_%s': 'main_channel_%s',
 'hauptkanal_i_res': 'main_channel_i_res',
 'hinweis': 'note',
 'hinweise': 'hints',
 'i_pen_n': 'i_pen_busbar',
 'i_pen_v': 'i_pen_feeders',
 'i_schirm': 'i_shield',
 'ignorieren': 'ignore',
 'injektion': 'injection',
 'injektionen': 'injections',
 'interpoliert': 'interpolated',
 'ires_niederfrequent_A': 'ires_low_frequency_A',
 'ja': 'yes',
 'k_ON': 'k_LV',
 'kanaele': 'channels',
 'kanal': 'channel',
 'kennwerte': 'metrics',
 'konsistenz': 'consistency',
 'koordinaten': 'coordinates',
 'korrekturen': 'corrections',
 'kurz': 'short',
 'l_Grenz_km': 'l_limit_km',
 'lage': 'position',
 'last_n': 'load_busbar',
 'last_schwankung': 'load_fluctuation',
 'last_v': 'load_feeders',
 'letzte': 'last',
 'manuell': 'manual',
 'markieren': 'mark',
 'max_suche_hop': 'max_search_hop',
 'messort': 'site',
 'messung': 'measurement',
 'messung_id': 'measurement_id',
 'messwert': 'measured_value',
 'methode': 'method',
 'methode_vergleich': 'method_comparison',
 'mit_spannungen': 'with_voltages',
 'mittel': 'mean',
 'mittelwert': 'mean',
 'momentanwerte': 'instantaneous',
 'n_fehler': 'n_fault',
 'n_fenster': 'window_samples',
 'n_grundlast': 'n_background_',
 'nachfehler': 'post_fault',
 'natuerlich': 'natural',
 'nulltest': 'null_test',
 'nummern_ok': 'numbers_ok',
 'ordnungen': 'orders',
 'ort': 'location',
 'ort_groundmeas': 'location_groundmeas',
 'ort_id': 'location_id',
 'ort_neu': 'location_new',
 'ortsnetz': 'lv_network',
 'passend': 'suitable',
 'plausibel': 'plausible',
 'plausibilitaet': 'plausibility',
 'polaritaet_i_res': 'polarity_i_res',
 'polaritaet_korrigieren': 'correct_polarity',
 'polaritaet_reserve_deg': 'polarity_margin_deg',
 'pq_sicherheitsfaktor': 'pq_safety_factor',
 'prominenz': 'prominence',
 'rZE_H%d_Winkel_deg': 'rZE_H%d_angle_deg',
 'rZE_H1_Winkel_deg': 'rZE_H1_angle_deg',
 'rZE_V_je_100A': 'rZE_V_per_100A',
 'rZE_sonde': 'rZE_probe',
 'r_H%d_betrag': 'r_H%d_magnitude',
 'r_H%d_komplex': 'r_H%d_complex',
 'r_H1_komplex': 'r_H1_complex',
 'r_Schirmstrom': 'r_shield',
 'r_betrag': 'r_magnitude',
 'r_direkt': 'r_direct',
 'r_eff_Effektivwerte': 'r_eff_rms',
 'r_eff_Schirmstrom': 'r_eff_shield',
 'r_eff_direkt': 'r_eff_direct',
 'r_komplex': 'r_complex',
 'rec_info': 'recording_info',
 'rechteck': 'rectangular',
 'reduktionsfaktor': 'reduction_factor',
 'referenz': 'reference',
 'resistiver_ansatz': 'resistive_approach',
 'rolle': 'role',
 'rollen': 'roles',
 'rollen_': 'roles_',
 'schirm': 'shield',
 'schirmstrom_': 'shield_current_',
 'schreibbar': 'writable',
 'schreibweisen': 'spellings',
 'sicherung': 'backup',
 'signale': 'signals',
 'spanne_grund_hz': 'span_background_hz',
 'spanne_hz': 'span_hz',
 'spannung': 'voltage',
 'spannung_': 'voltage_',
 'spannung_erdschluss': 'voltage_fault',
 'spannung_gegensystem': 'voltage_negative_sequence',
 'spannung_kennwerte': 'voltage_metrics',
 'spannung_mitsystem': 'voltage_positive_sequence',
 'spannung_nachfehler': 'voltage_post_fault',
 'spannung_vorfehler': 'voltage_pre_fault',
 'spannungs_harmonische': 'voltage_harmonics',
 'spannungsanalyse': 'voltage_analysis',
 'spannungsebene_kv': 'voltage_level_kv',
 'spektral': 'spectral',
 'spektrum': 'spectrum',
 'spektrum_fehlerstrom': 'spectrum_fault_current',
 'spruenge': 'jumps',
 'spulen_H1_A': 'coils_H1_A',
 'spulenbilanz_steigung': 'coil_balance_slope',
 'spulenstroeme': 'coil_currents',
 'stabil': 'stable',
 'station_frequenz': 'station_frequency',
 'station_grundlast': 'station_background',
 'station_hochrechnung': 'station_extrapolation',
 'station_kennwerte': 'station_metrics',
 'station_ortsnetz': 'station_lv_network',
 'station_ortsnetz_eff': 'station_lv_network_eff',
 'station_spannungen': 'station_voltages',
 'station_stroeme': 'station_currents',
 'station_stroeme_frequenz': 'station_currents_frequency',
 'stationaer': 'steady_state',
 'stationär': 'steady state',
 'statistik': 'statistics',
 'streuung_hz': 'spread_hz',
 't_fehler_s': 't_fault_s',
 't_fehlereintritt_s': 't_fault_inception_s',
 't_fehlerende_s': 't_fault_clearance_s',
 't_grundlast_s': 't_background_s',
 't_max_fenster_s': 't_max_window_s',
 'tabellen': 'tables',
 'thd_bezug': 'thd_reference',
 'thd_bis_ordnung': 'thd_max_order',
 'trafo': 'transformer',
 'trafo_leistung': 'transformer_power',
 'trafo_spannung': 'transformer_voltage',
 'trafo_vorzeichen': 'transformer_sign',
 'u_hs_l%se': 'u_hv_l%se',
 'u_hs_l1e': 'u_hv_l1e',
 'u_hs_l2e': 'u_hv_l2e',
 'u_hs_l3e': 'u_hv_l3e',
 'u_thd95_prozent': 'u_thd95_percent',
 'uebersicht': 'overview',
 'ueberspringen': 'skip',
 'unbekannt': 'unknown',
 'unkritisch': 'uncritical',
 'unregelmaessig_proz': 'irregular_pct',
 'unsicher': 'uncertain',
 'unsicherheit_I': 'uncertainty_I',
 'unsicherheit_U': 'uncertainty_U',
 'untypisch': 'atypical',
 'verfahren': 'method',
 'verletzt': 'violated',
 'verschoben': 'shifted',
 'vertauscht': 'swapped',
 'voll': 'full',
 'vorfehler': 'pre_fault',
 'vorgabe': 'override',
 'vorhanden_id': 'existing_id',
 'vorhersagefehler': 'forecast_error',
 'vorzeichen': 'sign',
 'vorzeichen_n': 'sign_busbar',
 'wahr': 'truth',
 'warnungen': 'warnings',
 'weglassen': 'omit',
 'werte': 'values',
 'winkel_deg_bez_ULL': 'angle_deg_ref_ULL',
 'winkelverfahren': 'angle_method',
 'z_fehler_ohm': 'z_fault_ohm',
 'zeile': 'line',
 'zeitstempel': 'timestamps',
 'ähnlich': 'similar'}
"""German key or column name → current name."""

KEYS.update({
    "bewertung": "assessed", "dc_methode": "dc_method", "fenster_t_s": "window_t_s", "stationaer_s": "steady_state_s",
    "vorfehler_s": "pre_fault_s", "nachfehler_s": "post_fault_s", "rms_fenster": "rms_window", "rms_mittel": "rms_mean",
    "harmonische_hz": "harmonics_hz", "datenmodus": "data_mode", "werkzeug": "tool", "n_grundlast": "n_background",
    "Bereich": "interval", "zeitstempel": "start_time", "erdschluss": "fault", "erdschluss_phasor": "fault_phasor",
})
# erdschluss 1.5.0: probe maximum, checks against the fault test, classification and assessment relevance
KEYS.update({
    "Sonde": "probe", "Z_E_Erdschluss_Ohm": "rZE_fault_Ohm", "Z_E_Erdschluss_eff_Ohm": "rZE_fault_eff_Ohm",
    "Z_Ortsnetz_zu_Z_E_Erdschluss": "Z_LV_to_rZE_fault", "Pruefung_Erdungsstrom": "earth_current_check",
    "Vergleich_Erdungsmessung": "injection_comparison", "Vergleich_Unsicherheit_proz": "comparison_uncertainty_pct",
    "Anteil_Schirmstrom": "share_shield", "Anteil_Schirmstrom_eff": "share_shield_eff",
    "UE_je_A_Erdungsstrom": "Z_E_earth_current_Ohm", "UE_je_A_Erdungsstrom_eff": "Z_E_earth_current_eff_Ohm",
    "Z_E_Erdschluss_zu_Erdungsmessung": "Z_E_earth_current_to_injection",
    "Z_E_Erdschluss_zu_Erdungsmessung_eff": "Z_E_earth_current_to_injection_eff", "r_zu_r_50Hz": "r_to_r_50Hz",
    "r_50Hz": "r_50Hz", "Z_E_Erdschluss_50Hz_Ohm": "rZE_fault_50Hz_Ohm",
    "Z_E_Erdungsmessung_50Hz_Ohm": "Z_E_injection_50Hz_Ohm", "Einordnung_r_50Hz": "classification_r_50Hz",
    "Verlauf_r_ueber_f": "trend_r_vs_f", "Exponent_r_ueber_f": "exponent_r_vs_f",
    "Exponent_Z_Erdschluss": "exponent_rZE_fault", "Exponent_Z_Erdungsmessung": "exponent_Z_E_injection",
    "Verlauf_Ordnungen": "trend_orders", "U_E_Erdschluss_bei_Bezugsstrom_V": "U_E_fault_at_reference_current_V",
    "U_E_Erdungsmessung_bei_Bezugsstrom_V": "U_E_injection_at_reference_current_V",
    "Abweichung_bei_Bezugsstrom_V": "deviation_at_reference_current_V", "F_mal_U_Tp_V": "F_times_U_Tp_V",
    "Bewertungsrelevanz_proz": "assessment_relevance_pct", "Bewertungsrelevanz": "assessment_relevance",
})
# keys of the section meta (campaign, origin of a correction); the scaling factor of the harmonic content and the
# plausibility values of the harmonic content are read by pattern (_PATTERNS)
KEYS.update({"kampagne": "campaign", "quelle": "source"})

#: Keys whose names are built from a code (``Anteil_eintritt``, ``Z_ende_Winkel_deg`` …)
_CODES = {"direkt": "direct", "eintritt": "inception", "ende": "clearance", "spannung": "voltage",
          "fehlerbedingt": "fault", "v": "feeders", "n": "busbar", "PEN": "PEN", "vorfehler": "pre_fault",
          "nachfehler": "post_fault", "erdschluss": "fault", "stationaer": "steady_state", "alle": "all",
          "auswahl": "selection"}
_PATTERNS = [
    (re.compile(r"^Anteil_H(\d+)$"), r"share_H\1"),
    (re.compile(r"^Anteil_(direkt|eintritt|ende|spannung|fehlerbedingt)$"), "share_{0}"),
    (re.compile(r"^Anteil_(direkt|eintritt|ende|spannung|fehlerbedingt)_Winkel_deg$"), "share_{0}_angle_deg"),
    (re.compile(r"^Z_(direkt|eintritt|ende|spannung|fehlerbedingt)_Ohm$"), "Z_{0}_Ohm"),
    (re.compile(r"^Z_(direkt|eintritt|ende|spannung|fehlerbedingt)_Winkel_deg$"), "Z_{0}_angle_deg"),
    (re.compile(r"^Verhaeltnis_(direkt|fehlerbedingt)$"), "ratio_{0}"),
    (re.compile(r"^Gewicht_(v|n)$"), "weight_{0}"),
    (re.compile(r"^I_ON_(v|n|PEN)_A$"), "I_LV_{0}_A"),
    (re.compile(r"^(UE|UT)_bei_([0-9.]+)A_V$"), r"\1_at_\2A_V"),
    (re.compile(r"^Winkel_zu_IF_H(\d+)_deg$"), r"angle_to_IF_H\1_deg"),
    (re.compile(r"^(r?ZE)_H(\d+)_Winkel_deg$"), r"\1_H\2_angle_deg"),
    (re.compile(r"^r_H(\d+)_betrag$"), r"r_H\1_magnitude"),
    (re.compile(r"^r_H(\d+)_komplex$"), r"r_H\1_complex"),
    (re.compile(r"^(vorfehler|nachfehler|erdschluss|stationaer)_phasor$"), "{0}_phasor"),
    (re.compile(r"^spannung_(vorfehler|nachfehler|erdschluss)$"), "voltage_{0}"),
    (re.compile(r"^hauptkanal_(\w+)$"), r"main_channel_\1"),
    # predecessor keys that carry the number of a formula: the scaling factor of the harmonic content and the
    # plausibility values of the harmonic content (all orders / the selected orders)
    (re.compile(r"^faktor_gl\d+$"), "factor_scaling"),
    (re.compile(r"^plaus_gl\d+_(alle|auswahl)$"), "plaus_harmonic_{0}"),
]

VALUES: Dict[str, Dict[str, str]] = {'background_from': {'erdschluss': 'fault',
                     'nachfehler': 'post_fault',
                     'stationaer': 'steady_state',
                     'vorfehler': 'pre_fault'},
 'distance_match': {'abweichend': 'different', 'gleich': 'equal', 'unbekannt': 'unknown', 'ähnlich': 'similar'},
 'f1_method': {'nulldurchgang': 'zero_crossing',
               'phase': 'phase',
               'regression': 'regression',
               'spektral': 'spectral'},
 'interval': {'erdschluss': 'fault',
              'nachfehler': 'post_fault',
              'stationaer': 'steady_state',
              'vorfehler': 'pre_fault'},
 'method': {'direkt': 'direct',
            'eintritt': 'inception',
            'ende': 'clearance',
            'fehlerbedingt': 'fault',
            'spannung': 'voltage'},
 'method_comparison': {'nulldurchgang': 'zero_crossing',
                       'phase': 'phase',
                       'regression': 'regression',
                       'spektral': 'spectral'},
 'parallel_check': {'Grenzfall (innerhalb der Unsicherheit)': 'borderline',
                    'erfüllt': 'satisfied',
                    'verletzt': 'violated'},
 'position': {'n': 'busbar', 'v': 'feeders'},
 'quantity': {'IH_ges': 'IH_total',
              'IH_skaliert': 'IH_scaled',
              'IRES_skaliert': 'IRES_scaled',
              'IRMS_prognose': 'IRMS_forecast'},
 'role': {'i_pen_n': 'i_pen_busbar',
          'i_pen_v': 'i_pen_feeders',
          'i_schirm': 'i_shield',
          'u_hs_l1e': 'u_hv_l1e',
          'u_hs_l2e': 'u_hv_l2e',
          'u_hs_l3e': 'u_hv_l3e'},
 'source': {'Erdschluss': 'fault test',
            'Erdschluss (groundmeas)': 'fault test (groundmeas)',
            'Erdungsmessung': 'injection test'},
 'status': {'HINWEIS': 'NOTE', 'KORRIGIERT': 'CORRECTED', 'WARNUNG': 'WARNING'},
 'thd_reference': {'mittel': 'mean', 'nachfehler': 'post_fault', 'vorfehler': 'pre_fault'},
 'transformer_voltage': {'hs': 'hv', 'ms': 'mv'}}
"""Code values in table cells and lists, per (current) column or key name."""

_CHECK = {"erfüllt": "satisfied", "verletzt": "violated", "Grenzfall (innerhalb der Unsicherheit)": "borderline",
          "verletzt (siehe Ordnungen)": "violated (see orders)"}
VALUES["parallel_check"] = dict(_CHECK)
VALUES["earth_current_check"] = dict(_CHECK)
VALUES["injection_comparison"] = {"erfüllt": "satisfied", "Grenzfall (innerhalb der Unsicherheit)": "borderline",
                                  "unterschritten": "below", "unterschritten (siehe Ordnungen)": "below (see orders)"}
VALUES["distance_match"]["Maximum"] = "maximum"
VALUES["assessment_relevance"] = {"vernachlässigbar": "negligible", "Bewertung unverändert": "unchanged",
                                  "bewertungsrelevant": "relevant"}
VALUES["trend_r_vs_f"] = {"fallend (erwartet)": "falling", "etwa konstant": "constant",
                          "steigend (unerwartet)": "rising"}
VALUES["status"]["UNSICHER"] = "UNCERTAIN"
VALUES["normalization"] = {"komplex": "complex", "betrag": "magnitude", "keine": "none"}
VALUES["polarity"] = {"gedreht": "rotated", "wie gemessen": "as measured"}
VALUES["sequence"] = {"Mit": "pos", "Gegen": "neg", "Null": "zero"}
VALUES["location_id"] = {"neu": "new"}
VALUES["quantity"].update({"Erdungsspannung": "earth_potential_rise", "Berührungsspannung": "touch_voltage"})
VALUES["distance_match"]["Berührung (≤ 1,5 m)"] = "touch"
VALUES["kind"] = {"Station": "station", "UW": "substation", "Momentanwerte": "instantaneous"}
VALUES["assessment_substation"] = {"unkritisch": "uncritical", "Ersatzmaßnahmen": "countermeasures"}
KEYS["Bewertung_UW"] = "assessment_substation"
# settings stored with the result: window function, DC removal and the frequency-estimation method (``f1``)
VALUES["window"] = {"hann_periodisch": "hann_periodic", "rechteck": "rectangular", "keine": "rectangular"}
VALUES["dc"] = {"mittel": "mean", "mittelwert": "mean", "keine": "none"}
VALUES["dc_method"] = dict(VALUES["dc"])
VALUES["method"].update({"spektral": "spectral", "nulldurchgang": "zero_crossing"})
VALUES["quantity"]["UTHD_mess"] = "UTHD_meas"
#: role names in lists (``alignment.roles``)
VALUES["roles"] = dict(VALUES["role"])

PREFIX_VALUES: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "classification_r_50Hz": (("unter dem üblichen Bereich", "below"), ("im üblichen Bereich", "typical"),
                              ("über dem üblichen Bereich", "above"), ("über 1", "implausible")),
}
"""Code values that the predecessor wrote together with numbers (``"im üblichen Bereich <low>–<high>"``): per column
the German text prefixes and their codes (checked in this order)."""

FORMER_OPTION_VALUES: Dict[str, Dict[str, str]] = {
    "reference": {"mittel": "mean", "vorfehler": "pre_fault", "nachfehler": "post_fault"},
    "thd_reference": {"mittel": "mean", "vorfehler": "pre_fault", "nachfehler": "post_fault"},
    "normalization": {"komplex": "complex", "betrag": "magnitude", "keine": "none"},
    "method": {"gleichungsfehler": "equation_error", "ausgangsfehler": "output_error", "spektral": "spectral",
               "direkt": "direct", "fehlerbedingt": "fault", "eintritt": "inception", "ende": "clearance",
               "spannung": "voltage"},
    "f1_method": {"spektral": "spectral"},
    "sequence": {"natuerlich": "natural", "Mit": "pos", "Gegen": "neg", "Null": "zero", "mit": "pos",
                 "gegen": "neg", "null": "zero"},
    "angle_reference": {"grundschwingung": "fundamental", "harmonische": "harmonics"},
    "window": {"hann_periodisch": "hann_periodic", "rechteck": "rectangular", "keine": "rectangular"},
    "dc": {"mittel": "mean", "mittelwert": "mean", "keine": "none"},
    "transformer_voltage": {"ms": "mv", "hs": "hv"},
    "existing": {"ersetzen": "replace", "ueberspringen": "skip"},
    "uncertain_mode": {"markieren": "mark", "weglassen": "omit"},
    "units": {"passend": "suitable", "basis": "base"},
    "GROUNDMEAS_EXPORT": {"ersetzen": "replace"},
}
"""Former (German) values of options of the predecessor tool → current value, per option name (parameter or notebook
variable). They are not accepted; ``check_option`` names the current value in its error message."""
FORMER_OPTION_KEYS: Dict[str, Dict[str, str]] = {
    "alignment": {"rollen": "roles", "kanaele": "channels", "kanäle": "channels"},
    "RESISTIVE": {"aus_ll": "from_ll"},
    "MEASUREMENTS": {"messung": "measurement", "ort": "location", "beschreibung": "description",
                     "zeitpunkt": "timestamp"},
}
"""Former (German) keys of option dictionaries of the predecessor tool → current key, per option name. They are not
accepted; ``check_keys`` names the current key in its error message."""


def _shown(value: Any) -> str:
    """A value as it is written in Python (strings quoted)."""
    return repr(value) if isinstance(value, str) else str(value)


def _contains(values: Iterable[Any], value: Any) -> bool:
    """``value in values`` without errors for values that cannot be compared."""
    try:
        return any(value == v and type(value) is not bool or value is v for v in values)
    except Exception:
        return False


def _former(table: Mapping[str, str], value: Any, accepted: Sequence[Any]) -> str:
    """Hint on the current name of a former value or key (only if that name is accepted here)."""
    new = table.get(value) if isinstance(value, str) else None
    return tr("legacy.former_name", old=_shown(value), new=_shown(new)) if new is not None and \
        _contains(accepted, new) else ""


def check_option(option: str, value: Any, allowed: Sequence[Any], *, aliases: Iterable[Any] = (),
                 former: Optional[Mapping[str, str]] = None) -> Any:
    """Check the value of an option – options are given with their English values.

    Parameters
    ----------
    option : str
        Name of the option (parameter or notebook variable), used in the message.
    value : any
        The given value.
    allowed : sequence
        Allowed values (named in the message).
    aliases : iterable, optional
        Further accepted spellings (not named in the message).
    former : mapping, optional
        Former values of the predecessor tool → current value (default: ``FORMER_OPTION_VALUES[option]``).

    Returns
    -------
    any
        ``value`` unchanged.

    Raises
    ------
    ValueError
        If ``value`` is neither allowed nor an alias. The message names the allowed values and, for a former value
        of the predecessor tool, its current name.

    Examples
    --------
    >>> check_option("reference", "mittel", ("pre_fault", "post_fault", "mean"))  # doctest: +NORMALIZE_WHITESPACE
    Traceback (most recent call last):
    ...
    ValueError: reference='mittel' is not allowed – allowed: 'pre_fault', 'post_fault', 'mean' ('mittel' is the former
    name of 'mean')
    """
    aliases = tuple(aliases)
    if _contains(allowed, value) or _contains(aliases, value):
        return value
    table = FORMER_OPTION_VALUES.get(option, {}) if former is None else former
    raise ValueError(tr("legacy.invalid_option", option=option, value=_shown(value),
                        allowed=", ".join(_shown(v) for v in allowed),
                        former=_former(table, value, tuple(allowed) + aliases)))


def check_keys(option: str, mapping: Mapping[str, Any], allowed: Sequence[str], *,
               former: Optional[Mapping[str, str]] = None) -> None:
    """Check the keys of an option dictionary (``alignment``, notebook settings such as ``RESISTIVE``).

    Parameters
    ----------
    option : str
        Name of the option, used in the message.
    mapping : mapping
        The given dictionary.
    allowed : sequence of str
        Allowed keys.
    former : mapping, optional
        Former keys of the predecessor tool → current key (default: ``FORMER_OPTION_KEYS[option]``).

    Raises
    ------
    ValueError
        For the first unknown key: the message names the allowed keys and, for a former key of the predecessor tool,
        its current name.
    """
    table = FORMER_OPTION_KEYS.get(option, {}) if former is None else former
    for key in mapping:
        if key not in allowed:
            raise ValueError(tr("legacy.unknown_key", option=option, name=_shown(key),
                                allowed=", ".join(_shown(k) for k in allowed), former=_former(table, key, allowed)))


#: Containers whose keys are data (channel names) rather than field names
_DATA_KEYS = {"signale", "signals", "rollen", "roles"}
#: Containers whose keys are roles
_ROLE_KEYS = {"hauptkanal", "main_channel"}


def is_legacy_result(data: Mapping[str, Any]) -> bool:
    """True for a result file of the predecessor tool (German keys)."""
    return data.get("format") == LEGACY_RESULT_FORMAT or "werte" in data or "signale" in data


def translate_key(key: str) -> str:
    """Current name of a German key or column name (unchanged if it is not a legacy name)."""
    if key in KEYS:
        return KEYS[key]
    for pattern, target in _PATTERNS:
        m = pattern.match(key)
        if m:
            if "{0}" in target:
                return target.format(_CODES.get(m.group(1), m.group(1)))
            return pattern.sub(target, key)
    return key


def _value(key: str, value: Any) -> Any:
    """Current code of a legacy cell value of column/key ``key`` (unchanged if it is not a legacy text)."""
    if not isinstance(value, str):
        return value
    table = VALUES.get(key)
    if table and value in table:
        return table[value]
    for prefix, code in PREFIX_VALUES.get(key, ()):
        if value.startswith(prefix):
            return code
    return value


def _translate(x: Any, parent: str = "") -> Any:
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if parent in _DATA_KEYS:
                k2 = k
            elif parent in _ROLE_KEYS:
                k2 = VALUES["role"].get(k, k)
            else:
                k2 = translate_key(k) if isinstance(k, str) else k
            if parent in _DATA_KEYS and isinstance(v, str):          # roles: {channel: role}
                out[k2] = VALUES["role"].get(v, v)
            elif isinstance(v, (dict, list)):
                out[k2] = _translate(v, k2 if parent not in _DATA_KEYS else "")
            else:
                out[k2] = _value(k2, v)
        return out
    if isinstance(x, list):
        return [_translate(v, parent) if isinstance(v, (dict, list)) else _value(parent, v) for v in x]
    return x


def translate_result(data: Mapping[str, Any]) -> Dict[str, Any]:
    """Convert a result file of the predecessor tool into the current structure.

    Parameters
    ----------
    data : mapping
        Parsed JSON of a ``*_ergebnis.json`` file (format ``erdschluss-ergebnis``).

    Returns
    -------
    dict
        The same content with current keys, column names and codes; ``format`` is kept so that the origin of
        the file stays visible.
    """
    out = _translate(dict(data))
    out["format"] = data.get("format", LEGACY_RESULT_FORMAT)
    return out


def update_result(data: Mapping[str, Any]) -> Dict[str, Any]:
    """Bring a result file of an earlier groundfault version up to date: column names of the tables that were renamed
    ([`RENAMED`][groundfault.legacy.RENAMED]).

    Parameters
    ----------
    data : mapping
        Parsed JSON of a result file (format ``groundfault-result``).

    Returns
    -------
    dict
        The same content; the tables carry the current column names. Files of the current version are returned
        unchanged.
    """
    out = dict(data)
    try:
        version = int(out.get("version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version >= RESULT_VERSION:
        return out
    tables = out.get("tables")
    if isinstance(tables, dict):
        out["tables"] = {t: [{RENAMED.get(k, k): v for k, v in row.items()} if isinstance(row, dict) else row
                             for row in rows] if isinstance(rows, list) else rows
                         for t, rows in tables.items()}
    return out


def translate_columns(columns: Iterable[str]) -> list:
    """Current names for German column headers (e.g. of ``Korrekturen.csv`` or ``Messregister.csv``)."""
    return [translate_key(str(c).strip()) for c in columns]
