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
    for make in (generator.measurement_notebook, generator.campaign_notebook, generator.forecast_notebook,
                 generator.without_fault_notebook):
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
              'legacy.check_option("IG_CHOICE"': ('IG_CHOICE == "max"', dict(IG_CHOICE="maximal")),
              'legacy.check_option("SOURCE"': ('SOURCE == "measured"', dict(SOURCE="gemessen")),
              'legacy.check_option("SOURCE_IMPEDANCE"': ('impedance=SOURCE_IMPEDANCE', dict(SOURCE_IMPEDANCE="null"))}
    for start, (use, values) in checks.items():
        cell, statement = _statement(cells, start)
        assert cell.index(start) < cell.index(use), start                  # checked before the value is used
        with pytest.raises(ValueError, match="frühere Name|former name|nicht zulässig|not allowed"):
            exec(statement, dict(legacy=legacy, **values))
    assert sum(c.count('legacy.check_option("GROUNDMEAS_EXPORT"') for c in cells) == 2      # both notebooks


#: the parameters each user defines and their values in the published notebooks: not set
USER_PARAMETERS = {"LIMITS": (), "U_TP": None, "F_FACTOR": None, "REFERENCE_CURRENT": None, "R_TYPICAL": None,
                   "UNCERTAINTY_I": 0.0, "PQ_SAFETY_FACTOR": 1.0, "PQ_FACTORS": None}


@pytest.mark.parametrize("lang", ["en", "de"])
@pytest.mark.parametrize("example", [False, True])
def test_no_limits_or_safety_factors_in_the_notebooks(generator, lang, example):
    """The notebooks contain no limits, U_Tp, F, reference current, uncertainty margins, safety factors or typical
    range of r – one configuration cell names them, not set, and the evaluation passes them on."""
    for make, extra in ((generator.measurement_notebook, {"UNCERTAINTY_U": 0.0}),
                        (generator.campaign_notebook, {"LOO_LIMIT_PCT": None, "LOO_LIMIT_A": None})):
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
    assert "MAIN.loo_table(LOO_LIMIT_PCT, LOO_LIMIT_A)" in campaign


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
        generator.main(["--lang", lang, "--out", str(tmp_path / lang), "--example", "--overwrite", "--forecast"])
    generated = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.ipynb"))
    committed = sorted(os.path.relpath(p, os.path.join(root, "notebooks")).replace(os.sep, "/")
                       for p in glob.glob(os.path.join(root, "notebooks", "**", "*.ipynb"), recursive=True))
    assert generated == committed and len(generated) == 16
    for rel in generated:
        new = (tmp_path / rel).read_bytes()
        with open(os.path.join(root, "notebooks", rel), "rb") as f:
            assert new == f.read(), "%s differs from the generator – regenerate the notebooks" % rel
    ids = [c["id"] for c in nbformat.read(str(tmp_path / generated[0]), as_version=4).cells]
    assert len(set(ids)) == len(ids) and all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", i) for i in ids)


@pytest.mark.parametrize("lang", ["en", "de"])
def test_numbered_cell_ids_keep_their_cells(generator, lang):
    """Cells added after a release have a key instead of a number, so the numbered ids still denote the same cells
    and a working copy updated from an earlier version maps every cell to its counterpart: the section headings stay
    at the ids they had in 2.x, the numbers have no gaps, the cells of the transformer node have keys."""
    sections = ((generator.measurement_notebook, generator.NAMES[lang][0], (2, 4, 6, 8, 20, 22, 24)),
                (generator.campaign_notebook, generator.NAMES[lang][1], (2, 4, 6, 10, 12, 14, 16)),
                (generator.forecast_notebook, generator.FORECAST_NAMES[lang][0], (2, 4, 6, 8, 10, 12, 14)),
                (generator.without_fault_notebook, generator.WITHOUT_FAULT_NAMES[lang], (2, 4, 6, 8, 10)))
    for build, name, numbers in sections:
        cells = {c["id"]: c["source"] for c in build(lang, False).cells}
        for section, number in enumerate(numbers, start=1):
            assert cells["%s-%02d" % (name, number)].startswith("## %d · " % section)
        numbered = sorted(int(i[len(name) + 1:]) for i in cells if i[len(name) + 1:].isdigit())
        assert numbered == list(range(len(numbered)))
    name = generator.NAMES[lang][0]
    cells = {c["id"]: c["source"] for c in generator.measurement_notebook(lang, False).cells}
    assert cells["%s-transformer-node-text" % name].startswith("### ")
    assert cells["%s-transformer-node" % name].startswith('if res is not None and "transformer_node" in res.tables')


