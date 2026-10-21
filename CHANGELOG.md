# Changelog

All notable changes to groundfault are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and groundfault adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.2.0] - 2026-10-21

A minor version with a new module for power-quality measurements and corrected rules for the scaling to a
power-quality quantile: the zero sequence and the even orders are no longer scaled, every order of the positive or
negative sequence is scaled with its own voltage – also in the remainder outside the orders of the model (see
*Changed*). Without a scaling the results of 3.1 are unchanged. Result files of an evaluation with a scaling gain the
rows `IH_zero`, `IH_even`, `IH_other` and the table `harmonic_scaling`.

### Added

- **Power-quality measurements** (`groundfault.pq`): the voltage of the busbar in undisturbed operation as recorded
  by a PQ instrument, and its use in the assessment.
  - Reading: `read_winpq` (CSV export of WinPQ mobil for the PQ-Box instruments: header with instrument, serial
    number, measurement, interval and nominal voltage; comma or semicolon, decimal point or comma), `from_frame` (any
    instrument, after reading its export with pandas; harmonic voltages in V or % of the fundamental) and `read`
    (several files; identical files and the same period are used once, overlapping time stamps keep the values of
    the first file, exports with different intervals are refused). Time stamps mark the end of an interval;
    `timezone` localises the instrument clock.
  - `ten_minute_values`: clock-aligned 10-min intervals as the square root of the mean of the squares of the shorter
    values (IEC 61000-4-30) or as the mean; incomplete intervals are left out and counted. Time stamps are localised
    in the order of the file (the repeated hour at the end of daylight saving time), the interval of the header is
    checked against the step of the time stamps, columns without values are left out.
  - `assess` → `PQAssessment`: per 10-min interval the largest of the three phases (line-to-earth, per order) and the
    largest loop (line-to-line THD), the quantile over the measurement (default 0.95), a factor of the user – directly
    (`factor`) or by the duration of the measurement from a rule `{minimum days: factor}` (`factors`,
    `duration_factor`); groundfault contains no such factor. The duration is the longest stretch of gapless values
    (`PQData.coverage()["gapless_days"]`, `max_gap_minutes` tolerates short gaps); a measurement shorter than every
    duration of the rule is not valid (`valid`, factor NaN): `scaling`, `settings`, `voltages` and `series` then raise a
    ValueError. Intervals with an earth fault or a dip of one phase are left out (`fault_threshold`). Tables `table()`
    (per order and phase) and `summary_table()`, the 10-min values per phase (`series`) and of the largest phase
    (`largest`), the weekly profile (`profile`).
  - The values for the evaluation: `PQAssessment.settings()` (`Settings`: quantiles per order and of the THD),
    `scaling()` (keyword arguments of `equivalent_source.ires_at_impedance`), `voltages()` and `series()` (the
    forecast).
  - `pre_fault_levels(result, kind=…)` and `PQAssessment.comparability(levels, times)`: where the pre-fault voltage
    of a test lies in the distribution of the PQ measurement, over the whole measurement and in the time window of
    the test (the same time of the week ± `window_h` hours, recorder time in UTC). Line-to-line data keep their
    reference in all values.
- `formulas.harmonic_category` (`"pos_neg"`, `"zero"`, `"even"`, `"fundamental"`) and `formulas.order_scaling`: the
  factor and rule of one order (`"own voltage"`, `"THD"`, `"as measured"`, `"no information"`).
- Equivalent-source method: the result of `ires_at_impedance` gains the result per order `table` (orders of the model
  at Z_E and orders of the remainder with test, level, quantile, factor and rule), `rules`, `IH_rest_scaled`,
  `IH_zero`, `IH_even`, `IH_other` and `rest_test`; a hint names the even orders from 5 % of the harmonic content.
  `ires_over_time(series, Z_E, voltages)`: I_RES at Z_E for every time step of a time series of harmonic voltages
  (e.g. the 10-min values of a PQ measurement) – its quantile instead of the quantiles per order.
  `ires_over_line(…, rest_A=)`: a scaled remainder. The settings of a series store `min_level_V`.
- Evaluation: `Settings.pq_u95` (quantiles per order), `pq_u95_reference` and `pq_min_level_V`; the table
  `harmonic_scaling` per order and the rows `IH_zero`, `IH_even` and `IH_other`.
- Forecast: `NetworkModel.test_voltages()` – the pre-fault voltage per order of the calibration tests (the orders
  that are not scaled to a PQ measurement).
