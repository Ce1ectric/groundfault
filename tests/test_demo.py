# -*- coding: utf-8 -*-
"""Demo campaign and demo groundmeas database: complete campaigns in both folder layouts whose evaluation
reproduces the known solution – including the reduction factor against the synthetic earthing measurement."""
import os

import numpy as np
import pytest

from groundfault import (Intervals, corrections, demo, detect_roles, earthing, evaluate, i18n, open_recording, register,
                         sites)


@pytest.fixture(scope="module")
def campaign_en(tmp_path_factory):
    return demo.make_campaign(str(tmp_path_factory.mktemp("demo_en")), layout="en")


def test_campaign_structure_english_layout(campaign_en):
    d = campaign_en
    camp = d["campaign"]
    assert camp.endswith(os.path.join("campaigns", "2026-01-15_Demo")) and os.path.isfile(d["db"])
    assert [w["cfg"] for w in d["substation"]] == ["raw/SUB/SUB_0_10_000kHz.cfg", "raw/SUB/SUB_2_5_10_000kHz.cfg",
                                                   "raw/SUB/SUB_5_10_000kHz.cfg"]
    assert d["station"]["cfg"] == "raw/Station_Elm_Road/Station_Elm_Road_10_000kHz.cfg"
    for rel in [w["cfg"] for w in d["substation"]] + [d["station"]["cfg"], d["station"]["rms_cfg"],
                                                      "notes/corrections.csv", "notes/sites.csv", "README.md"]:
        assert os.path.isfile(os.path.join(camp, rel)), rel
    df, lang = register.read_register(d["register"])
    assert lang == "en" and len(df) == 5
    s = sites.load(camp)
    assert s.for_site("Station_Elm_Road").location == "Station Elm Road"     # exact name from groundmeas
    assert s.for_site("SUB").location == "Substation Demo" and s.for_site("SUB").asset_type == "substation"


def test_reduction_factor_against_demo_database(campaign_en):
    """The fault test against the synthetic earthing measurement gives the reduction factor of the recording."""
    d = campaign_en
    st = d["station"]
    b = st["intervals"]
    rec = open_recording(os.path.join(d["campaign"], st["cfg"]))
    corr = corrections.load(d["campaign"])                  # distance of the touch-voltage probe UT
    corr.apply(rec)
    roles = detect_roles(rec.channel_names, rec.units, corr.role_overrides(rec), corr.main_channel(rec),
                         corr.distances(rec))
    res = evaluate(rec, Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]), tuple(b["post_fault"])), roles=roles)
    with earthing.Database(d["db"]) as db:
        choice = db.choose_location(earthing.location_from_site("Station_Elm_Road"))
        assert choice["location"] == "Station Elm Road"
        ids = list(db.measurements(location=choice["location"])["measurement_id"])
        response = earthing.frequency_response(db, ids)
    spectrum, effective = earthing.reduction_factor(res, response)
    mx = spectrum[spectrum["channel"] == "max(UE)"].set_index("order")
    assert sorted(mx.index) == sorted(st["orders"]) == [1, 5, 7, 11]
    for m, v in st["orders"].items():
        assert mx.at[m, "r"] == pytest.approx(abs(v["r"]), rel=0.03), m
        # r = r·Z_E/Z_E, the span of the superposition methods contains r
        assert mx.at[m, "r"] == pytest.approx(mx.at[m, "rZE_fault_Ohm"] / mx.at[m, "Z_E_injection_Ohm"], rel=1e-12)
        assert mx.at[m, "r_min"] <= mx.at[m, "r"] <= mx.at[m, "r_max"]
    e = effective[effective["channel"] == "max(UE)"].iloc[0]
    # trend of r and of both compared quantities (r·Z_E falls, Z_E rises with the frequency in the demo)
    assert e["exponent_r_vs_f"] < 0 and e["exponent_rZE_fault"] < 0 < e["exponent_Z_E_injection"]
    assert e["exponent_r_vs_f"] == pytest.approx(e["exponent_rZE_fault"] - e["exponent_Z_E_injection"], abs=1e-9)
    from groundfault import interactive, report
    with i18n.language("en"):
        fig = report.reduction_factor(spectrum, effective, direct=True)
        texts = [t.get_text() for ax in fig.axes for t in (ax.get_legend().get_texts() if ax.get_legend() else [])]
        assert any(t.startswith("trend $r \\propto f^{\\,b}$, b = −0.2") for t in texts), texts
        assert "r direct (as measured, with background)" in texts
        assert any("$r\\,Z_\\mathrm{E} = U_\\mathrm{E}/I_\\mathrm{F}$" in t for t in texts)
        fi = interactive.reduction_factor(spectrum, effective)
        assert any(t.name.startswith("trend r ∝ f<sup>b</sup>, b = ") for t in fi.data)
    report.plt.close("all")
    # no range and no limits given: no classification, no relevance – groundfault has no defaults for them
    assert e["classification_r_50Hz"] == "–" and e["trend_r_vs_f"] == "falling"
    assert e["assessment_relevance"] == "–" and np.isnan(e["reference_current_A"]) and np.isnan(e["F_times_U_Tp_V"])
    # with a range of the user (invented here) the demo station (r = 0.5 at 50 Hz) is typical
    _, effective = earthing.reduction_factor(res, response, r_typical=(0.3, 0.8))
    e = effective[effective["channel"] == "max(UE)"].iloc[0]
    assert e["classification_r_50Hz"] == "typical" and (e["r_typical_min"], e["r_typical_max"]) == (0.3, 0.8)
    plan = earthing.export_to_groundmeas(res, d["campaign"], d["db"])          # dry run
    assert plan["writable"] and plan["location"] == "Station Elm Road" and not plan["written"]
    items = earthing.plan_items(plan)
    touch = items[items["measurement_type"].str.contains("touch_voltage")]
    assert len(touch) and set(touch["measurement_distance_m"]) == {1.0}                                # corrections
    assert set(items["distance_to_current_injection_m"].dropna()) == {2400.0}                           # sites file


