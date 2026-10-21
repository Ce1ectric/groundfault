# Without an earth fault (V0 to V3)

Before the first staged fault test – or where none is possible – the harmonic fault current of a busbar comes from
network data and, with a recorder at the transformer, from undisturbed recordings of the transformer node. Four
methods, from the coarsest to the most detailed:

| Method | Fault loop | Data | Result | Functions |
|---|---|---|---|---|
| **V0** classical estimate | zero sequence only, Z_1 = Z_2 = 0 | U_m, I_C, coil current I_L | an upper estimate above about the resonance of the busbar – none below it | [`classical_bound`][groundfault.forecast.bounds.classical_bound] |
| **V1** resonance bound | Z_1 = Z_2 = 1/G_max | as V0, an upper limit G_max of the damping | the order of magnitude at the resonance | [`resonance_bound`][groundfault.forecast.bounds.resonance_bound] |
| **V2** network data | full loop, the MV network from an assumed damping G and C_1 | as V0, damping d of the coil controller, rating plate, S″_k, C_1, G | an estimate with G; the envelope over a range of G | [`network_data_estimate`][groundfault.forecast.bounds.network_data_estimate], [`network_data_envelope`][groundfault.forecast.bounds.network_data_envelope] |
| **V3** transformer node | full loop, the MV network measured | as V2, undisturbed recordings of HV voltages, MV voltages and transformer currents in one device | an estimate with the damping measured | [`mv_network_series`][groundfault.transformer.mv_network_series], [`network_estimate`][groundfault.forecast.bounds.network_estimate] |

