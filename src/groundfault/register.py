# -*- coding: utf-8 -*-
"""Measurement register: overview of all recordings in the working folder (``register.csv``, German layout
``Messregister.csv``) and a read-me file per campaign (``README.md`` / ``LIESMICH.md``).

Folder convention ([`groundfault.layout`][groundfault.layout]; English names, German names in brackets)::

    campaigns/<YYYY-MM-DD>_<place>/notes/notes.txt, corrections.csv, sites.csv
    (01_Messkampagnen)             (0_Notizen/Notizen_Messung.txt, Korrekturen.csv, Messorte.csv)
                                  /raw/<site>/…cfg/.dat                      (1_Rohdaten)
                                  /results/…  figures/…  report/…  media/…   (2_Auswertung, 3_Abbildungen, …)

The register is built from the headers of the .cfg files. Manually maintained columns (``fault_resistance_Ohm``,
``fault_location``, ``remark`` and the evaluation intervals) are kept when the register is rebuilt. The register
of a German-layout working folder keeps its German column names and values (``Kampagne;Datum;…``).
"""
from __future__ import annotations

import datetime as _dt
import glob
import os
import re
import unicodedata
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from . import i18n
from .channels import detect_roles, short_name
from .comtrade import open_recording
from .i18n import tr
from .layout import ENGLISH, GERMAN, CampaignLayout, detect_layout, get_layout

__all__ = ["scan", "write_register", "read_register", "campaign_readme", "record_intervals", "update_all",
           "create_notes_folder", "fault_resistance", "resistance_from_name", "register_path", "REGISTER_COLUMNS",
           "REGISTER_HEADERS_DE", "MANUAL_COLUMNS"]

REGISTER_COLUMNS = ("campaign", "date", "location", "site", "measurement_no", "file", "kind", "measurement_kind",
                    "fault_resistance_Ohm", "fault_location", "fs_Hz", "duration_s", "start_cfg", "trigger_s",
                    "analog_channels", "digital_channels", "channels", "steady_state_s", "pre_fault_s",
                    "post_fault_s", "remark", "status", "path")
"""Columns of the register (English layout)."""
REGISTER_HEADERS_DE = ("Kampagne", "Datum", "Ort", "Messort", "Messung_Nr", "Datei", "Art", "Messart",
                       "Fehlerwiderstand_Ohm", "Fehlerort", "fs_Hz", "Dauer_s", "Start_cfg", "Trigger_s",
                       "Analogkanaele", "Digitalkanaele", "Kanaele", "Stationaer_s", "Vorfehler_s", "Nachfehler_s",
                       "Bemerkung", "Status", "Pfad")
"""The same columns in a German-layout register (names of the predecessor tool)."""
_DE_TO_EN = dict(zip(REGISTER_HEADERS_DE, REGISTER_COLUMNS))
_DE_TO_EN.update({"AnalogChannels": "analog_channels", "DigitalChannels": "digital_channels"})
_EN_TO_DE = dict(zip(REGISTER_COLUMNS, REGISTER_HEADERS_DE))
MANUAL_COLUMNS = ("fault_resistance_Ohm", "fault_location", "remark", "steady_state_s", "pre_fault_s", "post_fault_s")
"""Columns maintained by hand – kept when the register is rebuilt."""
_KIND_DE = {"instantaneous": "Momentanwerte", "RMS": "RMS"}
_MEASUREMENT_KIND_DE = {"station": "Station", "substation": "UW", "transformer": "Trafo", "undetermined": "unbestimmt"}

_NOTES_TEMPLATES = {
    "en": ("Notes on the measurement (free text): set-up, CTs and clamps, switching state, particularities.\n"
           "Corrections that the evaluation shall apply (wrong CT ratio, clamp around only one of several conductors,\n"
           "polarity, channel not to be evaluated) must also be entered in corrections.csv – only those are\n"
           "applied automatically.\n\n"),
    "de": ("Notizen zur Messung (frei): Messaufbau, Wandler und Zangen, Schaltzustand, Besonderheiten.\n"
           "Korrekturen, die in die Auswertung einfließen sollen (falsche Wandlerübersetzung, Zange nur auf\n"
           "einem von mehreren Leitern, Polarität, Kanal nicht auswerten), bitte zusätzlich in Korrekturen.csv\n"
           "eintragen – nur die werden automatisch angewendet.\n\n"),
}

