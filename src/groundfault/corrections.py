# -*- coding: utf-8 -*-
"""Corrections of the measuring chain per campaign: ``notes/corrections.csv`` (German layout:
``0_Notizen/Korrekturen.csv``).

A staged earth fault test can rarely be repeated. If it turns out after the test that a CT ratio was set
wrongly, a clamp enclosed only one of several parallel conductors or was connected with reversed polarity,
this is noted in the corrections file. groundfault applies the corrections whenever a recording is read and
documents every applied correction in the hints, the plausibility table and the result file.

Format (semicolon, decimal point or comma; edit with a spreadsheet program or a text editor; lines starting
with ``#`` are comments)::

    file;channel;factor;role;main_channel;distance_m;remark
    SUB_7_5_*;ISp22;10;;;;CT ratio of the coil current set wrongly (reads a tenth)
    SUB_*;ISp21;2;;;;clamp encloses only one of two parallel coil cables
    *;IF3;;ignore;;;spare channel, not connected – do not evaluate
    SUB_*;IF2;;;yes;;main fault-current channel (the CT at the fault location)
    Station_*;UE?;;;;40;probes UEr/UEl at 40 m (distance not in the channel name)

* **file** – file name or pattern (``*`` any characters, ``?`` one character), with or without ``.cfg``; applies
  to the instantaneous-value and the RMS file if the pattern matches both (``SUB_7_5_*``).
* **channel** – short name as in the channel name after the device prefix (``ISp21``) or a pattern (``ISp*``).
* **factor** – multiplier applied to the measured values: ``10``, ``0.1``/``0,1``, ``1/3``, ``-1`` (polarity).
  Factors of several lines matching the same channel are multiplied. RMS values (RMS file) have no sign – only
  the magnitude of the factor is applied there.
* **role** – optional: fix the channel role (``i_res``, ``i_coil``, ``u_l1e`` …) or ``ignore``; PEN currents with
  their position: ``i_pen_feeders`` (LV feeders, before the transformer star point), ``i_pen_busbar`` (to the main
  earthing busbar).
* **main_channel** – optional ``yes``: this channel is the main channel of its role (e.g. fault-current CT).
* **distance_m** – optional: probe distance in m for earth-potential channels whose name contains no distance
  (``UEr``, ``UE``; ``UE_70m``/``U1m`` already carry it). Used for the touch-voltage detection (probe ≤ 1.5 m),
  the comparison with earthing measurements and the export to groundmeas (``measurement_distance_m``). The
  column may be missing (older files) and may stand anywhere before ``remark``.
* **remark** – reason, who, when (shown with every applied correction).

Files of the predecessor tool with German headers (``Datei;Kanal;Faktor;Rolle;Hauptkanal;Abstand_m;Bemerkung``)
and German values (``ignorieren``, ``ja``, ``i_pen_v``) are read as well. New files are written with the
headers of the campaign layout ([`groundfault.layout`][groundfault.layout]).
"""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Union

import pandas as pd

from . import i18n
from .channels import LEGACY_ROLES, ROLE_ALIASES, ROLE_DESCRIPTIONS, _mv_levels_kv, detect_role, short_name
from .i18n import tr
from .layout import ENGLISH, GERMAN, CampaignLayout, detect_layout, get_layout

__all__ = ["CorrectionRule", "Corrections", "load", "path_for", "write_template", "template", "parse_factor",
           "is_rms_channel", "COLUMNS", "HEADERS", "TEMPLATE", "NOTES_FOLDER", "FILENAME"]

COLUMNS = ("file", "channel", "factor", "role", "main_channel", "distance_m", "remark")
"""Column names (English layout); the German layout uses [`HEADERS`][groundfault.corrections.HEADERS] ``["de"]``."""
HEADERS = {"en": COLUMNS,
           "de": ("Datei", "Kanal", "Faktor", "Rolle", "Hauptkanal", "Abstand_m", "Bemerkung")}
