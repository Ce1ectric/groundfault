# Evaluation chain

The block diagrams on this page show the order of the steps – from the COMTRADE file to the result file of a
recording and on to the campaign – and where the settings act. They are a map: the formulas and the reasons behind
every step are on the pages the blocks refer to, mainly [Signal processing](signal-processing.md),
[Assessment quantities](assessment.md) and [Equivalent-source method](equivalent-source.md). Numbers in the blocks are
the defaults; the names in `code` are the settings or functions that change them.

| Diagram | Steps |
|---|---|
| [1 · Recording](#1-recording) | the whole evaluation of one recording ([`evaluate`](../reference/evaluation.md)) |
| [2 · DC removal and window analysis](#2-dc-removal-and-window-analysis) | high-pass, windows, mean, true RMS value, DFT |
| [3 · Analysis intervals](#3-analysis-intervals) | fault inception and clearance, settling, disturbed states, the suggestion of the steady-state interval, pre-fault and post-fault |
| [4 · Max window and assessment quantities](#4-max-window-and-assessment-quantities) | reference windows, max window, angle method, harmonic content, margins, scaling |
| [5 · Campaign](#5-campaign) | equivalent sources, power-quality measurement, residual current at the earthing impedance, network expansion, report |

## 1 · Recording

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 400}}}%%
flowchart TB
    rec["COMTRADE recording<br/>.cfg + .dat, primary values"] --> corr["corrections of the measuring chain<br/>ratio, polarity, roles, main channel<br/>(corrections file of the campaign)"]
    corr --> roles["channel roles<br/>detect_roles → capabilities"]
    roles --> diag["raw-data diagnostics<br/>time base, offsets, saturation,<br/>alignment of subsystems"]
    diag --> iv["analysis intervals (diagram 3)<br/>pre-fault · steady-state fault · post-fault"]
    iv --> win["DC removal and window analysis (diagram 2)<br/>per interval: f1, 200-ms windows,<br/>true RMS value, phasors of the orders 1 … 40"]
    win --> dist["disturbed states in the steady-state interval<br/>active residual current increase,<br/>network change → reference windows"]
    dist --> maxw["max window and assessment quantities<br/>(diagram 4): I_RES, I_G, Iw, Iv, I_H"]
    win --> volt["voltages before, during and after the fault<br/>sequence components per order, THD"]
    maxw --> extra["station · transformer node<br/>(if the channels are recorded)"]
    maxw --> checks["plausibility checks<br/>statistics over the reference windows"]
    volt --> checks
    extra --> checks
    checks --> json["result file (JSON)<br/>→ campaign (diagram 5)"]
```

Corrections, roles and diagnostics are described in [Evaluating a recording](../user-guide/evaluation.md); the
station and the transformer node have pages of their own ([Superposition at the station](superposition.md),
[Transformer node](transformer-node.md)). All quantities of the assessment come from **one** window, the max window,
so that magnitudes and phase angles of all channels belong to the same instant.

## 2 · DC removal and window analysis

Every analysis interval is read for all channels at once and passes the same steps; the high-pass acts on the whole
interval, the rest on each window.

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 400}}}%%
flowchart TB
    x["analysis interval<br/>all channels, primary values"] --> gap["gaps (NaN) bridged linearly<br/>for the filter only"]
    gap --> pad["mirror extension at both ends<br/>3 / f_c = 0.6 s"]
    pad --> hp["Butterworth high-pass, order 4, f_c = 5 Hz<br/>forwards and backwards – no phase shift<br/>Settings.dc_cutoff_hz"]
    hp --> cut["extension removed, gaps restored"]
    cut --> grid["window grid: N = T_win · f_s<br/>T_win = 200 ms, no overlap<br/>Settings.T_win, T_hop"]
    grid --> mean["per window: mean removed<br/>x₀ = x − mean(x)"]
    mean --> rms["true RMS value<br/>√(mean of x₀²)"]
    mean --> hann["Hann window<br/>Settings.window"]
    f1["network frequency f1 per interval<br/>from U_L1-L2, two methods<br/>Settings.f1_method"] --> dft
    hann --> dft["single-bin DFT at f = m · f1<br/>orders 1 … 40 and those of the settings"]
    dft --> ph["RMS phasors X_m<br/>per window and channel<br/>phase at the first sample"]
```

The high-pass removes the DC component of a clamp and a slowly decaying offset – the transient of the coil current
after the fault inception – before the windows are cut. Running forwards and backwards, it shifts no phase, and its
magnitude at 50 Hz differs from 1 by less than 10⁻⁸; the mirror extension avoids a step at the ends of the interval,
and no sample outside the interval (a fault inception just after it) acts on it. Only the first and last 0.2 s of
an interval keep a small error of the RMS value (about 0.1 %); the harmonics are unchanged.

After the high-pass the mean of a window is its remaining DC component. The **mean** is removed rather than the
median: for a waveform with even harmonics – a saturating clamp, the transient after a metallic fault – the median
differs from the mean, and the true RMS value would come out too high. 30 A at 50 Hz with 12 A of the 2nd and 8 A of
the 4th harmonic have a true RMS value of 33.29 A; the median per window gives 34.48 A (+3.6 %), the high-pass with
the mean 33.29 A.

| `Settings.dc` | On the interval | Per window | Use |
|---|---|---|---|
| `"highpass"` (default) | zero-phase high-pass | mean | exact true RMS value, also with even harmonics and a decaying offset |
| `"highpass_median"` | zero-phase high-pass | median | the high-pass of groundfault 3.4 |
| `"median"` | – | median | the default up to groundfault 3.4: robust against single spikes, too high with even harmonics |
| `"mean"` | – | mean | a constant offset only |
| `"none"` | – | – | signals without DC component |

The choice changes neither the window grid nor the phasors of the orders m ≥ 1 – only the DC and the low-frequency
part of a window, and with it the true RMS value. Formulas: [Signal processing](signal-processing.md#dc-removal).

## 3 · Analysis intervals

The three analysis intervals are chosen by the person who knows the test sequence. groundfault proposes the
steady-state interval ([`disturbances.scan`](../reference/disturbances.md)) and, inside the interval that is chosen,
leaves the disturbed windows out again with the same detection.

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 400, "nodeSpacing": 30}}}%%
flowchart TB
    i["main fault-current channel"] --> trend["RMS trend, 20-ms windows"]
    trend --> on["fault inception t_on and clearance t_off<br/>moving median above 10 % of its maximum"]
    on --> rset["RMS value settled: change below 3 %<br/>over 0.5 s, at least 0.5 s after t_on"]
    rset --> range["scan range<br/>settled RMS value + 0.1 s … t_off − 0.1 s"]
    range --> w["high-pass and 200-ms windows (diagram 2)"]
    w --> feat["per window: Iw, Iv (angle method to U0;<br/>|I_H1| without U0) and E² / (2 · I_RES),<br/>the RMS change by the even orders 2 … 10"]
    feat --> settle["settling test: first window from which the<br/>medians of two consecutive blocks of 3 windows<br/>differ by less than 0.5 · θ for every quantity<br/>– at the latest t_on + 4 s"]
    settle --> steps["steps of Iw and Iv:<br/>|Δ median of 3 windows| ≥ max(θ, 3 · spread)<br/>θ = max(5 % of |I_H1|, 0.5 A)"]
    steps --> cls["cause of a step: active increase (Iw),<br/>network change (Iv, coil currents unchanged),<br/>coil change (no disturbance), cause open"]
    cls --> states["state of every window<br/>reference · disturbed · no fault current"]
    states --> sug["suggestion for STEADY_STATE<br/>first undisturbed range of at least 1 s<br/>(else the longest)"]
    sug --> user
    subgraph user ["analysis intervals, chosen by the user"]
        direction LR
        pre["PRE_FAULT<br/>before t_on"] ~~~ ss["STEADY_STATE<br/>checked in the trend"] ~~~ post["POST_FAULT<br/>after t_off, U0 decayed"]
    end
