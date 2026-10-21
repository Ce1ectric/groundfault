# Working with the network model

The network model (V6, V7) builds on the result files of the single evaluation – one per recording, written by the
measurement notebook – and on the register of the work folder. It needs nothing else of the evaluation, and nothing of
it is loaded by `import groundfault`:

```python
from groundfault import forecast as fc
```

The estimates without an earth fault (V0 to V3) have a notebook of their own:
[Without an earth fault](without-fault.md#the-notebook).

```text
  staged fault tests of one or more campaigns (register, result files)  ──► calibration     build_model / add_test
            │                                                                checks          cross_check
  earth faults recorded at the busbar (result files, no fault current)  ──► update          add_entries / add_fault
            │                                                                checks          fault_check
  other measurements, e.g. a staged test in the network                 ──► check           check_data / verify
  harmonic voltages (95 % quantiles, time series), fault location        ──► forecast        forecast → I_H, I_RES
```

A network model belongs to a busbar, not to a campaign: the tests of several campaigns calibrate it, and every
earth fault recorded later at the same busbar updates it. The equations are on [Model and equations](model.md).

## The forecast notebook

`network_model_forecast.ipynb` (German `Netzmodell_Prognose.ipynb`) runs the whole sequence; it is in the folder
`notebooks/en/forecast/` (German `notebooks/de/Prognose/`) with a reference copy in `templates/`. The notebook
generator writes it on request – the measurement and campaign notebooks do not need it:

```text
python tools/make_notebooks.py --out <folder> --forecast         # measurement, campaign and forecast notebook
python tools/make_notebooks.py --out <folder> --forecast-only    # only the forecast notebook, in <folder>/forecast
```

| Section | What you do |
|---|---|
| 1 · Configuration | name the network and the campaigns, list recorded earth faults and further measurements, enter the harmonic voltages and the fault location |
| 2 · Calibration with the staged fault tests | check the impedances per test and order and the model per order |
| 3 · Checks between the tests | read the deviations; the largest underestimate per order is a basis for your margin |
| 4 · Recorded earth faults | Z_q of every recorded earth fault, its estimated fault current and the forecast at each of them |
| 5 · Checks with other measurements | e.g. a staged test in the network |
| 6 · Forecast | I_H and I_RES per order and in total, at the busbar and behind `LINE` |
| 7 · Save the model and export the tables | the model file and the tables in the forecast folder |

With `DEMO = True` the example notebook creates the demo campaign (if missing), a recording of the busbar voltages and
coil currents as a recorded earth fault, and the result files of all of them. The configuration cell:

| Name | Meaning |
|---|---|
| `NETWORK` | name of the model (substation, busbar) – also the sub-folder of the forecast folder |
| `CAMPAIGNS` | campaigns whose staged fault tests calibrate the model, taken from the register |
| `TESTS` | `None` = the tests of `CAMPAIGNS`; or a list of `dict(campaign=…, measurement=…, Z=…)` |
| `FAULTS` | recorded earth faults: `dict(campaign=…, measurement=…)` |
| `CHECKS` | further measurements: `dict(campaign=…, measurement=<busbar recording>, Z=…, current=<recording with the fault current>, line=…)` |
| `ORDERS`, `MIN_CURRENT_A`, `HOW`, `TWO_SOURCE` | orders of the calibration, aggregation of Z_q, orders with a source that arises with the fault |
| `VOLTAGES`, `VOLTAGE_REFERENCE`, `CSV_OPTIONS`, `QUANTILE` | harmonic voltages of the forecast (values per order or a CSV time series), line-to-earth or line-to-line, the quantile |
| `PQ_FILES`, `PQ_TIMEZONE`, `PQ_SERIES`, `PQ_FACTORS`, `PQ_SAFETY_FACTOR` | export(s) of a power-quality measurement of the busbar instead of `VOLTAGES`: the quantile `QUANTILE` per order (line-to-earth, largest phase) × your factor – or with `PQ_SERIES = True` every 10-min value per phase – for the orders of the positive or negative sequence; the zero sequence and the even orders keep the pre-fault voltage of the tests (`MODEL.test_voltages()`, not scaled). A measurement shorter than every duration of `PQ_FACTORS` (gapless values) is not valid and gives no voltages ([Power-quality measurements](../user-guide/pq.md)) |
| `Z_F`, `LINE` | fault impedance and fault location of the forecast (`LINE = None`: at the busbar) |
| `MARGIN_A`, `FUNDAMENTAL_A`, `LIMITS` | margin per order, fundamental residual current, limits – defined by you; groundfault contains none |

The entries of `TESTS`, `FAULTS` and `CHECKS` take the optional keys `name`, `meta` (free metadata, e.g. load or
switching state), `transformer` (the transformer recording of the same earth fault by a second recorder) and `line`
(the line to the fault location of a test or earth fault in the network). The notebook saves the model file and the
tables in the forecast folder of the work folder, `forecast/<network>/` (German layout `05_Prognose/<network>/`).

## Calibration from the campaigns

A staged fault test is a recording of the kind `substation` with an additional impedance in the column
`fault_resistance_Ohm` of the register ([register](../user-guide/campaigns.md#the-register)).
[`campaign_tests`][groundfault.forecast.campaigns.campaign_tests] lists them;
[`build_model`][groundfault.forecast.campaigns.build_model] reads their result files:

```python
import os, tempfile
import groundfault as gf
from groundfault import demo, layout
from groundfault import forecast as fc

work = tempfile.mkdtemp()
info = demo.make_campaign(work, groundmeas=False)                 # demo work folder: register and one campaign
for w in info["substation"]:                                      # the single evaluation (normally the notebook)
    b = w["intervals"]
    res = gf.evaluate(gf.open_recording(os.path.join(info["campaign"], w["cfg"])),
                      gf.Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]), tuple(b["post_fault"])),
                      z_fault_ohm=w["Z_F"])
    res.save_json(layout.ENGLISH.result_path(info["campaign"], os.path.splitext(w["file"])[0]))

tests = fc.campaign_tests(work, "2026-01-15_Demo")                # the staged tests from the register
print(tests)
model, messages = fc.build_model(work, tests, name="Demo substation")
print(model)
check = model.cross_check(mode="loo")
print(check[check.order.isin([3, 5, 7, "I_H"])][["target", "order", "kind", "I_measured_A", "I_forecast_A",
                                                 "deviation_A"]].round(2).to_string(index=False))
```

```text
[{'campaign': '2026-01-15_Demo', 'measurement': 'SUB_0_10_000kHz', 'Z': 0.0}, {'campaign': '2026-01-15_Demo', 'measurement': 'SUB_2_5_10_000kHz', 'Z': 2.5}, {'campaign': '2026-01-15_Demo', 'measurement': 'SUB_5_10_000kHz', 'Z': 5.0}]
NetworkModel('Demo substation', tests=3, faults=0, orders=[3, 5, 7, 11, 13])
           target order       kind  I_measured_A  I_forecast_A  deviation_A
  SUB_0_10_000kHz     3 two_source          4.04          4.12         0.08
  SUB_0_10_000kHz     5  pre_fault         42.74         42.75         0.01
  SUB_0_10_000kHz     7  pre_fault         14.06         14.05        -0.01
  SUB_0_10_000kHz   I_H                    46.58         46.59         0.01
SUB_2_5_10_000kHz     3 two_source          3.19          3.22         0.03
SUB_2_5_10_000kHz     5  pre_fault         32.56         32.55        -0.01
SUB_2_5_10_000kHz     7  pre_fault         11.95         11.94        -0.01
SUB_2_5_10_000kHz   I_H                    35.70         35.69        -0.01
  SUB_5_10_000kHz     3 two_source          2.14          2.15         0.01
  SUB_5_10_000kHz     5  pre_fault         21.28         21.28         0.01
  SUB_5_10_000kHz     7  pre_fault          8.36          8.36        -0.01
  SUB_5_10_000kHz   I_H                    23.46         23.47         0.00
```

`messages` lists missing result files and the hints of loading (a reversed coil channel, orders without a voltage
change …). If the transformer currents were recorded by a second recorder and every additional impedance occurs once
among the tests and the transformer recordings, `campaign_tests` names the transformer recording of each test
(`transformer`); its upstream impedance enters the model. In the demo network the model reproduces every test – a
real network shows the spread of its state between the tests.

`add_test` takes the odd orders from 3 on with at least 0.3 A of fault current (`min_current_A`), or the orders you
list (`orders=[3, 5, 7, 11, 13]`). **Tests with different additional impedances** separate the source that arises
with the fault (`kind = two_source` in `model.source_table()`); with a single additional impedance these orders keep
the measured current (`constant`).

Without a work folder the result files are read directly:

```python
model = fc.NetworkModel("Substation A")
for path, Z in (("…/SUB_0_10_000kHz_result.json", 0.0), ("…/SUB_5_10_000kHz_result.json", 5.0)):
    model.add_test(fc.load_fault_data(path, Z, meta=dict(switching_state="normal")))
```

Phasors from another tool enter through [`fault_data_from_values`][groundfault.forecast.data.fault_data_from_values]
(sequence or phase voltages per order before and during the fault, the fault current for a test).

## Checks between the tests

```python
model.cross_check(mode="loo")         # every test with the model of all other tests
model.cross_check(mode="pairwise")    # every test with the model of one other test
model.cross_check(mode="chain")       # Z_0 of one test, the update with a second, forecast for a third
```

Read the negative deviations: they are the underestimates. The orders of the pre-fault source should agree within a
few percent; larger deviations point to a state that differs between the tests (a switched feeder, a changed coil) or
to the voltage transformers. The largest underestimate per order is a basis for the margin you add (`margin_A`).

## Recorded earth faults

Every earth fault recorded at the busbar adds to the model – evaluate the recording with the measurement notebook
(line-to-earth voltages, a pre-fault interval and the steady state of the fault; no additional impedance), then:

```python
messages = fc.add_entries(model, work, [dict(campaign="…", measurement="…", meta=dict(feeder="…"))], kind="fault")
c = model.calibrations[-1]
c.currents, c.current_method        # estimated fault current per order and its method
model.fault_check()                 # forecast for every recorded earth fault from its own pre-fault voltage
```

Z_0 comes from the tests (median); Z_1, Z_2 and Z_q of the earth fault describe the network of that day. With coil
currents in the recording – and in the tests – the fault current follows from the
[node rule](model.md#node-rule-with-the-coil-currents) at every order (`node_rule`); otherwise from the zero-sequence
voltage at the orders without a source in the fault (`zero_sequence_voltage`). The orders of the zero sequence are not
used to update Z_q. A known fault location goes in as `line=…`; `fault_check` then forecasts the earth fault behind it.

## A staged test in the network

```python
LINE = dict(name="feeder 7, station 12", segments=[
    dict(length_km=3.2, R1=0.125, X1=0.11, R0=0.50, X0=0.40, C1_uF=0.30),    # cable
    dict(length_km=1.8, R1=0.30, X1=0.35, R0=0.45, X0=1.20, C1_uF=0.01)])   # overhead line
fd = fc.check_data(work, dict(campaign="…", measurement="<substation recording>", Z=0.0,
                              current="<recording at the fault location>", line=LINE))
model.verify(fd)                    # forecast from the busbar voltages before the test and the line, per order
```

The busbar voltages come from the substation recording, the fault current from the recording at the fault location
(magnitudes per order; both evaluated with the measurement notebook). A line is a list of segments with the length and
the per-length values at 50 Hz in Ω/km and µF/km ([`Line`][groundfault.forecast.line.Line],
[`LineSegment`][groundfault.forecast.line.LineSegment]); `Line.from_impedances(Z1, Z0)` takes the total impedances
instead.

**Values per order.** With the 50-Hz values the resistance stays constant and the reactance grows with m – not on the
safe side by construction ([model](model.md#fault-behind-a-line)). Give the orders of interest their own values: per
segment R′ and X′ at m·50 Hz from a line-parameter calculation, or for the whole line the loop contribution
Z_qL,m = (2·Z_1L,m + Z_0L,m)/3, e.g. measured from a recorded earth fault behind the line:

```python
LINE = dict(name="feeder 7, station 12", segments=[
    dict(length_km=3.2, R1=0.125, X1=0.11, R0=0.50, X0=0.40, C1_uF=0.30,
         orders={5: dict(R1=0.13, X1=0.53, R0=0.95, X0=1.45)}),           # values at 250 Hz (X not divided by m)
    dict(length_km=1.8, R1=0.30, X1=0.35, R0=0.45, X0=1.20, C1_uF=0.01,
         orders={5: dict(R1=0.31, X1=1.74, R0=1.05, X0=5.40)})])
line = fc.Line.from_impedances(1.5 + 1.8j, 6.0 + 4.5j, "strand",          # totals at 50 Hz …
                               orders={5: (1.6 + 8.2j, 6.6 + 15.0j)})      # … and at 250 Hz
fault = fc.load_fault_data("<result file of an earth fault behind the line>")
loop = model.line_from_fault(fault)                    # {order: Z_qL,m} from the busbar voltages alone
line = fc.Line(LINE["segments"], LINE["name"], loop=loop)
```

The forecast names the orders that still use the 50-Hz values (`f.hints`). `line_from_fault` takes the fault current
from the node rule (coil currents) or from the zero-sequence voltage – not at the orders of a source in the fault – and
returns Z_qL,m + Z_F with Z_F = 0 unless given (the earthing impedance of the station is part of it).

## Forecast

```python
f = model.forecast({5: U5, 7: U7, 11: U11, 13: U13, 3: U3}, Z_F=0.0, margin_A=…)    # at the busbar
g = model.forecast(voltages, line=LINE)                                           # behind a line
f.table()                 # per order: U_V, Us_V, |Z_q + Z_qL + Z_F|, I_A, margin_A, I_forecast_A; I_rest, I_H, I_1, I_RES
f.IH, f.IRES              # totals
```

| Input | Example |
|---|---|
| one value per order | `{5: 250.0, 7: 120.0}` or a pandas Series |
| time series | DataFrame with one column per order: `5`, `"H5"`, `"U_H5"`, `"U_L1_H5"` – the last number of the column name is the order |
| per phase | `{"L1": …, "L2": …, "L3": …}` – per order and time step the largest current of the phases |
| line-to-line | `reference="LL"`: divided by √3; the orders of the zero sequence keep only the source that arises with the fault |
| percent | `percent_of=U_LE`: the voltages are given in % of `U_LE` |
| PQ measurement | `pq.assess(pq.read(files), factor=k).voltages()` (quantile × factor per order) or `.series()` (10-min values per phase), with `reference="LE"`; the zero sequence and the even orders with `model.test_voltages(…)` instead ([Power-quality measurements](../user-guide/pq.md#the-forecast)) |

A time series is forecast per time step; `f.quantile(0.95)` gives the quantile of the time series of I_H and I_RES
and per order, `f.table(0.95)` the table at that quantile. The hints (`f.hints`) say where the forecast relies on a
constant current, where voltages are missing and how long the line is compared with a quarter wavelength.

## Model file and tables

```python
model.save(os.path.join(fc.forecast_folder(work, "Demo substation"), "demo_substation_network_model.json"))
model = fc.NetworkModel.load("…/demo_substation_network_model.json")
```

| Table | Columns |
|---|---|
| `model.table()` | `name`, `kind` (`test`/`fault`), `time`, `faulted_phase`, `Z_F_Ohm`, `line_name` (tests in the network), `order`, magnitude and angle of `Z0`, `Z1`, `Z2`, `Zq`, `U_q_V`, `dU0_V`, `I_measured_A`, `I_estimated_A`, `I_estimated_method`; with coil currents `Y0_net_S`; with the transformer node `Z_up_…`, `Z_down_…`, `G_down_S`, `B_down_S` |
| `model.source_table()` | `order`, `kind` (`pre_fault`, `two_source`, `constant`), `Zq_Ohm`, `Zq_angle_deg`, `Us_V`, `Us_angle_deg`, `I_constant_A`, `n`, `residual_pct`, `calibrations` |
| `cross_check()`, `fault_check()`, `verify()` | `mode`, `target`, `model`, `Z_F_Ohm`, `order`, `kind`, `I_measured_A`, `I_forecast_A`, `deviation_A`, `ratio` (`fault_check` also `I_estimated_method`) |
| `forecast.table()` | `order`, `kind`, `U_V`, `Us_V`, `Z_line_Ohm` (with a line), `Zq_ZF_Ohm`, `I_A`, `margin_A`, `I_forecast_A` and the rows `I_rest`, `I_H`, `I_1`, `I_RES` |

German column names and codes come with [`i18n.localize`](../user-guide/language.md), as for every table of
groundfault; importing `groundfault.forecast` registers them.
