# -*- coding: utf-8 -*-
"""groundmeas interface: read-only access, location search, units, frequency response, comparison earthing
measurement ↔ staged fault test, codes of the reduction-factor classification and their hints, export (dry run /
backup copy) – on a synthetic database with the original groundmeas schema; messages in English and German."""
import datetime
import hashlib
import json
import math
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

import pytest

from groundfault import Intervals, demo, earthing, i18n, open_recording, evaluate, units

# schema as in groundmeas (SQLModel) – taken from a groundmeas database
DDL = [
    """CREATE TABLE location (id INTEGER NOT NULL, name VARCHAR NOT NULL, latitude FLOAT, longitude FLOAT,
       altitude FLOAT, PRIMARY KEY (id))""",
    """CREATE TABLE measurement (id INTEGER NOT NULL, timestamp DATETIME NOT NULL, location_id INTEGER,
       method VARCHAR NOT NULL, voltage_level_kv FLOAT, asset_type VARCHAR NOT NULL, fault_resistance_ohm FLOAT,
       operator VARCHAR, description VARCHAR, PRIMARY KEY (id), FOREIGN KEY(location_id) REFERENCES location (id))""",
    """CREATE TABLE measurementitem (id INTEGER NOT NULL, measurement_type VARCHAR NOT NULL, value FLOAT,
       value_real FLOAT, value_imag FLOAT, value_angle_deg FLOAT, unit VARCHAR NOT NULL, description VARCHAR,
       frequency_hz FLOAT, additional_resistance_ohm FLOAT, input_impedance_ohm FLOAT, measurement_distance_m FLOAT,
       distance_to_current_injection_m FLOAT, measurement_id INTEGER, PRIMARY KEY (id),
       FOREIGN KEY(measurement_id) REFERENCES measurement (id))""",
]


def _md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def _db(path, locations=(), measurements=()):
    """locations: [(id, name)], measurements: [(id, location_id, method, [items…])], item: dict(measurement_type, …)."""
    con = sqlite3.connect(path)
    for d in DDL:
        con.execute(d)
    for oid, name in locations:
        con.execute("insert into location (id, name, latitude, longitude) values (?, ?, 51.0, 10.0)", (oid, name))
    for mid, oid, meth, items in measurements:
        con.execute("insert into measurement (id, timestamp, location_id, method, asset_type) values "
                    "(?, '2026-01-10 10:00:00', ?, ?, 'mv_lv_earthing_system')", (mid, oid, meth))
        for it in items:
            columns = ["measurement_id"] + list(it)
            con.execute("insert into measurementitem (%s) values (%s)"
                        % (", ".join(columns), ", ".join("?" * len(columns))),
                        [mid] + list(it.values()))
    con.commit(); con.close()
    return path


def _z(type_, value, f, unit="Ω", angle=None, distance=None, **kw):
    d = dict(measurement_type=type_, value=value, unit=unit, frequency_hz=f)
    if angle is not None:
        d["value_angle_deg"] = angle
    if distance is not None:
        d["measurement_distance_m"] = distance
    d.update(kw)
    return d


@pytest.fixture
def example_db(tmp_path):
    inj = []
    for f, z1, z100 in ((50, 0.08, 0.25), (150, 0.14, 0.40), (250, 0.19, 0.55)):
        inj += [_z("earthing_current", 200.0, f, "mA", 0.0),
                _z("earthing_impedance", z1 * 1000, f, "mOhm", 40.0, 1.0),          # mΩ → Ω
                _z("earthing_impedance", z100, f, "Ohm", 42.0, 100.0),
                _z("prospective_touch_voltage", z1 * 0.2, f, "V", 40.0, 1.0)]       # = Z(1 m)·I → duplicate
    fault_test = [_z("earth_fault_current", 30.0, 50, "A", 0.0), _z("earth_potential_rise", 1.8, 50, "V", 0.0, 40.0),
                  _z("earth_fault_current", 6.0, 250, "A", 0.0), _z("earth_potential_rise", 0.21, 250, "V", 0.0, 40.0)]
    complex_ = [dict(measurement_type="earthing_impedance", value_real=0.3, value_imag=0.4, unit="Ω",
                     frequency_hz=50.0, measurement_distance_m=50.0)]
    return _db(str(tmp_path / "gm.db"),
               locations=[(2, "Lindenweg"), (5, "Lindenweg"), (8, "SSt Bärenfeld"), (9, "Station B")],
               measurements=[(2, 2, "injection_earth_electrode", inj), (5, 5, "staged_fault_test", fault_test),
                             (9, 9, "injection_earth_electrode", complex_)])


