# -*- coding: utf-8 -*-
"""Generate the Jupyter notebooks of groundfault (user interface) in English or German.

Usage::

    python tools/make_notebooks.py --lang en --out notebooks/en --example
    python tools/make_notebooks.py --lang de --out <folder> [--templates-only] [--overwrite]
    python tools/make_notebooks.py --lang de --out <folder> --forecast [--forecast-only]

The evaluation notebooks, per language:

* ``evaluate_measurement.ipynb`` / ``Messung_auswerten.ipynb`` – one recording: channel roles, raw-data diagnostics,
  RMS trend, evaluation, station and earthing measurement (groundmeas), signal explorer, checks, export;
* ``evaluate_campaign.ipynb`` / ``Kampagne_auswerten.ipynb`` – a campaign: overview and consistency,
  equivalent-source method, residual current at the earthing impedance, resistive approach, stations, report
  tables and figures, entries in groundmeas.

The forecast notebooks of the optional part ``groundfault.forecast`` – only with ``--forecast`` (or
``--forecast-only``), in their own folder ``forecast/`` (German ``Prognose/``):

* ``forecast_without_fault.ipynb`` / ``Prognose_ohne_Erdschluss.ipynb`` – the estimates without an earth fault (V0
  to V3): network data, resonance of the busbar, the MV network from undisturbed recordings of the transformer node
  (angle error of the current transformers from a reference clamp, the share of the HV-driven variation per recording,
  pooled estimate), the methods side by side;
* ``network_model_forecast.ipynb`` / ``Netzmodell_Prognose.ipynb`` – the network model of a busbar from the staged
  fault tests of one or more campaigns (V4 to V7): calibration, checks between the tests, update and checks with
  recorded earth faults (node rule with coil currents), checks with other measurements (e.g. a test in the network),
  forecast of the harmonic residual current at the busbar or behind a line, model file.

The code cells are identical in both languages (English names); comments, explanations and printed texts follow
the language. ``--example`` fills the configuration for the demo campaign (``groundfault.demo.make_campaign``),
which the notebooks create on the first run (the forecast notebook adds a recorded earth fault, the notebook
without an earth fault a measuring day of undisturbed transformer recordings) – they then run without any measurement
data. Without ``--example`` the configuration contains placeholders. Unchanged reference
copies (``templates/*_DEFAULT.ipynb`` or ``Vorlagen/*_DEFAULT.ipynb``) are always written; working copies are written
only if they do not exist yet (own changes are kept) unless ``--overwrite`` is given.
"""
import argparse
import os

import nbformat as nbf

NAMES = {"en": ("evaluate_measurement", "evaluate_campaign", "templates"),
         "de": ("Messung_auswerten", "Kampagne_auswerten", "Vorlagen")}
FORECAST_NAMES = {"en": ("network_model_forecast", "forecast"), "de": ("Netzmodell_Prognose", "Prognose")}
"""Forecast notebook (optional part): file name and folder per language."""
WITHOUT_FAULT_NAMES = {"en": "forecast_without_fault", "de": "Prognose_ohne_Erdschluss"}
"""Forecast notebook without an earth fault (optional part, in the folder of the forecast notebook)."""


def md(text):
    return nbf.v4.new_markdown_cell(text.strip("\n"))


def code(text):
    return nbf.v4.new_code_cell(text.strip("\n"))


def keyed(key, cell):
    """The cell with an id of its own (``<name>-<key>``) instead of a position number. Cells added after a release
    get a key, so the numbered ids of the existing cells – which a working copy shares with its reference copy – do
    not shift and updating a working copy maps every cell to its counterpart."""
    cell["id"] = "@" + key
    return cell


def setup(lang):
    t = (lambda en, de: en if lang == "en" else de)
    return '''%matplotlib inline
import sys
from pathlib import Path

LANGUAGE = "''' + lang + '''"                ''' + t("# output language of tables, hints and figures: \"en\" | \"de\"",
                                                     "# Sprache von Tabellen, Hinweisen und Abbildungen: \"de\" | \"en\"") + '''
try:
    import groundfault as gf
except ImportError:            ''' + t("# not installed: use the source folder of a clone (…/groundfault/src)",
                                     "# nicht installiert: Quellordner eines Klons verwenden (…/groundfault/src)") + '''
    for p in [Path.cwd(), *Path.cwd().parents]:    # ./src, ./groundfault/src, ./*/groundfault/src
        try:
            candidates = [p / "src", p / "groundfault" / "src", *sorted(p.glob("*/groundfault/src"))]
        except OSError:
            candidates = [p / "src", p / "groundfault" / "src"]
        hits = [c for c in candidates if (c / "groundfault" / "__init__.py").is_file()]
        if hits:
            sys.path.insert(0, str(hits[0]))
            break
    import groundfault as gf
import numpy as np
import pandas as pd
from IPython.display import Markdown, display
from groundfault import (campaign, corrections, demo, diagnostics, disturbances, earthing, equivalent_source,
                         explorer, i18n, interactive, layout, legacy, pq, register, report, rms, sites, transformer)

i18n.set_language(LANGUAGE)
''' + t("# work folder = this folder or the first folder above it with a campaigns folder (\"campaigns\" or\n"
        "# \"01_Messkampagnen\"); its name gives the folder layout, without one the layout of LANGUAGE is used",
        "# Arbeitsordner = dieser Ordner oder der erste Ordner darüber mit einem Kampagnenordner („01_Messkampagnen“\n"
        "# oder „campaigns“); dessen Name gibt die Ordnerstruktur, ohne ihn gilt die Ordnerstruktur von LANGUAGE") + '''
WORK_FOLDER, LAYOUT = layout.find_work_folder(Path.cwd(), default=LANGUAGE)
WORK_FOLDER = Path(WORK_FOLDER)
pd.set_option("display.max_columns", 60); pd.set_option("display.width", 220)
pd.set_option("display.float_format", lambda x: "%.4g" % x)
report.activate_style()        ''' + t("# notebook preview = typeface of the exported figures",
                                       "# Vorschau im Notebook = Schriftbild der exportierten Abbildungen") + '''


def show(df):
    """''' + t("Table with column names and codes in the output language.",
               "Tabelle mit Spaltennamen und Codes in der Ausgabesprache.") + '''"""
    display(i18n.localize(df))


print("groundfault %s · ''' + t("work folder", "Arbeitsordner") + ''': %s · ''' + t("layout", "Ordnerstruktur") + \
        ''': %s · ''' + t("font of the figures", "Schrift der Abbildungen") + ''': %s"
      % (gf.__version__, WORK_FOLDER, LAYOUT.language, report.used_font()))'''


