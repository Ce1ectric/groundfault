# -*- coding: utf-8 -*-
"""Symmetrical components and channel roles (channel names of recorder exports and of the structured naming
convention); role descriptions and the role table in German and English."""
import numpy as np
import pytest

from groundfault import i18n, symmetrical
from groundfault.channels import (PEN_POSITION_DESCRIPTIONS, ROLE_DESCRIPTIONS, detect_role, detect_roles,
                                  pen_position_description, role_description, short_name)


def test_fortescue_round_trip():
    rng = np.random.default_rng(0)
    x = rng.standard_normal((3, 10)) + 1j * rng.standard_normal((3, 10))
    x0, x1, x2 = symmetrical.fortescue(*x)
    assert np.allclose(np.array(symmetrical.inverse_fortescue(x0, x1, x2)), x)


@pytest.mark.parametrize("m,seq", [(1, "pos"), (5, "neg"), (7, "pos"), (3, "zero"), (9, "zero"), (11, "neg"), (13, "pos")])
def test_natural_sequence(m, seq):
    """A symmetrical three-phase system of order m (time shift of 1/3 period per line) ends up completely in the
    natural sequence."""
    phi = -2 * np.pi / 3 * m
    ua, ub, uc = 1.0, np.exp(1j * phi), np.exp(2j * phi)
    d = dict(zip(("zero", "pos", "neg"), symmetrical.fortescue(ua, ub, uc)))
    assert abs(d[seq]) == pytest.approx(1.0)
    assert symmetrical.sequence_of_order(m) == seq


def test_reference_independent_of_time_origin():
    """X_m·e^{−j m φ} is invariant under a time shift τ."""
    w = 2 * np.pi * 50
    values = []
    for tau in (0.0, 0.0031, 0.017):
        U12 = 20000 * np.exp(1j * (0.4 + w * tau))
        I5 = 70 * np.exp(1j * (1.1 + 5 * w * tau))
        values.append(symmetrical.rotate_to_reference(I5, 5, symmetrical.reference_angle(U12)))
    assert np.allclose(values, values[0])
    assert values[0] == pytest.approx(70 * np.exp(1j * (1.1 - 5 * 0.4)))


EXPORT_CHANNELS = {   # channel name → (role, probe distance)
    "DANEO 1_System 1_UL1E Inst": ("u_l1e", None), "DANEO 1_System 1_V2 Inst": ("u_l2e", None),
    "DANEO 1_Spannungen_V3 Inst": ("u_l3e", None), "DANEO 1_System 3_V1HS Inst": ("u_hv_l1e", None),
    "DANEO 1_Ströme_IF Inst": ("i_res", None), "DANEO 1_Ströme_IF1 Inst": ("i_res", None),
    "DANEO 1_Ströme_IFr500 Inst": ("i_res", None), "DANEO 1_Ströme_IFx Inst": ("i_res", None),
    "DANEO 1_Ströme_ISp_B Inst": ("i_coil", None), "DANEO 1_Ströme_ESp21 Inst": ("i_coil", None),
    "DANEO 1_System 2_I1 Inst": ("i_l1", None), "DANEO 1_System 1_IL3 Inst": ("i_l3", None),
    "DANEO 1_Spannungen_UE_70m Inst": ("u_e", 70.0), "DANEO 1_Spannungen_U30m Inst": ("u_e", 30.0),
    "DANEO 1_Spannungen_UE100 Inst": ("u_e", 100.0), "DANEO 1_Spannungen_UEr Inst": ("u_e", None),
    "DANEO 1_Spannungen_UT Inst": ("u_t", None), "DANEO 1_Ströme_IS RMS": ("i_shield", None),
    "DANEO 1_Ströme_Ischirm Inst": ("i_shield", None), "DANEO 1_Ströme_IPEN_v Inst": ("i_pen", None),
    "DANEO 1_Ströme_Ipen Inst": ("i_pen", None),
    "i_20kv_res_j01_ct_m01_a__raw": ("i_res", None), "u_20kv_l1e_j02_vt_m01_v__raw": ("u_l1e", None),
    "i_20kv_coil_esp21_ct_m01_a__raw": ("i_coil", None),
}


