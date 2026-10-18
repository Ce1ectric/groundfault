# -*- coding: utf-8 -*-
"""Input of the network model: the busbar phasors of one earth fault.

An earth fault enters the model as [`FaultData`][groundfault.forecast.data.FaultData] – read from a result file of the
single evaluation ([`load_fault_data`][groundfault.forecast.data.load_fault_data]), taken from the equivalent-source
method ([`fault_data_from_measurement`][groundfault.forecast.data.fault_data_from_measurement]) or built from measured
values of another tool ([`fault_data_from_values`][groundfault.forecast.data.fault_data_from_values]). All phasors refer
to the fundamental of U_L1-L2 and follow the orientation of the angle method (the active part of the fault current is
in phase with the displacement voltage).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from ..equivalent_source import SourceMeasurement, load_measurement, natural_sequence
from ..i18n import tr
from ..legacy import check_option, is_legacy_result, translate_result
from ._util import SEQ, finite, fnum
from .line import Line, as_line

__all__ = ["FaultData", "fault_data_from_measurement", "fault_data_from_values", "load_fault_data",
           "fault_current_from_result", "upstream_from_result", "measurement_name"]

_KINDS = ("test", "fault")
_A = np.exp(2j * np.pi / 3)


@dataclass
class FaultData:
    """Busbar phasors of one earth fault – the input of the network model.

    Attributes
    ----------
    name : str
        Name (unique within a model).
    kind : {"test", "fault"}
        ``"test"``: staged fault test with the fault current measured (calibration); ``"fault"``: recorded earth fault
        with busbar voltages only (update).
    U_pre, U_fault : dict
        Sequence voltages per order before and during the fault, ``{order: {"zero"|"pos"|"neg": phasor}}``.
    faulted_phase : str
        ``"L1"``, ``"L2"``, ``"L3"`` or ``""`` (unknown).
    I : dict of int to complex
        Fault current per order (tests).
    Z_F : complex, optional
        Additional impedance (fault resistance) of a test in Ω.
    time : str
        Start time of the recording.
    Iw, Iv : float
        Active residual current and detuning (Iv > 0 overcompensated) in A.
    I_C : float
        Capacitive earth-fault current in A (coil currents − I_v, or given).
    U0 : float
        Displacement voltage (fundamental) during the fault in V.
    IH_sum : float
        Harmonic content of the fault current (orders 2…40) in A.
    file : str
        Result file.
    meta : dict
        Free metadata (load, PV infeed, switching state …).
    hints : list of str
        Hints from loading.
    Z_up : dict of int to complex
        Upstream impedance of transformer and HV network per order from the transformer node of the same recording
        (empty without transformer currents).
    I_coil : dict of int to complex
        Change of the summed coil currents per order (during minus before the fault), each coil oriented so that its
        current lags the displacement voltage at 50 Hz (empty without coil currents; the currents during the fault for
        result files without the coil currents before the fault).
    dU0_coil : dict of int to complex
        Change of the zero-sequence voltage over the same windows as ``I_coil`` (node rule).
    line : Line, optional
        Line between the busbar and the fault location (a test in the network).
    """

    name: str
    kind: str
    U_pre: Dict[int, Dict[str, complex]]
    U_fault: Dict[int, Dict[str, complex]]
    faulted_phase: str = ""
    I: Dict[int, complex] = field(default_factory=dict)
    Z_F: Optional[complex] = None
    time: str = ""
    Iw: float = float("nan")
    Iv: float = float("nan")
    I_C: float = float("nan")
    U0: float = float("nan")
    IH_sum: float = float("nan")
    file: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)
    hints: List[str] = field(default_factory=list)
    Z_up: Dict[int, complex] = field(default_factory=dict)
    I_coil: Dict[int, complex] = field(default_factory=dict)
    dU0_coil: Dict[int, complex] = field(default_factory=dict)
    line: Optional[Line] = None


def fault_data_from_measurement(m: SourceMeasurement, kind: Optional[str] = None, I_C: Optional[float] = None,
                                Iv: Optional[float] = None, meta: Optional[Mapping[str, Any]] = None
                                ) -> FaultData:
    """Fault data from a measurement of the equivalent-source method.

    Parameters
    ----------
    m : SourceMeasurement
        Measurement read with [`load_measurement`][groundfault.equivalent_source.load_measurement].
    kind : {"test", "fault"}, optional
        Default ``"test"`` (the measurement contains the fault current); ``"fault"`` uses the busbar voltages only.
    I_C : float, optional
        Capacitive earth-fault current in A.
    Iv : float, optional
        Detuning current in A.
    meta : mapping, optional
        Free metadata.

    Returns
    -------
    FaultData
    """
    kind = kind or "test"
    check_option("kind", kind, _KINDS)
    U0 = abs(m.U_fault[1]["zero"]) if 1 in m.U_fault and "zero" in m.U_fault[1] else float("nan")
    return FaultData(name=m.name, kind=kind, U_pre=m.U_pre, U_fault=m.U_fault, faulted_phase=m.faulted_phase,
                     I=dict(m.I) if kind == "test" else {}, Z_F=complex(m.Z) if kind == "test" else None,
                     time=m.time, Iw=fnum(m.Iw), Iv=fnum(Iv), I_C=fnum(I_C), U0=float(U0),
                     IH_sum=fnum(m.IH_sum), file=m.file, meta=dict(meta or {}), hints=list(m.hints))


def _sequences(name: str, block: Mapping[int, Mapping[str, complex]]) -> Dict[int, Dict[str, complex]]:
    """Voltages per order as sequences – given as sequences or as phases L1, L2, L3 (Fortescue)."""
    out: Dict[int, Dict[str, complex]] = {}
    for m, v in block.items():
        keys = {str(k) for k in v}
        if keys <= set(SEQ):
            out[int(m)] = {s: complex(v[s]) for s in v}
        elif keys == {"L1", "L2", "L3"}:
            a, b, c = (complex(v[k]) for k in ("L1", "L2", "L3"))
            out[int(m)] = {"zero": (a + b + c) / 3, "pos": (a + _A * b + _A ** 2 * c) / 3,
                           "neg": (a + _A ** 2 * b + _A * c) / 3}
        else:
            raise ValueError(tr("forecast.values_sequences", name=name))
    return out


def fault_data_from_values(name: str, U_pre: Mapping[int, Mapping[str, complex]],
                           U_fault: Mapping[int, Mapping[str, complex]], *, I: Optional[Mapping[int, complex]] = None,
                           Z_F: Optional[complex] = None, faulted_phase: str = "",
                           I_coil: Optional[Mapping[int, complex]] = None, Iw: Optional[float] = None,
                           Iv: Optional[float] = None, I_C: Optional[float] = None, IH_sum: Optional[float] = None,
                           time: str = "", line: Any = None, meta: Optional[Mapping[str, Any]] = None) -> FaultData:
    """Fault data from measured values of another tool – phasors per order, referred to the fundamental of U_L1-L2.

    Parameters
    ----------
    name : str
        Name of the earth fault.
    U_pre, U_fault : mapping
        Busbar voltages per order before and during the fault: ``{order: {"zero": …, "pos": …, "neg": …}}`` or
        ``{order: {"L1": …, "L2": …, "L3": …}}`` (line-to-earth).
    I : mapping, optional
        Fault current per order in the orientation of the angle method – with ``Z_F`` a calibration test.
    Z_F : complex, optional
        Additional impedance of a test in Ω.
    faulted_phase : str, optional
        ``"L1"``, ``"L2"``, ``"L3"`` (default: unknown, the phase factors of L1).
    I_coil : mapping, optional
        Change of the summed coil currents per order, during minus before the fault (each coil lagging the
        displacement voltage at 50 Hz); the currents during the fault where the change is not known.
    Iw, Iv, I_C, IH_sum : float, optional
        Fundamental quantities and harmonic content of the fault current in A.
    time : str, optional
        Time of the earth fault.
    line : Line, mapping or list, optional
        Line between the busbar and the fault location.
    meta : mapping, optional
        Free metadata.

    Returns
    -------
    FaultData
        Kind ``"test"`` with a fault current and ``Z_F``, otherwise ``"fault"``.
    """
    Upre, Ufault = _sequences(name, U_pre), _sequences(name, U_fault)
    is_test = bool(I) and Z_F is not None
    U0 = abs(Ufault[1]["zero"]) if 1 in Ufault and "zero" in Ufault[1] else float("nan")
    Ic = {int(m): complex(v) for m, v in (I_coil or {}).items()}
    dU0 = {m: Ufault[m].get("zero", 0) - Upre.get(m, {}).get("zero", 0) for m in Ic if m in Ufault}
    return FaultData(name=name, kind="test" if is_test else "fault", U_pre=Upre, U_fault=Ufault,
                     faulted_phase=faulted_phase, I={int(m): complex(v) for m, v in (I or {}).items()},
                     Z_F=complex(Z_F) if Z_F is not None else None, time=str(time), Iw=fnum(Iw), Iv=fnum(Iv),
                     I_C=fnum(I_C), U0=float(U0), IH_sum=fnum(IH_sum), meta=dict(meta or {}), I_coil=Ic,
                     dU0_coil=dU0, line=as_line(line))


def _phasor_block(block: Mapping[str, Sequence], orders: Sequence[int]) -> Dict[int, Dict[str, complex]]:
    out: Dict[int, Dict[str, complex]] = {}
    for s in SEQ:
        key = "U_" + s
        if key not in block:
            continue
        for m, z in zip(orders, block[key]):
            out.setdefault(int(m), {})[s] = complex(z["re"], z["im"]) if isinstance(z, Mapping) else complex(z)
    return out


def _cplx(z) -> complex:
    return complex(z["re"], z["im"]) if isinstance(z, Mapping) else complex(z)


def _coil_currents(d: Mapping[str, Any], orders: Sequence[int], U_fault_block: Optional[Mapping[str, Sequence]],
                   U_pre: Mapping[int, Mapping[str, complex]]
                   ) -> Tuple[Dict[int, complex], Dict[int, complex], List[str]]:
    """Change of the coil currents of a result file: each coil oriented (lagging U_0 at 50 Hz), its current before the
    fault subtracted, summed per order – and the change of the zero-sequence voltage over the same windows.

    During the fault: the means over the reference windows (``voltage.coil_mean_phasor`` with ``fault_mean_phasor``,
    result files of groundfault ≥ 3.1), otherwise the phasors of the max window of ``signals``. Before the fault: the
    means over the pre-fault interval (``voltage.coil_pre_phasor``); without them the coil currents during the fault
    are used (the coil currents before the fault are small at the harmonic orders).
    """
    sp = d.get("voltage") or {}
    hints: List[str] = []
    per_coil: Dict[str, Dict[int, complex]] = {}
    U0_f: Dict[int, complex] = {}
    if sp.get("coil_mean_phasor") and U_fault_block is not None and "U_zero" in U_fault_block:
        for ch, vals in sp["coil_mean_phasor"].items():
            per_coil[ch] = {int(m): _cplx(z) for m, z in zip(orders, vals)}
        U0_f = {int(m): _cplx(z) for m, z in zip(orders, U_fault_block["U_zero"])}
    else:
        sig = d.get("signals") or {}
        coils = {k: s for k, s in sig.items() if s.get("role") == "i_coil"}
        le = [next((s for s in sig.values() if s.get("role") == r), None) for r in ("u_l1e", "u_l2e", "u_l3e")]
        if not coils or any(x is None for x in le):
            return {}, {}, hints

        def p(h):
            return h["mag_rms"] * np.exp(1j * np.deg2rad(h["ang_deg"]))
        phi = float(np.angle(p(le[0]["harmonics"]["H1"]) - p(le[1]["harmonics"]["H1"])))
        for m in orders:
            k = "H%d" % m
            if all(k in x["harmonics"] for x in le):
                U0_f[int(m)] = sum(p(x["harmonics"][k]) for x in le) / 3 * np.exp(-1j * m * phi)
        for ch, s in coils.items():
            per_coil[ch] = {int(m): p(s["harmonics"]["H%d" % m]) * np.exp(-1j * m * phi)
                            for m in orders if "H%d" % m in s["harmonics"]}
    if not per_coil or 1 not in U0_f or abs(U0_f[1]) == 0:
        return {}, {}, hints
    ords_sp = [int(o) for o in sp.get("orders", [])]
    pre = {ch: {m: _cplx(z) for m, z in zip(ords_sp, vals)} for ch, vals in (sp.get("coil_pre_phasor") or {}).items()}
    total: Dict[int, complex] = {}
    for ch, ph in per_coil.items():
        if 1 not in ph:
            continue
        sign = 1 if (ph[1] / U0_f[1]).imag < 0 else -1          # coil current lags U_0 by about 90°
        if sign < 0:
            hints.append(tr("forecast.coil_reversed", channel=ch))
        before = pre.get(ch, {})
        for m, z in ph.items():
            total[m] = total.get(m, 0j) + sign * (z - before.get(m, 0j))
    dU0 = {m: U0_f[m] - U_pre.get(m, {}).get("zero", 0j) for m in total if m in U0_f}
    return total, dU0, hints


def load_fault_data(path: str, Z: Optional[complex] = None, name: Optional[str] = None, *,
                    use_current: bool = True, I_C: Optional[float] = None, line: Any = None,
                    meta: Optional[Mapping[str, Any]] = None) -> FaultData:
    """Read the busbar phasors of an earth fault from a result file.

    A recording with fault current and a given additional impedance ``Z`` becomes a calibration test (phasors of the
    max window, as in the equivalent-source method). Without fault current, without ``Z`` or with
    ``use_current=False`` it becomes a recorded earth fault: busbar voltages only, during the fault the mean over the
    used windows of the steady state (result files of groundfault ≥ 3.1; older ones: the max window). A recording
    with the line currents of the transformer also gives the upstream impedance of its transformer node
    (``FaultData.Z_up``, significant orders); a recording with coil currents their oriented sum per order
    (``FaultData.I_coil`` – the node rule of [`add_fault`][groundfault.forecast.model.NetworkModel.add_fault]).

    Parameters
    ----------
    path : str
        Result file of the single evaluation.
    Z : complex, optional
        Additional impedance in Ω (tests).
    name : str, optional
        Name (default: the measurement – the file name without ``_result.json`` or ``_ergebnis.json``).
    use_current : bool, optional
        False: treat a test like a recorded earth fault (busbar voltages only).
    I_C : float, optional
        Capacitive earth-fault current in A; default: sum of the coil currents − I_v of the result file.
    line : Line, mapping or list, optional
        Line between the busbar and the fault location – for a test in the network.
    meta : mapping, optional
        Free metadata.

    Returns
    -------
    FaultData

    Raises
    ------
    ValueError
        Without busbar voltages before and during the fault.
    """
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if is_legacy_result(d):
        d = translate_result(d)
    name = name or measurement_name(path)
    values = d.get("values") or {}
    Z_up = _upstream_rows(((d.get("tables") or {}).get("transformer_impedance")) or [], True)
    coils = ((d.get("tables") or {}).get("coil_currents")) or []
    coil_sum = float(sum(fnum(c.get("H1_A")) for c in coils)) if coils else float("nan")
    Iv = fnum(values.get("Iv"))
    if I_C is None and np.isfinite(coil_sum) and np.isfinite(Iv):
        I_C = coil_sum - Iv
    sp = d.get("voltage") or {}
    orders_sp = [int(o) for o in sp.get("orders", [])]
    has_current = any((s or {}).get("role") == "i_res" for s in (d.get("signals") or {}).values())
    if has_current and use_current and Z is not None:
        m = load_measurement(path, complex(Z), name)
        fd = fault_data_from_measurement(m, "test", I_C=I_C, Iv=Iv, meta=meta)
        fd.file = os.path.basename(path)
        fd.Z_up = Z_up
        fd.line = as_line(line)
        # coil currents of the max window (the fault current is a max-window phasor, too)
        fd.I_coil, fd.dU0_coil, h = _coil_currents(d, sorted(m.I), None, m.U_pre)
        fd.hints.extend(h)
        return fd
    if "pre_fault_phasor" not in sp or not ("fault_mean_phasor" in sp or "fault_phasor" in sp):
        raise ValueError(tr("forecast.no_voltages", name=name))
    U_pre = _phasor_block(sp["pre_fault_phasor"], orders_sp)
    fault_block = sp.get("fault_mean_phasor") or sp["fault_phasor"]
    U_fault = _phasor_block(fault_block, orders_sp)
    phase = values.get("faulted_phase") or ""
    if not phase and 1 in orders_sp and "fault" in sp:
        i1 = orders_sp.index(1)
        mags = [sp["fault"].get(k, [float("nan")] * len(orders_sp))[i1] for k in ("U_L1E", "U_L2E", "U_L3E")]
        b = np.asarray(mags, float)
        if np.all(np.isfinite(b)) and b.max() > 0 and b.min() / b.max() < 0.3:
            phase = "L%d" % (int(np.argmin(b)) + 1)
    U0 = abs(U_fault[1]["zero"]) if 1 in U_fault and "zero" in U_fault[1] else float("nan")
    I_coil, dU0, hints = _coil_currents(d, orders_sp, sp.get("fault_mean_phasor"), U_pre)
    return FaultData(name=name, kind="fault", U_pre=U_pre, U_fault=U_fault, faulted_phase=phase,
                     time=str((d.get("meta") or {}).get("start_time", "")), Iw=fnum(values.get("Iw")), Iv=Iv,
                     I_C=fnum(I_C), U0=float(U0), IH_sum=fnum(values.get("IH_sum")), file=os.path.basename(path),
                     meta=dict(meta or {}), hints=hints, Z_up=Z_up, I_coil=I_coil, dU0_coil=dU0, line=as_line(line))


def fault_current_from_result(path: str) -> Tuple[Dict[int, complex], float]:
    """Fault current per order (magnitudes, max window of the main fault-current channel) and its harmonic content
    I_H,Σ from a result file – e.g. of a recording at a fault location in the network.

    Parameters
    ----------
    path : str
        Result file with a fault-current channel (role ``i_res``).

    Returns
    -------
    (dict of int to complex, float)
        ``{order: |I_m|}`` (real values) and I_H,Σ in A (NaN if not in the file).

    Raises
    ------
    ValueError
        Without a fault-current channel.
    """
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if is_legacy_result(d):
        d = translate_result(d)
    sig = d.get("signals") or {}
    cand = [(k, s) for k, s in sig.items() if s.get("role") == "i_res"]
    if not cand:
        raise ValueError(tr("forecast.verify_no_current", name=measurement_name(path)))
    main = ((d.get("measurement") or {}).get("main_channel") or {}).get("i_res")
    s = next((x for k, x in cand if k == main), cand[0][1])
    I = {int(k[1:]): complex(float(h["mag_rms"])) for k, h in s.get("harmonics", {}).items()}
    IH = fnum(((d.get("assessment_quantities") or {}).get("IH_sum") or {}).get("measured_value"))
    if not np.isfinite(IH):
        IH = fnum((d.get("values") or {}).get("IH_sum"))
    return I, IH


def measurement_name(path: str) -> str:
    """Name of the measurement of a result file: the file name without the result suffix of either layout."""
    from ..layout import LAYOUTS
    base = os.path.basename(path)
    for suffix in sorted({lay.result_suffix for lay in LAYOUTS.values()}, key=len, reverse=True):
        if base.endswith(suffix) and len(base) > len(suffix):
            return base[:-len(suffix)]
    return os.path.splitext(base)[0]


def upstream_from_result(result, significant_only: bool = True) -> Dict[int, complex]:
    """Upstream impedance Z_up per order from the transformer node of a result – from the sequence other than the
    natural one (m = 5, 11 …: positive, m = 7, 13 …: negative sequence).

    Z_up of the transformer and the HV network is the same in the positive and the negative sequence. The natural
    sequence carries the pre-fault harmonic of the network – ten to a hundred times the other sequence –, and its
    drift between the states enters ΔU and ΔI (angles above 90°, deviations of tens of percent); the other sequence
    changes almost only by the fault. An order without a significant value in that sequence gets no Z_up.

    Parameters
    ----------
    result : Result, ResultFile or str
        Evaluation of the transformer recording, or its result file.
    significant_only : bool, optional
        Only orders whose estimate is significant (uncertainty ≤ 20 %).

    Returns
    -------
    dict of int to complex
        ``{order: Z_up}`` in Ω.

    Raises
    ------
    ValueError
        If the result has no table ``transformer_impedance``.
    """
    if isinstance(result, str):
        from ..evaluation import load_result
        result = load_result(result)
    tab = getattr(result, "tables", {}).get("transformer_impedance")
    if tab is None or len(tab) == 0:
        raise ValueError(tr("forecast.transformer_table_missing", name=getattr(result, "name", "")))
    return _upstream_rows(tab.to_dict("records"), significant_only)


def _upstream_rows(rows: Sequence[Mapping[str, Any]], significant_only: bool) -> Dict[int, complex]:
    """Z_up per order (orders ≥ 2 not divisible by 3) from the rows of the table ``transformer_impedance``: the
    sequence other than the natural one."""
    out = {}
    for r in rows:
        try:
            m = int(r["order"])
            z = float(r["Z_up_Ohm"]) * np.exp(1j * np.radians(float(r["Z_up_angle_deg"])))
        except (KeyError, TypeError, ValueError):
            continue
        seq = r.get("sequence")
        if m < 2 or m % 3 == 0 or seq not in ("pos", "neg") or seq == natural_sequence(m) or not finite(z):
            continue
        if significant_only and not bool(r.get("significant", True)):
            continue
        out[m] = complex(z)
    return dict(sorted(out.items()))