# =========================================================================== single measurement
def measurement_notebook(lang: str, example: bool) -> nbf.NotebookNode:
    t = (lambda en, de: en if lang == "en" else de)
    if example:
        conf = t('''CAMPAIGN    = "2026-01-15_Demo"                     # folder in the campaigns folder
FILE        = "raw/SUB/SUB_0_10_000kHz.cfg"          # .cfg relative to the campaign folder
MEASUREMENT = None                                   # name for exports (None = file name without extension)
Z_FAULT     = 0.0                                    # additional impedance in the fault branch in Ω (substation: 0 / 2.5 / 5, station: None)
DEMO        = True                                   # create the demo campaign if missing (changes nothing outside it)

# ---------------------------------------------------------------- analysis intervals in s (read them in section 3!)
# demo substation 0 Ω – fault from 2 s to 6 s, active residual current increased from 4.6 s:
STEADY_STATE = (2.6, 4.4)   # steady-state fault – after the transient (disturbed states inside are left out)
PRE_FAULT    = (0.2, 1.8)   # operation without fault before the fault
POST_FAULT   = (7.0, 8.8)   # after the decay of the neutral displacement voltage''',
                 '''CAMPAIGN    = "2026-01-15_Demo"                     # Ordner im Kampagnenordner
FILE        = "1_Rohdaten/UW/UW_0_10_000kHz.cfg"     # .cfg relativ zum Kampagnenordner
MEASUREMENT = None                                   # Name für Exporte (None = Dateiname ohne Endung)
Z_FAULT     = 0.0                                    # Zusatzimpedanz im Fehlerzweig in Ω (UW: 0 / 2,5 / 5 – Station: None)
DEMO        = True                                   # Demo-Kampagne anlegen, falls sie fehlt (ändert nichts außerhalb)

# ---------------------------------------------------------------- Auswertebereiche in s (in Abschnitt 3 ablesen!)
# Demo-UW 0 Ω – Fehler von 2 s bis 6 s, Wattreststromerhöhung ab 4,6 s:
STEADY_STATE = (2.6, 4.4)   # stationärer Erdschluss – nach dem Einschwingen (gestörte Zustände darin werden ausgeblendet)
PRE_FAULT    = (0.2, 1.8)   # erdschlussfreier Betrieb vor dem Fehler
POST_FAULT   = (7.0, 8.8)   # nach dem Abklingen der Verlagerungsspannung''')
        rms_file = "None"
        db = 'str(WORK_FOLDER / "demo_groundmeas.db")   ' + t("# demo database (written with the demo campaign)",
                                                              "# Demo-Datenbank (mit der Demo-Kampagne angelegt)")
        pq_files = t('''["raw/PQ/SUB_PQ_export.csv"]   # demo: PQ export of the demo busbar (written with the demo campaign)''',
                     '''["1_Rohdaten/PQ/UW_PQ_Export.csv"]   # Demo: PQ-Export der Demo-Sammelschiene (mit der Demo-Kampagne angelegt)''')
    else:
        conf = t('''CAMPAIGN    = "YYYY-MM-DD_Place"                     # folder in the campaigns folder
FILE        = "raw/<site>/<file>.cfg"                 # .cfg relative to the campaign folder
MEASUREMENT = None                                    # name for exports (None = file name without extension)
Z_FAULT     = 0.0                                     # additional impedance in the fault branch in Ω (substation: 0 / 2.5 / 5, station: None)
DEMO        = False                                   # True: create the demo campaign if it does not exist yet

# ---------------------------------------------------------------- analysis intervals in s (read them in section 3!)
STEADY_STATE = None   # (t0, t1) steady-state fault – after the transient (disturbed states inside are left out)
PRE_FAULT    = None   # (t0, t1) operation without fault before the fault
POST_FAULT   = None   # (t0, t1) after the decay of the neutral displacement voltage''',
                 '''CAMPAIGN    = "JJJJ-MM-TT_Ort"                       # Ordner im Kampagnenordner
FILE        = "1_Rohdaten/<Messort>/<Datei>.cfg"      # .cfg relativ zum Kampagnenordner
MEASUREMENT = None                                    # Name für Exporte (None = Dateiname ohne Endung)
Z_FAULT     = 0.0                                     # Zusatzimpedanz im Fehlerzweig in Ω (UW: 0 / 2,5 / 5 – Station: None)
DEMO        = False                                   # True: Demo-Kampagne anlegen, falls sie noch nicht existiert

# ---------------------------------------------------------------- Auswertebereiche in s (in Abschnitt 3 ablesen!)
STEADY_STATE = None   # (t0, t1) stationärer Erdschluss – nach dem Einschwingen (gestörte Zustände darin werden ausgeblendet)
PRE_FAULT    = None   # (t0, t1) erdschlussfreier Betrieb vor dem Fehler
POST_FAULT   = None   # (t0, t1) nach dem Abklingen der Verlagerungsspannung''')
        rms_file = "None"
        db = "None   " + t("# None = as groundmeas (environment variable GROUNDMEAS_DB or ~/.config/groundmeas/config.json)",
                           "# None = wie groundmeas (Umgebungsvariable GROUNDMEAS_DB bzw. ~/.config/groundmeas/config.json)")
        pq_files = t('''None    # export(s) of a PQ instrument at the busbar, e.g. ["…/Export.csv"] (relative to the campaign folder or absolute; None = no scaling)''',
                     '''None    # Export(e) eines PQ-Messgeräts an der Sammelschiene, z. B. ["…/Export.csv"] (relativ zum Kampagnenordner oder absolut; None = keine Skalierung)''')
    notes = "notes/corrections.csv" if lang == "en" else "0_Notizen/Korrekturen.csv"
    cells = [
        md(t('''
# Staged earth-fault test – evaluate one measurement

Evaluation of one COMTRADE recording of a staged earth-fault test in a compensated (resonant-earthed) network. All
computations are in the package **`groundfault`** – the notebook is only the user interface. Reference copy:
`templates/evaluate_measurement_DEFAULT.ipynb`.

**Procedure**
1. **Configuration** – campaign, file, additional impedance; your limits, margins and factors (groundfault has none).
   Leave the analysis intervals empty at first.
2. **Open the file** – check the channel roles and the raw-data diagnostics.
3. **RMS trend** – read the times of the *steady-state fault*, *pre-fault* and *post-fault* intervals, enter them in
   section 1 and run the notebook again (*Run All*). groundfault proposes the undisturbed part of the fault as the
   steady state. Of all undisturbed 200-ms windows in the steady-state interval the window with the **largest**
   residual current is assessed – an active residual current increase or a network change (a section trips) inside
   the interval is detected and left out.
4. **Evaluation** – assessment quantities with your measurement-uncertainty margins, angle method, plausibility checks, voltages
   before/during/after the fault, station and transformer if measured. At a **station**: earth potential rise and
   touch voltage per frequency (direct and fault-related), PEN currents and current into the LV network (Z_E,LV),
   comparison with the **earthing measurement from groundmeas** and **reduction factor**.
5. **Signal explorer** – look at all channels: RMS value over time with harmonics/THD on hover, instantaneous values
   and spectrum of a freely chosen excerpt (check that the numbers match the curves).
6. **Checks** (optional) – mains frequency, spectra per window, comparison with the RMS values of the recorder,
   resonance curve.
7. **Export** – result file (input of `evaluate_campaign.ipynb`), tables (CSV/XLSX/DOCX/Markdown), figures
   (PDF/SVG/PNG, without titles, A4 type area) and the signal explorer as an HTML file; entry in groundmeas.
''', '''
# Erdschlussmessung auswerten – Einzelmessung

Auswertung einer COMTRADE-Aufzeichnung eines Erdschlussversuchs im kompensierten Netz. Alle Berechnungen stecken im
Paket **`groundfault`** – das Notebook ist nur die Bedienoberfläche. Ausgangsfassung:
`Vorlagen/Messung_auswerten_DEFAULT.ipynb`.

**Ablauf**
1. **Konfiguration** – Kampagne, Datei, Zusatzimpedanz; eigene Grenzwerte, Zuschläge und Faktoren (groundfault hat
   keine). Auswertebereiche zunächst leer lassen.
2. **Datei öffnen** – Kanalrollen und Rohdaten-Diagnose prüfen.
3. **Effektivwertverlauf** – Zeiten für *stationären Fehler*, *Vorfehler* und *Nachfehler* ablesen
   und in Abschnitt 1 eintragen, dann das Notebook erneut ausführen (*Run All*). groundfault schlägt den ungestörten
   Teil des Fehlers als stationären Bereich vor. Aus allen ungestörten 200-ms-Fenstern im stationären Bereich wird
   das Fenster mit dem **größten** Erdschlussreststrom bewertet – eine Wattreststromerhöhung oder eine Netzänderung
   (ein Netzabschnitt löst aus) im Bereich wird erkannt und ausgeblendet.
4. **Auswertung** – Bewertungsgrößen mit den eigenen Messunsicherheitszuschlägen, Winkelverfahren, Plausibilitätsprüfungen, Spannungen
   vor/im/nach dem Fehler, ggf. Station und Trafo. An einer **Station**: Erdungs- und Berührungsspannung je Frequenz
   (direkt und fehlerbedingt), PEN-Ströme und Strom ins Ortsnetz (Z_E,Ortsnetz), Vergleich mit der
   **Erdungsmessung aus groundmeas** und **Reduktionsfaktor**.
5. **Signal-Explorer** – alle Kanäle ansehen: Effektivwert über der Zeit mit Harmonischen/THD im Mouse-over,
   Momentanwerte und Spektrum eines frei wählbaren Ausschnitts (prüfen, ob die Zahlen zur Kurve passen).
6. **Kontrollen** (optional) – Netzfrequenz, Spektren je Fenster, Vergleich mit den RMS-Werten des Messgeräts, V-Kurve.
7. **Export** – Ergebnisdatei (Grundlage für `Kampagne_auswerten.ipynb`), Tabellen (CSV/XLSX/DOCX/Markdown),
   Abbildungen (PDF/SVG/PNG, ohne Titel, A4-Satzspiegel) und der Signal-Explorer als HTML-Datei; Eintrag in groundmeas.
''')),
        code(setup(lang)),
        md(t("## 1 · Configuration", "## 1 · Konfiguration")),
        code(t("# ---------------------------------------------------------------- measurement\n",
               "# ---------------------------------------------------------------- Messung\n") + conf + t('''

# ---------------------------------------------------------------- limits, margins and factors – defined by you
# groundfault contains no limits or safety factors: take them from the operator's specification or the applicable
# standard. Not set (the values below), the parts that need them are skipped with a note.
LIMITS            = ()      # limits of the residual current in A, e.g. (I_1, I_2): extrapolation of the station voltages
U_TP              = None    # permissible touch voltage U_Tp in V (relevance of the reduction factor)
F_FACTOR          = None    # factor F of the permissible earth potential rise F·U_Tp
REFERENCE_CURRENT = None    # reference current in A for the reduction factor (None = the largest of LIMITS)
UNCERTAINTY_I     = 0.0     # measurement-uncertainty margin m_I of currents as a fraction: I·(1 + m_I) (0.0 = none)
UNCERTAINTY_U     = 0.0     # measurement-uncertainty margin m_U of voltages as a fraction: U·(1 − m_U) (0.0 = none)
PQ_SAFETY_FACTOR  = 1.0     # factor on the 95 % quantile of a PQ measurement (1.0 = none)
PQ_FACTORS        = None    # factor on the quantile by the duration of the PQ measurement {minimum days: factor} (None = PQ_SAFETY_FACTOR)
R_TYPICAL         = None    # range (low, high) of the reduction factor at 50 Hz you expect, e.g. from your experience
# (LIMITS, U_TP, F_FACTOR, UNCERTAINTY_I/_U and PQ_SAFETY_FACTOR become the settings ires_limits, u_tp, f_factor,
#  uncertainty_I/_U and pq_safety_factor and are stored in the result file)

# ---------------------------------------------------------------- power-quality (PQ) measurement of the busbar
# With PQ_FILES the quantiles of the PQ measurement scale the harmonic content in section 4: every order of the
# positive or negative sequence (5, 7, 11, 13 …) with its own quantile (largest phase per 10-min interval), without one
# with the quantile of the THD (largest line-to-line loop); the zero sequence (3, 9, 15 …) and the even orders stay as
# measured (table harmonic_scaling, rows IH_zero, IH_even, IH_other, IH_scaled and IRMS_forecast).
PQ_FILES          = ''' + pq_files + '''
PQ_TIMEZONE       = None    # time zone of the instrument clock, e.g. "Europe/Berlin" (None = time stamps as exported)
PQ_QUANTILE       = 0.95    # quantile of the 10-min values

# ---------------------------------------------------------------- evaluation parameters
SETTINGS = gf.Settings(
    T_win=0.200,                 # window length in s (step = window length)
    harmonics=(1, 3, 5, 7),      # orders of the assessment quantities
    uncertainty_I=UNCERTAINTY_I,  # increases currents
    uncertainty_U=UNCERTAINTY_U,  # decreases voltages
    u_thd95_percent=None,        # 95 % quantile of the THD (line-to-line) of a PQ measurement in % (None = no scaling; with PQ_FILES from the measurement)
    pq_safety_factor=PQ_SAFETY_FACTOR,
    correct_polarity=True,       # Iw < 0 → rotate the current phasors by 180° (clamp reversed)
    exclude_disturbances=True,   # active residual current increase and network change are not the reference
    transformer_sign=None,       # transformer currents: None = polarity from the upstream impedance, +1 as measured, -1 reversed
    ires_limits=LIMITS, u_tp=U_TP, f_factor=F_FACTOR,
)

# ---------------------------------------------------------------- channels (only if needed)
# Permanent corrections of the campaign (wrong CT ratio, clamp around one of several conductors, polarity, channel
# to be ignored, main channel) belong in ''' + notes + ''' of the campaign –
# they are applied automatically and documented in the result. Here only settings for this run:
APPLY_CORRECTIONS = True
ROLE_OVERRIDES = {}      # e.g. {"ISp22": None} = ignore the channel, {"U1": "u_l1e"} = fix the role
MAIN_CHANNEL   = {}      # e.g. {"i_res": "IF2"} (default: IF before IF1 before IFr with the largest range)
ALIGNMENT      = None    # time offset between subsystems, e.g. dict(roles=["u_l1e", "u_l2e", "u_l3e"], dt_s=1.5)
FS_OVERRIDE    = None    # force the sampling rate (only for a defective time base, see the diagnostics)

# ---------------------------------------------------------------- checks and export
RMS_FILE         = ''' + rms_file + '''      # RMS export of the recorder (check), e.g. "raw/<site>/<file>_10_000Hz.cfg"
V_CURVE          = False   # fundamental trend / resonance curve (coil adjustment during the fault)
SHOW_ENVELOPE    = False   # also the envelope of the instantaneous values of the whole recording (interactive)
EXPORT_FORMATS   = ("pdf", "svg", "png")
RECORD_INTERVALS = True    # document the chosen intervals in the register of the work folder (not with DEMO = True)

# ---------------------------------------------------------------- signal explorer and earthing measurement (station)
SIGNAL_EXPLORER  = True    # section 5: look at all channels (hover with RMS value, harmonics, THD)
EXPLORER_HTML    = True    # also export the explorer as an HTML file (opens in a browser without Python)
GROUNDMEAS_DB    = ''' + db + '''
GROUNDMEAS_LOCATION = None       # location in groundmeas; None = from the sites file of the campaign or the folder name
GROUNDMEAS_MEASUREMENTS = None   # comparison: ids of the measurements in groundmeas, e.g. [3, 21]; None = all of the location
GROUNDMEAS_EXPORT = False        # True: enter as "staged_fault_test" (after a backup copy); "replace": renew the own entry
GROUNDMEAS_UNCERTAIN = "mark"    # uncertain fault-related values: "mark" (with a remark) | "omit"
GROUNDMEAS_UNITS = "suitable"    # "suitable": readable per quantity (mV, mA …; groundmeas ≥ 1.6.1) | "base": V and A
GROUNDMEAS_DESCRIPTION = ""      # optional text before the automatic description, e.g. "20 to 0.4 kV, compensated"
GROUNDMEAS_TIMEZONE = None       # time zone of the recorder clock if it is not UTC, e.g. "Europe/Berlin"
GROUNDMEAS_TIMESTAMP = None      # only for a wrongly set recorder clock: start of the recording in UTC "YYYY-MM-DD hh:mm:ss"''',
                                                                                       '''

# ---------------------------------------------------------------- Grenzwerte, Zuschläge und Faktoren – selbst festlegen
# groundfault enthält keine Grenzwerte oder Sicherheitsfaktoren: aus der Vorgabe des Netzbetreibers bzw. der geltenden
# Norm übernehmen. Nicht gesetzt (die Werte unten), werden die Teile, die sie brauchen, mit einem Hinweis übersprungen.
LIMITS            = ()      # Grenzwerte des Reststroms in A, z. B. (I_1, I_2): Hochrechnung der Stationsspannungen
U_TP              = None    # zulässige Berührungsspannung U_Tp in V (Bewertungsrelevanz des Reduktionsfaktors)
F_FACTOR          = None    # Faktor F der zulässigen Erdungsspannung F·U_Tp
REFERENCE_CURRENT = None    # Bezugsstrom in A für den Reduktionsfaktor (None = größter Wert von LIMITS)
UNCERTAINTY_I     = 0.0     # Messunsicherheitszuschlag m_I der Ströme als Anteil: I·(1 + m_I) (0.0 = keiner)
UNCERTAINTY_U     = 0.0     # Messunsicherheitszuschlag m_U der Spannungen als Anteil: U·(1 − m_U) (0.0 = keiner)
PQ_SAFETY_FACTOR  = 1.0     # Faktor auf das 95-%-Quantil einer PQ-Messung (1.0 = keiner)
PQ_FACTORS        = None    # Faktor auf das Quantil nach Dauer der PQ-Messung {Mindesttage: Faktor} (None = PQ_SAFETY_FACTOR)
R_TYPICAL         = None    # erwarteter Bereich (unten, oben) des Reduktionsfaktors bei 50 Hz, z. B. aus Erfahrung
# (LIMITS, U_TP, F_FACTOR, UNCERTAINTY_I/_U und PQ_SAFETY_FACTOR werden zu den Einstellungen ires_limits, u_tp,
#  f_factor, uncertainty_I/_U und pq_safety_factor und in der Ergebnisdatei gespeichert)

# ---------------------------------------------------------------- Netzqualitätsmessung (PQ) der Sammelschiene
# Mit PQ_FILES skalieren die Quantile der PQ-Messung den Oberschwingungsanteil in Abschnitt 4: jede Ordnung des Mit-
# oder Gegensystems (5, 7, 11, 13 …) mit ihrem eigenen Quantil (größter Leiter je 10-min-Intervall), ohne eines mit dem
# Quantil des THD (größte Leiter-Leiter-Schleife); Nullsystem (3, 9, 15 …) und gerade Ordnungen bleiben wie gemessen
# (Tabelle harmonic_scaling, Zeilen IH_null, IH_gerade, IH_sonstige, IH_skaliert und IRMS_prognose).
PQ_FILES          = ''' + pq_files + '''
PQ_TIMEZONE       = None    # Zeitzone der Geräteuhr, z. B. "Europe/Berlin" (None = Zeitstempel wie exportiert)
PQ_QUANTILE       = 0.95    # Quantil der 10-min-Werte

# ---------------------------------------------------------------- Auswerteparameter
SETTINGS = gf.Settings(
    T_win=0.200,                 # Fensterlänge in s (Schrittweite = Fensterlänge)
    harmonics=(1, 3, 5, 7),      # Ordnungen der Bewertungsgrößen
    uncertainty_I=UNCERTAINTY_I,  # vergrößert die Ströme
    uncertainty_U=UNCERTAINTY_U,  # verkleinert die Spannungen
    u_thd95_percent=None,        # 95-%-Quantil des THD (L-L) einer PQ-Messung in % (None = keine Skalierung; mit PQ_FILES aus der Messung)
    pq_safety_factor=PQ_SAFETY_FACTOR,
    correct_polarity=True,       # Iw < 0 → Stromzeiger um 180° drehen (verpolte Zange)
    exclude_disturbances=True,   # Wattreststromerhöhung und Netzänderung nicht als Referenz verwenden
    transformer_sign=None,       # Trafoströme: None = Polarität aus der Vorimpedanz, +1 wie gemessen, -1 umgekehrt
    ires_limits=LIMITS, u_tp=U_TP, f_factor=F_FACTOR,
)

# ---------------------------------------------------------------- Kanäle (nur bei Bedarf)
# Dauerhafte Korrekturen der Kampagne (falsche Wandlerübersetzung, Zange nur auf einem von mehreren Leitern,
# Polarität, Kanal ignorieren, Hauptkanal) gehören in ''' + notes + ''' der Kampagne –
# sie werden automatisch angewendet und im Ergebnis dokumentiert. Hier nur Einstellungen für diesen Lauf:
APPLY_CORRECTIONS = True
ROLE_OVERRIDES = {}      # z. B. {"ISp22": None} = Kanal ignorieren, {"U1": "u_l1e"} = Rolle festlegen
MAIN_CHANNEL   = {}      # z. B. {"i_res": "IF2"} (Standard: IF vor IF1 vor IFr mit größtem Messbereich)
ALIGNMENT      = None    # Zeitversatz zwischen Subsystemen, z. B. dict(roles=["u_l1e", "u_l2e", "u_l3e"], dt_s=1.5)
FS_OVERRIDE    = None    # Abtastrate erzwingen (nur bei defekter Zeitbasis, siehe Diagnose)

# ---------------------------------------------------------------- Kontrollen & Export
RMS_FILE         = ''' + rms_file + '''      # RMS-Export des Messgeräts (Kontrolle), z. B. "1_Rohdaten/<Messort>/<Datei>_10_000Hz.cfg"
V_CURVE          = False   # Grundschwingungsverlauf/V-Kurve (Spulenverstellung während des Fehlers)
SHOW_ENVELOPE    = False   # zusätzlich Momentanwert-Hüllkurve der ganzen Aufzeichnung (interaktiv)
EXPORT_FORMATS   = ("pdf", "svg", "png")
RECORD_INTERVALS = True    # gewählte Bereiche im Messregister des Arbeitsordners dokumentieren (nicht mit DEMO = True)

# ---------------------------------------------------------------- Signal-Explorer und Erdungsmessung (Station)
SIGNAL_EXPLORER  = True    # Abschnitt 5: alle Kanäle ansehen (Mouse-over mit Effektivwert, Harmonischen, THD)
EXPLORER_HTML    = True    # Explorer zusätzlich als HTML-Datei exportieren (ohne Python im Browser zu öffnen)
GROUNDMEAS_DB    = ''' + db + '''
GROUNDMEAS_LOCATION = None       # Ort in groundmeas; None = aus der Messorte-Datei der Kampagne bzw. dem Ordnernamen
GROUNDMEAS_MEASUREMENTS = None   # Vergleich: IDs der Messungen in groundmeas, z. B. [3, 21]; None = alle des Ortes
GROUNDMEAS_EXPORT = False        # True: als „staged_fault_test“ eintragen (nach Sicherungskopie); "replace": eigenen Eintrag erneuern
GROUNDMEAS_UNCERTAIN = "mark"    # unsichere fehlerbedingte Werte: "mark" (mit Vermerk) | "omit" (weglassen)
GROUNDMEAS_UNITS = "suitable"    # "suitable": je Größe gut lesbar (mV, mA …; groundmeas ≥ 1.6.1) | "base": V und A
GROUNDMEAS_DESCRIPTION = ""      # optional, vor der automatischen Beschreibung, z. B. "20 to 0.4 kV, compensated"
GROUNDMEAS_TIMEZONE = None       # Zeitzone der Geräteuhr, falls nicht UTC, z. B. "Europe/Berlin"
GROUNDMEAS_TIMESTAMP = None      # nur bei falsch gestellter Geräteuhr: Beginn der Aufzeichnung in UTC "JJJJ-MM-TT hh:mm:ss"''')),
        md(t('''
## 2 · Open the file, channel roles, raw-data diagnostics

Check: Are all roles detected correctly (line-to-earth voltages, fault current, coils, station)? Is the right
**main channel** of the fault current marked (✓)? Does the diagnosis report saturation, flat channels, a deviating
time base or a time offset between voltage and current channels? The corrections of the campaign are applied here
and shown as a table.
''', '''
## 2 · Datei öffnen, Kanalrollen, Rohdaten-Diagnose

Prüfen: Sind alle Rollen richtig erkannt (Leiter-Erde-Spannungen, Fehlerstrom, Spulen, Station)? Ist der
richtige **Hauptkanal** des Fehlerstroms markiert (✓)? Meldet die Diagnose Sättigung, flache Kanäle, eine
abweichende Zeitbasis oder einen Zeitversatz zwischen Spannungs- und Stromkanälen?
Die Korrekturen der Kampagne werden hier angewendet und als Tabelle angezeigt.
''')),
        code('''CAMPAIGN_FOLDER = WORK_FOLDER / LAYOUT.campaigns / CAMPAIGN
if DEMO and not CAMPAIGN_FOLDER.exists():
    demo.make_campaign(str(WORK_FOLDER), CAMPAIGN, layout=LAYOUT.language)
CFG = CAMPAIGN_FOLDER / FILE
SITE = sites.site_from_path(FILE)
CORR = corrections.load(CAMPAIGN_FOLDER) if APPLY_CORRECTIONS else corrections.Corrections.empty()
rec = gf.open_recording(str(CFG), fs_override=FS_OVERRIDE)
corrections_log = CORR.apply(rec)        ''' + t("# CT factors per channel – contained in all values from here on",
                                               "# Wandlerfaktoren je Kanal – ab hier in allen Werten enthalten") + '''
roles = gf.detect_roles(rec.channel_names, rec.units, {**CORR.role_overrides(rec), **ROLE_OVERRIDES},
                        {**CORR.main_channel(rec), **MAIN_CHANNEL}, CORR.distances(rec))
MEASUREMENT = MEASUREMENT or CFG.stem
if len(corrections_log):
    display(Markdown("''' + t("**Corrections of the campaign** (contained in all following values)",
                              "**Korrekturen der Kampagne** (in allen folgenden Werten enthalten)") + '''"))
    show(corrections_log)
for h in CORR.hints:
    print("⚠", h)
kind = "+".join(str(i18n.value_label("measurement_kind", k)) for k in roles.measurement_kind().split("+"))
print(rec, "| ''' + t("start (cfg)", "Start (cfg)") + ''':", rec.t_start, "| ''' + t("kind of measurement", "Messart") + ''':", kind)
show(roles.table())
dg = diagnostics.diagnose(rec, roles)
print(dg.text())
show(dg.channels)'''),
        md(t('''
## 3 · RMS trend – read the analysis intervals

Moving true RMS value (20-ms windows, DC removed per window). Read the times with zoom and range slider:
**steady state** = after the transient; **pre-fault** and **post-fault** = operation without fault (after the decay of
the neutral displacement voltage). Entered intervals are shaded.

groundfault searches the whole fault for **disturbed states** – an active residual current increase (Iw rises
abruptly for a few seconds) and a network change (a section trips or is switched: Iv and thus the fundamental
component and the RMS value change abruptly) – shades them red and proposes the undisturbed part as `STEADY_STATE`.
Inside `STEADY_STATE` they are left out automatically (`exclude_disturbances` in section 1); a coil adjustment is no
disturbance. A transformer recording without a fault-current channel is scanned with the fault current estimated from
the negative-sequence current of the transformer; enter a pre-fault interval for it in the evaluation as well.
''', '''
## 3 · Effektivwertverlauf – Auswertebereiche ablesen

Gleitender Echt-Effektivwert (20-ms-Fenster, DC je Fenster entfernt). Mit Zoom/Range-Slider die Zeiten ablesen:
**stationär** = nach dem Einschwingen; **Vorfehler** und **Nachfehler** = erdschlussfreier Betrieb (nach dem Abklingen
der Verlagerungsspannung). Eingetragene Bereiche werden farbig hinterlegt.

groundfault durchsucht den ganzen Fehler nach **gestörten Zuständen** – Wattreststromerhöhung (Iw steigt für einige
Sekunden sprunghaft) und Netzänderung (ein Netzabschnitt löst aus oder wird umgeschaltet: Iv und damit
Grundschwingung und Effektivwert ändern sich sprunghaft) –, hinterlegt sie rot und schlägt den ungestörten Teil als
`STEADY_STATE` vor. Innerhalb von `STEADY_STATE` werden sie automatisch ausgeblendet (`exclude_disturbances` in
Abschnitt 1); eine Spulenverstellung ist keine Störung. Eine Trafoaufzeichnung ohne Fehlerstromkanal wird mit dem aus
dem Gegenstrom des Trafos geschätzten Fehlerstrom durchsucht; dafür in der Auswertung auch einen Vorfehlerbereich
eintragen.
''')),
        code('''INTERVALS = gf.Intervals(STEADY_STATE, PRE_FAULT, POST_FAULT)
SCAN = None
if roles.has("i_res") or roles.capabilities()["transformer"]:
    try:
        SCAN = disturbances.scan(rec, roles, SETTINGS)     ''' + t("# disturbed states in the whole fault, suggestion",
                                                           "# gestörte Zustände im ganzen Fehler, Vorschlag") + '''
        print(SCAN.text())
    except ValueError as ex:
        print("ℹ", ex)
interactive.rms_values(rec, roles, intervals=INTERVALS, disturbances=SCAN).show()
if SHOW_ENVELOPE:
    interactive.overview(rec, roles, intervals=INTERVALS).show()'''),
        md(t("## 4 · Evaluation", "## 4 · Auswertung")),
        keyed("pq-scaling", code('''PQ = None
if PQ_FILES:                           ''' + t("# PQ measurement of the busbar: quantiles per order and of the THD, factor of the scaling (SETTINGS)",
                                           "# PQ-Messung der Sammelschiene: Quantile je Ordnung und des THD, Faktor der Skalierung (SETTINGS)") + '''
    from dataclasses import replace
    files = [CAMPAIGN_FOLDER / p for p in ([PQ_FILES] if isinstance(PQ_FILES, (str, Path)) else PQ_FILES)]
    PQ = pq.assess(pq.read(files, timezone=PQ_TIMEZONE), quantile=PQ_QUANTILE,
                   **(dict(factors=PQ_FACTORS) if PQ_FACTORS else dict(factor=PQ_SAFETY_FACTOR)))
    print(PQ.summary())
    for h in PQ.hints:
        print("ℹ", h)
    if PQ.valid:
        SETTINGS = replace(SETTINGS, **PQ.settings())
        print(i18n.format_text("''' + t("Factor {:g} · THD quantile (largest line-to-line loop per interval) {:.3f} % → U_95 = {:.3f} % · quantiles per order: {}",
                                         "Faktor {:g} · THD-Quantil (größte Leiter-Leiter-Schleife je Intervall) {:.3f} % → U_95 = {:.3f} % · Quantile je Ordnung: {}") + '''",
                               PQ.factor, PQ.thd95(), PQ.thd95(True),
                               ", ".join(i18n.format_text("{}: {:.1f} V", m, u) for m, u in PQ.u95().items())))
    else:
        print("''' + t("⚠ The PQ measurement is not valid for the assessment (gapless values shorter than every duration of PQ_FACTORS) – no scaling.",
                       "⚠ Die PQ-Messung ist für die Bewertung nicht gültig (lückenlose Werte kürzer als jede Dauer von PQ_FACTORS) – keine Skalierung.") + '''")''')),
        code('''res = None
if STEADY_STATE is None:
    display(Markdown("''' + t("**➜ First enter `STEADY_STATE` (and `PRE_FAULT`/`POST_FAULT`) in section 1 and run again.**",
                              "**➜ Zuerst `STEADY_STATE` (und `PRE_FAULT`/`POST_FAULT`) in Abschnitt 1 eintragen und erneut ausführen.**") + '''"))
else:
    res = gf.evaluate(rec, INTERVALS, SETTINGS, roles, alignment=ALIGNMENT, name=MEASUREMENT, z_fault_ohm=Z_FAULT,
                      metadata=dict(campaign=CAMPAIGN, site=SITE))
    print(res.summary())
    display(Markdown("''' + t("**Assessment quantities** – measured value and assessment value with the measurement-uncertainty margins of section 1",
                              "**Bewertungsgrößen** – Messwert und Bewertung mit den Messunsicherheitszuschlägen aus Abschnitt 1") + '''"))
    show(res.table("assessment_quantities"))
    if "harmonic_scaling" in res.tables:
        display(Markdown("''' + t("**Scaling per order** – positive/negative sequence with its own quantile (`own voltage`), without one with the THD; zero sequence and even orders as measured (`IH_other`: content without an order, as measured)",
                                  "**Skalierung je Ordnung** – Mit-/Gegensystem mit dem eigenen Quantil (`eigene Spannung`), ohne eines mit dem THD; Nullsystem und gerade Ordnungen wie gemessen (`IH_sonstige`: Anteil ohne Ordnung, wie gemessen)") + '''"))
        show(res.table("harmonic_scaling"))
    display(Markdown("''' + t("**Plausibility checks**", "**Plausibilitätsprüfungen**") + '''"))
    show(res.table("plausibility"))
    if res.disturbances is not None and res.disturbances.found:
        display(Markdown("''' + t("**States in the steady-state interval** – disturbed states are not part of the reference (`used`)",
                                  "**Zustände im stationären Bereich** – gestörte Zustände sind nicht Teil der Referenz (`verwendet`)") + '''"))
        show(res.table("steady_state_segments"))'''),
        md(t("### Voltages before, during and after the fault", "### Spannungen vor, im und nach dem Fehler")),
        code('''if res is not None and "voltage" in res.values:
    show(res.table("voltage_metrics"))
    interactive.voltage_spectrum(res).show()'''),
        md(t("### Fault current – harmonics per window and statistics over the steady-state interval",
             "### Fehlerstrom – Harmonische je Fenster und Statistik über den stationären Bereich")),
        code('''if res is not None and res.roles.has("i_res"):
    interactive.window_spectrum(res).show()
    interactive.harmonics_time(res).show()
    if not res.table("coil_currents").empty:
        show(res.table("coil_currents"))
    show(res.table("statistics"))'''),
        md(t("### Station (earth potential rise, touch voltage, shield current) – if measured",
             "### Station (Erdungs-/Berührungsspannung, Schirmstrom) – falls gemessen")),
        code('''if res is not None:
    for name in ("station_metrics", "station_voltages", "station_currents"):
        if name in res.tables and not res.tables[name].empty:
            display(Markdown("**%s**" % report.table_title(name)))
            show(res.tables[name])'''),
        md(t('''
### Station: earth potential rise and touch voltage per frequency

Per probe and harmonic (I_F ≥ 1 % of the fundamental): **direct** = voltage/fault current during the fault, as
measured; **fault-related** = only the part caused by the fault current. Before the fault there is often already a
voltage at the station (**background**, e.g. currents from the LV network) – it is subtracted with three methods:
time reference at the fault inception, time reference at the fault clearance and (if measured) reference to the
line-to-line voltage.

**How reliable is the fault-related part?** `method_spread_pct` shows how well the methods agree. `uncertainty_pct`
estimates how much the background can distort the result: a fluctuating background (null test in the fault-free
intervals) and – without a voltage measurement – the frequency reference through the fault current, each × background
/ fault-related part. If one of them exceeds 20 %, `uncertain` is True and the figures show the value as **⊗** –
typical at 150 Hz, where the background is often larger than the fault-related part. The **touch voltage** comes from
the 1-m probe (U1m, UE1 …) or – as an approximation – from the shortest probe up to 5 m (see the role table in
section 2). For the comparison with the earthing measurement the fault-related part counts.

**PEN currents and LV network** (if `IPEN_v`/`IPEN_n` are measured): the same superposition separates the load
unbalance of the PEN current (present before the fault) from the fault-related current into the LV network I_LV.
`IPEN_v` (sum of the LV feeders, before the transformer star point) and `IPEN_n` (to the main earthing busbar) must
carry the same fault-related current (Kirchhoff's current law – the current of the transformer star point does not
change). **Z_E,LV = ΔU_E/I_LV** per frequency and as an RMS value – for every earth-potential probe and for the
**probe maximum** (`channel` = `max(UE)`, column `probe`): per frequency the highest voltage of all probes against the
station earth, as RMS value the probe with the highest RMS value. Potentials spread differently; each probe measures
at most the full earth potential rise. **Parallel check** (`parallel_check`): the LV network is a branch of the total
earthing, so |Z_E,LV| ≥ |r·Z_E| = |max(U_E)/I_F| (equivalent to |I_LV| ≤ |I_F|) at every frequency; with a shield
current also against the earth current I_E = I_F − I_S (`earth_current_check`). Violated only if the deviation exceeds
the measurement uncertainty. The comparison with the earthing measurement follows in the next section.
''', '''
### Station: Erdungs- und Berührungsspannung je Frequenz

Je Sonde und Harmonische (I_F ≥ 1 % der Grundschwingung): **direkt** = Spannung/Fehlerstrom im Fehler, wie gemessen;
**fehlerbedingt** = nur der vom Fehlerstrom verursachte Anteil. Vor dem Fehler liegt an der Station oft schon eine
Spannung an (**Grundlast**, z. B. Ströme aus dem NS-Netz) – sie wird mit drei Verfahren abgezogen: Zeitbezug am
Fehlereintritt, Zeitbezug am Fehlerende und (falls gemessen) Bezug auf die Leiter-Leiter-Spannung.

**Wie verlässlich ist der fehlerbedingte Anteil?** `Streuung_Verfahren_proz` zeigt, wie gut die Verfahren
übereinstimmen. `Unsicherheit_proz` schätzt, wie stark die Grundlast das Ergebnis verfälschen kann: schwankende
Grundlast (Nulltest in den fehlerfreien Abschnitten) und – ohne Spannungsmessung – der Frequenzbezug über den
Fehlerstrom, jeweils × Grundlast/fehlerbedingter Anteil. Liegt eines davon über 20 %, steht in `unsicher` „True“ und
die Abbildungen zeigen den Wert als **⊗** – typisch bei 150 Hz, wo die Grundlast oft größer ist als der
fehlerbedingte Anteil. Die **Berührungsspannung** stammt von der 1-m-Sonde (U1m, UE1 …) oder – Näherung – von
der kürzesten Sonde bis 5 m (siehe Rollentabelle in Abschnitt 2). Für den Vergleich mit der Erdungsmessung gilt der
fehlerbedingte Anteil.

**PEN-Ströme und Ortsnetz** (falls `IPEN_v`/`IPEN_n` gemessen): Dieselbe Überlagerung trennt beim PEN-Strom die
Unsymmetrie der Last (schon vor dem Fehler vorhanden) vom fehlerbedingten Strom ins Ortsnetz I_ON. `IPEN_v` (Summe der
NS-Abgänge, vor dem Trafoknoten) und `IPEN_n` (zur Haupterdungsschiene) müssen denselben fehlerbedingten Strom führen
(Knotenregel – der Strom des Trafosternpunkts ändert sich nicht). **Z_E,Ortsnetz = ΔU_E/I_ON** je Frequenz und als
Effektivwert – für jede Erdungsspannungssonde und für das **Sondenmaximum** (`Kanal` = `max(UE)`, Spalte `Sonde`): je
Frequenz die höchste Spannung aller Sonden gegen die Stationserde, effektiv die Sonde mit dem höchsten Effektivwert.
Die Potentiale breiten sich unterschiedlich aus; jede Sonde misst höchstens die volle Erdungsspannung.
**Prüfung Parallelschaltung** (`Pruefung_Parallelschaltung`): Das Ortsnetz ist ein Zweig der Gesamterdung, also
|Z_E,Ortsnetz| ≥ |r·Z_E| = |max(U_E)/I_F| (gleichbedeutend |I_ON| ≤ |I_F|), bei jeder Frequenz; mit
Schirmstrom zusätzlich gegen den Erdungsstrom I_E = I_F − I_S (`Pruefung_Erdungsstrom`). Verletzt erst, wenn die
Abweichung größer ist als die Messunsicherheit. Der Vergleich mit der Erdungsmessung folgt im nächsten Abschnitt.
''')),
        code('''if res is not None and not res.tables.get("station_frequency", pd.DataFrame()).empty:
    show(res.table("station_frequency"))
    if LIMITS:
        display(Markdown("''' + t("**Extrapolation to the limits of the residual current** (proportional; fault-related; with background as in the test and – upper bound – in phase)",
                                  "**Hochrechnung auf die Grenzwerte des Reststroms** (proportional; fehlerbedingt; mit Grundlast wie im Versuch und – obere Schranke – gleichphasig)") + '''"))
        show(res.table("station_extrapolation"))
    else:
        print("''' + t("ℹ Extrapolation to the limits of the residual current skipped – LIMITS is not set (section 1).",
                       "ℹ Hochrechnung auf die Grenzwerte des Reststroms übersprungen – LIMITS ist nicht gesetzt (Abschnitt 1).") + '''")
    interactive.station_frequency(res).show()
    if not res.tables.get("station_currents_frequency", pd.DataFrame()).empty:
        display(Markdown("''' + t("**PEN and shield currents per frequency** – measured during the fault, background (load unbalance) and fault-related part (share = ΔI/I_F)",
                                  "**PEN- und Schirmströme je Frequenz** – im Fehler gemessen, Grundlast (Unsymmetrie der Last) und fehlerbedingter Anteil (Anteil = ΔI/I_F)") + '''"))
        show(res.table("station_currents_frequency"))
    if not res.tables.get("station_lv_network", pd.DataFrame()).empty:
        display(Markdown("''' + t("**LV network: current I_LV and earthing impedance Z_E,LV = ΔU_E/I_LV** (per frequency and RMS value; parallel check: Z_E,LV ≥ r·Z_E = max(U_E)/I_F, earth-current check: |I_LV| ≤ |I_E|)",
                                  "**Ortsnetz: Strom I_ON und Erdungsimpedanz Z_E,Ortsnetz = ΔU_E/I_ON** (je Frequenz und effektiv; Prüfung Parallelschaltung: Z_E,Ortsnetz ≥ r·Z_E = max(U_E)/I_F, Prüfung Erdungsstrom: |I_ON| ≤ |I_E|)") + '''"))
        show(res.table("station_lv_network"))
        show(res.table("station_lv_network_eff"))
        interactive.lv_network(res.table("station_lv_network")).show()
elif res is not None:
    print("''' + t("No earth potential rise or touch voltage measured – section not applicable.",
                   "Keine Erdungs-/Berührungsspannung gemessen – Abschnitt entfällt.") + '''")'''),
        md(t('''
### Station: comparison with the earthing measurement (groundmeas)

The earthing measurements (current injection) are kept in a **groundmeas database**, which is only **read** here.
The location comes from the sites file of the campaign, otherwise from the folder name (typing errors are tolerated)
– if needed set `GROUNDMEAS_LOCATION` or `GROUNDMEAS_MEASUREMENTS` in section 1. Compared is the **voltage per ampere**
(V/A = Ω) at the same frequency: injection (probe at a comparable distance) ↔ fault-related part of the fault test.
For the earth potential rise the fault test gives **r·Z_E** = U_E/I_F – the earthing impedance times the reduction
factor, because only the earth current I_E = r·I_F flows into the earthing system (the rest returns through cable
shields) – while the earthing measurement gives Z_E itself. At a remote probe their ratio is the effective
**reduction factor**. Add probe distances that are not in the channel name (`UEr`, `UE`) to the corrections file (column
`distance_m`). The entry of this measurement in groundmeas follows in section 7.

**Reduction factor** r = r·Z_E (fault test) / Z_E (earthing measurement), magnitudes only: per harmonic – shown
over the frequency like the impedances, with the span of the superposition methods and the trend r ∝ f^b – and as an
RMS value over all harmonics (weighted with the fault current); for comparison the RMS value from the measured
RMS values (with background, earthing impedance at 50 Hz) and – if measured – the cross-check from the shield
current. Decisive is the **probe maximum** of the fault test (`max(UE)`: highest voltage of all probes) against the
farthest probe of the earthing measurement; in addition each probe against the probe at a comparable distance. If the
earthing measurement lacks a frequency, it is interpolated between the neighbouring frequencies (never extrapolated).
**Classification:** r at 50 Hz against the range you expect (`R_TYPICAL` in section 1, e.g. from your experience
with comparable installations – groundfault has no default range); r should fall with the frequency (inductive
coupling of the return conductors, f → ∞: r → 0). Much smaller values indicate too high a value of the earthing
measurement (methodological error of the fall-of-potential method) or further return paths.
**Relevance for the assessment:** for small impedances relative deviations look large – the voltage decides. Both
impedances are converted to the reference current (`REFERENCE_CURRENT`, otherwise the largest of `LIMITS`) and the
deviation is related to F·U_Tp (`F_FACTOR`, `U_TP`): `assessment_relevance` "negligible" (< 10 %), "unchanged" (both
on the same side of F·U_Tp) or "relevant". Without these values of yours the relevance is not determined.
**LV network ↔ earthing measurement:** as a parallel branch Z_E,LV should also exceed Z_E of the earthing measurement
(`injection_comparison`). If it is smaller while the check against the fault test is satisfied, the earthing
measurement probably measures too much – a finding, not an error of the LV-network evaluation.
''', '''
### Station: Vergleich mit der Erdungsmessung (groundmeas)

Die Erdungsmessungen (Strom-Einspeisung) liegen in der **groundmeas-Datenbank**. Sie wird hier nur **gelesen**.
Der Ort kommt aus der Messorte-Datei der Kampagne, sonst aus dem Ordnernamen (Tippfehler werden erkannt) – bei Bedarf
`GROUNDMEAS_LOCATION` bzw. `GROUNDMEAS_MEASUREMENTS` in Abschnitt 1 setzen. Verglichen wird **Spannung je Ampere**
(V/A = Ω) bei derselben Frequenz: Einspeisung (Sonde in vergleichbarem Abstand) ↔ fehlerbedingter Anteil im
Erdschluss. Für die Erdungsspannung liefert der Erdschluss **r·Z_E** = U_E/I_F – die Erdungsimpedanz mal den
Reduktionsfaktor, denn nur der Erdungsstrom I_E = r·I_F fließt in die Erdungsanlage (der Rest über die Kabelschirme
zurück) –, die Erdungsmessung dagegen Z_E selbst. An einer fernen Sonde ist ihr Verhältnis der wirksame
**Reduktionsfaktor**. Sondenabstände, die nicht im Kanalnamen stehen (`UEr`, `UE`), in der Korrekturen-Datei
(Spalte `Abstand_m`) nachtragen. Der Eintrag dieser Messung in groundmeas folgt in Abschnitt 7.

**Reduktionsfaktor** r = r·Z_E (Erdschluss) / Z_E (Erdungsmessung), nur Beträge: je Harmonische – über der Frequenz
dargestellt wie die Impedanzen, mit der Spanne der Überlagerungsverfahren und dem Verlauf r ∝ f^b – und als
Effektivwert über alle Harmonischen (gewichtet mit dem Fehlerstrom); zum Vergleich der Effektivwert aus den
gemessenen Effektivwerten (mit Grundlast, Erdungsimpedanz bei 50 Hz) und – falls gemessen – die Gegenprobe aus dem
Schirmstrom. Maßgeblich ist das **Sondenmaximum** des Erdschlusses (`max(UE)`: höchste Spannung aller Sonden) gegen die
fernste Sonde der Erdungsmessung; dazu jede Sonde gegen die Sonde mit vergleichbarem Abstand. Fehlt die Erdungsmessung
bei einer Frequenz, wird zwischen den Nachbarfrequenzen interpoliert (nie extrapoliert).
**Einordnung:** r bei 50 Hz gegen den Bereich, den Sie erwarten (`R_TYPICAL` in Abschnitt 1, z. B. aus eigener
Erfahrung mit vergleichbaren Anlagen – groundfault hat keinen vorgegebenen Bereich); mit steigender Frequenz sollte r
fallen (induktive Kopplung der Rückleiter, f → ∞: r → 0). Deutlich kleinere Werte deuten auf einen zu hohen Messwert
der Erdungsmessung (methodischer Fehler des Strom-Spannungs-Verfahrens) oder weitere Rückleiter.
**Bedeutung für die Bewertung:** Bei kleinen Impedanzen wirken relative Abweichungen groß – entscheidend ist die
Spannung. Beide Impedanzen werden auf den Bezugsstrom (`REFERENCE_CURRENT`, sonst der größte Wert von `LIMITS`)
umgerechnet und die Abweichung auf F·U_Tp (`F_FACTOR`, `U_TP`) bezogen: `Bewertungsrelevanz` „vernachlässigbar“
(< 10 %), „Bewertung unverändert“ (beide auf derselben Seite von F·U_Tp) oder „bewertungsrelevant“. Ohne diese
eigenen Werte wird die Bewertungsrelevanz nicht bestimmt.
**Ortsnetz ↔ Erdungsmessung:** Als Parallelzweig sollte Z_E,Ortsnetz auch über Z_E der Erdungsmessung liegen
(`Vergleich_Erdungsmessung`). Ist es kleiner, die Prüfung gegen den Erdschluss aber erfüllt, misst die Erdungsmessung
vermutlich zu viel – ein Befund, kein Fehler der Ortsnetzauswertung.
''')),
        code('''COMPARISON = RATIO = None
RF = RF_EFF = LV_CHECK = LV_CHECK_EFF = pd.DataFrame()
if res is not None and not res.tables.get("station_frequency", pd.DataFrame()).empty:
    try:
        DB = earthing.Database(GROUNDMEAS_DB)          ''' + t("# opened read-only", "# nur lesend geöffnet") + '''
    except (FileNotFoundError, ValueError) as ex:
        DB = None
        print("ℹ ''' + t("groundmeas database not available:", "groundmeas-Datenbank nicht verfügbar:") + '''", ex)
    if DB is not None:
        try:
            ENTRY = sites.load(CAMPAIGN_FOLDER).for_site(SITE)      ''' + t("# line of the sites file", "# Zeile der Messorte-Datei") + '''
        except ValueError as ex:
            ENTRY = None
            print("⚠", ex)
        LOCATION = GROUNDMEAS_LOCATION or (ENTRY.location if ENTRY is not None and ENTRY.location else None) or \\
            earthing.location_from_site(SITE)
        CHOICE = DB.choose_location(LOCATION, exact_only=bool(GROUNDMEAS_LOCATION or (ENTRY is not None and ENTRY.location)),
                                    preset='GROUNDMEAS_LOCATION = "{}"')
        LOCATION_DB = CHOICE["location"]
        if CHOICE["note"]:
            print("ℹ", CHOICE["note"])
        if LOCATION_DB is None and len(CHOICE["candidates"]):
            display(Markdown("''' + t("**Locations in groundmeas with similar names:**", "**Orte in groundmeas, die ähnlich heißen:**") + '''"))
            show(CHOICE["candidates"])
        if GROUNDMEAS_MEASUREMENTS:
            MEAS = DB.measurements()[lambda d: d["measurement_id"].isin(GROUNDMEAS_MEASUREMENTS)]
        else:
            MEAS = DB.measurements(location=LOCATION_DB) if LOCATION_DB else DB.measurements().iloc[0:0]
        MEAS = earthing.exclude_own(MEAS, CAMPAIGN, MEASUREMENT)   ''' + t("# do not compare the own entry with itself", "# eigenen Eintrag nicht mit sich selbst vergleichen") + '''
        display(Markdown("''' + t("**groundmeas: %s** – %d measurement(s) at the location “%s” (searched: “%s”)",
                                  "**groundmeas: %s** – %d Messung(en) am Ort „%s“ (gesucht: „%s“)") + '''"
                         % (DB.path, len(MEAS), LOCATION_DB or "–", LOCATION)))
        show(MEAS)
        RESPONSE = earthing.frequency_response(DB, MEAS["measurement_id"])
        COMPARISON, RATIO = earthing.compare(res.table("station_frequency"), RESPONSE, measurement=MEASUREMENT)
        if len(RATIO):
            display(Markdown("''' + t("**Ratio fault test / earthing measurement per frequency** (column `distance_match`: \\\"different\\\" = probes not comparable, not to be read as a reduction factor)",
                                      "**Verhältnis Erdschluss / Erdungsmessung je Frequenz** (Spalte `Abstandsvergleich`: „abweichend“ = Sonden nicht vergleichbar, nicht als Reduktionsfaktor deuten)") + '''"))
            show(RATIO)
        if COMPARISON["source"].isin([earthing.SOURCE_INJECTION, earthing.SOURCE_GROUNDMEAS_FAULT]).any():
            interactive.earthing_comparison(COMPARISON, RATIO).show()
        else:
            print("''' + t("No matching values in groundmeas for “%s” – check the location/ids in section 1.",
                           "Keine passenden Werte in groundmeas für „%s“ – Ort/IDs in Abschnitt 1 prüfen.") + '''" % LOCATION)
        RF, RF_EFF = earthing.reduction_factor(res, RESPONSE, reference_current_A=REFERENCE_CURRENT,
                                               r_typical=R_TYPICAL)      ''' + t("# U_Tp, F and LIMITS from SETTINGS", "# U_Tp, F und LIMITS aus SETTINGS") + '''
        if len(RF_EFF) and R_TYPICAL is None:
            print("''' + t("ℹ No classification of r at 50 Hz – R_TYPICAL is not set (section 1).",
                           "ℹ Keine Einordnung von r bei 50 Hz – R_TYPICAL ist nicht gesetzt (Abschnitt 1).") + '''")
        NOT_SET = [v for v, c in (("REFERENCE_CURRENT ''' + t("or", "oder") + ''' LIMITS", "reference_current_A"), ("U_TP", "U_Tp_V"),
                                  ("F_FACTOR", "F_factor")) if len(RF_EFF) and RF_EFF[c].isna().all()]
        if NOT_SET:                    ''' + t("# relevance for the assessment: reference current, U_Tp and F of section 1",
                                                "# Bedeutung für die Bewertung: Bezugsstrom, U_Tp und F aus Abschnitt 1") + '''
            print("''' + t("ℹ Relevance of the deviation for the assessment not determined – not set (section 1): %s",
                           "ℹ Bedeutung der Abweichung für die Bewertung nicht bestimmt – nicht gesetzt (Abschnitt 1): %s") + '''"
                  % ", ".join(NOT_SET))
        if len(RF_EFF):
            display(Markdown("''' + t("**Reduction factor** – RMS value (`r_eff`, for comparison from the measured RMS values and from the shield current; classification at 50 Hz, trend over f, relevance for the assessment) and per harmonic (`r`); first rows: probe maximum",
                                      "**Reduktionsfaktor** – effektiv (`r_eff`, zum Vergleich aus den gemessenen Effektivwerten und aus dem Schirmstrom; Einordnung bei 50 Hz, Verlauf über f, Bedeutung für die Bewertung) und je Harmonische (`r`); erste Zeilen: Sondenmaximum") + '''"))
            show(RF_EFF); show(RF)
            interactive.reduction_factor(RF, RF_EFF).show()
        LV_CHECK, LV_CHECK_EFF = earthing.check_lv_network(res, RESPONSE)
        if len(LV_CHECK):
            display(Markdown("''' + t("**LV network ↔ earthing measurement** (ratio Z_E,LV/Z_E ≥ 1 expected; parallel check: against the fault test)",
                                      "**Ortsnetz ↔ Erdungsmessung** (Verhältnis Z_E,Ortsnetz/Z_E ≥ 1 erwartet; Prüfung Parallelschaltung: gegen den Erdschluss)") + '''"))
            show(LV_CHECK_EFF); show(LV_CHECK)
            interactive.lv_network(res.table("station_lv_network"), LV_CHECK).show()
        for h in earthing.reduction_hints(RF_EFF, LV_CHECK):
            print("⚠", h)
        DB.close()'''),
        keyed("transformer-node-text", md(t('''
### Transformer node: power and impedance per harmonic before, during and after the fault

With the three line currents of the HV/MV transformer (`I1` … `I3`, `IL1` … `IL3`) and the busbar voltages, the
harmonic sources of the whole network – bundled at the transformer – can be followed through the fault. The states
are the pre-fault interval, the undisturbed windows of `STEADY_STATE` and the post-fault interval. Without a
fault-current channel the fault current for the detection of disturbed states (active residual current increase,
network change) is estimated from the change of the negative-sequence current of the transformer (3·ΔI₂).

* **Power per order** (sum of the sequences, consumer reference arrow system: P > 0 flows from the HV into the MV
  network). P_m < 0 means that the MV network as a whole feeds this harmonic into the HV network. Table
  `transformer_node` holds U, I, P, Q and the apparent impedance U/I per state, order and sequence,
  `transformer_power_change` the changes fault − pre-fault and post-fault − pre-fault (null test).
* **Upstream impedance** Z_up = −ΔU/ΔI (`transformer_impedance`): the earth fault draws positive- and
  negative-sequence currents of every order through the transformer; the busbar voltage changes by −Z_up·ΔI. Z_up is
  the impedance of transformer and HV network seen from the MV busbar – inductive, X_up/m about constant. Two
  estimates (fault − pre-fault, fault − post-fault) and the null test give the uncertainty; `significant` = at most
  20 %. Positive and negative sequence must agree (`pos_neg_deviation_pct`); orders divisible by 3 and the
  fundamental are affected by other effects (voltage transformers at the raised voltage of the healthy phases, load
  changes). With HV voltages Z_up is split into transformer and HV network.
* **Polarity:** a capacitive Z_up means that the currents were measured in the generator reference arrow system –
  they are reversed automatically (hint and plausibility table); `transformer_sign` in `SETTINGS` (section 1) fixes
  the sign.
''', '''
### Trafoknoten: Leistung und Impedanz je Harmonische vor, im und nach dem Erdschluss

Mit den drei Leiterströmen des HS/MS-Trafos (`I1` … `I3`, `IL1` … `IL3`) und den Sammelschienenspannungen lässt sich
verfolgen, wie sich die Oberschwingungsquellen des ganzen Netzes – gebündelt am Trafo – im Erdschluss verhalten. Die
Zustände sind der Vorfehlerbereich, die ungestörten Fenster von `STEADY_STATE` und der Nachfehlerbereich. Ohne
Fehlerstromkanal wird der Fehlerstrom für die Erkennung gestörter Zustände (Wattreststromerhöhung, Netzänderung) aus
der Änderung des Gegenstroms des Trafos geschätzt (3·ΔI₂).

* **Leistung je Ordnung** (Summe der Systeme, Verbraucherzählpfeilsystem: P > 0 fließt vom HS- ins MS-Netz). P_m < 0
  heißt: Das MS-Netz speist diese Harmonische als Ganzes ins HS-Netz. Die Tabelle `trafoknoten` enthält U, I, P, Q
  und die scheinbare Impedanz U/I je Zustand, Ordnung und System, `trafo_leistungsaenderung` die Änderungen
  Erdschluss − Vorfehler und Nachfehler − Vorfehler (Nulltest).
* **Vorimpedanz** Z_vor = −ΔU/ΔI (`trafo_impedanz`): Der Erdschluss zieht Mit- und Gegenströme aller Ordnungen über
  den Trafo; die Sammelschienenspannung ändert sich um −Z_vor·ΔI. Z_vor ist die Impedanz von Trafo und HS-Netz von der
  MS-Sammelschiene aus – induktiv, X_vor/m etwa konstant. Zwei Schätzungen (Erdschluss − Vorfehler,
  Erdschluss − Nachfehler) und der Nulltest ergeben die Unsicherheit; `signifikant` = höchstens 20 %. Mit- und
  Gegensystem müssen übereinstimmen (`Abweichung_Mit_Gegen_proz`); durch 3 teilbare Ordnungen und die
  Grundschwingung sind von anderen Effekten beeinflusst (Spannungswandler bei der erhöhten Spannung der gesunden
  Leiter, Laständerungen). Mit HS-Spannungen wird Z_vor in Trafo und HS-Netz aufgeteilt.
* **Polarität:** Eine kapazitive Z_vor bedeutet, dass die Ströme im Erzeugerzählpfeilsystem gemessen wurden – sie
  werden automatisch umgekehrt (Hinweis und Plausibilitätstabelle); `transformer_sign` in `SETTINGS` (Abschnitt 1)
  legt das Vorzeichen fest.
'''))),
        keyed("transformer-node", code('''if res is not None and "transformer_node" in res.tables:
    display(Markdown("**''' + t("Transformer node:", "Trafoknoten:") + '''** " + transformer.summary_text(res)))
    display(Markdown("**''' + t("Power per order", "Leistung je Ordnung") + '''** (''' + t("sum of the sequences, in kW and kvar", "Summe der Systeme, in kW und kvar") + ''')"))
    show(transformer.power_overview(res))
    if "transformer_impedance" in res.tables:
        ZI = res.table("transformer_impedance")
        display(Markdown("**%s** (''' + t("significant orders", "signifikante Ordnungen") + ''')" % report.table_title("transformer_impedance")))
        show(ZI[ZI["significant"]])
        report.transformer_impedance(res)
    report.transformer_power(res)
elif res is not None:
    print("''' + t("No transformer currents measured – section not applicable.", "Keine Trafoströme gemessen – Abschnitt entfällt.") + '''")''')),
        md(t('''
## 5 · Signal explorer – check the values at the curve

All channels of the recording: **at the top** the RMS value per 200-ms window over the whole file – on hover all
selected channels show RMS value, harmonics (H1, H3, H5, H7), THD and DC component at the same instant; **below**
instantaneous values, spectrum and characteristic values of the excerpt marked grey. Operation: select channels on the
left (Ctrl/⌘ or Shift for several), move the excerpt with the slider, with *instant* (fault inception, max window, …)
or ◀ ▶, set *width* and *up to order*. The max window gives the same values as the evaluation. The explorer also works
before the intervals are entered (then without the max window).
''', '''
## 5 · Signal-Explorer – Werte an der Kurve prüfen

Alle Kanäle der Aufzeichnung: **oben** der Effektivwert je 200-ms-Fenster über der ganzen Datei – der Mouse-over zeigt
für alle gewählten Kanäle Effektivwert, Harmonische (H1, H3, H5, H7), THD und Gleichanteil zum selben Zeitpunkt;
**darunter** Momentanwerte, Spektrum und Kennwerte des grau markierten Ausschnitts. Bedienung: Kanäle links wählen
(Strg/⌘ bzw. Shift für mehrere), Ausschnitt mit dem Schieberegler, *Zeitpunkt* (Fehlereintritt, Max-Fenster, …)
oder ◀ ▶ verschieben, *Breite* und *bis Ordnung* einstellen. Das Max-Fenster liefert dieselben Werte wie die Auswertung.
Der Explorer funktioniert auch schon vor dem Eintragen der Bereiche (dann ohne Max-Fenster).
''')),
        code('''EX = explorer.explorer(rec, res, alignment=ALIGNMENT) if SIGNAL_EXPLORER else None
EX'''),
        md(t("## 6 · Checks (optional)", "## 6 · Kontrollen (optional)")),
        code('''FT = VC = None
if res is not None:
    interactive.frequency_diagnosis(rec, res).show()
    P_RMS = CAMPAIGN_FOLDER / RMS_FILE if RMS_FILE else None
    if P_RMS is not None and not P_RMS.is_file():
        CANDIDATES = sorted(str(p.relative_to(CAMPAIGN_FOLDER)) for p in P_RMS.parent.glob("*.cfg")) if P_RMS.parent.is_dir() else []
        print("''' + t("⚠ RMS_FILE not found: %s – check skipped.%s", "⚠ RMS_FILE nicht gefunden: %s – Kontrolle übersprungen.%s") + '''" % (
            RMS_FILE, (" ''' + t("Files in the folder:", "Im Ordner vorhanden:") + ''' " + ", ".join(CANDIDATES)) if CANDIDATES else ""))
    elif P_RMS is not None:
        rec_rms = gf.open_recording(str(P_RMS))
        CORR.apply(rec_rms)                 ''' + t("# the same corrections for the RMS file", "# dieselben Korrekturen auch auf die RMS-Datei") + '''
        for h in CORR.hints:                ''' + t("# hints on the RMS file (e.g. no sign there)", "# Hinweise zur RMS-Datei (z. B. kein Vorzeichen)") + '''
            print("⚠", h)
        display(Markdown("''' + t("**Own true RMS value ↔ RMS value of the recorder** – deviations come mainly from DC offsets of the clamps (the recorder includes the DC, the evaluation removes it).",
                                  "**Eigener Echt-Effektivwert ↔ RMS des Messgeräts** – Abweichungen entstehen v. a. durch DC-Offsets der Zangen (das Gerät rechnet den DC mit, die Auswertung entfernt ihn).") + '''"))
        show(rms.compare_with_instantaneous(rec, rec_rms, STEADY_STATE))
    if V_CURVE and res.roles.has("i_res"):
        FT = rms.fundamental_trend(rec, STEADY_STATE, res.roles)
        VC = rms.v_curve(FT["t_s"], FT["IH1_A"])
        print(i18n.format_text("''' + t("Resonance curve: smallest fundamental current {:.2f} A at {:.2f} s{} {}",
                                         "V-Kurve: kleinster Grundschwingungsstrom {:.2f} A bei {:.2f} s{} {}") + '''",
                               VC.I_min_measured, VC.t_min_s, "" if np.isnan(VC.I_min_fit) else i18n.format_text(
                                   " (''' + t("fitted parabola", "Ausgleichsparabel") + ''': {:.2f} A)", VC.I_min_fit), VC.note))
        show(FT)
        report.v_curve(FT["t_s"], FT["IH1_A"], VC, quantity="I_G")'''),
        md(t('''
## 7 · Export for the campaign evaluation and the report

* `<results>/<measurement>/<measurement>_result.json` – complete result (input of `evaluate_campaign.ipynb`)
* `<results>/<measurement>/tables/` – all tables as CSV, Markdown, one Excel workbook and one Word file with
  formatted tables
* `<figures>/<measurement>/` – figures in final size (15.9 cm wide, without titles) as PDF, SVG and PNG
* `<figures>/<measurement>/<measurement>_explorer.html` – signal explorer to pass on (opens in a browser without
  Python; for stations with the figures per frequency and the comparison with the earthing measurement)
''', '''
## 7 · Export für Kampagnenauswertung und Bericht

* `2_Auswertung/<Messung>/<Messung>_ergebnis.json` – vollständiges Ergebnis (Grundlage für `Kampagne_auswerten.ipynb`)
* `2_Auswertung/<Messung>/tabellen/` – alle Tabellen als CSV (Semikolon/Dezimalkomma), Markdown, eine Excel-Mappe
  und eine Word-Datei mit formatierten Tabellen
* `3_Abbildungen/<Messung>/` – Abbildungen in Endgröße (15,9 cm breit, ohne Titel) als PDF, SVG und PNG
* `3_Abbildungen/<Messung>/<Messung>_explorer.html` – Signal-Explorer zum Weitergeben (im Browser öffnen, ohne Python;
  bei Stationen mit den Abbildungen „frequenzselektiv“ und „Vergleich mit der Erdungsmessung“)
''')),
        code('''if res is not None:
    RESULTS = CAMPAIGN_FOLDER / LAYOUT.results / MEASUREMENT
    FIGURES = CAMPAIGN_FOLDER / LAYOUT.figures / MEASUREMENT
    p = res.save_json(LAYOUT.result_path(CAMPAIGN_FOLDER, MEASUREMENT))
    has_comparison = COMPARISON is not None and COMPARISON["source"].isin(
        [earthing.SOURCE_INJECTION, earthing.SOURCE_GROUNDMEAS_FAULT]).any()
    TABLES = dict(res.tables)
    if has_comparison:                 ''' + t("# comparison with groundmeas in the same workbook/Word file", "# Vergleich mit groundmeas in dieselbe Excel-/Word-Datei") + '''
        TABLES.update(earthing_comparison=COMPARISON, earthing_ratio=RATIO)
    TABLES.update({n: df for n, df in (("reduction_factor", RF), ("reduction_factor_eff", RF_EFF),
                                       ("lv_network_check", LV_CHECK), ("lv_network_check_eff", LV_CHECK_EFF)) if len(df)})
    tables = report.export_tables(TABLES, str(RESULTS / ("tables" if LAYOUT.language == "en" else "tabellen")),
                                  prefix=MEASUREMENT + "_", formats=("csv", "md"))
    figures = report.all_figures(res, str(FIGURES), rec=rec, prefix=MEASUREMENT + "_", formats=EXPORT_FORMATS)
    if VC is not None:
        figures += report.save(report.v_curve(FT["t_s"], FT["IH1_A"], VC, quantity="I_G"),
                               str(FIGURES / (MEASUREMENT + "_v_curve")), EXPORT_FORMATS, close=True)
    extra = {}
    if not res.tables.get("station_frequency", pd.DataFrame()).empty:
        extra["''' + t("Earth potential rise and touch voltage per frequency", "Erdungs- und Berührungsspannung frequenzselektiv") + '''"] = interactive.station_frequency(res)
    if has_comparison:
        figures += report.save(report.earthing_comparison(COMPARISON, RATIO),
                               str(FIGURES / (MEASUREMENT + "_earthing_comparison")), EXPORT_FORMATS, close=True)
        extra["''' + t("Earthing measurement (groundmeas) and fault test per frequency", "Erdungsmessung (groundmeas) und Erdschluss je Frequenz") + '''"] = interactive.earthing_comparison(COMPARISON, RATIO)
    if len(RF_EFF):
        figures += report.save(report.reduction_factor(RF, RF_EFF), str(FIGURES / (MEASUREMENT + "_reduction_factor")),
                               EXPORT_FORMATS, close=True)
        extra["''' + t("Reduction factor per harmonic", "Reduktionsfaktor je Harmonische") + '''"] = interactive.reduction_factor(RF, RF_EFF)
    if not res.tables.get("station_lv_network", pd.DataFrame()).empty:
        if len(LV_CHECK):              ''' + t("# with the earthing measurement (otherwise the standard figure station_lv_network)", "# mit Erdungsmessung (sonst ohne – Standardabbildung station_lv_network)") + '''
            figures += report.save(report.lv_network(res.table("station_lv_network"), LV_CHECK),
                                   str(FIGURES / (MEASUREMENT + "_lv_network_injection")), EXPORT_FORMATS, close=True)
        extra["''' + t("LV network: current and earthing impedance", "Ortsnetz: Strom und Erdungsimpedanz") + '''"] = interactive.lv_network(
            res.table("station_lv_network"), LV_CHECK if len(LV_CHECK) else None)
    if EXPLORER_HTML:
        h = explorer.explorer_html(rec, str(FIGURES / (MEASUREMENT + "_explorer.html")), res, figures=extra,
                                   alignment=ALIGNMENT)
        print("''' + t("Signal explorer (HTML):", "Signal-Explorer (HTML):") + '''", Path(h).relative_to(WORK_FOLDER))
    if RECORD_INTERVALS and DEMO:      ''' + t("# the demo changes nothing outside its campaign folder", "# die Demo ändert nichts außerhalb ihres Kampagnenordners") + '''
        print("''' + t("Register of the work folder left unchanged (demo)", "Messregister des Arbeitsordners unverändert (Demo)") + '''")
    elif RECORD_INTERVALS:
        args = (str(WORK_FOLDER), str(CFG.relative_to(WORK_FOLDER)), STEADY_STATE, PRE_FAULT, POST_FAULT, Z_FAULT)
        ok = register.record_intervals(*args)
        if not ok:                     ''' + t("# new file → read the register again (manual columns are kept)", "# neue Datei → Register neu einlesen (Handspalten bleiben erhalten)") + '''
            register.write_register(str(WORK_FOLDER))
            ok = register.record_intervals(*args)
        print("''' + t("Register updated", "Messregister aktualisiert") + '''" if ok else "''' + t("File not in the register – check the path", "Datei nicht im Messregister – Pfad prüfen") + '''")
    print("''' + t("Result:", "Ergebnis:") + '''", Path(p).relative_to(WORK_FOLDER))
    print("''' + t("%d table files, %d figure files", "%d Tabellen-Dateien, %d Abbildungsdateien") + '''" % (len(tables), len(figures)))'''),
        md(t('''
### groundmeas – enter this measurement

The evaluated measurement can be entered as a **staged fault test** (`staged_fault_test`) in the groundmeas database –
its dashboard then shows it at the same location as the earthing measurement. **Station:** fault current, earth
potential rise and touch voltage per probe (with distance) and frequency – fault-related part, angle relative to I_F
– and shield current; **substation:** fault current per order, fault resistance = additional impedance. Location,
coordinates, asset type, voltage level and distance to the substation come from the sites file of the campaign
(created pre-filled from groundmeas the first time – **enter coordinates for a new location**). At first only the
planned entry is shown (dry run); it is written with `GROUNDMEAS_EXPORT = True` – after a backup copy of the database,
in one transaction, without changing existing entries. An entry made before is recognised;
`GROUNDMEAS_EXPORT = "replace"` renews the own entry.
''', '''
### groundmeas – diese Messung eintragen

Die ausgewertete Messung kann als **Erdschlussmessung** (`staged_fault_test`) in die groundmeas-Datenbank übernommen
werden – dort steht sie im Dashboard am selben Ort wie die Erdungsmessung. **Station:** Fehlerstrom, Erdungs- und
Berührungsspannung je Sonde (mit Abstand) und Frequenz – fehlerbedingter Anteil, Winkel bezogen auf I_F – und
Schirmstrom; **UW:** Fehlerstrom je Ordnung, Fehlerwiderstand = Zusatzimpedanz. Ort, Koordinaten, Anlagentyp,
Spannungsebene und Entfernung zum UW stehen in der Messorte-Datei der Kampagne (wird beim ersten Mal aus groundmeas
vorbelegt angelegt – für einen **neuen Ort Koordinaten eintragen**). Zunächst wird nur angezeigt, was eingetragen würde
(Trockenlauf); geschrieben wird mit `GROUNDMEAS_EXPORT = True` – nach einer Sicherungskopie der Datenbank, in einer
Transaktion, ohne vorhandene Einträge zu verändern. Eine schon eingetragene Messung wird erkannt;
`GROUNDMEAS_EXPORT = "replace"` erneuert den eigenen Eintrag.
''')),
        code('''legacy.check_option("GROUNDMEAS_EXPORT", GROUNDMEAS_EXPORT, (False, True, "replace"))
PLAN = None
if res is not None:
    try:
        PLAN = earthing.export_to_groundmeas(
            res, CAMPAIGN_FOLDER, GROUNDMEAS_DB, location=GROUNDMEAS_LOCATION, write=bool(GROUNDMEAS_EXPORT),
            existing="replace" if GROUNDMEAS_EXPORT == "replace" else "skip", uncertain_mode=GROUNDMEAS_UNCERTAIN,
            description=GROUNDMEAS_DESCRIPTION, timezone=GROUNDMEAS_TIMEZONE, timestamp=GROUNDMEAS_TIMESTAMP,
            units=GROUNDMEAS_UNITS)
    except (FileNotFoundError, ValueError) as ex:
        print("ℹ ''' + t("groundmeas entry not possible:", "groundmeas-Eintrag nicht möglich:") + '''", ex)
if PLAN is not None:
    for h in PLAN["hints"]:
        print("ℹ", h)
    for w in PLAN["warnings"]:
        print("⚠ ''' + t("check before entering:", "vor dem Eintragen prüfen:") + '''", w)
    show(earthing.plan_overview({MEASUREMENT: PLAN}))
    if PLAN["written"]:
        print("''' + t("✓ %s in groundmeas: measurement %d at the location “%s” (location %d) – backup copy: %s – now set GROUNDMEAS_EXPORT back to False.",
                       "✓ in groundmeas %s: Messung %d am Ort „%s“ (Ort %d) – Sicherungskopie: %s – jetzt GROUNDMEAS_EXPORT wieder auf False stellen.") + '''"
              % ("''' + t("renewed", "erneuert") + '''" if PLAN.get("renewed") else "''' + t("entered", "eingetragen") + '''", PLAN["measurement_id"], PLAN["location"],
                 PLAN["location_id"], PLAN["backup"]))
    elif not PLAN["writable"]:
        print("ℹ ''' + t("Not entered:", "Nicht eingetragen:") + ''' %s" % ("; ".join(PLAN["reasons"]) or PLAN.get("reason", "")))
    else:
        display(Markdown("''' + t("**Dry run** – the measurement would be entered like this (write with `GROUNDMEAS_EXPORT = True`):",
                                  "**Trockenlauf** – so würde die Messung eingetragen (schreiben mit `GROUNDMEAS_EXPORT = True`):") + '''"))
    print("''' + t("Description:", "Beschreibung:") + '''", PLAN["measurement"]["description"])
    show(earthing.plan_items(PLAN))'''),
        md(t('''
---
**Conventions**
* Phasors are RMS phasors (cosine convention). Angles in the tables "ref. U_L1-L2" refer to the fundamental of the
  line-to-line voltage U_L1-L2 (order m: X_m·e^(−j·m·φ)) and are therefore independent of the time origin of the
  recording.
* Polarity: the active component of the fundamental must be positive (Iw > 0). If it is negative, the fault current
  is rotated by 180° (note in the table). With this orientation **Iv > 0 means over-compensation** (inductive excess).
* DC offset: removed per window by the median. RMS value = true RMS value over all frequencies, not only over the
  selected harmonics.
''', '''
---
**Konventionen**
* Phasoren sind Effektivwertzeiger (Kosinus-Konvention). Winkel in den Tabellen „bez. U_L1-L2“ sind auf die
  Grundschwingung der Leiter-Leiter-Spannung U_L1-L2 bezogen (Ordnung m: X_m·e^(−j·m·φ)) und damit unabhängig vom
  Zeitursprung der Aufzeichnung.
* Polarität: Der Wirkanteil der Grundschwingung muss positiv sein (Iw > 0). Ist er negativ, wird der Fehlerstrom um
  180° gedreht (Hinweis in der Tabelle). Mit dieser Orientierung bedeutet **Iv > 0 Überkompensation** (induktiver
  Überschuss).
* DC-Offset: je Fenster per Median entfernt. Effektivwert = Echt-Effektivwert über alle Frequenzen, nicht nur über
  die ausgewählten Harmonischen.
''')),
    ]
    return _notebook(cells, lang, NAMES[lang][0])