def test_db_path_as_groundmeas(tmp_path, monkeypatch):
    monkeypatch.setenv("GROUNDMEAS_DB", "~/x/gm.db")
    assert earthing.default_db_path() == os.path.expanduser("~/x/gm.db")
    monkeypatch.delenv("GROUNDMEAS_DB")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))      # home directory on Windows
    assert earthing.default_db_path() is None
    (tmp_path / ".config" / "groundmeas").mkdir(parents=True)
    (tmp_path / ".config" / "groundmeas" / "config.json").write_text(json.dumps({"db_path": str(tmp_path / "a.db")}))
    assert earthing.default_db_path() == str(tmp_path / "a.db")


def test_read_only_and_schema_check(example_db, tmp_path):
    before = _md5(example_db)
    with earthing.Database(example_db) as db:
        with pytest.raises(sqlite3.OperationalError):
            db.con.execute("insert into location (name) values ('x')")
        assert len(db.locations()) == 4
    assert _md5(example_db) == before
    with pytest.raises(FileNotFoundError):
        earthing.Database(str(tmp_path / "missing.db"))
    empty = str(tmp_path / "empty.db")
    con = sqlite3.connect(empty)
    con.execute("create table x (a int)"); con.commit(); con.close()
    import gc
    import warnings
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        with pytest.raises(ValueError, match="keine groundmeas"):
            earthing.Database(empty)
        gc.collect()
    assert [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)] == []   # connection closed


def test_backup_copy_of_wal_database_closes_connections(tmp_path):
    """With a non-empty WAL file the backup copy goes through the SQLite backup API; both connections are closed and
    the copy contains the committed data."""
    import gc
    import warnings
    db = str(tmp_path / "wal.db")
    writer = sqlite3.connect(db)
    writer.execute("pragma journal_mode=wal"); writer.execute("create table t (a int)")
    writer.execute("insert into t values (7)"); writer.commit()
    try:
        assert os.path.getsize(db + "-wal") > 0                    # data still in the WAL file
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            copy = earthing._backup(db)
            gc.collect()
    finally:
        writer.close()
    assert [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)] == []
    check = sqlite3.connect(copy)
    try:
        assert check.execute("select a from t").fetchall() == [(7,)]
    finally:
        check.close()


@pytest.mark.parametrize("search,location", [
    ("Station B", "Station B"), (earthing.location_from_site("Station_B"), "Station B"),
    (earthing.location_from_site("Station_Lindemweg"), "Lindenweg"),   # typing error in the folder name
    ("Station_Lindem", "Lindenweg"),                                     # shortened, with a typing error
    ("SSt Baerenfeld", "SSt Bärenfeld"), ("bärenfeld", "SSt Bärenfeld"),
    ("SSt Riverton", None),
])
def test_find_location(example_db, search, location):
    with earthing.Database(example_db) as db:
        t = db.find_location(search)
        assert (t["location"].iloc[0] if len(t) else None) == location


def test_values_in_si_units(example_db):
    with earthing.Database(example_db) as db:
        w = db.values([2, 9])
    z1 = w[(w["type"] == "earthing_impedance") & (w["distance_m"] == 1.0) & (w["f_Hz"] == 50)].iloc[0]
    assert z1["magnitude"] == pytest.approx(0.08) and z1["unit"] == "Ω"                    # mOhm → Ω
    assert z1["unit_stored"] == "mOhm" and z1["unit_note"] is None
    assert z1["designation"] == "Erdungsimpedanz (Sonde)"
    i = w[(w["type"] == "earthing_current") & (w["f_Hz"] == 50)].iloc[0]
    assert i["magnitude"] == pytest.approx(0.2) and i["unit"] == "A"                       # mA → A
    k = w[w["measurement_id"] == 9].iloc[0]                                     # real and imaginary part only
    assert k["magnitude"] == pytest.approx(0.5) and k["angle_deg"] == pytest.approx(math.degrees(math.atan2(0.4, 0.3)))


