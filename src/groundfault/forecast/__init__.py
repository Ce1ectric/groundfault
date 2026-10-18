# -*- coding: utf-8 -*-
"""Forecast of the harmonic residual current – an optional part of groundfault.

The evaluation of a recording ([`groundfault.evaluation`][groundfault.evaluation]) and of a campaign does not need this
package, and ``import groundfault`` does not load it. It builds on their result files:

* [`NetworkModel`][groundfault.forecast.model.NetworkModel] – the network model of the earth-fault loop at a busbar per
  harmonic order: calibrated with staged fault tests (fault current measured), updated with every earth fault recorded
  at the busbar (busbar voltages, coil currents if recorded), checked between the tests and at recorded earth faults,
  and used to forecast the harmonic residual current I_H and the residual current I_RES from harmonic voltages – the
  95 % quantiles or a time series of a power-quality measurement – for a fault at the busbar or behind a line.
* [`FaultData`][groundfault.forecast.data.FaultData] and its readers – the busbar phasors of one earth fault from a
  result file, from the equivalent-source method or from measured values of another tool.
* [`Line`][groundfault.forecast.line.Line] – the line between the busbar and a fault location in the network.
* [`campaign_tests`][groundfault.forecast.campaigns.campaign_tests] and
  [`build_model`][groundfault.forecast.campaigns.build_model] – campaigns of a work folder as input.
* [`classical_bound`][groundfault.forecast.bounds.classical_bound] (V0),
  [`resonance_bound`][groundfault.forecast.bounds.resonance_bound] (V1),
  [`network_data_estimate`][groundfault.forecast.bounds.network_data_estimate] and
  [`network_data_envelope`][groundfault.forecast.bounds.network_data_envelope] (V2) and
  [`network_estimate`][groundfault.forecast.bounds.network_estimate] (V3) – estimates without an earth fault, the last
  with the MV network measured in undisturbed operation
  ([`mv_network_series`][groundfault.transformer.mv_network_series]); side by side with
  [`estimates_without_fault`][groundfault.forecast.bounds.estimates_without_fault]; the impedances from network data
  with [`groundfault.forecast.network_data`][groundfault.forecast.network_data].

The package contains no margins, limits or network data; you define them. Two notebooks run the sequences:
``forecast_without_fault`` (German ``Prognose_ohne_Erdschluss``) the estimates without an earth fault (V0 to V3) and
``network_model_forecast`` (German ``Netzmodell_Prognose``) the network model from staged tests and recorded earth
faults (V4 to V7); ``tools/make_notebooks.py --forecast`` writes both.

Examples
--------
>>> from groundfault import forecast as fc
>>> model, messages = fc.build_model("work", fc.campaign_tests("work", "2026-01-15_Demo"), name="Demo")  # doctest: +SKIP
>>> model.forecast({5: 250.0, 7: 130.0}, margin_A=2.0).table()                                        # doctest: +SKIP
"""
from __future__ import annotations

from . import _texts  # noqa: F401  (messages, German labels, report titles)
from .bounds import (classical_bound, estimates_without_fault, network_data_envelope, network_data_estimate,
                     network_estimate, resonance_bound)
from .campaigns import (ENTRY_KEYS, FOLDERS, add_entries, build_model, campaign_tests, check_data, forecast_folder,
                        result_path)
from .data import (FaultData, fault_current_from_result, fault_data_from_measurement, fault_data_from_values,
                   load_fault_data, measurement_name, upstream_from_result)
from .line import Line, LineSegment
from .model import MODEL_FORMAT, MODEL_VERSION, Calibration, Forecast, NetworkModel, OrderEstimate, SourceTerm
from .network_data import (at_order, earth_capacitance, hv_network_reactance, mv_network_from_data, resonance_order,
                           transformer_reactance)

__all__ = ["NetworkModel", "Calibration", "OrderEstimate", "SourceTerm", "Forecast", "MODEL_FORMAT", "MODEL_VERSION",
           "FaultData", "load_fault_data", "fault_data_from_measurement", "fault_data_from_values",
           "fault_current_from_result", "upstream_from_result", "measurement_name", "Line", "LineSegment",
           "campaign_tests", "result_path", "forecast_folder", "add_entries", "build_model", "check_data", "FOLDERS",
           "ENTRY_KEYS", "classical_bound", "resonance_bound", "network_data_estimate", "network_data_envelope",
           "network_estimate", "estimates_without_fault", "transformer_reactance", "hv_network_reactance", "at_order", "earth_capacitance",
           "mv_network_from_data", "resonance_order"]