"""Header line per layout language."""
#: accepted spellings of the header names (lower case) → column
_HEADER_NAMES = {name.lower(): col for lang in HEADERS for name, col in zip(HEADERS[lang], COLUMNS)}
_HEADER_NAMES.update({"main channel": "main_channel", "distance": "distance_m", "comment": "remark"})
NOTES_FOLDER = GERMAN.notes
"""Deprecated alias: the notes folder of the German layout (``0_Notizen``); use
[`path_for`][groundfault.corrections.path_for]."""
FILENAME = GERMAN.corrections_file
"""Deprecated alias: the corrections file of the German layout (``Korrekturen.csv``); use
[`path_for`][groundfault.corrections.path_for]."""
_IGNORE = {"ignore", "ignorieren", "keine", "none", "-", "–", "aus", "off"}      # German spellings: legacy files
_YES = {"yes", "y", "ja", "j", "x", "1", "true", "wahr"}

_TEMPLATES = {
    "en": (
        "file;channel;factor;role;main_channel;distance_m;remark\n"
        "# Corrections for this measurement campaign – applied automatically whenever a recording is read.\n"
        "# file: file name or pattern (* ?), channel: short name (e.g. ISp21) or pattern,\n"
        "# factor: multiplier (10 | 0.1 | 1/3 | -1 = polarity), role: e.g. i_res, i_coil, u_l1e or ignore,\n"
        "# main_channel: yes = main channel of its role, distance_m: probe distance in m if not in the channel name\n"
        "# (e.g. UEr, UE), remark: reason, who, when.\n"
        "# Examples (remove the # to activate):\n"
        "# SUB_7_5_*;ISp22;10;;;;CT ratio of the coil current set wrongly (reads a tenth)\n"
        "# SUB_*;IF2;;;yes;;main fault-current channel\n"
        "# Station*;UE;;;;40;probe at 40 m\n"),
    "de": (
        "Datei;Kanal;Faktor;Rolle;Hauptkanal;Abstand_m;Bemerkung\n"
        "# Korrekturen für die Auswertung dieser Messkampagne – werden beim Einlesen automatisch angewendet.\n"
        "# Datei: Dateiname oder Muster (* ?), Kanal: Kurzname (z. B. ISp21) oder Muster,\n"
        "# Faktor: Multiplikator (10 | 0,1 | 1/3 | -1 = Polarität), Rolle: z. B. i_res, i_coil, u_l1e oder ignorieren,\n"
        "# Hauptkanal: ja = Hauptkanal seiner Rolle, Abstand_m: Sondenabstand in m, falls nicht im Kanalnamen\n"
        "# (z. B. UEr, UE), Bemerkung: Begründung, wer, wann.\n"
        "# Beispiele (zum Aktivieren das # entfernen):\n"
        "# UW_7_5_*;ISp22;10;;;;Wandlerübersetzung des Spulenstroms falsch eingestellt (misst ein Zehntel)\n"
        "# UW_*;IF2;;;ja;;Hauptkanal Fehlerstrom\n"
        "# Station*;UE;;;;40;Sonde in 40 m\n"),
}
TEMPLATE = _TEMPLATES["en"]
"""Template of the English layout (see [`template`][groundfault.corrections.template])."""

