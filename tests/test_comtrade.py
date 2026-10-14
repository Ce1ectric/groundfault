# -*- coding: utf-8 -*-
"""COMTRADE reading and writing: formats, scaling (a, b, PS), timemult, digital channels, block functions; messages
of the reader and of the demo recordings in German and English."""

from pathlib import Path

import numpy as np
import pytest

from groundfault import demo, i18n
from groundfault.comtrade import ComtradeError, open_recording, write_comtrade


def _signals(n=20000, fs=10000.0):
    t = np.arange(n) / fs
    return {"DANEO 1_System 1_V1 Inst": ("V", 16000 * np.cos(2 * np.pi * 50 * t) + 120.0),
            "DANEO 1_Ströme_IF Inst": ("A", 50 * np.sin(2 * np.pi * 250 * t) - 3.0),
            "DANEO 1_Ströme_ISp21 Inst": ("A", 400 * np.sin(2 * np.pi * 50 * t + 1.0))}


@pytest.mark.parametrize("fmt,tol", [("BINARY", 1e-4), ("BINARY32", 1e-8), ("FLOAT32", 1e-6), ("ASCII", 1e-4)])
def test_round_trip_formats(tmp_path, fmt, tol):
    sig = _signals()
    p = str(tmp_path / ("t_%s.cfg" % fmt))
    write_comtrade(p, sig, 10000.0, file_format=fmt, offsets={"DANEO 1_Ströme_IF Inst": 7.5})
    with open_recording(p) as rec:
        assert rec.fs == 10000.0 and rec.n == 20000 and rec.file_format == fmt
        x = rec.read(0, rec.n)
        for j, (nm, (unit, v)) in enumerate(sig.items()):
            span = np.max(np.abs(v))
            assert np.max(np.abs(x[:, j] - v)) <= tol * span * 2 + 1e-9, nm
        assert rec.units == ["V", "A", "A"]
        assert "Ströme" in rec.channel_names[1]          # cp1252 umlaut read correctly


def test_primary_secondary_and_timemult(tmp_path):
    t = np.arange(4000) / 4000.0
    p = str(tmp_path / "ps.cfg")
    write_comtrade(p, {"I": ("A", np.sin(2 * np.pi * 50 * t))}, 4000.0, ps="S", primary=600.0, secondary=5.0,
                      timemult=10.0)
    with open_recording(p) as rec:
        assert rec.timemult == 10.0
        assert rec.fs_timestamps == pytest.approx(4000.0, rel=1e-3)
        assert np.max(rec.read(0, rec.n)[:, 0]) == pytest.approx(120.0, rel=1e-3)      # 1 A secondary × 600/5
    with open_recording(p, primary_values=False) as rec:
        assert np.max(rec.read(0, rec.n)[:, 0]) == pytest.approx(1.0, rel=1e-3)


def test_digital_channels(tmp_path):
    n = 1000
    dig = {"Trigger": (np.arange(n) >= 300).astype(int), "Toggle": (np.arange(n) % 2).astype(int)}
    p = str(tmp_path / "dig.cfg")
    write_comtrade(p, {"U": ("V", np.zeros(n))}, 1000.0, digital=dig)
    with open_recording(p) as rec:
        d = rec.digital_values()
        assert d.shape == (n, 2) and d[299, 0] == 0 and d[300, 0] == 1
        assert np.array_equal(d[:, 1], dig["Toggle"].astype(bool))


def test_read_with_shift_and_edge(tmp_path):
    n = 1000
    p = str(tmp_path / "v.cfg")
    write_comtrade(p, {"A": ("V", np.arange(n, dtype=float)), "B": ("V", np.arange(n, dtype=float))}, 1000.0,
                      file_format="FLOAT32")
    with open_recording(p) as rec:
        x = rec.read(100, 200, None, {1: 50})
        assert x[0, 0] == 100 and x[0, 1] == 150
        x = rec.read(950, 1000, None, {1: 30})
        assert np.isnan(x[-1, 1]) and x[0, 1] == 980


def test_envelope_and_rms_trend_block_by_block(tmp_path):
    fs = 10000.0
    n = 50000
    t = np.arange(n) / fs
    v = 100 * np.sqrt(2) * np.sin(2 * np.pi * 50 * t) * (t > 2) + 5.0
    p = str(tmp_path / "h.cfg")
    write_comtrade(p, {"I": ("A", v)}, fs)
    with open_recording(p) as rec:
        tt, lo, hi = rec.envelope(n_bins=100, block=1000)       # small blocks → tests the block boundaries
        assert hi.max() == pytest.approx(v.max(), rel=1e-3) and lo.min() == pytest.approx(v.min(), rel=1e-3)
        tr, R = rec.rms_trend(window_s=0.02, block_s=0.5)
        assert R[tr < 1.9].max() < 0.05                            # DC (5 A) removed
        assert np.median(R[tr > 2.1]) == pytest.approx(100.0, rel=1e-3)


def test_index_unambiguous(tmp_path):
    p = str(tmp_path / "i.cfg")
    write_comtrade(p, {"DANEO 1_Ströme_IFr500 Inst": ("A", np.zeros(10)),
                          "DANEO 1_Ströme_IFr50 Inst": ("A", np.zeros(10))}, 1000.0)
    with open_recording(p) as rec:
        assert rec.index("IFr50") == 1 and rec.index("IFr500") == 0
        with pytest.raises(KeyError):
            rec.index("IFr")


