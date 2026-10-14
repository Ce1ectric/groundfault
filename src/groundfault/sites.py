# -*- coding: utf-8 -*-
"""Measurement sites per campaign: ``notes/sites.csv`` (German layout: ``0_Notizen/Messorte.csv``) – the data
needed to enter a test into **groundmeas**.

groundmeas (database of earthing measurements) assigns every measurement to a *location* with coordinates; its
dashboard shows the locations on a map and collects all measurements of a location there (earthing measurement
and staged fault test side by side). What cannot be taken from the recordings is noted in this file – one line
per folder in ``raw``::

    site;location_groundmeas;latitude;longitude;asset_type;voltage_level_kV;distance_to_substation_m;operator;remark
    Station_A;Station A;51.10000;10.20000;mv_lv_earthing_system;20;2400;Grid Operator;location 7 in groundmeas
    SUB;Substation North;;;substation;20;;Grid Operator;new in groundmeas – enter coordinates

* **site** – folder name in ``raw`` (``Station_A``, ``SUB``, ``SUB_Transformer`` …).
* **location_groundmeas** – location name in groundmeas. If the name already exists in groundmeas (case-insensitive,
  umlauts as ae/oe/ue), that location is used and **not changed**; otherwise a new location is created.
* **latitude / longitude** – WGS84 in degrees (decimal point or comma). Required for a **new** location (without
  coordinates it does not appear on the map); for existing locations only a cross-check (deviation > 100 m → hint).
* **asset_type** – groundmeas ``asset_type``: ``substation`` or ``mv_lv_earthing_system`` (secondary substation in a
  global earthing system) … (see [`ASSET_TYPES`][groundfault.sites.ASSET_TYPES]); empty → from the folder name
  (``Station*`` / ``UW*``, ``SUB*``).
* **voltage_level_kV** – ``voltage_level_kv`` (medium voltage, e.g. 20).
* **distance_to_substation_m** – line length from the feeding substation to the site →
  ``distance_to_current_injection_m`` of the values (as in existing staged-fault entries); empty at the
  substation itself.
* **operator** – ``operator``.
* **remark** – free text.

[`write_template`][groundfault.sites.write_template] creates the file if it is missing and pre-fills it from groundmeas
(read-only): location name, coordinates, asset type, voltage level, operator and distance of existing entries of the
same location. An existing file is never overwritten. Files of the predecessor tool with German headers
(``Messort;Ort_groundmeas;Breite;Laenge;Anlagentyp;Spannungsebene_kV;Entfernung_UW_m;Betreiber;Bemerkung``) are read as
well; new files get the headers of the campaign layout.
"""
from __future__ import annotations

import os
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from typing import List, Optional, Sequence, Union

import pandas as pd

from . import i18n
from .i18n import tr
from .layout import ENGLISH, GERMAN, CampaignLayout, detect_layout, get_layout

__all__ = ["Site", "Sites", "load", "suggest", "write_template", "path_for", "hints", "asset_type_from_site",
           "site_from_path", "ASSET_TYPES", "COLUMNS", "HEADERS", "NOTES_FOLDER", "FILENAME"]

COLUMNS = ("site", "location_groundmeas", "latitude", "longitude", "asset_type", "voltage_level_kV",
           "distance_to_substation_m", "operator", "remark")
"""Column names (English layout)."""
HEADERS = {"en": COLUMNS,
           "de": ("Messort", "Ort_groundmeas", "Breite", "Laenge", "Anlagentyp", "Spannungsebene_kV",
                  "Entfernung_UW_m", "Betreiber", "Bemerkung")}
"""Header line per layout language."""
_HEADER_NAMES = {name.lower(): col.lower() for lang in HEADERS for name, col in zip(HEADERS[lang], COLUMNS)}
_HEADER_NAMES.update({"länge": "longitude", "location": "location_groundmeas", "comment": "remark"})
NOTES_FOLDER = GERMAN.notes
"""Deprecated alias: the notes folder of the German layout (``0_Notizen``); use
[`path_for`][groundfault.sites.path_for]."""
FILENAME = GERMAN.sites_file
"""Deprecated alias: the sites file of the German layout (``Messorte.csv``); use
[`path_for`][groundfault.sites.path_for]."""
ASSET_TYPES = ("substation", "overhead_line_tower", "cable", "cable_cabinet", "house", "pole_mounted_transformer",
               "mv_lv_earthing_system")