@pytest.mark.parametrize("name,expected", list(EXPORT_CHANNELS.items()))
def test_roles_of_channel_names(name, expected):
    unit = "A" if ("Ströme" in name or name.startswith("i_") or "_I" in name) else "V"
    assert detect_role(name, unit) == expected


def test_short_name():
    assert short_name("DANEO 1_Spannungen_UE_70m Inst") == ("UE_70m", "Spannungen", "Inst")
    assert short_name("DANEO 1_System 1_V1 RMS")[0] == "V1"


@pytest.mark.parametrize("name,expected", [
    ("REC 2_Ströme_IF1 Inst", ("IF1", "Ströme", "Inst")), ("Recorder-A 3_Voltages_V2 RMS", ("V2", "Voltages", "RMS")),
    ("DANEO 12_Spannungen_UE_5m Inst", ("UE_5m", "Spannungen", "Inst")),
    ("daneo 1_Currents_IS Raw", ("IS", "Currents", "Raw")),
    ("REC 2_System 1_V1 Inst", ("V1", "System 1", "Inst")),
    ("DANEO_IF Inst", ("IF", "", "Inst")), ("DANEO1_Ströme_IF Inst", ("IF", "Ströme", "Inst")),   # as before
])
def test_short_name_device_prefix(name, expected):
    """A recorder/device prefix ``<name> <number>_`` is removed, whatever the device."""
    assert short_name(name) == expected


@pytest.mark.parametrize("name,expected", [
    ("System 1_V1 Inst", ("V1", "System 1", "Inst")),               # a channel group, not a device prefix
    ("Ströme_IF Inst", ("IF", "Ströme", "Inst")), ("UE_70m", ("UE_70m", "", "")), ("IPEN_v", ("IPEN_v", "", "")),
    ("i_20kv_res_j01_ct_m01_a__raw", ("i_20kv_res_j01_ct_m01_a__raw", "", "")), ("IF1 RMS", ("IF1", "", "RMS")),
    ("System1_V1", ("V1", "System1", "")),
])
def test_short_name_without_device_prefix(name, expected):
    """Names without a device prefix are not changed (apart from the group and the kind of values)."""
    assert short_name(name) == expected


def test_roles_with_other_device_prefixes():
    assert detect_role("REC 2_Ströme_IF1 Inst", "A") == ("i_res", None)
    assert detect_role("Recorder-A 3_Spannungen_UE_70m Inst", "V") == ("u_e", 70.0)
    assert detect_role("REC 2_System 1_V3 Inst", "V") == ("u_l3e", None)


def test_main_channel_ranking_fault_current():
    names = ["DANEO 1_Ströme_IFx Inst", "DANEO 1_Ströme_IFr50 Inst", "DANEO 1_Ströme_IFr500 Inst"]
    r = detect_roles(names, ["A"] * 3)
    assert r.main("i_res").short == "IFr500"           # largest measuring range (no saturation)
    r = detect_roles(["DANEO 1_Ströme_IF2 Inst", "DANEO 1_Ströme_IF1 Inst"], ["A", "A"])
    assert r.main("i_res").short == "IF1"
    r = detect_roles(names, ["A"] * 3, main_channel={"i_res": "IFx"})
    assert r.main("i_res").short == "IFx"


def test_capabilities_and_overrides():
    names = ["DANEO 1_System 1_V1 Inst", "DANEO 1_System 1_V2 Inst", "DANEO 1_System 1_V3 Inst",
             "DANEO 1_Ströme_IF Inst", "DANEO 1_Ströme_ISp21 Inst"]
    r = detect_roles(names, ["V", "V", "V", "A", "A"])
    f = r.capabilities()
    assert f["angle_method"] and f["coil_currents"] and not f["station"] and r.measurement_kind() == "substation"
    r2 = detect_roles(names, ["V", "V", "V", "A", "A"], overrides={"ISp21": None})
    assert not r2.has("i_coil")


