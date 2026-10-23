# -*- coding: utf-8 -*-
"""Signal processing of the recordings: windows, DC removal (per window or a high-pass), RMS values, phasors, mains
frequency, decimation.

All phasors are **complex RMS phasors** in cosine convention::

    x(t) = √2·|X|·cos(2π f t + φ)   ⇔   X = |X|·e^{jφ}

with the phase referred to the **first sample of the window**.

Two independent ways lead to the same phasor (for mutual checking):

* [`dft_phasors`][groundfault.dsp.dft_phasors] – single-bin DFT, vectorised (standard way),
* [`goertzel`][groundfault.dsp.goertzel] – Goertzel recursion (reference; it refers the phase to the *end* of the
  window, [`goertzel_phasor`][groundfault.dsp.goertzel_phasor] converts it to the first sample).

Mains-frequency estimation (methods that can be checked against each other):

* [`f1_phase_method`][groundfault.dsp.f1_phase_method] – phase progression of a phasor at the nominal frequency over
  successive windows (standard),
* [`f1_spectral`][groundfault.dsp.f1_spectral] – spectral maximum with interpolation and prominence check,
* [`f1_zero_crossing`][groundfault.dsp.f1_zero_crossing] – interpolated zero crossings after a band-pass filter,
* [`f1_regression`][groundfault.dsp.f1_regression] – mean frequency of a section from the phase trend of one or more
  harmonics (linear regression with standard error).

[`estimate_f1`][groundfault.dsp.estimate_f1] combines the phase method with the spectral method as a plausibility check.
"""
from __future__ import annotations

import math
import warnings
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

from . import i18n
from .i18n import tr
from .legacy import check_option

try:  # optional
    from scipy import signal as _sps
except Exception:  # pragma: no cover
    _sps = None
HAS_SCIPY = _sps is not None
"""True if SciPy can be imported (a core dependency): [`decimate`][groundfault.dsp.decimate] then uses a polyphase FIR
filter, the Goertzel algorithm and the zero-crossing frequency estimate use SciPy filters; without it simpler fallbacks
are used."""

__all__ = [
    "hann", "window_function", "coherent_gain", "remove_dc", "highpass", "true_rms",
    "window_grid", "window_view", "dft_phasors", "window_phasors", "goertzel",
    "goertzel_phasor", "f1_phase_method", "f1_regression", "f1_spectral", "f1_zero_crossing", "estimate_f1",
    "decimate", "thd", "HAS_SCIPY", "WINDOWS", "DC_METHODS", "DC_FILTERS", "F1_METHODS",
]

WINDOWS = ("hann", "hann_periodic", "rectangular")
"""Window functions of the DFT (``window_function``); also accepted: ``"hanning"``, ``"hann_p"``, ``"rect"``,
``"none"`` (rectangular)."""
_WINDOW_ALIASES = ("hanning", "hann_p", "rect", "none")
DC_METHODS = ("median", "mean", "none")
"""Methods of the DC removal per window (``remove_dc``); None counts as ``"none"``."""
DC_FILTERS = DC_METHODS + ("highpass",)
"""DC removal of an evaluation (``Settings.dc``): a method per window, or ``"highpass"`` – the zero-phase high-pass
[`highpass`][groundfault.dsp.highpass] on every interval before the windows, then the median per window."""
HIGHPASS_ORDER = 4
"""Order of the Butterworth high-pass of [`highpass`][groundfault.dsp.highpass] (applied forwards and backwards)."""
F1_METHODS = ("phase", "spectral")
"""Methods of the mains-frequency estimation (``estimate_f1``)."""