"""Allowed ``asset_type`` values of groundmeas (core/models.py, AssetType)."""
_IGNORED = ("pq",)                    # folders without fault recordings (e.g. PQ_measurement)

_COMMENTS = {
    "en": (
        "# Measurement sites of this campaign for groundmeas – pre-filled from groundmeas, please check/complete.\n"
        "# site: folder in raw. location_groundmeas: location name in groundmeas – an existing location is used and\n"
        "# not changed, a new one needs latitude/longitude (WGS84 in degrees, e.g. 52.52000 / 13.40500) for the map.\n"
        "# asset_type: substation | mv_lv_earthing_system | overhead_line_tower | cable | cable_cabinet | house |\n"
        "# pole_mounted_transformer. distance_to_substation_m: line length from the feeding substation (groundmeas:\n"
        "# distance_to_current_injection_m), empty at the substation. operator: groundmeas operator. # = comment.\n"),
    "de": (
        "# Messorte dieser Kampagne für den Eintrag in groundmeas – aus groundmeas vorbelegt, bitte prüfen/ergänzen.\n"
        "# Messort: Ordner in 1_Rohdaten. Ort_groundmeas: Ortsname in groundmeas – ein vorhandener Ort wird verwendet und\n"
        "# nicht verändert, ein neuer braucht Breite/Laenge (WGS84 in Grad, z. B. 52,52000 / 13,40500) für die Karte.\n"
        "# Anlagentyp: substation | mv_lv_earthing_system | overhead_line_tower | cable | cable_cabinet | house |\n"
        "# pole_mounted_transformer. Entfernung_UW_m: Leitungslänge vom speisenden UW (groundmeas: distance_to_current_\n"
        "# injection_m), im UW leer. Betreiber: groundmeas operator. Zeilen mit # sind Kommentare.\n"),
}

i18n.register({
    "sites.encoding": {"en": "{file}: character encoding not readable.",
                       "de": "{file}: Zeichenkodierung nicht lesbar."},
    "sites.header": {
        "en": "{file}, line {line}: the header needs the column site (German: Messort) – found: {header}",
        "de": "{file}, Zeile {line}: Kopfzeile braucht die Spalte Messort (englisch: site) – gefunden: {header}"},
    "sites.where": {"en": "{file}, line {line}", "de": "{file}, Zeile {line}"},
    "sites.not_a_number": {"en": "{field}: {value!r} is not a number", "de": "{field}: {value!r} ist keine Zahl"},
    "sites.coordinates_pair": {"en": "{where}: give latitude and longitude together.",
                               "de": "{where}: Breite und Laenge nur zusammen angeben."},
    "sites.coordinates_range": {
        "en": "{where}: coordinates {lat:g} / {lon:g} out of range (degrees, WGS84).",
        "de": "{where}: Koordinaten {lat:g} / {lon:g} außerhalb des Wertebereichs (Grad, WGS84)."},
    "sites.coordinates_swapped": {
        "en": "{where}: latitude {lat:g} / longitude {lon:g} – swapped? (Central Europe: latitude ≈ 45…56, "
              "longitude ≈ 5…16)",
        "de": "{where}: Breite {lat:g} / Länge {lon:g} – vertauscht? (Mitteleuropa: Breite ≈ 45…56, Länge ≈ 5…16)"},
    "sites.asset_type": {"en": "{where}: asset type {value!r} unknown (allowed: {allowed})",
                         "de": "{where}: Anlagentyp {value!r} unbekannt (zulässig: {allowed})"},
    "sites.duplicate": {"en": "{where}: site {value!r} already in line {line}.",
                        "de": "{where}: Messort {value!r} steht schon in Zeile {line}."},
    "sites.remark_location": {"en": "location {id} in groundmeas{origin}", "de": "Ort {id} in groundmeas{origin}"},
    "sites.remark_origin": {"en": " (folder name “{name}”)", "de": " (Ordnername „{name}“)"},
    "sites.remark_no_coordinates": {"en": " – without coordinates: please enter",
                                    "de": " – ohne Koordinaten: bitte eintragen"},
    "sites.remark_new": {"en": "new in groundmeas – enter coordinates",
                         "de": "neu in groundmeas – Koordinaten eintragen"},
    "sites.remark_no_db": {"en": "groundmeas not read – check location name and coordinates",
                           "de": "groundmeas nicht gelesen – Ortsname und Koordinaten prüfen"},
    "sites.missing_row": {
        "en": "{file}: no line for the folder “{site}” – add one if needed (suggestion: "
              "groundfault.sites.suggest(campaign_folder)).",
        "de": "{file}: keine Zeile für den Ordner „{site}“ – bei Bedarf ergänzen (Vorschlag: "
              "groundfault.sites.suggest(campaign_folder))."},
})


