# -*- coding: utf-8 -*-
"""Line between the busbar and a fault location in the network.

A fault behind a line adds the series impedances of the line to the fault loop in all three sequence systems:

    Z_qL,m = (2·Z_1L,m + Z_0L,m)/3,   Z_2L = Z_1L

Per segment i (length l_i) the per-length values enter in one of two forms:

* **per order** (``orders`` of a [`LineSegment`][groundfault.forecast.line.LineSegment]): R'_1, X'_1, R'_0, X'_0 at
  m·50 Hz – from a line-parameter calculation at that frequency or from a measurement –,
  Z_kL,m = Σ l_i·(R'_k,i(m) + j·X'_k,i(m));
* **at 50 Hz** for every other order: the resistance independent of the frequency, the reactance proportional to m,
  Z_kL,m = Σ l_i·(R'_k,i + j·m·X'_k,i).

The 50-Hz form is an approximation in two opposite directions: the resistance rises with frequency (skin effect, earth
return, currents in bonded cable sheaths), which it underestimates, while the reactance of earth-return paths (overhead
lines in the zero sequence) and of cables with bonded sheaths rises less than proportionally, which it overestimates.
Which effect dominates depends on the line – a forecast behind a line with the 50-Hz values is therefore not on the
safe side by construction, and the orders of interest should get their own values. The loop contribution of the whole
line can also be given per order (``loop`` of a [`Line`][groundfault.forecast.line.Line]), e.g. measured from a
recorded earth fault behind the line
([`NetworkModel.line_from_fault`][groundfault.forecast.model.NetworkModel.line_from_fault]); at those orders it
replaces the segments. The shunt capacitance along the line is not part of the series model; it holds while the line is
short compared with a quarter wavelength at the order considered
([`Line.wavelength_fraction`][groundfault.forecast.line.Line.wavelength_fraction]).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from ..i18n import tr
from ._util import cx

__all__ = ["LineSegment", "Line"]

_F1 = 50.0
_FIELDS = ("R1", "X1", "R0", "X0")


def _complex(v: Any) -> complex:
    """Complex number from a number, ``[re, im]``, ``(re, im)`` or ``{"re": …, "im": …}``."""
    if isinstance(v, Mapping):
        return complex(float(v["re"]), float(v["im"]))
    if isinstance(v, (list, tuple)):
        if len(v) != 2:
            raise ValueError(tr("forecast.line_complex", value=v))
        return complex(float(v[0]), float(v[1]))
    return complex(v)


@dataclass
class LineSegment:
    """One section of a line (cable or overhead line).

    Attributes
    ----------
    length_km : float
        Length in km.
    R1, X1 : float
        Positive-sequence resistance and reactance in Ω/km at 50 Hz.
    R0, X0 : float
        Zero-sequence resistance and reactance in Ω/km at 50 Hz (cables: with the return through sheath and earth
        as in the data of the cable).
    C1_uF : float, optional
        Positive-sequence (operating) capacitance in µF/km – only for the wavelength check.
    name : str
        Name (type, section).
    orders : dict, optional
        Values at single orders, ``{m: dict(R1=…, X1=…, R0=…, X0=…)}`` in Ω/km at m·50 Hz – the reactance at that
        frequency, not divided by m. Orders not listed use the 50-Hz values (resistance constant, reactance ∝ m).
    """

    length_km: float
    R1: float
    X1: float
    R0: float
    X0: float
    C1_uF: Optional[float] = None
    name: str = ""
    orders: Dict[int, Dict[str, float]] = field(default_factory=dict)

    def __post_init__(self):
        clean: Dict[int, Dict[str, float]] = {}
        for m, vals in dict(self.orders or {}).items():
            vals = dict(vals)
            missing = [k for k in _FIELDS if k not in vals]
            if missing:
                raise ValueError(tr("forecast.line_order_fields", order=m, fields=", ".join(missing)))
            clean[int(m)] = {k: float(vals[k]) for k in _FIELDS}
        self.orders = clean

    def Z1(self, m: int) -> complex:
        """Positive-sequence impedance of the segment at order m in Ω."""
        o = self.orders.get(int(m))
        if o is not None:
            return self.length_km * complex(o["R1"], o["X1"])
        return self.length_km * complex(self.R1, m * self.X1)

    def Z0(self, m: int) -> complex:
        """Zero-sequence impedance of the segment at order m in Ω."""
        o = self.orders.get(int(m))
        if o is not None:
            return self.length_km * complex(o["R0"], o["X0"])
        return self.length_km * complex(self.R0, m * self.X0)

    def velocity_km_s(self) -> Optional[float]:
        """Propagation velocity 1/√(L'·C') in km/s (None without C1_uF)."""
        if not self.C1_uF or self.X1 <= 0:
            return None
        L = self.X1 / (2 * math.pi * _F1)               # H/km
        C = self.C1_uF * 1e-6                           # F/km
        return 1.0 / math.sqrt(L * C)

    def to_dict(self) -> Dict[str, Any]:
        """JSON form."""
        d: Dict[str, Any] = dict(length_km=self.length_km, R1=self.R1, X1=self.X1, R0=self.R0, X0=self.X0,
                                 C1_uF=self.C1_uF, name=self.name)
        if self.orders:
            d["orders"] = {str(m): dict(v) for m, v in sorted(self.orders.items())}
        return d


class Line:
    """Line between the busbar and the fault location – one or more segments in series.

    Parameters
    ----------
    segments : iterable of LineSegment or mapping
        Segments; a mapping gives the fields of [`LineSegment`][groundfault.forecast.line.LineSegment]
        (``length_km``, ``R1``, ``X1``, ``R0``, ``X0``, optional ``C1_uF``, ``name``, ``orders``).
    name : str, optional
        Name of the line or the fault location.
    loop : mapping, optional
        Loop contribution Z_qL,m = (2·Z_1L,m + Z_0L,m)/3 of the whole line at single orders in Ω,
        ``{m: complex | [re, im] | {"re": …, "im": …}}`` – e.g. measured from a recorded earth fault behind the line
        ([`NetworkModel.line_from_fault`][groundfault.forecast.model.NetworkModel.line_from_fault]). At these orders
        it replaces the segments.

    Examples
    --------
    >>> line = Line([dict(length_km=4.0, R1=0.125, X1=0.11, R0=0.5, X0=0.4)], "Example feeder")
    >>> round(abs(line.Zq(5)), 3)
    4.253
    >>> line = Line([dict(length_km=4.0, R1=0.125, X1=0.11, R0=0.5, X0=0.4,
    ...                   orders={5: dict(R1=0.13, X1=0.5, R0=0.9, X0=1.6)})], "Example feeder")
    >>> z = line.Zq(5)
    >>> round(z.real, 4), round(z.imag, 4)
    (1.5467, 3.4667)
    >>> line.source(5), line.source(7)
    ('orders', '50Hz')
    """

    def __init__(self, segments: Iterable[Any] = (), name: str = "", loop: Optional[Mapping[Any, Any]] = None):
        self.segments: List[LineSegment] = [s if isinstance(s, LineSegment) else LineSegment(**dict(s))
                                            for s in segments]
        if not self.segments:
            raise ValueError(tr("forecast.line_empty"))
        self.name = name
        self.loop: Dict[int, complex] = {int(m): _complex(v) for m, v in dict(loop or {}).items()}

    @classmethod
    def from_impedances(cls, Z1: complex, Z0: complex, name: str = "",
                        orders: Optional[Mapping[Any, Tuple[Any, Any]]] = None,
                        loop: Optional[Mapping[Any, Any]] = None) -> "Line":
        """Line from its total positive- and zero-sequence impedance in Ω (one segment of 1 km).

        Parameters
        ----------
        Z1, Z0 : complex
            Total impedances at 50 Hz.
        name : str, optional
            Name.
        orders : mapping, optional
            Total impedances at single orders, ``{m: (Z1_m, Z0_m)}`` in Ω at m·50 Hz (complex or ``[re, im]``).
        loop : mapping, optional
            Loop contribution per order, as for [`Line`][groundfault.forecast.line.Line].
        """
        Z1, Z0 = _complex(Z1), _complex(Z0)
        per = {}
        for m, (z1, z0) in dict(orders or {}).items():
            z1, z0 = _complex(z1), _complex(z0)
            per[int(m)] = dict(R1=z1.real, X1=z1.imag, R0=z0.real, X0=z0.imag)
        return cls([LineSegment(1.0, Z1.real, Z1.imag, Z0.real, Z0.imag, name=name, orders=per)], name, loop=loop)

    def __repr__(self) -> str:
        return "Line(%r, %d segments, %.3g km)" % (self.name, len(self.segments), self.length_km)

    @property
    def length_km(self) -> float:
        """Total length in km."""
        return float(sum(s.length_km for s in self.segments))

    def Z1(self, m: int) -> complex:
        """Positive-sequence impedance Z_1L,m in Ω (= Z_2L,m) from the segments."""
        return complex(sum(s.Z1(m) for s in self.segments))

    def Z0(self, m: int) -> complex:
        """Zero-sequence impedance Z_0L,m in Ω from the segments."""
        return complex(sum(s.Z0(m) for s in self.segments))

    def Zq(self, m: int) -> complex:
        """Contribution of the line to the loop impedance in Ω: ``loop`` at that order, otherwise
        (2·Z_1L,m + Z_0L,m)/3 from the segments."""
        m = int(m)
        if m in self.loop:
            return self.loop[m]
        return (2 * self.Z1(m) + self.Z0(m)) / 3

    def source(self, m: int) -> str:
        """Where the value at order m comes from: ``"loop"`` (given for the whole line), ``"orders"`` (every
        segment has values of that order), ``"mixed"`` (some segments) or ``"50Hz"`` (50-Hz values, reactance ∝ m)."""
        m = int(m)
        if m in self.loop:
            return "loop"
        have = [m in s.orders for s in self.segments]
        if all(have):
            return "orders"
        return "mixed" if any(have) else "50Hz"

    def orders_given(self) -> List[int]:
        """Orders with values of their own for the whole line (``loop`` or every segment)."""
        cand = set(self.loop) | {m for s in self.segments for m in s.orders}
        return sorted(m for m in cand if self.source(m) in ("loop", "orders"))

    def wavelength_fraction(self, m: int) -> Optional[float]:
        """Electrical length as a fraction of a quarter wavelength at order m, Σ l_i/(λ_i/4) with
        λ_i = v_i/(m·50 Hz) – None if a segment has no capacitance."""
        total = 0.0
        for s in self.segments:
            v = s.velocity_km_s()
            if v is None:
                return None
            total += s.length_km / (v / (m * _F1) / 4.0)
        return total

    def to_dict(self) -> Dict[str, Any]:
        """JSON form."""
        d: Dict[str, Any] = dict(name=self.name, segments=[s.to_dict() for s in self.segments])
        if self.loop:
            d["loop"] = {str(m): cx(z) for m, z in sorted(self.loop.items())}
        return d

    @classmethod
    def from_dict(cls, d: Optional[Mapping[str, Any]]) -> Optional["Line"]:
        """Line from its JSON form (None for None)."""
        if not d:
            return None
        return cls(d.get("segments", []), d.get("name", ""), loop=d.get("loop"))


def as_line(line: Any) -> Optional[Line]:
    """A [`Line`][groundfault.forecast.line.Line], a mapping ``dict(segments=…, name=…, loop=…)`` or a list of
    segments, or None."""
    if line is None or isinstance(line, Line):
        return line
    if isinstance(line, Mapping):
        return Line(line.get("segments", []), line.get("name", ""), loop=line.get("loop"))
    return Line(line)
