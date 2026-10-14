# -*- coding: utf-8 -*-
"""RMS recordings (DANEO "… RMS" export, 10 Hz), comparison with the instantaneous values and resonance curve.

* [`evaluate_rms_recording`][groundfault.rms.evaluate_rms_recording] – characteristic values per interval directly from
  an RMS recording (time trend, maximum in the steady-state interval, pre-fault and post-fault).
* [`compare_with_instantaneous`][groundfault.rms.compare_with_instantaneous] – check: own true RMS value computed from
  the instantaneous-value recording against the RMS values computed by the recorder.
* [`v_curve`][groundfault.rms.v_curve] – resonance curve (V curve): minimum of the residual earth-fault current while
  the coil is tuned. Two ways: the direct minimum of the measured values and a fitted parabola
  I_RES² = a·(I_L − I_Res)² + c over the coil current (or the time), with I_Res the coil current at resonance.
* [`fundamental_trend`][groundfault.rms.fundamental_trend] – |I_H1|(t), Iw(t), Iv(t) from instantaneous values (the
  minimum of the fundamental is the active residual current at the resonance point).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from . import dsp
from . import i18n
from .i18n import tr
from .comtrade import Recording
from .channels import RoleAssignment, detect_roles

__all__ = ["evaluate_rms_recording", "compare_with_instantaneous", "VCurve", "v_curve", "fundamental_trend"]

i18n.register({
    "rms.no_common_channels": {
        "en": "No common channels (names without Inst/RMS) found.",
        "de": "Keine gemeinsamen Kanäle (Namen ohne Inst/RMS) gefunden."},
    "rms.device_includes_dc": {
        "en": "The device includes the DC component (RMS incl. DC deviates by only {deviation:.1f} %)",
        "de": "Gerät rechnet den DC-Anteil mit (RMS inkl. DC weicht nur {deviation:.1f} % ab)"},
    "rms.scaling": {
        "en": "Scaling of the RMS file? Factor ≈ {factor:g}",
        "de": "Skalierung der RMS-Datei? Faktor ≈ {factor:g}"},
    "rms.deviation_unexplained": {
        "en": "Deviation unexplained – check the channel assignment, the transformer ratio or the time grid",
        "de": "Abweichung ungeklärt – Kanalzuordnung, Wandlerfaktor oder Zeitraster prüfen"},
    "rms.too_few_points": {
        "en": "Too few points for the resonance curve (V curve).",
        "de": "Zu wenige Punkte für die V-Kurve."},
    "rms.vertex_outside": {
        "en": "Vertex outside the measured points – resonance not passed through?",
        "de": "Scheitel außerhalb der Messpunkte – Resonanz nicht überstrichen?"},
    "rms.no_v_shape": {
        "en": "no V shape recognisable (curvature ≤ 0)",
        "de": "keine V-Form erkennbar (Krümmung ≤ 0)"},
    "rms.no_fault_current_channel": {
        "en": "No earth-fault current channel (i_res).",
        "de": "Kein Erdschlussstrom-Kanal (i_res)."},
})


def _interval_mask(t: np.ndarray, b: Optional[Tuple[float, float]]) -> np.ndarray:
    """Boolean mask of the samples in the interval ``b`` (all False if ``b`` is None)."""
    if b is None:
        return np.zeros(t.size, bool)
    return (t >= b[0]) & (t <= b[1])


def evaluate_rms_recording(rec: Recording, steady_state: Optional[Tuple[float, float]] = None,
                           pre_fault: Optional[Tuple[float, float]] = None,
                           post_fault: Optional[Tuple[float, float]] = None,
                           roles: Optional[RoleAssignment] = None) -> Dict[str, object]:
    """Characteristic values of an RMS recording per interval (mean, minimum, maximum, 95 % quantile).

    At 10 Hz, the maximum in the steady-state interval corresponds to a 100-ms value of the recorder – it is
    comparable with the 200-ms maximum of the own evaluation, but not identical.

    Parameters
    ----------
    rec : Recording
        RMS recording (e.g. the DANEO "RMS" export).
    steady_state, pre_fault, post_fault : tuple of float, optional
        Intervals (t0, t1) in s; intervals that are not given are skipped.
    roles : RoleAssignment, optional
        Channel roles (detected from the channel names if omitted).

    Returns
    -------
    dict
        ``t`` (time in s), ``values`` (all samples, shape ``(n, channels)``), ``roles`` and ``table`` – one row
        per channel and interval with the columns ``channel``, ``role``, ``unit``, ``interval``
        (``steady_state``, ``pre_fault``, ``post_fault``), ``n``, ``mean``, ``min``, ``max``, ``P95`` and
        ``t_Max_s``.
    """
    roles = roles or detect_roles(rec.channel_names, rec.units)
    t = np.arange(rec.n) / rec.fs
    x = rec.read(0, rec.n)
    rows = []
    for k in roles.channels:
        for name, b in (("steady_state", steady_state), ("pre_fault", pre_fault), ("post_fault", post_fault)):
            m = _interval_mask(t, b)
            if not m.any():
                continue
            v = x[m, k.index]; v = v[np.isfinite(v)]
            if v.size == 0:
                continue
            rows.append(dict(channel=k.short, role=k.role, unit=k.unit, interval=name, n=int(v.size),
                             mean=float(v.mean()), min=float(v.min()), max=float(v.max()),
                             P95=float(np.percentile(v, 95)), t_Max_s=float(t[m][np.nanargmax(x[m, k.index])])))
    return dict(t=t, values=x, roles=roles, table=pd.DataFrame(rows))


def compare_with_instantaneous(rec_inst: Recording, rec_rms: Recording,
                               interval: Optional[Tuple[float, float]] = None,
                               window_s: Optional[float] = None, dc: str = "median") -> pd.DataFrame:
    """Compare the own true RMS value with the RMS values computed by the recorder, per common channel.

    The channels are matched by their short name (without the device suffix "Inst"/"RMS"). On the time grid of the
    RMS file, the own true RMS value is computed from the window of length ``window_s`` that ends at each RMS
    sample. A larger deviation (median ≥ 2 %) is explained in the column ``note`` where possible: the recorder
    includes the DC component, the RMS file is scaled by a power of ten, or the deviation is unexplained.

    Parameters
    ----------
    rec_inst : Recording
        Instantaneous-value recording.
    rec_rms : Recording
        RMS recording of the same test.
    interval : tuple of float, optional
        Compared interval (t0, t1) in s (default: the common length of both recordings).
    window_s : float, optional
        Window length of the own RMS value in s (default: one sampling period of the RMS file, 1/f_RMS).
    dc : str, optional
        Method of the DC removal ([`groundfault.dsp.remove_dc`][groundfault.dsp.remove_dc]).

    Returns
    -------
    pandas.DataFrame
        One row per common channel: ``channel``, ``n``, ``mean_own``, ``mean_device``, ``deviation_median_pct``,
        ``deviation_P95_pct``, ``deviation_incl_dc_pct`` (own RMS value including the DC component) and ``note``.

    Raises
    ------
    ValueError
        If the two recordings have no channel in common.
    """
    from .channels import short_name
    window_s = window_s or 1.0 / rec_rms.fs
    t_r = np.arange(rec_rms.n) / rec_rms.fs
    assign = {}
    k_rms = {short_name(n)[0]: j for j, n in enumerate(rec_rms.channel_names)}
    for j, n in enumerate(rec_inst.channel_names):
        kz = short_name(n)[0]
        if kz in k_rms:
            assign[kz] = (j, k_rms[kz])
    if not assign:
        raise ValueError(tr("rms.no_common_channels"))
    t0, t1 = interval or (0.0, min(rec_inst.duration_s, rec_rms.duration_s))
    sel = (t_r >= t0 + window_s) & (t_r <= t1 - window_s)
    nw = int(round(window_s * rec_inst.fs))
    rows = []
    rms_device = rec_rms.read(0, rec_rms.n)
    for kz, (ji, jr) in assign.items():
        own_, with_dc, device = [], [], []
        for t_dev in t_r[sel]:
            # the device value at t_dev (presumably) describes the window [t_dev − T, t_dev) → check both positions
            i1 = int(round(t_dev * rec_inst.fs)); i0 = i1 - nw
            if i0 < 0:
                continue
            x = rec_inst.read(i0, i1, [ji])[:, 0]
            own_.append(float(dsp.true_rms(dsp.remove_dc(x, dc))))
            with_dc.append(float(np.sqrt(np.mean(np.square(x, dtype=float)))))
            device.append(float(rms_device[int(round(t_dev * rec_rms.fs)), jr]))
        e = np.array(own_); d = np.array(with_dc); g = np.array(device)
        ok = np.isfinite(e) & np.isfinite(g) & (g > 0)
        if not ok.any():
            continue
        rel = (e[ok] - g[ok]) / g[ok]
        rel_dc = float(np.median((d[ok] - g[ok]) / g[ok]))
        med = float(np.median(rel))
        note = ""
        if abs(med) >= 0.02:
            factor = float(np.median(g[ok] / e[ok])) if np.all(e[ok] > 0) else np.nan
            dec = np.log10(factor) if np.isfinite(factor) and factor > 0 else np.nan
            if abs(rel_dc) < 0.02:
                note = tr("rms.device_includes_dc", deviation=100 * rel_dc)
            elif np.isfinite(dec) and abs(dec) >= 0.9 and abs(dec - round(dec)) < 0.05:
                note = tr("rms.scaling", factor=10.0 ** round(dec))
            else:
                note = tr("rms.deviation_unexplained")
        rows.append(dict(channel=kz, n=int(ok.sum()), mean_own=float(e[ok].mean()),
                         mean_device=float(g[ok].mean()), deviation_median_pct=100 * med,
                         deviation_P95_pct=100 * float(np.percentile(np.abs(rel), 95)),
                         deviation_incl_dc_pct=100 * rel_dc, note=note))
    return pd.DataFrame(rows)


@dataclass
class VCurve:
    """Resonance curve (V curve) evaluated by [`v_curve`][groundfault.rms.v_curve].

    Attributes
    ----------
    I_min_measured : float
        Smallest RMS value (measured point) in A.
    t_min_s : float
        Time of the smallest value in s.
    I_min_fit : float
        Vertex of the fitted parabola in A (NaN without a V shape).
    x_min_fit : float
        Position of the vertex (coil current in A or time in s).
    axis : str
        Abscissa of the fit: ``"coil current"`` or ``"time"``.
    coefficients : tuple of float
        Coefficients (a, b, c) of the parabola I² = a·u² + b·u + c in the normalised abscissa
        u = (x − mean)/standard deviation of the fitted points.
    IG_v_curve : float
        Fundamental component at the operating point √(I_min² + Iv_operating²) in A.
    Iv_operating : float
        Operational detuning (reactive residual current) in A.
    note : str
        Hint if the vertex lies outside the measured points or no V shape is recognisable.
    """
    I_min_measured: float          # smallest RMS value (measured point)
    t_min_s: float
    I_min_fit: float               # vertex of the fitted parabola
    x_min_fit: float               # position of the vertex (coil current or time)
    axis: str                      # "coil current" | "time"
    coefficients: Tuple[float, float, float]
    IG_v_curve: float              # √(I_min² + Iv_operating²) with the operational detuning
    Iv_operating: float
    note: str = ""


def v_curve(t: np.ndarray, ires: np.ndarray, i_coil: Optional[np.ndarray] = None,
            interval: Optional[Tuple[float, float]] = None, Iv_operating: float = 0.0,
            fit_share: float = 0.5) -> VCurve:
    """Resonance curve (V curve): minimum of the residual earth-fault current while the coil is tuned.

    Method 1: the smallest measured value in the interval. Method 2: a parabola I² = a·x² + b·x + c fitted to the
    points around the minimum (``fit_share`` = share of the points with the smallest values), with x = coil current
    if given (physically I² = Iw² + I_H² + (I_L − I_Res)²), otherwise the time. The fundamental component at the
    operating point is I_G = √(I_min² + Iv_operating²); with RMS values, I_min also contains the harmonics
    (conservative), with |I_H1| from [`fundamental_trend`][groundfault.rms.fundamental_trend], I_min = Iw.

    Parameters
    ----------
    t : numpy.ndarray
        Time in s.
    ires : numpy.ndarray
        Residual earth-fault current (RMS value or |I_H1|) in A.
    i_coil : numpy.ndarray, optional
        Coil current in A at the same instants (abscissa of the fit; default: the time).
    interval : tuple of float, optional
        Evaluated interval (t0, t1) in s (default: all points).
    Iv_operating : float, optional
        Operational detuning (reactive residual current at the operating point) in A.
    fit_share : float, optional
        Share of the points with the smallest values used for the parabola (at least 5 points).

    Returns
    -------
    VCurve

    Raises
    ------
    ValueError
        If fewer than 5 finite points lie in the interval.
    """
    t = np.asarray(t, float); y = np.asarray(ires, float)
    m = np.isfinite(y)
    if interval is not None:
        m &= (t >= interval[0]) & (t <= interval[1])
    if m.sum() < 5:
        raise ValueError(tr("rms.too_few_points"))
    tt, yy = t[m], y[m]
    k = int(np.argmin(yy))
    x = np.asarray(i_coil, float)[m] if i_coil is not None else tt
    axis = "coil current" if i_coil is not None else "time"
    n_fit = max(5, int(fit_share * yy.size))
    idx = np.argsort(yy)[:n_fit]
    xs = x[idx]; s = float(np.std(xs)) or 1.0; x0 = float(np.mean(xs))
    M = np.column_stack([((xs - x0) / s) ** 2, (xs - x0) / s, np.ones_like(xs)])
    coef, *_ = np.linalg.lstsq(M, yy[idx] ** 2, rcond=None)
    a, b, c = coef
    note = ""
    if a > 0:
        u_min = -b / (2 * a)
        I2 = c - b * b / (4 * a)
        I_fit = math.sqrt(I2) if I2 > 0 else float("nan")
        x_min = x0 + s * u_min
        if not (xs.min() <= x_min <= xs.max()):
            note = tr("rms.vertex_outside")
    else:
        I_fit, x_min = float("nan"), float("nan")
        note = tr("rms.no_v_shape")
    I_min = float(yy[k])
    return VCurve(I_min_measured=I_min, t_min_s=float(tt[k]), I_min_fit=I_fit, x_min_fit=float(x_min),
                  axis=axis, coefficients=(float(a), float(b), float(c)),
                  IG_v_curve=float(math.hypot(I_min, Iv_operating)), Iv_operating=float(Iv_operating), note=note)


def fundamental_trend(rec: Recording, interval: Tuple[float, float], roles: Optional[RoleAssignment] = None,
                      T_win: float = 0.2, T_hop: float = 0.1, f1: Optional[float] = None,
                      f_nominal: float = 50.0) -> pd.DataFrame:
    """Time trend of I_RES (RMS), |I_H1|, Iw and Iv (angle method) and of the coil currents (H1) in an interval.

    Iw and Iv are the components of the fundamental of the fault current in phase and in quadrature with the
    zero-sequence voltage (from the line-to-earth voltages, otherwise the measured neutral displacement voltage);
    the polarity is chosen so that the median of Iw is positive. Iv > 0 means over-compensated, as
    ``Result.values["Iv"]`` of [`groundfault.evaluate`][groundfault.evaluation.evaluate].

    Parameters
    ----------
    rec : Recording
        Instantaneous-value recording.
    interval : tuple of float
        Interval (t0, t1) in s.
    roles : RoleAssignment, optional
        Channel roles (detected from the channel names if omitted).
    T_win, T_hop : float, optional
        Window length and hop in s.
    f1 : float, optional
        Fundamental frequency in Hz (default: estimated from U_L1-L2, otherwise from the fault current).
    f_nominal : float, optional
        Nominal frequency in Hz for the estimation.

    Returns
    -------
    pandas.DataFrame
        Columns ``t_s``, ``IRES_A``, ``IH1_A``; with voltages also ``Iw_A``, ``Iv_A``, ``U0_V``; per coil current
        ``<channel>_H1_A``.

    Raises
    ------
    ValueError
        If there is no fault-current channel (role ``i_res``).
    """
    roles = roles or detect_roles(rec.channel_names, rec.units)
    ires = roles.main("i_res")
    if ires is None:
        raise ValueError(tr("rms.no_fault_current_channel"))
    i0 = int(round(interval[0] * rec.fs)); i1 = int(round(interval[1] * rec.fs))
    blk = rec.read(i0, i1)
    le = roles.line_to_earth
    if f1 is None:
        ref = blk[:, le[0]] - blk[:, le[1]] if le else blk[:, ires.index]
        f1 = dsp.estimate_f1(ref[np.isfinite(ref)], rec.fs, f_nominal)["f1"]
    nwin, nhop, starts = dsp.window_grid(blk.shape[0], rec.fs, T_win, T_hop)

    def ph(j):
        X, r = dsp.dft_phasors(dsp.window_view(blk[:, j], nwin, nhop), rec.fs, [f1])
        return X[:, 0], r

    I1, Irms = ph(ires.index)
    df = pd.DataFrame(dict(t_s=(i0 + starts + nwin / 2) / rec.fs, IRES_A=Irms, IH1_A=np.abs(I1)))
    if le or roles.has("u_ne"):
        U0 = (sum(ph(k)[0] for k in le) / 3.0) if le else ph(roles.index("u_ne"))[0]
        d = np.angle(U0) - np.angle(I1)
        Iw = np.abs(I1) * np.cos(d); Iv = np.abs(I1) * np.sin(d)
        if np.nanmedian(Iw) < 0:                      # polarity (Iw > 0)
            Iw, Iv = -Iw, -Iv
        df["Iw_A"] = Iw; df["Iv_A"] = Iv; df["U0_V"] = np.abs(U0)
    for k in roles.with_role("i_coil"):
        df["%s_H1_A" % k.short] = np.abs(ph(k.index)[0])
    return df
