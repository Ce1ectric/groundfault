# -*- coding: utf-8 -*-
"""Result files of the predecessor tool: translation of keys and codes (synthetic files), campaign and site of old
files without them from their path, and the entry tag of the groundmeas export of such a file."""
import copy
import json
import os
import sqlite3

import pytest

import groundfault as gf
from groundfault import Intervals, corrections, demo, detect_roles, earthing, evaluate, i18n, legacy, open_recording


def test_meta_corrections_settings_and_codes_translated():
    old = {"format": "erdschluss-ergebnis", "version": 2,
           "meta": {"zeitstempel": "2026-01-15T10:00:00", "werkzeug": "erdschluss 1.5.0", "messung": "SUB_0_10_000kHz",
                    "kampagne": "2026-01-15_Demo", "messort": "SUB",
                    "korrekturen": [{"kanal": "REC 1_Currents_IC1 Inst", "kurz": "IC1", "faktor": 2.0,
                                     "faktor_gesamt": 2.0, "bemerkung": "clamp around one of two conductors",
                                     "quelle": "notes/corrections.csv, line 3"}]},
           "messung": {"fenster": "hann_periodisch", "dc_methode": "mittel",
                       "f1": {"methode": "spektral", "methode_vergleich": "phase"},
                       "ausrichtung": {"dt_s": 0.5, "rollen": ["u_hs_l1e", "u_l2e"], "kanaele": ["U3"]},
                       "einstellungen": {"fenster": "rechteck", "dc": "keine", "f1_methode": "spektral",
                                         "thd_bezug": "mittel", "trafo_spannung": "hs"}},
           "werte": {"IRES": 56.5, "faktor_gl7": 1.25, "plaus_gl3_alle": 0.98, "plaus_gl3_auswahl": 0.99},
           "tabellen": {"bewertungsgroessen": [{"Groesse": "UTHD_mess", "Messwert": 2.1, "Einheit": "%"}]}}
    d = legacy.translate_result(old)
    assert d["meta"] == {"start_time": "2026-01-15T10:00:00", "tool": "erdschluss 1.5.0",
                         "measurement": "SUB_0_10_000kHz", "campaign": "2026-01-15_Demo", "site": "SUB",
                         "corrections": [{"channel": "REC 1_Currents_IC1 Inst", "short": "IC1", "factor": 2.0,
                                          "factor_total": 2.0, "remark": "clamp around one of two conductors",
                                          "source": "notes/corrections.csv, line 3"}]}
    m = d["measurement"]
    assert (m["window"], m["dc_method"]) == ("hann_periodic", "mean")
    assert m["f1"] == {"method": "spectral", "method_comparison": "phase"}
    assert m["alignment"] == {"dt_s": 0.5, "roles": ["u_hv_l1e", "u_l2e"], "channels": ["U3"]}
    assert m["settings"] == {"window": "rectangular", "dc": "none", "f1_method": "spectral", "thd_reference": "mean",
                             "transformer_voltage": "hv"}
    assert d["values"] == {"IRES": 56.5, "factor_scaling": 1.25, "plaus_harmonic_all": 0.98,
                           "plaus_harmonic_selection": 0.99}
    assert d["tables"]["assessment_quantities"][0]["quantity"] == "UTHD_meas"
    assert d["format"] == "erdschluss-ergebnis"


def test_keys_with_formula_numbers_translated_by_pattern():
    """Predecessor keys that carry the number of a formula are read whatever the number: the scaling factor of the
    harmonic content and its plausibility values (all orders, selected orders); other keys stay unchanged."""
    for key, new in (("faktor_gl12", "factor_scaling"), ("plaus_gl4_alle", "plaus_harmonic_all"),
                     ("plaus_gl31_auswahl", "plaus_harmonic_selection"), ("faktor_glx", "faktor_glx"),
                     ("plaus_gl4_andere", "plaus_gl4_andere"), ("factor_scaling", "factor_scaling")):
        assert legacy.translate_key(key) == new
    assert legacy.translate_columns(["faktor_gl5", "Messwert"]) == ["factor_scaling", "measured_value"]


def test_translation_leaves_current_names_unchanged():
    new = {"format": "groundfault-result", "meta": {"campaign": "2026-01-15_Demo", "site": "SUB",
                                                    "corrections": [{"source": "x", "factor": 2.0}]},
           "measurement": {"window": "hann", "dc_method": "median", "f1": {"method": "phase"},
                           "alignment": {"dt_s": 0.5, "roles": ["u_l1e"], "channels": ["U1"]}},
           "values": {"factor_scaling": 1.1}}
    t = legacy.translate_result(new)
    t["format"] = new["format"]
    assert t == new


