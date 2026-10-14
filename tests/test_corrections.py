# -*- coding: utf-8 -*-
"""Corrections per campaign (``notes/corrections.csv``, German layout ``0_Notizen/Korrekturen.csv``): reading,
applying, documentation and the physical cross-check by the coil-current balance."""
import json
import os
from pathlib import Path

import numpy as np
import pytest

from groundfault import Intervals, demo, detect_roles, corrections, i18n, open_recording, evaluate


def _csv(folder, text, enc="utf-8-sig", layout="de"):
    """Write a corrections file into the notes folder of ``folder`` (German layout by default)."""
    p = corrections.path_for(folder, layout=layout)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding=enc) as f:
        f.write(text)
    return p


@pytest.mark.parametrize("text,value", [("10", 10.0), ("0,1", 0.1), ("1/3", 1 / 3), ("−1", -1.0), ("x3", 3.0),
                                       ("", 1.0), ("2.5", 2.5), ("1.000,5", 1000.5)])
def test_parse_factor(text, value):
    assert corrections.parse_factor(text) == pytest.approx(value)


def test_read_csv_comments_separators_and_errors(tmp_path):
    """German headers and values (predecessor files): comments, separators, line numbers and invalid entries."""
    _csv(tmp_path, "# Kommentar\nDatei;Kanal;Faktor;Rolle;Hauptkanal;Bemerkung\n"
                   "UW_7_5_*;ISp22;10;;;Übersetzung falsch\n# UW_*;IF3;;ignorieren;;aus\n"
                   "UW_*;ISp21;2;;;nur die Hälfte gemessen\n*;IF3;;ignorieren;;Kanal nicht belegt\n;;;;;\n")
    k = corrections.load(tmp_path)
    assert len(k) == 3 and k.rules[0].factor == 10 and k.rules[2].role is None
    assert k.rules[1].line == 5                              # line number of the file (for queries)
    # comma as separator (spreadsheet with an English locale)
    _csv(tmp_path, "Datei,Kanal,Faktor\nUW_*,ISp21,2\n")
    assert corrections.load(tmp_path).rules[0].factor == 2
    for wrong in ("Datei;Kanal;Faktor\nUW_*;ISp21;zwei\n", "Datei;Kanal;Faktor\nUW_*;ISp21;0\n",
                  "Datei;Kanal;Rolle\nUW_*;ISp21;spule\n", "Kanal;Faktor\nISp;2\n"):
        _csv(tmp_path, wrong)
        with pytest.raises(ValueError):
            corrections.load(tmp_path)
    assert len(corrections.load(tmp_path / "does_not_exist")) == 0
    _csv(tmp_path, "Datei;Kanal;Faktor;Rolle;Hauptkanal;Bemerkung\nUW_*;ISp21;2;;;nur 1/2; bestätigt; Notiz\n")
    assert corrections.load(tmp_path).rules[0].remark == "nur 1/2; bestätigt; Notiz"


def test_english_layout_and_messages(tmp_path):
    """English headers and values in ``notes/corrections.csv``; error messages in both languages."""
    p = _csv(tmp_path, "file;channel;factor;role;main_channel;distance_m;remark\n"
                       "SUB_*;ISp21;2;;;;clamp on one of two cables\n*;IF3;;ignore;;;spare channel\n"
                       "*;IF2;;;yes;;main channel\n*;IPEN1;;i_pen_feeders;;;PEN of the LV feeders\n"
                       "Station_*;UE?;;;;40;probes right/left at 40 m\n", layout="en")
    assert p.endswith(os.path.join("notes", "corrections.csv"))
    k = corrections.load(tmp_path)
    assert [r.factor for r in k.rules] == [2.0, 1.0, 1.0, 1.0, 1.0]
    assert k.rules[1].role is None and k.rules[2].main_channel and k.rules[3].role == "i_pen_feeders"
    assert k.rules[4].distance_m == 40.0 and k.rules[4].remark == "probes right/left at 40 m"
    t = k.table()
    assert list(t["role"]) == ["", "ignore", "", "i_pen_feeders", ""] and list(t["main_channel"]) == ["", "", "yes",
                                                                                                    "", ""]
    _csv(tmp_path, "file;channel;factor\nSUB_*;ISp;three\n", layout="en")
    with pytest.raises(ValueError, match="Faktor 'three' nicht lesbar"):
        corrections.load(tmp_path)
    with i18n.language("en"), pytest.raises(ValueError, match="factor 'three' not readable"):
        corrections.load(tmp_path)


