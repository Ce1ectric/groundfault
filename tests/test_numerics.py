# -*- coding: utf-8 -*-
"""Numerical stability and accuracy limits of the algorithms."""
import math

import numpy as np
import pytest

from groundfault import dsp, equivalent_source


def _tone(fs, T, f, a, phi=0.0):
    t = np.arange(int(round(T * fs))) / fs
    return math.sqrt(2) * a * np.cos(2 * np.pi * f * t + phi)


def test_large_dc_component_no_cancellation():
    """DC of 1e6 plus a 1-A signal: the median is removed before the DFT, no loss of accuracy (float64)."""
    fs = 10000.0
    x0 = _tone(fs, 0.2, 50.0, 1.0, 0.3)
    X, rms = dsp.dft_phasors((x0 + 1e6)[None, :], fs, [50.0])
    X0, _ = dsp.dft_phasors(x0[None, :], fs, [50.0])
    assert abs(X[0, 0] - X0[0, 0]) < 1e-9                  # the DC component does not affect the result
    assert abs(X[0, 0]) == pytest.approx(1.0, rel=1e-5)    # remainder: leakage of the image at −f (Hann window)
    assert rms[0] == pytest.approx(1.0, rel=2e-3)


def test_high_order_dft_goertzel():
    fs = 10000.0
    x = _tone(fs, 0.2, 40 * 50.0, 2.0, 1.0)
    a = dsp.window_phasors(x, fs, [2000.0])[0][0]
    b = dsp.goertzel_phasor(x, 2000.0, fs)
    assert abs(a) == pytest.approx(2.0, rel=1e-6) and abs(a - b) < 1e-9


def test_leakage_hann_versus_rectangular():
    """f1 = 50.4 Hz evaluated on the grid of the nominal frequency (non-integer number of periods): the strong
    fundamental component leaks into the 3rd harmonic. The Hann window attenuates the leakage considerably."""
    fs = 10000.0
    x = _tone(fs, 0.2, 50.4, 1000.0) + _tone(fs, 0.2, 151.2, 10.0, 0.5)     # 3rd harmonic = 1 % of the fundamental
    h = abs(dsp.window_phasors(x, fs, [150.0], "hann")[0][0])
    r = abs(dsp.window_phasors(x, fs, [150.0], "rectangular")[0][0])
    assert abs(h - 10.0) < 0.2 * abs(r - 10.0)            # nominal grid: Hann −4 % (scalloping), rectangular −28 %
    # with the estimated f1 (grid m·f1) the Hann window hits the harmonic within 0.1 %, the rectangular window
    # does not (leakage of the fundamental component, which is 100 times larger, ≈ 100 %)
    h_ok = abs(dsp.window_phasors(x, fs, [151.2], "hann")[0][0])
    r_ok = abs(dsp.window_phasors(x, fs, [151.2], "rectangular")[0][0])
    assert h_ok == pytest.approx(10.0, rel=2e-3)
    assert abs(r_ok - 10.0) > 1.0


def test_phasors_with_own_frequency_per_window():
    fs = 10000.0
    seg = np.stack([_tone(fs, 0.2, 49.9, 1.0), _tone(fs, 0.2, 50.1, 2.0)])
    X, _ = dsp.dft_phasors(seg, fs, np.array([[49.9], [50.1]]))
    assert abs(X[0, 0]) == pytest.approx(1.0, rel=1e-4) and abs(X[1, 0]) == pytest.approx(2.0, rel=1e-4)


def test_equivalent_source_sensitivity_for_nearly_equal_currents():
    """Additional impedances small compared with |Z_q| → nearly equal currents → the equivalent source from two
    measurements is ill-conditioned. The pairwise table states the sensitivity (ΔZ_q per 1 % current error)."""
    Zq, Uq = 30 - 30j, 300.0
    for Zk, limit_ in (([0.0, 2.5, 5.0], 0.5), ([0.0, 0.1, 0.2], 2.0)):
        Z = np.array(Zk)
        I = Uq / (Zq + Z)
        m = [equivalent_source.SourceMeasurement("m%d" % i, complex(z), "", "v2", 50.0, 0.0, {1: 30.0 + 0j, 5: complex(i_)},
                                    {1: {"zero": 1e4 + 0j}, 5: {}}) for i, (z, i_) in enumerate(zip(Z, I))]
        r = equivalent_source.fit_equivalent_source(m, normalization=None, orders=[5])
        pw = r.pairwise_table()
        if limit_ < 1:
            assert pw["dZq_rel_per_1pct"].max() < limit_        # well conditioned
        else:
            assert pw["dZq_rel_per_1pct"].max() > limit_        # 1 % current error → > 200 % error of Z_q
        assert r.fits[5].Zq == pytest.approx(Zq, rel=1e-6)            # exact data: still exact


def test_monte_carlo_reproducible():
    Zq, Uq = 4.5 - 2.5j, 220.0
    Z = np.array([0.0, 2.5, 5.0])
    m = [equivalent_source.SourceMeasurement("m%d" % i, complex(z), "", "v2", 50.0, 0.0, {1: 30.0 + 0j, 5: Uq / (Zq + z)},
                                {1: {"zero": 1e4 + 0j}, 5: {}}) for i, z in enumerate(Z)]
    r = equivalent_source.fit_equivalent_source(m, normalization=None, orders=[5])
    a = equivalent_source.monte_carlo(r, 2.5, n=200, seed=7)
    b = equivalent_source.monte_carlo(r, 2.5, n=200, seed=7)
    assert a["IRES"] == b["IRES"]
    ideal = math.hypot(30.0, abs(Uq / (Zq + 2.5)))
    assert a["IRES"][5] < ideal < a["IRES"][95]


def test_f1_robust_against_drift_and_harmonics():
    fs = 40000.0
    t = np.arange(int(3 * fs)) / fs
    x = (math.sqrt(2) * 20000 * np.cos(2 * np.pi * 49.97 * t) + math.sqrt(2) * 2000 * np.cos(2 * np.pi * 5 * 49.97 * t)
         + 3000 * t)                                     # linear drift (offset drift)
    e = dsp.estimate_f1(x, fs)
    assert e["f1"] == pytest.approx(49.97, abs=5e-4) and e["plausible"]