@pytest.mark.parametrize("lang", ["en", "de"])
def test_transformer_cell_runs(generator, lang, tmp_path):
    """The cell of the transformer node shows its tables and figures for a transformer recording and is skipped with
    a note without transformer currents."""
    import matplotlib.pyplot as plt
    from groundfault import Intervals, demo, evaluate, i18n, open_recording, report, transformer
    cell = next(c for c in _code(generator.measurement_notebook(lang, False)) if '"transformer_node" in res.tables' in c)
    path = str(tmp_path / "TR_0_10_000kHz.cfg")
    w = demo.make_transformer_recording(path)
    b = w["intervals"]
    shown, printed = [], []
    plt.close("all")                                   # figures left open by other tests
    with i18n.language(lang):
        res = evaluate(open_recording(path), Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]),
                                                       tuple(b["post_fault"])))
        namespace = dict(res=res, transformer=transformer, report=report, show=shown.append,
                         display=lambda x: shown.append(x), Markdown=str, print=printed.append)
        exec(cell, namespace)
        assert len(plt.get_fignums()) == 2 and not printed
        plt.close("all")
        tables = [x for x in shown if hasattr(x, "columns")]
        assert len(tables) == 2 and "P_fault_kW" in tables[0].columns and tables[1]["significant"].all()
        no_transformer = type("R", (), {"tables": {}})()
        exec(cell, dict(namespace, res=no_transformer))
        assert len(printed) == 1 and not plt.get_fignums()


#: the parameters of the forecast notebook each user defines and their values in the published notebooks: not set
FORECAST_PARAMETERS = {"MARGIN_A": 0.0, "FUNDAMENTAL_A": None, "LIMITS": (), "PQ_SAFETY_FACTOR": 1.0, "PQ_FACTORS": None}


@pytest.mark.parametrize("lang", ["en", "de"])
@pytest.mark.parametrize("example", [False, True])
def test_forecast_notebook_contains_no_margins_or_network_data(generator, lang, example):
    """Margin, fundamental residual current and limits of the forecast notebook are not set; the harmonic voltages
    are not set in the templates and marked demo values in the example notebooks."""
    cells = _code(generator.forecast_notebook(lang, example))
    config = [c for c in cells if "MARGIN_A      =" in c]
    assert len(config) == 1
    values = {}
    for line in config[0].splitlines():
        m = re.match(r"([A-Z_]+)\s*=\s*([^#]+?)\s*(#.*)?$", line)
        if m and m.group(1) in FORECAST_PARAMETERS:
            values[m.group(1)] = eval(m.group(2))
    assert values == FORECAST_PARAMETERS
    m = re.search(r"^VOLTAGES\s*=\s*(.+?)\s*#\s*(.*)$", config[0], re.M)
    if example:
        assert re.match(r"demo values|Demo-Werte", m.group(2)), m.group(0)
    else:
        assert m.group(1) == "None", m.group(0)
    m = re.search(r"^LINE\s*=\s*(.+?)\s*#\s*(.*)$", config[0], re.M)
    if example:
        assert re.match(r"demo|Demo", m.group(2)), m.group(0)
    else:
        assert m.group(1) == "None", m.group(0)
    text = "\n".join(cells)
    assert "margin_A=MARGIN_A" in text and "fundamental_A=FUNDAMENTAL_A" in text
    assert text.index('legacy.check_keys("FAULTS" if i < len(FAULTS) else "CHECKS"') < text.index(
        'fc.add_entries(MODEL, WORK_FOLDER, TESTS, "test"')