def test_apply_multiplies_factors_once(tmp_path):
    demo.make_substation_recording(str(tmp_path / "UW_2_5_10_000kHz.cfg"), 2.5, duration=6.0, active_step=None)
    _csv(tmp_path, "Datei;Kanal;Faktor;Rolle;Hauptkanal;Bemerkung\nUW_2_5_*;ISp21;10;;;falsch\n"
                   "UW_*;ISp21;3;;;ein Drittel\nUW_*;ISp99;2;;;Tippfehler\nANDERE_*;ISp22;5;;;nicht diese Datei\n")
    k = corrections.load(tmp_path)
    raw = open_recording(str(tmp_path / "UW_2_5_10_000kHz.cfg"))
    rec = open_recording(str(tmp_path / "UW_2_5_10_000kHz.cfg"))
    log = k.apply(rec)
    k.apply(rec)                                            # a second call applies nothing
    j = rec.index("ISp21")
    x0, x1 = raw.read(0, 5000, [j])[:, 0], rec.read(0, 5000, [j])[:, 0]
    assert np.allclose(x1, 30 * x0)
    assert np.allclose(rec.read(0, 5000, ["ISp22"]), raw.read(0, 5000, ["ISp22"]))
    assert set(log["factor_total"]) == {30.0} and len(rec.corrections) == 2
    assert any("ISp99" in h for h in k.hints)
    t, lo, hi = rec.envelope(50, ["ISp21"])
    assert np.all(lo <= hi)


def test_hints_refer_to_the_last_apply(tmp_path):
    """Corrections.hints holds the hints of the last apply() call only – no accumulation over recordings, no
    duplicates; the queries (roles, main channel, distances, log) do not change it."""
    for name in ("UW_2_5_10_000kHz.cfg", "UW_5_10_000kHz.cfg"):
        demo.make_substation_recording(str(tmp_path / name), 2.5, duration=3.0, active_step=None)
    _csv(tmp_path, "Datei;Kanal;Faktor;Rolle;Hauptkanal;Bemerkung\nUW_2_5_*;ISp99;2;;;Tippfehler\n"
                   "UW_*;ISp21;3;;;ein Drittel\n")
    k = corrections.load(tmp_path)
    a, b = (open_recording(str(tmp_path / n)) for n in ("UW_2_5_10_000kHz.cfg", "UW_5_10_000kHz.cfg"))
    k.apply(a)
    assert len(k.hints) == 1 and "ISp99" in k.hints[0]
    k.role_overrides(a); k.main_channel(a); k.distances(a); k.log(a)
    assert len(k.hints) == 1
    k.apply(b)
    assert k.hints == [] and len(b.corrections) == 1
    k.apply(a)                                              # again: nothing applied twice, the hint is back
    assert len(k.hints) == 1 and "ISp99" in k.hints[0] and len(a.corrections) == 1


def test_roles_and_main_channel_from_corrections(tmp_path):
    demo.make_substation_recording(str(tmp_path / "UW_0_10_000kHz.cfg"), 0.0, duration=5.0, active_step=None)
    _csv(tmp_path, "Datei;Kanal;Faktor;Rolle;Hauptkanal;Bemerkung\n*;IF1;;ignorieren;;Zange defekt\n"
                   "*;IF2;;;ja;Hauptkanal\n")
    k = corrections.load(tmp_path)
    rec = open_recording(str(tmp_path / "UW_0_10_000kHz.cfg"))
    r = detect_roles(rec.channel_names, rec.units, k.role_overrides(rec), k.main_channel(rec))
    assert r.main("i_res").short == "IF2" and [x.short for x in r.with_role("i_res")] == ["IF2"]


def test_coil_current_balance_and_documentation(tmp_path):
    """Coil 1 is retuned by 12 A during the fault (Iv changes by the same amount). If the clamp measures only one
    half, the balance shows a slope ≈ 2; with the correction "× 2" it agrees again, and the correction appears in
    the hints, the plausibility table and the result file."""
    cfg = str(tmp_path / "UW_0_10_000kHz.cfg")
    demo.make_substation_recording(cfg, 0.0, duration=8.0, active_step=None, reactive_step=(4.6, 5.4, -12.0))
    B = Intervals((2.6, 5.9), (0.2, 1.8), (7.0, 7.8))
    correct = evaluate(open_recording(cfg), B)
    pr = correct.table("plausibility").set_index("check")
    assert pr.at["Spulenstrombilanz ΔIv ↔ ΔΣI_Spule", "status"] == "OK"
    assert correct.values["coil_balance_slope"] == pytest.approx(1.0, abs=0.05)
    half = open_recording(cfg)
    half.set_correction("ISp21", 1 / 2)                # the measuring chain captures only one half
    wrong = evaluate(half, B)
    pr = wrong.table("plausibility").set_index("check")
    assert pr.at["Spulenstrombilanz ΔIv ↔ ΔΣI_Spule", "status"] == "WARNING"
    assert wrong.values["coil_balance_slope"] == pytest.approx(2.0, rel=0.05)
    # the correction × 2 cancels the measuring-chain error again
    _csv(tmp_path, "Datei;Kanal;Faktor;Rolle;Hauptkanal;Bemerkung\nUW_*;ISp21;2;;;Zange auf 1 von 2 Leitern\n")
    rec = open_recording(cfg)
    rec.set_correction("ISp21", 1 / 2)
    corrections.load(tmp_path).apply(rec)
    res = evaluate(rec, B)
    pr = res.table("plausibility").set_index("check")
    assert pr.at["Spulenstrombilanz ΔIv ↔ ΔΣI_Spule", "status"] == "OK"
    assert pr.at["Korrekturen (0_Notizen/Korrekturen.csv)", "status"] == "CORRECTED"
    assert any("Zange auf 1 von 2 Leitern" in h for h in res.hints)
    p = res.save_json(str(tmp_path / "result.json"))
    meta = json.loads(Path(p).read_text(encoding="utf-8"))["meta"]
    assert [k["factor"] for k in meta["corrections"]] == pytest.approx([1 / 2, 2.0])


