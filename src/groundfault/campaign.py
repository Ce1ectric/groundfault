# -*- coding: utf-8 -*-
"""Evaluation of a measurement campaign: overview, consistency checks between the measurements and an assessment
method beyond the single measurement (resistive approach).

Works with [`Result`][groundfault.evaluation.Result] objects or with saved result files
([`load_result`][groundfault.evaluation.load_result]), i.e. without reading the raw data again.
"""
from __future__ import annotations

import math
from typing import Dict, Mapping, Optional

import numpy as np
import pandas as pd

from . import formulas as fml
from . import i18n
from .i18n import tr

__all__ = ["overview", "consistency", "resistive_approach"]

i18n.register({
    # ---- consistency checks: labels (column check), values and comments
    "campaign.check_count": {"en": "Number of measurements", "de": "Anzahl Messungen"},
    "campaign.count_comment": {"en": "the consistency check needs ≥ 2 measurements",
                               "de": "Konsistenzprüfung braucht ≥ 2 Messungen"},
    "campaign.check_equal": {"en": "{quantity} equal in all measurements",
                             "de": "{quantity} gleich in allen Messungen"},
    "campaign.value_span": {"en": "{low} … {high} {unit} (span {span:.1f} %)",
                            "de": "{low} … {high} {unit} (Spanne {span:.1f} %)"},
    "campaign.equal_ok_IG": {"en": "fundamental hardly depends on Z_F – as expected",
                             "de": "Grundschwingung kaum abhängig von Z_F – wie erwartet"},
    "campaign.equal_warning_IG": {"en": "large span of the fundamental → network state or detuning changed?",
                                  "de": "große Spanne der Grundschwingung → Netzzustand oder Verstimmung geändert?"},
    "campaign.equal_ok_UH1n": {"en": "displacement voltage hardly depends on Z_F – as expected",
                               "de": "Verlagerungsspannung kaum abhängig von Z_F – wie erwartet"},
    "campaign.equal_warning_UH1n": {"en": "large span of the displacement voltage → network state or detuning changed?",
                                    "de": "große Spanne der Verlagerungsspannung → Netzzustand oder Verstimmung "
                                          "geändert?"},
    "campaign.check_coil_in": {"en": "Coil current {channel} in {measurement}",
                               "de": "Spulenstrom {channel} in {measurement}"},
    "campaign.value_coil_median": {"en": "{value} A (median {median} A)", "de": "{value} A (Median {median} A)"},
    "campaign.coil_deviation": {"en": "deviates by {deviation:.0f} %{note}", "de": "weicht um {deviation:.0f} % ab{note}"},
    "campaign.coil_factor_note": {"en": " – factor ≈ {factor:g}: check the measuring range/CT ratio",
                                  "de": " – Faktor ≈ {factor:g}: Messbereich/Wandlerübersetzung prüfen"},
    "campaign.coil_state_note": {"en": " – coil position/network state changed?",
                                 "de": " – Spulenstellung/Netzzustand geändert?"},
    "campaign.check_coil": {"en": "Coil current {channel}", "de": "Spulenstrom {channel}"},
    "campaign.value_range": {"en": "{low} … {high} A", "de": "{low} … {high} A"},
    "campaign.coil_equal": {"en": "equal in all measurements", "de": "in allen Messungen gleich"},
    "campaign.check_harmonics": {"en": "I_H decreases with Z_F", "de": "I_H sinkt mit Z_F"},
    "campaign.value_harmonics": {"en": "{z} Ω: {i} A", "de": "{z} Ω: {i} A"},
    "campaign.harmonics_comment": {
        "en": "active Thevenin equivalent: smaller harmonic current with increasing additional impedance; "
              "otherwise source drift",
        "de": "aktiver Zweipol: mit wachsender Zusatzimpedanz kleinerer Oberschwingungsstrom; sonst Quelldrift"},
    "campaign.check_faulted_phase": {"en": "Faulted phase", "de": "Fehlerleiter"},
    "campaign.same_phase": {"en": "all measurements in the same phase", "de": "alle Messungen im selben Leiter"},
    "campaign.different_phases": {"en": "different faulted phases", "de": "unterschiedliche Fehlerleiter"},
    # ---- resistive approach (comment)
    "campaign.resistive_limit_missing": {
        "en": "Resistive approach: no permissible residual current – give I_res_max, or U_Tp and F (missing: "
              "{missing}); the limits are defined by the user.",
        "de": "Resistiver Ansatz: kein zulässiger Erdschlussreststrom – I_res_max oder U_Tp und F angeben (fehlt: "
              "{missing}); die Grenzwerte legt der Anwender fest."},
    "campaign.resistive_fundamental": {
        "en": "I_G ≥ I_RES,max: limit already reached by the fundamental component – countermeasures regardless of "
              "the distance",
        "de": "I_G ≥ I_RES,max: Grenzwert schon durch die Grundschwingung erreicht – Ersatzmaßnahmen unabhängig "
              "von der Entfernung"},
    "campaign.resistive_uncritical": {
        "en": "R_lim ≤ 0: even for a fault directly at the substation I_H = U/(r·R_E) = {ih:.1f} A stays below "
              "I_H,perm = {ih_perm:.1f} A → uncritical in the whole network",
        "de": "R_Grenz ≤ 0: selbst bei einem Fehler direkt am UW bleibt I_H = U/(r·R_E) = {ih:.1f} A unter "
              "I_H,zul = {ih_perm:.1f} A → im ganzen Netz unkritisch"},
    "campaign.resistive_limit": {
        "en": "stations with a line length to the substation below l_lim = {l_lim:.2f} km can exceed the limit → "
              "individual verification (equivalent-source method) or countermeasures; uncritical further away",
        "de": "Stationen mit einer Leitungslänge zum UW unter l_Grenz = {l_lim:.2f} km können den Grenzwert "
              "überschreiten → Einzelnachweis (Ersatzquellenverfahren) oder Ersatzmaßnahmen; weiter entfernt "
              "unkritisch"},
})


