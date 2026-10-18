# -*- coding: utf-8 -*-
"""Equivalent circuits of the forecast documentation (SVG, English and German labels).

Usage::

    python docs/scripts/forecast_circuits.py [--out docs/assets] [--lang en|de|both]

Writes ``forecast_fault_loop``, ``forecast_sequence_networks``, ``forecast_node_rule``, ``forecast_recording`` and
``forecast_hv_network``
(``…_de.svg`` with German labels). The drawings are schematic and contain no data of real networks.
"""
import argparse
import os
import re

WIRE = "#5f5e5a"
INK = "#2c2c2a"
TEXT = "#3d3d3a"
BOX_FILL = "#f1efe8"
BOX_STROKE = "#888780"
MEASURED = "#0f6e56"
SOURCE = "#993c1d"
FONT = "DejaVu Sans, Helvetica, Arial, sans-serif"


# =========================================================================== drawing helpers
class Svg:
    def __init__(self, width, height, title, desc):
        self.w, self.h = width, height
        self.parts = []
        self.title, self.desc = title, desc

    def add(self, s):
        self.parts.append(s)

    # ---------------------------------------------------------------- text with sub- and superscripts
    @staticmethod
    def _rich(text, size):
        """``Z_q``, ``U_{q,m}``, ``X^{2}`` → tspans shifted with ``dy`` (portable to every SVG renderer)."""
        out = []
        pos = 0
        small = max(int(size * 0.75), 8)
        shift = 0.0                                      # current vertical offset from the baseline
        for m in re.finditer(r"([_^])(\{[^}]*\}|[A-Za-z0-9αβγ]+)", text):
            plain = text[pos:m.start()]
            if plain:
                out.append('<tspan dy="%g">%s</tspan>' % (-shift, _esc(plain)) if shift else _esc(plain))
                shift = 0.0
            body = m.group(2)
            body = body[1:-1] if body.startswith("{") else body
            target = size * 0.3 if m.group(1) == "_" else -size * 0.4
            out.append('<tspan dy="%g" font-size="%d">%s</tspan>' % (target - shift, small, _esc(body)))
            shift = target
            pos = m.end()
        rest = text[pos:]
        if rest:
            out.append('<tspan dy="%g">%s</tspan>' % (-shift, _esc(rest)) if shift else _esc(rest))
        return "".join(out)

    def text(self, x, y, text, size=13, anchor="middle", color=TEXT, weight=None, italic=False):
        w = ' font-weight="bold"' if weight else ""
        it = ' font-style="italic"' if italic else ""
        self.add('<text x="%g" y="%g" font-size="%d" fill="%s" text-anchor="%s"%s%s>%s</text>'
                 % (x, y, size, color, anchor, w, it, self._rich(text, size)))

    # ---------------------------------------------------------------- elements
    def wire(self, d, color=WIRE, width=1.2, dash=None):
        da = ' stroke-dasharray="%s"' % dash if dash else ""
        self.add('<path d="%s" fill="none" stroke="%s" stroke-width="%g"%s stroke-linejoin="round"/>'
                 % (d, color, width, da))

    def box(self, x, y, w, h, label=None, size=13, fill=BOX_FILL, stroke=BOX_STROKE, dash=None):
        da = ' stroke-dasharray="%s"' % dash if dash else ""
        self.add('<rect x="%g" y="%g" width="%g" height="%g" rx="4" fill="%s" stroke="%s" stroke-width="0.8"%s/>'
                 % (x, y, w, h, fill, stroke, da))
        if label:
            self.text(x + w / 2, y + h / 2 + size * 0.36, label, size)

    def frame(self, x, y, w, h, color=BOX_STROKE):
        self.add('<rect x="%g" y="%g" width="%g" height="%g" rx="8" fill="none" stroke="%s" stroke-width="0.9" '
                 'stroke-dasharray="5 4"/>' % (x, y, w, h, color))

    def source(self, x, y, r=16, sym="~", color=WIRE):
        self.add('<circle cx="%g" cy="%g" r="%g" fill="#ffffff" stroke="%s" stroke-width="1.3"/>' % (x, y, r, color))
        self.text(x, y + 5, sym, 15, color=color)

    def current_source(self, x, y, r=15, up=True, color=WIRE):
        self.add('<circle cx="%g" cy="%g" r="%g" fill="#ffffff" stroke="%s" stroke-width="1.3"/>' % (x, y, r, color))
        y1, y2 = (y + r * 0.6, y - r * 0.6) if up else (y - r * 0.6, y + r * 0.6)
        self.arrow(x, y1, x, y2, color=color)

    def arrow(self, x1, y1, x2, y2, color=TEXT, width=1.5):
        self.add('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="%s" stroke-width="%g" marker-end="url(#arrow)"/>'
                 % (x1, y1, x2, y2, color, width))

    def capacitor(self, x, y, horizontal=False, gap=6, plate=22):
        """Capacitor centred at (x, y) on a vertical (default) or horizontal wire."""
        if horizontal:
            self.wire("M%g %g V%g M%g %g V%g" % (x - gap / 2, y - plate / 2, y + plate / 2, x + gap / 2,
                                                 y - plate / 2, y + plate / 2), color=INK, width=2)
        else:
            self.wire("M%g %g H%g M%g %g H%g" % (x - plate / 2, y - gap / 2, x + plate / 2, x - plate / 2,
                                                 y + gap / 2, x + plate / 2), color=INK, width=2)

    def inductor(self, x, y, n=4, r=5, vertical=True):
        """Coil from (x, y) downwards (vertical) with n turns of radius r."""
        d = "M%g %g" % (x, y)
        for _ in range(n):
            d += " a%g %g 0 0 1 0 %g" % (r, r, 2 * r) if vertical else " a%g %g 0 0 1 %g 0" % (r, r, 2 * r)
        self.wire(d, color=INK, width=1.4)

    def earth(self, x, y):
        self.wire("M%g %g H%g M%g %g H%g M%g %g H%g" % (x - 11, y, x + 11, x - 7, y + 4, x + 7, x - 3, y + 8, x + 3),
                  color=WIRE, width=1.3)

    def busbar(self, x1, y1, x2, y2, width=3.5):
        self.add('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="%s" stroke-width="%g"/>' % (x1, y1, x2, y2, INK, width))

    def dot(self, x, y, r=2.6, color=WIRE):
        self.add('<circle cx="%g" cy="%g" r="%g" fill="%s"/>' % (x, y, r, color))

    def ct(self, x, y, r=7, horizontal=True, color=MEASURED):
        """Current transformer (ring) on a wire."""
        self.add('<ellipse cx="%g" cy="%g" rx="%g" ry="%g" fill="none" stroke="%s" stroke-width="1.6"/>'
                 % (x, y, r * (0.55 if horizontal else 1.0), r * (1.0 if horizontal else 0.55), color))

    def save(self, path):
        head = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" '
                'font-family="%s">\n  <title>%s</title>\n  <desc>%s</desc>\n  <defs>\n    <marker id="arrow" '
                'viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
                '\n      <path d="M2 1L8 5L2 9" fill="none" stroke="#3d3d3a" stroke-width="1.5" stroke-linecap="round" '
                'stroke-linejoin="round"/>\n    </marker>\n  </defs>\n  <rect x="0" y="0" width="%d" height="%d" '
                'fill="#ffffff"/>\n' % (self.w, self.h, self.w, self.h, FONT, _esc(self.title), _esc(self.desc),
                                        self.w, self.h))
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(head + "\n".join("  " + p for p in self.parts) + "\n</svg>\n")


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# =========================================================================== figure 1: fault loop per order
LOOP = {
    "en": dict(title="Fault loop of a single-line-to-earth fault per harmonic order",
               desc="The positive-, negative- and zero-sequence networks seen from the busbar are connected in series "
                    "with three times the fault impedance; for a fault behind a line the series impedances of the line "
                    "add to each sequence network. Below the reduced loop: source U_q + U_s, source impedance Z_q, the "
                    "line contribution Z_qL and Z_F.",
               pos="positive sequence", neg="negative sequence", zero="zero sequence", fault="fault",
               line="line (fault in the network)", reduced="Reduced loop per order m",
               eq1="I_F = (U_q + U_s)/(Z_q + Z_qL + Z_F)", eq2="Z_q = (Z_0 + Z_1 + Z_2)/3,   Z_qL = (2·Z_1L + Z_0L)/3",
               eq3="U_q = −Σ p_k·U_{k,pre}   (pre-fault voltage of the faulted phase)",
               note1="U_s: source that arises with the fault",
               note2="(zero sequence: coils, VTs, earthing transformers)"),
    "de": dict(title="Fehlerschleife eines einpoligen Erdschlusses je Oberschwingungsordnung",
               desc="Mit-, Gegen- und Nullsystem, von der Sammelschiene aus gesehen, liegen in Reihe mit der dreifachen "
                    "Fehlerimpedanz; bei einem Fehler hinter einer Leitung kommen deren Längsimpedanzen in jedem System "
                    "hinzu. Unten die reduzierte Schleife: Quelle U_q + U_s, Quellimpedanz Z_q, Leitungsanteil Z_qL "
                    "und Z_F.",
               pos="Mitsystem", neg="Gegensystem", zero="Nullsystem", fault="Fehler",
               line="Leitung (Fehler im Netz)", reduced="Reduzierte Schleife je Ordnung m",
               eq1="I_F = (U_q + U_s)/(Z_q + Z_qL + Z_F)", eq2="Z_q = (Z_0 + Z_1 + Z_2)/3,   Z_qL = (2·Z_1L + Z_0L)/3",
               eq3="U_q = −Σ p_k·U_{k,vor}   (Vorfehlerspannung des Fehlerleiters)",
               note1="U_s: mit dem Fehler entstehende Quelle",
               note2="(Nullsystem: Spulen, Spannungswandler, Sternpunktbildner)"),
}


