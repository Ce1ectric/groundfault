# -*- coding: utf-8 -*-
"""Output language for tables, hints, figure labels and exported files (English or German).

All code works with English names internally: table columns such as ``U_E_fault_V`` or ``parallel_check`` and
codes such as ``"satisfied"``. Only the output is translated:

* hints and warnings are rendered from message catalogs ([`tr`][groundfault.i18n.tr]) in the active language,
* [`localize`][groundfault.i18n.localize] renames table columns and code values for display and export,
* [`format_number`][groundfault.i18n.format_number] writes numbers with a decimal point (``en``) or decimal comma
  (``de``).

The language is chosen with [`set_language`][groundfault.i18n.set_language] (or temporarily with
[`language`][groundfault.i18n.language]), or with the environment variable ``GROUNDFAULT_LANGUAGE``. The default is
English.

Examples
--------
>>> from groundfault import i18n
>>> i18n.set_language("de")
>>> i18n.column_label("U_E_fault_V")
'U_E_fehlerbedingt_V'
>>> i18n.format_number(0.0373, digits=3)
'0,0373'
>>> i18n.set_language("en")
"""
from __future__ import annotations

import contextlib
import math
import os
import re
import string
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional

__all__ = ["SUPPORTED_LANGUAGES", "DEFAULT_LANGUAGE", "set_language", "get_language", "language", "register",
           "tr", "has_message", "message_key", "missing_keys", "format_number", "format_text", "column_label",
           "value_label", "localize", "normalize_language", "COLUMNS_DE", "VALUES_DE"]

SUPPORTED_LANGUAGES = ("en", "de")
"""Codes of the output languages: English and German."""
DEFAULT_LANGUAGE = "en"
"""Output language unless [`set_language`][groundfault.i18n.set_language] or the environment variable
``GROUNDFAULT_LANGUAGE`` chooses another one."""


def normalize_language(lang: Optional[str]) -> str:
    """Language code ``"en"`` or ``"de"`` of a language name.

    ``"de"``, ``"DE"``, ``"de_DE"``, ``"de-AT"``, ``"german"`` → ``"de"`` (likewise ``"en"``, ``"en_GB"``,
    ``"english"`` → ``"en"``); ``None`` or an empty string → the active language.

    Raises
    ------
    ValueError
        For any other (unsupported) language name.
    """
    if not lang:
        return get_language()
    code = _language_code(lang)
    if code is None:
        raise ValueError(tr("i18n.unsupported_language", language=lang, supported=", ".join(SUPPORTED_LANGUAGES)))
    return code


def _language_code(lang: Any) -> Optional[str]:
    """``"de"``/``"en"`` for a German or English language name, otherwise None."""
    s = str(lang).strip().lower().replace("-", "_")
    if s.startswith(("de", "ger")):
        return "de"
    if s.startswith(("en", "eng")):
        return "en"
    return None


# an unsupported value of GROUNDFAULT_LANGUAGE falls back to the default language
_language = _language_code(os.environ.get("GROUNDFAULT_LANGUAGE") or DEFAULT_LANGUAGE) or DEFAULT_LANGUAGE


def set_language(lang: str) -> None:
    """Set the output language (``"en"`` or ``"de"``) for everything that follows."""
    global _language
    _language = normalize_language(lang)


def get_language() -> str:
    """Active output language (``"en"`` or ``"de"``)."""
    return _language


@contextlib.contextmanager
def language(lang: str) -> Iterator[str]:
    """Temporarily switch the output language::

        with i18n.language("de"):
            report.export_tables(tables, folder)
    """
    global _language
    old = _language
    _language = normalize_language(lang)
    try:
        yield _language
    finally:
        _language = old


# ---------------------------------------------------------------------------------------------- messages
_MESSAGES: Dict[str, Dict[str, str]] = {}


def register(messages: Mapping[str, Mapping[str, str]]) -> None:
    """Add message templates ``{key: {"en": ..., "de": ...}}`` (called by the modules at import)."""
    for key, texts in messages.items():
        if key in _MESSAGES and _MESSAGES[key] != dict(texts):
            raise KeyError("message key %r registered twice with different texts" % key)
        _MESSAGES[key] = dict(texts)


def has_message(key: str) -> bool:
    """True if a message with this key is registered (see [`register`][groundfault.i18n.register])."""
    return key in _MESSAGES


register({
    "i18n.unsupported_language": {
        "en": "unsupported language {language!r} (supported: {supported})",
        "de": "nicht unterstützte Sprache {language!r} (unterstützt: {supported})"},
})


def _template_parts(template: str):
    """Literal text and placeholders of a template: list of (literal, has_placeholder) (``{{``/``}}`` unescaped)."""
    return [(literal, field is not None) for literal, field, _, _ in string.Formatter().parse(template)]


def message_key(text: Any, keys: Iterable[str]) -> Optional[str]:
    """Key among ``keys`` whose message ``text`` was rendered from – in any supported language.

    A text is recognised by the literal start of the template, i.e. the text before its first placeholder
    (``"Station: uncertain values – "`` for ``"Station: uncertain values – {parts}. …"``), in English or German.
    The rest of the text is not compared, so hints written in either output language – also by earlier versions
    with a different wording after the first placeholder – are recognised. A template that starts with a
    placeholder has to match as a whole (every placeholder matches any text).

    Parameters
    ----------
    text : str
        Rendered message, e.g. a hint of an evaluation result (other objects give None).
    keys : iterable of str
        Candidate message keys (keys without a registered message are skipped).

    Returns
    -------
    str or None
        The first matching key of ``keys``, or None.
    """
    if not isinstance(text, str):
        return None
    for key in keys:
        for lang in SUPPORTED_LANGUAGES:
            template = _MESSAGES.get(key, {}).get(lang)
            if not template:
                continue
            parts = _template_parts(template)
            head = parts[0][0] if parts else ""
            if head.strip():
                if text.startswith(head):
                    return key
            elif re.fullmatch("".join(re.escape(lit) + (".*?" if field else "") for lit, field in parts), text,
                              re.S):
                return key
    return None


