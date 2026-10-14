# -*- coding: utf-8 -*-
"""Generate the Jupyter notebooks of groundfault (user interface) in English or German.

Usage::

    python tools/make_notebooks.py --lang en --out notebooks/en --example
    python tools/make_notebooks.py --lang de --out <folder> [--templates-only] [--overwrite]

Two notebooks are written per language:

* ``evaluate_measurement.ipynb`` / ``Messung_auswerten.ipynb`` – one recording: channel roles, raw-data diagnostics,
  RMS trend, evaluation, station and earthing measurement (groundmeas), signal explorer, checks, export;
* ``evaluate_campaign.ipynb`` / ``Kampagne_auswerten.ipynb`` – a campaign: overview and consistency,
  equivalent-source method, residual current at the earthing impedance, resistive approach, stations, report
  tables and figures, entries in groundmeas.

The code cells are identical in both languages (English names); comments, explanations and printed texts follow
the language. ``--example`` fills the configuration for the demo campaign (``groundfault.demo.make_campaign``),
which the notebooks create on the first run – they then run without any measurement data. Without ``--example`` the
configuration contains placeholders. Unchanged reference copies (``templates/*_DEFAULT.ipynb`` or
``Vorlagen/*_DEFAULT.ipynb``) are always written; working copies are written only if they do not exist yet (own
changes are kept) unless ``--overwrite`` is given.
"""
import argparse
import os

import nbformat as nbf

NAMES = {"en": ("evaluate_measurement", "evaluate_campaign", "templates"),
         "de": ("Messung_auswerten", "Kampagne_auswerten", "Vorlagen")}


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
                         explorer, i18n, interactive, layout, legacy, register, report, rms, sites, transformer)

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
R_TYPICAL         = None    # range (low, high) of the reduction factor at 50 Hz you expect, e.g. from your experience
# (LIMITS, U_TP, F_FACTOR, UNCERTAINTY_I/_U and PQ_SAFETY_FACTOR become the settings ires_limits, u_tp, f_factor,
#  uncertainty_I/_U and pq_safety_factor and are stored in the result file)