- Figures `report.pq_series` (10-min values with the quantile and the quantile times the factor), `report.pq_duration`
  (duration curve with the levels of the tests) and `report.pq_profile` (weekly profile).
- `demo.make_pq_export`: a synthetic export in the WinPQ format with a weekly and a daily pattern and known quantiles;
  the demo campaign contains one (`raw/PQ/SUB_PQ_export.csv`, German `1_Rohdaten/PQ/UW_PQ_Export.csv`).
- Notebooks: `PQ_FILES`, `PQ_TIMEZONE`, `PQ_QUANTILE` and `PQ_FACTORS` in all four notebooks; a measurement that is
  not valid is reported and not used. The measurement notebook takes the quantiles per order and of the THD and the
  factor into `SETTINGS` and shows the table per order; the campaign notebook replaces `U95`, `U95_REFERENCE`,
  `THD95_PERCENT` and `PQ_SAFETY_FACTOR` with the values of the measurement, shows the tests in its distribution and
  three figures, the result per order at Z_E, and compares I_RES at Z_E per order, as the quantile of the time series
  and with the THD factor; the forecast notebooks take `VOLTAGES` from it (network model also as a time series,
  `PQ_SERIES`; the zero sequence and the even orders keep the voltage of the tests). Export of the tables
  `pq_quantiles`, `pq_summary`, `pq_tests`, `pq_scaling` and the figures.
- Documentation: the page *Power-quality measurements* of the user guide, the method in *Assessment quantities*, the
  rules per order, the remainder and the time series in *Equivalent-source method*.

### Changed

- **Scaling to a power-quality quantile** – single recording (`Settings.u_thd95_percent`/`u_thd95_volt`) and
  equivalent-source method (`ires_at_impedance(u95=…, thd95_percent=…)`), rules per order:
  - an order of the positive or negative sequence (5, 7, 11, 13 …) with its own voltage U_95,m/U_m, without its own
    value (no quantile, level below 1 V) with the THD factor – as before for the orders of the model;
  - the orders of the zero sequence (3, 9, 15 …) are **not scaled** (before: with their own value or the THD factor) –
    the zero sequence arises in the earth fault;
  - the even orders are **not scaled** (before: with the THD factor or the largest factor) and are listed separately;
  - the remainder outside the orders of the model is scaled order by order with the levels of its test (before: with
    the largest factor of the orders); its content without an order stays as measured;
  - the flat THD scaling of a single recording scales only the orders of the positive or negative sequence,
    I_H,scaled = √((I_H² − I_u²)·(U_95/U_meas)² + I_u²) with I_u the part not scaled (before: I_H·U_95/U_meas);
    `formulas.scaled_harmonic_current(…, I_unscaled=)`.

## [3.1.0] - 2026-10-18

A minor version with an optional new part; the results of 3.0 are unchanged except the summary value X_up/m of the
transformer node (see *Changed*), and result files gain three entries and a column.

### Added