i18n.register({
    "register.error": {"en": "error: {error}", "de": "Fehler: {error}"},
    "register.date_mismatch": {
        "en": "cfg date {cfg} ≠ campaign date {campaign} (recorder clock? file in the right campaign?)",
        "de": "cfg-Datum {cfg} ≠ Kampagnendatum {campaign} (Uhr des Messgeräts? Datei zugeordnet?)"},
    "register.readme_title": {"en": "# Staged earth fault test {place} – {date}",
                              "de": "# Erdschlussmessung {place} – {date}"},
    "register.readme_intro": {
        "en": "Generated automatically (package `groundfault`). Notes go into `{notes}/{notes_file}`, corrections "
              "for the evaluation into `{notes}/{corrections}`, locations and coordinates for groundmeas into "
              "`{notes}/{sites}`, characteristics of the recordings into the columns *{manual}* of `{register}`.",
        "de": "Automatisch erzeugt (Paket `groundfault`). Notizen bitte in `{notes}/{notes_file}`, Korrekturen "
              "für die Auswertung in `{notes}/{corrections}`, Orte und Koordinaten für groundmeas in "
              "`{notes}/{sites}`, Kenndaten der Aufzeichnungen in den Spalten *{manual}* von `{register}`."},
    "register.readme_recordings": {"en": "## Recordings", "de": "## Aufzeichnungen"},
    "register.readme_no_files": {"en": "_no COMTRADE files found_", "de": "_keine COMTRADE-Dateien gefunden_"},
    "register.readme_corrections": {"en": "## Corrections for the evaluation (`{path}`)",
                                    "de": "## Korrekturen für die Auswertung (`{path}`)"},
    "register.readme_corrections_note": {
        "en": "Applied automatically whenever a recording is read and shown in the results.",
        "de": "Werden beim Einlesen automatisch angewendet und in den Ergebnissen ausgewiesen."},
    "register.readme_corrections_short": {"en": "## Corrections", "de": "## Korrekturen"},
    "register.readme_unreadable": {"en": "⚠ `{path}` not readable: {error}", "de": "⚠ `{path}` nicht lesbar: {error}"},
    "register.readme_sites": {"en": "## Measurement sites for groundmeas (`{path}`)",
                              "de": "## Messorte für groundmeas (`{path}`)"},
    "register.readme_sites_short": {"en": "## Measurement sites", "de": "## Messorte"},
    "register.readme_notes": {"en": "## Notes from the test", "de": "## Notizen von der Messung"},
    "register.readme_folders": {"en": "## Folders", "de": "## Ordner"},
    "register.readme_folder_table": {"en": "| Folder | Content |", "de": "| Ordner | Inhalt |"},
    "register.readme_folder_notes": {
        "en": "| `{notes}/` | `{notes_file}` (free text), `{corrections}` (CT factors, polarity, channel roles, probe "
              "distances – applied automatically) and `{sites}` (location, coordinates, asset type for groundmeas) |",
        "de": "| `{notes}/` | `{notes_file}` (frei), `{corrections}` (Wandlerfaktoren, Polarität, Kanalrollen, "
              "Sondenabstände – fließen automatisch in die Auswertung ein) und `{sites}` (Ort, Koordinaten, "
              "Anlagentyp für den Eintrag in groundmeas) |"},
    "register.readme_folder_raw": {
        "en": "| `{raw}/` | COMTRADE (.cfg/.dat) and project files of the recorder, per site |",
        "de": "| `{raw}/` | COMTRADE (.cfg/.dat) und Projektdateien des Messgeräts, je Messort |"},
    "register.readme_folder_results": {"en": "| `{results}/` | results per measurement (JSON, tables) |",
                                       "de": "| `{results}/` | Ergebnisse je Messung (JSON, Tabellen) |"},
    "register.readme_folder_figures": {"en": "| `{figures}/` | figures for the report (PDF/SVG/PNG) |",
                                       "de": "| `{figures}/` | Abbildungen für den Bericht (PDF/SVG/PNG) |"},
    "register.readme_folder_report": {"en": "| `{report}/` | report (Word/PDF) |",
                                      "de": "| `{report}/` | Bericht (Word/PDF) |"},
    "register.readme_folder_media": {"en": "| `{media}/` | audio/video |", "de": "| `{media}/` | Audio/Video |"},
    "register.readme_times": {
        "en": "Times in `{start}` come from the .cfg file (recorders usually write UTC; file names with times are "
              "local time). `{number}` is the chronological order of the fault events.",
        "de": "Zeitangaben `{start}` stammen aus der .cfg (Messgeräte schreiben meist UTC; Dateinamen mit Uhrzeit "
              "sind Ortszeit). `{number}` ist die chronologische Reihenfolge der Fehlerereignisse."},
    "register.moved": {"en": "moved: {old} → {new}", "de": "verschoben: {old} → {new}"},
    "register.duplicate_notes": {
        "en": "⚠ {file} exists twice (campaign folder and {notes}) – please merge",
        "de": "⚠ {file} liegt doppelt (Kampagnenordner und {notes}) – bitte zusammenführen"},
    "register.created": {"en": "created: {path}", "de": "angelegt: {path}"},
    # ---- summary of tools/update_register.py
    "register.summary_register": {"en": "register: {path} – recordings: {count}",
                                  "de": "Messregister: {path} – Aufzeichnungen: {count}"},
    "register.summary_readme": {"en": "read-me files ({file}) written: {count}",
                                "de": "Liesmich-Dateien ({file}) geschrieben: {count}"},
    "register.created_sites": {"en": "created: {path} (for groundmeas – enter coordinates of new locations)",
                               "de": "angelegt: {path} (für groundmeas – Koordinaten neuer Orte eintragen)"},
})


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _posix(path: str) -> str:
    """Relative path with forward slashes in NFC form – the key of a register row (independent of the
    operating system that wrote the register)."""
    return _nfc(str(path).replace("\\", "/"))


