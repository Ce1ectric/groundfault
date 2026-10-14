# -*- coding: utf-8 -*-
"""Folder layout: detection from work folders, campaign folders and files inside campaigns – the distinctive German
names count wherever they appear, the generic English names in parent folders only on the path – the work folder
of a notebook with its layout, and the errors for unknown layout and language names."""
import os

from groundfault import demo, layout
from groundfault.layout import ENGLISH, GERMAN


def _folders(base, *rel):
    for r in rel:
        os.makedirs(os.path.join(str(base), r), exist_ok=True)


def test_new_folder_below_generic_english_names(tmp_path):
    """A new, empty work folder below a folder with ``results``, ``notes`` and ``raw`` (a home or project folder) is
    no campaign: no layout is detected, and the notebook uses the layout of its language."""
    _folders(tmp_path, "results", "notes", "raw", "new/work")
    (tmp_path / "register.csv").write_text("path\n", encoding="utf-8")
    new = tmp_path / "new" / "work"
    assert layout._find_layout(new) is None and layout._find_layout(new / "x.cfg") is None
    assert layout.detect_layout(new, default="de") is GERMAN
    assert layout.campaign_root(new / "x.cfg", ENGLISH) is None
    assert layout.find_work_folder(new, default="de") == (str(new), GERMAN)
    assert layout.find_work_folder(new, default="en") == (str(new), ENGLISH)


def test_english_campaign_from_its_folders_and_files(tmp_path):
    d = demo.make_campaign(str(tmp_path), layout="en", groundmeas=False)
    camp = d["campaign"]
    cfg = os.path.join(camp, d["substation"][0]["cfg"])
    result = ENGLISH.result_path(camp, "SUB_0_10_000kHz")
    for p in (tmp_path, os.path.join(str(tmp_path), "campaigns"), camp, cfg, result,
              os.path.join(camp, "notes", "corrections.csv"), os.path.join(camp, "figures", "SUB_0", "x.png")):
        assert layout.detect_layout(p, default="de") is ENGLISH, p
    for p in (camp, cfg, result, os.path.join(camp, "README.md")):
        assert layout.campaign_root(p) == camp, p
    assert layout.campaign_root(tmp_path) is None
    # a campaign folder outside a campaigns folder
    _folders(tmp_path, "single/raw/SUB/RMS_10Hz", "single/notes")
    rec = tmp_path / "single" / "raw" / "SUB" / "RMS_10Hz" / "x.cfg"
    assert layout.detect_layout(rec, default="de") is ENGLISH
    assert layout.campaign_root(rec) == str(tmp_path / "single")


def test_german_names_count_next_to_the_path(tmp_path):
    d = demo.make_campaign(str(tmp_path), layout="de", groundmeas=False)
    camp = d["campaign"]
    _folders(tmp_path, "Notebooks")
    assert layout.detect_layout(tmp_path / "Notebooks") is GERMAN          # campaigns folder in the folder above
    assert layout.detect_layout(os.path.join(camp, "Fotos", "x.jpg")) is GERMAN
    assert layout.campaign_root(os.path.join(camp, "Fotos", "x.jpg")) == camp
    assert layout.campaign_root(GERMAN.result_path(camp, "measurement")) == camp


def test_work_folder_and_its_layout_from_the_campaigns_folder(tmp_path):
    _folders(tmp_path, "campaigns", "notebooks/old")
    start = tmp_path / "notebooks" / "old"
    assert layout.find_work_folder(start, default="de") == (str(tmp_path), ENGLISH)
    _folders(tmp_path, "01_Messkampagnen")                                 # both: the layout of default wins
    assert layout.find_work_folder(start, default="de") == (str(tmp_path), GERMAN)
    assert layout.find_work_folder(start, default="en") == (str(tmp_path), ENGLISH)
    cwd = os.getcwd()
    try:
        os.chdir(str(start))
        assert layout.find_work_folder(default="de") == (str(tmp_path), GERMAN)
    finally:
        os.chdir(cwd)


def test_unknown_layout_and_language_in_the_output_language():
    """An unknown layout or language name raises a ValueError whose message follows the output language; an
    unsupported GROUNDFAULT_LANGUAGE falls back to English at import."""
    import subprocess
    import sys

    import pytest

    from groundfault import i18n
    with i18n.language("en"):
        with pytest.raises(ValueError, match=r"^unknown layout 'fr' \(known: en, de\)$"):
            layout.get_layout("fr")
        with pytest.raises(ValueError, match=r"^unsupported language 'french' \(supported: en, de\)$"):
            i18n.normalize_language("french")
    with i18n.language("de"):
        with pytest.raises(ValueError, match=r"^unbekannte Ordnerstruktur 'fr' \(bekannt: en, de\)$"):
            layout.get_layout("fr")
        with pytest.raises(ValueError, match=r"^nicht unterstützte Sprache 'french' \(unterstützt: en, de\)$"):
            i18n.set_language("french")
        assert i18n.get_language() == "de"                                  # unchanged after the error
    assert i18n.normalize_language("de-AT") == "de" and i18n.normalize_language("English") == "en"
    assert [k for lang in ("en", "de") for k in i18n.missing_keys(lang) if k.startswith(("layout.", "i18n."))] == []
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    for value, expected in (("klingon", "en"), ("de_DE", "de"), ("", "en")):
        env = dict(os.environ, GROUNDFAULT_LANGUAGE=value, PYTHONPATH=src)
        out = subprocess.run([sys.executable, "-c", "from groundfault import i18n; print(i18n.get_language())"],
                             env=env, capture_output=True, text=True, check=True).stdout.strip()
        assert out == expected, value