def fault_loop(lang, path):
    L = LOOP[lang]
    s = Svg(780, 470, L["title"], L["desc"])
    y = 104
    # three sequence networks, each: source, network impedance, line impedance (dashed)
    blocks = [(30, L["pos"], "−p_1·U_{1,pre}" if lang == "en" else "−p_1·U_{1,vor}", "Z_1", "Z_1L"),
              (240, L["neg"], "−p_2·U_{2,pre}" if lang == "en" else "−p_2·U_{2,vor}", "Z_2", "Z_2L"),
              (450, L["zero"], "−p_0·U_{0,pre} + U_s" if lang == "en" else "−p_0·U_{0,vor} + U_s", "Z_0", "Z_0L")]
    s.wire("M14 %g V290 H730 V%g" % (y, y + 150))
    for x0, title, src, z, zl in blocks:
        s.frame(x0, 40, 196, 120)
        s.text(x0 + 98, 62, title, 13, weight=True, color=INK)
        s.wire("M%g %g H%g" % (x0 - 16 if x0 > 30 else 14, y, x0 + 26))
        s.source(x0 + 42, y)
        s.wire("M%g %g H%g" % (x0 + 58, y, x0 + 80))
        s.box(x0 + 80, y - 12, 50, 24, z)
        s.wire("M%g %g H%g" % (x0 + 130, y, x0 + 140))
        s.box(x0 + 140, y - 12, 44, 24, zl, dash="4 3")
        s.wire("M%g %g H%g" % (x0 + 184, y, x0 + 212))
        s.text(x0 + 98, y + 40, src, 12, color=SOURCE)
    s.wire("M662 %g H730 V%g" % (y, y + 98))
    s.box(716, y + 98, 28, 52, None)
    s.text(730, y + 129, "3Z_F", 12)
    s.text(708, y + 128, L["fault"], 12, color=INK, weight=True, anchor="end")
    s.arrow(420, 290, 340, 290)
    s.text(380, 282, "I_F/3", 13)
    s.text(450, 182, "– – –  " + L["line"], 11, anchor="start", color=BOX_STROKE)
    # reduced loop
    s.text(30, 336, L["reduced"], 13, anchor="start", weight=True, color=INK)
    s.wire("M90 386 V440 H360 V370")
    s.source(90, 386 - 16, 14)
    s.wire("M90 356 V352 H120")
    s.box(120, 340, 56, 24, "Z_q", 12)
    s.wire("M176 352 H192")
    s.box(192, 340, 56, 24, "Z_qL", 12, dash="4 3")
    s.wire("M248 352 H264")
    s.box(264, 340, 56, 24, "Z_F", 12)
    s.wire("M320 352 H360 V370")
    s.text(66, 368, "U_q", 12, color=SOURCE, anchor="end")
    s.text(66, 384, "+ U_s", 12, color=SOURCE, anchor="end")
    s.arrow(260, 440, 190, 440)
    s.text(225, 432, "I_F", 12)
    s.text(400, 360, L["eq1"], 13, anchor="start")
    s.text(400, 384, L["eq2"], 12, anchor="start")
    s.text(400, 406, L["eq3"], 12, anchor="start")
    s.text(400, 430, L["note1"], 11, anchor="start", color=SOURCE)
    s.text(400, 446, L["note2"], 11, anchor="start", color=SOURCE)
    s.save(path)


