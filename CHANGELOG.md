# Changelog

All notable changes to groundfault are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and groundfault adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.0] - 2026-10-14

A major version because of incompatible changes: columns of the station, reduction-factor and LV-network tables are
renamed (r·Z_E, see *Changed*), disturbed states inside the steady-state interval are now left out of the assessment
by default, which changes the results of recordings that contain them, and the transformer evaluation determines the
polarity of the transformer currents itself. Result files of groundfault 2.0 are read and translated;
`Settings(exclude_disturbances=False, transformer_sign=1)` gives the results of 2.0 (except the table
`transformer_power`, see *Changed*).

### Added

- Disturbed states during the fault (`groundfault.disturbances`): an **active residual current increase** (a resistor
  switched on for a few seconds to locate the faulted feeder) and a **network change** (a network section trips or is
  switched) are found as abrupt steps of the active and the reactive current (angle method relative to U0) in the
  200-ms windows. A step of the reactive current that the measured coil currents follow is a coil change and stays
  part of the reference; without coil currents a reactive step is treated as a network change, and without U0 only
  steps of the fundamental component are found. Windows without fault current – a steady-state interval that reaches
  beyond the clearance or begins before the inception – are left out as well (state `no fault current`).
- `disturbances.scan` searches the whole fault – from the settled fault current after inception to the clearance –
  and proposes the first undisturbed range as the steady-state interval. The measurement notebook shows the proposal
  in section 3 and shades the disturbed ranges in the RMS trend.
- `evaluate` leaves disturbed windows of the steady-state interval out of the max window, the statistics, the
  stationarity check, the coil-current balance and the least-squares superposition at a station
  (`Settings.exclude_disturbances`, default `True`; `Settings.disturbance_threshold`, default 5 % of |I_H1|, at least
  0.5 A). New: the table `steady_state_segments`, the plausibility row *Disturbed states in the steady-state interval*,
  the section `disturbances` of the result file, `Result.disturbances` and `Result.reference_windows`; the RMS trend
  and the harmonics per window (report and interactive figures) hatch the disturbed ranges.
- Reduction factor over the frequency, drawn like the impedances: `report.reduction_factor` and
  `interactive.reduction_factor` show r per order with the span of the superposition methods (columns `r_min` and
  `r_max`), optionally the direct ratio (`direct=True`), and a trend r = c·f^b fitted over the orders (`trend=True`,
  `earthing.power_fit`); the lower panel shows the two compared quantities r·Z_E and Z_E.
- Station extrapolation: the column `U_background_plus_fault_in_phase_V`, an upper bound with the background and the
  scaled fault-related component in phase at every order. The phasor sum of the test is only one case – at a real
  fault the phase relation is another one, and a background in antiphase makes the measured voltage even smaller than
  the fault-related component.
- Demo: `demo.make_substation_recording(network_step=(t, ΔIv))` adds a network change with unchanged coil currents.
- Transformer node (`groundfault.transformer`): with the three line currents of the HV/MV transformer, `evaluate`
  analyses power and impedance per order and sequence before, during and after the earth fault – how the harmonic
  sources of the network, bundled at the transformer, behave through the fault. New tables `transformer_node` (U, I,
  P, Q and the apparent impedance U/I per state, order and sequence, consumer reference arrow system),
  `transformer_power_change` (fault − pre-fault and post-fault − pre-fault) and `transformer_impedance`: the
  **upstream impedance** Z_up = −ΔU/ΔI of transformer and HV network from the fault-related change of every order,
  with a second estimate (fault − post-fault), null test, uncertainty, significance and the deviation between positive
  and negative sequence; with HV voltages split into the transformer and the HV network (ratio and vector group from
  the fundamental). `res.values["transformer"]` (also in the result file) holds the polarity, X_up/m over the
  significant orders, the HV ratio and vector group and the change of the fundamental power.
  `transformer.summary_text` and `transformer.power_overview` give a one-line summary and P, Q per order and state
  side by side; plausibility rows *Polarity of the transformer currents*, *Upstream impedance* and *HV side*.
- Polarity of the transformer currents from the angle of the upstream impedance (inductive for transformer and HV
  network): currents measured in the generator reference arrow system are reversed automatically
  (`Settings.transformer_sign = None`, the new default), with a hint and the status `CORRECTED`; `+1`/`−1` fix it and
  a contradiction is reported.
- Without a fault-current channel – the usual case for a transformer recording – the fault current for the detection
  of disturbed states is estimated from the change of the negative-sequence current of the transformer (3·ΔI₂), so an
  active residual current increase or a network change is left out of the fault state of the transformer node too.
  `disturbances.scan` searches transformer recordings in the same way (the fault from the zero-sequence voltage,
  `transformer.fault_times`; the start once the estimate has settled, at least 1.5 s after the inception), and the
  measurement notebook shows its proposal for them as well. A step of the estimate counts only if it is at least four
  times its window-to-window noise (`transformer.estimate_noise`). `disturbances.detect(orient=False)` takes such an
  already oriented current.
