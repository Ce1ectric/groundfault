# Notebooks

Two Jupyter notebooks are the user interface of groundfault. All computations are in the package; the notebooks only
collect the settings, call the functions and show tables and figures.

| Notebook (English / German) | Purpose |
|---|---|
| `evaluate_measurement.ipynb` / `Messung_auswerten.ipynb` | one recording: channel roles, raw-data diagnostics, RMS trend, evaluation, station and earthing measurement (groundmeas), signal explorer, checks, export |
| `evaluate_campaign.ipynb` / `Kampagne_auswerten.ipynb` | a campaign: overview and consistency, equivalent-source method, residual current at the earthing impedance, resistive approach, stations, report tables and figures, entries in groundmeas |

The English notebooks are in `notebooks/en/`, the German ones in `notebooks/de/`. The code cells are identical in
both languages and use the same English variable names (`CAMPAIGN`, `FILE`, `STEADY_STATE` …); comments,
explanations and printed texts follow the language, and so does the output language of tables, hints and figures
(variable `LANGUAGE` in the first code cell, see [Language and folder layout](language.md)).

## Setting up

Install groundfault with the `notebook` extra and register a Jupyter kernel as described in
[Installation](../getting-started/installation.md); then open the notebooks in JupyterLab or VS Code and choose that
kernel. If the package is not installed in the kernel's environment, the first code cell imports it from the source
folder of a clone: it looks in the current folder and every folder above it for `src`, `groundfault/src` or
`*/groundfault/src` – so a clone in `~/src/groundfault` is found from any work folder below the home folder. The
dependencies must be installed in the environment all the same.

Each language folder contains two kinds of notebooks:

* `templates/evaluate_measurement_DEFAULT.ipynb` and `templates/evaluate_campaign_DEFAULT.ipynb` (German:
  `Vorlagen/…_DEFAULT.ipynb`) – **reference copies with placeholders**. Do not edit them.
* `evaluate_measurement.ipynb` and `evaluate_campaign.ipynb` – **examples** configured for the demo campaign.

For a new campaign copy the two reference copies into your [work folder](campaigns.md#the-work-folder) (or a folder
below it) and give them names of your choice. The first code cell finds the work folder by itself – the first folder
upwards from the notebook that contains a campaigns folder – and takes the folder layout from the name of that
campaigns folder; in a folder without one (a new, empty work folder) the layout of `LANGUAGE` is used. It prints a
line such as

```text
groundfault 2.0.0 · work folder: /home/user/earth_fault_tests · layout: en · font of the figures: Liberation Sans
```

One copy of the measurement notebook is enough for all recordings of a campaign: for the next recording change
`FILE`, `Z_FAULT` and the intervals. Every recording gets its own result and figure folders, and the chosen intervals
are written to the register. Keep one copy per recording only if you want to keep each notebook with its outputs.

**Trying the demo:** copy the two example notebooks into an empty folder and run them (*Run → Run All Cells*). With
`DEMO = True` the measurement notebook creates the demo campaign `campaigns/2026-01-15_Demo` and the database
`demo_groundmeas.db` in that folder and evaluates `SUB_0_10_000kHz.cfg`; the campaign notebook evaluates the other
demo recordings with their known intervals and the corrections of the campaign and continues with the campaign
evaluation. The demo changes nothing outside its campaign folder, so it is also safe in a real work folder: the
database and the register are only created if they do not exist yet – the register only in a work folder without
other campaigns – and the notebook records no intervals in the register.

## The measurement notebook

The notebook has seven sections; you work through them from top to bottom.

| Section | What you do |
|---|---|
| 1 · Configuration | enter campaign, file and additional impedance; leave the intervals at `None` the first time |
| – | run all cells (*Run → Run All Cells*) |
| 2 · Open the file, channel roles, raw-data diagnostics | check the roles (✓ marks the main channel of each role), the probe distances and the diagnosis |
| 3 · RMS trend – read the analysis intervals | read off the steady-state, pre-fault and post-fault intervals, enter them in section 1, run all cells again |
| 4 · Evaluation | read the summary, the hints, the assessment quantities and the plausibility checks; at a station also the evaluation per frequency, the LV network and the comparison with groundmeas |
| 5 · Signal explorer | check the values at the measured curves (works before the intervals are entered) |
| 6 · Checks (optional) | network frequency, comparison with the RMS export of the recorder, resonance curve |
| 7 · Export | result file, tables, figures and explorer HTML are written; read the groundmeas dry run and enter the test on request |