# =========================================================================== campaign
def campaign_notebook(lang: str, example: bool) -> nbf.NotebookNode:
    t = (lambda en, de: en if lang == "en" else de)
    if example:
        conf = t('''CAMPAIGN = "2026-01-15_Demo"
DEMO     = True      # create the demo campaign and evaluate its recordings if the result files are missing
# Result files of evaluate_measurement.ipynb: <results>/<measurement>/<measurement>_result.json
# Order = columns of the report tables. Z = additional impedance in Ω (None → not in the equivalent-source method)
MEASUREMENTS = [
    dict(name="Measurement 1 (SUB 2.5 Ω)", measurement="SUB_2_5_10_000kHz", Z=2.5),
    dict(name="Measurement 2 (SUB 5 Ω)",   measurement="SUB_5_10_000kHz",   Z=5.0),
    dict(name="Measurement 3 (SUB 0 Ω)",   measurement="SUB_0_10_000kHz",   Z=0.0),
    dict(name="Measurement 4 (Station)",   measurement="Station_Elm_Road_10_000kHz", Z=None),
]''', '''CAMPAIGN = "2026-01-15_Demo"
DEMO     = True      # Demo-Kampagne anlegen und auswerten, falls die Ergebnisdateien fehlen
# Ergebnisdateien aus Messung_auswerten.ipynb: 2_Auswertung/<Messung>/<Messung>_ergebnis.json
# Reihenfolge = Spalten der Berichtstabellen. Z = Zusatzimpedanz in Ω (None → nicht im Ersatzquellenverfahren)
MEASUREMENTS = [
    dict(name="Messung 1 (UW 2,5 Ω)", measurement="UW_2_5_10_000kHz", Z=2.5),
    dict(name="Messung 2 (UW 5 Ω)",   measurement="UW_5_10_000kHz",   Z=5.0),
    dict(name="Messung 3 (UW 0 Ω)",   measurement="UW_0_10_000kHz",   Z=0.0),
    dict(name="Messung 4 (Station)",  measurement="Station_Elm_Road_10_000kHz", Z=None),
]''')
        db = 'str(WORK_FOLDER / "demo_groundmeas.db")   ' + t("# demo database (written with the demo campaign)",
                                                              "# Demo-Datenbank (mit der Demo-Kampagne angelegt)")
        z_e = "2.5                " + t("# demo value: earthing impedance in Ω at which I_RES is computed",
                                        "# Demo-Wert: Erdungsimpedanz in Ω, an der I_RES berechnet wird")
        pq_files = t('''["raw/PQ/SUB_PQ_export.csv"]   # demo: PQ export of the demo busbar (written with the demo campaign)''',
                     '''["1_Rohdaten/PQ/UW_PQ_Export.csv"]   # Demo: PQ-Export der Demo-Sammelschiene (mit der Demo-Kampagne angelegt)''')
    else:
        conf = t('''CAMPAIGN = "YYYY-MM-DD_Place"
DEMO     = False
# Result files of evaluate_measurement.ipynb: <results>/<measurement>/<measurement>_result.json
# Order = columns of the report tables. Z = additional impedance in Ω (None → not in the equivalent-source method)
MEASUREMENTS = [
    dict(name="Measurement 1 (substation 2.5 Ω)", measurement="<measurement_2_5>", Z=2.5),
    dict(name="Measurement 2 (substation 5 Ω)",   measurement="<measurement_5>",   Z=5.0),
    dict(name="Measurement 3 (substation 0 Ω)",   measurement="<measurement_0>",   Z=0.0),
    dict(name="Measurement 4 (station)",          measurement="<station>",         Z=None),
]''', '''CAMPAIGN = "JJJJ-MM-TT_Ort"
DEMO     = False
# Ergebnisdateien aus Messung_auswerten.ipynb: 2_Auswertung/<Messung>/<Messung>_ergebnis.json
# Reihenfolge = Spalten der Berichtstabellen. Z = Zusatzimpedanz in Ω (None → nicht im Ersatzquellenverfahren)
MEASUREMENTS = [
    dict(name="Messung 1 (UW 2,5 Ω)", measurement="<Messung_2_5>", Z=2.5),
    dict(name="Messung 2 (UW 5 Ω)",   measurement="<Messung_5>",   Z=5.0),
    dict(name="Messung 3 (UW 0 Ω)",   measurement="<Messung_0>",   Z=0.0),
    dict(name="Messung 4 (Station)",  measurement="<Station>",     Z=None),
]''')
        db = "None   " + t("# None = as groundmeas (environment variable GROUNDMEAS_DB or ~/.config/groundmeas/config.json)",
                           "# None = wie groundmeas (Umgebungsvariable GROUNDMEAS_DB bzw. ~/.config/groundmeas/config.json)")
        z_e = "None               " + t("# earthing impedance in Ω at which I_RES is computed – a value of your network (None = not set)",
                                        "# Erdungsimpedanz in Ω, an der I_RES berechnet wird – Wert des eigenen Netzes (None = nicht gesetzt)")
        pq_files = t('''None               # export(s) of a PQ instrument at the busbar, e.g. ["…/Export.csv"] (relative to the campaign folder or absolute)''',
                     '''None               # Export(e) eines PQ-Messgeräts an der Sammelschiene, z. B. ["…/Export.csv"] (relativ zum Kampagnenordner oder absolut)''')
    conf += t('''
# optional per measurement: location="…" (exact location name in groundmeas, otherwise from the sites file or the
# site), description="…" (text before the automatic groundmeas description), timestamp="YYYY-MM-DD hh:mm:ss" (UTC,
# only for a wrongly set recorder clock)''', '''
# optional je Messung: location="…" (genauer Ortsname in groundmeas, sonst aus der Messorte-Datei bzw. dem Messort),
# description="…" (Text vor der automatischen groundmeas-Beschreibung, englisch), timestamp="JJJJ-MM-TT hh:mm:ss"
# (UTC, nur bei falsch gestellter Geräteuhr)''')
    cells = [
        md(t('''
# Evaluate a campaign – overview, equivalent-source method, report tables

Works only with the **result files** of the single evaluations (`evaluate_measurement.ipynb`, section 7) – the raw
data are not read again. Reference copy: `templates/evaluate_campaign_DEFAULT.ipynb`.

1. **Overview and consistency** of the measurements (same fundamental component, coil currents, harmonics decrease
   with Z).
2. **Equivalent-source method**: active two-terminal equivalent per harmonic with a common angle reference
   (U_L1-L2), normalization of the source fluctuation to the voltage level before/after the fault, two estimators in
   comparison, pairwise solution of two measurements, forecast error, jackknife and Monte Carlo uncertainty – and the
   **measured source** (U_q = pre-fault voltage of the faulted phase, Z_q from the tests), which carries beyond the
   tested additional impedances.
3. **Residual current at Z_E** with the measured source (or the fitted one, `SOURCE`), the other one for comparison,
   scaling to the quantile of a **PQ measurement** of the busbar (read from the export of the PQ instrument: 10-min
   values, largest phase, quantile, factor by the duration) and your limits of the residual current; **resistive
   approach** (after the VDE Impuls on the residual earth-fault current).
4. **Stations** – earth potential rise and touch voltage per frequency (direct and fault-related), comparison with
   the earthing measurements from **groundmeas**, **reduction factor** (per harmonic and RMS value) and – with PEN
   currents – current into the **LV network** and Z_E,LV with the parallel check.
5. **Report tables** and **figures** – export to `<results>/campaign` and `<figures>/campaign`.
6. **groundmeas** – enter all measurements of the campaign as staged fault tests (dry run, then on request).
''', '''
# Messkampagne auswerten – Übersicht, Ersatzquellenverfahren, Berichtstabellen

Arbeitet ausschließlich mit den **Ergebnisdateien** der Einzelauswertungen (`Messung_auswerten.ipynb`, Abschnitt 7) –
die Rohdaten werden nicht erneut gelesen. Ausgangsfassung: `Vorlagen/Kampagne_auswerten_DEFAULT.ipynb`.

1. **Übersicht und Konsistenz** der Messungen (gleiche Grundschwingung, Spulenströme, Oberschwingungen sinken mit Z).
2. **Ersatzquellenverfahren**: aktiver Zweipol je Harmonische mit gemeinsamem Winkelbezug (U_L1-L2), Normierung der
   Quellschwankung auf den Spannungspegel vor/nach dem Fehler, zwei Schätzverfahren im Vergleich, paarweise Lösung aus
   je zwei Messungen, Prognosefehler, Jackknife und Monte-Carlo-Unsicherheit – und die **gemessene Quelle**
   (U_q = Vorfehlerspannung des Fehlerleiters, Z_q aus den Versuchen), die über die Zusatzimpedanzen der Versuche
   hinaus trägt.
3. **Erdschlussreststrom an Z_E** mit der gemessenen Quelle (oder der geschätzten, `SOURCE`), die andere zum
   Vergleich, Skalierung auf das Quantil einer **PQ-Messung** der Sammelschiene (aus dem Export des PQ-Messgeräts:
   10-min-Werte, größter Leiter, Quantil, Faktor nach Messdauer) und den eigenen Grenzwerten des Reststroms;
   **resistiver Ansatz** (nach dem VDE Impuls zum Erdschluss-Reststrom).
4. **Station** – Erdungs- und Berührungsspannung je Frequenz (direkt und fehlerbedingt), Vergleich mit den
   Erdungsmessungen aus **groundmeas**, **Reduktionsfaktor** (je Harmonische und effektiv) und – mit PEN-Strömen –
   Strom ins **Ortsnetz** und Z_E,Ortsnetz mit Parallelschaltungsprüfung.
5. **Berichtstabellen** und **Abbildungen** – Export nach `2_Auswertung/Kampagne` und `3_Abbildungen/Kampagne`.
6. **groundmeas** – alle Messungen der Kampagne als Erdschlussmessungen eintragen (Trockenlauf, dann auf Wunsch).
''')),
        code(setup(lang)),
        md(t("## 1 · Configuration", "## 1 · Konfiguration")),
        code(conf + t('''

# ---------------------------------------------------------------- equivalent-source method
ORDERS        = "auto"             # "auto" = odd orders with ≥ 0.5 A in ≥ 2 measurements, otherwise e.g. [3, 5, 7, 11, 13]
NORMALIZATION = "complex"          # "complex" (magnitude and phase) | "magnitude" | None
LEVEL         = "mean"             # source level: "pre_fault" | "post_fault" | "mean"
METHOD        = "equation_error"   # "equation_error" (linear least squares) | "output_error" (nonlinear)
SOURCE        = "measured"         # source of the result I_RES(Z_E): "measured" (pre-fault voltage) | "fitted" (from the currents)
SOURCE_IMPEDANCE = "median"        # Z_q of the measured source: "median" over the tests | "smallest" (test without additional impedance, the others check it)
Z_E           = ''' + z_e + '''
Z_E_MAX       = 10.0               # end of the axis of the figure I_RES(Z_E)
IG_CHOICE     = "max"              # fundamental component: "max" (conservative) | "median" | a number in A

# ---------------------------------------------------------------- scaling to the 95 % quantile of a PQ measurement
# U95 scales every order of the positive or negative sequence (5, 7, 11, 13, 17 …) with its own 95 % value – also in
# the remainder outside the orders of the model; THD95_PERCENT scales flat with THD95/THD of the series the orders
# without their own value (alone: all of them). The zero sequence (3, 9, 15 …) and the even orders stay as measured.
U95 = None                         # per order in V, e.g. {5: U_5, 7: U_7}
U95_REFERENCE = "LL"               # "LL" = line-to-line (PQ device) | "seq" = sequence voltage (line-to-earth)
THD95_PERCENT = None               # flat: 95 % quantile of the THD in % (line-to-line), alone or together with U95
# With PQ_FILES section 4 takes U95 (line-to-earth, largest phase per 10-min interval) and THD95_PERCENT (largest loop)
# from the export(s) of a PQ instrument at the busbar – the values above are then replaced.
PQ_FILES      = ''' + pq_files + '''
PQ_TIMEZONE   = None               # time zone of the instrument clock, e.g. "Europe/Berlin" (None = time stamps as exported)
PQ_QUANTILE   = 0.95               # quantile of the 10-min values

# ---------------------------------------------------------------- limits, margins and factors – defined by you
# groundfault contains no limits or safety factors: take them from the operator's specification or the applicable
# standard. Not set (the values below), the parts that need them are skipped with a note.
LIMITS            = ()      # limits of the residual current in A, e.g. (I_1, I_2): lines in the figures I_RES(Z_E)
U_TP              = None    # permissible touch voltage U_Tp in V (resistive approach; reduction factor: None = from the result file)
F_FACTOR          = None    # factor F of the permissible earth potential rise F·U_Tp (as U_TP)
REFERENCE_CURRENT = None    # reference current in A for the reduction factor (None = largest limit of the result file)
UNCERTAINTY_I     = 0.0     # measurement-uncertainty margin m_I of currents for I_RES at Z_E: I·(1 + m_I) (0.0 = none)
LOO_LIMIT_PCT     = None    # leave-one-out check: permissible deviation in % of every test from the model of the others (None = without assessment)
LOO_LIMIT_A       = None    # … and in A, for the small currents of the higher orders (within one of the two = passed; None = not used)
PQ_SAFETY_FACTOR  = 1.0     # factor on the 95 % quantiles of the PQ measurement (1.0 = none)
PQ_FACTORS        = None    # factor on the quantile by the duration of the PQ measurement {minimum days: factor} (None = PQ_SAFETY_FACTOR)
R_TYPICAL         = None    # range (low, high) of the reduction factor at 50 Hz you expect, e.g. from your experience

# ---------------------------------------------------------------- groundmeas (comparison section 5, entries section 7)
GROUNDMEAS_DB = ''' + db + '''
GROUNDMEAS_EXPORT = False          # True: enter the measurements (one backup copy before); "replace": renew own entries
GROUNDMEAS_UNCERTAIN = "mark"      # uncertain fault-related values: "mark" (with a remark) | "omit"
GROUNDMEAS_UNITS = "suitable"      # "suitable": readable per quantity (mV, mA …; groundmeas ≥ 1.6.1) | "base": V and A

# ---------------------------------------------------------------- resistive approach (data of your network)
RESISTIVE = dict(U_thd95_V=None,   # harmonic voltage (95 %) in V (None = skip)
                 from_ll=True,     # True: the value is line-to-line → /√3
                 R_E_max=None, R1_km=None, R0_km=None,   # largest earthing resistance in Ω; Ω/km at the dominant frequency
                 r=1.0,            # reduction factor; r < 1: r·R_E acts in the fault circuit
                 I_res_max=None)   # permissible residual current in A (None = F_FACTOR·U_TP/(r·R_E_max))

EXPORT_FORMATS = ("pdf", "svg", "png")''', '''

# ---------------------------------------------------------------- Ersatzquellenverfahren
ORDERS        = "auto"             # "auto" = ungerade Ordnungen mit ≥ 0,5 A in ≥ 2 Messungen, sonst z. B. [3, 5, 7, 11, 13]
NORMALIZATION = "complex"          # "complex" (Betrag + Phase) | "magnitude" (nur Betrag) | None
LEVEL         = "mean"             # Quellenpegel: "pre_fault" (Vorfehler) | "post_fault" (Nachfehler) | "mean" (Mittel)
METHOD        = "equation_error"   # "equation_error" (Gleichungsfehler, linear) | "output_error" (Ausgangsfehler, nichtlinear)
SOURCE        = "measured"         # Quelle des Ergebnisses I_RES(Z_E): "measured" (Vorfehlerspannung) | "fitted" (aus den Strömen)
SOURCE_IMPEDANCE = "median"        # Z_q der gemessenen Quelle: "median" über die Versuche | "smallest" (Versuch ohne Zusatzimpedanz, die übrigen prüfen)
Z_E           = ''' + z_e + '''
Z_E_MAX       = 10.0               # Achsenende im Diagramm I_RES(Z_E)
IG_CHOICE     = "max"              # Grundschwingung: "max" (konservativ) | "median" | Zahl in A

# ---------------------------------------------------------------- Skalierung auf das 95-%-Quantil einer PQ-Messung
# U95 skaliert jede Ordnung des Mit- oder Gegensystems (5, 7, 11, 13, 17 …) mit ihrem eigenen 95-%-Wert – auch im Rest
# außerhalb der Ordnungen des Modells; THD95_PERCENT pauschal mit THD95/THD der Messreihe die Ordnungen ohne eigenen
# Wert (allein: alle). Nullsystem (3, 9, 15 …) und gerade Ordnungen bleiben wie gemessen.
U95 = None                         # je Ordnung in V, z. B. {5: U_5, 7: U_7}
U95_REFERENCE = "LL"               # "LL" = Leiter-Leiter (PQ-Gerät) | "seq" = Sequenzspannung (L-E)
THD95_PERCENT = None               # pauschal: THD-95-%-Quantil in % (L-L), allein oder zusammen mit U95
# Mit PQ_FILES übernimmt Abschnitt 4 U95 (Leiter-Erde, größter Leiter je 10-min-Intervall) und THD95_PERCENT (größte
# Schleife) aus dem Export bzw. den Exporten eines PQ-Messgeräts an der Sammelschiene – die Werte oben werden ersetzt.
PQ_FILES      = ''' + pq_files + '''
PQ_TIMEZONE   = None               # Zeitzone der Geräteuhr, z. B. "Europe/Berlin" (None = Zeitstempel wie exportiert)
PQ_QUANTILE   = 0.95               # Quantil der 10-min-Werte

# ---------------------------------------------------------------- Grenzwerte, Zuschläge und Faktoren – selbst festlegen
# groundfault enthält keine Grenzwerte oder Sicherheitsfaktoren: aus der Vorgabe des Netzbetreibers bzw. der geltenden
# Norm übernehmen. Nicht gesetzt (die Werte unten), werden die Teile, die sie brauchen, mit einem Hinweis übersprungen.
LIMITS            = ()      # Grenzwerte des Reststroms in A, z. B. (I_1, I_2): Linien in den Diagrammen I_RES(Z_E)
U_TP              = None    # zulässige Berührungsspannung U_Tp in V (resistiver Ansatz; Reduktionsfaktor: None = aus der Ergebnisdatei)
F_FACTOR          = None    # Faktor F der zulässigen Erdungsspannung F·U_Tp (wie U_TP)
REFERENCE_CURRENT = None    # Bezugsstrom in A für den Reduktionsfaktor (None = größter Grenzwert der Ergebnisdatei)
UNCERTAINTY_I     = 0.0     # Messunsicherheitszuschlag m_I der Ströme für I_RES an Z_E: I·(1 + m_I) (0.0 = keiner)
LOO_LIMIT_PCT     = None    # Leave-one-out-Prüfung: zulässige Abweichung in % jedes Versuchs vom Modell der übrigen (None = ohne Bewertung)
LOO_LIMIT_A       = None    # … und in A, für die kleinen Ströme der höheren Ordnungen (innerhalb einer der beiden = erfüllt; None = nicht genutzt)
PQ_SAFETY_FACTOR  = 1.0     # Faktor auf die 95-%-Quantile der PQ-Messung (1.0 = keiner)
PQ_FACTORS        = None    # Faktor auf das Quantil nach Dauer der PQ-Messung {Mindesttage: Faktor} (None = PQ_SAFETY_FACTOR)
R_TYPICAL         = None    # erwarteter Bereich (unten, oben) des Reduktionsfaktors bei 50 Hz, z. B. aus Erfahrung

# ---------------------------------------------------------------- groundmeas (Vergleich Abschnitt 5, Eintrag Abschnitt 7)
GROUNDMEAS_DB = ''' + db + '''
GROUNDMEAS_EXPORT = False          # True: Messungen eintragen (eine Sicherungskopie vorher); "replace": eigene erneuern
GROUNDMEAS_UNCERTAIN = "mark"      # unsichere fehlerbedingte Werte: "mark" (mit Vermerk) | "omit" (weglassen)
GROUNDMEAS_UNITS = "suitable"      # "suitable": je Größe gut lesbar (mV, mA …; groundmeas ≥ 1.6.1) | "base": V und A

# ---------------------------------------------------------------- Resistiver Ansatz (Daten des eigenen Netzes)
RESISTIVE = dict(U_thd95_V=None,   # Oberschwingungsspannung 95 % in V (None = überspringen)
                 from_ll=True,     # True: Wert ist Leiter-Leiter → /√3
                 R_E_max=None, R1_km=None, R0_km=None,   # größter Erdungswiderstand in Ω; Ω/km bei der dominanten Frequenz
                 r=1.0,            # Reduktionsfaktor; r < 1: im Fehlerkreis wirkt r·R_E
                 I_res_max=None)   # zulässiger Erdschlussreststrom in A (None = F_FACTOR·U_TP/(r·R_E_max))

EXPORT_FORMATS = ("pdf", "svg", "png")''')),
        md(t("## 2 · Load the results – overview and consistency", "## 2 · Ergebnisse laden – Übersicht und Konsistenz")),
        code('''CAMPAIGN_FOLDER = WORK_FOLDER / LAYOUT.campaigns / CAMPAIGN
for m in MEASUREMENTS:                 ''' + t("# known keys only (a misspelt or former key would be ignored)",
                                         "# nur bekannte Schlüssel (ein vertippter oder früherer Schlüssel bliebe unbeachtet)") + '''
    legacy.check_keys("MEASUREMENTS", m, ("name", "measurement", "Z", "location", "description", "timestamp"))


def result_file(measurement):
    """''' + t("Result file of a measurement (also with the suffix of the other layout).",
               "Ergebnisdatei einer Messung (auch mit der Endung der anderen Ordnerstruktur).") + '''"""
    p = Path(LAYOUT.result_path(CAMPAIGN_FOLDER, measurement))
    other = [p.parent / (measurement + lay.result_suffix) for lay in layout.LAYOUTS.values()]
    return next((x for x in [p, *other] if x.exists()), p)


if DEMO:                               ''' + t("# demo: create the campaign and evaluate the recordings with their known intervals",
                                                  "# Demo: Kampagne anlegen und die Aufzeichnungen mit ihren bekannten Bereichen auswerten") + '''
    if not CAMPAIGN_FOLDER.exists():
        demo.make_campaign(str(WORK_FOLDER), CAMPAIGN, layout=LAYOUT.language)
    CORR = corrections.load(CAMPAIGN_FOLDER)      ''' + t("# corrections of the campaign, as in evaluate_measurement.ipynb",
                                                     "# Korrekturen der Kampagne wie in Messung_auswerten.ipynb") + '''
    for m in MEASUREMENTS:
        if not result_file(m["measurement"]).exists():
            cfg = next(CAMPAIGN_FOLDER.glob("%s/*/%s.cfg" % (LAYOUT.raw, m["measurement"])))
            with open(str(cfg).replace(".cfg", "_truth.json"), encoding="utf-8") as f:
                b = json.load(f)["intervals"]
            rec_ = gf.open_recording(str(cfg))
            CORR.apply(rec_)
            roles_ = gf.detect_roles(rec_.channel_names, rec_.units, CORR.role_overrides(rec_), CORR.main_channel(rec_),
                                     CORR.distances(rec_))
            r_ = gf.evaluate(rec_, gf.Intervals(*(tuple(b[k]) for k in ("steady_state", "pre_fault", "post_fault"))),
                             gf.Settings(uncertainty_I=UNCERTAINTY_I, ires_limits=LIMITS, u_tp=U_TP, f_factor=F_FACTOR),
                             roles=roles_, z_fault_ohm=m["Z"])
            r_.save_json(LAYOUT.result_path(CAMPAIGN_FOLDER, m["measurement"]))
RESULTS = {}
for m in MEASUREMENTS:
    p = result_file(m["measurement"])
    if p.exists():
        RESULTS[m["name"]] = gf.load_result(str(p), m["name"])
    else:
        print("''' + t("⚠ missing:", "⚠ fehlt:") + '''", p.relative_to(WORK_FOLDER), "''' + t("→ evaluate it with evaluate_measurement.ipynb first",
                                                                                           "→ zuerst mit Messung_auswerten.ipynb auswerten") + '''")
show(campaign.overview(RESULTS))
display(Markdown("''' + t("**Consistency between the measurements**", "**Konsistenz zwischen den Messungen**") + '''"))
show(campaign.consistency({m["name"]: RESULTS[m["name"]] for m in MEASUREMENTS if m["Z"] is not None and m["name"] in RESULTS}))
for n, e in RESULTS.items():
    for h in e.hints:
        print("⚠ %s: %s" % (n, h))'''),
        md(t('''
## 3 · Equivalent-source method (active two-terminal equivalent per harmonic)

**Normalization:** the harmonic level of the network fluctuates between the measurements (minutes apart). Each current
is referred to the level of the natural sequence measured at the same time *at the faulted phase* (5th/11th negative
sequence, 7th/13th positive sequence; for L2/L3 rotated by ±120°). Orders of the zero sequence (3rd, 9th) are **not**
normalized – their current only arises in the earth fault.
**Two estimators:** *equation error* (linear least squares) and *output error* (minimises the current deviation). If
they disagree strongly, U_q and Z_q are individually uncertain (the hint says whether the forecast within the measured
range is stable nevertheless).
**Thevenin check:** physically U_q is the pre-fault voltage of the faulted phase → column `Uq_ref_faulted_phase` ≈ 1 and
`Uq_angle_ref_faulted_phase_deg` ≈ 0°. A deviation of more than 10 % or 10° shows that the fitted U_q has absorbed
changes of the network between the tests: U_q is the slope of 1/I over Z, poorly determined when the additional
impedances are small compared with |Z_q|. Within the tested range the model current stays reliable, beyond it not.
**Sensitivity** `dZq_rel_per_1pct`: relative change of Z_q for an error of 1 % (or 0.5°) of one current – above 0.1
ill-conditioned.
**Measured source:** U_q as measured – the pre-fault voltage of the faulted phase – and Z_q = U_q/I_k − Z_k from the
tests (`SOURCE_IMPEDANCE`: the median over the tests or the test without additional impedance); one test suffices, every
further test is checked against the model of the others (leave-one-out, `LOO_LIMIT_PCT`). The table of the single
tests shows how much the network changed between them, the comparison where the two sources agree (tested range) and
where not. Orders of the zero sequence keep the fitted source – their source
arises in the fault. `SOURCE` selects the result of the checks and of section 4; the other source is drawn dashed.
''', '''
## 3 · Ersatzquellenverfahren (aktiver Zweipol je Harmonische)

**Normierung:** Der Oberschwingungspegel des Netzes schwankt zwischen den Messungen (Minuten). Jeder Strom wird auf den
gleichzeitig gemessenen Pegel der natürlichen Sequenz *am Fehlerleiter* bezogen (5./11. Gegensystem, 7./13. Mitsystem;
bei L2/L3 um ±120° gedreht). Ordnungen des Nullsystems (3., 9.) werden **nicht** normiert – ihr Strom entsteht erst im
Erdschluss.
**Zwei Schätzer:** *Gleichungsfehler* (lineare Ausgleichsrechnung) und *Ausgangsfehler* (minimiert die
Stromabweichung). Liegen beide weit auseinander, sind U_q und Z_q einzeln unsicher (der Hinweis nennt, ob die
Vorhersage im Messbereich trotzdem stabil ist).
**Thevenin-Kontrolle:** Physikalisch ist U_q die Vorfehlerspannung des Fehlerleiters → Spalte
`Uq_bez_Fehlerleiter` ≈ 1 und `Uq_Winkel_bez_Fehlerleiter_deg` ≈ 0°. Mehr als 10 % bzw. 10° Abweichung zeigen, dass
das geschätzte U_q Änderungen des Netzes zwischen den Versuchen aufgenommen hat: U_q ist die Steigung von 1/I über Z,
schlecht bestimmt, wenn die Zusatzimpedanzen klein gegen |Z_q| sind. Im Bereich der Versuche bleibt der Modellstrom
belastbar, darüber hinaus nicht. **Empfindlichkeit**: relative Änderung von Z_q bei 1 % (bzw. 0,5°) Fehler eines
Stroms – über 0,1 schlecht konditioniert.
**Gemessene Quelle:** U_q wie gemessen – die Vorfehlerspannung des Fehlerleiters – und Z_q = U_q/I_k − Z_k aus den
Versuchen (`SOURCE_IMPEDANCE`: der Median über die Versuche oder der Versuch ohne Zusatzimpedanz); ein Versuch genügt,
jeder weitere wird mit dem Modell der übrigen geprüft (Leave-one-out, `LOO_LIMIT_PCT`). Die Tabelle der einzelnen
Versuche zeigt, wie stark sich das Netz zwischen ihnen geändert hat, der Vergleich, wo beide Quellen übereinstimmen
(Messbereich) und wo nicht. Ordnungen des Nullsystems behalten die
geschätzte Quelle – ihre Quelle entsteht im Fehler. `SOURCE` wählt das Ergebnis der Kontrollen und von Abschnitt 4;
die andere Quelle ist gestrichelt eingezeichnet.
''')),
        code('''SERIES = MEASURED = MAIN = OTHER = MC = None   ''' + t("# fitted source, measured source, result (SOURCE), comparison; MC: Monte Carlo (checks)",
                                                         "# geschätzte Quelle, gemessene Quelle, Ergebnis (SOURCE), Vergleich; MC: Monte Carlo (Kontrollen)") + '''
SOURCE_TEXT = {"measured": "''' + t("measured source", "gemessene Quelle") + '''", "fitted": "''' + t("fitted source", "geschätzte Quelle") + '''"}
entries = [dict(file=str(result_file(m["measurement"])), Z=m["Z"], name=m["name"])
           for m in MEASUREMENTS if m["Z"] is not None and m["name"] in RESULTS]
if entries:
    legacy.check_option("SOURCE", SOURCE, ("measured", "fitted"))
    legacy.check_option("SOURCE_IMPEDANCE", SOURCE_IMPEDANCE, ("median", "smallest"))
    TESTS = equivalent_source.load_series(entries)
    if len({complex(e["Z"]) for e in entries}) >= 2:
        SERIES = equivalent_source.fit_equivalent_source(TESTS, orders=ORDERS, normalization=NORMALIZATION,
                                                         reference=LEVEL, method=METHOD)
        MEASURED = equivalent_source.measured_source(SERIES, impedance=SOURCE_IMPEDANCE)
    else:                              ''' + t("# one additional impedance: no fitted source, the measured source suffices",
                                         "# eine Zusatzimpedanz: keine geschätzte Quelle, die gemessene genügt") + '''
        MEASURED = equivalent_source.measured_source(TESTS, impedance=SOURCE_IMPEDANCE, orders=ORDERS, reference=LEVEL)
        print("''' + t("ℹ One additional impedance only: the fitted source needs two – result with the measured source.",
                       "ℹ Nur eine Zusatzimpedanz: die geschätzte Quelle braucht zwei – Ergebnis mit der gemessenen Quelle.") + '''")
    MAIN, OTHER = (MEASURED, SERIES) if SOURCE == "measured" or SERIES is None else (SERIES, MEASURED)
    show(MAIN.measurements_table())
    display(Markdown("''' + t("**Source level before/after the fault** (drift within one measurement = quality of the normalization)",
                              "**Quellenpegel vor/nach dem Fehler** (Drift innerhalb einer Messung = Güte der Normierung)") + '''"))
    show(MAIN.level_table(LEVEL))
    if SERIES is not None:
        display(Markdown("''' + t("**Fitted source: two-terminal equivalents per order** (Thevenin check ≈ 1∠0°)",
                                  "**Geschätzte Quelle: Zweipol-Parameter je Ordnung** (Thevenin-Kontrolle ≈ 1∠0°)") + '''"))
        show(SERIES.source_table())
        for h in SERIES.hints:
            print("ℹ", h)
        for m, F in SERIES.fits.items():
            for h in F.hints:
                print("ℹ ''' + t("harmonic %d:", "%d. Harmonische:") + ''' %s" % (m, h))
    display(Markdown("''' + t("**Measured source** – U_q = pre-fault voltage of the faulted phase; Z_q of every single test (the spread is the change of the network between the tests) and of the series",
                              "**Gemessene Quelle** – U_q = Vorfehlerspannung des Fehlerleiters; Z_q jedes einzelnen Versuchs (die Streuung ist die Änderung des Netzes zwischen den Versuchen) und der Reihe") + '''"))
    show(MEASURED.single_test_table())
    show(MEASURED.source_table()[["order", "f_Hz", "sequence", "method", "Uq_V", "Rq_Ohm", "Xq_Ohm", "Zq_Ohm",
                                  "residual_pct", "Rq_fixed"]])
    for h in (MEASURED.hints[-1:] if SERIES is not None else MEASURED.hints):    ''' + t("# with a fitted series: only the new hint",
                                                                                       "# mit geschätzter Reihe: nur der neue Hinweis") + '''
        print("ℹ", h)
    for m, F in MEASURED.fits.items():
        for h in (F.hints if F.method == "measured" else F.hints[-1:]):     ''' + t("# kept fitted orders: only the new hint",
                                                                                    "# beibehaltene geschätzte Ordnungen: nur der neue Hinweis") + '''
            print("ℹ ''' + t("harmonic %d:", "%d. Harmonische:") + ''' %s" % (m, h))
    if SERIES is not None:
        display(Markdown("''' + t("**Measured against fitted source** – current per order and I_RES within and beyond the tested range (`fitted_to_measured`; `interpolation` = within the tested additional impedances)",
                                  "**Gemessene gegen geschätzte Quelle** – Strom je Ordnung und I_RES im Messbereich und darüber hinaus (`geschaetzt_zu_gemessen`; `Interpolation` = im Bereich der Zusatzimpedanzen der Versuche)") + '''"))
        zmin, zmax = SERIES.Z_range
        show(equivalent_source.compare_sources(MEASURED, SERIES, [0.0, zmax, 2 * zmax]
                                               + ([Z_E] if Z_E is not None and Z_E not in (0.0, zmax, 2 * zmax) else []),
                                               IG=IG_CHOICE))
else:
    print("''' + t("The equivalent-source method needs at least one substation measurement with its additional impedance Z (the fitted source two different ones).",
                   "Für das Ersatzquellenverfahren ist mindestens eine UW-Messung mit ihrer Zusatzimpedanz Z nötig (für die geschätzte Quelle zwei verschiedene).") + '''")'''),
        md(t("### Checks: pairwise solution, forecast per measurement, jackknife, Monte Carlo",
             "### Kontrollen: paarweise Lösung, Prognose je Messung, Jackknife, Monte Carlo")),
        code('''if MAIN is not None:
    if SERIES is not None:
        display(Markdown("''' + t("**Fitted source: solution of every pair of tests**", "**Geschätzte Quelle: Lösung aus je zwei Versuchen**") + '''"))
        show(SERIES.pairwise_table())
    display(Markdown(i18n.format_text("''' + t("**Result ({}): model against measurement per test, jackknife at Z_E**",
                                               "**Ergebnis ({}): Modell gegen Messung je Versuch, Jackknife an Z_E**") + '''",
                                      SOURCE_TEXT[MAIN.settings["source"]])))
    show(MAIN.forecast_table())
    display(Markdown("''' + t("**Leave-one-out: every test from the model of the other tests** (a large deviation: the network changed between the tests)",
                              "**Leave-one-out: jeder Versuch aus dem Modell der übrigen** (große Abweichung: das Netz hat sich zwischen den Versuchen geändert)") + '''"))
    LOO = MAIN.loo_table(LOO_LIMIT_PCT, LOO_LIMIT_A)
    show(LOO)
    BAD = LOO["within_limit"].eq(False) if "within_limit" in LOO else LOO["order"].isna()   ''' + t("# None: not determinable", "# None: nicht bestimmbar") + '''
    if BAD.any():
        print(i18n.format_text("''' + t("⚠ Leave-one-out: {} of {} values outside the permissible deviation ({}) – the network changed between the tests",
                                         "⚠ Leave-one-out: {} von {} Werten außerhalb der zulässigen Abweichung ({}) – das Netz hat sich zwischen den Versuchen geändert") + '''",
                               int(BAD.sum()), int(LOO["within_limit"].notna().sum()),
                               " / ".join(i18n.format_text(f, v) for f, v in (("±{:g} %", LOO_LIMIT_PCT), ("±{:g} A", LOO_LIMIT_A)) if v is not None)))
    if Z_E is not None:
        show(MAIN.jackknife_table(Z_E))
    display(Markdown("''' + t("**Residual current at the measured impedances** – model (with the level and I_G of each measurement, rest = orders not fitted) against the measured true RMS value",
                              "**Reststrom an den Messimpedanzen** – Modell (mit Pegel und I_G der jeweiligen Messung, Rest = nicht gefittete Ordnungen) gegen den gemessenen Echt-Effektivwert") + '''"))
    show(MAIN.check_table())
    if Z_E is None:
        print("''' + t("ℹ Jackknife and Monte Carlo at Z_E skipped – Z_E is not set (section 1).",
                       "ℹ Jackknife und Monte Carlo an Z_E übersprungen – Z_E ist nicht gesetzt (Abschnitt 1).") + '''")
    else:
        MC = equivalent_source.monte_carlo(MAIN, Z_E, n=2000)
        print(i18n.format_text("''' + t("Monte Carlo (1 %/0.5° current, 2 % Z, model residual): I_RES(Z_E = {:g} Ω) P5 … P95 = {:.1f} … {:.1f} A (median {:.1f} A)",
                                         "Monte Carlo (1 %/0,5° Strom, 2 % Z, Modellresiduum): I_RES(Z_E = {:g} Ω) P5 … P95 = {:.1f} … {:.1f} A (Median {:.1f} A)") + '''",
                               Z_E, MC["IRES"][5], MC["IRES"][95], MC["IRES"][50]))
        zmin, zmax = MAIN.Z_range
        print(i18n.format_text("''' + t("Z_E lies {} the measured range {:.1f} … {:.1f} Ω", "Z_E liegt {} des Messbereichs {:.1f} … {:.1f} Ω") + '''",
            "''' + t("within", "innerhalb") + '''" if zmin <= abs(Z_E) <= zmax else "''' + t("OUTSIDE (extrapolation)", "AUSSERHALB (Extrapolation)") + '''", zmin, zmax))
    interactive.source_fit(MAIN, Z_E, comparison=OTHER).show()'''),
        md(t("## 4 · Residual current at the earthing impedance and resistive approach",
             "## 4 · Erdschlussreststrom an der Erdungsimpedanz und resistiver Ansatz")),
        keyed("pq-text", md(t('''
### Power-quality measurement of the busbar (PQ)

With `PQ_FILES` the export(s) of a PQ instrument at the busbar replace `U95`, `U95_REFERENCE`, `THD95_PERCENT` and
`PQ_SAFETY_FACTOR` of section 1: 10-min values (from shorter intervals as the square root of the mean of the
squares), per interval the **largest phase** (harmonic voltage line-to-earth per order) or **loop** (THD
line-to-line), of these values the quantile `PQ_QUANTILE`. The factor on the quantile follows from the longest stretch
of **gapless** values and `PQ_FACTORS`; shorter than every duration of `PQ_FACTORS` the measurement is not valid and
nothing is scaled with it. The PQ measurement and the tests must refer to the same network and switching state.
Without a value in `RESISTIVE["U_thd95_V"]` the resistive approach gets the quantile of the harmonic voltage
(line-to-line) times the factor. The table of the tests shows where their pre-fault voltages lie in the distribution
of the PQ measurement: a low percentile is normal for a test at a time of low harmonic voltage (night, weekend) –
compare the time window of the same weekday; a test level above the largest value of the PQ measurement points to a
different network state (switching state, capacitances, transformer). Figures: 10-min values over the period, duration
curve with the levels of the tests and the weekly profile.
''', '''
### Netzqualitätsmessung der Sammelschiene (PQ)

Mit `PQ_FILES` ersetzt der Export bzw. ersetzen die Exporte eines PQ-Messgeräts an der Sammelschiene `U95`,
`U95_REFERENCE`, `THD95_PERCENT` und `PQ_SAFETY_FACTOR` aus Abschnitt 1: 10-min-Werte (aus kürzeren Intervallen als
quadratischer Mittelwert), je Intervall der **größte Leiter** (Oberschwingungsspannung Leiter-Erde je Ordnung) bzw.
die **größte Schleife** (THD Leiter-Leiter), davon das Quantil `PQ_QUANTILE`. Der Faktor auf das Quantil folgt aus der
längsten Strecke **lückenloser** Werte und `PQ_FACTORS`; kürzer als jede Dauer von `PQ_FACTORS` ist die Messung nicht
gültig, und mit ihr wird nichts skaliert. PQ-Messung und Versuche müssen sich auf dasselbe Netz und denselben
Schaltzustand beziehen. Ohne Wert in `RESISTIVE["U_thd95_V"]` erhält der resistive Ansatz das Quantil der
Oberschwingungsspannung (Leiter-Leiter) mal Faktor. Die Tabelle der Versuche zeigt, wo deren Vorfehlerspannungen in
der Verteilung der PQ-Messung liegen: Ein niedriges Perzentil ist normal für einen Versuch zu einer Zeit kleiner
Oberschwingungsspannung (Nacht, Wochenende) – dazu das Zeitfenster desselben Wochentags vergleichen; ein Pegel über
dem größten Wert der PQ-Messung deutet auf einen anderen Netzzustand (Schaltzustand, Kapazitäten, Trafo). Abbildungen:
10-min-Werte über den Zeitraum, Dauerlinie mit den Pegeln der Versuche und Wochengang.
'''))),
        keyed("pq", code('''PQ = PQ_COMPARISON = PQ_LEVELS = None
if PQ_FILES:
    files = [CAMPAIGN_FOLDER / p for p in ([PQ_FILES] if isinstance(PQ_FILES, (str, Path)) else PQ_FILES)]
    PQ = pq.assess(pq.read(files, timezone=PQ_TIMEZONE), quantile=PQ_QUANTILE,
                   **(dict(factors=PQ_FACTORS) if PQ_FACTORS else dict(factor=PQ_SAFETY_FACTOR)))
    print(PQ.summary())
    for h in PQ.hints:
        print("ℹ", h)
    show(PQ.table().query("order >= 2"))
    show(PQ.summary_table())
    if PQ.valid:                       ''' + t("# the values of the measurement replace those of section 1",
                                         "# die Werte der Messung ersetzen die aus Abschnitt 1") + '''
        U95, U95_REFERENCE = PQ.u95(), ("seq" if PQ.reference == "LE" else "LL")
        THD95_PERCENT, PQ_SAFETY_FACTOR = (PQ.thd95() if np.isfinite(PQ.thd95()) else None), PQ.factor
        if RESISTIVE.get("U_thd95_V") is None and np.isfinite(PQ.uh95_ll):
            RESISTIVE = dict(RESISTIVE, U_thd95_V=PQ.uh95_ll * PQ.factor, from_ll=True)
            print(i18n.format_text("''' + t("Resistive approach: U_thd95_V = {:.1f} V (quantile of the harmonic voltage line-to-line × {:g})",
                                             "Resistiver Ansatz: U_thd95_V = {:.1f} V (Quantil der Oberschwingungsspannung Leiter-Leiter × {:g})") + '''",
                                   RESISTIVE["U_thd95_V"], PQ.factor))
    else:
        print("''' + t("⚠ The PQ measurement is not valid for the assessment (gapless values shorter than every duration of PQ_FACTORS) – nothing is scaled with it; U95/THD95_PERCENT of section 1 stay.",
                       "⚠ Die PQ-Messung ist für die Bewertung nicht gültig (lückenlose Werte kürzer als jede Dauer von PQ_FACTORS) – mit ihr wird nichts skaliert; U95/THD95_PERCENT aus Abschnitt 1 bleiben.") + '''")
    PQ_LEVELS, times = {}, {}
    for m in MEASUREMENTS:
        if m["Z"] is not None and m["name"] in RESULTS:
            PQ_LEVELS[m["name"]], times[m["name"]] = pq.pre_fault_levels(RESULTS[m["name"]], kind=PQ.reference)
    orders = sorted(o for o in (MAIN.fits if MAIN is not None else PQ.u95()) if gf.formulas.harmonic_category(o) == "pos_neg"
                    and o in PQ.data.orders)
    PQ_COMPARISON = PQ.comparability(PQ_LEVELS, times, orders=orders or None)
    for h in PQ_COMPARISON.attrs.get("hints", []):
        print("ℹ", h)
    display(Markdown("''' + t("**Fault tests in the distribution of the PQ measurement** – share of the 10-min values below the pre-fault voltage of the test (largest phase) over the whole measurement and in its time window; `factor_to_test` = quantile/level of the test",
                              "**Erdschlussversuche in der Verteilung der PQ-Messung** – Anteil der 10-min-Werte unter der Vorfehlerspannung des Versuchs (größter Leiter) über die ganze Messung und im Zeitfenster des Versuchs; `Faktor_zu_Versuch` = Quantil/Pegel des Versuchs") + '''"))
    show(PQ_COMPARISON)
    report.pq_series(PQ)
    report.pq_duration(PQ, levels={n: lv[PQ.dominant_order] for n, lv in PQ_LEVELS.items() if PQ.dominant_order in lv})
    report.pq_profile(PQ)
else:
    print("''' + t("ℹ No PQ measurement (PQ_FILES) – U95/THD95_PERCENT of section 1 are used if set.",
                   "ℹ Keine PQ-Messung (PQ_FILES) – U95/THD95_PERCENT aus Abschnitt 1, falls gesetzt.") + '''")''')),
        code('''SCALING = None
if MAIN is not None:
    if U95 or THD95_PERCENT:           ''' + t("# U95 per order; THD95_PERCENT for the orders without their own value (alone: all of them)",
                                         "# U95 je Ordnung; THD95_PERCENT für die Ordnungen ohne eigenen Wert (allein: alle)") + '''
        SCALING = dict(safety_factor=PQ_SAFETY_FACTOR)
    if U95:
        SCALING.update(u95=U95, u95_reference=U95_REFERENCE)
    if THD95_PERCENT:
        thd_measured = float(pd.concat([e.tables["voltage_metrics"] for n, e in RESULTS.items()
                                        if n in [x["name"] for x in entries]])
                             .query("interval != 'fault'")[["UTHD12_pct", "UTHD23_pct", "UTHD31_pct"]].max(axis=1).mean())
        SCALING.update(thd95_percent=THD95_PERCENT, thd_measured_percent=thd_measured)
        print(i18n.format_text("''' + t("THD of the series (mean before/after, largest loop): {:.2f} %", "THD der Messreihe (Mittel vor/nach, max. Schleife): {:.2f} %") + '''", thd_measured))
    if Z_E is None:
        print("''' + t("ℹ Residual current at Z_E skipped – Z_E is not set (section 1); the figure shows I_RES over Z_E.",
                       "ℹ Reststrom an Z_E übersprungen – Z_E ist nicht gesetzt (Abschnitt 1); das Diagramm zeigt I_RES über Z_E.") + '''")
    else:
        r = equivalent_source.ires_at_impedance(MAIN, Z_E, IG=IG_CHOICE, uncertainty_I=UNCERTAINTY_I, **(SCALING or {}))
        margin = UNCERTAINTY_I > 0             ''' + t("# the value with the margin only if you set one", "# den Wert mit Zuschlag nur, wenn einer gesetzt ist") + '''
        print(i18n.format_text("{}: I_G = {:.2f} A | I_H(Z_E) = {:.2f} A (''' + t("rest", "davon Rest") + ''' {:.2f} A) | I_RES(Z_E = {:g} Ω) = {:.2f} A",
                               SOURCE_TEXT[MAIN.settings["source"]], r["IG"], r["IH"], r["IH_rest"], Z_E, r["IRES"])
              + (i18n.format_text(" | ''' + t("with the measurement-uncertainty margin", "mit Messunsicherheitszuschlag") + ''': {:.2f} A", r["IRES_assessed"]) if margin else ""))
        if SCALING:
            print(i18n.format_text("''' + t("scaled", "skaliert") + ''': I_H = {:.2f} A → I_RES = {:.2f} A", r["IH_scaled"], r["IRES_scaled"])
                  + (i18n.format_text(" (''' + t("with the margin", "mit Zuschlag") + ''': {:.2f} A)", r["IRES_scaled_assessed"]) if margin else "")
                  + i18n.format_text(" | ''' + t("not scaled: zero sequence {:.2f} A, even orders {:.2f} A, without an order {:.2f} A",
                                                  "nicht skaliert: Nullsystem {:.2f} A, gerade Ordnungen {:.2f} A, ohne Ordnung {:.2f} A") + '''",
                                     r["IH_zero"], r["IH_even"], r["IH_other"]))
        display(Markdown(i18n.format_text("''' + t("**Result per order at Z_E = {:g} Ω** – the orders of the model at Z_E, the remainder of the test {} (the largest one); rule: `own voltage` (positive/negative sequence, quantile/level of the tests × factor), `THD` (without their own value), `as measured` (zero sequence, even orders)",
                                                   "**Ergebnis je Ordnung an Z_E = {:g} Ω** – die Ordnungen des Modells an Z_E, der Rest des Versuchs {} (der größte); Regel: `eigene Spannung` (Mit-/Gegensystem, Quantil/Pegel der Versuche × Faktor), `THD` (ohne eigenen Wert), `wie gemessen` (Nullsystem, gerade Ordnungen)") + '''",
                                          Z_E, r["rest_test"] or "–")))
        show(r["table"])
        for h in r["hints"]:
            print("ℹ", h)
        if OTHER is not None:
            o = equivalent_source.ires_at_impedance(OTHER, Z_E, IG=IG_CHOICE, **(SCALING or {}))
            print(i18n.format_text("''' + t("comparison", "Vergleich") + ''' {}: I_H(Z_E) = {:.2f} A | I_RES(Z_E) = {:.2f} A",
                                   SOURCE_TEXT[OTHER.settings["source"]], o["IH"], o["IRES"])
                  + (i18n.format_text(" | ''' + t("scaled", "skaliert") + ''': I_RES = {:.2f} A", o["IRES_scaled"]) if SCALING else ""))
    if not LIMITS:
        print("''' + t("ℹ No limit lines in the figures I_RES(Z_E) – LIMITS is not set (section 1).",
                       "ℹ Keine Grenzwertlinien in den Diagrammen I_RES(Z_E) – LIMITS ist nicht gesetzt (Abschnitt 1).") + '''")
    interactive.ires_ze(MAIN, Z_E_MAX, LIMITS, SCALING, comparison=OTHER).show()
legacy.check_keys("RESISTIVE", RESISTIVE, ("U_thd95_V", "from_ll", "R_E_max", "R1_km", "R0_km", "r", "I_res_max"))
NOT_SET = [k for k in ("U_thd95_V", "R_E_max", "R1_km", "R0_km") if RESISTIVE.get(k) is None]
if RESISTIVE.get("I_res_max") is None:                ''' + t("# otherwise I_RES,max = F·U_Tp/(r·R_E,max)", "# sonst I_RES,max = F·U_Tp/(r·R_E,max)") + '''
    NOT_SET += [n for n, v in (("U_TP", U_TP), ("F_FACTOR", F_FACTOR)) if v is None]
if NOT_SET:
    print("''' + t("ℹ Resistive approach skipped – not set (section 1): %s", "ℹ Resistiver Ansatz übersprungen – nicht gesetzt (Abschnitt 1): %s") + '''"
          % ", ".join(n if n in ("U_TP", "F_FACTOR") else "RESISTIVE[%r]" % n for n in NOT_SET))
else:
    IG_ALL = [e.values["IG"] for e in RESULTS.values() if np.isfinite(e.values.get("IG", np.nan))] or [0.0]
    if isinstance(IG_CHOICE, str):
        legacy.check_option("IG_CHOICE", IG_CHOICE, ("max", "median"))
    IG = (max(IG_ALL) if IG_CHOICE == "max" else float(np.median(IG_ALL)) if IG_CHOICE == "median" else float(IG_CHOICE))
    display(pd.Series(campaign.resistive_approach(RESISTIVE["U_thd95_V"], IG, RESISTIVE["R_E_max"], RESISTIVE["R1_km"],
                                                  RESISTIVE["R0_km"], I_res_max=RESISTIVE.get("I_res_max"),
                                                  U_Tp=U_TP, F=F_FACTOR, from_ll=RESISTIVE.get("from_ll", False),
                                                  r=RESISTIVE.get("r", 1.0)),
                      name="''' + t("resistive approach", "resistiver Ansatz") + '''"))'''),
        keyed("pq-comparison-text", md(t('''
### PQ scaling at Z_E: per order, as a time series and with the THD

**Result** (`SCALING`): every order of the positive or negative sequence (5, 7, 11, 13, 17 …) with its own factor
quantile/level of the tests times the factor – also in the remainder outside the orders of the model; an order without
its own value (no quantile, level below 1 V) with the THD factor. The zero sequence (3, 9, 15 …) arises in the earth
fault and stays as measured; the even orders stay as measured and are listed separately (atypical – a hint names them
from 5 % of the harmonic content). **Time series**: the same for every 10-min value, of these I_RES the quantile
`PQ_QUANTILE` (times the factor) – smaller when the orders do not reach their high values at the same time. **THD**:
one flat factor THD quantile/THD of the tests for every order of the positive or negative sequence – the rule without
values per order.
''', '''
### PQ-Skalierung an Z_E: je Ordnung, als Zeitreihe und mit dem THD

**Ergebnis** (`SCALING`): jede Ordnung des Mit- oder Gegensystems (5, 7, 11, 13, 17 …) mit ihrem eigenen Faktor
Quantil/Pegel der Versuche mal Faktor – auch im Rest außerhalb der Ordnungen des Modells; eine Ordnung ohne eigenen
Wert (kein Quantil, Pegel unter 1 V) mit dem THD-Faktor. Das Nullsystem (3, 9, 15 …) entsteht im Erdschluss und bleibt
wie gemessen; die geraden Ordnungen bleiben wie gemessen und werden gesondert aufgeführt (untypisch – ein Hinweis nennt
sie ab 5 % des Oberschwingungsanteils). **Zeitreihe**: dasselbe für jeden 10-min-Wert, davon von I_RES das Quantil
`PQ_QUANTILE` (mal Faktor) – kleiner, wenn die Ordnungen ihre hohen Werte nicht gleichzeitig erreichen. **THD**: ein
pauschaler Faktor THD-Quantil/THD der Versuche für jede Ordnung des Mit- oder Gegensystems – die Regel ohne Werte je
Ordnung.
'''))),
        keyed("pq-comparison", code('''PQ_SCALING = None
if PQ is not None and PQ.valid and MAIN is not None and Z_E is not None and SCALING:
    kw = dict(IG=IG_CHOICE, uncertainty_I=UNCERTAINTY_I)
    rows = []
    r0 = equivalent_source.ires_at_impedance(MAIN, Z_E, **kw)
    rows.append(("''' + t("without scaling", "ohne Skalierung") + '''", r0["IH"], r0["IRES"], r0["IRES_assessed"]))
    r1 = equivalent_source.ires_at_impedance(MAIN, Z_E, **kw, **SCALING)
    rows.append(("''' + t("quantile per order (result)", "Quantil je Ordnung (Ergebnis)") + '''", r1["IH_scaled"], r1["IRES_scaled"],
                 r1["IRES_scaled_assessed"]))
    V = pd.DataFrame({m: PQ.largest(m) for m in PQ.data.orders if m >= 2})   ''' + t("# every order of the PQ measurement (model and remainder)",
                                                                              "# jede Ordnung der PQ-Messung (Modell und Rest)") + '''
    loops = [c for c in pq.PHASES_LL if c in PQ.data.thd.columns]
    ts = equivalent_source.ires_over_time(MAIN, Z_E, V, u95_reference=SCALING.get("u95_reference", "seq"),
                                          thd_percent=PQ.data.thd[loops].max(axis=1) if loops and "thd_measured_percent" in SCALING else None,
                                          thd_measured_percent=SCALING.get("thd_measured_percent"), safety_factor=PQ.factor, **kw)
    rows.append((i18n.format_text("''' + t("quantile {:g} of the time series I_RES(t)", "Quantil {:g} der Zeitreihe I_RES(t)") + '''", PQ_QUANTILE),
                 ts["IH"].quantile(PQ_QUANTILE), ts["IRES"].quantile(PQ_QUANTILE), ts["IRES_assessed"].quantile(PQ_QUANTILE)))
    if "thd_measured_percent" in SCALING:
        r2 = equivalent_source.ires_at_impedance(MAIN, Z_E, **kw, thd95_percent=PQ.thd95(),
                                                 thd_measured_percent=SCALING["thd_measured_percent"], safety_factor=PQ.factor)
        rows.append(("''' + t("THD factor (without values per order)", "THD-Faktor (ohne Werte je Ordnung)") + '''", r2["IH_scaled"], r2["IRES_scaled"],
                     r2["IRES_scaled_assessed"]))
    PQ_SCALING = pd.DataFrame(rows, columns=["method", "IH_A", "IRES_A", "IRES_assessed_A"])
    display(Markdown(i18n.format_text("''' + t("**Residual current at Z_E = {:g} Ω with the PQ measurement** (quantile {:g}, factor {:g}; assessed = with UNCERTAINTY_I)",
                                               "**Erdschlussreststrom an Z_E = {:g} Ω mit der PQ-Messung** (Quantil {:g}, Faktor {:g}; Bewertung = mit UNCERTAINTY_I)") + '''",
                                      Z_E, PQ_QUANTILE, PQ.factor)))
    show(PQ_SCALING)
    for h in ts.attrs.get("hints", []):
        if h not in r1["hints"]:
            print("ℹ", h)
    for limit in LIMITS:
        over = [r[0] for r in rows if r[3] > limit]
        print(i18n.format_text("I_RES ''' + t("above", "über") + ''' {:g} A: ", limit) + (", ".join(over) or "–"))
elif PQ is not None and not PQ.valid:
    print("''' + t("ℹ No PQ scaling at Z_E – the PQ measurement is not valid for the assessment (section 4, PQ).",
                   "ℹ Keine PQ-Skalierung an Z_E – die PQ-Messung ist für die Bewertung nicht gültig (Abschnitt 4, PQ).") + '''")
elif PQ is not None:
    print("''' + t("ℹ No comparison at Z_E – Z_E or the equivalent sources are missing (sections 1 and 3).",
                   "ℹ Kein Vergleich an Z_E – Z_E oder die Ersatzquellen fehlen (Abschnitte 1 und 3).") + '''")''')),
        md(t('''
## 5 · Stations: earth potential rise and touch voltage per frequency, earthing measurement (groundmeas)

For every station measurement of the campaign (result file with the table `station_frequency`): voltage per ampere of
fault current over the frequency – **direct** as measured and **fault-related** (without the background before the
fault) – and, if the location is in groundmeas, the comparison with the earthing measurement (injection) with the
ratio (for the earth potential rise at a remote probe = effective reduction factor). groundmeas is only read.
**Reduction factor** per harmonic and as RMS value (earth potential rise per ampere, fault test ÷ earthing measurement,
magnitudes; decisive is the probe maximum `max(UE)` against the farthest probe of the earthing measurement) with
classification (against your range `R_TYPICAL` at 50 Hz, falling with f) and relevance of the deviation for the
assessment (voltage at the reference current against F·U_Tp – `REFERENCE_CURRENT`, `U_TP` and `F_FACTOR` of section 1,
otherwise the values stored in the result file); with PEN currents also the current into the **LV network** and
Z_E,LV = ΔU_E/I_LV with the parallel check (against the fault test max(U_E)/I_F and the earth current) and the
comparison with the earthing measurement.
''', '''
## 5 · Station: Erdungs-/Berührungsspannung je Frequenz und Erdungsmessung (groundmeas)

Für jede Stationsmessung der Kampagne (Ergebnisdatei mit Tabelle `station_frequency`): Spannung je Ampere
Fehlerstrom über der Frequenz – **direkt** gemessen und **fehlerbedingt** (ohne die Grundlast vor dem Fehler) – und,
falls der Ort in groundmeas erfasst ist, der Vergleich mit der Erdungsmessung (Einspeisung) samt Verhältnis
(für die Erdungsspannung an einer fernen Sonde = wirksamer Reduktionsfaktor). groundmeas wird nur gelesen.
**Reduktionsfaktor** je Harmonische und effektiv (Erdungsspannung je Ampere, Erdschluss ÷ Erdungsmessung, Beträge;
maßgeblich das Sondenmaximum `max(UE)` gegen die fernste Sonde der Erdungsmessung) mit Einordnung (gegen den eigenen
Bereich `R_TYPICAL` bei 50 Hz, fallend mit f) und Bedeutung der Abweichung für die Bewertung (Spannung beim Bezugsstrom
gegen F·U_Tp – `REFERENCE_CURRENT`, `U_TP` und `F_FACTOR` aus Abschnitt 1, sonst die Werte der Ergebnisdatei); mit
PEN-Strömen außerdem der Strom ins **Ortsnetz** und Z_E,Ortsnetz = ΔU_E/I_ON samt Parallelschaltungsprüfung (gegen
den Erdschluss max(U_E)/I_F und den Erdungsstrom) und dem Vergleich mit der Erdungsmessung.
''')),
        code('''STATIONS = {n: e for n, e in RESULTS.items() if not e.tables.get("station_frequency", pd.DataFrame()).empty}
if STATIONS and R_TYPICAL is None:
    print("''' + t("ℹ No classification of r at 50 Hz – R_TYPICAL is not set (section 1).",
                   "ℹ Keine Einordnung von r bei 50 Hz – R_TYPICAL ist nicht gesetzt (Abschnitt 1).") + '''")
COMPARISONS = {}
REDUCTION = {}                                                    ''' + t("# reduction factor and parallel check per station", "# Reduktionsfaktor und Parallelschaltung je Station") + '''
DB = None
try:
    SITES = sites.load(CAMPAIGN_FOLDER)                            ''' + t("# sites file (location in groundmeas)", "# Messorte-Datei (Ort in groundmeas)") + '''
except ValueError as ex:
    SITES = sites.Sites()
    print("⚠", ex)
if STATIONS:
    try:
        DB = earthing.Database(GROUNDMEAS_DB)
    except (FileNotFoundError, ValueError) as ex:
        print("ℹ ''' + t("groundmeas database not available:", "groundmeas-Datenbank nicht verfügbar:") + '''", ex)
else:
    print("''' + t("No station measurement with an evaluation per frequency.", "Keine Stationsmessung mit frequenzselektiver Auswertung.") + '''")
for n, e in STATIONS.items():
    display(Markdown("### %s" % n))
    show(e.table("station_frequency"))
    interactive.station_frequency(e).show()
    if not e.tables.get("station_lv_network", pd.DataFrame()).empty:
        display(Markdown("''' + t("**LV network** – current I_LV and Z_E,LV = ΔU_E/I_LV (per frequency and RMS value)",
                                  "**Ortsnetz** – Strom I_ON und Z_E,Ortsnetz = ΔU_E/I_ON (je Frequenz und effektiv)") + '''"))
        show(e.table("station_lv_network_eff")); show(e.table("station_lv_network"))
    if DB is None:
        continue
    m = next(x for x in MEASUREMENTS if x["name"] == n)
    site = e.data.get("meta", {}).get("site") or ""
    entry = SITES.for_site(site)
    location = m.get("location") or (entry.location if entry is not None and entry.location else None) or \\
        earthing.location_from_site(site or m["measurement"])
    choice = DB.choose_location(location, exact_only=bool(m.get("location") or (entry is not None and entry.location)),
                                preset='location="{}" in MEASUREMENTS')
    if choice["note"]:
        print("ℹ", choice["note"])
    if choice["location"] is None:
        continue
    meas = earthing.exclude_own(DB.measurements(location=choice["location"]), CAMPAIGN, m["measurement"])
    response = earthing.frequency_response(DB, meas["measurement_id"])
    long_df, ratio = earthing.compare(e.table("station_frequency"), response, measurement=n)
    COMPARISONS[n] = (long_df, ratio)
    print("''' + t("groundmeas: location “%s”, measurements %s", "groundmeas: Ort „%s“, Messungen %s") + '''" % (choice["location"], ", ".join(map(str, meas["measurement_id"]))))
    if len(ratio):
        show(ratio)
    if long_df["source"].isin([earthing.SOURCE_INJECTION, earthing.SOURCE_GROUNDMEAS_FAULT]).any():
        interactive.earthing_comparison(long_df, ratio).show()
    rf, rf_eff = earthing.reduction_factor(e, response, reference_current_A=REFERENCE_CURRENT, U_Tp=U_TP, F=F_FACTOR,
                                           r_typical=R_TYPICAL)  ''' + t("# None: from the result file", "# None: aus der Ergebnisdatei") + '''
    not_set = [v for v, c in (("REFERENCE_CURRENT", "reference_current_A"), ("U_TP", "U_Tp_V"), ("F_FACTOR", "F_factor"))
               if len(rf_eff) and rf_eff[c].isna().all()]
    if not_set:
        print("''' + t("ℹ %s: relevance of the deviation for the assessment not determined – neither set in section 1 nor stored in the result file: %s",
                       "ℹ %s: Bedeutung der Abweichung für die Bewertung nicht bestimmt – weder in Abschnitt 1 gesetzt noch in der Ergebnisdatei gespeichert: %s") + '''"
              % (n, ", ".join(not_set)))
    lvc, lvc_eff = earthing.check_lv_network(e, response)
    REDUCTION[n] = dict(reduction_factor=rf, reduction_factor_eff=rf_eff, lv_network_check=lvc,
                        lv_network_check_eff=lvc_eff)
    if len(rf_eff):
        display(Markdown("''' + t("**Reduction factor** (RMS value and per harmonic)", "**Reduktionsfaktor** (effektiv und je Harmonische)") + '''")); show(rf_eff); show(rf)
        interactive.reduction_factor(rf, rf_eff).show()
    if len(lvc):
        display(Markdown("''' + t("**LV network ↔ earthing measurement**", "**Ortsnetz ↔ Erdungsmessung**") + '''")); show(lvc_eff); show(lvc)
        interactive.lv_network(e.table("station_lv_network"), lvc).show()
    for h in earthing.reduction_hints(rf_eff, lvc):
        print("⚠ %s: %s" % (n, h))'''),
        md(t('''
## 6 · Export the report tables and figures

Report tables (voltages before/after, residual current, split at 50 Hz, earth potential rises, shield current,
transformer, assessment quantities, equivalent sources) as an Excel workbook, a Word file, CSV and Markdown; figures
in final size without titles as PDF/SVG/PNG.
''', '''
## 6 · Berichtstabellen und Abbildungen exportieren

Berichtstabellen (Spannungen vor/nach, Erdschlussreststrom, Aufteilung 50 Hz, Erdungsspannungen, Schirmstrom, Trafo,
Bewertungsgrößen, Ersatzquellen) als Excel-Mappe, Word-Datei, CSV und Markdown; Abbildungen in Endgröße ohne Titel als
PDF/SVG/PNG.
''')),
        code('''slug = report.slug                  ''' + t("# names in file and table names: lower case, letters/digits/_ (as in the report tables)",
                                                   "# Namen in Datei- und Tabellennamen: Kleinbuchstaben, Buchstaben/Ziffern/_ (wie in den Berichtstabellen)") + '''
OUT = CAMPAIGN_FOLDER / LAYOUT.results / ("campaign" if LAYOUT.language == "en" else "Kampagne")
FIG = CAMPAIGN_FOLDER / LAYOUT.figures / ("campaign" if LAYOUT.language == "en" else "Kampagne")
TABLES = report.report_tables(RESULTS, series=MAIN, Z_E=Z_E, comparison=OTHER)
TABLES["overview"] = campaign.overview(RESULTS)
for n, e in STATIONS.items():                     ''' + t("# station: per frequency and ratio to the earthing measurement", "# Station: frequenzselektiv und Verhältnis zur Erdungsmessung") + '''
    TABLES["station_frequency_" + slug(n)] = e.table("station_frequency")
    if n in COMPARISONS and len(COMPARISONS[n][1]):
        TABLES["earthing_ratio_" + slug(n)] = COMPARISONS[n][1]
    if not e.tables.get("station_lv_network_eff", pd.DataFrame()).empty:
        TABLES["station_lv_network_eff_" + slug(n)] = e.table("station_lv_network_eff")
        TABLES["station_lv_network_" + slug(n)] = e.table("station_lv_network")
    for t_, df in REDUCTION.get(n, {}).items():
        if len(df):
            TABLES[t_ + "_" + slug(n)] = df
if PQ is not None:                                 ''' + t("# PQ measurement: quantiles, characteristic values, tests, residual current at Z_E",
                                                   "# PQ-Messung: Quantile, Kennwerte, Versuche, Reststrom an Z_E") + '''
    TABLES["pq_quantiles"] = PQ.table().query("order >= 2")
    TABLES["pq_summary"] = PQ.summary_table()
    for name_, df_ in (("pq_tests", PQ_COMPARISON), ("pq_scaling", PQ_SCALING)):
        if df_ is not None and len(df_):
            TABLES[name_] = df_
for name, df in TABLES.items():                    ''' + t("# title with the name of the measurement as given", "# Titel mit dem Namen der Messung wie angegeben") + '''
    display(Markdown("**%s**" % report.table_title(name, RESULTS))); display(report.format_table(df))
paths = report.export_tables(TABLES, str(OUT), prefix="campaign_", formats=("csv", "md"), names=RESULTS)
figures = []
for n, e in STATIONS.items():
    figures += report.save(report.station_frequency(e), str(FIG / ("station_frequency_" + slug(n))), EXPORT_FORMATS, close=True)
    figures += report.save(report.station_background(e), str(FIG / ("station_background_" + slug(n))), EXPORT_FORMATS, close=True)
    if n in COMPARISONS:
        try:
            figures += report.save(report.earthing_comparison(*COMPARISONS[n]),
                                   str(FIG / ("earthing_comparison_" + slug(n))), EXPORT_FORMATS, close=True)
        except ValueError as ex:
            print("ℹ %s: %s" % (n, ex))
    rd = REDUCTION.get(n, {})
    if len(rd.get("reduction_factor_eff", [])):
        figures += report.save(report.reduction_factor(rd["reduction_factor"], rd["reduction_factor_eff"]),
                               str(FIG / ("reduction_factor_" + slug(n))), EXPORT_FORMATS, close=True)
    if not e.tables.get("station_lv_network", pd.DataFrame()).empty:
        lvc = rd.get("lv_network_check")
        figures += report.save(report.lv_network(e.table("station_lv_network"), lvc if lvc is not None and len(lvc) else None),
                               str(FIG / ("lv_network_" + slug(n))), EXPORT_FORMATS, close=True)
sub_results = [RESULTS[m["name"]] for m in MEASUREMENTS if m["Z"] is not None and m["name"] in RESULTS]
if sub_results:
    f = report.spectrum_comparison(sub_results, [m["name"] for m in MEASUREMENTS if m["Z"] is not None and m["name"] in RESULTS])
    figures += report.save(f, str(FIG / "fault_current_spectrum_comparison"), EXPORT_FORMATS, close=True)
if MAIN is not None:                    ''' + t("# result (SOURCE), the other source dashed", "# Ergebnis (SOURCE), die andere Quelle gestrichelt") + '''
    figures += report.save(report.source_fit(MAIN, Z_E=Z_E, comparison=OTHER), str(FIG / "source_fit"), EXPORT_FORMATS,
                           close=True)
    figures += report.save(report.source_plane(MAIN, MC), str(FIG / "source_impedance"), EXPORT_FORMATS, close=True)
    figures += report.save(report.ires_over_ze(MAIN, Z_E_MAX, LIMITS, IG_CHOICE, SCALING, comparison=OTHER),
                           str(FIG / "ires_over_ZE"), EXPORT_FORMATS, close=True)
if PQ is not None:
    figures += report.save(report.pq_series(PQ), str(FIG / "pq_series"), EXPORT_FORMATS, close=True)
    figures += report.save(report.pq_duration(PQ, levels={n: lv[PQ.dominant_order] for n, lv in (PQ_LEVELS or {}).items()
                                                          if PQ.dominant_order in lv}),
                           str(FIG / "pq_duration"), EXPORT_FORMATS, close=True)
    figures += report.save(report.pq_profile(PQ), str(FIG / "pq_profile"), EXPORT_FORMATS, close=True)
print("''' + t("%d table files in %s", "%d Tabellen-Dateien in %s") + '''" % (len(paths), OUT.relative_to(WORK_FOLDER)))
print("''' + t("%d figure files in %s", "%d Abbildungsdateien in %s") + '''" % (len(figures), FIG.relative_to(WORK_FOLDER)))'''),
        md(t('''
## 7 · groundmeas: enter the measurements of the campaign

Every measurement of `MEASUREMENTS` as a staged fault test (`staged_fault_test`) in groundmeas – substation with the
fault current per order and the fault resistance, station also with the earth potential rise and touch voltage per
probe and frequency (fault-related part) and the shield current. Location, coordinates, asset type, voltage level and
distance to the substation come from the sites file of the campaign (created pre-filled from groundmeas the first
time – **enter coordinates for new locations**). At first only the overview (dry run); written with
`GROUNDMEAS_EXPORT = True` – after **one** backup copy of the database; measurements entered before are recognised and
skipped (`"replace"` renews the own entries), other entries are never changed.
''', '''
## 7 · groundmeas: Messungen der Kampagne eintragen

Jede Messung aus `MEASUREMENTS` als Erdschlussmessung (`staged_fault_test`) in groundmeas – UW mit dem Fehlerstrom je
Ordnung und dem Fehlerwiderstand, Station zusätzlich mit Erdungs-/Berührungsspannung je Sonde und Frequenz
(fehlerbedingter Anteil) und Schirmstrom. Ort, Koordinaten, Anlagentyp, Spannungsebene und Entfernung zum UW stehen in
der Messorte-Datei der Kampagne (wird beim ersten Mal aus groundmeas vorbelegt angelegt – für **neue Orte Koordinaten
eintragen**). Zuerst nur Übersicht (Trockenlauf); geschrieben wird mit `GROUNDMEAS_EXPORT = True` – nach **einer**
Sicherungskopie der Datenbank; schon eingetragene Messungen werden erkannt und übersprungen (`"replace"` erneuert die
eigenen Einträge), andere Einträge werden nie verändert.
''')),
        code('''legacy.check_option("GROUNDMEAS_EXPORT", GROUNDMEAS_EXPORT, (False, True, "replace"))
PLANS, BACKUP = {}, True
for m in MEASUREMENTS:
    if m["name"] not in RESULTS:
        continue
    try:
        PLANS[m["name"]] = p = earthing.export_to_groundmeas(
            RESULTS[m["name"]], CAMPAIGN_FOLDER, GROUNDMEAS_DB, location=m.get("location"), write=bool(GROUNDMEAS_EXPORT),
            existing="replace" if GROUNDMEAS_EXPORT == "replace" else "skip", uncertain_mode=GROUNDMEAS_UNCERTAIN,
            description=m.get("description", ""), timestamp=m.get("timestamp"), units=GROUNDMEAS_UNITS, backup=BACKUP)
        if p.get("written"):
            BACKUP = p["backup"]           ''' + t("# one backup copy for all entries of this run", "# eine Sicherungskopie für alle Einträge dieses Laufs") + '''
    except FileNotFoundError as ex:
        print("ℹ ''' + t("groundmeas database not available:", "groundmeas-Datenbank nicht verfügbar:") + '''", ex)
        break
    except ValueError as ex:
        print("ℹ %s: %s" % (m["name"], ex))
if PLANS:
    show(earthing.plan_overview(PLANS))
    for n, p in PLANS.items():
        for h in p["hints"]:
            print("ℹ %s: %s" % (n, h))
        for w in p["warnings"]:
            print("⚠ %s: %s" % (n, w))
    display(Markdown("**%s**" % Path(sites.path_for(CAMPAIGN_FOLDER)).relative_to(CAMPAIGN_FOLDER)))
    show(sites.load(CAMPAIGN_FOLDER).table())
    if isinstance(BACKUP, str):
        print("''' + t("✓ entered – backup copy: %s – now set GROUNDMEAS_EXPORT back to False.",
                       "✓ eingetragen – Sicherungskopie: %s – jetzt GROUNDMEAS_EXPORT wieder auf False stellen.") + '''" % BACKUP)
    elif any(p["writable"] for p in PLANS.values()):
        print("''' + t("Dry run – enter with GROUNDMEAS_EXPORT = True (values per measurement: earthing.plan_items(PLANS[name])).",
                       "Trockenlauf – eintragen mit GROUNDMEAS_EXPORT = True (Werte je Messung: earthing.plan_items(PLANS[name])).") + '''")'''),
    ]
    # the campaign notebook needs json for the demo cell
    cells[1] = code(setup(lang).replace("import sys\n", "import json\nimport sys\n", 1))
    return _notebook(cells, lang, NAMES[lang][1])


