# -*- coding: utf-8 -*-
"""Signal explorer: time trend of all channels with RMS value and harmonics on hover, instantaneous values and
spectrum of a freely chosen excerpt – to check the evaluation ("does the value match the curve?").

* **Notebook:** ``explorer(rec, res)`` shows controls (channel selection, moving the excerpt, width, spectrum up to
  an order, RMS value or percent of H1) and interactive figures (Plotly, ``ipywidgets``).
* **Without Python:** ``explorer_html(rec, path, res)`` writes one HTML file (Plotly embedded, readable offline,
  opens in a browser without any installation). It contains the complete RMS trend with harmonics and the
  instantaneous values of selected excerpts (max window, fault inception/clearance, before/after the fault and
  evenly spread over the recording) together with their spectrum and characteristic values.

The computation is the same as in the evaluation ([`groundfault.evaluate`][groundfault.evaluation.evaluate]): window
``T_win`` (default 200 ms = 10 cycles), DC component removed per window by the median, true RMS value over all
frequencies, harmonics as RMS phasors from the DFT with a Hann window at m·f1, and THD = √(Σ_{m≥2} X_m²)/X_1 over the
computed orders. Given the evaluation result ``res``, f1 and the channel roles are taken from the evaluation; the values
of the max window then agree with its tables.

Titles, labels and hover texts follow the output language ([`groundfault.i18n`][groundfault.i18n]); the HTML file is
written in the language that is active when [`explorer_html`][groundfault.explorer.explorer_html] is called.
"""
from __future__ import annotations

import base64
import datetime as _dt
import html as _html
import json
import math
import os
import re
import warnings
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import dsp
from . import i18n
from .i18n import tr
from .report import INTERVAL_COLORS, _group_colors, _groups
from .channels import detect_roles, role_description

__all__ = ["WindowMetrics", "window_metrics", "line_frequency", "event_times", "excerpt_spectrum", "excerpt_table",
           "default_channels", "overview_figure", "instantaneous_figure", "spectrum_figure", "SignalExplorer",
           "explorer", "explorer_html", "MAX_SPECTRUM_S"]

#: Plotly template of all figures
TEMPLATE = "plotly_white"
#: Plotly number separators (decimal mark, thousands separator) per output language
SEPARATORS = {"en": ".,", "de": ",."}
#: locale of the number formatting in the HTML page (JavaScript ``toLocaleString``) per output language
_LOCALES = {"en": "en-GB", "de": "de-DE"}
#: keys of :func:`event_times` → message with the display name
_EVENT_LABELS = {"pre-fault": "explorer.event_pre_fault", "fault inception": "explorer.event_fault_inception",
                 "max window": "explorer.event_max_window", "fault clearance": "explorer.event_fault_clearance",
                 "post-fault": "explorer.event_post_fault"}

i18n.register({
    # ---- notes on the excerpt, missing packages
    "explorer.note_short_excerpt": {
        "en": "Excerpt < 2 cycles – spectrum over 10 cycles around the centre",
        "de": "Ausschnitt < 2 Perioden – Spektrum über 10 Perioden um die Mitte"},
    "explorer.note_long_excerpt": {
        "en": "Excerpt > {limit:g} s – spectrum and characteristic values over the middle {limit:g} s",
        "de": "Ausschnitt > {limit:g} s – Spektrum und Kennwerte über die mittleren {limit:g} s"},
    "explorer.plotly_missing": {
        "en": "plotly is not installed: pip install \"groundfault[interactive]\"",
        "de": "plotly ist nicht installiert: pip install \"groundfault[interactive]\""},
    "explorer.ipywidgets_missing": {
        "en": "ipywidgets is missing (pip install \"groundfault[interactive]\") – only the overview is shown.",
        "de": "ipywidgets fehlt (pip install \"groundfault[interactive]\") – nur die Übersicht wird angezeigt."},
    # ---- display names of the excerpts (keys of event_times)
    "explorer.event_pre_fault": {"en": "before the fault", "de": "vor dem Fehler"},
    "explorer.event_fault_inception": {"en": "fault inception", "de": "Fehlereintritt"},
    "explorer.event_max_window": {"en": "max window (evaluation)", "de": "Max-Fenster (Auswertung)"},
    "explorer.event_fault_clearance": {"en": "fault clearance", "de": "Fehlerende"},
    "explorer.event_post_fault": {"en": "after the fault", "de": "nach dem Fehler"},
    "explorer.excerpt_at": {"en": "t = {t:.1f} s", "de": "t = {t:.1f} s"},
    # ---- figures
    "explorer.axis": {"en": "{quantity} in {unit}", "de": "{quantity} in {unit}"},
    "explorer.rms_subscript": {"en": "rms", "de": "eff"},
    "explorer.overview_title": {
        "en": "RMS value per {window_ms:g} ms window (hover: harmonics, THD, DC component)",
        "de": "Effektivwert je {window_ms:g}-ms-Fenster (Mouse-over: Harmonische, THD, Gleichanteil)"},
    "explorer.instantaneous_title": {
        "en": "Instantaneous values {t0:.3f} … {t1:.3f} s{condensed}",
        "de": "Momentanwerte {t0:.3f} … {t1:.3f} s{condensed}"},
    "explorer.condensed": {
        "en": " (display condensed: minimum/maximum per section)",
        "de": " (Anzeige verdichtet: Minimum/Maximum je Abschnitt)"},
    "explorer.spectrum_title": {
        "en": "Spectrum of the excerpt (Hann, DFT at m·f1)",
        "de": "Spektrum des Ausschnitts (Hann, DFT bei m·f1)"},
    "explorer.spectrum_title_range": {
        "en": "Spectrum {t0:.3f} … {t1:.3f} s (Hann, f1 = {f1:.3f} Hz)",
        "de": "Spektrum {t0:.3f} … {t1:.3f} s (Hann, f1 = {f1:.3f} Hz)"},
    "explorer.share_of_fundamental": {"en": "Share of the fundamental", "de": "Anteil an der Grundschwingung"},
    "explorer.share_axis": {"en": "Share of H1 in %", "de": "Anteil an H1 in %"},
    "explorer.spectrum_hover": {
        "en": "{name} · order {order} ({f} Hz): <b>{value} {unit}</b> · {share} % of H1 · angle {angle}°",
        "de": "{name} · Ordnung {order} ({f} Hz): <b>{value} {unit}</b> · {share} % von H1 · Winkel {angle}°"},
    # ---- labels of the notebook interface and the HTML page
    "explorer.label_channels": {"en": "Channels", "de": "Kanäle"},
    "explorer.label_excerpt": {"en": "Excerpt", "de": "Ausschnitt"},
    "explorer.label_spectrum": {"en": "Spectrum", "de": "Spektrum"},
    "explorer.label_rms": {"en": "RMS value", "de": "Effektivwert"},
    "explorer.label_relative": {"en": "% of H1", "de": "% von H1"},
    "explorer.label_max_order": {"en": "up to order", "de": "bis Ordnung"},
    # ---- column headers of the table of an excerpt
    "explorer.col_channel": {"en": "Channel", "de": "Kanal"},
    "explorer.col_quantity": {"en": "Quantity", "de": "Größe"},
    "explorer.col_unit": {"en": "Unit", "de": "Einheit"},
    "explorer.col_rms": {"en": "RMS value", "de": "Effektivwert"},
    "explorer.col_dc": {"en": "DC component", "de": "Gleichanteil"},
    "explorer.col_peak": {"en": "Peak value", "de": "Scheitelwert"},
    "explorer.col_crest_factor": {"en": "Crest factor", "de": "Scheitelfaktor"},
    "explorer.col_h1_angle": {"en": "Angle H1", "de": "Winkel H1"},
    "explorer.col_h1_angle_deg": {"en": "Angle H1 in °", "de": "Winkel H1 in °"},
    "explorer.col_thd": {"en": "THD in %", "de": "THD in %"},
    # ---- notebook interface
    "explorer.ui_jump_to": {"en": "– jump to –", "de": "– springen zu –"},
    "explorer.ui_time": {"en": "Time", "de": "Zeitpunkt"},
    "explorer.ui_width": {"en": "Width", "de": "Breite"},
    "explorer.ui_one_cycle": {"en": "1 cycle", "de": "1 Periode"},
    "explorer.ui_cycles": {"en": "{n} cycles ({t:g} s)", "de": "{n} Perioden ({t:g} s)"},
    "explorer.ui_seconds": {"en": "{t:g} s", "de": "{t:g} s"},
    "explorer.ui_back": {"en": "◀ back", "de": "◀ zurück"},
    "explorer.ui_forward": {"en": "forward ▶", "de": "weiter ▶"},
    "explorer.ui_table_caption": {
        "en": "Characteristic values in the excerpt {t0:.3f} … {t1:.3f} s (RMS value without DC component, angles "
              "referred to H1 of {channel}):",
        "de": "Kennwerte im Ausschnitt {t0:.3f} … {t1:.3f} s (Effektivwert ohne Gleichanteil, Winkel bezogen auf H1 "
              "von {channel}):"},
    "explorer.ui_help": {
        "en": "Select several channels with Ctrl/⌘ or Shift. Hovering over the overview shows the RMS value, "
              "harmonics, THD and DC component per {window_ms:g} ms window (f1 = {f1:.3f} Hz); the excerpt is "
              "shaded grey, the analysis intervals in colour. Legend: a click hides a channel, a double click shows "
              "only this one.",
        "de": "Kanäle mit Strg/⌘ bzw. Shift mehrfach wählen. Mouse-over in der Übersicht zeigt Effektivwert, "
              "Harmonische, THD und Gleichanteil je {window_ms:g}-ms-Fenster (f1 = {f1:.3f} Hz); grau hinterlegt "
              "ist der Ausschnitt, farbig die Auswertebereiche. Legende: Klick blendet einen Kanal aus, Doppelklick "
              "zeigt nur diesen."},
    # ---- HTML page: static texts (overview help and footer contain markup)
    "explorer.html_title": {"en": "Signal explorer – {file}", "de": "Signal-Explorer – {file}"},
    "explorer.html_all": {"en": "all", "de": "alle"},
    "explorer.html_none": {"en": "none", "de": "keine"},
    "explorer.html_default": {"en": "default", "de": "Standard"},
    "explorer.html_rms_over_time": {"en": "RMS value over time", "de": "Effektivwert über der Zeit"},
    "explorer.html_overview_help": {
        "en": "Hover: RMS value, harmonics, THD and DC component of all selected channels at the same instant. A "
              "<b>click</b> into the chart selects the nearest excerpt (▼ = available excerpts). Drag = zoom, "
              "double click = back.",
        "de": "Mouse-over: Effektivwert, Harmonische, THD und Gleichanteil aller gewählten Kanäle zum selben "
              "Zeitpunkt. <b>Klick</b> in das Diagramm wählt den nächstgelegenen Ausschnitt (▼ = verfügbare "
              "Ausschnitte). Ziehen = Zoom, Doppelklick = zurück."},
    "explorer.html_no_channels": {
        "en": "No channels selected – tick at least one channel above.",
        "de": "Keine Kanäle gewählt – oben mindestens einen Kanal ankreuzen."},
    "explorer.html_instantaneous_heading": {
        "en": "Instantaneous values in the excerpt", "de": "Momentanwerte im Ausschnitt"},
    "explorer.html_spectrum_heading": {
        "en": "Spectrum and characteristic values of the excerpt", "de": "Spektrum und Kennwerte des Ausschnitts"},
    "explorer.html_envelope_summary": {
        "en": "Instantaneous values of the whole recording (envelope: minimum/maximum per section)",
        "de": "Momentanwerte der ganzen Aufzeichnung (Hüllkurve: Minimum/Maximum je Abschnitt)"},
    "explorer.html_footer": {
        "en": "Computed as in the evaluation tool (package <code>groundfault</code>): window {window_ms:.4g} ms, "
              "DC component removed per window by the median, true RMS value over all frequencies, harmonics as RMS "
              "values from the DFT with a Hann window at m·f1 (f1 = {f1:.6g} Hz), THD = √(Σ H<sub>m</sub>², "
              "m ≥ 2)/H<sub>1</sub>. Angles in the spectrum and in the table are referred to the fundamental of the "
              "first selected channel (φ<sub>m</sub> − m·φ<sub>1</sub>). Instantaneous values are stored for the "
              "display with at most {fs_max_khz:g} kHz (low-pass filtered); spectrum and characteristic values are "
              "computed from the original data.",
        "de": "Berechnung wie im Auswertewerkzeug (Paket <code>groundfault</code>): Fenster {window_ms:.4g} ms, "
              "Gleichanteil je Fenster per Median entfernt, Echt-Effektivwert über alle Frequenzen, Harmonische als "
              "Effektivwerte aus der DFT mit Hann-Fenster bei m·f1 (f1 = {f1:.6g} Hz), THD = √(Σ H<sub>m</sub>², "
              "m ≥ 2)/H<sub>1</sub>. Winkel im Spektrum und in der Tabelle sind auf die Grundschwingung des ersten "
              "gewählten Kanals bezogen (φ<sub>m</sub> − m·φ<sub>1</sub>). Momentanwerte für die Anzeige mit "
              "höchstens {fs_max_khz:g} kHz (Tiefpass) gespeichert, Spektrum und Kennwerte aus den Originaldaten."},
    "explorer.html_created": {
        "en": "Created {date} with the evaluation tool groundfault.",
        "de": "Erstellt {date} mit dem Auswertewerkzeug groundfault."},
    "explorer.date_format": {"en": "%Y-%m-%d %H:%M", "de": "%d.%m.%Y %H:%M"},
    # ---- HTML page: texts of the page script ({field} placeholders are filled in by the script)
    "explorer.meta_measurement": {"en": "Measurement {name}", "de": "Messung {name}"},
    "explorer.meta_start": {"en": "Start {start}", "de": "Start {start}"},
    "explorer.meta_sampling_rate": {"en": "Sampling rate {fs} Hz", "de": "Abtastrate {fs} Hz"},
    "explorer.meta_duration": {"en": "Duration {duration} s", "de": "Dauer {duration} s"},
    "explorer.meta_channels": {"en": "{n} channels", "de": "{n} Kanäle"},
    "explorer.excerpts": {"en": "Excerpts", "de": "Ausschnitte"},
    "explorer.excerpt_hover": {"en": "Excerpt {name}", "de": "Ausschnitt {name}"},
    "explorer.excerpt_title": {
        "en": "Instantaneous values in the excerpt “{name}” ({t0} … {t1} s)",
        "de": "Momentanwerte im Ausschnitt „{name}“ ({t0} … {t1} s)"},
})