def missing_keys(lang: str) -> list:
    """Message keys without a text in ``lang`` (used by the test suite)."""
    lang = normalize_language(lang)
    return sorted(k for k, v in _MESSAGES.items() if not v.get(lang))


#: German number style: decimal comma and a full stop as thousands separator (``{n:,.1f}`` → ``60.000,0``)
_SWAP_SEPARATORS = str.maketrans(",.", ".,")


class _Formatter(string.Formatter):
    """``str.format`` with numbers in the style of the language (decimal comma, thousands point for German)."""

    def __init__(self, lang: str):
        super().__init__()
        self.lang = lang

    def format_field(self, value: Any, format_spec: str) -> str:
        if isinstance(value, bool) or not isinstance(value, (int, float)) and not _is_numpy_number(value):
            return super().format_field(value, format_spec)
        s = format(value, format_spec)
        return s.translate(_SWAP_SEPARATORS) if self.lang == "de" else s


def _is_numpy_number(x: Any) -> bool:
    return type(x).__module__ == "numpy" and hasattr(x, "dtype") and x.dtype.kind in "iuf"


def tr(key: str, lang: Optional[str] = None, **values: Any) -> str:
    """Message ``key`` in the active (or given) language, filled with ``values``.

    Numbers in the template (``{iw:.1f}``) follow the language: ``1.5`` in English, ``1,5`` in German. A missing
    translation falls back to English.
    """
    lang = normalize_language(lang)
    texts = _MESSAGES[key]
    template = texts.get(lang) or texts["en"]
    return _Formatter(lang).format(template, **values)


def format_text(template: str, *args: Any, lang: Optional[str] = None, **values: Any) -> str:
    """``str.format`` with numbers in the style of the active (or given) language – for texts that are not message
    catalog entries (e.g. printed in a notebook).

    Examples
    --------
    >>> format_text("I = {:.2f} A ({n:,} samples)", 1234.5, n=60000, lang="de")
    'I = 1234,50 A (60.000 samples)'
    """
    return _Formatter(normalize_language(lang)).format(template, *args, **values)


def format_number(x: Any, digits: int = 4, mode: str = "significant", lang: Optional[str] = None) -> str:
    """Number as text: ``digits`` significant digits (``mode="significant"``) or decimals (``mode="decimals"``);
    decimal comma in German. NaN and None → ``"–"``."""
    lang = normalize_language(lang)
    if x is None:
        return "–"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    if not math.isfinite(v):
        return "–"
    s = ("%%.%dg" % digits) % v if mode == "significant" else ("%%.%df" % digits) % v
    return s.replace(".", ",") if lang == "de" else s


