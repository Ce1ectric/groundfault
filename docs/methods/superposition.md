# Superposition at the station

At a secondary substation (MV/LV station) the earthing system usually carries a voltage **before** the earth fault –
the **background**, caused by currents of the LV network through PEN conductors and earth electrodes, mainly at 50 and
150 Hz. During the fault, the component caused by the fault current adds to it as a phasor, per harmonic order m:

\[
\underline{U}_{\text{fault},m} = \underline{U}_{\text{background},m} + \underline{Z}_m\,\underline{I}_{\text{F},m}
\]

An earthing measurement with current injection measures only Z. The quantity that can be compared with it – and that
scales with the fault current – is therefore the **fault-related component**
\( \Delta\underline{U}_m = \underline{U}_{\text{fault},m} - \underline{U}_{\text{background},m} \), or per ampere
\( \underline{Z}_m = \Delta\underline{U}_m/\underline{I}_{\text{F},m} \) (V/A). For an earth-potential probe in remote
earth Z_m is the transfer impedance r·Z_E of the station. The quotient U/I_F as measured in the max window (`direct`)
contains the background and can be far off, larger or smaller depending on its phase.

The difficulty: background and fault can only be measured in different windows, seconds apart, and phasors of
different windows have different time origins. Subtracting them needs a phase reference that holds across the
switching instant. groundfault obtains it in up to three independent ways, combines them and estimates how reliable
the result is. The same superposition gives the fault-related PEN and shield currents, and from them the current into
the LV network. Everything on this page is done by [`station.frequency_selective`](../reference/station.md), which
[`evaluate`](../reference/evaluation.md) calls for every station recording; how to read the tables is described in
[Stations and the LV network](../user-guide/station.md).

**Orders evaluated:** the orders up to 25 whose fault current in the max window is at least max(0.1 A, 1 % of the
fundamental component), and always the fundamental.

## Fault inception and clearance

