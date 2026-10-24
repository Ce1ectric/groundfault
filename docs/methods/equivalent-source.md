# Equivalent-source method

The harmonic content of the residual current depends on the impedance of the fault path: at a substation test with
an additional impedance in the fault branch it is smaller than with a solid fault, and at a station it depends on the
earthing impedance there. The **equivalent-source method** determines from a series of substation tests with
different additional impedances Z_k, per harmonic order, the active two-terminal equivalent of the network seen from
the fault – and from it the residual earth-fault current at any earthing impedance Z_E. The functions are in
[`groundfault.equivalent_source`](../reference/equivalent_source.md); the campaign notebook runs them
([Campaign evaluation](../user-guide/campaign.md#equivalent-source-method), where the tables and hints are listed).
The network model of the optional [forecast](../forecast/model.md) determines the same equivalent from the busbar
voltages of each single test – a second method for the same series – and also learns from earth faults recorded
without fault current.

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
complex   5: Z_q = 4.50 -2.50j Ω, residual 0.00 % | 7: Z_q = 7.00 -3.49j Ω, residual 0.00 %
magnitude 5: Z_q = 3.13 -2.74j Ω, residual 12.78 % | 7: Z_q = 3.89 -3.75j Ω, residual 14.16 %
None      5: Z_q = 2.82 -2.52j Ω, residual 15.64 % | 7: Z_q = 3.37 -3.27j Ω, residual 17.54 %
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
| Thevenin check | with complex normalisation −U_q divided by the level of the series (`Uq_ref_faulted_phase`, `Uq_angle_ref_faulted_phase_deg`) should be ≈ 1∠0°, since U_q is the pre-fault voltage of the faulted phase; beyond ±10 % or ±10° (`thevenin_tolerance`, [`THEVENIN_TOLERANCE`](../reference/equivalent_source.md#groundfault.equivalent_source.THEVENIN_TOLERANCE)) a hint says that the fitted source has absorbed changes of the network – reliable within the tested range, beyond it use the [measured source](#measured-source); outside 0.5…2 or ±45° the hint first asks to check normalisation, polarity or the series ([below](#within-and-beyond-the-tested-range)) |
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
     5      neg       complex                 1.000                          -0.003             0.021
     7      pos       complex                 0.999                           0.055             0.027
    11      neg       complex                 1.001                           0.022             0.017
    13      pos       complex                 0.999                          -0.068             0.022
 order        pair  Rq_Ohm  Xq_Ohm    Uq_V  dZq_rel_per_1pct assessment
     5 0 Ω / 2.5 Ω     4.5  -2.499 219.984             0.030         ok
     5   0 Ω / 5 Ω     4.5  -2.501 220.009             0.020         ok
     5 2.5 Ω / 5 Ω     4.5  -2.504 220.035             0.057         ok
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
order 5: R_q 4.250 … 4.747 Ω, X_q -2.735 … -2.275 Ω
order 7: R_q 6.526 … 7.478 Ω, X_q -3.949 … -3.060 Ω
```

The boxes contain the source impedances of the demo network, 4.5 − j2.5 Ω and 7 − j3.5 Ω.

## Within and beyond the tested range

The fit takes two complex unknowns from currents that often differ only a little. Rearranged, the model is a straight
line of the reciprocal current over the additional impedance,

\[
\frac{1}{\underline{I}_{k}} = \frac{\underline{Z}_{q}}{\underline{U}_{q}} + \frac{Z_k}{\underline{U}_{q}}
\]

with the slope 1/U_q. When the additional impedances are small compared with |Z_q|, the slope – and with it U_q –
rests on a small difference between the currents. A deviation δ of a current from the model then changes U_q by about
V·δ,

\[
V = \frac{\sqrt{\lvert\underline{I}_1\rvert^2 + \lvert\underline{I}_2\rvert^2}}{\lvert\underline{I}_1 - \underline{I}_2\rvert}
\]

with the (normalised) currents at the smallest and the largest additional impedance: V ≈ 2 when the current halves
over the tested range, V ≈ 4 when it falls only to 70 %. Such deviations are not only measuring errors: the network
itself changes a little between tests that are minutes apart – loads, switching state, the harmonic sources –, and
the normalisation removes the change of the source level, not that of Z_q. Within the tested range the errors of U_q
and Z_q compensate each other, since the fitted curve still passes through the measured currents; at a larger earthing
impedance or behind a line they do not. An invented equivalent whose source impedance changes by 3–5 % and 5–8°
between three tests:

```python
import numpy as np
from groundfault import equivalent_source as es

Uq, Zq = 200.0, 9 * np.exp(-1j * np.deg2rad(25))       # invented equivalent of one order; U_q = pre-fault level
Z = np.array([0.0, 2.0, 4.0])                            # additional impedances of the tests in Ω
drift = np.array([1.0, 1.05 * np.exp(-1j * np.deg2rad(8)), 0.97 * np.exp(1j * np.deg2rad(5))])
I = Uq / (Zq * drift + Z)                                # the network changes a little between the tests
Uf, Zf, _ = es.fit_equation_error(I, Z)                  # source voltage fitted from the currents
Zk = Uq / I - Z                                          # source voltage measured: Z_q of every test
Zm = np.median(Zk.real) + 1j * np.median(Zk.imag)
V = np.sqrt(abs(I[0]) ** 2 + abs(I[-1]) ** 2) / abs(I[0] - I[-1])
print("currents %s A, V = %.1f, fitted |U_q|/U_pre = %.2f" % (" / ".join("%.2f" % abs(i) for i in I), V, abs(Uf) / Uq))
for name, Zx in (("Z_E = 2 Ω", 2.0), ("Z_E = 12 Ω", 12.0), ("line 4 + j9 Ω", 4 + 9j)):
    true, fit, meas = Uq / abs(Zq + Zx), abs(Uf / (Zf + Zx)), Uq / abs(Zm + Zx)
    dev = lambda x: round(100 * (x / true - 1)) + 0.0     # deviation in %, without "−0"
    print("%-13s true %5.2f A | fitted source %5.2f A (%+.0f %%) | measured source %5.2f A (%+.0f %%)"
          % (name, true, fit, dev(fit), meas, dev(meas)))
```

```text
currents 22.22 / 17.89 / 15.92 A, V = 3.7, fitted |U_q|/U_pre = 0.80
Z_E = 2 Ω     true 18.44 A | fitted source 18.27 A (-1 %) | measured source 18.44 A (+0 %)
Z_E = 12 Ω    true  9.75 A | fitted source  8.79 A (-10 %) | measured source  9.75 A (+0 %)
line 4 + j9 Ω true 15.13 A | fitted source 14.64 A (-3 %) | measured source 15.13 A (+0 %)
```

The fitted source voltage is 20 % too small, the source impedance compensates it within the tested range, and the
prediction at 12 Ω is 10 % too low. Two consequences:

* **Check the source voltage.** For every order whose source is the pre-fault voltage – all orders except those of the
  zero sequence – the Thevenin check −U_q/level should be ≈ 1∠0°. A deviation of more than about 10 % or 10° shows
  that U_q has absorbed changes of the network (a hint says so). Beyond the tested range, compute with the *measured*
  source instead: U_q = the pre-fault level of the faulted phase and Z_q = U_q/I_k − Z_k, from the test without
  additional impedance or as the median over the tests – one test suffices, the others check it
  ([Measured source](#measured-source)). This is how the network model of the [forecast](../forecast/model.md) is
  calibrated.
* **Choose the largest additional impedance of the order of |Z_q|** of the dominant order, so that its current about
  halves (V ≈ 2), if the fitted source is to be used beyond the tested range.

At the orders of the zero sequence the source arises during the fault (saturation at full displacement voltage) and
the pre-fault level is not the source: there the fitted source is the appropriate model, and its fit is usually well
conditioned because |Z_q| is small at these orders.

## Measured source

[`measured_source`](../reference/equivalent_source.md#groundfault.equivalent_source.measured_source) turns a fitted
series into one with the **measured** source voltage. In the frame of the complex-normalised currents
\(\underline{I}'_{m,k}\) the pre-fault voltage of the faulted phase is the level \(\tilde{U}_m\) of the series, and

\[
\underline{U}_{q,m} = -\tilde{U}_m,
\qquad
\underline{Z}_{q,m,k} = \frac{\underline{U}_{q,m}}{\underline{I}'_{m,k}} - Z_k
\]

(the minus sign is the current orientation of the angle method). For the test without additional impedance this is
the rule of the active two-terminal network – internal impedance equals open-circuit voltage divided by short-circuit
current. One test suffices: `impedance="median"` (default) takes the median of Z_q,k over the tests (real and
imaginary part) – a change of the network between the tests enters as the middle state –, `impedance="smallest"` the
test with the smallest additional impedance – normally the solid fault, whose current the model then reproduces, and
the other tests check it in `forecast_table()`. `loo_table(limit_pct)` checks either rule test by test: every test is
forecast with the model of the others and compared with its measured current; the permissible deviation – in per
cent and, for the small currents of the higher orders, in ampere – is yours to set (none by default).

* **Zero sequence:** the orders 3, 9, 15 … keep the fitted equivalent, with a hint – their source arises in the fault.
  So do orders without a complex level and, with `orders=[…]`, the orders not listed.
* **One test is enough:** `measured_source` also takes the measurements themselves (`load_series(…)`). With two or
  more different additional impedances they are fitted first; with a single test – often only the test without
  additional impedance exists – the measured source is the only equivalent, and the zero-sequence orders stay in the
  remainder I_rest with their measured current, independent of Z_E (on the safe side, since their current falls with
  Z_E).
* **R_q < 0:** a median Z_q with a negative real part is no pure network impedance (the network changed between the
  tests, or a source arises in the fault). With `rq_non_negative` (the setting of the series, default) R_q = 0 is used
  with |Z_q| kept: the current at Z_E = 0 stays the measured one, and for an ohmic Z_E the current becomes
  \(\lvert\underline{U}_q\rvert/\sqrt{\lvert\underline{Z}_q\rvert^2 + Z_\text{E}^2}\) – a bound on the safe side.
* **Tables and functions:** every method of the series works with it – `ires_at_impedance`, `ires_over_line`,
  `monte_carlo` (which determines Z_q again from the falsified currents and keeps the measured U_q),
  `jackknife_table` and `loo_table` (from two tests on). `single_test_table()` lists Z_q,k of every single test: its
  spread is the change of the network between the tests that the fitted source absorbs into U_q.
  [`compare_sources(measured, fitted, Z_E)`](../reference/equivalent_source.md#groundfault.equivalent_source.compare_sources)
  gives the current per order and I_RES with both sources at one or more Z_E.

Three demo recordings in which the network itself changes a little between the tests – the source impedance of every
order by 5 % and −8° in the 2.5-Ω test and by −3 % and +5° in the 5-Ω test:

```python
import dataclasses

change = {0.0: 1.0, 2.5: 1.05 * np.exp(-0.14j), 5.0: 0.97 * np.exp(0.09j)}   # the network per test
folder = tempfile.mkdtemp()
entries = []
for k, (z, c) in enumerate(change.items()):
    sources = [dataclasses.replace(h, Zq=h.Zq * c) for h in demo.DEFAULT_HARMONICS]
    path = os.path.join(folder, "SUB_%d.cfg" % k)
    demo.make_substation_recording(path, z, harmonic_sources=sources, seed=k)
    res = gf.evaluate(gf.open_recording(path), gf.Intervals((2.6, 4.4), (0.2, 1.8), (7.0, 8.8)), z_fault_ohm=z)
    entries.append(dict(file=res.save_json(path.replace(".cfg", "_result.json")), Z=z, name="%g Ω" % z))
fitted = es.fit_equivalent_source(es.load_series(entries), orders=[5, 7])
measured = es.measured_source(fitted)
print(measured.single_test_table().query("order == 7")[["measurement", "Rq_Ohm", "Xq_Ohm", "Zq_deviation_pct",
                                                         "Zq_angle_deviation_deg"]].round(2).to_string(index=False))
print(es.compare_sources(measured, fitted, [0.0, 5.0, 10.0]).query("order == 7")[
    ["Z_E_Ohm", "Uq_fitted_to_measured", "I_measured_source_A", "I_fitted_source_A", "fitted_to_measured",
     "interpolation"]].round(3).to_string(index=False))
print(measured.fits[7].hints[0])
print(measured.loo_table().query("order == 7")[["measurement", "I_measured_A", "I_from_others_A",
                                                "deviation_pct"]].round(2).to_string(index=False))
```

```text
measurement  Rq_Ohm  Xq_Ohm  Zq_deviation_pct  Zq_angle_deviation_deg
        0 Ω    7.00   -3.50              0.00                    0.00
      2.5 Ω    6.77   -4.67              5.04                   -8.03
        5 Ω    7.07   -2.77             -3.00                    5.16
Z_E_Ohm  Uq_fitted_to_measured  I_measured_source_A  I_fitted_source_A  fitted_to_measured  interpolation
      0                  0.892               14.056             14.215               1.011           True
      5                  0.892                8.800              8.584               0.975           True
     10                  0.892                6.337              6.042               0.953          False
fitted equivalent source: −U_q/level = 0.89∠-3°; current fitted/measured source 0.98 at Z = 5 Ω (tested range), 0.95 at Z = 10 Ω
measurement  I_measured_A  I_from_others_A  deviation_pct
        0 Ω         14.06            14.01          -0.35
      2.5 Ω         10.60            10.96           3.38
        5 Ω          8.88             8.75          -1.46
```

The single tests show the change of the network; the fitted source voltage has absorbed it (0.89 of the pre-fault
voltage). Within the tested range both sources agree to 2.5 %; at 10 Ω the fitted source gives 4.6 % less. The
deviation grows with |Z_q| compared with the largest additional impedance and with the change of the network between
the tests ([Within and beyond the tested range](#within-and-beyond-the-tested-range)). The measured series (median of
the tests, here the values of the test without additional impedance) gives the source impedance of the demo network,
7 − j3.5 Ω, and its currents. The leave-one-out check forecasts every test with the median of the other two: the
change of the network appears as a deviation of a few per cent – how much is acceptable is your choice
(`limit_pct`).

The campaign notebook computes the result with the measured source (`SOURCE = "measured"`) and draws the fitted one
dashed for comparison; `report.source_fit`, `report.ires_over_ze`, `report.report_tables` and the interactive figures
take the second series as `comparison`, and `report.source_plane` marks the single tests of a measured series (+)
([Campaign evaluation](../user-guide/campaign.md#measured-source)).

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

Each order is scaled by its sequence to the 95 % quantile of the harmonic voltage from a power-quality measurement of
the same network and switching state
([`order_scaling`](../reference/formulas.md#groundfault.formulas.order_scaling)):

* **Positive or negative sequence** (odd orders that are not a multiple of 3: 5, 7, 11, 13, 17, 19 …) – with its own
  voltage,

  \[
  k_m = k_\text{s}\,\frac{U_{95,m}}{\tilde{U}_m}
  \]

  with the level \(\tilde{U}_m\) of the order during the tests (`level_reference_V`, a sequence voltage
  line-to-earth) and a factor k_s that you define (`safety_factor`, default 1 – no factor). `u95` gives the quantiles
  per order, either as sequence voltages line-to-earth (`u95_reference="seq"`) or line-to-line as a power-quality
  instrument reports them (`"LL"`, divided by √3). An order without its own value – no quantile, or no level of at
  least `settings["min_level_V"]` (1 V) – gets the flat factor
  \( k = k_\text{s}\,\mathrm{THD}_{95}/\mathrm{THD}_\text{series} \) if `thd95_percent` and the THD of the series are
  given, otherwise it stays as measured (hint). Without `u95` the flat THD factor applies to all of these orders.
* **Zero sequence** (odd multiples of 3: 3, 9, 15 …) – as measured (k = 1). Its source arises in the earth fault – the
  displaced neutral and the loads on the healthy phases –, so the PQ measurement of undisturbed operation says nothing
  about it.
* **Even orders** (2, 4, 6, 8 …) – as measured and listed separately; a hint names them from 5 % of the harmonic
  content: unusual for the voltage of a network, they may point to another cause.

The **remainder** I_rest outside the orders of the model follows the same rules order by order: per test its orders
\( \lvert\underline{I}_m\rvert \) with the levels \( \tilde{U}_{m,k} \) of the same test, the content without a phasor
(orders above those of the result file) as measured; the test with the largest scaled remainder is used (independent
of Z_E, as for the unscaled remainder). The result per order is the table `table` of the result: the orders of the
model at Z_E and the orders of the remainder with their test, level, quantile, factor and rule (`own voltage`, `THD`,
`as measured`, `no information`). The scaled results are `IH_scaled`, `IRES_scaled`, `IRES_scaled_assessed` and
`IH_rest_scaled`, the parts not scaled `IH_zero`, `IH_even` and `IH_other`; an example is in
[Campaign evaluation](../user-guide/campaign.md#scaling-to-a-power-quality-measurement).

The scaling per order assumes that all orders reach their quantile at the same time. For a time series of harmonic
voltages – e.g. the 10-min values of a PQ measurement –
[`ires_over_time`](../reference/equivalent_source.md#groundfault.equivalent_source.ires_over_time) gives I_RES at Z_E
for every time step, with k_m(t) = k_s·U_m(t)/Ũ_m; its quantile is the quantile of the residual current itself and is
at most the result per order when the orders rise together (comonotone), smaller when they do not.

The level Ũ_m is the natural-sequence voltage at the faulted phase, while a PQ instrument records line-to-earth
voltages. The largest phase contains the other sequences of the order as well,
\( \max_x |\underline{U}_x| \geq \sqrt{(|\underline{U}_0|^2 + |\underline{U}_1|^2 + |\underline{U}_2|^2)} \geq |\underline{U}_\text{nat}| \),
so k_m = k_s·U95,m/Ũ_m is at least the ratio of the largest phases of the PQ measurement and of the tests.

## Fault behind a line

For a fault at a station behind a line with the positive- and zero-sequence impedances Z_1L and Z_0L (and Z_2L = Z_1L),
the line impedances add to the sequence impedances of the source
([`ires_over_line`](../reference/equivalent_source.md#groundfault.equivalent_source.ires_over_line)):

\[
\underline{I}_m = \frac{3\,k_m\,\underline{U}_{q,m}}{3\underline{Z}_{q,m} + 2\underline{Z}_{1L,m} + \underline{Z}_{0L,m} + 3Z_\text{E}}
\]

Z_1L and Z_0L can be functions of the order (e.g. from [line parameters](assessment.md#line-parameters)). For a line of
zero length this is the residual current at the earthing impedance; with the source impedance neglected and purely
resistive lines it becomes the [resistive approach](assessment.md#resistive-approach). A line lies beyond the tested
range: check the source voltage first ([Within and beyond the tested range](#within-and-beyond-the-tested-range)) –
the forecast computes the fault behind a line with the measured source and line values per order
([Fault behind a line](../forecast/model.md#fault-behind-a-line)).

```python
r = es.ires_at_impedance(series, 2.5)
line = es.ires_over_line(series, 2.5, Z1L=0.0, Z0L=0.0)          # a fault directly at the substation
print("I_RES(2.5 Ω) = %.3f A, behind a line of zero length %.3f A, rest %.3f A" % (r["IRES"], line["IRES"], r["IH_rest"]))
```

```text
I_RES(2.5 Ω) = 45.589 A, behind a line of zero length 45.589 A, rest 0.012 A
```

## Network expansion

Network planning asks whether further cables can be connected at the substation: up to which capacitive earth-fault
current I_C does the residual current keep the limits? Further cables raise the earth capacitance and the operating
capacitance of the network, and the coils are retuned to the same detuning, I_L,new = I_L·I_C,new/I_C. The equivalent
sources describe the fault loop at every order as an active two-terminal network – the source voltage U_q and the
source impedance Z_q = (Z_0 + Z_1 + Z_2)/3 with Z_2 = Z_1 ([fault loop](../forecast/model.md#fault-loop-per-order)).
The expansion changes its parts
([`network_expansion`](../reference/equivalent_source.md#groundfault.equivalent_source.network_expansion);
ΔI_C = I_C,new − I_C, ΔI_L likewise, d_a the damping I_w/I_C of the new cables):

* **Zero sequence** – the added earth admittance with its losses and the retuned coils lie in parallel with Z_0:

  \[
  \frac{1}{\underline{Z}_{0,\text{new}}} = \frac{1}{\underline{Z}_0}
    + \frac{j\,m\,\Delta I_C + d_a\,\Delta I_C - j\,\Delta I_L/m}{3\,U_\text{LE}}
  \]

* **Positive and negative sequence** – the operating capacitance of the new cables, C_1 = c·C_E (`c1_ratio`, 1 for
  cables with a screen per core), lies in parallel with the busbar and shifts its parallel resonance to lower orders:

  \[
  \frac{1}{\underline{Z}_{1,\text{new}}} = \frac{1}{\underline{Z}_1} + \frac{j\,m\,c\,\Delta I_C + d_a\,\Delta I_C}{3\,U_\text{LE}}
  \]

* **Source** – the harmonic voltage of the busbar comes from sources outside the new cables (HV network, loads) and
  acts on the busbar impedance, \( \underline{U}_{q,\text{new}} = \underline{U}_q\,\underline{Z}_{1,\text{new}}/\underline{Z}_1 \)
  – for a source behind the upstream impedance (U = E·Z_1/Z_up) and for a current source of the MV network
  (U = Z_1·I) alike. At the orders of the zero sequence the source arises in the fault, U_s = Z_0·I_Nh/3 with the
  nonlinear current I_Nh of the coils; it grows with Z_0 and, taken proportional to the current of the coils, with
  I_L,new/I_L (`zero_sequence="network"`: without that factor).
* **Fundamental** – the active current grows with the damping of the new cables, the detuning current with I_C:
  I_w,new = I_w + d_a·ΔI_C, I_v,new = I_v·I_C,new/I_C.

The changes are added to the measured Z_q – I_C,new = I_C returns the series unchanged. Orders outside the model (the
remainder, even orders without a fit) keep their measured content, and new harmonic sources that come with the cables
(converters, for instance) are not included.

**Split of the source impedance.** The equivalent sources give Z_q, not its split into Z_0 and Z_1, and the two change
differently. `split` takes it in one of two ways:

| `split` | Z_0 | Z_1 |
|---|---|---|
| `"sources"` (default) | from network data ([`zero_sequence_impedance`](../reference/formulas.md#groundfault.formulas.zero_sequence_impedance)): 1/(j·(m/X_C0 − 1/(m·X_L0))) + d·X_C0 with X_C0 = 3·U_LE/I_C, X_L0 = 3·U_LE/I_L | (3·Z_q − Z_0)/2 |
| `"busbar"` | from the busbar voltages of the tests ([`busbar_impedances`](../reference/equivalent_source.md#groundfault.equivalent_source.busbar_impedances), the [B method](../forecast/model.md#calibration-with-a-staged-fault-test)): 3·p_0·ΔU_0/I, median of the tests; at the orders of the zero sequence 3·Z_q − 2·Z_1 | 3·p_s·ΔU_s/I in the sequence that is not the natural one of the order (positive at the 5th, negative at the 7th) |

At the orders of the zero sequence the source that arises in the fault changes ΔU_0 as well; the equivalent sources
separate it, so Z_0 = 3·Z_q − 2·Z_1 there. `Z0` and `Z1` give the split per order instead. The two ways rest on
different data – the network data on I_C, I_L and the damping, the busbar split on small voltage changes at the
harmonic frequencies –; where the data are consistent they lie close, and their difference shows how well the split is
known. The [report](../user-guide/document.md) computes both and takes the larger residual current.

An order the tests hardly excite may give a busbar split with a negative real part, Re Z_0 < 0 or Re Z_1 < 0. That is
no passive network: added in parallel with the capacitance of the new cables, it can produce a parallel resonance that
does not exist, and with it an implausibly large current of that order. Such an order takes the split from the
network data instead, with a hint (column `busbar_rejected` of the table per order); `split="sources"` is unchanged.

**Validation.** `tests/test_forecast_physics.py` checks the conversion against the nodal calculation of a synthetic
20-kV network – three phases per order, the upstream impedance, earth capacitances with losses, loads, a coil with a
nonlinear current that arises with the fault, harmonic sources behind the upstream impedance and in the MV network –
before and after an expansion (earth and operating capacitance +30 %, the coil retuned): with the busbar split the
currents of the expanded network are reproduced exactly (to 10⁻⁸), with the split from network data within 2 % at
the orders 5 to 13 and 7 % high at the 3rd (the reference network has the damping as a conductance, the network data
as the series resistance d·X_C0).

**Over I_C.** [`expansion_curve`](../reference/equivalent_source.md#groundfault.equivalent_source.expansion_curve)
gives the residual current at Z_E over I_C – with the scaling and the margins of `ires_at_impedance` –, and
[`expansion_limit`](../reference/equivalent_source.md#groundfault.equivalent_source.expansion_limit) the I_C at which
it reaches a limit you define. With the demo series of this page:

```python
import numpy as np

print(es.busbar_impedances(series)[["order", "Z0", "Z1", "Z0_from", "Z1_from"]].round(2).to_string(index=False))
for split in ("sources", "busbar"):
    kw = dict(I_L=620.0, damping=0.033, split=split)           # coils today, damping I_w/I_C
    curve = es.expansion_curve(series, 2.5, 600.0, [600.0, 700.0, 800.0, 900.0], **kw)
    reach = es.expansion_limit(es.expansion_curve(series, 2.5, 600.0, np.linspace(600.0, 2400.0, 181), **kw), 60.0,
                               column="IRES_A")
    print("%-7s" % split, " | ".join("%.0f A: %.1f A" % (r.I_C_A, r.IRES_A) for r in curve.itertuples()),
          "| 60 A at I_C ≈ %.0f A" % reach["I_C_A"])
```

```text
 order           Z0          Z1           Z0_from Z1_from
     3 10.93- 5.62j  0.01-0.03j equivalent_source pos/neg
     5 13.50- 7.50j -0.00+0.00j            busbar     pos
     7 20.99-10.52j -0.00-0.00j            busbar     neg
    11  7.51- 6.59j  0.02+0.03j            busbar     pos
    13 14.98- 8.39j -0.01-0.01j            busbar     neg
sources 600 A: 45.6 A | 700 A: 50.0 A | 800 A: 54.3 A | 900 A: 58.6 A | 60 A at I_C ≈ 931 A
busbar  600 A: 45.6 A | 700 A: 50.2 A | 800 A: 54.7 A | 900 A: 59.1 A | 60 A at I_C ≈ 920 A
```

The demo network is a signal model rather than a network: its harmonic sources are stiff (Z_1 ≈ 0 – the busbar
voltages do not change with the fault) and its source impedance lies in the zero sequence with a large resistance.
The busbar split sees exactly that, the split from network data assumes a cable network with
Z_0 ≈ −j·X_C0/m; so the two differ here by 8 A at 900 A. The 13th order has a slightly negative real part of Z_1 –
noise around zero; `NetworkExpansion.hints` names such an order, whose change is uncertain.