def _run_cells(cells, namespace):
    """Run code cells of a notebook in-process (without IPython magics)."""
    for cell in cells:
        exec("\n".join(line for line in cell.splitlines() if not line.startswith("%")), namespace)


@pytest.mark.parametrize("lang", ["en", "de"])
def test_forecast_notebook_runs(generator, lang, tmp_path, monkeypatch):
    """The example forecast notebook creates the demo campaign and a recorded earth fault with coil currents,
    calibrates with the tests of the campaign from the register, checks, updates (node rule) and checks at the
    recorded earth fault, forecasts at the busbar and behind the demo line; with a CSV time series it forecasts the
    quantile, and it saves the model in the forecast folder."""
    pytest.importorskip("IPython")
    import matplotlib
    import numpy as np
    import pandas as pd
    from groundfault import i18n
    cells = _code(generator.forecast_notebook(lang, True))
    monkeypatch.chdir(tmp_path)
    shown = []
    namespace = {"__name__": "notebook"}
    try:
        with matplotlib.rc_context():
            _run_cells(cells[:2], namespace)                                    # setup and configuration
            namespace.update(display=lambda *a, **k: shown.append(a[0]) if a else None)
            _run_cells(cells[2:], namespace)
            model, forecast = namespace["MODEL"], namespace["FORECAST"]
            assert len(model.tests) == 3 and len(model.faults) == 1
            assert [t["Z"] for t in namespace["TESTS"]] == [0.0, 2.5, 5.0]          # from the register
            assert set(namespace["CROSS_CHECKS"]["mode"]) == {"loo", "pairwise", "chain"}
            assert set(model.faults[0].current_method.values()) == {"node_rule"}   # coil currents in the demo
            assert set(namespace["FAULT_CHECKS"]["mode"]) == {"fault_check"}
            assert forecast is not None and len(forecast.currents) == 1 and forecast.line is None
            assert len(namespace["FORECASTS"]) == 2 and len(set(namespace["FORECAST_TABLE"]["location"])) == 2
            out = tmp_path / ("forecast" if lang == "en" else "05_Prognose")
            assert out.is_dir() and namespace["OUT"].parent == out
            saved = namespace["fc"].NetworkModel.load(str(namespace["path"]))
            assert saved.names == model.names
            # a transformer recording of the same test by a second recorder: its upstream impedance (key transformer)
            from groundfault import Intervals, demo, evaluate, open_recording
            cfg = str(tmp_path / "TR_0_10_000kHz.cfg")
            w = demo.make_transformer_recording(cfg)
            b = w["intervals"]
            tr = evaluate(open_recording(cfg), Intervals(tuple(b["steady_state"]), tuple(b["pre_fault"]),
                                                         tuple(b["post_fault"])))
            folder = namespace["WORK_FOLDER"] / namespace["LAYOUT"].campaigns / namespace["TESTS"][0]["campaign"]
            tr.save_json(namespace["LAYOUT"].result_path(folder, "TR_0_10_000kHz"))
            namespace["TESTS"][0]["transformer"] = "TR_0_10_000kHz"
            namespace["TESTS"][1]["transformer"] = "missing"
            printed = []
            namespace["print"] = lambda *a, **k: printed.append(" ".join(map(str, a)))
            _run_cells([c for c in cells if "MODEL = fc.NetworkModel(NETWORK)" in c], namespace)
            del namespace["print"]
            first = namespace["MODEL"].tests[0]
            assert any(e.Z_up is not None for e in first.orders.values())
            assert all(e.Z_up is None for e in namespace["MODEL"].tests[1].orders.values())
            name1 = namespace["MODEL"].tests[1].name
            assert any(line.startswith("ℹ " + name1) and "missing" in line for line in printed)
            # a check with another measurement: busbar voltages of one recording, fault current of another
            namespace["CHECKS"] = [dict(campaign=namespace["TESTS"][2]["campaign"],
                                        measurement=namespace["TESTS"][2]["measurement"], Z=5.0,
                                        current=namespace["TESTS"][2]["measurement"], line=namespace["LINE"])]
            _run_cells([c for c in cells if c.startswith("VERIFY = pd.DataFrame()")], namespace)
            v = namespace["VERIFY"]
            assert set(v["mode"]) == {"verify"} and (v[v.order != "I_H"].deviation_A < 0).any()  # line not in the test
            lt = namespace["LINE_TABLE"]                 # the busbar voltages measure no line: the test was at the busbar
            assert len(lt) and (lt["Z_measured_Ohm"] < 0.01 * lt["Z_line_Ohm"]).all()
            assert set(namespace["LINE_MEASURED"]) == {lt["target"].iloc[0]}
            # a time series of a power-quality measurement as a CSV file (semicolon, decimal comma)
            rng = np.random.default_rng(3)
            idx = pd.date_range("2026-02-01", periods=300, freq="10min")
            df = pd.DataFrame({"U_H%d" % m: rng.uniform(0.5, 1.0, 300) * u for m, u in
                               ((3, 30.0), (5, 250.0), (7, 130.0), (11, 40.0), (13, 30.0))}, index=idx)
            csv = tmp_path / "pq.csv"
            df.to_csv(csv, sep=";", decimal=",")
            namespace["VOLTAGES"] = str(csv)
            _run_cells([c for c in cells if c.startswith("FORECAST = FORECAST_TABLE = None")], namespace)
            f = namespace["FORECAST"]
            assert len(f.currents) == 300
            t = namespace["FORECAST_TABLE"]
            table = t[t["location"] == t["location"].iloc[0]].set_index("order")
            assert table.loc["I_RES", "I_forecast_A"] == pytest.approx(float(f.IRES.quantile(0.95)))
            # the PQ export of the demo campaign: the quantile per order × factor, or every 10-min value
            lay = namespace["LAYOUT"]
            export = (namespace["WORK_FOLDER"] / lay.campaigns / namespace["TESTS"][0]["campaign"] / lay.raw / "PQ"
                      / ("SUB_PQ_export.csv" if lang == "en" else "UW_PQ_Export.csv"))
            section6 = [c for c in cells if c.startswith("FORECAST = FORECAST_TABLE = None")]
            namespace.update(PQ_FILES=str(export), PQ_SAFETY_FACTOR=1.25, VOLTAGES=None)
            _run_cells(section6, namespace)
            pq_ = namespace["PQ"]
            from groundfault.formulas import harmonic_category
            assert pq_.factor == 1.25 and pq_.valid and len(namespace["FORECAST"].currents) == 1
            v = namespace["VOLTAGES"]
            # positive/negative sequence: the quantile × factor; zero sequence (3rd harmonic of the demo) and even
            # orders: the pre-fault voltage of the tests (not scaled)
            assert {m: u for m, u in v.items() if harmonic_category(m) == "pos_neg"} == {
                m: u for m, u in pq_.voltages().items() if harmonic_category(m) == "pos_neg"}
            kept = namespace["KEPT"]
            assert 3 in kept and v[3] == kept[3] == namespace["MODEL"].test_voltages()[3] != pq_.voltages()[3]
            assert all(harmonic_category(m) in ("zero", "even") for m in kept)
            one = namespace["FORECAST_TABLE"]
            namespace.update(PQ_SERIES=True, VOLTAGES=None)
            _run_cells(section6, namespace)
            f = namespace["FORECAST"]
            assert len(f.currents) == len(namespace["PQ"].data.harmonics)
            assert all((df[3] == kept[3]).all() for df in namespace["VOLTAGES"].values())
            many = namespace["FORECAST_TABLE"]
            i_one = one[one["location"] == one["location"].iloc[0]].set_index("order").loc["I_RES", "I_forecast_A"]
            i_many = many[many["location"] == many["location"].iloc[0]].set_index("order").loc["I_RES", "I_forecast_A"]
            assert i_many <= i_one * (1 + 1e-6)     # quantile of I_RES(t) ≤ I_RES of the quantiles (interpolation aside)
            # a PQ measurement shorter than every duration of PQ_FACTORS is not valid: no voltages from it
            namespace.update(PQ_SERIES=False, VOLTAGES=None, PQ_FACTORS={1000.0: 1.0})
            _run_cells(section6, namespace)
            assert not namespace["PQ"].valid and namespace["VOLTAGES"] is None and namespace["FORECAST"] is None
    finally:
        i18n.set_language("de")                                                # the language of the test suite