def test_campaign_german_layout(tmp_path):
    d = demo.make_campaign(str(tmp_path), layout="de", groundmeas=False)
    assert d["campaign"].endswith(os.path.join("01_Messkampagnen", "2026-01-15_Demo")) and d["db"] is None
    assert d["substation"][0]["cfg"] == "1_Rohdaten/UW/UW_0_10_000kHz.cfg"
    assert os.path.isfile(os.path.join(d["campaign"], "0_Notizen", "Korrekturen.csv"))
    assert os.path.isfile(os.path.join(d["campaign"], "LIESMICH.md"))
    assert sites.load(d["campaign"]).for_site("UW").location == "UW Demo"


def test_demo_database_matches_the_groundmeas_schema(tmp_path):
    """Values in the database come back in SI units, per order the test current and the impedance at 1 m and
    70 m; ``factor`` scales the measured impedances."""
    p = demo.make_groundmeas_db(str(tmp_path / "gm.db"), "Station X", factor=2.0, orders=(1, 5))
    with earthing.Database(p) as db:
        v = db.values([1])
        fr = earthing.frequency_response(db, [1])
    z = v[(v["type"] == "earthing_impedance") & (v["distance_m"] == 70.0)].set_index("f_Hz")["magnitude"]
    assert z.loc[50.0] == pytest.approx(2.0 * 0.93 * abs(1.0 + 0.08j))
    assert z.loc[250.0] == pytest.approx(2.0 * 0.93 * abs(1.0 + 0.4j))
    assert set(fr["quantity"]) == {"earth_potential_rise", "touch_voltage"}


def _files(base, skip):
    """md5 of every file below ``base`` outside the folder ``skip``."""
    import hashlib
    out = {}
    for folder, _, files in os.walk(str(base)):
        if os.path.abspath(folder).startswith(os.path.abspath(str(skip))):
            continue
        for f in files:
            p = os.path.join(folder, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, str(base))] = hashlib.md5(fh.read()).hexdigest()
    return out


@pytest.mark.parametrize("layout", ["en", "de"])
def test_demo_changes_nothing_outside_its_campaign_folder(tmp_path, layout):
    """In a real work folder (other campaigns of either layout, a register with a column maintained by hand, an
    existing database named like the demo database) the demo writes only into its own campaign folder."""
    field = tmp_path / "01_Messkampagnen" / "2026-02-01_Field"
    (field / "1_Rohdaten" / "UW").mkdir(parents=True)
    demo.make_substation_recording(str(field / "1_Rohdaten" / "UW" / "UW_A_10_000kHz.cfg"), 0.0, active_step=None)
    (field / "LIESMICH.md").write_text("own read-me\n", encoding="utf-8")
    (tmp_path / "Messregister.csv").write_text("Kampagne;Datei;Bemerkung\n2026-02-01_Field;UW_A_10_000kHz.cfg;"
                                               "checked by hand\n", encoding="utf-8-sig")
    demo.make_groundmeas_db(str(tmp_path / "demo_groundmeas.db"), "Station Somewhere")
    campaign = tmp_path / ("campaigns" if layout == "en" else "01_Messkampagnen") / "2026-01-15_Demo"
    before = _files(tmp_path, campaign)
    d = demo.make_campaign(str(tmp_path), layout=layout)
    assert _files(tmp_path, campaign) == before
    assert d["register"] is None and d["db"] == str(tmp_path / "demo_groundmeas.db")
    assert not (field / "0_Notizen").exists() and not os.path.exists(str(tmp_path / "register.csv"))
    with open(os.path.join(d["campaign"], "README.md" if layout == "en" else "LIESMICH.md"), encoding="utf-8") as f:
        readme = f.read()
    assert "Station_Elm_Road_10_000kHz.cfg" in readme and "2026-02-01_Field" not in readme


def test_demo_keeps_an_existing_register(tmp_path):
    """A register of the work folder is never rewritten by the demo, even without other campaigns."""
    (tmp_path / "register.csv").write_text("campaign;file;remark\n", encoding="utf-8-sig")
    d = demo.make_campaign(str(tmp_path), layout="en", groundmeas=False)
    assert d["register"] is None
    assert (tmp_path / "register.csv").read_text(encoding="utf-8-sig") == "campaign;file;remark\n"
    fresh = demo.make_campaign(str(tmp_path / "new"), layout="en", groundmeas=False)       # empty work folder
    assert fresh["register"] == str(tmp_path / "new" / "register.csv")
    assert len(register.read_register(fresh["register"])[0]) == 5
