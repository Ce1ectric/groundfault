# -*- coding: utf-8 -*-
"""Measurement sites per campaign (sites file, here in the German layout ``0_Notizen/Messorte.csv``) and export to
groundmeas: reading and checking the file, template from groundmeas, choice of the location (existing location, new
location only with coordinates), conventions of the entries (nominal frequency, units, asset type, distance to the
substation), substation measurements, uncertain values, recognising and renewing own entries, one backup copy per
run, messages in English – all on synthetic databases with the groundmeas schema."""
import hashlib
import os
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from groundfault import Intervals, demo, earthing, i18n, open_recording, evaluate, sites, units
from test_earthing import DDL, _z


def _md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def _db(path, locations=(), measurements=()):
    """locations: [(id, name, latitude, longitude)], measurements: [(id, location_id, method, timestamp, description,
    [items])]."""
    con = sqlite3.connect(path)
    for d in DDL:
        con.execute(d)
    for oid, name, b, l in locations:
        con.execute("insert into location (id, name, latitude, longitude) values (?, ?, ?, ?)", (oid, name, b, l))
    for mid, oid, meth, ts, descr, items in measurements:
        con.execute("insert into measurement (id, timestamp, location_id, method, voltage_level_kv, asset_type, "
                    "operator, description) values (?, ?, ?, ?, 20.0, ?, 'Grid Operator GmbH', ?)",
                    (mid, ts, oid, meth, "substation" if "UW" in str(descr) else "mv_lv_earthing_system", descr))
        for it in items:
            sp = ["measurement_id"] + list(it)
            con.execute("insert into measurementitem (%s) values (%s)" % (", ".join(sp), ", ".join("?" * len(sp))),
                        [mid] + list(it.values()))
    con.commit(); con.close()
    return path


def _csv(cfolder, text):
    p = cfolder / "0_Notizen" / "Messorte.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8-sig")
    return p


HEADER = "Messort;Ort_groundmeas;Breite;Laenge;Anlagentyp;Spannungsebene_kV;Entfernung_UW_m;Betreiber;Bemerkung\n"


# ---------------------------------------------------------------------------------------------- sites file
def test_read_and_check_sites_file(tmp_path):
    _csv(tmp_path, HEADER + "# comment\nStation_Ashdown;Ashdown;51,15;10,25;mv_lv_earthing_system;20;"
                            "12.500;Grid Services AG;remark; with; semicolons\nUW;UW Demo;51.4;10.5;;;;;\n")
    m = sites.load(tmp_path)
    assert len(m) == 2 and m.path.endswith("Messorte.csv")
    g = m.for_site("station_ashdown")                                          # case does not matter
    assert (g.location, g.latitude, g.longitude, g.voltage_level_kv) == ("Ashdown", 51.15, 10.25, 20.0)
    assert g.distance_to_substation_m == 12500.0                             # thousands separator for metres
    assert g.remark == "remark; with; semicolons" and g.line == 3
    u = m.for_site("UW")
    assert u.coordinates and u.asset_type == "" and u.voltage_level_kv is None and m.for_site("UW_Trafo") is None
    assert list(m.table().columns)[:3] == ["line", "site", "location_groundmeas"]
    _csv(tmp_path, HEADER + "UW;UW X;10,30;51,20;;;;;\n")                     # swapped? only a hint
    assert any("vertauscht" in h for h in sites.hints(sites.load(tmp_path), tmp_path))
    for line, fault in (("UW;UW X;95;9;;;;;", "Wertebereich"),
                        ("UW;UW X;51,2;;;;;;", "nur zusammen"), ("UW;UW X;;;umspannwerk;;;;", "Anlagentyp"),
                        ("UW;UW X;;;;zwanzig;;;", "keine Zahl")):
        _csv(tmp_path, HEADER + line + "\n")
        with pytest.raises(ValueError, match=fault):
            sites.load(tmp_path)
    _csv(tmp_path, HEADER + "UW;A;;;;;;;\nuw;B;;;;;;;\n")
    with pytest.raises(ValueError, match="schon in Zeile"):
        sites.load(tmp_path)
    assert len(sites.load(tmp_path / "missing")) == 0 and sites.load(tmp_path / "missing").path is None


@pytest.mark.parametrize("path,site", [("1_Rohdaten/UW/RMS_10Hz/UW_0_10_000Hz.cfg", "UW"),
                                       ("1_Rohdaten/Station_A/Station_A_40_000kHz.cfg", "Station_A"),
                                       ("Station_X/file.cfg", "Station_X")])
def test_site_from_path(path, site):
    assert sites.site_from_path(path) == site