def test_frequency_response(example_db):
    with earthing.Database(example_db) as db:
        fg = earthing.frequency_response(db, [2, 5])
    inj = fg[fg["source"] == "injection test"]
    assert len(inj) == 6                                   # touch voltage = Z(1 m) → not counted twice
    assert set(inj[inj["distance_m"] == 1.0]["quantity"]) == {"touch_voltage"}
    assert set(inj[inj["distance_m"] == 100.0]["quantity"]) == {"earth_potential_rise"}
    shown = i18n.localize(inj)                             # German display of the codes
    assert set(shown["Groesse"]) == {"Berührungsspannung", "Erdungsspannung"}
    st = fg[fg["source"] == "fault test (groundmeas)"].set_index("f_Hz")
    assert st.loc[50.0, "Z_Ohm"] == pytest.approx(1.8 / 30.0) and st.loc[250.0, "Z_Ohm"] == pytest.approx(0.21 / 6.0)
    assert st["angle_deg"].isna().all()                   # angles 0/0 (taken from a report) → not recorded
    assert st.loc[50.0, "reference_current_A"] == 30.0


def _station_frequency(rows):
    sp = ["channel", "role", "distance_m", "order", "f_Hz", "I_F_A", "Z_direct_Ohm", "Z_fault_Ohm",
          "Z_inception_Ohm", "Z_clearance_Ohm"]
    return pd.DataFrame([dict(zip(sp, z)) for z in rows])


def test_compare_probe_choice_and_ratio(example_db):
    with earthing.Database(example_db) as db:
        fg = earthing.frequency_response(db, [2, 5])
    sf = _station_frequency([("UE70", "u_e", 70.0, 1, 50.0, 30.0, 0.07, 0.055, 0.058, 0.052),
                             ("UE10", "u_e", 10.0, 1, 50.0, 30.0, 0.03, 0.02, 0.02, 0.02),
                             ("UEr", "u_e", None, 5, 250.1, 5.0, 0.031, 0.028, 0.027, 0.029),
                             ("UT", "u_t", None, 1, 50.02, 30.0, 0.034, 0.029, 0.031, 0.027)])
    long_df, rat = earthing.compare(sf, fg, measurement="Test")
    v = rat.set_index("channel")
    assert v.loc["UE70", "distance_injection_m"] == 100.0 and v.loc["UE70", "distance_match"] == "similar"
    assert v.loc["UE70", "ratio_fault"] == pytest.approx(0.055 / 0.25)
    assert v.loc["UE10", "distance_match"] == "different"                 # 10 m ↔ 100 m: not to be read as r
    assert v.loc["UEr", "distance_match"] == "unknown" and v.loc["UEr", "f_Hz"] == pytest.approx(250.1)
    assert v.loc["UEr", "ratio_fault"] == pytest.approx(0.028 / 0.55)
    assert v.loc["UT", "distance_injection_m"] == 1.0 and v.loc["UT", "distance_match"] == "touch"
    assert v.loc["UT", "ratio_direct"] == pytest.approx(0.034 / 0.08)
    fb = long_df[(long_df["source"] == "fault test") & (long_df["type"] == "fault")].set_index("channel")
    assert set(fb["measurement"]) == {"Test"}
    assert fb.loc["UE70", "Z_min_Ohm"] == pytest.approx(0.052) and fb.loc["UE70", "Z_max_Ohm"] == pytest.approx(0.058)
    assert fb.loc["UEr", "description"] == "Ordnung 5"
    assert {"injection test", "fault test (groundmeas)"} <= set(long_df["source"])


