# Equivalent-source method

The harmonic content of the residual current depends on the impedance of the fault path: at a substation test with
an additional impedance in the fault branch it is smaller than with a solid fault, and at a station it depends on the
earthing impedance there. The **equivalent-source method** determines from a series of substation tests with
different additional impedances Z_k, per harmonic order, the active two-terminal equivalent of the network seen from
the fault – and from it the residual earth-fault current at any earthing impedance Z_E. The functions are in
[`groundfault.equivalent_source`](../reference/equivalent_source.md); the campaign notebook runs them
([Campaign evaluation](../user-guide/campaign.md#equivalent-source-method), where the tables and hints are listed).

## The model

Per harmonic order m the network acts like a source voltage \(\underline{U}_{q,m}\) behind a source impedance
\(\underline{Z}_{q,m}\); with the additional impedance Z_k in the fault branch the harmonic current is

\[
\underline{I}_{m,k} = \frac{\underline{U}_{q,m}}{\underline{Z}_{q,m} + \underline{Z}_k}
\]

Physically, \(\underline{U}_{q,m}\) is the voltage of the faulted phase at order m before the fault (Thevenin), and
\(\underline{Z}_{q,m} = (\underline{Z}_{1,m} + \underline{Z}_{2,m} + \underline{Z}_{0,m})/3\) combines the
positive-, negative- and zero-sequence impedances of the network at the fault location – a single-line-to-earth
fault connects the three sequence networks in series. In the orientation of the angle method (Iw > 0) the current is
counted opposite to the fault current, so \(\underline{U}_{q,m}\) equals the *negative* pre-fault voltage of the
faulted phase. The fundamental component is not part of the model: it is set by the high-impedance zero-sequence
system and hardly depends on Z_k; it is taken from the measurements.

**Input:** the result files of the single evaluations – the phasors of the orders 1 to 25 of the fault current and of
the three line-to-earth voltages in the max window, and the sequence voltages before and after the fault. The series
needs at least two tests with different additional impedances (three or more give a goodness of fit and the
jackknife), the line-to-earth voltages and pre- and post-fault intervals in every recording.
[`load_series`](../reference/equivalent_source.md#groundfault.equivalent_source.load_series) reads them,
[`fit_equivalent_source`](../reference/equivalent_source.md#groundfault.equivalent_source.fit_equivalent_source)
fits the equivalents.

## Common angle reference and polarity

Each recording has its own time origin. All phasors of a measurement are referred to the fundamental of U_L1-L2 in
its evaluated window, \( \hat{\underline{X}}_m = \underline{X}_m\,e^{-jm\varphi_\text{LL1}} \), which makes the
phasors of different recordings comparable ([Methods](index.md#angle-reference)). The pre-fault and post-fault levels
are stored with the same reference.

The polarity of the fault current is set per measurement so that the active component of the fundamental is positive
(`polarity="auto"`); `1` or `-1`, also as a list per measurement, fixes it. With three or more measurements,
`polarity_brute_force=True` tries all sign combinations (the first measurement fixed) if some orders give a negative
source resistance, and keeps the one with R_q ≥ 0 for most orders and then the smallest residual.

## Normalisation of the source fluctuation

The tests of a series are minutes apart, and in the meantime the harmonic voltages of the network change – in
magnitude and in phase. A two-terminal fit over currents driven by different source levels gives wrong parameters.
Every current is therefore referred to the harmonic level measured at the same time, before and after the same test
(`reference`: `"pre_fault"`, `"post_fault"` or the `"mean"` of both):

* The level of order m is the sequence voltage of its **natural sequence** (positive for m mod 3 = 1, negative for
  m mod 3 = 2), referred to U_L1-L2. `sequence` can assign other sequences per order with a mapping order →
  `"pos"`/`"neg"`/`"zero"`; `sequence="legacy"` uses the simplified assignment of earlier evaluations
  (`SEQUENCE_LEGACY`: 3rd order zero, 5th negative, 7th positive, all other orders negative sequence), for
  comparisons with old results.
* Since U_q is the pre-fault voltage of the **faulted phase**, the sequence voltage is multiplied by the factor with
  which it enters that phase – 1, a or a² from the inverse Fortescue transformation
  ([`phase_factor`](../reference/equivalent_source.md#groundfault.equivalent_source.phase_factor)). The faulted phase
  of each test is the line-to-earth voltage with the smallest fundamental (below 30 % of the largest); tests in
  different phases are handled this way.
* **Complex normalisation** (default, `normalization="complex"`):
  \( \underline{I}'_{m,k} = \underline{I}_{m,k}\,\tilde{U}_m/\underline{U}_{\text{ref},m,k} \), with the median
  \(\tilde{U}_m\) of the level magnitudes of the series (`level_reference_V`) – the drift of the source in magnitude
  *and* phase is removed. `"magnitude"` divides by \(\lvert\underline{U}_{\text{ref},m,k}\rvert\) only; `None` fits the
  currents as measured.
* **Zero-sequence orders** (3, 9, …) are not normalised by default: their current arises only during the earth fault
  (saturation of coils and transformers at full displacement voltage), and the small zero-sequence level before the
  fault is no reference for it. `normalize_zero=True` normalises them as well.
* Fallbacks, with a hint per order: no complex levels in the result file → magnitude normalisation; a level missing or
  below `min_level_V` (1 V) → no normalisation.

The demo series drifts between the tests by 1.10∠10° and 0.95∠−8° (relative to the 0-Ω test). Only the complex
normalisation recovers the demo source impedances 4.5 − j2.5 Ω (250 Hz) and 7 − j3.5 Ω (350 Hz):

```python
import os
import tempfile

import groundfault as gf
from groundfault import demo, equivalent_source as es
from groundfault.layout import ENGLISH

d = demo.make_campaign(tempfile.mkdtemp(), layout="en")
entries = []
for w in d["substation"]:                     # the demo tests at 0 / 2.5 / 5 Ω – the sources drift between them
    res = gf.evaluate(gf.open_recording(os.path.join(d["campaign"], w["cfg"])),
                      gf.Intervals((2.6, 4.4), (0.2, 1.8), (7.0, 8.8)), z_fault_ohm=w["Z_F"])
    entries.append(dict(file=res.save_json(ENGLISH.result_path(d["campaign"], res.name)), Z=w["Z_F"],
                        name="%g Ω" % w["Z_F"]))
measurements = es.load_series(entries)
print(es.fit_equivalent_source(measurements).level_table().query("order == 5")
      [["measurement", "U_pre_V", "U_post_V"]].round(1).to_string(index=False))
for normalization in ("complex", "magnitude", None):
    t = es.fit_equivalent_source(measurements, orders=[5, 7], normalization=normalization).source_table()
    print("%-9s" % normalization, " | ".join("%d: Z_q = %.2f %+.2fj Ω, residual %.2f %%"
                                           % (r.order, r.Rq_Ohm, r.Xq_Ohm, r.residual_pct) for r in t.itertuples()))
```

```text
measurement  U_pre_V  U_post_V
        0 Ω    220.0     220.0
      2.5 Ω    242.0     242.0
        5 Ω    209.0     209.0
complex   5: Z_q = 4.50 -2.50j Ω, residual 0.01 % | 7: Z_q = 7.00 -3.50j Ω, residual 0.01 %
magnitude 5: Z_q = 3.13 -2.74j Ω, residual 12.79 % | 7: Z_q = 3.89 -3.75j Ω, residual 14.16 %
None      5: Z_q = 2.82 -2.52j Ω, residual 15.65 % | 7: Z_q = 3.37 -3.27j Ω, residual 17.53 %
```

**Orders.** `orders="auto"` fits the odd orders above 1 whose current is at least `min_current_A` (0.5 A) in at least
two measurements – the two complex unknowns need two meaningful currents. Even orders are left out: in staged fault
tests they mostly come from transients and DC saturation of the clamps and follow no two-terminal model. A hint names
the skipped orders; a list such as `[3, 5, 7, 11, 13]` fits exactly these.

## Two estimators

The model is fitted to the (normalised) currents of all tests in two ways:

* **Equation error** – the model multiplied out is linear in the unknowns,
  \( \underline{I}_k\,\underline{Z}_q - \underline{U}_q = -\underline{I}_k\,\underline{Z}_k \), and is solved by linear
  least squares ([`fit_equation_error`](../reference/equivalent_source.md#groundfault.equivalent_source.fit_equation_error);
  the columns are scaled to unit norm, which makes the condition number `condition_number` independent of the units).
  Its residual is \( (\underline{Z}_q + \underline{Z}_k)(\underline{I}_k - \underline{I}_{\text{model},k}) \): it
  weights the current deviations with \(\lvert\underline{Z}_q + \underline{Z}_k\rvert\).
* **Output error** – minimises the current deviations themselves,
  \( \min \sum_k \lvert\underline{I}_k - \underline{U}_q/(\underline{Z}_q + \underline{Z}_k)\rvert^2 \), a nonlinear
  least-squares problem solved from the equation-error estimate
  ([`fit_output_error`](../reference/equivalent_source.md#groundfault.equivalent_source.fit_output_error)).

Both are always computed (columns `Zq_<method>`, `Uq_<method>_V` of the source table); `method` (`"equation_error"`
by default, or `"output_error"`) selects the result. With exact data they coincide, and with two measurements the
problem is exactly determined – both give the closed-form solution

\[
\underline{Z}_q = \frac{\underline{I}_2\underline{Z}_2 - \underline{I}_1\underline{Z}_1}{\underline{I}_1 - \underline{I}_2},
\qquad
\underline{U}_q = \underline{I}_1(\underline{Z}_q + \underline{Z}_1)
\]

([`formulas.source_from_two_measurements`](../reference/formulas.md#groundfault.formulas.source_from_two_measurements)).
U_q and Z_q scale together: when the additional impedances are small compared with |Z_q|, they are individually
poorly determined, while the current they predict within the tested range stays well determined. If the estimators
differ by more than 20 % in Z_q, a hint compares their currents at the middle of the tested range and says whether the
prediction is stable (within 5 %). An invented equivalent with small measurement errors in three tests:

```python
import numpy as np
from groundfault import equivalent_source as es, formulas as fml

Uq, Zq = 140 * np.exp(1j * np.deg2rad(25)), 6.5 - 2.4j            # invented two-terminal equivalent of one order
Z = np.array([0.0, 2.0, 6.0])                                      # additional impedances in Ω
I = Uq / (Zq + Z)                                                  # exact currents
err = np.array([1.004, 0.997, 1.002]) * np.exp(1j * np.deg2rad([0.2, -0.3, 0.1]))
I_meas = I * err                                                   # with small measuring errors

for name, (u, z) in (("equation error", es.fit_equation_error(I_meas, Z)[:2]),
                     ("output error", es.fit_output_error(I_meas, Z)),
                     ("pair 0 Ω / 6 Ω", fml.source_from_two_measurements(I_meas[0], Z[0], I_meas[2], Z[2]))):
    print("%-15s U_q = %6.2f V ∠ %5.1f°  Z_q = %.3f %+.3fj Ω  I(Z_E = 1 Ω) = %.3f A"
          % (name, abs(u), np.degrees(np.angle(u)), z.real, z.imag, abs(u / (z + 1.0))))
print("%-15s U_q = %6.2f V ∠ %5.1f°  Z_q = %.3f %+.3fj Ω  I(Z_E = 1 Ω) = %.3f A"
      % ("true", abs(Uq), 25.0, Zq.real, Zq.imag, abs(Uq / (Zq + 1.0))))
```

```text
equation error  U_q = 139.52 V ∠  24.9°  Z_q = 6.460 -2.397j Ω  I(Z_E = 1 Ω) = 17.807 A
output error    U_q = 138.69 V ∠  24.7°  Z_q = 6.403 -2.418j Ω  I(Z_E = 1 Ω) = 17.809 A
pair 0 Ω / 6 Ω  U_q = 139.88 V ∠  25.0°  Z_q = 6.462 -2.407j Ω  I(Z_E = 1 Ω) = 17.841 A
true            U_q = 140.00 V ∠  25.0°  Z_q = 6.500 -2.400j Ω  I(Z_E = 1 Ω) = 17.779 A
```

The parameters deviate by up to 1.5 %, the predicted current at 1 Ω by less than 0.4 %.

**R_q ≥ 0.** A passive network has a non-negative source resistance. If the free fit gives R_q < 0 and
`rq_non_negative` is set (default), the boundary solution R_q = 0 is fitted instead – the unknowns are then X_q (real)
and U_q (complex) in \( \underline{U}_q - jX_q\,\underline{I}_k = \underline{I}_k\,\underline{Z}_k \), again by linear
least squares ([`fit_rq0`](../reference/equivalent_source.md#groundfault.equivalent_source.fit_rq0); column
`Rq_fixed`). The hint gives the currents of both solutions at the middle of the tested range: the boundary solution is
not necessarily the conservative one.

## Checks

| Check | What it shows |
|---|---|
| `residual_pct` | relative RMS deviation of the model currents from the (normalised) measured currents, ‖I − U_q/(Z_q + Z)‖/‖I‖ |
| `pairwise_table()` | the closed-form solution of every pair of tests – all pairs should give the same equivalent; a negative R_q (`R_q < 0`) contradicts the model assumption |
| `forecast_table()` | model current against measured current per test and order |
| `dZq_rel_per_1pct` | sensitivity: the largest relative change of Z_q if one current is falsified by ±1 % in magnitude or ±0.5° in angle; above 0.1 the hint “ill-conditioned” appears (additional impedances small compared with \|Z_q\|) |
| Thevenin check | with complex normalisation −U_q divided by the level of the series (`Uq_ref_faulted_phase`, `Uq_angle_ref_faulted_phase_deg`) should be ≈ 1∠0°, since U_q is the pre-fault voltage of the faulted phase; outside 0.5…2 or ±45° a hint asks to check normalisation, polarity or the series |
| `jackknife_table(Z_E)` | with three or more tests: the current at Z_E when the fit is repeated without one test at a time – minimum, maximum and span |
| `monte_carlo(series, Z_E)` | the fit repeated with random errors (default 1 % and 0.5° on the currents, plus the fit residual of each order as model error, 2 % on the additional impedances, optionally on the levels): quantiles P5/P50/P95 of I_RES and I_H at Z_E and the spread of Z_q per order (entry `Zq`: 5 % and 95 % quantiles of R_q and X_q) |
| `check_table()` | the residual current of the model at the tested impedances – with the level, the fundamental and the remaining harmonic content of each test – against its measured true RMS value; a negative deviation together with a large `I_low_frequency_A` comes from a decaying DC component in the max window |

For the demo series, the Thevenin check is 1∠0° within 0.1 % and 0.1°, and every pair of tests gives the same source
impedance at 250 Hz:

```python
series = es.fit_equivalent_source(measurements)         # defaults: orders "auto", complex normalisation
print(series.source_table()[["order", "sequence", "normalization", "Uq_ref_faulted_phase",
                             "Uq_angle_ref_faulted_phase_deg", "dZq_rel_per_1pct"]].round(3).to_string(index=False))
print(series.pairwise_table().query("order == 5").round(3).to_string(index=False))
```

```text
 order sequence normalization  Uq_ref_faulted_phase  Uq_angle_ref_faulted_phase_deg  dZq_rel_per_1pct
     3     zero          none                   NaN                             NaN             0.022
     5      neg       complex                 1.000                          -0.009             0.021
     7      pos       complex                 1.000                           0.015             0.027
    11      neg       complex                 1.001                           0.065             0.017
    13      pos       complex                 0.999                           0.072             0.022
 order        pair  Rq_Ohm  Xq_Ohm    Uq_V  dZq_rel_per_1pct assessment
     5 0 Ω / 2.5 Ω   4.500  -2.500 220.002             0.030         ok
     5   0 Ω / 5 Ω   4.498  -2.501 219.963             0.020         ok
     5 2.5 Ω / 5 Ω   4.496  -2.504 219.924             0.057         ok
```

`report.source_plane(series, mc)` shows these checks in the complex plane: per order the fitted source impedance
(●), the pairwise solutions (×) and, with the result `mc` of `monte_carlo`, a shaded box over the 5–95 % range of R_q
and X_q of the Monte Carlo runs. The campaign notebook exports the figure as `source_impedance`.

```python
from groundfault import report

mc = es.monte_carlo(series, 2.5, n=2000)                 # random errors of currents, impedances and the model
for m in (5, 7):
    z = mc["Zq"][m]
    print("order %d: R_q %.3f … %.3f Ω, X_q %.3f … %.3f Ω" % (m, z["Rq_P5"], z["Rq_P95"], z["Xq_P5"], z["Xq_P95"]))
fig = report.source_plane(series, mc)                    # one shaded box per order
```

```text
order 5: R_q 4.250 … 4.746 Ω, X_q -2.735 … -2.275 Ω
order 7: R_q 6.530 … 7.483 Ω, X_q -3.959 … -3.069 Ω
```

The boxes contain the source impedances of the demo network, 4.5 − j2.5 Ω and 7 − j3.5 Ω.

## Residual current at the earthing impedance

With the fitted equivalents, the residual earth-fault current at an earthing impedance Z_E is
([`ires_at_impedance`](../reference/equivalent_source.md#groundfault.equivalent_source.ires_at_impedance))

\[
I_\text{RES}(Z_\text{E}) = \sqrt{I_\text{G}^2
  + \sum_m \left\lvert\frac{k_m\,\underline{U}_{q,m}}{\underline{Z}_{q,m} + Z_\text{E}}\right\rvert^2
  + I_\text{rest}^2}
\]

* I_G – the fundamental component: the largest measured value of the series (`IG="max"`, conservative), the median,
  or a number in A (e.g. from network data).
* k_m – the scaling factors to the 95 % quantile (below; 1 without scaling).
* I_rest – the harmonic content not covered by the fitted orders. Per test it is computed from the phasors of the same
  window, \( \sqrt{\max(I_{\text{H},\Sigma}^2 - \sum_{m\,\text{fitted}}\lvert\underline{I}_m\rvert^2,\,0)} \) with
  I_H,Σ over the orders 2 to 40 – only the small orders that are not covered remain. (The alternative
  √(I_RES² − I_G² − Σ|I_m|²) is a difference of large numbers: an error of 0.05 % in I_RES = 80 A alone would give a
  “rest” of about 2.5 A.) The largest value of the series is used, independent of Z_E – conservative; `rest=False`
  leaves it out.

The result also contains the currents per order, `IRES_assessed` = I_RES·(1 + m_I) with the measurement-uncertainty
margin m_I that you define (`uncertainty_I`, default 0 – no margin) and `interpolation`: whether |Z_E| lies within the
range of the tested additional impedances – outside, the value is an extrapolation of the model.

## Scaling to the 95 % quantile

Per order, the source voltage is scaled to the 95 % quantile of the harmonic voltage from a power-quality measurement:

\[
k_m = k_\text{s}\,\frac{U_{95,m}}{\tilde{U}_m}
\]

with the level \(\tilde{U}_m\) of the order during the tests (`level_reference_V`, a sequence voltage line-to-earth)
and a factor k_s that you define (`safety_factor`, default 1 – no factor). `u95` gives the quantiles per order, either
as sequence voltages line-to-earth (`u95_reference="seq"`) or line-to-line as a power-quality instrument reports them
(`"LL"`, divided by √3). Zero-sequence orders cannot be scaled with line-to-line values – a line-to-line voltage
contains no zero sequence – and neither can orders without a level or without a value. They get the flat factor
\( k = k_\text{s}\,\mathrm{THD}_{95}/\mathrm{THD}_\text{series} \) if `thd95_percent` and the THD of the series are
given, otherwise they stay unscaled (hint). The remainder I_rest is scaled with the largest factor. Without `u95`, the
flat THD factor applies to all orders. The scaled results are `IH_scaled`, `IRES_scaled` and `IRES_scaled_assessed`;
an example is in [Campaign evaluation](../user-guide/campaign.md#scaling-to-a-power-quality-measurement).

## Fault behind a line

For a fault at a station behind a line with the positive- and zero-sequence impedances Z_1L and Z_0L (and Z_2L = Z_1L),
the line impedances add to the sequence impedances of the source
([`ires_over_line`](../reference/equivalent_source.md#groundfault.equivalent_source.ires_over_line)):

\[
\underline{I}_m = \frac{3\,k_m\,\underline{U}_{q,m}}{3\underline{Z}_{q,m} + 2\underline{Z}_{1L,m} + \underline{Z}_{0L,m} + 3Z_\text{E}}
\]

Z_1L and Z_0L can be functions of the order (e.g. from [line parameters](assessment.md#line-parameters)). For a line of
zero length this is the residual current at the earthing impedance; with the source impedance neglected and purely
resistive lines it becomes the [resistive approach](assessment.md#resistive-approach).

```python
r = es.ires_at_impedance(series, 2.5)
line = es.ires_over_line(series, 2.5, Z1L=0.0, Z0L=0.0)          # a fault directly at the substation
print("I_RES(2.5 Ω) = %.3f A, behind a line of zero length %.3f A, rest %.3f A" % (r["IRES"], line["IRES"], r["IH_rest"]))
```

```text
I_RES(2.5 Ω) = 45.587 A, behind a line of zero length 45.587 A, rest 0.012 A
```