def _example(tmp_path):
    """groundmeas as in practice: duplicate location rows, the earthing measurement at one of them, an entry taken
    from a report at another."""
    fault_test = [_z("earth_fault_current", 30.0, 50.0, "A", 0.0, distance_to_current_injection_m=4000.0),
                  _z("earth_potential_rise", 1.8, 50.0, "V", 0.0, 40.0, distance_to_current_injection_m=4000.0)]
    inj = [_z("earthing_current", 0.2, 50.0, "A", 0.0), _z("earthing_impedance", 0.3, 50.0, "Ohm", 40.0, 40.0)]
    return _db(str(tmp_path / "gm.db"),
               locations=[(2, "Lindenweg", 51.1, 10.2), (4, "UW Southdale", 51.05, 10.15),
                          (5, "Lindenweg", 51.1001, 10.2001), (6, "Lindenweg", None, None),
                          (7, "Ashdown", 51.15, 10.25)],
               measurements=[(2, 2, "injection_earth_electrode", "2026-01-10 10:00:00", "invented injection", inj),
                             (5, 4, "staged_fault_test", "2026-01-12 09:00:00", "invented test at the UW", []),
                             (8, 5, "staged_fault_test", "2026-01-12 09:20:00", "invented station test",
                              fault_test)])


def test_location_rows_prefer_the_earthing_measurement(tmp_path):
    db = _example(tmp_path)
    con = sqlite3.connect(db)
    z = earthing.location_rows(con, "lindenweg")
    assert [x["id"] for x in z] == [2, 5, 6]       # coordinates + earthing measurement, latest, without coordinates
    assert z[0]["injection"] and not z[2]["coordinates"] and z[0]["all_ids"] == [2, 5, 6]
    assert earthing.location_rows(con, "Äshdown") == [] and earthing.location_rows(con, "") == []   # Ä is not A
    assert earthing.location_rows(con, "Aeshdown") == []
    con.close()


def test_template_from_groundmeas_and_never_overwritten(tmp_path):
    db = _example(tmp_path)
    k = tmp_path / "01_Messkampagnen" / "2026-01-15_Southdale"
    for o in ("Station_Lindemweg", "UW", "UW_Trafo", "PQ_measurement"):
        (k / "1_Rohdaten" / o).mkdir(parents=True)
    before = _md5(db)
    p = sites.write_template(k, db)
    assert p and _md5(db) == before                                       # groundmeas is only read
    m = sites.load(k)
    assert [e.site for e in m.entries] == ["Station_Lindemweg", "UW", "UW_Trafo"]     # without PQ_measurement
    s = m.for_site("Station_Lindemweg")
    assert (s.location, s.latitude, s.longitude) == ("Lindenweg", 51.1, 10.2)        # row of the earthing measurement
    assert s.asset_type == "mv_lv_earthing_system" and s.voltage_level_kv == 20.0 and s.operator == "Grid Operator GmbH"
    assert s.distance_to_substation_m == 4000.0 and "Ort 2" in s.remark and "Lindemweg" in s.remark
    u = m.for_site("UW")
    assert (u.location, u.asset_type, u.latitude) == ("UW Southdale", "substation", 51.05)
    assert u.distance_to_substation_m is None
    text = Path(p).read_text(encoding="utf-8-sig")
    assert ";51,1;10,2;" in text and text.startswith("Messort;Ort_groundmeas")
    assert sites.write_template(k, db) is None                     # an existing file stays
    assert Path(p).read_text(encoding="utf-8-sig") == text
    # without a database: location name from the folder, the substation from the campaign name
    k2 = tmp_path / "2026-01-15_Northtown"
    (k2 / "1_Rohdaten" / "UW").mkdir(parents=True)
    (k2 / "1_Rohdaten" / "Station_Ashdown").mkdir()
    vs = sites.suggest(k2, str(tmp_path / "missing.db"))
    assert vs.set_index("site").loc["UW", "location_groundmeas"] == "UW Northtown"
    assert vs.set_index("site").loc["Station_Ashdown", "location_groundmeas"] == "Ashdown"


# ---------------------------------------------------------------------------------------------- export
def _station_res(name="Ashdown_10_000kHz", campaign="2026-01-15_Northtown", site="Station_Ashdown"):
    sp = ["channel", "role", "distance_m", "order", "f_Hz", "I_F_A", "Z_direct_Ohm", "Z_direct_angle_deg",
          "Z_fault_Ohm", "Z_fault_angle_deg", "method_spread_pct", "uncertainty_pct",
          "uncertain"]
    sf = pd.DataFrame([dict(zip(sp, z)) for z in (
        ("UE_70m", "u_e", 70.0, 1, 49.98, 40.0, 0.018, 50.0, 0.016, 30.0, 6.0, 0.5, False),
        ("UE_70m", "u_e", 70.0, 3, 149.94, 5.0, 0.012, -100.0, 0.006, 120.0, 40.0, 4.0, True),
        ("UE_5m", "u_t", 5.0, 1, 49.98, 40.0, 0.012, 50.0, 0.010, 30.0, 6.0, 0.5, False),
        ("UE_5m", "u_t", 5.0, 3, 149.94, 5.0, 0.008, -100.0, 0.004, 125.0, 40.0, 0.5, True),
        ("U1m", "u_t", 1.0, 1, 49.98, 40.0, 0.005, 30.0, 0.006, 30.0, 4.0, 1.0, False))])
    ss = pd.DataFrame([dict(channel="IS", role="i_shield", H1_A=12.0, angle_to_IF_H1_deg=-20.0, H3_A=1.5,
                            angle_to_IF_H3_deg=150.0)])
    return SimpleNamespace(tables={"station_frequency": sf, "station_currents": ss}, name=name,
                           hints=["Station: unsichere Werte – 150 Hz …"], values={"main_channel_i_res": "IF1"},
                           settings=SimpleNamespace(f_nominal=50.0),
                           result_set={"meta": {"start_time": "2026-01-15T10:30:00.250000", "campaign": campaign,
                                                "measurement": name, "site": site, "tool": "groundfault 9.9"},
                                       "measurement": {"z_fault_ohm": None, "f1_hz": 49.98,
                                                       "cfg_file": name + ".cfg"}})


