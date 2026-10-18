# -*- coding: utf-8 -*-
"""Helpers of the forecast package: complex numbers in JSON, aggregation, phase factors."""
from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

import numpy as np

from ..equivalent_source import phase_factor
from ..i18n import tr

SEQ = ("zero", "pos", "neg")
"""The sequence systems in the order zero, positive, negative."""


def cx(z) -> Optional[dict]:
    """JSON form of a complex number (None for None/NaN)."""
    if z is None:
        return None
    z = complex(z)
    if not (math.isfinite(z.real) and math.isfinite(z.imag)):
        return None
    return {"re": z.real, "im": z.imag}


def from_cx(d) -> complex:
    """Complex number from its JSON form (NaN for None)."""
    if d is None:
        return complex("nan")
    if isinstance(d, (int, float, complex)):
        return complex(d)
    return complex(d["re"], d["im"])


def finite(z) -> bool:
    """True for a finite complex (or real) number."""
    try:
        z = complex(z)
    except (TypeError, ValueError):
        return False
    return math.isfinite(z.real) and math.isfinite(z.imag)


def fnum(x) -> float:
    """Float of a value (NaN for None and non-numbers)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return x


def none_if_nan(x):
    """JSON form of a float (None for NaN)."""
    x = fnum(x)
    return x if math.isfinite(x) else None


def complex_aggregate(values: Sequence[complex], how: str) -> complex:
    """Median (component-wise), mean or last of complex values; NaN values are ignored."""
    v = [complex(x) for x in values if finite(x)]
    if not v:
        return complex("nan")
    if how == "latest":
        return v[-1]
    a = np.asarray(v)
    if how == "mean":
        return complex(a.mean())
    return complex(float(np.median(a.real)), float(np.median(a.imag)))


def parallel(a: complex, b: complex) -> complex:
    """Parallel connection a ∥ b."""
    return a * b / (a + b)


def phase_factors(phase: str) -> Dict[str, complex]:
    """Phase factors p_s of the faulted phase (L1: 1, 1, 1; L2: 1, a², a; L3: 1, a, a²; unknown: L1)."""
    return {s: phase_factor(s, phase) for s in SEQ}


def source_voltage(pf: Mapping[str, complex], U: Mapping[str, complex]) -> complex:
    """Source voltage U_q = −Σ p_s·U_s – the pre-fault voltage of the faulted phase in the orientation of the angle
    method."""
    return -sum(pf[s] * U.get(s, 0.0) for s in SEQ)


def orders_text(orders: Iterable[int]) -> str:
    """``"order 5"`` or ``"orders 5, 7"`` in the output language."""
    lst = sorted({int(m) for m in orders})
    return tr("forecast.order_list" if len(lst) > 1 else "forecast.order_single", orders=", ".join(map(str, lst)))


def order_of(column) -> Optional[int]:
    """Harmonic order from a column name (``5``, ``"5"``, ``"H5"``, ``"U_L1_H5"``, ``"5.0"``): the last integer."""
    if isinstance(column, (int, np.integer)):
        return int(column)
    if isinstance(column, float) and float(column).is_integer():
        return int(column)
    m = re.search(r"(\d+)(?:\.0+)?\s*$", str(column))
    return int(m.group(1)) if m else None


def json_safe(o: Any) -> Any:
    """JSON-serialisable copy (complex numbers as ``{"re", "im"}``, NumPy scalars as Python numbers)."""
    if isinstance(o, Mapping):
        return {str(k): json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [json_safe(v) for v in o]
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, complex):
        return cx(o)
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    return str(o)