def test_reversed_probes_rotate_only_instantaneous_values(tmp_path):
    """Earth-potential probes connected with reversed polarity: U_E/I_F then lies 180° away from r·Z_E and the
    plausibility check reports it; the correction "−1" restores the true angle. In the RMS file (RMS values, no
    sign) the polarity must not be applied."""
    from groundfault import rms, write_comtrade
    truth = demo.make_station_recording(str(tmp_path / "correct.cfg"), duration=6.0)
    cfg = str(tmp_path / "Station_X_10_000kHz.cfg")
    with open_recording(str(tmp_path / "correct.cfg")) as q:          # "measurement" with reversed probes
        x = q.read(0, q.n)
        sig = {nm: (unit, -x[:, j] if "_UE_" in nm else x[:, j])
               for j, (nm, unit) in enumerate(zip(q.channel_names, q.units))}
        write_comtrade(cfg, sig, q.fs, t_start=q.t_start, trigger_s=q.trigger_s or 0.0)
    cfg_rms = demo.rms_file_from_instantaneous(cfg, str(tmp_path / "Station_X_10_000Hz.cfg"))
    B = Intervals(*[tuple(truth["intervals"][k]) for k in ("steady_state", "pre_fault", "post_fault")])
    assert any("Winkel U_E/I_F" in h for h in evaluate(open_recording(cfg), B).hints)
    _csv(tmp_path, "Datei;Kanal;Faktor;Rolle;Hauptkanal;Bemerkung\nStation_X_*;UE_*;-1;;;Sonden verpolt\n")
    k = corrections.load(tmp_path)
    rec, rec_rms = open_recording(cfg), open_recording(cfg_rms)
    k.apply(rec)
    k.apply(rec_rms)
    corrected = evaluate(rec, B)
    assert not any("Winkel U_E/I_F" in h for h in corrected.hints)
    st = corrected.table("station_voltages").set_index("channel")
    target = np.degrees(np.angle(truth["orders"][1]["rZE"]))
    assert st.at["UE_70m", "rZE_H1_angle_deg"] == pytest.approx(target, abs=2.0)
    # RMS file: RMS values stay positive, the polarity has no effect there, the comparison contains the probes
    assert not rec_rms.corrections and any("Effektivwerte" in h for h in k.hints)
    j = [i for i, nm in enumerate(rec_rms.channel_names) if "_UE_" in nm]
    assert np.nanmin(rec_rms.read(0, rec_rms.n, j)) >= 0
    v = rms.compare_with_instantaneous(rec, rec_rms, B.steady_state).set_index("channel")
    assert {"UE_5m", "UE_70m"} <= set(v.index)
    assert abs(v.at["UE_70m", "deviation_median_pct"]) < 2.0


@pytest.mark.parametrize("layout,folder,file", [("de", "0_Notizen", "Korrekturen.csv"),
                                                ("en", "notes", "corrections.csv")])
def test_write_template(tmp_path, layout, folder, file):
    p = corrections.write_template(str(tmp_path), layout=layout)
    assert p == str(tmp_path / folder / file) and len(corrections.load(tmp_path)) == 0     # comments only
    assert Path(p).read_text(encoding="utf-8-sig").splitlines()[0] == ";".join(corrections.HEADERS[layout])
    assert corrections.write_template(str(tmp_path), layout=layout) is None               # never overwrite