# ---------------------------------------------------------------------------------------------- tables
COLUMNS_DE: Dict[str, str] = {'F_UE_to_UT': 'F_UE_zu_UT',
 'F_direct': 'F_direkt',
 'F_fault': 'F_fehlerbedingt',
 'H1_angle_deg': 'H1_Winkel_deg',
 'H1_angle_ref_ULL_deg': 'H1_Winkel_bez_ULL_deg',
 'IF_A': 'IF_A',
 'IG': 'IG',
 'IH_scaled': 'IH_skaliert',
 'IH_total': 'IH_ges',
 'IRES_assessed': 'IRES_bewertung',
 'IRES_scaled': 'IRES_skaliert',
 'IRES_sources_A': 'IRES_Ersatzquellen_A',
 'IRES_without_lf': 'IRES_ohne_nf',
 'IRMS_forecast': 'IRMS_prognose',
 'I_F_coverage_pct': 'Abdeckung_I_F_proz',
 'I_F_eff_A': 'I_F_eff_A',
 'I_H_permissible_A': 'I_H_zulaessig_A',
 'I_LV': 'I_ON',
 'I_LV_%s_A': 'I_ON_%s_A',
 'I_LV_A': 'I_ON_A',
 'I_LV_busbar_A': 'I_ON_n_A',
 'I_LV_eff_A': 'I_ON_eff_A',
 'I_LV_feeders_A': 'I_ON_v_A',
 'I_LV_to_I_E': 'I_ON_zu_I_E',
 'I_LV_to_I_E_eff': 'I_ON_zu_I_E_eff',
 'I_LV_uncertainty_pct': 'I_ON_Unsicherheit_proz',
 'I_S_A': 'I_S_A',
 'I_background_A': 'I_Grundlast_A',
 'I_during_fault_A': 'I_Fehler_A',
 'I_fault_A': 'I_fehlerbedingt_A',
 'I_limit_A': 'I_Grenz_A',
 'I_lower': 'I_unten',
 'I_neg_A': 'I_Gegen_A',
 'I_pos_A': 'I_Mit_A',
 'I_resonance': 'I_resonanz',
 'I_resonance_fit': 'I_resonanz_fit',
 'I_upper': 'I_oben',
 'I_zero_A': 'I_Null_A',
 'I_zero_fault_A': 'I_Null_fehler_A',
 'Inst': 'Inst',
 'Iv_A': 'Iv_A',
 'Iw_A': 'Iw_A',
 'Iw_fit': 'Iw_fit',
 'P_additional_impedance_kW': 'P_Zusatzimpedanz_kW',
 'R_E_effective_Ohm': 'R_E_wirksam_Ohm',
 'R_LV': 'R_ON',
 'R_limit_Ohm': 'R_Grenz_Ohm',
 'Rq_P5': 'Rq_P5',
 'THD_pct': 'THD_proz',
 'UE_at_%gA_V': 'UE_bei_%gA_V',
 'UE_max_V': 'UE_max_V',
 'UE_per_A_direct': 'UE_je_A_Erdschluss_direkt',
 'UE_per_A_fault': 'UE_je_A_Erdschluss_fehlerbedingt',
 'UE_per_A_fault_eff': 'UE_je_A_Erdschluss_eff',
 'UE_per_A_injection': 'UE_je_A_Erdungsmessung',
 'UE_per_A_injection_eff': 'UE_je_A_Erdungsmessung_eff',
 'UH5g_pre': 'UH5g_vor',
 'UH7m_pre': 'UH7m_vor',
 'UH_LL_pre_V': 'UH_LL_vor_V',
 'UTHD%s_pct': 'UTHD%s_proz',
 'UTHD12_pct': 'UTHD12_proz',
 'UTHD23_pct': 'UTHD23_proz',
 'UTHD31_pct': 'UTHD31_proz',
 'UTHD_LL_pre_pct': 'UTHD_LL_vor_proz',
 'UTHD_meas': 'UTHD_mess',
 'UT_at_%gA_V': 'UT_bei_%gA_V',
 'U_': 'U_',
 'U_E_fault_V': 'U_E_fehlerbedingt_V',
 'U_E_fault_eff_V': 'U_E_fehlerbedingt_eff_V',
 'U_background_V': 'U_Grundlast_V',
 'U_background_plus_fault_V': 'U_Grundlast_plus_Fehler_V',
 'U_during_fault_V': 'U_Fehler_V',
 'U_fault_V': 'U_fehlerbedingt_V',
 'U_max_fit': 'U_max_fit',
 'U_neg': 'U_Gegen',
 'U_pos': 'U_Mit',
 'U_pos_H1_V': 'U_Mit_H1_V',
 'U_post_V': 'U_nach_V',
 'U_pre_V': 'U_vor_V',
 'U_pre_ll': 'U_vor_ll',
 'U_proportional_V': 'U_proportional_V',
 'U_target': 'U_ziel',
 'U_zero': 'U_Null',
 'Uq_%s_V': 'Uq_%s_V',
 'Uq_angle_deg': 'Uq_Winkel_deg',
 'Uq_angle_ref_faulted_phase_deg': 'Uq_Winkel_bez_Fehlerleiter_deg',
 'Uq_ref_faulted_phase': 'Uq_bez_Fehlerleiter',
 'Uzero_H1_V': 'UNull_H1_V',
 'V_per_100A': 'V_pro_100A',
 'V_per_100A_RMS': 'V_pro_100A_RMS',
 'V_per_100A_direct': 'V_je_100A_direkt',
 'V_per_100A_fault': 'V_je_100A_fehlerbedingt',
 'X_LV1': 'X_ON1',
 'ZE_probe': 'ZE_sonde',
 'Z_%s_Ohm': 'Z_%s_Ohm',
 'Z_%s_angle_deg': 'Z_%s_Winkel_deg',
 'Z_E_LV_Ohm': 'Z_E_Ortsnetz_Ohm',
 'Z_E_LV_angle_deg': 'Z_E_Ortsnetz_Winkel_deg',
 'Z_E_LV_eff_Ohm': 'Z_E_Ortsnetz_eff_Ohm',
 'Z_E_LV_uncertainty_pct': 'Z_E_Ortsnetz_Unsicherheit_proz',
 'Z_E_Ohm': 'Z_E_Ohm',
 'Z_E_injection_Ohm': 'Z_E_Erdungsmessung_Ohm',
 'Z_E_injection_eff_Ohm': 'Z_E_Erdungsmessung_eff_Ohm',
 'Z_LV': 'Z_ON',
 'Z_LV_probe': 'Z_ON_sonde',
 'Z_LV_to_Z_E': 'Z_Ortsnetz_zu_Z_E',
 'Z_LV_to_Z_E_eff': 'Z_Ortsnetz_zu_Z_E_eff',
 'Z_clearance_Ohm': 'Z_ende_Ohm',
 'Z_direct_Ohm': 'Z_direkt_Ohm',
 'Z_direct_angle_deg': 'Z_direkt_Winkel_deg',
 'Z_fault': 'Z_fehler',
 'Z_fault_Ohm': 'Z_fehlerbedingt_Ohm',
 'Z_fault_angle_deg': 'Z_fehlerbedingt_Winkel_deg',
 'Z_inception_Ohm': 'Z_eintritt_Ohm',
 'Z_injection_Ohm': 'Z_Erdungsmessung_Ohm',
 'Z_max_Ohm': 'Z_max_Ohm',
 'Z_min_Ohm': 'Z_min_Ohm',
 'Z_total_fault_Ohm': 'Z_gesamt_Erdschluss_Ohm',
 'Z_total_fault_eff_Ohm': 'Z_gesamt_Erdschluss_eff_Ohm',
 'Z_voltage_Ohm': 'Z_spannung_Ohm',
 'Zq_%s': 'Zq_%s',
 '_corrections_applied': '_korrekturen_angewendet',
 'additional_resistance_Ohm': 'Zusatzwiderstand_Ohm',
 'alignment': 'ausrichtung',
 'all_ids': 'alle_ids',
 'angle_deg': 'Winkel_deg',
 'angle_deg_ref_ULL': 'winkel_deg_bez_ULL',
 'angle_ref_ULL_deg': 'Winkel_bez_ULL_deg',
 'angle_to_IF_H%d_deg': 'Winkel_zu_IF_H%d_deg',
 'assessment': 'Bewertung',
 'assessment_quantities': 'bewertungsgroessen',
 'asset_type': 'Anlagentyp',
 'background_forecast_error_pct': 'Grundlast_Vorhersagefehler_proz',
 'background_to_fault': 'Grundlast_zu_fehlerbedingt',
 'backup': 'sicherung',
 'base_unit': 'Basiseinheit',
 'campaign': 'Kampagne',
 'cfg_file': 'cfg_datei',
 'cfg_path': 'cfg_pfad',
 'channel': 'Kanal',
 'channels': 'Kanaele',
 'check': 'Pruefung',
 'check_uncertainty_pct': 'Pruefung_Unsicherheit_proz',
 'clearance': 'ende',
 'coil_balance_slope': 'spulenbilanz_steigung',
 'coil_currents': 'spulenstroeme',
 'coils_H1_A': 'spulen_H1_A',
 'comment': 'Kommentar',
 'condition_number': 'Konditionszahl',
 'consistency': 'konsistenz',
 'coordinates': 'koordinaten',
 'corrections': 'korrekturen',
 'count': 'Anzahl',
 'crest_factor': 'Scheitelfaktor',
 'date': 'Datum',
 'dc': 'Gleichanteil',
 'description': 'Beschreibung',
 'designation': 'Bezeichnung',
 'deviation_P95_pct': 'Abweichung_P95_proz',
 'deviation_hz': 'abweichung_hz',
 'deviation_incl_dc_pct': 'Abweichung_inkl_DC_proz',
 'deviation_median_pct': 'Abweichung_Median_proz',
 'deviation_pct': 'Abweichung_proz',
 'direct': 'direkt',
 'distance_fault_m': 'Abstand_Erdschluss_m',
 'distance_injection_m': 'Abstand_Erdungsmessung_m',
 'distance_m': 'Abstand_m',
 'distance_match': 'Abstandsvergleich',
 'distance_to_substation_m': 'Entfernung_UW_m',
 'drift_in_measurement_pct': 'Drift_in_Messung_proz',
 'dt_s': 'dt_s',
 'duration': 'Dauer',
 'duration_s': 'Dauer_s',
 'earthing_comparison': 'erdung_vergleich',
 'epr_': 'erdungsspannungen_',
 'equation': 'Gleichung',
 'equivalent_sources': 'ersatzquellen',
 'event_s': 'Ereignis_s',
 'event_times': 'ereigniszeiten',
 'excerpts': 'ausschnitte',
 'existing_id': 'vorhanden_id',
 'f1_hz': 'f1_hz',
 'f1_used': 'f1_verwendet',
 'f_background_hz': 'f_grundlast_hz',
 'f_background_source': 'f_grundlast_quelle',
 'f_fault_hz': 'f_fehler_hz',
 'f_fault_source': 'f_fehler_quelle',
 'factor': 'Faktor',
 'factor_feeders': 'faktor_v',
 'factor_total': 'Faktor_gesamt',
 'factors': 'faktoren',
 'fault': 'fehlerbedingt',
 'fault_location': 'Fehlerort',
 'fault_resistance_Ohm': 'Fehlerwiderstand_Ohm',
 'fault_resistance_ohm': 'fehlerwiderstand_ohm',
 'fault_times': 'fehlerzeiten',
 'faulted_phase': 'Fehlerleiter',
 'file': 'Datei',
 'file_': 'datei_',
 'forecast_error': 'vorhersagefehler',
 'format': 'Format',
 'frequencies_Hz': 'Frequenzen_Hz',
 'frequency': 'Frequenz',
 'frequency_uncertainty_pct': 'Unsicherheit_Frequenz_proz',
 'fs_cfg': 'fs_cfg',
 'fs_source': 'fs_herkunft',
 'fs_timestamps': 'fs_zeitstempel',
 'fundamental_hz': 'grundfrequenz_hz',
 'harmonics': 'harmonische',
 'hints': 'hinweise',
 'inception': 'eintritt',
 'index': 'Index',
 'injection': 'injektion',
 'injection_angle_deg': 'Winkel_Erdungsmessung_deg',
 'injection_frequency': 'Erdungsmessung_Frequenz',
 'injection_id': 'Erdungsmessung_id',
 'injections': 'injektionen',
 'input_impedance_Ohm': 'Eingangsimpedanz_Ohm',
 'instantaneous': 'momentanwerte',
 'intervals': 'bereiche',
 'ires_low_frequency_A': 'ires_niederfrequent_A',
 'irregular_pct': 'unregelmaessig_proz',
 'item_id': 'Wert_id',
 'jumps': 'spruenge',
 'k_LV': 'k_ON',
 'kcl_deviation_pct': 'Knotenregel_Abweichung_proz',
 'kind': 'Art',
 'l_limit_km': 'l_Grenz_km',
 'last': 'letzte',
 'latitude': 'Breite',
 'level_complex': 'Pegel_komplex',
 'level_reference_V': 'Pegel_Bezug_V',
 'line': 'Zeile',
 'load_busbar': 'last_n',
 'load_feeders': 'last_v',
 'load_fluctuation': 'last_schwankung',
 'location': 'Ort',
 'location_groundmeas': 'Ort_groundmeas',
 'location_id': 'Ort_id',
 'location_new': 'ort_neu',
 'longitude': 'Laenge',
 'lv_network': 'ortsnetz',
 'magnitude': 'Betrag',
 'main_channel': 'Hauptkanal',
 'main_channel_%s': 'hauptkanal_%s',
 'main_channel_i_res': 'hauptkanal_i_res',
 'max': 'Max',
 'mean': 'Mittel',
 'mean_device': 'Mittel_Geraet',
 'mean_own': 'Mittel_eigen',
 'meaning': 'Bedeutung',
 'measured_value': 'Messwert',
 'measurement': 'Messung',
 'measurement_id': 'Messung_id',
 'measurement_kind': 'Messart',
 'measurement_no': 'Messung_Nr',
 'measurements': 'Messungen',
 'meta': 'meta',
 'method': 'Methode',
 'method_spread_pct': 'Streuung_Verfahren_proz',
 'methods': 'Methoden',
 'metrics': 'kennwerte',
 'min': 'Min',
 'monte_carlo': 'monte_carlo',
 'name': 'name',
 'no': 'Nr',
 'normalization': 'Normierung',
 'note': 'Hinweis',
 'notes': 'Hinweise',
 'null_test': 'nulltest',
 'numbers_ok': 'nummern_ok',
 'operator': 'Betreiber',
 'order': 'Ordnung',
 'orders': 'Ordnungen',
 'overview': 'uebersicht',
 'own_id': 'eigen_id',
 'pair': 'Paar',
 'parallel_check': 'Pruefung_Parallelschaltung',
 'path': 'Pfad',
 'peak': 'Scheitelwert',
 'peak_rms': 'Spitze_RMS',
 'pen': 'pen',
 'phase': 'Phase',
 'plaus_harmonic_all': 'plaus_harmonische_alle',
 'plaus_harmonic_selection': 'plaus_harmonische_auswahl',
 'plausibility': 'plausibilitaet',
 'polarity': 'Polaritaet',
 'polarity_i_res': 'polaritaet_i_res',
 'polarity_margin_deg': 'polaritaet_reserve_deg',
 'position': 'Lage',
 'post_fault': 'nachfehler',
 'post_fault_s': 'Nachfehler_s',
 'pre_fault': 'vorfehler',
 'pre_fault_s': 'Vorfehler_s',
 'quantities': 'groessen',
 'quantity': 'Groesse',
 'rZE_V_per_100A': 'rZE_V_je_100A',
 'rZE_probe': 'rZE_sonde',
 'r_H%d_complex': 'r_H%d_komplex',
 'r_H%d_magnitude': 'r_H%d_betrag',
 'r_H1_complex': 'r_H1_komplex',
 'r_complex': 'r_komplex',
 'r_direct': 'r_direkt',
 'r_eff_direct': 'r_eff_direkt',
 'r_eff_rms': 'r_eff_Effektivwerte',
 'r_eff_shield': 'r_eff_Schirmstrom',
 'r_magnitude': 'r_betrag',
 'r_shield': 'r_Schirmstrom',
 'range': 'Messbereich',
 'rated_value': 'Nennwert',
 'ratio_%s': 'Verhaeltnis_%s',
 'ratio_direct': 'Verhaeltnis_direkt',
 'ratio_fault': 'Verhaeltnis_fehlerbedingt',
 'reason': 'grund',
 'reasons': 'gruende',
 'recording_info': 'rec_info',
 'reduction_factor': 'reduktionsfaktor',
 'reference': 'bezug',
 'reference_current_A': 'Bezugsstrom_A',
 'remark': 'Bemerkung',
 'renewed': 'erneuert',
 'residual_pct': 'Residuum_proz',
 'resistive_approach': 'resistiver_ansatz',
 'result_set': 'ergebnis_set',
 'rms': 'Effektivwert',
 'rms_ac': 'RMS_ac',
 'rms_trend': 'effektivwertverlauf',
 'role': 'Rolle',
 'roles': 'rollen',
 'roles_': 'rollen_',
 'samples': 'abtastwerte',
 'saturation': 'Sättigung',
 'saturation_pct': 'Saettigung_proz',
 'sequence': 'Sequenz',
 'settings': 'einstellungen',
 'settled_from': 'eingeschwungen_ab',
 'share_%s': 'Anteil_%s',
 'share_%s_angle_deg': 'Anteil_%s_Winkel_deg',
 'share_H%d': 'Anteil_H%d',
 'share_H1_pct': 'Anteil_H1_proz',
 'share_I_LV': 'Anteil_I_ON',
 'share_I_LV_eff': 'Anteil_I_ON_eff',
 'share_fault': 'Anteil_fehlerbedingt',
 'share_fault_angle_deg': 'Anteil_fehlerbedingt_Winkel_deg',
 'shield': 'schirm',
 'shield_current_': 'schirmstrom_',
 'short': 'Kurz',
 'sign': 'vorzeichen',
 'sign_busbar': 'vorzeichen_n',
 'signals': 'signale',
 'similarity': 'Aehnlichkeit',
 'site': 'Messort',
 'source': 'Quelle',
 'span_background_hz': 'spanne_grund_hz',
 'span_hz': 'spanne_hz',
 'span_pct': 'Spanne_proz',
 'spectrum': 'spektrum',
 'spectrum_fault_current': 'spektrum_fehlerstrom',
 'spellings': 'schreibweisen',
 'split_50hz': 'aufteilung_50hz',
 'spread_hz': 'streuung_hz',
 'start_cfg': 'Start_cfg',
 'station': 'station',
 'station_background': 'station_grundlast',
 'station_currents': 'station_stroeme',
 'station_currents_frequency': 'station_stroeme_frequenz',
 'station_extrapolation': 'station_hochrechnung',
 'station_frequency': 'station_frequenz',
 'station_lv_network': 'station_ortsnetz',
 'station_lv_network_eff': 'station_ortsnetz_eff',
 'station_metrics': 'station_kennwerte',
 'station_voltages': 'station_spannungen',
 'statistics': 'statistik',
 'status': 'Status',
 'steady_state': 'stationaer',
 'steady_state_s': 'Stationaer_s',
 't_background_s': 't_grundlast_s',
 't_fault_clearance_s': 't_fehlerende_s',
 't_fault_inception_s': 't_fehlereintritt_s',
 't_fault_s': 't_fehler_s',
 't_max_window_s': 't_max_fenster_s',
 'tables': 'tabellen',
 'time': 'Zeit',
 'time_UTC': 'Zeit_UTC',
 'timestamp': 'Zeitpunkt',
 'timestamps': 'zeitstempel',
 'total_earthing_reference': 'Bezug_Gesamterdung',
 'transformer_power': 'trafo_leistung',
 'trigger_s': 'Trigger_s',
 'truth': 'wahr',
 'type': 'Typ',
 'uncertain': 'unsicher',
 'uncertain_share_pct': 'Anteil_unsicher_proz',
 'uncertainty_pct': 'Unsicherheit_proz',
 'unit': 'Einheit',
 'unit_note': 'Einheit_Hinweis',
 'unit_stored': 'Einheit_gespeichert',
 'value': 'Wert',
 'value_max_window': 'Wert_Max_Fenster',
 'value_range': 'Wertebereich',
 'values': 'Werte',
 'voltage': 'spannung',
 'voltage_': 'spannung_',
 'voltage_fault': 'spannung_erdschluss',
 'voltage_level_kV': 'Spannungsebene_kV',
 'voltage_level_kv': 'spannungsebene_kv',
 'voltage_metrics': 'spannung_kennwerte',
 'voltage_negative_sequence': 'spannung_gegensystem',
 'voltage_positive_sequence': 'spannung_mitsystem',
 'voltage_post_fault': 'spannung_nachfehler',
 'voltage_pre_fault': 'spannung_vorfehler',
 'warnings': 'warnungen',
 'weight_%s': 'Gewicht_%s',
 'weight_busbar': 'Gewicht_n',
 'weight_feeders': 'Gewicht_v',
 'with_voltages': 'mit_spannungen',
 'writable': 'schreibbar',
 'written': 'geschrieben',
 'z_fault_ohm': 'z_fehler_ohm'}