def test_export_dry_run_and_write_with_read_back(tmp_path):
    """Synthetic station (background, frequency drift) → fault-related component → export into an empty groundmeas
    database → read back: U/I per order as in the result; with an injection measurement Z_E,m at the same probe the
    comparison gives the reduction factor |r| at all frequencies (a second, independent way)."""
    p = str(tmp_path / "st.cfg")
    w = demo.make_station_recording(p, duration=7.0, t_on=1.6, t_off=5.0, f1_drift_hz_s=0.01,
                                    background={1: demo.polar(8, 70), 5: demo.polar(2, 100)})
    res = evaluate(open_recording(p), Intervals(*[tuple(w["intervals"][k]) for k in ("steady_state", "pre_fault",
                                                                                     "post_fault")]))
    sf = res.table("station_frequency")
    a70 = 70.0                                         # distance of the probe UE_70m (from the channel name)
    inj = [_z("earthing_current", 1.0, 50.0 * m, "A", 0.0) for m in (1, 5, 7, 11)]
    inj += [_z("earthing_impedance", abs(w["R_E"] + 1j * m * w["X_E1"]) * w["probes"]["UE_70m"], 50.0 * m, "Ω",
               math.degrees(math.atan2(m * w["X_E1"], w["R_E"])), a70) for m in (1, 5, 7, 11)]
    db_path = _db(str(tmp_path / "gm.db"), locations=[(1, "SSt Demo")],
                  measurements=[(1, 1, "injection_earth_electrode", inj)])
    before = _md5(db_path)
    plan = earthing.export_fault_test(db_path, res, "SSt Demo")
    assert plan["written"] is False and _md5(db_path) == before               # the dry run writes nothing
    types_ = pd.Series([i["measurement_type"] for i in plan["values"]]).value_counts()
    assert types_["earth_fault_current"] == sf["order"].nunique()
    plan = earthing.export_fault_test(db_path, res, "SSt Demo", dry_run=False)
    assert plan["written"] and os.path.exists(plan["backup"]) and _md5(plan["backup"]) == before
    with earthing.Database(db_path) as db:
        assert len(db.locations()) == 1                                                  # location reused
        fg = earthing.frequency_response(db, [1, plan["measurement_id"]])
    st = fg[(fg["source"] == "fault test (groundmeas)") & (fg["type"] == "earth_potential_rise")]
    for m in (1, 5, 7, 11):
        target = w["orders"][m]["rZE_probe"]
        z = st[(st["f_Hz"] - m * sf["f_Hz"].iloc[0]).abs() < 1.0]
        z = z[z["distance_m"] == a70].iloc[0]
        assert z["Z_Ohm"] == pytest.approx(abs(target), rel=0.03)
        assert z["angle_deg"] == pytest.approx(np.degrees(np.angle(target)), abs=3.0)
    _, rat = earthing.compare(sf, fg[fg["source"] == "injection test"])
    v = rat[rat["channel"] == "UE_70m"].set_index("order")
    for m in (1, 5, 7, 11):
        assert v.loc[m, "ratio_fault"] == pytest.approx(abs(w["r"]), rel=0.03)
        assert v.loc[m, "distance_match"] == "equal"
    ut = rat[rat["channel"] == "UT"]
    assert ut.empty                                     # no 1-m probe in the earthing measurement → no comparison


def test_export_without_station_evaluation():
    with pytest.raises(ValueError, match="station_frequency"):
        earthing.export_fault_test("x.db", SimpleNamespace(tables={}, name="x"), "location")


def test_choose_location_safely(tmp_path):
    db_path = _db(str(tmp_path / "gm.db"), locations=[(1, "UW Hillcrest"), (2, "SSt Bärenfeld"), (3, "Lindenweg"),
                                                      (4, "Eastfield"), (5, "Station B"), (6, "SSt Westbrook")])
    with earthing.Database(db_path) as db:
        w = db.choose_location("SSt Baerenfeld")
        assert w["location"] == "SSt Bärenfeld" and w["exact"]                    # umlaut spelling counts as equal
        w = db.choose_location("Lindemweg")
        assert w["location"] == "Lindenweg" and not w["exact"] and w["unique"]    # comparison yes, export no
        assert 'location="Lindenweg"' in w["note"]                                # default: the argument of the API
        w = db.choose_location("Lindemweg", preset='LOCATION = "{}"')             # caller's own text (e.g. a notebook)
        assert 'LOCATION = "Lindenweg"' in w["note"] and 'location="' not in w["note"]
        assert db.choose_location("SSt Hillcrest")["location"] is None           # SSt ≠ UW
        assert db.choose_location("SSt Bärenfeld 2")["location"] is None         # different number
        assert db.choose_location("Lindemweg", exact_only=True)["location"] is None   # a given name is not "guessed"
        assert db.choose_location("SSt Riverton")["location"] is None


def test_db_path_with_special_characters(tmp_path):
    d = tmp_path / "folder #1 50%"
    d.mkdir()
    p = _db(str(d / "gm.db"), locations=[(1, "Station B")])
    before = sorted(os.listdir(tmp_path))
    with earthing.Database(p) as db:
        assert db.locations()["location"].tolist() == ["Station B"]
    assert sorted(os.listdir(tmp_path)) == before                            # no empty file "folder " created


