# -*- coding: utf-8 -*-
"""Equivalent-source method: recovery of the known two-terminal equivalent despite source drift, different time
origins and a clamp with reversed polarity; comparison of the estimators; condition; uncertainties."""
import inspect
import json
import math

import numpy as np
import pytest

from groundfault import demo, equivalent_source, i18n
from groundfault import formulas as fml


@pytest.fixture(scope="module")
def series(demo_results):
    entry = [dict(file=p, Z=Z, name="%g Ω" % Z) for Z, (_, _, p, _) in sorted(demo_results.items())]
    return equivalent_source.load_series(entry)


def test_recovery_with_complex_normalization(series):
    """Positive/negative-sequence orders: Z_q and |U_q| exact despite a source drift of 20 %/30°, different time
    origins and a clamp with reversed polarity. (The demo also drives the 3rd harmonic with the drift – therefore
    it is recovered here as well with ``normalize_zero=True``.)"""
    r = equivalent_source.fit_equivalent_source(series, normalization="complex")
    truth = {h.order: h for h in demo.DEFAULT_HARMONICS}
    for m, F in r.fits.items():
        if F.sequence == "zero":
            assert F.normalization == "none"          # default: zero sequence without level normalization
            assert any("Nullsystem-Ordnung" in h for h in F.hints)
            continue
        assert abs(F.Zq - truth[m].Zq) < 0.01 * abs(truth[m].Zq) + 0.02, m
        assert abs(F.Uq) == pytest.approx(abs(truth[m].Uq), rel=0.01), m      # median of the drift magnitudes = 1
        assert F.resid_rel < 0.01
    r3 = equivalent_source.fit_equivalent_source(series, normalization="complex", normalize_zero=True, orders=[3])
    assert abs(r3.fits[3].Zq - truth[3].Zq) < 0.05


def test_normalization_spellings(series):
    """``"complex"`` is the canonical value (also ``"complex_"``, any case); the former German values ``"komplex"``,
    ``"betrag"`` and ``"keine"`` and unknown values are rejected with the allowed values and the current name."""
    ref = equivalent_source.fit_equivalent_source(series)
    assert ref.settings["normalization"] == "complex"
    assert {F.normalization for F in ref.fits.values() if F.sequence != "zero"} == {"complex"}
    for spelling in ("complex_", "Complex"):
        r = equivalent_source.fit_equivalent_source(series, normalization=spelling)
        assert r.settings["normalization"] == "complex"
        assert all(r.fits[m].Zq == ref.fits[m].Zq and r.fits[m].normalization == ref.fits[m].normalization
                   for m in ref.fits)
    mag = equivalent_source.fit_equivalent_source(series, normalization="magnitude")
    assert {F.normalization for F in mag.fits.values() if F.sequence != "zero"} == {"magnitude"}
    for none in (None, "none"):
        r = equivalent_source.fit_equivalent_source(series, normalization=none, rq_non_negative=False)
        assert r.settings["normalization"] is None
        assert {F.normalization for F in r.fits.values()} == {"none"}
    for former, new in (("komplex", "complex"), ("Betrag", "magnitude"), ("keine", "none")):
        with pytest.raises(ValueError, match=r"^normalization='%s' ist nicht zulässig – zulässig: 'complex', "
                                             r"'magnitude', 'none', None \('%s' ist der frühere Name von '%s'\)$"
                                             % (former.lower(), former.lower(), new)):
            equivalent_source.fit_equivalent_source(series, normalization=former)
    with pytest.raises(ValueError, match=r"^normalization='phase' ist nicht zulässig – zulässig: 'complex', "
                                         r"'magnitude', 'none', None$"):
        equivalent_source.fit_equivalent_source(series, normalization="phase")


def test_without_normalization_fails_with_phase_drift(series):
    """With a phase drift of the source of 30°/−25° the two-terminal equivalent cannot be determined without
    normalization – this shows why the complex normalization is needed (residual ≫ 1 %)."""
    r = equivalent_source.fit_equivalent_source(series, normalization=None, rq_non_negative=False)
    assert r.fits[5].resid_rel > 0.2


def test_both_estimators_agree_on_exact_data():
    Zq, Uq = 4.5 - 2.5j, 220 * np.exp(0.4j)
    Z = np.array([0.0, 2.5, 5.0])
    I = Uq / (Zq + Z)
    a = equivalent_source.fit_equation_error(I, Z)
    b = equivalent_source.fit_output_error(I, Z)
    assert a[1] == pytest.approx(Zq) and b[1] == pytest.approx(Zq)
    assert a[0] == pytest.approx(Uq) and b[0] == pytest.approx(Uq)


def test_two_measurements_match_closed_form():
    I1, I2 = 45 * np.exp(1j * np.deg2rad(28)), 17 * np.exp(1j * np.deg2rad(9))
    Uq, Zq = fml.source_from_two_measurements(I1, 1.0, I2, 10.0)
    Uq2, Zq2, _ = equivalent_source.fit_equation_error(np.array([I1, I2]), np.array([1.0, 10.0]))
    assert Zq2 == pytest.approx(Zq) and Uq2 == pytest.approx(Uq)


def test_rq0_boundary_solution():
    Zq, Uq = 0.0 - 4j, 100.0
    Z = np.array([0.0, 2.5, 5.0])
    I = Uq / (Zq + Z)
    Uq_b, Zq_b = equivalent_source.fit_rq0(I, Z)
    assert Zq_b.real == 0.0 and Zq_b.imag == pytest.approx(-4.0) and Uq_b == pytest.approx(Uq)


