# Assessment quantities

The assessment quantities describe the residual earth-fault current of a staged fault test: its RMS value, its
fundamental component split into active current and detuning, and its harmonic content – each with a
measurement-uncertainty margin of the user, and optionally scaled to the harmonic level of a power-quality
measurement. They come from the
[max window](signal-processing.md#true-rms-value-and-max-window) of the recording and form the table
`assessment_quantities` ([how to read it](../user-guide/evaluation.md#assessment-quantities)). Further formulas –
the √2 method on a resonance curve, the limit from the permissible touch voltage, the resistive approach and line
parameters – assess a network beyond a single test. The formulas are in [`groundfault.formulas`](../reference/formulas.md);
the conventions (phasors, angle reference, orientation) are listed in [Methods](index.md#conventions).

## Residual earth-fault current

The residual earth-fault current is the **true RMS value** of the main fault-current channel in the max window –
over all frequencies, with the DC component removed:

\[
I_\text{RES} = \sqrt{\frac{1}{N}\sum_{n=0}^{N-1} i_0[n]^2}
\]

(`IRES`). Of all 200-ms windows of the steady-state interval the one with the largest value is taken, which is
conservative. Choose the steady-state interval after the decay of the DC component of the fault inception, otherwise
the check *Low-frequency component of I_RES* warns ([DC removal](signal-processing.md#dc-removal)). From its
components the residual current is \( I_\text{RES} = \sqrt{I_\text{w}^2 + I_\text{v}^2 + I_\text{H}^2} \)
([`residual_current`](../reference/formulas.md#groundfault.formulas.residual_current)). Without measured values,
EN 50522 (Table 1) allows 10 % of the capacitive earth-fault current as the residual current of a well-compensated
network ([`residual_current_estimate`](../reference/formulas.md#groundfault.formulas.residual_current_estimate)) – a
rough estimate without its components.

## Fundamental component

The fundamental component is the magnitude of the phasor at the estimated network frequency in the max window,
\( I_\text{G} = \lvert\underline{I}_1\rvert \) (`IH1`; its angle in the table refers to U_L1-L2). Other ways to it:

| Formula | Function | Use |
|---|---|---|
| \( I_\text{G} = \sqrt{I_\text{w}^2 + I_\text{v}^2} \) | `fundamental_current(Iw, Iv)` | from the components |
| \( I_\text{G} = I_\text{CE}\sqrt{d^2 + v^2} \) | `fundamental_from_network_data(I_CE, d, v)` | from network data: capacitive earth-fault current, damping and detuning |
| \( I_\text{G} = \sqrt{I_\text{min}^2 + I_\text{v}^2} \) | `fundamental_from_v_curve(I_min, Iv)` | from the minimum of the resonance curve (V curve) and the detuning in operation |

The fundamental component hardly depends on the additional impedance of a substation test; the campaign evaluation
checks this between the tests and, by default, uses the largest measured value for the residual current at an
earthing impedance ([Equivalent-source method](equivalent-source.md#residual-current-at-the-earthing-impedance)).

## Active current and detuning: the angle method

The angle method splits the fundamental component with the zero-sequence voltage U0 of the same window – the mean of
the three line-to-earth voltages, or the measured neutral displacement voltage:

\[
I_\text{w} = \lvert\underline{I}_1\rvert\cos(\varphi_{U0} - \varphi_{I1}),
\qquad
I_\text{v} = \lvert\underline{I}_1\rvert\sin(\varphi_{U0} - \varphi_{I1})
\]

([`angle_method`](../reference/formulas.md#groundfault.formulas.angle_method)). The active current Iw comes from the
losses of the network and the coil and is positive for a passive network. The evaluation therefore orients the fault
current so that **Iw > 0**: if Iw comes out negative, the clamp is reversed, and all fault-current phasors are rotated
by 180° (`Settings.correct_polarity`; hint, plausibility status `CORRECTED`). In this orientation **Iv > 0 means
over-compensation**.

The decision is only as safe as the angle measurement. Its **margin** is the angular distance of the current phasor
from the ±90° limit at which Iw changes its sign:

\[
\delta = \arcsin\frac{\lvert I_\text{w}\rvert}{\lvert\underline{I}_1\rvert}
\]

With a large detuning and a small active current δ becomes small; below 10° an angle error of the measuring chain of
that size (CT phase errors, a time offset between voltage and current channels) could reverse the sign of Iw, and the
polarity check reports `UNCERTAIN` with the hint “Polarity decision uncertain …”. Check the polarity of the clamp; if it
is known for sure, set `correct_polarity=False`.

Iw and Iv per window over the whole steady-state interval separate an active residual current increase (Iw changes)
from a coil adjustment (Iv changes) – see the stationarity check in
[Signal processing](signal-processing.md#statistics-over-the-steady-state); `rms.fundamental_trend` gives both over
time.

## Detuning and the √2 method

A tuning run of the coil gives the **resonance curve**: the neutral displacement voltage over the coil current I_L.
For the parallel resonant circuit of the network's zero-sequence system it is

\[
U_\text{NE}(I_L) = \frac{K}{\sqrt{I_\text{w}^2 + (I_\text{res} - I_L)^2}}
\]

with the coil current at resonance I_res and the maximum U_max = K/Iw. At I_L = I_res ± Iw the voltage has dropped to
U_max/√2 – the **√2 method** reads the active current from the two coil currents at which this happens:

\[
I_\text{w} = \frac{I_\text{upper} - I_\text{lower}}{2}
\]

[`sqrt2_method`](../reference/formulas.md#groundfault.formulas.sqrt2_method) evaluates a measured curve in two
independent ways:

1. **Interpolation** – the highest measured point is taken as the resonance, and the crossings with U_max/√2 on both
   sides are interpolated linearly between the measured points.
2. **Fitted curve** – squared and inverted, the resonance curve is a polynomial of second order in I_L,
   \( 1/U_\text{NE}^2 = a I_L^2 + b I_L + c \). A weighted linear least-squares fit over **all** points (weights
   U_NE², i.e. relative errors of U_NE) gives \( I_\text{res} = -b/(2a) \), \( I_\text{w} = \sqrt{c/a - I_\text{res}^2} \)
   and \( U_\text{max} = 1/\sqrt{c - b^2/(4a)} \). It needs no measured point at the maximum or at the crossings and
   is robust against single outliers.

With the coil current in operation, `sqrt2_method` adds the detuning
**Iv = I_operating − I_res** ([`detuning_current`](../reference/formulas.md#groundfault.formulas.detuning_current)),
the fundamental component I_G = √(Iw² + Iv²), the damping d = Iw/I_res and the relative detuning v = Iv/I_res
([`detuning`](../reference/formulas.md#groundfault.formulas.detuning)) – from the interpolation results. Iv > 0 means
over-compensation, the same sign as the angle method ([conventions](index.md#orientation-of-the-fault-current-and-sign-of-the-detuning)).

An invented network with its resonance at 380 A coil current, Iw = 11.4 A and U_max = 6 kV, measured in steps of 4 A
and operated at 400 A:

```python
import numpy as np
from groundfault import formulas as fml

# resonance curve of an invented network: resonance at 380 A coil current, Iw = 11.4 A, U_max = 6 kV
I_res, Iw, U_max = 380.0, 11.4, 6000.0
I_coil = np.arange(350.0, 412.0, 4.0)                        # coil positions of the tuning run
U_ne = U_max * Iw / np.sqrt(Iw ** 2 + (I_res - I_coil) ** 2)  # U_NE = K/√(Iw² + (I_res − I_L)²)
r = fml.sqrt2_method(I_coil, U_ne, I_operating=400.0)
for key in ("I_resonance", "U_max", "I_lower", "I_upper", "Iw", "I_resonance_fit", "Iw_fit", "U_max_fit",
            "Iv", "I_G", "d", "v"):
    print("%-15s %10.4f" % (key, r[key]))
```

```text
I_resonance       378.0000
U_max            5909.7421
I_lower           368.1621
I_upper           391.8379
Iw                 11.8379
I_resonance_fit   380.0000
Iw_fit             11.4000
U_max_fit        6000.0000
Iv                 22.0000
I_G                24.9827
d                   0.0313
v                   0.0582
```

The interpolation is limited by the grid: the highest measured point (378 A) stands in for the resonance, and Iw comes
out 4 % too large. The fitted curve returns the exact values. The operating point lies above the resonance – the
network is over-compensated, Iv = +22 A.

## Harmonic content

The harmonic content is everything in the residual current except the fundamental component:

\[
I_\text{H} = \sqrt{I_\text{RES}^2 - I_\text{G}^2}
\]

(`IH_total`, [`harmonic_current`](../reference/formulas.md#groundfault.formulas.harmonic_current); a negative
radicand from noise is set to zero). It contains the harmonics, interharmonics and noise. As a cross-check the
evaluation also sums the phasors of the orders 2 to 40 of the same window,
\( I_{\text{H},\Sigma} = \sqrt{\sum_{m=2}^{40}\lvert\underline{I}_m\rvert^2} \) (`IH_sum`); for a current that consists
of harmonics only both agree. The plausibility rows *RMS ↔ √ΣX²* report a difference of 5 % or more between I_RES
and the assessed orders (note) or of 3 % or more against the orders 1…40 (warning) – then the window contains
interharmonics, noise or a transient.

The coil compensates the capacitive current at the fundamental frequency only: at the order m its reactance is m
times larger, the capacitive reactance m times smaller, so the harmonic currents of the network flow into the fault
practically uncompensated. They are driven by the harmonic voltages of the network – mostly the orders 5, 7, 11 and
13 in the negative and positive sequence – and depend on the impedance of the fault path, which the
[equivalent-source method](equivalent-source.md) models. The table shows the orders of `Settings.harmonics` (default
1, 3, 5, 7); the table `harmonics` lists all orders up to 40 of every channel, and the result file stores the orders 1
to 25 for the campaign evaluation.

## Measurement uncertainty

The assessment values (column `assessment`) include a relative measurement-uncertainty margin of the measuring chain:

\[
I_\text{assessed} = I_\text{measured}\,(1 + m_I),
\qquad
U_\text{assessed} = U_\text{measured}\,(1 - m_U)
\]

([`current_with_uncertainty`](../reference/formulas.md#groundfault.formulas.current_with_uncertainty),
[`voltage_with_uncertainty`](../reference/formulas.md#groundfault.formulas.voltage_with_uncertainty)). The margins m_I
and m_U (`Settings.uncertainty_I`, `Settings.uncertainty_U`) are parameters the user defines, e.g. from the accuracy of
the measuring chain; groundfault has no default margin – with 0, the assessment value is the measured value. Currents
are increased because a larger residual current is the conservative assumption. Voltages are decreased because the
harmonic voltage measured during the test is the *denominator* of the scaling described next – a smaller value gives
a larger, conservative scaled current. The equivalent-source method applies m_I to the residual current at the
earthing impedance (`IRES_assessed`, argument `uncertainty_I`).

## Scaling to the 95 % quantile of a power-quality measurement

The harmonic voltages of the network during the tests are a snapshot; the harmonic content of the residual current
grows in proportion to them. To assess the residual current at the harmonic level that is not exceeded 95 % of the
time, the harmonic content is scaled with the 95 % quantile of a power-quality measurement (an instrument according
to IEC 61000-4-30) of the same network and switching state. Each order is treated by its sequence
([`harmonic_category`](../reference/formulas.md#groundfault.formulas.harmonic_category),
[`order_scaling`](../reference/formulas.md#groundfault.formulas.order_scaling)):

* **Positive or negative sequence** (odd orders that are not a multiple of 3: 5, 7, 11, 13, 17, 19 …): the current of
  the order is driven by the voltage of the same order and is scaled with it – the 250-Hz current with the 250-Hz
  voltage:

  \[
  I_{m,\text{scaled}} = k_m\,I_m,
  \qquad
  k_m = k_\text{s}\,\frac{U_{95,m}}{U_m}
  \]

  with the quantile U_95,m of the order (`Settings.pq_u95`, line-to-earth of the largest phase; a line-to-line value
  divided by √3) and its level U_m in the test – the natural sequence of the order (positive for m = 7, 13, 19 …,
  negative for m = 5, 11, 17 …) before and after the fault (`Settings.thd_reference`: `"mean"`, `"pre_fault"` or
  `"post_fault"`). An order without its own value – no quantile, or a level below `Settings.pq_min_level_V` (1 V) –
  gets the flat factor of the THD (in % `Settings.u_thd95_percent` or in V `Settings.u_thd95_volt`, both line-to-line):

  \[
  k_\text{THD} = k_\text{s}\,\frac{U_{\text{PQ},95\%}}{U_\text{meas}}
  \]

  where U_meas is the THD (or harmonic voltage) of the largest of the three line-to-line loops, averaged over the
  pre-fault and post-fault intervals. Without a THD such an order stays as measured (with a hint).
* **Zero sequence** (odd multiples of 3: 3, 9, 15 …): not scaled. The zero sequence arises in the earth fault – the
  displaced neutral and the non-linear loads on the healthy phases drive it –, not the harmonic voltage of undisturbed
  operation that the PQ measurement records.
* **Even orders** (2, 4, 6, 8 …, the even multiples of 3 included): not scaled, and listed separately. They are
  unusual for the voltage of a network and may point to another cause (a DC component or saturation at the fault
  inception, current clamps); a hint names them when they carry 5 % of the harmonic content or more.
* **Content without an order** (\( I_\text{other} = \sqrt{I_\text{H}^2 - \sum_{m\geq2} I_m^2} \): interharmonics, DC and
  low-frequency parts, orders without a phasor): not scaled.

\[
I_\text{H,scaled} = \sqrt{\sum_{m\ \text{pos/neg}} \left(k_m I_m\right)^2 + I_0^2 + I_\text{even}^2 + I_\text{other}^2},
\qquad
I_\text{RMS} = \sqrt{I_\text{G}^2 + I_\text{H,scaled}^2}
\]

With the THD alone every order of the positive or negative sequence gets k_THD:
\( I_\text{H,scaled} = \sqrt{(I_\text{H}^2 - I_\text{u}^2)\,k_\text{THD}^2 + I_\text{u}^2} \) with I_u the part not
scaled ([`scaled_harmonic_current`](../reference/formulas.md#groundfault.formulas.scaled_harmonic_current),
[`rms_current_forecast`](../reference/formulas.md#groundfault.formulas.rms_current_forecast)). The factor k_s
(`Settings.pq_safety_factor`) is the factor of the user on the 95 % quantile (default 1: none). The assessment values
combine both margins: the currents are increased by m_I, the voltages of the test decreased by m_U (the factors grow by
1/(1 − m_U)), and I_RMS takes I_G(1 + m_I). The table `assessment_quantities` gets the rows `UTHD_meas`, `UTHD_95`
(with a THD), `IH_zero`, `IH_even`, `IH_other`, `IH_scaled` and `IRMS_forecast`; the table `harmonic_scaling` shows
every order with its level, quantile, factor and rule. The equivalent-source method applies the same rules to the
orders of its model and to its remainder ([Scaling to U95](equivalent-source.md#scaling-to-the-95-quantile)).

```python
from groundfault import formulas as fml

I_RES, I_G = 41.0, 27.0                                      # invented measured values in A
I_H = fml.harmonic_current(I_RES, I_G)                       # √(I_RES² − I_G²)
I_5, I_7, I_3 = 24.0, 12.0, 9.0                              # invented currents of the orders in A
k_s = 1.2                                                    # illustrative factor – define your own
k_5, rule_5 = fml.order_scaling(5, 320.0, 240.0, safety_factor=k_s)    # U_95,5 = 320 V, level 240 V
k_7, rule_7 = fml.order_scaling(7, 150.0, 100.0, safety_factor=k_s)
k_3, rule_3 = fml.order_scaling(3, 40.0, 20.0, safety_factor=k_s)      # zero sequence: as measured
I_other = (I_H ** 2 - I_5 ** 2 - I_7 ** 2 - I_3 ** 2) ** 0.5
I_H_s = ((k_5 * I_5) ** 2 + (k_7 * I_7) ** 2 + (k_3 * I_3) ** 2 + I_other ** 2) ** 0.5
print("k_5 = %.2f (%s), k_7 = %.2f (%s), k_3 = %.2f (%s)" % (k_5, rule_5, k_7, rule_7, k_3, rule_3))
print("I_H = %.2f A → I_H,scaled = %.2f A → I_RMS = %.2f A" % (I_H, I_H_s, fml.rms_current_forecast(I_G, I_H_s)))
# the THD alone (95 % quantile 3.2 %, during the tests 2.4 %): k_THD for the positive/negative sequence
I_u = (I_3 ** 2 + I_other ** 2) ** 0.5                       # zero sequence and content without an order
print("THD alone: I_H,scaled = %.2f A" % fml.scaled_harmonic_current(I_H, 3.2 * k_s, 2.4, I_unscaled=I_u))
```

```text
k_5 = 1.60 (own voltage), k_7 = 1.80 (own voltage), k_3 = 1.00 (as measured)
I_H = 30.85 A → I_H,scaled = 46.62 A → I_RMS = 53.87 A
THD alone: I_H,scaled = 45.55 A
```

## Power-quality measurement

The quantiles above come from a power-quality measurement of the busbar in undisturbed operation
([`groundfault.pq`](../reference/pq.md), [Power-quality measurements](../user-guide/pq.md)):

1. **10-min values.** The shorter values of the export (e.g. 30 s) are combined into clock-aligned 10-min intervals,
   each labelled with its end, as the square root of the mean of their squares (aggregation of IEC 61000-4-30):
   \( U_{10} = \sqrt{\tfrac{1}{n}\sum_{i=1}^{n} U_i^2} \). An interval with missing values is left out.
2. **Largest phase per interval.** Per interval and order the largest of the three line-to-earth voltages, for the THD
   the largest of the three line-to-line loops: \( U_{\max}(t) = \max_{x} U_{x,10}(t) \). The fault can occur in any
   phase, so the phase with the highest voltage at that time counts. Intervals with an earth fault or a dip of one
   phase (smallest line-to-earth fundamental below 0.8 times the largest) are not undisturbed operation and are left
   out. Without a line-to-line THD in the export, the THD of the line-to-earth orders without the zero sequence
   takes its place – a line-to-line voltage contains no zero sequence.
3. **Quantile.** The quantile p (default 0.95) of these values over the measuring period, by linear interpolation
   between the sorted values (with N values, the value at the position (N − 1)·p counted from 0).
4. **Factor.** A factor k_s of the user on the quantile, \( U_{95} = k_\text{s}\,U_{\text{PQ},95\%} \) – set directly
   or chosen by the duration of the measurement from a rule {minimum duration: factor}: the factor of the longest
   minimum duration the measurement reaches. The duration is the longest stretch of gapless values (an interval
   without a value interrupts it). A measurement shorter than every duration of the rule is not valid for the
   assessment – nothing is scaled with it. A measurement that covers less than the variation over the year (seasons,
   holidays) may need a factor above 1; groundfault contains no such value.

The quantile of the largest phase per interval is at least the largest of the quantiles of the single phases. The
harmonic voltage of the loops \( U_\text{H} = \sqrt{\sum_{m\geq 2} U_m^2} \) of the largest loop per interval (from
the THD and the RMS value) gives the harmonic voltage of the [resistive approach](#resistive-approach).

## Limit from the permissible touch voltage

EN 50522 limits the touch voltage to the permissible touch voltage U_Tp, which depends on the fault duration. The
earth potential rise of an earthing system with the earthing resistance R_E and the reduction factor r is
U_E = r·R_E·I_RES; groundfault takes the condition U_E ≤ F·U_Tp, with F the ratio of the permissible earth potential
rise to the permissible touch voltage, and obtains the largest permissible residual current of a network whose largest
earthing resistance is R_E,max:

\[
I_\text{RES,max} = \frac{F\,U_\text{Tp}}{r\,R_\text{E,max}}
\]

([`max_residual_current`](../reference/formulas.md#groundfault.formulas.max_residual_current)). U_Tp and F are
parameters the user defines – from the applicable standard and the specification of the network operator; groundfault
contains no values for them, nor for the limits of the residual current. The VDE Impuls on the residual earth-fault
current ([VDE Impuls](#references)) writes this limit as I_RES,max ≤ 2·U_Tp/R_E,max: groundfault turns its factor 2
into the parameter F and adds the reduction factor r (r = 1 there). A reduction factor r < 1 raises the limit, because
only r·R_E acts in the fault circuit. The evaluation settings hold U_Tp (`Settings.u_tp`), F (`Settings.f_factor`)
and the limits of the residual current (`Settings.ires_limits`) to which the station voltages are extrapolated and
whose largest value is the reference current of the reduction factor; without them these parts are skipped.

```python
from groundfault import formulas as fml

U_Tp, F = 100.0, 2.5                                         # illustrative values – define your own
for R_E, r in ((1.2, 1.0), (1.2, 0.5)):
    print("R_E,max = %.1f Ω, r = %.1f → I_RES,max = %.1f A" % (R_E, r, fml.max_residual_current(R_E, U_Tp, F, r)))
```

```text
R_E,max = 1.2 Ω, r = 1.0 → I_RES,max = 208.3 A
R_E,max = 1.2 Ω, r = 0.5 → I_RES,max = 416.7 A
```

## Resistive approach

The resistive approach of the VDE Impuls on the residual earth-fault current ([VDE Impuls](#references)) estimates for a
whole network, without a series of tests, which fault locations can exceed the permissible residual current. It takes
the worst case: a series resonance of the positive-, negative- and zero-sequence systems – all reactances and the
source impedance are neglected –, a fault resistance of 0, the harmonic sources as voltage sources taken from a
long-term measurement of the busbar voltages at the substation (a high quantile, switching events excluded), and the
largest earthing resistance R_E,max of the network. For a fault behind a line the harmonic voltage U of the network
(all orders above the fundamental, sequence voltage line-to-earth) drives the harmonic current through the series
connection of the three sequence systems plus three times the earthing resistance at the fault; only the line
resistances R_1 + R_2 + R_0 and 3·r·R_E remain:

\[
I_\text{H} = \frac{3\,U}{R_1 + R_2 + R_0 + 3\,r\,R_\text{E,max}}
\]

The residual current stays below I_RES,max as long as \( I_\text{H} \le I_\text{H,perm} = \sqrt{I_\text{RES,max}^2 -
I_\text{G}^2} \), i.e. as long as the line resistance of the fault path R_1 + R_2 + R_0 reaches the **limiting
resistance** – such a fault location is uncritical
([`resistive_assessment`](../reference/formulas.md#groundfault.formulas.resistive_assessment)); with the resistances
per unit length at the dominant harmonic frequency (R_2' = R_1') the limiting resistance becomes a **critical
distance**:

\[
R_\text{lim} = \frac{3\,U}{\sqrt{I_\text{RES,max}^2 - I_\text{G}^2}} - 3\,r\,R_\text{E,max},
\qquad
l_\text{lim} = \frac{R_\text{lim}}{R_1' + R_2' + R_0'}
\]

([`campaign.resistive_approach`](../reference/campaign.md#groundfault.campaign.resistive_approach),
[`limit_resistance`](../reference/formulas.md#groundfault.formulas.limit_resistance),
[`limit_distance`](../reference/formulas.md#groundfault.formulas.limit_distance)). The permissible residual current is
given directly (`I_res_max`) or follows from U_Tp and F of the user with the same r; without either the function
raises an error that names the missing parameters. With r = 1 the limiting resistance is the R_Grenz of the VDE
Impuls; groundfault generalises the approach in a few points:

| | VDE Impuls | groundfault |
|---|---|---|
| permissible residual current | I_RES,max ≤ 2·U_Tp/R_E,max | I_RES,max = F·U_Tp/(r·R_E,max) with F and r as parameters, or given directly (`I_res_max`) |
| earthing resistance in the fault circuit | R_E,max (the worst case) | r·R_E,max – r = 1 reproduces the VDE Impuls; with r < 1 it is consistent with the raised limit |
| harmonic voltage | \( \sqrt{\sum_{\nu>1} U_{q,\max}(\nu)^2} \), sequence values line-to-earth | the same quantity U; line-to-line values of a power-quality instrument are divided by √3 (`from_ll=True`) |
| fundamental component | \( \sqrt{I_{rw,\max}^2 + I_{rb,\max}^2} \) (active and reactive residual current) | I_G = √(Iw² + Iv²) |
| result | R_Grenz, compared with the resistances of each fault path (e.g. from a network calculation) | also the critical distance l_lim from the resistances per unit length |

The factor 3 in R_lim stands for the series connection of the three sequence systems (the fault current is three times
the zero-sequence current); it has nothing to do with the √3 that converts line-to-line into line-to-earth values. How
the quantile of the busbar voltages is formed and over which period they are measured is discussed in the VDE Impuls.
Three outcomes:

* R_lim ≤ 0 – even a fault directly at the substation keeps I_H = U/(r·R_E,max) below I_H,perm: uncritical in the whole
  network;
* R_lim > 0 – stations closer to the substation than l_lim can exceed the limit: verify them individually (e.g. with
  the [equivalent-source method](equivalent-source.md#fault-behind-a-line)) or take countermeasures;
* I_G ≥ I_RES,max – the fundamental component alone reaches the limit: R_lim = ∞, countermeasures regardless of the
  distance.

An invented network – harmonic voltage 600 V line-to-line, I_G = 25 A, R_E,max = 1.5 Ω, r = 1,
R_1' = 0.27 Ω/km, R_0' = 0.62 Ω/km – with illustrative values of U_Tp and F:

```python
from groundfault import campaign

# harmonic voltage 600 V line-to-line (95 % quantile), I_G = 25 A, R_E,max = 1.5 Ω, line resistances in Ω/km
U_Tp, F = 100.0, 2.5                                         # illustrative values – define your own
ra = campaign.resistive_approach(600.0, 25.0, R_E_max=1.5, R1_km=0.27, R0_km=0.62, U_Tp=U_Tp, F=F, from_ll=True)
for key in ("U_seq_V", "I_RES_max_A", "I_H_permissible_A", "R_limit_Ohm", "l_limit_km"):
    print("%-18s %8.3f" % (key, ra[key]))
print(ra["comment"])
# second way: a fault at the critical distance drives exactly the permissible harmonic current
R_line = ra["l_limit_km"] * (0.27 + 0.27 + 0.62)
print("I_H at l_lim = %.3f A" % (3 * ra["U_seq_V"] / (R_line + 3 * ra["R_E_effective_Ohm"])))
```

```text
U_seq_V             346.410
I_RES_max_A         166.667
I_H_permissible_A   164.781
R_limit_Ohm           1.807
l_limit_km            1.558
stations with a line length to the substation below l_lim = 1.56 km can exceed the limit → individual verification (equivalent-source method) or countermeasures; uncritical further away
I_H at l_lim = 164.781 A
```

## Line parameters

The zero-sequence resistance of an overhead line grows with the frequency, because the earth return path adds a
resistance proportional to ω (Carson). For a line without earth wire, per unit length:

\[
\underline{Z}_0' = R_L' + \frac{3\omega\mu_0}{8}
+ j\,\frac{\omega\mu_0}{2\pi}\left(\frac{\mu_r}{4} + 3\ln\frac{\delta_\text{E}}{\sqrt[3]{r_L\,d^2}}\right),
\qquad
\delta_\text{E} = \frac{1.85}{\sqrt{\omega\mu_0/\rho_\text{E}}}
\]

with the conductor resistance R_L', the conductor radius r_L, the geometric mean distance d of the conductors, the
soil resistivity ρ_E and the equivalent depth δ_E of the earth return
([`z0_overhead_line`](../reference/formulas.md#groundfault.formulas.z0_overhead_line),
[`earth_return_depth`](../reference/formulas.md#groundfault.formulas.earth_return_depth)). The real part,
\( R_0' = R_L' + 3\omega\mu_0/8 \) ([`r0_overhead_line`](../reference/formulas.md#groundfault.formulas.r0_overhead_line)),
depends neither on the geometry nor on ρ_E. The soil resistivity has no default: give the value of the site. In the
resistive approach use the resistances at the dominant harmonic frequency:

```python
from groundfault import formulas as fml

for f in (50.0, 250.0):                                      # overhead line without earth wire
    z0 = fml.z0_overhead_line(f, R_L_km=0.27, r_L_m=0.0068, d_m=1.1, rho_E=250.0)   # invented line and soil data
    print("%5.0f Hz: δ_E = %4.0f m, R0' = %.3f Ω/km, Z0' = %.3f %+.3fj Ω/km"
          % (f, fml.earth_return_depth(f, 250.0), fml.r0_overhead_line(f, 0.27), z0.real, z0.imag))
```

```text
   50 Hz: δ_E = 1472 m, R0' = 0.418 Ω/km, Z0' = 0.418 +1.692j Ω/km
  250 Hz: δ_E =  658 m, R0' = 1.010 Ω/km, Z0' = 1.010 +7.703j Ω/km
```

## References

* **VDE Impuls** – VDE ETG: *VDE Impuls „Erdschluss-Reststrom in Mittelspannungsnetzen: Eine (überschätzte) Gefahr?“*
  VDE Verband der Elektrotechnik Elektronik Informationstechnik e. V., Energietechnische Gesellschaft (ETG), Frankfurt
  am Main, October 2021. [PDF](https://www.vde.com/resource/blob/2091758/8372514d5f581c4f86fd14aaffe4cfa2/vde-impuls-erdschlussreststrom-in-mittelspannungsnetzen-eine-ueberschaetzte-gefahr--data.pdf). Source of the resistive approach – the limiting resistance R_Grenz, the
  criterion R_1 + R_2 + R_0 ≥ R_Grenz and the limit I_RES,max ≤ 2·U_Tp/R_E,max –, which groundfault generalises as
  described above.
* **EN 50522:2022** – Earthing of power installations exceeding 1 kV a.c., Table 1 (relevant currents for the design of
  earthing systems): the residual current of a resonant-earthed network may be assumed as 10 % of the capacitive
  earth-fault current if the exact value is not available – not for a network that is not well compensated.