i18n.register({
    "dsp.highpass_cutoff": {
        "en": "Cut-off frequency of the high-pass must lie between 0 and half the sampling rate ({fs} Hz): {value}",
        "de": "Grenzfrequenz des Hochpasses muss zwischen 0 und der halben Abtastrate ({fs} Hz) liegen: {value}"},
    "dsp.highpass_scipy": {
        "en": "The high-pass needs SciPy (pip install scipy).",
        "de": "Der Hochpass braucht SciPy (pip install scipy)."},
    "dsp.window_too_short": {
        "en": "Window too short (N_win={nwin})",
        "de": "Fenster zu kurz (N_win={nwin})"},
    "dsp.f1_not_possible": {
        "en": "estimation not possible → nominal frequency",
        "de": "Schätzung nicht möglich → Nennfrequenz"},
    "dsp.f1_weak_peak": {
        "en": "weak 50-Hz peak (prominence {prominence:.1f})",
        "de": "schwacher 50-Hz-Peak (Prominenz {prominence:.1f})"},
    "dsp.f1_methods_differ": {
        "en": "methods differ by {deviation:.3f} Hz",
        "de": "Verfahren weichen um {deviation:.3f} Hz ab"},
    "dsp.f1_outside_tolerance": {
        "en": "outside the tolerance",
        "de": "außerhalb Toleranz"},
    "dsp.f1_implausible": {
        "en": "f1 estimate implausible ({f1:.4f} Hz): {note}",
        "de": "f1-Schätzung unplausibel ({f1:.4f} Hz): {note}"},
    "dsp.decimation_without_scipy": {
        "en": "scipy missing – decimation by block averaging (amplitude errors possible for higher harmonics).",
        "de": "scipy fehlt – Dezimierung per Blockmittelung (Amplitudenfehler bei höheren Harmonischen möglich)."},
})


# ---------------------------------------------------------------- windows and pre-processing
def hann(N: int, symmetric: bool = True) -> np.ndarray:
    """Hann window of length ``N``.

    Parameters
    ----------
    N : int
        Number of samples.
    symmetric : bool, optional
        True: w[n] = 0.5·(1 − cos(2πn/(N−1))), the window used for the phasors; False: periodic variant with N in
        the denominator.

    Returns
    -------
    numpy.ndarray
        Window values.
    """
    if N <= 0:
        return np.zeros(0)
    if N == 1:
        return np.ones(1)
    n = np.arange(N)
    denominator = (N - 1) if symmetric else N
    return 0.5 * (1.0 - np.cos(2.0 * np.pi * n / denominator))


def window_function(N: int, kind: str = "hann") -> np.ndarray:
    """Window of length ``N``: ``"hann"`` (symmetric), ``"hann_periodic"`` or ``"rectangular"``.

    Raises
    ------
    ValueError
        For an unknown window name, also for a former name of the predecessor tool (``"rechteck"`` …).
    """
    kind = check_option("window", (kind or "hann").lower(), WINDOWS, aliases=_WINDOW_ALIASES)
    if kind in ("hann", "hanning"):
        return hann(N, True)
    if kind in ("hann_periodic", "hann_p"):
        return hann(N, False)
    return np.ones(N)                                   # rectangular


def coherent_gain(w: np.ndarray) -> float:
    """Coherent gain of a window, g = (1/N)·Σ w[n] (Hann ≈ 0.5, rectangular = 1)."""
    return float(np.mean(w))


def remove_dc(x: np.ndarray, method: str = "median", axis: int = -1) -> np.ndarray:
    """Remove the DC component: x0 = x − DC(x).

    Parameters
    ----------
    x : array_like
        Signal (one window, or several windows along ``axis``).
    method : {"median", "mean", "none"}, optional
        Estimate of the DC component. The median (recommended) is robust against spikes and transients.
    axis : int, optional
        Axis along which the DC component is estimated.

    Returns
    -------
    numpy.ndarray
        Signal without DC component.

    Raises
    ------
    ValueError
        For an unknown method, also for a former name of the predecessor tool (``"mittel"`` …).
    """
    check_option("dc", method, DC_METHODS, aliases=(None,))
    x = np.asarray(x, dtype=np.float64)
    if method == "median":
        return x - np.median(x, axis=axis, keepdims=True)
    if method == "mean":
        return x - np.mean(x, axis=axis, keepdims=True)
    return x