i18n.register({
    "corrections.encoding": {
        "en": "{file}: character encoding not readable.",
        "de": "{file}: Zeichenkodierung nicht lesbar."},
    "corrections.header": {
        "en": "{file}, line {line}: the header needs at least the columns file;channel (German: Datei;Kanal) – "
              "found: {header}",
        "de": "{file}, Zeile {line}: Kopfzeile braucht mindestens die Spalten Datei;Kanal (englisch: file;channel) – "
              "gefunden: {header}"},
    "corrections.factor": {
        "en": "{file}, line {line}: factor {value!r} not readable (e.g. 10, 0.1, 1/3, -1)",
        "de": "{file}, Zeile {line}: Faktor {value!r} nicht lesbar (z. B. 10, 0,1, 1/3, -1)"},
    "corrections.factor_zero": {
        "en": "{file}, line {line}: factor 0 is not allowed.",
        "de": "{file}, Zeile {line}: Faktor 0 ist nicht zulässig."},
    "corrections.role": {
        "en": "{file}, line {line}: unknown role {value!r} (allowed: {allowed}, ignore)",
        "de": "{file}, Zeile {line}: unbekannte Rolle {value!r} (zulässig: {allowed}, ignorieren)"},
    "corrections.distance": {
        "en": "{file}, line {line}: {column} {value!r} is not a probe distance in m (e.g. 70 or 1.0)",
        "de": "{file}, Zeile {line}: {column} {value!r} ist kein Sondenabstand in m (z. B. 70 oder 1,0)"},
    "corrections.channel_missing": {
        "en": "{file} line {line}: channel {channel!r} not in {recording} – check the spelling.",
        "de": "{file} Zeile {line}: Kanal {channel!r} nicht in {recording} – Schreibweise prüfen."},
    "corrections.rms_sign": {
        "en": "{file} line {line}: {channel} in {recording} contains RMS values – the sign has no meaning, {action}.",
        "de": "{file} Zeile {line}: {channel} in {recording} enthält Effektivwerte – Vorzeichen ohne Bedeutung, "
              "{action}."},
    "corrections.rms_polarity_skipped": {
        "en": "polarity not applied there",
        "de": "Polarität dort nicht angewendet"},
    "corrections.rms_magnitude": {
        "en": "only |factor| = {factor:g} applied",
        "de": "nur |Faktor| = {factor:g} angewendet"},
    "corrections.source": {
        "en": "{path}, line {line}",
        "de": "{path}, Zeile {line}"},
})


def parse_factor(text) -> float:
    """Factor from a table cell: ``"10"``, ``"0,1"``, ``"1/3"``, ``"−1"``, ``"x3"`` → float; empty → 1.

    Raises
    ------
    ValueError
        If the text is not a number.
    """
    if text is None:
        return 1.0
    t = str(text).strip().replace("−", "-").replace("×", "").replace("*", "").replace(" ", "")
    if t.lower().startswith("x"):
        t = t[1:]
    if t == "" or t.lower() == "nan":
        return 1.0
    if "/" in t:
        num, den = t.split("/", 1)
        return parse_factor(num) / parse_factor(den)
    if "," in t and "." in t:                     # 1.000,5 → 1000.5
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", ".")
    return float(t)


def is_rms_channel(rec, j: int) -> bool:
    """True if channel ``j`` of ``rec`` contains RMS values (device suffix ``RMS`` or a sampling rate below
    200 Hz, i.e. no instantaneous values of the 50-Hz quantities) – such values have no sign."""
    return short_name(rec.channel_names[j])[2].upper() == "RMS" or float(getattr(rec, "fs", 1e9)) < 200.0


@dataclass
class CorrectionRule:
    """One line of the corrections file.

    ``role`` is ``""`` (unchanged), a role name, or ``None`` (ignore the channel).
    """

    file: str
    channel: str
    factor: float = 1.0
    role: Optional[str] = ""
    main_channel: bool = False
    remark: str = ""
    line: int = 0
    distance_m: Optional[float] = None    # probe distance (earth potential) if not in the channel name

    def matches_file(self, filename: str) -> bool:
        """True if the rule applies to the recording ``filename`` (pattern with or without extension)."""
        name = os.path.basename(filename).lower()
        stem = os.path.splitext(name)[0]
        pat = self.file.strip().lower() or "*"
        return fnmatch.fnmatchcase(name, pat) or fnmatch.fnmatchcase(stem, pat)

    def matches_channel(self, name: str) -> bool:
        """True if the rule applies to the channel ``name`` (short name or full name)."""
        pat = self.channel.strip().lower()
        return fnmatch.fnmatchcase(short_name(name)[0].lower(), pat) or fnmatch.fnmatchcase(name.lower(), pat)


