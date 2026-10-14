# -*- coding: utf-8 -*-
"""Raw-data diagnostics of a COMTRADE recording (.cfg/.dat).

Checks whether a file is usable for the evaluation **before** the analysis intervals are chosen:

* structure: file size ↔ record length, sample numbers, format, encoding,
* time base: sampling rate from the .cfg ↔ from the time stamps, jumps and irregularities,
* channels: active range, event time (largest step of the RMS value), DC offset, share of the fundamental,
  saturation (flat tops), "flat/broken",
* synchronism of the subsystems: event time of the voltages ↔ of the currents (DANEO export error with a time offset →
  suggestion ``alignment = dict(roles=[…], dt_s=…)`` for [`groundfault.evaluate`][groundfault.evaluation.evaluate]),
* digital channels: number of edges, first edge.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from . import dsp
from . import i18n
from .i18n import tr
from .evaluation import _flat_top_share
from .comtrade import Recording
from .channels import RoleAssignment, detect_roles

__all__ = ["Diagnosis", "diagnose"]

i18n.register({
    # ---- summary (Diagnosis.text)
    "diagnostics.summary_file": {
        "en": "File: {file} | {format} | {channels} channels | {samples:,} samples | {duration:.3f} s",
        "de": "Datei: {file} | {format} | {channels} Kanäle | {samples:,} Abtastwerte | {duration:.3f} s"},
    "diagnostics.summary_sampling_rate": {
        "en": "Sampling rate: cfg {fs_cfg:.3f} Hz | time stamps {fs_timestamps} Hz | used {fs:.3f} Hz ({source})",
        "de": "Abtastrate: cfg {fs_cfg:.3f} Hz | Zeitstempel {fs_timestamps} Hz | verwendet {fs:.3f} Hz ({source})"},
    "diagnostics.summary_time_stamps": {
        "en": "Time stamps: jumps {jumps} | irregular {irregular:.3f} % | sample numbers consecutive: {consecutive}",
        "de": "Zeitstempel: Sprünge {jumps} | unregelmäßig {irregular:.3f} % | Abtastnummern fortlaufend: "
              "{consecutive}"},
    "diagnostics.yes": {"en": "yes", "de": "ja"},
    "diagnostics.no": {"en": "NO", "de": "NEIN"},
    "diagnostics.summary_event_times": {
        "en": "Event time (largest step): voltages {voltages} s | currents {currents} s",
        "de": "Ereigniszeit (größter Sprung): Spannungen {voltages} s | Ströme {currents} s"},
    "diagnostics.summary_not_synchronous": {
        "en": "Subsystems not synchronous – suggestion: alignment = {suggestion!r}",
        "de": "Subsysteme nicht synchron – Vorschlag: alignment = {suggestion!r}"},
    "diagnostics.summary_no_findings": {"en": "no anomalies", "de": "keine Auffälligkeiten"},
    # ---- warnings
    "diagnostics.time_stamp_jumps": {
        "en": "Time stamps with {jumps} jumps/backward steps – check the time base.",
        "de": "Zeitstempel mit {jumps} Sprüngen/Rückschritten – Zeitbasis prüfen."},
    "diagnostics.sample_numbers": {
        "en": "Sample numbers not consecutive – the file may be concatenated or corrupt.",
        "de": "Abtastnummern nicht fortlaufend – Datei evtl. zusammengesetzt/defekt."},
    "diagnostics.channel_flat": {
        "en": "Channel {channel} ({role}) is flat – do not use it as a reference.",
        "de": "Kanal {channel} ({role}) flach – nicht als Referenz verwenden."},
    "diagnostics.not_synchronous": {
        "en": "Voltage and current channels show the fault inception at different times ({t_u:.3f} s ↔ "
              "{t_i:.3f} s). Try a new export first, otherwise set alignment.",
        "de": "Spannungs- und Stromkanäle zeigen den Fehlereintritt zu verschiedenen Zeiten ({t_u:.3f} s ↔ "
              "{t_i:.3f} s). Zuerst Neu-Export versuchen, sonst alignment setzen."},
    # ---- notes per channel (column note)
    "diagnostics.note_flat": {"en": "flat/broken", "de": "flach/kaputt"},
    "diagnostics.note_zero": {"en": "≈ 0 at the check time (faulted phase?)",
                              "de": "≈ 0 an der Prüfstelle (Fehlerleiter?)"},
    "diagnostics.note_little_50hz": {"en": "hardly any 50 Hz", "de": "kaum 50 Hz"},
    "diagnostics.note_saturation": {"en": "saturation {pct:.2f} %", "de": "Sättigung {pct:.2f} %"},
})


@dataclass
class Diagnosis:
    """Result of [`diagnose`][groundfault.diagnostics.diagnose].

    Attributes
    ----------
    file : str
        File name of the .cfg file.
    info : dict
        Header information of the recording ([`groundfault.Recording.info`][groundfault.comtrade.Recording.info]).
    time_base : dict
        ``fs`` (sampling rate used), ``fs_cfg``, ``fs_timestamps``, ``fs_source``, ``jumps`` (number of jumps and
        backward steps of the time stamps), ``irregular_pct`` (share of irregular time steps) and ``numbers_ok``
        (sample numbers consecutive).
    channels : pandas.DataFrame
        One row per analog channel: ``channel``, ``role``, ``unit``, ``peak_rms`` (largest RMS value),
        ``active_from_s``, ``active_to_s``, ``event_s`` (largest step of the RMS value), ``DC``, ``rms_ac``,
        ``share_H1_pct`` (share of the fundamental at the check time), ``saturation_pct`` and ``note``.
    digital : pandas.DataFrame
        One row per digital channel: ``channel``, ``Edges``, ``first_edge_s``.
    event_U_s, event_I_s : float or None
        Event time of the voltages and of the currents (median over the channels) in s.
    alignment_suggestion : dict or None
        ``dict(roles=[…], dt_s=…)`` for ``evaluate(…, alignment=…)`` if voltages and currents show the fault
        inception at different times.
    warnings : list of str
        Warnings of the recording and of the diagnosis.
    """
    file: str
    info: dict
    time_base: dict
    channels: pd.DataFrame
    digital: pd.DataFrame
    event_U_s: Optional[float]
    event_I_s: Optional[float]
    alignment_suggestion: Optional[dict]
    warnings: List[str] = field(default_factory=list)

    def text(self) -> str:
        """Summary as text, one finding per line, in the active output language.

        Returns
        -------
        str
        """
        tb = self.time_base
        lines = [tr("diagnostics.summary_file", file=self.file, format=self.info["format"],
                    channels=self.info["channels"], samples=int(self.info["samples"]),
                    duration=self.info["duration_s"]),
                 tr("diagnostics.summary_sampling_rate", fs_cfg=tb["fs_cfg"],
                    fs_timestamps=i18n.format_number(tb["fs_timestamps"], 3, mode="decimals"), fs=tb["fs"],
                    source=tb["fs_source"]),
                 tr("diagnostics.summary_time_stamps", jumps=tb["jumps"], irregular=tb["irregular_pct"],
                    consecutive=tr("diagnostics.yes") if tb["numbers_ok"] else tr("diagnostics.no"))]
        if self.event_U_s is not None or self.event_I_s is not None:
            lines.append(tr("diagnostics.summary_event_times", voltages=_seconds(self.event_U_s),
                            currents=_seconds(self.event_I_s)))
        if self.alignment_suggestion:
            lines.append("⚠ " + tr("diagnostics.summary_not_synchronous", suggestion=self.alignment_suggestion))
        for w in self.warnings:
            lines.append("⚠ " + w)
        if not self.warnings and not self.alignment_suggestion:
            lines.append("✓ " + tr("diagnostics.summary_no_findings"))
        return "\n".join(lines)


def _seconds(x: Optional[float]) -> str:
    """Time in s with three decimals in the style of the output language; None → "–"."""
    return i18n.format_number(x, 3, mode="decimals")


def _event_time(t: np.ndarray, r: np.ndarray, smooth: int = 5) -> Optional[float]:
    """Time of the largest step of the (smoothed) RMS trend (None if there is no clear step)."""
    r = np.asarray(r, float)
    if r.size < 3 * smooth or not np.isfinite(r).any() or np.nanmax(r) <= 0:
        return None
    k = np.ones(smooth) / smooth
    rp = np.pad(np.nan_to_num(r), smooth, mode="edge")             # continue the edge values (no step at the edges)
    rs = np.convolve(rp, k, mode="same")[smooth:-smooth]
    d = np.abs(np.diff(rs)) / (np.nanmax(rs) or 1.0)
    i = int(np.argmax(d))
    return float(0.5 * (t[i] + t[i + 1])) if d[i] > 0.05 else None


def _moving_median(r: np.ndarray, n: int = 51) -> np.ndarray:
    """Moving median over ``n`` values (51 ≈ 1 s for 20-ms values): suppresses transient peaks at the fault
    inception but keeps the step edges (start and end of the earth fault)."""
    r = np.nan_to_num(np.asarray(r, float))
    n = min(n, r.size if r.size % 2 else r.size - 1)
    if n < 3:
        return r
    rp = np.pad(r, n // 2, mode="edge")
    return np.median(np.lib.stride_tricks.sliding_window_view(rp, n), axis=1)


def _active_range(t: np.ndarray, r: np.ndarray, share: float = 0.1, n_median: int = 11):
    """First and last time with r > share·(robust maximum) → (from, to) or (nan, nan).

    The moving median over ``n_median`` values (11 ≈ 0.2 s) is evaluated: it removes the transient peak at the fault
    inception (at 0 Ω often a multiple of the steady current, typically < 0.1 s), which would otherwise shorten the
    active range to this one instant, and keeps sections from ≈ 0.12 s on together with their edges."""
    r = np.asarray(r, float)
    if r.size == 0 or not np.isfinite(r).any():
        return np.nan, np.nan
    rm = _moving_median(r, n_median)
    ref = float(np.max(rm))
    if not ref > 0:
        return np.nan, np.nan
    active = np.flatnonzero(rm > share * ref)
    return (float(t[active[0]]), float(t[active[-1]])) if active.size else (np.nan, np.nan)


def _active_section(t: np.ndarray, r: np.ndarray, t_inside: float, share: float = 0.1, n_median: int = 11,
                    gap_s: float = 1.0):
    """Like ``_active_range``, but only the contiguous active section around ``t_inside`` (gaps shorter than
    ``gap_s`` are bridged) → (from, to). If ``t_inside`` itself is not active: like ``_active_range``."""
    r = np.asarray(r, float)
    if r.size == 0 or not np.isfinite(r).any():
        return np.nan, np.nan
    rm = _moving_median(r, n_median)
    ref = float(np.nanmax(rm))
    if not ref > 0:
        return np.nan, np.nan
    active = rm > share * ref
    i = int(np.argmin(np.abs(t - t_inside)))
    if not active[i]:
        return _active_range(t, r, share, n_median)
    dt = float(np.median(np.diff(t))) if len(t) > 1 else 1.0
    n_gap = max(1, int(round(gap_s / dt)))
    a = i
    while True:                                   # to the left: active, or a gap < gap_s up to the next active value
        left = np.flatnonzero(active[max(0, a - n_gap):a])
        if not left.size:
            break
        a = max(0, a - n_gap) + int(left[0])
        if a == 0:
            break
    b = i
    while True:
        right = np.flatnonzero(active[b + 1:b + 1 + n_gap])
        if not right.size:
            break
        b = b + 1 + int(right[-1])
        if b >= len(t) - 1:
            break
    return float(t[a]), float(t[b])


def _longest_active_section(t: np.ndarray, r: np.ndarray, share: float = 0.5) -> Optional[float]:
    """Centre of the longest contiguous section with r > share·max (robust against transient peaks)."""
    if r.size == 0 or not np.isfinite(r).any():
        return None
    r = _moving_median(r)
    a = np.concatenate([[False], r > share * np.max(r), [False]]).astype(np.int8)
    d = np.diff(a); s0 = np.where(d == 1)[0]; s1 = np.where(d == -1)[0]
    if s0.size == 0:
        return None
    j = int(np.argmax(s1 - s0))
    return float(0.5 * (t[s0[j]] + t[s1[j] - 1]))


def diagnose(rec: Recording, roles: Optional[RoleAssignment] = None, probe_t: Optional[float] = None,
             probe_s: float = 0.5, rms_window_s: float = 0.02) -> Diagnosis:
    """Complete raw-data diagnosis of a recording.

    Parameters
    ----------
    rec : Recording
        The recording.
    roles : RoleAssignment, optional
        Channel roles (detected from the channel names if omitted).
    probe_t : float, optional
        Time of the channel check in s (default: the centre of the longest section with a high fault current,
        otherwise the middle of the recording).
    probe_s : float, optional
        Length of the checked section in s.
    rms_window_s : float, optional
        Window of the RMS trend over the whole file in s.

    Returns
    -------
    Diagnosis
        Time base, channel table, event times, alignment suggestion and warnings
        ([`Diagnosis.text`][groundfault.diagnostics.Diagnosis.text] gives a summary).
    """
    roles = roles or detect_roles(rec.channel_names, rec.units)
    warn = list(rec.warnings)
    # ---------------------------------------------------------------- time base
    n_ts = min(rec.n, 2_000_000)
    ts = rec.timestamps_us(0, n_ts)
    spr, irreg = 0, 0.0
    if np.any(ts):
        dt = np.diff(ts)
        med = float(np.median(dt[dt > 0])) if np.any(dt > 0) else float("nan")
        if np.isfinite(med):
            spr = int(np.sum(dt > 1.5 * med) + np.sum(dt <= 0))
            irreg = 100.0 * float(np.mean(np.abs(dt - med) > 0.5 * med))
    number = rec.sample_numbers(0, min(rec.n, 200_000)).astype(np.int64)
    numbers_ok = bool(number.size < 2 or np.all(np.diff(number) == 1))
    zb = dict(fs=rec.fs, fs_cfg=rec.fs_cfg, fs_timestamps=rec.fs_timestamps, fs_source=rec.fs_source,
              jumps=spr, irregular_pct=irreg, numbers_ok=numbers_ok)
    if spr:
        warn.append(tr("diagnostics.time_stamp_jumps", jumps=spr))
    if not numbers_ok:
        warn.append(tr("diagnostics.sample_numbers"))
    # ---------------------------------------------------------------- RMS trend (whole file)
    t_r, R = rec.rms_trend(window_s=rms_window_s)
    # ---------------------------------------------------------------- check time
    ires = roles.main("i_res")
    if probe_t is None:
        if ires is not None and R.shape[0]:
            probe_t = _longest_active_section(t_r, R[:, ires.index])
        if probe_t is None:
            probe_t = rec.duration_s / 2
    i0 = int(round(max(0.0, probe_t - probe_s / 2) * rec.fs))
    i0 = max(0, min(i0, rec.n - int(probe_s * rec.fs)))
    i1 = min(rec.n, i0 + int(round(probe_s * rec.fs)))
    blk = rec.read(i0, i1)
    rows = []
    event = {}
    for k in roles.channels:
        r = R[:, k.index] if R.size else np.array([])
        peak = float(np.nanmax(r)) if r.size else float("nan")
        from_, until = _active_range(t_r, r) if r.size else (np.nan, np.nan)
        ev = _event_time(t_r, r)
        event[k.index] = ev
        x = blk[:, k.index]
        x = x[np.isfinite(x)]
        dc = float(np.median(x)) if x.size else float("nan")
        x0 = x - dc
        rms_ac = float(np.sqrt(np.mean(x0 ** 2))) if x.size else float("nan")
        share50 = float("nan")
        if x0.size >= int(0.1 * rec.fs) and rms_ac > 0:
            nwin = int(round(0.2 * rec.fs)) if x0.size >= int(0.2 * rec.fs) else x0.size
            X, _ = dsp.dft_phasors(x0[None, :nwin], rec.fs, [rec.line_frequency or 50.0])
            share50 = 100.0 * abs(X[0, 0]) / float(np.sqrt(np.mean(x0[:nwin] ** 2)))
        sat = _flat_top_share(rec, k.index, i0, i1 - i0, max(4, int(round(1e-4 * rec.fs))))
        notes = []
        raw_span = (peak / abs(rec.analog[k.index].a * rec.analog[k.index].primary_factor)
                    if rec.analog[k.index].a else float("nan"))
        flat = not np.isfinite(peak) or raw_span < 5            # largest RMS value below 5 raw (ADC) steps
        if flat:
            notes.append(tr("diagnostics.note_flat"))
        elif k.role and k.role.startswith("u_l") and np.isfinite(rms_ac) and rms_ac < 0.05 * peak:
            notes.append(tr("diagnostics.note_zero"))
        elif np.isfinite(share50) and share50 < 20 and k.role and k.role.startswith("u_l"):
            notes.append(tr("diagnostics.note_little_50hz"))
        if sat > 1e-4:
            notes.append(tr("diagnostics.note_saturation", pct=100 * sat))
        rows.append(dict(channel=k.short, role=k.role or "–", unit=k.unit, peak_rms=peak,
                         active_from_s=from_, active_to_s=until,
                         event_s=ev if ev is not None else np.nan, DC=dc, rms_ac=rms_ac,
                         share_H1_pct=share50, saturation_pct=100 * sat, note=", ".join(notes)))
        if flat and k.role:
            warn.append(tr("diagnostics.channel_flat", channel=k.short, role=k.role))
    df = pd.DataFrame(rows)
    # ---------------------------------------------------------------- synchronism
    tU = [event[k.index] for k in roles.channels if k.role and k.role.startswith("u_l") and event[k.index] is not None]
    tI = [event[k.index] for k in roles.channels if k.role in ("i_res", "i_coil") and event[k.index] is not None]
    eU = float(np.median(tU)) if tU else None
    eI = float(np.median(tI)) if tI else None
    suggest = None
    if eU is not None and eI is not None and abs(eU - eI) > 0.2:
        suggest = dict(roles=[r for r in ("u_l1e", "u_l2e", "u_l3e", "u_l12", "u_l23", "u_l31", "u_ne")
                              if roles.has(r)], dt_s=round(eU - eI, 3))
        warn.append(tr("diagnostics.not_synchronous", t_u=eU, t_i=eI))
    # ---------------------------------------------------------------- digital channels
    dz = []
    if rec.digital:
        dig = rec.digital_values(0, min(rec.n, 5_000_000))
        for j, dk in enumerate(rec.digital):
            fl = np.flatnonzero(np.diff(dig[:, j].astype(np.int8)) != 0)
            dz.append(dict(channel=dk.name, Edges=int(fl.size),
                           first_edge_s=float((fl[0] + 1) / rec.fs) if fl.size else np.nan))
    return Diagnosis(file=os.path.basename(rec.cfg_path), info=rec.info(), time_base=zb, channels=df,
                     digital=pd.DataFrame(dz), event_U_s=eU, event_I_s=eI,
                     alignment_suggestion=suggest, warnings=warn)