# =========================================================================== figure 2: sequence networks at the busbar
SEQNET = {
    "en": dict(title="What the sequence impedances at the busbar contain",
               desc="Positive and negative sequence: the upstream impedance Z_up of transformer and HV network (network "
                    "feeder Z_Q in parallel with the capacitance and the loads of the HV network) in parallel with the "
                    "MV network Z_down (cable capacitance, loads, harmonic sources). Zero sequence: earth "
                    "capacitances, partly behind the series impedance of long feeders, losses, Petersen coils with a "
                    "nonlinear part and further nonlinear paths such as voltage transformers.",
               a="(a) positive and negative sequence (k = 1, 2)", b="(b) zero sequence",
               hv="HV network", tr="transformer", mv="MV network", bus="MV busbar",
               up="Z_up = Z_T + Z_HV", hvz="Z_HV = Z_Q ∥ C_HV ∥ loads", down="Z_down",
               z1="Z_k = Z_up ∥ Z_down   (k = 1, 2)",
               res="parallel resonances: HV network m_p ≈ √(X_{C,HV,1}/X_{Q,1}), MV busbar m_r ≈ √(X_{C,1}/X_{up,1})",
               chv="C_HV", load="loads", cab="C_1", src="I_h",
               ce="C_E", feeder="feeder", gl="G_0", coil="coil", nl="I_Nh", vt="VTs",
               z0="Z_0 = 1/(Y_C + G_0 + Y_L)", bg="U_bg"),
    "de": dict(title="Was die Sequenzimpedanzen an der Sammelschiene enthalten",
               desc="Mit- und Gegensystem: die Vorimpedanz Z_vor von Trafo und HS-Netz (Netzeinspeisung Z_Q parallel "
                    "zur Kapazität und zu den Lasten des HS-Netzes) parallel zum MS-Netz Z_MS (Kabelkapazität, Lasten, "
                    "Oberschwingungsquellen). Nullsystem: Erdkapazitäten, teils hinter der Längsimpedanz langer "
                    "Abgänge, Verluste, Erdschlussspulen mit nichtlinearem Anteil und weitere nichtlineare Pfade wie "
                    "Spannungswandler.",
               a="(a) Mit- und Gegensystem (k = 1, 2)", b="(b) Nullsystem",
               hv="HS-Netz", tr="Trafo", mv="MS-Netz", bus="MS-Sammelschiene",
               up="Z_vor = Z_T + Z_HS", hvz="Z_HS = Z_Q ∥ C_HS ∥ Lasten", down="Z_MS",
               z1="Z_k = Z_vor ∥ Z_MS   (k = 1, 2)",
               res="Parallelresonanzen: HS-Netz m_p ≈ √(X_{C,HS,1}/X_{Q,1}), MS-Sammelschiene m_r ≈ "
                   "√(X_{C,1}/X_{vor,1})",
               chv="C_HS", load="Lasten", cab="C_1", src="I_OS",
               ce="C_E", feeder="Abgang", gl="G_0", coil="Spule", nl="I_Nh", vt="Spannungswandler",
               z0="Z_0 = 1/(Y_C + G_0 + Y_L)", bg="U_VB"),
}