class Corrections:
    """Corrections of a measurement campaign (empty if there is no corrections file).

    Parameters
    ----------
    rules : sequence of CorrectionRule
        The rules in file order.
    path : str, optional
        File the rules were read from.

    Attributes
    ----------
    hints : list of str
        Hints of the last [`apply`][groundfault.corrections.Corrections.apply] call, i.e. on the recording it was
        applied to (rules whose channel is not in the recording, negative factors on RMS channels); reset by every call.
    """

    def __init__(self, rules: Sequence[CorrectionRule] = (), path: Optional[str] = None):
        self.rules: List[CorrectionRule] = list(rules)
        self.path = path
        self.hints: List[str] = []

    @classmethod
    def empty(cls) -> "Corrections":
        """Corrections without any line (what [`load`][groundfault.corrections.load] returns for a campaign without a
        corrections file)."""
        return cls()

    # ------------------------------------------------------------------ reading
    @classmethod
    def from_file(cls, path: str) -> "Corrections":
        """Read a corrections file (English or German headers, ``;``, tab or ``,`` as separator).

        Raises
        ------
        ValueError
            For an unreadable encoding, a missing ``file``/``channel`` column, an unreadable or zero factor, an
            unknown role or an invalid probe distance – with file name and line number.
        """
        name = os.path.basename(path)
        raw = None
        for enc in ("utf-8-sig", "cp1252", "mac_roman"):
            try:
                with open(path, encoding=enc) as f:
                    raw = f.read()
                break
            except UnicodeDecodeError:
                continue
        if raw is None:
            raise ValueError(tr("corrections.encoding", file=path))
        rows = [(i + 1, z) for i, z in enumerate(raw.splitlines())]
        content = [(i, z) for i, z in rows if z.strip() and not z.lstrip().startswith("#")]
        if not content:
            return cls([], path)
        header_no, header = content[0]
        separator = max((";", "\t", ","), key=header.count)
        header_names = [c.strip().strip('"') for c in header.split(separator)]
        columns = [_HEADER_NAMES.get(c.lower(), c.lower()) for c in header_names]
        written = dict(zip(columns, header_names))           # column → its name in this file (for messages)
        if "file" not in columns or "channel" not in columns:
            raise ValueError(tr("corrections.header", file=name, line=header_no, header=header))
        rules = []
        for number, z in content[1:]:
            raw_fields = z.split(separator)
            values = [w.strip().strip('"') for w in raw_fields]
            if not any(values):
                continue
            n = len(columns)
            if len(values) > n and columns[-1] == "remark":                 # separator inside the remark
                rest = separator.join(raw_fields[n - 1:]).rstrip().rstrip(separator).strip().strip('"')
                values = values[:n - 1] + [rest]
            values += [""] * (len(columns) - len(values))
            d = dict(zip(columns, values))
            if not d.get("file") and not d.get("channel"):
                continue
            try:
                factor = parse_factor(d.get("factor", ""))
            except ValueError:
                raise ValueError(tr("corrections.factor", file=name, line=number, value=d.get("factor")))
            if factor == 0:
                raise ValueError(tr("corrections.factor_zero", file=name, line=number))
            role_txt = d.get("role", "").strip()
            role_txt = LEGACY_ROLES.get(role_txt, role_txt)
            if not role_txt:
                role = ""
            elif role_txt.lower() in _IGNORE:
                role = None
            elif role_txt in ROLE_DESCRIPTIONS or role_txt in ROLE_ALIASES:
                role = role_txt
            else:
                raise ValueError(tr("corrections.role", file=name, line=number, value=role_txt,
                                    allowed=", ".join([r for r in ROLE_DESCRIPTIONS if r] + list(ROLE_ALIASES))))
            distance_txt = d.get("distance_m", "").strip().lower().replace("m", "").strip()
            distance = None
            if distance_txt:
                try:
                    distance = parse_factor(distance_txt)
                except ValueError:
                    distance = -1.0
                if not (distance > 0):
                    raise ValueError(tr("corrections.distance", file=name, line=number, value=d.get("distance_m"),
                                        column=written.get("distance_m", "distance_m")))
            rules.append(CorrectionRule(file=d.get("file", "") or "*", channel=d.get("channel", ""), factor=factor,
                                        role=role, main_channel=d.get("main_channel", "").strip().lower() in _YES,
                                        remark=d.get("remark", ""), line=number, distance_m=distance))
        return cls(rules, path)

    # ------------------------------------------------------------------ queries
    def for_file(self, filename: str) -> List[CorrectionRule]:
        """Rules that apply to the recording ``filename``."""
        return [r for r in self.rules if r.matches_file(filename)]

    def table(self) -> pd.DataFrame:
        """All rules as a table (columns ``line``, ``file``, ``channel``, ``factor``, ``role``, ``main_channel``,
        ``distance_m``, ``remark``)."""
        return pd.DataFrame([dict(line=r.line, file=r.file, channel=r.channel, factor=r.factor,
                                  role=("ignore" if r.role is None else r.role),
                                  main_channel="yes" if r.main_channel else "", distance_m=r.distance_m,
                                  remark=r.remark)
                             for r in self.rules], columns=["line", "file", "channel", "factor", "role",
                                                             "main_channel", "distance_m", "remark"])

    def _file_label(self) -> str:
        """``notes/corrections.csv`` – the file relative to its campaign folder (for messages)."""
        if not self.path:
            return ENGLISH.corrections_file
        return os.path.basename(os.path.dirname(self.path)) + "/" + os.path.basename(self.path)   # same on every OS

    def _pairs(self, rec, hints: Optional[List[str]] = None):
        """(rule, channel index) of every rule of ``rec`` and every matching channel; a rule without a matching
        channel adds a hint to ``hints`` (if given)."""
        pairs = []
        name = os.path.basename(self.path) if self.path else ENGLISH.corrections_file
        for r in self.for_file(rec.cfg_path):
            hits = [j for j, nm in enumerate(rec.channel_names) if r.matches_channel(nm)]
            if not hits and hints is not None:
                hints.append(tr("corrections.channel_missing", file=name, line=r.line, channel=r.channel,
                                recording=os.path.basename(rec.cfg_path)))
            pairs += [(r, j) for j in hits]
        return pairs

    def apply(self, rec) -> pd.DataFrame:
        """Apply all factors of this recording to ``rec`` (once per recording) and return the log.

        RMS values (RMS file) have no sign: only the magnitude of the factor is applied to them; a pure polarity
        correction (−1) has no effect there (with a hint).

        ``hints`` is reset by every call and then holds the hints on ``rec`` only (also when the factors had
        been applied to ``rec`` before and nothing is applied again).

        Returns
        -------
        pandas.DataFrame
            One row per corrected channel (see [`log`][groundfault.corrections.Corrections.log]).
        """
        applied = getattr(rec, "_corrections_applied", None) == (self.path, len(self.rules))
        name = os.path.basename(self.path) if self.path else ENGLISH.corrections_file
        hints: List[str] = []
        for r, j in self._pairs(rec, hints):
            f = r.factor
            if f < 0 and is_rms_channel(rec, j):
                f = -f
                action = tr("corrections.rms_polarity_skipped") if f == 1.0 else tr("corrections.rms_magnitude",
                                                                                   factor=f)
                hints.append(tr("corrections.rms_sign", file=name, line=r.line,
                                channel=short_name(rec.channel_names[j])[0],
                                recording=os.path.basename(rec.cfg_path), action=action))
            if f != 1.0 and not applied:
                rec.set_correction(j, f, r.remark, tr("corrections.source", path=self._file_label(), line=r.line))
        self.hints = list(dict.fromkeys(hints))
        rec._corrections_applied = (self.path, len(self.rules))
        return self.log(rec)

    def log(self, rec) -> pd.DataFrame:
        """Corrections of ``rec``: ``channel``, ``factor`` (this rule), ``factor_total`` (all rules and earlier
        corrections), ``role``, ``main_channel``, ``distance_m``, ``line``, ``remark``."""
        rows = []
        for r, j in self._pairs(rec):
            rows.append(dict(channel=short_name(rec.channel_names[j])[0], factor=r.factor,
                             factor_total=float(rec._cf[j]),
                             role=("ignore" if r.role is None else r.role),
                             main_channel="yes" if r.main_channel else "", distance_m=r.distance_m, line=r.line,
                             remark=r.remark))
        return pd.DataFrame(rows, columns=["channel", "factor", "factor_total", "role", "main_channel", "distance_m",
                                           "line", "remark"])

    def role_overrides(self, rec) -> Dict[str, Optional[str]]:
        """``{channel name: role}`` for [`groundfault.detect_roles`][groundfault.channels.detect_roles] (``None`` =
        ignore)."""
        return {rec.channel_names[j]: r.role for r, j in self._pairs(rec) if r.role != ""}

    def distances(self, rec) -> Dict[str, float]:
        """``{channel name: probe distance in m}`` for [`groundfault.detect_roles`][groundfault.channels.detect_roles]
        (column ``distance_m``)."""
        return {rec.channel_names[j]: r.distance_m for r, j in self._pairs(rec) if r.distance_m is not None}

    def main_channel(self, rec) -> Dict[str, str]:
        """``{role: channel name}`` for [`groundfault.detect_roles`][groundfault.channels.detect_roles]."""
        out = {}
        mv_levels = _mv_levels_kv(rec.channel_names)          # as in detect_roles (structured names)
        for r, j in self._pairs(rec):
            if not r.main_channel:
                continue
            nm = rec.channel_names[j]
            role = r.role if r.role else detect_role(nm, rec.units[j], mv_levels)[0]
            role = ROLE_ALIASES.get(role, (role,))[0]          # i_pen_feeders / i_pen_busbar → i_pen
            if role:
                out[role] = nm
        return out

    def __len__(self) -> int:
        return len(self.rules)

    def __repr__(self) -> str:
        return "<Corrections: %d rules from %s>" % (len(self.rules), self.path or "–")


