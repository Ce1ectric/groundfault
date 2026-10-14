# Corrections of the measuring chain

A staged earth-fault test can rarely be repeated. If it turns out afterwards that a CT ratio was set wrongly, a
clamp enclosed only one of several parallel conductors, a clamp was connected with reversed polarity, a channel name
lacks the probe distance or a channel got the wrong role, this is noted **once per campaign** in the corrections
file `notes/corrections.csv` (German layout: `0_Notizen/Korrekturen.csv`). groundfault applies the corrections
whenever a recording is read – the raw data stay untouched – and documents every applied correction in the hints,
in the plausibility table and in the result file.

## The file

The file is created with a header and an explanation when the campaign is set up – by `tools/update_register.py`
or `corrections.write_template(campaign_folder)`; an existing file is never overwritten. It is a semicolon-separated
text file; edit it with a spreadsheet program or a text editor. Lines starting with `#` are comments, empty lines are
ignored. A file with all kinds of entries:

```text
file;channel;factor;role;main_channel;distance_m;remark
SUB_7_5_*;ISp22;10;;;;CT ratio of the coil current set wrongly in the 7.5-Ω test (reads a tenth)
SUB_*;ISp21;2;;;;clamp encloses only one of two parallel coil cables
SUB_*;IF?;-1;;;;fault-current clamps connected with reversed polarity
*;IF3;;ignore;;;spare channel, not connected – do not evaluate
SUB_*;IF2;;;yes;;main fault-current channel (the CT at the fault location)
Station_*;UEr;;;;40;remote probe at 40 m (distance not in the channel name)
Station_*;IPEN1;;i_pen_feeders;;;PEN clamp around the LV feeders
```

