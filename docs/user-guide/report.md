# Reports and exports

groundfault writes the figures and tables of a test report ready to insert: figures in their final size for an A4
page, tables as CSV, Excel, Markdown, LaTeX and Word. The notebooks export everything in their last sections; this
page explains the functions behind it, the style and the language of the exported files. The functions are in
[`groundfault.report`](../reference/report.md) (report figures and tables) and
[`groundfault.interactive`](../reference/interactive.md) (interactive figures for the notebook).

## Figures

The report figures follow a few rules, so that all figures of a report look alike:

* **no titles** – the caption belongs in the report;
* **final size** – full width 15.9 cm (type area of A4 with 2.54 cm margins) or half width 7.7 cm; insert them
  without scaling, then the font size in the figure equals the font size in the document;
* one font for everything, also for formula symbols: the first installed of Aptos, Arial, Helvetica, Liberation Sans
  and DejaVu Sans;
* axis labels in the form “quantity in unit”, one y-axis per panel – different quantities go into stacked panels
  with the letters (a), (b), …;
* a fixed colour per quantity (L1, L2, L3, fault current, coil current …), a legend from two data series on;
* export as PDF (vector, font embedded), SVG (text stays text) and PNG (300 dpi).

### All figures of a measurement

`report.all_figures(res, folder, rec=rec, prefix=…, formats=…)` saves the standard figures that the channels of the
recording allow – the measurement notebook calls it in section 7:

```python
import os
import tempfile

import groundfault as gf
from groundfault import corrections, demo, i18n, report

base = tempfile.mkdtemp()
d = demo.make_campaign(base, layout="en")
campaign = d["campaign"]
rec = gf.open_recording(os.path.join(campaign, "raw/SUB/SUB_0_10_000kHz.cfg"))
corr = corrections.load(campaign)
corr.apply(rec)
roles = gf.detect_roles(rec.channel_names, rec.units, corr.role_overrides(rec), corr.main_channel(rec),
                        corr.distances(rec))
res = gf.evaluate(rec, gf.Intervals((2.6, 4.4), (0.2, 1.8), (7.0, 8.8)), roles=roles, z_fault_ohm=0.0)

paths = report.all_figures(res, os.path.join(base, "figures"), rec=rec, prefix="SUB_0_10_000kHz_",
                           formats=("png",))
print("\n".join(os.path.basename(p) for p in paths))
```

```text
SUB_0_10_000kHz_instantaneous.png
SUB_0_10_000kHz_rms_trend.png
SUB_0_10_000kHz_spectrum_fault_current.png
SUB_0_10_000kHz_harmonics_trend.png
SUB_0_10_000kHz_phasor_diagram.png
SUB_0_10_000kHz_voltage_negative_sequence.png
SUB_0_10_000kHz_voltage_positive_sequence.png
```