"""English column name → German column name (the names of the predecessor tool, used for German output)."""

#: Columns whose names are built from a code: English pattern → German name
_COLUMN_PATTERNS_DE = [
    (re.compile(r"^share_H(\d+)$"), "Anteil_H{0}"),
    (re.compile(r"^share_(direct|inception|clearance|voltage|fault)$"), "Anteil_{c0}"),
    (re.compile(r"^share_(direct|inception|clearance|voltage|fault)_angle_deg$"), "Anteil_{c0}_Winkel_deg"),
    (re.compile(r"^Z_(direct|inception|clearance|voltage|fault)_Ohm$"), "Z_{c0}_Ohm"),
    (re.compile(r"^Z_(direct|inception|clearance|voltage|fault)_angle_deg$"), "Z_{c0}_Winkel_deg"),
    (re.compile(r"^ratio_(direct|fault)$"), "Verhaeltnis_{c0}"),
    (re.compile(r"^weight_(feeders|busbar)$"), "Gewicht_{c0}"),
    (re.compile(r"^I_LV_(feeders|busbar|PEN)_A$"), "I_ON_{c0}_A"),
    (re.compile(r"^(UE|UT)_at_([0-9.]+)A_V$"), "{0}_bei_{1}A_V"),
    (re.compile(r"^angle_to_IF_H(\d+)_deg$"), "Winkel_zu_IF_H{0}_deg"),
    (re.compile(r"^(r?ZE)_H(\d+)_angle_deg$"), "{0}_H{1}_Winkel_deg"),
    (re.compile(r"^r_H(\d+)_magnitude$"), "r_H{0}_betrag"),
    (re.compile(r"^r_H(\d+)_complex$"), "r_H{0}_komplex"),
    (re.compile(r"^main_channel_(\w+)$"), "hauptkanal_{0}"),
]
_CODES_DE = {"direct": "direkt", "inception": "eintritt", "clearance": "ende", "voltage": "spannung",
             "fault": "fehlerbedingt", "feeders": "v", "busbar": "n", "PEN": "PEN"}