def test_export_not_twice_and_touch_voltage_approximation(tmp_path):
    sp = ["channel", "role", "distance_m", "order", "f_Hz", "I_F_A", "Z_direct_Ohm", "Z_fault_Ohm",
          "Z_fault_angle_deg"]
    sf = pd.DataFrame([dict(zip(sp, z)) for z in (("UE_70m", "u_e", 70.0, 1, 50.0, 40.0, 0.018, 0.016, 30.0),
                                                   ("UE_5m", "u_t", 5.0, 1, 50.0, 40.0, 0.012, 0.010, 32.0),
                                                   ("U1m", "u_t", 1.0, 1, 50.0, 40.0, 0.005, 0.006, 35.0))])
    atypical = i18n.tr("evaluation.angle_atypical", channel="UE_5m", angle=95.0)      # a hint of the evaluation
    res = SimpleNamespace(tables={"station_frequency": sf}, name="Test", hints=[atypical],
                          result_set={"meta": {"start_time": "2026-07-15T10:30:00.250000", "campaign": "K"},
                                      "measurement": {"z_fault_ohm": None}})
    p = _db(str(tmp_path / "gm.db"), locations=[(1, "Ashdown")])
    plan = earthing.export_fault_test(p, res, "Ashdown")
    assert plan["measurement"]["timestamp"] == "2026-07-15 10:30:00.250000"      # format as groundmeas (SQLAlchemy)
    utc = earthing.export_fault_test(p, res, "Ashdown", timezone="Europe/Berlin")
    assert utc["measurement"]["timestamp"] == "2026-07-15 08:30:00.250000"       # summer time: CEST = UTC + 2 h
    winter = SimpleNamespace(**{**vars(res), "result_set": {**res.result_set, "meta": {
        "start_time": "2026-01-15T10:30:00.250000", "campaign": "K"}}})
    assert earthing.export_fault_test(p, winter, "Ashdown", timezone="Europe/Berlin")["measurement"]["timestamp"] \
        == "2026-01-15 09:30:00.250000"                                          # winter time: CET = UTC + 1 h
    assert plan["measurement"]["voltage_level_kv"] is None and plan["measurement"]["fault_resistance_ohm"] is None
    assert plan["warnings"] == [atypical]
    type_ = {w["description"].split()[1]: w["measurement_type"] for w in plan["values"]
             if units.parse_unit(w["unit"]).quantity == "voltage"}
    assert type_ == {"UE_70m": "earth_potential_rise", "UE_5m": "earth_potential_rise",
                     "U1m": "prospective_touch_voltage"}            # the 5-m approximation is not entered as U_T
    one = earthing.export_fault_test(p, res, "Ashdown", dry_run=False)
    two = earthing.export_fault_test(p, res, "Ashdown", dry_run=False)
    assert one["written"] and not two["written"] and two["existing_id"] == one["measurement_id"]
    three = earthing.export_fault_test(p, res, "Ashdown", dry_run=False, timezone="Europe/Berlin")
    assert not three["written"] and three["existing_id"] == one["measurement_id"]   # other time, same measurement
    now_ = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    t = datetime.datetime.fromisoformat(earthing._groundmeas_time(None, "Europe/Berlin"))
    assert abs((t - now_).total_seconds()) < 60                                 # fallback "now" stays UTC
    with earthing.Database(p) as db:
        assert len(db.measurements()) == 1


def test_units_as_groundmeas_1_6_1(tmp_path):
    """Values as entered (μΩ, MΩ, kV, Ohm_meter …), read in the base unit; unusable units (A for a voltage, the
    typing error MA) stay as stored and are reported – as in groundmeas ≥ 1.6.1."""
    items = [_z("earthing_impedance", 350.0, 50.0, "µΩ", 0.0, 10.0),
             _z("earthing_impedance", 2.0, 50.0, "MΩ", 0.0, 20.0),
             _z("earth_potential_rise", 1.5, 50.0, "kV", 0.0, 70.0), _z("touch_voltage", 3.0, 50.0, "A"),
             _z("earth_fault_current", 5.0, 50.0, "MA"), _z("soil_resistivity", 120.0, None, "Ohm_meter", None, 2.0),
             _z("earthing_current", 20.0, 50.0, "")]
    p = _db(str(tmp_path / "gm.db"), locations=[(1, "Test")], measurements=[(1, 1, "injection_earth_electrode", items)])
    with earthing.Database(p) as db:
        w = db.values([1]).set_index("distance_m", drop=False)
        e = db.units().set_index(["type", "unit"])
    z = w[w["type"] == "earthing_impedance"].set_index("distance_m")
    assert z.loc[10.0, "magnitude"] == pytest.approx(350e-6) and z.loc[20.0, "magnitude"] == pytest.approx(2e6)
    assert w[w["type"] == "earth_potential_rise"]["magnitude"].iloc[0] == pytest.approx(1500.0)
    t = w[w["type"] == "touch_voltage"].iloc[0]
    assert t["magnitude"] == 3.0 and "current" in t["unit_note"]
    assert w[w["type"] == "earth_fault_current"]["magnitude"].iloc[0] == 5.0
    assert w[w["type"] == "soil_resistivity"]["unit"].iloc[0] == "Ωm"
    assert w[w["type"] == "earthing_current"]["unit"].iloc[0] == "A"            # without a unit: base unit
    assert e.loc[("earth_fault_current", "MA"), "note"] and not e.loc[("earth_potential_rise", "kV"), "note"]
    assert e.loc[("earthing_impedance", "MΩ"), "factor"] == 1e6


