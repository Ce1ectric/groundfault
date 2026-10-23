# Word report of a campaign

`groundfault.document` writes the report of a campaign of staged earth-fault tests as a Word file: title page, key
results, contents, three chapters and appendices, with every number taken from the result files and the objects of the
campaign evaluation – nothing is typed over by hand. Photos taken on site and the recommendation of the author are
placeholders that you fill in Word. The report is written in English or German, in a neutral layout or in the template
of your organisation. The module needs [python-docx](https://python-docx.readthedocs.io), installed with the extra
`export`:

```bash
pip install "groundfault[export]"
```

The functions are in [`groundfault.document`](../reference/document.md). In the campaign notebook the report is
section 8 (`REPORT`, [Notebooks](notebooks.md)).

## Step by step

1. **Install** groundfault with the extra `export` (above) – for a PDF from Python also LibreOffice.
2. **Evaluate every recording** with the measurement notebook and export its result file (section 7,
   `<results>/<measurement>/<measurement>_result.json`). The report works on the result files and on the raw
   recordings of the campaign folder, which it evaluates again for the waveforms and as a check.
3. **Configure the campaign notebook** in section 1: `MEASUREMENTS` (the tests in the order of the report), the
   parameters of the assessment (limits, `U_TP`, `F_FACTOR`, the margins, `Z_E`, the PQ measurement) and the report:
   `REPORT` with the title page and the texts ([below](#title-page-and-texts-reportinfo)), `PHOTOS`, optionally
   `REPORT_TEMPLATE`, `REPORT_STYLES` and `REPORT_PDF`.
4. **Copy the photos** taken on site into the media folder of the campaign (`<campaign>/media`, German layout
   `5_Medien`) and name them in `PHOTOS`; a photo you do not have yet stays a placeholder.
5. **Run the notebook** (*Run → Run All Cells*). Section 8 writes the report into the report folder
   (`<campaign>/report`, German layout `4_Bericht`), e.g. `Evaluation_of_staged_earth-fault_tests_<campaign>.docx`, and
   lists the placeholders still to fill and the hints.
6. **Open the report in Word** and confirm the question to update the fields (contents, numbers of figures and tables,
   page numbers). Insert the missing photos, write the recommendation, check the texts and save. Running section 8
   again later does not overwrite the edited file (see below).
7. **PDF**: save it from Word for the final version (`REPORT_PDF = True` writes a preview with LibreOffice).

## Structure

| Part | Content |
|---|---|
| Title page | title, network area, places and date of the tests (from the recordings), date, authors, version, the software version |
| Key results | the characteristic values against your limits: I_CE, damping and detuning, the residual current measured and with the margin, scaled to the PQ measurement, at Z_E with the equivalent sources (the decisive value marked), the network expansion (the residual current at the planned I_CE, the I_CE at which every limit is reached), the touch voltage at every station (largest approach), the validity of the PQ measurement |
| 1 Set-up and procedure | 1.1 object and measurement set-up: tests with place, additional impedance, fault inception and duration; photo of the additional impedance; recorder and table of measured quantities (channels, measuring points, transducers); photo of the recording; corrections of the measuring chain. 1.2 procedure |
| 2 Results | 2.1 measurement uncertainty (accuracy of the measuring chain, margins) and processing of the recordings (RMS trend with the intervals of the evaluation); 2.2 fault current – waveforms and the spectrum of every test with all orders above `threshold_A`, grouped by sequence, the split of the fundamental into active and reactive current, coil currents; 2.3 earth potential rise per station – photo of the set-up, waveforms, values per frequency, comparison with the earthing measurement, reduction factor, LV network; 2.4 network voltages – 2.4.1 the power-quality measurement, 2.4.2 the voltages before and after every test |
| 3 Assessment | 3.1 processing of the residual current in three steps (margin, scaling per order, residual current with the scaled harmonic content); 3.2 equivalent-source method and forecast; 3.3 network expansion – can further cables be connected at the substation? (the residual current over I_CE with the coils retuned, the I_CE at which every limit is reached); 3.4 assessment of the earthing per station (touch voltage, approaches 1 to 4); 3.5 uncertainties; 3.6 summary with the recommendation |
| Appendices | A data of the recordings (file, start, sampling rate, fundamental frequency, intervals, window, corrections, reproduction from the raw data); B plausibility checks (findings of the single evaluations, consistency between the tests, checks of the report); C symbols |

Sections without data are left out or say so: without a station there is no section 2.3 and no assessment of the
earthing; without a PQ measurement section 2.4.1 states that none was available and step 2 of 3.1 uses the scaling of
the single evaluations (none: step 2 is left out); without equivalent sources 3.2 says that none were determined, and
without them or without I_CE there is no network expansion.

## From the campaign notebook

Section 1 of the campaign notebook holds the configuration of the report; section 8 writes it into the report folder of
the campaign (`<campaign>/report`, German layout `4_Bericht`) and lists the placeholders still to fill:

```python
REPORT = dict(network="20 kV network of substation …",    # line under the title
              authors=["…"],                              # names on the title page
              places={"SUB": "Substation …", "Station_Elm_Road": "Station Elm Road"},
              expansion=dict(I_CE=800.0))                 # network expansion: the planned I_CE in A
PHOTOS = {"setup_impedance": "impedance.jpg", "recorder": "recorder.jpg"}   # file names in <campaign>/media
REPORT_TEMPLATE = None             # Word file of your organisation (styles, header and footer, logo)
REPORT_STYLES = None               # style names of the template, e.g. {"title": "…", "subtitle": "…"}
REPORT_PDF = False                 # also a PDF with LibreOffice
```

The limits, U_Tp, F, the margins `UNCERTAINTY_I` and `UNCERTAINTY_U`, `Z_E`, `IG_CHOICE`, the PQ measurement and the
equivalent sources are those of the notebook – the report shows what the notebook computed. `REPORT = None` writes no
report.

Running the section again replaces the report only while it is unchanged. A report that was saved in Word (or
LibreOffice) since it was written is kept as `<name>_<date>_<time>.docx` (its modification time) and the new one is
written next to it – nothing filled in by hand is lost. Photos and the recommendation are best given in `PHOTOS` and
`REPORT["recommendation"]`, so that they are part of every new version.

## From Python

`document.campaign_report(results, path=None, *, info=None, …)` takes the results of the tests (in the order of the
report columns) and whatever else is available; everything except the results is optional:

```python
import os
import tempfile

import groundfault as gf
from groundfault import corrections, demo, document

base = tempfile.mkdtemp()
d = demo.make_campaign(base, layout="en", groundmeas=False, pq=False)
campaign = d["campaign"]
corr = corrections.load(campaign)
results, measurements = {}, []
for i, t in enumerate(d["substation"], 1):
    rec = gf.open_recording(os.path.join(campaign, t["cfg"]))
    corr.apply(rec)
    roles = gf.detect_roles(rec.channel_names, rec.units, corr.role_overrides(rec), corr.main_channel(rec),
                            corr.distances(rec))
    b = t["intervals"]
    name = "Test %d (substation %g Ω)" % (i, t["Z_F"])
    results[name] = gf.evaluate(rec, gf.Intervals(b["steady_state"], b["pre_fault"], b["post_fault"]), roles=roles,
                                z_fault_ohm=t["Z_F"])
    measurements.append(dict(name=name, measurement=os.path.splitext(os.path.basename(t["cfg"]))[0], Z=t["Z_F"]))

out = document.campaign_report(results, campaign_folder=campaign, measurements=measurements,
                               info=dict(network="20 kV network of the demo substation", authors=["A. Author"]))
print(os.path.relpath(out["path"], campaign))
print("\n".join(out["placeholders"]))
```

```text
report/Evaluation_of_staged_earth-fault_tests_2026-01-15_Demo.docx
Connection of the additional impedance in the fault circuit
Recording set-up with transient recorder and current clamps in the switchgear
Recommendation for the network area (engineering judgement of the author)
```

The further arguments are the objects of the campaign evaluation: `series` and `comparison` (equivalent sources,
measured and fitted), `monte_carlo` and `loo` (their checks), `Z_E` and `IG`, `scaling` (the keyword arguments of the
scaling, e.g. `PQAssessment.scaling()`), `pq`, `pq_levels` and `pq_comparison` (the PQ measurement and the tests in
its distribution), `earthing` and `reduction` (the comparison with the earthing measurements and the reduction factor
per station), `limits`, `u_tp`, `f_factor`, `uncertainty_I` and `uncertainty_U`. The result names the file, the PDF
(or None), the figures, the placeholders, hints, the test the assessment is based on (`basis`) and `kept` – the earlier
report under its new name if it had been edited (otherwise None).

### Title page and texts: `ReportInfo`

`info` is a [`ReportInfo`](../reference/document.md#groundfault.document.ReportInfo) or a dict with its keys; an unknown
key raises an error. Names of the network, places, persons and the organisation appear **only** as you give them. The
texts may use the mark-up of the report: `**bold**`, `*italic*`, `I_[RES]` (subscript), `^[2]` (superscript) and a
footnote `[^text of the note^]`:

| Key | Meaning |
|---|---|
| `title`, `network`, `subtitle` | title (default: “Evaluation of staged earth-fault tests”), network area, a further line |
| `authors`, `organisation`, `date`, `version`, `further_info` | title page (date default: today) |
| `places` | display name per measuring point (site folder of the recordings), e.g. `{"SUB": "Substation North"}`; default: the location of the sites file, else the folder name |
| `timezone` | time zone of the times in the report, e.g. `"Europe/Berlin"` (the recorder clock is taken as UTC) |
| `purpose`, `normal_state`, `coil_unchanged`, `auto_tuning`, `procedure`, `notes` | texts of chapter 1 |
| `instrument`, `transducers`, `uncertainty_components` | recorder, transducer per channel role (without: the table of measured quantities has no column for them), accuracy of every device of the measuring chain in % |
| `quantity_labels` | own name of a measured quantity per key of that table (`"u_le"`, `"i_res"`, `"i_coil"`, `"i_shield"`, `"i_pen"`, `"u_e"`, `"u_t"` …), e.g. `{"i_shield": "shield current of a parallel feeder"}` |
| `coil_controller` | display of the coil controller read before the tests: `ice_A` (I_CE), `coils_A` (current per coil), `detuning_pct` (v in %, v > 0: overcompensation), `active_A`, `when` – I_CE is `ice_A` or I_L/(1 + v); it replaces the sum of the measured coil currents as I_CE of damping and detuning, and the report compares the measured values with the display |
| `limit_A` | limit of the residual current of the network (default: the first of `limit_cases`, else the smallest of `limits`) |
| `limit_cases` | limits with their conditions on the earthing systems, `[{"limit_A": 60, "Z_E": 2.5}, {"limit_A": 90, "Z_E": 1.7, "condition": "all Z_E < 1.7 Ω"}, {"limit_A": 120, "Z_E": 2.5, "r": 0.5, "condition": "fully cabled, r ≥ 0.5 everywhere"}]` – see below |
| `Z_E_basis` | where Z_E of the assessment comes from, e.g. “design value of the earthing systems of the network” (a footnote to the result at Z_E) |
| `assessment` | decisive value: `"Z_E"` (at the earthing impedance, with the equivalent sources), `"busbar"` (the largest test) or `"auto"` (Z_E if given) |
| `expansion` | network expansion (3.3): `True` (default; planned values 1.25, 1.5 and 2 times I_CE of today), `False` (left out) or a dict – `I_CE` (planned capacitive earth-fault current in A, one value or a list, e.g. `800`), `damping_added` (damping I_w/I_C of the new cables; default that of the network), `c1_ratio` (C_1/C_E of the new cables; default 1, cables with a screen per core), `I_L_max` (largest current of the coils in A: the report says where their range ends), `I_CE_max` (end of the curve in A; default four times today), `zero_sequence` (`"coil"`: the source of the zero-sequence orders grows with the current of the coils – default; `"network"`: not) – see below |
| `reference_frequency_Hz`, `r_flat` | frequency of Z_E of the earthing measurement in the cases 1 and 2 of the touch voltage (default 50 Hz; not measured there: interpolated linearly between the neighbouring frequencies), flat reduction factor of case 2 (without: case 2 is left out) |
| `station_detail` | `"full"` (default) or `"compact"`: a station shown for information only – waveforms, earth potential rise per order, the probes in one sentence, Z_E at 50 Hz and the approaches to the touch voltage, without the comparison with the earthing measurement, the reduction factor, the LV network and their notes |
| `recommendation` | your recommendation (paragraphs separated by a blank line; without: a highlighted placeholder) |
| `key_results`, `appendix`, `waveforms`, `threshold_A` | parts of the report, smallest current of an order in the tables |
| `equations` | the displayed formulas as Word equations (Office Math, editable in the equation editor; default) – words between them (“with”, a remark in parentheses) stay normal text; `False`: the formulas as text |

### Photos

`photos` maps the slots `"setup_impedance"`, `"recorder"` and `"station"` (or `"station:<test>"` per station) to a
file – relative paths are taken in the media folder of the campaign – or to `{"path": …, "caption": …}`; `False` leaves
a photo out. A slot without a photo is a framed placeholder with its caption, so the numbering of the figures stays
the same when you insert the photo in Word. `"extra"` adds further photos: `[{"path": …, "caption": …, "section":
"1.1"}]`.

### Template of your organisation

`template` is a Word file whose styles, page layout, headers, footers and logo the report uses; its content is
replaced. `document.make_template(report, target)` turns an earlier report into such a template (the body and the
document properties are removed). If the template numbers its headings, its numbering is kept; otherwise the report
adds 1, 1.1, 1.1.1. `styles` maps the parts of the report to the style names of the template – the keys `title`,
`subtitle`, `carried_out`, `toc_heading`, `body`, `caption`, `table`, `list_bullet`, `list_number`, `list_paragraph`,
`heading1` … `heading3`:

```python
out = document.campaign_report(results, campaign_folder=campaign, template="report_template.docx",
                               styles={"title": "Title with frame", "subtitle": "Subtitle", "table": "Table Grid"})
```

### Layout

The report is set as a scientific report – in the neutral layout and on top of a template:

* **Body text** justified, in a paragraph style of its own (`body`, default “Body Text”: created on the default style
  of a template that has none, with 6 pt between the paragraphs if the template sets no spacing), with widow and
  orphan control; automatic hyphenation (unless the template switches it off) in the language of the report – the
  text is marked de-DE or en-GB, so that Word checks the spelling and hyphenates in that language.
* **Lists** indented: the number or bullet at 0.63 cm, the text at 1.27 cm – with the list styles of the template
  (`list_bullet`, `list_number`) or, if it has none, with a numbering of its own in the style `list_paragraph`; every
  numbered list starts at 1.
* **Captions** centred, in the size of the body text (style `caption`): the title of a table above it, the caption of
  a figure below it, each with a blank line to the text.
* **Displayed formulas** centred, with a blank line to the text above and below (one between two formulas).
* **Footnotes** for sources and side remarks: the formats and standards (COMTRADE, the 10-min values of the PQ
  measurement), the software, where the accuracies of the measuring chain come from, the earthing measurement of a
  station, the errors of the Monte Carlo simulation, the leave-one-out and where Z_E comes from (`Z_E_basis`). Your
  own texts can have footnotes as well, e.g. in `REPORT["notes"]`:

```python
REPORT = dict(network="20 kV network of substation North", authors=["A. Author"],
              notes=["Two unplanned earth faults occurred before test 1[^Visible in the 30-s values of a further "
                     "power-quality measurement of the busbar.^]."])
```

In Word everything is a style or a paragraph setting you can change: e.g. the style “Body Text” (German Word:
“Textkörper”) for the alignment and the spacing of all body text, the style of the captions for their size.

### Language

`language="de"` or `"en"` (default: the output language, [`i18n.set_language`](../reference/i18n.md)). The texts, the
captions (“Figure”/“Abbildung”), the axis labels of the figures and the number format follow it; the figures are saved
as PNG in `<campaign>/figures/report` (German layout `3_Abbildungen/Bericht`). Texts stored in the result files –
findings of the plausibility checks, hints – keep the language of the evaluation.

## What the numbers are

* **Assessment values** carry the margins of the measurement uncertainty: every current I·(1 + m_I); an order scaled
  with a measured voltage level of the tests k_m/(1 − m_U) – in the single tests (3.1) and at Z_E (3.2) alike. The
  report applies its own margins (`uncertainty_I`, `uncertainty_U`; default: those stored in the results) to every test;
  appendix B says whether they agree with those of the single evaluations. The symbols keep the values apart:
  I_RES,max is the residual current with the scaled harmonic content without the margins, I_RES,ass (German
  I_RES,Bew) the assessment value – of a test or at Z_E.
* **Voltages of the scaling**: U_95,m is the quantile of the largest phase of the PQ measurement; U_m in k_m is the
  positive- or negative-sequence component of the order in the test (mean of before and after the fault) – never
  larger than the largest phase, so k_m is on the safe side of the ratio of the largest phases that the table of the
  tests in the PQ distribution shows. The source voltage U_q,m of the measured source is the same component at the
  faulted phase (median of the tests).
* **Scaling to the PQ measurement**: with a valid PQ measurement every test is scaled again with the quantiles and the
  factor of that measurement ([`evaluation.rescale_harmonics`](../reference/evaluation.md#groundfault.evaluation.rescale_harmonics))
  – also when its single evaluation used other settings (appendix B names the difference); a station test only if its
  single evaluation was scaled.
* **Decisive value**: the largest scaled assessment value of the substation tests (fault at the busbar) or the value at
  the earthing impedance Z_E of the equivalent sources (faults at installations in the network); the summary and the
  key results name it.
* **Limits with their conditions** (`limit_cases`, 3.2): a limit usually stands for a condition on the earthing
  systems – the earth potential rise U_E = r·I_RES·Z_E may not exceed F·U_Tp. The residual current falls with Z_E,
  U_E rises with it, so every case is assessed at its largest earthing impedance: I_RES,ass(Z_E) from the equivalent
  sources (without them: the busbar value, an upper bound) against the limit, and U_E = r·I_RES,ass·Z_E against
  F·U_Tp. The case with `limit_A` applies; the other cases hold only if their condition is met. The figure of I_RES over
  Z_E marks on the line of a limit the Z_E of its condition and adds the assessment value (with the margins).
* **Network expansion** (3.3): can further cables be connected at the substation? The equivalent sources are
  converted to a network with more cable and the coils retuned to the same detuning
  ([Network expansion](../methods/equivalent-source.md#network-expansion)): per order the added earth and operating
  capacitance in parallel with Z_0 and Z_1, the source voltage of the busbar with the busbar impedance, the
  fundamental with the damping of the new cables. I_CE of today and the coil current are those of the coil controller
  (`coil_controller`) or the measured coil currents, the damping that of the tests. The split of Z_q into Z_0 and
  Z_1 is taken from network data and from the busbar voltages of the tests; the larger residual current of the two
  decides (the table of uncertainties gives both). For every limit case – at its Z_E, with the smaller of the limit
  and F·U_Tp/(r·Z_E) – the report gives the I_CE at which the residual current reaches it, and at the planned I_CE
  the fundamental, the harmonic content, the proportional estimate (every part growing like I_CE) and per order the
  factor of the source voltage. It assumes no new harmonic sources with the cables and the scaling of 3.1 unchanged.
* **Context** where a reader would ask: the factors k_m of the scaling are classified by the percentile of the tests in
  the PQ measurement and the median of the dominant order on the weekday of the tests and over the week; a station
  with a larger harmonic current than the busbar test is explained by its larger voltage before the fault (active
  two-terminal network, current per volt smaller); much larger even orders of one test and their decay in the steady
  state are named; a change of the reactive current between the tests at an equal active current is noted – if the
  coil current balance of every single evaluation gives ΔIv/ΔΣI_L ≈ 1 (the coil currents change by the same amount at
  a constant U0), the coils were adjusted during the fault and the network stayed the same; the uncertainty table
  names the orders that change by more than 20 % over the windows of the steady state.
* **Touch voltage** per station, U_T = r·I·Z_E/F = U_E/F, by four approaches
  ([`document.touch_voltage_cases`](../reference/document.md#groundfault.document.touch_voltage_cases)): 1 the limit
  current with r = 1 and Z_E of the earthing measurement, 2 the same with a flat r, 3 per frequency with r·Z_E of the
  earth-fault test and the assessment current per order of the decisive test, 4 the measured earth potential rise and
  4b the same extrapolated to the limit current – and the measured touch voltage of a probe. The permissible earthing
  impedance follows as F·U_Tp/(r·I_RES,ass). The cases 3 and 4 use the earth-potential probe (role `u_e`), the
  reduction factor of the earthing comparison the probe maximum (all probes); a touch-voltage probe that reads more than
  the earth-potential probe – U_T > U_E, physically inconsistent – is named in the text and flagged in appendix B, as
  are the notes of the earthing comparison (r outside the expected range, shield current nearly zero, Z_E of the LV
  network below the earthing impedance).
* **Checks of the equivalent sources** (appendix B): I_RES at the impedances of the tests (dominated by the
  fundamental), the residual of the currents per order and the leave-one-out per order – the last two show how well the
  harmonic model itself fits.
* **Uncertainties** (3.4): the measuring chain, the steady state of the fault (spread of I_RES over the windows), the
  differences between the tests, the model of the equivalent sources (Monte Carlo band with the fundamental of the
  report, leave-one-out), the sample of the PQ measurement (bootstrap over days,
  [`PQAssessment.quantile_bootstrap`](../reference/pq.md#groundfault.pq.PQAssessment.quantile_bootstrap)), with
  several measuring periods (e.g. exports of different seasons) I_RES(Z_E) scaled with each period alone
  ([`PQAssessment.periods`](../reference/pq.md#groundfault.pq.PQAssessment.periods)) – section 2.4.1 then names the
  periods and the quantile of the dominant order per period against the assessment voltage –, the method
  of the scaling ([`PQAssessment.scaling_methods`](../reference/pq.md#groundfault.pq.PQAssessment.scaling_methods)) and
  the range of the equivalent sources – each with what it amounts to and whether it is part of the assessment value.
* **Reproduction**: with the raw recordings in the campaign folder every test is evaluated again with the settings of
  its result file (waveforms, fault inception and clearance, duration); appendix A shows the largest deviation from the
  stored values.
* **References**: the key results give the section of every value; figure and table numbers in the text are those of
  the report as written (Word fields number the captions).

## Word, LibreOffice and PDF

The contents, the figure and table numbers and the page numbers are Word fields; Word updates them when the file is
opened (confirm the question). The displayed formulas are Word equations; LibreOffice shows them with its Math
component (in Linux distributions often a package of its own, e.g. `libreoffice-math`). `pdf=True` (notebook: `REPORT_PDF`) or `document.to_pdf(path)` writes a PDF with
LibreOffice if it is installed. A template made for Word may look different in LibreOffice – fonts that are not
installed are replaced, fields in headers and footers or frames can be drawn differently, and LibreOffice hyphenates
only with the hyphenation patterns of the language installed (e.g. `hyphen-de`); save the PDF from Word for the final
version.