def highpass(x: np.ndarray, fs: float, cutoff_hz: float = 5.0, order: int = HIGHPASS_ORDER,
             axis: int = 0) -> np.ndarray:
    """Remove the DC component and slow drifts with a zero-phase Butterworth high-pass.

    The filter runs forwards and backwards (``scipy.signal.sosfiltfilt``): no phase shift, the magnitude response is
    the square of the Butterworth response – at 50 Hz with the default 5 Hz and order 4 below 10⁻⁸. The signal is
    extended at both ends by its mirror image (up to 3/``cutoff_hz`` long): a constant or slowly decaying offset gives
    no step at the ends, and no sample outside the signal (e.g. a fault inception just after an interval) acts on it;
    the first and last 0.2 s of the signal keep a small error of the RMS value (about 0.1 %, the harmonics stay
    unchanged). NaN values are bridged by linear interpolation for the filter and stay NaN.

    Parameters
    ----------
    x : array_like
        Signal (several channels along the other axes).
    fs : float
        Sampling rate in Hz.
    cutoff_hz : float, optional
        Cut-off frequency (−3 dB of one pass) in Hz.
    order : int, optional
        Order of the Butterworth filter of one pass.
    axis : int, optional
        Time axis.

    Returns
    -------
    numpy.ndarray
        The filtered signal (same shape).

    Raises
    ------
    ValueError
        For a cut-off frequency outside 0 < f < fs/2.
    ImportError
        Without SciPy.

    Examples
    --------
    >>> import numpy as np
    >>> fs = 10000.0
    >>> t = np.arange(0, 2.0, 1 / fs)
    >>> x = 10 * np.sqrt(2) * np.sin(2 * np.pi * 50 * t) + 30 * np.exp(-t / 0.8)     # 10 A at 50 Hz + decaying DC
    >>> y = highpass(x, fs)
    >>> bool(abs(np.median(y[5000:15000])) < 0.05), round(float(np.sqrt(np.mean(y[5000:15000] ** 2))), 3)
    (True, 10.0)
    """
    fc = float(cutoff_hz)
    if not (math.isfinite(fc) and 0.0 < fc < 0.5 * float(fs)):
        raise ValueError(tr("dsp.highpass_cutoff", fs=0.5 * float(fs), value=cutoff_hz))
    if _sps is None:  # pragma: no cover
        raise ImportError(tr("dsp.highpass_scipy"))
    a = np.asarray(x, dtype=np.float64)
    if a.shape[axis] < 2:
        return a.copy()
    sos = _sps.butter(int(order), fc, btype="highpass", fs=float(fs), output="sos")
    m = np.moveaxis(a, axis, 0).copy()
    flat = m.reshape(m.shape[0], -1)
    nan = ~np.isfinite(flat)
    n = flat.shape[0]
    idx = np.arange(n)
    for j in np.nonzero(nan.any(axis=0))[0]:            # bridge NaN for the filter (linear), restored below
        ok = ~nan[:, j]
        flat[:, j] = np.interp(idx, idx[ok], flat[ok, j]) if ok.any() else 0.0
    padlen = int(min(n - 1, round(3.0 * float(fs) / fc)))
    out = _sps.sosfiltfilt(sos, flat, axis=0, padtype="even", padlen=padlen)
    out[nan] = np.nan
    return np.moveaxis(out.reshape(m.shape), 0, axis)


def true_rms(x0: np.ndarray, axis: int = -1) -> np.ndarray:
    """True RMS value x_RMS = sqrt((1/N)·Σ x0[n]²) of a signal without DC component."""
    return np.sqrt(np.mean(np.square(x0), axis=axis))


# ---------------------------------------------------------------- segmentation
def window_grid(n: int, fs: float, T_win: float, T_hop: Optional[float] = None
                  ) -> Tuple[int, int, np.ndarray]:
    """Window grid of a signal with ``n`` samples: N_win = T_win·f_s samples per window.

    Parameters
    ----------
    n : int
        Number of samples of the signal.
    fs : float
        Sampling rate in Hz.
    T_win : float
        Window length in s.
    T_hop : float, optional
        Step between window starts in s (default ``T_win``, i.e. no overlap).

    Returns
    -------
    nwin, nhop : int
        Window length and step in samples.
    starts : numpy.ndarray
        Start indices of all complete windows.

    Raises
    ------
    ValueError
        If a window would have fewer than two samples.
    """
    nwin = int(round(T_win * fs))
    nhop = max(1, int(round((T_hop if T_hop else T_win) * fs)))
    if nwin < 2:
        raise ValueError(tr("dsp.window_too_short", nwin=nwin))
    if n < nwin:
        return nwin, nhop, np.zeros(0, dtype=int)
    return nwin, nhop, np.arange(0, n - nwin + 1, nhop)