#: the limits of the notebook without an earth fault and their values in the published notebooks: not set
WITHOUT_FAULT_LIMITS = {"MIN_HV_SHARE": None, "V0_RATIO": None, "FUNDAMENTAL_A": None, "LIMITS": (),
                        "PQ_SAFETY_FACTOR": 1.0, "PQ_FACTORS": None}
#: network data and assumptions of that notebook: not set in the templates, demo values in the example notebooks
WITHOUT_FAULT_DATA = ("U_N", "U_LE", "I_C", "I_L", "D", "U_K", "S_RT", "S_K", "C_1", "R_X_UP", "R_X_HV", "VOLTAGES",
                      "G_MAX", "G", "G_RANGE")


@pytest.mark.parametrize("lang", ["en", "de"])
@pytest.mark.parametrize("example", [False, True])
def test_without_fault_notebook_contains_no_limits_or_network_data(generator, lang, example):
    """The limits of the notebook without an earth fault are not set; network data, harmonic voltages and the
    assumptions about the damping are not set in the templates and marked demo values in the example notebooks."""
    cells = _code(generator.without_fault_notebook(lang, example))
    config = [c for c in cells if "MIN_HV_SHARE  =" in c]
    assert len(config) == 1
    values = {}
    for line in config[0].splitlines():
        m = re.match(r"([A-Z_0-9]+)\s*=\s*([^#]+?)\s*(#.*)?$", line)
        if m:
            values[m.group(1)] = m.group(2)
    assert {k: eval(values[k]) for k in WITHOUT_FAULT_LIMITS} == WITHOUT_FAULT_LIMITS
    if example:
        assert re.search(r"network data \(demo values\)|Netzdaten \(Demo-Werte\)", config[0])
        assert re.search(r"V1 and V2 \(demo values\)|V1 und V2 \(Demo-Werte\)", config[0])
        assert re.search(r"^VOLTAGES\s*=.*#\s*(demo values|Demo-Werte)", config[0], re.M)
    else:
        assert all(values[k] == "None" for k in WITHOUT_FAULT_DATA), {k: values[k] for k in WITHOUT_FAULT_DATA}
        assert values["RECORDINGS"] == "[]" and values["REFERENCE"] == "None"


