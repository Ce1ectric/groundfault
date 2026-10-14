# groundfault

**Evaluation of staged earth-fault tests in compensated (resonant-earthed) medium-voltage networks.**

groundfault reads the COMTRADE recordings (IEEE C37.111) of staged earth-fault tests – at the substation and at
secondary substations – and computes everything that is needed to assess the residual earth-fault current and the
earthing systems of a resonant-earthed network: assessment quantities with measurement uncertainty, harmonics,
voltages, the earth potential rise and touch voltage per frequency, the current into the LV network and the reduction
factor compared with earthing measurements. All algorithms live in a Python package; two Jupyter notebooks serve as the
user interface. Tables, hints and figures are available in English and German.

![Reduction factor per harmonic order from a staged fault test and an earthing measurement of the same station (top)
and the two compared impedances (bottom) – demo station](assets/station_reduction_factor.png)

*Reduction factor of the demo station: the fault-related earth potential rise per ampere of fault current divided by
the earthing impedance from a current-injection measurement, per harmonic order (top), and the two compared impedances
(bottom).*

## What it does

<div class="grid cards" markdown>

-   __Substation__

    ---

    Residual earth-fault current as the true RMS value of the largest 200-ms window, its fundamental component and
    harmonics, active and reactive (detuning) current by the angle method, measurement uncertainty, scaling to the
    95 % quantile of a power-quality measurement, voltages before, during and after the fault (sequence components,
    THD). Over a series of tests with different additional impedances: the **equivalent-source method** – an active
    two-terminal equivalent per harmonic order and the residual current at any earthing impedance Z_E.

-   __Secondary substation__

    ---

    Earth potential rise and touch voltage **per frequency**, as measured and as the **fault-related component**
    (superposition removes the background already present before the fault), with an uncertainty estimate. PEN
    currents give the current into the LV network and the earthing impedance of the LV network. Compared with the
    earthing measurements stored in a [groundmeas](https://github.com/Ce1ectric/groundmeas) database, the
    **reduction factor** follows per harmonic and as an RMS value; evaluated tests can be entered in groundmeas.

-   __Checks at the curves__

    ---

    The **signal explorer** shows all channels of a recording with RMS values, harmonics and THD on hover – in the
    notebook and as a single HTML file that opens in any browser – computed exactly as in the evaluation, so every
    number can be checked at the measured waveform.

-   __Report output__

    ---

    Figures in their final size for an A4 report (no titles, one font, PDF/SVG/PNG) and tables as CSV, Markdown,
    Excel and Word. Output in **English or German** (hints, tables, figures, exported files) and two folder layouts
    for the campaigns (English `campaigns/…/raw|results|figures`, German `01_Messkampagnen/…/1_Rohdaten|…`).

</div>

## At a glance

The demo campaign of `groundfault.demo` contains synthetic recordings with a known solution, so this example runs
without any measurement data:

```python
import os, tempfile
import groundfault as gf
from groundfault import demo

d = demo.make_campaign(tempfile.mkdtemp(), layout="en")              # synthetic campaign, known solution
rec = gf.open_recording(os.path.join(d["campaign"], "raw/SUB/SUB_0_10_000kHz.cfg"))
res = gf.evaluate(rec, gf.Intervals(steady_state=(2.6, 4.4), pre_fault=(0.2, 1.8), post_fault=(7.0, 8.8)),
                  z_fault_ohm=0.0)
print(res.summary())
print(res.table("assessment_quantities")[["quantity", "measured_value", "assessment", "unit"]].round(2).head(3))
```

```text
Measurement: SUB_0_10_000kHz  (SUB_0_10_000kHz.cfg)
Max window: 4.300 s  | f1 = 50.0200 Hz (phase)
IRES = 56.53 A | IG = 32.01 A | Iw = 20.00 A | Iv = 25.00 A | IH = 46.59 A
  quantity  measured_value  assessment unit
0     IRES           56.53       56.53    A
1       Iw           20.00       20.00    A
2       Iv           25.00       25.00    A
```

The demo network was generated with an active residual current of 20 A and a detuning of 25 A – the evaluation finds
both. The column `assessment` adds a measurement-uncertainty margin of your choice; groundfault contains no margins,
limits or safety factors – you define them ([Evaluating a recording](user-guide/evaluation.md#settings)) – so here it
equals the measured value. The [quickstart](getting-started/quickstart.md) continues this example through the whole
workflow.

## Where to go next

| If you want to … | read |
|---|---|
| install groundfault, set up Jupyter, run the tests | [Installation](getting-started/installation.md) |
| see the whole workflow once, with the demo campaign | [Quickstart](getting-started/quickstart.md) |
| evaluate your own recordings step by step | [User guide](user-guide/index.md) |
| understand what is computed and why | [Methods](methods/index.md) |
| look up a function, a parameter or a table column | [API reference](reference/index.md) |

groundfault is released under the [MIT licence](about/license.md). Contributions are welcome – see
[Contributing](about/contributing.md).