# ---------------------------------------------------------------------------------------------- files in a campaign
@pytest.fixture(scope="module")
def station(tmp_path_factory):
    """German demo campaign with the station evaluated by groundfault (result in memory and as JSON content)."""
    d = demo.make_campaign(str(tmp_path_factory.mktemp("legacy")), layout="de")
    st, camp = d["station"], d["campaign"]
    b = st["intervals"]
    rec = open_recording(os.path.join(camp, st["cfg"]))
    corr = corrections.load(camp)
    corr.apply(rec)
    rec.set_correction(rec.channel_names[0], 1.0, remark="checked", source="0_Notizen/Korrekturen.csv, Zeile 3")
    roles = detect_roles(rec.channel_names, rec.units, corr.role_overrides(rec), corr.main_channel(rec),
                         corr.distances(rec))
    res = evaluate(rec, Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]), tuple(b["post_fault"])), roles=roles)
    return d, res, json.loads(json.dumps(res.result_set, default=str))


def _predecessor_file(content, folder, name, campaign=True, site=True):
    """The result as the predecessor wrote it: format tag and German keys of the section meta (an early version
    wrote neither the campaign nor the site); the rest of the structure is translated alike."""
    d = copy.deepcopy(content)
    meta = d.pop("meta")
    d.update(format=legacy.LEGACY_RESULT_FORMAT, version=2)
    d["meta"] = {"zeitstempel": meta["start_time"], "werkzeug": "erdschluss 1.0.0", "messung": meta["measurement"],
                 "korrekturen": [{"kanal": c["channel"], "kurz": c["short"], "faktor": c["factor"],
                                  "faktor_gesamt": c["factor_total"], "bemerkung": c["remark"], "quelle": c["source"]}
                                 for c in meta.get("corrections", [])]}
    if campaign:
        d["meta"]["kampagne"] = meta["campaign"]
    if site:
        d["meta"]["messort"] = meta["site"]
    path = os.path.join(folder, "2_Auswertung", name, name + "_ergebnis.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    return path


def test_predecessor_file_keeps_its_campaign_and_is_recognised_as_own_entry(station, tmp_path):
    """The campaign of an old file gives the entry tag; an entry the predecessor made counts as the own entry and
    can be renewed."""
    d, res, content = station
    name = res.name
    path = _predecessor_file(content, d["campaign"], name)
    old = gf.load_result(path)
    assert old.data["meta"]["campaign"] == "2026-01-15_Demo" and old.data["meta"]["site"] == "Station_Elm_Road"
    assert old.data["meta"]["corrections"][0]["source"] == content["meta"]["corrections"][0]["source"]
    db = str(tmp_path / "gm.db")
    with open(d["db"], "rb") as f_in, open(db, "wb") as f_out:
        f_out.write(f_in.read())
    first = earthing.export_to_groundmeas(res, d["campaign"], db, write=True)
    assert first["written"] and first["entry_tag"] == "[groundfault 2026-01-15_Demo/%s]" % name
    con = sqlite3.connect(db)                      # the entry as the predecessor tool tagged it
    con.execute("update measurement set description = replace(description, '[groundfault ', '[erdschluss ') "
                "where id = ?", (first["measurement_id"],))
    con.commit(); con.close()
    plan = earthing.export_to_groundmeas(old, d["campaign"], db, existing="replace", backup=first["backup"])
    assert plan["entry_tag"] == "[groundfault 2026-01-15_Demo/%s]" % name
    assert plan["own_id"] == first["measurement_id"] and plan["writable"]
    assert plan["location"] == "Station Elm Road"


def test_campaign_and_site_of_an_early_file_from_its_path(station, tmp_path):
    """Files of early versions name neither the campaign nor the site: inside a campaign both come from the path
    (the site from the folder of the recording); the plan uses the location of the sites file."""
    d, res, content = station
    path = _predecessor_file(content, d["campaign"], res.name + "_early", campaign=False, site=False)
    old = gf.load_result(path)
    assert old.data["meta"]["campaign"] == "2026-01-15_Demo" and old.data["meta"]["site"] == "Station_Elm_Road"
    plan = earthing.export_to_groundmeas(old, d["campaign"], d["db"])
    assert plan["location"] == "Station Elm Road" and not any("None" in h for h in plan["hints"])
    # outside a campaign nothing is guessed – the hint says that the site is unknown
    outside = _predecessor_file(content, str(tmp_path), res.name, campaign=False, site=False)
    alone = gf.load_result(outside)
    assert "campaign" not in alone.data["meta"] and "site" not in alone.data["meta"]
    plan = earthing.export_to_groundmeas(alone, d["campaign"], d["db"])
    assert any(h.startswith("Das Ergebnis nennt keinen Messort") for h in plan["hints"])
    assert not any("None" in h for h in plan["hints"])


# ---------------------------------------------------------------------------------------------- options
def test_check_option_and_check_keys_messages():
    """Options are English: an unknown value raises with the allowed values, a former value of the predecessor
    also with its current name – but only where that name is allowed."""
    assert legacy.check_option("existing", "replace", ("skip", "replace")) == "replace"
    assert legacy.check_option("window", "rect", ("hann", "rectangular"), aliases=("rect",)) == "rect"
    with i18n.language("en"):
        with pytest.raises(ValueError, match=r"^GROUNDMEAS_EXPORT='ersetzen' is not allowed – allowed: False, True, "
                                             r"'replace' \('ersetzen' is the former name of 'replace'\)$"):
            legacy.check_option("GROUNDMEAS_EXPORT", "ersetzen", (False, True, "replace"))
        with pytest.raises(ValueError, match=r"^method='spektral' is not allowed – allowed: 'equation_error', "
                                             r"'output_error'$"):                 # 'spectral' is no choice here
            legacy.check_option("method", "spektral", ("equation_error", "output_error"))
        with pytest.raises(ValueError, match=r"^polarity=True is not allowed"):  # True is not taken for 1
            legacy.check_option("polarity", True, ("auto", 1, -1))
        with pytest.raises(ValueError, match=r"^RESISTIVE: unknown key 'aus_ll' – allowed: 'U_thd95_V', 'from_ll' "
                                             r"\('aus_ll' is the former name of 'from_ll'\)$"):
            legacy.check_keys("RESISTIVE", dict(U_thd95_V=300.0, aus_ll=True), ("U_thd95_V", "from_ll"))
    with pytest.raises(ValueError, match=r"^MEASUREMENTS: unbekannter Schlüssel 'messung' – zulässig: 'name', "
                                         r"'measurement' \('messung' ist der frühere Name von 'measurement'\)$"):
        legacy.check_keys("MEASUREMENTS", dict(name="M1", messung="SUB_0"), ("name", "measurement"))
    legacy.check_keys("RESISTIVE", dict(from_ll=True), ("U_thd95_V", "from_ll"))
    assert legacy.check_option("GROUNDMEAS_EXPORT", 1, (False, True, "replace")) == 1     # 1 counts as True


def test_result_file_of_groundfault_2_0_gets_the_current_column_names(tmp_path):
    """Result files of groundfault 2.0 (format version 3) call U_E/I_F of the fault test ``Z_E_fault_Ohm``; read with
    3.0 the tables carry the r·Z_E names (``rZE_fault_Ohm`` …), other columns stay as they are."""
    old = {"format": legacy.RESULT_FORMAT, "version": 3, "meta": {"measurement": "Station_A_10_000kHz"},
           "tables": {"station_lv_network": [{"channel": "UE_70m", "order": 1, "Z_E_LV_Ohm": 0.9,
                                              "Z_E_fault_Ohm": 0.05, "Z_LV_to_Z_E_fault": 18.0,
                                              "Z_total_fault_Ohm": 0.06}],
                      "station_lv_network_eff": [{"channel": "UE_70m", "Z_E_fault_eff_Ohm": 0.05,
                                                  "Z_total_fault_eff_Ohm": 0.06}]}}
    p = tmp_path / "Station_A_10_000kHz_result.json"
    p.write_text(json.dumps(old), encoding="utf-8")
    res = gf.load_result(str(p))
    lv = res.table("station_lv_network")
    assert list(lv.columns) == ["channel", "order", "Z_E_LV_Ohm", "rZE_fault_Ohm", "Z_LV_to_rZE_fault",
                                "Z_E_earth_current_Ohm"]
    assert list(res.table("station_lv_network_eff").columns) == ["channel", "rZE_fault_eff_Ohm",
                                                                 "Z_E_earth_current_eff_Ohm"]
    current = dict(old, version=legacy.RESULT_VERSION)               # a current file is not changed
    assert legacy.update_result(current) == current
    # the predecessor's German names lead to the current names as well
    assert legacy.translate_key("Z_E_Erdschluss_Ohm") == "rZE_fault_Ohm"
    assert legacy.translate_key("UE_je_A_Erdungsstrom") == "Z_E_earth_current_Ohm"