- Figures `report.transformer_impedance` (apparent impedance per state, upstream impedance over the frequency with
  m·X_up,1 and the shares of transformer and HV network; also in `report.all_figures`) and the campaign table
  `transformer_summary` of `report.report_tables` (polarity, X_up/m, transformer and HV network, ΔP and ΔQ at 50 Hz per
  measurement). The measurement notebook has a new section *Transformer node* and the option `transformer_sign` in
  `SETTINGS`.
- Demo: `demo.make_transformer_recording` models the upstream impedance (`Z_transformer`, `Z_hv`), the fault current
  of every order (`Iw`, `Iv`, `fault_harmonics`, `share`), currents in the generator reference arrow system
  (`generator_reference`) and an active residual current increase (`active_step`), with the true values in the truth
  file.

### Changed

- The ratio U_E/I_F of the staged fault test is called **r·Z_E** – the earth potential rise per ampere of fault current
  contains the reduction factor r – and Z_E denotes only the earthing impedance: from the earth current
  I_E = I_F − I_S of the fault test or from the earthing measurement. Renamed columns:
  - `UE_per_A_fault`, `Z_E_fault_Ohm` → `rZE_fault_Ohm` (and `…_eff_Ohm`), `UE_per_A_direct` → `rZE_direct_Ohm`,
    `Z_E_fault_50Hz_Ohm` → `rZE_fault_50Hz_Ohm`, `Z_LV_to_Z_E_fault` → `Z_LV_to_rZE_fault`, `exponent_Z_fault` →
    `exponent_rZE_fault`;
  - `UE_per_A_earth_current`, `Z_total_fault_Ohm` → `Z_E_earth_current_Ohm` (and `…_eff_Ohm`),
    `Z_E_fault_to_injection` → `Z_E_earth_current_to_injection` (and `…_eff`);
  - `UE_per_A_injection`, `Z_injection_Ohm` → `Z_E_injection_Ohm` (and `…_eff_Ohm`), `exponent_Z_injection` →
    `exponent_Z_E_injection`.

  In German output the ratios U/I_F of the table `station_frequency` are called `U_zu_I_F_<method>_Ohm` (before
  `Z_<method>_Ohm`); the English keys `Z_<method>_Ohm` are unchanged.
- Result format version 4. Result files of groundfault 2.0 (version 3) are read, and their renamed columns are
  translated.
- With a disturbed state inside the steady-state interval the assessment refers to the undisturbed state, so the
  residual current and all values of the max window can differ from groundfault 2.0 for such recordings.
  `Settings(exclude_disturbances=False)` only reports the disturbed states and gives the results of 2.0; recordings
  without disturbed states give identical results.
- `Settings.transformer_sign` defaults to `None` (polarity from the upstream impedance) instead of `1.0`;
  `transformer_voltage` names the side of the transformer currents. Values other than `None`, `+1` and `−1` raise a
  `ValueError`.
- The table `transformer_power` keeps its columns, but the fault state is the mean over the undisturbed windows of the
  steady-state interval instead of the max window (a transformer recording has no fault current that defines a max
  window), and the sequence currents are RMS values over the windows instead of medians; P and Q are in the consumer
  reference arrow system after the polarity decision. The figure `report.transformer_power` has its legend above both
  panels (above panel (a) it pushed panel (b) aside).
- The section *Station … and transformer* of the measurement notebook shows the station tables only; the transformer
  has its own section. Its two cells have cell ids with a name (`evaluate_measurement-transformer-node`), so the
  numbered ids of the other cells are those of 2.x and updating a working copy maps every cell to its counterpart.

## [2.0.1] - 2026-10-14

### Fixed

- The measurement register listed every recording twice on case-insensitive file systems (Windows): a second search
  for `*.CFG` also found the `.cfg` files. Configuration files are now collected in one pass over the folder tree, in
  any letter case and each once; hidden files are skipped as before.
- Messages name files relative to the campaign folder with forward slashes on every operating system, e.g. the source
  of an applied correction (`notes/corrections.csv, line 2`).

## [2.0.0] - 2026-10-14

First public release. groundfault is the English, published successor of an in-house tool (version 1.x): API and
documentation in English, output in English or German, campaigns in an English or a German folder layout. It reads
the result files, the campaign files and the German folder layout of its predecessor, and it reproduces the results
of the predecessor on field recordings of several campaigns exactly (all numerical results identical) when it is given
the values the predecessor had preset – limits of the residual current, permissible touch voltage, factor F,
measurement-uncertainty margins and the range of the reduction factor.

### Added

- COMTRADE reader (IEEE C37.111, revisions 1991, 1999 and 2013; ASCII, BINARY, BINARY32 and FLOAT32 data files,
  binary data memory-mapped for large recordings) and writer (revision 1999, for synthetic recordings), and raw-data
  diagnostics (file structure, time base, active channels, time offset between subsystems of the recorder).
- Channel roles detected from the channel names; per-campaign corrections of the measuring chain (ratio, polarity,
  role, main channel, probe distance) and measurement sites.
