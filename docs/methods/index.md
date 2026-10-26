# Methods

These pages describe what groundfault computes and why: the signal processing, the formulas as they are
implemented, the assumptions behind them and the checks that accompany every result. How to run the evaluations and
how to read their tables is described in the [user guide](../user-guide/index.md); every function is documented in
the [API reference](../reference/index.md).

| Page | Content | Main functions |
|---|---|---|
| [Evaluation chain](evaluation-chain.md) | block diagrams of the steps: a recording, the DC removal and window analysis, the analysis intervals (settling, disturbed states, suggestion), the max window and the assessment quantities, the campaign | [`evaluate`](../reference/evaluation.md), [`disturbances.scan`](../reference/disturbances.md) |
| [Signal processing](signal-processing.md) | windows, DC removal, DFT at the harmonic frequencies, network frequency, true RMS value, max window, disturbed states (active residual current increase, network change), statistics, symmetrical components, alignment of recorder subsystems, RMS recordings | [`dsp`](../reference/dsp.md), [`evaluate`](../reference/evaluation.md), [`disturbances`](../reference/disturbances.md), [`symmetrical`](../reference/symmetrical.md), [`rms`](../reference/rms.md) |
| [Assessment quantities](assessment.md) | residual current, fundamental component, active and detuning current (angle method, √2 method), harmonic content, measurement uncertainty, scaling to a power-quality measurement, limit from the permissible touch voltage, resistive approach, line parameters | [`formulas`](../reference/formulas.md), [`campaign`](../reference/campaign.md) |
| [Superposition at the station](superposition.md) | background and fault-related component, the three superposition methods, network frequency on both sides, uncertainty (null test, frequency reference), extrapolation, PEN currents, current into the LV network, probe maximum, parallel checks | [`station`](../reference/station.md) |
| [Reduction factor and LV network](reduction-factor.md) | comparison with the earthing measurement per frequency, reduction factor per order and as RMS value, comparison methods, classification, trend, relevance for the assessment, physical interpretation | [`earthing`](../reference/earthing.md) |
| [Equivalent-source method](equivalent-source.md) | active two-terminal equivalent per harmonic order from a series of tests, normalisation of the source fluctuation, estimators, checks, residual current at the earthing impedance | [`equivalent_source`](../reference/equivalent_source.md) |
| [Transformer node](transformer-node.md) | power, apparent impedance and upstream impedance (transformer + HV network) per order and sequence before, during and after the fault, polarity of the current transformers, fault current estimated from the transformer currents; interpretation: sources of an order, resonance of the MV network, link to the harmonic residual current | [`transformer`](../reference/transformer.md) |
| [Validation](validation.md) | synthetic recordings with known solution, second methods, test suite, limitations | [`demo`](../reference/demo.md) |

The model behind the optional forecast of the harmonic residual current – the fault loop per order, calibrated with
the staged tests and updated with recorded earth faults – is described in its own section,
[Forecast → Model and equations](../forecast/model.md).

## Processing chain

In short – the block diagrams of every step are on the page [Evaluation chain](evaluation-chain.md):

```text
COMTRADE recording (.cfg/.dat)
  │  corrections of the measuring chain, channel roles, analysis intervals (read off by hand, with a proposal)
  ▼
high-pass per interval ── 200-ms windows of all channels ── mean removed ── Hann window ── DFT at m·f1 (f1 per interval)
  │  per window and channel: true RMS value and RMS phasors of the orders 1 … 40
  ├─► disturbed states (steps of Iw, Iv) left out
  ├─► max window (largest residual current) ──► assessment quantities: I_RES, I_G, Iw, Iv, I_H, uncertainty,
  │                                              scaling to the 95 % quantile of a power-quality measurement
  ├─► voltages before, during and after the fault: sequence components per order, THD
  ├─► station: superposition per order ──► ΔU/I_F per probe, ΔI_PEN/I_F ──► LV network, parallel checks
  │                                    └─► with groundmeas: reduction factor, LV network vs earthing measurement
  ├─► transformer node: P, Q, U/I per order and sequence ──► upstream impedance Z_up = −ΔU/ΔI (transformer, HV)
  ▼
result file (JSON) ──► campaign: consistency, equivalent sources per order ──► I_RES(Z_E), resistive approach
                   └─► forecast (optional): network model of the busbar ──► I_H, I_RES from harmonic voltages
```

