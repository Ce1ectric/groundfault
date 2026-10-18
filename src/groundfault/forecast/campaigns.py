# -*- coding: utf-8 -*-
"""Campaigns as input of the network model: the staged fault tests of a campaign from the register, the result files
of the single evaluation and a model built from them.

A network model belongs to a busbar, not to a campaign: the staged fault tests of one or more campaigns calibrate it,
later recordings of earth faults at the same busbar update it. The functions here find these recordings in a work
folder (register, campaigns, result files) and load them; the model itself does not depend on the folder layout.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .. import layout as _layout
from .. import register as _register
from ..i18n import tr
from ..legacy import check_keys, check_option
from .data import fault_current_from_result, load_fault_data, upstream_from_result
from .model import NetworkModel

__all__ = ["campaign_tests", "result_path", "forecast_folder", "add_entries", "build_model", "check_data", "FOLDERS",
           "ENTRY_KEYS"]

FOLDERS = {"en": "forecast", "de": "05_Prognose"}
"""Folder of the network models and forecasts in a work folder, by layout language."""
ENTRY_KEYS = ("campaign", "measurement", "Z", "name", "meta", "transformer", "line")
"""Keys of a test or earth-fault entry (``campaign`` and ``measurement`` are required, ``Z`` for tests)."""


def _float(v) -> Optional[float]:
    try:
        x = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return x


def campaign_tests(work_folder: str, campaign: str, layout: Any = None) -> List[Dict[str, Any]]:
    """Staged fault tests of a campaign from the register of the work folder.

    A test is an instantaneous-value recording of the kind ``substation`` (also ``substation+transformer``) with an
    additional impedance in the column ``fault_resistance_Ohm``. If the line currents of the transformer were
    recorded by a second recorder (kind ``transformer``) and every additional impedance occurs once among the tests and
    once among the transformer recordings, the transformer recording of the same impedance is named as
    ``transformer`` – its upstream impedance enters the model.

    Parameters
    ----------
    work_folder : str
        Work folder (with the register and the campaigns folder).
    campaign : str
        Name of the campaign folder.
    layout : str or CampaignLayout, optional
        Folder layout (default: detected).

    Returns
    -------
    list of dict
        ``dict(campaign, measurement, Z[, transformer])`` sorted by the additional impedance.

    Raises
    ------
    FileNotFoundError
        Without a register.
    ValueError
        For a campaign that is not in the register.
    """
    lay = _layout.get_layout(layout) if layout is not None else _layout.detect_layout(str(work_folder))
    path = _register.register_path(str(work_folder), lay)
    if not os.path.isfile(path):
        raise FileNotFoundError(tr("forecast.no_register", path=path))
    df, _ = _register.read_register(path)
    known = list(dict.fromkeys(df["campaign"]))
    if campaign not in known:
        raise ValueError(tr("forecast.unknown_campaign", campaign=campaign, campaigns=", ".join(known)))
    rows = df[(df["campaign"] == campaign) & (df["kind"].isin(["instantaneous", ""]))]
    tests, trafos = [], []
    for _, r in rows.iterrows():
        z = _float(r.get("fault_resistance_Ohm"))
        kind = str(r.get("measurement_kind", ""))
        meas = os.path.splitext(str(r["file"]))[0]
        if z is None:
            continue
        if "substation" in kind.split("+"):
            tests.append(dict(campaign=campaign, measurement=meas, Z=z))
        elif kind == "transformer":
            trafos.append((z, meas))
    zs = [t["Z"] for t in tests]
    for t in tests:
        same = [m for z, m in trafos if abs(z - t["Z"]) < 1e-9]
        if len(same) == 1 and zs.count(t["Z"]) == 1:
            t["transformer"] = same[0]
    return sorted(tests, key=lambda t: t["Z"])


def result_path(work_folder: str, campaign: str, measurement: str, layout: Any = None) -> str:
    """Result file of a measurement – also with the suffix of the other layout; the expected path if none exists."""
    lay = _layout.get_layout(layout) if layout is not None else _layout.detect_layout(str(work_folder))
    folder = os.path.join(str(work_folder), lay.campaigns, campaign)
    p = lay.result_path(folder, measurement)
    cands = [p] + [os.path.join(os.path.dirname(p), measurement + other.result_suffix)
                   for other in _layout.LAYOUTS.values()]
    return next((c for c in cands if os.path.exists(c)), p)


def forecast_folder(work_folder: str, network: str = "", layout: Any = None) -> str:
    """Folder of the network models and forecasts (``forecast`` or ``05_Prognose``), with the sub-folder of a
    network if ``network`` is given (name as in [`groundfault.report.slug`][groundfault.report.slug])."""
    from ..report import slug
    lay = _layout.get_layout(layout) if layout is not None else _layout.detect_layout(str(work_folder))
    base = os.path.join(str(work_folder), FOLDERS.get(lay.language, FOLDERS["en"]))
    return os.path.join(base, slug(network)) if network else base


def add_entries(model: NetworkModel, work_folder: str, entries: Iterable[Mapping[str, Any]], kind: str = "test", *,
                orders: Any = "auto", min_current_A: float = 0.3, two_source: Any = "zero_sequence",
                layout: Any = None) -> List[str]:
    """Add staged fault tests (``kind="test"``) or recorded earth faults (``kind="fault"``) of a work folder to a
    model – from the result files of the single evaluation.

    Parameters
    ----------
    model : NetworkModel
        The model.
    work_folder : str
        Work folder.
    entries : iterable of mapping
        ``dict(campaign=…, measurement=…)`` – tests with ``Z`` – and the optional keys ``name``, ``meta``,
        ``transformer`` (transformer recording of the same earth fault by a second recorder) and ``line`` (line to
        the fault location of a test in the network, see [`Line`][groundfault.forecast.line.Line]), e.g. from
        [`campaign_tests`][groundfault.forecast.campaigns.campaign_tests].
    kind : {"test", "fault"}, optional
        Calibration tests or recorded earth faults.
    orders, min_current_A
        See [`add_test`][groundfault.forecast.model.NetworkModel.add_test].
    two_source
        See [`add_fault`][groundfault.forecast.model.NetworkModel.add_fault].
    layout : str or CampaignLayout, optional
        Folder layout (default: detected).

    Returns
    -------
    list of str
        Messages: missing result files, hints of loading, upstream impedances.

    Raises
    ------
    ValueError
        For an unknown key in an entry or an unknown ``kind``.
    """
    check_option("kind", kind, ("test", "fault"))
    messages: List[str] = []
    for e in entries:
        check_keys("tests" if kind == "test" else "faults", e, ENTRY_KEYS)
        label = e.get("name") or e["measurement"]
        p = result_path(work_folder, e["campaign"], e["measurement"], layout)
        if not os.path.exists(p):
            messages.append(tr("forecast.result_missing", name=label, path=p))
            continue
        if kind == "fault" and not model.tests:
            messages.append(tr("forecast.no_reference"))
            break
        try:
            fd = load_fault_data(p, e.get("Z") if kind == "test" else None, label, meta=e.get("meta"),
                                 line=e.get("line"))
            c = model.add_test(fd, orders=orders, min_current_A=min_current_A) if kind == "test" else \
                model.add_fault(fd, two_source=two_source)
        except ValueError as ex:
            messages.append("%s: %s" % (label, ex))
            continue
        messages.extend("%s: %s" % (c.name, h) for h in c.hints)
        if e.get("transformer"):
            pt = result_path(work_folder, e["campaign"], e["transformer"], layout)
            try:
                model.add_upstream(c.name, upstream_from_result(pt))
                messages.append(tr("forecast.upstream_from", name=c.name, transformer=e["transformer"]))
            except (OSError, ValueError) as ex:
                messages.append("%s: %s" % (c.name, ex))
    return messages


def build_model(work_folder: str, tests: Sequence[Mapping[str, Any]], faults: Iterable[Mapping[str, Any]] = (),
                name: str = "", *, orders: Any = "auto", min_current_A: float = 0.3,
                two_source: Any = "zero_sequence", layout: Any = None) -> Tuple[NetworkModel, List[str]]:
    """Network model from the result files of staged fault tests and recorded earth faults of a work folder
    ([`add_entries`][groundfault.forecast.campaigns.add_entries] for both).

    Parameters
    ----------
    work_folder : str
        Work folder.
    tests : sequence of mapping
        Staged fault tests, e.g. from [`campaign_tests`][groundfault.forecast.campaigns.campaign_tests].
    faults : iterable of mapping, optional
        Recorded earth faults.
    name : str, optional
        Name of the model (network, busbar).
    orders, min_current_A, two_source, layout
        See [`add_entries`][groundfault.forecast.campaigns.add_entries].

    Returns
    -------
    (NetworkModel, list of str)
        The model and the messages.
    """
    model = NetworkModel(name)
    messages = add_entries(model, work_folder, tests, "test", orders=orders, min_current_A=min_current_A,
                           layout=layout)
    messages += add_entries(model, work_folder, faults, "fault", two_source=two_source, layout=layout)
    return model, messages


def check_data(work_folder: str, entry: Mapping[str, Any], layout: Any = None):
    """A measurement to check the model with ([`verify`][groundfault.forecast.model.NetworkModel.verify]) – e.g. a
    staged fault test at a location in the network: the busbar voltages of ``measurement`` (substation recording)
    and the fault current of ``current`` (recording at the fault location; default: the same recording).

    Parameters
    ----------
    work_folder : str
        Work folder.
    entry : mapping
        ``dict(campaign=…, measurement=…, Z=…)`` with the optional keys ``current``, ``line``, ``name``, ``meta``.
    layout : str or CampaignLayout, optional
        Folder layout (default: detected).

    Returns
    -------
    FaultData
        Busbar voltages, the fault current per order (magnitudes) and the line.

    Raises
    ------
    FileNotFoundError
        For a missing result file.
    """
    check_keys("checks", entry, ENTRY_KEYS + ("current",))
    label = entry.get("name") or entry["measurement"]
    p = result_path(work_folder, entry["campaign"], entry["measurement"], layout)
    if not os.path.exists(p):
        raise FileNotFoundError(tr("forecast.result_missing", name=label, path=p))
    fd = load_fault_data(p, None, label, use_current=False, meta=entry.get("meta"), line=entry.get("line"))
    pc = result_path(work_folder, entry["campaign"], entry.get("current") or entry["measurement"], layout)
    if not os.path.exists(pc):
        raise FileNotFoundError(tr("forecast.result_missing", name=entry.get("current"), path=pc))
    fd.I, fd.IH_sum = fault_current_from_result(pc)
    fd.Z_F = complex(entry["Z"]) if entry.get("Z") is not None else None
    return fd
