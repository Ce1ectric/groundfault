# -*- coding: utf-8 -*-
"""Signal processing: windows, RMS values, phasors, Goertzel recursion, f1 estimation; messages in German and
English."""
import math
import re

import numpy as np
import pytest

from groundfault import dsp, i18n


def _sine(fs, T, f, rms, phi=0.0, dc=0.0):
    t = np.arange(int(round(T * fs))) / fs
    return math.sqrt(2) * rms * np.cos(2 * np.pi * f * t + phi) + dc


def test_hann_window_and_coherent_gain():
    w = dsp.hann(8001)
    assert w[0] == 0 and w[-1] == pytest.approx(0) and w[4000] == pytest.approx(1)
    assert dsp.coherent_gain(w) == pytest.approx(0.5, abs=1e-3)     # 0.5 for the Hann window
    assert dsp.coherent_gain(dsp.window_function(100, "rectangular")) == 1.0


def test_window_grid():
    nwin, nhop, starts = dsp.window_grid(40000 * 3, 40000, 0.2)
    assert nwin == 8000 and nhop == 8000 and len(starts) == 15


@pytest.mark.parametrize("fs", [10000.0, 40000.0])
def test_phasor_of_single_tone_off_bin(fs):
    """Tone of 50.03 Hz (not on the DFT grid) with a DC offset: magnitude and angle exact (phase referred to the
    start of the window)."""
    x = _sine(fs, 0.2, 50.03, 100.0, phi=0.7, dc=35.0)
    X, rms = dsp.dft_phasors(x[None, :], fs, [50.03])
    assert abs(X[0, 0]) == pytest.approx(100.0, rel=2e-4)
    assert np.angle(X[0, 0]) == pytest.approx(0.7, abs=2e-4)
    # true RMS value after removing the median ≈ 100 (the median of a non-integer number of periods differs
    # slightly from the mean)
    assert rms[0] == pytest.approx(100.0, rel=2e-3)


def test_dft_and_goertzel_identical():
    fs = 40000.0
    x = _sine(fs, 0.2, 50.0, 30.0, 0.3) + _sine(fs, 0.2, 250.0, 70.0, -1.0) + 3.0
    for f in (50.0, 250.0, 350.0):
        a = dsp.window_phasors(x, fs, [f])[0][0]
        b = dsp.goertzel_phasor(x, f, fs)
        assert abs(a - b) < 1e-8 * max(abs(a), 1.0)


def test_goertzel_numerics_long_window():
    """ω = 2π·50/40000 ≈ 0.0079 → the state grows like N/(2 sin ω); relative error < 1e-9 compared with the direct
    sum (cancellation is uncritical in float64)."""
    fs = 40000.0
    x = _sine(fs, 1.0, 50.0, 1.0, 0.1)            # N = 40000
    w0 = 2 * np.pi * 50 / fs
    direct = np.sum(x * np.exp(-1j * w0 * np.arange(x.size)))
    g = dsp.goertzel(x, 50.0, fs) * np.exp(-1j * w0 * x.size)
    assert abs(g - direct) / abs(direct) < 1e-9


def test_rms_equals_root_sum_of_squares_of_harmonics():
    """For a signal that consists of harmonics only, the true RMS value equals √(Σ|X_m|²) of the phasors."""
    fs = 10000.0
    parts = {1: 30.0, 3: 6.5, 5: 42.0, 7: 13.0}
    x = sum(_sine(fs, 0.2, m * 50.0, a, 0.2 * m) for m, a in parts.items())
    X, rms = dsp.dft_phasors(x[None, :], fs, [m * 50.0 for m in parts])
    assert rms[0] == pytest.approx(math.sqrt(np.sum(np.abs(X[0]) ** 2)), rel=1e-4)
    assert rms[0] == pytest.approx(math.sqrt(sum(v * v for v in parts.values())), rel=1e-4)


def test_remove_dc_median_robust_against_spikes():
    x = np.zeros(1000); x[:5] = 1e4
    assert dsp.remove_dc(x, "median")[100] == 0.0
    assert dsp.remove_dc(x, "mean")[100] == pytest.approx(-50.0)


def test_f1_three_methods_agree():
    fs = 10000.0
    rng = np.random.default_rng(3)
    t = np.arange(int(4 * fs)) / fs
    x = (math.sqrt(2) * 20000 * np.cos(2 * np.pi * 50.03 * t + 0.4)
         + math.sqrt(2) * 300 * np.cos(2 * np.pi * 250.15 * t) + 30 * rng.standard_normal(t.size) + 500)
    f_ph, _ = dsp.f1_phase_method(x, fs)
    f_sp, prom = dsp.f1_spectral(x, fs)
    f_zc = dsp.f1_zero_crossing(x, fs)
    for f in (f_ph, f_sp, f_zc):
        assert f == pytest.approx(50.03, abs=1e-3)
    e = dsp.estimate_f1(x, fs)
    assert e["plausible"] and abs(e["deviation_hz"]) < 1e-3