def test_scale_invariance_and_condition():
    Zq, Uq = 4.5 - 2.5j, 220.0
    Z = np.array([0.0, 2.5, 5.0])
    I = Uq / (Zq + Z)
    for s in (1e-6, 1.0, 1e6):
        Uq_b, Zq_b, cond = equivalent_source.fit_equation_error(I * s, Z)
        assert Zq_b == pytest.approx(Zq) and Uq_b == pytest.approx(Uq * s)
    # source impedance ≫ additional impedances → currents almost equal → poor condition
    _, _, c_good = equivalent_source.fit_equation_error(Uq / (Zq + Z), Z)
    _, _, c_bad = equivalent_source.fit_equation_error(Uq / (300 - 300j + Z), Z)
    assert c_bad > 20 * c_good


def test_residual_current_and_scaling(series):
    r = equivalent_source.fit_equivalent_source(series)
    e = equivalent_source.ires_at_impedance(r, 2.5)
    assert e["interpolation"]
    assert e["IRES"] == pytest.approx(math.sqrt(e["IG"] ** 2 + sum(v * v for v in e["parts"].values())
                                                + e["IH_rest"] ** 2))
    assert e["IH_rest"] < 0.05                                   # all orders of the demo are fitted
    assert e["IRES_assessed"] == e["IRES"]                         # no margin unless the user gives one
    a = equivalent_source.ires_at_impedance(r, 2.5, uncertainty_I=0.03)  # margin of the user (invented)
    assert a["IRES_assessed"] == pytest.approx(1.03 * e["IRES"]) and a["IRES"] == e["IRES"]
    k = equivalent_source.ires_at_impedance(r, 2.5, thd95_percent=3.0, thd_measured_percent=1.5)
    assert k["IH_scaled"] == pytest.approx(2.0 * k["IH"])
    u = equivalent_source.ires_at_impedance(r, 2.5, u95={5: 360.0}, u95_reference="LL")
    assert u["factors"][5] == pytest.approx(360.0 / math.sqrt(3) / r.fits[5].level_reference)
    # line with Z = 0 → identical to the residual current at Z_E
    l0 = equivalent_source.ires_over_line(r, 2.5, 0.0, 0.0)
    assert l0["IRES"] == pytest.approx(e["IRES"])
    # purely resistive line → smaller current; with reactance the line can partly compensate the capacitive source
    # impedance (resonance) – then the current even increases (the reason for the resistive approach)
    l1 = equivalent_source.ires_over_line(r, 2.5, 0.4, 1.2)
    assert l1["IH"] < e["IH"]
    z1 = lambda m: 0.4 + 1j * 0.35 * m
    z0 = lambda m: 1.2 + 1j * 1.2 * m
    l2 = equivalent_source.ires_over_line(r, 2.5, z1, z0)
    F = r.fits[5]
    assert l2["parts"][5] == pytest.approx(abs(3 * F.Uq / (3 * F.Zq + 2 * z1(5) + z0(5) + 7.5)))
    with pytest.raises(ValueError, match="thd_measured_percent"):
        equivalent_source.ires_at_impedance(r, 2.5, thd95_percent=3.0)


def test_uncertainties(series):
    r = equivalent_source.fit_equivalent_source(series, normalize_zero=True)
    jk = r.jackknife_table(2.5)
    assert (jk["span_pct"] < 1).all()
    mc = equivalent_source.monte_carlo(r, 2.5, n=300, seed=1)
    assert mc["IRES"][5] < mc["IRES"][50] < mc["IRES"][95]
    best = equivalent_source.ires_at_impedance(r, 2.5)["IRES"]
    assert mc["IRES"][5] <= best * 1.01 and mc["IRES"][95] >= best * 0.99
    pw = r.pairwise_table()
    assert (pw["assessment"] == "ok").all()


def test_legacy_complex_format(tmp_path):
    """The legacy complex export of earlier evaluation notebooks is read (phasors per frequency, magnitudes
    before/after the fault; German keys of that format)."""
    Zq, Uq = 4.6 - 3.7j, 196.0
    for Z, name in ((0.0, "0"), (2.5, "25"), (5.0, "5")):
        I = Uq / (Zq + Z)
        d = {"vor": {"uGegen_250": 230.0, "uMit_350": 15.0}, "nach": {"uGegen_250": 226.0, "uMit_350": 15.0},
             "fehler": {"irest_50_real": 20.0, "irest_50_imag": -10.0, "irest_250_real": I.real,
                        "irest_250_imag": I.imag, "i_fehler_rms": 40.0,
                        "ul1e_50_real": 1e4, "ul1e_50_imag": -1.75e4, "ul2e_50_real": -1e4, "ul2e_50_imag": -1.75e4,
                        "ul3e_50_real": -100.0, "ul3e_50_imag": 90.0,
                        "ul1e_250_real": 280.0, "ul1e_250_imag": 110.0, "ul2e_250_real": -70.0, "ul2e_250_imag": 110.0,
                        "ul3e_250_real": 5.0, "ul3e_250_imag": -4.0}}
        (tmp_path / ("legacy_%s.json" % name)).write_text(json.dumps(d))
    ms = equivalent_source.load_series([dict(file=str(tmp_path / ("legacy_%s.json" % n)), Z=Z) for Z, n in
                                        ((0.0, "0"), (2.5, "25"), (5.0, "5"))], polarity=1)
    assert ms[0].format == "legacy_complex"
    assert ms[0].IRES == pytest.approx(40.0) and ms[0].faulted_phase == "L3"
    assert any(h.startswith("Altformat (komplexer Export): Winkel je Frequenz") for h in ms[0].hints)
    with i18n.language("en"):
        m_en = equivalent_source.load_measurement(str(tmp_path / "legacy_0.json"), 0.0, polarity=1)
    assert m_en.hints[0].startswith("Legacy complex format: angles per frequency refer to U_L12")
    r = equivalent_source.fit_equivalent_source(ms, normalization=None, orders=[5])
    assert r.fits[5].Zq == pytest.approx(Zq) and abs(r.fits[5].Uq) == pytest.approx(Uq)