- **Forecast** (`groundfault.forecast`), an optional subpackage that `import groundfault` does not load: a network
  model of the earth-fault loop at a busbar per harmonic order and the forecast of the harmonic residual current from
  harmonic voltages.
  - `NetworkModel.add_test` calibrates with a staged fault test: Z_k = 3·p_k·ΔU_k/I_F from the changes of the busbar
    voltages, with the pre-fault voltage of the faulted phase as the source (Thevenin). `add_fault` updates with an
    earth fault recorded at the busbar without a fault current: Z_k = Z_0·p_k·ΔU_k/(p_0·ΔU_0) with Z_0 of the
    calibration.
  - **Node rule** with the coil currents: the fault current of a recorded earth fault per order,
    I_F = 3·Y_0,net·ΔU_0 + ΔI_coil, with the zero-sequence admittance of the network without the coils from the tests
    – also at the orders where saturating coils and transformers add harmonic currents. Every coil channel is
    oriented by its 50-Hz current; a reversed channel is reported. Without coil currents: 3·|ΔU_0|/|Z_0| at the orders
    without a source in the fault.
  - **Source that arises with the fault**: tests with different series impedances (additional impedance plus line)
    separate it from the source impedance by linear least squares; with one series impedance the measured current is
    used (`constant`), with a hint when a forecast asks for a smaller one.
  - **Fault behind a line** (`Line`, `LineSegment`): the series impedances of the line per segment enter the loop,
    Z_qL = (2·Z_1L + Z_0L)/3, with the length as a fraction of a quarter wavelength as a validity hint – for tests in
    the network, forecasts and checks. **Values per order**: R′, X′ of a segment at m·50 Hz (`orders`), totals per
    order (`Line.from_impedances(…, orders=)`) or the loop contribution of the whole line (`loop`); the other orders use
    the 50-Hz values (resistance constant, reactance ∝ m), and the forecast names them.
  - `NetworkModel.line_from_fault`: the loop contribution of the line per order from a recorded earth fault behind it,
    Z_qL,m = −U_ph,bus,m/I_F,m − Z_F, with the fault current from the node rule or the zero-sequence voltage – a
    measurement of the line at the harmonic orders from the substation alone.
  - `forecast` per order and in total (I_H, I_RES) from one value per order (e.g. 95 % quantiles), a time series
    (quantiles of the totals), per phase, line-to-line or in percent; the magnitudes of the two sources are added; a
    margin per order is a parameter without a default.
  - Checks: `cross_check` between the tests (`loo`, `pairwise`, `chain`), `fault_check` at the recorded earth faults
    with an estimated current, `verify` with another measurement such as a staged test in the network.
  - Upstream split with the transformer node: the MV network Z_down = 1/(1/Z_1 − 1/Z_up) and forecasts for another
    upstream impedance (`upstream=`).
  - Input: `load_fault_data` (result files), `fault_data_from_values` (phasors of another tool),
    `fault_data_from_measurement`; campaigns of a work folder: `campaign_tests` (the staged tests from the register),
    `build_model`, `add_entries`, `check_data`, `forecast_folder`.
  - Estimates without a calibration: `classical_bound` and `resonance_bound`.
  - Model file (JSON, format `groundfault-network-model`, version 2) with `save` and `load`; `subset` selects earth
    faults by name, kind or metadata.
  - Tests against an independent three-phase nodal calculation of a synthetic network: limit cases (no earth
    admittance, Z_F → ∞, stiff source, tuned coil), calibration, update, node rule, two-source fit, a fault behind a
    line with and without shunt capacitance, `line_from_fault` and the classical estimate below the resonance.
- The forecast notebook `forecast/network_model_forecast.ipynb` (German `Prognose/Netzmodell_Prognose.ipynb`),
  written by `tools/make_notebooks.py --forecast` or `--forecast-only`: calibration from the campaigns of the register,
  checks between the tests, recorded earth faults, checks with other measurements, forecast at the busbar and behind a
  line, model file and tables in the forecast folder of the work folder (`forecast/`, German `05_Prognose/`).
- `i18n.register_labels`: German column names and codes for the tables of an optional part; report titles of
  registered messages `report.title_<name>`.
- `demo.make_substation_recording`: positive- and negative-sequence impedances at the busbar (`DemoHarmonic.Z1`,
  `Z2`), a source that exists only during the fault (`DemoHarmonic.Us`, optionally carried by the coil currents) and
  recordings without a fault current (`fault_current=False`).
- Result files: `voltage.fault_mean_phasor` and `voltage.coil_mean_phasor` – the busbar phasors and the coil currents
  during the fault, averaged over the reference windows of the steady state (`voltage.fault_mean_windows`) – and
  `voltage.coil_pre_phasor`, the coil currents before the fault (mean over the pre-fault interval).
- Documentation: the section *Forecast* with the pages *Model and equations* (equivalent circuits, assumptions),
  *Measurements for the model* (requirements for a disturbance recorder) and *Working with the network model*.
- Transformer node: `transformer.voltage_divider` – the share k = Z_HV/(Z_T + Z_HV) of the HV network from the
  fault-related change of the HV and MV voltages of the same recording, also without transformer currents (table
  `transformer_divider`, `res.values["transformer_divider"]` in the result file, plausibility row); with the
  currents also Z_HV = k·Z_up and Z_T = (1 − k)·Z_up – a second method beside Z_HV from HV voltage and current.
- Documentation: the HV network with its line to the EHV/HV substation (capacitance at the far end, parallel path)
  and the voltage divider, figure `forecast_hv_network`.
- Documentation of the equivalent-source method: *Within and beyond the tested range* – with additional impedances
  small compared with |Z_q| the fitted source voltage is poorly determined (error amplification
  V = √(|I_1|² + |I_2|²)/|I_1 − I_2|); within the tested range the errors of U_q and Z_q compensate, beyond it (larger
  earthing impedance, a line) they do not. Check the source voltage with the Thevenin check, compute with the measured
  pre-fault level beyond the tested range, or choose the largest additional impedance of the order of |Z_q|; the
  zero-sequence orders are the exception. The forecast documentation explains why one test is enough there.