def _assessment(e, quantity: str, column: str = "measured_value") -> float:
    """Value of ``quantity`` in the table ``assessment_quantities`` of a result (NaN if missing)."""
    df = e.tables.get("assessment_quantities")
    if df is None or df.empty:
        return float("nan")
    s = df[df["quantity"] == quantity]
    return float(s[column].iloc[0]) if len(s) else float("nan")


def _metric(e, interval: str, column: str) -> float:
    """Value of ``column`` for ``interval`` in the table ``voltage_metrics`` of a result (NaN if missing)."""
    df = e.tables.get("voltage_metrics")
    if df is None or df.empty:
        return float("nan")
    s = df[df["interval"] == interval]
    return float(s[column].iloc[0]) if len(s) and column in s else float("nan")


def overview(results: Mapping[str, object]) -> pd.DataFrame:
    """One row per measurement with the main characteristic values.

    Parameters
    ----------
    results : mapping of str to Result or ResultFile
        Results of the campaign by measurement name.

    Returns
    -------
    pandas.DataFrame
        Columns ``measurement``, ``Z_F in Ω``, ``IRES in A``, ``IG in A``, ``Iw in A``, ``Iv in A``, ``IH in A``
        (total harmonic content √(IRES² − IG²)), ``IH3 in A``, ``IH5 in A``, ``IH7 in A``, ``U0 in V``,
        ``UH5g pre-fault in V``, ``UH7m pre-fault in V``, ``THD pre-fault (max) in %`` (largest of the three
        line-to-line loops), ``Σ coils H1 in A``, ``faulted_phase``, ``Corrections`` (total correction factor per
        channel) and ``notes`` (number of hints).
    """
    z = []
    for nm, e in results.items():
        w = e.values
        zf = getattr(e, "z_fault_ohm", None)
        if zf is None:
            zf = w.get("Z_fault", np.nan)
        thd_pre = max((_metric(e, "pre_fault", c) for c in ("UTHD12_pct", "UTHD23_pct", "UTHD31_pct")),
                      default=np.nan)
        sp = e.tables.get("coil_currents")
        corr = ((getattr(e, "data", None) or {}).get("meta", {}) or {}).get("corrections") or []
        total = {}
        for k in corr:
            total[k.get("short", k.get("channel", "?"))] = k.get("factor_total", k.get("factor"))
        z.append({"measurement": nm, "Z_F in Ω": zf, "IRES in A": w.get("IRES", np.nan), "IG in A": w.get("IG", np.nan),
                  "Iw in A": w.get("Iw", np.nan), "Iv in A": w.get("Iv", np.nan),
                  "IH in A": w.get("IH_total", np.nan), "IH3 in A": _assessment(e, "IH3"),
                  "IH5 in A": _assessment(e, "IH5"), "IH7 in A": _assessment(e, "IH7"), "U0 in V": _assessment(e, "UH1n"),
                  "UH5g pre-fault in V": _metric(e, "pre_fault", "UH5g_V"),
                  "UH7m pre-fault in V": _metric(e, "pre_fault", "UH7m_V"),
                  "THD pre-fault (max) in %": thd_pre,
                  "Σ coils H1 in A": float(sp["H1_A"].sum()) if sp is not None and not sp.empty else np.nan,
                  "faulted_phase": w.get("faulted_phase", ""),
                  "Corrections": "; ".join("%s ×%s" % (kk, i18n.format_number(f, digits=6)) for kk, f in total.items()),
                  "notes": len(getattr(e, "hints", []))})
    return pd.DataFrame(z)