def test_role_descriptions_in_german_and_english():
    """The role codes stay the keys of ROLE_DESCRIPTIONS (English texts); role_description follows the language."""
    assert set(ROLE_DESCRIPTIONS) == {"u_l1e", "u_l2e", "u_l3e", "u_hv_l1e", "u_hv_l2e", "u_hv_l3e", "u_l12",
                                      "u_l23", "u_l31", "u_ne", "u_e", "u_t", "u_gen", "i_res", "i_coil", "i_l1",
                                      "i_l2", "i_l3", "i_shield", "i_pen", "i_gen", None}
    assert ROLE_DESCRIPTIONS["i_res"] == "residual earth-fault current"
    assert role_description("i_res") == "Erdschlussreststrom"
    assert role_description(None) == "– (nicht zugeordnet)"
    assert role_description("i_unknown") == "" and role_description("i_unknown", "–") == "–"
    assert pen_position_description("busbar") == "n – zur HES (nach dem Trafoknoten)"
    assert pen_position_description(None) == ""
    with i18n.language("en"):
        assert role_description("u_e") == "earth potential rise"
        assert role_description(None) == "– (not assigned)"
        assert pen_position_description("feeders") == PEN_POSITION_DESCRIPTIONS["feeders"]
    assert role_description("u_t", lang="en") == "touch voltage"


def test_role_table_and_touch_voltage_source_in_german_and_english():
    """Role table with descriptions in the active language; the source of a touch voltage derived from the probe
    distances is a text in the language of the detection, the approximation is also marked by a flag."""
    names = ["DANEO 1_Spannungen_UE_5m Inst", "DANEO 1_Spannungen_UE_70m Inst", "DANEO 1_Ströme_IPEN_v Inst",
             "DANEO 1_Ströme_IF1 Inst"]
    units = ["V", "V", "A", "A"]
    r = detect_roles(names, units)
    t = r.table().set_index("short")
    assert t.at["UE_5m", "role"] == "u_t" and t.at["UE_5m", "meaning"] == "Berührungsspannung"
    assert t.at["UE_5m", "source"] == "automatisch (kürzeste Sonde 5 m – Näherung)"
    assert t.at["IPEN_v", "position"] == "v – NS-Abgänge (vor dem Trafoknoten)"
    assert r.channels[0].touch_approximation and not r.channels[1].touch_approximation
    with i18n.language("en"):
        r = detect_roles(names, units)
        t = r.table().set_index("short")
    assert t.at["UE_5m", "meaning"] == "touch voltage" and t.at["IF1", "meaning"] == "residual earth-fault current"
    assert t.at["UE_5m", "source"] == "automatic (shortest probe 5 m – approximation)"
    assert t.at["UE_70m", "source"] == "automatic" and t.at["UE_70m", "main_channel"] == "✓"
    assert t.at["IPEN_v", "position"] == "feeders – LV feeders (before the transformer star point)"
    assert r.channels[0].touch_approximation
    # a probe within 1.5 m measures the touch voltage (no approximation); German with a decimal comma
    names = ["DANEO 1_Spannungen_UEr Inst", "DANEO 1_Spannungen_UE_70m Inst"]
    r = detect_roles(names, ["V", "V"], distances={"UEr": 1.5})
    assert r.channels[0].role == "u_t" and r.channels[0].source == "automatisch (Sonde 1,5 m)"
    assert not r.channels[0].touch_approximation and "position" not in r.table().columns
    with i18n.language("en"):
        assert detect_roles(names, ["V", "V"], distances={"UEr": 1.5}).channels[0].source == "automatic (probe 1.5 m)"


def test_main_channel_error_in_german_and_english():
    names = ["DANEO 1_Ströme_IF1 Inst", "DANEO 1_Ströme_IF2 Inst"]
    r = detect_roles(names, ["A", "A"], main_channel={"i_res": "IF3"})
    with pytest.raises(KeyError, match=r"Hauptkanal 'IF3' für Rolle i_res nicht unter \['IF1', 'IF2'\]"):
        r.main("i_res")
    with i18n.language("en"), pytest.raises(KeyError, match=r"Main channel 'IF3' for role i_res not among"):
        r.main("i_res")


def test_message_catalog_complete():
    """Every message of the channel roles exists in English and German."""
    for lang in ("en", "de"):
        assert [m for m in i18n.missing_keys(lang) if m.startswith("channels.")] == []


