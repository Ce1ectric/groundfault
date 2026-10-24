# Language and folder layout

groundfault works with English names internally – table columns such as `U_E_fault_V`, codes such as `"satisfied"`,
role codes such as `i_res`. Two things can be German instead: the **output language** of hints, tables, figures and
exported files, and the **folder layout** of the campaigns. Both are independent of each other: an English output
for a campaign in the German layout is as possible as the reverse.

## Output language

The output language is English (`"en"`) or German (`"de"`); the default is English.

| How | Effect |
|---|---|
| `i18n.set_language("de")` | for everything that follows |
| `with i18n.language("de"): …` | temporarily, inside the block |
| environment variable `GROUNDFAULT_LANGUAGE=de` | the default when groundfault is imported |
| `LANGUAGE = "de"` in the first cell of a notebook | the notebook calls `i18n.set_language(LANGUAGE)`; the German notebooks set it to `"de"` |

`i18n.get_language()` returns the active language. Language names are accepted in several forms (`"de"`, `"DE"`,
`"de_DE"`, `"german"`); other values raise a `ValueError`.

```python
import os
import tempfile

import groundfault as gf
from groundfault import corrections, demo, i18n, layout, legacy

base = tempfile.mkdtemp()
d = demo.make_campaign(base, layout="de")            # the demo campaign in the German folder layout
campaign = d["campaign"]
rec = gf.open_recording(os.path.join(campaign, "1_Rohdaten/UW/UW_0_10_000kHz.cfg"))
corr = corrections.load(campaign)
corr.apply(rec)
roles = gf.detect_roles(rec.channel_names, rec.units, corr.role_overrides(rec), corr.main_channel(rec),
                        corr.distances(rec))

i18n.set_language("de")
res = gf.evaluate(rec, gf.Intervals((2.6, 4.4), (0.2, 1.8), (7.0, 8.8)), roles=roles, z_fault_ohm=0.0)
print(res.summary())
print(i18n.localize(res.table("plausibility")[["check", "status", "value"]].head(3)).to_string(index=False))
print(i18n.localize(roles.table()[["short", "role", "meaning", "main_channel"]].head(4)).to_string(index=False))
i18n.set_language("en")
```

```text
Messung: UW_0_10_000kHz  (UW_0_10_000kHz.cfg)
Max-Fenster: 4,100 s  | f1 = 50,0200 Hz (phase)
IRES = 56,53 A | IG = 32,02 A | Iw = 20,00 A | Iv = 25,00 A | IH = 46,58 A
                                Pruefung Status                              Wert
          Fenster im stationären Bereich     OK                                 9
Gestörte Zustände im stationären Bereich     OK   keine erkannt (Schwelle 1,60 A)
                         Netzfrequenz f1     OK 50,0200 Hz (Vergleich 50,0200 Hz)
Kurz Rolle                    Bedeutung Hauptkanal
  V1 u_l1e Leiter-Erde-Spannung L1 (MS)          ✓
  V2 u_l2e Leiter-Erde-Spannung L2 (MS)          ✓
  V3 u_l3e Leiter-Erde-Spannung L3 (MS)          ✓
 IF1 i_res          Erdschlussreststrom          ✓
```

### What is translated

* **Messages** – hints, warnings, error messages and printed summaries come from message catalogues in both
  languages (`i18n.tr(key, **values)`); numbers inside them follow the language (`56,53 A` in German). A message
  without a German text falls back to English.