def test_notes_folder_and_readme(tmp_path, monkeypatch):
    from groundfault import register
    monkeypatch.setenv("GROUNDMEAS_DB", str(tmp_path / "no_db.db"))           # template without groundmeas
    kd = tmp_path / "01_Messkampagnen" / "2026-01-15_Demo"
    (kd / "1_Rohdaten" / "UW").mkdir(parents=True)
    demo.make_substation_series(str(kd / "1_Rohdaten" / "UW"), Z_values=(0.0,), prefix="UW")
    (kd / "Notizen_Messung.txt").write_text("Zange IF2 am Abgang 3\n", encoding="utf-8")
    act = register.create_notes_folder(str(kd))
    assert (kd / "0_Notizen" / "Notizen_Messung.txt").read_text(encoding="utf-8") == "Zange IF2 am Abgang 3\n"
    assert not (kd / "Notizen_Messung.txt").exists() and any("verschoben" in a for a in act)
    assert (kd / "0_Notizen" / "Korrekturen.csv").exists() and (kd / "0_Notizen" / "Messorte.csv").exists()
    assert any("Messorte.csv" in a for a in act)
    assert register.create_notes_folder(str(kd)) == []                     # second run: nothing to do
    _csv(kd, "Datei;Kanal;Faktor;Rolle;Hauptkanal;Bemerkung\nUW_*;ISp22;2;;;nur die Hälfte gemessen\n")
    r = register.update_all(str(tmp_path))
    txt = (kd / "LIESMICH.md").read_text(encoding="utf-8")
    assert "nur die Hälfte gemessen" in txt and "Zange IF2 am Abgang 3" in txt and r["files"] == 1
    assert "Messorte für groundmeas" in txt and "UW Demo" in txt


def test_probe_distance_from_corrections(tmp_path):
    """Channels without a distance in the name (UEr/UEl): distance_m from the corrections file → role table,
    station_frequency (comparison, groundmeas entry); older files without the column stay readable."""
    p = str(tmp_path / "Station_Elm_Road_10_000kHz.cfg")
    w = demo.make_station_recording(p, probes={"UEr": 0.93, "UEl": 0.9}, with_voltages=False)
    _csv(tmp_path, "Datei;Kanal;Faktor;Rolle;Hauptkanal;Abstand_m;Bemerkung\n"
                   "Station_Elm_Road_*;UE?;;;;40 m;Sonden rechts/links ohne Abstand im Namen\n"
                   "ANDERE_*;UT;;;;1;andere Datei\n")
    k = corrections.load(tmp_path)
    assert k.rules[0].distance_m == 40.0 and k.rules[0].factor == 1.0 and k.rules[1].distance_m == 1.0
    assert list(k.table()["distance_m"]) == [40.0, 1.0]
    rec = open_recording(p)
    assert k.apply(rec)["distance_m"].tolist() == [40.0, 40.0] and not rec.corrections   # no factor
    distances = k.distances(rec)
    assert sorted(distances.values()) == [40.0, 40.0] and all("UE" in n for n in distances)
    r = detect_roles(rec.channel_names, rec.units, k.role_overrides(rec), k.main_channel(rec), distances)
    t = r.table().set_index("short")
    assert t.loc["UEr", "distance_m"] == 40.0 and t.loc["UEl", "distance_m"] == 40.0 and t.loc["UT", "role"] == "u_t"
    b = w["intervals"]
    res = evaluate(rec, Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]), tuple(b["post_fault"])), roles=r)
    sf = res.table("station_frequency")
    assert set(sf[sf["role"] == "u_e"]["distance_m"]) == {40.0}
    for wrong in ("abc", "0", "-5"):
        _csv(tmp_path, "Datei;Kanal;Abstand_m\n*;UE;%s\n" % wrong)
        with pytest.raises(ValueError, match="Abstand_m"):
            corrections.load(tmp_path)
    _csv(tmp_path, "Datei;Kanal;Faktor;Rolle;Hauptkanal;Bemerkung\n*;UE;2;;;ältere Datei ohne Abstand_m\n")
    assert corrections.load(tmp_path).rules[0].distance_m is None
    assert "distance_m" in corrections.TEMPLATE.splitlines()[0]


@pytest.mark.parametrize("lang", ["en", "de"])
def test_errors_name_the_columns_of_the_file(tmp_path, lang):
    """An invalid probe distance is reported with the column name as written in the file (German or English
    headers), whatever the output language."""
    for layout, column in (("de", "Abstand_m"), ("en", "distance_m")):
        folder = tmp_path / layout
        _csv(folder, "%s\n*;UE;;;;abc;\n" % ";".join(corrections.HEADERS[layout]), layout=layout)
        with i18n.language(lang), pytest.raises(ValueError) as e:
            corrections.load(folder)
        assert ("line 2: %s 'abc'" % column if lang == "en" else "Zeile 2: %s 'abc'" % column) in str(e.value)