| File (after the prefix) | Content | Written when |
|---|---|---|
| `instantaneous` | instantaneous values of 80 ms around the max window, one panel per quantity | `rec` is given |
| `rms_trend` | true RMS value over time with the analysis intervals and the max window | `rec` is given |
| `spectrum_fault_current` | harmonics of the fault current in the max window (bars) | fault current |
| `harmonics_trend` | RMS value and harmonics per 200-ms window of the steady-state interval | fault current |
| `phasor_diagram` | line-to-earth voltages and U0; fault current split into Iw and Iv | fault current and voltages |
| `voltage_negative_sequence`, `voltage_positive_sequence` | 5th/11th (negative) and 7th/13th (positive sequence) harmonic before, during and after the fault | line-to-earth voltages |
| `station_voltages`, `station_frequency`, `station_background`, `station_lv_network` | station figures ([Stations and the LV network](station.md#figures-and-interactive-views)) | station evaluation |
| `transformer_power` | active and reactive power per order at the transformer | line currents |
| `transformer_impedance` | apparent impedance per state and upstream impedance over the frequency | line currents and a pre-fault or post-fault interval |

Without `prefix` the file names start with the measurement name as `report.slug` writes it – letters and digits,
everything else `_`, lower case (`report.slug("M1 (2,5 Ω)")` → `m1_2_5`). Each figure function can also be called on
its own; it returns a matplotlib figure that `report.save` writes:

| Function | Figure |
|---|---|
| `instantaneous(rec, roles, t0, duration=0.08, channels=None)` | waveforms in an excerpt |
| `rms_trend(res, rec=None, channels=("i_res", "i_coil"), window_s=0.02, t_range=None)` | RMS trend with intervals |
| `harmonics_trend(res, role="i_res", orders=(1, 3, 5, 7))` | RMS value and harmonics per window |
| `spectrum(res, role="i_res", orders=None)` | harmonics in the max window |
| `spectrum_comparison(results, names, role="i_res")` | harmonics of several measurements side by side |
| `voltage_spectrum(res, quantity="U_neg", orders=(5, 7, 11, 13))` | a voltage quantity before, during and after the fault |
| `phasor_diagram(res, coils=False)` | phasor diagram of the fundamental |
| `v_curve(t, ires, result=None, i_coil=None, quantity="I_RES")` | resonance curve |
| `transformer_power(res, orders=(5, 7, 11, 13))` | power per order at the transformer |
| `transformer_impedance(res, orders=(5, 7, 11, 13))` | apparent impedance \|U_m/I_m\| per state (a) and upstream impedance \|Z_up\| over the frequency with m·X_up,1 and the shares of transformer and HV network (b) |
| `station_voltages(res)`, `station_frequency(res)`, `station_background(res)`, `lv_network(table, check=None)` | station ([Stations and the LV network](station.md)) |
| `earthing_comparison(long_df, ratio)`, `reduction_factor(spectrum, effective, r_typical=None)` | earthing measurement ([Earthing measurements](earthing.md)); a grey bar at 50 Hz only for a typical range of r that you give |
| `source_fit(series, Z_E=None)`, `source_plane(series, mc=None)`, `ires_over_ze(series, Z_E_max, limits=(), IG, scaling)` | equivalent-source method, `ires_over_ze` with lines at the limits of the residual current that you give (none by default); `source_plane` draws the Monte Carlo spread of Z_q given the result of `equivalent_source.monte_carlo` ([Campaign evaluation](campaign.md#checks-and-hints)) |

All of them accept `width` (`"full"`, `"half"` or a width in cm) and a height in cm (`height_cm` or
`height_per_panel_cm`). The figures of a single measurement accept an evaluation result or a loaded result file.

### Style, sizes and formats

The style is the global `report.STYLE` (a `ReportStyle`); `report.set_style(…)` changes fields of it:

| Field | Default | Meaning |
|---|---|---|
| `fonts` | `("Aptos", "Arial", "Helvetica", "Liberation Sans", "DejaVu Sans")` | font preference; the first installed one is used (`report.used_font()`) |
| `font_file` | `None` | path of a font file (e.g. a licensed corporate font) that is registered and put first |
| `font_size`, `font_size_small` | `9.0`, `8.0` | axis labels; ticks and legend, in pt |
| `full_width_cm`, `half_width_cm`, `height_cm` | `15.9`, `7.7`, `7.0` | figure sizes in cm |
| `line_width` | `0.9` | line width in pt |
| `decimal_comma` | `None` | `None`: decimal separator of the output language; `True`/`False`: always comma/point |
| `formats`, `dpi` | `("pdf", "svg", "png")`, `300` | export formats of `save` and the resolution of PNG files |
| `panel_letters` | `True` | label the panels (a), (b), … |

```python
report.set_style(font_size=10.0, formats=("pdf", "png"))
fig = report.spectrum(res, width="half", height_cm=6.0)
print("%.1f × %.1f cm" % tuple(fig.get_size_inches() * 2.54))
paths = report.save(fig, os.path.join(base, "figures", "spectrum_half"), close=True)
print([os.path.basename(p) for p in paths])
report.set_style(font_size=9.0, formats=("pdf", "svg", "png"))      # back to the defaults
```

```text
7.7 × 6.0 cm
['spectrum_half.pdf', 'spectrum_half.png']
```

`report.figure(width, height_cm, nrows, ncols)` creates an empty figure in the report style for your own plots, and
`report.activate_style()` sets the style for all matplotlib figures – the notebooks call it, so the preview shows the
font of the exported files. The notebooks write the figures in `EXPORT_FORMATS` to `figures/<measurement>/` and
`figures/campaign/`.

### Interactive figures

The notebooks show interactive Plotly figures from `groundfault.interactive` – with zoom, hover texts and sliders,
for exploring, not for the report:

| Function | Content |
|---|---|
| `overview(rec, roles)` | envelope of the instantaneous values of the whole recording |
| `rms_values(rec, roles, intervals=…)` | moving RMS value (20-ms windows) for reading off the intervals |
| `window_spectrum(res)`, `harmonics_time(res)` | harmonics per window of the steady-state interval (slider), harmonics over time |
| `voltage_spectrum(res)` | voltage quantities per order before, during and after the fault |
| `frequency_diagnosis(rec, res)` | spectrum of the reference voltage around 50 Hz with the estimated f1 |
| `station_frequency(res)`, `earthing_comparison(long_df, ratio)`, `reduction_factor(spectrum, effective)`, `lv_network(table, check)` | station and earthing measurement |
| `source_fit(series, Z_E)`, `ires_ze(series, Z_E_max, limits=(), scaling)` | equivalent-source method (limit lines only for limits that you give) |

They return `plotly.graph_objects.Figure` objects: `fig.show()` displays one, `fig.write_html(path)` saves it. The
[signal explorer](explorer.md) combines several of these views and can be written as one HTML file.

## Tables

All tables of a result use English column names and codes (see [Evaluating a recording](evaluation.md#the-result)).
For a report they are formatted and exported in the output language:

```python
aq = res.table("assessment_quantities")[["quantity", "measured_value", "assessment", "unit"]].head(3)
print(report.format_table(aq).to_string(index=False))
paths = report.export_tables({"assessment_quantities": res.table("assessment_quantities"),
                              "plausibility": res.table("plausibility")},
                             os.path.join(base, "tables"), prefix="SUB_0_10_000kHz_")
print("\n".join(os.path.basename(p) for p in paths))
print(report.number(12.25, 3), report.number(-0.012345, 3), report.number(12.5, 2, "fixed"),
      report.number(1234567.0, 4, thousands=True))
```

```text
quantity measured_value assessment unit
    IRES           56.5       56.5    A
      Iw           20.0       20.0    A
      Iv           25.0       25.0    A
SUB_0_10_000kHz_assessment_quantities.csv
SUB_0_10_000kHz_assessment_quantities.md
SUB_0_10_000kHz_plausibility.csv
SUB_0_10_000kHz_plausibility.md
SUB_0_10_000kHz_tables.xlsx
SUB_0_10_000kHz_tables.docx
12.3 −0.0123 12.50 1 234 567
```

| Function | Purpose |
|---|---|
| `format_table(df, digits=3, mode="significant", thousands=False, lang=None)` | copy with all numbers as text: `digits` significant digits (`mode="fixed"`: decimals; `digits` may be a dict per column), columns and codes in the output language |
| `number(x, digits=3, mode="significant", thousands=False, lang=None)` | one number as text: rounds half away from zero (12.25 → 12.3), typographic minus, optional thin space as thousands separator, “–” for NaN |
| `export_table(df, path_stem, formats=("csv", "xlsx", "md"), digits=3, index=False)` | one table in the formats `csv`, `xlsx`, `md`, `tex`, `docx` |
| `export_tables(tables, folder, prefix="", formats=("csv", "md"), excel_workbook=True, docx=True, digits=3, names=())` | several tables: single files plus one Excel workbook `<prefix>tables.xlsx` (one sheet per table) and one Word file `<prefix>tables.docx`; `names` as in `table_title` |
| `docx_tables(tables, path, digits=3, font=None, size_pt=10.0, names=())` | Word file with formatted tables, a heading per table (`table_title`), the font of the report |
| `report_tables(results, series=None, Z_E=None, orders=(1, 3, 5, 7))` | the campaign tables with one column per measurement ([Campaign evaluation](campaign.md#report-tables-and-figures)) |
| `table_title(name, names=())` | heading of a table in the output language (`"residual_current"` → “Residual earth-fault current”): every table of a result, of `report_tables` and of the notebook exports has one; a table of one measurement (`station_frequency_m4_station`) gets the name of the measurement as given if it is one of `names` (“… per frequency – M4 (Station)”) |
| `slug(name)` | a name as part of file and table names: letters and digits, everything else `_`, lower case |

CSV and Excel keep numbers as numbers (Excel can calculate with them); CSV files use semicolons, UTF-8 with BOM and
the decimal separator of the language. Markdown, LaTeX and Word contain the formatted numbers. Excel files need
`openpyxl`, Word files `python-docx` (both in the extra `export`). Without them `export_tables` skips the workbook or
the Word file with a warning (“tables.xlsx not written: openpyxl is not installed (pip install
"groundfault[export]").”) and writes the other files; an explicit `export_table(…, formats=("xlsx",))` or
`("docx",)` raises an `ImportError` with the same installation hint and writes nothing.

What the notebooks export: the measurement notebook writes all tables of the result – at a station also the
comparison with groundmeas (`earthing_comparison`, `earthing_ratio`, `reduction_factor`, `reduction_factor_eff`,
`lv_network_check`, `lv_network_check_eff`) – to `results/<measurement>/tables/`; the campaign notebook writes the
report tables to `results/campaign/` with the prefix `campaign_`. Tables and figures of a single measurement in the
campaign export – such as `station_frequency_measurement_4_station` – carry its name in the form of `report.slug`, the
same rule as the tables of `report_tables` (`epr_m4_station`).

## Language of the exports

Figures and tables are written in the **output language that is active when they are created** (see
[Language and folder layout](language.md)):

* **Figures** – axis labels, legends and annotations; the decimal separator (comma in German, point in English,
  unless `STYLE.decimal_comma` is set). Formula symbols are the same in both languages, except subscripts that are
  words: coil current I_coil / I_Sp, current into the LV network I_LV / I_ON, sequence voltages U_pos / U_Mit.
* **Exported tables** – in English the canonical column names and codes; in German the column names and code values
  are translated by `i18n.localize` (e.g. `quantity` → `Groesse`, `measured_value` → `Messwert`, status `WARNING` →
  `WARNUNG`), and CSV files get a decimal comma.
* **Texts inside table cells** that the evaluation wrote – names of plausibility checks, comments, hints,
  descriptions – are in the language that was active **during the evaluation**; a later switch translates only
  column names and codes. Evaluate in the language of the report.
* **File names** are English in every language and folder layout – the tables (`<prefix><table>.csv`,
  `<prefix>tables.xlsx`, `<prefix>tables.docx`), the figures and the explorer (`<measurement>_explorer.html`) –; only
  the folders follow the folder layout of the campaign (`results/<measurement>/tables/` and `results/campaign/`,
  German `2_Auswertung/<Messung>/tabellen/` and `2_Auswertung/Kampagne/`).

To export German files from an English session, switch the language temporarily:

```python
with i18n.language("de"):
    print(report.format_table(aq).to_string(index=False))
    paths = report.export_tables({"assessment_quantities": aq}, os.path.join(base, "tabellen"),
                                 prefix="SUB_0_10_000kHz_", docx=False)
print("\n".join(os.path.basename(p) for p in paths))
with open(paths[0], encoding="utf-8-sig") as f:
    print(f.read())
```

```text
Groesse Messwert Bewertung Einheit
   IRES     56,5      56,5       A
     Iw     20,0      20,0       A
     Iv     25,0      25,0       A
SUB_0_10_000kHz_assessment_quantities.csv
SUB_0_10_000kHz_assessment_quantities.md
SUB_0_10_000kHz_tables.xlsx
Groesse;Messwert;Bewertung;Einheit
IRES;56,52565693412697;56,52565693412697;A
Iw;19,99869925978915;19,99869925978915;A
Iv;24,999618455486452;24,999618455486452;A
```