# =========================================================================== forecast (optional part)
def forecast_notebook(lang: str, example: bool) -> nbf.NotebookNode:
    """The forecast notebook (optional part of groundfault): network model of a busbar and forecast."""
    t = (lambda en, de: en if lang == "en" else de)
    if example:
        conf = t('''NETWORK   = "Demo substation"            # name of the network model (substation, busbar)
DEMO      = True                         # create the demo campaign, a recorded earth fault and their result files if missing
CAMPAIGNS = ["2026-01-15_Demo"]          # campaigns whose staged fault tests calibrate the model (from the register)
TESTS     = None                         # None = the tests of CAMPAIGNS from the register; or a list of dict(campaign=…, measurement=…, Z=…)
# Recorded earth faults at the busbar (update): result files of evaluate_measurement.ipynb with the busbar voltages
# before and during the fault – no fault current needed; with coil currents also the fault current per order
FAULTS = [
    dict(campaign="2026-01-15_Demo", measurement="SUB_fault_10_000kHz"),
]
# Measurements to check the model with, e.g. a staged fault test at a location in the network:
# dict(campaign=…, measurement=<busbar recording>, Z=…, current=<recording with the fault current>, line=LINE)
CHECKS = []''', '''NETWORK   = "Demo-UW"                    # Name des Netzmodells (Umspannwerk, Sammelschiene)
DEMO      = True                         # Demo-Kampagne, einen aufgezeichneten Erdschluss und ihre Ergebnisdateien anlegen, falls sie fehlen
CAMPAIGNS = ["2026-01-15_Demo"]          # Kampagnen, deren Erdschlussversuche das Modell kalibrieren (aus dem Messregister)
TESTS     = None                         # None = die Versuche von CAMPAIGNS aus dem Messregister; oder eine Liste dict(campaign=…, measurement=…, Z=…)
# Aufgezeichnete Erdschlüsse an der Sammelschiene (Nachführung): Ergebnisdateien aus Messung_auswerten.ipynb mit den
# Sammelschienenspannungen vor und im Fehler – ohne Fehlerstrom; mit Spulenströmen auch der Fehlerstrom je Ordnung
FAULTS = [
    dict(campaign="2026-01-15_Demo", measurement="UW_Erdschluss_10_000kHz"),
]
# Messungen zur Prüfung des Modells, z. B. ein Erdschlussversuch an einem Ort im Netz:
# dict(campaign=…, measurement=<Aufzeichnung der Sammelschiene>, Z=…, current=<Aufzeichnung mit dem Fehlerstrom>, line=LINE)
CHECKS = []''')
        voltages = t('''{3: 30.0, 5: 250.0, 7: 130.0, 11: 40.0, 13: 30.0}   # demo values: 95 % quantiles in V (line-to-earth)''',
                     '''{3: 30.0, 5: 250.0, 7: 130.0, 11: 40.0, 13: 30.0}   # Demo-Werte: 95-%-Quantile in V (Leiter-Erde)''')
        line = t('''dict(name="Demo feeder, station 4", segments=[         # demo: 4 km cable, 1.5 km overhead line
    dict(length_km=4.0, R1=0.125, X1=0.11, R0=0.50, X0=0.40, C1_uF=0.30),
    dict(length_km=1.5, R1=0.30,  X1=0.35, R0=0.45, X0=1.20, C1_uF=0.01)])''', '''dict(name="Demo-Abgang, Station 4", segments=[         # Demo: 4 km Kabel, 1,5 km Freileitung
    dict(length_km=4.0, R1=0.125, X1=0.11, R0=0.50, X0=0.40, C1_uF=0.30),
    dict(length_km=1.5, R1=0.30,  X1=0.35, R0=0.45, X0=1.20, C1_uF=0.01)])''')
    else:
        conf = t('''NETWORK   = "<substation>"               # name of the network model (substation, busbar)
DEMO      = False
CAMPAIGNS = ["YYYY-MM-DD_Place"]         # campaigns whose staged fault tests calibrate the model (from the register)
TESTS     = None                         # None = the tests of CAMPAIGNS from the register; or a list of dict(campaign=…, measurement=…, Z=…)
# Recorded earth faults at the busbar (update): result files of evaluate_measurement.ipynb with the busbar voltages
# before and during the fault – no fault current needed; with coil currents also the fault current per order
FAULTS = [
    # dict(campaign="YYYY-MM-DD_Place", measurement="<recording>"),
]
# Measurements to check the model with, e.g. a staged fault test at a location in the network:
# dict(campaign=…, measurement=<busbar recording>, Z=…, current=<recording with the fault current>, line=LINE)
CHECKS = []''', '''NETWORK   = "<UW>"                       # Name des Netzmodells (Umspannwerk, Sammelschiene)
DEMO      = False
CAMPAIGNS = ["JJJJ-MM-TT_Ort"]           # Kampagnen, deren Erdschlussversuche das Modell kalibrieren (aus dem Messregister)
TESTS     = None                         # None = die Versuche von CAMPAIGNS aus dem Messregister; oder eine Liste dict(campaign=…, measurement=…, Z=…)
# Aufgezeichnete Erdschlüsse an der Sammelschiene (Nachführung): Ergebnisdateien aus Messung_auswerten.ipynb mit den
# Sammelschienenspannungen vor und im Fehler – ohne Fehlerstrom; mit Spulenströmen auch der Fehlerstrom je Ordnung
FAULTS = [
    # dict(campaign="JJJJ-MM-TT_Ort", measurement="<Aufzeichnung>"),
]
# Messungen zur Prüfung des Modells, z. B. ein Erdschlussversuch an einem Ort im Netz:
# dict(campaign=…, measurement=<Aufzeichnung der Sammelschiene>, Z=…, current=<Aufzeichnung mit dem Fehlerstrom>, line=LINE)
CHECKS = []''')
        voltages = t('''None   # harmonic voltages per order in V, e.g. {5: U_5, 7: U_7}, or a CSV file (None = no forecast)''',
                     '''None   # Oberschwingungsspannungen je Ordnung in V, z. B. {5: U_5, 7: U_7}, oder eine CSV-Datei (None = keine Prognose)''')
        line = t('''None   # fault location in the network: dict(name=…, segments=[dict(length_km=…, R1=…, X1=…, R0=…, X0=…, C1_uF=…)])''',
                 '''None   # Fehlerort im Netz: dict(name=…, segments=[dict(length_km=…, R1=…, X1=…, R0=…, X0=…, C1_uF=…)])''')
    conf += t('''
# optional per entry: name="…" (default: the measurement), meta=dict(…) (e.g. load, PV infeed, switching state),
# transformer="…" (transformer recording of the same earth fault by a second recorder: its upstream impedance Z_up),
# line=dict(…) (a test in the network: the line to its fault location)

# ---------------------------------------------------------------- model
ORDERS        = "auto"            # "auto" = odd orders ≥ 3 with at least MIN_CURRENT_A in the test, otherwise e.g. [3, 5, 7, 11, 13]
MIN_CURRENT_A = 0.3               # smallest current of an order for "auto" in A
HOW           = "median"          # Z_q over the earth faults: "median" | "mean" | "latest" (the last one added)
TWO_SOURCE    = "zero_sequence"   # orders with a source that arises in the fault: "zero_sequence" (3, 9, 15 …) | [orders] | None

# ---------------------------------------------------------------- forecast
VOLTAGES          = ''' + voltages + '''
VOLTAGE_REFERENCE = "LE"          # "LE" = line-to-earth | "LL" = line-to-line (divided by √3; no zero sequence)
CSV_OPTIONS       = dict(sep=";", decimal=",", index_col=0)   # reading a CSV file (pandas.read_csv): one column per order
QUANTILE          = 0.95          # quantile of a time series (and of the 10-min values of PQ_FILES)
PQ_FILES          = None          # export(s) of a PQ instrument at the busbar → VOLTAGES = quantile per order (line-to-earth, largest phase) × factor; relative to the work folder or absolute
PQ_TIMEZONE       = None          # time zone of the instrument clock, e.g. "Europe/Berlin" (None = time stamps as exported)
PQ_SERIES         = False         # True: every 10-min value of PQ_FILES (time series) → quantile QUANTILE of I_H and I_RES
Z_F               = 0.0           # fault impedance in Ω (0 = fault without resistance)
LINE              = ''' + line + '''
# per-length values at 50 Hz (Ω/km, µF/km) give R constant, X ∝ m – not on the safe side; at the orders of interest give
# values of their own: per segment orders={5: dict(R1=…, X1=…, R0=…, X0=…)} (Ω/km at 250 Hz, X not divided by 5) or for
# the whole line loop={5: Z_qL} (Ω, e.g. measured with MODEL.line_from_fault(<recorded earth fault behind the line>))

# ---------------------------------------------------------------- margins and limits – defined by you
# groundfault contains no margins or limits. Not set (the values below), the forecast is shown without them.
MARGIN_A      = 0.0     # margin per order in A: a number or {order: A} (0.0 = none), e.g. from the checks of section 3
FUNDAMENTAL_A = None    # fundamental residual current in A (None = median of √(I_w² + I_v²) of the tests)
LIMITS        = ()      # limits of the residual current in A, e.g. (I_1, I_2)
PQ_SAFETY_FACTOR = 1.0  # factor on the quantile of the PQ measurement (1.0 = none)
PQ_FACTORS    = None    # factor on the quantile by the duration of the PQ measurement {minimum days: factor} (None = PQ_SAFETY_FACTOR)''', '''
# optional je Eintrag: name="…" (Standard: die Messung), meta=dict(…) (z. B. Last, PV-Einspeisung, Schaltzustand),
# transformer="…" (Trafoaufzeichnung desselben Erdschlusses, zweites Messgerät: deren Vorimpedanz Z_vor),
# line=dict(…) (ein Versuch im Netz: die Leitung bis zu seinem Fehlerort)

# ---------------------------------------------------------------- Modell
ORDERS        = "auto"            # "auto" = ungerade Ordnungen ≥ 3 mit mindestens MIN_CURRENT_A im Versuch, sonst z. B. [3, 5, 7, 11, 13]
MIN_CURRENT_A = 0.3               # kleinster Strom einer Ordnung für "auto" in A
HOW           = "median"          # Z_q über die Erdschlüsse: "median" | "mean" (Mittel) | "latest" (der zuletzt hinzugefügte)
TWO_SOURCE    = "zero_sequence"   # Ordnungen mit einer im Fehler entstehenden Quelle: "zero_sequence" (3, 9, 15 …) | [Ordnungen] | None

# ---------------------------------------------------------------- Prognose
VOLTAGES          = ''' + voltages + '''
VOLTAGE_REFERENCE = "LE"          # "LE" = Leiter-Erde | "LL" = Leiter-Leiter (durch √3 geteilt; ohne Nullsystem)
CSV_OPTIONS       = dict(sep=";", decimal=",", index_col=0)   # Lesen einer CSV-Datei (pandas.read_csv): eine Spalte je Ordnung
QUANTILE          = 0.95          # Quantil einer Zeitreihe (und der 10-min-Werte von PQ_FILES)
PQ_FILES          = None          # Export(e) eines PQ-Messgeräts an der Sammelschiene → VOLTAGES = Quantil je Ordnung (Leiter-Erde, größter Leiter) × Faktor; relativ zum Arbeitsordner oder absolut
PQ_TIMEZONE       = None          # Zeitzone der Geräteuhr, z. B. "Europe/Berlin" (None = Zeitstempel wie exportiert)
PQ_SERIES         = False         # True: jeder 10-min-Wert von PQ_FILES (Zeitreihe) → Quantil QUANTILE von I_H und I_RES
Z_F               = 0.0           # Fehlerimpedanz in Ω (0 = Fehler ohne Widerstand)
LINE              = ''' + line + '''
# Beläge bei 50 Hz (Ω/km, µF/km) heißen R konstant, X ∝ m – nicht auf der sicheren Seite; für die wichtigen Ordnungen
# eigene Werte angeben: je Abschnitt orders={5: dict(R1=…, X1=…, R0=…, X0=…)} (Ω/km bei 250 Hz, X nicht durch 5 geteilt)
# oder für die ganze Leitung loop={5: Z_qL} (Ω, z. B. gemessen mit MODEL.line_from_fault(<Erdschluss hinter der Leitung>))

# ---------------------------------------------------------------- Zuschläge und Grenzwerte – selbst festlegen
# groundfault enthält keine Zuschläge oder Grenzwerte. Nicht gesetzt (die Werte unten), zeigt die Prognose sie nicht.
MARGIN_A      = 0.0     # Zuschlag je Ordnung in A: eine Zahl oder {Ordnung: A} (0.0 = keiner), z. B. aus der Prüfung in Abschnitt 3
FUNDAMENTAL_A = None    # Grundschwingungsreststrom in A (None = Median von √(I_w² + I_v²) der Versuche)
LIMITS        = ()      # Grenzwerte des Reststroms in A, z. B. (I_1, I_2)
PQ_SAFETY_FACTOR = 1.0  # Faktor auf das Quantil der PQ-Messung (1.0 = keiner)
PQ_FACTORS    = None    # Faktor auf das Quantil nach Dauer der PQ-Messung {Mindesttage: Faktor} (None = PQ_SAFETY_FACTOR)''')
    cells = [
        md(t('''
# Forecast of the harmonic residual current – network model of a busbar

An **optional part** of groundfault: it builds on the **result files** of the single evaluations
(`evaluate_measurement.ipynb`, section 7) and needs nothing else of the evaluation. The **network model** of the
earth-fault loop at a busbar per harmonic order is calibrated with the staged fault tests, updated with every earth
fault recorded at the busbar and checked; from harmonic voltages – e.g. the 95 % quantiles of a power-quality
measurement – it forecasts the **harmonic residual current** I_H and the residual current I_RES of an earth fault at
the busbar or behind a line. Reference copy: `templates/network_model_forecast_DEFAULT.ipynb`. Method and
equivalent circuits: online documentation, *Forecast*.

1. **Calibration** with the staged fault tests of the campaigns (fault current measured): sequence impedances
   Z_0, Z_1, Z_2 per order from the changes of the busbar voltages, Z_q = (Z_0 + Z_1 + Z_2)/3; at the orders of the
   zero sequence also the source that only exists during the fault (saturating coils and transformers).
2. **Checks between the tests** – the deviations show the margin a forecast needs.
3. **Recorded earth faults** (busbar voltages, e.g. of a disturbance recorder): Z_1, Z_2, Z_q updated, the fault
   current estimated (with coil currents by the node rule at every order) and the forecast checked at each of them.
4. **Checks with other measurements**, e.g. a staged fault test at a location in the network.
5. **Forecast** of I_H and I_RES (one value per order or a time series; at the busbar or behind `LINE`).
6. **Save** the model file and the tables in the forecast folder of the work folder.
''', '''
# Prognose des Oberschwingungsreststroms – Netzmodell einer Sammelschiene

Ein **optionaler Teil** von groundfault: Er baut auf den **Ergebnisdateien** der Einzelauswertungen auf
(`Messung_auswerten.ipynb`, Abschnitt 7) und braucht sonst nichts von der Auswertung. Das **Netzmodell** der
Erdschlussschleife an einer Sammelschiene je Oberschwingungsordnung wird mit den Erdschlussversuchen kalibriert, mit
jedem an der Sammelschiene aufgezeichneten Erdschluss nachgeführt und geprüft; aus Oberschwingungsspannungen – z. B.
den 95-%-Quantilen einer Netzqualitätsmessung – prognostiziert es den **Oberschwingungsreststrom** I_H und den
Reststrom I_RES eines Erdschlusses an der Sammelschiene oder hinter einer Leitung. Ausgangsfassung:
`Vorlagen/Netzmodell_Prognose_DEFAULT.ipynb`. Verfahren und Ersatzschaltbilder: Online-Dokumentation, *Forecast*.

1. **Kalibrierung** mit den Erdschlussversuchen der Kampagnen (Fehlerstrom gemessen): Sequenzimpedanzen Z_0, Z_1, Z_2
   je Ordnung aus den Änderungen der Sammelschienenspannungen, Z_q = (Z_0 + Z_1 + Z_2)/3; bei den Ordnungen des
   Nullsystems zusätzlich die Quelle, die nur im Fehler besteht (sättigende Spulen und Wandler).
2. **Prüfung zwischen den Versuchen** – die Abweichungen zeigen, welchen Zuschlag eine Prognose braucht.
3. **Aufgezeichnete Erdschlüsse** (Sammelschienenspannungen, z. B. eines Störschreibers): Z_1, Z_2, Z_q nachgeführt,
   der Fehlerstrom geschätzt (mit Spulenströmen über die Knotenregel bei jeder Ordnung) und die Prognose an jedem von
   ihnen geprüft.
4. **Prüfung mit weiteren Messungen**, z. B. einem Erdschlussversuch an einem Ort im Netz.
5. **Prognose** von I_H und I_RES (ein Wert je Ordnung oder eine Zeitreihe; an der Sammelschiene oder hinter `LINE`).
6. Modelldatei und Tabellen im Prognoseordner des Arbeitsordners **speichern**.
''')),
        code(setup(lang).replace("import sys\n", "import datetime\nimport json\nimport sys\nimport warnings\n", 1)
             .replace("from IPython.display import Markdown, display\n",
                      "from IPython.display import Markdown, display\nfrom groundfault import forecast as fc\n", 1)),
        md(t("## 1 · Configuration", "## 1 · Konfiguration")),
        code(conf),
        md(t('''
## 2 · Calibration with the staged fault tests

Per test and order the **B method**: Z_s = 3·p_s·ΔU_s/I (s = zero, positive, negative sequence; ΔU = change of the
busbar voltage during the fault, I = fault current, p_s = phase factor of the faulted phase). The source is the
pre-fault voltage of the faulted phase, U_q = −Σ p_s·U_pre,s. At the orders of `TWO_SOURCE` the tests with different
additional impedances also separate the source U_s that arises in the fault (`two_source`); with only one additional
impedance the measured current is used for every fault impedance (`constant`). With coil currents in the tests the
admittance of the network without the coils, Y_0,net = (I − I_coil)/(3·ΔU_0), is kept for the node rule (section 4).
''', '''
## 2 · Kalibrierung mit den Erdschlussversuchen

Je Versuch und Ordnung das **B-Verfahren**: Z_s = 3·p_s·ΔU_s/I (s = Null-, Mit-, Gegensystem; ΔU = Änderung der
Sammelschienenspannung im Fehler, I = Fehlerstrom, p_s = Phasenfaktor des Fehlerleiters). Quelle ist die
Vorfehlerspannung des Fehlerleiters, U_q = −Σ p_s·U_pre,s. Bei den Ordnungen von `TWO_SOURCE` trennen Versuche mit
verschiedener Zusatzimpedanz zusätzlich die im Fehler entstehende Quelle U_s ab (`zwei Quellen`); mit nur einer
Zusatzimpedanz gilt der gemessene Strom für jede Fehlerimpedanz (`konstant`). Mit Spulenströmen in den Versuchen wird
die Admittanz des Netzes ohne die Spulen, Y_0,Netz = (I − I_Spule)/(3·ΔU_0), für die Knotenregel (Abschnitt 4)
behalten.
''')),
        code('''for i, e in enumerate(FAULTS + CHECKS):     ''' + t("# known keys only (a misspelt key would be ignored)",
                                                    "# nur bekannte Schlüssel (ein vertippter Schlüssel bliebe unbeachtet)") + '''
    legacy.check_keys("FAULTS" if i < len(FAULTS) else "CHECKS", e, fc.ENTRY_KEYS + ("current",))

if DEMO:                         ''' + t("# demo: campaign, a recording of the busbar voltages and coil currents, result files",
                                        "# Demo: Kampagne, eine Aufzeichnung der Sammelschienenspannungen und Spulenströme, Ergebnisdateien") + '''
    for c in CAMPAIGNS:
        if not (WORK_FOLDER / LAYOUT.campaigns / c).exists():
            demo.make_campaign(str(WORK_FOLDER), c, layout=LAYOUT.language)
    for e in [*FAULTS, *[dict(campaign=c, measurement=t["measurement"], Z=t["Z"]) for c in CAMPAIGNS
                         for t in fc.campaign_tests(WORK_FOLDER, c)]]:
        folder = WORK_FOLDER / LAYOUT.campaigns / e["campaign"]
        cfg = folder / LAYOUT.raw / ("SUB" if LAYOUT.language == "en" else "UW") / (e["measurement"] + ".cfg")
        if e in FAULTS and not cfg.exists():            ''' + t("# recorded earth fault: busbar voltages and coil currents",
                                                              "# aufgezeichneter Erdschluss: Sammelschienenspannungen und Spulenströme") + '''
            demo.make_substation_recording(str(cfg), 0.0, drift=demo.polar(1.15, 20), fault_current=False, seed=7,
                                           start=datetime.datetime(2026, 3, 2, 14, 7))
        if not Path(fc.result_path(WORK_FOLDER, e["campaign"], e["measurement"])).exists():
            with open(str(cfg).replace(".cfg", "_truth.json"), encoding="utf-8") as f:
                b = json.load(f)["intervals"]
            r_ = gf.evaluate(gf.open_recording(str(cfg)),
                             gf.Intervals(*(tuple(b[k]) for k in ("steady_state", "pre_fault", "post_fault"))),
                             z_fault_ohm=e.get("Z"))
            r_.save_json(LAYOUT.result_path(folder, e["measurement"]))
if TESTS is None:
    TESTS = [t for c in CAMPAIGNS for t in fc.campaign_tests(WORK_FOLDER, c)]
display(Markdown("''' + t("**Staged fault tests** (`TESTS`)", "**Erdschlussversuche** (`TESTS`)") + '''"))
show(pd.DataFrame(TESTS))
MODEL = fc.NetworkModel(NETWORK)
for msg in fc.add_entries(MODEL, WORK_FOLDER, TESTS, "test", orders=ORDERS, min_current_A=MIN_CURRENT_A):
    print("ℹ", msg)
if MODEL.tests:
    show(MODEL.table())
    display(Markdown("''' + t("**Model per order**", "**Modell je Ordnung**") + '''"))
    show(MODEL.source_table(how=HOW, two_source=TWO_SOURCE))
    for T in MODEL.source_terms(how=HOW, two_source=TWO_SOURCE).values():
        for h in T.hints:
            print("ℹ", h)
else:
    print("''' + t("No calibration – the model needs at least one staged fault test with the fault current (TESTS).",
                   "Keine Kalibrierung – das Modell braucht mindestens einen Erdschlussversuch mit Fehlerstrom (TESTS).") + '''")'''),
        md(t('''
## 3 · Checks between the tests

Every test is forecast from its own pre-fault voltage and additional impedance with the model of other tests:
`loo` = model of all other tests, `pairwise` = model of one other test (every pair), `chain` = Z_0 of one test, Z_q
from the busbar voltages of a second one (as a recorded earth fault), forecast for a third. `deviation_A` = forecast
− measured: **negative values are underestimates**. The largest underestimate per order of `loo` – a model of the
other tests, like the forecast with all of them – is a basis for your margin `MARGIN_A`; `pairwise` and `chain` show
how far a single test or an update with a recorded earth fault carries (with one test the orders of the zero sequence
keep the current of that test). The row `I_H` is the whole harmonic content (orders not modelled included).
''', '''
## 3 · Prüfung zwischen den Versuchen

Jeder Versuch wird aus seiner eigenen Vorfehlerspannung und Zusatzimpedanz mit dem Modell anderer Versuche
prognostiziert: `alle anderen` = Modell aller übrigen Versuche, `paarweise` = Modell eines anderen Versuchs (jedes
Paar), `Lernkette` = Z_0 eines Versuchs, Z_q aus den Sammelschienenspannungen eines zweiten (wie ein aufgezeichneter
Erdschluss), Prognose für einen dritten. `Abweichung_A` = Prognose − Messung: **negative Werte sind
Unterschätzungen**. Die größte Unterschätzung je Ordnung von `alle anderen` – ein Modell der übrigen Versuche, wie
die Prognose mit allen – ist eine Grundlage für den eigenen Zuschlag `MARGIN_A`; `paarweise` und `Lernkette` zeigen,
wie weit ein einzelner Versuch oder eine Nachführung mit einem aufgezeichneten Erdschluss trägt (mit einem Versuch
behalten die Ordnungen des Nullsystems den Strom dieses Versuchs). Die Zeile `I_H` ist der gesamte
Oberschwingungsanteil (nicht modellierte Ordnungen eingeschlossen).
''')),
        code('''CROSS_CHECKS = pd.DataFrame()
if len(MODEL.tests) >= 2:
    modes = ["loo", "pairwise"] + (["chain"] if len(MODEL.tests) >= 3 else [])
    CROSS_CHECKS = pd.concat([MODEL.cross_check(0.0, mode, how=HOW, two_source=TWO_SOURCE) for mode in modes],
                             ignore_index=True)
    summary = (CROSS_CHECKS.assign(order=CROSS_CHECKS["order"].astype(str))
               .groupby(["order", "mode"], sort=False)
               .agg(n=("deviation_A", "size"), deviation_min_A=("deviation_A", "min"),
                    deviation_max_A=("deviation_A", "max"), ratio_min=("ratio", "min"), ratio_max=("ratio", "max"))
               .reset_index())
    show(summary)
    under = CROSS_CHECKS[CROSS_CHECKS["order"] != "I_H"].groupby(["mode", "order"])["deviation_A"].min()
    for mode in [m for m in modes if m in under.index.get_level_values(0)]:   ''' + t("# per check, without margin",
                                                                                       "# je Prüfung, ohne Zuschlag") + '''
        print(i18n.format_text("''' + t("Largest underestimate per order without margin ({}):",
                                         "Größte Unterschätzung je Ordnung ohne Zuschlag ({}):") + '''",
                               i18n.value_label("mode", mode)),
              ", ".join(i18n.format_text("{}: {:.2f} A", m, min(v, 0.0)) for m, v in under[mode].items()))
    display(Markdown("''' + t("**All other tests (loo)**", "**Alle anderen Versuche (loo)**") + '''"))
    show(CROSS_CHECKS[CROSS_CHECKS["mode"] == "loo"])
else:
    print("''' + t("The checks need at least two staged fault tests.", "Die Prüfung braucht mindestens zwei Erdschlussversuche.") + '''")'''),
        md(t('''
## 4 · Recorded earth faults

An earth fault of the network recorded at the busbar – line-to-earth voltages before and during the fault, evaluated
with `evaluate_measurement.ipynb` (pre-fault and steady-state interval; a fault current is not needed). With Z_0 of
the tests: Z_s = Z_0·p_s·ΔU_s/ΔU_0. The **fault current** of the earth fault (`I_estimated_A`): with the coil currents
in the recording and in the tests by the **node rule** of the zero sequence, I_F = 3·Y_0,net·ΔU_0 + I_coil – at every
order, also where a source arises in the fault –, otherwise 3·|ΔU_0|/|Z_0|. The orders of `TWO_SOURCE` are not
updated. A recording with the line currents of the transformer – or `transformer=` – also gives the upstream impedance
Z_up and with it the MV network Z_down. Each earth fault then **checks the forecast**: the model of all other earth
faults forecasts it from its own pre-fault voltage with the fault impedance 0 (the fault impedance of a natural earth
fault is not known – its current can only be smaller).
''', '''
## 4 · Aufgezeichnete Erdschlüsse

Ein an der Sammelschiene aufgezeichneter Erdschluss des Netzes – Leiter-Erde-Spannungen vor und im Fehler,
ausgewertet mit `Messung_auswerten.ipynb` (Vorfehler- und stationärer Bereich; ein Fehlerstrom ist nicht nötig). Mit
Z_0 der Versuche: Z_s = Z_0·p_s·ΔU_s/ΔU_0. Der **Fehlerstrom** des Erdschlusses (`I_geschaetzt_A`): mit Spulenströmen
in der Aufzeichnung und in den Versuchen über die **Knotenregel** des Nullsystems, I_F = 3·Y_0,Netz·ΔU_0 + I_Spule –
bei jeder Ordnung, auch wo im Fehler eine Quelle entsteht –, sonst 3·|ΔU_0|/|Z_0|. Die Ordnungen von `TWO_SOURCE`
werden nicht nachgeführt. Eine Aufzeichnung mit den Leiterströmen des Trafos – oder `transformer=` – liefert
zusätzlich die Vorimpedanz Z_vor und damit das MS-Netz Z_MS. Jeder Erdschluss **prüft dann die Prognose**: Das Modell
aller anderen Erdschlüsse prognostiziert ihn aus seiner eigenen Vorfehlerspannung mit der Fehlerimpedanz 0 (die
Fehlerimpedanz eines natürlichen Erdschlusses ist unbekannt – sein Strom kann nur kleiner sein).
''')),
        code('''FAULT_CHECKS = pd.DataFrame()
if FAULTS and not MODEL.tests:
    print("''' + t("⚠ a recorded earth fault needs Z_0 of a calibration (section 2)",
                   "⚠ ein aufgezeichneter Erdschluss braucht Z_0 einer Kalibrierung (Abschnitt 2)") + '''")
elif FAULTS:
    for msg in fc.add_entries(MODEL, WORK_FOLDER, FAULTS, "fault", two_source=TWO_SOURCE):
        print("ℹ", msg)
if MODEL.faults:
    tab = MODEL.table()
    show(tab[tab["kind"] == "fault"])
    display(Markdown("''' + t("**|Z_q| of the earth faults ÷ median of the tests**", "**|Z_q| der Erdschlüsse ÷ Median der Versuche**") + '''"))
    ref = tab[tab["kind"] == "test"].groupby("order")["Zq_Ohm"].median()
    show(tab[tab["kind"] == "fault"].pivot(index="order", columns="name", values="Zq_Ohm").div(ref, axis=0))
    if any(c.currents for c in MODEL.faults):
        FAULT_CHECKS = MODEL.fault_check(0.0, how=HOW, two_source=TWO_SOURCE)
        display(Markdown("''' + t("**Forecast (fault impedance 0, without margin) ÷ estimated fault current**",
                                  "**Prognose (Fehlerimpedanz 0, ohne Zuschlag) ÷ geschätzter Fehlerstrom**") + '''"))
        show(FAULT_CHECKS)
else:
    print("''' + t("No recorded earth fault in the model (FAULTS).", "Kein aufgezeichneter Erdschluss im Modell (FAULTS).") + '''")'''),
        md(t('''
## 5 · Checks with other measurements

A measurement that is not part of the model – e.g. a staged fault test at a location in the network: the busbar
voltages of the substation recording (`measurement`), the fault current of the recording at the fault location
(`current`, magnitudes per order) and the line to the fault location (`line`). The model forecasts the fault current
from the pre-fault voltage of the busbar, the fault impedance `Z` and the line, Z_q + (2·Z_1L + Z_0L)/3 + Z_F. For an
entry with a line the busbar voltages of the same fault also measure the line per order (`MODEL.line_from_fault`):
Z_qL,m = −U_ph,bus,m/I_F,m − Z_F with the fault current from the busbar (node rule, otherwise 3·ΔU_0/Z_0 at the orders
without a source in the fault). `LINE_MEASURED` holds the values – as `loop=` of a line they give the forecast its own
values per order.
''', '''
## 5 · Prüfung mit weiteren Messungen

Eine Messung, die nicht Teil des Modells ist – z. B. ein Erdschlussversuch an einem Ort im Netz: die
Sammelschienenspannungen der UW-Aufzeichnung (`measurement`), der Fehlerstrom der Aufzeichnung am Fehlerort
(`current`, Beträge je Ordnung) und die Leitung bis zum Fehlerort (`line`). Das Modell prognostiziert den Fehlerstrom
aus der Vorfehlerspannung der Sammelschiene, der Fehlerimpedanz `Z` und der Leitung, Z_q + (2·Z_1L + Z_0L)/3 + Z_F. Für
einen Eintrag mit Leitung messen die Sammelschienenspannungen desselben Fehlers auch die Leitung je Ordnung
(`MODEL.line_from_fault`): Z_qL,m = −U_L,SS,m/I_F,m − Z_F mit dem Fehlerstrom aus der Sammelschiene (Knotenregel, sonst
3·ΔU_0/Z_0 bei den Ordnungen ohne Quelle im Fehler). `LINE_MEASURED` enthält die Werte – als `loop=` einer Leitung geben
sie der Prognose eigene Werte je Ordnung.
''')),
        code('''VERIFY = pd.DataFrame()
LINE_MEASURED, LINE_TABLE = {}, pd.DataFrame()
if CHECKS and MODEL.tests:
    parts, rows = [], []
    for e in CHECKS:
        try:
            fd = fc.check_data(WORK_FOLDER, e)
            parts.append(MODEL.verify(fd, 0.0, how=HOW, two_source=TWO_SOURCE))
            if fd.line is not None:          ''' + t("# the line per order from the busbar voltages of the same fault",
                                                     "# die Leitung je Ordnung aus den Sammelschienenspannungen desselben Fehlers") + '''
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    z = LINE_MEASURED[fd.name] = MODEL.line_from_fault(fd, fd.Z_F or 0.0, two_source=TWO_SOURCE)
                for w in caught:
                    print("ℹ", w.message)
                for m, v in sorted(z.items()):
                    g = fd.line.Zq(m)
                    rows.append(dict(target=fd.name, order=m, line_values=fd.line.source(m), Z_line_Ohm=abs(g),
                                     R_measured_Ohm=v.real, X_measured_Ohm=v.imag, Z_measured_Ohm=abs(v),
                                     ratio=abs(v) / abs(g) if abs(g) else float("nan")))
        except (OSError, ValueError) as ex:
            print("⚠", ex)
    if parts:
        VERIFY = pd.concat(parts, ignore_index=True)
        show(VERIFY)
    if rows:
        LINE_TABLE = pd.DataFrame(rows)
        display(Markdown("''' + t("**Line per order: given (`line`) and measured from the busbar voltages of the fault "
                                    "(`LINE_MEASURED`)**",
                                    "**Leitung je Ordnung: angegeben (`line`) und aus den Sammelschienenspannungen des "
                                    "Fehlers gemessen (`LINE_MEASURED`)**") + '''"))
        show(LINE_TABLE)
else:
    print("''' + t("ℹ No further measurements (CHECKS).", "ℹ Keine weiteren Messungen (CHECKS).") + '''")'''),
        md(t('''
## 6 · Forecast of the harmonic residual current

Harmonic voltages of the busbar per order (line-to-earth, the largest of the three phases): one value per order –
e.g. the 95 % quantile of a power-quality measurement – or a time series (CSV file, one column per order such as
`U_H5`; the last number of a column name is the order). Per order |I_F,m| = (|U_m| + |U_s,m|)/|Z_q,m + Z_qL,m + Z_F|
+ margin (Z_qL = 0 at the busbar, (2·Z_1L + Z_0L)/3 behind `LINE`), then I_H = √(Σ I_F,m² + I_rest²) with I_rest =
harmonic content of the tests outside the forecast orders and I_RES = √(I_1² + I_H²). A time series gives the
quantile `QUANTILE` of the time series of I_H and I_RES. With `PQ_FILES` the orders of the positive or negative sequence
get the quantile of the PQ measurement (times the factor of `PQ_FACTORS`); the zero sequence (3, 9, 15 …) – it arises
in the earth fault – and the even orders keep the pre-fault voltage of the tests (not scaled). A PQ measurement shorter
than every duration of `PQ_FACTORS` (gapless values) is not valid and gives no voltages.
''', '''
## 6 · Prognose des Oberschwingungsreststroms

Oberschwingungsspannungen der Sammelschiene je Ordnung (Leiter-Erde, die größte der drei Phasen): ein Wert je Ordnung
– z. B. das 95-%-Quantil einer Netzqualitätsmessung – oder eine Zeitreihe (CSV-Datei, eine Spalte je Ordnung wie
`U_H5`; die letzte Zahl eines Spaltennamens ist die Ordnung). Je Ordnung |I_F,m| = (|U_m| + |U_s,m|)/|Z_q,m + Z_qL,m +
Z_F| + Zuschlag (Z_qL = 0 an der Sammelschiene, (2·Z_1L + Z_0L)/3 hinter `LINE`), dann I_H = √(Σ I_F,m² + I_Rest²)
mit I_Rest = Oberschwingungsanteil der Versuche außerhalb der Prognoseordnungen und I_RES = √(I_1² + I_H²). Eine
Zeitreihe ergibt das Quantil `QUANTILE` der Zeitreihe von I_H und I_RES. Mit `PQ_FILES` erhalten die Ordnungen des Mit-
oder Gegensystems das Quantil der PQ-Messung (mal Faktor aus `PQ_FACTORS`); das Nullsystem (3, 9, 15 …) – es entsteht
im Erdschluss – und die geraden Ordnungen behalten die Vorfehlerspannung der Versuche (nicht skaliert). Eine PQ-Messung
kürzer als jede Dauer von `PQ_FACTORS` (lückenlose Werte) ist nicht gültig und liefert keine Spannungen.
''')),
        code('''FORECAST = FORECAST_TABLE = None
PQ = None
if PQ_FILES:                           ''' + t("# PQ measurement of the busbar: quantile per order × factor, or the 10-min values",
                                           "# PQ-Messung der Sammelschiene: Quantil je Ordnung × Faktor oder die 10-min-Werte") + '''
    files = [WORK_FOLDER / p for p in ([PQ_FILES] if isinstance(PQ_FILES, (str, Path)) else PQ_FILES)]
    PQ = pq.assess(pq.read(files, timezone=PQ_TIMEZONE), quantile=QUANTILE,
                   **(dict(factors=PQ_FACTORS) if PQ_FACTORS else dict(factor=PQ_SAFETY_FACTOR)))
    print(PQ.summary())
    for h in PQ.hints:
        print("ℹ", h)
    if not PQ.valid:
        print("''' + t("⚠ The PQ measurement is not valid for the assessment (gapless values shorter than every duration of PQ_FACTORS) – no voltages from it; VOLTAGES of section 1 stays.",
                       "⚠ Die PQ-Messung ist für die Bewertung nicht gültig (lückenlose Werte kürzer als jede Dauer von PQ_FACTORS) – keine Spannungen daraus; VOLTAGES aus Abschnitt 1 bleibt.") + '''")
    else:
        VOLTAGES, VOLTAGE_REFERENCE = (PQ.series() if PQ_SERIES else PQ.voltages()), PQ.reference
        ''' + t("# zero sequence (arises in the earth fault) and even orders: not scaled – the pre-fault voltage of the tests",
                "# Nullsystem (entsteht im Erdschluss) und gerade Ordnungen: nicht skaliert – die Vorfehlerspannung der Versuche") + '''
        KEPT = ({m: u for m, u in MODEL.test_voltages().items() if gf.formulas.harmonic_category(m) in ("zero", "even")}
                if VOLTAGE_REFERENCE == "LE" else {})
        for m, u in KEPT.items():
            if PQ_SERIES:
                for df in VOLTAGES.values():
                    df[m] = u
            else:
                VOLTAGES[m] = u
        if KEPT:
            print(i18n.format_text("''' + t("Zero sequence and even orders – pre-fault voltage of the tests (median, not scaled): {}",
                                             "Nullsystem und gerade Ordnungen – Vorfehlerspannung der Versuche (Median, nicht skaliert): {}") + '''",
                                   ", ".join(i18n.format_text("{}: {:.1f} V", m, u) for m, u in KEPT.items())))
        if not PQ_SERIES:
            print(i18n.format_text("''' + t("VOLTAGES from the PQ measurement (quantile × {:g}, reference {}): {}",
                                             "VOLTAGES aus der PQ-Messung (Quantil × {:g}, Bezug {}): {}") + '''", PQ.factor,
                                   PQ.reference, ", ".join(i18n.format_text("{}: {:.1f} V", m, u) for m, u in VOLTAGES.items()
                                                           if m not in KEPT)))
if VOLTAGES is None:
    print("''' + t("ℹ Forecast skipped – VOLTAGES is not set (section 1).",
                   "ℹ Prognose übersprungen – VOLTAGES ist nicht gesetzt (Abschnitt 1).") + '''")
elif not MODEL.calibrations:
    print("''' + t("ℹ Forecast skipped – the model contains no calibration (section 2).",
                   "ℹ Prognose übersprungen – das Modell enthält keine Kalibrierung (Abschnitt 2).") + '''")
else:
    U = pd.read_csv(VOLTAGES, **CSV_OPTIONS) if isinstance(VOLTAGES, (str, Path)) else VOLTAGES
    places = [(None, "''' + t("busbar", "Sammelschiene") + '''")] + ([(LINE, LINE.get("name") or "LINE")] if LINE else [])
    FORECASTS, tables = {}, []
    for line, place in places:
        f = FORECASTS[place] = MODEL.forecast(U, Z_F=Z_F, margin_A=MARGIN_A, how=HOW, two_source=TWO_SOURCE,
                                              reference=VOLTAGE_REFERENCE, fundamental_A=FUNDAMENTAL_A, line=line)
        series = len(f.currents) > 1
        tab = f.table(QUANTILE if series else None)
        tab.insert(0, "location", place)
        tables.append(tab)
        display(Markdown("**%s**" % place))
        show(tab)
        for h in f.hints:
            print("ℹ", h)
        value = tab.set_index("order")["I_forecast_A"]
        print(i18n.format_text("''' + t("Forecast{}: I_H = {:.2f} A, I_RES = {:.2f} A (fault impedance {:g} Ω)",
                                         "Prognose{}: I_H = {:.2f} A, I_RES = {:.2f} A (Fehlerimpedanz {:g} Ω)") + '''",
                               i18n.format_text(" (''' + t("quantile", "Quantil") + ''' {:g} ''' + t("of", "von") + ''' {} ''' + t("time steps", "Zeitschritten") + ''')",
                                                QUANTILE, len(f.currents)) if series else "",
                               value["I_H"], value["I_RES"], abs(complex(Z_F))))
        if LIMITS:
            for limit in LIMITS:
                print(i18n.format_text("I_RES = {:.2f} A {} {:g} A", value["I_RES"],
                                       "≤" if value["I_RES"] <= limit else ">", limit))
    FORECAST = FORECASTS[places[0][1]]                   ''' + t("# at the busbar", "# an der Sammelschiene") + '''
    FORECAST_TABLE = pd.concat(tables, ignore_index=True)
    if not MARGIN_A:
        print("''' + t("ℹ Without a margin – MARGIN_A is not set (section 1); section 3 shows the deviations of the model.",
                       "ℹ Ohne Zuschlag – MARGIN_A ist nicht gesetzt (Abschnitt 1); Abschnitt 3 zeigt die Abweichungen des Modells.") + '''")
    if not LIMITS:
        print("''' + t("ℹ No comparison with limits – LIMITS is not set (section 1).",
                       "ℹ Kein Vergleich mit Grenzwerten – LIMITS ist nicht gesetzt (Abschnitt 1).") + '''")'''),
        md(t("## 7 · Save the model and export the tables", "## 7 · Modell speichern und Tabellen exportieren")),
        code('''OUT = Path(fc.forecast_folder(WORK_FOLDER, NETWORK))
if MODEL.calibrations:
    path = OUT / (report.slug(NETWORK) + "_''' + t("network_model", "netzmodell") + '''.json")
    MODEL.save(str(path))
    TABLES = {"forecast_calibrations": MODEL.table(),
              "forecast_model": MODEL.source_table(how=HOW, two_source=TWO_SOURCE),
              "forecast_checks": pd.concat([CROSS_CHECKS, VERIFY], ignore_index=True),
              "forecast_faults": FAULT_CHECKS, "forecast": FORECAST_TABLE}
    paths = report.export_tables({k: v for k, v in TABLES.items() if v is not None and len(v)}, str(OUT),
                                 prefix=report.slug(NETWORK) + "_", formats=("csv", "md"))
    print("''' + t("model file:", "Modelldatei:") + '''", path)
    print("''' + t("%d table files in %s", "%d Tabellen-Dateien in %s") + '''" % (len(paths), OUT))
    ''' + t("# later: fc.NetworkModel.load(path) – add earth faults with add_fault, forecast with forecast",
            "# später: fc.NetworkModel.load(path) – Erdschlüsse mit add_fault ergänzen, Prognose mit forecast")),
    ]
    return _notebook(cells, lang, FORECAST_NAMES[lang][0])