def sequence_networks(lang, path):
    L = SEQNET[lang]
    s = Svg(780, 540, L["title"], L["desc"])
    # ---------------- (a) positive / negative sequence
    s.text(20, 28, L["a"], 13, anchor="start", weight=True, color=INK)
    yb, ye = 80, 200                           # upper wire, return
    s.text(105, 56, L["hv"], 12, color=INK, weight=True)
    s.text(295, 56, L["tr"], 12, color=INK, weight=True)
    s.text(550, 56, L["mv"], 12, color=INK, weight=True)
    s.source(40, 140)
    s.text(62, 145, L["bg"], 12, color=SOURCE, anchor="start")
    s.wire("M40 124 V%g H70" % yb)
    s.box(70, yb - 12, 60, 24, "Z_Q")
    s.wire("M130 %g H260" % yb)
    s.wire("M40 156 V%g H660" % ye)
    s.dot(160, yb)
    s.wire("M160 %g V122" % yb)
    s.capacitor(160, 128)
    s.wire("M160 134 V%g" % ye)
    s.text(176, 132, L["chv"], 12, anchor="start")
    s.dot(225, yb)
    s.wire("M225 %g V112" % yb)
    s.box(213, 112, 24, 40, None)
    s.wire("M225 152 V%g" % ye)
    s.text(244, 136, L["load"], 11, anchor="start")
    s.box(260, yb - 12, 70, 24, "Z_T")
    s.wire("M330 %g H660" % yb)
    s.busbar(400, yb - 22, 400, yb + 22)
    s.text(400, yb - 28, L["bus"], 11, color=INK)
    s.dot(460, yb)
    s.wire("M460 %g V122" % yb)
    s.capacitor(460, 128)
    s.wire("M460 134 V%g" % ye)
    s.text(476, 132, L["cab"], 12, anchor="start")
    s.dot(530, yb)
    s.wire("M530 %g V112" % yb)
    s.box(518, 112, 24, 40, None)
    s.wire("M530 152 V%g" % ye)
    s.text(548, 136, L["load"], 11, anchor="start")
    s.dot(620, yb)
    s.wire("M620 %g V124" % yb)
    s.current_source(620, 138, 14)
    s.wire("M620 152 V%g" % ye)
    s.text(640, 142, L["src"], 12, anchor="start", color=SOURCE)
    # brackets and relations
    s.wire("M70 222 V230 H330 V222", color=BOX_STROKE, width=0.8)
    s.text(200, 248, L["up"], 13)
    s.text(200, 266, L["hvz"], 11)
    s.wire("M440 222 V230 H660 V222", color=BOX_STROKE, width=0.8)
    s.text(550, 248, L["down"], 13)
    s.text(390, 296, L["z1"], 13)
    s.text(390, 318, L["res"], 11)
    # ---------------- (b) zero sequence
    y0 = 340
    s.text(20, y0 + 10, L["b"], 13, anchor="start", weight=True, color=INK)
    yt = y0 + 50
    ye2 = y0 + 150
    s.busbar(60, yt - 18, 60, yt + 18)
    s.text(60, yt - 24, "U_0", 12, color=MEASURED)
    s.wire("M60 %g H690" % yt)
    s.wire("M60 %g H690" % ye2)
    s.earth(380, ye2 + 4)
    # earth capacitance at the busbar
    s.dot(120, yt)
    s.wire("M120 %g V%g" % (yt, yt + 44))
    s.capacitor(120, yt + 50)
    s.wire("M120 %g V%g" % (yt + 56, ye2))
    s.text(136, yt + 54, L["ce"], 12, anchor="start")
    # feeder: series impedance, then earth capacitance
    s.dot(190, yt)
    s.wire("M190 %g V%g" % (yt, yt + 14))
    s.box(178, yt + 14, 24, 34, None)
    s.text(208, yt + 36, "Z_0L", 11, anchor="start")
    s.wire("M190 %g V%g" % (yt + 48, yt + 62))
    s.capacitor(190, yt + 68)
    s.wire("M190 %g V%g" % (yt + 74, ye2))
    s.text(206, yt + 90, L["ce"] + " (" + L["feeder"] + ")", 11, anchor="start")
    # losses
    s.dot(330, yt)
    s.wire("M330 %g V%g" % (yt, yt + 30))
    s.box(318, yt + 30, 24, 40, None)
    s.wire("M330 %g V%g" % (yt + 70, ye2))
    s.text(348, yt + 54, L["gl"], 12, anchor="start")
    # coil with nonlinear part
    s.dot(440, yt)
    s.wire("M440 %g V%g" % (yt, yt + 26))
    s.ct(440, yt + 16, horizontal=False)
    s.text(452, yt + 20, "I_coil" if lang == "en" else "I_Spule", 11, anchor="start", color=MEASURED)
    s.inductor(440, yt + 30, n=4, r=6)
    s.wire("M440 %g V%g" % (yt + 78, ye2))
    s.wire("M440 %g H486 V%g M486 %g V%g H440" % (yt + 26, yt + 38, yt + 70, yt + 82))
    s.current_source(486, yt + 54, 14)
    s.text(506, yt + 58, L["nl"], 12, anchor="start", color=SOURCE)
    s.text(440, ye2 + 22, L["coil"] + " (Y_L)", 11)
    # voltage transformers (nonlinear)
    s.dot(600, yt)
    s.wire("M600 %g V%g" % (yt, yt + 40))
    s.current_source(600, yt + 54, 14)
    s.wire("M600 %g V%g" % (yt + 68, ye2))
    s.text(620, yt + 58, L["vt"], 12, anchor="start", color=SOURCE)
    s.text(690, yt - 8, L["z0"], 12, anchor="end")
    s.save(path)