# ---------------------------------------------------------------------------------------------- reduction factor codes
@pytest.mark.parametrize("r,code", [(0.1, "below"), (0.3, "typical"), (0.45, "typical"), (0.8, "typical"),
                                    (0.9, "above"), (1.1, "above"), (1.2, "implausible"), (float("nan"), "–")])
def test_classification_codes(r, code):
    assert earthing._classify_r(r, (0.3, 0.8)) == code                   # a range of the user (invented)


@pytest.mark.parametrize("r,code", [(0.1, "–"), (0.5, "–"), (1.0, "–"), (1.2, "implausible"), (float("nan"), "–")])
def test_classification_without_a_range(r, code):
    """groundfault has no typical range: without one there is no classification, only the physical check
    r > R_IMPLAUSIBLE (the fault test would measure more than the full earth potential rise)."""
    assert earthing._classify_r(r) == code
    assert earthing._classify_r(r, None) == code


@pytest.mark.parametrize("r_typical", [(0.8, 0.3), (0.3,), (-0.1, 0.5), "0.3-0.8", (0.3, float("inf"))])
def test_invalid_range_is_rejected(r_typical):
    with pytest.raises(ValueError, match="r_typical muss ein Paar"):
        earthing._check_r_typical(r_typical)


@pytest.mark.parametrize("u_fault,u_injection,code", [(100.0, 110.0, "negligible"), (50.0, 100.0, "unchanged"),
                                                      (260.0, 300.0, "unchanged"), (200.0, 300.0, "relevant"),
                                                      (float("nan"), 100.0, "–")])
def test_relevance_codes(u_fault, u_injection, code):
    share, c = earthing._relevance(u_fault, u_injection, 250.0, 10.0)        # F·U_Tp = 250 V (invented)
    assert c == code
    if code != "–":
        assert share == pytest.approx(100.0 * abs(u_injection - u_fault) / 250.0)
    assert earthing._relevance(u_fault, u_injection, float("nan"), 10.0)[1] == "–"    # U_Tp or F not given


def _spectrum_rows(r, measured=(True, True, True), uncertain=(False, False, False)):
    """Rows of one probe against one earthing measurement as built by reduction_factor (orders 1, 5, 7)."""
    return pd.DataFrame(dict(order=[1, 5, 7], f_Hz=[50.0, 250.0, 350.0], r=list(r),
                             rZE_fault_Ohm=[0.5 * x for x in r], Z_E_injection_Ohm=[0.5, 0.5, 0.5],
                             uncertain=list(uncertain), _measured=list(measured)))


@pytest.mark.parametrize("exponent,code", [(-0.5, "falling"), (0.0, "constant"), (0.3, "rising")])
def test_trend_codes_against_exact_power_law(exponent, code):
    f = np.array([50.0, 250.0, 350.0])
    c = earthing._classify(_spectrum_rows(0.4 * (f / 50.0) ** exponent), (0.25, 0.6))
    assert c["trend_r_vs_f"] == code and c["exponent_r_vs_f"] == pytest.approx(exponent, abs=1e-9)
    assert c["exponent_rZE_fault"] == pytest.approx(exponent, abs=1e-9)
    assert c["exponent_Z_E_injection"] == pytest.approx(0.0)
    assert (c["r_50Hz"], c["classification_r_50Hz"], c["r_typical_min"], c["r_typical_max"]) == (0.4, "typical", 0.25,
                                                                                                    0.6)
    assert c["trend_orders"] == "1, 5, 7"