| Column | Meaning |
|---|---|
| `file` | file name or pattern: `*` any characters, `?` one character; with or without `.cfg`; case is ignored; empty = all files. `SUB_2_5_*` applies to the instantaneous-value file `SUB_2_5_10_000kHz.cfg` **and** the RMS file `SUB_2_5_10_000Hz.cfg`; `SUB_2_5_10_000kHz` only to the first |
| `channel` | short name – the channel name without device prefix and channel group, `DANEO 1_Spannungen_UE_70m Inst` → `UE_70m` – or the full channel name, or a pattern (`IF?`, `ISp*`); case is ignored |
| `factor` | multiplier applied to the measured values: `10`, `0.1` or `0,1`, `1/3`, `-1` (polarity), also `x3`; empty = 1; 0 is not allowed. The factors of several lines that match the same channel are multiplied |
| `role` | fixes the channel role ([role codes](#role-codes)) or `ignore` – the channel is not evaluated (also accepted: `none`, `off`, `-`) |
| `main_channel` | `yes` (also `y`, `x`, `1`, `true`): this channel is the main channel of its role, e.g. the fault-current CT the evaluation uses |
| `distance_m` | probe distance in m (`70`, `1.0`, `70 m`) for earth-potential channels whose name contains none (`UE`, `UEr`); see below |
| `remark` | reason, who, when – shown with every applied correction; it may contain the separator |

Details:

* **Separator, numbers, encoding.** The separator is the one that occurs most often in the header line (`;`, tab or
  `,`). Factors and distances take a decimal point or comma. UTF-8 is expected; files saved by a spreadsheet program
  in Windows-1252 or Mac Roman are read as well.
* **German headers** (`Datei;Kanal;Faktor;Rolle;Hauptkanal;Abstand_m;Bemerkung`) and German values (`ignorieren`,
  `keine`, `aus`; `ja`, `j`, `wahr`) are accepted in either layout, as are files of the predecessor tool. New files
  are written with the headers of the campaign's [folder layout](language.md#folder-layouts). The column `distance_m`
  may be missing (older files) and may stand anywhere before `remark`.
* **RMS files have no sign.** A channel of an RMS export (device suffix `RMS`, or a sampling rate below 200 Hz) gets
  only the magnitude of the factor, with a hint (“… contains RMS values – the sign has no meaning, only |factor| = …
  applied.”); a pure polarity correction does nothing there. So one line with a `SUB_*` pattern serves the
  instantaneous values and the RMS export alike.
* **Probe distance.** `distance_m` is needed where the channel name does not carry it (`UE_70m`, `U1m` and `UE100`
  do). It decides whether a probe measures the touch voltage (up to 1.5 m, see
  [Stations and the LV network](station.md#probes-and-touch-voltage)), which probe of an earthing measurement it is
  compared with, and it becomes `measurement_distance_m` in groundmeas.
* **Errors** stop the reading with the file name and the line: “corrections.csv, line 5: unknown role 'i_fault'
  (allowed: u_l1e, …, ignore)”, “… factor 0 is not allowed.”, “… factor 'ten' not readable (e.g. 10, 0.1, 1/3, -1)”,
  “… distance_m 'far' is not a probe distance in m (e.g. 70 or 1.0)” – the column is named as it is written in the
  file (`Abstand_m` with German headers). A line whose channel does not occur in a matching recording only gives a
  hint: “corrections.csv line 9: channel 'ISp99' not in SUB_0_10_000kHz.cfg – check the spelling.”

## Role codes

| Code | Meaning |
|---|---|
| `u_l1e`, `u_l2e`, `u_l3e` | line-to-earth voltages (MV) |
| `u_hv_l1e`, `u_hv_l2e`, `u_hv_l3e` | line-to-earth voltages (HV) |
| `u_l12`, `u_l23`, `u_l31` | line-to-line voltages (measured) |
| `u_ne` | neutral displacement voltage (measured directly) |
| `u_e` | earth potential rise (station; possibly several probes) |
| `u_t` | touch voltage |
| `u_gen` | other voltage |
| `i_res` | residual earth-fault current (possibly several CTs) |
| `i_coil` | coil current (arc suppression coil) |
| `i_l1`, `i_l2`, `i_l3` | line currents (transformer) |
| `i_shield` | shield current |
| `i_pen` | PEN or earth-electrode leakage current |
| `i_pen_feeders` | PEN current before the transformer star point (sum of the PEN conductors of the LV feeders) – role `i_pen` with position `feeders` |
| `i_pen_busbar` | PEN current after the transformer star point (connection to the main earthing busbar) – role `i_pen` with position `busbar` |
| `i_gen` | other current |
| `ignore` | the channel is not evaluated |

Role names of the predecessor tool are translated: `i_schirm` → `i_shield`, `u_hs_l1e` … → `u_hv_l1e` …, `i_pen_v` →
`i_pen_feeders`, `i_pen_n` → `i_pen_busbar`. How roles are detected from the channel names is described in
[Campaigns, folders and files](campaigns.md#channel-names).

**Main channel.** Several channels can have the same role – two fault-current CTs, several probes. The evaluation
uses one of them, the main channel (✓ in the role table): by default for the fault current `IF`/`I_F`, then `IF1`,
`IF2` …, then the largest measuring range (`IFr500` before `IFr50`); for the earth potential rise the remote probe.
Set it with `main_channel` = `yes` when the default is the saturated or the wrongly scaled CT.

## What happens when a recording is read

The example adds a fourth substation test to the demo campaign whose measuring chain had two errors: the
fault-current clamps were connected the wrong way round, and the CT ratio of the coil current `ISp22` was set ten times
too large, so it reads a tenth of the real current. Evaluated without corrections:

```python
import os
import tempfile

import groundfault as gf
from groundfault import corrections, demo

base = tempfile.mkdtemp()
d = demo.make_campaign(base, layout="en")
campaign = d["campaign"]
cfg = os.path.join(campaign, "raw/SUB/SUB_7_5_10_000kHz.cfg")
demo.make_substation_recording(cfg, 7.5, polarity=-1, coils_A=(300.0, 25.0), seed=7)   # the two errors

intervals = gf.Intervals((2.6, 4.4), (0.2, 1.8), (7.0, 8.8))
res = gf.evaluate(gf.open_recording(cfg), intervals, z_fault_ohm=7.5)
print(res.summary())
print(res.table("coil_currents").round(2).to_string(index=False))
```

```text
Measurement: SUB_7_5_10_000kHz  (SUB_7_5_10_000kHz.cfg)
Max window: 3.700 s  | f1 = 50.0200 Hz (phase)
IRES = 37.69 A | IG = 32.02 A | Iw = 20.00 A | Iv = 25.00 A | IH = 19.89 A
⚠ Iw was negative → current measurement reversed; current phasors rotated by 180° (magnitudes unchanged).
channel  RMS_A   H1_A  H1_angle_ref_ULL_deg
  ISp21 296.05 296.06               -179.07
  ISp22  24.67  24.67               -179.07
```

The evaluation notices the reversed polarity by itself (and rotates the current phasors), but not the coil current:
25 A is a plausible value. The campaign consistency check would flag it against the other tests
([Campaign evaluation](campaign.md#overview-and-consistency)). Both errors belong in the corrections file:

```python
with open(corrections.path_for(campaign), "a", encoding="utf-8") as f:
    f.write("SUB_7_5_*;IF?;-1;;;;fault-current clamps connected with reversed polarity (test report)\n")
    f.write("SUB_7_5_*;ISp22;10;;;;CT ratio of the coil current set wrongly – reads 1/10\n")
corr = corrections.load(campaign)
print(corr.table().to_string(index=False))
```

```text
 line               file channel  factor role main_channel  distance_m                                                              remark
   11 Station_Elm_Road_*      UT     1.0                           1.0                                   touch-voltage probe at 1 m (demo)
   12          SUB_7_5_*     IF?    -1.0                           NaN fault-current clamps connected with reversed polarity (test report)
   13          SUB_7_5_*   ISp22    10.0                           NaN               CT ratio of the coil current set wrongly – reads 1/10
```

The demo campaign already contains one line: the touch-voltage probe `UT` of the station gets its distance of 1 m.
Reading the recording again with the corrections, as the measurement notebook does in section 2:

```python
rec = gf.open_recording(cfg)
log = corr.apply(rec)                     # once per recording; all values read from now on are corrected
print(log.to_string(index=False))
roles = gf.detect_roles(rec.channel_names, rec.units, corr.role_overrides(rec), corr.main_channel(rec),
                        corr.distances(rec))
res = gf.evaluate(rec, intervals, roles=roles, z_fault_ohm=7.5)
print(res.summary())
print(res.table("coil_currents").round(2).to_string(index=False))
plausibility = res.table("plausibility")
print(plausibility[plausibility["check"].str.startswith("Corrections")][["check", "status", "value"]]
      .to_string(index=False))
```

```text
channel  factor  factor_total role main_channel distance_m  line                                                              remark
    IF1    -1.0          -1.0                         None    12 fault-current clamps connected with reversed polarity (test report)
    IF2    -1.0          -1.0                         None    12 fault-current clamps connected with reversed polarity (test report)
  ISp22    10.0          10.0                         None    13               CT ratio of the coil current set wrongly – reads 1/10
Measurement: SUB_7_5_10_000kHz  (SUB_7_5_10_000kHz.cfg)
Max window: 3.700 s  | f1 = 50.0200 Hz (phase)
IRES = 37.69 A | IG = 32.02 A | Iw = 20.00 A | Iv = 25.00 A | IH = 19.89 A
⚠ Correction applied: IF1 × -1 (notes/corrections.csv, line 12) – fault-current clamps connected with reversed polarity (test report)
⚠ Correction applied: IF2 × -1 (notes/corrections.csv, line 12) – fault-current clamps connected with reversed polarity (test report)
⚠ Correction applied: ISp22 × 10 (notes/corrections.csv, line 13) – CT ratio of the coil current set wrongly – reads 1/10
channel  RMS_A   H1_A  H1_angle_ref_ULL_deg
  ISp21 296.05 296.06               -179.07
  ISp22 246.70 246.72               -179.07
                              check    status                          value
Corrections (notes/corrections.csv) CORRECTED IF1 × -1; IF2 × -1; ISp22 × 10
```

`apply` multiplies the channels in the recording object (`log` lists them: the `factor` of the line, the
`factor_total` of all lines and the `line` in the file); called again for the same recording, it multiplies nothing
a second time. Its hints – a line whose channel is not in the recording, a negative factor on RMS values – are in
`corr.hints`, which always refers to the last `apply` call; the measurement notebook prints them after applying the
corrections to the recording and again after applying them to the RMS file. The roles, main channels and probe
distances of the file are passed to `detect_roles`. Every applied factor then appears

* in the **hints** of the evaluation (“Correction applied: … × … (notes/corrections.csv, line …) – remark”),
* in the **plausibility table**, row `Corrections (notes/corrections.csv)` with the status `CORRECTED` and the total
  factor per channel,
* in the **result file** (`meta` → `corrections`: channel, factor, total factor, remark, file and line) and in the
  column `Corrections` of the [campaign overview](campaign.md#overview-and-consistency).

In the notebook, `APPLY_CORRECTIONS = False` shows the raw data without corrections for comparison; `ROLE_OVERRIDES`
and `MAIN_CHANNEL` fix roles and main channels for the current run only and take precedence over the file
([Notebooks](notebooks.md#settings-in-section-1)). Corrections that should last belong in the file.

## Python interface

| Function or method | Purpose |
|---|---|
| `corrections.load(folder_or_file)` | the corrections of a campaign: campaign folder, notes folder or the file itself; both layouts are searched; no file → empty `Corrections` |
| `corrections.path_for(campaign_folder, layout=None)` | path of the file for the detected or given layout |
| `corrections.write_template(campaign_folder, layout=None)` | create the file with header and explanation if the campaign has none (returns the path or `None`) |
| `corrections.template(layout=None)` | the content of a new file |
| `corrections.parse_factor(text)` | `"1/3"` → 0.333…, `"0,1"` → 0.1, `"−1"` → −1.0, `"x3"` → 3.0, `""` → 1.0 |
| `Corrections.table()` | all lines: `line`, `file`, `channel`, `factor`, `role`, `main_channel`, `distance_m`, `remark` |
| `Corrections.for_file(name)` | the lines that apply to a recording |
| `Corrections.apply(rec)` | apply the factors; returns the log (`channel`, `factor`, `factor_total`, `role`, `main_channel`, `distance_m`, `line`, `remark`) |
| `Corrections.log(rec)` | the log without applying anything |
| `Corrections.role_overrides(rec)` | `{channel name: role or None}` for `detect_roles` |
| `Corrections.main_channel(rec)` | `{role: channel name}` for `detect_roles` (`i_pen_feeders`/`i_pen_busbar` count as `i_pen`) |
| `Corrections.distances(rec)` | `{channel name: probe distance in m}` for `detect_roles` |
| `Corrections.hints` | hints of the last `apply` call, on the recording it was applied to (channel not found, sign of RMS values); replaced by every call, the other methods leave it unchanged |

`detect_roles(names, units, overrides, main_channel, distances)` accepts the channels by their full or short name, so
the same dictionaries can also be written by hand.
