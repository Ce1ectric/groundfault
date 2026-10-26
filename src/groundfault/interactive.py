# -*- coding: utf-8 -*-
"""Interactive diagrams (Plotly) for the notebook – for exploring a recording and reading off the time intervals.

Principles: one y-axis per panel (current and voltage in separate panels with a common time axis), the same fixed
colours as in [`groundfault.report`][groundfault.report], hover texts with all values. For the report use the figures of
[`groundfault.report`][groundfault.report].

Titles, axis labels, legend entries and hover texts are rendered in the output language of
[`groundfault.i18n`][groundfault.i18n] that is active when a figure is created. Numbers in texts are written with a
decimal comma in German and a decimal point in English (``groundfault.report.ReportStyle.decimal_comma`` overrides
this); the figures of the station, the earthing measurement, the reduction factor and the LV network also set the
separators of their Plotly axes and hover templates accordingly.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except Exception:  # pragma: no cover
    go = make_subplots = None

from . import i18n
from .i18n import tr
from .report import (COLORS, INTERVAL_COLORS, COLOR_DISTURBED, COLOR_MAX, ROLE_COLORS, COLOR_TYPICAL, _COMPARISON_QUANTITIES,
                     _SOURCE_FAULT, _SOURCE_GROUNDMEAS_FAULT, _SOURCE_INJECTION, _cap, _comma, _group_colors,
                     _groups, _interpolated, _pair_text, _probe_selection, _span, probe_label, station_colors, number,
                     typical_band)
from .earthing import QUANTITY_EPR, _yes
from .station import MAX_PROBE
from .channels import detect_roles

__all__ = ["overview", "rms_values", "window_spectrum", "harmonics_time", "voltage_spectrum", "source_fit", "ires_ze",
           "frequency_diagnosis", "station_frequency", "earthing_comparison", "reduction_factor", "lv_network",
           "HAS_PLOTLY", "TEMPLATE"]

HAS_PLOTLY = go is not None
"""True if plotly can be imported; every figure of this module needs it (extra ``interactive``)."""
TEMPLATE = "plotly_white"
"""Plotly template of all figures."""

i18n.register({
    "interactive.no_plotly": {"en": "plotly is not installed: pip install \"groundfault[interactive]\"",
                              "de": "plotly ist nicht installiert: pip install \"groundfault[interactive]\""},
    # ---- recording, RMS values and spectra
    "interactive.overview_title": {"en": "Whole recording (envelope) – {file}",
                                   "de": "Gesamte Aufzeichnung (Hüllkurve) – {file}"},
    "interactive.rms_title": {"en": "RMS values ({window} ms window) – read off the times of the analysis intervals",
                              "de": "Effektivwerte (Fenster {window} ms) – Zeiten für die Auswertebereiche ablesen"},
    "interactive.spectrum_window_title": {"en": "Spectrum {channel} · window t = {t} s · RMS {rms} {unit}{max}",
                                          "de": "Spektrum {channel} · Fenster t = {t} s · RMS {rms} {unit}{max}"},
    "interactive.max_window_suffix": {"en": " (max window)", "de": " (Max-Fenster)"},
    "interactive.window_prefix": {"en": "Window ", "de": "Fenster "},
    "interactive.spectrum_title": {"en": "Spectrum {channel} · max window t = {t} s",
                                   "de": "Spektrum {channel} · Max-Fenster t = {t} s"},
    "interactive.order_frequency": {"en": "Order (frequency)", "de": "Ordnung (Frequenz)"},
    "interactive.rms_in": {"en": "RMS value in {unit}", "de": "Effektivwert in {unit}"},
    "interactive.harmonic": {"en": "H{order}", "de": "{order}. Harm."},
    "interactive.harmonics_title": {"en": "Harmonics {channel} per 200 ms window (steady state)",
                                    "de": "Harmonische {channel} je 200-ms-Fenster (stationärer Bereich)"},
    "interactive.no_voltage_analysis": {"en": "No voltage analysis available.",
                                        "de": "Keine Spannungsanalyse vorhanden."},
    "interactive.voltage_spectrum_title": {"en": "Voltage spectrum {quantity}", "de": "Spannungsspektrum {quantity}"},
    "interactive.trace_pre_fault": {"en": "pre-fault", "de": "vorfehler"},
    "interactive.trace_fault": {"en": "fault", "de": "erdschluss"},
    "interactive.trace_post_fault": {"en": "post-fault", "de": "nachfehler"},
    "interactive.frequency": {"en": "Frequency", "de": "Frequenz"},
    # ---- equivalent sources
    "interactive.measurement_normalised": {"en": "measurement (normalised)", "de": "Messung (normiert)"},
    "interactive.model": {"en": "model {formula}", "de": "Modell {formula}"},
    "interactive.source_title_residual": {
        "en": "Equivalent source {f} Hz: Z_q = {r} {x}j Ω, |U_q| = {u} V, residual {residual} %",
        "de": "Zweipol {f} Hz: Z_q = {r} {x}j Ω, |U_q| = {u} V, Residuum {residual} %"},
    "interactive.source_title": {"en": "Equivalent source {f} Hz: Z_q = {r} {x}j Ω, |U_q| = {u} V",
                                 "de": "Zweipol {f} Hz: Z_q = {r} {x}j Ω, |U_q| = {u} V"},
    "interactive.additional_impedance": {"en": "Additional impedance Z in Ω", "de": "Zusatzimpedanz Z in Ω"},
    "interactive.ires_title": {"en": "Residual earth-fault current over Z_E", "de": "Erdschlussreststrom über Z_E"},
    "interactive.reference_spectrum_title": {"en": "Reference spectrum ({name}) – f1 = {f1} Hz",
                                             "de": "Referenzspektrum ({name}) – f1 = {f1} Hz"},
    # ---- station per frequency: hover texts, titles
    "interactive.hover_order_line": {"en": "Order {order} · f = {f} Hz · I<sub>F</sub> = {i_f} A",
                                     "de": "Ordnung {order} · f = {f} Hz · I<sub>F</sub> = {i_f} A"},
    "interactive.hover_voltages": {
        "en": "U during the fault {during} V · background before the fault {background} V · fault-related {fault} V",
        "de": "U im Fehler {during} V · Grundlast vor dem Fehler {background} V · fehlerbedingt {fault} V"},
    "interactive.hover_fault_quotient": {
        "en": "<b>U/I<sub>F</sub> fault-related {z} V/A</b> ({angle}°) = {zk} V/kA",
        "de": "<b>U/I<sub>F</sub> fehlerbedingt {z} V/A</b> ({angle}°) = {zk} V/kA"},
    "interactive.hover_methods": {
        "en": "  fault inception {inception} · fault clearance {clearance} · voltage reference {voltage} V/A · "
              "spread {spread} %",
        "de": "  Fehlereintritt {inception} · Fehlerende {clearance} · Spannungsbezug {voltage} V/A · "
              "Streuung {spread} %"},
    "interactive.hover_direct_quotient": {"en": "U/I<sub>F</sub> direct {z} V/A ({angle}°)",
                                          "de": "U/I<sub>F</sub> direkt {z} V/A ({angle}°)"},
    "interactive.hover_f_ratio": {
        "en": "F = U<sub>E</sub>/U<sub>T</sub> = {fault} (fault-related) · {direct} (direct)",
        "de": "F = U<sub>E</sub>/U<sub>T</sub> = {fault} (fehlerbedingt) · {direct} (direkt)"},
    "interactive.hover_background": {
        "en": "background/fault-related {ratio} · null test of the background {null_test} % · "
              "uncertainty {uncertainty} %{frequency}",
        "de": "Grundlast/fehlerbedingt {ratio} · Nulltest Grundlast {null_test} % · Unsicherheit {uncertainty} %"
              "{frequency}"},
    "interactive.hover_frequency_uncertainty": {"en": " (frequency reference without voltage measurement {value} %)",
                                                "de": " (Frequenzbezug ohne Spannungsmessung {value} %)"},
    "interactive.hover_uncertain_station": {
        "en": "<b>⚠ uncertain</b> – methods disagree or background large and fluctuating",
        "de": "<b>⚠ unsicher</b> – Verfahren uneinig oder Grundlast groß und schwankend"},
    "interactive.station_title_quotient": {
        "en": "Voltage per ampere of fault current (● fault-related with span of the methods, ⊗ uncertain, "
              "○ measured directly)",
        "de": "Spannung je Ampere Fehlerstrom (● fehlerbedingt mit Spanne der Verfahren, ⊗ unsicher, "
              "○ direkt gemessen)"},
    "interactive.station_title_voltage": {
        "en": "Voltage (● during the fault, □ background before the fault, ◆ fault-related component)",
        "de": "Spannung (● im Fehler, □ Grundlast vor dem Fehler, ◆ fehlerbedingter Anteil)"},
    "interactive.channel_direct": {"en": "{channel} direct", "de": "{channel} direkt"},
    "interactive.station_title": {"en": "Earth potential rise and touch voltage per frequency – {name}",
                                  "de": "Erdungs- und Berührungsspannung frequenzselektiv – {name}"},
    # ---- earthing measurement and fault test
    "interactive.hover_order_suffix": {"en": " · order {order}", "de": " · Ordnung {order}"},
    "interactive.hover_probe_distance": {"en": "probe distance {distance} m", "de": "Sondenabstand {distance} m"},
    "interactive.hover_methods_span": {"en": "span of the methods {low} … {high} V/A",
                                       "de": "Spanne der Verfahren {low} … {high} V/A"},
    "interactive.hover_reference_current": {"en": "reference current {current} A", "de": "Bezugsstrom {current} A"},
    "interactive.hover_groundmeas": {"en": "groundmeas measurement {id}{date}", "de": "groundmeas Messung {id}{date}"},
    "interactive.hover_uncertain_spread": {
        "en": "<b>⚠ uncertain</b> (spread of the methods {spread} %, uncertainty {uncertainty} %)",
        "de": "<b>⚠ unsicher</b> (Streuung der Verfahren {spread} %, Unsicherheit {uncertainty} %)"},
    "interactive.kind_injection": {"en": "Earthing measurement (injection)", "de": "Erdungsmessung (Einspeisung)"},
    "interactive.kind_fault": {"en": "Fault test {channel} – {method}", "de": "Erdschluss {channel} – {method}"},
    "interactive.kind_groundmeas": {"en": "Fault test from groundmeas", "de": "Erdschluss aus groundmeas"},
    "interactive.fault_related": {"en": "fault-related", "de": "fehlerbedingt"},
    "interactive.direct": {"en": "direct", "de": "direkt"},
    "interactive.uncertain_marker": {"en": " (⊗ = uncertain)", "de": " (⊗ = unsicher)"},
    "interactive.per_ampere": {"en": "{quantity} per ampere{extra}", "de": "{quantity} je Ampere{extra}"},
    "interactive.ratio_title": {"en": "Ratio fault test (fault-related) / earthing measurement",
                                "de": "Verhältnis Erdschluss (fehlerbedingt) / Erdungsmessung"},
    "interactive.injection_distance_id": {"en": "Earthing measurement {distance} m (ID {id})",
                                          "de": "Erdungsmessung {distance} m (ID {id})"},
    "interactive.fault_channel_fault": {"en": "Fault test {channel} (fault-related)",
                                        "de": "Erdschluss {channel} (fehlerbedingt)"},
    "interactive.fault_channel_rze": {"en": "Fault test {channel}: r·Z<sub>E</sub> (fault-related)",
                                      "de": "Erdschluss {channel}: r·Z<sub>E</sub> (fehlerbedingt)"},
    "interactive.fault_channel_direct": {"en": "Fault test {channel} (direct)", "de": "Erdschluss {channel} (direkt)"},
    "interactive.name_probe": {"en": "{name} · probe {probe}", "de": "{name} · Sonde {probe}"},
    "interactive.hover_ratio": {
        "en": "<b>{name}</b><br>f = {f} Hz · order {order}<br>ratio fault-related <b>{fault}</b> · direct {direct}<br>"
              "fault test {z_fault} V/A ÷ earthing measurement {z_injection} V/A (ID {id}, {distance} m)<br>"
              "probe distance: {match}{uncertain}",
        "de": "<b>{name}</b><br>f = {f} Hz · Ordnung {order}<br>Verhältnis fehlerbedingt <b>{fault}</b> · "
              "direkt {direct}<br>Erdschluss {z_fault} V/A ÷ Erdungsmessung {z_injection} V/A "
              "(ID {id}, {distance} m)<br>"
              "Sondenabstand: {match}{uncertain}"},
    "interactive.hover_uncertain_fault_value": {"en": "<br><b>⚠ uncertain</b> (fault-test value)",
                                                "de": "<br><b>⚠ unsicher</b> (Erdschlusswert)"},
    "interactive.ratio_name": {"en": "Ratio {name}", "de": "Verhältnis {name}"},
    "interactive.comparison_title": {"en": "Earthing measurement and real earth fault per frequency",
                                     "de": "Erdungsmessung und realer Erdschluss je Frequenz"},
    # ---- reduction factor
    "interactive.rf_title_ratio": {
        "en": "Reduction factor r = r·Z<sub>E</sub> (fault test) / Z<sub>E</sub> (earthing measurement) over f",
        "de": "Reduktionsfaktor r = r·Z<sub>E</sub> (Erdschluss) / Z<sub>E</sub> (Erdungsmessung) über f"},
    "interactive.rf_title_impedances": {
        "en": "Compared quantities: r·Z<sub>E</sub> from the fault test, Z<sub>E</sub> (voltage per ampere)",
        "de": "Verglichene Größen: r·Z<sub>E</sub> aus dem Erdschluss, Z<sub>E</sub> (Spannung je Ampere)"},
    "interactive.direct_short": {"en": "direct (as measured)", "de": "direkt (wie gemessen)"},
    "interactive.typical_hover": {
        "en": "typical reduction factor at 50 Hz: {low} … {high} (the range given by the user)",
        "de": "üblicher Reduktionsfaktor bei 50 Hz: {low} … {high} (vom Anwender vorgegebener Bereich)"},
    "interactive.probe_suffix": {"en": " · probe {probe}", "de": " · Sonde {probe}"},
    "interactive.hover_shield": {
        "en": "<br>from the shield current: r = {r} (shield current {share} % of I<sub>F</sub>)",
        "de": "<br>aus dem Schirmstrom: r = {r} (Schirmstrom {share} % von I<sub>F</sub>)"},
    "interactive.hover_rf_point": {
        "en": "<b>{name}</b><br>f = {f} Hz · order {order} · I<sub>F</sub> = {i_f} A{probe}<br>"
              "<b>r = {r}</b> (direct {r_direct}) · r/r(50 Hz) = {r_relative}<br>fault test r·Z<sub>E</sub> = "
              "{z_fault} V/A (fault-related) ÷ earthing measurement Z<sub>E</sub> = {z_injection} V/A ({origin})<br>"
              "probes: {d_fault} m ↔ "
              "{d_injection} m ({match}){shield}<br>at the reference current: U<sub>E</sub> {u_fault} V (fault test) · "
              "{u_injection} V (earthing measurement) = {relevance} % of F·U<sub>Tp</sub>{uncertain}",
        "de": "<b>{name}</b><br>f = {f} Hz · Ordnung {order} · I<sub>F</sub> = {i_f} A{probe}<br>"
              "<b>r = {r}</b> (direkt {r_direct}) · r/r(50 Hz) = {r_relative}<br>Erdschluss r·Z<sub>E</sub> = "
              "{z_fault} V/A (fehlerbedingt) ÷ Erdungsmessung Z<sub>E</sub> = {z_injection} V/A ({origin})<br>"
              "Sonden: {d_fault} m ↔ "
              "{d_injection} m ({match}){shield}<br>beim Bezugsstrom: U<sub>E</sub> {u_fault} V (Erdschluss) · "
              "{u_injection} V (Erdungsmessung) = {relevance} % von F·U<sub>Tp</sub>{uncertain}"},
    "interactive.hover_rf_effective": {
        "en": "<b>RMS value {name}</b>: r<sub>eff</sub> = {r_eff}<br>orders {orders} ({coverage} % of "
              "I<sub>F</sub>²)<br>direct {direct} · from RMS values {rms} · from the shield current {shield}<br>"
              "r at 50 Hz {r_50} – {classification} · trend {trend} (r ∝ f^{exponent})<br>at the reference current "
              "{current} A: U<sub>E</sub> {u_fault} V (fault test) · {u_injection} V (earthing measurement) → "
              "{relevance}",
        "de": "<b>Effektivwert {name}</b>: r<sub>eff</sub> = {r_eff}<br>Ordnungen {orders} ({coverage} % von "
              "I<sub>F</sub>²)<br>direkt {direct} · aus Effektivwerten {rms} · aus dem Schirmstrom {shield}<br>"
              "r bei 50 Hz {r_50} – {classification} · Verlauf {trend} (r ∝ f^{exponent})<br>beim Bezugsstrom "
              "{current} A: U<sub>E</sub> {u_fault} V (Erdschluss) · {u_injection} V (Erdungsmessung) → {relevance}"},
    "interactive.r_from_shield": {"en": "r from the shield current", "de": "r aus dem Schirmstrom"},
    "interactive.fault_test": {"en": "fault test", "de": "Erdschluss"},
    "interactive.hover_injection": {
        "en": "Earthing measurement ID {id} · f = {f} Hz<br>Z<sub>E</sub> = {z} V/A ({origin})",
        "de": "Erdungsmessung ID {id} · f = {f} Hz<br>Z<sub>E</sub> = {z} V/A ({origin})"},
    "interactive.rf_title": {"en": "Reduction factor per harmonic – ○ earthing measurement interpolated, ⊗ uncertain",
                             "de": "Reduktionsfaktor je Harmonische – ○ Erdungsmessung interpoliert, ⊗ unsicher"},
    # ---- LV network
    "interactive.lv_title_impedance": {
        "en": "Earthing impedance per frequency (Z<sub>E,LV</sub> must lie above r·Z<sub>E</sub> from the fault test)",
        "de": "Erdungsimpedanz je Frequenz (Z<sub>E,Ortsnetz</sub> muss über r·Z<sub>E</sub> aus dem Erdschluss liegen)"},
    "interactive.lv_title_current": {"en": "Fault-related current into the LV network and fault current",
                                     "de": "Fehlerbedingter Strom ins Ortsnetz und Fehlerstrom"},
    "interactive.probe_in_parentheses": {"en": " (probe {probe})", "de": " (Sonde {probe})"},
    "interactive.hover_lv": {
        "en": "<b>{name}</b>{probe} · f = {f} Hz · order {order}<br><b>Z<sub>E,{lv}</sub> = {z} V/A</b> ({angle}°, "
              "uncertainty {uncertainty} %)<br>ΔU<sub>E</sub> = {du} V · I<sub>{lv_i}</sub> = {i_lv} A ({share} % of "
              "I<sub>F</sub>)<br>fault test r·Z<sub>E</sub> = {reference}/I<sub>F</sub> = {z_fault} V/A → "
              "<b>{check}</b><br>with the earth current: Z<sub>E</sub> = {z_total} V/A · "
              "I<sub>{lv_i}</sub>/I<sub>E</sub> = {ratio} → "
              "{earth_check}{uncertain}",
        "de": "<b>{name}</b>{probe} · f = {f} Hz · Ordnung {order}<br><b>Z<sub>E,{lv}</sub> = {z} V/A</b> ({angle}°, "
              "Unsicherheit {uncertainty} %)<br>ΔU<sub>E</sub> = {du} V · I<sub>{lv_i}</sub> = {i_lv} A ({share} % von "
              "I<sub>F</sub>)<br>Erdschluss r·Z<sub>E</sub> = {reference}/I<sub>F</sub> = {z_fault} V/A → "
              "<b>{check}</b><br>mit dem Erdungsstrom: Z<sub>E</sub> = {z_total} V/A · "
              "I<sub>{lv_i}</sub>/I<sub>E</sub> = {ratio} → "
              "{earth_check}{uncertain}"},
    "interactive.hover_uncertain": {"en": "<br><b>⚠ uncertain</b>", "de": "<br><b>⚠ unsicher</b>"},
    "interactive.hover_lv_check": {
        "en": "Earthing measurement ID {id} ({distance} m) · f = {f} Hz<br>Z<sub>E</sub> = {z} V/A ({origin})<br>"
              "Z<sub>E,{lv}</sub>/Z<sub>E</sub> = {ratio} → <b>{check}</b> (uncertainty {uncertainty} %)",
        "de": "Erdungsmessung ID {id} ({distance} m) · f = {f} Hz<br>Z<sub>E</sub> = {z} V/A ({origin})<br>"
              "Z<sub>E,{lv}</sub>/Z<sub>E</sub> = {ratio} → <b>{check}</b> (Unsicherheit {uncertainty} %)"},
    "interactive.lv_current": {"en": "{symbol} (fault-related)", "de": "{symbol} (fehlerbedingt)"},
    "interactive.lv_title": {
        "en": "LV network: current into the LV network and earthing impedance Z<sub>E,{lv}</sub> = "
              "ΔU<sub>E</sub>/I<sub>{lv_i}</sub>",
        "de": "Ortsnetz: Strom ins Ortsnetz und Erdungsimpedanz Z<sub>E,{lv}</sub> = "
              "ΔU<sub>E</sub>/I<sub>{lv_i}</sub>"},
})


def _check_plotly():
    """ImportError if plotly is missing."""
    if not HAS_PLOTLY:
        raise ImportError(tr("interactive.no_plotly"))


def _rgba(hex_color: str, a: float) -> str:
    """``"#rrggbb"`` and opacity → ``"rgba(r,g,b,a)"``."""
    h = hex_color.lstrip("#")
    return "rgba(%d,%d,%d,%.2f)" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def _fmt(x, spec: str) -> str:
    """Number with a format specification (``".2f"``, ``"g"``) and the decimal separator of the figures."""
    s = format(float(x), spec)
    return s.replace(".", ",") if _comma() else s


def _separators() -> str:
    """Plotly ``separators`` (decimal, thousands) of the output language: ``",."`` (German) or ``".,"``."""
    return ",." if _comma() else ".,"


#: annotations of the analysis intervals (message keys)
_INTERVAL_NAMES = {"pre_fault": "report.label_pre_fault", "steady_state": "report.interval_steady_state",
                   "post_fault": "report.label_post_fault"}
#: trace names of the intervals before, during and after the fault in the voltage spectrum (message keys)
_INTERVAL_TRACES = {"pre_fault": "interactive.trace_pre_fault", "fault": "interactive.trace_fault",
                    "post_fault": "interactive.trace_post_fault"}


def _draw_intervals(fig, intervals, rows: int):
    """Shade the analysis intervals in all panels (annotation in the top panel)."""
    if intervals is None:
        return
    for name in ("pre_fault", "steady_state", "post_fault"):
        b = getattr(intervals, name, None) if not isinstance(intervals, dict) else intervals.get(name)
        if b:
            for r in range(1, rows + 1):
                fig.add_vrect(x0=b[0], x1=b[1], fillcolor=INTERVAL_COLORS[name], opacity=0.35, line_width=0,
                              row=r, col=1, layer="below",
                              annotation_text=tr(_INTERVAL_NAMES[name]) if r == 1 else None,
                              annotation_position="top left")


def _draw_disturbed(fig, disturbances, rows: int) -> None:
    """Shade the disturbed time ranges of a [`Disturbances`][groundfault.disturbances.Disturbances] (or of the
    ``disturbances`` of a result) in all panels; the state is named in the top panel."""
    d = getattr(disturbances, "disturbances", disturbances)
    if d is None or not getattr(d, "found", False):
        return
    from .disturbances import _label
    for t0, t1, state in d.excluded_intervals():
        for r in range(1, rows + 1):
            kw = dict(row=r, col=1) if rows > 1 else {}
            fig.add_vrect(x0=t0, x1=t1, fillcolor=COLOR_DISTURBED, opacity=0.12, line_width=0, layer="below", **kw)
        # the state on hover: an invisible marker line over the range in the top panel
        fig.add_trace(go.Scatter(x=[t0, t1], y=[0, 0], mode="lines", line=dict(color=COLOR_DISTURBED, width=6),
                                 opacity=0.5, name=tr("report.interval_disturbed"), showlegend=False,
                                 hovertemplate="%s<br>%s–%s s<extra></extra>" % (_label(state), _fmt(t0, ".2f"),
                                                                               _fmt(t1, ".2f"))),
                      **(dict(row=1, col=1) if rows > 1 else {}))


def overview(rec, roles=None, n_bins: int = 4000, intervals=None, height_per_panel: int = 230):
    """Min/max envelope of the whole recording, one panel per quantity, range slider at the bottom.

    Parameters
    ----------
    rec : Recording
        The recording.
    roles : RoleAssignment, optional
        Channel roles (default: [`groundfault.detect_roles`][groundfault.channels.detect_roles] from the channel names
        and units).
    n_bins : int
        Number of time bins of the envelope.
    intervals : Intervals or dict, optional
        Analysis intervals to shade (``pre_fault``, ``steady_state``, ``post_fault``).
    height_per_panel : int
        Height per panel in pixels.

    Returns
    -------
    plotly.graph_objects.Figure
    """
    _check_plotly()
    roles = roles or detect_roles(rec.channel_names, rec.units)
    groups = _groups(roles, None)
    t, lo, hi = rec.envelope(n_bins=n_bins)
    n = len(groups)
    fig = make_subplots(rows=n, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                        subplot_titles=list(groups))
    for r, (g, ks) in enumerate(groups.items(), start=1):
        for k, c in zip(ks, _group_colors(ks)):
            fig.add_trace(go.Scatter(x=np.concatenate([t, t[::-1]]), y=np.concatenate([hi[:, k.index], lo[::-1, k.index]]),
                                     fill="toself", mode="lines", line=dict(width=0.5, color=c),
                                     fillcolor=_rgba(c, 0.35), name=k.short, hoverinfo="name", legendgroup=g),
                          row=r, col=1)
        fig.update_yaxes(title_text="%s in %s" % ("u" if ks[0].unit.upper().startswith("V") else "i",
                                                  ks[0].unit), row=r, col=1)
    if rec.trigger_s is not None and 0 <= rec.trigger_s <= rec.duration_s:
        for r in range(1, n + 1):
            fig.add_vline(x=rec.trigger_s, line=dict(color="#333333", dash="dash", width=1), row=r, col=1)
    _draw_intervals(fig, intervals, n)
    fig.update_xaxes(title_text="t in s", row=n, col=1, rangeslider=dict(visible=True, thickness=0.06))
    fig.update_layout(template=TEMPLATE, height=height_per_panel * n + 120, hovermode="x",
                      title=tr("interactive.overview_title", file=rec.info()["file"]),
                      legend=dict(orientation="h", y=1.02, yanchor="bottom", x=1, xanchor="right"))
    return fig


def rms_values(rec, roles=None, window_s: float = 0.02, intervals=None, max_window: Optional[Tuple[float, float]] = None,
               height_per_panel: int = 230, disturbances=None):
    """True RMS value (window ``window_s``) over time – for reading off the analysis intervals.

    Parameters
    ----------
    rec : Recording
        The recording.
    roles : RoleAssignment, optional
        Channel roles (default: [`groundfault.detect_roles`][groundfault.channels.detect_roles]).
    window_s : float
        RMS window in s.
    intervals : Intervals or dict, optional
        Analysis intervals to shade.
    max_window : (float, float), optional
        Max window (start, end) in s to shade.
    height_per_panel : int
        Height per panel in pixels.
    disturbances : Disturbances or Result, optional
        Disturbed states to shade, e.g. from [`groundfault.disturbances.scan`][groundfault.disturbances.scan] (before
        the intervals are chosen) or the result of the evaluation.

    Returns
    -------
    plotly.graph_objects.Figure
    """
    _check_plotly()
    roles = roles or detect_roles(rec.channel_names, rec.units)
    groups = _groups(roles, None)
    t, R = rec.rms_trend(window_s=window_s)
    n = len(groups)
    fig = make_subplots(rows=n, cols=1, shared_xaxes=True, vertical_spacing=0.03, subplot_titles=list(groups))
    for r, (g, ks) in enumerate(groups.items(), start=1):
        for k, c in zip(ks, _group_colors(ks)):
            fig.add_trace(go.Scattergl(x=t, y=R[:, k.index], mode="lines", line=dict(width=1.2, color=c),
                                       name=k.short, legendgroup=g), row=r, col=1)
        fig.update_yaxes(title_text="%s in %s" % ("U" if ks[0].unit.upper().startswith("V") else "I",
                                                  ks[0].unit), row=r, col=1, rangemode="tozero")
    _draw_intervals(fig, intervals, n)
    _draw_disturbed(fig, disturbances, n)
    if max_window:
        for r in range(1, n + 1):
            fig.add_vrect(x0=max_window[0], x1=max_window[1], fillcolor="#111111", opacity=0.2, line_width=0,
                          row=r, col=1)
    fig.update_xaxes(title_text="t in s", row=n, col=1, rangeslider=dict(visible=True, thickness=0.06))
    fig.update_layout(template=TEMPLATE, height=height_per_panel * n + 120, hovermode="x unified",
                      title=tr("interactive.rms_title", window=_fmt(1000 * window_s, "g")),
                      legend=dict(orientation="h", y=1.02, yanchor="bottom", x=1, xanchor="right"))
    return fig


def window_spectrum(res, role: str = "i_res", orders: Optional[Sequence[int]] = None):
    """Harmonics per 200 ms window of the steady-state interval (slider over the windows).

    Parameters
    ----------
    res : Result
        Evaluation result.
    role : str
        Role of the channel (its main channel is shown).
    orders : sequence of int, optional
        Harmonic orders (default: 1…13 as far as evaluated).

    Returns
    -------
    plotly.graph_objects.Figure
        The slider starts at the max window.
    """
    _check_plotly()
    st = res.steady_state; k = res.roles.main(role)
    ords = [o for o in (orders or range(1, 14)) if o in st.orders]
    f1 = st.f1["f1_used"]
    fig = go.Figure()
    for w in range(len(st.t_mid)):
        fig.add_trace(go.Bar(x=["%d (%g Hz)" % (m, round(m * f1)) for m in ords],
                             y=[abs(st.X[w, k.index, st.ix(m)]) for m in ords], visible=(w == res.max_index),
                             marker_color=ROLE_COLORS.get(role, COLORS[0]), name="t = %s s" % _fmt(st.t_mid[w], ".2f")))
    steps = []
    for w in range(len(st.t_mid)):
        v = [False] * len(st.t_mid); v[w] = True
        title = tr("interactive.spectrum_window_title", channel=k.short, t=_fmt(st.t_mid[w], ".2f"),
                   rms=_fmt(st.rms[w, k.index], ".2f"), unit=k.unit,
                   max=tr("interactive.max_window_suffix") if w == res.max_index else "")
        steps.append(dict(method="update", label="%s s" % _fmt(st.t_mid[w], ".2f"),
                          args=[{"visible": v}, {"title": title}]))
    slider = dict(active=res.max_index, steps=steps, currentvalue={"prefix": tr("interactive.window_prefix")})
    fig.update_layout(template=TEMPLATE, height=430, sliders=[slider],
                      title=tr("interactive.spectrum_title", channel=k.short, t=_fmt(res.t_max_window, ".2f")),
                      xaxis_title=tr("interactive.order_frequency"), yaxis_title=tr("interactive.rms_in", unit=k.unit))
    return fig


def harmonics_time(res, role: str = "i_res", orders: Sequence[int] = (1, 3, 5, 7)):
    """RMS value and harmonics per 200 ms window of the steady-state interval over time.

    Parameters
    ----------
    res : Result
        Evaluation result.
    role : str
        Role of the channel (its main channel is shown).
    orders : sequence of int
        Harmonic orders.

    Returns
    -------
    plotly.graph_objects.Figure
        The dashed line marks the max window; disturbed states (not part of the reference) are shaded.
    """
    _check_plotly()
    st = res.steady_state; k = res.roles.main(role)
    fig = go.Figure()
    _draw_disturbed(fig, getattr(res, "disturbances", None), 1)
    fig.add_trace(go.Scatter(x=st.t_mid, y=st.rms[:, k.index], mode="lines+markers", name=tr("report.rms"),
                             line=dict(color="#111111")))
    for i, m in enumerate(o for o in orders if o in st.orders):
        fig.add_trace(go.Scatter(x=st.t_mid, y=np.abs(st.X[:, k.index, st.ix(m)]), mode="lines+markers",
                                 name=tr("interactive.harmonic", order=m), line=dict(color=COLORS[i % 8])))
    fig.add_vline(x=res.t_max_window, line=dict(color="#666666", dash="dash"))
    fig.update_layout(template=TEMPLATE, height=420, hovermode="x unified",
                      title=tr("interactive.harmonics_title", channel=k.short),
                      xaxis_title="t in s", yaxis_title=tr("interactive.rms_in", unit=k.unit))
    return fig


def voltage_spectrum(res, orders: Optional[Sequence[int]] = None):
    """Voltage quantities (line-to-earth, line-to-line, positive/negative/zero sequence) per harmonic before, during
    and after the fault (selection menu, initially the negative sequence).

    Parameters
    ----------
    res : Result
        Evaluation result with the voltage analysis.
    orders : sequence of int, optional
        Harmonic orders (default: the odd orders 1…13).

    Returns
    -------
    plotly.graph_objects.Figure

    Raises
    ------
    ValueError
        If the result has no voltage analysis.
    """
    _check_plotly()
    sp = res.values.get("voltage")
    if not sp:
        raise ValueError(tr("interactive.no_voltage_analysis"))
    ords = sp["orders"]; sel = [o for o in (orders or [1, 3, 5, 7, 9, 11, 13]) if o in ords]
    quantities = ["U_pos", "U_neg", "U_zero", "U_L12", "U_L23", "U_L31", "U_L1E", "U_L2E", "U_L3E"]
    bl = [b for b in ("pre_fault", "fault", "post_fault") if b in sp]
    colors = {"pre_fault": COLORS[0], "fault": COLORS[7], "post_fault": COLORS[1]}
    fig = go.Figure()
    for gi, g in enumerate(quantities):
        for b in bl:
            fig.add_trace(go.Bar(x=["%g Hz" % round(m * res.steady_state.f1["f1_used"]) for m in sel],
                                 y=[sp[b][g][ords.index(m)] for m in sel], name=tr(_INTERVAL_TRACES[b]),
                                 marker_color=colors[b], visible=(gi == 1)))
    buttons = []
    for gi, g in enumerate(quantities):
        v = [False] * (len(quantities) * len(bl))
        for j in range(len(bl)):
            v[gi * len(bl) + j] = True
        buttons.append(dict(method="update", label=i18n.column_label(g),
                            args=[{"visible": v},
                                  {"title": tr("interactive.voltage_spectrum_title", quantity=i18n.column_label(g))}]))
    fig.update_layout(template=TEMPLATE, barmode="group", height=430,
                      title=tr("interactive.voltage_spectrum_title", quantity=i18n.column_label("U_neg")),
                      updatemenus=[dict(buttons=buttons, x=1.0, xanchor="right", y=1.15, active=1)],
                      yaxis_title=tr("interactive.rms_in", unit="V"), xaxis_title=tr("interactive.frequency"))
    return fig


def source_fit(series, Z_E: Optional[float] = None, comparison=None):
    """Two-terminal (Thevenin) fit per order (slider): normalised measuring points and model curve
    |U_q/(Z_q + Z)| over the additional impedance.

    Parameters
    ----------
    series : SourceSeries
        Equivalent sources
        ([`groundfault.equivalent_source.fit_equivalent_source`][groundfault.equivalent_source.fit_equivalent_source] or
        [`groundfault.equivalent_source.measured_source`][groundfault.equivalent_source.measured_source]).
    Z_E : float, optional
        Earthing impedance in Ω (dashed vertical line).
    comparison : SourceSeries, optional
        A second series of the same measurements (e.g. the fitted source when ``series`` is the measured one): its
        model curve dashed.

    Returns
    -------
    plotly.graph_objects.Figure
    """
    _check_plotly()
    from .report import _source_label
    ords = sorted(series.fits)
    zz = np.array([abs(m.Z) for m in series.measurements])
    zg = np.linspace(0, max(zz.max() * 1.3, (Z_E or 0) * 1.3, 1.0), 200)
    fig = go.Figure()
    per = 3 if comparison is not None else 2                          # traces per order
    for i, m in enumerate(ords):
        F = series.fits[m]
        fig.add_trace(go.Scatter(x=np.abs(F.Z), y=np.abs(F.I_fit), mode="markers",
                                 name=tr("interactive.measurement_normalised"),
                                 marker=dict(size=10, color=COLORS[1]), visible=(i == 0),
                                 text=[mm.name for mm in series.measurements]))
        name = tr("interactive.model", formula="|U_q/(Z_q+Z)|")
        fig.add_trace(go.Scatter(x=zg, y=np.abs(F.Uq / (F.Zq + zg)), mode="lines",
                                 name=name if comparison is None else "%s – %s" % (name, _source_label(series)),
                                 line=dict(color=COLORS[0]), visible=(i == 0)))
        if comparison is not None:
            G = comparison.fits.get(m, F)
            fig.add_trace(go.Scatter(x=zg, y=np.abs(G.Uq / (G.Zq + zg)), mode="lines",
                                     name="%s – %s" % (name, _source_label(comparison)),
                                     line=dict(color=COLORS[0], dash="dash"), visible=(i == 0)))
    steps = []
    for i, m in enumerate(ords):
        v = [False] * (per * len(ords))
        for j in range(per):
            v[per * i + j] = True
        F = series.fits[m]
        title = tr("interactive.source_title_residual", f=_fmt(F.f_Hz, "g"), r=_fmt(F.Zq.real, ".2f"),
                   x=_fmt(F.Zq.imag, "+.2f"), u=_fmt(abs(F.Uq), ".1f"), residual=_fmt(100 * F.resid_rel, ".1f"))
        steps.append(dict(method="update", label="%g Hz" % round(F.f_Hz), args=[{"visible": v}, {"title": title}]))
    if Z_E is not None:
        fig.add_vline(x=Z_E, line=dict(color="#666666", dash="dash"), annotation_text="Z_E")
    F0 = series.fits[ords[0]]
    fig.update_layout(template=TEMPLATE, height=440, sliders=[dict(active=0, steps=steps)],
                      title=tr("interactive.source_title", f=_fmt(F0.f_Hz, "g"), r=_fmt(F0.Zq.real, ".2f"),
                               x=_fmt(F0.Zq.imag, "+.2f"), u=_fmt(abs(F0.Uq), ".1f")),
                      xaxis_title=tr("interactive.additional_impedance"), yaxis_title="|I| in A")
    return fig


def ires_ze(series, Z_E_max: float = 10.0, limits=(), scaling: Optional[dict] = None, comparison=None):
    """Residual current I_RES over the earthing impedance Z_E from the equivalent sources (equivalent-source method),
    with the current per harmonic order and the limits given by the user.

    Parameters
    ----------
    series : SourceSeries
        Equivalent sources (fitted, or measured with
        [`groundfault.equivalent_source.measured_source`][groundfault.equivalent_source.measured_source]).
    Z_E_max : float
        End of the impedance axis in Ω.
    limits : sequence of float
        Limits of the residual current in A, defined by the user (dotted horizontal lines); empty (default): no
        lines.
    scaling : dict, optional
        Keyword arguments of
        [`groundfault.equivalent_source.ires_at_impedance`][groundfault.equivalent_source.ires_at_impedance] for the
        scaling of the harmonic currents → additional curve "I_RES scaled".
    comparison : SourceSeries, optional
        A second series of the same measurements (e.g. the fitted source when ``series`` is the measured one): its
        I_RES (and I_RES scaled) dashed.

    Returns
    -------
    plotly.graph_objects.Figure
        Grey background: range of the measured additional impedances.
    """
    _check_plotly()
    from .equivalent_source import ires_at_impedance
    from .report import _source_label
    zg = np.linspace(0, Z_E_max, 201)
    res = [ires_at_impedance(series, z, **(scaling or {})) for z in zg]
    other = [ires_at_impedance(comparison, z, **(scaling or {})) for z in zg] if comparison is not None else []
    lab = (lambda s, x: tr("report.with_source", symbol=s, source=_source_label(x))) if other else (lambda s, x: s)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=zg, y=[r["IRES"] for r in res], name=lab("I_RES", series),
                             line=dict(color="#111111", width=3)))
    if other:
        fig.add_trace(go.Scatter(x=zg, y=[r["IRES"] for r in other], name=lab("I_RES", comparison),
                                 line=dict(color="#111111", width=2, dash="dash")))
    if scaling:
        fig.add_trace(go.Scatter(x=zg, y=[r["IRES_scaled"] for r in res],
                                 name=lab(tr("report.scaled", symbol="I_RES"), series),
                                 line=dict(color=COLORS[7], width=3)))
        if other:
            fig.add_trace(go.Scatter(x=zg, y=[r["IRES_scaled"] for r in other],
                                     name=lab(tr("report.scaled", symbol="I_RES"), comparison),
                                     line=dict(color=COLORS[7], width=2, dash="dash")))
    for i, m in enumerate(sorted(series.fits)):
        fig.add_trace(go.Scatter(x=zg, y=[r["parts"][m] for r in res], name="%g Hz" % round(series.fits[m].f_Hz),
                                 line=dict(color=COLORS[i % 8], width=1.5)))
    for g in limits:
        fig.add_hline(y=g, line=dict(color="#333333", dash="dot", width=1), annotation_text="%s A" % _short(g))
    zmin, zmax = series.Z_range
    fig.add_vrect(x0=zmin, x1=zmax, fillcolor="#dddddd", opacity=0.4, line_width=0, layer="below",
                  annotation_text=tr("report.measured_range"), annotation_position="bottom")
    fig.update_layout(template=TEMPLATE, height=450, hovermode="x unified", title=tr("interactive.ires_title"),
                      xaxis_title="Z_E in Ω", yaxis_title="I in A")
    return fig


def frequency_diagnosis(rec, res, band: Tuple[float, float] = (40.0, 60.0)):
    """Spectrum of the reference voltage around 50 Hz (check of the f1 estimation).

    Parameters
    ----------
    rec : Recording
        The recording.
    res : Result
        Evaluation result (steady-state interval, roles, estimated f1).
    band : (float, float)
        Frequency band in Hz.

    Returns
    -------
    plotly.graph_objects.Figure
        Dashed line: the fundamental frequency f1 used by the evaluation.
    """
    _check_plotly()
    from .evaluation import _reference_signal
    b = res.intervals.steady_state
    i0 = int(b[0] * rec.fs); i1 = int(min(b[1], b[0] + 2.0) * rec.fs)
    blk = rec.read(i0, i1)
    ref, name = _reference_signal(blk, res.roles)
    x = ref[np.isfinite(ref)]
    tt = np.arange(x.size); x = x - np.polyval(np.polyfit(tt, x, 1), tt)
    nf = 1 << int(np.ceil(np.log2(max(x.size * 4, 8))))
    X = np.abs(np.fft.rfft(x * np.hanning(x.size), nf)); f = np.fft.rfftfreq(nf, 1 / rec.fs)
    m = (f > band[0]) & (f < band[1])
    fig = go.Figure(go.Scatter(x=f[m], y=X[m], mode="lines", line=dict(color=COLORS[0]), name=name))
    fig.add_vline(x=res.steady_state.f1["f1_used"], line=dict(color=COLORS[7], dash="dash"), annotation_text="f1")
    fig.update_layout(template=TEMPLATE, height=360,
                      title=tr("interactive.reference_spectrum_title", name=name,
                               f1=_fmt(res.steady_state.f1["f1_used"], ".4f")),
                      xaxis_title="f in Hz", yaxis_title="|X|")
    return fig


# ====================================================================== station per frequency, earthing measurement
def _z(v, digits: int = 4) -> str:
    """Number for hover texts ([`groundfault.report.number`][groundfault.report.number]); missing → "–"."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "–"
    return number(v, digits) if np.isfinite(v) else "–"