def test_trend_only_from_measured_and_certain_orders():
    """The value of order 5 is interpolated, the one of order 7 uncertain: the trend uses only reliable orders as
    long as there are two of them, otherwise all orders."""
    r = [0.4, 0.9, 0.2]
    c = earthing._classify(_spectrum_rows(r, measured=(True, False, True)), None)
    assert c["trend_orders"] == "1, 7"
    assert c["exponent_r_vs_f"] == pytest.approx(math.log(0.2 / 0.4) / math.log(350.0 / 50.0))
    assert c["classification_r_50Hz"] == "–" and np.isnan(c["r_typical_min"]) and np.isnan(c["r_typical_max"])
    c = earthing._classify(_spectrum_rows(r, measured=(True, False, True), uncertain=(False, False, True)), None)
    assert c["trend_orders"] == "1, 5, 7"                   # only one reliable order left → all orders
    assert c["exponent_r_vs_f"] == pytest.approx(np.polyfit(np.log([50.0, 250.0, 350.0]), np.log(r), 1)[0])


def _effective_row(**kw):
    row = dict(channel="max(UE)", probe="UE_5m", injection_id=1, distance_injection_m=70.0, distance_match="maximum",
               r_50Hz=0.05, rZE_fault_50Hz_Ohm=0.05, Z_E_injection_50Hz_Ohm=1.0, classification_r_50Hz="below",
               r_typical_min=0.25, r_typical_max=0.6, trend_r_vs_f="falling", exponent_r_vs_f=-0.3,
               trend_orders="1, 5, 7", reference_current_A=100.0, U_E_fault_at_reference_current_V=5.0,
               U_E_injection_at_reference_current_V=100.0, U_Tp_V=100.0, F_factor=2.5, F_times_U_Tp_V=250.0,
               assessment_relevance_pct=38.0, assessment_relevance="unchanged")      # invented parameters
    row.update(kw)
    return pd.DataFrame([row])


def test_reduction_hints_from_codes():
    h = earthing.reduction_hints(_effective_row())
    assert len(h) == 1
    assert h[0].startswith("Reduktionsfaktor Sondenmaximum (UE_5m) ↔ Erdungsmessung ID 1 (70 m): r = 0,05 bei 50 Hz "
                           "liegt unter dem üblichen Bereich 0,25–0,6 (r·Z_E aus dem Erdschluss (max(U_E)/I_F) "
                           "0,05 Ω, Z_E aus der Erdungsmessung 1 Ω).")
    assert h[0].endswith("Für die Bewertung: beim Bezugsstrom 100 A ergibt der Erdschluss U_E = 5 V, die "
                         "Erdungsmessung 100 V – die Abweichung von 95 V sind 38 % von F·U_Tp = 250 V; beide liegen "
                         "unter F·U_Tp, die Bewertung ändert sich nicht.")
    h = earthing.reduction_hints(_effective_row(r_50Hz=0.9, classification_r_50Hz="above"))
    assert "liegt über dem üblichen Bereich 0,25–0,6" in h[0]
    h = earthing.reduction_hints(_effective_row(r_50Hz=1.3, classification_r_50Hz="implausible"))
    assert "r = 1,3 bei 50 Hz ist größer als 1" in h[0]
    h = earthing.reduction_hints(_effective_row(r_50Hz=0.4, classification_r_50Hz="typical",
                                                assessment_relevance="relevant",
                                                U_E_injection_at_reference_current_V=300.0))
    assert len(h) == 1 and h[0].startswith("Erdschluss und Erdungsmessung Sondenmaximum (UE_5m)")
    assert h[0].endswith("einer liegt über, einer unter F·U_Tp – die Bewertung hängt vom Verfahren ab.")
    assert earthing.reduction_hints(_effective_row(r_50Hz=0.4, classification_r_50Hz="typical")) == []
    h = earthing.reduction_hints(_effective_row(r_50Hz=0.4, classification_r_50Hz="typical", trend_r_vs_f="rising",
                                                exponent_r_vs_f=0.3))
    assert len(h) == 1 and "r steigt mit der Frequenz (r ∝ f^0,3 über die Ordnungen 1, 5, 7)" in h[0]
    # without a range in the row (no range given, or an older table): no hint about the range; display texts are
    # not codes
    assert earthing.reduction_hints(_effective_row().drop(columns=["r_typical_min", "r_typical_max"])) == []
    assert earthing.reduction_hints(_effective_row(r_typical_min=np.nan, r_typical_max=np.nan)) == []
    assert earthing.reduction_hints(_effective_row(classification_r_50Hz="below the typical range 0,3–0,8")) == []


