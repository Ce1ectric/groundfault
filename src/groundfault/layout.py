# -*- coding: utf-8 -*-
"""Folder layout of measurement campaigns.

groundfault organises staged earth fault tests in campaigns: one folder per campaign with sub-folders for notes,
raw recordings, results, figures, the report and media. Two layouts are supported and detected automatically:

==================  ======================  ============================
item                English (``"en"``)      German (``"de"``)
==================  ======================  ============================
campaigns folder    ``campaigns``           ``01_Messkampagnen``
notes               ``notes``               ``0_Notizen``
raw recordings      ``raw``                 ``1_Rohdaten``
results             ``results``             ``2_Auswertung``
figures             ``figures``             ``3_Abbildungen``
report              ``report``              ``4_Bericht``
media               ``media``               ``5_Medien``
corrections         ``corrections.csv``     ``Korrekturen.csv``
measurement sites   ``sites.csv``           ``Messorte.csv``
free notes          ``notes.txt``           ``Notizen_Messung.txt``
register            ``register.csv``        ``Messregister.csv``
campaign read-me    ``README.md``           ``LIESMICH.md``
result file         ``<name>_result.json``  ``<name>_ergebnis.json``
==================  ======================  ============================

The layout also decides the language of the column headers in the CSV files groundfault writes there (readers
accept both).

Detection ([`detect_layout`][groundfault.layout.detect_layout], [`campaign_root`][groundfault.layout.campaign_root])
relies on the folder names. The German names are distinctive and count wherever they appear in the path or next to it.
The English names (``notes``, ``raw``, ``results``, ``campaigns`` …) are common words: in a parent folder they count
only if the path runs through them (the path lies inside that campaign or campaigns folder), never because a folder of
that name happens to sit next to the path. [`find_work_folder`][groundfault.layout.find_work_folder] gives the work
folder of a notebook and its layout from the name of its campaigns folder alone.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Tuple, Union

from . import i18n
from .i18n import tr

__all__ = ["CampaignLayout", "ENGLISH", "GERMAN", "LAYOUTS", "get_layout", "set_default_layout",
           "default_layout", "detect_layout", "campaign_root", "find_work_folder"]


@dataclass(frozen=True)
class CampaignLayout:
    """Names of the folders and files of a campaign (see the module documentation)."""

    language: str
    campaigns: str
    notes: str
    raw: str
    results: str
    figures: str
    report: str
    media: str
    corrections_file: str
    sites_file: str
    notes_file: str
    register_file: str
    readme_file: str
    result_suffix: str = "_result.json"

    def campaign_folders(self) -> tuple:
        """Sub-folders created in a new campaign."""
        return (self.notes, self.raw, self.results, self.figures, self.report, self.media)

    def result_path(self, campaign_folder, measurement: str) -> str:
        """Path of the result file of a measurement: ``<campaign>/<results>/<measurement>/<measurement><suffix>``."""
        return os.path.join(str(campaign_folder), self.results, measurement, measurement + self.result_suffix)


ENGLISH = CampaignLayout("en", "campaigns", "notes", "raw", "results", "figures", "report", "media",
                         "corrections.csv", "sites.csv", "notes.txt", "register.csv", "README.md")
"""The English folder layout (``campaigns/<campaign>/notes|raw|results|figures|report|media``)."""
GERMAN = CampaignLayout("de", "01_Messkampagnen", "0_Notizen", "1_Rohdaten", "2_Auswertung", "3_Abbildungen",
                        "4_Bericht", "5_Medien", "Korrekturen.csv", "Messorte.csv", "Notizen_Messung.txt",
                        "Messregister.csv", "LIESMICH.md", "_ergebnis.json")
"""The German folder layout (``01_Messkampagnen/<Kampagne>/0_Notizen|1_Rohdaten|2_Auswertung|…``)."""
LAYOUTS = {"en": ENGLISH, "de": GERMAN}
"""The layouts by language code."""

_default: CampaignLayout = ENGLISH

i18n.register({
    "layout.unknown_layout": {
        "en": "unknown layout {layout!r} (known: {known})",
        "de": "unbekannte Ordnerstruktur {layout!r} (bekannt: {known})"},
})


def get_layout(layout: Union[str, CampaignLayout, None]) -> CampaignLayout:
    """Layout by name (``"en"``/``"de"``; ``"english"``, ``"Deutsch"`` … by their first two letters) or the default
    layout for ``None``; a [`CampaignLayout`][groundfault.layout.CampaignLayout] is returned as it is.

    Raises
    ------
    ValueError
        For an unknown name (message in the output language).
    """
    if layout is None:
        return _default
    if isinstance(layout, CampaignLayout):
        return layout
    key = str(layout).strip().lower()[:2]
    if key not in LAYOUTS:
        raise ValueError(tr("layout.unknown_layout", layout=layout, known=", ".join(LAYOUTS)))
    return LAYOUTS[key]


def set_default_layout(layout: Union[str, CampaignLayout]) -> None:
    """Layout used for new campaigns when nothing can be detected."""
    global _default
    _default = get_layout(layout)


def default_layout() -> CampaignLayout:
    """Layout used for new campaigns when nothing can be detected (see
    [`set_default_layout`][groundfault.layout.set_default_layout])."""
    return _default


def _markers(lay: CampaignLayout):
    return (lay.notes, lay.raw, lay.results, lay.campaigns)


def _shows(folder: str, lay: CampaignLayout, child: Optional[str]) -> bool:
    """True if ``folder`` points to the layout ``lay``: it contains one of the marker folders or the register file.
    In a parent folder (``child``: the folder the path runs through) the generic English names count only if the path
    runs through the campaigns folder or a campaign sub-folder itself."""
    if child is not None and lay is not GERMAN:
        return child in lay.campaign_folders() or child == lay.campaigns
    return any(os.path.isdir(os.path.join(folder, m)) for m in _markers(lay)) or \
        os.path.isfile(os.path.join(folder, lay.register_file))


def detect_layout(path: Union[str, os.PathLike, None], default: Union[str, CampaignLayout, None] = None
                  ) -> CampaignLayout:
    """Layout of a campaign folder, the folder above the campaigns, or a file inside a campaign.

    German folder names in the path decide at once. Otherwise the folder itself (for a file: its folder) and up to
    three parent folders are checked for the typical sub-folders and the register file: the distinctive German names
    (``0_Notizen``, ``1_Rohdaten``, ``2_Auswertung``, ``01_Messkampagnen``, ``Messregister.csv``) everywhere, the
    English names (``notes``, ``raw``, ``results``, ``campaigns``, ``register.csv``) in the folder itself; in a parent
    folder only the campaigns folder or a campaign sub-folder (``notes``, ``raw``, ``results``, ``figures``,
    ``report``, ``media``) that the path runs through counts – a folder ``results`` next to the path is no sign of a
    campaign. Without a hit the ``default`` (or the default layout) is returned.

    Parameters
    ----------
    path : str or path-like or None
        A work folder, a campaign folder, or a file or folder inside a campaign.
    default : str or CampaignLayout, optional
        Layout returned when nothing points to a layout (None: [`default_layout`][groundfault.layout.default_layout]).

    Returns
    -------
    CampaignLayout
    """
    if path is None:
        return get_layout(default)
    found = _find_layout(path)
    return found if found is not None else get_layout(default)


def _find_layout(path: Union[str, os.PathLike]) -> Optional[CampaignLayout]:
    """Layout detected from ``path`` as in [`detect_layout`][groundfault.layout.detect_layout], or None if nothing
    points to a layout."""
    p = os.path.abspath(str(path))
    parts = set(p.replace("\\", "/").split("/"))
    if parts & {GERMAN.notes, GERMAN.raw, GERMAN.campaigns, GERMAN.results}:     # distinctive German names
        return GERMAN
    q = p if os.path.isdir(p) else os.path.dirname(p)
    child = None
    for _ in range(4):
        for lay in (GERMAN, ENGLISH):
            if _shows(q, lay, child):
                return lay
        parent = os.path.dirname(q)
        if parent == q:
            break
        child, q = os.path.basename(q), parent
    return None


def campaign_root(path: Union[str, os.PathLike], layout: Optional[CampaignLayout] = None) -> Optional[str]:
    """Campaign folder that contains ``path`` (a file or folder inside the campaign), or None.

    The campaign folder is the folder itself (for a file: its folder) or a parent folder with the notes or raw-data
    folder of the layout. For the English layout a parent folder counts only if the path runs through one of its
    campaign sub-folders (``notes``, ``raw``, ``results`` …), as in [`detect_layout`][groundfault.layout.detect_layout].
    """
    lay = layout or detect_layout(path)
    p = os.path.abspath(str(path))
    q = p if os.path.isdir(p) else os.path.dirname(p)
    child = None
    for _ in range(6):
        if child is not None and lay is not GERMAN:
            if child in lay.campaign_folders():
                return q
        elif any(os.path.isdir(os.path.join(q, m)) for m in (lay.notes, lay.raw)):
            return q
        parent = os.path.dirname(q)
        if parent == q:
            break
        child, q = os.path.basename(q), parent
    return None


def find_work_folder(start: Union[str, os.PathLike, None] = None, default: Union[str, CampaignLayout, None] = None
                     ) -> Tuple[str, CampaignLayout]:
    """Work folder of a notebook or script and its layout.

    The work folder is the first folder – ``start`` or one of its parents – that contains a campaigns folder
    (``campaigns`` or ``01_Messkampagnen``); its layout is the layout of that campaigns folder (if it contains both,
    the layout of ``default`` wins). Without a campaigns folder ``start`` is the work folder and its layout is
    ``default``: other folders above it (``results``, ``raw`` …) are not used, so a new, empty folder always gets the
    layout of ``default``.

    Parameters
    ----------
    start : str or path-like, optional
        Folder to start from (default: the current folder).
    default : str or CampaignLayout, optional
        Layout without a campaigns folder, and the preferred one if there are both (None:
        [`default_layout`][groundfault.layout.default_layout]).

    Returns
    -------
    folder : str
        Absolute path of the work folder.
    layout : CampaignLayout
        Its layout.

    Examples
    --------
    >>> folder, lay = find_work_folder(default="de")                     # doctest: +SKIP
    >>> lay.campaigns                                                     # doctest: +SKIP
    '01_Messkampagnen'
    """
    first = get_layout(default)
    order = (first,) + tuple(lay for lay in LAYOUTS.values() if lay is not first)
    q = os.path.abspath(str(start) if start is not None else os.getcwd())
    folder = q
    while True:
        for lay in order:
            if os.path.isdir(os.path.join(q, lay.campaigns)):
                return q, lay
        parent = os.path.dirname(q)
        if parent == q:
            return folder, first
        q = parent