def test_station_conventions_and_uncertain_values(tmp_path):
    db = _example(tmp_path)
    site_ = sites.Site("Station_Ashdown", "Ashdown", 51.15, 10.25, "", 20.0, 9000.0, "Grid Services AG")
    plan = earthing.export_fault_test(db, _station_res(), site=site_)
    w = earthing.plan_items(plan)
    assert plan["writable"] and plan["location_id"] == 7 and not plan["location_new"]
    assert set(w["frequency_hz"]) == {50.0, 150.0}                          # nominal frequencies, not 49.98 Hz
    assert (w["distance_to_current_injection_m"] == 9000.0).all()
    unit_ = w.groupby("measurement_type")["unit"].agg(set).to_dict()        # one well readable unit per type
    assert unit_ == {"earth_fault_current": {"A"}, "earth_potential_rise": {"mV"},
                     "prospective_touch_voltage": {"mV"}, "shield_current": {"A"}}
    assert any("earth_potential_rise in mV" in h and "1.6.1" in h for h in plan["hints"])
    epr = w[w["measurement_type"] == "earth_potential_rise"].set_index(["description", "frequency_hz"])
    assert sorted(set(w[w["measurement_type"] == "earth_potential_rise"]["measurement_distance_m"])) == [5.0, 70.0]
    ut = w[w["measurement_type"] == "prospective_touch_voltage"]
    assert list(ut["measurement_distance_m"]) == [1.0] and "U1m" in ut["description"].iloc[0]
    z70 = w[(w["measurement_type"] == "earth_potential_rise") & (w["measurement_distance_m"] == 70.0)
            & (w["frequency_hz"] == 50.0)].iloc[0]
    assert z70["value"] == pytest.approx(0.016 * 40.0 * 1000) and z70["value_angle_deg"] == pytest.approx(30.0)
    assert units.to_base(z70["value"], z70["unit"]) == pytest.approx(0.016 * 40.0)
    base = earthing.plan_items(earthing.export_fault_test(db, _station_res(), site=site_, units="base"))
    assert set(base["unit"]) == {"A", "V"}
    for (_, a), (_, b) in zip(w.iterrows(), base.iterrows()):                # same values, other unit
        assert units.to_base(a["value"], a["unit"]) == pytest.approx(b["value"], rel=1e-6)
    with pytest.raises(ValueError, match="units"):
        earthing.export_fault_test(db, _station_res(), site=site_, units="SI")
    uncertain = w[w["description"].str.contains("UNCERTAIN")]
    assert set(uncertain["frequency_hz"]) == {150.0} and len(uncertain) == 2
    assert "differ by 40 %" in uncertain["description"].iloc[0]
    assert "uncertainty 0.5 %" in uncertain["description"].iloc[1]
    assert len(epr) == 4
    m = plan["measurement"]
    assert (m["asset_type"], m["voltage_level_kv"], m["operator"], m["fault_resistance_ohm"]) == \
        ("mv_lv_earthing_system", 20.0, "Grid Services AG", None)
    assert m["description"].endswith("[groundfault 2026-01-15_Northtown/Ashdown_10_000kHz]")
    assert "Uncertain fault-related part at 150 Hz (marked in the items)" in m["description"]
    assert "f1 = 49.980 Hz" in m["description"] and "Evaluated with groundfault 9.9" in m["description"]
    s = w[w["measurement_type"] == "shield_current"].set_index("frequency_hz")
    assert s.loc[150.0, "value_angle_deg"] == pytest.approx(150.0)
    i1 = plan["values"][0]
    assert i1["value_real"] == pytest.approx(40.0) and i1["value_imag"] == pytest.approx(0.0)   # as groundmeas
    removed = earthing.export_fault_test(db, _station_res(), site=site_, uncertain_mode="omit")
    ww = earthing.plan_items(removed)
    assert not ww["description"].str.contains("UNCERTAIN").any() and len(ww) == len(w) - 2
    assert (ww["measurement_type"] == "earth_fault_current").sum() == 2                     # the current remains
    assert "(omitted)" in removed["measurement"]["description"]
    with pytest.raises(ValueError, match="uncertain_mode"):
        earthing.export_fault_test(db, _station_res(), site=site_, uncertain_mode="ignore")


