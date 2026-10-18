# Forecast (optional)

groundfault evaluates single recordings and campaigns of staged earth-fault tests – the **direct evaluation** of the
[user guide](../user-guide/index.md). The forecast goes one step further: it predicts the **harmonic residual current**
I_H and the residual current I_RES of a future earth fault from the harmonic voltages of normal operation – the 95 %
quantiles of a power-quality measurement, a time series or the voltages of a planned network state –, at the busbar
or at a fault location behind a line.

The forecast is an **optional part** of the package. `import groundfault` does not load it, the measurement and
campaign notebooks do not use it, and an evaluation needs nothing of it. Its functions are in `groundfault.forecast`:

```python
from groundfault import forecast as fc
```

## In brief

Per harmonic order m the fault current of a single-line-to-earth fault is that of a Thevenin equivalent at the fault
location:

\[
\lvert\underline{I}_{\text{F},m}\rvert =
  \frac{\lvert\underline{U}_{q,m} + \underline{U}_{s,m}\rvert}{\lvert\underline{Z}_{q,m} + \underline{Z}_{qL,m} + Z_\text{F}\rvert},
\qquad
\underline{Z}_{q,m} = \tfrac{1}{3}\left(\underline{Z}_{0,m} + \underline{Z}_{1,m} + \underline{Z}_{2,m}\right)
\]

with the pre-fault voltage U_q of the faulted phase, a source U_s that arises with the fault (saturating coils and
transformers, zero-sequence orders), the sequence impedances Z_k of the network at the busbar, the line to the fault
location Z_qL and the fault impedance Z_F. The methods differ in where they take Z_q – and U_s – from: from network data,
from undisturbed recordings at the transformer, from staged fault tests or from the earth faults of operation.

## The methods

| | Method | Earth fault | Z_q from | Result | Package / notebook |
|---|---|---|---|---|---|
| **V0** | classical estimate | none | zero sequence from I_C, Z_1 = Z_2 = 0 | upper estimate above about the resonance of the busbar | [`classical_bound`][groundfault.forecast.bounds.classical_bound]; [without an earth fault](without-fault.md) |
| **V1** | resonance bound | none | as V0, Z_1 = Z_2 = 1/G_max | order of magnitude at the resonance | [`resonance_bound`][groundfault.forecast.bounds.resonance_bound] |
| **V2** | network data with a damping range | none | rating plate, S″_k, C_1, assumed damping G | estimate; envelope over a range of G | [`network_data_estimate`][groundfault.forecast.bounds.network_data_estimate], [`network_data_envelope`][groundfault.forecast.bounds.network_data_envelope] |
| **V3** | transformer node, undisturbed | none | as V2, the MV network measured with the HV voltage as instrument | estimate | [`mv_network_series`][groundfault.transformer.mv_network_series], [`network_estimate`][groundfault.forecast.bounds.network_estimate]; notebook `forecast_without_fault` |
| **V4** | one staged test, measured source | staged | the test: Z_q = U_q/I_F | estimate for the state of the test | [campaign evaluation](../user-guide/campaign.md) (`SOURCE = "measured"`), [`measured_source`][groundfault.equivalent_source.measured_source] |
| **V5** | several staged tests | staged | median of the tests, each checked with the others; equivalent source for the orders with a source in the fault | estimate with a check | [campaign evaluation](../user-guide/campaign.md) (`SOURCE_IMPEDANCE = "median"`, leave-one-out), [`SourceSeries.loo_table`][groundfault.equivalent_source.SourceSeries.loo_table], [equivalent-source method](../methods/equivalent-source.md) |
| **V6** | network model with sequence impedances | staged | Z_0, Z_1, Z_2 per order from the tests, lines to fault locations | estimate at the busbar and behind a line | [`build_model`][groundfault.forecast.campaigns.build_model], [`NetworkModel`][groundfault.forecast.model.NetworkModel], [`Line`][groundfault.forecast.line.Line]; notebook `network_model_forecast` |
| **V7** | learning network model | staged and recorded | every recorded earth fault updates Z_1, Z_2, Z_q; its fault current from the coil currents | estimate, checked at every earth fault | [`add_entries`][groundfault.forecast.campaigns.add_entries], [`fault_check`][groundfault.forecast.model.NetworkModel.fault_check]; notebook `network_model_forecast` |
| **V8** | data-driven model | many | learned from examples | – | not part of the package (see below) |