- **Measured source** in the equivalent-source method: `equivalent_source.measured_source(series)` takes the source
  voltage as measured – the pre-fault voltage of the faulted phase – and Z_q = U_q/I_k − Z_k as the median over the
  tests (default, `impedance="median"`) or from the test with the smallest additional impedance
  (`impedance="smallest"`); the zero-sequence orders keep the fitted equivalent, a Z_q with a negative real part
  becomes R_q = 0 with |Z_q| kept. `SourceSeries.loo_table(limit_pct=None, limit_A=None)` forecasts every test with
  the model of the other tests (leave-one-out, both sources); the permissible deviations in % and in A are parameters
  without a default. It also takes the measurements themselves – one test is enough; the zero-sequence orders then
  stay in the remainder. `SourceSeries.single_test_table()` gives Z_q of every single test,
  `equivalent_source.compare_sources(measured, fitted, Z_E)` the currents with both sources; `ires_at_impedance`, `ires_over_line`, `jackknife_table` and `monte_carlo` work with the measured source.
  `fit_equivalent_source` gives a hint when the Thevenin check deviates by more than `thevenin_tolerance`
  (`THEVENIN_TOLERANCE`, ±10 % / ±10°). `report.source_fit`, `report.ires_over_ze`, `report.report_tables`,
  `interactive.source_fit` and `interactive.ires_ze` take a second series as `comparison` (dashed);
  `report.source_plane` marks the single tests of a measured series.
- Campaign notebook: the result I_RES(Z_E) – checks, section 4, report table and figures – uses the measured source
  (`SOURCE = "measured"`, `SOURCE_IMPEDANCE = "median"`), the fitted one is shown for comparison; the checks show the
  leave-one-out table with your permissible deviations `LOO_LIMIT_PCT` and `LOO_LIMIT_A` (`None`: without
  assessment); section 3 shows the single tests and the comparison of both sources within and beyond the tested range.
  A campaign with one substation test now gets the curve I_RES(Z_E) as well (measured source).
- **MV network impedance from undisturbed operation**: `transformer.mv_network_impedance(recordings, orders, intervals)`
  estimates the impedance of the MV network seen from the busbar, Z_MV = Σ ΔU·ΔU_HV*/Σ ΔI·ΔU_HV*, from the variations
  of undisturbed operation with the HV voltage as instrumental variable – the MV network with its damping, which U/I of
  the undisturbed node does not show. Pooled over recordings, with a bootstrap range, the strength of the instrument
  (`corr_I_hv`), the polarity of the current transformers from the passivity of the result, an optional correction
  with the HV network impedance (`Z_hv`: the instrument becomes the HV source voltage) and the check against a result
  that is the upstream impedance (`IV_MIN_CORRELATION`, `IV_MAX_ANGLE_DEG`). `demo.make_undisturbed_transformer_recording`
  writes a recording with independently fluctuating sources on both sides and known Z_MV.
- `forecast.network_estimate`: the harmonic fault current from quantities of undisturbed operation and network data –
  Z_1 = Z_up ∥ Z_MV per sequence, Z_0 capacitive from I_C with the damping d = I_w/I_C as a series resistance – without
  a staged test (an estimate, not a bound; the orders with a source in the fault need a test or a recorded fault).
- **Share of the HV-driven variation** (V3): `mv_network_impedance(…, Z_up=…)` gives `hv_share` =
  |Z_MV/(Z_up + Z_MV)|²·Σ|ΔU + Z_up·ΔI|²/Σ|ΔU|², the share of the HV-driven variation in the variance of the busbar
  voltage, per order and sequence; `min_hv_share` (a value you define, no default; needs `Z_up` and `Z_hv`, since the
  share holds only with the corrected instrument) marks recordings below it as not reliable, with a hint. Where the
  MV side drives most of the variation the estimate drifts towards −Z_up, and neither the correlation nor the angle
  shows it until it drives nearly everything.
- **Angle error of the current transformers** (V3): `mv_network_impedance(…, ct_angle_deg=…)` rotates the transformer
  currents back by the angle error per order (one value, `{order: angle}` or the table of the reference clamp);
  `transformer.ct_angle_from_reference(recording, channel, reference, orders)` gives the angle and ratio error of a
  current channel against a reference clamp on the same conductor, with the reversed clamp recognised.