def consistency(results: Mapping[str, object], tolerance: float = 0.10) -> pd.DataFrame:
    """Check physical relations **between** the measurements of a campaign.

    * The fundamental component I_G and the neutral displacement voltage U0 hardly depend on the fault
      resistance (Z_F ≪ 1/|Y0|) → nearly equal in all measurements.
    * The coil currents (H1) are proportional to U0 → nearly equal per coil; a factor ≈ 10 indicates a wrong
      measuring range or CT ratio. A coil current of 0 A (coil switched off, clamp not connected) cannot be
      assessed this way and is left out like a missing value.
    * The harmonic content must decrease with increasing Z_F (active Thevenin equivalent).
    * Faulted phase (and polarity) should agree.

    Parameters
    ----------
    results : mapping of str to Result or ResultFile
        Results of the campaign by measurement name.
    tolerance : float
        Permissible relative span or deviation (0.10 = 10 %).

    Returns
    -------
    pandas.DataFrame
        One row per check with the columns ``check``, ``status`` (OK, NOTE, WARNING or INFO), ``value`` and
        ``comment``.
    """
    pr = []

    def p(check, status, value, comment):
        pr.append(dict(check=check, status=status, value=value, comment=comment))

    names = list(results)
    if len(names) < 2:
        return pd.DataFrame([dict(check=tr("campaign.check_count"), status="INFO", value=str(len(names)),
                                  comment=tr("campaign.count_comment"))])
    for quantity, sym, unit in (("IG", "I_G", "A"), ("UH1n", "U0", "V")):
        v = np.array([results[n].values.get(quantity, np.nan) if quantity == "IG" else _assessment(results[n], quantity)
                      for n in names], float)
        if np.isfinite(v).sum() >= 2:
            sp = np.nanmax(v) / np.nanmin(v) - 1
            ok = sp < tolerance
            p(tr("campaign.check_equal", quantity=sym), "OK" if ok else "WARNING",
              tr("campaign.value_span", low=_z(np.nanmin(v)), high=_z(np.nanmax(v)), unit=unit, span=100 * sp),
              tr("campaign.equal_%s_%s" % ("ok" if ok else "warning", quantity)))
    # coil currents per channel
    channels: Dict[str, Dict[str, float]] = {}
    for n in names:
        sp = results[n].tables.get("coil_currents")
        if sp is None or sp.empty:
            continue
        for _, r in sp.iterrows():
            channels.setdefault(r["channel"], {})[n] = float(r["H1_A"])
    for k, all_values in channels.items():
        # a coil current of 0 A (or a missing one) cannot be assessed as a ratio: left out like a missing value
        values = {n: v for n, v in all_values.items() if np.isfinite(v) and v > 0}
        if len(values) < 2:
            continue
        med = float(np.median(list(values.values())))
        for n, v in values.items():
            q = v / med if med > 0 else np.nan
            if not np.isfinite(q):
                continue
            if abs(q - 1) > tolerance:
                factor = 10 ** round(math.log10(q))
                note = (tr("campaign.coil_factor_note", factor=factor)
                        if abs(math.log10(q)) > 0.7 else tr("campaign.coil_state_note"))
                p(tr("campaign.check_coil_in", channel=k, measurement=n), "WARNING",
                  tr("campaign.value_coil_median", value=_z(v), median=_z(med)),
                  tr("campaign.coil_deviation", deviation=100 * (q - 1), note=note))
        if all(abs(v / med - 1) <= tolerance for v in values.values() if med > 0):
            p(tr("campaign.check_coil", channel=k), "OK",
              tr("campaign.value_range", low=_z(min(values.values())), high=_z(max(values.values()))),
              tr("campaign.coil_equal"))
    # harmonic content over Z_F
    zf = [(getattr(results[n], "z_fault_ohm", None) or results[n].values.get("Z_fault"), n) for n in names]
    zf = [(z, n) for z, n in zf if z is not None and np.isfinite(z)]
    if len(zf) >= 2:
        zf.sort()
        ih = [results[n].values.get("IH_total", np.nan) for _, n in zf]
        mono = all(a >= b * 0.95 for a, b in zip(ih[:-1], ih[1:]))
        p(tr("campaign.check_harmonics"), "OK" if mono else "NOTE",
          " → ".join(tr("campaign.value_harmonics", z=_z(z), i=_z(v)) for (z, _), v in zip(zf, ih)),
          tr("campaign.harmonics_comment"))
    fl = {results[n].values.get("faulted_phase", "") for n in names} - {""}
    if fl:
        p(tr("campaign.check_faulted_phase"), "OK" if len(fl) == 1 else "NOTE", ", ".join(sorted(fl)),
          tr("campaign.same_phase") if len(fl) == 1 else tr("campaign.different_phases"))
    return pd.DataFrame(pr)


