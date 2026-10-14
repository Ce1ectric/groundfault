# Signal explorer

The signal explorer answers the question every evaluation should be checked against: *does the value match the
curve?* It shows the RMS trend of all channels over the whole recording and, for an excerpt that you choose, the
instantaneous values, the spectrum and a table of characteristic values – computed exactly as in the evaluation. It
exists in two forms:

* in the notebook – `explorer.explorer(rec, res)`, an interactive interface (section 5 of the measurement notebook);
* as **one HTML file** – `explorer.explorer_html(rec, path, res)`, which opens in any browser without Python and can
  be passed on with the report (written in section 7 with `EXPLORER_HTML = True`).

The functions are in [`groundfault.explorer`](../reference/explorer.md).

## In the notebook

```python
import os
import tempfile

import groundfault as gf
from groundfault import corrections, demo, explorer

base = tempfile.mkdtemp()
d = demo.make_campaign(base, layout="en")
campaign = d["campaign"]
rec = gf.open_recording(os.path.join(campaign, "raw/SUB/SUB_0_10_000kHz.cfg"))
corr = corrections.load(campaign)
corr.apply(rec)
roles = gf.detect_roles(rec.channel_names, rec.units, corr.role_overrides(rec), corr.main_channel(rec),
                        corr.distances(rec))
res = gf.evaluate(rec, gf.Intervals((2.6, 4.4), (0.2, 1.8), (7.0, 8.8)), roles=roles, z_fault_ohm=0.0)

ex = explorer.explorer(rec, res)        # as the last line of a notebook cell it shows the interface
print(ex)
print({key: tuple(round(t, 3) for t in span) for key, span in ex.times.items()})
```

```text
<SignalExplorer SUB_0_10_000kHz.cfg | 7 channels | 89 windows of 200 ms>
{'pre-fault': (0.9, 1.1), 'fault inception': (1.96, 2.16), 'max window': (4.2, 4.4), 'fault clearance': (5.84, 6.04), 'post-fault': (7.8, 8.0)}
```

As the last expression of a cell the object shows the interface. Given the evaluation result `res`, it takes the
channel roles, the network frequency f1, the analysis intervals, the max window and the time alignment of recorder
subsystems from it. Without `res` (`explorer.explorer(rec)`) it works as well – before the intervals are entered,
for a first look – then with roles detected from the channel names, f1 estimated from the recording and without a
max window.

**Controls**

| Control | Effect |
|---|---|
| *Channels* | channels shown (Ctrl/⌘ or Shift for several); by default the fault current, earth potential rise and touch voltage, the line-to-earth and neutral displacement voltages, coil, shield and PEN currents (at most ten) |
| *Time* (jump to) | moves the excerpt to an event: before the fault, fault inception, max window (evaluation), fault clearance, after the fault |
| *Width* | width of the excerpt: 1 cycle, 5 or 10 cycles, 0.5 to 10 s |
| ◀ back / forward ▶ | moves the excerpt by its width |
| *up to order* | highest order of the spectrum |
| *RMS value* / *% of H1* | spectrum as RMS values or as share of the fundamental |
| *Excerpt* (slider below the overview) | sets the excerpt freely |

**Figures and table**

* **Overview** – the true RMS value per 200-ms window over the whole recording (windows overlap by half for
  recordings up to 180 s). Hovering shows, for all selected channels at the same instant, the RMS value, the
  harmonics H1, H3, H5, H7 …, the THD and the DC component. The analysis intervals are shaded in colour, the excerpt
  in grey. A click on a legend entry hides a channel, a double click shows only this one.
* **Instantaneous values** of the excerpt; long excerpts are condensed for the display (minimum and maximum per
  section – the title says so).
* **Spectrum** of the excerpt (Hann window, DFT at m·f1) up to the chosen order; the hover text gives the value, the
  share of H1 and the angle.
* **Characteristic values** of the excerpt per channel – the table below.

| Column | Meaning |
|---|---|
| RMS value | true RMS value over all frequencies, DC component removed (median), as in the evaluation |
| DC component | mean value of the excerpt |
| Peak value, Crest factor | largest magnitude of the instantaneous values; peak value / RMS value (√2 ≈ 1.41 for a sine) |
| H1, Angle H1 in ° | fundamental component (RMS value) and its angle, referred to the fundamental of the **first selected channel** |
| H3, H5, H7 | RMS values of these harmonics |
| THD in % | √(Σ H_m², m ≥ 2)/H1 over the computed orders (up to 40) |

An excerpt shorter than two cycles is analysed over ten cycles around its centre, one longer than 10 s over its
middle 10 s; a note above the table says so.

## Checking the max window

Jumping to *max window (evaluation)* selects exactly the window the evaluation assessed: the explorer shows the same
values as the result tables. In Python the same table comes from `ex.table(t0, t1)`:

```python
t0, t1 = ex.times["max window"]
table = ex.table(t0, t1)
print(table[["channel", "unit", "rms", "dc", "peak", "crest_factor", "H1", "H1_angle_deg", "H5", "THD_pct"]]
      .round(3).to_string(index=False))
print("evaluation: IRES = %.3f A, IH1 = %.3f A" % (res.values["IRES"], abs(res.phasor(roles.main("i_res").index, 1))))
```

