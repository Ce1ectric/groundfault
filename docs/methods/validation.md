# Validation

Staged earth-fault tests can rarely be repeated, so an evaluation has to be right the first time. groundfault is
validated in three ways: against **synthetic recordings with a known solution**, by checking **every numerical method
against a second, independent method**, and against the **results of its predecessor** on field recordings. The test
suite runs all of these checks except the last one, whose field data are not part of the repository.

## Synthetic recordings with a known solution

[`groundfault.demo`](../reference/demo.md) writes COMTRADE recordings from physical models and saves the exact
values of every quantity the evaluation derives from them next to the recording (`<name>_truth.json`). The models
contain what makes real recordings difficult:

| Recording | Model |
|---|---|
| substation (`make_substation_recording`, `make_substation_series`) | 20-kV network with a fault in L3 (or another phase) through an additional impedance: line-to-earth voltages E_x + U0 with U0 from the closed-form solution; fundamental component of the fault current with prescribed active current and detuning; harmonics 3, 5, 7, 11, 13 from active two-terminal equivalents whose source voltage is the pre-fault voltage of the faulted phase, with a source drift in magnitude and phase between the tests; coil currents including their harmonics and a decaying DC component at switch-on; the transient at fault inception; an active residual current increase or a coil adjustment during the fault; the decaying neutral displacement voltage after the clearance; noise and DC offsets of the clamps; a second CT with ratio and phase error; a reversed clamp; different time origins; recorder-export or structured channel names; optionally a decaying DC component in the fault current |
| station (`make_station_recording`) | earth potential rise U_E = r·Z_E·I_F per order with Z_E,m = R_E + j·m·X_E1 and a reduction factor per order; probes measuring a share of the earth potential; touch voltage U_E/F; shield current (1 − r)·I_F; a background per order – constant, fluctuating, or changing at the clearance; a linearly drifting network frequency; with or without line-to-earth voltages; optionally an LV network in parallel to the station earth electrode, measured at two PEN points with a (fluctuating) load unbalance, a reversed or wrongly scaled clamp or a single measuring point |
| transformer (`make_transformer_recording`) | line currents of the transformer, MV and HV voltages with given powers per order, an upstream impedance (transformer + HV network) through which the fault draws positive- and negative-sequence currents of every order, the zero-sequence current of the coil; optionally reversed currents (generator reference arrow system) and an active residual current increase |
| RMS export (`rms_file_from_instantaneous`) | RMS values of 100-ms windows of an instantaneous-value recording, as recorders export them |
| groundmeas database (`make_groundmeas_db`) | an earthing measurement (current injection) matching the station model, per order and probe; a factor makes it deliberately too high |
| campaign (`make_campaign`) | all of the above as a complete campaign in the English or German folder layout |

An example: a substation test at 7.5 Ω in an under-compensated network, with a reversed clamp and a source drift of
15 % and 25°:

```python
import os
import tempfile

import groundfault as gf
from groundfault import demo

cfg = os.path.join(tempfile.mkdtemp(), "SUB_7_5_10_000kHz.cfg")
truth = demo.make_substation_recording(cfg, Z_F=7.5, f1=49.97, Iw=14.0, Iv=-8.0,     # under-compensated
                                       drift=demo.polar(1.15, 25.0), polarity=-1)      # reversed clamp
b = truth["intervals"]
res = gf.evaluate(gf.open_recording(cfg), gf.Intervals(b["steady_state"], b["pre_fault"], b["post_fault"]),
                  z_fault_ohm=7.5)
for key in ("IRES", "IG", "Iw", "Iv", "IH"):
    value = res.values["IH_total" if key == "IH" else key]
    print("%-4s evaluated %8.3f A   true %8.3f A   deviation %+.3f %%"
          % (key, value, truth[key], 100 * (value / truth[key] - 1)))
print(res.polarity, res.hints)
```

