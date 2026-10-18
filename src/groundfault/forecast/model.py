# -*- coding: utf-8 -*-
"""Network model of the earth-fault loop per harmonic order – calibrated with staged fault tests, updated with
recorded earth faults and used to forecast the harmonic residual current from harmonic voltages.

Model (fault at the MV busbar or behind a line, per harmonic order m, Thevenin equivalent at the fault location):

    I_F,m = (U_q,m + U_s,m)/(Z_q,m + Z_qL,m + Z_F),   Z_q = (Z_0 + Z_1 + Z_2)/3,   Z_qL = (2·Z_1L + Z_0L)/3

* **U_q,m** – pre-fault voltage of the faulted phase (orientation of the angle method, U_q = −Σ p_s·U_pre,s with the
  phase factor p_s of the faulted phase). It follows the harmonic voltage of the network and is taken from a
  power-quality measurement for a forecast.
* **U_s,m** – a source that only exists during the fault: Petersen coils, earthing transformers and voltage
  transformers at the full displacement voltage saturate and add harmonic currents in the zero sequence. It matters at
  the orders of the zero sequence (3, 9, 15 …), where the pre-fault voltage is small.
* **Z_s,m** – sequence impedances at the busbar; **Z_qL,m** – the line to a fault location in the network
  ([`Line`][groundfault.forecast.line.Line]).

Calibration with a staged fault test (fault current measured, busbar voltages before and during the fault):

    Z_s,m = 3·p_s·ΔU_s,m/I_m     (s = zero, pos, neg; ΔU = U_fault − U_pre)

Update with a recorded earth fault (busbar voltages only, Z_0 from the calibration):

    Z_s,m = Z_0,m·p_s·ΔU_s,m/ΔU_0,m,   |I_F,m| = 3·|ΔU_0,m|/|Z_0,m|

With the coil currents of the recording the fault current follows from the node rule of the zero sequence,

    I_F,m = 3·Y_0,net,m·ΔU_0,m + ΔI_coil,m,   Y_0,net,m = (I_m − ΔI_coil,m)/(3·ΔU_0,m) from the tests,

with the change ΔI_coil of the coil currents (during minus before the fault), which holds also at the orders with a
source that arises in the fault (the coils are measured, not modelled).

Source that arises in the fault (two or more tests i with different series impedances Z_i = Z_F,i + Z_qL,i, linear
least squares):

    I_i·Z_q − U_s = U_q,i − I_i·Z_i

Upstream split with the transformer node (upstream impedance Z_up of transformer and HV network):

    Z_down,s = 1/(1/Z_s − 1/Z_up)   (s = pos, neg) – the MV network with its damping

Forecast from the harmonic voltage U_m (line-to-earth, e.g. 95 % quantile or a time series): per order

    |I_F,m| ≤ (|U_m| + |U_s,m|)/|Z_q,m + Z_qL,m + Z_F| + margin_m

and I_H = √(Σ I_F,m² + I_rest²), I_RES = √(I_1² + I_H²). The phase between U_m and U_s,m is not known from a
power-quality measurement – their magnitudes are added (safe side). I_rest are the harmonics the model does not cover
(from the calibration tests), I_1 the fundamental residual current.

All quantities are phasors referred to the fundamental of U_L1-L2 (as in the result files of
[`groundfault.evaluation`][groundfault.evaluation] and the equivalent-source method). The model is stored as a JSON
file and grows with every calibration and every recorded earth fault.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Union

import numpy as np
import pandas as pd

from ..equivalent_source import SourceMeasurement, natural_sequence
from ..i18n import tr
from ..legacy import check_option
from ._util import (SEQ, complex_aggregate, cx, finite, fnum, from_cx, json_safe, none_if_nan, order_of,
                    orders_text, parallel, phase_factors, source_voltage)
from .data import FaultData, fault_data_from_measurement
from .line import Line, as_line

__all__ = ["MODEL_FORMAT", "MODEL_VERSION", "OrderEstimate", "Calibration", "SourceTerm", "Forecast", "NetworkModel"]

MODEL_FORMAT = "groundfault-network-model"
"""Format tag of the model files."""
MODEL_VERSION = 2
"""Version of the model file format (2: lines, estimated currents, Y_0 of the network; version 1 is read)."""

_KINDS = ("test", "fault")
_PASSIVE_TOL_OHM = 0.05                 # line_from_fault: tolerance of the resistive-inductive check in Ω
_HOW = ("median", "mean", "latest")
_MODES = ("loo", "pairwise", "chain")
_REFERENCES = ("LE", "LL", "seq")


# ============================================================================================ model contents
@dataclass
class OrderEstimate:
    """Sequence impedances of one harmonic order from one earth fault.

    Attributes
    ----------
    order : int
        Harmonic order m.
    Z0, Z1, Z2 : complex
        Zero-, positive- and negative-sequence impedance at the busbar in Ω.
    U_q : complex
        Pre-fault voltage of the faulted phase (angle-method orientation) in V.
    dU0 : complex
        Change of the zero-sequence voltage during the fault in V.
    I : complex
        Measured fault current (tests; NaN for recorded earth faults).
    I_estimated : float
        Estimated fault current of a recorded earth fault in A (node rule or 3·|ΔU_0|/|Z_0|).
    Z_up : complex, optional
        Upstream impedance of transformer and HV network (transformer node).
    Y0_net : complex, optional
        Zero-sequence admittance of the network without the coils, (I − ΔI_coil)/(3·ΔU_0) (tests with coil
        currents).
    """

    order: int
    Z0: complex
    Z1: complex
    Z2: complex
    U_q: complex
    dU0: complex
    I: complex = complex("nan")
    I_estimated: float = float("nan")
    Z_up: Optional[complex] = None
    Y0_net: Optional[complex] = None

    @property
    def Zq(self) -> complex:
        """Source impedance Z_q = (Z_0 + Z_1 + Z_2)/3."""
        return (self.Z0 + self.Z1 + self.Z2) / 3

    def Z_down(self, seq: str = "pos") -> complex:
        """Impedance of the MV network (downstream of the busbar) in the positive or negative sequence,
        1/(1/Z_s − 1/Z_up); NaN without Z_up."""
        if self.Z_up is None or not finite(self.Z_up):
            return complex("nan")
        Zs = self.Z1 if seq == "pos" else self.Z2
        return 1.0 / (1.0 / Zs - 1.0 / self.Z_up)

    def with_upstream(self, Z_up_new: complex) -> "OrderEstimate":
        """Copy with Z_1, Z_2 for another upstream impedance (Z_up,new ∥ Z_down,s)."""
        if self.Z_up is None or not finite(self.Z_up):
            return self
        Z1 = parallel(Z_up_new, self.Z_down("pos"))
        Z2 = parallel(Z_up_new, self.Z_down("neg"))
        return OrderEstimate(self.order, self.Z0, Z1, Z2, self.U_q, self.dU0, self.I, self.I_estimated, Z_up_new,
                             self.Y0_net)


@dataclass
class Calibration:
    """One earth fault in the model: a staged fault test (kind ``"test"``) or a recorded earth fault (``"fault"``).

    Attributes
    ----------
    name, kind, time, faulted_phase, file
        As in [`FaultData`][groundfault.forecast.data.FaultData].
    Z_F : complex, optional
        Additional impedance of a test in Ω.
    orders : dict of int to OrderEstimate
        Sequence impedances per order.
    Iw, Iv, I_C, U0, IH_sum : float
        Fundamental quantities and harmonic content of the fault current (NaN if unknown).
    reference : str
        Recorded earth faults: the calibration(s) that supplied Z_0.
    meta : dict
        Free metadata.
    hints : list of str
        Hints.
    line : Line, optional
        Line between the busbar and the fault location (a test in the network).
    currents : dict of int to complex
        Recorded earth faults: estimated fault current per order (also at the orders that are not updated).
    current_method : dict of int to str
        Method per order: ``"node_rule"`` (coil currents) or ``"zero_sequence_voltage"`` (3·ΔU_0/Z_0).
    U_q : dict of int to complex
        Pre-fault voltage of the faulted phase per order (all orders of the recording).
    """

    name: str
    kind: str
    time: str
    faulted_phase: str
    Z_F: Optional[complex]
    orders: Dict[int, OrderEstimate]
    Iw: float = float("nan")
    Iv: float = float("nan")
    I_C: float = float("nan")
    U0: float = float("nan")
    IH_sum: float = float("nan")
    reference: str = ""
    file: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)
    hints: List[str] = field(default_factory=list)
    line: Optional[Line] = None
    currents: Dict[int, complex] = field(default_factory=dict)
    current_method: Dict[int, str] = field(default_factory=dict)
    U_q: Dict[int, complex] = field(default_factory=dict)

    @property
    def I1(self) -> float:
        """Fundamental residual current √(I_w² + I_v²) in A (NaN if unknown)."""
        if np.isfinite(self.Iw):
            return float(math.hypot(self.Iw, self.Iv if np.isfinite(self.Iv) else 0.0))
        return float("nan")

    def series_impedance(self, m: int) -> complex:
        """Series impedance of the fault loop outside the busbar equivalent at order m: Z_F + Z_qL,m (tests)."""
        z = complex(self.Z_F) if self.Z_F is not None else 0j
        return z + (self.line.Zq(m) if self.line is not None else 0j)

    def rest_A(self, orders: Iterable[int]) -> float:
        """Harmonic content of the measured fault current outside ``orders`` in A, √max(I_H,Σ² − Σ|I_m|², 0) (NaN
        without fault current)."""
        if self.kind != "test" or not np.isfinite(self.IH_sum):
            return float("nan")
        sel = sum(abs(e.I) ** 2 for m, e in self.orders.items() if m in set(orders) and finite(e.I))
        return float(math.sqrt(max(self.IH_sum ** 2 - sel, 0.0)))


@dataclass
class SourceTerm:
    """Model of one harmonic order used by the forecast.

    Attributes
    ----------
    order : int
        Harmonic order.
    kind : {"pre_fault", "two_source", "constant"}
        ``"pre_fault"``: I = U/(Z_q + Z) with the pre-fault voltage as source; ``"two_source"``: additionally the
        source U_s that arises in the fault; ``"constant"``: the current of one test (source that arises in the fault,
        not separable).
    Zq : complex
        Source impedance at the busbar in Ω.
    Us : complex
        Source that arises in the fault in V (0 for ``"pre_fault"``).
    I_constant : float
        Current of ``"constant"`` in A.
    Z_F_constant : float
        Magnitude of the series impedance (additional impedance and line) in Ω of the test whose current
        ``"constant"`` uses.
    n : int
        Number of earth faults used.
    residual : float
        Largest relative deviation of the fit of ``"two_source"`` (NaN otherwise).
    calibrations : list of str
        Names of the earth faults used.
    hints : list of str
        Hints.
    """

    order: int
    kind: str
    Zq: complex
    Us: complex = 0j
    I_constant: float = float("nan")
    Z_F_constant: float = float("nan")
    n: int = 0
    residual: float = float("nan")
    calibrations: List[str] = field(default_factory=list)
    hints: List[str] = field(default_factory=list)

    def current(self, U, Z_F: complex = 0.0, conservative: bool = True):
        """Fault current of this order in A for the pre-fault voltage ``U`` (line-to-earth, magnitude or phasor;
        scalar or array) and the series impedance ``Z_F`` (fault impedance plus the line contribution Z_qL).

        ``conservative=True`` adds the magnitudes of U and U_s (the phase between them is not known from a
        power-quality measurement); False uses the phasor sum (``U`` complex, same angle reference)."""
        if self.kind == "constant":
            return np.full(np.shape(U), self.I_constant) if np.ndim(U) else float(self.I_constant)
        den = abs(self.Zq + complex(Z_F))
        if conservative or self.kind == "pre_fault":
            num = np.abs(U) + (abs(self.Us) if self.kind == "two_source" else 0.0)
        else:
            num = np.abs(np.asarray(U, complex) + self.Us)
        return num / den


# ============================================================================================ forecast
@dataclass
class Forecast:
    """Forecast of the harmonic residual current.

    Attributes
    ----------
    currents : pandas.DataFrame
        Fault current per order in A including the margin (columns: orders; rows: time steps or ``"value"``).
    voltages : pandas.DataFrame
        Line-to-earth voltage per order in V that was used (largest of the phases).
    terms : dict of int to SourceTerm
        Model per order.
    Z_F : complex
        Fault impedance in Ω.
    margin : dict of int to float
        Margin per order in A.
    I1 : float
        Fundamental residual current in A (NaN if unknown).
    rest_A : float
        Harmonic content outside the forecast orders in A.
    hints : list of str
        Hints.
    line : Line, optional
        Line between the busbar and the fault location.
    """

    currents: pd.DataFrame
    voltages: pd.DataFrame
    terms: Dict[int, SourceTerm]
    Z_F: complex
    margin: Dict[int, float]
    I1: float
    rest_A: float
    hints: List[str] = field(default_factory=list)
    line: Optional[Line] = None

    @property
    def IH(self) -> pd.Series:
        """Harmonic residual current √(Σ I_m² + I_rest²) in A."""
        return np.sqrt((self.currents ** 2).sum(axis=1) + self.rest_A ** 2)

    @property
    def IRES(self) -> pd.Series:
        """Residual current √(I_1² + I_H²) in A (without I_1 if unknown)."""
        i1 = self.I1 if np.isfinite(self.I1) else 0.0
        return np.sqrt(i1 ** 2 + self.IH ** 2)

    def quantile(self, q: float) -> Dict[str, Any]:
        """Quantile of a time-series forecast.

        Parameters
        ----------
        q : float
            Quantile, e.g. 0.95.

        Returns
        -------
        dict
            ``IRES``, ``IH`` (quantiles of the time series of the totals) and ``orders`` (quantile per order) in A.

        Raises
        ------
        ValueError
            For a forecast with a single value per order.
        """
        if len(self.currents) < 2:
            raise ValueError(tr("forecast.quantile_needs_series"))
        return dict(IRES=float(self.IRES.quantile(q)), IH=float(self.IH.quantile(q)),
                    orders={int(m): float(self.currents[m].quantile(q)) for m in self.currents.columns})

    def loop_impedance(self, m: int) -> complex:
        """Series impedance outside the busbar equivalent at order m: Z_F + Z_qL,m."""
        return self.Z_F + (self.line.Zq(m) if self.line is not None else 0j)

    def table(self, q: Optional[float] = None) -> pd.DataFrame:
        """Forecast per order (single value, or the quantile ``q`` of a time series).

        Returns
        -------
        pandas.DataFrame
            Columns ``order``, ``kind``, ``U_V``, ``Us_V``, ``Z_line_Ohm`` (with a line: |Z_qL|), ``Zq_ZF_Ohm``
            (|Z_q + Z_qL + Z_F|), ``I_A`` (without margin), ``margin_A``, ``I_forecast_A``; the last rows ``I_rest``,
            ``I_H`` (total, rest included), ``I_1`` and ``I_RES``.
        """
        if len(self.currents) > 1 and q is None:
            raise ValueError(tr("forecast.quantile_needs_series"))
        pick = (lambda s: float(s.iloc[0])) if len(self.currents) == 1 else (lambda s: float(s.quantile(q)))
        rows = []
        for m in self.currents.columns:
            T = self.terms[m]
            I = pick(self.currents[m])
            row = dict(order=int(m), kind=T.kind, U_V=pick(self.voltages[m]) if m in self.voltages else float("nan"),
                       Us_V=abs(T.Us))
            if self.line is not None:
                row["Z_line_Ohm"] = abs(self.line.Zq(int(m)))
            row.update(Zq_ZF_Ohm=abs(T.Zq + self.loop_impedance(int(m))) if T.kind != "constant" else float("nan"),
                       I_A=I - self.margin.get(m, 0.0), margin_A=self.margin.get(m, 0.0), I_forecast_A=I)
            rows.append(row)
        rows.append(dict(order="I_rest", kind="", I_forecast_A=self.rest_A))
        rows.append(dict(order="I_H", kind="", I_forecast_A=pick(self.IH)))
        rows.append(dict(order="I_1", kind="", I_forecast_A=self.I1))
        rows.append(dict(order="I_RES", kind="", I_forecast_A=pick(self.IRES)))
        return pd.DataFrame(rows)


def _voltage_frames(voltages, reference: str, percent_of: Optional[float]) -> Dict[str, pd.DataFrame]:
    """Voltages per phase as DataFrames (rows: time steps, columns: orders), line-to-earth in V."""
    def frame(x) -> pd.DataFrame:
        if isinstance(x, pd.Series):                         # one value per order
            x = x.to_dict()
        if isinstance(x, Mapping) and not isinstance(x, pd.DataFrame):
            df = pd.DataFrame({k: [v] for k, v in x.items()}, index=["value"])
        else:
            df = pd.DataFrame(x).copy()
        cols = {c: order_of(c) for c in df.columns}
        keep = {c: o for c, o in cols.items() if o is not None and o >= 1}
        if not keep:
            raise ValueError(tr("forecast.no_voltage_columns", columns=list(df.columns)))
        df = df[list(keep)].rename(columns=keep).astype(float)
        df = df.T.groupby(level=0).max().T                  # the same order twice → the larger
        if percent_of is not None:
            df = df * float(percent_of) / 100.0
        if reference == "LL":
            df = df / math.sqrt(3.0)
        return df
    if isinstance(voltages, Mapping) and voltages and all(str(k).upper() in ("L1", "L2", "L3") for k in voltages):
        return {str(k).upper(): frame(v) for k, v in voltages.items()}
    return {"": frame(voltages)}


def _line_hints(line: Optional[Line], orders: Iterable[int]) -> List[str]:
    if line is None:
        return []
    out = [tr("forecast.line_used", line=line.name or "–")]
    ords = sorted(int(m) for m in orders)
    if ords:
        given = [m for m in ords if line.source(m) in ("loop", "orders")]
        rest = [m for m in ords if m not in given]
        if not given:
            out.append(tr("forecast.line_50hz_only", line=line.name or "–"))
        elif rest:
            out.append(tr("forecast.line_orders", line=line.name or "–", given=orders_text(given),
                          rest=orders_text(rest)))
        frac = line.wavelength_fraction(ords[-1])
        if frac is not None:
            out.append(tr("forecast.line_wavelength", line=line.name or "–", pct=100 * frac, order=ords[-1]))
    return out


# ============================================================================================ the model
class NetworkModel:
    """Learnable network model of the earth-fault loop per harmonic order.

    Parameters
    ----------
    name : str, optional
        Name of the network (substation, busbar).
    description : str, optional
        Free text.

    Examples
    --------
    >>> from groundfault import forecast as fc
    >>> model = fc.NetworkModel("Demo")                                                  # doctest: +SKIP
    >>> for path, Z in (("SUB_0_result.json", 0.0), ("SUB_5_result.json", 5.0)):         # doctest: +SKIP
    ...     model.add_test(fc.load_fault_data(path, Z))
    >>> f = model.forecast({3: 30.0, 5: 250.0, 7: 120.0}, margin_A=2.0)                  # doctest: +SKIP
    >>> f.table()                                                                        # doctest: +SKIP
    """

    def __init__(self, name: str = "", description: str = ""):
        self.name = name
        self.description = description
        self.calibrations: List[Calibration] = []

    # ------------------------------------------------------------------------------------ access
    def __len__(self) -> int:
        return len(self.calibrations)

    def __repr__(self) -> str:
        return "NetworkModel(%r, tests=%d, faults=%d, orders=%s)" % (self.name, len(self.tests), len(self.faults),
                                                                     self.orders)

    @property
    def tests(self) -> List[Calibration]:
        """Calibration tests (fault current measured)."""
        return [c for c in self.calibrations if c.kind == "test"]

    @property
    def faults(self) -> List[Calibration]:
        """Recorded earth faults (busbar voltages only)."""
        return [c for c in self.calibrations if c.kind == "fault"]

    @property
    def orders(self) -> List[int]:
        """Harmonic orders contained in at least one earth fault."""
        return sorted({m for c in self.calibrations for m in c.orders})

    @property
    def names(self) -> List[str]:
        """Names of the earth faults in the model."""
        return [c.name for c in self.calibrations]

    def calibration(self, name: str) -> Calibration:
        """The earth fault named ``name``."""
        for c in self.calibrations:
            if c.name == name:
                return c
        raise KeyError(tr("forecast.unknown_name", name=name, names=", ".join(self.names) or "–"))

    def remove(self, name: str) -> None:
        """Remove the earth fault named ``name``."""
        self.calibrations.remove(self.calibration(name))

    def subset(self, names: Optional[Iterable[str]] = None, kinds: Optional[Iterable[str]] = None,
               where: Optional[Callable[[Calibration], bool]] = None) -> "NetworkModel":
        """Model with a selection of the earth faults (e.g. by time of day, switching state or load in ``meta``).

        Parameters
        ----------
        names : iterable of str, optional
            Names to keep.
        kinds : iterable of {"test", "fault"}, optional
            Kinds to keep.
        where : callable, optional
            Condition ``f(calibration) → bool``.
        """
        keep = []
        names = set(names) if names is not None else None
        kinds = set(kinds) if kinds is not None else None
        for c in self.calibrations:
            if names is not None and c.name not in names:
                continue
            if kinds is not None and c.kind not in kinds:
                continue
            if where is not None and not where(c):
                continue
            keep.append(c)
        out = NetworkModel(self.name, self.description)
        out.calibrations = list(keep)
        return out

    # ------------------------------------------------------------------------------------ adding earth faults
    def _check_name(self, name: str) -> None:
        if name in self.names:
            raise ValueError(tr("forecast.duplicate", name=name))

    def add_test(self, data: Union[FaultData, SourceMeasurement], orders: Union[str, Sequence[int]] = "auto",
                 min_current_A: float = 0.3, name: Optional[str] = None, line: Any = None,
                 meta: Optional[Mapping[str, Any]] = None) -> Calibration:
        """Calibrate with a staged fault test: Z_s,m = 3·p_s·ΔU_s,m/I_m for every order.

        Parameters
        ----------
        data : FaultData or SourceMeasurement
            Test with fault current and additional impedance.
        orders : "auto" or sequence of int, optional
            ``"auto"``: odd orders ≥ 3 with a fault current of at least ``min_current_A``.
        min_current_A : float, optional
            Smallest current of an order for ``"auto"`` in A.
        name : str, optional
            Name (default: the name of ``data``).
        line : Line, mapping or list, optional
            Line between the busbar and the fault location of a test in the network (default: ``data.line``). The
            busbar voltages give the sequence impedances at the busbar; the line enters the fault loop.
        meta : mapping, optional
            Metadata, added to that of ``data``.

        Returns
        -------
        Calibration

        Raises
        ------
        ValueError
            Without fault current or additional impedance, or for a name that exists already.
        """
        if isinstance(data, SourceMeasurement):
            data = fault_data_from_measurement(data, "test")
        nm = name or data.name
        if not data.I or data.Z_F is None:
            raise ValueError(tr("forecast.no_current", name=nm))
        self._check_name(nm)
        hints = list(data.hints)
        phase = data.faulted_phase
        if not phase:
            hints.append(tr("forecast.phase_unknown"))
        pf = phase_factors(phase)
        if isinstance(orders, str):
            check_option("orders", orders, ("auto",))
            orders = [m for m in sorted(data.I) if m >= 3 and m % 2 == 1 and abs(data.I[m]) >= min_current_A]
        est = {}
        for m in orders:
            m = int(m)
            if m not in data.I or m not in data.U_pre or m not in data.U_fault or abs(data.I[m]) == 0:
                continue
            dU = {s: data.U_fault[m].get(s, 0.0) - data.U_pre[m].get(s, 0.0) for s in SEQ}
            Zs = {s: 3 * pf[s] * dU[s] / data.I[m] for s in SEQ}
            y0 = None
            if m in data.I_coil and m in data.dU0_coil and abs(data.dU0_coil[m]) > 0:
                y0 = complex((data.I[m] - data.I_coil[m]) / (3 * data.dU0_coil[m]))
            est[m] = OrderEstimate(m, Zs["zero"], Zs["pos"], Zs["neg"], source_voltage(pf, data.U_pre[m]),
                                   dU["zero"], I=complex(data.I[m]), Z_up=_upstream_of(data, m), Y0_net=y0)
        if not est:
            raise ValueError(tr("forecast.no_orders", name=nm))
        c = Calibration(name=nm, kind="test", time=data.time, faulted_phase=phase, Z_F=complex(data.Z_F), orders=est,
                        Iw=data.Iw, Iv=data.Iv, I_C=data.I_C, U0=data.U0, IH_sum=data.IH_sum, file=data.file,
                        meta={**data.meta, **dict(meta or {})}, hints=hints,
                        line=as_line(line) if line is not None else data.line,
                        U_q={m: source_voltage(pf, data.U_pre[m]) for m in data.U_pre})
        self.calibrations.append(c)
        return c

    def _y0_net(self) -> Dict[int, complex]:
        """Zero-sequence admittance of the network without the coils per order: median over the tests."""
        out = {}
        for m in sorted({m for c in self.tests for m in c.orders}):
            vals = [c.orders[m].Y0_net for c in self.tests if m in c.orders and c.orders[m].Y0_net is not None]
            if vals:
                out[m] = complex_aggregate(vals, "median")
        return out

    def add_fault(self, data: Union[FaultData, SourceMeasurement], orders: Optional[Sequence[int]] = None,
                  z0: Union[str, Mapping[int, complex]] = "tests", min_dU0_V: float = 0.5,
                  two_source: Union[str, Iterable[int], None] = "zero_sequence",
                  name: Optional[str] = None, meta: Optional[Mapping[str, Any]] = None) -> Calibration:
        """Update with a recorded earth fault (busbar voltages only): Z_s,m = Z_0,m·p_s·ΔU_s,m/ΔU_0,m and the fault
        current of this earth fault.

        The fault current per order (``Calibration.currents``) follows from the node rule of the zero sequence if
        the recording contains the coil currents and the tests did too, I_F,m = 3·Y_0,net,m·ΔU_0,m + ΔI_coil,m, and
        otherwise from the zero-sequence voltage, |I_F,m| = 3·|ΔU_0,m|/|Z_0,m|.

        Parameters
        ----------
        data : FaultData or SourceMeasurement
            Earth fault; a fault current in it is kept for comparison only (``OrderEstimate.I``).
        orders : sequence of int, optional
            Orders to update (default: all orders with Z_0).
        z0 : "tests", str or mapping, optional
            Zero-sequence impedance: ``"tests"`` = median of the calibration tests, the name of one calibration, or
            ``{order: Z_0}``.
        min_dU0_V : float, optional
            Smallest |ΔU_0,m| in V; orders below are not updated.
        two_source : "zero_sequence", iterable of int or None, optional
            Orders with a source that arises in the fault – Z not updated (the busbar voltages contain that source,
            ΔU_0 = Z_0·I/3 − U_s), the current is estimated. Default: the orders of the zero sequence.
        name : str, optional
            Name (default: the name of ``data``).
        meta : mapping, optional
            Metadata, added to that of ``data``.

        Returns
        -------
        Calibration

        Raises
        ------
        ValueError
            Without Z_0, without an order to update, or for a name that exists already.
        """
        if isinstance(data, SourceMeasurement):
            data = fault_data_from_measurement(data, "test")
        nm = name or data.name
        self._check_name(nm)
        if isinstance(z0, str) and z0 == "tests":
            tests = self.tests
            Z0 = {m: complex_aggregate([c.orders[m].Z0 for c in tests if m in c.orders], "median")
                  for m in sorted({m for c in tests for m in c.orders})}
            reference = ", ".join(c.name for c in tests)
        elif isinstance(z0, str):
            cal = self.calibration(z0)
            Z0 = {m: e.Z0 for m, e in cal.orders.items()}
            reference = cal.name
        else:
            Z0 = {int(m): complex(v) for m, v in z0.items()}
            reference = "z0"
        Z0 = {m: v for m, v in Z0.items() if finite(v)}
        if not Z0:
            raise ValueError(tr("forecast.no_reference"))
        hints = list(data.hints)
        phase = data.faulted_phase
        if not phase:
            hints.append(tr("forecast.phase_unknown"))
        pf = phase_factors(phase)
        wanted = sorted(set(int(m) for m in orders) if orders is not None else set(Z0))
        if isinstance(two_source, str):
            check_option("two_source", two_source, ("zero_sequence",))
            skip = {m for m in wanted if m % 3 == 0}
        else:
            skip = set(int(m) for m in (two_source or ()))
        # ---- fault current of this earth fault per order: node rule (coil currents) or zero-sequence voltage
        Y0 = self._y0_net() if data.I_coil else {}
        currents, method = {}, {}
        for m in wanted:
            if m in Y0 and m in data.I_coil and m in data.dU0_coil:
                currents[m] = 3 * Y0[m] * data.dU0_coil[m] + data.I_coil[m]
                method[m] = "node_rule"
            elif m in Z0 and m in data.U_pre and m in data.U_fault and m not in skip:
                dU0 = data.U_fault[m].get("zero", 0.0) - data.U_pre[m].get("zero", 0.0)
                if abs(dU0) >= min_dU0_V:          # not at a source in the fault: ΔU_0 = Z_0·I_F/3 − U_s there
                    currents[m] = 3 * dU0 / Z0[m]
                    method[m] = "zero_sequence_voltage"
        if data.I_coil:
            hints.append(tr("forecast.node_rule", tests=", ".join(c.name for c in self.tests
                                                                    if any(e.Y0_net is not None
                                                                           for e in c.orders.values())))
                         if Y0 else tr("forecast.node_rule_no_tests"))
        # ---- sequence impedances
        est, small, missing = {}, [], []
        if skip & set(wanted):
            hints.append(tr("forecast.fault_source_not_updated", orders=orders_text(skip & set(wanted))))
        for m in wanted:
            if m in skip:
                continue
            if m not in Z0:
                missing.append(m)
                continue
            if m not in data.U_pre or m not in data.U_fault:
                continue
            dU = {s: data.U_fault[m].get(s, 0.0) - data.U_pre[m].get(s, 0.0) for s in SEQ}
            if abs(dU["zero"]) < min_dU0_V:
                small.append(m)
                continue
            Zs = {s: Z0[m] * pf[s] * dU[s] / (pf["zero"] * dU["zero"]) for s in SEQ}
            est[m] = OrderEstimate(m, Zs["zero"], Zs["pos"], Zs["neg"], source_voltage(pf, data.U_pre[m]), dU["zero"],
                                   I=complex(data.I[m]) if m in data.I else complex("nan"),
                                   I_estimated=float(abs(currents[m])) if m in currents else float("nan"),
                                   Z_up=_upstream_of(data, m))
        if small:
            hints.append(tr("forecast.small_dU0", orders=orders_text(small), limit=min_dU0_V))
        if missing:
            hints.append(tr("forecast.no_z0", orders=orders_text(missing)))
        if not est:
            raise ValueError(tr("forecast.no_orders", name=nm))
        c = Calibration(name=nm, kind="fault", time=data.time, faulted_phase=phase, Z_F=None, orders=est,
                        Iw=data.Iw, Iv=data.Iv, I_C=data.I_C, U0=data.U0, IH_sum=data.IH_sum, reference=reference,
                        file=data.file, meta={**data.meta, **dict(meta or {})}, hints=hints, line=data.line,
                        currents=currents, current_method=method,
                        U_q={m: source_voltage(pf, data.U_pre[m]) for m in data.U_pre})
        self.calibrations.append(c)
        return c

    def line_from_fault(self, data: FaultData, Z_F: complex = 0.0, *,
                        z0: Union[str, Mapping[int, complex]] = "tests", orders: Optional[Iterable[int]] = None,
                        min_dU0_V: float = 0.5, two_source: Union[str, Iterable[int], None] = "zero_sequence"
                        ) -> Dict[int, complex]:
        """Loop contribution of the line per order from a recorded earth fault behind it – a measurement of the line
        at the harmonic orders from the busbar alone.

        The voltage of the faulted phase at the busbar during the fault is the voltage drop of the fault current
        across the line and the fault impedance, U_L,bus,m = −(Z_qL,m + Z_F)·I_F,m (zero for a fault at the busbar).
        The fault current follows from the busbar as in
        [`add_fault`][groundfault.forecast.model.NetworkModel.add_fault]: with coil currents in the recording and in
        the tests from the node rule at every order, otherwise I_F,m = 3·ΔU_0,m/Z_0,m – not at the orders of a source
        in the fault. Hence

            Z_qL,m = −U_L,bus,m/I_F,m − Z_F

        The result goes into a [`Line`][groundfault.forecast.line.Line] as ``loop``. The shunt capacitance of the line
        carries part of the zero-sequence current; the estimate holds for a line short against a quarter wavelength
        (a few per cent for some kilometres of cable at 250 Hz). A result that is not resistive-inductive (real or
        imaginary part below −0.05 Ω) is left out with a warning: the fault current from the busbar does not describe
        that order – usually a source in the fault that the zero-sequence voltage contains.

        Parameters
        ----------
        data : FaultData
            Recorded earth fault behind the line with the busbar voltages before and during the fault and the
            faulted phase.
        Z_F : complex, optional
            Fault impedance in Ω (default 0: the result contains the fault impedance, e.g. the earthing impedance of
            the station).
        z0, min_dU0_V, two_source
            As in [`add_fault`][groundfault.forecast.model.NetworkModel.add_fault].
        orders : iterable of int, optional
            Orders (default: all orders with Z_0 of the tests).

        Returns
        -------
        dict of int to complex
            Z_qL,m in Ω.

        Raises
        ------
        ValueError
            Without an order to derive the line from.
        """
        if isinstance(z0, str) and z0 == "tests":
            tests = self.tests
            Z0 = {m: complex_aggregate([c.orders[m].Z0 for c in tests if m in c.orders], "median")
                  for m in sorted({m for c in tests for m in c.orders})}
        elif isinstance(z0, str):
            Z0 = {m: e.Z0 for m, e in self.calibration(z0).orders.items()}
        else:
            Z0 = {int(m): complex(v) for m, v in z0.items()}
        Z0 = {m: v for m, v in Z0.items() if finite(v)}
        wanted = sorted(set(int(m) for m in orders) if orders is not None else set(Z0))
        if isinstance(two_source, str):
            check_option("two_source", two_source, ("zero_sequence",))
            skip = {m for m in wanted if m % 3 == 0}
        else:
            skip = set(int(m) for m in (two_source or ()))
        pf = phase_factors(data.faulted_phase)
        Y0 = self._y0_net() if data.I_coil else {}
        out: Dict[int, complex] = {}
        src, small, active = [], [], []
        for m in wanted:
            if m not in data.U_fault or m not in data.U_pre:
                continue
            if m in Y0 and m in data.I_coil and m in data.dU0_coil:
                I_F = 3 * Y0[m] * data.dU0_coil[m] + data.I_coil[m]
            elif m in Z0:
                if m in skip:
                    src.append(m)
                    continue
                dU0 = data.U_fault[m].get("zero", 0.0) - data.U_pre[m].get("zero", 0.0)
                if abs(dU0) < min_dU0_V:
                    small.append(m)
                    continue
                I_F = 3 * dU0 / Z0[m]
            else:
                continue
            if abs(I_F) == 0:
                continue
            U_bus = -source_voltage(pf, data.U_fault[m])           # faulted phase at the busbar during the fault
            z = complex(-U_bus / I_F - complex(Z_F))
            if z.real < -_PASSIVE_TOL_OHM or z.imag < -_PASSIVE_TOL_OHM:
                active.append(m)                                   # a series line is resistive-inductive
                continue
            out[m] = z
        if active:
            warnings.warn(tr("forecast.line_from_fault_active", name=data.name, orders=orders_text(active)),
                          stacklevel=2)
        if src:
            warnings.warn(tr("forecast.line_from_fault_source", name=data.name, orders=orders_text(src)),
                          stacklevel=2)
        if small:
            warnings.warn(tr("forecast.line_from_fault_small", name=data.name, orders=orders_text(small),
                             limit=min_dU0_V), stacklevel=2)
        if not out:
            raise ValueError(tr("forecast.line_from_fault_none", name=data.name))
        return out

    def add_upstream(self, name: str, Z_up: Mapping[int, complex]) -> None:
        """Attach the upstream impedance (transformer + HV network) of the transformer node to an earth fault – a
        recording with the line currents of the transformer gives it by itself
        ([`load_fault_data`][groundfault.forecast.data.load_fault_data]); this adds it from another recording.

        Parameters
        ----------
        name : str
            Name of the earth fault.
        Z_up : mapping
            ``{order: Z_up}`` in Ω, e.g. from [`upstream_from_result`][groundfault.forecast.data.upstream_from_result].
        """
        c = self.calibration(name)
        for m, z in Z_up.items():
            if int(m) in c.orders:
                c.orders[int(m)].Z_up = complex(z)

    # ------------------------------------------------------------------------------------ the model per order
    def source_terms(self, orders: Optional[Iterable[int]] = None, how: str = "median",
                     two_source: Union[str, Iterable[int], None] = "zero_sequence",
                     kinds: Iterable[str] = ("test", "fault"),
                     upstream: Optional[Mapping[int, complex]] = None) -> Dict[int, SourceTerm]:
        """The model per order used for a forecast.

        Parameters
        ----------
        orders : iterable of int, optional
            Orders (default: all orders of the model).
        how : {"median", "mean", "latest"}, optional
            Aggregation of Z_q over the earth faults (``"latest"`` = the last one added).
        two_source : "zero_sequence", iterable of int or None, optional
            Orders with a source that arises in the fault (default: the orders of the zero sequence, m divisible
            by 3). With two or more tests of different series impedance U_s and Z_q are fitted; with fewer the
            measured current is used (``"constant"``).
        kinds : iterable of {"test", "fault"}, optional
            Kinds of earth faults used for the orders with the pre-fault source.
        upstream : mapping, optional
            Another upstream impedance ``{order: Z_up}`` (transformer node: Z_1 = Z_up ∥ Z_down) – only for earth
            faults with Z_up.

        Returns
        -------
        dict of int to SourceTerm
        """
        check_option("how", how, _HOW)
        kinds = tuple(kinds)
        for k in kinds:
            check_option("kinds", k, _KINDS)
        if not self.calibrations:
            raise ValueError(tr("forecast.empty"))
        if isinstance(two_source, str):
            check_option("two_source", two_source, ("zero_sequence",))
            two = {m for m in self.orders if m % 3 == 0}
        else:
            two = set(int(m) for m in (two_source or ()))
        out = {}
        for m in (sorted(set(int(x) for x in orders)) if orders is not None else self.orders):
            if m in two:
                T = self._two_source_term(m)
                if T is not None:
                    out[m] = T
                    continue
            cals = [c for c in self.calibrations if c.kind in kinds and m in c.orders]
            if not cals:
                continue
            ests, hints = [], []
            for c in cals:
                e = c.orders[m]
                if upstream is not None and m in upstream:
                    if e.Z_up is None:
                        hints.append(tr("forecast.upstream_missing", name=c.name, orders=orders_text([m])))
                    else:
                        e = e.with_upstream(complex(upstream[m]))
                ests.append(e)
            out[m] = SourceTerm(order=m, kind="pre_fault", Zq=complex_aggregate([e.Zq for e in ests], how),
                                n=len(ests), calibrations=[c.name for c in cals], hints=hints)
        return out

    def _two_source_term(self, m: int) -> Optional[SourceTerm]:
        tests = [c for c in self.tests if m in c.orders and finite(c.orders[m].I)]
        if not tests:
            return None
        Z = np.array([c.series_impedance(m) for c in tests])
        if len(tests) < 2 or len({round(abs(z), 6) for z in Z}) < 2:
            c = max(tests, key=lambda x: abs(x.orders[m].I))
            I0 = float(abs(c.orders[m].I))
            return SourceTerm(order=m, kind="constant", Zq=complex_aggregate([x.orders[m].Zq for x in tests], "median"),
                              I_constant=I0, Z_F_constant=abs(c.series_impedance(m)), n=len(tests),
                              calibrations=[x.name for x in tests],
                              hints=[tr("forecast.constant_source", order=m, name=c.name, current=I0,
                                        z=abs(c.series_impedance(m)))])
        I = np.array([complex(c.orders[m].I) for c in tests])
        Uq = np.array([complex(c.orders[m].U_q) for c in tests])
        A = np.column_stack([I, -np.ones_like(I)])
        cond = float(np.linalg.cond(A))
        if cond > 1e4:
            return SourceTerm(order=m, kind="pre_fault", Zq=complex_aggregate([x.orders[m].Zq for x in tests], "median"),
                              n=len(tests), calibrations=[x.name for x in tests],
                              hints=[tr("forecast.ill_conditioned", order=m, cond=cond)])
        x, *_ = np.linalg.lstsq(A, Uq - I * Z, rcond=None)
        Zq, Us = complex(x[0]), complex(x[1])
        pred = (Uq + Us) / (Zq + Z)
        resid = float(np.max(np.abs(pred - I) / np.abs(I)))
        return SourceTerm(order=m, kind="two_source", Zq=Zq, Us=Us, n=len(tests), residual=resid,
                          calibrations=[c.name for c in tests])

    # ------------------------------------------------------------------------------------ forecast
    def forecast(self, voltages, Z_F: complex = 0.0, margin_A: Union[float, Mapping[int, float]] = 0.0, *,
                 orders: Optional[Iterable[int]] = None, how: str = "median",
                 two_source: Union[str, Iterable[int], None] = "zero_sequence",
                 kinds: Iterable[str] = ("test", "fault"), reference: str = "LE",
                 percent_of: Optional[float] = None, fundamental_A: Optional[float] = None,
                 rest_A: Union[str, float, None] = "calibration",
                 upstream: Optional[Mapping[int, complex]] = None, line: Any = None) -> Forecast:
        """Forecast of the harmonic residual current from harmonic voltages of the busbar.

        Parameters
        ----------
        voltages : mapping, pandas.DataFrame or dict of DataFrames
            Harmonic voltages: ``{order: U}`` (e.g. 95 % quantiles), a time series with one column per order (column
            names ``5``, ``"H5"``, ``"U_L1_H5"`` … – the last integer is the order), or ``{"L1": …, "L2": …,
            "L3": …}`` per phase (the largest current of the phases is used per order).
        Z_F : complex, optional
            Fault impedance in Ω.
        margin_A : float or mapping, optional
            Margin per order in A added to the forecast (0 = none) – define it yourself, e.g. from
            [`cross_check`][groundfault.forecast.model.NetworkModel.cross_check].
        orders : iterable of int, optional
            Orders to forecast (default: all of the model).
        how, two_source, kinds, upstream
            See [`source_terms`][groundfault.forecast.model.NetworkModel.source_terms].
        reference : {"LE", "LL", "seq"}, optional
            ``"LE"``/``"seq"``: line-to-earth (sequence) voltages; ``"LL"``: line-to-line, divided by √3 (orders of
            the zero sequence are not contained).
        percent_of : float, optional
            Voltages in % of this voltage (e.g. the line-to-earth voltage).
        fundamental_A : float, optional
            Fundamental residual current in A (default: median of √(I_w² + I_v²) of the tests).
        rest_A : "calibration", float or None, optional
            Harmonic content outside the forecast orders: ``"calibration"`` = largest value of the tests, a number,
            or None/0.
        line : Line, mapping or list, optional
            Line between the busbar and a fault location in the network: Z_qL,m is added to the loop, the source is
            the voltage of the busbar.

        Returns
        -------
        Forecast
        """
        check_option("reference", reference, _REFERENCES)
        line = as_line(line)
        terms = self.source_terms(orders, how=how, two_source=two_source, kinds=kinds, upstream=upstream)
        frames = _voltage_frames(voltages, reference, percent_of)
        Z_F = complex(Z_F)
        margin = ({int(m): float(v) for m, v in margin_A.items()} if isinstance(margin_A, Mapping)
                  else {m: float(margin_A) for m in terms})
        hints: List[str] = []
        index = next(iter(frames.values())).index
        for df in frames.values():                          # phases with other time steps: union of the time steps
            if not df.index.equals(index):
                index = index.union(df.index)
        frames = {ph: df.reindex(index) for ph, df in frames.items()}
        cur = {}
        volt = {}
        missing, missing_src, ll_zero, ll_zero_skip = [], [], [], []
        for m, T in terms.items():
            have = [df[m].to_numpy(float) for df in frames.values() if m in df.columns]
            if reference == "LL" and m % 3 == 0:            # line-to-line voltages: no zero sequence
                if T.kind == "pre_fault":
                    ll_zero_skip.append(m)
                    continue
                ll_zero.append(m)
                have = []
            elif not have:
                if T.kind == "pre_fault":
                    missing.append(m)
                    continue
                if T.kind == "two_source":
                    missing_src.append(m)
            Zser = Z_F + (line.Zq(m) if line is not None else 0j)
            U_all = np.vstack(have) if have else np.zeros((1, len(index)))
            I_all = np.vstack([np.asarray(T.current(U, Zser), float) for U in U_all])
            cur[m] = np.fmax.reduce(I_all, axis=0) + margin.get(m, 0.0)      # largest phase (NaN of a phase ignored)
            volt[m] = np.fmax.reduce(U_all, axis=0)
        for key, lst in (("forecast.voltage_missing", missing),
                         ("forecast.voltage_missing_source", missing_src),
                         ("forecast.ll_zero_sequence", ll_zero),
                         ("forecast.ll_zero_sequence_skipped", ll_zero_skip)):
            if lst:
                hints.append(tr(key, orders=orders_text(lst)))
        currents = pd.DataFrame(cur, index=index)
        voltages_used = pd.DataFrame(volt, index=index)
        tests = self.tests
        if fundamental_A is None:
            vals = [c.I1 for c in tests if np.isfinite(c.I1)]
            I1 = float(np.median(vals)) if vals else float("nan")
            hints.append(tr("forecast.fundamental_from_tests", value=I1) if vals
                         else tr("forecast.fundamental_missing"))
        else:
            I1 = float(fundamental_A)
        if isinstance(rest_A, str):
            check_option("rest_A", rest_A, ("calibration",))
            vals = [c.rest_A(currents.columns) for c in tests]
            vals = [v for v in vals if np.isfinite(v)]
            rest = float(max(vals)) if vals else 0.0
            if vals:
                hints.append(tr("forecast.rest_from_tests", value=rest))
        else:
            rest = float(rest_A or 0.0)
        for T in terms.values():
            hints.extend(T.hints)
            zser = abs(Z_F + (line.Zq(T.order) if line is not None else 0j))
            if T.kind == "constant" and T.order in currents.columns and zser < T.Z_F_constant - 1e-9:
                hints.append(tr("forecast.constant_smaller_zf", order=T.order, z=T.Z_F_constant, zf=zser))
        hints.extend(_line_hints(line, currents.columns))
        return Forecast(currents=currents, voltages=voltages_used, terms=terms, Z_F=Z_F,
                        margin={m: margin.get(m, 0.0) for m in currents.columns}, I1=I1, rest_A=rest, hints=hints,
                        line=line)

    # ------------------------------------------------------------------------------------ checks
    def _predict(self, terms: Mapping[int, SourceTerm], U_q: Mapping[int, complex], Zser: Callable[[int], complex],
                 margin_A, conservative: bool, orders: Iterable[int]) -> Dict[int, float]:
        margin = margin_A if isinstance(margin_A, Mapping) else None
        pred = {}
        for m in orders:
            T = terms.get(m)
            if T is None or m not in U_q:
                continue
            U = U_q[m] if not conservative else abs(U_q[m])
            I = float(T.current(U, Zser(m), conservative=conservative))
            pred[m] = I + (float(margin.get(m, 0.0)) if margin is not None else float(margin_A))
        return pred

    def cross_check(self, margin_A: Union[float, Mapping[int, float]] = 0.0, mode: str = "loo", *,
                    how: str = "median", two_source: Union[str, Iterable[int], None] = "zero_sequence",
                    conservative: bool = True) -> pd.DataFrame:
        """Check the forecast at the calibration tests: the model of the other tests forecasts the current of each
        test from its own pre-fault voltage, additional impedance and line.

        Parameters
        ----------
        margin_A : float or mapping, optional
            Margin per order in A.
        mode : {"loo", "pairwise", "chain"}, optional
            ``"loo"``: model of all other tests; ``"pairwise"``: model of one other test (every pair);
            ``"chain"``: Z_0 of test k, Z_q from the busbar voltages of test j (as a recorded earth fault), forecast
            for test i (every triple; the orders of a source that arises in the fault from test k).
        how, two_source
            See [`source_terms`][groundfault.forecast.model.NetworkModel.source_terms].
        conservative : bool, optional
            True: magnitudes of U_q and U_s added (as in the forecast); False: phasor sum.

        Returns
        -------
        pandas.DataFrame
            One row per target test, model and order (``order``) plus a row ``I_H`` with the harmonic content (rest
            of the model tests included): ``mode``, ``target``, ``model``, ``Z_F_Ohm``, ``order``, ``kind``,
            ``I_measured_A``, ``I_forecast_A``, ``deviation_A``, ``ratio``.

        Raises
        ------
        ValueError
            With fewer than two tests (three for ``"chain"``).
        """
        check_option("mode", mode, _MODES)
        tests = [c for c in self.tests if np.isfinite(c.IH_sum) or c.orders]
        if len(tests) < 2:
            raise ValueError(tr("forecast.no_tests"))
        if mode == "chain" and len(tests) < 3:
            raise ValueError(tr("forecast.chain_needs_three"))
        rows = []

        def evaluate(target: Calibration, sub: "NetworkModel", label: str, kinds=("test", "fault")):
            terms = sub.source_terms(orders=None, how=how, two_source=two_source, kinds=kinds)
            ords = [m for m in terms if m in target.orders and finite(target.orders[m].I)]
            pred = self._predict(terms, {m: target.orders[m].U_q for m in ords}, target.series_impedance, margin_A,
                                 conservative, ords)
            rows.extend(_check_rows(mode, target.name, label, abs(complex(target.Z_F)), terms,
                                    {m: abs(target.orders[m].I) for m in ords}, pred, target.IH_sum,
                                    _rest_of(sub, pred)))

        if mode == "loo":
            for t in tests:
                others = [c.name for c in tests if c.name != t.name]
                evaluate(t, self.subset(names=others, kinds=("test",)), ", ".join(others))
        elif mode == "pairwise":
            for t in tests:
                for s in tests:
                    if s.name != t.name:
                        evaluate(t, self.subset(names=[s.name]), s.name)
        else:
            for k in tests:
                for j in tests:
                    if j.name == k.name:
                        continue
                    for i in tests:
                        if i.name in (k.name, j.name):
                            continue
                        sub = self.subset(names=[k.name])
                        try:
                            sub.add_fault(_fault_data_of(j), z0=k.name, two_source=two_source)
                        except ValueError:
                            continue
                        evaluate(i, sub, "%s → %s" % (k.name, j.name), kinds=("fault",))
        return pd.DataFrame(rows)

    def verify(self, data: FaultData, margin_A: Union[float, Mapping[int, float]] = 0.0, *,
               Z_F: Optional[complex] = None, line: Any = None, how: str = "median",
               two_source: Union[str, Iterable[int], None] = "zero_sequence",
               conservative: bool = True) -> pd.DataFrame:
        """Check the model at a measurement that is not part of it – e.g. a staged fault test at a location in the
        network: forecast from its pre-fault busbar voltage, its fault impedance and its line, compared with its
        measured fault current (magnitudes per order).

        Parameters
        ----------
        data : FaultData
            Measurement with fault current (``data.I``, magnitudes suffice) and busbar voltages before the fault.
        margin_A : float or mapping, optional
            Margin per order in A.
        Z_F : complex, optional
            Fault impedance in Ω (default ``data.Z_F``, else 0).
        line : Line, mapping or list, optional
            Line to the fault location (default ``data.line``).
        how, two_source, conservative
            See [`cross_check`][groundfault.forecast.model.NetworkModel.cross_check].

        Returns
        -------
        pandas.DataFrame
            Rows as [`cross_check`][groundfault.forecast.model.NetworkModel.cross_check] with ``mode`` =
            ``"verify"``.

        Raises
        ------
        ValueError
            Without a fault current in ``data``.
        """
        if not data.I:
            raise ValueError(tr("forecast.verify_no_current", name=data.name))
        line = as_line(line) if line is not None else data.line
        zf = complex(Z_F if Z_F is not None else (data.Z_F if data.Z_F is not None else 0.0))
        terms = self.source_terms(orders=None, how=how, two_source=two_source)
        pf = phase_factors(data.faulted_phase)
        Uq = {m: source_voltage(pf, data.U_pre[m]) for m in data.U_pre}
        ords = [m for m in terms if m in data.I and m in Uq]
        pred = self._predict(terms, Uq, lambda m: zf + (line.Zq(m) if line is not None else 0j), margin_A,
                             conservative, ords)
        return pd.DataFrame(_check_rows("verify", data.name, self.name or "model", abs(zf), terms,
                                        {m: abs(data.I[m]) for m in ords}, pred, data.IH_sum, _rest_of(self, pred)))

    def fault_check(self, margin_A: Union[float, Mapping[int, float]] = 0.0, *, Z_F: complex = 0.0,
                    how: str = "median", two_source: Union[str, Iterable[int], None] = "zero_sequence",
                    conservative: bool = True) -> pd.DataFrame:
        """Check the forecast at every recorded earth fault with an estimated fault current: the model of all other
        earth faults forecasts it from its own pre-fault voltage and the fault impedance ``Z_F`` (0 = the largest
        current – the fault impedance of a natural earth fault is not known).

        Parameters
        ----------
        margin_A : float or mapping, optional
            Margin per order in A.
        Z_F : complex, optional
            Fault impedance of the forecast in Ω.
        how, two_source, conservative
            See [`cross_check`][groundfault.forecast.model.NetworkModel.cross_check].

        Returns
        -------
        pandas.DataFrame
            Rows as [`cross_check`][groundfault.forecast.model.NetworkModel.cross_check] with ``mode`` =
            ``"fault_check"``; ``I_measured_A`` is the estimated current (``I_estimated_method`` per row).

        Raises
        ------
        ValueError
            Without a recorded earth fault with estimated currents.
        """
        faults = [c for c in self.faults if c.currents]
        if not faults:
            raise ValueError(tr("forecast.no_fault_currents"))
        rows = []
        for c in faults:
            sub = self.subset(names=[x.name for x in self.calibrations if x.name != c.name])
            if not sub.tests:
                continue
            terms = sub.source_terms(orders=None, how=how, two_source=two_source)
            ords = [m for m in terms if m in c.currents and m in c.U_q]
            pred = self._predict(terms, c.U_q, lambda m: complex(Z_F) + (c.line.Zq(m) if c.line is not None else 0j),
                                 margin_A, conservative, ords)
            part = _check_rows("fault_check", c.name, ", ".join(sub.names), abs(complex(Z_F)), terms,
                               {m: abs(c.currents[m]) for m in ords}, pred, float("nan"), 0.0)
            for r in part:
                r["I_estimated_method"] = c.current_method.get(r["order"], "") if isinstance(r["order"], int) else ""
            rows.extend(part)
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------------------------ tables
    def table(self) -> pd.DataFrame:
        """Sequence impedances per earth fault and order.

        Returns
        -------
        pandas.DataFrame
            ``name``, ``kind``, ``time``, ``faulted_phase``, ``Z_F_Ohm``, ``line_name`` (tests in the network),
            ``order``, magnitude and angle of
            ``Z0``, ``Z1``, ``Z2``, ``Zq`` (``…_Ohm``, ``…_angle_deg``), ``U_q_V``, ``dU0_V``, ``I_measured_A``,
            ``I_estimated_A`` with ``I_estimated_method``, with coil currents ``Y0_net_S`` and – with the
            transformer node – ``Z_up`` and ``Z_down`` (positive sequence).
        """
        rows = []
        for c in self.calibrations:
            for m, e in sorted(c.orders.items()):
                r = dict(name=c.name, kind=c.kind, time=c.time, faulted_phase=c.faulted_phase,
                         Z_F_Ohm=abs(c.Z_F) if c.Z_F is not None else float("nan"),
                         line_name=(c.line.name or "✓") if c.line is not None else "", order=m)
                for key, z in (("Z0", e.Z0), ("Z1", e.Z1), ("Z2", e.Z2), ("Zq", e.Zq)):
                    r[key + "_Ohm"] = abs(z)
                    r[key + "_angle_deg"] = math.degrees(np.angle(z))
                r.update(U_q_V=abs(e.U_q), dU0_V=abs(e.dU0),
                         I_measured_A=abs(e.I) if finite(e.I) else float("nan"),
                         I_estimated_A=abs(c.currents[m]) if m in c.currents else e.I_estimated,
                         I_estimated_method=c.current_method.get(m, ""))
                if e.Y0_net is not None:
                    r.update(Y0_net_S=abs(e.Y0_net), Y0_net_angle_deg=math.degrees(np.angle(e.Y0_net)))
                if e.Z_up is not None:
                    zd = e.Z_down("pos")
                    r.update(Z_up_Ohm=abs(e.Z_up), Z_up_angle_deg=math.degrees(np.angle(e.Z_up)),
                             Z_down_Ohm=abs(zd), Z_down_angle_deg=math.degrees(np.angle(zd)),
                             G_down_S=(1 / zd).real, B_down_S=(1 / zd).imag)
                rows.append(r)
        df = pd.DataFrame(rows)
        if len(df) and not df["line_name"].astype(bool).any():
            df = df.drop(columns="line_name")
        return df

    def source_table(self, **kwargs) -> pd.DataFrame:
        """The model per order (arguments as [`source_terms`][groundfault.forecast.model.NetworkModel.source_terms]).

        Returns
        -------
        pandas.DataFrame
            ``order``, ``kind``, ``Zq_Ohm``, ``Zq_angle_deg``, ``Us_V``, ``Us_angle_deg``, ``I_constant_A``, ``n``,
            ``residual_pct``, ``calibrations``.
        """
        rows = []
        for m, T in self.source_terms(**kwargs).items():
            rows.append(dict(order=m, kind=T.kind, Zq_Ohm=abs(T.Zq), Zq_angle_deg=math.degrees(np.angle(T.Zq)),
                             Us_V=abs(T.Us), Us_angle_deg=math.degrees(np.angle(T.Us)) if abs(T.Us) else float("nan"),
                             I_constant_A=T.I_constant, n=T.n, residual_pct=100 * T.residual,
                             calibrations=", ".join(T.calibrations)))
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------------------------ persistence
    def to_dict(self) -> Dict[str, Any]:
        """The model as a JSON-serialisable dictionary."""
        from .. import __version__
        cals = []
        for c in self.calibrations:
            cals.append(dict(
                name=c.name, kind=c.kind, time=c.time, faulted_phase=c.faulted_phase, Z_F=cx(c.Z_F),
                Iw=none_if_nan(c.Iw), Iv=none_if_nan(c.Iv), I_C=none_if_nan(c.I_C), U0=none_if_nan(c.U0),
                IH_sum=none_if_nan(c.IH_sum), reference=c.reference, file=c.file, meta=json_safe(c.meta),
                hints=list(c.hints), line=c.line.to_dict() if c.line is not None else None,
                currents={str(m): cx(z) for m, z in sorted(c.currents.items())},
                current_method={str(m): v for m, v in sorted(c.current_method.items())},
                U_q={str(m): cx(z) for m, z in sorted(c.U_q.items())},
                orders={str(m): dict(Z0=cx(e.Z0), Z1=cx(e.Z1), Z2=cx(e.Z2), U_q=cx(e.U_q), dU0=cx(e.dU0),
                                     I=cx(e.I), I_estimated=none_if_nan(e.I_estimated), Z_up=cx(e.Z_up),
                                     Y0_net=cx(e.Y0_net))
                        for m, e in sorted(c.orders.items())}))
        return dict(format=MODEL_FORMAT, version=MODEL_VERSION, name=self.name, description=self.description,
                    saved=_dt.datetime.now().replace(microsecond=0).isoformat(), groundfault=__version__,
                    calibrations=cals)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any], path: str = "") -> "NetworkModel":
        """Model from a dictionary of [`to_dict`][groundfault.forecast.model.NetworkModel.to_dict] (format versions
        1 and 2)."""
        if d.get("format") != MODEL_FORMAT:
            raise ValueError(tr("forecast.not_a_model", path=path, format=d.get("format")))
        if int(d.get("version", 0)) > MODEL_VERSION:
            raise ValueError(tr("forecast.newer_version", path=path, version=d.get("version"),
                                supported=MODEL_VERSION))
        model = cls(d.get("name", ""), d.get("description", ""))

        def opt(z):
            z = from_cx(z)
            return z if finite(z) else None

        for c in d.get("calibrations", []):
            orders = {}
            for m, e in c.get("orders", {}).items():
                orders[int(m)] = OrderEstimate(int(m), from_cx(e["Z0"]), from_cx(e["Z1"]), from_cx(e["Z2"]),
                                               from_cx(e["U_q"]), from_cx(e["dU0"]), I=from_cx(e.get("I")),
                                               I_estimated=fnum(e.get("I_estimated")), Z_up=opt(e.get("Z_up")),
                                               Y0_net=opt(e.get("Y0_net")))
            zf = from_cx(c.get("Z_F"))
            Uq = {int(m): from_cx(z) for m, z in (c.get("U_q") or {}).items()}
            if not Uq:                                               # version 1: the orders of the model
                Uq = {m: e.U_q for m, e in orders.items()}
            model.calibrations.append(Calibration(
                name=c["name"], kind=c["kind"], time=c.get("time", ""), faulted_phase=c.get("faulted_phase", ""),
                Z_F=zf if finite(zf) else None, orders=orders, Iw=fnum(c.get("Iw")), Iv=fnum(c.get("Iv")),
                I_C=fnum(c.get("I_C")), U0=fnum(c.get("U0")), IH_sum=fnum(c.get("IH_sum")),
                reference=c.get("reference", ""), file=c.get("file", ""), meta=dict(c.get("meta") or {}),
                hints=list(c.get("hints") or []), line=Line.from_dict(c.get("line")),
                currents={int(m): from_cx(z) for m, z in (c.get("currents") or {}).items()},
                current_method={int(m): v for m, v in (c.get("current_method") or {}).items()}, U_q=Uq))
        return model

    def save(self, path: str) -> str:
        """Save the model as a JSON file (folders are created); returns the path."""
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)
        return path

    @classmethod
    def load(cls, path: str) -> "NetworkModel":
        """Read a model file."""
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f), path)


# ============================================================================================ helpers
def _check_rows(mode: str, target: str, model: str, Z_F: float, terms: Mapping[int, SourceTerm],
                measured: Mapping[int, float], pred: Mapping[int, float], IH_measured: float,
                rest: float) -> List[Dict[str, Any]]:
    """Rows of a check: per order and – with a measured harmonic content – the total I_H."""
    rows = []
    for m, Ip in pred.items():
        Im = float(measured[m])
        rows.append(dict(mode=mode, target=target, model=model, Z_F_Ohm=Z_F, order=m, kind=terms[m].kind,
                         I_measured_A=Im, I_forecast_A=Ip, deviation_A=Ip - Im,
                         ratio=Ip / Im if Im > 0 else float("nan")))
    if np.isfinite(IH_measured) and pred:
        IH = math.sqrt(sum(v ** 2 for v in pred.values()) + rest ** 2)
        rows.append(dict(mode=mode, target=target, model=model, Z_F_Ohm=Z_F, order="I_H", kind="",
                         I_measured_A=IH_measured, I_forecast_A=IH, deviation_A=IH - IH_measured,
                         ratio=IH / IH_measured if IH_measured else float("nan")))
    return rows


def _rest_of(model: NetworkModel, pred: Mapping[int, float]) -> float:
    rest = [c.rest_A(pred) for c in model.tests]
    return max([v for v in rest if np.isfinite(v)] or [0.0])


def _upstream_of(data: FaultData, m: int) -> Optional[complex]:
    z = (getattr(data, "Z_up", None) or {}).get(m)
    return complex(z) if z is not None and finite(z) else None


def _fault_data_of(c: Calibration) -> FaultData:
    """The busbar voltages of a calibration as fault data (for the learning chain): U_pre and U_fault are rebuilt
    from U_q and the sequence impedances – only the ratios ΔU_s/ΔU_0 and U_q matter for an update."""
    pf = phase_factors(c.faulted_phase)
    U_pre, U_fault, I = {}, {}, {}
    for m, e in c.orders.items():
        # ΔU_s = Z_s·I/(3·p_s); the pre-fault voltage only in the natural sequence (gives the same U_q)
        dU = {"zero": e.Z0 * e.I / (3 * pf["zero"]), "pos": e.Z1 * e.I / (3 * pf["pos"]),
              "neg": e.Z2 * e.I / (3 * pf["neg"])}
        seq = natural_sequence(m)
        pre = {s: 0j for s in SEQ}
        pre[seq] = -e.U_q / pf[seq]
        U_pre[m] = pre
        U_fault[m] = {s: pre[s] + dU[s] for s in SEQ}
        I[m] = e.I
    return FaultData(name=c.name, kind="fault", U_pre=U_pre, U_fault=U_fault, faulted_phase=c.faulted_phase,
                     I=I, time=c.time, Iw=c.Iw, Iv=c.Iv, I_C=c.I_C, U0=c.U0, IH_sum=c.IH_sum, file=c.file)