def resistance_from_name(filename: str) -> Optional[float]:
    """Fault resistance (additional impedance) in Ω from the name of a recording.

    The sampling-rate part (``_40_000kHz``, ``_10_000Hz`` …) and a trailing ``_Messung``/``_measurement`` are
    ignored; then the number at the end of the name counts:

    * ``<int>.<digits>`` or ``<int>,<digits>`` – a decimal (``SUB_7.5_…`` → 7.5 Ω, ``SUB_12,5_…`` → 12.5 Ω);
    * ``<int>_<digits>`` with an integer part of up to four digits – a decimal as well
      (``SUB_2_5_40_000kHz`` → 2.5 Ω, ``SUB_12_5_…`` → 12.5 Ω);
    * ``<int>`` (up to four digits) – that integer (``SUB_0_…`` → 0 Ω, ``SUB_3_…`` → 3 Ω,
      ``SUB_15_…`` → 15 Ω). The one special case: ``25`` means 2.5 Ω, the shorthand of earlier campaigns
      (``SUB_25_measurement_40_000kHz`` → 2.5 Ω).

    Parameters
    ----------
    filename : str
        File name or path of the recording, with its extension (``.cfg``).

    Returns
    -------
    float or None
        Resistance in Ω, or None if the name ends without such a number (``Station_A_40_000kHz``, time stamps).
    """
    stem = os.path.splitext(os.path.basename(filename))[0]
    stem = re.sub(r"_\d+_\d+k?Hz$", "", stem, flags=re.I)                             # sampling rate
    stem = re.sub(r"_(Messung|measurement)$", "", stem, flags=re.I)
    m = re.search(r"(?:^|_)(\d+)[.,](\d+)$", stem)
    if m:
        return float("%s.%s" % (m.group(1), m.group(2)))
    m = re.search(r"(?:^|_)(\d{1,4})_(\d+)$", stem)
    if m:
        return float("%s.%s" % (m.group(1), m.group(2)))
    m = re.search(r"(?:^|_)(\d{1,4})$", stem)
    if m:
        return 2.5 if m.group(1) == "25" else float(m.group(1))
    return None


def _site(rel: str, lay: CampaignLayout) -> str:
    parts = rel.replace("\\", "/").split("/")
    for raw in dict.fromkeys((lay.raw, ENGLISH.raw, GERMAN.raw)):
        if raw in parts:
            i = parts.index(raw)
            return parts[i + 1] if len(parts) > i + 2 else ""
    return ""