* **Figures** – titles of interactive figures, axis labels, legends, hover texts and the decimal separator
  ([Reports and exports](report.md#language-of-the-exports)).
* **Tables** – for display and export, `i18n.localize(df)` renames the columns and translates the code values; in
  English it returns the table unchanged. The notebooks show every table through it, and the export functions of
  `groundfault.report` apply it as well.
* **Texts inside tables** that are written during the evaluation – names and comments of the plausibility checks,
  role descriptions, hints – are in the language that was active when they were created. Switch the language
  **before** the evaluation; a result loaded later keeps the texts of its evaluation.

What stays the same in both languages: the role codes (`i_res`, `u_e` …), the table names (`station_frequency`,
`assessment_quantities` …), the keys of the result file, the formula symbols and the equations in the column
`equation`, the item descriptions written into groundmeas (always English) and every function and parameter name.

### German column names and codes

`i18n.column_label(name, lang)` and `i18n.value_label(column, value, lang)` give the display name of a column and of
a code; the dictionaries `i18n.COLUMNS_DE` and `i18n.VALUES_DE` contain all of them – the German names are those of
the predecessor tool, so German exports look as before:

```python
print(i18n.column_label("U_E_fault_V", "de"), "|", i18n.value_label("parallel_check", "satisfied", "de"), "|",
      i18n.value_label("status", "WARNING", "de"), "|", i18n.column_label("assessment_relevance", "de"))
with i18n.language("de"):
    print(i18n.format_number(0.0373, digits=3), "|", i18n.format_text("I = {:.2f} A ({n:,} samples)", 56.5257,
                                                                       n=90000))
print(i18n.format_number(0.0373, digits=3), "|", i18n.format_text("I = {:.2f} A ({n:,} samples)", 56.5257,
                                                                   n=90000))
```

```text
U_E_fehlerbedingt_V | erfüllt | WARNUNG | Bewertungsrelevanz
0,0373 | I = 56,53 A (90.000 samples)
0.0373 | I = 56.53 A (90,000 samples)
```

**Number format.** German output uses a decimal comma and a full stop as thousands separator in texts
(`i18n.format_number`, `i18n.format_text`); report tables and figures use a decimal comma and, on request, a thin
space as thousands separator (`report.number`). CSV files written in German have a decimal comma and semicolons, in English a decimal point and
semicolons. `report.set_style(decimal_comma=True)` forces the comma in figures and tables regardless of the language.

## Folder layouts

Campaigns can be organised in an English or a German folder layout (see
[Campaigns, folders and files](campaigns.md#the-work-folder)):

| Item | English layout (`"en"`) | German layout (`"de"`) |
|---|---|---|
| campaigns folder | `campaigns` | `01_Messkampagnen` |
| notes | `notes` | `0_Notizen` |
| raw recordings | `raw` | `1_Rohdaten` |
| results | `results` | `2_Auswertung` |
| figures | `figures` | `3_Abbildungen` |
| report | `report` | `4_Bericht` |
| media | `media` | `5_Medien` |
| corrections file | `corrections.csv` | `Korrekturen.csv` |
| sites file | `sites.csv` | `Messorte.csv` |
| free notes | `notes.txt` | `Notizen_Messung.txt` |
| register (work folder) | `register.csv` | `Messregister.csv` |
| campaign read-me | `README.md` | `LIESMICH.md` |
| result file | `<measurement>_result.json` | `<measurement>_ergebnis.json` |
| substation folder and prefix (convention) | `SUB` | `UW` |

The layout is **detected**, never configured: `layout.detect_layout(path)` looks at the path and up to three parent
folders for the typical folders (`0_Notizen`, `1_Rohdaten` … or `notes`, `raw` …) and the register file; German
folder names in the path decide at once. The English names are common words, so in a parent folder they count only
if the path runs through them (a file inside `raw/` or `results/` of a campaign) – a folder `results` that merely
sits next to the path is ignored. Without a hit it returns the default layout (English;
`layout.set_default_layout("de")` changes it). The notebooks take the layout from the name of the campaigns folder of
their work folder (`layout.find_work_folder`) and use their `LANGUAGE` if there is none.

```python
print(os.path.relpath(campaign, base), sorted(os.listdir(campaign)))
print(layout.detect_layout(campaign).language, layout.detect_layout(rec.cfg_path).language)
path = res.save_json(layout.GERMAN.result_path(campaign, res.name))
print(os.path.relpath(path, campaign))
```

```text
01_Messkampagnen/2026-01-15_Demo ['0_Notizen', '1_Rohdaten', 'LIESMICH.md']
de de
2_Auswertung/UW_0_10_000kHz/UW_0_10_000kHz_ergebnis.json
```

The layout object (`layout.ENGLISH`, `layout.GERMAN`, `layout.get_layout("de")`) has the folder and file names as
attributes (`raw`, `results`, `corrections_file` …) and builds the path of a result file with `result_path`. The
layout also decides the **language of the column headers** of the files groundfault writes (corrections and sites
file, register, read-me); all readers accept both header languages. A campaign's language of the headers and the
output language are independent: the German demo above was evaluated with German output, but could as well be
evaluated in English.

Messages that ask you to complete one of these files – the hints of the groundmeas export, the errors of the readers
of the corrections and sites files – name the file and its columns as they are in the campaign, whatever the output
language. The English output for the German demo campaign:

```python
from groundfault import earthing

plan = earthing.export_to_groundmeas(res, campaign, d["db"])      # dry run; English output, German folder layout
print(plan["reasons"])
```

```text
['new location “UW Demo” without coordinates (enter Breite/Laenge in 0_Notizen/Messorte.csv)']
```

## Files of the predecessor tool

groundfault continues a German in-house tool. Its files keep working:

* **Result files** (`*_ergebnis.json`, format `erdschluss-ergebnis`, German keys, column names and codes) are
  translated into the current structure when they are read – by `gf.load_result`, by the equivalent-source method
  (`equivalent_source.load_series`) and therefore by the campaign notebook. The `format` field is kept, so the
  origin stays visible. Inside a campaign folder, a file that names no campaign or site gets both from its path
  ([The result file](evaluation.md#the-result-file)).
* **Campaign files** with German headers – `Korrekturen.csv`, `Messorte.csv`, `Messregister.csv` – and German values
  (`ignorieren`, `ja`, `i_pen_v`) are read in both layouts.
* **Role names** of the predecessor (`i_schirm`, `u_hs_l1e` …, `i_pen_v`, `i_pen_n`) are translated – in the
  corrections file ([Corrections](corrections.md#role-codes)), in the role overrides, the main channels and the
  alignment of `evaluate`.
* **Settings** are not translated: options of the functions and notebooks take their English values. A value or key
  of the predecessor (`"mittel"`, `"spektral"`, `"komplex"`, `"ersetzen"`, `rollen`, `aus_ll` …) – settings copied by
  hand from an old notebook – raises an error that names the current name
  (`f1_method='spektral' is not allowed – allowed: 'phase', 'spectral' ('spektral' is the former name of 'spectral')`),
  so it is neither ignored nor misread ([Notebooks](notebooks.md#settings-in-section-1)).
* **Entries in groundmeas** made by the predecessor (tag `[erdschluss <campaign>/<measurement>]`) count as own entries:
  they are not entered twice, can be renewed and are left out of comparisons
  ([Entering a staged fault test](earthing.md#entering-a-staged-fault-test)).

`groundfault.legacy` does the translation; it is used automatically, but can be called directly:

```python
old = {"format": "erdschluss-ergebnis", "werte": {"IRES": 56.5},
       "tabellen": {"plausibilitaet": [{"Pruefung": "Fehlerleiter", "Status": "WARNUNG", "Wert": "L3"}],
                    "bewertungsgroessen": [{"Groesse": "IH_ges", "Messwert": 46.6, "Einheit": "A"}]}}
print(legacy.is_legacy_result(old))
print(legacy.translate_result(old))
print(legacy.translate_columns(["Datei", "Kanal", "Faktor", "Rolle", "Hauptkanal", "Abstand_m", "Bemerkung"]))
```

```text
True
{'format': 'erdschluss-ergebnis', 'values': {'IRES': 56.5}, 'tables': {'plausibility': [{'check': 'Fehlerleiter', 'status': 'WARNING', 'value': 'L3'}], 'assessment_quantities': [{'quantity': 'IH_total', 'measured_value': 46.6, 'unit': 'A'}]}}
['file', 'channel', 'factor', 'role', 'main_channel', 'distance_m', 'remark']
```

Texts inside old result files (check names, hints) stay German – only keys, column names and codes are translated.
