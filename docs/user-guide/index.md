# User guide

This guide describes the work with groundfault from the raw COMTRADE recordings of a test day to the figures and
tables of the report and the entry of the tests in a groundmeas database. It is written for engineers who carry out
or evaluate staged earth-fault tests in compensated (resonant-earthed) medium-voltage networks: it explains what each
step does, how to read its results and what to do when a check fails. The physics and the numerical methods are
described in [Methods](../methods/index.md), every function in the [API reference](../reference/index.md).

There are two ways of working, and they give the same results:

* **Notebooks** – two Jupyter notebooks are the user interface: `evaluate_measurement.ipynb` for one recording and
  `evaluate_campaign.ipynb` for all recordings of a campaign. You enter a few settings (campaign, file, analysis
  intervals) and run them; see [Notebooks](notebooks.md). The optional [forecast](../forecast/index.md) has a notebook
  of its own.
* **Python** – all computations live in the package; the notebooks only call its functions. Every page of this guide
  shows the corresponding calls, so you can build your own evaluations.

## From the recordings to the report

```text
  raw recordings (.cfg/.dat)  →  campaigns/<date>_<place>/raw/<site>/
            │
  1  campaign folder: register, sites file, corrections file            tools/update_register.py
            │
  2  one recording (evaluate_measurement.ipynb, once per recording)
     open → corrections → channel roles → raw-data diagnostics → RMS trend → analysis intervals
     → evaluate: assessment quantities, plausibility checks, voltages, harmonics
     → station: earth potential rise and touch voltage per frequency, PEN currents, LV network
     → groundmeas: comparison with the earthing measurement, reduction factor
     → signal explorer: check the values at the curves
     → export: <measurement>_result.json, tables, figures, explorer as HTML   ──→  groundmeas entry
            │                                                                     (dry run, then write)
  3  the campaign (evaluate_campaign.ipynb, works on the result files only)
     overview and consistency → equivalent-source method → residual current at Z_E
     → resistive approach → stations → report tables and figures              ──→  groundmeas entries
            │
  4  report (Word/PDF) with the exported figures and tables
```

| Step | What you do | Where | Page |
|---|---|---|---|
| 1 | Sort the recordings into the campaign folder, rebuild the register, check the sites file | file manager, `tools/update_register.py` | [Campaigns, folders and files](campaigns.md) |
| 2 | Note known errors of the measuring chain (CT ratio, polarity, channel roles, probe distances) | `notes/corrections.csv` | [Corrections](corrections.md) |
| 3 | Open a recording, check the channel roles and the raw-data diagnostics, read off the analysis intervals | measurement notebook, sections 1–3 | [Notebooks](notebooks.md), [Evaluating a recording](evaluation.md) |
| 4 | Evaluate: assessment quantities, plausibility checks, voltages, harmonics | section 4 | [Evaluating a recording](evaluation.md) |
| 5 | At a secondary substation: earth potential rise and touch voltage per frequency, PEN currents, LV network | section 4 | [Stations and the LV network](station.md) |
| 6 | Compare with the earthing measurement, reduction factor | section 4 | [Earthing measurements](earthing.md) |
| 7 | Check the numbers at the measured curves | section 5 | [Signal explorer](explorer.md) |
| 8 | Optional checks: network frequency, RMS values of the recorder, resonance curve | section 6 | [Notebooks](notebooks.md) |
| 9 | Export the result file, tables, figures and the explorer; enter the test in groundmeas | section 7 | [Reports and exports](report.md), [Earthing measurements](earthing.md) |
| 10 | Campaign: overview, consistency, equivalent sources, residual current at Z_E, report tables | campaign notebook | [Campaign evaluation](campaign.md) |

Steps 3 to 9 are repeated for every recording. The campaign notebook does not read the raw data again; it works with
the result files of step 9.

## Pages of this guide

* [Campaigns, folders and files](campaigns.md) – folder layout, the names groundfault relies on (sites, files,
  channels), the register, the sites file, notes and read-me.
* [Notebooks](notebooks.md) – the two notebooks, all settings, the checklist per recording, regenerating the
  notebooks.
* [Evaluating a recording](evaluation.md) – opening, channel roles, diagnostics, analysis intervals, `Settings`,
  `evaluate` and its result, the result file.
* [Stations and the LV network](station.md) – probes and touch voltage, direct and fault-related values, uncertainty,
  extrapolation, PEN currents and the earthing impedance of the LV network.
* [Earthing measurements (groundmeas)](earthing.md) – reading the database, comparison, reduction factor, entering a
  staged fault test.
* [Campaign evaluation](campaign.md) – overview, consistency, equivalent-source method, residual current at the
  earthing impedance, resistive approach, report tables.
* [Signal explorer](explorer.md) – all channels with RMS values and harmonics on hover, in the notebook and as an HTML
  file.
* [Corrections of the measuring chain](corrections.md) – the corrections file and its Python interface.
* [Reports and exports](report.md) – figures, tables and interactive figures.
* [Language and folder layout](language.md) – English and German output, folder layouts, files of the predecessor
  tool.
* [Troubleshooting](troubleshooting.md) – messages and what to do.

The forecast of the harmonic residual current from the staged tests and the earth faults recorded at a busbar is an
optional part with its own section: [Forecast](../forecast/index.md).

## Trying it with the demo campaign

All examples in this guide use the demo campaign of `groundfault.demo`: synthetic recordings with a known solution,
no measurement data. It contains a substation series with the additional impedances 0, 2.5 and 5 Ω, one secondary
substation with probes, shield and PEN currents, and a small groundmeas database with an earthing measurement of that
station.

```python
import os
import tempfile

from groundfault import demo

base = tempfile.mkdtemp()                       # work folder
d = demo.make_campaign(base, layout="en")       # campaign "2026-01-15_Demo" and demo_groundmeas.db
print(os.path.relpath(d["campaign"], base))
for w in d["substation"]:
    print(w["cfg"], "–", w["Z_F"], "Ω")
print(d["station"]["cfg"], "and", d["station"]["rms_cfg"])
```

```text
campaigns/2026-01-15_Demo
raw/SUB/SUB_0_10_000kHz.cfg – 0.0 Ω
raw/SUB/SUB_2_5_10_000kHz.cfg – 2.5 Ω
raw/SUB/SUB_5_10_000kHz.cfg – 5.0 Ω
raw/Station_Elm_Road/Station_Elm_Road_10_000kHz.cfg and raw/Station_Elm_Road/Station_Elm_Road_10_000Hz.cfg
```

Next to every instantaneous-value recording lies a file `<name>_truth.json` with the true values and the analysis
intervals; the example campaign notebook uses it to evaluate the demo recordings without any input. The output
language of all examples is English; German output is described in [Language and folder layout](language.md).