def test_reduction_hints_name_the_missing_parameters():
    """Without a reference current, U_Tp or F the relevance is not determined: one hint names the missing parameters
    (reduction_factor has no defaults for them)."""
    missing = dict(reference_current_A=np.nan, U_Tp_V=np.nan, F_times_U_Tp_V=np.nan, assessment_relevance="–",
                   U_E_fault_at_reference_current_V=np.nan, U_E_injection_at_reference_current_V=np.nan,
                   assessment_relevance_pct=np.nan, classification_r_50Hz="–", r_eff=0.05)
    h = earthing.reduction_hints(_effective_row(**missing))
    assert h == ["Bedeutung der Abweichung zwischen Erdschluss und Erdungsmessung für die Bewertung nicht bestimmt – "
                 "nicht angegeben: reference_current_A, U_Tp. Selbst festlegen: Argumente von earthing.reduction_factor "
                 "oder Settings.ires_limits (größter Grenzwert = Bezugsstrom), u_tp und f_factor der Auswertung."]
    with i18n.language("en"):
        h = earthing.reduction_hints(_effective_row(**dict(missing, reference_current_A=100.0, U_Tp_V=100.0,
                                                           F_factor=np.nan)))
    assert h == ["Relevance of the deviation between fault test and earthing measurement for the assessment not "
                 "determined – not given: F. Define them yourself: arguments of earthing.reduction_factor, or "
                 "Settings.ires_limits (largest limit = reference current), u_tp and f_factor of the evaluation."]
    # older tables without the parameter columns: F·U_Tp missing → U_Tp and F
    old = _effective_row(**missing).drop(columns=["U_Tp_V", "F_factor"])
    assert "nicht angegeben: reference_current_A, U_Tp, F." in earthing.reduction_hints(old)[0]
    assert not any(x.startswith("Bedeutung der Abweichung") for x in earthing.reduction_hints(_effective_row()))


def test_messages_in_english(example_db, tmp_path):
    with i18n.language("en"):
        with earthing.Database(example_db) as db:
            w = db.choose_location("Lindemweg")
            v = db.values([2])
            fg = earthing.frequency_response(db, [2, 5])
        with pytest.raises(FileNotFoundError, match="groundmeas database not found"):
            earthing.Database(str(tmp_path / "missing.db"))
        with pytest.raises(ValueError, match="Neither a station evaluation"):
            earthing.export_fault_test("x.db", SimpleNamespace(tables={}, name="x"), "location")
        _, rat = earthing.compare(_station_frequency([("UT", "u_t", None, 1, 50.02, 30.0, 0.034, 0.029, 0.031,
                                                       0.027)]), fg)
        h = earthing.reduction_hints(_effective_row())
        h_rising = earthing.reduction_hints(_effective_row(r_50Hz=0.4, classification_r_50Hz="typical",
                                                           trend_r_vs_f="rising", exponent_r_vs_f=0.3))
    assert w["note"] == ("Location “Lindenweg” is similar to “Lindemweg” (89 %) – used for the comparison; set it "
                         "exactly with location=\"Lindenweg\".")
    assert set(v[v["type"] == "earthing_impedance"]["designation"]) == {"earthing impedance (probe)"}
    assert set(v[v["type"] == "earthing_current"]["designation"]) == {"test current"}
    assert set(rat[rat["channel"] == "UT"]["distance_match"]) == {"touch"}
    assert h[0].startswith("Reduction factor probe maximum (UE_5m) ↔ earthing measurement ID 1 (70 m): r = 0.05 at "
                           "50 Hz is below the typical range 0.25–0.6 (r·Z_E from the fault test (max(U_E)/I_F) "
                           "0.05 Ω, Z_E from the earthing measurement 1 Ω).")
    assert h[0].endswith("the deviation of 95 V is 38 % of F·U_Tp = 250 V; both are below F·U_Tp, the assessment "
                         "does not change.")
    assert "r rises with the frequency (r ∝ f^0.3 over the orders 1, 5, 7)" in h_rising[0]


def test_message_catalog_complete():
    """Every message of the earthing and units modules exists in English and German."""
    for lang in ("en", "de"):
        assert [k for k in i18n.missing_keys(lang) if k.startswith(("earthing.", "units."))] == []