def _cfg_files(folder: str) -> List[str]:
    """Every COMTRADE configuration file below ``folder`` (``.cfg`` in any letter case), each exactly once and sorted.

    One pass over the directory tree instead of one search per letter case: on a case-insensitive file system
    (Windows) a search for ``*.CFG`` also finds ``x.cfg``, so two searches listed every recording twice. Hidden files
    and folders (names starting with ``.``, e.g. ``._x.cfg`` written by macOS on foreign volumes) are skipped, as
    before.
    """
    found = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        found += [os.path.join(dirpath, f) for f in filenames if f.lower().endswith(".cfg") and not f.startswith(".")]
    return sorted(found)


def _campaign_folders(base: str, lay: CampaignLayout) -> List[str]:
    return [kd for kd in sorted(glob.glob(os.path.join(base, lay.campaigns, "*"))) if os.path.isdir(kd)]


def scan(base: str, with_roles: bool = True, presets: Optional[Mapping[str, Mapping[str, object]]] = None,
         layout: Union[str, CampaignLayout, None] = None, campaigns: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """Search the campaign folders below ``base`` for .cfg files and read their headers.

    Parameters
    ----------
    base : str
        Working folder that contains the campaigns folder (``campaigns`` or ``01_Messkampagnen``).
    with_roles : bool
        Detect the channel roles to classify each recording (``measurement_kind``).
    presets : mapping, optional
        ``{file name: {column: value}}`` – values for recordings whose file names carry no information (e.g.
        time-stamp names), such as ``fault_resistance_Ohm``, ``fault_location`` or ``remark``.
    layout : str or CampaignLayout, optional
        Folder layout; detected from ``base`` if omitted.
    campaigns : sequence of str, optional
        Names of the campaign folders to scan (default: all campaigns of the work folder).

    Returns
    -------
    pandas.DataFrame
        One row per .cfg file with the columns [`REGISTER_COLUMNS`][groundfault.register.REGISTER_COLUMNS] (English
        names and codes).
    """
    lay = get_layout(layout) if layout is not None else detect_layout(base)
    rows = []
    for kd in _campaign_folders(base, lay):
        if campaigns is not None and os.path.basename(kd) not in campaigns:
            continue
        campaign = _nfc(os.path.basename(kd))
        m = re.match(r"(\d{4}-\d{2}-\d{2})_(.+)", campaign)
        date, location = (m.group(1), m.group(2)) if m else ("", campaign)
        raw = os.path.join(kd, lay.raw)
        for cfg in _cfg_files(raw):
            rel = _posix(os.path.relpath(cfg, base))          # same key on every operating system
            name = os.path.basename(cfg)
            z = dict(campaign=campaign, date=date, location=location, site=_site(os.path.relpath(cfg, kd), lay),
                     file=name, path=rel)
            try:
                rec = open_recording(cfg, emit_warnings=False)
            except Exception as e:  # broken or incomplete file
                z.update(status=tr("register.error", error=e))
                rows.append(z)
                continue
            with rec:
                rms = any(n.strip().upper().endswith(" RMS") for n in rec.channel_names) or rec.fs < 1000
                z.update(kind="RMS" if rms else "instantaneous", fs_Hz=rec.fs, duration_s=round(rec.duration_s, 3),
                         start_cfg=rec.t_start.isoformat(sep=" ") if rec.t_start else "",
                         trigger_s=round(rec.trigger_s, 3) if rec.trigger_s is not None else np.nan,
                         analog_channels=len(rec.analog), digital_channels=len(rec.digital),
                         channels=", ".join(short_name(n)[0] for n in rec.channel_names),
                         status="ok" if not rec.warnings else "; ".join(rec.warnings))
                # date check: cfg time (UTC) against the campaign date (±1 day because of UTC/local time)
                if date and rec.t_start:
                    try:
                        d_k = _dt.date.fromisoformat(date)
                        d_c = rec.t_start.date()
                        if abs((d_c - d_k).days) > 1:
                            h = tr("register.date_mismatch", cfg=d_c.isoformat(), campaign=date)
                            z["status"] = h if z["status"] == "ok" else z["status"] + "; " + h
                    except ValueError:
                        pass
                if with_roles and rec.analog:
                    r = detect_roles(rec.channel_names, rec.units)
                    z["measurement_kind"] = r.measurement_kind()
                else:
                    z["measurement_kind"] = "–"
            z["fault_resistance_Ohm"] = resistance_from_name(name)
            z["fault_location"] = ""
            z["remark"] = ""
            for k, v in (presets or {}).get(name, {}).items():
                z[k] = v
            rows.append(z)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # measurement number per campaign: chronological order of the fault events (without RMS files)
    df["measurement_no"] = np.nan
    for _, g in df.groupby("campaign"):
        h = g[(g.get("kind") == "instantaneous")
              & ~g["site"].str.contains("Trafo|transformer", case=False, na=False)]
        h = h.sort_values("start_cfg")
        for number, idx in enumerate(h.index, start=1):
            df.loc[idx, "measurement_no"] = number
    return df


def register_path(base: str, layout: Union[str, CampaignLayout, None] = None) -> str:
    """Path of the register of a working folder (``register.csv`` or ``Messregister.csv``); an existing
    register of either layout is preferred."""
    lay = get_layout(layout) if layout is not None else detect_layout(base)
    for cand in (lay, ENGLISH, GERMAN):
        p = os.path.join(base, cand.register_file)
        if os.path.exists(p):
            return p
    return os.path.join(base, lay.register_file)


def read_register(path: str) -> Tuple[pd.DataFrame, str]:
    """Read a register (English or German headers) → (table with English column names and codes, language
    of the file)."""
    df = pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False)
    lang = "de" if any(c in _DE_TO_EN for c in df.columns) and "path" not in df.columns else "en"
    df = df.rename(columns=_DE_TO_EN)
    if lang == "de":
        inv_kind = {v: k for k, v in _KIND_DE.items()}
        if "kind" in df.columns:
            df["kind"] = [inv_kind.get(v, v) for v in df["kind"]]
        if "measurement_kind" in df.columns:
            inv = {v: k for k, v in _MEASUREMENT_KIND_DE.items()}
            df["measurement_kind"] = ["+".join(inv.get(p, p) for p in str(v).split("+")) for v in df["measurement_kind"]]
    return df, lang