## Conventions

### Phasors

All phasors are complex **RMS phasors** in the cosine convention:

\[
x(t) = \sqrt{2}\,\lvert\underline{X}\rvert\cos(2\pi f t + \varphi)
\quad\Leftrightarrow\quad
\underline{X} = \lvert\underline{X}\rvert\,e^{j\varphi}
\]

\(\underline{X}_m\) is the phasor of the harmonic order m at the frequency m·f1, with the network frequency f1
estimated from the recording. As computed per window, its phase refers to the first sample of the window.

### Angle reference

Every recording has its own time origin, and every window starts at a different instant. Phasors of different windows
or recordings are therefore compared only after referring them to the fundamental of the line-to-line voltage
U_L1-L2 in the same window:

\[
\hat{\underline{X}}_m = \underline{X}_m\,e^{-j m \varphi_\text{LL1}},
\qquad \varphi_\text{LL1} = \arg \underline{U}_\text{L1-L2,1}
\]

A time shift τ rotates \(\underline{X}_m\) by m·ω1·τ and \(\varphi_\text{LL1}\) by ω1·τ, so \(\hat{\underline{X}}_m\)
does not depend on the time origin. The line-to-line voltage is the natural reference: it is not affected by the
neutral displacement of the earth fault, and it is available whenever the line-to-earth voltages are recorded
(U_L1-L2 = U_L1E − U_L2E). Angles in the columns `angle_ref_ULL_deg` and `angle_deg` of the assessment quantities and
all phasors of the equivalent-source method use this reference. In the station tables, angles of U/I_F are referred to
the fault current (I_F at 0°).

### Orientation of the fault current and sign of the detuning

The angle method splits the fundamental component of the fault current into the components in phase and in
quadrature with the zero-sequence voltage \(\underline{U}_0 = (\underline{U}_\text{L1E} + \underline{U}_\text{L2E} +
\underline{U}_\text{L3E})/3\) (or the measured neutral displacement voltage):

\[
I_\text{w} = \lvert\underline{I}_1\rvert\cos(\varphi_{U0} - \varphi_{I1}),
\qquad
I_\text{v} = \lvert\underline{I}_1\rvert\sin(\varphi_{U0} - \varphi_{I1})
\]