# ---------------------------------------------------------------- evaluation parameters
SETTINGS = gf.Settings(
    T_win=0.200,                 # window length in s (step = window length)
    harmonics=(1, 3, 5, 7),      # orders of the assessment quantities
    uncertainty_I=UNCERTAINTY_I,  # increases currents
    uncertainty_U=UNCERTAINTY_U,  # decreases voltages
    u_thd95_percent=None,        # 95 % quantile of the THD (line-to-line) of a PQ measurement in % (None = no scaling)
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
R_TYPICAL         = None    # erwarteter Bereich (unten, oben) des Reduktionsfaktors bei 50 Hz, z. B. aus Erfahrung
# (LIMITS, U_TP, F_FACTOR, UNCERTAINTY_I/_U und PQ_SAFETY_FACTOR werden zu den Einstellungen ires_limits, u_tp,
#  f_factor, uncertainty_I/_U und pq_safety_factor und in der Ergebnisdatei gespeichert)

# ---------------------------------------------------------------- Auswerteparameter
SETTINGS = gf.Settings(
    T_win=0.200,                 # Fensterlänge in s (Schrittweite = Fensterlänge)
    harmonics=(1, 3, 5, 7),      # Ordnungen der Bewertungsgrößen
    uncertainty_I=UNCERTAINTY_I,  # vergrößert die Ströme
    uncertainty_U=UNCERTAINTY_U,  # verkleinert die Spannungen
    u_thd95_percent=None,        # 95-%-Quantil des THD (L-L) einer PQ-Messung in % (None = keine Skalierung)
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
   comparison, pairwise solution of two measurements, forecast error, jackknife and Monte Carlo uncertainty.
3. **Residual current at Z_E** with scaling to the 95 % quantile of a PQ measurement and your limits of the residual
   current; **resistive approach** (after the VDE Impuls on the residual earth-fault current).
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
   je zwei Messungen, Prognosefehler, Jackknife und Monte-Carlo-Unsicherheit.
3. **Erdschlussreststrom an Z_E** mit Skalierung auf das 95-%-Quantil einer PQ-Messung und den eigenen Grenzwerten
   des Reststroms; **resistiver Ansatz** (nach dem VDE Impuls zum Erdschluss-Reststrom).
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
Z_E           = ''' + z_e + '''
Z_E_MAX       = 10.0               # end of the axis of the figure I_RES(Z_E)
IG_CHOICE     = "max"              # fundamental component: "max" (conservative) | "median" | a number in A

# ---------------------------------------------------------------- scaling to the 95 % quantile of a PQ measurement
# U95 scales every order with its own 95 % value; THD95_PERCENT scales flat with THD95/THD of the series. Both
# given: U95 where possible, the THD factor for the orders U95 cannot scale (no value, zero sequence with "LL").
U95 = None                         # per order in V, e.g. {5: U_5, 7: U_7}
U95_REFERENCE = "LL"               # "LL" = line-to-line (PQ device) | "seq" = sequence voltage (line-to-earth)
THD95_PERCENT = None               # flat: 95 % quantile of the THD in % (line-to-line), alone or together with U95

# ---------------------------------------------------------------- limits, margins and factors – defined by you
# groundfault contains no limits or safety factors: take them from the operator's specification or the applicable
# standard. Not set (the values below), the parts that need them are skipped with a note.
LIMITS            = ()      # limits of the residual current in A, e.g. (I_1, I_2): lines in the figures I_RES(Z_E)
U_TP              = None    # permissible touch voltage U_Tp in V (resistive approach; reduction factor: None = from the result file)
F_FACTOR          = None    # factor F of the permissible earth potential rise F·U_Tp (as U_TP)
REFERENCE_CURRENT = None    # reference current in A for the reduction factor (None = largest limit of the result file)
UNCERTAINTY_I     = 0.0     # measurement-uncertainty margin m_I of currents for I_RES at Z_E: I·(1 + m_I) (0.0 = none)
PQ_SAFETY_FACTOR  = 1.0     # factor on the 95 % quantiles of the PQ measurement (1.0 = none)
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
Z_E           = ''' + z_e + '''
Z_E_MAX       = 10.0               # Achsenende im Diagramm I_RES(Z_E)
IG_CHOICE     = "max"              # Grundschwingung: "max" (konservativ) | "median" | Zahl in A

# ---------------------------------------------------------------- Skalierung auf das 95-%-Quantil einer PQ-Messung
# U95 skaliert jede Ordnung mit ihrem eigenen 95-%-Wert; THD95_PERCENT pauschal mit THD95/THD der Messreihe. Beide
# angegeben: U95, wo möglich, der THD-Faktor für die Ordnungen, die U95 nicht skaliert (kein Wert, Nullsystem bei "LL").
U95 = None                         # je Ordnung in V, z. B. {5: U_5, 7: U_7}
U95_REFERENCE = "LL"               # "LL" = Leiter-Leiter (PQ-Gerät) | "seq" = Sequenzspannung (L-E)
THD95_PERCENT = None               # pauschal: THD-95-%-Quantil in % (L-L), allein oder zusammen mit U95

# ---------------------------------------------------------------- Grenzwerte, Zuschläge und Faktoren – selbst festlegen
# groundfault enthält keine Grenzwerte oder Sicherheitsfaktoren: aus der Vorgabe des Netzbetreibers bzw. der geltenden
# Norm übernehmen. Nicht gesetzt (die Werte unten), werden die Teile, die sie brauchen, mit einem Hinweis übersprungen.
LIMITS            = ()      # Grenzwerte des Reststroms in A, z. B. (I_1, I_2): Linien in den Diagrammen I_RES(Z_E)
U_TP              = None    # zulässige Berührungsspannung U_Tp in V (resistiver Ansatz; Reduktionsfaktor: None = aus der Ergebnisdatei)
F_FACTOR          = None    # Faktor F der zulässigen Erdungsspannung F·U_Tp (wie U_TP)
REFERENCE_CURRENT = None    # Bezugsstrom in A für den Reduktionsfaktor (None = größter Grenzwert der Ergebnisdatei)
UNCERTAINTY_I     = 0.0     # Messunsicherheitszuschlag m_I der Ströme für I_RES an Z_E: I·(1 + m_I) (0.0 = keiner)
PQ_SAFETY_FACTOR  = 1.0     # Faktor auf die 95-%-Quantile der PQ-Messung (1.0 = keiner)
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
`Uq_angle_ref_faulted_phase_deg` ≈ 0°. **Sensitivity** `dZq_rel_per_1pct`: relative change of Z_q for an error of 1 %
(or 0.5°) of one current – above 0.1 ill-conditioned.
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
`Uq_bez_Fehlerleiter` ≈ 1 und `Uq_Winkel_bez_Fehlerleiter_deg` ≈ 0°. **Empfindlichkeit**: relative Änderung von Z_q
bei 1 % (bzw. 0,5°) Fehler eines Stroms – über 0,1 schlecht konditioniert.
''')),
        code('''SERIES = MC = None                 ''' + t("# MC: Monte Carlo uncertainty (section 3, checks)", "# MC: Monte-Carlo-Unsicherheit (Abschnitt 3, Kontrollen)") + '''
entries = [dict(file=str(result_file(m["measurement"])), Z=m["Z"], name=m["name"])
           for m in MEASUREMENTS if m["Z"] is not None and m["name"] in RESULTS]
if len(entries) >= 2:
    SERIES = equivalent_source.fit_equivalent_source(equivalent_source.load_series(entries), orders=ORDERS,
                                                     normalization=NORMALIZATION, reference=LEVEL, method=METHOD)
    show(SERIES.measurements_table())
    display(Markdown("''' + t("**Source level before/after the fault** (drift within one measurement = quality of the normalization)",
                              "**Quellenpegel vor/nach dem Fehler** (Drift innerhalb einer Messung = Güte der Normierung)") + '''"))
    show(SERIES.level_table(LEVEL))
    display(Markdown("''' + t("**Two-terminal equivalents per order**", "**Zweipol-Parameter je Ordnung**") + '''"))
    show(SERIES.source_table())
    for h in SERIES.hints:
        print("ℹ", h)
    for m, F in SERIES.fits.items():
        for h in F.hints:
            print("ℹ ''' + t("harmonic %d:", "%d. Harmonische:") + ''' %s" % (m, h))
else:
    print("''' + t("The equivalent-source method needs at least two substation measurements with different additional impedances.",
                   "Für das Ersatzquellenverfahren sind mindestens zwei UW-Messungen mit verschiedener Zusatzimpedanz nötig.") + '''")'''),
        md(t("### Checks: pairwise solution, forecast per measurement, jackknife, Monte Carlo",
             "### Kontrollen: paarweise Lösung, Prognose je Messung, Jackknife, Monte Carlo")),
        code('''if SERIES is not None:
    show(SERIES.pairwise_table())
    show(SERIES.forecast_table())
    if Z_E is not None:
        show(SERIES.jackknife_table(Z_E))
    display(Markdown("''' + t("**Residual current at the measured impedances** – model (with the level and I_G of each measurement, rest = orders not fitted) against the measured true RMS value",
                              "**Reststrom an den Messimpedanzen** – Modell (mit Pegel und I_G der jeweiligen Messung, Rest = nicht gefittete Ordnungen) gegen den gemessenen Echt-Effektivwert") + '''"))
    show(SERIES.check_table())
    if Z_E is None:
        print("''' + t("ℹ Jackknife and Monte Carlo at Z_E skipped – Z_E is not set (section 1).",
                       "ℹ Jackknife und Monte Carlo an Z_E übersprungen – Z_E ist nicht gesetzt (Abschnitt 1).") + '''")
    else:
        MC = equivalent_source.monte_carlo(SERIES, Z_E, n=2000)
        print(i18n.format_text("''' + t("Monte Carlo (1 %/0.5° current, 2 % Z, model residual): I_RES(Z_E = {:g} Ω) P5 … P95 = {:.1f} … {:.1f} A (median {:.1f} A)",
                                         "Monte Carlo (1 %/0,5° Strom, 2 % Z, Modellresiduum): I_RES(Z_E = {:g} Ω) P5 … P95 = {:.1f} … {:.1f} A (Median {:.1f} A)") + '''",
                               Z_E, MC["IRES"][5], MC["IRES"][95], MC["IRES"][50]))
        zmin, zmax = SERIES.Z_range
        print(i18n.format_text("''' + t("Z_E lies {} the measured range {:.1f} … {:.1f} Ω", "Z_E liegt {} des Messbereichs {:.1f} … {:.1f} Ω") + '''",
            "''' + t("within", "innerhalb") + '''" if zmin <= Z_E <= zmax else "''' + t("OUTSIDE (extrapolation)", "AUSSERHALB (Extrapolation)") + '''", zmin, zmax))
    interactive.source_fit(SERIES, Z_E).show()'''),
        md(t("## 4 · Residual current at the earthing impedance and resistive approach",
             "## 4 · Erdschlussreststrom an der Erdungsimpedanz und resistiver Ansatz")),
        code('''SCALING = None
if SERIES is not None:
    if U95 or THD95_PERCENT:           ''' + t("# U95 per order; THD95_PERCENT alone for all orders, with U95 for the orders U95 cannot scale",
                                         "# U95 je Ordnung; THD95_PERCENT allein für alle Ordnungen, mit U95 für die, die U95 nicht skaliert") + '''
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
        r = equivalent_source.ires_at_impedance(SERIES, Z_E, IG=IG_CHOICE, uncertainty_I=UNCERTAINTY_I, **(SCALING or {}))
        margin = UNCERTAINTY_I > 0             ''' + t("# the value with the margin only if you set one", "# den Wert mit Zuschlag nur, wenn einer gesetzt ist") + '''
        print(i18n.format_text("I_G = {:.2f} A | I_H(Z_E) = {:.2f} A (''' + t("rest", "davon Rest") + ''' {:.2f} A) | I_RES(Z_E = {:g} Ω) = {:.2f} A",
                               r["IG"], r["IH"], r["IH_rest"], Z_E, r["IRES"])
              + (i18n.format_text(" | ''' + t("with the measurement-uncertainty margin", "mit Messunsicherheitszuschlag") + ''': {:.2f} A", r["IRES_assessed"]) if margin else ""))
        if SCALING:
            print(i18n.format_text("''' + t("scaled", "skaliert") + ''': I_H = {:.2f} A → I_RES = {:.2f} A", r["IH_scaled"], r["IRES_scaled"])
                  + (i18n.format_text(" (''' + t("with the margin", "mit Zuschlag") + ''': {:.2f} A)", r["IRES_scaled_assessed"]) if margin else "")
                  + i18n.format_text(" | ''' + t("factors", "Faktoren") + ''' {}", ", ".join(i18n.format_text("{}: {:.3f}", m, k)
                                                                         for m, k in r["factors"].items())))
        for h in r["hints"]:
            print("ℹ", h)
    if not LIMITS:
        print("''' + t("ℹ No limit lines in the figures I_RES(Z_E) – LIMITS is not set (section 1).",
                       "ℹ Keine Grenzwertlinien in den Diagrammen I_RES(Z_E) – LIMITS ist nicht gesetzt (Abschnitt 1).") + '''")
    interactive.ires_ze(SERIES, Z_E_MAX, LIMITS, SCALING).show()
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
TABLES = report.report_tables(RESULTS, series=SERIES, Z_E=Z_E)
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
if SERIES is not None:
    figures += report.save(report.source_fit(SERIES, Z_E=Z_E), str(FIG / "source_fit"), EXPORT_FORMATS, close=True)
    figures += report.save(report.source_plane(SERIES, MC), str(FIG / "source_impedance"), EXPORT_FORMATS, close=True)
    figures += report.save(report.ires_over_ze(SERIES, Z_E_MAX, LIMITS, IG_CHOICE, SCALING), str(FIG / "ires_over_ZE"),
                           EXPORT_FORMATS, close=True)
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
    a = ap.parse_args(argv)
    meas, camp, templates = NAMES[a.lang]
    write(measurement_notebook(a.lang, False), os.path.join(a.out, templates, meas + "_DEFAULT.ipynb"))
    write(campaign_notebook(a.lang, False), os.path.join(a.out, templates, camp + "_DEFAULT.ipynb"))
    if not a.templates_only:
        write(measurement_notebook(a.lang, a.example), os.path.join(a.out, meas + ".ipynb"), overwrite=a.overwrite)
        write(campaign_notebook(a.lang, a.example), os.path.join(a.out, camp + ".ipynb"), overwrite=a.overwrite)


if __name__ == "__main__":
    main()