def test_format_codes_of_result_files(demo_results, tmp_path):
    """groundfault result files are format ``"v3"``; a file of the same structure without a format tag (legacy
    notebook export) is read as ``"legacy_notebook"`` with the same phasors."""
    _, _, p, _ = demo_results[0.0]
    m = equivalent_source.load_measurement(p, 0.0)
    assert m.format == "v3"
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    d.pop("format", None)
    q = tmp_path / "untagged.json"
    q.write_text(json.dumps(d), encoding="utf-8")
    u = equivalent_source.load_measurement(str(q), 0.0)
    assert u.format == "legacy_notebook"
    assert u.I == m.I and u.U_pre == m.U_pre


def test_legacy_sequence_assignment(series):
    """``sequence="legacy"``: 3rd order zero, 5th negative, 7th positive, all other orders negative sequence;
    any other name raises an error that lists the allowed values (there is no alias)."""
    assert equivalent_source.SEQUENCE_LEGACY == {3: "zero", 5: "neg", 7: "pos"}
    assert "SEQUENCE_LEGACY" in equivalent_source.__all__
    r = equivalent_source.fit_equivalent_source(series, sequence="legacy")
    expected = {m: equivalent_source.SEQUENCE_LEGACY.get(m, "neg") for m in r.fits}
    assert {m: F.sequence for m, F in r.fits.items()} == expected and r.settings["sequence"] == "legacy"
    assert r.fits[13].sequence == "neg" and equivalent_source.natural_sequence(13) == "pos"
    with pytest.raises(ValueError, match=r"^sequence='simplified' ist nicht zulässig – zulässig: 'natural', "
                                         r"'legacy'$"):
        equivalent_source.fit_equivalent_source(series, sequence="simplified")


def test_error_cases(series):
    with pytest.raises(ValueError):
        equivalent_source.fit_equivalent_source(series[:1])
    equal = [series[0], series[0]]
    with pytest.raises(ValueError):
        equivalent_source.fit_equivalent_source(equal)
    with pytest.raises(ValueError, match=r"^method='gleichungsfehler' ist nicht zulässig – zulässig: "
                                         r"'equation_error', 'output_error' \('gleichungsfehler' ist der frühere Name "
                                         r"von 'equation_error'\)$"):
        equivalent_source.fit_equivalent_source(series, method="gleichungsfehler")


def test_auto_orders_only_odd_and_two_measurements():
    """"auto": even orders (transients/DC saturation) and orders with only one meaningful current are left out –
    with a hint; if given explicitly, they are evaluated."""
    Z = [0.0, 2.5, 5.0]
    I = {2: [3.3, 0.4, 0.3], 3: [13.0, 8.0, 5.0], 5: [5.4, 5.0, 4.1], 9: [0.7, 0.3, 0.1]}
    m = [equivalent_source.SourceMeasurement("m%d" % k, complex(z), "", "v2", 50.0, 0.0,
                                             {1: 30.0 + 0j, **{o: complex(v[k]) for o, v in I.items()}},
                                             {1: {"zero": 1e4 + 0j}, **{o: {} for o in I}}) for k, z in enumerate(Z)]
    r = equivalent_source.fit_equivalent_source(m, normalization=None)
    assert sorted(r.fits) == [3, 5]
    assert any("[2, 9]" in h and "≥ 0,5 A" in h for h in r.hints)      # numbers with a decimal comma in German
    r2 = equivalent_source.fit_equivalent_source(m, normalization=None, orders=[2, 3, 5, 9])
    assert sorted(r2.fits) == [2, 3, 5, 9]


def test_estimators_disagree_but_prediction_stable():
    """Source level drifting between the measurements (250 Hz, 16 % lower in the 0-Ω measurement, not normalized):
    the two estimators give different Z_q/U_q (their common scaling is poorly determined), but the current within
    the measured range is practically the same – the hint distinguishes both cases."""
    Z = np.array([2.5, 5.0, 0.0])
    Uq, Zq = 50.0 * np.exp(0.524j), 11.0 - 7.0j                   # synthetic source of order 5
    I = Uq / (Zq + Z) * np.array([1.0, 1.0, 0.84])
    m = [equivalent_source.SourceMeasurement("m%d" % k, complex(z), "", "v2", 50.0, 0.0, {1: 30.0 + 0j, 5: complex(i)},
                                             {1: {"zero": 1e4 + 0j}, 5: {}}) for k, (z, i) in enumerate(zip(Z, I))]
    F = equivalent_source.fit_equivalent_source(m, normalization=None, orders=[5]).fits[5]
    (Ug, Zg, _), (Ua, Za, _) = F.comparison["equation_error"], F.comparison["output_error"]
    assert abs(Za - Zg) > 0.2 * abs(Zg)
    assert abs(Ug / (Zg + 2.5)) == pytest.approx(abs(Ua / (Za + 2.5)), rel=0.01)
    assert any("Schätzer uneinig" in h and "stabil" in h for h in F.hints)
    with i18n.language("en"):
        F_en = equivalent_source.fit_equivalent_source(m, normalization=None, orders=[5]).fits[5]
    assert any("Estimators disagree" in h and "stable" in h and "Z = 2.5 Ω" in h for h in F_en.hints)


# ------------------------------------------------------------------ physically consistent measurement series
A_ = np.exp(2j * np.pi / 3)