def without_fault_notebook(lang: str, example: bool) -> nbf.NotebookNode:
    """The forecast notebook without an earth fault (optional part of groundfault): V0 to V3."""
    t = (lambda en, de: en if lang == "en" else de)
    if example:
        raw = t("campaigns/2026-03-10_Demo/raw/SUB", "01_Messkampagnen/2026-03-10_Demo/1_Rohdaten/UW")
        conf = t('''NETWORK = "Demo substation"     # name of the network (substation, busbar) – also the sub-folder of the forecast folder
DEMO    = True                  # create demo recordings of the undisturbed transformer node if missing

# ---------------------------------------------------------------- network data (demo values)
U_N    = 20e3                   # nominal voltage of the MV network in V
U_LE   = 20e3 / 3 ** 0.5        # line-to-earth voltage (fundamental) in V
I_C    = 700.0                  # capacitive earth-fault current in A (coil controller)
I_L    = 735.0                  # coil current in A (coil controller; None = I_C, tuned)
D      = 0.03                   # damping I_w/I_C (coil controller): series resistance d·X_C0 of the zero sequence in V2, V3
U_K    = 0.18                   # short-circuit voltage of the transformer (0.18 = 18 %)
S_RT   = 40e6                   # rated power of the transformer in VA
S_K    = 3.67e9                 # short-circuit power S″_k of the HV network in VA
C_1    = 65e-6                  # operating capacitance of the MV network per phase in F (cable lengths); None = Q_C·C_E
Q_C    = None                   # C_1/C_E when C_1 is None: cable networks about 1, mixed networks somewhat more
R_X_UP = 0.03                   # R/X of the upstream impedance (transformer and HV network) at the orders – your assumption
R_X_HV = 0.1                    # R/X of the HV network (corrected instrument of V3) – your assumption''', '''NETWORK = "Demo-UW"             # Name des Netzes (Umspannwerk, Sammelschiene) – auch der Unterordner des Prognoseordners
DEMO    = True                  # Demo-Aufzeichnungen des ungestörten Trafoknotens anlegen, falls sie fehlen

# ---------------------------------------------------------------- Netzdaten (Demo-Werte)
U_N    = 20e3                   # Nennspannung des MS-Netzes in V
U_LE   = 20e3 / 3 ** 0.5        # Leiter-Erde-Spannung (Grundschwingung) in V
I_C    = 700.0                  # kapazitiver Erdschlussstrom in A (Spulenregler)
I_L    = 735.0                  # Spulenstrom in A (Spulenregler; None = I_C, abgestimmt)
D      = 0.03                   # Dämpfung I_w/I_C (Spulenregler): Reihenwiderstand d·X_C0 des Nullsystems in V2, V3
U_K    = 0.18                   # Kurzschlussspannung des Trafos (0.18 = 18 %)
S_RT   = 40e6                   # Bemessungsleistung des Trafos in VA
S_K    = 3.67e9                 # Kurzschlussleistung S″_k des HS-Netzes in VA
C_1    = 65e-6                  # Betriebskapazität des MS-Netzes je Leiter in F (Kabellängen); None = Q_C·C_E
Q_C    = None                   # C_1/C_E, wenn C_1 fehlt: Kabelnetze etwa 1, Mischnetze etwas mehr
R_X_UP = 0.03                   # R/X der Vorimpedanz (Trafo und HS-Netz) bei den Ordnungen – Ihre Annahme
R_X_HV = 0.1                    # R/X des HS-Netzes (korrigiertes Instrument von V3) – Ihre Annahme''')
        conf += t('''

# ---------------------------------------------------------------- harmonic voltages and fault impedances
ORDERS   = (5, 7)               # orders of the positive and negative sequence (not 3, 9, 15 …: their source arises in the fault)
VOLTAGES = {5: 250.0, 7: 130.0} # demo values: 95 % quantiles in V (line-to-earth), e.g. of a power-quality measurement
Z_F      = (0.0, 2.5, 5.0)      # fault impedances in Ω
PQ_FILES    = None              # export(s) of a PQ instrument at the busbar → VOLTAGES (quantile × factor); relative to the work folder or absolute
PQ_TIMEZONE = None              # time zone of the instrument clock, e.g. "Europe/Berlin" (None = time stamps as exported)
PQ_QUANTILE = 0.95              # quantile of the 10-min values

# ---------------------------------------------------------------- assumptions for V1 and V2 (demo values)
G_MAX   = 0.15                  # V1: upper limit of the damping of the MV network in S (None = V1 not computed)
G       = 0.06                  # V2: assumed damping in S (None = no V2 estimate)
G_RANGE = (0.02, 0.15)          # V2: range of the damping in S for the envelope (None = no envelope)

# ---------------------------------------------------------------- V3: undisturbed recordings of the transformer node
RECORDINGS = "''' + raw + '''/TRU_*.cfg"   # demo: pattern relative to the work folder, or a list of .cfg paths
SIGN       = None               # polarity of the transformer currents: +1 as measured, −1 reversed (None = from all recordings)
CT_ANGLE   = None               # angle error of the transformer current transformers in degrees: one value or {order: angle}
REFERENCE  = dict(recording="''' + raw + '''/TRU_02h_10_000kHz.cfg", channel="I1", reference="IRef")
# reference clamp parallel to a transformer current (demo: in the first recording) – gives the angle error per order;
# None = CT_ANGLE''', '''

# ---------------------------------------------------------------- Oberschwingungsspannungen und Fehlerimpedanzen
ORDERS   = (5, 7)               # Ordnungen des Mit- und Gegensystems (nicht 3, 9, 15 …: deren Quelle entsteht im Fehler)
VOLTAGES = {5: 250.0, 7: 130.0} # Demo-Werte: 95-%-Quantile in V (Leiter-Erde), z. B. einer Netzqualitätsmessung
Z_F      = (0.0, 2.5, 5.0)      # Fehlerimpedanzen in Ω
PQ_FILES    = None              # Export(e) eines PQ-Messgeräts an der Sammelschiene → VOLTAGES (Quantil × Faktor); relativ zum Arbeitsordner oder absolut
PQ_TIMEZONE = None              # Zeitzone der Geräteuhr, z. B. "Europe/Berlin" (None = Zeitstempel wie exportiert)
PQ_QUANTILE = 0.95              # Quantil der 10-min-Werte

# ---------------------------------------------------------------- Annahmen für V1 und V2 (Demo-Werte)
G_MAX   = 0.15                  # V1: Obergrenze der Dämpfung des MS-Netzes in S (None = V1 nicht gerechnet)
G       = 0.06                  # V2: angenommene Dämpfung in S (None = keine Schätzung V2)
G_RANGE = (0.02, 0.15)          # V2: Bereich der Dämpfung in S für die Hüllkurve (None = keine Hüllkurve)

# ---------------------------------------------------------------- V3: ungestörte Aufzeichnungen des Trafoknotens
RECORDINGS = "''' + raw + '''/TRU_*.cfg"   # Demo: Muster relativ zum Arbeitsordner oder eine Liste von .cfg-Pfaden
SIGN       = None               # Polarität der Trafoströme: +1 wie gemessen, −1 umgekehrt (None = aus allen Aufzeichnungen)
CT_ANGLE   = None               # Winkelfehler der Trafostromwandler in Grad: ein Wert oder {Ordnung: Winkel}
REFERENCE  = dict(recording="''' + raw + '''/TRU_02h_10_000kHz.cfg", channel="I1", reference="IRef")
# Referenzzange parallel zu einem Trafostrom (Demo: in der ersten Aufzeichnung) – gibt den Winkelfehler je Ordnung;
# None = CT_ANGLE''')
    else:
        conf = t('''NETWORK = "<substation>"        # name of the network (substation, busbar) – also the sub-folder of the forecast folder
DEMO    = False

# ---------------------------------------------------------------- network data
U_N    = None                   # nominal voltage of the MV network in V
U_LE   = None                   # line-to-earth voltage (fundamental) in V
I_C    = None                   # capacitive earth-fault current in A (coil controller)
I_L    = None                   # coil current in A (coil controller; None = I_C, tuned)
D      = None                   # damping I_w/I_C (coil controller): series resistance d·X_C0 of the zero sequence in V2, V3
U_K    = None                   # short-circuit voltage of the transformer (e.g. 0.14 for 14 %)
S_RT   = None                   # rated power of the transformer in VA
S_K    = None                   # short-circuit power S″_k of the HV network in VA
C_1    = None                   # operating capacitance of the MV network per phase in F (cable lengths); None = Q_C·C_E
Q_C    = None                   # C_1/C_E when C_1 is None: cable networks about 1, mixed networks somewhat more
R_X_UP = None                   # R/X of the upstream impedance (transformer and HV network) at the orders – your assumption
R_X_HV = None                   # R/X of the HV network (corrected instrument of V3) – your assumption

# ---------------------------------------------------------------- harmonic voltages and fault impedances
ORDERS   = (5, 7)               # orders of the positive and negative sequence (not 3, 9, 15 …: their source arises in the fault)
VOLTAGES = None                 # harmonic voltages per order in V, e.g. {5: U_5, 7: U_7} (None = no forecast)
Z_F      = (0.0,)               # fault impedances in Ω
PQ_FILES    = None              # export(s) of a PQ instrument at the busbar → VOLTAGES (quantile × factor); relative to the work folder or absolute
PQ_TIMEZONE = None              # time zone of the instrument clock, e.g. "Europe/Berlin" (None = time stamps as exported)
PQ_QUANTILE = 0.95              # quantile of the 10-min values

# ---------------------------------------------------------------- assumptions for V1 and V2
G_MAX   = None                  # V1: upper limit of the damping of the MV network in S (None = V1 not computed)
G       = None                  # V2: assumed damping in S (None = no V2 estimate)
G_RANGE = None                  # V2: range of the damping in S for the envelope, (G_min, G_max) (None = no envelope)

# ---------------------------------------------------------------- V3: undisturbed recordings of the transformer node
RECORDINGS = []                 # pattern relative to the work folder (e.g. "campaigns/<campaign>/raw/<folder>/*.cfg") or a list of .cfg paths
SIGN       = None               # polarity of the transformer currents: +1 as measured, −1 reversed (None = from all recordings)
CT_ANGLE   = None               # angle error of the transformer current transformers in degrees: one value or {order: angle}
REFERENCE  = None               # reference clamp: dict(recording=…, channel=<transformer current>, reference=<clamp>) – gives
                                # the angle error per order; None = CT_ANGLE''', '''NETWORK = "<UW>"                # Name des Netzes (Umspannwerk, Sammelschiene) – auch der Unterordner des Prognoseordners
DEMO    = False

# ---------------------------------------------------------------- Netzdaten
U_N    = None                   # Nennspannung des MS-Netzes in V
U_LE   = None                   # Leiter-Erde-Spannung (Grundschwingung) in V
I_C    = None                   # kapazitiver Erdschlussstrom in A (Spulenregler)
I_L    = None                   # Spulenstrom in A (Spulenregler; None = I_C, abgestimmt)
D      = None                   # Dämpfung I_w/I_C (Spulenregler): Reihenwiderstand d·X_C0 des Nullsystems in V2, V3
U_K    = None                   # Kurzschlussspannung des Trafos (z. B. 0.14 für 14 %)
S_RT   = None                   # Bemessungsleistung des Trafos in VA
S_K    = None                   # Kurzschlussleistung S″_k des HS-Netzes in VA
C_1    = None                   # Betriebskapazität des MS-Netzes je Leiter in F (Kabellängen); None = Q_C·C_E
Q_C    = None                   # C_1/C_E, wenn C_1 fehlt: Kabelnetze etwa 1, Mischnetze etwas mehr
R_X_UP = None                   # R/X der Vorimpedanz (Trafo und HS-Netz) bei den Ordnungen – Ihre Annahme
R_X_HV = None                   # R/X des HS-Netzes (korrigiertes Instrument von V3) – Ihre Annahme

# ---------------------------------------------------------------- Oberschwingungsspannungen und Fehlerimpedanzen
ORDERS   = (5, 7)               # Ordnungen des Mit- und Gegensystems (nicht 3, 9, 15 …: deren Quelle entsteht im Fehler)
VOLTAGES = None                 # Oberschwingungsspannungen je Ordnung in V, z. B. {5: U_5, 7: U_7} (None = keine Prognose)
Z_F      = (0.0,)               # Fehlerimpedanzen in Ω
PQ_FILES    = None              # Export(e) eines PQ-Messgeräts an der Sammelschiene → VOLTAGES (Quantil × Faktor); relativ zum Arbeitsordner oder absolut
PQ_TIMEZONE = None              # Zeitzone der Geräteuhr, z. B. "Europe/Berlin" (None = Zeitstempel wie exportiert)
PQ_QUANTILE = 0.95              # Quantil der 10-min-Werte

# ---------------------------------------------------------------- Annahmen für V1 und V2
G_MAX   = None                  # V1: Obergrenze der Dämpfung des MS-Netzes in S (None = V1 nicht gerechnet)
G       = None                  # V2: angenommene Dämpfung in S (None = keine Schätzung V2)
G_RANGE = None                  # V2: Bereich der Dämpfung in S für die Hüllkurve, (G_min, G_max) (None = keine Hüllkurve)

# ---------------------------------------------------------------- V3: ungestörte Aufzeichnungen des Trafoknotens
RECORDINGS = []                 # Muster relativ zum Arbeitsordner (z. B. "01_Messkampagnen/<Kampagne>/1_Rohdaten/<Ordner>/*.cfg") oder Liste von .cfg-Pfaden
SIGN       = None               # Polarität der Trafoströme: +1 wie gemessen, −1 umgekehrt (None = aus allen Aufzeichnungen)
CT_ANGLE   = None               # Winkelfehler der Trafostromwandler in Grad: ein Wert oder {Ordnung: Winkel}
REFERENCE  = None               # Referenzzange: dict(recording=…, channel=<Trafostrom>, reference=<Zange>) – gibt den
                                # Winkelfehler je Ordnung; None = CT_ANGLE''')
    conf += t('''

# ---------------------------------------------------------------- limits – defined by you
# groundfault contains no limits. Not set (the values below), the notebook lists the values without assessing them.
MIN_HV_SHARE  = None            # V3: smallest share of the HV-driven variation of a reliable recording (None = not assessed)
V0_RATIO      = None            # V0: below m/m_r < V0_RATIO the column V0_rule_A doubles V0 (None = no such column)
FUNDAMENTAL_A = None            # fundamental residual current in A for I_RES (None = I_H only)
LIMITS        = ()              # limits of the residual current in A, e.g. (I_1, I_2)
PQ_SAFETY_FACTOR = 1.0          # factor on the quantile of the PQ measurement (1.0 = none)
PQ_FACTORS    = None            # factor on the quantile by the duration of the PQ measurement {minimum days: factor} (None = PQ_SAFETY_FACTOR)''', '''

# ---------------------------------------------------------------- Grenzwerte – selbst festlegen
# groundfault enthält keine Grenzwerte. Nicht gesetzt (die Werte unten), listet das Notebook die Werte ohne Bewertung.
MIN_HV_SHARE  = None            # V3: kleinster Anteil der HS-getriebenen Schwankung einer verlässlichen Aufzeichnung (None = ohne Bewertung)
V0_RATIO      = None            # V0: unter m/m_r < V0_RATIO verdoppelt die Spalte V0_Regel_A den Wert von V0 (None = keine solche Spalte)
FUNDAMENTAL_A = None            # Grundschwingungsreststrom in A für I_RES (None = nur I_H)
LIMITS        = ()              # Grenzwerte des Reststroms in A, z. B. (I_1, I_2)
PQ_SAFETY_FACTOR = 1.0          # Faktor auf das Quantil der PQ-Messung (1.0 = keiner)
PQ_FACTORS    = None            # Faktor auf das Quantil nach Dauer der PQ-Messung {Mindesttage: Faktor} (None = PQ_SAFETY_FACTOR)''')
    cells = [
        md(t('''
# Forecast without an earth fault – estimates V0 to V3

An **optional part** of groundfault: the harmonic fault current at a busbar from network data and – with a recorder at
the transformer – from undisturbed recordings of the transformer node, **without a staged fault test**. Four methods
side by side:

| Method | Data | Result |
|---|---|---|
| **V0** classical estimate | U_m, I_C, coil | an upper estimate above about the resonance of the busbar, none below it |
| **V1** resonance bound | as V0, an upper limit G_max of the damping | the order of magnitude at the resonance |
| **V2** network data | as V0, damping d of the coil controller, rating plate, S″_k, C_1, an assumed damping G of the MV network | an estimate with G and an envelope over a range of G |
| **V3** transformer node | as V2, undisturbed recordings of HV voltages, MV voltages and transformer currents in one device | an estimate with the damping of the MV network measured |

The orders of the zero sequence (3, 9, 15 …) have a source that arises only in the fault: without an earth fault there
is no forecast for them. With staged fault tests or recorded earth faults use `network_model_forecast.ipynb` (V4 to
V7). Reference copy: `templates/forecast_without_fault_DEFAULT.ipynb`. Methods: online documentation, *Forecast*.

1. **Configuration** – network data, harmonic voltages, assumptions, recordings of the transformer node, limits.
2. **Network data and resonance** – upstream impedance, operating capacitance, resonance order m_r and m/m_r.
3. **V3** – the MV network from each undisturbed recording with its checks, and the pooled estimate of the reliable ones.
4. **V0 to V3 side by side** per order and fault impedance, and I_H.
5. **Export** of the tables to the forecast folder of the work folder.
''', '''
# Prognose ohne Erdschluss – Abschätzungen V0 bis V3

Ein **optionaler Teil** von groundfault: der Oberschwingungs-Fehlerstrom an einer Sammelschiene aus Netzdaten und – mit
einem Messgerät am Trafo – aus ungestörten Aufzeichnungen des Trafoknotens, **ohne Erdschlussversuch**. Vier Verfahren
nebeneinander:

| Verfahren | Daten | Ergebnis |
|---|---|---|
| **V0** klassische Abschätzung | U_m, I_C, Spule | oberhalb etwa der Resonanz der Sammelschiene eine obere Abschätzung, darunter nicht |
| **V1** Resonanzschranke | wie V0, eine Obergrenze G_max der Dämpfung | die Größenordnung in der Resonanz |
| **V2** Netzdaten | wie V0, Dämpfung d des Spulenreglers, Typschild, S″_k, C_1, eine angenommene Dämpfung G des MS-Netzes | eine Schätzung mit G und eine Hüllkurve über einen Bereich von G |
| **V3** Trafoknoten | wie V2, ungestörte Aufzeichnungen von HS-Spannungen, MS-Spannungen und Trafoströmen in einem Gerät | eine Schätzung mit gemessener Dämpfung des MS-Netzes |

Die Ordnungen des Nullsystems (3, 9, 15 …) haben eine Quelle, die erst im Fehler entsteht: Ohne Erdschluss gibt es für
sie keine Prognose. Mit Erdschlussversuchen oder aufgezeichneten Erdschlüssen `Netzmodell_Prognose.ipynb` verwenden
(V4 bis V7). Ausgangsfassung: `Vorlagen/Prognose_ohne_Erdschluss_DEFAULT.ipynb`. Verfahren: Online-Dokumentation,
*Forecast*.

1. **Konfiguration** – Netzdaten, Oberschwingungsspannungen, Annahmen, Aufzeichnungen des Trafoknotens, Grenzwerte.
2. **Netzdaten und Resonanz** – Vorimpedanz, Betriebskapazität, Resonanzordnung m_r und m/m_r.
3. **V3** – das MS-Netz aus jeder ungestörten Aufzeichnung mit ihren Prüfwerten und die zusammengefasste Schätzung der
   verlässlichen.
4. **V0 bis V3 nebeneinander** je Ordnung und Fehlerimpedanz, und I_H.
5. **Export** der Tabellen in den Prognoseordner des Arbeitsordners.
''')),
        code(setup(lang).replace("import sys\n", "import datetime\nimport sys\n", 1)
             .replace("from IPython.display import Markdown, display\n",
                      "from IPython.display import Markdown, display\nfrom groundfault import forecast as fc\n", 1)),
        md(t("## 1 · Configuration", "## 1 · Konfiguration")),
        code(conf),
        md(t('''
## 2 · Network data and resonance

From the rating plate and the short-circuit power: X_T = u_k·U_n²/S_rT, X_Q = 1.1·U_n²/S″_k, the upstream impedance
Z_up,m = m·(X_T + X_Q)·(R/X + j) and the impedance of the HV network Z_HV,m = m·X_Q·(R/X + j) (for the corrected
instrument of V3). The earth capacitance C_E = I_C/(3·ω₁·U_LE) and the operating capacitance C_1 give the parallel
resonance of the busbar, m_r = √(X_C1/X_up) with X_C1 = 1/(ω₁·C_1). Above about m_r the positive and negative
sequence are capacitive in the fault loop and the classical estimate V0 lies above the current; below m_r they are
inductive, partly cancel the capacitive zero sequence, and the current can exceed V0 severalfold.
''', '''
## 2 · Netzdaten und Resonanz

Aus Typschild und Kurzschlussleistung: X_T = u_k·U_n²/S_rT, X_Q = 1,1·U_n²/S″_k, die Vorimpedanz
Z_vor,m = m·(X_T + X_Q)·(R/X + j) und die Impedanz des HS-Netzes Z_HS,m = m·X_Q·(R/X + j) (für das korrigierte
Instrument von V3). Die Erdkapazität C_E = I_C/(3·ω₁·U_LE) und die Betriebskapazität C_1 ergeben die Parallelresonanz
der Sammelschiene, m_r = √(X_C1/X_vor) mit X_C1 = 1/(ω₁·C_1). Oberhalb etwa m_r sind Mit- und Gegensystem in der
Fehlerschleife kapazitiv, und die klassische Abschätzung V0 liegt über dem Strom; unterhalb m_r sind sie induktiv,
heben das kapazitive Nullsystem teilweise auf, und der Strom kann V0 um ein Mehrfaches übersteigen.
''')),
        code('''X_T = fc.transformer_reactance(U_K, S_RT, U_N) if None not in (U_K, S_RT, U_N) else None
X_Q = fc.hv_network_reactance(S_K, U_N) if None not in (S_K, U_N) else None
X_UP = X_T + X_Q if None not in (X_T, X_Q) else None
C_E = fc.earth_capacitance(I_C, U_LE) if None not in (I_C, U_LE) else None
C1 = C_1 if C_1 is not None else (Q_C * C_E if None not in (Q_C, C_E) else None)
M_R = fc.resonance_order(X_UP, C1) if X_UP and C1 else None
Z_UP = {m: fc.at_order(X_UP, m, R_X_UP) for m in ORDERS} if None not in (X_UP, R_X_UP) else None
Z_HV = {m: fc.at_order(X_Q, m, R_X_HV) for m in ORDERS} if None not in (X_Q, R_X_HV) else None
NETWORK_DATA = pd.DataFrame([dict(X_T_Ohm=X_T, X_Q_Ohm=X_Q, X_up_Ohm=X_UP, C_E_uF=C_E * 1e6 if C_E else None,
                                  C_1_uF=C1 * 1e6 if C1 else None, m_r=M_R)])
show(NETWORK_DATA)
if M_R:
    show(pd.DataFrame([dict(order=m, f_Hz=50.0 * m, m_over_mr=m / M_R) for m in ORDERS]))
NOT_SET = [n for n, v in (("U_N", U_N), ("U_LE", U_LE), ("I_C", I_C), ("U_K", U_K), ("S_RT", S_RT), ("S_K", S_K),
                          ("R_X_UP", R_X_UP), ("R_X_HV", R_X_HV)) if v is None] + ([] if C1 else ["C_1 ''' + t("or", "oder") + ''' Q_C"])
if NOT_SET:
    print("''' + t("ℹ Not set (section 1): ", "ℹ Nicht gesetzt (Abschnitt 1): ") + '''" + ", ".join(NOT_SET) + "''' +
             t(" – the methods that need them are left out.", " – die Verfahren, die sie brauchen, entfallen.") + '''")'''),
        md(t('''
## 3 · V3 – the MV network from undisturbed recordings

In undisturbed operation the harmonic sources of the HV and of the MV network vary all the time. A variation driven
from the HV side changes busbar voltage and transformer current by ΔU = Z_MV·ΔI, one driven from the MV side by
ΔU = −Z_up·ΔI. The HV voltage, corrected by the drop over the HV network (E = U_HV + Z_HV·I_T), follows only the HV
sources and serves as **instrument**: per 200-ms window the deviations from the mean give
Z_MV = ΣΔU·ΔE*/ΣΔI·ΔE* in the natural sequence of each order. Before that the angle error of the transformer current
transformers is corrected (reference clamp `REFERENCE` or `CT_ANGLE`).

Checks per recording: correlation between current and instrument (`corr_I_hv`), a capacitive result with a positive
real part, and the **share of the HV-driven variation** in the variance of the busbar voltage (`hv_share`). The share
is what decides: where the MV side drives most of the variation the estimate drifts towards −Z_up, and neither the
correlation nor the angle shows it. The share changes over the day (e.g. higher at night), so record at several times.
The recordings that pass are pooled – the estimate for the forecast.
''', '''
## 3 · V3 – das MS-Netz aus ungestörten Aufzeichnungen

Im ungestörten Betrieb schwanken die Oberschwingungsquellen des HS- und des MS-Netzes ständig. Eine vom HS-Netz
getriebene Schwankung ändert Sammelschienenspannung und Trafostrom um ΔU = Z_MS·ΔI, eine vom MS-Netz getriebene um
ΔU = −Z_vor·ΔI. Die HS-Spannung, korrigiert um den Spannungsfall über dem HS-Netz (E = U_HS + Z_HS·I_T), folgt nur den
HS-Quellen und dient als **Instrument**: Je 200-ms-Fenster ergeben die Abweichungen vom Mittel
Z_MS = ΣΔU·ΔE*/ΣΔI·ΔE* im natürlichen Drehsystem jeder Ordnung. Vorher wird der Winkelfehler der Trafostromwandler
korrigiert (Referenzzange `REFERENCE` oder `CT_ANGLE`).

Prüfwerte je Aufzeichnung: Korrelation zwischen Strom und Instrument (`corr_I_hv`), ein kapazitives Ergebnis mit
positivem Wirkanteil und der **Anteil der HS-getriebenen Schwankung** an der Varianz der Sammelschienenspannung
(`hv_share`). Der Anteil entscheidet: Treibt das MS-Netz den größten Teil der Schwankung, rückt die Schätzung zu
−Z_vor, und weder die Korrelation noch der Winkel zeigen das. Der Anteil ändert sich über den Tag (z. B. nachts höher),
deshalb zu mehreren Zeiten aufzeichnen. Die bestandenen Aufzeichnungen werden zusammengefasst – die Schätzung für die
Prognose.
''')),
        code('''def path_in_work_folder(p):
    p = Path(p)
    return p if p.is_absolute() else WORK_FOLDER / p


if DEMO:                         ''' + t("# demo: a measuring day – six recordings of one minute, the share of the HV side falls towards noon",
                                        "# Demo: ein Messtag – sechs Aufzeichnungen von einer Minute, der HS-Anteil fällt zum Mittag") + '''
    folder = path_in_work_folder(Path(RECORDINGS).parent)
    folder.mkdir(parents=True, exist_ok=True)
    z_mv = {m: 1 / complex(g, m * 2 * np.pi * 50.0 * 65e-6) for m, g in ((5, 0.07), (7, 0.09))}   ''' + t("# the truth of the demo", "# die Wahrheit der Demo") + '''
    for k, (hour, hv, mv) in enumerate(((2, 0.10, 0.05), (6, 0.08, 0.07), (10, 0.04, 0.10), (12, 0.02, 0.13),
                                        (16, 0.05, 0.09), (22, 0.09, 0.06))):
        cfg = folder / ("TRU_%02dh_10_000kHz.cfg" % hour)
        if not cfg.exists():
            demo.make_undisturbed_transformer_recording(str(cfg), duration=60.0, Z_mv=z_mv, hv_fluctuation=hv,
                                                        mv_fluctuation=mv, ct_angle_deg={5: 2.0, 7: 2.8},
                                                        reference_clamp=(k == 0), seed=30 + k,
                                                        start=datetime.datetime(2026, 3, 10, hour, 0))
FILES = (sorted(WORK_FOLDER.glob(RECORDINGS)) if isinstance(RECORDINGS, str)
         else [path_in_work_folder(p) for p in RECORDINGS])
CT_TABLE = V3_TABLE = V3_POOLED = None
Z_MV = {}
CT = CT_ANGLE
if REFERENCE:
    CT_TABLE = transformer.ct_angle_from_reference(str(path_in_work_folder(REFERENCE["recording"])),
                                                   REFERENCE["channel"], REFERENCE["reference"], orders=ORDERS)
    display(Markdown("''' + t("**Angle error of the current transformers** against the reference clamp",
                              "**Winkelfehler der Stromwandler** gegen die Referenzzange") + '''"))
    show(CT_TABLE)
    CT = CT_TABLE
if not FILES:
    print("''' + t("ℹ V3 skipped – no recordings (RECORDINGS, section 1).",
                   "ℹ V3 übersprungen – keine Aufzeichnungen (RECORDINGS, Abschnitt 1).") + '''")
elif Z_UP is None or Z_HV is None:
    print("''' + t("ℹ V3 skipped – the upstream impedance needs U_N, U_K, S_RT, S_K, R_X_UP and R_X_HV (section 1).",
                   "ℹ V3 übersprungen – die Vorimpedanz braucht U_N, U_K, S_RT, S_K, R_X_UP und R_X_HV (Abschnitt 1).") + '''")
else:
    V3_TABLE, V3_POOLED = transformer.mv_network_series([str(f) for f in FILES], ORDERS, sign=SIGN, Z_hv=Z_HV,
                                                        Z_up=Z_UP, ct_angle_deg=CT, min_hv_share=MIN_HV_SHARE)
    cols = ["recording", "start", "order", "sequence", "Z_Ohm", "Z_angle_deg", "G_S", "B_S", "corr_I_hv", "hv_share",
            "reliable"]
    display(Markdown("''' + t("**Per recording** (natural sequence; polarity of the currents: %+g)",
                              "**Je Aufzeichnung** (natürliches Drehsystem; Polarität der Ströme: %+g)") + '''" % V3_TABLE.attrs["sign"]))
    show(V3_TABLE[cols])
    for name, hints in V3_TABLE.attrs["hints"].items():
        for h in hints:
            print("ℹ %s: %s" % (name, h))
    display(Markdown("''' + t("**Pooled estimate of the reliable recordings**",
                              "**Zusammengefasste Schätzung der verlässlichen Aufzeichnungen**") + '''"))
    show(V3_POOLED[["order", "sequence", "recordings", "Z_Ohm", "Z_angle_deg", "Z_low_Ohm", "Z_high_Ohm", "G_S", "B_S",
                    "hv_share", "names"]])
    Z_MV = {int(r.order): complex(r.R_Ohm, r.X_Ohm) for r in V3_POOLED.itertuples() if r.recordings}
    if MIN_HV_SHARE is None:
        print("''' + t("ℹ The share of the HV-driven variation (hv_share) is listed, not assessed – MIN_HV_SHARE is not "
                       "set (section 1). Recordings in which the MV side drives most of the variation are then pooled too.",
                       "ℹ Der Anteil der HS-getriebenen Schwankung (hv_share) ist gelistet, nicht bewertet – MIN_HV_SHARE "
                       "ist nicht gesetzt (Abschnitt 1). Aufzeichnungen, in denen das MS-Netz den größten Teil der "
                       "Schwankung treibt, werden dann mit zusammengefasst.") + '''")'''),
        md(t('''
## 4 · V0 to V3 side by side

Per order and fault impedance: **V0** = 3·U_m/|Z_0,m + 3·Z_F| with the capacitive Z_0 from I_C and the coil;
**V1** = 3·U_m/|2/G_max + Z_0,m + 3·Z_F|; **V2** the full fault loop 3·U_m/|Z_0 + Z_1 + Z_2 + 3·Z_F| with
Z_1 = Z_2 = (1/Z_up + G + j·m·ω₁·C_1)⁻¹ and Z_0 with the series resistance d·X_C0 – the estimate with `G` and the
envelope (largest current) over `G_RANGE`, there without damping of the zero sequence; **V3** the same loop with the
MV network measured (section 3). With `V0_RATIO` the column `V0_rule_A` doubles V0 below m/m_r < `V0_RATIO`. The rows
`I_H` are √Σ I_m² over the orders of the table.
''', '''
## 4 · V0 bis V3 nebeneinander

Je Ordnung und Fehlerimpedanz: **V0** = 3·U_m/|Z_0,m + 3·Z_F| mit dem kapazitiven Z_0 aus I_C und der Spule;
**V1** = 3·U_m/|2/G_max + Z_0,m + 3·Z_F|; **V2** die volle Fehlerschleife 3·U_m/|Z_0 + Z_1 + Z_2 + 3·Z_F| mit
Z_1 = Z_2 = (1/Z_vor + G + j·m·ω₁·C_1)⁻¹ und Z_0 mit dem Reihenwiderstand d·X_C0 – die Schätzung mit `G` und die
Hüllkurve (größter Strom) über `G_RANGE`, dort ohne Dämpfung des Nullsystems; **V3** dieselbe Schleife mit dem
gemessenen MS-Netz (Abschnitt 3). Mit `V0_RATIO` verdoppelt die Spalte `V0_Regel_A` den Wert von V0 unterhalb
m/m_r < `V0_RATIO`. Die Zeilen `I_H` sind √Σ I_m² über die Ordnungen der Tabelle.
''')),
        code('''COMPARISON = None
PQ = None
if PQ_FILES:                           ''' + t("# PQ measurement of the busbar: quantile per order (line-to-earth, largest phase) × factor",
                                           "# PQ-Messung der Sammelschiene: Quantil je Ordnung (Leiter-Erde, größter Leiter) × Faktor") + '''
    files = [WORK_FOLDER / p for p in ([PQ_FILES] if isinstance(PQ_FILES, (str, Path)) else PQ_FILES)]
    PQ = pq.assess(pq.read(files, timezone=PQ_TIMEZONE), quantile=PQ_QUANTILE,
                   **(dict(factors=PQ_FACTORS) if PQ_FACTORS else dict(factor=PQ_SAFETY_FACTOR)))
    print(PQ.summary())
    for h in PQ.hints:
        print("ℹ", h)
    if PQ.valid:
        VOLTAGES = PQ.voltages() if PQ.reference == "LE" else {m: u / 3 ** 0.5 for m, u in PQ.voltages().items() if m % 3}
        print(i18n.format_text("''' + t("VOLTAGES from the PQ measurement (quantile × {:g}, line-to-earth): {}",
                                         "VOLTAGES aus der PQ-Messung (Quantil × {:g}, Leiter-Erde): {}") + '''", PQ.factor,
                               ", ".join(i18n.format_text("{}: {:.1f} V", m, VOLTAGES[m]) for m in ORDERS if m in VOLTAGES)))
    else:
        print("''' + t("⚠ The PQ measurement is not valid for the assessment (gapless values shorter than every duration of PQ_FACTORS) – no voltages from it; VOLTAGES of section 1 stays.",
                       "⚠ Die PQ-Messung ist für die Bewertung nicht gültig (lückenlose Werte kürzer als jede Dauer von PQ_FACTORS) – keine Spannungen daraus; VOLTAGES aus Abschnitt 1 bleibt.") + '''")
if VOLTAGES is None:
    print("''' + t("ℹ No forecast – VOLTAGES is not set (section 1).",
                   "ℹ Keine Prognose – VOLTAGES ist nicht gesetzt (Abschnitt 1).") + '''")
elif None in (U_LE, I_C) or Z_UP is None:
    print("''' + t("ℹ No forecast – network data missing (section 2).",
                   "ℹ Keine Prognose – Netzdaten fehlen (Abschnitt 2).") + '''")
else:
    COMPARISON = fc.estimates_without_fault({m: VOLTAGES[m] for m in ORDERS if m in VOLTAGES}, I_C, U_LE, Z_UP,
                                            Z_F=tuple(Z_F), I_L=I_L, d=D or 0.0, C_1=C1, m_r=M_R, G_max=G_MAX,
                                            G=G, G_range=G_RANGE, Z_mv=Z_MV or None)
    if V0_RATIO is not None and M_R:
        rule = [v * (2.0 if isinstance(o, (int, np.integer)) and o / M_R < V0_RATIO else 1.0)
                for o, v in zip(COMPARISON.order, COMPARISON.V0_A)]
        COMPARISON.insert(list(COMPARISON.columns).index("V0_A") + 1, "V0_rule_A", rule)
        for zf in COMPARISON.Z_F_Ohm.unique():      ''' + t("# I_H of the rule: √Σ over the orders",
                                                                "# I_H der Regel: √Σ über die Ordnungen") + '''
            part = (COMPARISON.Z_F_Ohm == zf) & (COMPARISON.order != "I_H")
            COMPARISON.loc[(COMPARISON.Z_F_Ohm == zf) & (COMPARISON.order == "I_H"), "V0_rule_A"] = \\
                float(np.sqrt((COMPARISON.loc[part, "V0_rule_A"] ** 2).sum()))
    show(COMPARISON)
    names = {"V0_A": "V0", "V0_rule_A": "''' + t("V0 rule", "V0 Regel") + '''", "V1_A": "V1", "V2_A": "V2",
             "V2_envelope_A": "''' + t("V2 envelope", "V2 Hüllkurve") + '''", "V3_A": "V3"}
    methods = [c for c in names if c in COMPARISON.columns]
    for zf in COMPARISON.Z_F_Ohm.unique():
        h = COMPARISON[(COMPARISON.Z_F_Ohm == zf) & (COMPARISON.order == "I_H")].iloc[0]
        text = ", ".join(i18n.format_text("{} {:.1f} A", names[c], h[c]) for c in methods)
        if FUNDAMENTAL_A is not None:
            text += " · I_RES: " + ", ".join(i18n.format_text("{} {:.1f} A", names[c], float(np.hypot(FUNDAMENTAL_A, h[c])))
                                             for c in methods)
        print(i18n.format_text("Z_F = {:g} Ω – I_H: ", zf) + text)
        if LIMITS and FUNDAMENTAL_A is not None:
            for limit in LIMITS:
                over = [names[c] for c in methods if np.hypot(FUNDAMENTAL_A, h[c]) > limit]
                print(i18n.format_text("   I_RES ''' + t("above", "über") + ''' {:g} A: ", limit) + (", ".join(over) or "–"))
    if FUNDAMENTAL_A is None:
        print("''' + t("ℹ I_RES not computed – FUNDAMENTAL_A is not set (section 1).",
                       "ℹ I_RES nicht gerechnet – FUNDAMENTAL_A ist nicht gesetzt (Abschnitt 1).") + '''")'''),
        md(t("## 5 · Export the tables", "## 5 · Tabellen exportieren")),
        code('''OUT = Path(fc.forecast_folder(WORK_FOLDER, NETWORK))
TABLES = {"forecast_network_data": NETWORK_DATA, "forecast_ct_angle": CT_TABLE, "forecast_v3_recordings": V3_TABLE,
          "forecast_v3": V3_POOLED, "forecast_without_fault": COMPARISON}
TABLES = {k: v for k, v in TABLES.items() if v is not None and len(v) and v.notna().any().any()}
if TABLES:
    paths = report.export_tables(TABLES, str(OUT), prefix=report.slug(NETWORK) + "_without_fault_",
                                 formats=("csv", "md"))
    print("''' + t("%d table files in %s", "%d Tabellen-Dateien in %s") + '''" % (len(paths), OUT))
else:
    print("''' + t("ℹ Nothing to export – no network data, recordings or voltages (section 1).",
                   "ℹ Nichts zu exportieren – keine Netzdaten, Aufzeichnungen oder Spannungen (Abschnitt 1).") + '''")'''),
    ]
    return _notebook(cells, lang, WITHOUT_FAULT_NAMES[lang])