```text
IRES evaluated   27.985 A   true   27.980 A   deviation +0.015 %
IG   evaluated   16.124 A   true   16.125 A   deviation -0.000 %
Iw   evaluated   13.999 A   true   14.000 A   deviation -0.008 %
Iv   evaluated   -8.002 A   true   -8.000 A   deviation +0.025 %
IH   evaluated   22.872 A   true   22.867 A   deviation +0.023 %
-1 ['Iw was negative → current measurement reversed; current phasors rotated by 180° (magnitudes unchanged).']
```

The reversed clamp is detected and corrected, the negative detuning keeps its sign, and all quantities agree to a few
hundredths of a per cent – the remaining deviations come from the noise of the synthetic signals and from taking the
largest window.

## Every numerical method against a second one

Each method is checked either against an exact synthetic solution or against an independent second way to the same
number. Examples from the test suite (`tests/`):

| Method | Second method or exact solution | Test |
|---|---|---|
| phasor by single-bin DFT | Goertzel recursion – agreement to 10⁻⁸ | `test_dsp.py::test_dft_and_goertzel_identical` |
| true RMS value | root sum of squares of the phasors of a purely harmonic signal | `test_dsp.py::test_rms_equals_root_sum_of_squares_of_harmonics` |
| network frequency | phase method, spectral method and zero crossings agree within 1 mHz | `test_dsp.py::test_f1_three_methods_agree` |
| DFT with a large DC offset and off-grid frequencies | the same signal without offset; Hann against rectangular window | `test_numerics.py::test_large_dc_component_no_cancellation`, `::test_leakage_hann_versus_rectangular` |
| signal explorer | the evaluation in the same max window; an FFT over exactly ten cycles with a rectangular window for RMS value, harmonics, THD and DC component | `test_explorer.py::test_max_window_matches_evaluation`, `::test_characteristic_values_second_method` |
| assessment quantities | the true values of the demo series (fundamental component, Iw, Iv, I_RES, harmonics), despite drift, different time origins and a reversed clamp | `test_evaluation.py::test_assessment_quantities_substation`, `::test_polarity_corrected` |
| √2 method | interpolation against the fitted curve on an analytical resonance curve, also with 1 % noise | `test_formulas.py::test_sqrt2_method_from_resonance_curve_two_ways` |
| resonance curve (V curve) | measured minimum against the vertex of the fitted parabola | `test_report.py::test_v_curve_two_methods` |
| resistive approach | a fault at the critical distance drives exactly the permissible residual current | `test_formulas.py::test_resistive_approach_example` |
| equivalent sources | equation error and output error on exact data; the closed-form solution of two tests; the residual current against the explicit sum; recovery of the true sources despite drift, time origins and a reversed clamp | `test_equivalent_source.py::test_both_estimators_agree_on_exact_data`, `::test_two_measurements_match_closed_form`, `::test_recovery_with_complex_normalization`, `test_formulas.py::test_residual_current_from_sources` |
| superposition at the station | the true r·Z_E per order despite a background of up to 60 % of the earth potential rise and a frequency drift of 10 mHz/s, with and without voltage measurement | `test_station.py::test_fault_component_despite_background_and_frequency_drift` |
| null test | flags a fluctuating background as uncertain, a constant one with voltage measurement not | `test_station.py::test_null_test_flags_fluctuating_background` |
| LV network | RMS values of synthetic time series instead of the root sum of squares of the orders | `test_lv_network.py::test_lv_network_rms_values_recomputed_in_time_domain` |
| reduction factor | from the earth potential rise and from the shield current; r_eff against the RMS values of synthetic time series | `test_lv_network.py::test_reduction_factor_per_harmonic_and_effective` |
| transformer node: power | sum over the sequences against the sum over the phases (identity), the true powers of the demo per order before and during the fault | `test_transformer.py::test_sequence_power_identity`, `::test_power_per_state_and_sequence` |
| transformer node: upstream impedance | the true impedance of the demo per order from fault − pre-fault and from fault − post-fault, positive and negative sequence; the split into transformer and HV network; the same result with currents in the generator reference arrow system | `test_transformer.py::test_upstream_impedance_per_order`, `::test_hv_side_splits_transformer_and_hv_network`, `::test_generator_reference_and_estimated_fault_current` |
| fault current estimated from the transformer currents | the true active and reactive residual current (times the share of the transformer); the active residual current increase found without a fault-current channel | `test_transformer.py::test_fault_current_estimate_phase_factor`, `::test_generator_reference_and_estimated_fault_current` |
| groundmeas entry | written to a database, read back and compared with an earthing measurement: the ratio equals the reduction factor at all frequencies | `test_earthing.py::test_export_dry_run_and_write_with_read_back` |
| trend of r over f | an exact power law | `test_earthing.py::test_trend_codes_against_exact_power_law` |
| units of groundmeas values | a reference table of 322 spellings generated with groundmeas 1.6.1, and a direct comparison when groundmeas ≥ 1.6.1 is installed | `test_units.py` |