def _log_ticks(fig, values, row: int, col: int = 1) -> None:
    """Logarithmic y-axis with readable ticks (1-2-5 per decade, decimal separator of the language) instead of the
    digits 2…9."""
    w = np.asarray(pd.to_numeric(pd.Series(np.ravel(values)), errors="coerce"), float)
    w = w[np.isfinite(w) & (w > 0)]
    if not w.size:
        return
    lo, hi = int(np.floor(np.log10(w.min()))), int(np.ceil(np.log10(w.max())))
    mant = ((1, 1.5, 2, 3, 4, 5, 6, 7, 8) if w.max() / w.min() < 5 else (1, 2, 5) if hi - lo <= 3 else
            (1, 3) if hi - lo <= 5 else (1,))
    vals = [m * 10.0 ** e for e in range(lo, hi + 1) for m in mant]
    vals = [v for v in vals if w.min() / 2.5 <= v <= w.max() * 2.5]
    fig.update_yaxes(type="log", tickvals=vals, ticktext=[_short(v) for v in vals], row=row, col=col)


def _num(x) -> float:
    """Number from a table cell (None, text, empty → NaN)."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def _station_hover(r) -> str:
    """All numbers of a row of the table ``station_frequency`` as hover text."""
    g = lambda sp: _num(r.get(sp, np.nan))                             # noqa: E731
    rows = ["<b>%s</b>" % probe_label(r["channel"], r["role"], r.get("distance_m")),
            tr("interactive.hover_order_line", order=int(r["order"]), f=_z(r["f_Hz"], 5), i_f=_z(r["I_F_A"])),
            tr("interactive.hover_voltages", during=_z(g("U_during_fault_V")), background=_z(g("U_background_V")),
               fault=_z(g("U_fault_V"))),
            tr("interactive.hover_fault_quotient", z=_z(g("Z_fault_Ohm")), angle=_z(g("Z_fault_angle_deg"), 3),
               zk=_z(1000 * g("Z_fault_Ohm"), 3)),
            tr("interactive.hover_methods", inception=_z(g("Z_inception_Ohm")), clearance=_z(g("Z_clearance_Ohm")),
               voltage=_z(g("Z_voltage_Ohm")), spread=_z(g("method_spread_pct"), 2)),
            tr("interactive.hover_direct_quotient", z=_z(g("Z_direct_Ohm")), angle=_z(g("Z_direct_angle_deg"), 3))]
    if np.isfinite(g("F_fault")):
        rows.append(tr("interactive.hover_f_ratio", fault=_z(g("F_fault"), 3), direct=_z(g("F_direct"), 3)))
    if np.isfinite(g("uncertainty_pct")) or np.isfinite(g("background_to_fault")):
        frequency = (tr("interactive.hover_frequency_uncertainty", value=_z(g("frequency_uncertainty_pct"), 2))
                     if np.isfinite(g("frequency_uncertainty_pct")) else "")
        rows.append(tr("interactive.hover_background", ratio=_z(g("background_to_fault"), 2),
                       null_test=_z(g("background_forecast_error_pct"), 2), uncertainty=_z(g("uncertainty_pct"), 2),
                       frequency=frequency))
    if _yes(r.get("uncertain")):
        rows.append(tr("interactive.hover_uncertain_station"))
    return "<br>".join(rows)


def _symbols(g, certain: str = "circle", uncertain: str = "circle-x-open") -> List[str]:
    """Marker symbol per point: uncertain values (column ``uncertain``) as ⊗."""
    if "uncertain" not in g:
        return [certain] * len(g)
    return [uncertain if _yes(x) else certain for x in g["uncertain"]]


def _marker(g, color: str, size: int = 7) -> dict:
    """Marker per point: filled, uncertain values as a slightly larger ⊗."""
    sym = _symbols(g)
    return dict(size=[size + 2 if s != "circle" else size for s in sym], color=color, symbol=sym,
                line=dict(color=color, width=1.4))


def _legend_as_certain(fig, g, name: str, group: str, color: str, row: int, col: int = 1) -> bool:
    """Plotly shows the symbol of the first point in the legend – if that point is uncertain, add a separate legend
    entry with the normal symbol (returns True: the trace itself without a legend entry)."""
    if _symbols(g)[0] == "circle":
        return False
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines+markers", name=name, legendgroup=group,
                             line=dict(color=color, width=1.6), marker=dict(size=7, color=color), hoverinfo="skip"),
                  row=row, col=col)
    return True


def station_frequency(res, log: bool = True, f_max: Optional[float] = None, height: int = 760):
    """Earth potential rise and touch voltage per frequency (table ``station_frequency``).

    Top U/I_F in V/A: fault-related component (filled, line; bar = smallest/largest value of the methods fault
    inception, fault clearance, voltage reference; ⊗ = uncertain), direct quotient (open). Bottom the voltages in V:
    measured during the fault (●), background before the fault (□), fault-related component (◆). Hover: all
    values; a click on a probe in the legend hides it in both panels.

    Parameters
    ----------
    res : Result or ResultFile
        Result with the table ``station_frequency``.
    log : bool
        Logarithmic y-axis of the top panel.
    f_max : float, optional
        Highest frequency in Hz.
    height : int
        Figure height in pixels.

    Returns
    -------
    plotly.graph_objects.Figure

    Raises
    ------
    ValueError
        If the table ``station_frequency`` is missing or empty.
    """
    _check_plotly()
    df = (getattr(res, "tables", None) or {}).get("station_frequency")
    if df is None or df.empty:
        raise ValueError(tr("report.no_station_frequency", table="station_frequency"))
    if f_max:
        df = df[df["f_Hz"] <= f_max]
    colors = station_colors(df["channel"])
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
                        subplot_titles=(tr("interactive.station_title_quotient"),
                                        tr("interactive.station_title_voltage")))
    for channel, g in df.groupby("channel", sort=False):
        g = g.sort_values("f_Hz"); c = colors[channel]; r0 = g.iloc[0]
        text = [_station_hover(r) for _, r in g.iterrows()]
        name = probe_label(channel, r0["role"], r0.get("distance_m"))
        has_fault = "Z_fault_Ohm" in g and g["Z_fault_Ohm"].notna().any()
        if has_fault:
            y, lo, hi = _span(g)
            own_ = _legend_as_certain(fig, g, name, channel, c, 1)
            fig.add_trace(go.Scatter(x=g["f_Hz"], y=y, mode="lines+markers", name=name, legendgroup=channel,
                                     showlegend=not own_, line=dict(color=c, width=1.6), marker=_marker(g, c),
                                     error_y=dict(type="data", symmetric=False, array=hi - y, arrayminus=y - lo,
                                                  thickness=1.3, width=0, color=c),
                                     hovertext=text, hoverinfo="text"), row=1, col=1)
        fig.add_trace(go.Scatter(x=g["f_Hz"], y=g["Z_direct_Ohm"], mode="markers",
                                 name=name if not has_fault else tr("interactive.channel_direct", channel=channel),
                                 legendgroup=channel, showlegend=not has_fault,
                                 marker=dict(size=7, color="white", line=dict(color=c, width=1.6)),
                                 hovertext=text, hoverinfo="text"), row=1, col=1)
        for sp, sym, filled in (("U_during_fault_V", "circle", True), ("U_background_V", "square", False),
                                ("U_fault_V", "diamond", True)):
            if sp in g and g[sp].notna().any():
                fig.add_trace(go.Scatter(x=g["f_Hz"], y=g[sp], mode="markers", legendgroup=channel, showlegend=False,
                                         name=channel, marker=dict(size=7, symbol=sym, color=c if filled else "white",
                                                                   line=dict(color=c, width=1.4)),
                                         hovertext=text, hoverinfo="text"), row=2, col=1)
    fig.update_yaxes(type="log" if log else "linear", title_text="U/I<sub>F</sub> in V/A", row=1, col=1)
    if log:
        _log_ticks(fig, df[[c for c in df.columns if c.startswith("Z_") and c.endswith("_Ohm")]], 1)
    _log_ticks(fig, df[[c for c in ("U_during_fault_V", "U_background_V", "U_fault_V") if c in df]], 2)
    fig.update_yaxes(title_text="U in V", row=2, col=1)
    fig.update_xaxes(title_text="f in Hz", row=2, col=1, rangemode="tozero")
    fig.update_layout(template=TEMPLATE, separators=_separators(), height=height, hovermode="closest",
                      title=tr("interactive.station_title", name=getattr(res, "name", "")),
                      legend=dict(orientation="h", y=-0.1, yanchor="top", x=0, xanchor="left"),
                      margin=dict(t=90, b=130))
    return fig


def _comparison_hover(r, kind: str) -> str:
    """Hover text of a row of the comparison table of [`groundfault.earthing.compare`][groundfault.earthing.compare]."""
    def g(sp):
        v = r.get(sp, np.nan) if hasattr(r, "get") else np.nan
        return v if isinstance(v, str) else _num(v)
    z = ["<b>%s</b>" % kind, "f = %s Hz%s" % (_z(r["f_Hz"], 5), tr("interactive.hover_order_suffix",
                                                                   order=int(r["order"]))
                                             if np.isfinite(g("order")) else ""),
         "U/I = <b>%s V/A</b>%s" % (_z(r["Z_Ohm"]), " (%s°)" % _z(g("angle_deg"), 3) if np.isfinite(g("angle_deg"))
                                    else "")]
    if np.isfinite(g("distance_m")):
        z.append(tr("interactive.hover_probe_distance", distance=_z(g("distance_m"), 3)))
    if np.isfinite(g("Z_min_Ohm")):
        z.append(tr("interactive.hover_methods_span", low=_z(g("Z_min_Ohm")), high=_z(g("Z_max_Ohm"))))
    if np.isfinite(g("reference_current_A")):
        z.append(tr("interactive.hover_reference_current", current=_z(g("reference_current_A"))))
    if np.isfinite(g("measurement_id")):
        date = g("date")
        z.append(tr("interactive.hover_groundmeas", id=int(g("measurement_id")),
                    date=", " + date if isinstance(date, str) and date else ""))
    if _yes(r.get("uncertain") if hasattr(r, "get") else None):
        z.append(tr("interactive.hover_uncertain_spread", spread=_z(g("method_spread_pct"), 2),
                    uncertainty=_z(g("uncertainty_pct"), 2)))
    return "<br>".join(z)


def earthing_comparison(long_df, ratio=None, f_max="auto", height_per_panel: int = 330):
    """Earthing measurement (groundmeas) ↔ real earth fault per frequency (result of
    [`groundfault.earthing.compare`][groundfault.earthing.compare]).

    One panel per quantity (earth potential rise, touch voltage; V/A, logarithmic): injection measurement per probe
    distance (grey, ■), earth fault of this evaluation per probe (fault-related ●, bar = span of the methods,
    ⊗ = uncertain; direct ○, can be shown via the legend), fault-test values from groundmeas (✕). Below, the ratio
    fault test / earthing measurement (fault-related; for the earth potential rise at a remote probe = reduction
    factor).

    Parameters
    ----------
    long_df : pandas.DataFrame
        Long table of [`groundfault.earthing.compare`][groundfault.earthing.compare].
    ratio : pandas.DataFrame, optional
        Ratio table of [`groundfault.earthing.compare`][groundfault.earthing.compare] → bottom panel (rows with
        ``distance_match == "different"`` are left out).
    f_max : "auto", float or None
        Highest frequency in Hz; ``"auto"``: 15 % above the highest frequency of the earthing measurement.
    height_per_panel : int
        Height per panel in pixels.

    Returns
    -------
    plotly.graph_objects.Figure

    Raises
    ------
    ValueError
        If there are no values to compare.
    """
    _check_plotly()
    es_ = long_df[long_df["source"] == _SOURCE_FAULT]
    inj = long_df[long_df["source"] == _SOURCE_INJECTION]
    gm = long_df[long_df["source"] == _SOURCE_GROUNDMEAS_FAULT]
    if f_max == "auto":
        f_max = 1.15 * float(inj["f_Hz"].max()) if not inj.empty else None
    if f_max:
        es_, inj, gm = (d[d["f_Hz"] <= f_max] for d in (es_, inj, gm))
    groups = [g for g in _COMPARISON_QUANTITIES if g in set(es_["quantity"]) | set(inj["quantity"])]
    v = ratio if ratio is not None and len(ratio) else None
    if v is not None:
        v = v[v["distance_match"] != "different"] if "distance_match" in v else v
        v = v[v["f_Hz"] <= f_max] if f_max else v
        v = v if len(v) else None
    n = len(groups) + (1 if v is not None else 0)
    if not n:
        raise ValueError(tr("report.no_values_to_compare"))
    extra = tr("interactive.uncertain_marker") if "uncertain" in es_ and any(_yes(x) for x in es_["uncertain"]) else ""
    title = [tr("interactive.per_ampere", quantity=_cap(tr(_COMPARISON_QUANTITIES[g])), extra=extra)
             for g in groups] + ([tr("interactive.ratio_title")] if v is not None else [])
    fig = make_subplots(rows=n, cols=1, shared_xaxes=True, vertical_spacing=0.08, subplot_titles=title)
    colors = station_colors(es_["channel"].dropna())
    ticks = ["solid", "dash", "dot", "dashdot"]
    methods = {"fault": tr("interactive.fault_related"), "direct": tr("interactive.direct")}
    for r, grp in enumerate(groups, start=1):
        sub = inj[inj["quantity"] == grp]
        for j, a in enumerate(sorted(sub["distance_m"].dropna().unique(), reverse=True)):
            for mid, s_ in sub[sub["distance_m"] == a].groupby("measurement_id"):
                s_ = s_.sort_values("f_Hz")
                fig.add_trace(go.Scatter(x=s_["f_Hz"], y=s_["Z_Ohm"], mode="lines+markers",
                                         name=tr("interactive.injection_distance_id", distance=_short(a), id=int(mid)),
                                         line=dict(color="#4d4d4d", dash=ticks[j % 4], width=1.6),
                                         marker=dict(symbol="square", size=7, color="#4d4d4d"),
                                         hovertext=[_comparison_hover(x, tr("interactive.kind_injection"))
                                                    for _, x in s_.iterrows()], hoverinfo="text"), row=r, col=1)
        for meth_ in ("fault", "direct"):
            e = es_[(es_["quantity"] == grp) & (es_["type"] == meth_)]
            for channel, g in e.groupby("channel", sort=False):
                g = g.sort_values("f_Hz"); c = colors.get(channel, "#777777")
                y = g["Z_Ohm"].to_numpy(float)
                hov = [_comparison_hover(x, tr("interactive.kind_fault", channel=channel, method=methods[meth_]))
                       for _, x in g.iterrows()]
                if meth_ == "fault":
                    lo = np.fmin(np.asarray(g["Z_min_Ohm"], float), y); hi = np.fmax(np.asarray(g["Z_max_Ohm"], float), y)
                    lo = np.where(np.isfinite(lo), lo, y); hi = np.where(np.isfinite(hi), hi, y)
                    nm = tr("interactive.fault_channel_rze" if grp == QUANTITY_EPR
                            else "interactive.fault_channel_fault", channel=channel)
                    own_ = _legend_as_certain(fig, g, nm, channel, c, r)
                    fig.add_trace(go.Scatter(x=g["f_Hz"], y=y, mode="lines+markers", legendgroup=channel,
                                             name=nm, showlegend=not own_, line=dict(color=c, width=1.6),
                                             marker=_marker(g, c, 8),
                                             error_y=dict(type="data", symmetric=False, array=hi - y,
                                                          arrayminus=y - lo, thickness=1.3, width=0, color=c),
                                             hovertext=hov, hoverinfo="text"), row=r, col=1)
                else:
                    fig.add_trace(go.Scatter(x=g["f_Hz"], y=y, mode="markers", legendgroup=channel,
                                             name=tr("interactive.fault_channel_direct", channel=channel),
                                             visible="legendonly",
                                             marker=dict(size=8, color="white", line=dict(color=c, width=1.6)),
                                             hovertext=hov, hoverinfo="text"), row=r, col=1)
        for mid, s_ in gm[gm["quantity"] == grp].groupby("measurement_id"):
            fig.add_trace(go.Scatter(x=s_["f_Hz"], y=s_["Z_Ohm"], mode="markers",
                                     name=tr("report.fault_groundmeas", id=int(mid), distance=""),
                                     marker=dict(symbol="x", size=10, color="#111111"),
                                     hovertext=[_comparison_hover(x, tr("interactive.kind_groundmeas"))
                                                for _, x in s_.iterrows()], hoverinfo="text"), row=r, col=1)
        fig.update_yaxes(type="log", title_text="U/I in V/A", row=r, col=1)
        values = pd.concat([inj[inj["quantity"] == grp]["Z_Ohm"], es_[es_["quantity"] == grp]["Z_Ohm"],
                            gm[gm["quantity"] == grp]["Z_Ohm"]])
        _log_ticks(fig, values, r)
    if v is not None:
        for channel, g in v.groupby("channel", sort=False):
            g = g.sort_values("f_Hz")
            is_max = channel == MAX_PROBE
            name = (tr("report.probe_maximum", probes=" (%s)" % ", ".join(dict.fromkeys(g["probe"].astype(str))))
                    if is_max and "probe" in g else channel)
            hov = [tr("interactive.hover_ratio",
                      name=tr("interactive.name_probe", name=name, probe=x["probe"]) if is_max else channel,
                      f=_z(x["f_Hz"], 5), order=int(x["order"]), fault=_z(x["ratio_fault"], 3),
                      direct=_z(x["ratio_direct"], 3), z_fault=_z(x["Z_fault_Ohm"]),
                      z_injection=_z(x["Z_E_injection_Ohm"]),
                      id=int(x["injection_id"]), distance=_z(x["distance_injection_m"], 3),
                      match=i18n.value_label("distance_match", x.get("distance_match", "")),
                      uncertain=tr("interactive.hover_uncertain_fault_value") if _yes(x.get("uncertain")) else "")
                   for _, x in g.iterrows()]
            c = _color(colors, channel)
            fig.add_trace(go.Scatter(x=g["f_Hz"], y=g["ratio_fault"], mode="lines+markers",
                                     name=tr("interactive.ratio_name", name=name), legendgroup=channel,
                                     showlegend=is_max, line=dict(color=c, width=1.6), marker=_marker(g, c, 8),
                                     hovertext=hov, hoverinfo="text"), row=n, col=1)
        fig.update_yaxes(title_text=tr("report.fault_to_injection"), rangemode="tozero", row=n, col=1)
    fig.update_xaxes(title_text="f in Hz", row=n, col=1, rangemode="tozero")
    fig.update_layout(template=TEMPLATE, separators=_separators(), height=height_per_panel * n + 150,
                      hovermode="closest", title=tr("interactive.comparison_title"),
                      legend=dict(orientation="h", y=-0.06, yanchor="top", x=0, xanchor="left"),
                      margin=dict(t=90, b=150))
    return fig


def _remote(df: pd.DataFrame) -> pd.DataFrame:
    """Only the rows with a comparable probe distance ("equal"/"similar") – if there are none, all rows."""
    if "distance_match" not in df:
        return df
    remote = df[df["distance_match"].isin(["equal", "similar"])]
    return remote if len(remote) else df


def _color(colors: Dict[str, str], channel: str) -> str:
    """Colour of a probe (probe maximum: [`groundfault.report.COLOR_MAX`][groundfault.report.COLOR_MAX])."""
    return COLOR_MAX if channel == MAX_PROBE else colors.get(channel, "#777777")


def _short(v) -> str:
    """Short number without superfluous zeros (legends, ticks): 0,2 · 70 with a decimal comma or 0.2 · 70."""
    v = _num(v)
    return _fmt(v, "g") if np.isfinite(v) else "–"


def reduction_factor(spectrum, effective=None, probes: str = "maximum", height: Optional[int] = None,
                     impedances: bool = True, r_typical: Optional[Tuple[float, float]] = None,
                     remote_probes_only: Optional[bool] = None, direct: bool = False, trend: bool = True):
    """Reduction factor over the frequency (magnitude) – result of
    [`groundfault.earthing.reduction_factor`][groundfault.earthing.reduction_factor].

    Top r = r·Z_E/Z_E, drawn like the impedances: ● per order (earthing measurement measured), ○ earthing
    measurement interpolated, ⊗ uncertain, bar = span of the superposition methods; dotted the trend r ∝ f^b
    (``trend``); dashed the RMS value r_eff; grey bar at 50 Hz the typical range given by the user; ◇ grey the
    cross-check from the shield current; with ``direct`` also r from the values as measured (open circles). Bottom
    (``impedances``) in V/A: fault test r·Z_E = U_E/I_F (●), with the earth current Z_E = U_E/I_E (◇) and earthing
    measurement Z_E (■). Hover: values, origin, relevance at the reference current.

    Parameters
    ----------
    spectrum : pandas.DataFrame
        Reduction factor per order (first table of
        [`groundfault.earthing.reduction_factor`][groundfault.earthing.reduction_factor]).
    effective : pandas.DataFrame, optional
        RMS values r_eff (second table of
        [`groundfault.earthing.reduction_factor`][groundfault.earthing.reduction_factor]).
    probes : {"maximum", "remote", "all"}
        ``"maximum"`` the probe maximum (default), ``"remote"`` the probes with a comparable distance, ``"all"``
        all probes.
    height : int, optional
        Figure height in pixels (default: 820 with, 520 without the impedance panel).
    impedances : bool
        Add the panel with the compared impedances.
    r_typical : (float, float), optional
        Typical range of the reduction factor at 50 Hz drawn as a grey bar; default: the range stored in ``effective``
        (``r_typical`` of [`groundfault.earthing.reduction_factor`][groundfault.earthing.reduction_factor]), without
        one no bar.
    remote_probes_only : bool, optional
        Earlier interface: True → ``probes="remote"``, False → ``probes="all"``.
    direct : bool
        Also show r from the values as measured (``r_direct``, with background).
    trend : bool
        Show the trend r ∝ f^b (needs ``effective``).

    Returns
    -------
    plotly.graph_objects.Figure

    Raises
    ------
    ValueError
        If there is no reduction factor (no earthing measurement at the frequencies of the fault test).
    """
    _check_plotly()
    from .earthing import power_fit
    band = typical_band(r_typical, effective)
    if remote_probes_only is not None:                    # earlier interface
        probes = "remote" if remote_probes_only else "all"
    sp = spectrum[np.isfinite(pd.to_numeric(spectrum["r"], errors="coerce"))] if len(spectrum) else spectrum
    if not len(sp):
        raise ValueError(tr("report.no_reduction_factor"))
    sp = _probe_selection(sp, probes)
    colors = station_colors(spectrum["channel"])
    f_max = 1.08 * float(sp["f_Hz"].max())
    n = 2 if impedances else 1
    fig = make_subplots(rows=n, cols=1, shared_xaxes=True, vertical_spacing=0.12,
                        subplot_titles=([tr("interactive.rf_title_ratio"), tr("interactive.rf_title_impedances")][:n]))
    f1 = sp.loc[sp["order"] == 1, "f_Hz"]
    f1 = float(f1.iloc[0]) if len(f1) else 50.0
    if band:
        fig.add_trace(go.Scatter(x=[f1, f1], y=list(band), mode="lines", line=dict(color=COLOR_TYPICAL, width=10),
                                 name=tr("report.typical_at_50hz", low=_short(band[0]), high=_short(band[1])),
                                 hovertext=tr("interactive.typical_hover", low=_short(band[0]), high=_short(band[1])),
                                 hoverinfo="text"),
                      row=1, col=1)
    for (channel, mid), g in sp.groupby(["channel", "injection_id"], sort=False):
        g = g.sort_values("f_Hz"); c = _color(colors, channel)
        interp = _interpolated(g)
        sym = ["circle-x-open" if _yes(u) else ("circle-open" if i else "circle")
               for u, i in zip(g["uncertain"], interp)]
        name = _pair_text(channel, g)
        hov = [tr("interactive.hover_rf_point", name=name, f=_z(x["f_Hz"], 5), order=int(x["order"]),
                  i_f=_z(x["I_F_A"]),
                  probe=tr("interactive.probe_suffix", probe=x["probe"]) if channel == MAX_PROBE else "",
                  r=_z(x["r"], 3), r_direct=_z(x["r_direct"], 3), r_relative=_z(x.get("r_to_r_50Hz"), 3),
                  z_fault=_z(x["rZE_fault_Ohm"]), z_injection=_z(x["Z_E_injection_Ohm"]),
                  origin=x["injection_frequency"], d_fault=_z(x["distance_fault_m"], 3),
                  d_injection=_z(x["distance_injection_m"], 3),
                  match=i18n.value_label("distance_match", x["distance_match"]),
                  shield=tr("interactive.hover_shield", r=_z(x["r_shield"], 3),
                            share=_z(100 * _num(x.get("share_shield")), 2))
                  if np.isfinite(_num(x["r_shield"])) else "",
                  u_fault=_z(x.get("U_E_fault_at_reference_current_V"), 3),
                  u_injection=_z(x.get("U_E_injection_at_reference_current_V"), 3),
                  relevance=_z(x.get("assessment_relevance_pct"), 2),
                  uncertain=tr("interactive.hover_uncertain_fault_value") if _yes(x["uncertain"]) else "")
               for _, x in g.iterrows()]
        r_ = g["r"].to_numpy(float)
        error = None
        if {"r_min", "r_max"} <= set(g.columns):                  # span of the superposition methods
            lo = np.fmin(pd.to_numeric(g["r_min"], errors="coerce").to_numpy(float), r_)
            hi = np.fmax(pd.to_numeric(g["r_max"], errors="coerce").to_numpy(float), r_)
            lo = np.where(np.isfinite(lo), lo, r_); hi = np.where(np.isfinite(hi), hi, r_)
            if np.any(hi - lo > 0.01 * np.abs(r_)):
                error = dict(type="data", symmetric=False, array=hi - r_, arrayminus=r_ - lo, thickness=1.2,
                             width=0, color=c)
        fig.add_trace(go.Scatter(x=g["f_Hz"], y=g["r"], mode="lines+markers", name=name, legendgroup=name,
                                 line=dict(color=c, width=1.6), error_y=error,
                                 marker=dict(symbol=sym, size=9, color=c, line=dict(color=c, width=1.4)),
                                 hovertext=hov, hoverinfo="text"), row=1, col=1)
        if direct and "r_direct" in g:
            fig.add_trace(go.Scatter(x=g["f_Hz"], y=g["r_direct"], mode="markers", legendgroup=name,
                                     name=tr("report.r_direct"), marker=dict(symbol="circle-open", size=8, color=c),
                                     hovertemplate="f = %{x:.1f} Hz<br>r " + tr("interactive.direct_short")
                                                   + " = %{y:.3f}<extra></extra>"), row=1, col=1)
        if effective is not None and len(effective):
            e = effective[(effective["channel"] == channel) & (effective["injection_id"] == mid)]
            if len(e) and np.isfinite(_num(e["r_eff"].iloc[0])):
                x0 = e.iloc[0]
                hover = tr("interactive.hover_rf_effective", name=name, r_eff=_z(x0["r_eff"], 3), orders=x0["orders"],
                           coverage=_z(x0["I_F_coverage_pct"], 3), direct=_z(x0["r_eff_direct"], 3),
                           rms=_z(x0["r_eff_rms"], 3), shield=_z(x0["r_eff_shield"], 3), r_50=_z(x0.get("r_50Hz"), 3),
                           classification=i18n.value_label("classification_r_50Hz",
                                                           x0.get("classification_r_50Hz", "–")),
                           trend=i18n.value_label("trend_r_vs_f", x0.get("trend_r_vs_f", "–")),
                           exponent=_z(x0.get("exponent_r_vs_f"), 2), current=_z(x0.get("reference_current_A"), 3),
                           u_fault=_z(x0.get("U_E_fault_at_reference_current_V"), 3),
                           u_injection=_z(x0.get("U_E_injection_at_reference_current_V"), 3),
                           relevance=i18n.value_label("assessment_relevance", x0.get("assessment_relevance", "–")))
                fig.add_trace(go.Scatter(x=[0, f_max], y=[x0["r_eff"]] * 2, mode="lines", legendgroup=name,
                                         name="r<sub>eff</sub> = %s – %s" % (_z(x0["r_eff"], 3), name.split(" ↔ ")[0]),
                                         line=dict(color=c, width=1.2, dash="dash"),
                                         hovertext=hover, hoverinfo="text"), row=1, col=1)
                orders_ = str(x0.get("trend_orders") or "")
                chosen = [int(v) for v in orders_.replace(" ", "").split(",") if v.isdigit()]
                if trend and len(chosen) >= 2:                   # r ∝ f^b at the reliable orders
                    gt = g[g["order"].isin(chosen)]
                    c_, b_ = power_fit(gt["f_Hz"], gt["r"])
                    if np.isfinite(b_):
                        ft = np.geomspace(float(gt["f_Hz"].min()), float(gt["f_Hz"].max()), 50)
                        label = tr("report.trend_r", formula="r ∝ f<sup>b</sup>", b=_z(b_, 2), orders=orders_)
                        fig.add_trace(go.Scatter(x=ft, y=c_ * ft ** b_, mode="lines", legendgroup=name, name=label,
                                                 line=dict(color=c, width=1.2, dash="dot"),
                                                 hovertemplate=label + "<extra></extra>"), row=1, col=1)
    if "r_shield" in spectrum and spectrum["r_shield"].notna().any():
        s_ = spectrum.drop_duplicates("order").sort_values("f_Hz")
        s_ = s_[(s_["f_Hz"] <= f_max) & s_["r_shield"].notna()]
        if len(s_):
            fig.add_trace(go.Scatter(x=s_["f_Hz"], y=s_["r_shield"], mode="markers",
                                     name=tr("report.from_shield_current",
                                             quotient="|I<sub>F</sub>−I<sub>S</sub>|/|I<sub>F</sub>|"),
                                     marker=dict(symbol="diamond-open", size=12, color="#6b6b6b",
                                                 line=dict(width=1.4)),
                                     hovertemplate="f = %{x:.1f} Hz<br>" + tr("interactive.r_from_shield")
                                                   + " = %{y:.3f}<extra></extra>"),
                          row=1, col=1)
    fig.update_yaxes(title_text=tr("report.reduction_factor_axis", symbol="r"), rangemode="tozero", row=1, col=1)
    values = pd.concat([sp["r"], spectrum["r_shield"] if "r_shield" in spectrum else pd.Series(dtype=float),
                        pd.Series(list(band or ()), dtype=float)])
    w = np.asarray(pd.to_numeric(values, errors="coerce"), float); w = w[np.isfinite(w) & (w > 0)]
    if w.size and w.max() / w.min() > 20:                          # far apart: logarithmic
        _log_ticks(fig, w, 1)
    if impedances:
        all_ = _probe_selection(spectrum[spectrum["f_Hz"] <= f_max], probes)
        pairs = set(map(tuple, sp[["channel", "injection_id"]].drop_duplicates().to_numpy().tolist()))
        values_z = []
        fault_test = tr("interactive.fault_test")
        for (channel, mid), g in all_.groupby(["channel", "injection_id"], sort=False):
            if (channel, mid) not in pairs:
                continue
            g = g.sort_values("f_Hz"); c = _color(colors, channel)
            left = _pair_text(channel, g).split(" ↔ ")[0]
            y = pd.to_numeric(g["rZE_fault_Ohm"], errors="coerce")
            fig.add_trace(go.Scatter(x=g["f_Hz"], y=y, mode="lines+markers",
                                     name=tr("report.fault_quotient", name=left,
                                             quotient="r·Z<sub>E</sub> = U<sub>E</sub>/I<sub>F</sub>"),
                                     line=dict(color=c, width=1.6), marker=_marker(g, c, 8),
                                     hovertemplate="f = %{x:.1f} Hz<br>" + fault_test
                                                   + " r·Z<sub>E</sub> = U<sub>E</sub>/I<sub>F</sub> = %{y:.4g} V/A"
                                                     "<extra></extra>"),
                          row=2, col=1)
            values_z += list(y)
            if "Z_E_earth_current_Ohm" in g:
                ie = pd.to_numeric(g["Z_E_earth_current_Ohm"], errors="coerce")
                if ie.notna().any() and np.nanmax(np.abs(ie / y - 1.0)) > 0.05:
                    fig.add_trace(go.Scatter(x=g["f_Hz"], y=ie, mode="lines+markers",
                                             name=tr("report.fault_quotient", name=left,
                                                     quotient="Z<sub>E</sub> = U<sub>E</sub>/I<sub>E</sub>"),
                                             line=dict(color=c, width=1.0, dash="dot"),
                                             marker=dict(symbol="diamond-open", size=9, color=c),
                                             hovertemplate="f = %{x:.1f} Hz<br>Z<sub>E</sub> = U<sub>E</sub>/I<sub>E</sub> (I<sub>E</sub> "
                                                           "= I<sub>F</sub> − I<sub>S</sub>) = %{y:.4g} V/A"
                                                           "<extra></extra>"), row=2, col=1)
                    values_z += list(ie)
        for mid, g in sp.groupby("injection_id", sort=False):
            g = g.drop_duplicates("order").sort_values("f_Hz")
            interp = _interpolated(g)
            fig.add_trace(go.Scatter(x=g["f_Hz"], y=g["Z_E_injection_Ohm"], mode="lines+markers",
                                     name=tr("report.injection_ze", symbol="Z<sub>E</sub>",
                                             label=tr("report.injection_id", id=int(mid),
                                                      distance=" (%s m)" % _short(g["distance_injection_m"].iloc[0]))),
                                     line=dict(color="#4d4d4d", dash="dash", width=1.4),
                                     marker=dict(symbol=["square-open" if i else "square" for i in interp], size=8,
                                                 color="#4d4d4d"),
                                     hovertext=[tr("interactive.hover_injection", id=int(mid), f=_z(x["f_Hz"], 5),
                                                   z=_z(x["Z_E_injection_Ohm"]), origin=x["injection_frequency"])
                                                for _, x in g.iterrows()],
                                     hoverinfo="text"), row=2, col=1)
            values_z += list(g["Z_E_injection_Ohm"])
        _log_ticks(fig, values_z, 2)
        fig.update_yaxes(title_text="r·Z<sub>E</sub>, Z<sub>E</sub> in V/A", row=2, col=1)
    fig.update_xaxes(title_text="f in Hz", range=[0, f_max], row=n, col=1)
    fig.update_layout(template=TEMPLATE, separators=_separators(), height=height or (820 if impedances else 520),
                      hovermode="closest", title=tr("interactive.rf_title"),
                      legend=dict(orientation="h", y=-0.1, yanchor="top", x=0, xanchor="left"),
                      margin=dict(t=90, b=150))
    return fig


def lv_network(lv_table, check=None, all_probes: bool = False, height_per_panel: int = 330):
    """Current into the LV network and earthing impedance of the LV network (table ``station_lv_network``) with the
    parallel-connection check.

    Top |Z| in V/A: Z_E,LV ●, from the fault test r·Z_E = max(U_E)/I_F ◇ – and with a shield current
    Z_E = ΔU_E/I_E △ if visibly different –, earthing measurement Z_E ■. Bottom the currents in A: I_LV ●, ▲ before / ▼ after
    the transformer star point, fault current □, earth current ◇.

    Parameters
    ----------
    lv_table : pandas.DataFrame
        Table ``station_lv_network`` of the result.
    check : pandas.DataFrame, optional
        Check against the earthing measurement (first table of
        [`groundfault.earthing.check_lv_network`][groundfault.earthing.check_lv_network]).
    all_probes : bool
        All probes; otherwise only the probe maximum (``max(UE)``; without such rows the farthest probe).
    height_per_panel : int
        Height per panel in pixels.

    Returns
    -------
    plotly.graph_objects.Figure

    Raises
    ------
    ValueError
        If there is no LV network evaluation (PEN currents).
    """
    _check_plotly()
    if lv_table is None or not len(lv_table):
        raise ValueError(tr("report.no_lv_network"))
    so = lv_table
    if not all_probes:
        if (so["channel"] == MAX_PROBE).any():
            so = so[so["channel"] == MAX_PROBE]
        elif so["distance_m"].notna().any():
            so = so[so["distance_m"] == so["distance_m"].max()]
    colors = station_colors(so["channel"])
    lv, lv_i = tr("report.sub_lv_impedance"), tr("report.sub_lv_current")
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
                        subplot_titles=[tr("interactive.lv_title_impedance"), tr("interactive.lv_title_current")])
    values_z = []
    for channel, g in so.groupby("channel", sort=False):
        g = g.sort_values("f_Hz"); c = _color(colors, channel)
        if channel == MAX_PROBE:
            s = ", ".join(dict.fromkeys(str(x) for x in g["probe"].dropna())) if "probe" in g else ""
            name, ref_label = tr("report.probe_maximum", probes=" (%s)" % s if s else ""), "max(U<sub>E</sub>)"
        else:
            name, ref_label = channel, "U<sub>E</sub>"
        hov = [tr("interactive.hover_lv", name=name,
                  probe=tr("interactive.probe_in_parentheses", probe=x["probe"])
                  if channel == MAX_PROBE and "probe" in x else "",
                  f=_z(x["f_Hz"], 5), order=int(x["order"]), lv=lv, lv_i=lv_i, z=_z(x["Z_E_LV_Ohm"]),
                  angle=_z(x["Z_E_LV_angle_deg"], 3), uncertainty=_z(x["Z_E_LV_uncertainty_pct"], 2),
                  du=_z(x["U_E_fault_V"]), i_lv=_z(x["I_LV_A"]), share=_z(100 * _num(x["share_I_LV"]), 3),
                  reference=ref_label, z_fault=_z(x.get("rZE_fault_Ohm")),
                  check=i18n.value_label("parallel_check", x["parallel_check"]),
                  z_total=_z(x["Z_E_earth_current_Ohm"]), ratio=_z(x["I_LV_to_I_E"], 3),
                  earth_check=i18n.value_label("earth_current_check", x.get("earth_current_check", "–")),
                  uncertain=tr("interactive.hover_uncertain") if _yes(x["uncertain"]) else "")
               for _, x in g.iterrows()]
        fig.add_trace(go.Scatter(x=g["f_Hz"], y=g["Z_E_LV_Ohm"], mode="lines+markers",
                                 name="Z<sub>E,%s</sub> %s" % (lv, name), line=dict(color=c, width=1.6),
                                 marker=_marker(g, c, 8), hovertext=hov, hoverinfo="text"), row=1, col=1)
        values_z += list(g["Z_E_LV_Ohm"])
        z_f = pd.to_numeric(g["rZE_fault_Ohm"], errors="coerce") if "rZE_fault_Ohm" in g else None
        if z_f is not None and z_f.notna().any():
            fig.add_trace(go.Scatter(x=g["f_Hz"], y=z_f, mode="lines+markers",
                                     name=tr("report.fault_rze", symbol="r·Z<sub>E</sub>",
                                             quotient="%s/I<sub>F</sub>" % ref_label),
                                     line=dict(color=c, width=1.0, dash="dot"),
                                     marker=dict(symbol="diamond-open", size=9, color=c),
                                     hovertemplate="f = %{x:.1f} Hz<br>"
                                                   + tr("report.fault_rze", symbol="r·Z<sub>E</sub>",
                                                        quotient="%{y:.4g} V/A")
                                                   + "<extra></extra>"), row=1, col=1)
            values_z += list(z_f)
        with_s = str(g["total_earthing_reference"].iloc[0]).startswith("I_E")
        z_g = pd.to_numeric(g["Z_E_earth_current_Ohm"], errors="coerce")
        if with_s and (z_f is None or not z_f.notna().any() or np.nanmax(np.abs(z_g / z_f - 1.0)) > 0.05):
            fig.add_trace(go.Scatter(x=g["f_Hz"], y=z_g, mode="lines+markers",
                                     name=tr("report.fault_rze", symbol="Z<sub>E</sub>",
                                             quotient="%s/I<sub>E</sub>" % ref_label),
                                     line=dict(color=c, width=1.0, dash="dot"),
                                     marker=dict(symbol="triangle-up-open", size=9, color=c),
                                     hovertemplate="f = %{x:.1f} Hz<br>Z<sub>E</sub> = ΔU<sub>E</sub>/I<sub>E</sub> = "
                                                   "%{y:.4g} V/A"
                                                   "<extra></extra>"), row=1, col=1)
            values_z += list(z_g)
    if check is not None and len(check):
        pr = check[check["channel"].isin(set(so["channel"]))]
        pr = pr if (pr["channel"] == MAX_PROBE).any() else _remote(pr)
        for (channel, mid), g in pr.groupby(["channel", "injection_id"], sort=False):
            g = g.sort_values("f_Hz")
            st = "injection_comparison" if "injection_comparison" in g else "parallel_check"
            un = "comparison_uncertainty_pct" if "comparison_uncertainty_pct" in g else "check_uncertainty_pct"
            hov = [tr("interactive.hover_lv_check", id=int(mid), distance=_z(x["distance_injection_m"], 3),
                      f=_z(x["f_Hz"], 5), z=_z(x["Z_E_injection_Ohm"]), origin=x["injection_frequency"], lv=lv,
                      ratio=_z(x["Z_LV_to_Z_E"], 3), check=i18n.value_label(st, x[st]), uncertainty=_z(x.get(un), 2))
                   for _, x in g.iterrows()]
            fig.add_trace(go.Scatter(x=g["f_Hz"], y=g["Z_E_injection_Ohm"], mode="lines+markers",
                                     name=tr("report.injection_id", id=int(mid), distance=""),
                                     line=dict(color="#4d4d4d", dash="dash", width=1.4),
                                     marker=dict(symbol="square", size=7, color="#4d4d4d"), hovertext=hov,
                                     hoverinfo="text"), row=1, col=1)
            values_z += list(g["Z_E_injection_Ohm"])
    _log_ticks(fig, values_z, 1)
    g = so[so["channel"] == so["channel"].iloc[0]].sort_values("f_Hz")
    i_lv = "I<sub>%s</sub>" % lv_i
    fig.add_trace(go.Scatter(x=g["f_Hz"], y=g["I_LV_A"], mode="lines+markers",
                             name=tr("interactive.lv_current", symbol=i_lv),
                             line=dict(color="#111111", width=1.6), marker=dict(size=8, color="#111111"),
                             hovertemplate="f = %{x:.1f} Hz<br>" + i_lv + " = %{y:.4g} A<extra></extra>"),
                  row=2, col=1)
    values_i = list(g["I_LV_A"])
    for sp_, sym, key in (("I_LV_feeders_A", "triangle-up-open", "report.before_star_point"),
                          ("I_LV_busbar_A", "triangle-down-open", "report.after_star_point")):
        if sp_ in g and g[sp_].notna().any():
            tx = tr(key)
            fig.add_trace(go.Scatter(x=g["f_Hz"], y=g[sp_], mode="markers", name=tx,
                                     marker=dict(symbol=sym, size=10, color="#111111"),
                                     hovertemplate="f = %{x:.1f} Hz<br>" + tx + ": %{y:.4g} A<extra></extra>"),
                          row=2, col=1)
            values_i += list(g[sp_])
    fig.add_trace(go.Scatter(x=g["f_Hz"], y=g["I_F_A"], mode="markers",
                             name=tr("report.fault_current", symbol="I<sub>F</sub>"),
                             marker=dict(symbol="square-open", size=9, color="#6b6b6b"),
                             hovertemplate="f = %{x:.1f} Hz<br>I<sub>F</sub> = %{y:.4g} A<extra></extra>"), row=2, col=1)
    values_i += list(g["I_F_A"])
    if str(g["total_earthing_reference"].iloc[0]).startswith("I_E"):
        i_e = (g["I_LV_A"] / g["I_LV_to_I_E"]).where(g["I_LV_to_I_E"] > 0)
        if np.nanmax(np.abs(i_e / g["I_F_A"] - 1.0)) > 0.05:
            fig.add_trace(go.Scatter(x=g["f_Hz"], y=i_e, mode="markers",
                                     name=tr("report.earth_current",
                                             symbol="I<sub>E</sub> = I<sub>F</sub> − I<sub>S</sub>"),
                                     marker=dict(symbol="diamond-open", size=9, color="#6b6b6b"),
                                     hovertemplate="f = %{x:.1f} Hz<br>I<sub>E</sub> = %{y:.4g} A<extra></extra>"),
                          row=2, col=1)
            values_i += list(i_e)
    _log_ticks(fig, values_i, 2)
    fig.update_yaxes(title_text="|Z| in V/A", row=1, col=1)
    fig.update_yaxes(title_text="I in A", row=2, col=1)
    fig.update_xaxes(title_text="f in Hz", rangemode="tozero", row=2, col=1)
    fig.update_layout(template=TEMPLATE, separators=_separators(), height=2 * height_per_panel + 170,
                      hovermode="closest", title=tr("interactive.lv_title", lv=lv, lv_i=lv_i),
                      legend=dict(orientation="h", y=-0.08, yanchor="top", x=0, xanchor="left"),
                      margin=dict(t=90, b=140))
    return fig