def test_demo_with_structured_channel_names(tmp_path):
    """The demo writes the structured naming convention on request; the roles follow from the names alone and the
    evaluation finds the fault current, the voltages and the coil currents."""
    from groundfault import Intervals, demo, evaluate, open_recording
    p = str(tmp_path / "SUB_0_10_000kHz.cfg")
    w = demo.make_substation_recording(p, 0.0, duration=8.0, t_off=5.0, active_step=None, channel_names="structured")
    rec = open_recording(p)
    roles = {k.name: k.role for k in detect_roles(rec.channel_names, rec.units).channels}
    assert roles["i_20kv_res_j01_ct_m01_a__raw"] == "i_res" and roles["i_20kv_res_j01_rog_m02_a__raw"] == "i_res"
    assert [roles["u_20kv_l%de_j02_vt_m01_v__raw" % x] for x in (1, 2, 3)] == ["u_l1e", "u_l2e", "u_l3e"]
    assert {r for n, r in roles.items() if "_coil_" in n} == {"i_coil"}
    b = w["intervals"]
    res = evaluate(rec, Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]), tuple(b["post_fault"])))
    assert res.values["faulted_phase"] == "L3"


MIXED_LEVELS = {   # structured names of a recording with several voltage levels → role
    "u_20kv_l1e_j02_vt_m01_v__raw": "u_l1e", "u_20kv_l2e_j02_vt_m01_v__raw": "u_l2e",
    "u_20kv_l3e_j02_vt_m01_v__raw": "u_l3e", "i_20kv_res_j01_ct_m01_a__raw": "i_res",
    "i_20kv_coil_esp21_ct_m01_a__raw": "i_coil", "u_20kv_l12_j02_vt_m01_v__raw": "u_l12",
    "u_110kv_l1e_j03_vt_m01_v__raw": "u_hv_l1e", "u_110kv_l2e_j03_vt_m01_v__raw": "u_hv_l2e",
    "u_110kv_l3e_j03_vt_m01_v__raw": "u_hv_l3e", "u_110kv_l12_j03_vt_m01_v__raw": "u_gen",
    "u_110kv_ne_j03_vt_m01_v__raw": "u_gen", "i_110kv_l1_j03_ct_m01_a__raw": "i_gen",
    "i_110kv_coil_j03_ct_m01_a__raw": "i_gen",
    "i_0_4kv_n_j04_ct_m01_a__raw": "i_pen", "u_0.4kv_l1e_j04_vt_m01_v__raw": "u_gen",
    "i_400v_l1_j04_ct_m01_a__raw": "i_gen", "u_0,4kv_l12_j04_vt_m01_v__raw": "u_gen",
}


def test_structured_names_with_several_voltage_levels():
    """With channels of several voltage levels only the MV level (1 … 60 kV) gets the roles of the MV network; HV
    line-to-earth voltages get the HV roles, the LV neutral current i_pen, everything else u_gen/i_gen. Decimal
    levels (0.4kv, 0_4kv, 0,4kv, 400v) are read."""
    names = list(MIXED_LEVELS)
    r = detect_roles(names, ["A" if n.startswith("i_") else "V" for n in names])
    assert {k.name: k.role for k in r.channels} == MIXED_LEVELS
    assert [r.channels[i].name[:6] for i in r.line_to_earth] == ["u_20kv"] * 3
    assert [r.channels[i].name[:7] for i in r.line_to_earth_hv] == ["u_110kv"] * 3
    assert r.main("i_res").name == "i_20kv_res_j01_ct_m01_a__raw"


@pytest.mark.parametrize("names,expected", [
    (["u_110kv_l1e_j03_vt_m01_v__raw", "i_110kv_res_j01_ct_m01_a__raw"], ["u_l1e", "i_res"]),    # only one level
    (["u_0_4kv_l1e_a__raw", "u_0.4kv_l2e_a__raw", "u_400v_l3e_a__raw"], ["u_l1e", "u_l2e", "u_l3e"]),   # 0.4 kV
    (["u_20kv_l1e_a__raw", "u_10kv_l1e_a__raw"], ["u_l1e", "u_l1e"]),                         # two MV levels
    (["u_110kv_l1e_a__raw", "u_0_4kv_l1e_a__raw", "i_0_4kv_n_a__raw"], ["u_hv_l1e", "u_gen", "i_pen"]),   # no MV
])
def test_structured_names_mv_level_of_the_recording(names, expected):
    """The MV level of a recording is its only voltage level; with several levels the levels from 1 kV to below
    60 kV (none: no MV roles)."""
    r = detect_roles(names, ["A" if n.startswith("i_") else "V" for n in names])
    assert [k.role for k in r.channels] == expected