Error cases are tested as well: implausible clamps and probes, wrong ratios, missing channels, files of the
predecessor tool, and messages in both output languages (every message exists in English and German).

## The test suite

The tests run with [pytest](https://pytest.org) in the repository (the `dev` extra, see
[Installation](../getting-started/installation.md#running-the-tests)):

```bash
pytest -q
```

```text
…
SKIPPED [1] tests/test_units.py:63: could not import 'groundmeas.core.units': No module named 'groundmeas'
572 passed, 1 skipped in 63.26s
```

They use synthetic recordings only and take about a minute. The skipped test compares the unit handling directly
with groundmeas and runs when groundmeas 1.6.1 or newer is installed (see
[Installation](../getting-started/installation.md#running-the-tests)). By default the suite checks the German output
(the messages and labels of the predecessor tool); English output is tested explicitly.

## Comparison with the predecessor

groundfault continues an in-house tool that was used for the evaluation of staged fault tests before. groundfault
reproduces the results of its in-house predecessor on field recordings of several campaigns exactly (all numerical
results identical) when it is given the same parameters: the predecessor had presets for the limits of the residual
current, the permissible touch voltage, the factor F, the measurement-uncertainty margins and the typical range of the
reduction factor, while groundfault leaves all of them to the user.

## Limitations and assumptions

The evaluation rests on assumptions that the checks can point to but not remove:

* **Steady state.** The steady-state interval is chosen by hand and must contain a steady fault – after the decay of
  the DC component, before an active residual current increase or a coil adjustment. One network frequency applies to
  each interval; the plausibility checks report variations.
* **Window analysis.** 200-ms Hann windows resolve 5 Hz; interharmonics close to a harmonic partly fall into it. The
  orders are limited to 40 and to the sampling rate. The median DC removal slightly overestimates the true RMS value of
  currents with strong even harmonics.
* **Superposition.** The background is assumed to be the same during the fault as before or after it, and the network
  frequency to change linearly between the two sides. Without a voltage measurement the fault current is the frequency
  reference during the fault. The uncertainty estimate is a typical value, not a bound.
* **LV network and shield.** Kirchhoff's current law assumes that the current of the transformer star point does not
  change during the fault, and the PEN measuring points must capture all PEN conductors; the shield-current
  cross-check of the reduction factor is valid only if all return conductors are measured.
* **Reduction factor.** Only magnitudes are compared; the earthing measurement is interpolated linearly in frequency,
  never extrapolated; the probes of the two measurements are not at the same place. The classification of r at 50 Hz
  uses the range the user expects (`r_typical`) – an empirical range of the user, not part of the method.
* **Equivalent sources.** The network is a linear, time-invariant two-terminal equivalent per order during the series;
  level drift is removed by the normalisation, but zero-sequence orders are not normalised by default and even orders
  are not fitted. Outside the tested range of additional impedances the result is an extrapolation.
* **Measuring chain.** Synthetic recordings validate the algorithms, not the instrument transformers, clamps and
  probes. Errors of the measuring chain are found by the plausibility checks and fixed in the corrections file.

groundfault computes and checks; whether an earthing system or a network meets its requirements is decided by the
engineer according to the applicable standards, such as EN 50522. The package therefore contains no limits, safety
factors or uncertainty margins – the user defines them, and the parts of an evaluation that need them are skipped
until they are given.