def _notebook(cells, lang, name):
    """Notebook of the cells with deterministic cell ids: ``<name>-<number>`` counted over the cells without a key
    (e.g. ``evaluate_measurement-07``), ``<name>-<key>`` for cells with a key (see ``keyed``).

    nbformat gives new cells random ids; fixed ids make every regeneration of an unchanged notebook give the same
    file (a reference copy and its working copy share the ids).
    """
    number = 0
    for cell in cells:
        if cell["id"].startswith("@"):
            cell["id"] = "%s-%s" % (name, cell["id"][1:])
        else:
            cell["id"] = "%s-%02d" % (name, number)
            number += 1
    nb = nbf.v4.new_notebook(cells=cells)
    nb.metadata = {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                   "language_info": {"name": "python"}}
    return nb


def write(nb, path, overwrite=True):
    """Write a notebook (an existing working copy only with ``overwrite``)."""
    if os.path.exists(path) and not overwrite:
        print("exists, not overwritten:", path)
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    nbf.validate(nb)
    with open(path, "w", encoding="utf-8", newline="\n") as f:         # the same bytes on every platform
        nbf.write(nb, f)
    print("written:", path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lang", choices=("en", "de"), default="en", help="language of the notebooks")
    ap.add_argument("--out", default=".", help="target folder")
    ap.add_argument("--example", action="store_true", help="configuration for the demo campaign")
    ap.add_argument("--templates-only", action="store_true", help="write only the reference copies")
    ap.add_argument("--overwrite", action="store_true", help="also overwrite existing working copies")
    ap.add_argument("--forecast", action="store_true",
                    help="also write the forecast notebooks (optional part) into <out>/forecast (German: <out>/Prognose)")
    ap.add_argument("--forecast-only", action="store_true", help="write only the forecast notebooks")
    a = ap.parse_args(argv)
    meas, camp, templates = NAMES[a.lang]
    if not a.forecast_only:
        write(measurement_notebook(a.lang, False), os.path.join(a.out, templates, meas + "_DEFAULT.ipynb"))
        write(campaign_notebook(a.lang, False), os.path.join(a.out, templates, camp + "_DEFAULT.ipynb"))
        if not a.templates_only:
            write(measurement_notebook(a.lang, a.example), os.path.join(a.out, meas + ".ipynb"), overwrite=a.overwrite)
            write(campaign_notebook(a.lang, a.example), os.path.join(a.out, camp + ".ipynb"), overwrite=a.overwrite)
    if a.forecast or a.forecast_only:
        name, folder = FORECAST_NAMES[a.lang]
        out = os.path.join(a.out, folder)
        for build, nb_name in ((forecast_notebook, name), (without_fault_notebook, WITHOUT_FAULT_NAMES[a.lang])):
            write(build(a.lang, False), os.path.join(out, templates, nb_name + "_DEFAULT.ipynb"))
            if not a.templates_only:
                write(build(a.lang, a.example), os.path.join(out, nb_name + ".ipynb"), overwrite=a.overwrite)


if __name__ == "__main__":
    main()