def _z(x: float) -> str:
    """Number with three significant digits as in the report tables, with the decimal separator of the output
    language."""
    from .report import number
    return number(x, 3, lang=i18n.get_language())


def resistive_approach(U_thd95_V: float, I_G: float, R_E_max: float, R1_km: float, R0_km: float,
                      I_res_max: Optional[float] = None, U_Tp: Optional[float] = None, F: Optional[float] = None,
                      r: float = 1.0, from_ll: bool = False) -> Dict[str, float]:
    """Resistive approach: limiting resistance and critical distance of a network.

    The harmonic voltage drives the harmonic current through the fault circuit (3·R_E plus the line
    resistances). The limiting resistance R_lim = 3·U/√(I_RES,max² − I_G²) − 3·r·R_E,max is the line resistance
    below which the residual current can exceed I_RES,max; the critical distance is
    l_lim = R_lim/(R1' + R2' + R0') with R2' = R1'.

    Parameters
    ----------
    U_thd95_V : float
        Harmonic voltage (95 % quantile) in the positive/negative sequence in V; with ``from_ll=True`` the
        largest line-to-line value (divided by √3).
    I_G : float
        Fundamental component of the residual current in A.
    R_E_max : float
        Largest earthing resistance of the stations in Ω.
    R1_km, R0_km : float
        Positive- and zero-sequence resistance per unit length of the line at the dominant frequency in Ω/km.
    I_res_max : float, optional
        Permissible residual current in A, defined by the user; None = limit from the permissible touch voltage
        I_RES,max = F·U_Tp/(r·R_E,max), which needs ``U_Tp`` and ``F``.
    U_Tp : float, optional
        Permissible touch voltage in V, defined by the user (needed without ``I_res_max``).
    F : float, optional
        Ratio of the permissible earth potential rise to the permissible touch voltage, defined by the user (needed
        without ``I_res_max``).
    r : float
        Reduction factor.
    from_ll : bool
        ``U_thd95_V`` is a line-to-line value.

    Returns
    -------
    dict
        ``U_seq_V``, ``I_RES_max_A``, ``I_H_permissible_A`` (√(I_RES,max² − I_G²)), ``R_E_effective_Ohm``
        (r·R_E,max), ``R_limit_Ohm``, ``l_limit_km``, ``assessment_substation`` (``"uncritical"`` or
        ``"countermeasures"`` for a fault at the substation) and ``comment`` (in the output language).

    Raises
    ------
    ValueError
        Without ``I_res_max`` if ``U_Tp`` or ``F`` is not given (the message names the missing parameters) –
        groundfault has no defaults for limits.

    Notes
    -----
    The resistive approach of the VDE Impuls on the residual earth-fault current (see References and
    [`groundfault.formulas.limit_resistance`][groundfault.formulas.limit_resistance]), generalised in three points:

    * F and r are parameters: I_RES,max = F·U_Tp/(r·R_E,max), where the VDE Impuls has I_RES,max ≤ 2·U_Tp/R_E,max;
    * r·R_E,max acts in the fault circuit, where the VDE Impuls has R_E,max (r = 1, its worst case). For r < 1 only
      r·R_E acts in the fault circuit (U_E = r·Z_E·I_F, as in the limit from the permissible touch voltage), so
      r·R_E,max is used consistently; with R_E,max alone the limiting resistance would be too small (not
      conservative);
    * the resistances per unit length give the critical distance l_lim, where the VDE Impuls compares the total
      resistance of each fault path with R_Grenz.

    With r = 1 and the same I_RES,max, R_limit_Ohm is the R_Grenz of the VDE Impuls. ``U_thd95_V`` is its
    √Σ_{ν>1} U_q,max(ν)² (sequence value, line-to-earth); a line-to-line value is divided by √3 (``from_ll``), which
    is unrelated to the factor 3 of the series connection of the sequence systems.

    References
    ----------
    VDE ETG: *VDE Impuls „Erdschluss-Reststrom in Mittelspannungsnetzen: Eine (überschätzte) Gefahr?“* VDE Verband der
    Elektrotechnik Elektronik Informationstechnik e. V., Energietechnische Gesellschaft (ETG), Frankfurt am Main,
    October 2021. <https://www.vde.com/resource/blob/2091758/8372514d5f581c4f86fd14aaffe4cfa2/vde-impuls-erdschlussreststrom-in-mittelspannungsnetzen-eine-ueberschaetzte-gefahr--data.pdf>
    """
    U = fml.sequence_voltage_from_ll(U_thd95_V) if from_ll else U_thd95_V
    if I_res_max is None:
        missing = [n for n, v in (("U_Tp", U_Tp), ("F", F)) if v is None]
        if missing:
            raise ValueError(tr("campaign.resistive_limit_missing", missing=", ".join(missing)))
        I_max = fml.max_residual_current(R_E_max, U_Tp, F, r)
    else:
        I_max = I_res_max
    R_E_effective = r * R_E_max
    Rg = fml.limit_resistance(float(U), I_max, I_G, R_E_effective)
    lg = fml.limit_distance(Rg, R1_km, R0_km)
    I_perm = math.sqrt(max(I_max ** 2 - I_G ** 2, 0.0))
    if not math.isfinite(Rg):
        comment_ = tr("campaign.resistive_fundamental")
    elif Rg <= 0:
        comment_ = tr("campaign.resistive_uncritical", ih=U / R_E_effective, ih_perm=I_perm)
    else:
        comment_ = tr("campaign.resistive_limit", l_lim=lg)
    return {"U_seq_V": float(U), "I_RES_max_A": float(I_max), "I_H_permissible_A": I_perm,
            "R_E_effective_Ohm": float(R_E_effective), "R_limit_Ohm": float(Rg), "l_limit_km": float(lg),
            "assessment_substation": fml.resistive_assessment(Rg, 0.0, 0.0, 0.0), "comment": comment_}