def window_view(x: np.ndarray, nwin: int, nhop: int) -> np.ndarray:
    """Windows of ``x`` as an (n_windows, N_win) view without copying."""
    x = np.asarray(x, dtype=np.float64)
    if len(x) < nwin:
        return np.zeros((0, nwin))
    return np.lib.stride_tricks.sliding_window_view(x, nwin)[::nhop]


# ---------------------------------------------------------------- phasors
def dft_phasors(segments: np.ndarray, fs: float, frequencies, window: str = "hann",
                 dc: str = "median", block: int = 256) -> Tuple[np.ndarray, np.ndarray]:
    """Complex RMS phasors per window and frequency (single-bin DFT).

    Per window, the DC component is removed (x0), the window w applied and the phasor computed as

        X(f) = √2/(N·g) · Σ x0[n]·w[n]·e^{−j2πf·n/f_s}

    with the coherent gain g of the window; the true RMS value of x0 is returned as well. With the frequencies
    m·f1 (estimated mains frequency) the harmonics are hit exactly even if f1 deviates from the nominal value.

    Parameters
    ----------
    segments : numpy.ndarray
        Windows, shape (n_windows, N) (a single window may be given as a 1-D array).
    fs : float
        Sampling rate in Hz.
    frequencies : array_like
        Frequencies in Hz, shape (n_f,) common to all windows or (n_windows, n_f) per window.
    window : str, optional
        Window function (see [`window_function`][groundfault.dsp.window_function]).
    dc : str, optional
        DC removal (see [`remove_dc`][groundfault.dsp.remove_dc]).
    block : int, optional
        Number of windows processed at once.

    Returns
    -------
    X : numpy.ndarray
        Complex RMS phasors, shape (n_windows, n_f); phase referred to the first sample of the window.
    rms : numpy.ndarray
        True RMS value per window, shape (n_windows,).

    Notes
    -----
    Windows that contain NaN give NaN.
    """
    seg = np.asarray(segments, dtype=np.float64)
    if seg.ndim == 1:
        seg = seg[None, :]
    n_w, N = seg.shape
    f = np.asarray(frequencies, dtype=np.float64)
    per_window = f.ndim == 2
    n_f = f.shape[-1]
    w = window_function(N, window)
    g = coherent_gain(w)
    scal = math.sqrt(2.0) / (N * g)
    n = np.arange(N)
    X = np.empty((n_w, n_f), dtype=np.complex128)
    rms = np.empty(n_w)
    if not per_window:
        E = np.exp(-2j * np.pi * np.outer(n, f) / fs)            # (N, n_f)
    for a in range(0, n_w, block):
        b = min(n_w, a + block)
        x0 = remove_dc(seg[a:b], dc, axis=1)
        rms[a:b] = true_rms(x0, axis=1)
        xw = x0 * w
        if per_window:
            for k in range(a, b):
                Ek = np.exp(-2j * np.pi * np.outer(n, f[k]) / fs)
                X[k] = scal * (xw[k - a] @ Ek)
        else:
            X[a:b] = scal * (xw @ E)
    return X, rms


def window_phasors(x: np.ndarray, fs: float, frequencies, window: str = "hann",
                     dc: str = "median") -> Tuple[np.ndarray, float]:
    """Phasors of a single window (see [`dft_phasors`][groundfault.dsp.dft_phasors]).

    Returns
    -------
    X : numpy.ndarray
        Complex RMS phasors, shape (n_f,).
    rms : float
        True RMS value of the window.
    """
    X, rms = dft_phasors(np.asarray(x)[None, :], fs, np.atleast_1d(frequencies), window, dc)
    return X[0], float(rms[0])