Until `STEADY_STATE` is set, section 4 shows “➜ First enter `STEADY_STATE` (and `PRE_FAULT`/`POST_FAULT`) in section 1
and run again.” and nothing is exported. What the sections compute is described in
[Evaluating a recording](evaluation.md), [Stations and the LV network](station.md),
[Earthing measurements](earthing.md), [Signal explorer](explorer.md) and [Reports and exports](report.md).

### Settings in section 1

The configuration cell is divided into blocks. The defaults below are those of the reference copies.

Every value is checked where it is used – by the function it is passed to, or by the notebook itself
(`GROUNDMEAS_EXPORT`, `RESISTIVE`, `MEASUREMENTS`, `IG_CHOICE`). Text values are English: a misspelt value or key, or
one of the predecessor tool copied from an old notebook (`"mittel"`, `"spektral"`, `"ersetzen"`, the key `aus_ll` …),
stops the cell with an error that names the allowed values and the current name instead of being ignored, e.g.

```text
ValueError: GROUNDMEAS_EXPORT='ersetzen' is not allowed – allowed: False, True, 'replace' ('ersetzen' is the former name of 'replace')
```

**Measurement**

| Variable | Default | Meaning – when to change |
|---|---|---|
| `CAMPAIGN` | `"YYYY-MM-DD_Place"` | campaign folder in the campaigns folder, e.g. `"2026-01-15_Demo"` |
| `FILE` | `"raw/<site>/<file>.cfg"` | `.cfg` file relative to the campaign folder – the instantaneous values (`…_10_000kHz.cfg`), not the RMS export |
| `MEASUREMENT` | `None` | name of the result and figure folders and file prefix; `None` = file name without extension |
| `Z_FAULT` | `0.0` | additional impedance in the fault branch in Ω (substation tests, e.g. 0 / 2.5 / 5); `None` at a station |
| `DEMO` | `False` | `True`: create the demo campaign if it does not exist yet; nothing outside the demo campaign folder is changed |
| `STEADY_STATE` | `None` | steady-state fault `(t0, t1)` in s – after the transient, before an active residual current increase |
| `PRE_FAULT` | `None` | operation without fault before the fault `(t0, t1)` |
| `POST_FAULT` | `None` | operation without fault after the decay of the neutral displacement voltage `(t0, t1)` |