def _thevenin_measurement(name, Z, phase, drift, orders, IG=30.0, extra=None):
    """Thevenin at the fault location: I'_m = −U_x,pre,m/(Z_q,m + Z) with U_x,pre = phase factor·U_seq,pre (L1-L2
    reference). ``orders``: {m: (U_seq_pre, Zq)}; ``extra``: additional orders that are not fitted {m: current}."""
    I, Uv = {1: complex(IG)}, {1: {"zero": 1e4 + 0j, "pos": 1.15e4 + 0j}}
    for m, (Useq, Zq) in orders.items():
        seq = equivalent_source.natural_sequence(m)
        U = drift * Useq
        I[m] = -equivalent_source.phase_factor(seq, phase) * U / (Zq + Z)
        Uv[m] = {seq: U}
    for m, i in (extra or {}).items():
        I[m] = complex(i)
    ih_sum = math.sqrt(sum(abs(v) ** 2 for m, v in I.items() if m > 1))
    return equivalent_source.SourceMeasurement(name, complex(Z), "", "v2", 50.0, 0.0, I, {}, U_pre=Uv, U_post=Uv,
                                               U_complex=True, IRES=math.sqrt(IG ** 2 + ih_sum ** 2),
                                               faulted_phase=phase, IH_sum=ih_sum)


ORDERS = {5: (60.0 * np.exp(0.7j), 9.7 - 8.0j), 7: (10.0 * np.exp(-0.4j), 1.2 - 2.2j)}


def test_faulted_phase_change_and_thevenin():
    """Measurements in different phases (L3, L1, L2) with source drift: the normalization to the voltage of the
    faulted phase gives Z_q exactly and U_q = −(pre-fault voltage of the faulted phase) → Thevenin check 1∠0°."""
    series = [_thevenin_measurement("L3 0", 0.0, "L3", 1.0, ORDERS),
              _thevenin_measurement("L1 2.5", 2.5, "L1", 1.1 * np.exp(0.3j), ORDERS),
              _thevenin_measurement("L2 5", 5.0, "L2", 0.9 * np.exp(-0.2j), ORDERS)]
    r = equivalent_source.fit_equivalent_source(series, reference="pre_fault")
    for m, (U, Zq) in ORDERS.items():
        F = r.fits[m]
        assert F.Zq == pytest.approx(Zq, abs=1e-9) and F.resid_rel < 1e-9
        assert abs(F.thevenin) == pytest.approx(1.0) and abs(np.angle(F.thevenin)) < 1e-9
        assert not any("Thevenin" in h for h in F.hints)
    assert any("Fehlerleiter unterschiedlich" in h for h in r.hints)
    # without the phase information (old state) the model no longer fits: U_q rotates by ±120°
    for mm in series:
        mm.faulted_phase = ""
    r2 = equivalent_source.fit_equivalent_source(series, reference="pre_fault")
    assert r2.fits[5].resid_rel > 0.3


@pytest.mark.parametrize("lang, magnitude_only, level_missing", [
    ("de", "keine komplexen Pegel im Export", "Pegel fehlt/zu klein (< 1,0 V)"),
    ("en", "no complex levels in the export", "level missing/too small (< 1.0 V)"),
])
def test_normalization_fallbacks(lang, magnitude_only, level_missing):
    """Without complex levels the complex normalization falls back to magnitudes; without usable levels to no
    normalization – the second hint then replaces the first one (in both languages)."""
    series = [_thevenin_measurement("m%d" % k, z, "L3", 1.0, ORDERS) for k, z in enumerate((0.0, 2.5, 5.0))]
    for mm in series:
        mm.U_complex = False
    with i18n.language(lang):
        F = equivalent_source.fit_equivalent_source(series, reference="pre_fault").fits[5]
        assert F.normalization == "magnitude" and F.Zq == pytest.approx(ORDERS[5][1])
        assert [h for h in F.hints if magnitude_only in h] and not [h for h in F.hints if level_missing in h]
        for mm in series:
            mm.U_pre = {}                                   # no levels before the fault
        F = equivalent_source.fit_equivalent_source(series, reference="pre_fault").fits[5]
        assert F.normalization == "none" and np.isnan(F.U_ref).all()
        assert [h for h in F.hints if level_missing in h] and not [h for h in F.hints if magnitude_only in h]


def test_rest_and_check_at_measured_impedances():
    """An order that is not fitted (19th) enters the residual current as rest; at the measured impedances the
    model reproduces the measured true RMS value (check)."""
    series = [_thevenin_measurement("m%d" % k, z, "L3", 1.0, ORDERS, extra={19: i19})
              for k, (z, i19) in enumerate(((0.0, 6.0), (2.5, 4.0), (5.0, 3.0)))]
    r = equivalent_source.fit_equivalent_source(series, orders=[5, 7], reference="pre_fault")
    assert r.ih_rest() == pytest.approx([6.0, 4.0, 3.0])
    e = equivalent_source.ires_at_impedance(r, 2.5)
    assert e["IH_rest"] == pytest.approx(6.0)                   # largest rest of the series (conservative)
    k = r.check_table()
    assert (k["deviation_pct"].abs() < 1e-6).all()


def test_ill_conditioning_is_reported():
    """Standard case of two measurements, Z = 0/2.5 Ω with |Z_q| ≈ 42 Ω: a current error of 1 % → large error of
    Z_q."""
    o = {5: (300.0, 30.0 - 30.0j)}
    series = [_thevenin_measurement("a", 0.0, "L3", 1.0, o), _thevenin_measurement("b", 2.5, "L3", 1.0, o)]
    F = equivalent_source.fit_equivalent_source(series, reference="pre_fault").fits[5]
    assert F.sensitivity > 0.10
    assert any("schlecht konditioniert" in h for h in F.hints)
    with pytest.warns(UserWarning, match="schlecht konditioniert"):
        fml.source_from_two_measurements(series[0].I[5], 0.0, series[1].I[5], 2.5)
    with pytest.raises(ValueError):
        fml.source_from_two_measurements(1 + 0j, 1.0, 2 + 0j, 1.0 + 1e-9)