[`estimates_without_fault`][groundfault.forecast.bounds.estimates_without_fault] puts them side by side, and the
notebook `forecast_without_fault.ipynb` (German `Prognose_ohne_Erdschluss.ipynb`) runs the whole sequence
([below](#the-notebook)). None of them knows the source that arises in the fault: at the orders of the zero sequence
(3, 9, 15 …) there is no forecast without an earth fault.

## The fault loop from network data

All four use the [fault loop](model.md#fault-loop-per-order) at the busbar with the magnitude of the harmonic voltage
U_m of the busbar before the fault as the source,

\[
I_{\text{F},m} = \frac{3\,U_m}{\lvert \underline{Z}_{0,m} + \underline{Z}_{1,m} + \underline{Z}_{2,m} + 3 Z_\text{F}\rvert},
\qquad
\underline{Z}_{0,m} = \frac{1}{j\,(m/X_{C0} - 1/(m\,X_{L0}))} + d\,X_{C0},
\qquad
\underline{Z}_{1,m} = \underline{Z}_{2,m} = \Bigl(\frac{1}{\underline{Z}_{\text{up},m}} + \frac{1}{\underline{Z}_{\text{MV},m}}\Bigr)^{-1}
\]

with X_C0 = 3·U_LE/I_C and X_L0 = 3·U_LE/I_L from the coil controller, its damping d = I_w/I_C as a series resistance
of the zero sequence, the upstream impedance Z_up of transformer and HV network and the MV network Z_MV seen from the
busbar. They differ in how much of Z_1 and Z_2 they know.

**Upstream impedance.** From the rating plate and the short-circuit power of the HV network
([`network_data`][groundfault.forecast.network_data]):

\[
X_\text{T} = u_\text{k}\,\frac{U_\text{n}^2}{S_\text{rT}},\qquad X_\text{Q} = c\,\frac{U_\text{n}^2}{S''_\text{k}},\qquad
\underline{Z}_{\text{up},m} = m\,(X_\text{T} + X_\text{Q})\,(R/X + j)
\]

with c = 1.1 and an R/X ratio at the harmonic orders that you choose (the transformer has a small one, the HV network a
larger one). The upstream impedance can also be measured: from an earth fault recorded with the transformer currents
([transformer node](../methods/transformer-node.md#upstream-impedance-from-the-fault-related-change)).

**Resonance of the busbar.** The upstream impedance resonates with the operating capacitance C_1 of the MV network at

\[
m_\text{r} = \sqrt{\frac{X_{C1}}{X_\text{up}}},\qquad X_{C1} = \frac{1}{\omega_1 C_1},
\]

([`resonance_order`][groundfault.forecast.network_data.resonance_order]). C_1 comes from the cable lengths, or as
C_1 ≈ q·C_E from the earth capacitance C_E = I_C/(3·ω₁·U_LE) – q ≈ 1 for cable networks, somewhat more for mixed
networks. Above about m_r the positive and negative sequence are capacitive in the loop; below m_r they are inductive
and partly cancel the capacitive zero sequence – a series resonance of the fault loop, for a cable network with
m_r ≈ 5 near m ≈ 3. Where an order lies relative to m_r decides which estimate holds.

## V0 – classical estimate

Without positive and negative sequence (Z_1 = Z_2 = 0): I_F,m = 3·U_m/|Z_0,m + 3·Z_F| ≈ (m − 1/m)·I_C·U_m/U_LE for a
tuned network. Above about the resonance m_r it lies above the current – the more, the closer the order is to m_r,
where the damping of the MV network limits the current. Below m_r it is **no upper bound**: the inductive Z_1 + Z_2
partly cancel Z_0 and the current can exceed the estimate severalfold. Whether and by which factor you raise V0 below
the resonance is your rule (in the notebook `V0_RATIO`); check it with a staged test where it matters.

## V1 – resonance bound

At the resonance Z_1 = Z_2 ≈ 1/G with the conductance G of the MV network at the order (loads, lines): with an upper
limit G_max, I_F,m = 3·U_m/|2/G_max + Z_0,m + 3·Z_F|. It gives the order of magnitude at the resonance; away from it
the loop is not resistive and the estimate says little.

## V2 – network data with a damping range

The full loop with the MV network from data, Z_MV = 1/(G + j·m·ω₁·C_1)
([`mv_network_from_data`][groundfault.forecast.network_data.mv_network_from_data]). The damping G is the least known
quantity, and near the resonance it sets the current. Two results:

* **Estimate** with an assumed G ([`network_data_estimate`][groundfault.forecast.bounds.network_data_estimate]);
* **Envelope** – the largest current over a range [G_min, G_max]
  ([`network_data_envelope`][groundfault.forecast.bounds.network_data_envelope]), with Z_0 without damping. The current
  is not monotonic in G: near the resonance a *larger* damping raises it (Z_1 ≈ 1/G becomes smaller), below the
  resonance the smaller damping gives the maximum. The envelope searches the range instead of assuming an end.

The envelope would be a bound if G lay in the range and C_1, Z_up and Z_0 were right – without a measurement that is
not certain. The effective earth capacitance at the harmonic orders can differ from that at 50 Hz where feeders with
overhead lines or long cables add their own series resonances.

## V3 – the MV network measured in undisturbed operation

V3 measures what V2 has to assume: the MV network Z_MV per order, with its damping, in undisturbed operation. A
recorder at the transformer records the HV voltages, the MV busbar voltages and the transformer currents in **one
device**; every 200-ms window gives the phasors per order.

### The instrument

In undisturbed operation the harmonic sources of the HV and of the MV network vary all the time. A variation driven
from the HV side changes busbar voltage and transformer current by ΔU = Z_MV·ΔI (current from the HV into the MV
network), one driven from the MV side by ΔU = −Z_up·ΔI. The ratio of the deviations, ΣΔU·ΔI*/Σ|ΔI|², mixes both and
lies between Z_MV and −Z_up. A quantity that varies with the HV sources but not with the MV sources separates them – an
**instrumental variable** (a term from statistics: an auxiliary quantity that varies with the cause one wants to
measure but not with the disturbance). The HV voltage nearly is one; corrected by the voltage drop that the transformer
current itself causes over the HV network, E = U_HV + Z_HV·I_T, it is the voltage of the HV source, which the MV
sources do not change. With the deviations of the windows from their mean

\[
\underline{Z}_\text{MV} = \frac{\sum \Delta\underline{U}\,\Delta\underline{E}^{*}}{\sum \Delta\underline{I}\,\Delta\underline{E}^{*}}
\]

per order and sequence ([`mv_network_impedance`][groundfault.transformer.mv_network_impedance] with `Z_hv`). Evaluate
the **natural sequence** of an order (negative sequence at 250 Hz, positive at 350 Hz): the other sequence varies
little. The MV network is symmetrical, so its value holds for both sequences.

### Angle error of the current transformers

Near the resonance Z_MV is capacitive with a damping that is small against its susceptance; a few degrees of angle
error of the transformer current change the real part of Y_MV = 1/Z_MV and with it the forecast by about 1–2.5 % per
degree. Measure the angle error once: a reference clamp with a small known angle error, for a few minutes parallel to a
transformer current in the same recorder, gives per order

\[
\varphi_m = \arg \sum \underline{I}_{\text{CT},m}\,\underline{I}_{\text{ref},m}^{*}
\]

([`ct_angle_from_reference`][groundfault.transformer.ct_angle_from_reference]); `ct_angle_deg` rotates the current
phasors back before the estimate.

### Who drives the variation – the share of the HV side

The estimate holds only where the HV network drives a fair share of the variation. Where the sources in the MV network
drive most of it, the MV variations that still reach the instrument through an inexact Z_HV gain weight, the instrument
becomes weak, and the estimate drifts towards −Z_up. The correlation between current and instrument and the angle of
the result do not show this until the MV side drives nearly everything. The recording itself shows it:
ΔU + Z_up·ΔI is the variation of the HV source referred to the MV side, and the part Z_MV/(Z_up + Z_MV) of it reaches
the busbar, so

\[
s_\text{HV} = \Bigl\lvert\frac{\underline{Z}_\text{MV}}{\underline{Z}_\text{up} + \underline{Z}_\text{MV}}\Bigr\rvert^2
\frac{\sum\lvert\Delta\underline{U} + \underline{Z}_\text{up}\,\Delta\underline{I}\rvert^2}{\sum\lvert\Delta\underline{U}\rvert^2}
\]

is the share of the HV-driven variation in the variance of the busbar voltage – column `hv_share` with `Z_up`, assessed
with `min_hv_share`. Two further ways give the same share: the square of the correlation between busbar voltage and
instrument (`corr_U_hv`², without Z_up), and the position of the plain ratio ΣΔU·ΔI*/Σ|ΔI|² on the line from Z_MV to
−Z_up – the complex power of the variation, ΣΔU·ΔI*, compared with what it would be if only the HV side drove it. In
synthetic test series of a few hundred networks the three agreed closely with the true share (correlation about 0.97),
and the forecast with the measured Z_MV stayed within about ±10 % where the HV network drove at least a third of the
variation; below a fifth it degraded quickly. Choose `min_hv_share` from such tests or from a comparison with staged tests in your
own networks; the package contains no value. The share holds only with the corrected instrument (`Z_hv`): with the HV
voltage itself as instrument the estimate drifts where the MV side dominates, and the share is overestimated with it –
`min_hv_share` therefore needs `Z_hv` and `Z_up`.

**The power flow does not show it.** The harmonic power flowing through the transformer tells who supplies the
*level*, not who drives the *variation*: in the synthetic series the mean 250-Hz power flowed from the HV into the MV
network in the same share of the networks at every share of the HV-driven variation, and it changes with the phase
between the sources. The active power of the variation itself flows into the MV network as long as the MV network
carries most of the damping (its resistance was some 30 times that of the upstream impedance at 250 Hz); it changed
its sign only where the HV side drove hardly 5 % of the variation. In the demo of the example below:

| Recording | `hv_share` (250 Hz) | mean 250-Hz power, HV → MV | active power of the variation |
|---|---|---|---|
| 02 h | 0.82 | 197 W | 14.2 W |
| 06 h | 0.64 | 170 W | 9.9 W |
| 10 h | 0.18 | 170 W | 2.3 W |
| 12 h | 0.04 | 175 W | 0.4 W |
| 16 h | 0.28 | 169 W | 3.5 W |
| 22 h | 0.69 | 178 W | 10.7 W |

Only the complete complex power of the variation, set against Z_MV and −Z_up, carries the share – the third way above.

### A measuring day

Who drives the variation changes over the day – inverters, loads and the HV background change –, so one recording
says little about the network. Record at several times, e.g. ten minutes every hour for a day including the night;
[`mv_network_series`][groundfault.transformer.mv_network_series] evaluates each recording on its own, takes the
polarity of the currents once from all of them, and pools the reliable recordings of each order (the sums of all their
windows, like one long recording) – the estimate for the forecast. Two minutes per recording give a usable estimate,
ten minutes halve its spread; longer recordings help little, because the spread of the network state over the day
remains. If hardly any recording passes, the MV side drives the variation at this busbar most of the time: a staged
fault test (V4) is the way to the forecast.

What the share does not check: an angle error of the current transformers (measure it with the reference clamp), and
the parts of the loop that still come from network data – Z_0 from the coil controller and Z_up. A staged test per
network shows how far they carry.

### Limits

* **One device.** HV voltages, MV voltages and transformer currents need a common sampling; two devices need a common
  time base better than about 10 µs (1° at 250 Hz).
* **HV voltages.** The instrument needs them; inductive HV voltage transformers are usable at the orders 5 and 7 – check
  their frequency response for higher orders.
* **Polarity.** Taken from the passivity of the result (Z_MV has a positive real part); with recordings driven mostly
  from the MV side it is better given (`sign`, e.g. from an earth fault of the same recorder).
* **Parallel transformers.** The estimate is the MV network seen through the measured transformer; with a parallel
  transformer on the busbar its share of the current enters.

## The notebook

`forecast_without_fault.ipynb` (German `Prognose_ohne_Erdschluss.ipynb`) is written with the forecast notebook
(`tools/make_notebooks.py --forecast`) into the folder `notebooks/<language>/forecast/` (German `Prognose/`), with a
reference copy in `templates/`. With `DEMO = True` it creates a measuring day of the demo – six one-minute recordings
of the undisturbed transformer node, one with a reference clamp – and runs without measurement data.

| Section | What you do |
|---|---|
| 1 · Configuration | network data (coil controller, rating plate, S″_k, C_1), harmonic voltages, assumptions for V1 and V2, the recordings of the transformer node and the reference clamp, your limits |
| 2 · Network data and resonance | X_T, X_Q, X_up, C_E, C_1, m_r and m/m_r per order |
| 3 · V3 | the angle error from the reference clamp; per recording Z_MV and its checks (`corr_I_hv`, `hv_share`, `reliable`), the pooled estimate |
| 4 · V0 to V3 side by side | per order and fault impedance, I_H, I_RES with the fundamental residual current |
| 5 · Export | the tables in the forecast folder of the work folder, prefix `<network>_without_fault_`; nothing is written while section 1 has no data |

| Name | Meaning |
|---|---|
| `U_N`, `U_LE`, `I_C`, `I_L`, `D` | nominal voltage, line-to-earth voltage, capacitive earth-fault current, coil current, damping I_w/I_C |
| `U_K`, `S_RT`, `S_K` | rating plate of the transformer, short-circuit power of the HV network |
| `C_1`, `Q_C` | operating capacitance per phase; or C_1 = Q_C·C_E |
| `R_X_UP`, `R_X_HV` | R/X of the upstream impedance and of the HV network at the orders – your assumptions |
| `ORDERS`, `VOLTAGES`, `Z_F` | orders, harmonic voltages (e.g. 95 % quantiles), fault impedances |
| `PQ_FILES`, `PQ_TIMEZONE`, `PQ_QUANTILE`, `PQ_FACTORS`, `PQ_SAFETY_FACTOR` | export(s) of a power-quality measurement of the busbar instead of `VOLTAGES`: the quantile per order (line-to-earth, largest phase per 10-min interval) × your factor; a measurement shorter than every duration of `PQ_FACTORS` (gapless values) is not valid and gives no voltages ([Power-quality measurements](../user-guide/pq.md)) |
| `G_MAX`, `G`, `G_RANGE` | damping for V1, V2 and the envelope – your assumptions |
| `RECORDINGS`, `SIGN`, `CT_ANGLE`, `REFERENCE` | the undisturbed recordings (pattern or list), polarity, angle error or reference clamp |
| `MIN_HV_SHARE`, `V0_RATIO`, `FUNDAMENTAL_A`, `LIMITS` | your limits: share of the HV side, rule for V0 below the resonance, fundamental residual current, limits of I_RES – not set, the notebook lists the values without assessing them |

## Example

A measuring day of the demo: six one-minute recordings of an undisturbed transformer node, in which the share of the
HV-driven variation falls towards noon; the current transformers have an angle error of 2° at 250 Hz and 2.8° at
350 Hz, the first recording carries a reference clamp. The true MV network of the demo is
8.08 Ω ∠−55.6° (250 Hz) and 5.92 Ω ∠−57.8° (350 Hz).

```python
import datetime
import numpy as np
from groundfault import demo, transformer
from groundfault import forecast as fc

z_mv = {m: 1 / complex(g, m * 2 * np.pi * 50.0 * 65e-6) for m, g in ((5, 0.07), (7, 0.09))}   # the truth
files = []
for k, (hour, hv, mv) in enumerate(((2, 0.10, 0.05), (6, 0.08, 0.07), (10, 0.04, 0.10), (12, 0.02, 0.13),
                                    (16, 0.05, 0.09), (22, 0.09, 0.06))):
    path = "TRU_%02dh_10_000kHz.cfg" % hour
    demo.make_undisturbed_transformer_recording(path, duration=60.0, Z_mv=z_mv, hv_fluctuation=hv, mv_fluctuation=mv,
                                                ct_angle_deg={5: 2.0, 7: 2.8}, reference_clamp=(k == 0), seed=30 + k,
                                                start=datetime.datetime(2026, 3, 10, hour, 0))
    files.append(path)

X_T = fc.transformer_reactance(0.18, 40e6, 20e3)          # rating plate: 1.8 Ω
X_Q = fc.hv_network_reactance(3.67e9, 20e3)               # S″_k: 0.12 Ω
Z_up = {m: fc.at_order(X_T + X_Q, m, 0.03) for m in (5, 7)}
Z_hv = {m: fc.at_order(X_Q, m, 0.1) for m in (5, 7)}
m_r = fc.resonance_order(X_T + X_Q, 65e-6)               # 5.05

ct = transformer.ct_angle_from_reference("TRU_02h_10_000kHz.cfg", "I1", "IRef", orders=(5, 7))
print(ct[["order", "angle_deg", "angle_low_deg", "angle_high_deg", "ratio"]].round(2).to_string(index=False))
```

```text
 order  angle_deg  angle_low_deg  angle_high_deg  ratio
     5        2.0           1.99            2.01    1.0
     7        2.8           2.79            2.82    1.0
```

```python
table, pooled = transformer.mv_network_series(files, (5, 7), Z_hv=Z_hv, Z_up=Z_up, ct_angle_deg=ct,
                                              min_hv_share=0.25)                    # 0.25: your limit
print(table[["recording", "order", "Z_Ohm", "Z_angle_deg", "corr_I_hv", "hv_share", "reliable"]]
      .round(2).to_string(index=False))
print(pooled[["order", "recordings", "Z_Ohm", "Z_angle_deg", "G_S", "B_S"]].round(3).to_string(index=False))
```

```text
        recording  order  Z_Ohm  Z_angle_deg  corr_I_hv  hv_share  reliable
TRU_02h_10_000kHz      5   8.28       -54.78       0.93      0.82      True
TRU_02h_10_000kHz      7   6.00       -59.98       0.95      0.63      True
TRU_06h_10_000kHz      5   8.44       -57.39       0.84      0.64      True
TRU_06h_10_000kHz      7   6.03       -60.46       0.86      0.36      True
TRU_10h_10_000kHz      5   8.28       -59.08       0.48      0.18     False
TRU_10h_10_000kHz      7   6.74       -71.54       0.56      0.10     False
TRU_12h_10_000kHz      5   8.33       -63.57       0.24      0.04     False
TRU_12h_10_000kHz      7  10.07       -48.66       0.22      0.03     False
TRU_16h_10_000kHz      5   8.59       -55.20       0.57      0.28      True
TRU_16h_10_000kHz      7   5.35       -59.26       0.60      0.08     False
TRU_22h_10_000kHz      5   7.97       -53.33       0.87      0.69      True
TRU_22h_10_000kHz      7   5.64       -59.15       0.90      0.43      True
 order  recordings  Z_Ohm  Z_angle_deg   G_S   B_S
     5           4  8.263      -55.039 0.069 0.099
     7           3  5.893      -59.838 0.085 0.147
```

At 10 and 12 h the MV side drives most of the variation: the correlation still passes at 10 h, the share does not.
The pooled estimate of the remaining recordings lies within 2.3 % and 2° of the truth. Side by side with the
estimates from network data (U_5 = 250 V, U_7 = 130 V, I_C = 700 A, I_L = 735 A, d = 0.03, C_1 = 65 µF, G = 0.06 S
for V2 and 0.02–0.15 S for the envelope, G_max = 0.15 S for V1):

```python
Z_mv = {int(r.order): complex(r.R_Ohm, r.X_Ohm) for r in pooled.itertuples()}
t = fc.estimates_without_fault({5: 250.0, 7: 130.0}, I_C=700.0, U_LE=20e3 / 3 ** 0.5, Z_up=Z_up, Z_F=(0.0, 5.0),
                               I_L=735.0, d=0.03, C_1=65e-6, m_r=m_r, G_max=0.15, G=0.06, G_range=(0.02, 0.15),
                               Z_mv=Z_mv)
print(t.drop(columns=["f_Hz", "G_envelope_S"]).round(2).to_string(index=False))
```

```text
order  m_over_mr  Z_F_Ohm   U_V  V0_A  V1_A  V2_A  V2_envelope_A  V3_A
    5       0.99      0.0 250.0 72.59 44.46 21.78          45.32 24.86
    7       1.39      0.0 130.0 53.98 25.72 13.83          23.88 16.38
  I_H        NaN      0.0   NaN 90.47 51.37 25.81          51.23 29.77
    5       0.99      5.0 250.0 41.18 24.87 15.29          25.13 16.75
    7       1.39      5.0 130.0 23.42 13.34 10.07          13.62 11.06
  I_H        NaN      5.0   NaN 47.37 28.22 18.31          28.59 20.07
```

With the true Z_MV the loop gives 24.69 A and 16.65 A without fault impedance – V3 lies within 2 %. V2 with an assumed
G of 0.06 S instead of the true 0.07 S lies 12 % lower at 250 Hz, the envelope 1.8 times higher: near the resonance
(m/m_r = 0.99) the damping decides, and V0 lies almost three times above the current.