Set the three intervals back to `None` when you switch to the next recording; how to choose them is explained in
[Evaluating a recording](evaluation.md#choosing-the-analysis-intervals).

**Limits, margins and factors – defined by you.** groundfault contains no limits, safety factors or
measurement-uncertainty margins; this block collects them in one place. Take them from the operator's specification,
the applicable standard or the accuracy of your measuring chain. Not set (the defaults), the parts that need them are
skipped and the notebook prints a short note (ℹ) that names the variable.

| Variable | Default | Meaning – what needs it |
|---|---|---|
| `LIMITS` | `()` | limits of the residual current in A, e.g. `(I_1, I_2)` (`Settings.ires_limits`): extrapolation of the station voltages; the largest is the reference current of the reduction factor |
| `U_TP` | `None` | permissible touch voltage U_Tp in V (`Settings.u_tp`) |
| `F_FACTOR` | `None` | factor F of the permissible earth potential rise F·U_Tp (`Settings.f_factor`); with `U_TP` the relevance of the reduction factor for the assessment |
| `REFERENCE_CURRENT` | `None` | reference current of the reduction factor in A; `None` = the largest of `LIMITS`. Without both, the relevance is “–” |
| `UNCERTAINTY_I`, `UNCERTAINTY_U` | `0.0` | measurement-uncertainty margins m_I and m_U as fractions (`Settings.uncertainty_I`, `uncertainty_U`): assessment value = measured value × (1 + m_I) for currents, × (1 − m_U) for voltages; `0.0` = no margin |
| `PQ_SAFETY_FACTOR` | `1.0` | factor k_s on the 95 % quantile of a power-quality measurement (`Settings.pq_safety_factor`); `1.0` = no factor |
| `R_TYPICAL` | `None` | range `(low, high)` of the reduction factor at 50 Hz that you expect, e.g. from your own experience; `None` = no classification |

The values that become settings are stored in the result file; the campaign notebook takes U_Tp, F and the largest
limit for the reduction factor from there unless its own variables are set.

**Evaluation parameters** – `SETTINGS = gf.Settings(…)`; the notebook shows the fields you are most likely to change,
all fields are listed in [Evaluating a recording](evaluation.md#settings). The margins, the safety factor, the limits,
U_Tp and F come from the block above.

| Field | Default | Meaning – when to change |
|---|---|---|
| `T_win` | `0.200` | window length in s; the hop equals the window length. Change only for good reasons |
| `harmonics` | `(1, 3, 5, 7)` | orders of the assessment quantities; the result file stores the orders 1 to 25 regardless (for the equivalent-source method) |
| `u_thd95_percent` | `None` | 95 % quantile of the line-to-line THD of a power-quality measurement in %; adds the rows scaled to it to the assessment quantities (needs the voltages before or after the fault) |
| `correct_polarity` | `True` | if the active component Iw is negative (reversed clamp), rotate the current phasors by 180°. Set `False` only if the hint “Polarity decision uncertain” appears and the polarity of the clamp is known for sure |

**Channels** – only if needed. Permanent corrections belong in the [corrections file](corrections.md); these
variables apply to the current run only.

| Variable | Default | Meaning – when to change |
|---|---|---|
| `APPLY_CORRECTIONS` | `True` | apply `notes/corrections.csv`; `False` shows the raw data without corrections (for comparison) |
| `ROLE_OVERRIDES` | `{}` | fix roles for this run, e.g. `{"U1": "u_l1e"}`; `{"ISp22": None}` ignores a channel. Role codes: [corrections page](corrections.md#role-codes) |
| `MAIN_CHANNEL` | `{}` | main channel of a role, e.g. `{"i_res": "IF2"}`; default: `IF` before `IF1` before `IFr` with the largest range |
| `ALIGNMENT` | `None` | time offset between subsystems of the recorder, e.g. `dict(roles=["u_l1e", "u_l2e", "u_l3e"], dt_s=1.5)` – take the suggestion of the diagnosis, after trying a new export of the file |
| `FS_OVERRIDE` | `None` | enforce a sampling rate in Hz – only if the diagnosis reports a defective time base |

**Checks and export**

| Variable | Default | Meaning – when to change |
|---|---|---|
| `RMS_FILE` | `None` | RMS export of the recorder for the check in section 6, e.g. `"raw/Station_Elm_Road/Station_Elm_Road_10_000Hz.cfg"` |
| `V_CURVE` | `False` | `True`: trend of the fundamental component over the steady-state interval and resonance curve – useful if the coil was adjusted during the fault; the figure is exported as well |
| `SHOW_ENVELOPE` | `False` | `True`: also the envelope of the instantaneous values of the whole recording in section 3 |
| `EXPORT_FORMATS` | `("pdf", "svg", "png")` | file formats of the figures |
| `RECORD_INTERVALS` | `True` | write the chosen intervals to the register of the work folder (not with `DEMO = True`) |

**Signal explorer and earthing measurement**

| Variable | Default | Meaning – when to change |
|---|---|---|
| `SIGNAL_EXPLORER` | `True` | show the [signal explorer](explorer.md) in section 5 |
| `EXPLORER_HTML` | `True` | also write the explorer as an HTML file that opens in a browser without Python |
| `GROUNDMEAS_DB` | `None` | path of the groundmeas database; `None` = as groundmeas finds it ([details](earthing.md#where-the-database-is)). The example notebook uses the demo database |
| `GROUNDMEAS_LOCATION` | `None` | exact location name in groundmeas; `None` = from the sites file, otherwise from the folder name |
| `GROUNDMEAS_MEASUREMENTS` | `None` | compare only these groundmeas measurement ids, e.g. `[3, 21]`; `None` = all measurements of the location |
| `GROUNDMEAS_EXPORT` | `False` | `True`: enter the test in groundmeas (after a backup copy); `"replace"`: renew the own entry. Set it back to `False` afterwards |
| `GROUNDMEAS_UNCERTAIN` | `"mark"` | uncertain fault-related values: `"mark"` (entered with a remark) or `"omit"` |
| `GROUNDMEAS_UNITS` | `"suitable"` | `"suitable"`: a readable unit per quantity (mV, mA …, needs groundmeas ≥ 1.6.1); `"base"`: V and A |
| `GROUNDMEAS_DESCRIPTION` | `""` | text placed before the automatic description of the entry (English, like the other entries) |
| `GROUNDMEAS_TIMEZONE` | `None` | time zone of the recorder clock if it is not UTC, e.g. `"Europe/Berlin"` |
| `GROUNDMEAS_TIMESTAMP` | `None` | only for a wrongly set recorder clock: start of the recording in UTC, `"YYYY-MM-DD hh:mm:ss"` |

### Section 6: optional checks

* **Network frequency** – the spectrum of the reference voltage around 50 Hz with the frequency f1 used by the
  evaluation (dashed); the peak should lie on it.
* **RMS values of the recorder** – with `RMS_FILE` set, the own true RMS values are compared with the RMS export of the
  recorder (the corrections of the campaign are applied to both files; hints on the RMS file, e.g. that a polarity
  correction has no effect on RMS values, are printed). Deviations come mainly from DC offsets of the clamps: the
  recorder includes the DC component, the evaluation removes it. The column `note` names the cause where it can (DC
  component, a scaling by a power of ten) or says that the deviation is unexplained.
* **Resonance curve** – with `V_CURVE = True`, the fundamental component of the fault current over the steady-state
  interval and its smallest value (measured and from a fitted parabola).

### Checklist per recording

1. *Configuration:* `CAMPAIGN`, `FILE`, `Z_FAULT` entered, intervals `None` → *Run All*.
2. *Open the file, channel roles:* roles correct, main channel (✓) correct, probe distances present, diagnosis
   “✓ no anomalies” – otherwise complete the [corrections file](corrections.md) and run again.
3. *RMS trend:* intervals read off and entered in section 1 → *Run All*.
4. *Evaluation:* plausibility checks all `OK` (or understood), hints (⚠) read; at a station uncertain frequencies (⊗)
   noted, groundmeas location and `distance_match` plausible.
5. *Signal explorer:* max window looked at – curves without saturation, steps or clipped channels.
6. *Export:* result file and figures written, “Register updated” printed; groundmeas dry run read. Enter the test
   only deliberately (`GROUNDMEAS_EXPORT = True`, afterwards `False` again).
7. Next recording: change `FILE` and `Z_FAULT`, set the intervals back to `None` → step 1.

## The campaign notebook

The campaign notebook works only with the **result files** of the measurement notebook
(`results/<measurement>/<measurement>_result.json`); the raw data are not read again. Evaluate every recording first.

| Section | What you do |
|---|---|
| 1 · Configuration | enter the campaign and the list of measurements |
| 2 · Load the results – overview and consistency | run all cells; check the overview, the consistency checks and the hints of the single measurements |
| 3 · Equivalent-source method | check the two-terminal equivalents per order and the checks (substation measurements) |
| 4 · Residual current at the earthing impedance and resistive approach | read I_RES at Z_E (and the scaled value; needs `Z_E`) |
| 5 · Stations | look at the stations per frequency and at the comparison with groundmeas |
| 6 · Export the report tables and figures | find the exported files |
| 7 · groundmeas | read the dry run; enter all measurements on request |

The evaluation steps are described in [Campaign evaluation](campaign.md).

### Settings in section 1

**Campaign and measurements**

| Variable | Default | Meaning |
|---|---|---|
| `CAMPAIGN` | `"YYYY-MM-DD_Place"` | campaign folder |
| `DEMO` | `False` | `True`: create the demo campaign and evaluate its recordings if their result files are missing |
| `MEASUREMENTS` | four placeholder lines | one `dict` per measurement, see below |

```python
MEASUREMENTS = [
    dict(name="Measurement 1 (SUB 2.5 Ω)", measurement="SUB_2_5_10_000kHz", Z=2.5),
    dict(name="Measurement 2 (SUB 5 Ω)",   measurement="SUB_5_10_000kHz",   Z=5.0),
    dict(name="Measurement 3 (SUB 0 Ω)",   measurement="SUB_0_10_000kHz",   Z=0.0),
    dict(name="Measurement 4 (Station)",   measurement="Station_Elm_Road_10_000kHz", Z=None,
         location="Station Elm Road"),
]
```

| Field | Meaning |
|---|---|
| `name` | label in tables and figures; the order of the list is the order of the columns of the report tables |
| `measurement` | name of the result file = folder in `results/` (`MEASUREMENT` of the measurement notebook, by default the file name without extension) |
| `Z` | additional impedance in Ω (substation); `None` for a station – it then does not enter the equivalent-source method |
| `location` (optional) | exact location name in groundmeas, if it shall not come from the sites file |
| `description` (optional) | text placed before the automatic groundmeas description |
| `timestamp` (optional) | only for a wrongly set recorder clock: start of the recording in UTC, `"YYYY-MM-DD hh:mm:ss"` |

**Equivalent-source method**

| Variable | Default | Meaning – when to change |
|---|---|---|
| `ORDERS` | `"auto"` | odd orders whose current is at least 0.5 A in at least two measurements (a hint names the skipped ones); otherwise a list such as `[3, 5, 7, 11, 13]` |
| `NORMALIZATION` | `"complex"` | reference of the currents to the harmonic level of the network: `"complex"` (magnitude and phase, recommended), `"magnitude"` or `None` |
| `LEVEL` | `"mean"` | level used: `"pre_fault"`, `"post_fault"` or `"mean"` of both |
| `METHOD` | `"equation_error"` | estimator of the result: `"equation_error"` (linear) or `"output_error"` (nonlinear); both are always computed for comparison |
| `Z_E` | `None` | earthing impedance in Ω at which I_RES is computed – a value of your network (the example notebook uses the demo value 2.5); not set, the notebook skips I_RES at Z_E, the jackknife and the Monte Carlo spread with a note (ℹ) and shows only the figure I_RES(Z_E) |
| `Z_E_MAX` | `10.0` | end of the impedance axis of the figure I_RES(Z_E) |
| `IG_CHOICE` | `"max"` | fundamental component I_G: `"max"` (largest measured value, conservative), `"median"` or a number in A |

**Scaling to the 95 % quantile of a power-quality measurement**

| Variable | Default | Meaning – when to change |
|---|---|---|
| `U95` | `None` | 95 % quantiles of the harmonic voltages per order in V, e.g. `{5: U_5, 7: U_7}` – every order is scaled with its own value |
| `U95_REFERENCE` | `"LL"` | `"LL"`: the values are line-to-line (power-quality instrument, divided by √3); `"seq"`: sequence voltage (line-to-earth) |
| `THD95_PERCENT` | `None` | 95 % quantile of the line-to-line THD in % – one factor THD95/THD of the measurement series; alone for all orders, together with `U95` for the orders `U95` cannot scale |

`U95` and `THD95_PERCENT` can be given alone or together. With `U95` and `"LL"`, orders of the zero sequence (3, 9 …)
cannot be scaled per order – a line-to-line voltage contains no zero sequence –, nor can orders without a value in
`U95`; with `THD95_PERCENT` as well they get the flat THD factor, otherwise they stay unscaled (with a hint). The THD
of the series is the mean over the pre- and post-fault intervals of the largest line-to-line THD of the substation
tests ([Campaign evaluation](campaign.md#scaling-to-a-power-quality-measurement)).

**Limits, margins and factors – defined by you**, as in the measurement notebook: groundfault contains none, the
defaults leave them unset, and the parts that need them are skipped with a note (ℹ).

| Variable | Default | Meaning – what needs it |
|---|---|---|
| `LIMITS` | `()` | limits of the residual current in A, drawn as lines in the figures I_RES(Z_E) |
| `U_TP`, `F_FACTOR` | `None` | permissible touch voltage U_Tp in V and the factor F: the permissible residual current F·U_Tp/(r·R_E,max) of the resistive approach and the relevance of the reduction factor (there `None` = the values stored in the result file) |
| `REFERENCE_CURRENT` | `None` | reference current of the reduction factor in A; `None` = the largest limit stored in the result file |
| `UNCERTAINTY_I` | `0.0` | measurement-uncertainty margin m_I on I_RES at Z_E; the value with the margin is printed only if one is set |
| `PQ_SAFETY_FACTOR` | `1.0` | factor on the 95 % quantiles `U95`/`THD95_PERCENT`; `1.0` = no factor |
| `R_TYPICAL` | `None` | range `(low, high)` of the reduction factor at 50 Hz that you expect; `None` = no classification |

With `DEMO = True` the evaluation of the demo recordings uses `LIMITS`, `U_TP`, `F_FACTOR` and `UNCERTAINTY_I` as well.

**groundmeas** – `GROUNDMEAS_DB`, `GROUNDMEAS_EXPORT`, `GROUNDMEAS_UNCERTAIN` and `GROUNDMEAS_UNITS` as in the
measurement notebook; location, description and time stamp per measurement are fields of `MEASUREMENTS`.

**Resistive approach** – `RESISTIVE = dict(…)` with the data of your network; see
[Campaign evaluation](campaign.md#resistive-approach). A field that is not set skips the resistive approach with a
note that names it.

| Field | Default | Meaning |
|---|---|---|
| `U_thd95_V` | `None` | harmonic voltage (95 % quantile) in V |
| `from_ll` | `True` | the value is line-to-line and is divided by √3 |
| `R_E_max` | `None` | largest earthing resistance of the stations in Ω |
| `R1_km`, `R0_km` | `None` | positive- and zero-sequence resistance per unit length of the lines in Ω/km at the dominant frequency |
| `r` | `1.0` | reduction factor; with r < 1, r·R_E acts in the fault circuit |
| `I_res_max` | `None` | permissible residual current in A; `None` = F·U_Tp/(r·R_E,max) from `F_FACTOR` and `U_TP` |

`EXPORT_FORMATS` – file formats of the figures, as in the measurement notebook.

## Regenerating the notebooks

The notebooks are generated by `tools/make_notebooks.py` (needs `nbformat`):

```bash
python tools/make_notebooks.py --lang en --out notebooks/en --example --overwrite   # the notebooks of the repository
python tools/make_notebooks.py --lang de --out notebooks/de --example --overwrite
python tools/make_notebooks.py --lang en --out /path/to/work_folder                 # copies with placeholders
python tools/make_notebooks.py --lang en --out /path/to/work_folder --templates-only
```

| Option | Effect |
|---|---|
| `--lang en\|de` | language of the notebooks (default `en`) |
| `--out FOLDER` | target folder (default: the current folder) |
| `--example` | configuration of the working copies for the demo campaign; without it, placeholders |
| `--templates-only` | write only the reference copies (`templates/*_DEFAULT.ipynb`, German `Vorlagen/`) |
| `--overwrite` | also overwrite existing working copies |

The reference copies are always rewritten; existing working copies are kept (“exists, not overwritten”) unless
`--overwrite` is given, so your own changes survive an update of groundfault.

The cell ids are derived from the name of the notebook and the position of the cell (`evaluate_measurement-07`), so
an unchanged generator writes byte-identical files on every platform. After a change of `tools/make_notebooks.py`,
regenerate the notebooks of the repository with the first two commands; the test suite (`tests/test_notebooks.py`)
checks that the committed notebooks are exactly what the generator writes.