```

* **Fault inception and clearance** come from the RMS trend of the fault current; the RMS value counts as settled once
  it stays within 3 % for 0.5 s ([`station.settled_from`](../reference/station.md)).
* **Settling of the fault state** ([`settled_index`](../reference/disturbances.md)): the RMS value may settle before the
  fault state does. After a metallic fault Iw and Iv can need seconds – a clamp or transformer that saturates and
  recovers, the DC component of the coil current –, and the even harmonics decay with them. The test compares the
  medians of two consecutive blocks of three windows (0.6 s each) and starts the scan at the first window from which
  every quantity drifts by less than half the step threshold; the odd harmonics follow the harmonic voltage of the
  network and take no part. A state that has not settled 4 s after the inception is scanned from the settled RMS value
  on, with a note.
* **Disturbed states** are abrupt steps of Iw (an active residual current increase) or Iv (a network change; with
  measured coil currents that follow the step: a coil change, which is no disturbance). A ramp – a motor-driven coil
  adjustment – is no step. The start of the scanned range is the reference of the network state; that is why the scan
  must not start in the transient. The rules are in [Signal processing](signal-processing.md#disturbed-states).
* **Pre-fault and post-fault** are chosen from the RMS trend in the operation without fault: a few seconds before the
  inception, and after the clearance once the neutral displacement voltage has decayed. They give the voltage levels
  and harmonics without fault, the background at a station and the levels the equivalent-source method normalises
  with.

The scan text names the fault, the scanned range, the threshold, a shifted start with the quantity that settled
last, the disturbed ranges and the suggestion
([Evaluating a recording](../user-guide/evaluation.md#disturbed-states)).

## 4 · Max window and assessment quantities

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 400}}}%%
flowchart TB
    st["windows of STEADY_STATE<br/>diagram 2"] --> det["disturbed states and windows<br/>without fault current left out<br/>Settings.exclude_disturbances"]
    det --> ref["reference windows<br/>undisturbed, without gaps"]
    ref --> maxw["max window: largest true RMS value<br/>of the main fault-current channel<br/>finer grid: Settings.max_search_hop"]
    ref --> stat["statistics, stationarity,<br/>coil-current balance"]
    maxw --> ires["I_RES<br/>true RMS value of the max window"]
    maxw --> am["angle method<br/>I_1 against U0 = (U_L1E + U_L2E + U_L3E) / 3<br/>Iw = |I_1| cos Δφ, Iv = |I_1| sin Δφ"]
    am --> pol{"Iw < 0 ?"}
    pol -- yes --> rot["phasors of the fault current<br/>turned by 180°"]
    rot --> ig
    pol -- no --> ig["I_G = |I_1|<br/>I_H = √(I_RES² − I_G²)"]
    ires --> ig
    ig --> mar["measurement-uncertainty margins<br/>I · (1 + m_I), U · (1 − m_U)"]
    mar --> pq{"PQ quantiles?"}
    pq -- yes --> sc["scaling per order<br/>positive/negative sequence: U95,m / U_m<br/>zero sequence, even orders: as measured"]
    pq -- no --> aq["table assessment_quantities"]
    sc --> aq
```

