# -*- coding: utf-8 -*-
"""groundfault – evaluation of staged earth-fault tests in compensated (resonant-earthed) medium-voltage networks.

The package reads COMTRADE recordings of staged earth-fault tests and computes the residual earth-fault current and
its harmonic content, voltages and symmetrical components, the earth potential rise and touch voltage at secondary
substations (direct and fault-related, by superposition), the current into the LV network and the reduction factor
compared with earthing measurements. All algorithms live in the package; Jupyter notebooks are only a user
interface. User-facing output (hints, tables, figures, exported files) is available in English and German
([`groundfault.i18n`][groundfault.i18n]).

Modules
-------
comtrade           read and write COMTRADE files (IEEE C37.111 1991/1999/2013, memory-mapped, large files)
channels           channel roles (line-to-earth voltages, fault current, coil currents, station, transformer)
corrections        corrections per campaign (instrument-transformer ratio, polarity, roles, probe distance)
sites              sites per campaign (location, coordinates, asset type for groundmeas)
units              units of groundmeas values with the same rules as groundmeas ≥ 1.6.1 (mΩ, µV, kΩm …)
dsp                signal processing (windows, DC removal, Hann window, RMS, DFT/Goertzel, f1 estimation)
symmetrical        symmetrical components, line-to-line quantities, common angle reference
formulas           closed-form formulas (residual current, √2 method, angle method, measurement uncertainty,
                   harmonics, resistive approach, limits, line parameters)
evaluation         evaluation of one recording (assessment quantities, voltages, station, transformer)
disturbances       disturbed states during the fault (active residual current increase, network change) – not
                   the reference of the assessment
station            station per frequency: earth potential rise and touch voltage, direct and fault-related
                   (superposition), PEN and shield currents, current into the LV network and Z_E of the LV network
transformer        transformer node: power, apparent and upstream impedance (transformer + HV network) per order and
                   sequence before, during and after the fault
earthing           groundmeas: read earthing measurements, compare them with the staged fault test (reduction
                   factor, LV network in parallel) and enter the fault test
rms                evaluation of RMS recordings (trend, resonance curve, comparison with the device RMS values)
pq                 power-quality measurements of the busbar voltage: exports of PQ instruments, 10-min values,
                   quantiles per order and of the THD, factor by duration, scaling of the harmonic content
campaign           overview and consistency check of a measurement campaign, resistive approach
equivalent_source  equivalent-source method (active two-terminal equivalent per harmonic order)
diagnostics        raw-data diagnostics (.dat structure, time base, active channels, time offset)
report             figures and tables for an A4 report (no titles, uniform font)
interactive        interactive Plotly figures for the notebook
explorer           signal explorer: all channels with RMS values and harmonics on hover (notebook and HTML file)
register           measurement register and folder overview of a campaign
layout             folder layout of a campaign (English or German folder and file names)
i18n               output language (English/German): messages, column names, number format
legacy             reading result and campaign files of the predecessor tool (German keys)
demo               synthetic recordings with known solution (tests, training)

Optional part (not loaded by ``import groundfault``)
----------------------------------------------------
forecast           forecast of the harmonic residual current: a learnable network model of the earth-fault loop
                   per harmonic order – calibration with staged fault tests, update with recorded earth faults,
                   checks, faults behind a line – built on the result files of the evaluation
                   (``from groundfault import forecast``)
"""
__version__ = "3.5.0"
"""Version of the package."""

from .comtrade import Recording, ComtradeError, open_recording, write_comtrade  # noqa: E402
from .channels import RoleAssignment, detect_roles  # noqa: E402
from .evaluation import Intervals, Settings, Result, ResultFile, load_result, evaluate  # noqa: E402
from . import dsp, formulas, symmetrical  # noqa: E402

__all__ = ["__version__", "Recording", "ComtradeError", "open_recording", "write_comtrade",
           "RoleAssignment", "detect_roles", "Intervals", "Settings", "Result", "ResultFile",
           "load_result", "evaluate",
           "dsp", "formulas", "symmetrical"]