def goertzel(x: np.ndarray, f: float, fs: float) -> complex:
    """Goertzel recursion (without scaling) – reference for [`dft_phasors`][groundfault.dsp.dft_phasors].

    s[n] = x[n] + 2cos(ω)·s[n−1] − s[n−2],  X = e^{jω}·s[N−1] − s[N−2] with ω = 2πf/f_s.

    The result equals e^{jωN}·Σ x[n]·e^{−jωn}, i.e. the phase is referred to the time n = N (end of the window).

    Notes
    -----
    For small ω (50 Hz at 40 kHz: ω ≈ 0.008) the state grows like N/(2 sin ω); in float64 the cancellation error
    stays below 1e-9 (relative), see the tests.
    """
    x = np.asarray(x, dtype=np.float64)
    w0 = 2.0 * np.pi * f / fs
    c = 2.0 * math.cos(w0)
    if len(x) < 2:
        return complex(x[0] if len(x) else 0.0)
    if HAS_SCIPY:
        s = _sps.lfilter([1.0], [1.0, -c, 1.0], x)
        s1, s2 = s[-1], s[-2]
    else:  # plain Python loop (slow, but exactly the recursion above)
        s1 = s2 = 0.0
        for v in x:
            s0 = v + c * s1 - s2
            s2, s1 = s1, s0
    return complex(np.exp(1j * w0) * s1 - s2)


def goertzel_phasor(x: np.ndarray, f: float, fs: float, window: str = "hann",
                    dc: str = "median") -> complex:
    """Complex RMS phasor of one window computed with [`goertzel`][groundfault.dsp.goertzel] (DC removal, window and
    scaling as in [`dft_phasors`][groundfault.dsp.dft_phasors]), phase referred to the first sample."""
    x0 = remove_dc(np.asarray(x, dtype=np.float64), dc)
    w = window_function(len(x0), window)
    g = coherent_gain(w)
    N = len(x0)
    Xs = goertzel(x0 * w, f, fs)
    w0 = 2.0 * np.pi * f / fs
    return complex(math.sqrt(2.0) / (N * g) * Xs * np.exp(-1j * w0 * N))


def thd(magnitudes: Sequence[float], orders: Sequence[int]) -> float:
    """Total harmonic distortion THD = sqrt(Σ_{h≥2} U_h²) / U_1 (relative, p.u.).

    Parameters
    ----------
    magnitudes : sequence of float
        Magnitudes U_h.
    orders : sequence of int
        Harmonic orders h belonging to ``magnitudes`` (must contain 1).

    Returns
    -------
    float
        THD in p.u.; NaN without a usable fundamental component.
    """
    o = np.asarray(orders); u = np.asarray(magnitudes, dtype=float)
    if 1 not in o:
        return float("nan")
    u1 = u[o == 1][0]
    if not np.isfinite(u1) or u1 <= 0:
        return float("nan")
    return float(np.sqrt(np.nansum(u[o >= 2] ** 2)) / u1)