The max window is the conservative choice: of the reference windows the one with the largest residual current. With
`correct_polarity=False` a negative Iw is only reported. Without the three line-to-earth voltages the measured
neutral displacement voltage serves as U0. The scaling rules – with the THD for an order without its own quantile –
are in [Assessment quantities](assessment.md#scaling-to-the-95-quantile-of-a-power-quality-measurement).

## 5 · Campaign

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 400}}}%%
flowchart TB
    res["result files of the substation tests<br/>additional impedances Z_k"] --> ser["series per order<br/>phasors referred to U_L1-L2"]
    ser --> nrm["normalised to the harmonic level<br/>before and after each test"]
    nrm --> fit["two-terminal equivalent per order<br/>U_q, Z_q – two estimators, checks"]
    pqf["PQ measurement of the busbar<br/>read, e.g. a WinPQ or PQL export"] --> ten["10-min values (RMS)<br/>intervals with an earth fault or dip left out"]
    ten --> q["largest phase or loop per interval<br/>95 % quantile per order and of the THD"]
    q --> fac["factor by the duration of the measurement<br/>longest gapless stretch, rule of the user"]
    fit --> ze["I_RES at the earthing impedance Z_E<br/>scaled per order, margins m_I, m_U"]
    fac --> ze
    ze --> lim["limits of the user<br/>I_RES and F · U_Tp / (r · Z_E)"]
    ze --> exp["network expansion<br/>I_RES at Z_E over I_CE<br/>(more cable, coils retuned)"]
    exp --> lim
    lim --> doc["Word report"]
```

The fundamental component is not part of the model of the equivalent sources; it is taken from the measurements. A
power-quality measurement shorter than every duration of the rule is not valid for the assessment
([Power-quality measurements](../user-guide/pq.md#quantile-and-factor)). The network expansion converts the
equivalent sources of today to a network with more cable
([Equivalent-source method](equivalent-source.md#network-expansion)); the report puts all of it together
([Word report of a campaign](../user-guide/document.md)).