@pytest.mark.parametrize("lang", ["en", "de"])
def test_without_fault_notebook_runs(generator, lang, tmp_path, monkeypatch):
    """The example notebook without an earth fault creates a measuring day of undisturbed transformer recordings,
    finds the angle error of the current transformers from the reference clamp, evaluates every recording, pools the
    reliable ones and shows V0 to V3 side by side; with a limit for the share of the HV-driven variation only the
    recordings driven from the HV side are pooled, and with V0_RATIO the rule column appears."""
    pytest.importorskip("IPython")
    import matplotlib
    from groundfault import i18n
    cells = _code(generator.without_fault_notebook(lang, True))
    monkeypatch.chdir(tmp_path)
    shown = []
    namespace = {"__name__": "notebook"}
    try:
        with matplotlib.rc_context():
            _run_cells(cells[:2], namespace)
            namespace.update(display=lambda *a, **k: shown.append(a[0]) if a else None)
            _run_cells(cells[2:], namespace)
            assert len(namespace["FILES"]) == 6
            ct = namespace["CT_TABLE"].set_index("order")
            assert ct.loc[5, "angle_deg"] == pytest.approx(2.0, abs=0.05)
            assert ct.loc[7, "angle_deg"] == pytest.approx(2.8, abs=0.05)
            table, pooled = namespace["V3_TABLE"], namespace["V3_POOLED"]
            assert len(table) == 12 and table.natural_sequence.all() and table.attrs["sign"] == 1.0
            assert set(namespace["Z_MV"]) == {5, 7} and (pooled.recordings >= 4).all()
            comparison = namespace["COMPARISON"]
            for c in ("V0_A", "V1_A", "V2_A", "V2_envelope_A", "V3_A"):
                assert c in comparison.columns and comparison[c].notna().all()
            assert list(comparison.order).count("I_H") == 3 and "V0_rule_A" not in comparison.columns
            out = tmp_path / ("forecast" if lang == "en" else "05_Prognose")
            assert namespace["OUT"].parent == out and len(list(namespace["OUT"].glob("*_without_fault_*.csv"))) == 5
            # with limits: only the recordings driven from the HV side are pooled; the rule column of V0
            namespace.update(MIN_HV_SHARE=0.25, V0_RATIO=0.8, FUNDAMENTAL_A=40.0, LIMITS=(60.0,))
            _run_cells([c for c in cells if "mv_network_series" in c or "estimates_without_fault" in c], namespace)
            pooled = namespace["V3_POOLED"].set_index("order")
            assert pooled.loc[5, "recordings"] == 4 and pooled.loc[7, "recordings"] == 3
            low = namespace["V3_TABLE"]
            assert not low[low.hv_share < 0.25].reliable.any()
            comparison = namespace["COMPARISON"]
            assert "V0_rule_A" in comparison.columns
            z = {m: complex(1 / complex(g, m * 2 * 3.141592653589793 * 50.0 * 65e-6)) for m, g in ((5, 0.07), (7, 0.09))}
            for m, zm in z.items():
                assert abs(namespace["Z_MV"][m] / zm - 1) < 0.06               # the truth of the demo
            # the voltages from a PQ export: the quantile per order × factor
            from groundfault import demo
            w = demo.make_pq_export(str(tmp_path / "pq_export.csv"), days=8.0)
            namespace.update(PQ_FILES=w["path"], PQ_SAFETY_FACTOR=1.25)
            _run_cells([c for c in cells if "estimates_without_fault" in c], namespace)
            assert namespace["VOLTAGES"] == namespace["PQ"].voltages()
            assert namespace["VOLTAGES"][5] == pytest.approx(1.25 * w["quantiles"][0.95][5], rel=1e-4)
            assert namespace["COMPARISON"] is not None
    finally:
        i18n.set_language("de")                                                # the language of the test suite


