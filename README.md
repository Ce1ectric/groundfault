# groundfault

[![Tests](https://github.com/Ce1ectric/groundfault/actions/workflows/tests.yml/badge.svg)](https://github.com/Ce1ectric/groundfault/actions/workflows/tests.yml)
[![Docs](https://github.com/Ce1ectric/groundfault/actions/workflows/docs.yml/badge.svg)](https://github.com/Ce1ectric/groundfault/actions/workflows/docs.yml)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)
[![Python ≥ 3.10](https://img.shields.io/badge/python-%E2%89%A5%203.10-blue.svg)](https://www.python.org/downloads/)

**Evaluation of staged earth-fault tests in compensated (resonant-earthed) medium-voltage networks.**

groundfault reads the COMTRADE recordings (IEEE C37.111) of staged earth-fault tests – at the substation and at
secondary substations – and computes what is needed to assess the residual earth-fault current and the earthing
systems of a resonant-earthed network: assessment quantities with measurement uncertainty, harmonics and voltages,
the residual current at any earthing impedance from a series of tests, the earth potential rise and touch voltage per
frequency, the current into the LV network and the reduction factor compared with earthing measurements. All
algorithms live in a Python package; Jupyter notebooks serve as the user interface – two for the evaluation, two for
the optional forecast. Output is available in English and German, and a synthetic demo campaign lets everything run
without measurement data.

![Reduction factor over the frequency of the demo station from a staged fault test and an earthing measurement (top)
and the two compared quantities r·Z_E and Z_E (bottom)](docs/assets/station_reduction_factor.png)

## Features

- **Substation** – residual earth-fault current as the true RMS value of the largest 200-ms window, its fundamental
  component and harmonics, active and detuning current (angle method), measurement uncertainty, voltages before,
  during and after the fault (sequence components, THD), plausibility checks for every recording. Disturbed states
  during the fault – a network section that trips, a short active residual current increase for fault location – are
  detected and left out of the reference.
- **Equivalent-source method** – over a series of tests with different fault impedances, an active two-terminal
  equivalent per harmonic order and from it the residual current at any earthing impedance Z_E.
- **Transformer node** – with the line currents of the HV/MV transformer: power and apparent impedance per harmonic
  order and sequence before, during and after the fault, and the upstream impedance of transformer and HV network per
  order from the fault-related change (split into both with HV voltages); the polarity of the current transformers
  follows from it.
- **Forecast (optional)** – `groundfault.forecast`, not loaded by `import groundfault`: the harmonic residual current
  of a future earth fault from the harmonic voltages of a power-quality measurement, arranged by methods. **Without an
  earth fault** (V0 to V3): estimates from network data and the MV network measured in undisturbed operation at the
  transformer, with the HV voltage as instrumental variable – with the angle correction of the current transformers
  and the share of the HV-driven variation as the check of every recording. **With staged tests and recorded earth
  faults** (V4 to V7): a network model of the earth-fault loop at a busbar per harmonic order, calibrated with the
  tests and updated with every earth fault recorded there (busbar voltages; with the coil currents also the fault
  current per order, by the node rule of the zero sequence), with the harmonic currents that saturating coils and
  transformers add during the fault separated; it forecasts at the busbar or behind a line and checks itself between
  the tests, at recorded earth faults and with tests in the network.
- **Secondary substations** – earth potential rise and touch voltage per frequency, as measured and as the
  fault-related component (superposition removes the background present before the fault); PEN currents give the
  current into the LV network and the earthing impedance of the LV network.
- **Earthing measurements** – reduction factor r = r·Z_E / Z_E per harmonic, over the frequency with a trend, and as
  an RMS value compared with the earthing measurements in a [groundmeas](https://github.com/Ce1ectric/groundmeas)
  SQLite database; evaluated tests can be entered in groundmeas.
- **Report output** – figures in their final size for an A4 report (PDF/SVG/PNG) and tables as CSV, Markdown, Excel
  and Word.
- **Signal explorer** – all channels of a recording with RMS values, harmonics and THD on hover, in the notebook and
  as a single HTML file that opens in any browser.
- **English and German** – output language and campaign folder layout; the files of the in-house predecessor
  (version 1.x) are read as well.
- **Validated** – every numerical method is tested against an exact synthetic solution or a second method; on field
  recordings of several campaigns groundfault reproduces the results of its in-house predecessor exactly with the same
  parameters (all numerical results identical).
- **No built-in limits** – limits of the residual current, the permissible touch voltage, the factor F,
  measurement-uncertainty margins and safety factors are parameters that you define; the package contains only the
  methods.

## Installation

groundfault needs Python 3.10 or newer and runs on Windows, macOS and Linux. For scripts, install it with all optional
features of the library directly from GitHub (for the notebooks, see [below](#notebooks)):

```bash
pip install "groundfault[all] @ git+https://github.com/Ce1ectric/groundfault"
```

Or clone the repository and install it in editable mode – then the notebooks, the tools and the tests are at hand as
well:

```bash
git clone https://github.com/Ce1ectric/groundfault.git
cd groundfault
pip install -e ".[dev]"
```

Use a virtual environment for either way. The optional features are grouped as extras:

| Extra | Installs | Needed for |
|---|---|---|
| `interactive` | plotly, ipywidgets, jinja2 | interactive figures and the signal explorer |
| `export` | openpyxl, python-docx | the Excel and Word files of the exported tables |
| `all` | `interactive` + `export` | everything the package can do – the usual choice for scripts |
| `notebook` | `interactive` + `export`, JupyterLab, ipykernel | working with the notebooks |
| `dev` | `interactive` + `export`, pytest, ruff, nbformat, nbclient, ipykernel | tests, linting, regenerating the notebooks |
| `docs` | mkdocs-material, mkdocstrings[python], ruff | building the documentation |

The [installation guide](https://ce1ectric.github.io/groundfault/getting-started/installation/) shows a setup with
[uv](https://docs.astral.sh/uv/), the Jupyter kernel and the optional groundmeas database.

## Quick example

The demo campaign of `groundfault.demo` contains synthetic recordings with a known solution, so this example runs
without any measurement data:

```python
import os, tempfile
import groundfault as gf
from groundfault import demo

d = demo.make_campaign(tempfile.mkdtemp(), layout="en")              # synthetic campaign, known solution
rec = gf.open_recording(os.path.join(d["campaign"], "raw/SUB/SUB_0_10_000kHz.cfg"))
res = gf.evaluate(rec, gf.Intervals(steady_state=(2.6, 4.4), pre_fault=(0.2, 1.8), post_fault=(7.0, 8.8)),
                  z_fault_ohm=0.0)
print(res.summary())
print(res.table("assessment_quantities")[["quantity", "measured_value", "assessment", "unit"]].round(2).head(3))
```

```text
Measurement: SUB_0_10_000kHz  (SUB_0_10_000kHz.cfg)
Max window: 4.300 s  | f1 = 50.0200 Hz (phase)
IRES = 56.53 A | IG = 32.01 A | Iw = 20.00 A | Iv = 25.00 A | IH = 46.59 A
  quantity  measured_value  assessment unit
0     IRES           56.53       56.53    A
1       Iw           20.00       20.00    A
2       Iv           25.00       25.00    A
```

The demo network was generated with an active residual current of 20 A and a detuning of 25 A – the evaluation finds
both. The column `assessment` adds a measurement-uncertainty margin of your choice (`gf.Settings(uncertainty_I=…,
uncertainty_U=…)`); groundfault contains no margins, limits or safety factors – you define them – so here it equals
the measured value. The [quickstart](https://ce1ectric.github.io/groundfault/getting-started/quickstart/) continues
this example through the whole workflow: equivalent-source method, station, reduction factor, figures, tables and
signal explorer.

## Notebooks

Two Jupyter notebooks are the user interface: `evaluate_measurement.ipynb` for one recording and
`evaluate_campaign.ipynb` for a campaign (German: `Messung_auswerten.ipynb`, `Kampagne_auswerten.ipynb`); the optional
forecast has two more in the sub-folder `forecast/`: `forecast_without_fault.ipynb` (V0 to V3) and
`network_model_forecast.ipynb` (V6, V7) (German `Prognose/Prognose_ohne_Erdschluss.ipynb`,
`Prognose/Netzmodell_Prognose.ipynb`). The repository contains them in `notebooks/en/` and `notebooks/de/`,
configured for the demo campaign, together with reference copies with placeholders for your own campaigns
(`templates/`, German `Vorlagen/`). The notebooks are generated by `tools/make_notebooks.py`; to try them, write the
examples into an empty folder and open it in JupyterLab (in the clone):

```bash
pip install -e ".[notebook]"
python tools/make_notebooks.py --lang en --out ../groundfault-demo --example --forecast   # German: --lang de
cd ../groundfault-demo
jupyter lab
```

Run `evaluate_measurement.ipynb` and then `evaluate_campaign.ipynb` with *Run → Run All Cells*: the first creates the
demo campaign in the folder and evaluates one recording, the second evaluates the whole campaign;
`forecast/forecast_without_fault.ipynb` evaluates a demo measuring day at the transformer and compares the estimates
without an earth fault, `forecast/network_model_forecast.ipynb` builds the network model of the demo substation and
forecasts its harmonic residual current. How to work with
your own recordings is described in the [user guide](https://ce1ectric.github.io/groundfault/user-guide/notebooks/).

## Languages and folder layouts

Hints, tables, figures and exported files are written in English or German (`groundfault.i18n.set_language("de")`,
the environment variable `GROUNDFAULT_LANGUAGE=de` or `LANGUAGE = "de"` in a notebook), while the API and the result
files always use English names. Campaigns are organised in an English (`campaigns/<campaign>/raw`, `results`,
`figures` …) or a German folder layout (`01_Messkampagnen/<campaign>/1_Rohdaten`, `2_Auswertung`, `3_Abbildungen` …),
which is detected automatically and is independent of the output language.

## Documentation

The documentation at **<https://ce1ectric.github.io/groundfault/>** contains the installation guide, a quickstart
through the whole workflow, the user guide (campaign folders, notebooks, evaluation, stations, earthing measurements,
corrections, reports, troubleshooting), the methods behind every computed quantity and the API reference.

## Development

In the clone, with the `dev` and `docs` extras (`pip install -e ".[dev,docs]"`):

```bash
pytest -q                     # test suite (synthetic recordings only)
ruff check
mkdocs build --strict         # documentation in site/
```

The generated notebooks import their modules after a fallback for an uninstalled clone, hence the two rules ignored
for them in `pyproject.toml`. The continuous integration in `.github/workflows/` runs the same commands: ruff and the
tests with Python 3.10 to 3.14 on Linux, 3.12 on Windows and 3.13 on macOS, the tests with the lowest declared versions
of the dependencies on Python 3.10, and the strict documentation build. Conventions for code, messages in both
languages, docstrings and tests are described in [CONTRIBUTING.md](CONTRIBUTING.md).

## Citing

If you use groundfault in your work, please cite it. The citation metadata are in [CITATION.cff](CITATION.cff);
GitHub offers them as APA and BibTeX under *Cite this repository*:

```bibtex
@software{Ehlert_groundfault_2026,
  author  = {Ehlert, Christian},
  title   = {{groundfault}},
  version = {3.1.0},
  month   = oct,
  year    = {2026},
  url     = {https://github.com/Ce1ectric/groundfault},
  license = {MIT}
}
```

## Licence

groundfault is released under the [MIT licence](LICENSE). Copyright © 2026 Christian Ehlert.