def test_new_location_only_with_coordinates(tmp_path):
    db = _example(tmp_path)
    res = _station_res(site="Station_New")
    before = _md5(db)
    plan = earthing.export_fault_test(db, res, "SSt Newfield", dry_run=False)
    assert not plan["written"] and not plan["writable"] and "ohne Koordinaten" in plan["reasons"][0]
    assert _md5(db) == before and earthing.plan_overview({"x": plan})["status"].iloc[0].startswith("nicht möglich")
    similar = earthing.export_fault_test(db, res, "Lindenwg", latitude=51.1, longitude=10.2)
    assert any("„Lindenweg“" in w for w in similar["warnings"])           # typing error? note on the existing location
    plan = earthing.export_fault_test(db, res, "SSt Newfield", latitude=51.3, longitude=10.4, dry_run=False,
                                      backup=False)
    assert plan["written"] and plan["backup"] is None and plan["location_new"]
    con = sqlite3.connect(db)
    assert con.execute("select name, latitude, longitude from location where id = ?",
                       (plan["location_id"],)).fetchone() \
        == ("SSt Newfield", 51.3, 10.4)
    con.close()


def test_existing_location_unchanged_and_coordinate_check(tmp_path):
    db = _example(tmp_path)
    con = sqlite3.connect(db)
    locations_before = con.execute("select * from location order by id").fetchall()
    con.close()
    site_ = sites.Site("Station_Lindemweg", "Lindenweg", 51.111, 10.2)                      # ≈ 1.2 km away
    plan = earthing.export_fault_test(db, _station_res(site="Station_Lindemweg"), site=site_, dry_run=False)
    assert plan["written"] and plan["location_id"] == 2
    assert (plan["latitude"], plan["longitude"]) == (51.1, 10.2)
    assert any(re.search(r"liegen 122\d m vom groundmeas-Ort „Lindenweg“ \(Ort 2: 51.10000, 10.20000\)", w)
               for w in plan["warnings"])
    assert any("Messung 8" in h for h in plan["hints"])                   # entry from a report at the same location
    assert plan["injections"] == [2] and "Injection measurement at this site: 2." in plan["measurement"]["description"]
    con = sqlite3.connect(db)
    assert con.execute("select * from location order by id").fetchall() == locations_before       # nothing changed
    assert con.execute("select count(*) from measurementitem where measurement_id = 8").fetchone()[0] == 2
    con.close()


def test_own_entry_recognised_and_renewed(tmp_path):
    db = _example(tmp_path)
    res = _station_res()
    one = earthing.export_fault_test(db, res, "Ashdown", dry_run=False)
    n_backups = len([f for f in os.listdir(tmp_path) if "_before_groundfault_" in f])
    two = earthing.export_fault_test(db, res, "Ashdown", dry_run=False)
    assert one["written"] and not two["written"] and two["existing_id"] == one["measurement_id"]
    assert earthing.plan_overview({"x": two})["status"].iloc[0] == ("schon eingetragen (Messung %d)"
                                                                    % one["measurement_id"])
    # evaluation changed (e.g. a correction added later) → renew the own entry, the id stays
    res.tables["station_frequency"].loc[0, "Z_fault_Ohm"] = 0.020
    three = earthing.export_fault_test(db, res, "Ashdown", dry_run=False, existing="replace",
                                       backup=one["backup"], uncertain_mode="omit")
    assert three["written"] and three["renewed"] and three["measurement_id"] == one["measurement_id"]
    assert len([f for f in os.listdir(tmp_path) if "_before_groundfault_" in f]) == n_backups   # no further copy
    con = sqlite3.connect(db)
    n, value = con.execute("select count(*), max(value) from measurementitem where measurement_id = ? and "
                           "measurement_type = 'earth_potential_rise' and measurement_distance_m = 70",
                           (one["measurement_id"],)).fetchone()
    assert n == 1 and value == pytest.approx(0.020 * 40.0 * 1000)             # 150 Hz omitted, 50 Hz new (mV)
    assert con.execute("select count(*) from measurement").fetchone()[0] == 4
    con.close()
    with earthing.Database(db) as d:                                          # hidden in the comparison
        m = earthing.exclude_own(d.measurements(location="Ashdown"), "2026-01-15_Northtown", "Ashdown_10_000kHz")
    assert m.empty
    # an entry of another source with the same timestamp is not replaced
    db2 = _db(str(tmp_path / "gm2.db"), locations=[(1, "Ashdown", 51.15, 10.25)],
              measurements=[(5, 1, "staged_fault_test", "2026-01-15 10:30:00.250000", "entered by hand", [])])
    p = earthing.export_fault_test(db2, res, "Ashdown", dry_run=False, existing="replace")
    assert not p["written"] and p["existing_id"] == 5 and "nicht aus diesem Werkzeug" in p["reasons"][0]


