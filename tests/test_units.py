# -*- coding: utf-8 -*-
"""Units as in groundmeas 1.6.1 (groundmeas.core.units): reference table generated with groundmeas (322 spellings,
165 check pairs) and – if groundmeas can be imported – a direct comparison; choice of well readable units; messages in
English and German."""
import json
import math
import os
from pathlib import Path

import pytest

from groundfault import i18n, units

REF = json.loads(Path(os.path.dirname(__file__), "data", "units_groundmeas_1_6_1.json").read_text(
                     encoding="utf-8"))


def _ours(s):
    try:
        e = units.parse_unit(s)
        return [e.symbol, e.quantity, e.factor]
    except units.UnitError:
        return None


def test_spellings_as_groundmeas_1_6_1():
    assert REF["groundmeas"] == units.GROUNDMEAS_REFERENCE
    different = {s: (_ours(s), target) for s, target in REF["spellings"].items()
                 if (_ours(s) is None) != (target is None)
                 or (target is not None and (_ours(s)[:2] != target[:2] or not math.isclose(_ours(s)[2], target[2])))}
    assert not different
    assert len(REF["spellings"]) > 300


def test_check_and_base_unit_per_type_as_groundmeas():
    for u, type_, ok in REF["check_unit"]:
        assert (units.check_unit(u, type_) is None) == ok, (u, type_)
    for type_, base in REF["base"].items():
        assert units.base_unit(type_) == base


@pytest.mark.parametrize("text,symbol,factor", [
    ("mOhm", "mΩ", 1e-3), ("MΩ", "MΩ", 1e6), ("µV", "μV", 1e-6), ("uA", "μA", 1e-6), ("Ohm_meter", "Ωm", 1.0),
    ("[mV]", "mV", 1e-3), ("kΩm", "kΩm", 1e3), ("Ωcm", "Ωcm", 1e-2), ("Ω", "Ω", 1.0)])
def test_examples(text, symbol, factor):
    e = units.parse_unit(text)
    assert e.symbol == symbol and math.isclose(e.factor, factor)
    # earlier error of the tool: lower-casing turned MΩ (mega) into mΩ (milli)


def test_rejected_spellings_and_wrong_quantity():
    for s in ("MA", "MV", "xyz", "", None):
        with pytest.raises(units.UnitError):
            units.parse_unit(s)
    with pytest.raises(units.UnitError, match="current"):
        units.parse_unit("mA", "voltage")
    assert "keine Einheit" in units.check_unit("", "earth_potential_rise")
    assert units.check_unit("mV", "earth_potential_rise") is None
    assert units.check_unit("A", "touch_voltage") is not None


def test_directly_against_groundmeas():
    gm_units = pytest.importorskip("groundmeas.core.units")
    for s in REF["spellings"]:
        try:
            e = gm_units.parse_unit(s)
            target = [e.symbol, e.quantity, e.factor]
        except gm_units.UnitError:
            target = None
        actual = _ours(s)
        assert (actual is None) == (target is None), s
        if target is not None:
            assert actual[:2] == target[:2] and math.isclose(actual[2], target[2]), s


@pytest.mark.parametrize("values,type_,symbol", [
    ([0.75, 0.0042, 0.0016], "earth_potential_rise", "mV"), ([9.33, 0.233], "earth_potential_rise", "V"),
    ([40.0, 0.5], "earth_fault_current", "A"), ([2.0, 0.06], "shield_current", "A"),
    ([0.9995, 0.043], "shield_current", "mA"), ([1500.0], "earth_fault_current", "kA"),
    ([0.0004], "touch_voltage", "μV"), ([], "touch_voltage", "V"), ([0.25], "earthing_impedance", "mΩ")])
def test_suitable_unit(values, type_, symbol):
    s, f = units.suitable_unit(values, type_)
    assert s == symbol
    assert units.parse_unit(s).factor == f
    if values:
        assert 1.0 <= max(abs(w) for w in values) / f < 1000.0 or s.startswith("μ")
    with pytest.raises(ValueError):
        units.suitable_unit([1.0], "no_type")


def test_messages_in_english_and_german():
    with i18n.language("en"):
        assert units.check_unit("", "earth_potential_rise") == "no unit – values are taken as V"
        assert units.check_unit(None, "unknown_type") == "no unit – values are taken as base unit"
        assert units.check_unit("MA", "earth_fault_current") == "unknown unit 'MA'"
        with pytest.raises(units.UnitError, match="'mA' is a unit of current, expected voltage or resistance"):
            units.parse_unit("mA", ("voltage", "resistance"))
        with pytest.raises(ValueError, match="unknown measurement_type 'no_type'"):
            units.suitable_unit([1.0], "no_type")
    assert units.check_unit(None, "unknown_type") == "keine Einheit – Werte gelten als Basiseinheit"
    with pytest.raises(units.UnitError, match="'mA' ist eine Einheit für current, erwartet voltage oder resistance"):
        units.parse_unit("mA", ("voltage", "resistance"))
    for lang in ("en", "de"):
        assert [k for k in i18n.missing_keys(lang) if k.startswith("units.")] == []