# =========================================================================== figure 3: node rule
NODE = {
    "en": dict(title="Node rule of the zero sequence with the coil currents",
               desc="One loop: the fault current flows from earth through the fault impedance Z_F into the faulted "
                    "phase, along the line, through the positive and negative sequence with the source U_q to the "
                    "neutral point, and from there back to earth through the admittance of the network without the "
                    "coils and through the coils. These two lie in parallel with each other and together in series "
                    "with Z_F. The zero-sequence voltage lies across the parallel connection, and the fault current is "
                    "the sum of its branch currents. Without coils and without earth admittance the loop is open: no "
                    "fault current flows, however small Z_F.",
               seq="positive + negative sequence", line="line (fault in the network)", phase="faulted phase",
               floc="fault location F", neutral="neutral point N", earth="earth", net="network without coils",
               coil="coils", y="3·Y_{0,net}", ic="I_coil",
               eq1="I_{F,m} = 3·Y_{0,net,m}·ΔU_{0,m} + ΔI_{coil,m}   (current law at the neutral point N)",
               eq2="Y_{0,net,m} = (I_{F,m} − ΔI_{coil,m})/(3·ΔU_{0,m})   (staged fault test: I_F measured)",
               eq3="I_{coil,m} ≈ U_{0,m}/(j·m·X_L) + I_{Nh,m},   U_{s,m} = Z_{0,m}·I_{Nh,m}/3",
               eq4="Z_{0,m}/3 = 1/(3·Y_{0,net,m} + 1/(j·m·X_L)) – in series with Z_F, Z_qL and (Z_1 + Z_2)/3",
               lim1="Limit cases: no coils and Y_{0,net} → 0 ⇒ I_F → 0 for every Z_F;   Z_F → ∞ ⇒ I_F → 0;",
               lim2="Z_1, Z_2, Z_qL, Z_F → 0 ⇒ ΔU_0 = U_q (full displacement), "
                    "I_F = (3·Y_{0,net} + 1/(j·m·X_L))·U_q",
               note="orientation of the angle method: the active part of I_F is in phase with U_0; every coil current "
                    "lags U_0 at 50 Hz"),
    "de": dict(title="Knotenregel des Nullsystems mit den Spulenströmen",
               desc="Eine Schleife: Der Fehlerstrom fließt von Erde über die Fehlerimpedanz Z_F in den Fehlerleiter, "
                    "über die Leitung, Mit- und Gegensystem mit der Quelle U_q zum Sternpunkt und von dort über die "
                    "Admittanz des Netzes ohne Spulen und über die Spulen zurück zur Erde. Diese beiden liegen "
                    "parallel zueinander und gemeinsam in Reihe mit Z_F. Über der Parallelschaltung liegt die "
                    "Nullspannung, der Fehlerstrom ist die Summe ihrer Zweigströme. Ohne Spulen und ohne "
                    "Erdadmittanz ist die Schleife offen: Es fließt kein Fehlerstrom, wie klein Z_F auch ist.",
               seq="Mit- + Gegensystem", line="Leitung (Fehler im Netz)", phase="Fehlerleiter",
               floc="Fehlerort F", neutral="Sternpunkt N", earth="Erde", net="Netz ohne Spulen", coil="Spulen",
               y="3·Y_{0,Netz}", ic="I_Spule",
               eq1="I_{F,m} = 3·Y_{0,Netz,m}·ΔU_{0,m} + ΔI_{Spule,m}   (Knotensatz am Sternpunkt N)",
               eq2="Y_{0,Netz,m} = (I_{F,m} − ΔI_{Spule,m})/(3·ΔU_{0,m})   (Erdschlussversuch: I_F gemessen)",
               eq3="I_{Spule,m} ≈ U_{0,m}/(j·m·X_L) + I_{Nh,m},   U_{s,m} = Z_{0,m}·I_{Nh,m}/3",
               eq4="Z_{0,m}/3 = 1/(3·Y_{0,Netz,m} + 1/(j·m·X_L)) – in Reihe mit Z_F, Z_qL und (Z_1 + Z_2)/3",
               lim1="Grenzfälle: ohne Spulen und Y_{0,Netz} → 0 ⇒ I_F → 0 für jedes Z_F;   Z_F → ∞ ⇒ I_F → 0;",
               lim2="Z_1, Z_2, Z_qL, Z_F → 0 ⇒ ΔU_0 = U_q (volle Verlagerung), "
                    "I_F = (3·Y_{0,Netz} + 1/(j·m·X_L))·U_q",
               note="Orientierung des Winkelverfahrens: der Wirkanteil von I_F ist in Phase mit U_0; jeder Spulenstrom "
                    "eilt U_0 bei 50 Hz nach"),
}


def node_rule(lang, path):
    L = NODE[lang]
    s = Svg(780, 520, L["title"], L["desc"])
    yt, yn, ye = 62, 192, 312                     # faulted phase, neutral point N, earth
    xs, xf = 80, 690                              # source branch, fault branch
    xy, xc = 300, 450                             # branches of the parallel connection
    # faulted phase: source with positive and negative sequence, line to the fault location
    s.wire("M%g %g V%g" % (xs, yn, yt))
    s.wire("M%g %g H150" % (xs, yt))
    s.source(xs, (yt + yn) / 2)
    s.text(xs - 22, (yt + yn) / 2 + 5, "U_q", 13, anchor="end", color=SOURCE)
    s.box(150, yt - 12, 112, 24, "(Z_1 + Z_2)/3", 12)
    s.text(206, yt + 30, L["seq"], 11)
    s.wire("M262 %g H380" % yt)
    s.box(380, yt - 12, 64, 24, "Z_qL", 12, dash="4 3")
    s.text(412, yt + 30, L["line"], 11, color=BOX_STROKE)
    s.wire("M444 %g H%g" % (yt, xf))
    s.text(520, yt - 10, L["phase"], 11, color=INK)
    s.dot(xf, yt)
    s.text(xf - 8, yt - 10, L["floc"], 11, anchor="end", color=INK, weight=True)
    # fault: Z_F from the faulted phase to earth, I_F from earth into the phase
    s.wire("M%g %g V150" % (xf, yt))
    s.box(xf - 14, 150, 28, 46, None)
    s.text(xf + 22, 178, "Z_F", 13, anchor="start")
    s.wire("M%g 196 V%g" % (xf, ye))
    s.arrow(xf - 22, ye - 22, xf - 22, ye - 82)
    s.text(xf - 30, ye - 48, "I_F", 13, anchor="end")
    # earth and neutral point
    s.wire("M190 %g H%g" % (ye, xf))
    s.wire("M600 %g V%g" % (ye, ye + 4))
    s.earth(600, ye + 4)
    s.text(600, ye + 30, L["earth"], 11)
    s.wire("M%g %g H%g" % (xs, yn, xc))
    s.dot(xs, yn)
    s.text(xs + 8, yn + 16, L["neutral"], 11, anchor="start", color=INK, weight=True)
    # zero-sequence voltage across the parallel connection
    s.arrow(210, yn + 8, 210, ye - 6, color=MEASURED)
    s.text(220, (yn + ye) / 2 + 5, "ΔU_0", 13, anchor="start", color=MEASURED)
    # network admittance without the coils
    s.dot(xy, yn)
    s.wire("M%g %g V%g" % (xy, yn, yn + 30))
    s.box(xy - 14, yn + 30, 28, 46, None)
    s.text(xy + 22, yn + 58, L["y"], 12, anchor="start")
    s.wire("M%g %g V%g" % (xy, yn + 76, ye))
    s.dot(xy, ye)
    s.text(xy, ye + 30, L["net"], 11)
    # coils with their nonlinear part
    s.dot(xc, yn)
    s.wire("M%g %g V%g" % (xc, yn, yn + 24))
    s.ct(xc, yn + 14, horizontal=False)
    s.text(xc + 14, yn + 18, L["ic"], 12, anchor="start", color=MEASURED)
    s.inductor(xc, yn + 28, n=4, r=6)
    s.wire("M%g %g V%g" % (xc, yn + 76, ye))
    s.wire("M%g %g H%g V%g M%g %g V%g H%g" % (xc, yn + 24, xc + 46, yn + 38, xc + 46, yn + 68, yn + 82, xc))
    s.current_source(xc + 46, yn + 53, 14, up=False)
    s.text(xc + 66, yn + 57, "I_Nh", 12, anchor="start", color=SOURCE)
    s.dot(xc, ye)
    s.text(xc, ye + 30, L["coil"], 11)
    # relations
    s.text(40, 374, L["eq1"], 13, anchor="start")
    s.text(40, 398, L["eq2"], 12, anchor="start")
    s.text(40, 420, L["eq3"], 12, anchor="start")
    s.text(40, 442, L["eq4"], 12, anchor="start")
    s.text(40, 466, L["lim1"], 11, anchor="start", color=INK)
    s.text(40, 482, L["lim2"], 11, anchor="start", color=INK)
    s.text(40, 506, L["note"], 11, anchor="start")
    s.save(path)