def test_substation_fault_current_per_order(tmp_path):
    w = demo.make_substation_recording(str(tmp_path / "UW_2_5_10_000kHz.cfg"), 2.5, active_step=None)
    rec = open_recording(str(tmp_path / "UW_2_5_10_000kHz.cfg"))
    b = w["intervals"]
    res = evaluate(rec, Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]), tuple(b["post_fault"])),
                   z_fault_ohm=2.5, metadata=dict(campaign="%s_Demo" % rec.t_start.date().isoformat(), site="UW"))
    db = _example(tmp_path)
    plan = earthing.export_fault_test(db, res, "UW Demo", latitude=51.4, longitude=10.5)
    m, values = plan["measurement"], earthing.plan_items(plan)
    assert plan["kind"] == "substation" and plan["writable"] and plan["location_new"]
    assert (m["asset_type"], m["fault_resistance_ohm"]) == ("substation", 2.5)
    assert set(values["measurement_type"]) == {"earth_fault_current"}
    assert all(f % 50.0 == 0 for f in values["frequency_hz"]) and values["frequency_hz"].iloc[0] == 50.0
    h = res.table("harmonics")
    h = h[h["channel"] == res.values["main_channel_i_res"]].set_index("order")
    assert values.set_index("frequency_hz").loc[50.0, "value"] == pytest.approx(h.loc[1, "magnitude"])
    threshold = max(0.1, 0.01 * h.loc[1, "magnitude"])
    target = {50.0 * o for o, r in h.iterrows() if o <= 25 and (o == 1 or r["magnitude"] >= threshold)}
    assert set(values["frequency_hz"]) == target
    assert "R_F = 2.5 Ohm" in m["description"] and "I_RES = " in m["description"]
    with pytest.raises(ValueError, match="harmonics"):
        earthing.export_fault_test(db, SimpleNamespace(tables={}, name="x"), "UW X")


def test_export_to_groundmeas_with_sites_file_and_register(tmp_path):
    base = tmp_path / "fault_tests"
    k = base / "01_Messkampagnen" / "2026-01-15_Northtown"
    (k / "1_Rohdaten" / "Station_Ashdown").mkdir(parents=True)
    (k / "1_Rohdaten" / "UW").mkdir()
    db = _example(tmp_path)
    (base / "Messregister.csv").write_text(
        "Kampagne;Datei;Fehlerwiderstand_Ohm\n2026-01-15_Northtown;Ashdown_10_000kHz.cfg;0\n", encoding="utf-8-sig")
    plan = earthing.export_to_groundmeas(_station_res(), k, db)
    assert os.path.exists(sites.path_for(k)) and any("angelegt" in h for h in plan["hints"])
    assert plan["measurement"]["fault_resistance_ohm"] == 0.0 and any("Messregister" in h for h in plan["hints"])
    assert plan["location_id"] == 7 and plan["measurement"]["voltage_level_kv"] == 20.0     # most frequent level
    assert plan["measurement"]["operator"] == "Grid Operator GmbH" and plan["sites_path"] == sites.path_for(k)
    assert not plan["written"]
    # data in the sites file changed by hand → taken over
    p = sites.path_for(k)
    text = Path(p).read_text(encoding="utf-8-sig")
    line = next(z for z in text.splitlines() if z.startswith("Station_Ashdown;"))
    new = "Station_Ashdown;Ashdown;51,15;10,25;mv_lv_earthing_system;20;8.500;Grid Services AG;checked"
    Path(p).write_text(text.replace(line, new), encoding="utf-8-sig")
    p2 = earthing.export_to_groundmeas(_station_res(), k, db, write=True)
    assert p2["written"] and p2["measurement"]["operator"] == "Grid Services AG"
    assert {w.get("distance_to_current_injection_m") for w in p2["values"]} == {8500.0}
    assert Path(p).read_text(encoding="utf-8-sig").count("checked") == 1           # the file is not overwritten
    uw = earthing.export_to_groundmeas(_station_res(name="SUB_0_10_000kHz", site="UW"), k, db)
    assert uw["location"] == "UW Northtown" and "ohne Koordinaten" in uw["reasons"][0]
    without = earthing.export_to_groundmeas(_station_res(site="Station_Unknown"), k, db)
    assert any(h.startswith("Messorte.csv: keine Zeile für den Messort „Station_Unknown“") for h in without["hints"])
    os.remove(p)
    no_file = earthing.export_to_groundmeas(_station_res(), k, db, template=False)
    assert no_file["sites_path"] is None
    assert any(h == "keine 0_Notizen/Messorte.csv – Ort aus dem Ordnernamen."     # forward slash on every OS
               for h in no_file["hints"])
    with pytest.raises(FileNotFoundError):
        earthing.export_to_groundmeas(_station_res(), k, str(tmp_path / "missing.db"))