- `transformer.mv_network_series(recordings, orders, …)`: a series of undisturbed recordings – e.g. one every hour of a
  measuring day – each evaluated on its own (natural sequence), the polarity taken once from all of them, and the
  pooled estimate of the reliable recordings per order.
- Forecast without an earth fault, **V2**: `forecast.network_data_estimate` (the loop from network data with an assumed
  damping G of the MV network, Z_MV = 1/(G + j·m·ω₁·C_1)) and `forecast.network_data_envelope` (the largest current
  over a range of G – searched, since near the resonance a larger damping raises the current);
  `forecast.estimates_without_fault` puts V0 to V3 side by side per order and fault impedance with I_H.
  `groundfault.forecast.network_data`: `transformer_reactance`, `hv_network_reactance`, `at_order`,
  `earth_capacitance`, `mv_network_from_data`, `resonance_order` – the impedances from rating plate, S″_k, I_C and C_1
  (the R/X ratios and the damping are your assumptions).
- The notebook `forecast/forecast_without_fault.ipynb` (German `Prognose/Prognose_ohne_Erdschluss.ipynb`), written with
  `--forecast`: network data and resonance of the busbar, the angle error from a reference clamp, V3 per recording
  with its checks and pooled, V0 to V3 side by side, export; with `DEMO = True` a measuring day of six demo
  recordings. `demo.make_undisturbed_transformer_recording` gains `ct_angle_deg`, `reference_clamp` and `start`, and its
  truth file the share `hv_share` per order and sequence.
- Documentation: the forecast is arranged by the methods V0 to V8 (overview with the choice of a method, the page
  *Without an earth fault* with the measuring day and an example); the methods page of the transformer node and
  *Measurements for the model* describe the share of the HV-driven variation, the angle correction and the
  undisturbed recordings.

### Changed

- Transformer node: the summary value `X1_up_Ohm` (and `X1_transformer_Ohm`, `X1_hv_Ohm`) is the mean over the
  sequence **other than the natural one** of each order (m = 5, 11 …: positive, m = 7, 13 …: negative sequence);
  without a significant order there over both sequences as before (`X1_up_other_sequence`). The natural sequence
  carries the pre-fault harmonic – ten to a hundred times the other sequence – and its drift enters ΔU and ΔI. The
  table `transformer_impedance` gains the column `natural_sequence`; `transformer.is_natural`.
- Forecast: the upstream impedance Z_up of a transformer recording is taken per order from the sequence other than
  the natural one (before: the natural sequence); an order without a significant value there gets no Z_up.

### Fixed

- Documentation of the transformer node: the HV network can form a parallel resonance with its capacitance, and
  X_up/m is then not constant near it; this replaces the statement that X_HV/m can be half of U_n²/S_k,HV.
- Documentation of the line model: a frequency-independent resistance and a reactance proportional to m err in
  opposite directions – the resistance rises with frequency, the reactance of earth-return paths and of cables with
  bonded sheaths rises less than proportionally –, so the forecast behind a line is not on the safe side by
  construction; values per order can be given instead. New: the largest rise of an order behind a line
  (series resonance of the fault loop, g_max = 1/|sin(φ_q − φ_z)|), the line impedance from a recorded fault behind a
  line, and the time base needed to calibrate with a test in the network. Instrument transformers: the statement on
  the frequency response of inductive voltage transformers is replaced by a reference to measurements and
  IEC TR 61869-103.
- Figure of the node rule (`forecast_node_rule`): the fault impedance lies in series with the parallel connection of
  the network admittance and the coils – one loop with the source and the positive- and negative-sequence impedances;
  before, it was drawn as a third parallel branch, which would let a current flow without earth admittance. The
  equations were right.
- `classical_bound` and `resonance_bound` are estimates, not upper bounds at every order: below the resonance of the
  busbar the inductive Z_1 + Z_2 partly cancels the capacitive Z_0 (series resonance of the fault loop, for a cable
  network near m ≈ 3), and the current can exceed the classical estimate severalfold (docstrings, documentation of the
  forecast and of the transformer node).

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

[3.2.0]: https://github.com/Ce1ectric/groundfault/releases/tag/v3.2.0
[3.1.0]: https://github.com/Ce1ectric/groundfault/releases/tag/v3.1.0
[3.0.0]: https://github.com/Ce1ectric/groundfault/releases/tag/v3.0.0
[2.0.1]: https://github.com/Ce1ectric/groundfault/releases/tag/v2.0.1
[2.0.0]: https://github.com/Ce1ectric/groundfault/releases/tag/v2.0.0