# =========================================================================== figure 4: recording set-up
REC = {
    "en": dict(title="Measuring points for the network model",
               desc="Single-line diagram of a substation: HV/MV transformer with current transformers on the MV side, "
                    "Petersen coil at the transformer star point with its current transformer, MV busbar with "
                    "line-to-earth voltage transformers, feeders with core-balance current transformers, a "
                    "power-quality measurement at the same busbar and, for a staged fault test in the network, a "
                    "second synchronised recorder at the fault location.",
               hv="HV busbar", mv="MV busbar", tr="HV/MV transformer", coil="Petersen coil(s)",
               feeders="feeders", rec="disturbance recorder", pq="power-quality measurement",
               rec_1="≥ 10 kHz · ≥ 16 bit · COMTRADE", rec_2="all green channels, one time base (GPS)",
               pq_1="U_m per phase L-E (must)", pq_2="10-min values, 95 % quantiles",
               remote="fault location in the network", rec2="recorder: I_F, U_E, GPS (test in the network)",
               ch_u="U_L1E, U_L2E, U_L3E (must)", ch_une="U_NE (may)", ch_i="I_L1, I_L2, I_L3 (should)",
               ch_c="I_coil of every coil (must)", ch_f="3I_0 of every feeder (may)", ch_hv="U_HV (may)",
               legend="green: disturbance recorder · orange: power-quality measurement · must/should/may: "
                      "requirement for the network model"),
    "de": dict(title="Messstellen für das Netzmodell",
               desc="Übersichtsschaltbild eines Umspannwerks: HS/MS-Trafo mit Stromwandlern auf der MS-Seite, "
                    "Erdschlussspule am Trafo-Sternpunkt mit Stromwandler, MS-Sammelschiene mit "
                    "Leiter-Erde-Spannungswandlern, Abgänge mit Summenstromwandlern, eine Netzqualitätsmessung an "
                    "derselben Sammelschiene und für einen Erdschlussversuch im Netz ein zweites, synchronisiertes "
                    "Messgerät am Fehlerort.",
               hv="HS-Sammelschiene", mv="MS-Sammelschiene", tr="HS/MS-Trafo", coil="Erdschlussspule(n)",
               feeders="Abgänge", rec="Störschreiber", pq="Netzqualitätsmessung",
               rec_1="≥ 10 kHz · ≥ 16 bit · COMTRADE", rec_2="alle grünen Kanäle, eine Zeitbasis (GPS)",
               pq_1="U_m je Leiter L-E (Muss)", pq_2="10-min-Werte, 95-%-Quantile",
               remote="Fehlerort im Netz", rec2="Messgerät: I_F, U_E, GPS (Versuch im Netz)",
               ch_u="U_L1E, U_L2E, U_L3E (Muss)", ch_une="U_NE (Kann)", ch_i="I_L1, I_L2, I_L3 (Soll)",
               ch_c="I_Spule jeder Spule (Muss)", ch_f="3I_0 je Abgang (Kann)", ch_hv="U_HS (Kann)",
               legend="grün: Störschreiber · orange: Netzqualitätsmessung · Muss/Soll/Kann: Anforderung für das "
                      "Netzmodell"),
}
PQ_FILL, PQ_INK = "#faeeda", "#854f0b"
REC_FILL = "#e1f5ee"