def _write_register_df(df: pd.DataFrame, path: str, lang: str) -> None:
    out = df.copy()
    if lang == "de":
        out["kind"] = [_KIND_DE.get(v, v) for v in out["kind"]]
        out["measurement_kind"] = ["+".join(_MEASUREMENT_KIND_DE.get(p, p) for p in str(v).split("+"))
                                   if isinstance(v, str) else v for v in out["measurement_kind"]]
        out = out.rename(columns=_EN_TO_DE)
    out.to_csv(path, sep=";", decimal="," if lang == "de" else ".", index=False, encoding="utf-8-sig")


def write_register(base: str, path: Optional[str] = None, df: Optional[pd.DataFrame] = None,
                   presets: Optional[Mapping[str, Mapping[str, object]]] = None,
                   layout: Union[str, CampaignLayout, None] = None) -> str:
    """Write the register (semicolon, UTF-8 with BOM for spreadsheet programs; decimal comma in a German register).

    Manually maintained columns ([`MANUAL_COLUMNS`][groundfault.register.MANUAL_COLUMNS]) of an existing file are kept
    (key: ``path``). A German register keeps its German column names and values.

    Returns
    -------
    str
        Path of the register.
    """
    lay = get_layout(layout) if layout is not None else detect_layout(base)
    path = path or register_path(base, lay)
    df = scan(base, presets=presets, layout=lay) if df is None else df.copy()
    lang = lay.language
    if os.path.exists(path):
        old, lang = read_register(path)
        if "path" in old.columns and not df.empty:
            old = old.assign(path=old["path"].map(_posix)).drop_duplicates("path").set_index("path")
            for i, r in df.iterrows():
                key = _posix(r["path"])
                if key in old.index:
                    for sp in MANUAL_COLUMNS:
                        if sp in old.columns and str(old.at[key, sp]).strip() != "":
                            v = old.at[key, sp]
                            if sp == "fault_resistance_Ohm":
                                try:
                                    v = float(str(v).replace(",", "."))
                                except ValueError:
                                    pass
                            df.at[i, sp] = v
    for s in REGISTER_COLUMNS:
        if s not in df.columns:
            df[s] = ""
    # uniform notation: measurement_no as integer, fault resistance as "2,5"/"0" (German) or "2.5"/"0" (English),
    # also for manual values
    df["measurement_no"] = pd.to_numeric(df["measurement_no"], errors="coerce").astype("Int64")

    def _ohm(v):
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            return ""
        if isinstance(v, (int, float, np.number)):
            s = "%g" % float(v)
            return s.replace(".", ",") if lang == "de" else s
        return str(v)
    df["fault_resistance_Ohm"] = [_ohm(v) for v in df["fault_resistance_Ohm"]]
    _write_register_df(df[list(REGISTER_COLUMNS)], path, lang)
    return path