VALUES_DE: Dict[str, Dict[str, str]] = {'background_from': {'fault': 'erdschluss',
                     'post_fault': 'nachfehler',
                     'pre_fault': 'vorfehler',
                     'steady_state': 'stationaer'},
 'distance_match': {'different': 'abweichend', 'equal': 'gleich', 'similar': 'ähnlich', 'unknown': 'unbekannt'},
 'f1_method': {'phase': 'phase',
               'regression': 'regression',
               'spectral': 'spektral',
               'zero_crossing': 'nulldurchgang'},
 'interval': {'fault': 'erdschluss',
              'post_fault': 'nachfehler',
              'pre_fault': 'vorfehler',
              'steady_state': 'stationaer'},
 'method': {'clearance': 'ende',
            'direct': 'direkt',
            'fault': 'fehlerbedingt',
            'inception': 'eintritt',
            'voltage': 'spannung'},
 'method_comparison': {'phase': 'phase',
                       'regression': 'regression',
                       'spectral': 'spektral',
                       'zero_crossing': 'nulldurchgang'},
 'parallel_check': {'borderline': 'Grenzfall (innerhalb der Unsicherheit)',
                    'satisfied': 'erfüllt',
                    'violated': 'verletzt'},
 'position': {'busbar': 'n', 'feeders': 'v'},
 'quantity': {'IH_scaled': 'IH_skaliert',
              'IH_total': 'IH_ges',
              'IRES_scaled': 'IRES_skaliert',
              'IRMS_forecast': 'IRMS_prognose'},
 'role': {'i_pen_busbar': 'i_pen_n',
          'i_pen_feeders': 'i_pen_v',
          'i_shield': 'i_schirm',
          'u_hv_l1e': 'u_hs_l1e',
          'u_hv_l2e': 'u_hs_l2e',
          'u_hv_l3e': 'u_hs_l3e'},
 'source': {'fault test': 'Erdschluss',
            'fault test (groundmeas)': 'Erdschluss (groundmeas)',
            'injection test': 'Erdungsmessung'},
 'status': {'CORRECTED': 'KORRIGIERT', 'NOTE': 'HINWEIS', 'WARNING': 'WARNUNG'},
 'thd_reference': {'mean': 'mittel', 'post_fault': 'nachfehler', 'pre_fault': 'vorfehler'},
 'transformer_voltage': {'hv': 'hs', 'mv': 'ms'}}
