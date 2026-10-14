# -*- coding: utf-8 -*-
"""Notebook generator (tools/make_notebooks.py): demo only in the example notebooks, the options that the
notebooks interpret themselves are checked there (former or unknown values raise instead of being ignored), and the
committed notebooks are exactly what the generator writes."""
import glob
import importlib.util
import os
import re

import pytest

from groundfault import legacy

nbformat = pytest.importorskip("nbformat")
HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location("make_notebooks", os.path.join(os.path.dirname(HERE), "tools",
                                                                                 "make_notebooks.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _code(nb):
    return [c.source for c in nb.cells if c.cell_type == "code"]


@pytest.mark.parametrize("lang", ["en", "de"])
def test_demo_only_with_example(generator, lang):
    for make in (generator.measurement_notebook, generator.campaign_notebook):
        for example in (False, True):
            demo = [re.match(r"DEMO\s*=\s*(\w+)", line).group(1) for cell in _code(make(lang, example))
                    for line in cell.splitlines() if re.match(r"DEMO\s*=", line)]
            assert demo == [str(example)], (make.__name__, example)


def _statement(cells, start):
    """The (possibly wrapped) statement of the generated code that begins with ``start``."""
    for cell in cells:
        i = cell.find(start)
        if i >= 0:
            j, depth = i, 0
            while True:
                depth += {"(": 1, ")": -1}.get(cell[j], 0)
                j += 1
                if depth == 0 and cell[j - 1] == ")":
                    return cell, cell[i:j]
    raise AssertionError(start)


@pytest.mark.parametrize("lang", ["en", "de"])
def test_options_interpreted_by_the_notebooks_are_checked(generator, lang):
    cells = _code(generator.campaign_notebook(lang, True)) + _code(generator.measurement_notebook(lang, True))
    checks = {'legacy.check_option("GROUNDMEAS_EXPORT"': ("GROUNDMEAS_EXPORT ==", dict(GROUNDMEAS_EXPORT="ersetzen")),
              'legacy.check_keys("RESISTIVE"': ('RESISTIVE.get("from_ll"', dict(RESISTIVE=dict(U_thd95_V=300.0,
                                                                                               aus_ll=True))),
              'legacy.check_keys("MEASUREMENTS"': ('m["measurement"]', dict(m=dict(name="M1", messung="SUB_0", Z=0.0))),
              'legacy.check_option("IG_CHOICE"': ('IG_CHOICE == "max"', dict(IG_CHOICE="maximal"))}
    for start, (use, values) in checks.items():
        cell, statement = _statement(cells, start)
        assert cell.index(start) < cell.index(use), start                  # checked before the value is used
        with pytest.raises(ValueError, match="frühere Name|former name|nicht zulässig|not allowed"):
            exec(statement, dict(legacy=legacy, **values))
    assert sum(c.count('legacy.check_option("GROUNDMEAS_EXPORT"') for c in cells) == 2      # both notebooks


#: the parameters each user defines and their values in the published notebooks: not set
USER_PARAMETERS = {"LIMITS": (), "U_TP": None, "F_FACTOR": None, "REFERENCE_CURRENT": None, "R_TYPICAL": None,
                   "UNCERTAINTY_I": 0.0, "PQ_SAFETY_FACTOR": 1.0}


@pytest.mark.parametrize("lang", ["en", "de"])
@pytest.mark.parametrize("example", [False, True])
def test_no_limits_or_safety_factors_in_the_notebooks(generator, lang, example):
    """The notebooks contain no limits, U_Tp, F, reference current, uncertainty margins, safety factors or typical
    range of r – one configuration cell names them, not set, and the evaluation passes them on."""
    for make, extra in ((generator.measurement_notebook, {"UNCERTAINTY_U": 0.0}), (generator.campaign_notebook, {})):
        nb = make(lang, example)
        cells = _code(nb)
        config = [c for c in cells if "LIMITS            =" in c]
        assert len(config) == 1, make.__name__                                   # one place per notebook
        values = {}
        for line in config[0].splitlines():
            m = re.match(r"([A-Z_]+)\s*=\s*([^#]+?)\s*(#.*)?$", line)
            if m and m.group(1) in {**USER_PARAMETERS, **extra}:
                values[m.group(1)] = eval(m.group(2))
        assert values == {**USER_PARAMETERS, **extra}, make.__name__
        text = "\n".join(c.source for c in nb.cells)
        for preset in ("60.0, 90.0, 120.0", "(60, 90, 120)", "75.0", "1,3 bei", "1.3 for", "0.2–0.7", "0,2–0,7",
                       "0.2, 0.7", "uncertainty_I=0.05", "R1_km=0.31", "rho_E=100"):
            assert preset not in text, (make.__name__, preset)
    measurement = "\n".join(_code(generator.measurement_notebook(lang, example)))
    assert "ires_limits=LIMITS, u_tp=U_TP, f_factor=F_FACTOR" in measurement
    assert "reference_current_A=REFERENCE_CURRENT" in measurement and "r_typical=R_TYPICAL" in measurement
    campaign = "\n".join(_code(generator.campaign_notebook(lang, example)))
    assert "U_Tp=U_TP, F=F_FACTOR" in campaign and "uncertainty_I=UNCERTAINTY_I" in campaign


@pytest.mark.parametrize("lang", ["en", "de"])
@pytest.mark.parametrize("example", [False, True])
def test_earthing_impedance_is_site_data(generator, lang, example):
    """Z_E of the campaign notebook is the earthing impedance of the user's network: not set in the templates and
    working copies (sections 3 and 4 skip what needs it with a note), a marked demo value in the example notebooks."""
    campaign = "\n".join(_code(generator.campaign_notebook(lang, example)))
    m = re.search(r"^Z_E\s*=\s*(\S+)\s*#\s*(.*)$", campaign, re.M)
    assert m, "Z_E"
    if example:
        assert float(m.group(1)) == 2.5 and re.match(r"demo value|Demo-Wert", m.group(2)), m.group(0)
    else:
        assert m.group(1) == "None", m.group(0)
    assert campaign.count("if Z_E is None:") == 2
    assert campaign.count("Z_E is not set (section 1)" if lang == "en" else "Z_E ist nicht gesetzt (Abschnitt 1)") == 2


def test_relevance_notes_name_the_notebook_variables(generator):
    """The notes of the notebooks about a skipped relevance name the variables of section 1, not the arguments."""
    measurement = "\n".join(_code(generator.measurement_notebook("en", False)))
    campaign = "\n".join(_code(generator.campaign_notebook("en", False)))
    assert '("REFERENCE_CURRENT or LIMITS", "reference_current_A"), ("U_TP", "U_Tp_V")' in measurement
    assert '("F_FACTOR", "F_factor")' in measurement and '("F_FACTOR", "F_factor")' in campaign
    assert '("REFERENCE_CURRENT", "reference_current_A"), ("U_TP", "U_Tp_V")' in campaign
    assert "relevance of the deviation for the assessment not determined" in campaign.lower()


def test_demo_leaves_the_register_alone(generator):
    """With DEMO = True the measurement notebook records no intervals in the register of the work folder."""
    cell = next(c for c in _code(generator.measurement_notebook("en", True)) if "register.record_intervals" in c)
    assert cell.index("if RECORD_INTERVALS and DEMO:") < cell.index("elif RECORD_INTERVALS:") < \
        cell.index("register.record_intervals")


def test_committed_notebooks_are_regenerated_identically(generator, tmp_path):
    """Regenerating the notebooks as in the repository (both languages, ``--example --overwrite``) into a new folder
    gives files byte-identical to the committed ones: deterministic cell ids, the same bytes on every platform."""
    root = os.path.dirname(HERE)
    for lang in ("en", "de"):
        generator.main(["--lang", lang, "--out", str(tmp_path / lang), "--example", "--overwrite"])
    generated = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.ipynb"))
    committed = sorted(os.path.relpath(p, os.path.join(root, "notebooks")).replace(os.sep, "/")
                       for p in glob.glob(os.path.join(root, "notebooks", "**", "*.ipynb"), recursive=True))
    assert generated == committed and len(generated) == 8
    for rel in generated:
        new = (tmp_path / rel).read_bytes()
        with open(os.path.join(root, "notebooks", rel), "rb") as f:
            assert new == f.read(), "%s differs from the generator – regenerate the notebooks" % rel
    ids = [c["id"] for c in nbformat.read(str(tmp_path / generated[0]), as_version=4).cells]
    assert len(set(ids)) == len(ids) and all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", i) for i in ids)