def test_timestamp_does_not_match_the_campaign(tmp_path):
    """A recorder clock set wrongly, 12 days off (cfg 2026-01-27, campaign 2026-01-15) → nothing is written until
    the time is given; one day of difference (UTC ↔ local time around midnight) is accepted."""
    db = _example(tmp_path)
    res = _station_res(campaign="2026-01-15_Hillcrest")
    res.result_set["meta"]["start_time"] = "2026-01-27T14:05:00.250000"
    p = earthing.export_fault_test(db, res, "Ashdown", dry_run=False)
    assert not p["written"] and "12 Tage" in p["reasons"][0] and "2026-01-15" in p["reasons"][0]
    p = earthing.export_fault_test(db, res, "Ashdown", timestamp="2026-01-15 10:15:00", dry_run=False,
                                   backup=False)
    assert p["written"] and p["measurement"]["timestamp"] == "2026-01-15 10:15:00.000000"
    assert any("von Hand" in h for h in p["hints"])
    res2 = _station_res(campaign="2026-01-15_Hillcrest", name="other")
    res2.result_set["meta"]["start_time"] = "2026-01-16T00:30:00"
    assert earthing.export_fault_test(db, res2, "Ashdown")["writable"]
    with pytest.raises(ValueError, match="timestamp"):
        earthing.export_fault_test(db, res2, "Ashdown", timestamp="15.1.2026")


def test_hint_unknown_probe_distance(tmp_path):
    db = _example(tmp_path)
    res = _station_res()
    res.tables["station_frequency"].loc[res.tables["station_frequency"]["channel"] == "UE_70m", "distance_m"] = np.nan
    p = earthing.export_fault_test(db, res, "Ashdown")
    assert any("Sondenabstand unbekannt für UE_70m" in h for h in p["hints"])
    w = earthing.plan_items(p)
    assert w[w["description"].str.contains("UE_70m")]["measurement_distance_m"].isna().all()


def test_export_messages_in_english(tmp_path):
    """Hints, reasons, warnings and status in English; the station hints of the evaluation (prefix "Station", atypical
    angle) are passed on as warnings in either language; the database content stays English."""
    db = _example(tmp_path)
    res = _station_res()
    res.hints = ["Station: uncertain values – 150 Hz …", "Angle U_E/I_F (UE_70m, 50 Hz) = 95° – atypical …",
                 "Winkel U_E/I_F (UE_70m, 50 Hz) = 95° – untypisch …", "Network frequency …"]
    with i18n.language("en"):
        plan = earthing.export_fault_test(db, res, "Ashdown")
        ready = earthing.plan_overview({"x": plan})["status"].iloc[0]
        new = earthing.export_fault_test(db, res, "SSt Newfield")
        written = earthing.export_fault_test(db, res, "Ashdown", dry_run=False, backup=False)
        entered = earthing.plan_overview({"x": written})["status"].iloc[0]
        with pytest.raises(ValueError, match="^uncertain_mode='ignore' is not allowed – allowed: 'mark', 'omit'$"):
            earthing.export_fault_test(db, res, "Ashdown", uncertain_mode="ignore")
    assert plan["warnings"] == res.hints[:3]
    assert "Fault resistance unknown – fault_resistance_ohm stays empty (z_fault_ohm of the evaluation or column " \
           "fault_resistance_Ohm in register.csv, e.g. 0 = solid fault)." in plan["hints"]
    assert any(h.startswith("Units: earth_fault_current in A, earth_potential_rise in mV") for h in plan["hints"])
    assert ready == "ready" and entered == "entered: measurement %d" % written["measurement_id"]
    assert new["reasons"] == ["new location “SSt Newfield” without coordinates (enter latitude/longitude in "
                              "notes/sites.csv)"]
    assert plan["measurement"]["description"].startswith("Staged earth fault test at Ashdown (campaign "
                                                         "2026-01-15_Northtown, recording Ashdown_10_000kHz)")


def _former_selection(hints):
    """Export warnings as selected before the selection by message key (text match), for the comparison."""
    return [h for h in hints if "atypical" in h or "untypisch" in h or h.startswith("Station")]


def _render_with_dummies(key, lang):
    """Message ``key`` in ``lang`` with a dummy value for every placeholder."""
    import string
    values = {}
    for _, field, spec, _ in string.Formatter().parse(i18n._MESSAGES[key][lang]):
        if field:
            values[re.split(r"[.\[]", field)[0]] = 7 if (spec or "").endswith("d") else 1.5
    return i18n.tr(key, lang, **values)


def test_exported_hints_same_selection_for_every_message():
    """Every message of the evaluation (keys evaluation.*, station.*) is passed on to the export exactly when the
    former text match selected it, in English and in German. Only evaluation.check_stationarity – a label of the
    plausibility table, never a hint – was caught by the former prefix match ("Stationarity …")."""
    keys = [k for k in i18n._MESSAGES if k.startswith(("evaluation.", "station."))]
    assert set(earthing.EXPORTED_HINT_KEYS) <= set(keys)
    for key in keys:
        for lang in ("en", "de"):
            text = _render_with_dummies(key, lang)
            new = i18n.message_key(text, earthing.EXPORTED_HINT_KEYS)
            assert (new is not None) == (key in earthing.EXPORTED_HINT_KEYS), (key, lang, text)
            if key != "evaluation.check_stationarity":
                assert (new is not None) == bool(_former_selection([text])), (key, lang, text)
            assert new in (None, key)