# ---------------------------------------------------------------- mains frequency
def _middle_part(x: np.ndarray, fs: float, duration_s: Optional[float]) -> np.ndarray:
    """Finite samples of ``x``, limited to ``duration_s`` around the middle (None: all)."""
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    if duration_s is None:
        return x
    n = min(len(x), int(duration_s * fs))
    a = max(0, len(x) // 2 - n // 2)
    return x[a:a + n]


def f1_phase_method(x: np.ndarray, fs: float, f_nominal: float = 50.0, T: float = 0.2,
                     duration_s: Optional[float] = None) -> Tuple[float, float]:
    """Mains frequency f1 from the phase progression of a phasor at the nominal frequency over successive windows.

    For a signal of frequency f1, the phase advances between windows ΔT apart by Δφ = 2π·f1·ΔT (mod 2π), hence
    f1 = f_nominal + wrap(Δφ − 2π·f_nominal·ΔT)/(2π·ΔT). This is unambiguous for |f1 − f_nominal| < 1/(2ΔT)
    (2.5 Hz for 200-ms windows).

    Parameters
    ----------
    x : numpy.ndarray
        Signal (NaN values are dropped).
    fs : float
        Sampling rate in Hz.
    f_nominal : float, optional
        Nominal frequency in Hz.
    T : float, optional
        Window length and window distance ΔT in s.
    duration_s : float, optional
        Use only this duration around the middle of the signal.

    Returns
    -------
    f1 : float
        Median of the frequencies between successive windows, in Hz (NaN for fewer than two windows).
    spread : float
        Standard deviation of these frequencies in Hz.
    """
    seg_x = _middle_part(x, fs, duration_s)
    nwin, nhop, starts = window_grid(len(seg_x), fs, T, T)
    if len(starts) < 2:
        return float("nan"), float("nan")
    X, _ = dft_phasors(window_view(seg_x, nwin, nhop), fs, [f_nominal], "hann", "median")
    p = X[:, 0]
    ok = np.isfinite(p) & (np.abs(p) > 0)
    p = p[ok]
    if len(p) < 2:
        return float("nan"), float("nan")
    dT = nhop / fs
    dphi = np.angle(p[1:] * np.conj(p[:-1])) - 2 * np.pi * f_nominal * dT
    dphi = (dphi + np.pi) % (2 * np.pi) - np.pi
    f_k = f_nominal + dphi / (2 * np.pi * dT)
    return float(np.median(f_k)), float(np.std(f_k))


def f1_regression(x: np.ndarray, fs: float, f_nominal: float = 50.0, orders=(1,), T: float = 0.1
                  ) -> Tuple[np.ndarray, np.ndarray]:
    """Mean mains frequency f1 of a section from the phase trend of the harmonic m (linear regression).

    In each window (length T, no overlap) the phasor at m·f_nominal is computed; its phase minus the nominal
    progression 2π·m·f_nominal·t rises with 2π·m·(f1 − f_nominal). The regression line over all windows gives f1
    (the mean over the section; for a linear drift the value in the middle), its standard error (from the
    residuals) the uncertainty σ. At the same signal-to-noise ratio the m-th harmonic measures f1 m times more
    accurately – at earthing probes the background level at 150 Hz is often larger than at 50 Hz. Windows with
    NaN are skipped.

    Parameters
    ----------
    x : numpy.ndarray
        Signal.
    fs : float
        Sampling rate in Hz.
    f_nominal : float, optional
        Nominal frequency in Hz.
    orders : int or sequence of int, optional
        Harmonic orders m to evaluate.
    T : float, optional
        Window length in s.

    Returns
    -------
    f1, sigma : numpy.ndarray
        Frequency and its standard uncertainty in Hz, one value per order; NaN with fewer than four valid
        windows.
    """
    ords = np.atleast_1d(np.asarray(orders, dtype=float))
    f1 = np.full(len(ords), np.nan); sigma = np.full(len(ords), np.nan)
    nwin, nhop, starts = window_grid(len(x), fs, T, T)
    if len(starts) < 4:
        return f1, sigma
    X, _ = dft_phasors(window_view(x, nwin, nhop), fs, ords * f_nominal, "hann", "median")
    t = starts / fs
    for j, m in enumerate(ords):
        p = X[:, j]
        ok = np.isfinite(p) & (np.abs(p) > 0)
        if ok.sum() < 4:
            continue
        tt = t[ok] - t[ok].mean()
        psi = np.unwrap(np.angle(p[ok] * np.exp(-2j * np.pi * m * f_nominal * t[ok])))
        b = float(tt @ (psi - psi.mean()) / (tt @ tt))
        res = psi - psi.mean() - b * tt
        s = math.sqrt(float(res @ res) / (len(tt) - 2) / float(tt @ tt))
        f1[j] = f_nominal + b / (2 * np.pi * m)
        sigma[j] = s / (2 * np.pi * m)
    return f1, sigma


def f1_spectral(x: np.ndarray, fs: float, f_nominal: float = 50.0, band: float = 3.0,
                duration_s: Optional[float] = 2.0, min_prominence: float = 4.0,
                zero_pad: int = 4, interpolation: bool = True) -> Tuple[float, float]:
    """Mains frequency f1 from the spectral maximum in the band f_nominal ± ``band``.

    The section is linearly detrended, Hann-windowed and zero-padded; the peak is refined by a parabolic
    interpolation of the logarithmic magnitude.

    Parameters
    ----------
    x : numpy.ndarray
        Signal (NaN values are dropped).
    fs : float
        Sampling rate in Hz.
    f_nominal : float, optional
        Nominal frequency in Hz.
    band : float, optional
        Half width of the search band in Hz.
    duration_s : float, optional
        Use only this duration around the middle of the signal (None: all).
    min_prominence : float, optional
        Minimum prominence (peak / median in the band); below it the nominal frequency is returned.
    zero_pad : int, optional
        Zero-padding factor of the FFT.
    interpolation : bool, optional
        Parabolic interpolation of the peak.

    Returns
    -------
    f1 : float
        Frequency in Hz (``f_nominal`` for a too short signal or a too weak peak).
    prominence : float
        Peak divided by the median magnitude in the band.
    """
    seg = _middle_part(x, fs, duration_s)
    if len(seg) < 16:
        return f_nominal, 0.0
    tt = np.arange(len(seg))
    c = np.polyfit(tt, seg, 1)
    seg = seg - (c[0] * tt + c[1])
    nfft = 1 << int(np.ceil(np.log2(max(len(seg) * zero_pad, 16))))
    X = np.abs(np.fft.rfft(seg * hann(len(seg)), nfft))
    fr = np.fft.rfftfreq(nfft, 1.0 / fs)
    m = np.where((fr > f_nominal - band) & (fr < f_nominal + band))[0]
    if len(m) < 3:
        return f_nominal, 0.0
    k = int(m[np.argmax(X[m])])
    prom = float(X[k] / (np.median(X[m]) + 1e-300))
    if prom < min_prominence:
        return f_nominal, prom
    f1 = fr[k]
    if interpolation and 0 < k < len(X) - 1 and X[k - 1] > 0 and X[k + 1] > 0:
        a, b, cc = np.log(X[k - 1]), np.log(X[k]), np.log(X[k + 1])
        denominator = a - 2 * b + cc
        if denominator != 0:
            f1 = fr[k] + 0.5 * (a - cc) / denominator * (fs / nfft)
    return float(f1), prom


def f1_zero_crossing(x: np.ndarray, fs: float, f_nominal: float = 50.0,
                     duration_s: Optional[float] = None) -> float:
    """Mains frequency f1 from interpolated rising zero crossings after a band-pass filter (f_nominal·[0.5…1.5]).

    The crossing times t_k are fitted by a linear regression t_k = t_0 + k·T (more robust than using the first and
    the last crossing); 0.2 s at each edge are dropped (settling of the filter). Without scipy a moving average over
    half a period replaces the band-pass filter.

    Returns
    -------
    float
        Frequency in Hz; NaN for a too short signal or fewer than three crossings.
    """
    seg = _middle_part(x, fs, duration_s)
    if len(seg) < int(6 * fs / f_nominal):
        return float("nan")
    seg = seg - np.median(seg)
    if HAS_SCIPY:
        sos = _sps.butter(2, [0.5 * f_nominal, 1.5 * f_nominal], btype="bandpass", fs=fs, output="sos")
        y = _sps.sosfiltfilt(sos, seg)
    else:  # moving average over half a period attenuates the harmonics
        k = max(1, int(fs / f_nominal / 2))
        y = np.convolve(seg, np.ones(k) / k, mode="same")
    edge = int(0.2 * fs)
    if len(y) > 4 * edge + int(4 * fs / f_nominal):
        y = y[edge:-edge]
    i = np.where((y[:-1] < 0) & (y[1:] >= 0))[0]
    if len(i) < 3:
        return float("nan")
    t = (i + (-y[i]) / (y[i + 1] - y[i])) / fs  # linear interpolation
    k = np.arange(len(t))
    T = np.polyfit(k, t, 1)[0]
    return float(1.0 / T) if T > 0 else float("nan")


def estimate_f1(x: np.ndarray, fs: float, f_nominal: float = 50.0, method: str = "phase",
                duration_s: Optional[float] = None, tolerance_hz: float = 0.5,
                comparison_tolerance_hz: float = 0.05) -> Dict[str, object]:
    """Mains frequency with a plausibility check by a second method.

    The phase method ([`f1_phase_method`][groundfault.dsp.f1_phase_method]) and the spectral method
    ([`f1_spectral`][groundfault.dsp.f1_spectral]) are both evaluated; ``method`` selects the result, the other one
    serves as the comparison. An implausible result issues a ``UserWarning``.

    Parameters
    ----------
    x : numpy.ndarray
        Signal, usually a line-to-line voltage.
    fs : float
        Sampling rate in Hz.
    f_nominal : float, optional
        Nominal frequency in Hz.
    method : {"phase", "spectral"}, optional
        Method whose result is used.
    duration_s : float, optional
        Use only this duration around the middle of the signal (spectral method: 2 s if None).
    tolerance_hz : float, optional
        Permissible deviation from the nominal frequency.
    comparison_tolerance_hz : float, optional
        Permissible difference between the two methods.

    Returns
    -------
    dict
        ``f1``, ``method``, ``f1_comparison``, ``method_comparison``, ``deviation_hz`` (difference of the
        methods), ``spread_hz`` (spread of the phase method), ``prominence`` (of the spectral peak),
        ``plausible`` (|f1 − f_nominal| ≤ tolerance, methods consistent and prominence ≥ 4) and ``note`` (reasons
        in the active language, ``""`` if there are none).

    Raises
    ------
    ValueError
        For an unknown ``method``, also for the former name ``"spektral"``.
    """
    check_option("method", method, F1_METHODS)
    x = np.asarray(x, dtype=np.float64)
    f_ph, s_ph = f1_phase_method(x, fs, f_nominal, duration_s=duration_s)
    f_sp, prom = f1_spectral(x, fs, f_nominal, duration_s=2.0 if duration_s is None else duration_s)
    if method == "spectral":
        f1, old, m_old = f_sp, f_ph, "phase"
    else:
        f1, old, m_old = f_ph, f_sp, "spectral"
    note = ""
    if not np.isfinite(f1):
        f1, note = f_nominal, tr("dsp.f1_not_possible")
    dev = abs(f1 - old) if np.isfinite(old) else float("nan")
    plausible = abs(f1 - f_nominal) <= tolerance_hz and (not np.isfinite(dev) or dev <= comparison_tolerance_hz)
    if prom < 4.0:
        plausible = False
        note = (note + "; " if note else "") + tr("dsp.f1_weak_peak", prominence=prom)
    if np.isfinite(dev) and dev > comparison_tolerance_hz:
        note = (note + "; " if note else "") + tr("dsp.f1_methods_differ", deviation=dev)
    if not plausible:
        warnings.warn(tr("dsp.f1_implausible", f1=f1, note=note or tr("dsp.f1_outside_tolerance")))
    return dict(f1=float(f1), method=method, f1_comparison=float(old), method_comparison=m_old,
                deviation_hz=float(dev), spread_hz=float(s_ph), prominence=float(prom),
                plausible=bool(plausible), note=note)


# ---------------------------------------------------------------- decimation
def decimate(A: np.ndarray, fs: float, factor: int) -> Tuple[np.ndarray, float]:
    """Reduce the sampling rate by an integer ``factor`` with an anti-aliasing low-pass filter.

    With scipy: polyphase FIR filter (``resample_poly``, Kaiser window β = 10) – linear phase, delay
    compensated, pass-band ripple < 1e-4 (important: the IIR filter of ``scipy.signal.decimate`` has up to 1 %
    ripple and falsifies the amplitudes). Without scipy: block averaging (boxcar) with a warning.

    Parameters
    ----------
    A : numpy.ndarray
        Signal (1-D) or signals in columns (2-D).
    fs : float
        Sampling rate in Hz.
    factor : int
        Decimation factor (≤ 1: no decimation).

    Returns
    -------
    A_decimated : numpy.ndarray
        Decimated signal(s).
    fs_new : float
        New sampling rate ``fs / factor`` in Hz.
    """
    factor = int(factor)
    if factor <= 1:
        return A, fs
    A = np.asarray(A, dtype=np.float64)
    one_dim = A.ndim == 1
    if one_dim:
        A = A[:, None]
    if HAS_SCIPY:
        out = _sps.resample_poly(A, 1, factor, axis=0, window=("kaiser", 10.0))
    else:
        warnings.warn(tr("dsp.decimation_without_scipy"))
        n = (A.shape[0] // factor) * factor
        out = A[:n].reshape(-1, factor, A.shape[1]).mean(axis=1)
    return (out[:, 0] if one_dim else out), fs / factor