# ---------------------------------------------------------------------------------------------- numbers
def _number(text, thousands: bool = False, field_: str = "") -> Optional[float]:
    """``"52,52"``/``"52.52"`` → float, empty → None. ``thousands``: ``"12.500"`` = 12500 (distances in m)."""
    if text is None:
        return None
    t = str(text).strip().replace("−", "-").replace(" ", "").replace(" ", "")
    if t == "" or t.lower() in ("nan", "none", "-", "–"):
        return None
    if thousands and re.fullmatch(r"-?\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        raise ValueError(tr("sites.not_a_number", field=field_ or "value", value=text))


def _raw_folders() -> tuple:
    return tuple(dict.fromkeys((ENGLISH.raw, GERMAN.raw)))


def site_from_path(file) -> str:
    """Site of a recording (folder directly below ``raw``/``1_Rohdaten``): ``raw/SUB/RMS_10Hz/x.cfg`` → ``SUB``;
    without a raw folder in the path the parent folder."""
    parts = str(file).replace("\\", "/").split("/")
    for raw in _raw_folders():
        if raw in parts:
            i = len(parts) - 1 - parts[::-1].index(raw)
            if len(parts) > i + 2:
                return parts[i + 1]
    return parts[-2] if len(parts) > 1 else ""


def asset_type_from_site(site: str) -> str:
    """``Station_*`` → ``mv_lv_earthing_system``, ``UW*``/``SUB*`` → ``substation``, otherwise ``""``."""
    m = str(site).strip().lower()
    if m.startswith(("station", "sst", "ost", "secondary")):
        return "mv_lv_earthing_system"
    if m.startswith(("uw", "sub", "substation")):
        return "substation"
    return ""


def _key(s: str) -> str:
    s = (str(s).replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("Ä", "Ae").replace("Ö", "Oe")
         .replace("Ü", "Ue").replace("ß", "ss"))
    return re.sub(r"\s+", " ", s.lower().replace("_", " ")).strip()


# ---------------------------------------------------------------------------------------------- entries
@dataclass
class Site:
    """One line of the sites file."""

    site: str
    location: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    asset_type: str = ""
    voltage_level_kv: Optional[float] = None
    distance_to_substation_m: Optional[float] = None
    operator: str = ""
    remark: str = ""
    line: int = 0

    @property
    def coordinates(self) -> bool:
        """True if latitude and longitude are given."""
        return self.latitude is not None and self.longitude is not None


class Sites:
    """Measurement sites of a campaign (empty if there is no sites file).

    ``hints`` collects remarks on the content that do not prevent reading (e.g. possibly swapped coordinates).
    """

    def __init__(self, entries: Sequence[Site] = (), path: Optional[str] = None):
        self.entries: List[Site] = list(entries)
        self.path = path
        self.hints: List[str] = []

    @classmethod
    def from_file(cls, path: str) -> "Sites":
        """Read a sites file (English or German headers).

        Raises
        ------
        ValueError
            For an unreadable encoding, a missing ``site`` column, unreadable numbers, incomplete or impossible
            coordinates, an unknown asset type or a site listed twice – with file name and line number.
        """
        raw = None
        for enc in ("utf-8-sig", "cp1252", "mac_roman"):
            try:
                with open(path, encoding=enc) as f:
                    raw = f.read()
                break
            except UnicodeDecodeError:
                continue
        if raw is None:
            raise ValueError(tr("sites.encoding", file=path))
        name = os.path.basename(path)
        content = [(i + 1, z) for i, z in enumerate(raw.splitlines()) if z.strip() and not z.lstrip().startswith("#")]
        if not content:
            return cls([], path)
        header_no, header = content[0]
        separator = max((";", "\t", ","), key=header.count)
        header_names = [c.strip().strip('"') for c in header.split(separator)]
        columns = [_HEADER_NAMES.get(c.lower(), c.lower()) for c in header_names]
        written = dict(zip(columns, header_names))           # column → its name in this file (for messages)
        if "site" not in columns:
            raise ValueError(tr("sites.header", file=name, line=header_no, header=header))
        entries, seen, notes = [], {}, []
        for number, z in content[1:]:
            raw_fields = z.split(separator)
            fields = [w.strip().strip('"') for w in raw_fields]
            n = len(columns)
            if len(fields) > n and columns[-1] == "remark":               # separator inside the remark
                fields = fields[:n - 1] + [separator.join(raw_fields[n - 1:]).rstrip().rstrip(separator).strip()
                                           .strip('"')]
            fields += [""] * (n - len(fields))
            d = dict(zip(columns, fields))
            if not d.get("site"):
                continue
            where = tr("sites.where", file=name, line=number)
            try:
                latitude = _number(d.get("latitude"), field_=written.get("latitude"))
                longitude = _number(d.get("longitude"), field_=written.get("longitude"))
                level = _number(d.get("voltage_level_kv"), field_=written.get("voltage_level_kv"))
                distance = _number(d.get("distance_to_substation_m"), thousands=True,
                                   field_=written.get("distance_to_substation_m"))
            except ValueError as e:
                raise ValueError("%s: %s" % (where, e))
            if (latitude is None) != (longitude is None):
                raise ValueError(tr("sites.coordinates_pair", where=where))
            if latitude is not None:
                if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                    raise ValueError(tr("sites.coordinates_range", where=where, lat=latitude, lon=longitude))
                if 5 <= latitude <= 16 and 45 <= longitude <= 56:
                    notes.append(tr("sites.coordinates_swapped", where=where, lat=latitude, lon=longitude))
            kind = (d.get("asset_type") or "").strip()
            if kind and kind not in ASSET_TYPES:
                raise ValueError(tr("sites.asset_type", where=where, value=kind, allowed=", ".join(ASSET_TYPES)))
            key = d["site"].strip().lower()
            if key in seen:
                raise ValueError(tr("sites.duplicate", where=where, value=d["site"], line=seen[key]))
            seen[key] = number
            entries.append(Site(site=d["site"].strip(), location=(d.get("location_groundmeas") or "").strip(),
                                latitude=latitude, longitude=longitude, asset_type=kind, voltage_level_kv=level,
                                distance_to_substation_m=distance, operator=(d.get("operator") or "").strip(),
                                remark=d.get("remark", ""), line=number))
        out = cls(entries, path)
        out.hints = notes
        return out

    def for_site(self, site: Optional[str]) -> Optional[Site]:
        """Entry of the folder name ``site`` (case-insensitive) or None."""
        if not site:
            return None
        k = str(site).strip().lower()
        return next((e for e in self.entries if e.site.lower() == k), None)

    def table(self) -> pd.DataFrame:
        """All entries as a table (columns ``line`` and [`COLUMNS`][groundfault.sites.COLUMNS])."""
        return pd.DataFrame([dict(line=e.line, site=e.site, location_groundmeas=e.location, latitude=e.latitude,
                                  longitude=e.longitude, asset_type=e.asset_type, voltage_level_kV=e.voltage_level_kv,
                                  distance_to_substation_m=e.distance_to_substation_m, operator=e.operator,
                                  remark=e.remark)
                             for e in self.entries], columns=["line"] + list(COLUMNS))

    def __len__(self) -> int:
        return len(self.entries)

    def __repr__(self) -> str:
        return "<Sites: %d entries from %s>" % (len(self.entries), self.path or "–")


def path_for(campaign_folder, layout: Union[str, CampaignLayout, None] = None) -> str:
    """Path of the sites file of a campaign (``notes/sites.csv`` or ``0_Notizen/Messorte.csv``)."""
    lay = get_layout(layout) if layout is not None else detect_layout(campaign_folder)
    return os.path.join(str(campaign_folder), lay.notes, lay.sites_file)


def _candidates(p: str):
    yield p
    first = detect_layout(p)
    for lay in (first,) + tuple(x for x in (ENGLISH, GERMAN) if x is not first):
        yield os.path.join(p, lay.sites_file)
        yield os.path.join(p, lay.notes, lay.sites_file)


def load(folder_or_file) -> Sites:
    """Sites of a campaign (missing file → empty); accepts the campaign folder, its notes folder or the file."""
    p = str(folder_or_file)
    for cand in _candidates(p):
        if os.path.isfile(cand):
            return Sites.from_file(cand)
    return Sites([], None)


# ---------------------------------------------------------------------------------------------- template
def _sites_in_folder(campaign_folder) -> List[str]:
    for raw_name in (detect_layout(campaign_folder).raw,) + _raw_folders():
        raw = os.path.join(str(campaign_folder), raw_name)
        if os.path.isdir(raw):
            break
    else:
        return []
    out = []
    for n in sorted(os.listdir(raw)):
        p = os.path.join(raw, n)
        if not os.path.isdir(p) or n.startswith(".") or n.lower().startswith(_IGNORED):
            continue
        out.append(n)
    return out


def _campaign_location(campaign_folder) -> str:
    """``2026-01-15_Northtown`` → ``Northtown``."""
    n = os.path.basename(os.path.normpath(str(campaign_folder)))
    m = re.match(r"\d{4}-\d{2}-\d{2}_(.+)", n)
    return (m.group(1) if m else n).replace("_", " ").strip()


def _most_common(values):
    w = [x for x in values if x not in (None, "")]
    return Counter(w).most_common(1)[0][0] if w else None


def _location_from_db(con, name: str):
    """Preferred row of a location (name case- and umlaut-insensitive) – see
    [`earthing.location_rows`][groundfault.earthing.location_rows]."""
    from .earthing import location_rows
    z = location_rows(con, name)
    return z[0] if z else None


def suggest(campaign_folder, db_path: Optional[str] = None) -> pd.DataFrame:
    """Suggestion for the sites file (columns [`COLUMNS`][groundfault.sites.COLUMNS]): one line per folder in ``raw``,
    pre-filled from groundmeas (read-only) if ``db_path`` (default:
    [`groundfault.earthing.default_db_path`][groundfault.earthing.default_db_path]) is readable."""
    from . import earthing
    sites = _sites_in_folder(campaign_folder)
    substation_word = "UW" if detect_layout(campaign_folder).language == "de" else "Substation"
    db = None
    if db_path is None:
        db_path = earthing.default_db_path()
    if db_path and os.path.exists(db_path):
        try:
            db = earthing.Database(db_path)
        except (ValueError, sqlite3.Error):
            db = None
    rows = []
    try:
        level_db = operator_db = None
        if db is not None:
            q = db.con.execute("select voltage_level_kv, operator, method from measurement").fetchall()
            level_db = _most_common([r[0] for r in q if r[2] == "staged_fault_test"]) or _most_common([r[0] for r in q])
            operator_db = _most_common([r[1] for r in q])
        for site in sites:
            kind = asset_type_from_site(site)
            is_substation = kind == "substation"
            sought = (substation_word + " " + _campaign_location(campaign_folder)) if is_substation else \
                earthing.location_from_site(site)
            z = dict(site=site, location_groundmeas=sought, latitude=None, longitude=None, asset_type=kind,
                     voltage_level_kV=level_db, distance_to_substation_m=None, operator=operator_db or "", remark="")
            if db is not None:
                w = db.choose_location(sought)
                if w["location"] is not None:
                    o = _location_from_db(db.con, w["location"])
                    z["location_groundmeas"] = w["location"]
                    if o is not None:
                        z["latitude"], z["longitude"] = o["latitude"], o["longitude"]
                        ids = o["all_ids"]
                        meas = db.con.execute("select id, method, voltage_level_kv, asset_type, operator from "
                                              "measurement where location_id in (%s)" % ",".join("?" * len(ids)),
                                              ids).fetchall()
                        z["voltage_level_kV"] = _most_common([r[2] for r in meas]) or level_db
                        z["asset_type"] = _most_common([r[3] for r in meas]) or kind
                        z["operator"] = _most_common([r[4] for r in meas]) or operator_db or ""
                        staged = [r[0] for r in meas if r[1] == "staged_fault_test"]
                        if staged and not is_substation:
                            d = db.con.execute("select distance_to_current_injection_m from measurementitem where "
                                               "measurement_id in (%s)" % ",".join("?" * len(staged)), staged).fetchall()
                            z["distance_to_substation_m"] = _most_common([r[0] for r in d])
                        origin = "" if w["exact"] else tr("sites.remark_origin", name=sought)
                        z["remark"] = tr("sites.remark_location", id=o["id"], origin=origin)
                        if not o["coordinates"]:
                            z["remark"] += tr("sites.remark_no_coordinates")
                else:
                    z["remark"] = tr("sites.remark_new")
            else:
                z["remark"] = tr("sites.remark_no_db")
            if z["asset_type"] not in ASSET_TYPES:
                z["asset_type"] = kind
            rows.append(z)
    finally:
        if db is not None:
            db.close()
    return pd.DataFrame(rows, columns=list(COLUMNS))


def _cell(x, decimals: Optional[int] = None, comma: bool = True) -> str:
    if x is None or (isinstance(x, float) and x != x):
        return ""
    if isinstance(x, float):
        if decimals is not None:
            t = ("%." + str(decimals) + "f") % x
            t = t.rstrip("0").rstrip(".") if "." in t else t
        else:
            t = ("%d" % x) if x == int(x) else repr(x)
        return t.replace(".", ",") if comma else t
    return str(x).replace(";", ",")


def write_template(campaign_folder, db_path: Optional[str] = None,
                   layout: Union[str, CampaignLayout, None] = None) -> Optional[str]:
    """Create the sites file (pre-filled from groundmeas, see [`suggest`][groundfault.sites.suggest]) if the campaign
    has none.

    Headers and number format follow the layout: English with decimal points, German with decimal commas.

    Returns
    -------
    str or None
        Path of the new file, or None if a sites file already exists (it is never overwritten).
    """
    if any(os.path.isfile(c) for c in _candidates(str(campaign_folder)) if c != str(campaign_folder)):
        return None
    lay = get_layout(layout) if layout is not None else detect_layout(campaign_folder)
    target = path_for(campaign_folder, lay)
    comma = lay.language == "de"
    with i18n.language(lay.language):
        vs = suggest(campaign_folder, db_path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    rows = [";".join(HEADERS[lay.language])]
    for _, r in vs.iterrows():
        rows.append(";".join([_cell(r["site"]), _cell(r["location_groundmeas"]), _cell(r["latitude"], 6, comma),
                              _cell(r["longitude"], 6, comma), _cell(r["asset_type"]),
                              _cell(r["voltage_level_kV"], 3, comma), _cell(r["distance_to_substation_m"], 1, comma),
                              _cell(r["operator"]), _cell(r["remark"])]))
    with open(target, "w", encoding="utf-8-sig", newline="\n") as f:
        f.write(rows[0] + "\n" + _COMMENTS[lay.language] + "\n".join(rows[1:]) + ("\n" if len(rows) > 1 else ""))
    return target


def hints(sites: Sites, campaign_folder) -> List[str]:
    """Folders in ``raw`` without a line in the sites file (e.g. added later) → hints."""
    if sites.path is None:
        return []
    missing = [m for m in _sites_in_folder(campaign_folder) if sites.for_site(m) is None]
    return [tr("sites.missing_row", file=os.path.basename(sites.path), site=m) for m in missing] + list(sites.hints)