@pytest.mark.parametrize("lang", ["en", "de"])
def test_station_hints_passed_on_in_both_languages(tmp_path, lang):
    """A station recording with a reversed probe and a large, fluctuating background gives station hints and atypical
    angles; the export passes on the same hints as the former text match – evaluated in English or German, also
    after saving and reloading the result, and with hints of an earlier wording."""
    from groundfault import load_result
    p = str(tmp_path / "st.cfg")
    w = demo.make_station_recording(p, duration=7.0, t_on=1.6, t_off=5.0, probes={"UE_5m": -0.6, "UE_70m": 0.93},
                                    background={1: demo.polar(40, 70), 3: demo.polar(15, 20)},
                                    background_fluctuation=0.3, with_voltages=False)
    db = _example(tmp_path)
    with i18n.language(lang):
        res = evaluate(open_recording(p), Intervals(*[tuple(w["intervals"][k]) for k in ("steady_state", "pre_fault",
                                                                                         "post_fault")]))
        res.hints.append(i18n.tr("evaluation.polarity_corrected"))        # a hint that is not passed on
        plan = earthing.export_fault_test(db, res, "Ashdown")
        loaded = load_result(res.save_json(str(tmp_path / "st_result.json")))
        plan_loaded = earthing.export_fault_test(db, loaded, "Ashdown")
    selected = _former_selection(res.hints)
    assert len(selected) >= 4 and len(selected) < len(res.hints)
    assert plan["warnings"] == selected and plan_loaded["warnings"] == selected
    keys = {i18n.message_key(h, earthing.EXPORTED_HINT_KEYS) for h in selected}
    assert {"evaluation.angle_atypical", "station.uncertain_values", "station.background_large"} <= keys
    old = ["Station: unsichere Werte – 150 Hz (Verfahren weichen 35 % ab). … (Spalte „unsicher“ in station_frequenz).",
           "Ortsnetz: PEN-Ströme vor (IPEN_v) und nach dem Trafoknoten (IPEN_n) weichen bei 50 Hz um 56 % ab."]
    res.hints = old                                                       # wording of an earlier version
    assert earthing.export_fault_test(db, res, "Ashdown")["warnings"] == old[:1] == _former_selection(old)


def _mentions(text, name):
    """``name`` occurs in ``text`` as a whole name (``register.csv`` is not found in ``Messregister.csv``)."""
    return re.search(r"(?<!\w)%s(?!\w)" % re.escape(name), text) is not None


@pytest.mark.parametrize("lang,layout", [("en", "de"), ("de", "en"), ("en", "en"), ("de", "de")])
def test_export_hints_name_the_files_of_the_campaign_layout(tmp_path, lang, layout):
    """The hints name the sites, corrections and register files and their columns in the folder layout of the
    campaign – an English session on a German-layout campaign is not told to edit sites.csv, and vice versa."""
    from groundfault import corrections
    from groundfault import layout as layouts
    lay, other = layouts.get_layout(layout), layouts.get_layout("en" if layout == "de" else "de")
    k = tmp_path / "work" / lay.campaigns / "2026-01-15_Northtown"
    for site in ("Station_Ashdown", "Station_New"):
        (k / lay.raw / site).mkdir(parents=True)
    (k / lay.notes).mkdir()
    (k / lay.notes / lay.sites_file).write_text(";".join(sites.HEADERS[layout]) + "\n"
                                                "Station_Ashdown;Ashdown;;;mv_lv_earthing_system;;;;\n"
                                                "Station_New;SSt Newfield;;;;;;;\n", encoding="utf-8-sig")
    db = _example(tmp_path)
    res = _station_res()
    res.tables["station_frequency"].loc[res.tables["station_frequency"]["channel"] == "UE_70m", "distance_m"] = np.nan
    with i18n.language(lang):
        plan = earthing.export_to_groundmeas(res, k, db, template=False)
        new = earthing.export_to_groundmeas(_station_res(site="Station_New"), k, db, template=False)
    text = " ".join(plan["hints"] + plan["warnings"] + plan["reasons"] + new["reasons"])
    s, c = sites.HEADERS[layout], corrections.HEADERS[layout]
    for name in (lay.sites_file, lay.corrections_file, lay.register_file, s[5], s[6], c[5],
                 "Fehlerwiderstand_Ohm" if layout == "de" else "fault_resistance_Ohm"):
        assert _mentions(text, name), (name, text)
    for name in (other.sites_file, other.corrections_file, other.register_file):
        assert not _mentions(text, name), (name, text)
    assert ("%s/%s" % (lay.notes, lay.sites_file)) in new["reasons"][0] and "%s/%s" % (s[2], s[3]) in new["reasons"][0]
    expected = {"en": "Distance to the feeding substation unknown (%s, column %s)",
                "de": "Entfernung zum speisenden UW unbekannt (%s, Spalte %s)"}[lang] % (lay.sites_file, s[6])
    assert any(h.startswith(expected) for h in plan["hints"])