- Evaluation of a recording in 200-ms windows: RMS values and harmonic phasors, assessment quantities (residual
  earth-fault current, fundamental component, harmonics, active and detuning current by the angle method) with
  measurement uncertainty, scaling to the 95 % quantile of a power-quality measurement, voltages and sequence
  components before, during and after the fault, plausibility checks and hints; harmonic power and sequence currents
  at a transformer.
- Equivalent-source method: an active two-terminal equivalent per harmonic order from a series of tests with
  different fault impedances, and from it the residual current at any earthing impedance Z_E.
- Secondary substations: earth potential rise and touch voltage per frequency, direct and fault-related
  (superposition) with an uncertainty estimate; PEN and shield currents, the current into the LV network and the
  earthing impedance of the LV network.
- Earthing measurements from a groundmeas SQLite database (opened read-only): comparison with the staged fault test,
  reduction factor per harmonic and as an RMS value, and entry of evaluated tests (dry run first, backup copy).
- Campaign evaluation over the result files: overview and consistency checks, resistive approach (after the published
  VDE Impuls of the VDE ETG, 2021, generalised to a factor F, a reduction factor r and a critical line length), report
  tables and figures.
- Evaluation of RMS recordings: trend, resonance curve and comparison with the RMS values of the recorder.
- Report output: figures in their final size for an A4 report (PDF, SVG, PNG; no titles, one font) and tables as CSV,
  Markdown, Excel and Word; interactive Plotly figures.
- Signal explorer: all channels with RMS values, harmonics and THD on hover, in the notebook and as a single HTML
  file.
- Measurement register and folder overview of a campaign; English and German folder layouts, detected
  automatically.
- Output in English or German: hints, tables, figure labels and exported files (`groundfault.i18n`).
- Jupyter notebooks as the user interface in English and German (`notebooks/en`, `notebooks/de`), generated by
  `tools/make_notebooks.py`.
- Synthetic demo campaign with a known solution and a demo groundmeas database (`groundfault.demo.make_campaign`),
  so that everything runs without measurement data.
- Test suite on synthetic recordings: every numerical method is checked against an exact solution or a second
  method.
- Documentation with MkDocs Material: installation, quickstart, user guide, methods and API reference.

### Changed

Compared with the in-house predecessor, the API is English throughout: modules, functions, parameters, table columns,
the codes in table cells and the keys of the result files. German names remain only where German is the content: in
the output – the message catalogues and the German display names of columns and codes (`i18n.COLUMNS_DE`,
`i18n.VALUES_DE`) –, in the German folder layout with the German headers of its campaign files, and in reading older
files: `groundfault.legacy` translates the files of the predecessor when they are read. Options are not translated: a
value or key of the predecessor given as an option (settings copied from an old notebook) raises an error that names
the current name, so that it is neither ignored nor misread. English is the default output
language and the English folder layout the default for new campaigns; German output and the German layout remain
available.

- **No preset limits or safety factors.** The limits of the residual current, the permissible touch voltage U_Tp, the
  factor F of the permissible earth potential rise F·U_Tp (new setting `Settings.f_factor`, stored in the result file
  like `u_tp`), the reference current of the reduction factor, the measurement-uncertainty margins, the factor on the
  95 % quantile of a power-quality measurement and the range of the reduction factor are parameters of the user;
  groundfault contains none of them and recommends no values. Defaults: `Settings(ires_limits=(), u_tp=None,
  f_factor=None, uncertainty_I=0.0, uncertainty_U=0.0, pq_safety_factor=1.0)`, `earthing.reduction_factor(F=None,
  U_Tp=None, reference_current_A=None, r_typical=None)` (missing values from the settings of the evaluation),
  `equivalent_source.ires_at_impedance(uncertainty_I=0.0)`. Without them the parts that need them are skipped –
  `NaN` or “–” and a hint that names the missing parameter; `formulas.max_residual_current` requires `U_Tp` and `F`,
  `campaign.resistive_approach` requires `I_res_max` or `U_Tp` and `F`, and the soil resistivity of
  `formulas.earth_return_depth` and `formulas.z0_overhead_line` is a required argument. `earthing.R_TYPICAL` is not
  part of the API. The values are validated (limits and `pq_safety_factor` > 0, margins 0 ≤ m < 1). The notebooks
  collect these parameters in one block of their configuration cell, not set; the earthing impedance `Z_E` of the
  campaign notebook, a value of the user's network, is not set in the templates either.
- **One sign convention for the detuning:** Iv > 0 means over-compensation everywhere. `formulas.detuning_current`
  returns I_operating − I_resonance, so `formulas.detuning` and `formulas.sqrt2_method` give the sign of the angle
  method; the resonance-curve formulas of the predecessor used the opposite sign.

[3.0.0]: https://github.com/Ce1ectric/groundfault/releases/tag/v3.0.0
[2.0.1]: https://github.com/Ce1ectric/groundfault/releases/tag/v2.0.1
[2.0.0]: https://github.com/Ce1ectric/groundfault/releases/tag/v2.0.0