def _separators() -> str:
    """Plotly number separators (decimal mark, thousands separator) of the active output language."""
    return SEPARATORS[i18n.get_language()]


def _event_label(key: str) -> str:
    """Display name of an excerpt key of [`event_times`][groundfault.explorer.event_times] in the active output
    language."""
    return tr(_EVENT_LABELS[key]) if key in _EVENT_LABELS else key


# =========================================================================== characteristic values per window
@dataclass
class WindowMetrics:
    """RMS value, DC component, peak value and harmonics per window over the whole recording.

    Created by [`window_metrics`][groundfault.explorer.window_metrics]. The arrays are indexed ``[window, column]``
    (phasors ``[window, column, order]``); the columns belong to the channels in [`channels`][groundfault.channels].

    Attributes
    ----------
    t : numpy.ndarray
        Window centres in s, shape ``(n_w,)``.
    T_win, T_hop : float
        Window length and hop in s (whole samples).
    f1 : float
        Fundamental frequency in Hz of the harmonics.
    orders : numpy.ndarray
        Harmonic orders of ``X``, shape ``(n_m,)``.
    channels : list of int
        Channel indices of the columns.
    rms : numpy.ndarray
        True RMS value without the DC component, shape ``(n_w, n_k)``.
    dc : numpy.ndarray
        DC component (mean value), shape ``(n_w, n_k)``.
    peak : numpy.ndarray
        Largest magnitude of the instantaneous values, shape ``(n_w, n_k)``.
    X : numpy.ndarray
        Complex RMS phasors of the orders, shape ``(n_w, n_k, n_m)``.
    """
    t: np.ndarray                 # window centres in s, (n_w,)
    T_win: float
    T_hop: float
    f1: float
    orders: np.ndarray            # (n_m,)
    channels: List[int]           # channel indices of the columns
    rms: np.ndarray               # (n_w, n_k) true RMS value without DC component
    dc: np.ndarray                # (n_w, n_k) DC component (mean value)
    peak: np.ndarray              # (n_w, n_k) largest magnitude of the instantaneous values
    X: np.ndarray                 # (n_w, n_k, n_m) RMS phasors

    def column(self, channel_index: int) -> int:
        """Column of the channel ``channel_index`` in the arrays."""
        return self.channels.index(int(channel_index))

    def H(self, m: int) -> np.ndarray:
        """RMS value of order ``m`` per window and column (NaN if the order was not computed)."""
        o = list(self.orders)
        return np.abs(self.X[:, :, o.index(m)]) if m in o else np.full(self.rms.shape, np.nan)

    @property
    def thd(self) -> np.ndarray:
        """THD per window and column (p.u.) over the computed orders ≥ 2."""
        H = np.abs(self.X); o = self.orders
        h1 = H[:, :, list(o).index(1)] if 1 in o else np.full(self.rms.shape, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.sqrt(np.nansum(H[:, :, o >= 2] ** 2, axis=2)) / np.where(h1 > 0, h1, np.nan)

    def table(self, channel_index: int, orders: Sequence[int] = (1, 3, 5, 7)) -> pd.DataFrame:
        """Values of one channel per window.

        Parameters
        ----------
        channel_index : int
            Channel index (one of [`channels`][groundfault.channels]).
        orders : sequence of int, optional
            Harmonic orders included as columns ``H<m>``.

        Returns
        -------
        pandas.DataFrame
            Columns ``t_s``, ``rms``, ``H<m>`` per order, ``THD_pct``, ``dc`` and ``peak``.
        """
        j = self.column(channel_index)
        d = dict(t_s=self.t, rms=self.rms[:, j])
        for m in orders:
            d["H%d" % m] = self.H(m)[:, j]
        d.update(THD_pct=100 * self.thd[:, j], dc=self.dc[:, j], peak=self.peak[:, j])
        return pd.DataFrame(d)


def line_frequency(rec, roles=None, duration_s: float = 10.0, f_nominal: float = 50.0) -> float:
    """Network frequency for the overview.

    Estimated from a section in the middle of the recording (at most ``duration_s``) of the first suitable channel:
    line-to-line or line-to-earth voltage (preferred), neutral displacement voltage, fault current, earth potential
    rise or touch voltage, otherwise any channel.

    Parameters
    ----------
    rec : Recording
        The recording.
    roles : RoleAssignment, optional
        Channel roles (detected from the channel names if omitted).
    duration_s : float, optional
        Length of the analysed section in s.
    f_nominal : float, optional
        Nominal frequency in Hz; returned if no channel gives a plausible estimate.

    Returns
    -------
    float
        Frequency in Hz.
    """
    roles = roles or detect_roles(rec.channel_names, rec.units)
    cand = [k for r in ("u_l12", "u_l1e", "u_l2e", "u_l3e", "u_hv_l1e", "u_ne", "i_res", "u_e", "u_t")
            for k in roles.with_role(r)] or list(roles.channels)
    d = min(duration_s, rec.duration_s)
    i0 = int(max(0.0, rec.duration_s / 2 - d / 2) * rec.fs); i1 = min(rec.n, i0 + int(d * rec.fs))
    for k in cand:
        x = rec.read(i0, i1, [k.index])[:, 0]
        x = x[np.isfinite(x)]
        if x.size < 4 * rec.fs / f_nominal or not np.std(x) > 0:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            r = dsp.estimate_f1(x, rec.fs, f_nominal)
        if r["plausible"] or abs(r["f1"] - f_nominal) < 0.5:
            return float(r["f1"])
    return float(f_nominal)


def window_metrics(rec, channels=None, T_win: float = 0.2, T_hop: Optional[float] = None,
                   orders: Iterable[int] = range(1, 26), f1: Optional[float] = None, roles=None,
                   window: str = "hann", block_windows: int = 200, shift=None) -> WindowMetrics:
    """Characteristic values per window over the whole recording.

    The recording is read block by block (``block_windows`` windows at a time), so the memory stays small for long
    recordings. Per window: true RMS value after removing the DC component (median), mean value, peak value and the
    RMS phasors at m·f1 (window function ``window``) – the same functions as in the evaluation.

    Parameters
    ----------
    rec : Recording
        The recording.
    channels : sequence of int or str, optional
        Channels (default: all).
    T_win : float, optional
        Window length in s (default 0.2 s = 10 cycles at 50 Hz).
    T_hop : float, optional
        Hop between the windows in s (default ``T_win``).
    orders : iterable of int, optional
        Harmonic orders; order 1 is always included, orders at or above half the sampling rate are dropped.
    f1 : float, optional
        Fundamental frequency in Hz (default: [`line_frequency`][groundfault.explorer.line_frequency]).
    roles : RoleAssignment, optional
        Channel roles for the frequency estimation.
    window : str, optional
        Window function of the DFT.
    block_windows : int, optional
        Number of windows read per block.
    shift : dict, optional
        Time offset per channel ``{index: Δn}`` in samples, as in the evaluation (alignment of subsystems that were
        recorded with different time bases).

    Returns
    -------
    WindowMetrics
    """
    idx = rec._indices(channels)
    fs = rec.fs
    f1 = float(f1) if f1 else line_frequency(rec, roles)
    ords = np.array(sorted(set(int(m) for m in orders) | {1}))
    ords = ords[ords * f1 < fs / 2]
    nwin, nhop, starts = dsp.window_grid(rec.n, fs, T_win, T_hop or T_win)
    n_w, n_k = len(starts), len(idx)
    X = np.full((n_w, n_k, len(ords)), np.nan + 0j)
    rms = np.full((n_w, n_k), np.nan); dc = rms.copy(); sp = rms.copy()
    for a in range(0, n_w, block_windows):
        b = min(n_w, a + block_windows)
        blk = rec.read(int(starts[a]), int(starts[b - 1]) + nwin, idx, shift)
        for j in range(n_k):
            seg = dsp.window_view(blk[:, j], nwin, nhop)[: b - a]
            Xj, rj = dsp.dft_phasors(seg, fs, f1 * ords, window, "median")
            X[a:b, j] = Xj; rms[a:b, j] = rj
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                dc[a:b, j] = np.nanmean(seg, axis=1)
                sp[a:b, j] = np.nanmax(np.abs(seg), axis=1)
    t = (starts + nwin / 2.0) / fs
    return WindowMetrics(t=t, T_win=nwin / fs, T_hop=nhop / fs, f1=f1, orders=ords, channels=list(idx), rms=rms,
                         dc=dc, peak=sp, X=X)


def event_times(rec, roles, res=None, shift=None) -> Dict[str, Tuple[float, float]]:
    """Useful excerpts of a recording: the max window of the evaluation, fault inception and clearance and the
    intervals before and after the fault.

    Fault inception and clearance are taken from the RMS trend of the fault current (main channel of the role
    ``i_res``; without it the earth potential rise or the touch voltage).

    Parameters
    ----------
    rec : Recording
        The recording.
    roles : RoleAssignment
        Channel roles.
    res : Result, optional
        Evaluation result: analysis intervals and max window.
    shift : dict, optional
        Time offset per channel ``{index: Δn}`` (alignment); fault inception and clearance are converted to the
        aligned time axis, as in the display.

    Returns
    -------
    dict
        ``{key: (t0, t1)}`` in s with the keys (missing excerpts are left out)

        * ``"pre-fault"`` – 200 ms in the middle of the pre-fault interval of the evaluation (without an evaluation:
          1 s before the fault inception),
        * ``"fault inception"`` – 200 ms from 50 ms before the fault inception (not if the fault current flows from
          the start of the file),
        * ``"max window"`` – the max window of the evaluation (only with ``res``),
        * ``"fault clearance"`` – 200 ms up to 50 ms after the fault clearance,
        * ``"post-fault"`` – 200 ms in the middle of the post-fault interval (without an evaluation: 1 s after the
          fault clearance).

        The keys are codes; the notebook interface and the HTML page show them with display names in the output
        language.
    """
    from .station import fault_times
    T = 0.2
    z: Dict[str, Tuple[float, float]] = {}
    k = roles.main("i_res") or roles.main("u_e") or roles.main("u_t")
    t_on = t_off = None
    if k is not None:
        try:
            t_on, t_off = fault_times(rec, k.index)
        except Exception:                                               # pragma: no cover - convenience only
            t_on = t_off = None
        dt = float((shift or {}).get(k.index, 0)) / rec.fs       # the channel is read dt later
        if dt:
            t_on, t_off = (None if x is None else x - dt for x in (t_on, t_off))
        if t_on is not None and t_on < 0.1:                            # active from the start of the file → no inception
            t_on = None
    b = getattr(res, "intervals", None)
    if b is not None and b.pre_fault:
        m = 0.5 * (b.pre_fault[0] + b.pre_fault[1]); z["pre-fault"] = (m - T / 2, m + T / 2)
    elif t_on is not None and t_on > 1.2:
        z["pre-fault"] = (t_on - 1.0 - T / 2, t_on - 1.0 + T / 2)
    if t_on is not None:
        z["fault inception"] = (max(0.0, t_on - 0.05), max(0.0, t_on - 0.05) + T)
    if res is not None and hasattr(res, "t_max_window"):
        tm = float(res.t_max_window); Tw = float(res.settings.T_win)
        z["max window"] = (tm - Tw / 2, tm + Tw / 2)
    if t_off is not None:
        z["fault clearance"] = (t_off - T + 0.05, t_off + 0.05)
    if b is not None and b.post_fault:
        m = 0.5 * (b.post_fault[0] + b.post_fault[1]); z["post-fault"] = (m - T / 2, m + T / 2)
    elif t_off is not None and t_off + 1.2 < rec.duration_s:
        z["post-fault"] = (t_off + 1.0 - T / 2, t_off + 1.0 + T / 2)
    return {n: (max(0.0, a), min(rec.duration_s, e)) for n, (a, e) in z.items() if e - a > 0.02}


# =========================================================================== excerpt: spectrum and table
MAX_SPECTRUM_S = 10.0
"""Spectrum and characteristic values over at most this many seconds (middle of the excerpt) – limits memory and
time."""


def _read_window(rec, channels: Sequence[int], t0: float, t1: float, f1: float, shift=None):
    """Data of an excerpt; shorter than 2 cycles → 10 cycles around its centre (the spectrum needs resolution),
    longer than ``MAX_SPECTRUM_S`` → the middle ``MAX_SPECTRUM_S`` seconds. Returns (data, t0, t1, note)."""
    note = ""
    if t1 - t0 < 2.0 / f1:
        note = tr("explorer.note_short_excerpt")
    elif t1 - t0 > MAX_SPECTRUM_S:
        note = tr("explorer.note_long_excerpt", limit=MAX_SPECTRUM_S)
    t0, t1 = _limits(rec, t0, t1, f1)
    i0, i1 = int(round(t0 * rec.fs)), int(round(t1 * rec.fs))
    return rec.read(i0, max(i1, i0 + 4), list(channels), shift), t0, t1, note


def _phasors(x: np.ndarray, fs: float, freqs: np.ndarray, block: int = 1 << 15) -> np.ndarray:
    """Hann-window DFT phasors (RMS values) of an excerpt – for long excerpts computed block by block, so that the
    matrix e^{−j2πfn/f_s} is never built for all samples at once (same result as
    [`dsp.window_phasors`][groundfault.dsp.window_phasors])."""
    x = np.asarray(x, float)
    if len(x) <= 4 * block:
        return dsp.window_phasors(x, fs, freqs)[0]
    if not np.isfinite(x).all():
        return np.full(len(freqs), np.nan + 0j)
    N = len(x)
    w = dsp.window_function(N, "hann")
    x0 = (x - np.median(x)) * w
    X = np.zeros(len(freqs), complex)
    for a in range(0, N, block):
        n = np.arange(a, min(N, a + block))
        X += x0[n] @ np.exp(-2j * np.pi * np.outer(n, freqs) / fs)
    return X * math.sqrt(2.0) / (N * dsp.coherent_gain(w))


def excerpt_spectrum(rec, channels: Sequence[int], t0: float, t1: float, f1: float,
                     orders: Iterable[int] = range(1, 41), roles=None, reference: Optional[int] = None,
                     raw: bool = False, shift=None) -> pd.DataFrame:
    """Harmonics of the excerpt [t0, t1] per channel: RMS value, angle and share of H1 (Hann window, DFT at m·f1).

    The angles are referred to the fundamental of the reference channel, as in the evaluation: φ_m − m·φ_1,ref –
    and are therefore independent of the time origin.

    Parameters
    ----------
    rec : Recording
        The recording.
    channels : sequence of int
        Channel indices.
    t0, t1 : float
        Excerpt in s (shorter than 2 cycles: 10 cycles around its centre; longer than
        [`MAX_SPECTRUM_S`][groundfault.explorer.MAX_SPECTRUM_S]: the middle
        [`MAX_SPECTRUM_S`][groundfault.explorer.MAX_SPECTRUM_S] seconds).
    f1 : float
        Fundamental frequency in Hz.
    orders : iterable of int, optional
        Harmonic orders (order 1 is always included; orders at or above half the sampling rate are dropped).
    roles : RoleAssignment, optional
        Channel roles (short names and units).
    reference : int, optional
        Channel index of the angle reference (default: the first channel).
    raw : bool, optional
        True: angles without reference (phase at the start of the excerpt; used by the HTML page, which chooses
        the reference itself).
    shift : dict, optional
        Time offset per channel ``{index: Δn}`` (alignment).

    Returns
    -------
    pandas.DataFrame
        One row per channel and order: ``channel``, ``index``, ``unit``, ``order``, ``f_Hz``, ``rms``,
        ``angle_deg``, ``share_H1_pct``.
    """
    roles = roles or detect_roles(rec.channel_names, rec.units)
    channels = [int(k) for k in channels]
    x, t0, t1, _ = _read_window(rec, channels, t0, t1, f1, shift)
    ords = np.array([m for m in sorted(set(int(m) for m in orders) | {1}) if m * f1 < rec.fs / 2])
    X = np.empty((len(channels), len(ords)), complex)
    for j in range(len(channels)):
        X[j] = _phasors(x[:, j], rec.fs, f1 * ords)
    jb = channels.index(reference) if reference in channels else 0
    phi1 = 0.0 if raw else np.angle(X[jb, 0])
    rows = []
    for j, k in enumerate(channels):
        ki = roles.channels[k]
        for i, m in enumerate(ords):
            z = X[j, i] * np.exp(-1j * m * phi1)
            rows.append(dict(channel=ki.short, index=k, unit=ki.unit, order=int(m), f_Hz=float(m * f1),
                             rms=float(abs(X[j, i])), angle_deg=float(np.degrees(np.angle(z))),
                             share_H1_pct=float(100 * abs(X[j, i]) / abs(X[j, 0])) if abs(X[j, 0]) > 0 else np.nan))
    return pd.DataFrame(rows)


def excerpt_table(rec, channels: Sequence[int], t0: float, t1: float, f1: float, roles=None,
                  orders: Iterable[int] = range(1, 41), reference: Optional[int] = None,
                  shift=None) -> pd.DataFrame:
    """Characteristic values per channel in the excerpt [t0, t1].

    RMS value (without the DC component), DC component, peak value, crest factor, H1 with its angle (referred to
    the reference channel), H3/H5/H7 and THD over the orders ≥ 2 up to ``max(orders)``.

    Parameters
    ----------
    rec : Recording
        The recording.
    channels : sequence of int
        Channel indices.
    t0, t1 : float
        Excerpt in s (see [`excerpt_spectrum`][groundfault.explorer.excerpt_spectrum] for very short and very long
        excerpts).
    f1 : float
        Fundamental frequency in Hz.
    roles : RoleAssignment, optional
        Channel roles.
    orders : iterable of int, optional
        Harmonic orders of the spectrum (and of the THD).
    reference : int, optional
        Channel index of the angle reference (default: the first channel).
    shift : dict, optional
        Time offset per channel ``{index: Δn}`` (alignment).

    Returns
    -------
    pandas.DataFrame
        One row per channel: ``channel``, ``role`` (description of the role), ``unit``, ``rms``, ``dc``, ``peak``,
        ``crest_factor``, ``H1``, ``H1_angle_deg``, ``H3``, ``H5``, ``H7``, ``THD_pct``. ``attrs`` holds the time
        limits actually used (``t0``, ``t1``) and a ``note`` if the excerpt was shortened or extended.
    """
    roles = roles or detect_roles(rec.channel_names, rec.units)
    channels = [int(k) for k in channels]
    x, t0, t1, note = _read_window(rec, channels, t0, t1, f1, shift)
    sp = excerpt_spectrum(rec, channels, t0, t1, f1, orders, roles, reference, shift=shift)
    rows = []
    for j, k in enumerate(channels):
        ki = roles.channels[k]
        xj = x[:, j][np.isfinite(x[:, j])]
        x0 = dsp.remove_dc(xj[None, :], "median", axis=1)[0] if xj.size else xj
        eff = float(dsp.true_rms(x0)) if xj.size else np.nan
        s = sp[sp["index"] == k].set_index("order")
        h = lambda m: float(s.at[m, "rms"]) if m in s.index else np.nan   # noqa: E731
        thd = float(np.sqrt(np.nansum(s.loc[s.index >= 2, "rms"] ** 2)) / h(1)) if h(1) > 0 else np.nan
        peak = float(np.max(np.abs(xj))) if xj.size else np.nan
        rows.append(dict(channel=ki.short, role=role_description(ki.role, "–"), unit=ki.unit,
                         rms=eff, dc=float(np.mean(xj)) if xj.size else np.nan,
                         peak=peak, crest_factor=peak / eff if eff > 0 else np.nan,
                         H1=h(1), H1_angle_deg=float(s.at[1, "angle_deg"]) if 1 in s.index else np.nan,
                         H3=h(3), H5=h(5), H7=h(7), THD_pct=100 * thd))
    df = pd.DataFrame(rows)
    df.attrs.update(t0=t0, t1=t1, note=note)
    return df


# =========================================================================== Plotly figures
def _go():
    """plotly.graph_objects and make_subplots (ImportError with installation hint if plotly is missing)."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except Exception as ex:                                             # pragma: no cover
        raise ImportError(tr("explorer.plotly_missing")) from ex
    return go, make_subplots


def _colors(roles) -> Dict[int, str]:
    """Fixed colour per channel as in the report figures (the colour follows the quantity)."""
    f = {}
    for ks in _groups(roles, None).values():
        for k, c in zip(ks, _group_colors(ks)):
            f[k.index] = c
    return f


def _unit_label(ks, extra: str = "", small: bool = False) -> str:
    """Axis title "U<sub>eff</sub> in V" / "i in A" from the unit of the first channel."""
    e = ks[0].unit or ""
    z = "U" if e.upper().startswith("V") else "I" if e.upper().startswith("A") else "x"
    return tr("explorer.axis", quantity=(z.lower() if small else z) + extra, unit=e)


def default_channels(roles, n_max: int = 10) -> List[int]:
    """Channels selected by default.

    Parameters
    ----------
    roles : RoleAssignment
        Channel roles.
    n_max : int, optional
        Maximum number of channels.

    Returns
    -------
    list of int
        Channel indices of the fault current, earth potential rise/touch voltage, line-to-earth and neutral
        displacement voltages, coil, shield and PEN currents (at most ``n_max``); without any of these the first
        six channels.
    """
    important = ("i_res", "u_e", "u_t", "u_l1e", "u_l2e", "u_l3e", "u_ne", "i_coil", "i_shield", "i_pen")
    ks = [k.index for k in roles.channels if k.role in important]
    return ks[:n_max] if ks else [k.index for k in roles.channels][:6]


def _stack(groups: Sequence[str], ytitle: Sequence[str], height_per_panel: int, title: str,
           t_format: str = ".3f", top_free: float = 0.0):
    """Empty figure with panels stacked on **one** common time axis (one y axis per panel). The hover label
    ("x unified", ``hoversubplots="axis"``) therefore shows all channels of all panels at the same instant in one
    box."""
    go, _ = _go()
    n = max(1, len(groups))
    top = 1.0 - top_free
    gap = (0.07 if n < 4 else 0.04) * top
    h = (top - gap * (n - 1)) / n
    lay = dict(template=TEMPLATE, separators=_separators(), height=height_per_panel * n + 110, title=title,
               hovermode="x unified", hoversubplots="axis", margin=dict(t=70, b=40, l=70, r=20),
               legend=dict(orientation="h", y=1.02, yanchor="bottom", x=1, xanchor="right"),
               xaxis=dict(title_text=tr("explorer.axis", quantity="t", unit="s"), anchor="y%d" % n if n > 1 else "y",
                          unifiedhovertitle=dict(text="t = %%{x:%s} s" % t_format)),
               annotations=[])
    for r in range(n):
        top_ = top - r * (h + gap)
        lay["yaxis%s" % (r + 1 if r else "")] = dict(domain=[max(0.0, top_ - h), top_], title_text=ytitle[r],
                                                      anchor="x")
        lay["annotations"].append(dict(text="<b>%s</b>" % groups[r], xref="paper", yref="paper", x=0, y=top_,
                                       xanchor="left", yanchor="bottom", showarrow=False, font=dict(size=12)))
    try:
        return go.Figure(layout=lay)
    except ValueError:                     # plotly < 6.3 (below the declared minimum): no common hover label
        lay.pop("hoversubplots", None)
        lay["xaxis"].pop("unifiedhovertitle", None)
        return go.Figure(layout=lay)


def _y(r: int) -> str:
    """Name of the y axis of panel ``r`` (``"y"``, ``"y2"``, …)."""
    return "y%d" % (r + 1) if r else "y"


def _draw_intervals(fig, intervals):
    """Shade the analysis intervals in colour (across all panels)."""
    if intervals is None:
        return
    for name in ("pre_fault", "steady_state", "post_fault"):
        b = getattr(intervals, name, None) if not isinstance(intervals, dict) else intervals.get(name)
        if b:
            fig.add_shape(type="rect", xref="x", yref="paper", x0=b[0], x1=b[1], y0=0, y1=1, layer="below",
                          fillcolor=INTERVAL_COLORS[name], opacity=0.3, line_width=0)


def _hover_harmonics(unit: str, orders) -> str:
    """Hover template of the overview: RMS value, harmonics, THD and DC component."""
    parts = ["%%{fullData.name}: <b>%%{y:,.4~r} %s</b>" % unit]
    for i, m in enumerate(orders):
        parts.append("H%d %%{customdata[%d]:,.3~r}" % (m, i))
    n = len(orders)
    parts.append("THD %%{customdata[%d]:.1f} %%" % n)
    parts.append("DC %%{customdata[%d]:,.3~r}" % (n + 1))
    return " · ".join(parts) + "<extra></extra>"


def overview_figure(kw: WindowMetrics, roles, channels: Optional[Sequence[int]] = None, intervals=None,
                    excerpt: Optional[Tuple[float, float]] = None, hover_orders: Sequence[int] = (1, 3, 5, 7),
                    height_per_panel: int = 210, title: Optional[str] = None):
    """RMS value per window over time, one panel per physical quantity.

    The hover label shows RMS value, harmonics, THD and DC component of all visible channels at the same instant.

    Parameters
    ----------
    kw : WindowMetrics
        Characteristic values per window ([`window_metrics`][groundfault.explorer.window_metrics]).
    roles : RoleAssignment
        Channel roles (grouping and colours).
    channels : sequence of int, optional
        Channels to show (default: all channels of ``kw``).
    intervals : Intervals or dict, optional
        Analysis intervals (``pre_fault``, ``steady_state``, ``post_fault``), shaded in colour.
    excerpt : tuple of float, optional
        Excerpt (t0, t1) in s, shaded grey.
    hover_orders : sequence of int, optional
        Harmonic orders shown on hover.
    height_per_panel : int, optional
        Height of one panel in pixels.
    title : str, optional
        Figure title (default: window length and hover content).

    Returns
    -------
    plotly.graph_objects.Figure
    """
    go, _ = _go()
    channels = [k for k in (channels if channels is not None else kw.channels) if k in kw.channels]
    groups = _groups(roles, channels)
    colors = _colors(roles)
    fig = _stack(list(groups) or [""],
                 [_unit_label(ks, "<sub>%s</sub>" % tr("explorer.rms_subscript")) for ks in groups.values()] or [""],
                 height_per_panel, title or tr("explorer.overview_title", window_ms=1000 * kw.T_win), t_format=".2f")
    ords = [m for m in hover_orders if m in kw.orders]
    thd = kw.thd
    for r, (g, ks) in enumerate(groups.items()):
        for k in ks:
            j = kw.column(k.index)
            cd = np.column_stack([kw.H(m)[:, j] for m in ords] + [100 * thd[:, j], kw.dc[:, j]])
            fig.add_trace(go.Scatter(x=kw.t, y=kw.rms[:, j], mode="lines", name=k.short, legendgroup=k.short,
                                     line=dict(color=colors.get(k.index), width=1.4), customdata=cd, yaxis=_y(r),
                                     hovertemplate=_hover_harmonics(k.unit, ords)))
        fig.layout[_y(r).replace("y", "yaxis", 1)].rangemode = "tozero"
    _draw_intervals(fig, intervals)
    if excerpt:
        fig.add_shape(type="rect", xref="x", yref="paper", x0=excerpt[0], x1=excerpt[1], y0=0, y1=1,
                      fillcolor="#111111", opacity=0.18, line_width=0)
    return fig


def _min_max_decimate(t: np.ndarray, x: np.ndarray, max_points: int):
    """For the display: at most ``max_points`` per channel (minimum and maximum per section – peaks are kept)."""
    n = len(t)
    if n <= max_points:
        return t, x
    q = int(math.ceil(2 * n / max_points)); m = n // q
    tb = t[: m * q].reshape(m, q); xb = x[: m * q].reshape(m, q, -1)
    lo, hi = np.nanmin(xb, axis=1), np.nanmax(xb, axis=1)
    tt = np.repeat(tb.mean(axis=1), 2)
    xx = np.empty((2 * m, x.shape[1])); xx[0::2] = lo; xx[1::2] = hi
    return tt, xx


def _read_instantaneous(rec, channels: Sequence[int], t0: float, t1: float, max_points: int, shift=None,
                        block: int = 1 << 20):
    """Instantaneous values for the display: short excerpts completely, long ones condensed block by block to the
    minimum/maximum per section (the memory stays small, peaks stay visible) → (t, X, condensed)."""
    i0 = max(0, int(round(t0 * rec.fs))); i1 = min(rec.n, int(round(t1 * rec.fs)))
    n = max(0, i1 - i0)
    if n <= max_points:
        return np.arange(i0, i1) / rec.fs, rec.read(i0, max(i1, i0 + 1), list(channels), shift), False
    q = int(math.ceil(2 * n / max_points))
    blk = max(q, (block // q) * q)
    tt, xx = [], []
    for a in range(i0, i1, blk):
        b = min(i1, a + blk)
        x = rec.read(a, b, list(channels), shift)
        m = (b - a) // q
        if m == 0:
            continue
        xb = x[: m * q].reshape(m, q, -1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            lo, hi = np.nanmin(xb, axis=1), np.nanmax(xb, axis=1)
        tm = (a + np.arange(m) * q + q / 2.0) / rec.fs
        z = np.empty((2 * m, x.shape[1])); z[0::2] = lo; z[1::2] = hi
        tt.append(np.repeat(tm, 2)); xx.append(z)
    return np.concatenate(tt), np.concatenate(xx), True


def instantaneous_figure(rec, roles, channels: Sequence[int], t0: float, t1: float, max_points: int = 12000,
                         height_per_panel: int = 210, title: Optional[str] = None, shift=None):
    """Instantaneous values in the excerpt [t0, t1], one panel per physical quantity on a common time axis.

    Long excerpts are condensed for the display to the minimum/maximum per section (peaks stay visible).

    Parameters
    ----------
    rec : Recording
        The recording.
    roles : RoleAssignment
        Channel roles (grouping and colours).
    channels : sequence of int
        Channel indices.
    t0, t1 : float
        Excerpt in s.
    max_points : int, optional
        Maximum number of points per channel.
    height_per_panel : int, optional
        Height of one panel in pixels.
    title : str, optional
        Figure title (default: excerpt and whether the display is condensed).
    shift : dict, optional
        Time offset per channel ``{index: Δn}`` (alignment).

    Returns
    -------
    plotly.graph_objects.Figure
    """
    go, _ = _go()
    channels = [int(k) for k in channels]
    groups = _groups(roles, channels)
    t, X, condensed = _read_instantaneous(rec, channels, max(0.0, t0), min(rec.duration_s, t1), max_points,
                                          shift)
    pos = {k: j for j, k in enumerate(channels)}; colors = _colors(roles)
    fig = _stack(list(groups) or [""], [_unit_label(ks, small=True) for ks in groups.values()] or [""],
                 height_per_panel, title or tr("explorer.instantaneous_title", t0=t0, t1=t1,
                                               condensed=tr("explorer.condensed") if condensed else ""),
                 t_format=".4f")
    for r, (g, ks) in enumerate(groups.items()):
        for k in ks:
            fig.add_trace(go.Scatter(x=t, y=X[:, pos[k.index]], mode="lines", name=k.short, legendgroup=k.short,
                                     line=dict(color=colors.get(k.index), width=1.2), yaxis=_y(r),
                                     hovertemplate="%%{fullData.name}: %%{y:,.4~r} %s<extra></extra>" % k.unit))
    return fig


def spectrum_figure(sp: pd.DataFrame, roles, max_order: int = 13, relative: bool = False,
                    height_per_panel: int = 230, title: Optional[str] = None):
    """Harmonics of an excerpt as grouped bars per order.

    One panel per unit (like the overview) or, with ``relative=True``, one panel in percent of the fundamental. The
    hover label shows the RMS value, the share of H1 and the angle.

    Parameters
    ----------
    sp : pandas.DataFrame
        Spectrum from [`excerpt_spectrum`][groundfault.explorer.excerpt_spectrum].
    roles : RoleAssignment
        Channel roles (grouping and colours).
    max_order : int, optional
        Highest order shown.
    relative : bool, optional
        Show the share of H1 in % instead of the RMS values.
    height_per_panel : int, optional
        Height of one panel in pixels.
    title : str, optional
        Figure title.

    Returns
    -------
    plotly.graph_objects.Figure
    """
    go, make_subplots = _go()
    sp = sp[sp["order"] <= max_order]
    colors = _colors(roles)
    chan = [int(k) for k in dict.fromkeys(sp["index"])]
    if relative:
        groups = {tr("explorer.share_of_fundamental"): chan}
    else:                                              # like the overview: one panel per physical quantity
        groups = {g: [k.index for k in ks] for g, ks in _groups(roles, chan).items()}
    n = max(1, len(groups))
    fig = make_subplots(rows=n, cols=1, shared_xaxes=True, vertical_spacing=0.08 if n < 4 else 0.04,
                        subplot_titles=list(groups) or [""])
    for r, (g, ks) in enumerate(groups.items(), start=1):
        for k in ks:
            s = sp[sp["index"] == k]; ki = roles.channels[k]
            y = s["share_H1_pct"] if relative else s["rms"]
            cd = np.column_stack([s["rms"], s["share_H1_pct"], s["angle_deg"], s["order"]])
            hover = tr("explorer.spectrum_hover", name="%{fullData.name}", order="%{customdata[3]:.0f}",
                       f="%{x:.1f}", value="%{customdata[0]:,.4~r}", unit=ki.unit, share="%{customdata[1]:.2f}",
                       angle="%{customdata[2]:.1f}")
            fig.add_trace(go.Bar(x=s["f_Hz"], y=y, name=ki.short, legendgroup=ki.short, marker_color=colors.get(k),
                                 customdata=cd, hovertemplate=hover + "<extra></extra>"),
                          row=r, col=1)
        fig.update_yaxes(title_text=tr("explorer.share_axis") if relative else _unit_label([roles.channels[ks[0]]]),
                         row=r, col=1)
    fig.update_xaxes(title_text=tr("explorer.axis", quantity="f", unit="Hz"), row=n, col=1)
    fig.update_layout(template=TEMPLATE, separators=_separators(), barmode="group", bargap=0.25,
                      height=height_per_panel * n + 110, hovermode="closest", margin=dict(t=60, b=40, l=70, r=20),
                      title=title or tr("explorer.spectrum_title"),
                      legend=dict(orientation="h", y=1.02, yanchor="bottom", x=1, xanchor="right"))
    return fig


# =========================================================================== notebook interface
def _table_columns() -> Dict[str, str]:
    """Column headers of [`excerpt_table`][groundfault.explorer.excerpt_table] in the notebook (active output
    language)."""
    return {"channel": tr("explorer.col_channel"), "role": tr("explorer.col_quantity"),
            "unit": tr("explorer.col_unit"), "rms": tr("explorer.col_rms"), "dc": tr("explorer.col_dc"),
            "peak": tr("explorer.col_peak"), "crest_factor": tr("explorer.col_crest_factor"),
            "H1_angle_deg": tr("explorer.col_h1_angle_deg"), "THD_pct": tr("explorer.col_thd")}


class SignalExplorer:
    """Signal explorer for the notebook.

    In a notebook, ``explorer(rec, res)`` as the last line of a cell shows the interactive interface
    ([`ui`][groundfault.explorer.SignalExplorer.ui]). Without the interface,
    [`overview`][groundfault.explorer.SignalExplorer.overview],
    [`instantaneous`][groundfault.explorer.SignalExplorer.instantaneous] and
    [`spectrum`][groundfault.explorer.SignalExplorer.spectrum] return Plotly figures,
    [`table`][groundfault.explorer.SignalExplorer.table] the characteristic values of an excerpt and ``kw`` the values
    of all windows.

    Parameters
    ----------
    rec : Recording
        The recording.
    res : Result, optional
        Evaluation result: roles, f1, analysis intervals, max window and alignment are taken from it.
    roles : RoleAssignment, optional
        Channel roles (default: those of ``res`` or detected from the channel names).
    channels : sequence of int, optional
        Channels shown by default (default: [`default_channels`][groundfault.explorer.default_channels]).
    T_win : float, optional
        Window length of the overview in s.
    T_hop : float, optional
        Hop of the overview in s (default ``T_win/2`` for recordings up to 180 s, otherwise ``T_win``).
    orders : iterable of int, optional
        Harmonic orders of the spectra.
    f1 : float, optional
        Fundamental frequency in Hz (default: from ``res`` or [`line_frequency`][groundfault.explorer.line_frequency]).
    alignment : dict, optional
        Time alignment of channels as in [`groundfault.evaluate`][groundfault.evaluation.evaluate] (default: the one
        stored in ``res``).

    Attributes
    ----------
    kw : WindowMetrics
        Characteristic values of all windows.
    times : dict
        Excerpts of [`event_times`][groundfault.explorer.event_times] (``{key: (t0, t1)}``).
    defaults : list of int
        Channels shown by default.
    shift : dict or None
        Time offset per channel in samples (alignment).
    """

    def __init__(self, rec, res=None, roles=None, channels=None, T_win: float = 0.2, T_hop: Optional[float] = None,
                 orders: Iterable[int] = range(1, 41), f1: Optional[float] = None,
                 alignment: Optional[dict] = None):
        self.rec, self.res = rec, res
        self.roles = roles or getattr(res, "roles", None) or detect_roles(rec.channel_names, rec.units)
        if f1 is None and res is not None and hasattr(res, "steady_state"):
            f1 = res.steady_state.f1["f1_used"]
        self.f1 = float(f1) if f1 else line_frequency(rec, self.roles)
        self.orders = [m for m in orders]
        self.shift = _shift_from(rec, self.roles, res, alignment)
        if T_hop is None:
            T_hop = T_win / 2 if rec.duration_s <= 180 else T_win
        self.kw = window_metrics(rec, None, T_win, T_hop, self.orders, self.f1, self.roles,
                                 shift=self.shift)
        self.intervals = getattr(res, "intervals", None)
        self.times = event_times(rec, self.roles, res, self.shift)
        all_ = [k.index for k in self.roles.channels]
        self.defaults = [int(k) for k in (channels if channels is not None else default_channels(self.roles))] or all_

    def _start(self) -> Tuple[float, float]:
        """Initial excerpt: max window, fault inception or 200 ms around the largest RMS value."""
        for n in ("max window", "fault inception"):
            if n in self.times:
                return self.times[n]
        j = int(np.nanargmax(np.nanmax(self.kw.rms, axis=1))) if np.isfinite(self.kw.rms).any() else 0
        tm = float(self.kw.t[j]); return (tm - 0.1, tm + 0.1)

    # ------------------------------------------------------------------ figures / tables
    def overview(self, channels=None, excerpt=None):
        """RMS value per window over time ([`overview_figure`][groundfault.explorer.overview_figure]) with the analysis
        intervals.

        Parameters
        ----------
        channels : sequence of int, optional
            Channels (default: ``defaults``).
        excerpt : tuple of float, optional
            Excerpt (t0, t1) in s, shaded grey.

        Returns
        -------
        plotly.graph_objects.Figure
        """
        return overview_figure(self.kw, self.roles, channels or self.defaults, self.intervals, excerpt)

    def instantaneous(self, t0: float, t1: float, channels=None):
        """Instantaneous values in the excerpt [t0, t1]
        ([`instantaneous_figure`][groundfault.explorer.instantaneous_figure]).

        Parameters
        ----------
        t0, t1 : float
            Excerpt in s.
        channels : sequence of int, optional
            Channels (default: ``defaults``).

        Returns
        -------
        plotly.graph_objects.Figure
        """
        return instantaneous_figure(self.rec, self.roles, channels or self.defaults, t0, t1,
                                    shift=self.shift)

    def spectrum(self, t0: float, t1: float, channels=None, max_order: int = 13, relative: bool = False):
        """Spectrum of the excerpt [t0, t1] ([`excerpt_spectrum`][groundfault.explorer.excerpt_spectrum],
        [`spectrum_figure`][groundfault.explorer.spectrum_figure]).

        Parameters
        ----------
        t0, t1 : float
            Excerpt in s.
        channels : sequence of int, optional
            Channels (default: ``defaults``); the first one is the angle reference.
        max_order : int, optional
            Highest order shown.
        relative : bool, optional
            Show the share of H1 in % instead of the RMS values.

        Returns
        -------
        plotly.graph_objects.Figure
        """
        sp = excerpt_spectrum(self.rec, channels or self.defaults, t0, t1, self.f1, self.orders, self.roles,
                              shift=self.shift)
        a, b = _limits(self.rec, t0, t1, self.f1)
        return spectrum_figure(sp, self.roles, max_order, relative,
                               title=tr("explorer.spectrum_title_range", t0=a, t1=b, f1=self.f1))

    def table(self, t0: float, t1: float, channels=None) -> pd.DataFrame:
        """Characteristic values per channel in the excerpt [t0, t1]
        ([`excerpt_table`][groundfault.explorer.excerpt_table]).

        Parameters
        ----------
        t0, t1 : float
            Excerpt in s.
        channels : sequence of int, optional
            Channels (default: ``defaults``); the first one is the angle reference.

        Returns
        -------
        pandas.DataFrame
        """
        return excerpt_table(self.rec, channels or self.defaults, t0, t1, self.f1, self.roles, self.orders,
                             shift=self.shift)

    # ------------------------------------------------------------------ interface (ipywidgets)
    def ui(self):
        """Interactive notebook interface (``ipywidgets``).

        Controls: channel selection, a slider for the excerpt, a list to jump to the excerpts of ``times``,
        the width of the excerpt, buttons that move it by its width, the highest order of the spectrum and the
        choice between RMS value and percent of H1. Below: overview, instantaneous values, spectrum and the table
        of characteristic values of the excerpt. Jumping to the max window selects exactly the window of the
        evaluation (same values as its tables).

        Returns
        -------
        ipywidgets.VBox
            The interface.

        Raises
        ------
        ImportError
            If ``ipywidgets`` or IPython is not installed.
        """
        import ipywidgets as W
        from IPython.display import HTML, clear_output, display
        rec, roles = self.rec, self.roles
        opts = [("%s · %s [%s]" % (k.short, role_description(k.role, "–"), k.unit), k.index)
                for k in roles.channels]
        w_chan = W.SelectMultiple(options=opts, value=tuple(self.defaults), rows=min(12, max(4, len(opts))),
                                  description=tr("explorer.label_channels"), layout=W.Layout(width="440px"))
        a, b = self._start()
        w_time = W.FloatRangeSlider(value=(round(a, 3), round(b, 3)), min=0.0, max=round(rec.duration_s, 3),
                                    step=0.005, description=tr("explorer.label_excerpt"), readout_format=".3f",
                                    continuous_update=False, layout=W.Layout(width="98%"))
        w_jump = W.Dropdown(options=[(tr("explorer.ui_jump_to"), None)] + [(_event_label(n), n) for n in self.times],
                            description=tr("explorer.ui_time"), layout=W.Layout(width="340px"))
        widths = ([(tr("explorer.ui_one_cycle"), 0.02)]
                  + [(tr("explorer.ui_cycles", n=n, t=t), t) for n, t in ((5, 0.1), (10, 0.2))]
                  + [(tr("explorer.ui_seconds", t=t), t) for t in (0.5, 1.0, 5.0, 10.0)])
        w_width = W.Dropdown(options=widths, value=0.2, description=tr("explorer.ui_width"),
                             layout=W.Layout(width="340px"))
        w_back = W.Button(description=tr("explorer.ui_back"), layout=W.Layout(width="110px"))
        w_forward = W.Button(description=tr("explorer.ui_forward"), layout=W.Layout(width="110px"))
        w_ord = W.IntSlider(value=13, min=3, max=max(self.orders), description=tr("explorer.label_max_order"),
                            continuous_update=False, layout=W.Layout(width="340px"))
        w_rel = W.ToggleButtons(options=[(tr("explorer.label_rms"), "rms"),
                                         (tr("explorer.label_relative"), "relative")],
                                value="rms", style={"button_width": "110px"})
        out_ovw, out_det, out_spk, out_tab = W.Output(), W.Output(), W.Output(), W.Output()
        lock = {"active": False}

        def channels():
            return list(w_chan.value) or [opts[0][1]]

        def draw_overview(*_):
            with out_ovw:
                clear_output(wait=True)
                display(self.overview(channels(), w_time.value))

        def draw_excerpt(*_):
            t0, t1 = w_time.value
            with out_det:
                clear_output(wait=True)
                display(self.instantaneous(t0, t1, channels()))
            with out_spk:
                clear_output(wait=True)
                display(self.spectrum(t0, t1, channels(), w_ord.value, w_rel.value == "relative"))
            with out_tab:
                clear_output(wait=True)
                tab = self.table(t0, t1, channels())
                lines = ["ℹ " + tab.attrs["note"]] if tab.attrs.get("note") else []
                lines.append(tr("explorer.ui_table_caption", t0=tab.attrs["t0"], t1=tab.attrs["t1"],
                                channel=tab["channel"].iloc[0]))
                display(HTML("<br>".join(_html.escape(s) for s in lines)))
                decimal, thousands = _separators()
                display(tab.rename(columns=_table_columns()).style
                        .format(precision=4, decimal=decimal, thousands=thousands, na_rep="–").hide(axis="index"))

        def redraw_all(*_):
            if not lock["active"]:
                draw_overview(); draw_excerpt()

        def set_excerpt(t0, t1):
            width = min(t1 - t0, rec.duration_s)          # keep the width, move the excerpt into the file
            if t0 < 0:
                t0, t1 = 0.0, width
            if t1 > rec.duration_s:
                t0, t1 = max(0.0, rec.duration_s - width), rec.duration_s
            t1 = max(t0 + 1.0 / rec.fs, t1)
            lock["active"] = True
            w_time.value = (round(t0, 3), round(t1, 3))
            lock["active"] = False
            redraw_all()

        def jump(change):
            if change["new"] is None:
                return
            t0, t1 = self.times[change["new"]]
            if change["new"] == "max window":            # exactly the window of the evaluation (same values)
                set_excerpt(t0, t1)
            else:
                m = 0.5 * (t0 + t1); width = w_width.value
                set_excerpt(m - width / 2, m + width / 2)

        def change_width(change):
            t0, t1 = w_time.value; m = 0.5 * (t0 + t1)
            set_excerpt(m - change["new"] / 2, m + change["new"] / 2)

        def step(forward):
            t0, t1 = w_time.value; d = (t1 - t0) * (1 if forward else -1)
            if t0 + d < 0 or t1 + d > rec.duration_s + 1e-9:
                return
            set_excerpt(t0 + d, t1 + d)

        w_chan.observe(redraw_all, "value"); w_time.observe(redraw_all, "value")
        w_ord.observe(draw_excerpt, "value"); w_rel.observe(draw_excerpt, "value")
        w_jump.observe(jump, "value"); w_width.observe(change_width, "value")
        w_back.on_click(lambda _: step(False)); w_forward.on_click(lambda _: step(True))
        redraw_all()
        help_ = W.HTML("<small>%s</small>" % _html.escape(tr("explorer.ui_help", window_ms=1000 * self.kw.T_win,
                                                             f1=self.f1)))
        control = W.VBox([w_jump, w_width, W.HBox([w_back, w_forward]), w_ord, w_rel])
        return W.VBox([W.HBox([w_chan, control]), help_, out_ovw, w_time, out_det, out_spk, out_tab])

    def _repr_mimebundle_(self, **kw):
        try:
            ui = self.ui()
        except ImportError:                            # without ipywidgets: at least the overview (with hover)
            warnings.warn(tr("explorer.ipywidgets_missing"))
            return self.overview()._repr_mimebundle_(**kw)
        return ui._repr_mimebundle_(**kw)

    def __repr__(self):
        return "<SignalExplorer %s | %d channels | %d windows of %g ms>" % (
            os.path.basename(self.rec.cfg_path), len(self.kw.channels), len(self.kw.t), 1000 * self.kw.T_win)


def _limits(rec, t0: float, t1: float, f1: float) -> Tuple[float, float]:
    """Time limits over which the spectrum and the characteristic values are actually computed (see
    ``_read_window``)."""
    if t1 - t0 < 2.0 / f1:
        m = 0.5 * (t0 + t1); t0, t1 = m - 5.0 / f1, m + 5.0 / f1
    elif t1 - t0 > MAX_SPECTRUM_S:
        m = 0.5 * (t0 + t1); t0, t1 = m - MAX_SPECTRUM_S / 2, m + MAX_SPECTRUM_S / 2
    return max(0.0, t0), min(rec.duration_s, t1)


def _shift_from(rec, roles, res=None, alignment: Optional[dict] = None):
    """Time offset per channel as in the evaluation: from ``alignment`` or the one stored in the result."""
    if alignment is None and res is not None:
        alignment = ((getattr(res, "result_set", None) or getattr(res, "data", None) or {})
                     .get("measurement", {}) or {}).get("alignment")
    if not alignment:
        return None
    from .evaluation import _shift
    return _shift(rec, roles, alignment)


def explorer(rec, res=None, **kw) -> SignalExplorer:
    """Signal explorer for the notebook (see [`SignalExplorer`][groundfault.explorer.SignalExplorer]).

    Parameters
    ----------
    rec : Recording
        The recording.
    res : Result, optional
        Evaluation result of the recording.
    **kw
        Further arguments of [`SignalExplorer`][groundfault.explorer.SignalExplorer].

    Returns
    -------
    SignalExplorer
        Shows the interactive interface as the last expression of a notebook cell.
    """
    return SignalExplorer(rec, res, **kw)


# =========================================================================== HTML without Python
def _round(a, digits: int = 4):
    """List with ``digits`` significant digits (compact JSON), NaN → None."""
    a = np.asarray(a, float)
    out = []
    for v in a.ravel():
        if not np.isfinite(v):
            out.append(None)
        elif v == 0:
            out.append(0)
        else:
            out.append(float("%.*g" % (digits, v)))
    return out


def _int16(x: np.ndarray) -> dict:
    """Instantaneous values as int16 (Base64) with scale and middle – quantisation error ≤ span/65535."""
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    if not ok.any():
        return dict(scale=0.0, middle=0.0, b64="")
    lo, hi = float(np.min(x[ok])), float(np.max(x[ok]))
    middle = 0.5 * (lo + hi); scale = max((hi - lo) / 65000.0, 1e-12)
    q = np.round((np.where(ok, x, middle) - middle) / scale).astype("<i2")
    return dict(scale=scale, middle=middle, b64=base64.b64encode(q.tobytes()).decode("ascii"))


def _excerpt_data(rec, channels, t0, t1, f1, fs_max, orders, roles, shift=None):
    """Data of one excerpt for the HTML page: instantaneous values (low-pass decimated to at most ``fs_max``,
    int16), spectrum without angle reference and the values of [`excerpt_table`][groundfault.explorer.excerpt_table]."""
    from scipy import signal as sig
    q = max(1, int(math.ceil(rec.fs / fs_max)))
    edge = 0.02 if q > 1 else 0.0
    i0 = int(round(max(0.0, t0 - edge) * rec.fs)); i1 = int(round(min(rec.duration_s, t1 + edge) * rec.fs))
    t, x = np.arange(i0, i1) / rec.fs, rec.read(i0, i1, list(channels), shift)
    x = np.where(np.isfinite(x), x, 0.0)
    if q > 1:
        x = sig.decimate(x, q, ftype="fir", axis=0, zero_phase=True)
        t = t[::q][: len(x)]
    m = (t >= t0 - 0.5 / rec.fs) & (t <= t1)
    t, x = t[m], x[m]
    sp = excerpt_spectrum(rec, channels, t0, t1, f1, orders, roles, raw=True, shift=shift)
    tab = excerpt_table(rec, channels, t0, t1, f1, roles, orders, shift=shift)
    spectrum = dict(orders=[int(o) for o in sorted(sp["order"].unique())],
                    magnitude=[_round(sp[sp["index"] == k]["rms"]) for k in channels],
                    angle=[_round(sp[sp["index"] == k]["angle_deg"], 4) for k in channels])
    values = [[(None if not np.isfinite(v) else float("%.5g" % v)) for v in
               tab.loc[j, ["rms", "dc", "peak", "crest_factor", "H1", "H1_angle_deg",
                           "H3", "H5", "H7", "THD_pct"]].astype(float)] for j in range(len(channels))]
    return dict(t0=float(t[0]) if len(t) else t0, fs=rec.fs / q, n=int(len(t)),
                data=[_int16(x[:, j]) for j in range(len(channels))], spectrum=spectrum, values=values)


def _script_template(key: str, *fields: str) -> str:
    """Message ``key`` with its fields kept as ``{field}`` placeholders (filled in by the page script)."""
    return tr(key, **{f: "{%s}" % f for f in fields})


def _script_texts() -> Dict[str, object]:
    """Texts used by the page script, in the active output language (key ``text`` of the page data)."""
    return dict(
        meta_measurement=_script_template("explorer.meta_measurement", "name"),
        meta_start=_script_template("explorer.meta_start", "start"),
        meta_sampling_rate=_script_template("explorer.meta_sampling_rate", "fs"),
        meta_duration=_script_template("explorer.meta_duration", "duration"),
        meta_channels=_script_template("explorer.meta_channels", "n"),
        axis=_script_template("explorer.axis", "quantity", "unit"),
        rms_subscript=tr("explorer.rms_subscript"),
        excerpts=tr("explorer.excerpts"),
        excerpt_hover=_script_template("explorer.excerpt_hover", "name"),
        excerpt_title=_script_template("explorer.excerpt_title", "name", "t0", "t1"),
        share_of_fundamental=tr("explorer.share_of_fundamental"),
        share_axis=tr("explorer.share_axis"),
        spectrum_hover=_script_template("explorer.spectrum_hover", "name", "order", "f", "value", "unit", "share",
                                        "angle"),
        table_head=[tr("explorer.col_channel"), tr("explorer.col_quantity"), tr("explorer.col_unit"),
                    tr("explorer.col_rms"), tr("explorer.col_dc"), tr("explorer.col_peak"),
                    tr("explorer.col_crest_factor"), "H1", tr("explorer.col_h1_angle"), "H3", "H5", "H7",
                    tr("explorer.col_thd")],
    )


def _page_texts(window_ms: float, f1: float, fs_max: float, created: str) -> Dict[str, str]:
    """Static texts of the HTML page (placeholders ``@@name@@`` of ``_HTML``) in the active output language.

    Plain texts are HTML-escaped; the overview help and the footer are catalog texts with markup (``<b>``,
    ``<code>``, ``<sub>``)."""
    def text(key, **values):
        return _html.escape(tr(key, **values), quote=False)
    return dict(
        all=text("explorer.html_all"), none=text("explorer.html_none"), default=text("explorer.html_default"),
        excerpt=text("explorer.label_excerpt"), spectrum=text("explorer.label_spectrum"),
        rms=text("explorer.label_rms"), relative=text("explorer.label_relative"),
        max_order=text("explorer.label_max_order"), rms_over_time=text("explorer.html_rms_over_time"),
        overview_help=tr("explorer.html_overview_help"), no_channels=text("explorer.html_no_channels"),
        instantaneous_heading=text("explorer.html_instantaneous_heading"),
        spectrum_heading=text("explorer.html_spectrum_heading"),
        envelope_summary=text("explorer.html_envelope_summary"),
        footer=tr("explorer.html_footer", window_ms=window_ms, f1=f1, fs_max_khz=fs_max / 1000.0),
        created=text("explorer.html_created", date=created))


def explorer_html(rec, path: str, res=None, roles=None, channels=None, T_win: float = 0.2,
                  hover_orders: Sequence[int] = (1, 2, 3, 5, 7, 9, 11, 13),
                  spectrum_orders: Iterable[int] = range(1, 41), n_uniform: int = 40, fs_max: float = 10000.0,
                  max_bytes: float = 3.0e6, title: Optional[str] = None, plotly_js: str = "inline",
                  figures: Optional[Dict[str, object]] = None, alignment: Optional[dict] = None) -> str:
    """Write the signal explorer as one HTML file that opens in a browser without Python.

    The page contains the RMS trend of all channels with harmonics, THD and DC component on hover, the envelope of the
    instantaneous values and – for selected excerpts of 200 ms each (a click into the overview selects the nearest one)
    – the instantaneous values, the spectrum and the characteristic values. The excerpts are the events of
    [`event_times`][groundfault.explorer.event_times] (marked ★) and excerpts spread evenly over the recording. All
    texts are written in the output language that is active when the function is called.

    Parameters
    ----------
    rec : Recording
        The recording.
    path : str
        Output file (missing folders are created).
    res : Result, optional
        Evaluation result: f1, roles, analysis intervals, max window and alignment are taken from it.
    roles : RoleAssignment, optional
        Channel roles (default: those of ``res`` or detected from the channel names).
    channels : sequence of int, optional
        Channels included in the file (default: all).
    T_win : float, optional
        Window length of the RMS trend in s.
    hover_orders : sequence of int, optional
        Harmonic orders shown on hover in the overview.
    spectrum_orders : iterable of int, optional
        Orders of the spectra of the excerpts; the THD of the overview is computed over the same orders.
    n_uniform : int, optional
        Number of excerpts spread evenly over the recording (fewer if the stored instantaneous values would
        exceed ``max_bytes``).
    fs_max : float, optional
        Highest sampling rate of the stored instantaneous values in Hz (decimation with low-pass filter).
    max_bytes : float, optional
        Approximate size limit of the stored instantaneous values in bytes.
    title : str, optional
        Page title (default: "Signal explorer – <file name>").
    plotly_js : {"inline", "cdn"}, optional
        ``"inline"`` embeds plotly.js (readable offline, about 5 MB larger), ``"cdn"`` loads it from the internet.
    figures : dict, optional
        Further Plotly figures ``{heading: figure}`` shown at the end of the page (e.g. the frequency-selective
        station evaluation or the comparison with the earthing measurement).
    alignment : dict, optional
        Time alignment of channels as in [`groundfault.evaluate`][groundfault.evaluation.evaluate] (default: the one
        stored in ``res``).

    Returns
    -------
    str
        ``path``.
    """
    roles = roles or getattr(res, "roles", None) or detect_roles(rec.channel_names, rec.units)
    f1 = res.steady_state.f1["f1_used"] if (res is not None and hasattr(res, "steady_state")) else \
        line_frequency(rec, roles)
    idx = [k.index for k in roles.channels] if channels is None else [int(k) for k in channels]
    shift_ = _shift_from(rec, roles, res, alignment)
    T_hop = T_win if rec.duration_s > 60 else T_win / 2
    # THD over all orders up to 40 (like the characteristic values of the excerpts); only the hover orders are stored
    kw = window_metrics(rec, idx, T_win, T_hop, sorted(set(spectrum_orders) | set(hover_orders) | {1}), f1, roles,
                        shift=shift_)
    thd = kw.thd
    i_hover = [list(kw.orders).index(m) for m in hover_orders if m in kw.orders]
    # ---- excerpts: important instants + evenly spread (size limited)
    important = event_times(rec, roles, res, shift_)
    n_samples = int(round(0.2 * min(rec.fs, fs_max)))
    n_max = max(len(important) + 4, int(max_bytes // max(1, 2 * n_samples * len(idx))))
    n_eq = max(0, min(n_uniform, n_max - len(important)))
    uniform = {}
    if n_eq:
        d = rec.duration_s / n_eq
        for i in range(n_eq):
            m = (i + 0.5) * d
            uniform[tr("explorer.excerpt_at", t=m)] = (max(0.0, m - 0.1), min(rec.duration_s, m + 0.1))
    all_ = sorted([(key, _event_label(key), span) for key, span in important.items()]
                  + [(None, label, span) for label, span in uniform.items()], key=lambda x: x[2][0])
    colors = _colors(roles)
    groups = _groups(roles, idx)
    chan = []
    for g, ks in groups.items():
        for k in ks:
            chan.append(dict(i=k.index, column=idx.index(k.index), short=k.short, name=k.name, unit=k.unit,
                             role=k.role, role_text=role_description(k.role, "–"), group=g,
                             color=colors.get(k.index, "#555555"), distance=k.distance_m))
    defaults = [k for k in default_channels(roles) if k in idx] or idx[:6]
    t_h, X_h, condensed = _read_instantaneous(rec, idx, 0.0, rec.duration_s, 5000, shift_)
    if condensed:
        t_h, lo, hi = t_h[0::2], X_h[0::2], X_h[1::2]
    else:
        lo = hi = X_h
    excerpts = []
    for key, label, (a, b) in all_:
        d = _excerpt_data(rec, idx, a, b, f1, fs_max, list(spectrum_orders), roles, shift_)
        d.update(key=key, label=label, important=key is not None, t_mid=0.5 * (a + b), t_begin=a, t_end=b)
        excerpts.append(d)
    info = rec.info()
    lang = i18n.get_language()
    created = _dt.datetime.now().strftime(tr("explorer.date_format"))
    data = dict(
        title=title or tr("explorer.html_title", file=info["file"]),
        file=info["file"], start=info.get("start"), fs=rec.fs, duration=rec.duration_s,
        station=None if str(info.get("station") or "").lower() in ("", info["file"].lower()) else info.get("station"),
        f1=f1, T_win=kw.T_win, T_hop=kw.T_hop, created=created,
        measurement=getattr(res, "name", None), channels=chan, groups=list(groups), defaults=defaults,
        intervals={n: list(getattr(res.intervals, n)) for n in ("pre_fault", "steady_state", "post_fault")
                   if res is not None and getattr(res, "intervals", None) is not None and getattr(res.intervals, n)},
        interval_colors=dict(INTERVAL_COLORS),
        overview=dict(t=_round(kw.t, 6), orders=[int(kw.orders[i]) for i in i_hover],
                      rms=[_round(kw.rms[:, j]) for j in range(len(idx))],
                      H=[[_round(np.abs(kw.X[:, j, i])) for i in i_hover] for j in range(len(idx))],
                      thd=[_round(100 * thd[:, j], 3) for j in range(len(idx))],
                      dc=[_round(kw.dc[:, j]) for j in range(len(idx))]),
        envelope=dict(t=_round(t_h, 6), lo=[_round(lo[:, j]) for j in range(len(idx))],
                      hi=[_round(hi[:, j]) for j in range(len(idx))]),
        excerpts=excerpts,
        figures=[dict(title=t, fig=json.loads(f.to_json())) for t, f in (figures or {}).items()
                 if f is not None],
        lang=lang, locale=_LOCALES[lang], separators=_separators(), text=_script_texts(),
    )
    if plotly_js == "cdn":
        from plotly.offline import get_plotlyjs_version
        script = ('<script src="https://cdn.plot.ly/plotly-%s.min.js" charset="utf-8"></script>'
                  % get_plotlyjs_version())
    else:
        from plotly.offline import get_plotlyjs
        script = "<script>%s</script>" % get_plotlyjs()
    texts = _page_texts(window_ms=1000 * kw.T_win, f1=f1, fs_max=fs_max, created=created)
    values = {"__TITLE__": _html.escape(data["title"]), "__LANG__": lang, "__PLOTLY__": script,
              "__DATA__": json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")}
    page = _PLACEHOLDER.sub(lambda m: texts[m.group(1)] if m.group(1) else values[m.group(0)], _HTML)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    return path


#: placeholders of :data:`_HTML` – ``__TITLE__``, ``__LANG__``, ``__PLOTLY__``, ``__DATA__`` and texts ``@@name@@``
#: (replaced in one pass, so inserted content is never scanned again)
_PLACEHOLDER = re.compile(r"__(?:TITLE|LANG|PLOTLY|DATA)__|@@(\w+)@@")

_HTML = r"""<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root { --text:#1d1d1f; --text2:#55565b; --border:#d9d9de; --surface:#ffffff; --background:#f6f6f8; --accent:#2a78d6; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --text:#ececf0; --text2:#a8a9b0; --border:#3a3b40; --surface:#1c1c1f; --background:#141416; --accent:#6aa6ff; } }
:root[data-theme="dark"] { --text:#ececf0; --text2:#a8a9b0; --border:#3a3b40; --surface:#1c1c1f; --background:#141416;
  --accent:#6aa6ff; }
* { box-sizing: border-box; }
body { margin:0; font: 14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color:var(--text);
  background:var(--background); }
header, main, footer { max-width: 1280px; margin: 0 auto; padding: 0 16px; }
header { padding-top: 18px; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 22px 0 6px; }
.meta { color: var(--text2); font-size: 13px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; margin: 10px 0; }
.bar { display:flex; flex-wrap: wrap; gap: 8px 18px; align-items: center; }
.group { display:flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; }
.group b { font-size: 12px; color: var(--text2); font-weight: 600; margin-right: 4px; }
label { cursor: pointer; white-space: nowrap; }
.swatch { display:inline-block; width: 10px; height: 10px; border-radius: 2px; margin: 0 4px 0 2px; vertical-align: -1px; }
select, button { font: inherit; color: var(--text); background: var(--surface); border: 1px solid var(--border);
  border-radius: 6px; padding: 3px 8px; max-width: 100%; }
@media (max-width: 640px) { label { white-space: normal; } #excerpt { width: 100%; } }
button { cursor: pointer; }
.plot { width: 100%; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; font-size: 13px; }
th, td { border-bottom: 1px solid var(--border); padding: 4px 6px; text-align: right; white-space: nowrap; }
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
.table-wrap { overflow-x: auto; }
details > summary { cursor: pointer; color: var(--accent); }
footer { color: var(--text2); font-size: 12.5px; padding-bottom: 30px; }
</style>
__PLOTLY__
</head>
<body>
<header>
  <h1 id="heading"></h1>
  <div class="meta" id="meta"></div>
</header>
<main>
  <div class="card">
    <div class="bar" id="channel-picker"></div>
    <div class="bar" style="margin-top:8px">
      <span><button id="all">@@all@@</button> <button id="none">@@none@@</button> <button id="defaults">@@default@@</button></span>
      <label>@@excerpt@@ <select id="excerpt"></select></label>
      <span><button id="previous">◀</button> <button id="next">▶</button></span>
      <label>@@spectrum@@ <select id="mode"><option value="abs">@@rms@@</option>
        <option value="rel">@@relative@@</option></select></label>
      <label>@@max_order@@ <select id="max-order"></select></label>
    </div>
  </div>
  <h2>@@rms_over_time@@</h2>
  <div class="meta">@@overview_help@@</div>
  <div class="card"><div id="empty" class="meta" style="display:none">@@no_channels@@</div><div id="overview" class="plot"></div></div>
  <h2 id="excerpt-title">@@instantaneous_heading@@</h2>
  <div class="card"><div id="instantaneous" class="plot"></div></div>
  <h2>@@spectrum_heading@@</h2>
  <div class="card"><div id="spectrum" class="plot"></div></div>
  <div class="card table-wrap"><table id="table"></table></div>
  <details class="card"><summary>@@envelope_summary@@</summary>
    <div id="envelope" class="plot"></div></details>
  <div id="more"></div>
</main>
<footer>
  <p>@@footer@@</p>
  <p>@@created@@</p>
</footer>
<script id="data" type="application/json">__DATA__</script>
<script>
(function () {
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const X = D.text;                                  // texts in the language of the page
const dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
const T = dark ? {paper: "#1c1c1f", text: "#ececf0", grid: "#34353a", axis: "#6b6c72"} :
                 {paper: "#ffffff", text: "#1d1d1f", grid: "#e6e6ea", axis: "#9a9ba1"};
const fmt = (s, v) => s.replace(/\{(\w+)\}/g, (m, key) => (key in v ? v[key] : m));   // fill {field} placeholders
const num = (v, digits) => (v === null || v === undefined || !isFinite(v)) ? "–" :
  Number(v).toLocaleString(D.locale, {maximumSignificantDigits: digits || 4});
const angleText = v => (v === null || v === undefined || !isFinite(v)) ? "–" :
  (Math.abs(v) < 0.05 ? 0 : v).toLocaleString(D.locale, {minimumFractionDigits: 1, maximumFractionDigits: 1}) + "°";
const axisTitle = (quantity, unit) => fmt(X.axis, {quantity: quantity, unit: unit});
const channels = D.channels;
let visible = new Set(D.defaults);
let current = Math.max(0, D.excerpts.findIndex(a => a.key === "max window"));
if (current === 0 && D.excerpts.length && D.excerpts[0].key !== "max window") {
  const inception = D.excerpts.findIndex(a => a.key === "fault inception"); if (inception >= 0) current = inception; }
const cache = {};

document.getElementById("heading").textContent = D.title;
document.getElementById("meta").textContent = [D.measurement ? fmt(X.meta_measurement, {name: D.measurement}) : null,
  D.station, D.start ? fmt(X.meta_start, {start: D.start.replace("T", " ")}) : null,
  fmt(X.meta_sampling_rate, {fs: num(D.fs, 6)}), fmt(X.meta_duration, {duration: num(D.duration, 4)}),
  fmt(X.meta_channels, {n: channels.length}), "f1 = " + num(D.f1, 6) + " Hz"].filter(Boolean).join(" · ");

// ---------------------------------------------------------------- controls
const picker = document.getElementById("channel-picker");
D.groups.forEach(g => {
  const div = document.createElement("div"); div.className = "group";
  const b = document.createElement("b"); b.textContent = g; div.appendChild(b);
  channels.filter(k => k.group === g).forEach(k => {
    const l = document.createElement("label"); l.title = k.name + " – " + k.role_text;
    const c = document.createElement("input"); c.type = "checkbox"; c.value = k.i; c.checked = visible.has(k.i);
    c.addEventListener("change", () => { if (c.checked) visible.add(k.i); else visible.delete(k.i); redrawAll(); });
    const sw = document.createElement("span"); sw.className = "swatch"; sw.style.background = k.color;
    l.appendChild(c); l.appendChild(sw); l.appendChild(document.createTextNode(k.short + " [" + k.unit + "]"));
    div.appendChild(l);
  });
  picker.appendChild(div);
});
function syncCheckboxes() { picker.querySelectorAll("input").forEach(c => c.checked = visible.has(+c.value)); }
document.getElementById("all").onclick = () => { visible = new Set(channels.map(k => k.i)); syncCheckboxes(); redrawAll(); };
document.getElementById("none").onclick = () => { visible = new Set(); syncCheckboxes(); redrawAll(); };
document.getElementById("defaults").onclick = () => { visible = new Set(D.defaults); syncCheckboxes(); redrawAll(); };
const excerptSelect = document.getElementById("excerpt");
D.excerpts.forEach((a, j) => { const o = document.createElement("option"); o.value = j;
  o.textContent = (a.important ? "★ " : "") + a.label + " (" + num(a.t_begin, 5) + " … " + num(a.t_end, 5) + " s)";
  excerptSelect.appendChild(o); });
excerptSelect.onchange = () => { current = +excerptSelect.value; showExcerpt(); markExcerpt(); };
document.getElementById("previous").onclick = () => { if (current > 0) { current--; showExcerpt(); markExcerpt(); } };
document.getElementById("next").onclick = () => {
  if (current < D.excerpts.length - 1) { current++; showExcerpt(); markExcerpt(); } };
const maxOrder = document.getElementById("max-order");
[7, 13, 25, 40].forEach(m => { const o = document.createElement("option"); o.value = m; o.textContent = m;
  if (m === 13) o.selected = true; maxOrder.appendChild(o); });
maxOrder.onchange = drawSpectrum; document.getElementById("mode").onchange = drawSpectrum;

// ---------------------------------------------------------------- helpers
function selectedChannels() { return channels.filter(k => visible.has(k.i)); }
function grouped(ks) { const g = {}; ks.forEach(k => (g[k.group] = g[k.group] || []).push(k));
  return D.groups.filter(n => g[n]).map(n => [n, g[n]]); }
function quantitySymbol(k) { return (k.unit || "").toUpperCase().indexOf("V") === 0 ? "U" :
  (k.unit || "").toUpperCase().indexOf("A") === 0 ? "I" : "x"; }
function stackLayout(n, height, groups, ytitles, topFree) {
  const L = {height: height * Math.max(1, n) + 90, margin: {t: 34, r: 16, b: 46, l: 70}, paper_bgcolor: T.paper,
    plot_bgcolor: T.paper, font: {color: T.text, size: 12}, separators: D.separators, hovermode: "x unified",
    hoversubplots: "axis",
    showlegend: true, legend: {orientation: "h", y: 1.02, yanchor: "bottom", x: 1, xanchor: "right"},
    xaxis: {title: {text: axisTitle("t", "s")}, gridcolor: T.grid, linecolor: T.axis, zeroline: false,
      anchor: "y" + (n > 1 ? n : ""), unifiedhovertitle: {text: "t = %{x:.4f} s"}},
    annotations: [], shapes: []};
  const top = 1 - (topFree || 0), gap = 0.07 * top, h = (top - gap * (n - 1)) / Math.max(1, n);
  for (let r = 0; r < n; r++) {
    const upper = top - r * (h + gap), lower = upper - h, ax = "yaxis" + (r ? r + 1 : "");
    L[ax] = {domain: [Math.max(0, lower), upper], title: {text: ytitles[r]}, gridcolor: T.grid, linecolor: T.axis,
      zeroline: false, rangemode: "tozero", anchor: "x"};
    L.annotations.push({text: "<b>" + groups[r] + "</b>", xref: "paper", yref: "paper", x: 0, y: upper,
      xanchor: "left", yanchor: "bottom", showarrow: false, font: {size: 12, color: T.text}});
  }
  return L;
}

// ---------------------------------------------------------------- overview (RMS values)
function drawOverview() {
  const g = grouped(selectedChannels()), O = D.overview, n = g.length, traces = [];
  const ytitles = g.map(([name, ks]) => axisTitle(quantitySymbol(ks[0]) + "<sub>" + X.rms_subscript + "</sub>",
    ks[0].unit));
  g.forEach(([name, ks], r) => ks.forEach(k => {
    const j = k.column, cd = O.t.map((_, w) => O.orders.map((m, i) => O.H[j][i][w]).concat([O.thd[j][w], O.dc[j][w]]));
    const parts = ["%{fullData.name}: <b>%{y:,.4~r} " + k.unit + "</b>"];
    O.orders.forEach((m, i) => parts.push("H" + m + " %{customdata[" + i + "]:,.3~r}"));
    parts.push("THD %{customdata[" + O.orders.length + "]:.1f} %");
    parts.push("DC %{customdata[" + (O.orders.length + 1) + "]:,.3~r}");
    traces.push({type: "scatter", mode: "lines", x: O.t, y: O.rms[j], name: k.short, legendgroup: k.short,
      line: {color: k.color, width: 1.4}, yaxis: "y" + (r ? r + 1 : ""), customdata: cd,
      hovertemplate: parts.join(" · ") + "<extra></extra>"});
  }));
  if (n) {   // markers of the available excerpts
    traces.push({type: "scatter", mode: "markers", x: D.excerpts.map(a => a.t_mid),
      y: D.excerpts.map(() => 1), yaxis: "y", name: X.excerpts, showlegend: false,
      marker: {symbol: "triangle-down", size: 9, color: D.excerpts.map(a => a.important ? "#e34948" : T.axis)},
      text: D.excerpts.map(a => a.label), hovertemplate: fmt(X.excerpt_hover, {name: "%{text}"}) + "<extra></extra>"});
    // y = 1 on an extra axis → at the top edge (paper coordinates)
    traces[traces.length - 1].yaxis = "y" + (n + 1);
  }
  const L = stackLayout(n, 200, g.map(x => x[0]), ytitles, 0.05);
  L.xaxis.unifiedhovertitle = {text: "t = %{x:.2f} s"};
  L["yaxis" + (n + 1)] = {domain: [0.965, 1], range: [0, 2], visible: false, fixedrange: true};
  Object.keys(D.intervals || {}).forEach(name => { const v = D.intervals[name];
    L.shapes.push({type: "rect", xref: "x", yref: "paper", x0: v[0], x1: v[1], y0: 0, y1: 1,
      fillcolor: D.interval_colors[name], opacity: 0.28, line: {width: 0}, layer: "below"}); });
  const div = document.getElementById("overview");
  document.getElementById("empty").style.display = n ? "none" : "block";
  if (!n) { Plotly.purge(div); div._clickBound = false; return; }
  Plotly.react(div, traces, L, {responsive: true, displaylogo: false});
  markExcerpt();
  if (!div._clickBound) { div._clickBound = true; div.on("plotly_click", ev => {
    const t = ev.points[0].x; let best = 0, dist = Infinity;
    D.excerpts.forEach((a, j) => { const dd = Math.abs(a.t_mid - t); if (dd < dist) { dist = dd; best = j; } });
    current = best; showExcerpt(); markExcerpt(); }); }
}
function markExcerpt() {
  const div = document.getElementById("overview"); if (!div.layout) return;
  const a = D.excerpts[current];
  const shapes = (div.layout.shapes || []).filter(s => s.name !== "excerpt");
  if (a) shapes.push({name: "excerpt", type: "rect", xref: "x", yref: "paper", x0: a.t_begin, x1: a.t_end,
    y0: 0, y1: 1, fillcolor: dark ? "#ffffff" : "#111111", opacity: 0.22, line: {width: 1, color: "#e34948"}});
  Plotly.relayout(div, {shapes: shapes});
  excerptSelect.value = current;
}

// ---------------------------------------------------------------- excerpt: instantaneous values
function samples(a, j) {
  const key = current + ":" + j; if (cache[key]) return cache[key];
  const enc = a.data[j]; if (!enc || !enc.b64) return (cache[key] = new Float32Array(0));
  const bin = atob(enc.b64), n = bin.length >> 1, v = new Float32Array(n);
  for (let i = 0; i < n; i++) { let x = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8);
    if (x >= 32768) x -= 65536; v[i] = x * enc.scale + enc.middle; }
  return (cache[key] = v);
}
function showExcerpt() {
  const a = D.excerpts[current]; if (!a) return;
  document.getElementById("excerpt-title").textContent = fmt(X.excerpt_title,
    {name: a.label, t0: num(a.t_begin, 5), t1: num(a.t_end, 5)});
  const g = grouped(selectedChannels()), n = g.length, traces = [];
  const t = Array.from({length: a.n}, (_, i) => a.t0 + i / a.fs);
  g.forEach(([name, ks], r) => ks.forEach(k => {
    traces.push({type: "scatter", mode: "lines", x: t, y: Array.from(samples(a, k.column)), name: k.short,
      legendgroup: k.short, line: {color: k.color, width: 1.3}, yaxis: "y" + (r ? r + 1 : ""),
      hovertemplate: "%{fullData.name}: %{y:,.4~r} " + k.unit + "<extra></extra>"}); }));
  const L = stackLayout(n, 200, g.map(x => x[0]),
    g.map(([name, ks]) => axisTitle(quantitySymbol(ks[0]).toLowerCase(), ks[0].unit)));
  for (let r = 0; r < n; r++) L["yaxis" + (r ? r + 1 : "")].rangemode = "normal";
  const div = document.getElementById("instantaneous");
  if (!n) {                                  // no channels: clear the excerpt, the spectrum and the table
    Plotly.purge(div); Plotly.purge(document.getElementById("spectrum"));
    document.getElementById("table").innerHTML = ""; return; }
  Plotly.react(div, traces, L, {responsive: true, displaylogo: false});
  drawSpectrum(); drawTable();
}

// ---------------------------------------------------------------- spectrum and table
function drawSpectrum() {
  const a = D.excerpts[current]; if (!a) return;
  const rel = document.getElementById("mode").value === "rel", highest = +maxOrder.value;
  const ks = selectedChannels(), S = a.spectrum, idx = S.orders.map((m, i) => [m, i]).filter(([m]) => m <= highest);
  const g = rel ? [[X.share_of_fundamental, ks]] : grouped(ks);
  const traces = [], phi1 = ks.length ? S.angle[ks[0].column][0] : 0;   // reference: H1 of the first selected channel
  ks.forEach(k => {
    const j = k.column, b = S.magnitude[j], h1 = b[0];
    const w = S.angle[j].map((x, i) => referredAngle(x, S.orders[i], phi1));
    const r = rel ? 0 : g.findIndex(x => x[0] === k.group);
    traces.push({type: "bar", x: idx.map(([m]) => m * D.f1), name: k.short, legendgroup: k.short,
      y: idx.map(([m, i]) => rel ? (h1 > 0 ? 100 * b[i] / h1 : null) : b[i]), marker: {color: k.color},
      yaxis: "y" + (r ? r + 1 : ""),
      customdata: idx.map(([m, i]) => [m, b[i], h1 > 0 ? 100 * b[i] / h1 : null, w[i]]),
      hovertemplate: fmt(X.spectrum_hover, {name: "%{fullData.name}", order: "%{customdata[0]}", f: "%{x:.1f}",
        value: "%{customdata[1]:,.4~r}", unit: k.unit, share: "%{customdata[2]:.2f}", angle: "%{customdata[3]:.1f}"})
        + "<extra></extra>"});
  });
  const L = stackLayout(g.length, 200, g.map(x => x[0]),
    g.map(([name, kk]) => rel ? X.share_axis : axisTitle(quantitySymbol(kk[0]), kk[0].unit)));
  L.xaxis.title.text = axisTitle("f", "Hz"); L.barmode = "group"; L.bargap = 0.25; L.hovermode = "closest";
  const div = document.getElementById("spectrum");
  if (!ks.length) { Plotly.purge(div); return; }
  Plotly.react(div, traces, L, {responsive: true, displaylogo: false});
}
function referredAngle(x, m, phi1) {       // φ_m − m·φ_1,ref brought to −180 … 180°
  if (x === null || phi1 === null) return null;
  let w = (x - m * phi1) % 360; if (w > 180) w -= 360; if (w <= -180) w += 360; return w;
}
function drawTable() {
  const a = D.excerpts[current], S = a.spectrum, ks = selectedChannels(), table = document.getElementById("table");
  const phi1 = ks.length ? S.angle[ks[0].column][0] : 0;
  let s = "<thead><tr>" + X.table_head.map(h => "<th>" + h + "</th>").join("") + "</tr></thead><tbody>";
  ks.forEach(k => { const v = a.values[k.column].slice(); v[5] = referredAngle(S.angle[k.column][0], 1, phi1);
    s += "<tr><td><span class='swatch' style='background:" + k.color + "'></span>" + k.short + "</td><td>" +
      k.role_text + "</td><td>" + k.unit + "</td>" + v.map((x, i) => "<td>" + (i === 5 ? angleText(x) :
      num(x, 4)) + "</td>").join("") + "</tr>"; });
  table.innerHTML = s + "</tbody>";
}

// ---------------------------------------------------------------- envelope
let envelopeDrawn = false;
function drawEnvelope() {
  const g = grouped(selectedChannels()), E = D.envelope, n = g.length, traces = [];
  g.forEach(([name, ks], r) => ks.forEach(k => {
    const j = k.column;
    traces.push({type: "scatter", mode: "lines", x: E.t.concat(E.t.slice().reverse()),
      y: E.hi[j].concat(E.lo[j].slice().reverse()), fill: "toself", name: k.short, legendgroup: k.short,
      line: {color: k.color, width: 0.6}, fillcolor: k.color + "55", hoverinfo: "skip", yaxis: "y" + (r ? r + 1 : "")});
  }));
  const L = stackLayout(n, 170, g.map(x => x[0]),
    g.map(([name, ks]) => axisTitle(quantitySymbol(ks[0]).toLowerCase(), ks[0].unit)));
  for (let r = 0; r < n; r++) L["yaxis" + (r ? r + 1 : "")].rangemode = "normal";
  L.hovermode = false;
  const div = document.getElementById("envelope");
  if (!n) { Plotly.purge(div); return; }
  Plotly.react(div, traces, L, {responsive: true, displaylogo: false});
}
document.querySelector("details").addEventListener("toggle", ev => {
  if (ev.target.open) { drawEnvelope(); envelopeDrawn = true; } });

function redrawAll() { drawOverview(); showExcerpt(); if (envelopeDrawn) drawEnvelope(); }
redrawAll();
(D.figures || []).forEach(f => {      // further figures of the evaluation (station, earthing measurement …)
  const more = document.getElementById("more"), h = document.createElement("h2"), card = document.createElement("div");
  h.textContent = f.title; card.className = "card"; const plot = document.createElement("div"); plot.className = "plot";
  card.appendChild(plot); more.appendChild(h); more.appendChild(card);
  Plotly.newPlot(plot, f.fig.data, f.fig.layout, {responsive: true, displaylogo: false});
});
})();
</script>
</body>
</html>
"""