```text
channel unit       rms     dc      peak  crest_factor        H1  H1_angle_deg      H5  THD_pct
     V1    V 20001.515  3.954 28676.449         1.434 19999.928         0.000 381.170    2.163
     V2    V 20008.587 11.284 28675.189         1.433 20000.039       -59.999 381.079    2.162
     V3    V     2.965  0.113    10.661         3.596     0.134        -8.750   0.053  468.083
    IF1    A    56.526  2.026   114.946         2.034    32.015       -81.341  42.737  145.502
    IF2    A    56.961  0.025   113.590         1.994    32.333       -81.839  43.056  145.028
  ISp21    A   299.993  0.108   424.009         1.413   300.000      -119.999   1.140    0.411
  ISp22    A   249.995  0.089   353.312         1.413   250.002      -119.999   0.951    0.412
evaluation: IRES = 56.526 A, IH1 = 32.015 A
```

What to look for in and around the max window:

* **Clipping or saturation** – flat tops of the instantaneous values, a crest factor that is too small. The values of
  such a channel are distorted; use another CT as main channel ([Corrections](corrections.md)).
* **Steps, spikes and switching** in the excerpt – the max window should lie in a steady section. The plausibility
  checks “RMS ↔ √ΣX²” and “Stationarity of I_H1” point to such windows ([Evaluating a recording](evaluation.md#plausibility-checks)).
* **DC component** – a fault current with a large, decaying DC component right after the inception; the
  steady-state interval should start after it has decayed.
* **Voltage and current at the same time** – the fault inception must appear at the same instant in voltages and
  currents; otherwise the export has a time offset between recorder subsystems
  ([raw-data diagnostics](evaluation.md#raw-data-diagnostics)).
* **Polarity** – compare the angles of two CTs of the same current (the table refers them to the first selected
  channel; select that channel first).

The values of every window are also available as a table: `ex.kw` holds RMS value, DC component, peak value and
phasors of all windows (`explorer.WindowMetrics`); `ex.kw.table(channel_index)` returns them for one channel:

```python
k = roles.main("i_res").index
w = ex.kw.table(k)
print(w[(w["t_s"] > 4.0) & (w["t_s"] < 4.5)].round(3).to_string(index=False))
```

```text
 t_s    rms     H1    H3     H5     H7  THD_pct    dc    peak
 4.1 56.525 32.017 4.045 42.738 14.056  145.497 2.026 114.889
 4.2 56.525 32.015 4.043 42.738 14.055  145.503 2.026 114.889
 4.3 56.526 32.015 4.042 42.737 14.056  145.502 2.026 114.946
 4.4 56.526 32.015 4.040 42.738 14.056  145.504 2.028 114.946
```

The window centred at 4.3 s is the max window. Without `ipywidgets` the notebook shows only the overview (with a
warning); `ex.overview()`, `ex.instantaneous(t0, t1)` and `ex.spectrum(t0, t1)` return the single Plotly figures.

## The HTML file

`explorer.explorer_html(rec, path, res)` writes everything into one HTML file that opens in a browser without any
installation:

```python
path = explorer.explorer_html(rec, os.path.join(base, "SUB_0_10_000kHz_explorer.html"), res)
print(os.path.basename(path), "%.1f MB" % (os.path.getsize(path) / 1e6))
```

```text
SUB_0_10_000kHz_explorer.html 7.1 MB
```

The page contains

* the **RMS trend** of all channels with harmonics, THD and DC component on hover, with channel selection;
* the **envelope** of the instantaneous values of the whole recording (minimum and maximum per section);
* **excerpts** of 200 ms each with their instantaneous values, spectrum and characteristic values: the events
  (before the fault, fault inception, max window, fault clearance, after the fault; marked ★) and up to 40 excerpts
  spread evenly over the recording. A click into the overview selects the nearest excerpt. Because the instantaneous
  values must be stored in the file, they are kept with at most 10 kHz (low-pass filtered, `fs_max`), and the number
  of evenly spread excerpts is limited by the size (`max_bytes`, about 3 MB); spectra and characteristic values are
  computed from the original data;
* optionally further interactive figures at the end (`figures={heading: figure}`). The measurement notebook adds, at
  a station, the evaluation per frequency, the comparison with the earthing measurement, the reduction factor and
  the LV network.

`plotly_js="inline"` (default) embeds the Plotly library – the file works offline but is about 5 MB larger;
`plotly_js="cdn"` loads it from the internet. Texts, number format and date follow the output language that is
active when the file is written ([Language and folder layout](language.md)). In the notebook the file is
`figures/<measurement>/<measurement>_explorer.html`.

| Parameter | Default | Meaning |
|---|---|---|
| `res` | `None` | evaluation result: f1, roles, intervals, max window and alignment |
| `roles`, `channels` | `None` | roles (default: those of `res`); channels in the file (default: all) |
| `T_win` | `0.2` | window length of the RMS trend in s |
| `hover_orders` | `(1, 2, 3, 5, 7, 9, 11, 13)` | orders shown on hover in the overview |
| `spectrum_orders` | `range(1, 41)` | orders of the spectra (and of the THD) |
| `n_uniform`, `fs_max`, `max_bytes` | `40`, `10000.0`, `3.0e6` | evenly spread excerpts, sampling rate and size limit of the stored instantaneous values |
| `title` | `None` | page title (default “Signal explorer – <file name>”) |
| `plotly_js` | `"inline"` | `"inline"` or `"cdn"` |
| `figures` | `None` | further Plotly figures `{heading: figure}` |
| `alignment` | `None` | time alignment of subsystems (default: the one stored in `res`) |

The building blocks are available on their own: `explorer.window_metrics(rec, …)` (values of all windows),
`explorer.event_times(rec, roles, res)` (the excerpts above), `explorer.excerpt_spectrum` and
`explorer.excerpt_table` (spectrum and characteristic values of any excerpt) and `explorer.line_frequency(rec)` (the
network frequency estimated from the recording).