@pytest.mark.parametrize("lang", ["en", "de"])
def test_without_fault_template_runs_without_data(generator, lang, tmp_path, monkeypatch, capsys):
    """The template without network data, voltages and recordings runs through, says what is missing and writes
    nothing – no empty folder in the forecast folder."""
    pytest.importorskip("IPython")
    import matplotlib
    from groundfault import i18n
    cells = _code(generator.without_fault_notebook(lang, False))
    monkeypatch.chdir(tmp_path)
    namespace = {"__name__": "notebook"}
    try:
        with matplotlib.rc_context():
            _run_cells(cells[:2], namespace)
            namespace.update(display=lambda *a, **k: None)
            _run_cells(cells[2:], namespace)
        assert namespace["TABLES"] == {} and namespace["COMPARISON"] is None and namespace["V3_TABLE"] is None
        assert not (tmp_path / ("forecast" if lang == "en" else "05_Prognose")).exists()
        out = capsys.readouterr().out
        assert ("Nothing to export" if lang == "en" else "Nichts zu exportieren") in out
    finally:
        i18n.set_language("de")                                                # the language of the test suite


def test_campaign_notebook_with_the_pq_measurement(generator, tmp_path, monkeypatch):
    """The example campaign notebook reads the PQ export of the demo campaign: the quantiles replace U95 and
    THD95_PERCENT, the tests are placed in the distribution of the PQ measurement, the residual current at Z_E is shown
    per order, as a time series and with the THD factor, and the tables and figures of the PQ measurement are
    exported."""
    pytest.importorskip("IPython")
    import matplotlib
    from groundfault import i18n
    cells = _code(generator.campaign_notebook("en", True))
    monkeypatch.chdir(tmp_path)
    namespace = {"__name__": "notebook"}
    try:
        with matplotlib.rc_context():
            _run_cells(cells[:1], namespace)
            namespace.update(display=lambda *a, **k: None)
            _run_cells(cells[1:], namespace)
        pq_ = namespace["PQ"]
        assert pq_ is not None and pq_.factor == 1.0 and pq_.valid
        assert namespace["U95"] == pq_.u95() and namespace["U95_REFERENCE"] == "seq"
        assert namespace["THD95_PERCENT"] == pq_.thd95()
        scaling = namespace["SCALING"]
        assert set(scaling) == {"safety_factor", "u95", "u95_reference", "thd95_percent", "thd_measured_percent"}
        tests = namespace["PQ_COMPARISON"]
        assert set(tests["test"]) == {m["name"] for m in namespace["MEASUREMENTS"] if m["Z"] is not None}
        assert tests["order"].map(lambda m: m % 3 != 0).all() and tests["window"].str.contains("±").all()
        table = namespace["PQ_SCALING"].set_index("method")["IRES_A"]
        assert len(table) == 4
        none, per_order, series = table.iloc[0], table.iloc[1], table.iloc[2]
        assert per_order > none and series <= per_order * (1 + 1e-6)     # equal for orders that rise together
        main = namespace["MAIN"]
        r = namespace["equivalent_source"].ires_at_impedance(main, namespace["Z_E"], IG=namespace["IG_CHOICE"], **scaling)
        assert r["IRES_scaled"] == pytest.approx(per_order)
        per = r["table"].set_index("order")                    # the result per order shown in section 4
        assert per.loc[3, "rule"] == "as measured" and per.loc[5, "rule"] == "own voltage"
        assert set(per["part"]) == {"model", "remainder"} and (per.loc[per["category"] == "even", "factor"] == 1.0).all()
        assert {"pq_quantiles", "pq_summary", "pq_tests", "pq_scaling"} <= set(namespace["TABLES"])
        fig = namespace["FIG"]
        assert all((fig / ("%s.png" % n)).exists() for n in ("pq_series", "pq_duration", "pq_profile"))
        # a PQ measurement shorter than every duration of PQ_FACTORS is not valid: nothing is scaled with it
        section4 = [c for c in cells if c.startswith(("PQ = PQ_COMPARISON = PQ_LEVELS = None", "SCALING = None",
                                                      "PQ_SCALING = None"))]
        namespace.update(PQ_FACTORS={1000.0: 1.0}, U95=None, THD95_PERCENT=None, PQ_SAFETY_FACTOR=1.0)
        with matplotlib.rc_context():
            _run_cells(section4, namespace)
        assert not namespace["PQ"].valid and namespace["U95"] is None and namespace["SCALING"] is None
        assert namespace["PQ_SCALING"] is None
    finally:
        i18n.set_language("de")                                                # the language of the test suite