def test_two_measurements_via_source_fit():
    """Synthetic sources, two measurements (Z1 = 1 Ω, Z2 = 10 Ω) → two-terminal equivalent per order → residual
    current at 2 Ω, checked against the closed-form formula with the true sources."""
    sources = {5: (200.0 * np.exp(0.35j), 4.0 - 2.5j), 7: (70.0 * np.exp(-0.6j), 6.0 - 3.0j),
               11: (40.0 * np.exp(0.9j), 2.5 - 1.5j)}
    series = [equivalent_source.SourceMeasurement("Z%g" % z, complex(z), "", "v2", 50.0, 0.0,
                                                  {1: 30.0 + 0j, **{m: u / (zq + z) for m, (u, zq) in sources.items()}},
                                                  {})
              for z in (1.0, 10.0)]
    r = equivalent_source.fit_equivalent_source(series, normalization=None, orders=[5, 7, 11], rq_non_negative=False)
    for m, (u, zq) in sources.items():
        assert r.fits[m].Zq == pytest.approx(zq) and abs(r.fits[m].Uq) == pytest.approx(abs(u))
        # both estimators identical (exactly determined)
        assert r.fits[m].comparison["output_error"][1] == pytest.approx(r.fits[m].comparison["equation_error"][1])
    e = equivalent_source.ires_at_impedance(r, 2.0, IG=30.0, rest=False)
    I, parts = fml.residual_current_from_sources(30.0, {m: v[0] for m, v in sources.items()},
                                                 {m: v[1] for m, v in sources.items()}, 2.0)
    assert e["IRES"] == pytest.approx(I, rel=1e-6) and e["IRES"] == pytest.approx(44.55, abs=0.01)
    assert e["parts"][5] == pytest.approx(parts[5]) and e["parts"][11] == pytest.approx(parts[11])


def test_u95_scaling_reports_unscalable_orders(series):
    r = equivalent_source.fit_equivalent_source(series)                       # 3rd harmonic: zero sequence, not normalized
    u = equivalent_source.ires_at_impedance(r, 2.5, u95={3: 50.0, 5: 360.0}, u95_reference="LL")
    assert u["factors"][3] == 1.0 and any("[3" in h for h in u["hints"])
    v = equivalent_source.ires_at_impedance(r, 2.5, u95={5: 360.0}, u95_reference="LL", thd95_percent=3.0,
                                            thd_measured_percent=1.5)
    assert v["factors"][3] == pytest.approx(2.0)              # fallback to the THD factor


def test_messages_in_english():
    """Hints, errors and table texts follow the output language (decimal point in English, decimal comma in
    German); every message has both languages."""
    assert [k for k in i18n.missing_keys("en") + i18n.missing_keys("de") if k.startswith("equivalent_source.")] == []
    o = {5: (300.0, 30.0 - 30.0j)}
    series = [_thevenin_measurement("a", 0.0, "L3", 1.0, o), _thevenin_measurement("b", 2.5, "L3", 1.0, o)]
    with i18n.language("en"):
        r = equivalent_source.fit_equivalent_source(series, reference="pre_fault")
        assert any(h.startswith("Only 2 measurements → two-terminal equivalent exactly determined") for h in r.hints)
        assert any(h.startswith("ill-conditioned: a magnitude error of 1 % or an angle error of 0.5°")
                   for h in r.fits[5].hints)
        assert r.measurements_table()["Z_Ohm"].tolist() == ["0", "2.5"]
        with pytest.raises(ValueError, match="At least two measurements with different additional impedances"):
            equivalent_source.fit_equivalent_source(series[:1])
        with pytest.raises(ValueError, match="^normalization='phase' is not allowed – allowed: 'complex'"):
            equivalent_source.fit_equivalent_source(series, normalization="phase")
    r = equivalent_source.fit_equivalent_source(series, reference="pre_fault")
    assert any(h.startswith("Nur 2 Messungen → Zweipol exakt bestimmt") for h in r.hints)
    table = r.measurements_table()
    assert table["Z_Ohm"].tolist() == ["0", "2,5"] and table["polarity"].tolist() == ["as measured"] * 2


def test_public_names():
    """``__all__`` lists every public function and class of the module and only names that exist."""
    es = equivalent_source
    public = {n for n, v in vars(es).items() if (inspect.isfunction(v) or inspect.isclass(v))
              and v.__module__ == es.__name__ and not n.startswith("_")}
    assert public <= set(es.__all__)
    assert all(hasattr(es, n) for n in es.__all__)


def test_german_labels_of_the_tables(series):
    """The code values of the tables have German labels: the boundary solution (method rq0) and the assessment of
    the pairwise solutions ("ok", "R_q < 0")."""
    o = {5: (300.0, -1.0 - 5.0j)}                                         # R_q < 0: boundary solution
    neg = [_thevenin_measurement(n, z, "L3", 1.0, o) for n, z in (("a", 0.0), ("b", 2.5), ("c", 5.0))]
    r = equivalent_source.fit_equivalent_source(neg, normalization=None)
    assert r.fits[5].method == "rq0" and set(r.pairwise_table()["assessment"]) == {"R_q < 0"}
    src = i18n.localize(r.source_table(), "de")
    assert list(src["Methode"]) == ["randlösung R_q = 0"]
    assert set(i18n.localize(r.pairwise_table(), "de")["Bewertung"]) == {"R_q < 0 (nicht möglich)"}
    pw = equivalent_source.fit_equivalent_source(series).pairwise_table()
    shown = i18n.localize(pw, "de")["Bewertung"]
    assert "ok" in set(pw["assessment"]) and set(shown) <= {"in Ordnung", "R_q < 0 (nicht möglich)"}
    assert i18n.value_label("format", "legacy_complex", "de") == "Altformat (komplexer Export)"