The instants of fault inception and clearance come from the RMS trend of the fault current
([`station.fault_times`](../reference/station.md#groundfault.station.fault_times)): 20-ms windows, a section counts as
active where the moving median exceeds 10 % of the maximum, and the active section containing the middle of the
steady-state interval is used (gaps shorter than 1 s bridged) – a short transient elsewhere in the recording does not
shift the instants. If the fault current is active from the start of the file, there is no inception; if it lasts to
the end, no clearance.

After the inception the fault current needs time to settle (decaying DC component, CT saturation).
[`station.settled_from`](../reference/station.md#groundfault.station.settled_from) looks for the instant from which its
RMS value (100-ms windows) stays within 3 % for 0.5 s, starting the search 0.2 s after the inception; the result is at
least 0.5 s after the inception, and the fault windows start at the latest 1.5 s after it, which keeps the time span
of the phase reference short.

## The three superposition methods

| Method (code) | Background windows | Fault windows | Phase reference |
|---|---|---|---|
| fault inception (`inception`) | 1.2 s ending 0.06 s before the inception | 1.2 s from the settling instant, ending at least 0.12 s before the clearance | network phase at the inception |
| fault clearance (`clearance`) | 1.2 s starting 0.5 s after the clearance (the neutral displacement voltage has decayed) | 1.2 s ending 0.12 s before the clearance, not earlier than 0.5 s after the inception | network phase at the clearance |
| voltage reference (`voltage`) | all windows of the pre-fault and post-fault intervals | all windows of the steady-state interval | fundamental of U_L1-L2 of every window |

The windows are 200-ms windows as in the [signal processing](signal-processing.md); every side needs at least two of
them (0.4 s).

**Time reference.** The two time-reference methods need no voltage measurement. Every window is evaluated at the
network frequency of its centre (see below), and its phasors – whose phase refers to the first sample t_0 of the
window – are rotated back to the switching instant t_ref:

\[
\underline{X}_m^{(t_\text{ref})} = \underline{X}_m\,e^{-jm\,\Delta\theta},
\qquad
\Delta\theta = 2\pi\int_{t_\text{ref}}^{t_0} f(t)\,\mathrm{d}t
\]

All windows of one side are then averaged as phasors, which gives \( \underline{U}_\text{background} \),
\( \underline{U}_\text{fault} \) and \( \underline{I}_\text{F} \) of that side, and
\( \underline{Z}_m = (\underline{U}_{\text{fault},m} - \underline{U}_{\text{background},m})/\underline{I}_{\text{F},m} \).

**Voltage reference.** With the three line-to-earth voltages every window carries its own phase reference: its
phasors are referred to the fundamental of U_L1-L2 of the same window, \( \hat{\underline{X}}_{m,w} =
\underline{X}_{m,w}\,e^{-jm\varphi_{\text{LL1},w}} \). The background is the mean of the referred phasors of the
pre-fault interval, of the post-fault interval or of both; the fault component is fitted by least squares over all
windows w of the steady-state interval:

\[
\underline{Z}_m = \frac{\sum_w \big(\hat{\underline{U}}_{m,w} - \hat{\underline{U}}_{\text{background},m}\big)\,
\hat{\underline{I}}^{\,*}_{\text{F},m,w}}{\sum_w \lvert\hat{\underline{I}}_{\text{F},m,w}\rvert^2}
\]

**Combination.** The fault-related component (`fault`, column `Z_fault_Ohm` with its angle referred to I_F) is the
complex mean of the available methods. Their **spread** – the largest difference between two methods as phasors,
\( \max_{a,b}\lvert\underline{Z}_a - \underline{Z}_b\rvert/\lvert\underline{Z}_\text{fault}\rvert \) in % (column
`method_spread_pct`) – is the first check: the methods use different windows and references, so a large spread means
that the background changed during the fault or that a phase reference failed. With only one method there is no
mutual check (hint “only one superposition method available”); with none, only the direct values remain.

## Network frequency on both sides

Background and fault windows lie up to 2.7 s from the switching instant. A frequency error δf over a time Δt
turns the order m by 2π·m·δf·Δt – with 1 mHz over 2 s, 0.7° at 50 Hz and 2.2° at 150 Hz – and a phase error ε of the
background changes the fault-related component by \( 2\sin(\varepsilon/2)\,\lvert U_\text{background}\rvert/\lvert\Delta
U\rvert \): 11 % at 150 Hz if the background is three times the fault-related component. The network frequency also
drifts by some mHz per second. Therefore it is **estimated separately on both sides** of the switching instant and
assumed to change **linearly** in between (between the centres of the two window sequences – a quadratic phase,
integrated exactly by the trapezoidal rule); every window is evaluated at the frequency of its centre.

The frequency of a side is the mean frequency of its window sequence from the phase trend over 100-ms windows
(regression, [`dsp.f1_regression`](signal-processing.md#network-frequency)), from the first available source:

1. a **line-to-line voltage** (measured, or the difference of two line-to-earth voltages) – it is neither affected by
   the earth fault nor by the background, and it is used on both sides;
2. otherwise during the fault the **fault current** at 50 Hz, and before or after the fault the most distinct
   **network-synchronous background**: all channels at the orders 1 to 7, per order the channel with the smallest
   standard error, and across the orders the weighted median (weights 1/σ²). At probes the 150-Hz background is often
   the best source. σ only says how smooth a phase trend is, not whether it follows the network – with the weighted
   median a single order with a phase trend of its own (an interharmonic, a fluctuating harmonic) cannot decide the
   result.

An estimate counts if its standard error is at most 2 mHz, it lies within 0.5 Hz of the rated frequency and the
section is at least 0.5 s long. If the background side cannot be estimated – section too short, no distinct
network-synchronous background, or more than 50 mHz from the fault side – the frequency of the fault side is
continued, with the hint “network frequency before the fault not estimable (…) – frequency during the fault assumed;
irrelevant if the background is small” (without a background a phase error does not matter). If the fault side cannot be estimated, the background side is
used, otherwise f1 of the steady-state interval. `res.values["station_frequency"]` records the frequencies and their
sources.

A synthetic station without voltage measurement, with a large background at 50 and 150 Hz and a network frequency
drifting by 10 mHz/s:

```python
import os
import tempfile

import groundfault as gf
from groundfault import demo

cfg = os.path.join(tempfile.mkdtemp(), "Station_C_10_000kHz.cfg")
truth = demo.make_station_recording(
    cfg, duration=12.0, t_on=4.0, t_off=8.0, with_voltages=False,          # no voltage measurement
    background={1: demo.polar(8.0, 60.0), 3: demo.polar(4.0, -30.0)},       # background before/after the fault
    I_harm={3: demo.polar(2.0, 20.0), 5: demo.polar(30.0, 35.0)},
    f1_drift_hz_s=0.01)                                                     # network frequency drifts by 10 mHz/s
b = truth["intervals"]
res = gf.evaluate(gf.open_recording(cfg), gf.Intervals(b["steady_state"], b["pre_fault"], b["post_fault"]))
rows = res.table("station_frequency").query("channel == 'UE_70m'").set_index("order")
rows["true_Ohm"] = [abs(truth["orders"][m]["rZE_probe"]) for m in rows.index]
print(rows[["true_Ohm", "Z_direct_Ohm", "Z_inception_Ohm", "Z_clearance_Ohm", "Z_fault_Ohm",
            "method_spread_pct"]].round(4).to_string())
```

```text
       true_Ohm  Z_direct_Ohm  Z_inception_Ohm  Z_clearance_Ohm  Z_fault_Ohm  method_spread_pct
order
1        0.5131        0.3700           0.5131           0.5132       0.5131             0.0109
3        0.5260        2.1980           0.5261           0.5265       0.5263             0.1531
5        0.5509        0.5509           0.5509           0.5509       0.5509             0.0171
```

The direct quotient is 28 % too small at 50 Hz and four times too large at 150 Hz; both superposition methods hit the
true transfer impedance. The frequencies were estimated from the 150-Hz background of a probe before and after the
fault, and from the fault current during it:

```python
for side in ("inception", "clearance"):
    s = res.values["station_frequency"][side]
    print("%-9s background %.4f Hz from %s | fault %.4f Hz from %s"
          % (side, s["f_background_hz"], s["f_background_source"], s["f_fault_hz"], s["f_fault_source"]))
```

```text
inception background 50.0135 Hz from UE_70m at 150 Hz | fault 50.0311 Hz from IF1
clearance background 50.0709 Hz from UE_5m at 150 Hz | fault 50.0527 Hz from IF1
```

## How reliable is the fault-related component?

Besides the spread of the methods, two contributions are estimated per probe and order; both are multiplied by the
ratio of the background to the fault-related component (`background_to_fault`), because an error of the background
matters only in proportion to it.

**Null test – a fluctuating background.** The superposition assumes that the background during the fault equals the
background before (or after) it. How well that holds is tested where it can be tested: in the fault-free sections of
the recording, up to 20 s before the inception and after the clearance. At positions every 0.4 s (at most 15 per
section) the same calculation is carried out as for the fault – window sequences at the same distances, network
frequency estimated on both sides and linear in between, phasors rotated to the position and averaged – and the
background “predicted” from the first window sequence is compared with the phasors actually measured in the second
one; there is no fault there. The median of the relative prediction errors is `background_forecast_error_pct`; it
contains fluctuations of the background as well as errors of the frequency estimation. It is empty if the fault-free
sections are too short.

**Frequency reference – without a voltage measurement.** Without a line-to-line voltage the network frequency during
the fault follows the fault current. Its frequency can deviate from the network frequency by a few mHz (e.g. while
the fault impedance changes), which the null test cannot see – there is no fault current in the fault-free sections.
groundfault assumes a deviation δf = 3 mHz (`station.DF_FAULT_CURRENT_HZ`) at the centre of the fault windows; with
the linear frequency model the phase error between the two window sequences, Δt apart, is ε_m = π·m·δf·Δt, and the
contribution is

\[
u_\text{frequency} = 2\sin(\varepsilon_m/2)\cdot\frac{\lvert U_\text{background}\rvert}{\lvert\Delta U\rvert}
\]

(`frequency_uncertainty_pct`). With a voltage measurement it is zero. It is deliberately cautious: whether the fault
current follows the network phase cannot be checked without a voltage measurement.

**Estimated uncertainty.** Both contributions are added in quadrature, `uncertainty_pct` = √(u_null² + u_frequency²) –
a typical (median) error, not a bound. If the spread of the methods or the estimated uncertainty exceeds **20 %**, the
row is marked `uncertain` (figures: ⊗), and a hint names the frequencies concerned (at most six, those with the most
fault current), with “mainly frequency reference without voltage measurement” where that contribution dominates. If
neither can be determined, a background larger than the fault-related component marks the row as well. Uncertain
values should not be used for reduction factors or comparisons with earthing measurements; recording the line-to-earth
voltages removes the frequency contribution and adds the third method.

In the example above, the uncertainty at 150 Hz is almost entirely the frequency contribution:

```python
print(rows[["background_to_fault", "background_forecast_error_pct", "frequency_uncertainty_pct",
            "uncertainty_pct", "uncertain"]].round(3).to_string())
```

```text
       background_to_fault  background_forecast_error_pct  frequency_uncertainty_pct  uncertainty_pct  uncertain
order
1                    0.414                          0.026                      0.699            0.699      False
3                    3.528                          0.075                     17.853           17.855      False
5                    0.000                         49.449                      0.000            0.001      False
```

The synthetic background is constant, so the null test predicts it almost perfectly (0.075 % at 150 Hz). The
background at 150 Hz is 3.5 times the fault-related component, and the assumed 3 mHz over the 1.8 s between the window
sequences give 18 % – here more than the actual error (0.06 %), because the synthetic fault current follows the
network phase exactly. At 250 Hz the null test finds a large relative error of a background that is practically zero –
multiplied by the ratio 0, it does not matter.

## Extrapolation to the limits of the residual current

The table `station_extrapolation` scales the voltages of every probe to the limits of the residual current that the
user defines (`Settings.ires_limits`; groundfault contains none – without them the table is empty and a hint names the
setting) with the factor s = I_limit/I_F,RMS (RMS value of the fault current in the max window):

| Column | Formula |
|---|---|
| `U_proportional_V` | \( s\,U_\text{RMS} \) – the measured RMS value scaled, including the background |
| `U_fault_V` | \( \sqrt{\sum_m \lvert s\,\Delta\underline{U}_m\rvert^2} \) – only the fault-related component, over the evaluated orders |
| `U_background_plus_fault_V` | \( \sqrt{\sum_m \lvert \underline{U}_{\text{background},m} + s\,\Delta\underline{U}_m\rvert^2 + U_\text{rest}^2} \) – scaled fault-related component plus the unchanged background, added as phasors per order (both referred to I_F); U_rest² is the mean square of the pre-fault RMS values minus the squared background of the evaluated orders (not negative) |

## PEN currents and the current into the LV network

For PEN and shield currents the same methods give the ratio \( \underline{k}_m = \Delta\underline{I}_m/
\underline{I}_{\text{F},m} \) (complex, I_F at 0°): the load unbalance, present before the fault already, drops out
like the background of a probe (table `station_currents_frequency`).

The PEN current is usually measured at two points with the transformer star point between them: `feeders` (`IPEN_v`,
the PEN conductors of all outgoing LV cables) and `busbar` (`IPEN_n`, the connection to the main earthing busbar). The
current of the star point – the load unbalance – does not change because of the earth fault, so by **Kirchhoff's
current law** the fault-related current into the LV network flows through both measuring points: in the counting
directions of the two clamps ΔI_feeders = ±ΔI_busbar. groundfault aligns the two counting directions (the sign is
decided at the order at which both currents are largest, mostly 50 Hz), compares them as phasors,

\[
\text{deviation} = \frac{\lvert\underline{k}_\text{feeders} - \underline{k}_\text{busbar}\rvert}
{\tfrac{1}{2}\left(\lvert\underline{k}_\text{feeders}\rvert + \lvert\underline{k}_\text{busbar}\rvert\right)}
\]

(`kcl_deviation_pct`), and averages them with weights 1/u², u being the uncertainty of each measuring point – the
larger of its estimated uncertainty and its method spread, at least the measurement uncertainty m_I of the current
channels (`Settings.uncertainty_I`, defined by the user, default 0). A measuring point with a large, fluctuating
load unbalance is less certain, and the result then relies on the other one. The uncertainty of the weighted mean is
\( u = 1/\sqrt{\sum 1/u_i^2} \); if the two points differ by more than \( \sqrt{u_\text{feeders}^2 +
u_\text{busbar}^2} \), half of the excess is added in quadrature. The current into the LV network is
\( \underline{I}_{\text{LV},m} = \underline{k}_{\text{LV},m}\,\underline{I}_{\text{F},m} \), and the **earthing
impedance of the LV network**, per probe and order and as an RMS value over the orders:

\[
\underline{Z}_{\text{E,LV},m} = \frac{\Delta\underline{U}_{\text{E},m}}{\underline{I}_{\text{LV},m}},
\qquad
Z_\text{E,LV,eff} = \frac{\sqrt{\sum_m \lvert\Delta U_{\text{E},m}\rvert^2}}{\sqrt{\sum_m \lvert I_{\text{LV},m}\rvert^2}}
\]

with the uncertainty \( \sqrt{u_\text{probe}^2 + u_\text{LV}^2 + m_U^2 + m_I^2} \) (`Z_E_LV_uncertainty_pct`; m_U and
m_I are the measurement uncertainties of the user, `Settings.uncertainty_U` and `uncertainty_I` – without them only the
uncertainty of the superposition counts). A single PEN channel without a position is used as it is – its fault-related
component is the same at both points.

A synthetic station whose feeders carry a large load unbalance that fluctuates by 8 %, evaluated with a measurement
uncertainty of the channels of 3 % (an illustrative value):

```python
import os
import tempfile

import groundfault as gf
from groundfault import demo

cfg = os.path.join(tempfile.mkdtemp(), "Station_D_10_000kHz.cfg")
truth = demo.make_station_recording(
    cfg, duration=16.0, t_on=6.0, t_off=10.0,
    lv_network=dict(R_LV=4.0, X_LV1=0.4,                                    # LV network parallel to the station earth
                    load_feeders={1: demo.polar(60.0, -30.0), 3: demo.polar(25.0, 40.0)},   # large load unbalance
                    load_busbar={1: demo.polar(1.0, -20.0)}, load_fluctuation=0.08))        # … that fluctuates
b = truth["intervals"]
settings = gf.Settings(uncertainty_I=0.03, uncertainty_U=0.03)               # illustrative values – define your own
res = gf.evaluate(gf.open_recording(cfg), gf.Intervals(b["steady_state"], b["pre_fault"], b["post_fault"]), settings)
lv = res.table("station_lv_network").query("channel == 'UE_70m'").set_index("order")
lv["I_LV_true_A"] = [abs(truth["orders"][m]["I_LV"]) for m in lv.index]
print(lv[["I_LV_feeders_A", "I_LV_busbar_A", "weight_feeders", "weight_busbar", "kcl_deviation_pct", "I_LV_A",
          "I_LV_true_A"]].round(3).to_string())
lv["Z_E_LV_true_Ohm"] = [abs(truth["orders"][m]["Z_LV_probe"]) for m in lv.index]
print(lv[["Z_E_LV_Ohm", "Z_E_LV_true_Ohm", "Z_E_LV_uncertainty_pct", "parallel_check",
          "earth_current_check"]].round(3).to_string())
for h in res.hints:
    print("⚠", h)
```

```text
       I_LV_feeders_A  I_LV_busbar_A  weight_feeders  weight_busbar  kcl_deviation_pct  I_LV_A  I_LV_true_A
order
1               4.221          4.862           0.001          0.999             99.865   4.860        4.804
5               3.974          3.974           0.500          0.500              0.025   3.974        3.974
7               0.774          0.774           0.500          0.500              0.100   0.774        0.775
11              0.492          0.491           0.500          0.500              0.192   0.492        0.493
       Z_E_LV_Ohm  Z_E_LV_true_Ohm  Z_E_LV_uncertainty_pct parallel_check earth_current_check
order
1           3.696            3.739                   5.195      satisfied           satisfied
5           4.159            4.159                   4.743      satisfied           satisfied
7           4.544            4.541                   4.744      satisfied           satisfied
11          5.540            5.530                   4.744      satisfied           satisfied
⚠ LV network: PEN currents before (IPEN_v) and after the transformer star point (IPEN_n) differ by 100 % at 50 Hz – explained by their uncertainties (load unbalance, spread of the methods: 108 % and 3 %); I_LV relies on IPEN_n with a weight of 100 %.
⚠ No extrapolation of the station voltages to limits of the residual current: Settings.ires_limits is empty (the limits are defined by the user).
```

At 50 Hz the fluctuating unbalance makes the feeders point useless (uncertainty 108 %, the phasors differ by 100 %);
the weighting relies on the busbar point, and I_LV and Z_E,LV come out within about 1 % of the truth. At the
harmonics, where the load carries no unbalance, both points agree and count equally. If the deviation at 50 Hz
exceeds 20 % *and* is larger than the uncertainties explain, the hint asks to check the clamps, the ratio and a load
change during the fault instead.

## Probe maximum

A probe measures the voltage between the station earth and its own position, φ_station − φ(x), with
0 ≤ φ(x) ≤ φ_station: at most the full earth potential rise. In a fault test the potentials spread differently than at
a current injection (return currents through cable shields, PEN conductors, neighbouring earth electrodes), so the
remote probe does not always show the highest voltage. The best estimate of the earth potential rise is therefore the
**highest** probe: the rows with `channel` = `max(UE)` take per order the probe – earth potential rise or touch voltage
– with the highest fault-related voltage (column `probe`), and in the RMS tables the probe with the highest RMS value.
The LV-network tables, the comparison with earthing measurements and the reduction factor use these rows first.

## The two parallel checks

The LV network is one branch of the total earthing of the station; the other branches are the station earth
electrode and – for the fault current – the cable shields. For ohmic-inductive branches (angles between 0 and 90°)
the parallel connection is never larger than one of its branches:

\[
\lvert\underline{Z}_1 + \underline{Z}_2\rvert^2 = \lvert\underline{Z}_1\rvert^2 + \lvert\underline{Z}_2\rvert^2
+ 2\lvert\underline{Z}_1\rvert\lvert\underline{Z}_2\rvert\cos\Delta\varphi \ge \lvert\underline{Z}_2\rvert^2
\quad\Rightarrow\quad
\left\lvert\frac{\underline{Z}_1\underline{Z}_2}{\underline{Z}_1 + \underline{Z}_2}\right\rvert \le \lvert\underline{Z}_1\rvert
\]

Two checks follow, per order:

* **Parallel check** (`parallel_check`): \( \lvert\underline{Z}_\text{E,LV}\rvert \ge \lvert\max(\Delta\underline{U}_\text{E})/
  \underline{I}_\text{F}\rvert \), equivalent to \( \lvert\underline{I}_\text{LV}\rvert \le \lvert\underline{I}_\text{F}\rvert \) –
  the current into one branch cannot exceed the fault current. It depends on the currents only, not on the probe.
* **Earth-current check** (`earth_current_check`, with a measured shield current): the stricter condition against the
  earth current \( \underline{I}_\text{E} = \underline{I}_\text{F} - \sum\underline{I}_\text{S} \) (all shield-current
  channels, each turned into the direction of I_F): \( \lvert\underline{I}_\text{LV}\rvert \le \lvert\underline{I}_\text{E}\rvert \).

A condition counts as `violated` only if it is missed by more than its uncertainty – \( \sqrt{u_\text{LV}^2 + 2m_I^2} \)
with the measurement uncertainty m_I of the user,
with the shield current additionally its uncertainty – and as `borderline` within it; in the RMS tables the result is
`satisfied` or `violated (see orders)`. A violation points to a wrongly scaled PEN or shield clamp or a clamp around
more than the PEN conductors (hint “LV network: current into the LV network larger than the earth current …”). The
comparison of Z_E,LV with the earthing impedance of an earthing measurement is a statement about that measurement –
see [Reduction factor and LV network](reduction-factor.md#lv-network-and-earthing-measurement).