V0 to V3 need no earth fault: [Without an earth fault](without-fault.md). V4 and V5 are the campaign evaluation of
the staged tests ([equivalent-source method](../methods/equivalent-source.md)); V6 and V7 the network model:
[Model and equations](model.md), [Measurements for the model](recording.md), [Working with the network
model](guide.md).

**V8 – data-driven models.** A regression model (decision tree, random forest, gradient boosting, neural network)
could learn the fault current from inputs such as U_m, I_C, the rating plate and the damping. A handful of networks
with a few staged tests can neither train nor check such a model. In synthetic tests with a thousand networks it was
about as good as the network-data model inside its training range and clearly worse outside it – another voltage
level, larger networks, other orders – and it knows none of the physical limits (Z_F → ∞, the Thevenin equivalent,
the resonance). The package therefore contains no data-driven forecast; learning has its place in V7, where every
recorded earth fault checks and updates a physical model.

## Choosing a method

Four questions decide:

1. **Which order?** The orders of the zero sequence (3, 9, 15 …) have a source that arises only in the fault – without
   an earth fault (V0 to V3) there is no forecast for them; with staged tests V5 (equivalent source) or V6.
2. **Is an earth fault possible?** A staged test with the fault current measured gives the loop directly (V4 to V6);
   earth faults of operation recorded with the coil currents update it (V7).
3. **Which measurements are available?** A power-quality measurement or a recorder in fixed intervals (the source);
   HV voltages, MV voltages and transformer currents in one device (the damping, V3); the coil currents (the fault
   current of every earth fault, V7).
4. **Which network data?** The coil controller (I_C, detuning, damping), the rating plate of the transformer, S″_k of
   the HV network, the operating capacitance or the cable lengths, line data for faults in the network.

| You have | and | then |
|---|---|---|
| coil controller, rating plate, S″_k, PQ measurement | no recorder, no test | position of the order to the resonance m_r; V0 above it, V2 with a damping range; below the resonance V0 is no bound – a test or V3 pays most there |
| as above | recorder with HV voltages, MV voltages and transformer currents | V3 from recordings over a day; only the recordings in which the HV network drives enough of the variation count (`hv_share`); if hardly any does, a staged test |
| staged tests at the busbar | – | V4 (one test), V5 (several: median, each checked with the others), V6 for faults behind a line |
| a permanent recorder with coil currents | earth faults in operation | V7: every earth fault updates and checks the model; before the first one V3 |

All methods take the source from the harmonic voltage of the busbar before the fault; for a forecast on the safe side
use the 95 % quantile of the largest phase. The package contains no margins, limits or network data – you define them.

## Pages

| Page | Content |
|---|---|
| [Without an earth fault](without-fault.md) | V0 to V3: the fault loop from network data, resonance of the busbar, the damping range, the MV network from undisturbed recordings of the transformer node (instrument, angle error of the current transformers, share of the HV-driven variation, a measuring day), the notebook `forecast_without_fault`, an example |
| [Model and equations](model.md) | V6, V7: the fault loop and its equivalent circuits, what the impedances contain (resonances of the MV and the HV network), calibration, update, node rule with the coil currents, source that arises with the fault, fault behind a line, forecast, checks, assumptions |
| [Measurements for the model](recording.md) | what a disturbance recorder in the substation has to record and why (must, should, may), recorder settings, undisturbed recordings for V3, staged tests at the busbar and in the network, earth faults recorded in operation |
| [Working with the network model](guide.md) | the notebook `network_model_forecast`, the functions step by step, the model file and the tables |
| [API reference](../reference/forecast.md) | `groundfault.forecast` and its modules |