def test_former_and_unknown_options_rejected(series, tmp_path):
    """Options of the equivalent-source method take their English values. level="mittel" (``reference``) used to
    switch the normalization off silently, "natuerlich" and other sequence names, "harmonische" and "automatisch"
    were taken for the default – now each raises with the allowed values and the current name."""
    with pytest.raises(ValueError, match=r"^reference='mittel' ist nicht zulässig – zulässig: 'mean', 'pre_fault', "
                                         r"'post_fault' \('mittel' ist der frühere Name von 'mean'\)$"):
        equivalent_source.fit_equivalent_source(series, reference="mittel")
    with pytest.raises(ValueError, match="'vorfehler' ist der frühere Name von 'pre_fault'"):
        series[0].level(5, "neg", "vorfehler")
    with pytest.raises(ValueError, match="'natuerlich' ist der frühere Name von 'natural'"):
        equivalent_source.fit_equivalent_source(series, sequence="natuerlich")
    with pytest.raises(ValueError, match="'Gegen' ist der frühere Name von 'neg'"):
        equivalent_source.fit_equivalent_source(series, sequence={5: "Gegen"})
    with pytest.raises(ValueError, match="^orders='alle' ist nicht zulässig – zulässig: 'auto'$"):
        equivalent_source.fit_equivalent_source(series, orders="alle")
    r = equivalent_source.fit_equivalent_source(series)
    with pytest.raises(ValueError, match="^IG='maximal' ist nicht zulässig – zulässig: 'max', 'median'$"):
        equivalent_source.ires_at_impedance(r, 2.5, IG="maximal")
    with pytest.raises(ValueError, match="^u95_reference='L-L' ist nicht zulässig – zulässig: 'seq', 'LL'$"):
        equivalent_source.ires_at_impedance(r, 2.5, u95={5: 300.0}, u95_reference="L-L")
    assert equivalent_source.ires_at_impedance(r, 2.5, u95={5: 300.0}, u95_reference="ll")["IRES"] == \
        equivalent_source.ires_at_impedance(r, 2.5, u95={5: 300.0}, u95_reference="LL")["IRES"]
    for name, value, pattern in (("angle_reference", "harmonische", "'harmonische' ist der frühere Name von "
                                                                    "'harmonics'"),
                                 ("polarity", "automatisch", "^polarity='automatisch' ist nicht zulässig"),
                                 ("reference", "L12", "^reference='L12' ist nicht zulässig")):
        with pytest.raises(ValueError, match=pattern):
            equivalent_source.load_measurement(str(tmp_path / "never_read.json"), 0.0, **{name: value})


# ------------------------------------------------------------------ measured source
def _state_change_series(Z=(0.0, 2.0, 4.0), drift_z=(1.0, 1.05 * np.exp(-0.14j), 0.97 * np.exp(0.087j)),
                         Zq=9 * np.exp(-0.436j), U=200.0):
    """Thevenin series whose source impedance changes a little between the tests (network state): the level is the
    pre-fault voltage of the faulted phase L1, Z_q·drift_k the source impedance of test k."""
    out = []
    for k, (z, d) in enumerate(zip(Z, drift_z)):
        out.append(_thevenin_measurement("m%d" % k, z, "L1", 1.0, {5: (U, Zq * d)}))
    return out


def test_measured_source_recovers_exact_series():
    """Exact Thevenin data with source drift and changing faulted phases: the measured source gives U_q = −level and
    the true Z_q from every single test; the fitted and the measured source coincide at any Z_E."""
    series = [_thevenin_measurement("L3 0", 0.0, "L3", 1.0, ORDERS),
              _thevenin_measurement("L1 2.5", 2.5, "L1", 1.1 * np.exp(0.3j), ORDERS),
              _thevenin_measurement("L2 5", 5.0, "L2", 0.9 * np.exp(-0.2j), ORDERS)]
    fitted = equivalent_source.fit_equivalent_source(series, reference="pre_fault")
    for impedance in ("median", "smallest"):
        measured = equivalent_source.measured_source(fitted, impedance=impedance)
        assert measured.settings["source"] == "measured" and fitted.settings["source"] == "fitted"
        for m, (U, Zq) in ORDERS.items():
            F = measured.fits[m]
            assert F.method == "measured" and F.Zq == pytest.approx(Zq, abs=1e-9)
            assert F.Uq == pytest.approx(-F.level_reference) and F.thevenin == pytest.approx(1.0)
            assert F.resid_rel < 1e-9 and "measured" in F.comparison and "equation_error" in F.comparison
        single = measured.single_test_table()
        assert len(single) == 3 * len(ORDERS) and (single["Zq_deviation_pct"].abs() < 1e-6).all()
        assert (measured.jackknife_table(10.0)["span_pct"] < 1e-6).all()
        c = equivalent_source.compare_sources(measured, fitted, [0.0, 5.0, 12.0])
        assert np.allclose(c["fitted_to_measured"], 1.0) and list(c["interpolation"]) == [True] * 6 + [False] * 3
        assert list(c["order"]) == [5, 7, "I_RES"] * 3
    assert any("Gemessene Quelle für die Ordnungen [5, 7]" in h for h in measured.hints)