def test_structured_names_unchanged_and_standalone():
    """Names recognised so far keep their roles; detect_role without context takes the level of the name as the
    MV level."""
    for name, (role, _) in EXPORT_CHANNELS.items():
        if name[:2] in ("i_", "u_"):
            assert detect_role(name, "A" if name.startswith("i_") else "V") == (role, None)
            assert detect_role(name, "A", mv_levels_kv=[20.0])[0] == role
    assert detect_role("u_110kv_l1e_j03_vt_m01_v__raw", "V") == ("u_l1e", None)
    assert detect_role("u_110kv_l1e_j03_vt_m01_v__raw", "V", mv_levels_kv=[20.0]) == ("u_hv_l1e", None)
    assert detect_role("u_0_4kv_l1e_j04_vt_m01_v__raw", "V", mv_levels_kv=[20.0]) == ("u_gen", None)


def test_main_channel_from_corrections_with_several_levels():
    """A main channel from the corrections file (without a role) is assigned to the role it gets in the
    recording – an HV line-to-earth voltage to u_hv_l1e."""
    from types import SimpleNamespace
    from groundfault import corrections
    names = ["u_20kv_l1e_j02_vt_m01_v__raw", "u_110kv_l1e_j03_vt_m01_v__raw", "u_110kv_l1e_j03_vt_m02_v__raw"]
    rec = SimpleNamespace(cfg_path="/x/SUB_0_10_000kHz.cfg", channel_names=names, units=["V"] * 3)
    k = corrections.Corrections([corrections.CorrectionRule(file="*", channel="u_110kv_l1e_j03_vt_m02*",
                                                            main_channel=True, line=2)])
    main = k.main_channel(rec)
    assert main == {"u_hv_l1e": "u_110kv_l1e_j03_vt_m02_v__raw"}
    r = detect_roles(names, ["V"] * 3, main_channel=main)
    assert r.main("u_hv_l1e").name == "u_110kv_l1e_j03_vt_m02_v__raw" and r.main("u_l1e").name == names[0]


def test_role_table_source_in_german():
    """The origin of a role (codes automatic/override) has German labels in localized tables."""
    names = ["DANEO 1_Ströme_IF1 Inst", "DANEO 1_Ströme_ISp21 Inst"]
    t = detect_roles(names, ["A", "A"], overrides={"ISp21": "i_coil"}).table()
    assert list(t["source"]) == ["automatic", "override"]
    assert list(i18n.localize(t, "de")["Quelle"]) == ["automatisch", "vorgabe"]


def test_main_channel_and_overrides_with_former_and_unknown_roles():
    """Role names of the predecessor are translated in the main-channel mapping as in the overrides (before, they
    were ignored there); unknown roles raise in both."""
    names = ["DANEO 1_Ströme_IF1 Inst", "DANEO 1_Ströme_IS1 Inst", "DANEO 1_Ströme_IS2 Inst"]
    shields = {"IS1": "i_shield", "IS2": "i_schirm"}
    r = detect_roles(names, ["A"] * 3, overrides=shields, main_channel={"i_schirm": "IS2"})
    assert [k.short for k in r.with_role("i_shield")] == ["IS1", "IS2"] and r.main("i_shield").short == "IS2"
    assert detect_roles(names, ["A"] * 3, overrides=shields).main("i_shield").short == "IS1"
    r = detect_roles(["IPEN_a", "IPEN_b"], ["A", "A"], overrides={"IPEN_a": "i_pen_v", "IPEN_b": "i_pen_n"},
                     main_channel={"i_pen_n": "IPEN_b"})
    assert [k.position for k in r.channels] == ["feeders", "busbar"] and r.main("i_pen").short == "IPEN_b"
    with pytest.raises(ValueError, match="^main_channel='i_ress' ist nicht zulässig – zulässig: 'u_l1e'"):
        detect_roles(names, ["A"] * 3, main_channel={"i_ress": "IF1"})
    with i18n.language("en"), pytest.raises(ValueError, match="^overrides='strom' is not allowed – allowed: 'u_l1e'"):
        detect_roles(names, ["A"] * 3, overrides={"IF1": "strom"})
    assert not detect_roles(names, ["A"] * 3, overrides={"IF1": None}).has("i_res")
