# Campaigns, folders and files

groundfault organises staged earth-fault tests in **campaigns**: one folder per test day with the raw recordings,
the notes taken during the test and everything the evaluation writes. This page describes the folders and files, the
names the package relies on, and the three files you maintain by hand: the register, the sites file and the
corrections file.

## The work folder

The **work folder** contains the campaigns folder, the register of all recordings and – usually – the working copies
of the notebooks:

```text
<work folder>/
├─ register.csv                       one line per recording of all campaigns (rebuilt by tools/update_register.py)
├─ evaluate_measurement.ipynb         working copies of the notebooks (here or in a sub-folder)
├─ evaluate_campaign.ipynb
└─ campaigns/
   └─ 2026-01-15_Demo/                one campaign = one test day: <YYYY-MM-DD>_<place>
      ├─ README.md                    overview of the campaign (generated, do not edit)
      ├─ notes/
      │  ├─ notes.txt                 free notes on the test
      │  ├─ corrections.csv           corrections of the measuring chain (applied automatically)
      │  └─ sites.csv                 location, coordinates and asset type per site (for groundmeas)
      ├─ raw/
      │  ├─ PQ/                       export(s) of a power-quality measurement of the busbar (optional)
      │  ├─ SUB/                      substation: SUB_0_10_000kHz.cfg/.dat, SUB_2_5_10_000kHz.cfg/.dat, …
      │  └─ Station_Elm_Road/         secondary substation: …_10_000kHz.cfg (instantaneous values),
      │                               …_10_000Hz.cfg (RMS export of the recorder)
      ├─ results/
      │  ├─ <measurement>/            <measurement>_result.json and tables/
      │  └─ campaign/                 report tables of the campaign
      ├─ figures/
      │  ├─ <measurement>/            report figures and <measurement>_explorer.html
      │  └─ campaign/                 figures of the campaign
      ├─ report/                      the report (Word/PDF)
      └─ media/                       photos, audio and video of the test
```

The notebooks find the work folder themselves: it is the first folder, starting from the folder of the notebook and
going upwards, that contains a campaigns folder, and the name of that campaigns folder (`campaigns` or
`01_Messkampagnen`) gives the folder layout. Without a campaigns folder the folder of the notebook is the work folder
and the layout follows the notebook's `LANGUAGE` – other folders above it (`results`, `raw` …) play no part. Keep the
notebooks in the work folder or in a folder below it (`layout.find_work_folder` does the same in a script).

Who creates what:

* `notes/` with `notes.txt`, `corrections.csv` and `sites.csv`, the register and `README.md`:
  `tools/update_register.py` (see [below](#the-register)); each file only if it does not exist yet.
* `results/` and `figures/`: the export of the notebooks ([Reports and exports](report.md)).
* `raw/` (with one folder per site), `report/` and `media/`: you.

The German folder layout (`01_Messkampagnen/<Kampagne>/0_Notizen|1_Rohdaten|2_Auswertung|3_Abbildungen|4_Bericht|5_Medien`
with `Korrekturen.csv`, `Messorte.csv`, `Notizen_Messung.txt`, `Messregister.csv`, `LIESMICH.md` and result files
`<Messung>_ergebnis.json`) works the same way and is detected automatically; see
[Language and folder layout](language.md#folder-layouts).

The demo campaign has exactly this structure (without results and figures, which the evaluation writes):

```python
import os
import tempfile

from groundfault import demo

base = tempfile.mkdtemp()                           # work folder
d = demo.make_campaign(base, layout="en")
for folder, _, files in sorted(os.walk(base)):
    for f in sorted(files):
        if not f.endswith((".dat", "_truth.json")):
            print(os.path.relpath(os.path.join(folder, f), base))
```

```text
demo_groundmeas.db
register.csv
campaigns/2026-01-15_Demo/README.md
campaigns/2026-01-15_Demo/notes/corrections.csv
campaigns/2026-01-15_Demo/notes/notes.txt
campaigns/2026-01-15_Demo/notes/sites.csv
campaigns/2026-01-15_Demo/raw/PQ/SUB_PQ_export.csv
campaigns/2026-01-15_Demo/raw/SUB/SUB_0_10_000kHz.cfg
campaigns/2026-01-15_Demo/raw/SUB/SUB_2_5_10_000kHz.cfg
campaigns/2026-01-15_Demo/raw/SUB/SUB_5_10_000kHz.cfg
campaigns/2026-01-15_Demo/raw/Station_Elm_Road/Station_Elm_Road_10_000Hz.cfg
campaigns/2026-01-15_Demo/raw/Station_Elm_Road/Station_Elm_Road_10_000kHz.cfg
```

The demo writes only into its own campaign folder: `demo_groundmeas.db` and the register are created only if they do
not exist yet, the register only in a work folder without other campaigns (`d["register"]` is then its path,
otherwise `None` – add the demo to an existing register with `tools/update_register.py` if you want it there).
`demo_groundmeas.db` is the demo groundmeas database; a real database lies wherever groundmeas keeps it
([Earthing measurements](earthing.md#where-the-database-is)).

## Names groundfault relies on

### Campaign folder

`<YYYY-MM-DD>_<place>`, e.g. `2026-01-15_Demo`. The date and the place fill the columns `date` and `location` of the
register and the title of `README.md`. The date is also the reference of the clock check when a test is entered in
groundmeas: a recording whose start time (from the `.cfg` file) lies more than one day away from it is not entered
until the start time is given by hand ([Earthing measurements](earthing.md#time-stamp-and-recorder-clock)). The place
is used for the location name of the substation in the sites file (`Substation <place>`).

### Site folders

One folder per measuring site directly in `raw/`. The name decides the kind of site and the location searched in
groundmeas:

| Folder | Site | Asset type | Location searched in groundmeas |
|---|---|---|---|
| `SUB`, `SUB_…` (German `UW`, `UW_…`) | substation | `substation` | `Substation <place>` (German `UW <place>`) |
| `Station_<name>` (also `SSt…`, `Secondary…`) | secondary substation (MV/LV station) | `mv_lv_earthing_system` | `<name>` with blanks for underscores: `Station_Elm_Road` → “Elm Road” |
| other names | – | empty (enter it in the sites file) | the folder name |

The location search tolerates case, umlauts, small typing errors and words such as “Station” or “Substation”, so
“Elm Road” finds the groundmeas location “Station Elm Road”. Folders whose name starts with `PQ` (a power-quality
measurement, for example) are left out of the sites file. Recordings in a folder whose name contains `Trafo` or
`transformer` get no measurement number in the register. Sub-folders below a site folder (e.g.
`raw/SUB/RMS_10Hz/…`) belong to that site.

### File names

groundfault reads every `.cfg` file with its `.dat` file next to it; the recorder's names can be kept. Two things in
the name are used:

* **Additional impedance** (fault resistance) of a substation test: `SUB_2_5_10_000kHz.cfg` means 2.5 Ω. The
  sampling-rate suffix of the recorder (`_10_000kHz`, `_40_000kHz`, `_10_000Hz`) and a trailing `_measurement`
  (`_Messung`) are ignored; then the number at the end of the name counts. A decimal is written `<a>.<b>`,
  `<a>,<b>` or `<a>_<b>` with an integer part `a` of up to four digits (`SUB_7.5` → 7.5 Ω, `SUB_12,5` → 12.5 Ω,
  `SUB_2_5` → 2.5 Ω, `SUB_12_5` → 12.5 Ω). Otherwise an integer of up to four digits gives that value (`SUB_0` → 0 Ω,
  `SUB_3` → 3 Ω, `SUB_15` → 15 Ω), with one exception: `25` means 2.5 Ω, the shorthand of earlier campaigns. A name
  without such a number at its end (`Station_Elm_Road_10_000kHz`, a time stamp) gives no value. The value is
  written to the column `fault_resistance_Ohm` of the register, where you can correct it; groundfault uses it only as
  a fallback for the fault resistance of a groundmeas entry. In the evaluation itself you give the additional
  impedance explicitly (`Z_FAULT` in the notebook, `z_fault_ohm` in Python).
* **Instantaneous values or RMS values:** a recording counts as an RMS export (column `kind` of the register) if a
  channel name ends with ` RMS` or the sampling rate is below 1 kHz. Evaluate the instantaneous values
  (`…_10_000kHz.cfg`); the RMS export only serves as a check of the RMS values
  ([Notebooks](notebooks.md#section-6-optional-checks)). `evaluate` refuses recordings sampled below 20 × the rated frequency.

```python
from groundfault import register

for name in ("SUB_2_5_10_000kHz.cfg", "SUB_7.5_10_000kHz.cfg", "SUB_12,5_10_000kHz.cfg", "SUB_12_5_10_000kHz.cfg",
             "SUB_15_10_000kHz.cfg", "SUB_25_measurement_40_000kHz.cfg", "Station_Elm_Road_10_000kHz.cfg"):
    print(name, "→", register.resistance_from_name(name))
```

```text
SUB_2_5_10_000kHz.cfg → 2.5
SUB_7.5_10_000kHz.cfg → 7.5
SUB_12,5_10_000kHz.cfg → 12.5
SUB_12_5_10_000kHz.cfg → 12.5
SUB_15_10_000kHz.cfg → 15.0
SUB_25_measurement_40_000kHz.cfg → 2.5
Station_Elm_Road_10_000kHz.cfg → None
```

### Channel names

The **role** of a channel – line-to-earth voltage, fault current, coil current, probe … – is detected from its
name ([`channels`](../reference/channels.md)). Three naming schemes are recognised:

1. **Recorder export** `<device> <n>_<group>_<name> <kind>`, e.g. `DANEO 1_Ströme_IF1 Inst` or
   `REC 2_Currents_IF1 Inst`: the device prefix `<name> <number>_` (a name of letters, digits and hyphens, a blank
   and a number: `DANEO 1_`, `REC 2_`, `Recorder-A 3_`; also `DANEO_` and `DANEO1_`), a group (`System 1`, `Ströme`,
   `Spannungen`, `Currents`, `Voltages`) and the kind of values (`Inst`, `RMS`, `Raw`) are removed; the remaining
   **short name** (`IF1`) decides. A group such as `System 1` is not taken for a device prefix.
2. **Plain short names** such as `IF1`, `UE_70m`, `IPEN_v` – as in the table below.
3. **Structured names** `<quantity>_<voltage level>_<component>_…`, e.g. `i_20kv_res_j01_ct_m01_a__raw`: quantity
   `i` or `u`, voltage level in kV or V (`20kv`, `110kv`, `400v`; decimals as `0.4kv`, `0_4kv` or `0,4kv`),
   component `res` (fault current), `coil`, `l1`…`l3` (line currents), `n` (neutral or PEN current) for currents
   and `l1e`…`l3e`, `l12`, `l23`, `l31`, `ne` for voltages. The roles of the MV network go to the channels of the MV
   level of the recording: its only level, or – with channels of several levels – the levels from 1 kV to below
   60 kV (`channels.MV_MIN_KV`, `channels.HV_MIN_KV`). Channels of the other levels get the roles that exist for
   them – line-to-earth voltages from 60 kV on the HV roles `u_hv_l1e`…`u_hv_l3e`, a neutral current below 1 kV the
   role `i_pen` – and otherwise `u_gen` or `i_gen`. A recording whose channels all have one level is treated as the
   MV network, whatever the level. Structured names carry no probe distance and no PEN position; give them in the
   [corrections file](corrections.md), which also fixes any role.

Recognised short names (case does not matter):

| Role | Short names |
|---|---|
| `u_l1e`, `u_l2e`, `u_l3e` (MV) | `V1`, `U1`, `UL1`, `U_L1`, `U1E` … |
| `u_hv_l1e`, `u_hv_l2e`, `u_hv_l3e` (HV) | as above with `HS` at the end: `U1HS`, `V2HS` |
| `u_l12`, `u_l23`, `u_l31` | `V12`, `U23`, `UL31`, also in reverse order (`U21`) |
| `u_ne` | `UNE`, `UVE`, `U0`, `UNULL`, `UVerl…` |
| `u_t` | `UT`, `UT1`, `UT_…`, `UB…` |
| `u_e` | `UE`, `UEr`, `UEl` and probes with a distance: `UE_70m`, `UE70`, `UE100`, `U70m`, `U1m`, `UE1`, `UE_2,5m` |
| `i_res` | `IF`, `I_F`, `IF1`, `IF2`, `IFr500` (measuring range in the name), `IRES…`, `IREST…`, `IFEHLER…` |
| `i_coil` | `ISp…`, `I_Sp…`, `ESp…`, `ICOIL…`, `ISPULE…` |
| `i_l1`, `i_l2`, `i_l3` | `I1`, `IL1`, `I2` … |
| `i_shield` | `IS`, `ISchirm…`, `ISH…`, `I_SH…` |
| `i_pen` | `IPEN…`, `I_PEN…` |
| `u_gen`, `i_gen` | any other name, by the unit (V/kV or A/kA); other units: no role |

The meaning of every role code is listed on the [corrections page](corrections.md#role-codes).

**Probe distances** come from the name: `UE_70m`, `U70m`, `UE70`, `UE100` (in m, decimal comma allowed:
`UE_2,5m`). Probes without a distance in their name (`UE`, `UEr`, `UEl`) need the column `distance_m` of the
corrections file – the distance is used for the touch-voltage detection, the comparison with earthing measurements
and the groundmeas entry.

**Touch voltage:** a channel named `UT…`/`UB…` is the touch voltage. Without one, a probe at most 1.5 m away (`U1m`,
`UE1`) measures it; without such a probe the shortest probe up to 5 m serves as an approximation if there are at least
two probes with a known distance – the role table then says “automatic (shortest probe 5 m – approximation)”. Details
in [Stations and the LV network](station.md#probes-and-touch-voltage).

**PEN currents** are usually measured at two points; the position follows from the name:

| Position | Names | Meaning |
|---|---|---|
| `feeders` (`IPEN_v`) | `IPEN_v`, `IPENv`, `IPEN_vor`, `IPEN_feeders`, `IPEN_LV` | before the transformer star point: sum of the PEN conductors of all outgoing LV cables |
| `busbar` (`IPEN_n`) | `IPEN_n`, `IPEN_nach`, `IPEN_busbar`, `IPEN_MEB` | after the transformer star point: connection to the main earthing busbar |

Other PEN names (`IPEN`) have no position; the roles `i_pen_feeders`/`i_pen_busbar` in the corrections file set it.

**Main channel:** if several channels have the same role, the first one is the main channel used by the evaluation
(✓ in the role table). Fault-current channels are ordered `IF`/`I_F`, `IF1`, `IF2` …, then by decreasing measuring
range (`IFr500` before `IFr50`); probes by decreasing distance (the remote probe first). The column `main_channel` of
the corrections file chooses another one.

Example with invented channel names – note the shortest probe taken as touch voltage, the probe `UEr` without a
distance, the prefix of a second recorder, the HV voltage among the structured names and a channel that has no
role:

```python
from groundfault import detect_roles

names = ["DANEO 1_Spannungen_UE_70m Inst", "DANEO 1_Spannungen_UE_5m Inst", "DANEO 1_Spannungen_UEr Inst",
         "DANEO 1_Ströme_IF1 Inst", "DANEO 1_Ströme_IS Inst", "REC 2_Currents_IPEN_v Inst",
         "REC 2_Currents_IPEN_n Inst", "u_20kv_l1e_j01_vt_m01_v__raw", "u_110kv_l1e_j02_vt_m01_v__raw", "Temperature"]
units = ["V", "V", "V", "A", "A", "A", "A", "V", "V", "°C"]
roles = detect_roles(names, units)
print(roles.table()[["short", "role", "main_channel", "distance_m", "source"]].to_string(index=False))
print([(k.short, k.position) for k in roles.channels if k.role == "i_pen"])
print(roles.measurement_kind())
```

```text
                        short     role main_channel  distance_m                                         source
                       UE_70m      u_e            ✓        70.0                                      automatic
                        UE_5m      u_t            ✓         5.0 automatic (shortest probe 5 m – approximation)
                          UEr      u_e                      NaN                                      automatic
                          IF1    i_res            ✓         NaN                                      automatic
                           IS i_shield            ✓         NaN                                      automatic
                       IPEN_v    i_pen            ✓         NaN                                      automatic
                       IPEN_n    i_pen                      NaN                                      automatic
 u_20kv_l1e_j01_vt_m01_v__raw    u_l1e            ✓         NaN                                      automatic
u_110kv_l1e_j02_vt_m01_v__raw u_hv_l1e            ✓         NaN                                      automatic
                  Temperature        –                      NaN                                      automatic
[('IPEN_v', 'feeders'), ('IPEN_n', 'busbar')]
station
```

## The register

`register.csv` in the work folder lists every `.cfg` file of all campaigns – the overview of what was recorded and
what has been evaluated. It is built from the headers of the `.cfg` files:

| Column | Content |
|---|---|
| `campaign`, `date`, `location` | campaign folder, its date and its place |
| `site` | folder below `raw/` |
| `measurement_no` | chronological number of the fault events of the campaign (instantaneous-value recordings by start time; RMS exports and transformer folders get none) |
| `file`, `path` | file name and path relative to the work folder, with forward slashes on every operating system (`path` identifies the line) |
| `kind` | `instantaneous` or `RMS` |
| `measurement_kind` | `station`, `substation`, `transformer` (joined with `+`) or `undetermined`, from the channel roles |
| `fault_resistance_Ohm` | additional impedance from the file name – **maintained by hand** |
| `fault_location` | free text – **maintained by hand** |
| `fs_Hz`, `duration_s`, `start_cfg`, `trigger_s` | sampling rate, duration, start time and trigger time from the `.cfg` file |
| `analog_channels`, `digital_channels`, `channels` | number of channels and the short names |
| `steady_state_s`, `pre_fault_s`, `post_fault_s` | the analysis intervals chosen in the notebook (`2.6–4.4`) – written by the notebook, can be edited |
| `remark` | free text – **maintained by hand** |
| `status` | `ok`, the findings of the reader (e.g. a deviating sampling rate), `cfg date … ≠ campaign date …` or `error: …` |

Rebuild it after sorting in new recordings:

```bash
python tools/update_register.py /path/to/work_folder            # layout detected; --layout en|de to choose
python tools/update_register.py /path/to/work_folder --lang en  # messages in English for a German layout
```

The tool rebuilds the register, keeps the columns maintained by hand (`fault_resistance_Ohm`, `fault_location`,
`remark` and the three interval columns – also in a register written on another operating system), creates missing
notes folders with `notes.txt`, `corrections.csv` and `sites.csv` (the sites file pre-filled from groundmeas) and
rewrites `README.md` of every campaign. It prints the register path, the number of recordings, the files it created
and every recording whose status is not `ok` – in the language of the folder layout, or in the one given with
`--lang`. The same in Python:

```python
r = register.update_all(base)
print(os.path.basename(r["register"]), r["files"], r["hints"], r["actions"])

df, lang = register.read_register(r["register"])          # English column names and codes, either layout
print(df[["site", "measurement_no", "file", "kind", "measurement_kind", "fault_resistance_Ohm"]].to_string(index=False))
```

```text
register.csv 5 [] []
            site measurement_no                           file          kind measurement_kind fault_resistance_Ohm
             SUB              1            SUB_0_10_000kHz.cfg instantaneous       substation                    0
             SUB              2          SUB_2_5_10_000kHz.cfg instantaneous       substation                  2.5
             SUB              3            SUB_5_10_000kHz.cfg instantaneous       substation                    5
Station_Elm_Road                 Station_Elm_Road_10_000Hz.cfg           RMS          station                     
Station_Elm_Road              4 Station_Elm_Road_10_000kHz.cfg instantaneous          station                     
```

The measurement notebook records the intervals of every evaluated recording (`RECORD_INTERVALS = True`); in Python:

```python
ok = register.record_intervals(base, "campaigns/2026-01-15_Demo/raw/SUB/SUB_0_10_000kHz.cfg",
                               (2.6, 4.4), (0.2, 1.8), (7.0, 8.8))
df, _ = register.read_register(r["register"])
print(ok, df.loc[0, ["steady_state_s", "pre_fault_s", "post_fault_s"]].tolist())
```

```text
True ['2.6–4.4', '0.2–1.8', '7–8.8']
```

`record_intervals` returns `False` if the register or the line is missing; the notebook then rebuilds the register
once and tries again.

## The sites file

What cannot be taken from the recordings but is needed to enter a test in groundmeas is noted in `notes/sites.csv`,
one line per folder in `raw/` (semicolon-separated; edit it with a spreadsheet program or a text editor; lines
starting with `#` are comments):

| Column | Meaning |
|---|---|
| `site` | folder name in `raw/` |
| `location_groundmeas` | location name in groundmeas. If the name exists there (case and umlauts ignored), that location is used and **never changed**; otherwise a new location is created when the test is entered |
| `latitude`, `longitude` | WGS84 in degrees (decimal point or comma). **Required for a new location**; for an existing location only a cross-check (warning if more than 100 m away) |
| `asset_type` | groundmeas asset type: `substation`, `mv_lv_earthing_system` (secondary substation in a global earthing system), `overhead_line_tower`, `cable`, `cable_cabinet`, `house`, `pole_mounted_transformer`; empty → from the folder name |
| `voltage_level_kV` | network voltage, e.g. `20` |
| `distance_to_substation_m` | line length from the feeding substation to the site → `distance_to_current_injection_m` of the entered values; empty at the substation |
| `operator` | groundmeas operator |
| `remark` | free text; the pre-filled file notes where the values come from |

The file is created when it is missing – by `tools/update_register.py`, by the export cell of the notebooks and by
[`earthing.export_to_groundmeas`](earthing.md#entering-a-staged-fault-test) – and **pre-filled from groundmeas**
(read-only): the location is searched with the name derived from the folder; if it is found, its name, coordinates,
asset type, voltage level and operator are taken over, and the distance to the substation from earlier fault-test
entries of the same location. An existing file is never overwritten. The demo file after the pre-fill:

```python
from groundfault import sites

s = sites.load(d["campaign"])               # campaign folder, its notes folder or the file itself
print(s.table().drop(columns=["line", "operator"]).to_string(index=False))
```

```text
            site location_groundmeas  latitude  longitude            asset_type  voltage_level_kV  distance_to_substation_m                                            remark
             SUB     Substation Demo       NaN        NaN            substation              20.0                       NaN             new in groundmeas – enter coordinates
Station_Elm_Road    Station Elm Road      51.1       10.2 mv_lv_earthing_system              20.0                    2400.0 location 1 in groundmeas (folder name “Elm Road”)
```

The station was found in the demo database (location 1); the substation is new there and needs coordinates before
it can be entered. Reading the file raises a `ValueError` with file name and line for an unreadable number,
latitude without longitude, coordinates out of range, an unknown asset type or a site listed twice; coordinates that
look swapped (for Central Europe) only give a hint (`Sites.hints`). `sites.hints(sites.load(campaign), campaign)`
lists folders in `raw/` without a line, and `sites.suggest(campaign)` returns the pre-filled lines without writing a
file.

## Notes and read-me

`notes/notes.txt` takes everything noted during the test: set-up, instrument transformers and clamps, switching
state, particularities. It is free text and not evaluated. **Corrections that the evaluation shall apply** – a wrong
CT ratio, a clamp around one of several parallel conductors, a reversed polarity, a channel not to be evaluated, a
probe distance – must go into [`notes/corrections.csv`](corrections.md); only those are applied.

`README.md` in the campaign folder is generated by `tools/update_register.py` (`register.update_all`): a table of the
recordings, the active corrections, the sites and – if `notes.txt` contains more than the template text – the notes,
followed by a description of the folders. It is rewritten every time; edit `notes.txt` and the CSV files instead.