def test_measured_source_beyond_the_tested_range():
    """The source impedance changes by 3–5 % and 5–8° between three tests (network state): the fitted source voltage
    absorbs it (|U_q|/U_pre ≈ 0.8, hint), within the tested range both sources agree, beyond it the measured source
    stays close to the truth and the fitted one does not."""
    Zq = 9 * np.exp(-0.436j)
    series = _state_change_series(Zq=Zq)
    fitted = equivalent_source.fit_equivalent_source(series, reference="pre_fault", orders=[5])
    th = fitted.fits[5].thevenin
    assert abs(th) == pytest.approx(0.80, abs=0.03)
    assert any("Thevenin-Kontrolle" in h and "10 % bzw. 10°" in h for h in fitted.fits[5].hints)
    measured = equivalent_source.measured_source(fitted)
    true = lambda z: 200.0 / abs(Zq + z)
    assert measured.fits[5].current(12.0) == pytest.approx(true(12.0), rel=0.02)
    assert fitted.fits[5].current(12.0) < 0.93 * true(12.0)
    for k, z in enumerate((0.0, 2.0, 4.0)):              # within the tested range: both near the measured currents
        i = abs(fitted.fits[5].I_fit[k])
        assert fitted.fits[5].current(z) == pytest.approx(i, rel=0.05)
        assert measured.fits[5].current(z) == pytest.approx(i, rel=0.05)
    assert any("geschätzte Ersatzquelle: −U_q/Pegel = 0,8" in h for h in measured.fits[5].hints)
    smallest = equivalent_source.measured_source(fitted, impedance="smallest")
    assert smallest.fits[5].Zq == pytest.approx(Zq, abs=1e-9)                    # the 0-Ω test has no drift
    f = smallest.forecast_table()
    assert f["deviation_pct"].iloc[0] == pytest.approx(0.0, abs=1e-9) and f["deviation_pct"].abs().iloc[1:].max() > 1
    s = measured.single_test_table()
    assert s["Zq_Ohm"].round(3).tolist() == [round(abs(Zq * d), 3) for d in (1.0, 1.05, 0.97)]
    with i18n.language("en"):
        fitted_en = equivalent_source.fit_equivalent_source(series, reference="pre_fault", orders=[5])
        assert any("deviates by more than 10 % or 10°" in h for h in fitted_en.fits[5].hints)
        assert any(h.startswith("fitted equivalent source: −U_q/level = 0.8")
                   for h in equivalent_source.measured_source(fitted_en).fits[5].hints)
    loose = equivalent_source.fit_equivalent_source(series, reference="pre_fault", orders=[5],
                                                    thevenin_tolerance=(0.3, 30.0))
    assert not any("Thevenin" in h for h in loose.fits[5].hints)


def test_loo_table_every_test_from_the_others():
    """Leave-one-out: every test forecast with the model of the other tests (same rule). Exact Thevenin data give 0 %
    with the fitted and the measured source; a change of the network between the tests appears as a deviation, the
    permissible deviation is a parameter without a default; one test leaves nothing to compare."""
    exact = [_thevenin_measurement("L3 0", 0.0, "L3", 1.0, ORDERS),
             _thevenin_measurement("L1 2.5", 2.5, "L1", 1.1 * np.exp(0.3j), ORDERS),
             _thevenin_measurement("L2 5", 5.0, "L2", 0.9 * np.exp(-0.2j), ORDERS)]
    fitted = equivalent_source.fit_equivalent_source(exact, reference="pre_fault")
    for source in (fitted, equivalent_source.measured_source(fitted)):
        t = source.loo_table()
        assert list(t.columns) == ["order", "measurement", "Z_Ohm", "I_measured_A", "I_from_others_A", "deviation_pct",
                                   "deviation_A"]
        assert len(t) == 3 * len(ORDERS) and (t["deviation_pct"].abs() < 1e-6).all()
    measured = equivalent_source.measured_source(
        equivalent_source.fit_equivalent_source(_state_change_series(), reference="pre_fault", orders=[5]))
    t = measured.loo_table(limit_pct=1.0)
    assert t["deviation_pct"].abs().max() > 1.0
    assert list(t["within_limit"]) == [bool(abs(d) <= 1.0) for d in t["deviation_pct"]]
    F = measured.fits[5]                                    # by hand: the first test from the median of the other two
    zk = F.Uq / F.I_fit[1:] - F.Z[1:]
    zq = complex(np.median(zk.real), np.median(zk.imag))
    assert t["I_from_others_A"].iloc[0] == pytest.approx(abs(F.Uq / (zq + F.Z[0])))
    assert set(i18n.localize(t, "de").columns) >= {"I_aus_uebrigen_A", "innerhalb_Grenze", "Abweichung_A"}
    assert np.allclose(t["deviation_A"], t["I_from_others_A"] - t["I_measured_A"])
    big = float(t["deviation_A"].abs().max())                  # an absolute tolerance covers what % does not
    ta = measured.loo_table(limit_pct=1.0, limit_A=big)
    assert ta["within_limit"].all() and not measured.loo_table(limit_A=0.5 * big)["within_limit"].all()
    with pytest.raises(ValueError, match="limit_pct=-1 ist nicht zulässig"):
        measured.loo_table(-1)
    with pytest.raises(ValueError, match="limit_A=-0.5 ist nicht zulässig"):
        measured.loo_table(limit_A=-0.5)
    one = equivalent_source.measured_source([_thevenin_measurement("0 Ω", 0.0, "L2", 1.0, ORDERS)],
                                            reference="pre_fault")
    t1 = one.loo_table(15.0)
    assert t1["deviation_pct"].isna().all() and t1["within_limit"].isna().all()