"""Code values in table cells, per column: English code → German text."""

# probe maximum, checks against the fault test, classification and assessment relevance
COLUMNS_DE.update({
    "probe": "Sonde", "Z_E_fault_Ohm": "Z_E_Erdschluss_Ohm", "Z_E_fault_eff_Ohm": "Z_E_Erdschluss_eff_Ohm",
    "Z_LV_to_Z_E_fault": "Z_Ortsnetz_zu_Z_E_Erdschluss", "earth_current_check": "Pruefung_Erdungsstrom",
    "injection_comparison": "Vergleich_Erdungsmessung", "comparison_uncertainty_pct": "Vergleich_Unsicherheit_proz",
    "share_shield": "Anteil_Schirmstrom", "share_shield_eff": "Anteil_Schirmstrom_eff",
    "UE_per_A_earth_current": "UE_je_A_Erdungsstrom", "UE_per_A_earth_current_eff": "UE_je_A_Erdungsstrom_eff",
    "Z_E_fault_to_injection": "Z_E_Erdschluss_zu_Erdungsmessung",
    "Z_E_fault_to_injection_eff": "Z_E_Erdschluss_zu_Erdungsmessung_eff", "r_to_r_50Hz": "r_zu_r_50Hz",
    "r_50Hz": "r_50Hz", "Z_E_fault_50Hz_Ohm": "Z_E_Erdschluss_50Hz_Ohm",
    "Z_E_injection_50Hz_Ohm": "Z_E_Erdungsmessung_50Hz_Ohm", "classification_r_50Hz": "Einordnung_r_50Hz",
    "trend_r_vs_f": "Verlauf_r_ueber_f", "exponent_r_vs_f": "Exponent_r_ueber_f",
    "exponent_Z_fault": "Exponent_Z_Erdschluss", "exponent_Z_injection": "Exponent_Z_Erdungsmessung",
    "trend_orders": "Verlauf_Ordnungen", "U_E_fault_at_reference_current_V": "U_E_Erdschluss_bei_Bezugsstrom_V",
    "U_E_injection_at_reference_current_V": "U_E_Erdungsmessung_bei_Bezugsstrom_V",
    "deviation_at_reference_current_V": "Abweichung_bei_Bezugsstrom_V", "F_times_U_Tp_V": "F_mal_U_Tp_V",
    "assessment_relevance_pct": "Bewertungsrelevanz_proz", "assessment_relevance": "Bewertungsrelevanz",
})
_CHECK_DE = {"satisfied": "erfüllt", "violated": "verletzt", "borderline": "Grenzfall (innerhalb der Unsicherheit)",
             "violated (see orders)": "verletzt (siehe Ordnungen)"}