def fault_resistance(base: str, campaign: str, file: str) -> Optional[float]:
    """Fault resistance of a recording from the register (column ``fault_resistance_Ohm``, maintained by hand or
    taken from the file name) → float, or None (register or line missing, field empty)."""
    path = register_path(base)
    if not file or not os.path.exists(path):
        return None
    try:
        df, _ = read_register(path)
    except (OSError, ValueError, pd.errors.ParserError):
        return None
    if not {"campaign", "file", "fault_resistance_Ohm"} <= set(df.columns):
        return None
    z = df[(df["campaign"].map(_nfc) == _nfc(campaign)) & (df["file"].map(_nfc) == _nfc(os.path.basename(file)))]
    for v in z["fault_resistance_Ohm"]:
        try:
            return float(str(v).strip().replace(",", "."))
        except ValueError:
            continue
    return None


def _table_md(df: pd.DataFrame, columns: Sequence[str], labels: Optional[Sequence[str]] = None,
              comma: bool = True) -> str:
    labels = list(labels) if labels is not None else list(columns)
    header = "| " + " | ".join(labels) + " |\n|" + "|".join("---" for _ in columns) + "|\n"
    rows = []
    for _, r in df.iterrows():
        values = []
        for s in columns:
            v = r.get(s, "")
            if v is None:
                v = ""
            elif isinstance(v, float):
                v = "" if not np.isfinite(v) else ("%g" % v)
                v = v.replace(".", ",") if comma else v
            values.append(str(v))
        rows.append("| " + " | ".join(values) + " |")
    return header + "\n".join(rows) + "\n"