def test_export_hints_layout_from_the_result_path(tmp_path):
    """Without a campaign folder the layout comes from the path of the result file or of the recording; without
    any path from the output language."""
    db = _example(tmp_path)
    german = tmp_path / "01_Messkampagnen" / "2026-01-15_Northtown"
    english = tmp_path / "campaigns" / "2026-01-15_Northtown"
    for sub in ("raw", "results"):                     # English folder names are recognised by existing folders
        (english / sub).mkdir(parents=True)
    with i18n.language("en"):
        res = _station_res()
        res.path = str(german / "2_Auswertung" / "Ashdown_10_000kHz" / "Ashdown_10_000kHz_ergebnis.json")
        from_file = earthing.export_fault_test(db, res, "Ashdown")
        res = _station_res()
        res.recording_info = {"path": str(german / "1_Rohdaten" / "Station_Ashdown" / "Ashdown_10_000kHz.cfg")}
        from_recording = earthing.export_fault_test(db, res, "Ashdown")
        without = earthing.export_fault_test(db, _station_res(), "Ashdown")
    with i18n.language("de"):
        res = _station_res()
        res.path = str(english / "results" / "Ashdown_10_000kHz" / "Ashdown_10_000kHz_result.json")
        english_file = earthing.export_fault_test(db, res, "Ashdown")
    hint = [h for h in from_file["hints"] if h.startswith("Fault resistance unknown")][0]
    assert hint.endswith("column Fehlerwiderstand_Ohm in Messregister.csv, e.g. 0 = solid fault).")
    assert any(h.startswith("Voltage level unknown – voltage_level_kv stays empty (Messorte.csv, column "
                            "Spannungsebene_kV)") for h in from_recording["hints"])
    assert any("(sites.csv, column voltage_level_kV)" in h for h in without["hints"])
    assert any(h.startswith("Spannungsebene unbekannt – voltage_level_kv bleibt leer (sites.csv, Spalte "
                            "voltage_level_kV)") for h in english_file["hints"])


@pytest.mark.parametrize("lang", ["en", "de"])
def test_sites_errors_name_the_columns_of_the_file(tmp_path, lang):
    """A number that cannot be read is reported with the column name as written in the file (German or English
    headers), whatever the output language."""
    for layout, wrong in (("de", "Breite"), ("en", "latitude")):
        p = tmp_path / layout / "sites.csv"
        p.parent.mkdir()
        p.write_text(";".join(sites.HEADERS[layout]) + "\nStation_A;A;north;10.3;;;;;\n", encoding="utf-8-sig")
        with i18n.language(lang), pytest.raises(ValueError) as e:
            sites.Sites.from_file(str(p))
        assert ("%s: 'north'" % wrong) in str(e.value)


def test_shield_current_at_every_order_of_the_voltages(tmp_path):
    """The shield current is entered at every order of the earth potential rise (table
    station_currents_frequency) – not only at the orders of Settings.harmonics (here 550 Hz was missing). At the
    common orders the entries are those taken from station_currents before, also the angle of a reversed shield
    clamp (rotated by 180° there); result files without station_currents_frequency keep the orders of
    station_currents."""
    p = str(tmp_path / "st.cfg")
    w = demo.make_station_recording(p, duration=7.0, t_on=1.6, t_off=5.0, I_harm={5: 30, 7: 6, 11: 4})
    iv = Intervals(*[tuple(w["intervals"][k]) for k in ("steady_state", "pre_fault", "post_fault")])
    db = _db(str(tmp_path / "gm.db"), locations=[(7, "Ashdown", 51.15, 10.25)])

    def shield(plan):
        return {v["frequency_hz"]: v for v in plan["values"] if v["measurement_type"] == "shield_current"}
    for reversed_clamp in (False, True):
        rec = open_recording(p)
        if reversed_clamp:
            rec.set_correction("IS", -1.0)                              # shield clamp the wrong way round
        res = evaluate(rec, iv)
        assert res.settings.harmonics == (1, 3, 5, 7)
        assert res.table("station_currents").set_index("channel").at["IS", "polarity"] == (-1 if reversed_clamp
                                                                                            else 1)
        plan = earthing.export_fault_test(db, res, "Ashdown")
        new = shield(plan)
        epr = {v["frequency_hz"] for v in plan["values"] if v["measurement_type"] == "earth_potential_rise"}
        assert set(new) == epr == {50.0, 250.0, 350.0, 550.0}
        res.tables.pop("station_currents_frequency")                    # result file of an earlier version
        before = shield(earthing.export_fault_test(db, res, "Ashdown"))
        assert set(before) == {50.0, 250.0, 350.0}
        for f in before:
            assert (new[f]["value"], new[f]["unit"]) == (before[f]["value"], before[f]["unit"])
            assert new[f]["value_angle_deg"] == pytest.approx(before[f]["value_angle_deg"], abs=1e-9)
        assert abs(new[550.0]["value_angle_deg"] - new[50.0]["value_angle_deg"]) < 30          # nearly in phase