def recording(lang, path):
    L = REC[lang]
    s = Svg(780, 470, L["title"], L["desc"])
    yh, ym = 40, 176                                        # HV and MV busbar
    # HV busbar and transformer
    s.busbar(170, yh, 330, yh)
    s.text(160, yh + 4, L["hv"], 12, anchor="end", color=INK)
    s.text(340, yh + 4, L["ch_hv"], 11, anchor="start", color=MEASURED)
    s.wire("M240 %g V58" % yh)
    s.add('<circle cx="240" cy="74" r="16" fill="none" stroke="%s" stroke-width="1.4"/>' % WIRE)
    s.add('<circle cx="240" cy="96" r="16" fill="none" stroke="%s" stroke-width="1.4"/>' % WIRE)
    s.text(266, 90, L["tr"], 12, anchor="start")
    s.wire("M240 112 V%g" % ym)
    s.ct(240, 146, horizontal=False)
    s.text(254, 150, L["ch_i"], 11, anchor="start", color=MEASURED)
    # star point → Petersen coil (left of the MV busbar)
    s.wire("M224 96 H110 V190")
    s.ct(110, 198, horizontal=False)
    s.inductor(110, 208, n=4, r=6)
    s.wire("M110 256 V268")
    s.earth(110, 272)
    s.text(124, 202, L["ch_c"], 11, anchor="start", color=MEASURED)
    s.text(124, 240, L["coil"], 11, anchor="start")
    # MV busbar
    s.busbar(170, ym, 740, ym)
    s.text(740, ym - 8, L["mv"], 12, anchor="end", color=INK)
    # voltage transformers
    s.wire("M380 %g V196" % ym)
    s.add('<circle cx="380" cy="208" r="12" fill="none" stroke="%s" stroke-width="1.4"/>' % WIRE)
    s.add('<circle cx="380" cy="224" r="12" fill="none" stroke="%s" stroke-width="1.4"/>' % WIRE)
    s.wire("M380 236 V246")
    s.earth(380, 250)
    s.text(398, 212, L["ch_u"], 11, anchor="start", color=MEASURED)
    s.text(398, 230, L["ch_une"], 11, anchor="start", color=MEASURED)
    # feeders with core-balance current transformers
    for x in (600, 660, 720):
        s.wire("M%g %g V250" % (x, ym))
        s.ct(x, 206, horizontal=False)
    s.text(710, 270, L["feeders"] + ": " + L["ch_f"], 11, anchor="end", color=MEASURED)
    # fault location in the network (staged test) behind the last feeder
    s.wire("M720 250 V300")
    s.box(706, 300, 28, 30, None, dash="4 3")
    s.text(720, 320, "F", 12, weight=True)
    s.text(696, 312, L["remote"], 11, anchor="end", color=INK)
    s.text(696, 328, L["rec2"], 11, anchor="end", color=MEASURED)
    # recorder and power-quality measurement
    s.box(300, 362, 260, 70, None, fill=REC_FILL, stroke=MEASURED)
    s.text(430, 384, L["rec"], 13, weight=True, color=MEASURED)
    s.text(430, 404, L["rec_1"], 11, color=MEASURED)
    s.text(430, 421, L["rec_2"], 11, color=MEASURED)
    s.box(40, 362, 230, 70, None, fill=PQ_FILL, stroke=PQ_INK)
    s.text(155, 384, L["pq"], 12, weight=True, color=PQ_INK)
    s.text(155, 404, L["pq_1"], 11, color=PQ_INK)
    s.text(155, 421, L["pq_2"], 11, color=PQ_INK)
    s.text(20, 458, L["legend"], 11, anchor="start", color=TEXT)
    s.save(path)



# =========================================================================== figure 5: HV network at the harmonics
HVNET = {
    "en": dict(title="Upstream impedance: transformer and HV network at the harmonic orders",
               desc="Seen from the MV busbar the transformer Z_T lies in series with the HV network: the line to the "
                    "EHV/HV substation, the capacitance and the loads of the HV network at its busbar, the EHV feed "
                    "with the background source, and a parallel path of a meshed network. Below the voltage divider "
                    "that splits the measured upstream impedance with the HV voltages.",
               a="(a) Model of the HV network (positive and negative sequence, order m)",
               mv="MV busbar", hv="HV busbar", ehv="EHV/HV busbar", tr="transformer", line="line to the EHV/HV substation",
               cb="C_B: capacitance of the HV network", gb="G_B: loads, other MV networks", feed="EHV feed",
               zp="Z_P: parallel path (meshed network)", umv="U_MV", uhv="U_HV", zfeed="Z_EHV", bg1="U_bg", bg2="(background)", meas="measured", zt="Z_T", zhs="Z_HV",
               eq1="Z_{up,m} = Z_{T,m} + Z_{HV,m};  Z_{HV,m} = [(Z_{L,m} + Z_{B,m})^{-1} + Z_{P,m}^{-1}]^{-1}",
               eq2="Z_{B,m} = (Z_{EHV,m}^{-1} + j·m·ω·C_B + G_B)^{-1};  parallel resonance m_p ≈ (ω·C_B·X_{EHV,1})^{-1/2}",
               b="(b) Split with the HV voltages of the same recording (voltage divider)",
               b1="k_m = t_s·ΔU_{HV,s,m}/ΔU_{MV,s,m} = Z_{HV,m}/(Z_{T,m} + Z_{HV,m})",
               b2="Z_{HV,m} = k_m·Z_{up,m};  Z_{T,m} = (1 − k_m)·Z_{up,m}",
               b3="t_s: ratio HV → MV with the vector group, from the 50-Hz positive sequence (negative sequence: conjugate "
                  "phase shift)",
               b4="k needs only the voltages of one recording – no transformer current, no second recorder"),
    "de": dict(title="Vorimpedanz: Trafo und HS-Netz bei den Oberschwingungen",
               desc="Von der MS-Sammelschiene aus liegt der Trafo Z_T in Reihe mit dem HS-Netz: die Leitung zum "
                    "HöS/HS-Umspannwerk, Kapazität und Lasten des HS-Netzes an dessen Sammelschiene, die Einspeisung "
                    "aus dem Höchstspannungsnetz mit der Vorbelastung und ein Parallelpfad eines vermaschten Netzes. "
                    "Unten der Spannungsteiler, der die gemessene Vorimpedanz mit den HS-Spannungen aufteilt.",
               a="(a) Modell des HS-Netzes (Mit- und Gegensystem, Ordnung m)",
               mv="MS-Sammelschiene", hv="HS-Sammelschiene", ehv="HöS/HS-Sammelschiene", tr="Trafo",
               line="Leitung zum HöS/HS-UW", cb="C_B: Kapazität des HS-Netzes", gb="G_B: Lasten, übrige MS-Netze",
               feed="HöS-Einspeisung", zp="Z_P: Parallelpfad (vermaschtes Netz)",
               umv="U_MS", uhv="U_HS", zfeed="Z_{HöS}", bg1="U_VB", bg2="(Vorbelastung)", meas="gemessen", zt="Z_T", zhs="Z_HS",
               eq1="Z_{vor,m} = Z_{T,m} + Z_{HS,m};  Z_{HS,m} = [(Z_{L,m} + Z_{B,m})^{-1} + Z_{P,m}^{-1}]^{-1}",
               eq2="Z_{B,m} = (Z_{HöS,m}^{-1} + j·m·ω·C_B + G_B)^{-1};  Parallelresonanz m_p ≈ (ω·C_B·X_{HöS,1})^{-1/2}",
               b="(b) Aufteilung mit den HS-Spannungen derselben Aufzeichnung (Spannungsteiler)",
               b1="k_m = t_s·ΔU_{HS,s,m}/ΔU_{MS,s,m} = Z_{HS,m}/(Z_{T,m} + Z_{HS,m})",
               b2="Z_{HS,m} = k_m·Z_{vor,m};  Z_{T,m} = (1 − k_m)·Z_{vor,m}",
               b3="t_s: Übersetzung HS → MS mit der Schaltgruppe, aus dem 50-Hz-Mitsystem (Gegensystem: konjugierte "
                  "Drehung)",
               b4="k braucht nur die Spannungen einer Aufzeichnung – keinen Trafostrom, kein zweites Gerät"),
}