def campaign_readme(campaign_folder: str, register: pd.DataFrame,
                    layout: Union[str, CampaignLayout, None] = None) -> str:
    """Markdown text of the read-me file of a campaign (in the language of the layout).

    Parameters
    ----------
    campaign_folder : str
        The campaign folder.
    register : pandas.DataFrame
        Register with English column names ([`scan`][groundfault.register.scan] or
        [`read_register`][groundfault.register.read_register]).
    """
    from . import sites as _sites
    from .corrections import HEADERS as _CORR_HEADERS, load as _load_corrections
    lay = get_layout(layout) if layout is not None else detect_layout(campaign_folder)
    lang = lay.language
    comma = lang == "de"
    t_ = lambda key, **kw: tr(key, lang=lang, **kw)          # noqa: E731
    reg_label = (lambda c: _EN_TO_DE.get(c, c)) if lang == "de" else (lambda c: c)
    name = _nfc(os.path.basename(campaign_folder.rstrip("/")))
    g = register[register["campaign"] == name].copy() if "campaign" in register else register.iloc[0:0]
    m = re.match(r"(\d{4}-\d{2}-\d{2})_(.+)", name)
    date, place = (m.group(1), m.group(2)) if m else ("", name)
    manual = " / ".join(reg_label(c) for c in ("fault_resistance_Ohm", "fault_location", "remark"))
    z = [t_("register.readme_title", place=place.replace("_", " "), date=date), "",
         t_("register.readme_intro", notes=lay.notes, notes_file=lay.notes_file, corrections=lay.corrections_file,
            sites=lay.sites_file, manual=manual, register=lay.register_file), "",
         t_("register.readme_recordings"), ""]
    if g.empty:
        z.append(t_("register.readme_no_files"))
    else:
        g = g.sort_values(["measurement_no", "start_cfg"], na_position="last")
        if lang == "de":
            g["kind"] = [_KIND_DE.get(v, v) for v in g["kind"]]
            g["measurement_kind"] = ["+".join(_MEASUREMENT_KIND_DE.get(p, p) for p in str(v).split("+"))
                                     for v in g["measurement_kind"]]
        cols = ["measurement_no", "site", "file", "kind", "measurement_kind", "fault_resistance_Ohm", "fs_Hz",
                "duration_s", "start_cfg", "channels", "remark"]
        z.append(_table_md(g, cols, [reg_label(c) for c in cols], comma))
    corr_path = "%s/%s" % (lay.notes, lay.corrections_file)
    try:
        corr = _load_corrections(campaign_folder)
        if len(corr):
            t = corr.table()
            t["factor"] = [(("%g" % v).replace(".", ",") if comma else "%g" % v) if v != 1 else ""
                           for v in t["factor"]]
            cols = ["file", "channel", "factor", "role", "main_channel", "distance_m", "remark"]
            labels = list(_CORR_HEADERS["de"]) if lang == "de" else cols
            z += ["", t_("register.readme_corrections", path=corr_path), "",
                  t_("register.readme_corrections_note"), "", _table_md(t, cols, labels, comma)]
    except ValueError as e:
        z += ["", t_("register.readme_corrections_short"), "", t_("register.readme_unreadable", path=corr_path, error=e)]
    sites_path = "%s/%s" % (lay.notes, lay.sites_file)
    try:
        sites = _sites.load(campaign_folder)
        if len(sites):
            t = sites.table()
            for sp in ("latitude", "longitude"):
                t[sp] = ["" if v is None or v != v else ((("%.5f" % v).replace(".", ",")) if comma else "%.5f" % v)
                         for v in t[sp]]
            cols = ["site", "location_groundmeas", "latitude", "longitude", "asset_type", "voltage_level_kV",
                    "distance_to_substation_m", "remark"]
            labels = [dict(zip(_sites.COLUMNS, _sites.HEADERS["de"])).get(c, c) for c in cols] if lang == "de" \
                else cols
            z += ["", t_("register.readme_sites", path=sites_path), "", _table_md(t, cols, labels, comma)]
    except ValueError as e:
        z += ["", t_("register.readme_sites_short"), "", t_("register.readme_unreadable", path=sites_path, error=e)]
    for notes in dict.fromkeys((os.path.join(campaign_folder, lay.notes, lay.notes_file),
                                os.path.join(campaign_folder, lay.notes_file),
                                os.path.join(campaign_folder, ENGLISH.notes, ENGLISH.notes_file),
                                os.path.join(campaign_folder, GERMAN.notes, GERMAN.notes_file))):
        if os.path.exists(notes) and os.path.getsize(notes) > 0:
            with open(notes, encoding="utf-8", errors="replace") as f:
                text = f.read().strip()
            if text and text not in (x.strip() for x in _NOTES_TEMPLATES.values()):
                z += ["", t_("register.readme_notes"), "", "```", text, "```"]
            break
    z += ["", t_("register.readme_folders"), "", t_("register.readme_folder_table"), "|---|---|",
          t_("register.readme_folder_notes", notes=lay.notes, notes_file=lay.notes_file,
             corrections=lay.corrections_file, sites=lay.sites_file),
          t_("register.readme_folder_raw", raw=lay.raw),
          t_("register.readme_folder_results", results=lay.results),
          t_("register.readme_folder_figures", figures=lay.figures),
          t_("register.readme_folder_report", report=lay.report),
          t_("register.readme_folder_media", media=lay.media), "",
          t_("register.readme_times", start=reg_label("start_cfg"), number=reg_label("measurement_no"))]
    return "\n".join(z) + "\n"


def record_intervals(base: str, rel_path: str, steady_state=None, pre_fault=None, post_fault=None,
                     fault_resistance: Optional[float] = None, register: Optional[str] = None) -> bool:
    """Record the evaluation intervals of a recording in the register (documentation and repeatability).

    Parameters
    ----------
    rel_path : str
        Path of the .cfg file relative to the working folder ``base``.
    steady_state, pre_fault, post_fault : tuple of float, optional
        Intervals in s.
    fault_resistance : float, optional
        Fault resistance in Ω.

    Returns
    -------
    bool
        False if the register or the recording is missing.
    """
    register = register or register_path(base)
    if not os.path.exists(register):
        return False
    df, lang = read_register(register)
    rel_path = _posix(rel_path)
    hits = df.index[df["path"].map(_posix) == rel_path]
    if len(hits) == 0:
        return False
    sep = (lambda s: s.replace(".", ",")) if lang == "de" else (lambda s: s)
    fmt = lambda b: "" if b is None else sep("%g–%g" % (b[0], b[1]))       # noqa: E731
    i = hits[0]
    for sp, b in (("steady_state_s", steady_state), ("pre_fault_s", pre_fault), ("post_fault_s", post_fault)):
        if b is not None:
            df.at[i, sp] = fmt(b)
    if fault_resistance is not None:
        df.at[i, "fault_resistance_Ohm"] = sep("%g" % fault_resistance)
    out = df.rename(columns=_EN_TO_DE) if lang == "de" else df
    if lang == "de":
        out = out.copy()
        if "Art" in out:
            out["Art"] = [_KIND_DE.get(v, v) for v in out["Art"]]
        if "Messart" in out:
            out["Messart"] = ["+".join(_MEASUREMENT_KIND_DE.get(p, p) for p in str(v).split("+"))
                              for v in out["Messart"]]
    out.to_csv(register, sep=";", index=False, encoding="utf-8-sig")
    return True