VALUES_DE["parallel_check"] = dict(_CHECK_DE)
VALUES_DE["earth_current_check"] = dict(_CHECK_DE)
VALUES_DE["injection_comparison"] = {"satisfied": "erfüllt", "borderline": "Grenzfall (innerhalb der Unsicherheit)",
                                     "below": "unterschritten", "below (see orders)": "unterschritten (siehe Ordnungen)"}
VALUES_DE["distance_match"]["maximum"] = "Maximum"
VALUES_DE["assessment_relevance"] = {"negligible": "vernachlässigbar", "unchanged": "Bewertung unverändert",
                                     "relevant": "bewertungsrelevant"}
VALUES_DE["trend_r_vs_f"] = {"falling": "fallend (erwartet)", "constant": "etwa konstant",
                             "rising": "steigend (unerwartet)"}
VALUES_DE["classification_r_50Hz"] = {"below": "unter dem üblichen Bereich", "typical": "im üblichen Bereich",
                                      "above": "über dem üblichen Bereich", "implausible": "über 1 – nicht plausibel"}
COLUMNS_DE.update({"r_typical_min": "r_typisch_min", "r_typical_max": "r_typisch_max", "U_Tp_V": "U_Tp_V",
                   "F_factor": "Faktor_F"})

# campaign overview, diagnostics and RMS recordings
COLUMNS_DE.update({
    "UH5g pre-fault in V": "UH5g vor in V", "UH7m pre-fault in V": "UH7m vor in V",
    "THD pre-fault (max) in %": "THD vor (max) in %", "Σ coils H1 in A": "Σ Spulen H1 in A",
    "Corrections": "Korrekturen",
    "active_from_s": "aktiv_von_s", "active_to_s": "aktiv_bis_s", "Edges": "Flanken", "first_edge_s": "erste_Flanke_s",
    "interval": "Bereich",
})
VALUES_DE["status"]["UNCERTAIN"] = "UNSICHER"
VALUES_DE["normalization"] = {"complex": "komplex", "magnitude": "betrag", "none": "keine"}
VALUES_DE["polarity"] = {"rotated": "gedreht", "as measured": "wie gemessen"}
VALUES_DE["sequence"] = {"pos": "Mit", "neg": "Gegen", "zero": "Null"}
VALUES_DE["location_id"] = {"new": "neu"}
VALUES_DE["quantity"].update({"earth_potential_rise": "Erdungsspannung", "touch_voltage": "Berührungsspannung"})
VALUES_DE["distance_match"]["touch"] = "Berührung (≤ 1,5 m)"
VALUES_DE["kind"] = {"station": "Station", "substation": "UW", "instantaneous": "Momentanwerte"}
VALUES_DE["measurement_kind"] = {"station": "Station", "substation": "UW", "transformer": "Trafo",
                                 "undetermined": "unbestimmt"}