The active component of a passive network has a definite sign, while the orientation of a clamp is arbitrary. The
current is therefore oriented so that **Iw > 0**; a negative Iw means a reversed clamp, and the fault-current phasors
are rotated by 180° (hint and plausibility row). With this orientation **Iv > 0 means over-compensation** (the
inductive coil current exceeds the capacitive current, the residual current lags U0) and Iv < 0 under-compensation:
Iv = ΣI_coil − I_C. This is the one sign convention of groundfault – the detuning from a resonance curve,
Iv = I_operating − I_res ([Assessment quantities](assessment.md#detuning-and-the-2-method)), the column `Iv_A` of
`rms.fundamental_trend` and the groundmeas export use it as well.

### Symmetrical components

Fortescue transformation with \(a = e^{j120^\circ}\) and the phase sequence L1-L2-L3:

\[
\underline{U}_0 = \tfrac{1}{3}(\underline{U}_a + \underline{U}_b + \underline{U}_c),\quad
\underline{U}_1 = \tfrac{1}{3}(\underline{U}_a + a\underline{U}_b + a^2\underline{U}_c),\quad
\underline{U}_2 = \tfrac{1}{3}(\underline{U}_a + a^2\underline{U}_b + a\underline{U}_c)
\]

A symmetrical harmonic of order m belongs to its **natural sequence**: positive for m mod 3 = 1 (1, 7, 13 …),
negative for m mod 3 = 2 (5, 11 …), zero for m mod 3 = 0 (3, 9 …).

### Units

SI units throughout: A, V, Ω, Hz and s; probe distances in m, line lengths in km, per-unit-length impedances in Ω/km,
soil resistivity in Ωm. A voltage per ampere of fault current is given in V/A (= Ω) – for a remote probe it is the
transfer impedance r·Z_E –; the tables of the result keep it in V per 100 A as well (`V_per_100A_…`), the report and
its figures show V/A, or V/kA for small values. Column names carry their unit (`_A`, `_V`, `_Ohm`, `_Hz`, `_pct`,
`_deg`, `_m`, `_s`); angles are in degrees, ratios such as r, `share_…` and `F_…` are pure numbers. Values from
groundmeas are converted to the base units when they are read. The output language changes only the display (decimal
comma in German), never the values.

### Limits, factors and margins

groundfault contains the methods, no limits or safety factors: the limits of the residual current, the permissible
touch voltage U_Tp, the factor F, the reference current of the reduction factor, the measurement-uncertainty margins,
the factor on the 95 % quantile of a power-quality measurement and the range of the reduction factor you expect are
parameters that you define – e.g. from the operator's specification, the applicable standard or the accuracy of your
measuring chain. Without them a function skips the part that needs them (`NaN` or “–” and a hint that names the
missing parameter) or, where the value is the point of the call, raises a `ValueError`.

### Measurement uncertainty

Assessment values can include a relative measurement-uncertainty margin so that the assessment stays on the safe
side: currents are **increased** (I·(1 + m_I)), voltages are **decreased** (U·(1 − m_U)). The margins are defined by
the user (`Settings.uncertainty_I`, `Settings.uncertainty_U`); by default they are 0 – no margin. Why voltages are
decreased is explained in [Assessment quantities](assessment.md#measurement-uncertainty).

### Symbols

| Symbol | Meaning | Where |
|---|---|---|
| m, f1 | harmonic order, network frequency | columns `order`, `f1_Hz` |
| I_F | fault current (substation: residual earth-fault current; station: current at the faulted station) | role `i_res`, `I_F_A` |
| I_RES | residual earth-fault current: true RMS value of I_F in the max window | `IRES` |
| I_G | fundamental component of the residual current | `IG`, `IH1` |
| Iw, Iv | active component and detuning (reactive component) of I_G | `Iw`, `Iv` |
| I_H | harmonic content of the residual current | `IH_total`, `IH_sum` |
| U0 | zero-sequence voltage (neutral displacement voltage) | `UH1n` |
| Z_F | additional impedance (fault resistance) in the fault branch of a substation test | `z_fault_ohm`, `Z` |
| U_E, U_T | earth potential rise (probe against the station earth), touch voltage (probe at 1 m) | roles `u_e`, `u_t` |
| Z_E | earthing impedance; Z_E,LV earthing impedance of the LV network | `Z_E_LV_Ohm` |
| r | reduction factor | `r`, `r_eff` |
| I_S, I_E | shield current; earth current I_E = I_F − I_S | role `i_shield` |
| I_LV | fault-related current into the LV network (from the PEN currents) | `I_LV_A` |
| U_q, Z_q | source voltage and source impedance of the two-terminal equivalent of one order | `Uq_V`, `Rq_Ohm`, `Xq_Ohm` |
| U_Tp, F | permissible touch voltage; ratio of the permissible earth potential rise to U_Tp (both defined by the user) | `Settings.u_tp`, `Settings.f_factor`; arguments `U_Tp`, `F` |
| m_I, m_U | relative measurement-uncertainty margins of currents and voltages (defined by the user) | `Settings.uncertainty_I`, `uncertainty_U` |
