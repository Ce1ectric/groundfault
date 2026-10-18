# API reference

The reference is generated from the docstrings of the package (NumPy style) and has **one page per module**. Each
page starts with the module description, followed by every name in the module's `__all__`, in the order of the source:
classes with their public methods and properties, functions, and constants with the description that follows their
assignment. Private helpers (names starting with `_`) and names a module imports from another one are not shown; names
in the descriptions link to the objects they refer to. The page [groundfault](groundfault.md) shows the package
description only. The most important names are also available at package level – `gf.open_recording`,
`gf.detect_roles`, `gf.Intervals`, `gf.Settings`, `gf.evaluate`, `gf.Result`, `gf.load_result` and the modules
`gf.dsp`, `gf.formulas`, `gf.symmetrical` – and are documented on the pages of the modules that define them.

Conventions used throughout: units in SI (column names carry them: `_A`, `_V`, `_Ohm`, `_Hz`, `_pct`, `_deg`),
complex RMS phasors, English column names and language-neutral codes in all tables (German display names only through
[`i18n.localize`](i18n.md)); see [Methods](../methods/index.md#conventions).

## Modules

**Evaluating recordings**

| Module | Content |
|---|---|
| [comtrade](comtrade.md) | read COMTRADE files (IEEE C37.111, revisions 1991/1999/2013; binary data memory-mapped for large files) and write them (revision 1999, for synthetic recordings) |
| [channels](channels.md) | channel roles (line-to-earth voltages, fault current, coil currents, station, transformer) |
| [evaluation](evaluation.md) | evaluation of one recording (assessment quantities, voltages, station, transformer) |
| [disturbances](disturbances.md) | disturbed states during the fault (active residual current increase, network change) – not the reference of the assessment |
| [station](station.md) | station per frequency: earth potential rise and touch voltage, direct and fault-related (superposition), PEN and shield currents, current into the LV network and Z_E of the LV network |
| [transformer](transformer.md) | transformer node: power, apparent and upstream impedance (transformer + HV network) per order and sequence before, during and after the fault |
| [earthing](earthing.md) | groundmeas: read earthing measurements, compare them with the staged fault test (reduction factor, LV network in parallel) and enter the fault test |
| [equivalent_source](equivalent_source.md) | equivalent-source method (active two-terminal equivalent per harmonic order) |
| [formulas](formulas.md) | closed-form formulas (residual current, √2 method, angle method, measurement uncertainty, harmonics, resistive approach, limits, line parameters) |
| [campaign](campaign.md) | overview and consistency check of a measurement campaign, resistive approach |

**Forecast (optional, not loaded by `import groundfault`)**

| Module | Content |
|---|---|
| [forecast](forecast.md) | network model of the earth-fault loop per harmonic order at a busbar (`model`), its input from result files and other tools (`data`), lines to fault locations in the network (`line`), campaigns of a work folder (`campaigns`), estimates without an earth fault (`bounds`) and their impedances from network data (`network_data`) |

**Building blocks**

| Module | Content |
|---|---|
| [dsp](dsp.md) | signal processing (windows, DC removal, Hann window, RMS, DFT/Goertzel, f1 estimation) |
| [symmetrical](symmetrical.md) | symmetrical components, line-to-line quantities, common angle reference |
| [rms](rms.md) | evaluation of RMS recordings (trend, resonance curve, comparison with the device RMS values) |
| [diagnostics](diagnostics.md) | raw-data diagnostics (.dat structure, time base, active channels, time offset) |

**Output**

| Module | Content |
|---|---|
| [report](report.md) | figures and tables for an A4 report (no titles, uniform font) |
| [interactive](interactive.md) | interactive Plotly figures for the notebook |
| [explorer](explorer.md) | signal explorer: all channels with RMS values and harmonics on hover (notebook and HTML file) |

**Campaign files and support**

| Module | Content |
|---|---|
| [corrections](corrections.md) | corrections per campaign (instrument-transformer ratio, polarity, roles, probe distance) |
| [sites](sites.md) | sites per campaign (location, coordinates, asset type for groundmeas) |
| [register](register.md) | measurement register and folder overview of a campaign |
| [layout](layout.md) | folder layout of a campaign (English or German folder and file names) |
| [units](units.md) | units of groundmeas values with the same rules as groundmeas ≥ 1.6.1 (mΩ, µV, kΩm …) |
| [i18n](i18n.md) | output language (English/German): messages, column names, number format |
| [legacy](legacy.md) | reading result and campaign files of the predecessor tool (German keys) |
| [demo](demo.md) | synthetic recordings with known solution (tests, training) |

## Entry points

| Task | Start with |
|---|---|
| open a recording | [`open_recording`](comtrade.md#groundfault.comtrade.open_recording) → [`Recording`](comtrade.md#groundfault.comtrade.Recording) |
| apply the corrections file of a campaign | [`corrections.load`](corrections.md#groundfault.corrections.load) |
| detect the channel roles | [`detect_roles`](channels.md#groundfault.channels.detect_roles) → [`RoleAssignment`](channels.md#groundfault.channels.RoleAssignment) |
| check the raw data | [`diagnostics.diagnose`](diagnostics.md#groundfault.diagnostics.diagnose) |
| evaluate a recording | [`evaluate`](evaluation.md#groundfault.evaluation.evaluate) with [`Intervals`](evaluation.md#groundfault.evaluation.Intervals) and [`Settings`](evaluation.md#groundfault.evaluation.Settings) → [`Result`](evaluation.md#groundfault.evaluation.Result) |
| read a result file | [`load_result`](evaluation.md#groundfault.evaluation.load_result) → [`ResultFile`](evaluation.md#groundfault.evaluation.ResultFile) |
| compare with earthing measurements | [`earthing.Database`](earthing.md#groundfault.earthing.Database), [`frequency_response`](earthing.md#groundfault.earthing.frequency_response), [`compare`](earthing.md#groundfault.earthing.compare), [`reduction_factor`](earthing.md#groundfault.earthing.reduction_factor), [`check_lv_network`](earthing.md#groundfault.earthing.check_lv_network) |
| enter a test in groundmeas | [`earthing.export_to_groundmeas`](earthing.md#groundfault.earthing.export_to_groundmeas) |
| evaluate a campaign | [`campaign.overview`](campaign.md#groundfault.campaign.overview), [`consistency`](campaign.md#groundfault.campaign.consistency), [`resistive_approach`](campaign.md#groundfault.campaign.resistive_approach) |
| transformer node | tables `transformer_node`, `transformer_impedance` of [`evaluate`](evaluation.md#groundfault.evaluation.evaluate), [`transformer.power_overview`](transformer.md#groundfault.transformer.power_overview), [`report.transformer_impedance`](report.md#groundfault.report.transformer_impedance) |
| MV network from undisturbed operation (V3) | [`transformer.mv_network_impedance`](transformer.md#groundfault.transformer.mv_network_impedance), angle error of the current transformers with [`transformer.ct_angle_from_reference`](transformer.md#groundfault.transformer.ct_angle_from_reference) |
| forecast without an earth fault (V0–V3) | [`forecast.classical_bound`](forecast.md#groundfault.forecast.bounds.classical_bound), [`resonance_bound`](forecast.md#groundfault.forecast.bounds.resonance_bound), [`network_data_estimate`](forecast.md#groundfault.forecast.bounds.network_data_estimate), [`network_data_envelope`](forecast.md#groundfault.forecast.bounds.network_data_envelope), [`network_estimate`](forecast.md#groundfault.forecast.bounds.network_estimate) |
| forecast with staged tests and recorded earth faults (V4–V7) | [`forecast.build_model`](forecast.md#groundfault.forecast.campaigns.build_model) → [`NetworkModel`](forecast.md#groundfault.forecast.model.NetworkModel) |
| equivalent sources | [`equivalent_source.load_series`](equivalent_source.md#groundfault.equivalent_source.load_series), [`fit_equivalent_source`](equivalent_source.md#groundfault.equivalent_source.fit_equivalent_source), [`ires_at_impedance`](equivalent_source.md#groundfault.equivalent_source.ires_at_impedance), [`monte_carlo`](equivalent_source.md#groundfault.equivalent_source.monte_carlo) |
| figures and tables for the report | [`report.all_figures`](report.md#groundfault.report.all_figures), [`report.report_tables`](report.md#groundfault.report.report_tables), [`report.export_tables`](report.md#groundfault.report.export_tables) |
| signal explorer | [`explorer.explorer`](explorer.md#groundfault.explorer.explorer), [`explorer.explorer_html`](explorer.md#groundfault.explorer.explorer_html) |
| output language | [`i18n.set_language`](i18n.md#groundfault.i18n.set_language), [`i18n.localize`](i18n.md#groundfault.i18n.localize) |
| folder layout and work folder | [`layout.find_work_folder`](layout.md#groundfault.layout.find_work_folder), [`layout.detect_layout`](layout.md#groundfault.layout.detect_layout) |
| demo data | [`demo.make_campaign`](demo.md#groundfault.demo.make_campaign) |

The [user guide](../user-guide/index.md) shows these functions at work; the [quickstart](../getting-started/quickstart.md)
uses most of them in one session.