def test_f1_regression_orders_drift_and_gaps():
    """Regression of the phase trend: mean frequency of a section (with drift: the value in the middle) with an
    uncertainty from the residuals. If the fundamental component is weak, the strong 3rd harmonic measures f1 more
    accurately; windows with NaN are skipped; pure noise gives a large uncertainty."""
    fs = 10000.0
    rng = np.random.default_rng(5)
    t = np.arange(int(1.2 * fs)) / fs
    f0, a = 49.98, 0.01                                             # 10 mHz/s → middle (0.6 s): 49.986 Hz
    th = 2 * np.pi * (f0 * t + 0.5 * a * t ** 2)
    x = (math.sqrt(2) * 0.3 * np.cos(th + 1.2) + math.sqrt(2) * 5.0 * np.cos(3 * th + 0.2)
         + 0.3 * rng.standard_normal(t.size))
    f, s = dsp.f1_regression(x, fs, 50.0, (1, 3))
    assert f[1] == pytest.approx(f0 + a * 0.6, abs=5e-4) and s[1] < 5e-4
    assert s[0] > 3 * s[1]                                          # weak fundamental component: less certain
    x[3000:3500] = np.nan
    f2, s2 = dsp.f1_regression(x, fs, 50.0, 3)
    assert f2[0] == pytest.approx(f[1], abs=5e-4)
    f3, s3 = dsp.f1_regression(rng.standard_normal(t.size), fs, 50.0, (1, 3))
    assert np.all(~np.isfinite(s3) | (s3 > 0.002))
    assert np.isnan(dsp.f1_regression(x[:2000], fs, 50.0)[0][0])    # fewer than four windows


def test_f1_implausible_without_fundamental():
    fs = 10000.0
    x = np.random.default_rng(0).standard_normal(int(2 * fs))
    with pytest.warns(UserWarning):
        e = dsp.estimate_f1(x, fs)
    assert not e["plausible"]


def test_f1_notes_in_german_and_english():
    """The notes of the f1 estimate (shown in the plausibility checks) follow the language, with a decimal comma
    in German and a decimal point in English."""
    fs = 10000.0
    x = np.random.default_rng(0).standard_normal(int(2 * fs))
    with pytest.warns(UserWarning, match="f1-Schätzung unplausibel"):
        e = dsp.estimate_f1(x, fs)
    assert re.fullmatch(r"schwacher 50-Hz-Peak \(Prominenz \d+,\d\); Verfahren weichen um \d+,\d{3} Hz ab", e["note"])
    with i18n.language("en"), pytest.warns(UserWarning, match=r"f1 estimate implausible \(\d+\.\d{4} Hz\): weak"):
        e = dsp.estimate_f1(x, fs)
    assert re.fullmatch(r"weak 50-Hz peak \(prominence \d+\.\d\); methods differ by \d+\.\d{3} Hz", e["note"])


def test_error_messages_in_english():
    with i18n.language("en"):
        with pytest.raises(ValueError, match="^window='triangle' is not allowed – allowed: 'hann', 'hann_periodic', "
                                             "'rectangular'$"):
            dsp.window_function(10, "triangle")
        with pytest.raises(ValueError, match="^dc='mode' is not allowed – allowed: 'median', 'mean', 'none'$"):
            dsp.remove_dc(np.zeros(4), "mode")
        with pytest.raises(ValueError, match=r"Window too short \(N_win=1\)"):
            dsp.window_grid(100, 10.0, 0.1)
    with pytest.raises(ValueError, match="^window='triangle' ist nicht zulässig – zulässig: 'hann'"):
        dsp.window_function(10, "triangle")


def test_former_option_values_rejected_with_the_current_name():
    """Values of the predecessor tool are not accepted (they were misread or worked by accident): the error names
    the current value; English alternative names still work."""
    with i18n.language("en"):
        for kind, new in (("rechteck", "rectangular"), ("Hann_Periodisch", "hann_periodic"), ("keine", "rectangular")):
            with pytest.raises(ValueError, match=r"\('%s' is the former name of '%s'\)$" % (kind.lower(), new)):
                dsp.window_function(10, kind)
        for method, new in (("mittel", "mean"), ("mittelwert", "mean"), ("keine", "none")):
            with pytest.raises(ValueError, match=r"^dc='%s' is not allowed.*\('%s' is the former name of '%s'\)$"
                                                 % (method, method, new)):
                dsp.remove_dc(np.zeros(4), method)
        with pytest.raises(ValueError, match=r"^method='spektral' is not allowed – allowed: 'phase', 'spectral' "
                                             r"\('spektral' is the former name of 'spectral'\)$"):
            dsp.estimate_f1(np.zeros(1000), 1000.0, method="spektral")
    for kind in ("rect", "none", "hanning", "hann_p", "RECTANGULAR"):
        assert len(dsp.window_function(8, kind)) == 8
    assert dsp.remove_dc(np.ones(4), None).tolist() == dsp.remove_dc(np.ones(4), "none").tolist() == [1.0] * 4


def test_thd():
    assert dsp.thd([100, 3, 4], [1, 5, 7]) == pytest.approx(0.05)
    assert math.isnan(dsp.thd([3, 4], [5, 7]))


def test_decimate_preserves_fundamental():
    fs = 40000.0
    x = _sine(fs, 1.0, 50.0, 10.0) + _sine(fs, 1.0, 7000.0, 1.0)
    y, fs2 = dsp.decimate(x, fs, 4)
    assert fs2 == 10000.0
    X = dsp.window_phasors(y[2000:4000], fs2, [50.0])[0][0]
    assert abs(X) == pytest.approx(10.0, rel=1e-3)


def test_message_catalog_complete():
    """Every message of the signal processing exists in English and German."""
    for lang in ("en", "de"):
        assert [m for m in i18n.missing_keys(lang) if m.startswith("dsp.")] == []
