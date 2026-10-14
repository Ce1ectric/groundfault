# Signal processing

Every quantity of an evaluation – RMS values, harmonics, angles, sequence components – comes from the same window
analysis: the analysis intervals are cut into windows, and for every window and every channel the true RMS value and
the RMS phasors of the harmonic orders are computed. This page describes that analysis and the steps around it. The
functions are in [`groundfault.dsp`](../reference/dsp.md), [`groundfault.symmetrical`](../reference/symmetrical.md),
[`groundfault.rms`](../reference/rms.md) and [`groundfault.evaluate`](../reference/evaluation.md).

## Intervals and windows

The evaluation works on three **analysis intervals** chosen by hand from the RMS trend
([Choosing the analysis intervals](../user-guide/evaluation.md#choosing-the-analysis-intervals)): the steady-state
fault, and the operation without fault before and after it. Each interval is read for all channels at once and
divided into windows of

\[
N_\text{win} = \operatorname{round}(T_\text{win}\, f_\text{s})
\]

samples, with T_win = 200 ms (`Settings.T_win`) and consecutive windows without overlap (hop `Settings.T_hop`, default
T_win); only complete windows are used. 200 ms are ten cycles at 50 Hz – the window length of IEC 61000-4-7 for
50-Hz networks. Unlike there, the window is **not synchronised** with the network: the frequency is estimated instead
(see below), the DFT is evaluated exactly at the multiples of the estimated frequency, and a Hann window keeps the
leakage of a window that does not contain an integer number of cycles small.

All channels are analysed with the same windows, so magnitudes and phase angles of different channels belong to the
same instant – the precondition for the angle method, for U/I quotients and for every comparison between channels.

The sampling rate must be at least 20 times the rated frequency – an RMS export of a recorder (10 Hz) is refused
with a hint to [`rms`](#rms-recordings). Orders whose frequency comes close to the Nyquist frequency (above
f_s/2.2) are dropped with a hint.

## DC removal

Before any further step the DC component is removed per window:

\[
x_0[n] = x[n] - \operatorname{median}_n x[n]
\]

Current clamps often have a DC offset, and integrating sensors drift; a DC component would otherwise enter the true
RMS value. The **median** (`Settings.dc = "median"`, default) is robust against spikes and short transients in the
window; `"mean"` and `"none"` are available. For waveforms with even harmonics the median differs slightly from the
mean, so the true RMS value comes out a little too high – about 1 % with a 2nd harmonic of 10 % of the fundamental,
about 4 % with 20 % – which errs on the safe side. The phasors of the orders m ≥ 1 are not affected.

A constant offset is all the median removes. A **decaying DC component** – the transient of the coil current after
fault inception, with a time constant of up to several seconds – or a drift remains in the window and increases the
true RMS value without belonging to the steady-state residual current. The plausibility check *Low-frequency
component of I_RES (< f1/2)* therefore smooths the fault current of the max window with a moving average over one
cycle, which keeps only the components below about f1/2, and computes their RMS value I_lf. If

\[
1 - \frac{\sqrt{I_\text{RES}^2 - I_\text{lf}^2}}{I_\text{RES}} \ge 1\,\%
\]

the check warns and gives I_RES without this component; start the steady-state interval later.

## Phasors at the harmonic frequencies

Per window and frequency f, the complex RMS phasor is a single-bin DFT of the windowed signal:

\[
\underline{X}(f) = \frac{\sqrt{2}}{N\,g}\sum_{n=0}^{N-1} x_0[n]\,w[n]\,e^{-j2\pi f n/f_\text{s}},
\qquad
w[n] = \tfrac{1}{2}\left(1 - \cos\frac{2\pi n}{N-1}\right),
\qquad
g = \frac{1}{N}\sum_{n} w[n] \approx 0.5
\]

with the symmetric Hann window w and its coherent gain g ([`dsp.dft_phasors`](../reference/dsp.md)). The phase
refers to the first sample of the window. The frequencies are f = m·f1 with the estimated network frequency f1 –
not a fixed FFT grid – so every harmonic is hit exactly even if f1 differs from 50 Hz. The evaluation computes the
orders 1 to 40 (`Settings.thd_max_order`) plus the orders of `harmonics`, `export_orders` (1…25, stored in the result
file) and `voltage_harmonics`.

The **Goertzel recursion** s[n] = x[n] + 2 cos ω·s[n−1] − s[n−2] (ω = 2πf/f_s) is an independent second way to the
same phasor ([`dsp.goertzel_phasor`](../reference/dsp.md); its phase refers to the end of the window and is converted
to the first sample). Both agree to rounding errors – the test suite checks it, see [Validation](validation.md).

```python
import numpy as np
from groundfault import dsp

fs, f1 = 10_000.0, 50.03                                   # sampling rate, network frequency (off the 5-Hz grid)
t = np.arange(int(2.0 * fs)) / fs
x = (2.0 + np.sqrt(2) * 10.0 * np.cos(2 * np.pi * f1 * t + 0.3)          # DC 2, 10 A at 0.3 rad
     + np.sqrt(2) * 1.5 * np.cos(2 * np.pi * 5 * f1 * t - 1.0))           # 1.5 A of the 5th harmonic

est = dsp.estimate_f1(x, fs)                               # phase method, spectral method as cross-check
print("f1 = %.4f Hz (%s), comparison %.4f Hz (%s), plausible: %s"
      % (est["f1"], est["method"], est["f1_comparison"], est["method_comparison"], est["plausible"]))

window = x[:2000]                                          # one 200-ms window
X, rms = dsp.window_phasors(window, fs, [est["f1"], 5 * est["f1"]])
print("DFT:      |X| =", np.round(np.abs(X), 4), " angle =", np.round(np.angle(X), 4), " RMS = %.4f" % rms)
G = [dsp.goertzel_phasor(window, f, fs) for f in (est["f1"], 5 * est["f1"])]
print("Goertzel: |X| =", np.round(np.abs(G), 4), " angle =", np.round(np.angle(G), 4))
print("sqrt(10² + 1.5²) = %.4f" % np.hypot(10.0, 1.5))
```

```text
f1 = 50.0300 Hz (phase), comparison 50.0300 Hz (spectral), plausible: True
DFT:      |X| = [10.   1.5]  angle = [ 0.3 -1. ]  RMS = 10.1152
Goertzel: |X| = [10.   1.5]  angle = [ 0.3 -1. ]
sqrt(10² + 1.5²) = 10.1119
```

Both ways return the magnitudes and angles of the test signal, despite the DC offset and a window of 10.006 cycles.
The true RMS value of this window, 10.115, differs from √(10² + 1.5²) by 0.03 % – the window does not cover an
integer number of cycles; over long windows the difference vanishes.

## Network frequency

f1 is estimated separately for every analysis interval from a reference signal: U_L1-L2 computed from the
line-to-earth voltages, otherwise a measured line-to-line voltage, U_L1-L2 of the HV side, the neutral displacement
voltage, another voltage, an earth potential rise, the fault current – the first one available.
[`dsp.estimate_f1`](../reference/dsp.md) evaluates two methods and uses one of them as a cross-check of the other:

* **Phase method** (default, `Settings.f1_method = "phase"`): the phasor at the rated frequency f_n is computed in
  consecutive 200-ms windows; between two windows ΔT apart its phase advances by 2π·f1·ΔT, hence
  \( f_1 = f_n + \operatorname{wrap}(\Delta\varphi - 2\pi f_n \Delta T)/(2\pi \Delta T) \), unambiguous for
  |f1 − f_n| < 1/(2ΔT) = 2.5 Hz. The result is the median over all window pairs; their standard deviation is the
  *spread*.
* **Spectral method**: the spectrum of a 2-s section (linear trend removed, Hann window, zero-padding by 4) is searched
  for the largest peak within f_n ± 3 Hz; a parabola through the logarithmic magnitudes of the peak and its
  neighbours refines it. The prominence (peak divided by the median magnitude in the band) shows whether there is a
  clear peak at all.

The estimate is **plausible** if it lies within 0.5 Hz of the rated frequency, both methods agree within 0.05 Hz and
the prominence is at least 4. Otherwise the plausibility row *Network frequency f1* warns, and if the estimate is more
than 0.5 Hz off, the rated frequency is used. `Settings.estimate_frequency = False` uses the rated frequency
throughout.

One f1 applies to the whole interval. If the network frequency changes within the interval, the grid m·f1 misses the
actual frequency of the high orders: with a deviation Δf the offset is x = m·Δf·T_win DFT bins, the Hann window
responds with sinc(x)/(1 − x²), and the magnitude of order m comes out too small by about (π²/6 − 1)·x² ≈ 0.645·x² –
0.0065 % for m·Δf = 0.05 Hz, 0.65 % for m·Δf = 0.5 Hz with 200-ms windows. The plausibility row *Network frequency
constant in the interval* gives a note if the spread of the phase method exceeds 0.02 Hz; choose a narrower interval
then.

Two further estimators serve special purposes: [`f1_zero_crossing`](../reference/dsp.md) (interpolated zero crossings
after a band-pass filter, a regression line through the crossing times) and
[`f1_regression`](../reference/dsp.md), the mean frequency of a section from the phase trend of one or more harmonics
over 100-ms windows (linear regression, with a standard error from the residuals). At the same signal-to-noise ratio
the m-th harmonic measures f1 m times more accurately – the [station evaluation](superposition.md#network-frequency-on-both-sides)
uses this to estimate the frequency from the 150-Hz background at a probe when the 50-Hz component is weak:

```python
import numpy as np
from groundfault import dsp

fs, f1 = 10_000.0, 49.98
rng = np.random.default_rng(1)
t = np.arange(int(1.2 * fs)) / fs                                          # 1.2 s of background at a probe
x = (np.sqrt(2) * 0.3 * np.cos(2 * np.pi * f1 * t)                         # weak 50-Hz component
     + np.sqrt(2) * 5.0 * np.cos(2 * np.pi * 3 * f1 * t + 1.0)             # strong 150-Hz component
     + 0.5 * rng.standard_normal(t.size))                                  # noise
f, sigma = dsp.f1_regression(x, fs, orders=(1, 3))                          # phase trend over 100-ms windows
for m, fm, s in zip((1, 3), f, sigma):
    print("order %d: f1 = %.4f Hz ± %.4f Hz" % (m, fm, s))
```

```text
order 1: f1 = 49.9797 Hz ± 0.0084 Hz
order 3: f1 = 49.9800 Hz ± 0.0001 Hz
```

## True RMS value and max window

The true RMS value of a window is computed from the samples after the DC removal,

\[
X_\text{RMS} = \sqrt{\frac{1}{N}\sum_{n=0}^{N-1} x_0[n]^2}
\]

so it contains all frequencies – fundamental, harmonics, interharmonics, noise, transients – except the DC component.
For a signal that consists of harmonics only it equals \(\sqrt{\sum_m \lvert\underline{X}_m\rvert^2}\); the
plausibility rows *RMS ↔ √ΣX²* compare both, over the assessed orders and over the orders 1…40, and point to
interharmonics, noise or transients in the window if they differ.

The **max window** is the window of the undisturbed part of the steady-state interval (see the next section) with the
largest true RMS value of the main fault-current channel. All assessment quantities come from this one window – the
residual current, its harmonics, the angle method, the station quantities – so that they describe the same instant,
and taking the largest window is conservative. `Settings.max_search_hop` searches the maximum on a finer grid of window positions; the window found
there replaces the max window of the standard grid. Windows that contain gaps (NaN, e.g. after an alignment of
subsystems) are ignored, with a hint.

## Disturbed states

The assessment refers to the normal state of the network during the earth fault. Two events change that state while
the fault persists, and the windows they affect are left out of the reference
([`groundfault.disturbances`](../reference/disturbances.md)):

* an **active residual current increase** (a resistor at the auxiliary winding of a coil, for a few seconds, to locate
  the faulted feeder) – the active component Iw rises abruptly and falls back;
* a **network change** (a network section trips or is switched) – the capacitive earth-fault current I_C and with it
  the detuning Iv = ΣI_coil − I_C change abruptly and persist.

Windows **without fault current** are no state of the fault at all: if the steady-state interval reaches beyond the
clearance (or begins before the inception), the windows whose RMS value of the fault current is below 10 % of its
largest value in the interval (median of three consecutive windows, so that a single outlier does not count) get the
state *no fault current*. They are never part of the reference and take no part in the detection – otherwise the drop
of Iw at the clearance would look like the end of an active residual current increase that lasted the whole fault.

Per window k the fundamental phasor of the fault current gives Iw_k and Iv_k by the angle method (relative to U0,
oriented so that the median of Iw is positive). A **step** at window k is a difference of the medians of the m = 3
windows after and before it (window k itself, which may straddle the step, is left out)

\[
\Delta x_k = \operatorname{median}(x_{k+1} \ldots x_{k+m}) - \operatorname{median}(x_{k-m} \ldots x_{k-1})
\]

that is at least the threshold \(\theta\) and at least three times the spread (maximum − minimum) of either side,
\(\lvert\Delta x_k\rvert \geq \max(\theta,\, 3\,s_k)\). A uniform ramp gives \(\lvert\Delta x\rvert = 2\,s\) and is
therefore no step – a motor-driven coil adjustment changes Iv gradually and stays part of the reference (the
stationarity check reports it). The threshold is \(\theta = \max(0.05\,\lvert I_{H1}\rvert,\ 0.5\ \text{A})\)
with |I_H1| of the undisturbed state (`Settings.disturbance_threshold`; first from all windows, then repeated with the
undisturbed ones).

The steps are classified:

| Step | Classification |
|---|---|
| ΔIw ≥ θ (abrupt) | start of an active residual current increase (ΔIw ≤ −θ: its end); a simultaneous step of Iv smaller than half of ΔIw belongs to it (the resistor shifts the reactive component a little) |
| ΔIv ≥ θ (abrupt), coil currents measured and changing by at least 25 % of ΔIv | coil change – reported, **no** disturbance (25 % also covers a coil channel that captures only one of several conductors) |
| ΔIv ≥ θ (abrupt), coil currents unchanged | network change |
| ΔIv ≥ θ (abrupt), no coil currents | step of the reactive component, cause open – treated as a network change |
| Δ\|I_H1\| ≥ θ without U0 | step of the fundamental component, cause open (station without voltage measurement) |

The steps of Iw are added up per window; a window lies in an active residual current increase if its level is at
least θ above the lowest level (the increase only ever adds active current, so an interval may also start during one).
The network steps of Iv (of |I_H1| without U0) are added up as well; a window whose level differs from that of the
first window by at least θ is in a changed state – **the start of the steady-state interval is the reference**. A
window that straddles a step – judged from the stepping quantity and from the RMS value, because the Hann window hardly
sees a step near the edge of a window – belongs to the disturbed state.

Left out are the max window, the statistics, the stationarity check, the coil-current balance and the least-squares
superposition of a station (method `voltage`). The superposition at fault inception and clearance uses its own
windows next to those instants; a disturbed state there does not bias it, because the ratio ΔU/I_F of a linear earthing
system does not depend on the size of the fault current.

## Statistics over the steady state

Besides the max window, the table `statistics` describes the undisturbed windows of the steady-state interval: for every channel
the RMS value, and for fault, coil, shield and PEN currents and the probes also the magnitudes of the assessed orders –
number of windows, mean, standard deviation, minimum, maximum and 95 % quantile next to the value in the max window. A
large spread shows that the interval is not steady. Two plausibility rows look at the interval as well: *Stationarity
of I_H1 in the interval* evaluates the angle method in every undisturbed window and separates a change of the active
component from a change of the reactive component (typically a coil adjustment); the
*coil current balance* compares the change of Iv with the change of the measured coil currents (slope 1 expected) and
reveals a coil channel with a wrong ratio. See [Plausibility checks](../user-guide/evaluation.md#plausibility-checks).

## Symmetrical components and line-to-line quantities

With the three line-to-earth voltages, every window gives per order the line-to-line voltages
U_L1-L2 = U_L1E − U_L2E (and cyclically) and the zero-, positive- and negative-sequence components
([`symmetrical.fortescue`](../reference/symmetrical.md), conventions in [Methods](index.md#symmetrical-components)).
The voltage analysis of the pre-fault and post-fault intervals and of the max window gives:

* per order the **median magnitudes** over the windows of all nine quantities (tables `voltage_pre_fault`,
  `voltage_fault`, `voltage_post_fault`);
* the **THD** of each line-to-line loop over the orders 2 to 40, \( \mathrm{THD} = \sqrt{\sum_{m\ge2} U_m^2}/U_1 \),
  and the corresponding harmonic voltage \( U_\text{H} = \sqrt{\sum_{m\ge2} U_m^2} \) (columns `UTHD12_pct`, `UH12_V`
  …), the 5th harmonic in the negative sequence `UH5g_V`, the 7th harmonic in the positive sequence `UH7m_V`, and the
  zero-sequence fundamental `Uzero_H1_V` (table `voltage_metrics`);
* **complex sequence phasors referred to U_L1-L2**: every window is rotated with \(e^{-jm\varphi_\text{LL1}}\) of its
  own fundamental of U_L1-L2, then the windows are averaged as phasors. These levels before and after the fault are
  stored in the result file; the [equivalent-source method](equivalent-source.md#normalisation-of-the-source-fluctuation)
  normalises the harmonic currents with them.

The neutral displacement voltage U0 of the angle method is the zero-sequence fundamental of the max window.

## Alignment of recorder subsystems

Some recorders export voltage and current channels of different subsystems with a time offset. The
[raw-data diagnostics](../user-guide/evaluation.md#raw-data-diagnostics) determine for every channel the instant of
the largest step of its RMS value; if the median instants of the voltages and of the fault and coil currents differ by
more than 0.2 s, they suggest an alignment `dict(roles=[…], dt_s=…)` with dt_s = t_voltages − t_currents. Given to
`evaluate(…, alignment=…)`, the listed channels are read dt_s later (samples outside the file become NaN) for all
intervals, so all windows contain simultaneous samples again. The station evaluation and the signal explorer apply the
same offset.

## RMS recordings

Recorders often also export RMS values (e.g. 10 values per second). They are not evaluated like instantaneous values
but serve as checks ([`groundfault.rms`](../reference/rms.md)):

* `evaluate_rms_recording` – per channel and interval the number of values, mean, minimum, maximum, 95 % quantile and
  the instant of the maximum.
* `compare_with_instantaneous` – the own true RMS value, computed from the instantaneous values over the window that
  ends at each RMS sample, against the recorder's values. A median deviation of 2 % or more is explained where
  possible: the recorder includes the DC component (the own RMS value *with* DC agrees within 2 %), the RMS file is
  scaled by a power of ten, or the deviation is unexplained (channel assignment, ratio, time grid).
* `v_curve` – the resonance curve while the coil is tuned during the fault: the smallest measured value and the
  vertex of a parabola I² = a·x² + b·x + c fitted to the smallest half of the points, with x the coil current or the
  time; `fundamental_trend` gives |I_H1|, Iw and Iv over time from the instantaneous values. The fundamental
  component at the operating point follows as √(I_min² + Iv²) (see [Assessment quantities](assessment.md)).

For the HTML file of the signal explorer, instantaneous values are reduced to at most 10 kHz with
[`dsp.decimate`](../reference/dsp.md), a polyphase FIR low-pass filter (Kaiser window, pass-band ripple below 10⁻⁴);
the spectra and characteristic values in that file are still computed from the original samples.