COLUMNS_DE.update({"measurement_types": "Groessen", "of_which": "davon", "uncertain_Hz": "unsicher_Hz",
                   "assessment_substation": "Bewertung_UW"})
VALUES_DE["assessment_substation"] = {"uncritical": "unkritisch", "countermeasures": "Ersatzmaßnahmen"}
VALUES_DE["role"]["ignore"] = "ignorieren"
VALUES_DE["main_channel"] = {"yes": "ja"}
VALUES_DE["type"] = {"fault": "fehlerbedingt", "direct": "direkt"}
# tables of the equivalent-source method
COLUMNS_DE.update({
    "I_short_circuit_A": "I_kurzschluss_A", "dZq_rel_per_1pct": "dZq_rel_je_1proz", "Rq_fixed": "Rq_fixiert",
    "Zq_equation_error": "Zq_gleichungsfehler", "Uq_equation_error_V": "Uq_gleichungsfehler_V",
    "Zq_output_error": "Zq_ausgangsfehler", "Uq_output_error_V": "Uq_ausgangsfehler_V", "I_measured_A": "I_gemessen_A",
    "I_model_A": "I_modell_A", "I_at_ZE_A": "I_bei_ZE_A", "IRES_measured_A": "IRES_gemessen_A",
    "I_low_frequency_A": "I_niederfrequent_A",
})
VALUES_DE["method"].update({"equation_error": "gleichungsfehler", "output_error": "ausgangsfehler",
                            "rq0": "randlösung R_q = 0"})
VALUES_DE["assessment"] = {"ok": "in Ordnung", "R_q < 0": "R_q < 0 (nicht möglich)"}     # pairwise solutions
VALUES_DE["format"] = {"legacy_notebook": "Altformat (Notebook-Export)",                 # legacy input formats
                       "legacy_complex": "Altformat (komplexer Export)"}
# role table: origin of a role
VALUES_DE["source"].update({"automatic": "automatisch", "override": "vorgabe"})



def column_label(name: str, lang: Optional[str] = None) -> str:
    """Display name of a table column in the given (or active) language."""
    lang = normalize_language(lang)
    if lang == "en" or not isinstance(name, str):
        return name
    if name in COLUMNS_DE:
        return COLUMNS_DE[name]
    for pattern, target in _COLUMN_PATTERNS_DE:
        m = pattern.match(name)
        if m:
            groups = m.groups()
            return target.format(*groups, c0=_CODES_DE.get(groups[0], groups[0]))
    return name


def value_label(column: str, value: Any, lang: Optional[str] = None) -> Any:
    """Display text of a code value (``"satisfied"`` → ``"erfüllt"`` in German)."""
    lang = normalize_language(lang)
    if lang == "en" or not isinstance(value, str):
        return value
    return VALUES_DE.get(column, {}).get(value, value)


def localize(df, lang: Optional[str] = None):
    """Copy of a table with column names and code values in the given (or active) language.

    English output returns the table unchanged (canonical names). Code values are translated in text columns of
    dtype ``object`` and of the pandas string dtype (``str`` in pandas ≥ 3). Works for pandas DataFrames; other
    objects are returned unchanged.
    """
    lang = normalize_language(lang)
    if lang == "en" or not hasattr(df, "columns"):
        return df
    out = df.copy()
    for col in out.columns:
        if col in VALUES_DE and out[col].dtype.kind == "O":       # object or pandas string dtype
            out[col] = [value_label(col, v, lang) for v in out[col]]
    out.columns = [column_label(c, lang) for c in out.columns]
    if getattr(out.index, "name", None):
        out.index.name = column_label(out.index.name, lang)
    return out
