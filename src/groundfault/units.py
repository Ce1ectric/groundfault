# -*- coding: utf-8 -*-
"""Units of groundmeas values – the same rules as ``groundmeas.core.units`` (groundmeas ≥ 1.6.1).

groundmeas stores every value as it was entered (``118.1`` with ``"mΩ"``); it is converted only for calculations,
into the SI base unit of its quantity (Ω, A, V, Ωm). This module reproduces the rules of groundmeas 1.6.1 so that
groundfault obtains the same numbers – also without an installed groundmeas (groundmeas needs Python ≥ 3.14). The
tests check the agreement against a reference table generated with groundmeas 1.6.1 and, if groundmeas can be
imported, directly against ``groundmeas.core.units``.

========================  ==========  ===============================================
quantity                  base        units (canonical)
========================  ==========  ===============================================
current                   A           nA, μA, mA, A, kA
voltage                   V           μV, mV, V, kV
resistance                Ω           μΩ, mΩ, Ω, kΩ, MΩ, GΩ, V/A, mV/A
resistivity               Ωm          mΩm, Ωm, kΩm, MΩm, Ωcm
distance                  m           mm, cm, m, km, ft
frequency                 Hz          Hz, kHz
========================  ==========  ===============================================

Accepted spellings: micro as ``µ``, ``μ`` or ``u``; ohm as ``Ω``, ``Ω`` (ohm sign), ``Ohm``, ``ohm``, ``ohms``;
products with or without separator (``Ω·m``, ``Ohm-m``, ``Ohm_meter``); words (``milliohm``, ``kilovolt``);
brackets (``[mV]``); ``K`` for kilo, ``ma``/``kv``. Prefixes are case-sensitive (``m`` milli, ``M`` mega);
``MA``/``MV`` are rejected (typing errors for ``mA``/``mV``). A value without a unit is taken in the base unit; an
unknown unit or a unit of another quantity is not converted (a note is given instead) – as in groundmeas.

Examples
--------
>>> from groundfault import units
>>> units.parse_unit("mOhm")
Unit(symbol='mΩ', quantity='resistance', factor=0.001)
>>> units.to_base(2.5, "kV")
2500.0
>>> units.suitable_unit([0.75, 0.0042], "earth_potential_rise")
('mV', 0.001)
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Iterable, Optional, Tuple, Union

from . import i18n
from .i18n import tr

__all__ = ["Unit", "UnitError", "BASE_UNITS", "QUANTITIES_BY_TYPE", "parse_unit", "to_base", "check_unit",
           "base_unit", "quantities", "suitable_unit", "GROUNDMEAS_REFERENCE"]

GROUNDMEAS_REFERENCE = "1.6.1"
"""Version of groundmeas whose rules are reproduced here."""

BASE_UNITS: Dict[str, str] = {"current": "A", "voltage": "V", "resistance": "Ω", "resistivity": "Ωm",
                              "distance": "m", "frequency": "Hz"}
"""SI base unit per quantity."""
_PREFIXES: Dict[str, float] = {"n": 1e-9, "μ": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6, "G": 1e9}
_PREFIXES_BY_QUANTITY: Dict[str, str] = {"current": "nμmk", "voltage": "μmk", "resistance": "μmkMG",
                                         "resistivity": "mkM", "frequency": "k"}
QUANTITIES_BY_TYPE: Dict[str, Tuple[str, ...]] = {
    "prospective_touch_voltage": ("voltage",), "touch_voltage": ("voltage",), "earth_potential_rise": ("voltage",),
    "step_voltage": ("voltage",), "transferred_potential": ("voltage",),
    "earth_fault_current": ("current",), "earthing_current": ("current",), "shield_current": ("current",),
    "earthing_resistance": ("resistance",), "earthing_impedance": ("resistance",),
    "soil_resistivity": ("resistivity", "resistance"),
}
"""Quantity (or quantities) of the values per groundmeas ``measurement_type`` (the first one is the default)."""
#: usual units per quantity (choice for new entries, like ``common_units`` in groundmeas)
_USUAL: Dict[str, Tuple[str, ...]] = {"current": ("A", "mA", "kA"), "voltage": ("V", "mV", "kV"),
                                      "resistance": ("Ω", "mΩ", "kΩ"), "resistivity": ("Ωm", "kΩm")}

i18n.register({
    "units.no_unit": {"en": "no unit given", "de": "keine Einheit angegeben"},
    "units.unknown_quantity": {"en": "unknown quantity {quantity!r}", "de": "unbekannte Größe {quantity!r}"},
    "units.unknown_unit": {"en": "unknown unit {unit!r}", "de": "unbekannte Einheit {unit!r}"},
    "units.wrong_quantity": {"en": "{unit!r} is a unit of {quantity}, expected {expected}",
                             "de": "{unit!r} ist eine Einheit für {quantity}, erwartet {expected}"},
    "units.or": {"en": " or ", "de": " oder "},
    "units.no_unit_base": {"en": "no unit – values are taken as {base}",
                           "de": "keine Einheit – Werte gelten als {base}"},
    "units.base_unit": {"en": "base unit", "de": "Basiseinheit"},
    "units.unknown_type": {"en": "unknown measurement_type {type!r}", "de": "unbekannter measurement_type {type!r}"},
})


class UnitError(ValueError):
    """Unknown unit, or a unit of another quantity than expected."""


@dataclass(frozen=True)
class Unit:
    """A unit of a groundmeas value with its quantity and the factor to the SI base unit."""

    symbol: str          #: canonical symbol, e.g. "mΩ", "μV", "Ωm"
    quantity: str        #: current | voltage | resistance | resistivity | distance | frequency
    factor: float        #: value in this unit × factor = value in the base unit

    @property
    def base(self) -> str:
        """SI base unit of the quantity (``"Ω"`` for ``"mΩ"``)."""
        return BASE_UNITS[self.quantity]

    def to_base(self, value: float) -> float:
        """Convert ``value`` (in this unit) into the base unit."""
        return value if self.factor == 1.0 else value * self.factor


def _table() -> Dict[str, Tuple[str, float]]:
    """Canonical symbol → (quantity, factor to the base unit) for all units groundmeas accepts."""
    t: Dict[str, Tuple[str, float]] = {}
    for quantity, base in (("current", "A"), ("voltage", "V"), ("resistance", "Ω"), ("frequency", "Hz")):
        t[base] = (quantity, 1.0)
        for v in _PREFIXES_BY_QUANTITY[quantity]:
            t[v + base] = (quantity, _PREFIXES[v])
    t["Ωm"] = ("resistivity", 1.0)
    for v in _PREFIXES_BY_QUANTITY["resistivity"]:
        t[v + "Ωm"] = ("resistivity", _PREFIXES[v])
    t["Ωcm"] = ("resistivity", 1e-2)
    t.update({"m": ("distance", 1.0), "mm": ("distance", 1e-3), "cm": ("distance", 1e-2), "km": ("distance", 1e3),
              "ft": ("distance", 0.3048), "V/A": ("resistance", 1.0), "mV/A": ("resistance", 1e-3)})
    return t


_TABLE = _table()
_WORDS = ((re.compile(r"ohms?", re.IGNORECASE), "Ω"), (re.compile(r"volts?", re.IGNORECASE), "V"),
          (re.compile(r"amp(?:ere)?s?", re.IGNORECASE), "A"), (re.compile(r"hertz|hz", re.IGNORECASE), "Hz"),
          (re.compile(r"met(?:er|re)s?", re.IGNORECASE), "m"), (re.compile(r"feet|foot", re.IGNORECASE), "ft"),
          (re.compile(r"milli", re.IGNORECASE), "m"), (re.compile(r"micro", re.IGNORECASE), "μ"),
          (re.compile(r"centi", re.IGNORECASE), "c"), (re.compile(r"kilo", re.IGNORECASE), "k"),
          (re.compile(r"mega", re.IGNORECASE), "M"))
_SEPARATOR = re.compile(r"[\s·∙⋅*_.\-]")


def _canonical(text: str) -> str:
    """Normalised spelling: Unicode NFKC, without brackets and separators, words replaced by symbols."""
    e = unicodedata.normalize("NFKC", text).strip()          # ohm sign → Ω, micro sign → μ
    while len(e) >= 2 and e[0] in "[({" and e[-1] in "])}":
        e = e[1:-1].strip()
    for pattern, replacement in _WORDS:
        e = pattern.sub(replacement, e)
    return _SEPARATOR.sub("", e)


def _variants(e: str):
    """Spellings to look up: as given, ``u`` → ``μ``, ``K`` → ``k``, and with a final ``a``/``v`` in upper case."""
    heads = [e]
    if len(e) > 1 and e[0] == "u":
        heads.append("μ" + e[1:])
    if len(e) > 1 and e[0] == "K":
        heads.append("k" + e[1:])
    out = []
    for k in heads:
        out.append(k)
        if k and k[-1] in "av":
            out.append(k[:-1] + k[-1].upper())
    return out


@lru_cache(maxsize=1024)
def _lookup(text: str) -> Optional[Tuple[str, str, float]]:
    """(symbol, quantity, factor) of a spelling, or None if it is not a known unit."""
    for k in _variants(_canonical(text)):
        hits = _TABLE.get(k)
        if hits is not None:
            return k, hits[0], hits[1]
    return None


def _as_tuple(quantities_: Union[str, Iterable[str], None]) -> Tuple[str, ...]:
    """One quantity or several → tuple (None → empty)."""
    if quantities_ is None:
        return ()
    return (quantities_,) if isinstance(quantities_, str) else tuple(quantities_)


def parse_unit(text, quantities_: Union[str, Iterable[str], None] = None) -> Unit:
    """Read a unit as groundmeas 1.6.1 does.

    Parameters
    ----------
    text : str
        The unit as written (``"mOhm"``, ``"[mV]"``, ``"kilovolt"``, ``"Ohm_meter"`` …).
    quantities_ : str or iterable of str, optional
        Expected quantity or quantities (``"voltage"``, ``("resistivity", "resistance")``); a unit of another
        quantity raises [`UnitError`][groundfault.units.UnitError]. None accepts every quantity.

    Returns
    -------
    Unit

    Raises
    ------
    UnitError
        If no unit is given, the unit is unknown or it belongs to another quantity.
    ValueError
        If an expected quantity is unknown.
    """
    if text is None or not str(text).strip():
        raise UnitError(tr("units.no_unit"))
    allowed = _as_tuple(quantities_)
    for g in allowed:
        if g not in BASE_UNITS:
            raise ValueError(tr("units.unknown_quantity", quantity=g))
    t = _lookup(str(text))
    if t is None:
        raise UnitError(tr("units.unknown_unit", unit=text))
    symbol, quantity, factor = t
    if allowed and quantity not in allowed:
        raise UnitError(tr("units.wrong_quantity", unit=text, quantity=quantity, expected=tr("units.or").join(allowed)))
    return Unit(symbol, quantity, factor)


def to_base(value: float, unit, quantities_=None) -> float:
    """Convert ``value`` given in ``unit`` (as written) into the SI base unit (see
    [`parse_unit`][groundfault.units.parse_unit])."""
    return parse_unit(unit, quantities_).to_base(value)


def quantities(type_: Optional[str]) -> Optional[Tuple[str, ...]]:
    """Quantity (or quantities) of a groundmeas ``measurement_type``; None for an unknown type (any quantity)."""
    return QUANTITIES_BY_TYPE.get(str(type_)) if type_ is not None else None


def base_unit(type_: str) -> str:
    """SI base unit of a groundmeas ``measurement_type`` (``""`` for an unknown type)."""
    g = quantities(type_)
    return BASE_UNITS[g[0]] if g else ""


def check_unit(unit, type_: str) -> Optional[str]:
    """Check whether a stored unit can be converted for a ``measurement_type`` (like ``check_unit`` in groundmeas).

    Returns
    -------
    str or None
        None if the unit can be converted, otherwise an explanation (also for a missing unit, whose values are
        taken in the base unit).
    """
    if unit is None or not str(unit).strip():
        return tr("units.no_unit_base", base=base_unit(type_) or tr("units.base_unit"))
    try:
        parse_unit(str(unit), quantities(type_))
    except UnitError as e:
        return str(e)
    return None


def suitable_unit(values_base: Iterable[float], type_: str) -> Tuple[str, float]:
    """Well readable unit for values (in the base unit) of a groundmeas ``measurement_type``.

    One unit for all values (same column, same unit): the prefix with which the largest magnitude lies between 1
    and 1000, chosen from the units usual in groundmeas (A/mA/kA, V/mV/kV, Ω/mΩ/kΩ); below that μ.

    Parameters
    ----------
    values_base : iterable of float
        Values in the base unit (non-finite values and None are ignored).
    type_ : str
        groundmeas ``measurement_type``.

    Returns
    -------
    symbol, factor : str, float
        Unit symbol and its factor to the base unit (value in the unit = value in the base unit / factor).

    Raises
    ------
    ValueError
        For an unknown ``measurement_type``.
    """
    g = quantities(type_)
    if not g:
        raise ValueError(tr("units.unknown_type", type=type_))
    base = BASE_UNITS[g[0]]
    values = [abs(float(w)) for w in values_base if w is not None and math.isfinite(float(w))]
    large = max(values) if values else 0.0
    if large <= 0.0 or g[0] not in _USUAL:
        return base, 1.0
    for symbol in sorted(_USUAL[g[0]], key=lambda s: -parse_unit(s).factor):     # kA, A, mA
        f = parse_unit(symbol).factor
        if large >= f:
            return symbol, f
    micro = "μ" + base
    if micro in _TABLE:
        return micro, _TABLE[micro][1]
    return base, 1.0
