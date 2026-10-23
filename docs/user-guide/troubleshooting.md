# Troubleshooting

The messages below are quoted as groundfault prints them in English (German output: the same messages in German);
“…” stands for the values filled in. Messages that name a campaign file or one of its columns use the names of the
campaign's folder layout – `sites.csv` and `latitude/longitude` here, `Messorte.csv` and `Breite/Laenge` in the German
layout. Hints of the evaluation start with ⚠ in the notebook and are also in `res.hints`.

## Installation and notebooks

| Message or observation | Cause | Remedy |
|---|---|---|
| `error: externally-managed-environment` at `pip install` | the system Python (or one of a package manager) does not allow installing packages | install into a virtual environment ([Installation](../getting-started/installation.md)) |
| `ModuleNotFoundError: No module named 'groundfault'` in the notebook | the notebook runs in a kernel without groundfault, and no clone was found in the folders above the notebook | choose the kernel of the environment in which groundfault is installed ([Notebooks](notebooks.md#setting-up)) |
| The signal explorer shows only the overview: “ipywidgets is missing (pip install "groundfault[interactive]") – only the overview is shown.” | `ipywidgets` is missing, or JupyterLab was not restarted after installing it | install the extra `notebook` (or `interactive`), restart JupyterLab |
| “plotly is not installed: pip install "groundfault[interactive]"” | interactive figures need Plotly | install the extra `notebook` (or `interactive`) |
| “tables.xlsx not written: openpyxl is not installed (pip install "groundfault[export]").” (likewise `tables.docx` and python-docx), or an `ImportError` “The XLSX export needs openpyxl …” | the Excel workbook needs `openpyxl`, the Word file `python-docx` | install the extra `export` (it brings both) |
| Interactive figures stay empty in VS Code | outdated Jupyter extension | update VS Code and its Jupyter extension, or use JupyterLab |
| `FileNotFoundError: [Errno 2] No such file or directory: '…/campaigns/…/raw/….cfg'` | `CAMPAIGN` or `FILE` misspelt, or the notebook is not in the work folder or below it | compare with the line “work folder: …” of the first cell; move the notebook into the work folder ([Notebooks](notebooks.md#setting-up)) |
| The first cell shows another layout than expected (e.g. `layout: en` for a German notebook), and the demo stops with a `FileNotFoundError` for `…/campaigns/…/1_Rohdaten/…` | the work folder is the first folder upwards from the notebook with a campaigns folder, and that folder's name decides the layout: here a folder above the notebook contains `campaigns` (a new folder without any campaigns folder gets the layout of `LANGUAGE`) | keep the notebook in its own work folder, or create the campaigns folder of the wanted layout (`01_Messkampagnen` or `campaigns`) in the folder of the notebook ([Campaigns, folders and files](campaigns.md#the-work-folder)) |
| “➜ First enter `STEADY_STATE` (and `PRE_FAULT`/`POST_FAULT`) in section 1 and run again.” | not an error: the intervals are not set yet | read them off the RMS trend ([Evaluating a recording](evaluation.md#choosing-the-analysis-intervals)) |

## Reading the recording

| Message | Cause | Remedy |
|---|---|---|
| “Sampling rate 10.0 Hz is too low for a harmonic analysis – evaluate RMS recordings with `rms.evaluate_rms_recording`.” | the RMS export was chosen instead of the instantaneous values | set `FILE` to the instantaneous-value file (`…_10_000kHz.cfg`); use the RMS export only as `RMS_FILE` for the check in section 6 |
| `Interval steady_state=(…) is not within 0 … … s or t0 ≥ t1.` | an interval outside the recording, or start and end swapped | correct the interval |
| `Interval 'steady_state' is shorter than one window (200 ms).` | interval too short | at least 200 ms, better 0.6 s or more (≥ 3 windows) |
| Diagnosis: `Subsystems not synchronous – suggestion: alignment = {…}` and “Voltage and current channels show the fault inception at different times (… s ↔ … s). Try a new export first, otherwise set alignment.” | voltage and current channels were exported with a time offset between recorder subsystems | export the file again from the recorder software; if that does not help, set `ALIGNMENT` to the suggestion ([Evaluating a recording](evaluation.md#raw-data-diagnostics)) |
| “Time stamps with … jumps/backward steps – check the time base.”, “Sampling rate from the timestamps (… Hz) deviates by … % from the .cfg (… Hz) – check the time base (diagnosis).” | defective time base of the export | export again; otherwise enforce the sampling rate with `FS_OVERRIDE` |
| “DAT size is not a multiple of the record length (… B left over) – file possibly truncated.”, “CFG states … samples, DAT contains ….” | incomplete copy or export | copy or export the file again |
| “No .dat file found next to ….” | the `.dat` file is missing or named differently | put the `.dat` file next to the `.cfg` file with the same name |
| “Channel … (…) is flat – do not use it as a reference.” | the channel carries no signal | ignore it in the corrections file if it has a role |
| `Main channel '…' for role … not among [...]` | `MAIN_CHANNEL` or the corrections file names a channel that does not have this role | correct the channel name or its role |
| `corrections.csv, line …: …` (unknown role, unreadable factor, factor 0, probe distance) | an invalid line in the corrections file | correct the line ([Corrections](corrections.md#the-file)) |
| “corrections.csv line …: channel '…' not in ….cfg – check the spelling.” | the channel of a correction does not occur in this recording | correct the channel name or narrow the file pattern |

## Hints of the evaluation

| Hint | Cause | Remedy |
|---|---|---|
| “Iw was negative → current measurement reversed; current phasors rotated by 180° (magnitudes unchanged).” | fault-current clamp connected the wrong way round | nothing to do; to document it, add `-1` for the clamp to the corrections file |
| “Polarity decision uncertain: active component only … % of I_H1 (margin …° to the ±90° limit) – …” | the active component is so small that an angle error of the measuring chain could reverse its sign | check the polarity of the clamp; if it is known for sure and the rotation is wrong, set `correct_polarity=False` |
| “The fundamental component of the fault current varies by … % in the steady-state interval – …; the max window is at … s.” | an active residual current increase, a coil adjustment or network switching in the interval | choose a narrower steady-state interval |
| “Low-frequency component (decaying DC component/drift) of … A in the max window at … s increases I_RES by … % …” | the DC component of the fault inception has not decayed, or a clamp drifts | start the steady-state interval later, or use the high-pass `Settings(dc="highpass")` |
| “Coil current balance: … – enter a correction in … if necessary.” | Iv does not change by the same amount as the measured coil currents | a coil channel with a wrong ratio, or not all adjusted coils measured – correction in the corrections file |
| “f1 in interval '…' implausible (…) – using … Hz.” | no usable reference voltage in the interval | check the voltage channels and their roles |
| “Scaling of the harmonic content not possible: no voltage measurement in the pre-/post-fault interval.” | `u_thd95_percent` set without the line-to-earth voltages or without a pre-/post-fault interval | set `PRE_FAULT`/`POST_FAULT` |
| “Sampling rate … Hz limits the harmonics to order ≤ ….” | low sampling rate | information only |
| “Correction applied: … × … (notes/corrections.csv, line …) – …” | a correction of the corrections file | information only |

## Station

| Hint | Cause | Remedy |
|---|---|---|
| “Station: background before the fault up to … % of the earth potential rise/touch voltage during the fault (50 Hz) – …” | a voltage at the earthing already before the fault | use the fault-related component for comparisons (done automatically) |
| “Station: uncertain values – … Hz (…). The superposition methods contradict each other there, or the background is large …” | the methods disagree, or the background is large compared with the fault-related component and fluctuates; “mainly frequency reference without voltage measurement”: without line voltages the phase reference during the fault is uncertain | look at `method_spread_pct` and `uncertainty_pct`; do not use these frequencies (⊗) for reduction factors or comparisons; record the line-to-earth voltages in future tests ([Stations](station.md#uncertainty-and-the-mark)) |
| “Station (fault inception): network frequency before the fault not estimable (…) – frequency during the fault assumed; irrelevant if the background is small.” | no distinct network-synchronous background and no voltage measurement | uncritical as long as the background is small |
| “Station: fault-related component not determinable (…) – direct values only.” | fault too short (at least 0.4 s of windows per side), inception and clearance not recorded, no voltage measurement | use the direct values; record longer in future tests |
| “Station: only one superposition method available (…) – no mutual check, spread not determinable.” | the fault starts before or ends after the recording | result without mutual check – look at the background in the signal explorer |
| “Angle U_E/I_F (…, 50 Hz) = …° – atypical for an earthing impedance (expected ≈ −30…+60°): …” | probe or clamp reversed, probe connected wrongly | compare the angles H1 of the probes in the [signal explorer](explorer.md); if needed `-1` in the corrections file |
| “Touch voltage from the shortest probe … (… m) – approximation, not a 1-m measurement.” | no probe at 1 m | the value is an upper estimate of the touch voltage |
| “Shield current … in phase opposition to the fault current → polarity reversed.” | shield-current clamp reversed | information; the evaluation rotates it |
| “LV network: the fault-related PEN currents before (…) and after the transformer star point (…) differ by … % at 50 Hz – more than their uncertainties explain …” | clamp, ratio or position wrong, or a load change during the fault | check the clamps and ratios, and the position (`i_pen_feeders`/`i_pen_busbar`) in the corrections file |
| “LV network: current into the LV network larger than the earth current (…) at … Hz – …” | PEN or shield clamp scaled wrongly, or a clamp encloses more than the PEN conductors | check the clamps and ratios ([Stations](station.md#pen-currents-and-the-lv-network)) |
| “LV network: several PEN channels with position … (…) – using ….” | two channels with the same position | give the other one a role or `ignore` in the corrections file |

## groundmeas

| Message | Cause | Remedy |
|---|---|---|
| “groundmeas database not available: groundmeas database not found: None (GROUNDMEAS_DB or ~/.config/groundmeas/config.json)” | the path of the database is not known | set `GROUNDMEAS_DB` in section 1, the environment variable `GROUNDMEAS_DB` or the groundmeas configuration ([Earthing measurements](earthing.md#where-the-database-is)) |
| “… is not a groundmeas database (missing tables: …)” | another SQLite file | check the path |
| “No matching location for “…” – set GROUNDMEAS_LOCATION = "…" to the name in the database.”, “Several locations match “…” about equally well (…) – set …”, “No matching values in groundmeas for “…” – check the location/ids in section 1.” | the location was not found (uniquely), or it has no measurement | enter the name from groundmeas in the sites file (column `location_groundmeas`), or set `GROUNDMEAS_LOCATION`/`GROUNDMEAS_MEASUREMENTS`; in the campaign notebook the field `location` of `MEASUREMENTS` |
| status “not possible: new location “…” without coordinates (enter latitude/longitude in notes/sites.csv)” | the location is not in groundmeas yet | enter `latitude`/`longitude` in the sites file – or, if the location exists under another name (warning “… is new in groundmeas – similar names there: …”), enter that name |
| status “already entered (measurement …)” | the recording is in groundmeas already | nothing to do; after a changed evaluation `GROUNDMEAS_EXPORT = "replace"` |
| status “not possible: Start of the recording according to the cfg (…) is … days away from the campaign date … – recorder clock set wrongly? …” | recorder clock set wrongly | give the start of the recording in UTC: `GROUNDMEAS_TIMESTAMP = "YYYY-MM-DD hh:mm:ss"`, in the campaign notebook the field `timestamp` of `MEASUREMENTS` ([Earthing measurements](earthing.md#time-stamp-and-recorder-clock)) |
| status “not possible: measurement … with the same timestamp was not made by this tool – it is not replaced” | an entry of other origin with the same time stamp | groundfault does not change it; decide in groundmeas |
| “Coordinates from sites.csv are … m away from the groundmeas location “…” …” | typing error, or another location of the same name | check the coordinates; the entry goes to the existing location, which is not changed |
| “…: latitude … / longitude … – swapped? (Central Europe: latitude ≈ 45…56, longitude ≈ 5…16)” | latitude and longitude swapped in the sites file | swap the columns |
| probe “distance unknown” in an entry, `distance_match` `unknown`, hint “Probe distance unknown for … – measurement_distance_m stays empty; …” | the probe distance is neither in the channel name nor in the corrections file | add it (column `distance_m`) and evaluate again |
| Reduction-factor and LV-network hints | see [Earthing measurements](earthing.md#hints) | |

## Campaign evaluation

| Message | Cause | Remedy |
|---|---|---|
| “⚠ missing: …/results/…/…_result.json → evaluate it with evaluate_measurement.ipynb first” | the measurement is not evaluated yet, or `measurement` in `MEASUREMENTS` differs from the folder in `results/` | evaluate it, or correct the name |
| “The equivalent-source method needs at least two substation measurements with different additional impedances.” | fewer than two measurements with an additional impedance `Z` | enter `Z` of the substation measurements in `MEASUREMENTS` (stations: `None`) |
| `ValueError: The additional impedances must differ (Z1 ≠ Z2).` | all substation measurements with the same additional impedance | check `Z` – at least two different additional impedances are needed |
| `ValueError: …: roles missing in the export: [...]` | a result file without fault current or line-to-earth voltages in the series | only substation tests with voltage measurement belong to the series |
| `ValueError: The THD scaling needs the THD of the measurement series (thd_measured_percent).` | `thd95_percent` without the THD of the series | give `thd_measured_percent` ([Campaign evaluation](campaign.md#scaling-to-a-power-quality-measurement)) |
| “Scaling per order not possible for [...] (…): unscaled (factor 1) – specify thd95_percent as well if needed” | orders without a value in `U95`, or zero-sequence orders with line-to-line values | add the missing values, or give `THD95_PERCENT` as well (Python: `thd95_percent` with `thd_measured_percent`) – these orders then get the flat THD factor |
| Consistency: “Coil current … in …” with “deviates by … % – factor ≈ 10: check the measuring range/CT ratio” | wrong measuring range or CT ratio in one test | add a factor to the corrections file and evaluate that test again ([Corrections](corrections.md)) |
| Consistency: “I_G equal in all measurements” with `WARNING` | network state or detuning changed between the tests | check the test log; the equivalent-source method uses the largest I_G by default |