def hv_network(lang, path):
    L = HVNET[lang]
    s = Svg(820, 500, L["title"], L["desc"])
    s.text(20, 28, L["a"], 13, anchor="start", weight=True, color=INK)
    yt, yp, yr = 112, 182, 246                    # main wire, parallel path, return
    mv, hv, ehv = 50, 200, 390                     # busbars
    # MV busbar with the measured voltage and current
    s.busbar(mv, yt - 26, mv, yt + 26)
    s.text(20, yt - 36, L["mv"], 11, color=INK, anchor="start")
    s.text(mv, yt + 46, L["umv"], 11, color=MEASURED)
    s.wire("M%g %g H104" % (mv, yt))
    s.ct(80, yt)
    s.text(80, yt - 14, "I_T", 11, color=MEASURED)
    s.box(104, yt - 12, 60, 24, L["zt"])
    s.text(134, yt + 30, L["tr"], 11)
    s.wire("M164 %g H250" % yt)
    # HV busbar of the substation
    s.busbar(hv, yt - 26, hv, yt + 26)
    s.text(hv, yt - 36, L["hv"], 11, color=INK)
    s.text(hv, yt + 46, L["uhv"], 11, color=MEASURED)
    # line to the EHV/HV substation
    s.box(250, yt - 12, 84, 24, "Z_L")
    s.text(298, yt + 30, L["line"], 10)
    s.text(298, yt + 44, "R_1 + j·m·X_1", 10)
    s.wire("M334 %g H530" % yt)
    s.busbar(ehv, yt - 26, ehv, yt + 26)
    s.text(ehv, yt - 36, L["ehv"], 11, color=INK)
    # shunts at the EHV/HV busbar
    s.dot(425, yt)
    s.wire("M425 %g V%g" % (yt, yt + 40))
    s.capacitor(425, yt + 46)
    s.wire("M425 %g V%g" % (yt + 52, yr))
    s.text(441, yt + 50, "C_B", 11, anchor="start")
    s.dot(475, yt)
    s.wire("M475 %g V%g" % (yt, yt + 26))
    s.box(463, yt + 26, 24, 40, None)
    s.text(495, yt + 50, "G_B", 11, anchor="start")
    s.wire("M475 %g V%g" % (yt + 66, yr))
    s.text(486, yr - 24, L["cb"], 10, anchor="start")
    s.text(486, yr - 10, L["gb"], 10, anchor="start")
    # EHV feed and background source
    s.box(530, yt - 12, 80, 24, L["zfeed"])
    s.text(570, yt - 20, L["feed"], 11)
    s.wire("M610 %g H690 V%g" % (yt, yt + 46))
    s.source(690, yt + 62)
    s.text(712, yt + 58, L["bg1"], 11, color=SOURCE, anchor="start")
    s.text(712, yt + 74, L["bg2"], 10, color=SOURCE, anchor="start")
    s.wire("M690 %g V%g H%g V%g" % (yt + 78, yr, mv, yt + 26))
    # parallel path (dashed)
    s.dot(212, yt)
    s.wire("M212 %g V%g H300" % (yt, yp), dash="4 3")
    s.box(300, yp - 12, 70, 24, "Z_P", dash="4 3")
    s.wire("M370 %g H660 V%g" % (yp, yt), dash="4 3")
    s.dot(660, yt)
    s.text(486, yp + 18, L["zp"], 10, anchor="start")
    # brackets
    s.wire("M104 %g V%g H164 V%g" % (yr + 16, yr + 24, yr + 16), color=BOX_STROKE, width=0.8)
    s.text(134, yr + 40, L["zt"], 12)
    s.wire("M%g %g V%g H700 V%g" % (hv, yr + 16, yr + 24, yr + 16), color=BOX_STROKE, width=0.8)
    s.text(450, yr + 40, L["zhs"], 12)
    s.text(20, yr + 70, L["eq1"], 12, anchor="start")
    s.text(20, yr + 92, L["eq2"], 12, anchor="start")
    # (b) voltage divider
    s.text(20, yr + 130, L["b"], 13, anchor="start", weight=True, color=INK)
    s.text(20, yr + 154, L["b1"], 12, anchor="start")
    s.text(20, yr + 176, L["b2"], 12, anchor="start")
    s.text(20, yr + 200, L["b3"], 11, anchor="start")
    s.text(20, yr + 218, L["b4"], 11, anchor="start", color=MEASURED)
    s.save(path)


FIGURES = {"forecast_fault_loop": fault_loop, "forecast_sequence_networks": sequence_networks,
           "forecast_node_rule": node_rule, "forecast_recording": recording, "forecast_hv_network": hv_network}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                  "assets"))
    ap.add_argument("--lang", choices=("en", "de", "both"), default="en")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    for lang in (("en", "de") if a.lang == "both" else (a.lang,)):
        for name, make in FIGURES.items():
            path = os.path.join(a.out, name + ("" if lang == "en" else "_de") + ".svg")
            make(lang, path)
            print("written:", path)


if __name__ == "__main__":
    main()