def test_measured_source_keeps_zero_sequence_and_options(series):
    """Zero-sequence orders keep the fitted equivalent (source in the fault), so do orders not selected; two
    measurements are no longer 'exactly determined' – one calibrates, the other checks."""
    fitted = equivalent_source.fit_equivalent_source(series)
    measured = equivalent_source.measured_source(fitted)
    assert measured.fits[3].method == fitted.fits[3].method != "measured"
    assert measured.fits[3].Zq == fitted.fits[3].Zq
    assert any("Quelle entsteht im Fehler" in h for h in measured.fits[3].hints)
    assert not any("Quelle entsteht im Fehler" in h for h in fitted.fits[3].hints)      # the fitted series unchanged
    assert measured.single_test_table()["order"].unique().tolist() == [5, 7, 11, 13]
    only5 = equivalent_source.measured_source(fitted, orders=[5])
    assert only5.fits[5].method == "measured" and only5.fits[7].method != "measured"
    assert any("nicht unter den gewählten Ordnungen" in h for h in only5.fits[7].hints)
    with pytest.raises(ValueError, match="impedance='zero' ist nicht zulässig"):
        equivalent_source.measured_source(fitted, impedance="zero")
    two = equivalent_source.fit_equivalent_source(series[:2])
    assert any("exakt bestimmt" in h for h in two.hints)
    m2 = equivalent_source.measured_source(two)
    assert not any("exakt bestimmt" in h for h in m2.hints)
    assert np.isfinite(m2.jackknife_table(10.0).query("order == 5")["span_pct"]).all()
    none = equivalent_source.measured_source(equivalent_source.fit_equivalent_source(series, normalization="magnitude"))
    assert all(F.method != "measured" for F in none.fits.values())
    assert any("Gemessene Quelle für keine Ordnung" in h for h in none.hints)


def test_measured_source_negative_resistance():
    """A per-test source impedance with a negative real part (not a pure network impedance) → R_q = 0 with |Z_q|
    kept: the current at Z_E = 0 stays the measured one, for an ohmic Z_E it becomes U/√(|Z_q|² + Z_E²)."""
    o = {5: (150.0, -0.8 - 5.6j)}
    series = [_thevenin_measurement(n, z, "L2", 1.0, o) for n, z in (("a", 0.0), ("b", 2.5), ("c", 5.0))]
    fitted = equivalent_source.fit_equivalent_source(series, reference="pre_fault")
    measured = equivalent_source.measured_source(fitted)
    F = measured.fits[5]
    assert F.Rq_fixed and F.Zq.real == 0 and F.Zq.imag == pytest.approx(-abs(o[5][1]))
    assert F.current(0.0) == pytest.approx(150.0 / abs(o[5][1]))
    assert F.current(7.0) == pytest.approx(150.0 / math.hypot(abs(o[5][1]), 7.0))
    assert any("R_q < 0 mit gemessener Quelle" in h for h in F.hints)
    free = equivalent_source.measured_source(fitted, rq_non_negative=False)
    assert free.fits[5].Zq == pytest.approx(o[5][1]) and not free.fits[5].Rq_fixed


def test_monte_carlo_and_residual_current_with_measured_source(series):
    """Monte Carlo and the residual current work with the measured source; its spread of Z_q contains the demo
    value and the median of I_RES lies at the deterministic value."""
    measured = equivalent_source.measured_source(equivalent_source.fit_equivalent_source(series))
    mc = equivalent_source.monte_carlo(measured, 10.0, n=300, seed=1)
    r = equivalent_source.ires_at_impedance(measured, 10.0)
    assert mc["IRES"][5] <= r["IRES"] <= mc["IRES"][95]
    z = mc["Zq"][5]
    assert z["Rq_P5"] <= 4.5 <= z["Rq_P95"] and z["Xq_P5"] <= -2.5 <= z["Xq_P95"]
    line = equivalent_source.ires_over_line(measured, 2.5, Z1L=0.0, Z0L=0.0)
    assert line["IRES"] == pytest.approx(equivalent_source.ires_at_impedance(measured, 2.5)["IRES"])
    shown = i18n.localize(measured.source_table(), "de")
    assert "gemessene Quelle" in set(shown["Methode"])
    assert set(i18n.localize(measured.single_test_table(), "de").columns) >= {"Zq_Abweichung_proz", "Zq_Winkel_deg"}


def test_measured_source_from_one_test():
    """One test is enough for the measured source: Z_q = U_q/I − Z of that test (exact Thevenin data); an order of
    the zero sequence stays in the remainder (largest current, independent of Z_E). From two or more different
    additional impedances the measurements are fitted first – the same as measured_source(fit_equivalent_source(…))."""
    one = [_thevenin_measurement("0 Ω", 0.0, "L2", 1.1 * np.exp(0.2j), ORDERS, extra={3: 4.0})]
    with pytest.raises(ValueError, match="Mindestens zwei Messungen"):
        equivalent_source.fit_equivalent_source(one)
    measured = equivalent_source.measured_source(one, reference="pre_fault")
    assert measured.settings["source"] == "measured" and sorted(measured.fits) == [5, 7]
    for m, (U, Zq) in ORDERS.items():
        F = measured.fits[m]
        assert F.Zq == pytest.approx(Zq, abs=1e-9) and abs(F.Uq) == pytest.approx(abs(1.1 * U))
    assert any("Ordnungen [3] ohne gemessene Quelle" in h for h in measured.hints)
    r = equivalent_source.ires_at_impedance(measured, 10.0, rest=True)
    assert r["IH_rest"] == pytest.approx(4.0) and r["parts"][5] == pytest.approx(abs(1.1 * ORDERS[5][0] / (ORDERS[5][1] + 10)))
    assert np.isnan(measured.jackknife_table(10.0)["span_pct"]).all()
    assert measured.pairwise_table().empty and len(measured.single_test_table()) == 2
    mc = equivalent_source.monte_carlo(measured, 10.0, n=100, seed=2)
    assert mc["IRES"][5] <= r["IRES"] <= mc["IRES"][95]
    series = [_thevenin_measurement("a", 0.0, "L3", 1.0, ORDERS), _thevenin_measurement("b", 2.5, "L1", 0.9, ORDERS)]
    direct = equivalent_source.measured_source(series, reference="pre_fault")
    via_fit = equivalent_source.measured_source(equivalent_source.fit_equivalent_source(series, reference="pre_fault"))
    assert {m: F.Zq for m, F in direct.fits.items()} == pytest.approx({m: F.Zq for m, F in via_fit.fits.items()})
    with pytest.raises(ValueError, match="Mindestens eine Messung"):
        equivalent_source.measured_source([])