def path_for(campaign_folder, layout: Union[str, CampaignLayout, None] = None) -> str:
    """Path of the corrections file of a campaign (``notes/corrections.csv`` or ``0_Notizen/Korrekturen.csv``,
    depending on the detected or given layout)."""
    lay = get_layout(layout) if layout is not None else detect_layout(campaign_folder)
    return os.path.join(str(campaign_folder), lay.notes, lay.corrections_file)


def _candidates(p: str):
    yield p
    first = detect_layout(p)
    for lay in (first,) + tuple(x for x in (ENGLISH, GERMAN) if x is not first):
        yield os.path.join(p, lay.corrections_file)
        yield os.path.join(p, lay.notes, lay.corrections_file)


def load(folder_or_file) -> Corrections:
    """Corrections of a campaign (missing file → empty).

    Parameters
    ----------
    folder_or_file : str or path-like
        The campaign folder, its notes folder or the file itself; both layouts are searched.
    """
    p = str(folder_or_file)
    for cand in _candidates(p):
        if os.path.isfile(cand):
            return Corrections.from_file(cand)
    return Corrections([], None)


def template(layout: Union[str, CampaignLayout, None] = None) -> str:
    """Content of a new corrections file (header and explanation) in the language of the layout."""
    return _TEMPLATES[get_layout(layout).language]


def write_template(campaign_folder, layout: Union[str, CampaignLayout, None] = None) -> Optional[str]:
    """Create the corrections file with header and explanation if the campaign has none.

    Returns
    -------
    str or None
        Path of the new file, or None if a corrections file (either layout) already exists.
    """
    if any(os.path.isfile(c) for c in _candidates(str(campaign_folder)) if c != str(campaign_folder)):
        return None
    lay = get_layout(layout) if layout is not None else detect_layout(campaign_folder)
    target = path_for(campaign_folder, lay)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8-sig", newline="\n") as f:
        f.write(template(lay))
    return target