def test_reading_leaves_no_open_file(tmp_path):
    """Opening a recording (also without ``with`` and with a malformed ``.cfg``) leaves no file handle behind."""
    import gc
    import warnings
    p = str(tmp_path / "rw.cfg")
    write_comtrade(p, {"A": ("V", np.zeros(100))}, 1000.0)
    bad = tmp_path / "bad.cfg"
    bad.write_text("only one line\n")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        rec = open_recording(p)
        assert rec.n == 100
        rec.close()
        del rec
        with pytest.raises(ComtradeError):
            open_recording(str(bad))
        gc.collect()
    assert [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)] == []


def test_malformed_files(tmp_path):
    p = tmp_path / "x.cfg"
    p.write_text("only one line\n")
    with pytest.raises(ComtradeError):
        open_recording(str(p))
    p2 = str(tmp_path / "k.cfg")
    write_comtrade(p2, {"A": ("V", np.zeros(100))}, 1000.0)
    with open(p2.replace(".cfg", ".dat"), "ab") as f:          # truncated / too long record
        f.write(b"\x00\x01\x02")
    with pytest.warns(UserWarning):
        rec = open_recording(p2)
    assert any("Rest" in w for w in rec.warnings)


def test_timestamp_check_warns_on_deviation(tmp_path):
    p = str(tmp_path / "fs.cfg")
    write_comtrade(p, {"A": ("V", np.zeros(5000))}, 10000.0)
    txt = Path(p).read_text(encoding="cp1252").replace("10000,5000", "9000,5000")
    Path(p).write_text(txt, encoding="cp1252")
    with pytest.warns(UserWarning):
        rec = open_recording(p)
    assert rec.fs == 9000.0 and rec.fs_timestamps == pytest.approx(10000.0)
    rec2 = open_recording(p, fs_source_pref="timestamps", emit_warnings=False)
    assert rec2.fs == pytest.approx(10000.0)


def test_messages_in_english(tmp_path):
    """Findings, errors and the origin of the sampling rate in English (decimal point) and German (decimal
    comma)."""
    p = str(tmp_path / "fs.cfg")
    write_comtrade(p, {"DANEO 1_Ströme_IFr500 Inst": ("A", np.zeros(5000)),
                       "DANEO 1_Ströme_IFr50 Inst": ("A", np.zeros(5000))}, 10000.0)
    txt = Path(p).read_text(encoding="cp1252").replace("10000,5000", "9000,5000")
    Path(p).write_text(txt, encoding="cp1252")
    with open(p.replace(".cfg", ".dat"), "ab") as f:
        f.write(b"\x00\x01\x02")
    with i18n.language("en"):
        rec = open_recording(p, emit_warnings=False)
        with pytest.raises(KeyError, match="not found unambiguously"):
            rec.index("IFr")
        with pytest.raises(ValueError, match=r"Correction factor must be finite and ≠ 0 \(channel IFr50: 0\)"):
            rec.set_correction("IFr50", 0)
        assert open_recording(p, fs_override=8000.0, emit_warnings=False).fs_source == "manual (FS_OVERRIDE)"
    assert "DAT size is not a multiple of the record length (3 B left over) – file possibly truncated." in rec.warnings
    assert any(w.startswith("Sampling rate from the timestamps (10000.000 Hz) deviates by 11.11 % from the .cfg "
                            "(9000.000 Hz)") for w in rec.warnings)
    assert repr(rec).startswith("<Recording fs.cfg | 2 channels | 9000 Hz |")
    rec_de = open_recording(p, emit_warnings=False)
    assert any(w.startswith("Abtastrate aus Zeitstempeln (10000,000 Hz) weicht um 11,11 % von der .cfg "
                            "(9000,000 Hz) ab") for w in rec_de.warnings)
    assert open_recording(p, fs_override=8000.0, emit_warnings=False).fs_source == "manuell (FS_OVERRIDE)"
    short = tmp_path / "short.cfg"
    short.write_text("only one line\n")
    with i18n.language("en"), pytest.raises(ComtradeError, match="CFG too short"):
        open_recording(str(short))
    with pytest.raises(ComtradeError, match="CFG zu kurz"):
        open_recording(str(short))


def test_demo_messages(tmp_path):
    """Invalid arguments of the demo recordings are reported in the active language."""
    p = str(tmp_path / "SUB_0_10_000kHz.cfg")
    with pytest.raises(ValueError, match=r"Nur eine Stufe je Aufzeichnung \(active_step oder reactive_step\)"):
        demo.make_substation_recording(p, active_step=(4.6, 5.4, 15.0), reactive_step=(4.6, 5.4, 5.0))
    with i18n.language("en"), pytest.raises(ValueError, match=r"Only one step per recording"):
        demo.make_substation_recording(p, active_step=(4.6, 5.4, 15.0), reactive_step=(4.6, 5.4, 5.0))
    with i18n.language("en"), pytest.raises(ValueError, match=r"\|Z_LV\| must be larger than \|Z_E\|"):
        demo.make_station_recording(str(tmp_path / "station.cfg"), duration=2.0, t_on=0.5, t_off=1.5,
                                    lv_network=dict(R_LV=0.5, X_LV1=0.01))


def test_message_catalog_complete():
    """Every message of the COMTRADE reader and of the demo recordings exists in English and German."""
    for lang in ("en", "de"):
        assert [m for m in i18n.missing_keys(lang) if m.startswith(("comtrade.", "demo."))] == []