def update_all(base: str, readme: bool = True, presets: Optional[Mapping[str, Mapping[str, object]]] = None,
               layout: Union[str, CampaignLayout, None] = None) -> Dict[str, object]:
    """Rebuild the register (manual columns are kept) and rewrite the read-me file of every campaign.

    Call after sorting in new raw data, e.g. ``python tools/update_register.py``.

    Returns
    -------
    dict
        ``register`` (path), ``readme`` (paths), ``files`` (number of recordings), ``hints`` (recordings with a
        status other than ok), ``actions`` (created or moved files).
    """
    lay = get_layout(layout) if layout is not None else detect_layout(base)
    df = scan(base, presets=presets, layout=lay)
    path = write_register(base, df=df, layout=lay)
    df, _ = read_register(path)
    for sp in ("measurement_no", "fs_Hz", "duration_s"):
        if sp in df.columns:
            df[sp] = pd.to_numeric(df[sp].astype(str).str.replace(",", "."), errors="coerce")
    written, actions = [], []
    if readme:
        for kd in _campaign_folders(base, lay):
            actions += ["%s: %s" % (os.path.basename(kd), a) for a in create_notes_folder(kd, layout=lay)]
            target = os.path.join(kd, lay.readme_file)
            with open(target, "w", encoding="utf-8") as f:
                f.write(campaign_readme(kd, df, lay))
            written.append(target)
    hints = ["%s: %s" % (r["path"], r["status"]) for _, r in df.iterrows() if str(r.get("status", "ok")) != "ok"]
    return dict(register=path, readme=written, files=len(df), hints=hints, actions=actions)


def create_notes_folder(campaign_folder: str, db_path: Optional[str] = None,
                        layout: Union[str, CampaignLayout, None] = None) -> List[str]:
    """Create the notes folder with the notes file, the corrections file and the sites file (pre-filled from
    groundmeas if the database is readable – ``db_path`` or as groundmeas finds it) if they are missing, and move
    an existing notes file from the campaign folder there. Never overwrites anything.

    Returns
    -------
    list of str
        The actions taken (for a log), in the output language with the file names of the layout.
    """
    from . import sites
    from .corrections import write_template
    lay = get_layout(layout) if layout is not None else detect_layout(campaign_folder)
    actions = []
    target_dir = os.path.join(campaign_folder, lay.notes)
    os.makedirs(target_dir, exist_ok=True)
    old = os.path.join(campaign_folder, lay.notes_file)
    new = os.path.join(target_dir, lay.notes_file)
    rel = "%s/%s" % (lay.notes, lay.notes_file)
    if os.path.exists(old) and not os.path.exists(new):
        os.replace(old, new)
        actions.append(tr("register.moved", old=lay.notes_file, new=rel))
    elif os.path.exists(old) and os.path.exists(new):
        actions.append(tr("register.duplicate_notes", file=lay.notes_file, notes=lay.notes))
    if not os.path.exists(new):
        with open(new, "w", encoding="utf-8") as f:
            f.write(_NOTES_TEMPLATES[lay.language])
        actions.append(tr("register.created", path=rel))
    if write_template(campaign_folder, lay):
        actions.append(tr("register.created", path="%s/%s" % (lay.notes, lay.corrections_file)))
    if os.path.isdir(os.path.join(campaign_folder, lay.raw)) and sites.write_template(campaign_folder, db_path, lay):
        actions.append(tr("register.created_sites", path="%s/%s" % (lay.notes, lay.sites_file)))
    return actions
