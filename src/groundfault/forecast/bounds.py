# -*- coding: utf-8 -*-
"""Estimates of the harmonic fault current without a staged fault test (methods V0 to V3 of the
[forecast overview](https://ce1ectric.github.io/groundfault/forecast/)).

All use the capacitive zero-sequence impedance of a tuned network, Z_0,m = 1/(j·(m/X_C0 − 1/(m·X_L0))) with
X_C0 = 3·U_LE/I_C and X_L0 = 3·U_LE/I_L:

* [`classical_bound`][groundfault.forecast.bounds.classical_bound] (V0) – without positive and negative sequence;
* [`resonance_bound`][groundfault.forecast.bounds.resonance_bound] (V1) – at the parallel resonance of the busbar with
  an upper limit of the damping;
* [`network_data_estimate`][groundfault.forecast.bounds.network_data_estimate] and
  [`network_data_envelope`][groundfault.forecast.bounds.network_data_envelope] (V2) – the full fault loop from network
  data with an assumed damping G of the MV network, and the largest current over a range of G;
* [`network_estimate`][groundfault.forecast.bounds.network_estimate] (V3) – with the impedance of the MV network
  measured in undisturbed operation ([`mv_network_impedance`][groundfault.transformer.mv_network_impedance]) and the
  upstream impedance: the fault loop of the forecast model with every quantity taken from undisturbed operation and
  network data.

The first two give an order of magnitude; neither is an upper bound at every order: below the parallel resonance m_r
of the busbar ([`resonance_order`][groundfault.forecast.network_data.resonance_order]) Z_1 + Z_2 is inductive and
partly cancels the capacitive Z_0 (a series resonance of the fault loop, for a cable network with m_r ≈ 5 near m ≈ 3),
and the current can exceed the classical estimate severalfold. Above m_r both are capacitive and the classical
estimate lies above the current. None of them contains a source that arises only in the fault (the orders 3, 9,
15 … of the zero sequence).
"""
from __future__ import annotations

from typing import Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from .network_data import mv_network_from_data

__all__ = ["classical_bound", "resonance_bound", "network_data_estimate", "network_data_envelope", "network_estimate",
           "estimates_without_fault"]


def _z0_capacitive(m: int, I_C: float, U_LE: float, I_L: Optional[float]) -> complex:
    XC0 = 3 * U_LE / I_C
    XL0 = 3 * U_LE / (I_L if I_L else I_C)
    return 1.0 / (1j * (m / XC0 - 1.0 / (m * XL0)))


def classical_bound(U_m: float, m: int, I_C: float, U_LE: float, Z_F: complex = 0.0,
                    I_L: Optional[float] = None) -> float:
    """Classical estimate of the fault current of order m without positive and negative sequence (Z_1 = Z_2 = 0):
    3·U_m/|Z_0,m + 3·Z_F| with the capacitive zero-sequence impedance from I_C and the coils (≈ m·I_C·U_m/U_LE).
    Not an upper bound below the resonance of the busbar (see the module notes).

    Parameters
    ----------
    U_m : float
        Harmonic voltage (line-to-earth) in V.
    m : int
        Harmonic order.
    I_C : float
        Capacitive earth-fault current in A.
    U_LE : float
        Line-to-earth voltage (fundamental) in V.
    Z_F : complex, optional
        Fault impedance in Ω.
    I_L : float, optional
        Coil current in A (default I_C, tuned network).

    Returns
    -------
    float
        Current in A.
    """
    return float(3 * abs(U_m) / abs(_z0_capacitive(m, I_C, U_LE, I_L) + 3 * complex(Z_F)))


def resonance_bound(U_m: float, m: int, I_C: float, U_LE: float, G_max: float, Z_F: complex = 0.0,
                    I_L: Optional[float] = None) -> float:
    """Estimate for the order at the resonance of the transformer node: 3·U_m/|2/G_max + Z_0,m + 3·Z_F| (Z_1 = Z_2 =
    1/G at the resonance, G_max = upper limit of the damping of the MV network – a value you define).

    Parameters
    ----------
    U_m, m, I_C, U_LE, Z_F, I_L
        As in [`classical_bound`][groundfault.forecast.bounds.classical_bound].
    G_max : float
        Upper limit of the damping (conductance) of the MV network at that frequency in S.

    Returns
    -------
    float
        Current in A.
    """
    return float(3 * abs(U_m) / abs(2.0 / G_max + _z0_capacitive(m, I_C, U_LE, I_L) + 3 * complex(Z_F)))


def network_estimate(U_m: float, m: int, Z_mv: complex, Z_up: complex, I_C: float, U_LE: float, Z_F: complex = 0.0,
                     I_L: Optional[float] = None, d: float = 0.0, Z_mv_neg: Optional[complex] = None) -> float:
    """Fault current of order m from quantities of undisturbed operation and network data – without a staged test.

    Fault loop at the busbar, I = 3·U_m/|Z_0,m + Z_1,m + Z_2,m + 3·Z_F|, with

    * Z_1 = (1/Z_up + 1/Z_mv)⁻¹ and Z_2 likewise with ``Z_mv_neg`` – the upstream impedance (transformer and HV
      network, e.g. from nameplate and S″_k or from the transformer node) parallel to the MV network measured in
      undisturbed operation ([`mv_network_impedance`][groundfault.transformer.mv_network_impedance]);
    * Z_0 = the capacitive zero-sequence impedance from I_C with the coils (as in
      [`classical_bound`][groundfault.forecast.bounds.classical_bound]) plus the series resistance d·X_C0 – with the
      damping d = I_w/I_C of the coil controller as a resistance in series with the earth capacitances.

    An estimate, not a bound: the deviations of I_C, d and the effective earth capacitance at the order from their
    values at 50 Hz enter directly, and the source that arises in the fault (orders 3, 9, 15 …) is missing.

    Parameters
    ----------
    U_m : float
        Harmonic voltage (line-to-earth) of the busbar in V.
    m : int
        Harmonic order.
    Z_mv : complex
        Impedance of the MV network seen from the busbar at order m in Ω (positive sequence).
    Z_up : complex
        Upstream impedance (transformer and HV network) at order m in Ω.
    I_C : float
        Capacitive earth-fault current in A.
    U_LE : float
        Line-to-earth voltage (fundamental) in V.
    Z_F : complex, optional
        Fault impedance in Ω.
    I_L : float, optional
        Coil current in A (default I_C, tuned network).
    d : float, optional
        Damping I_w/I_C (series resistance d·X_C0 of the zero sequence).
    Z_mv_neg : complex, optional
        Impedance of the MV network in the negative sequence (default ``Z_mv``).

    Returns
    -------
    float
        Current in A.
    """
    XC0 = 3 * U_LE / I_C
    Z0 = _z0_capacitive(m, I_C, U_LE, I_L) + d * XC0
    Zup = complex(Z_up)
    Z1 = 1.0 / (1.0 / Zup + 1.0 / complex(Z_mv))
    Z2 = 1.0 / (1.0 / Zup + 1.0 / complex(Z_mv if Z_mv_neg is None else Z_mv_neg))
    return float(3 * abs(U_m) / abs(Z0 + Z1 + Z2 + 3 * complex(Z_F)))


def network_data_estimate(U_m: float, m: int, G: float, C_1: float, Z_up: complex, I_C: float, U_LE: float,
                          Z_F: complex = 0.0, I_L: Optional[float] = None, d: float = 0.0,
                          f1: float = 50.0) -> float:
    """Fault current of order m from network data with an assumed damping of the MV network (V2).

    The fault loop of [`network_estimate`][groundfault.forecast.bounds.network_estimate] with the MV network from
    its damping G and its operating capacitance C_1, Z_MV = 1/(G + j·m·ω₁·C_1)
    ([`mv_network_from_data`][groundfault.forecast.network_data.mv_network_from_data]), in the positive and the
    negative sequence alike. Near the parallel resonance of the busbar G sets the current, and G is the least known
    quantity: the result is an estimate for the G you assume;
    [`network_data_envelope`][groundfault.forecast.bounds.network_data_envelope] gives the largest current over a
    range of G.

    Parameters
    ----------
    U_m : float
        Harmonic voltage (line-to-earth) of the busbar in V.
    m : int
        Harmonic order.
    G : float
        Conductance of the MV network at order m in S – your assumption.
    C_1 : float
        Operating capacitance of the MV network per phase in F.
    Z_up : complex
        Upstream impedance (transformer and HV network) at order m in Ω, e.g.
        ``at_order(X_T + X_Q, m, R/X)`` ([`at_order`][groundfault.forecast.network_data.at_order]).
    I_C : float
        Capacitive earth-fault current in A.
    U_LE : float
        Line-to-earth voltage (fundamental) in V.
    Z_F : complex, optional
        Fault impedance in Ω.
    I_L : float, optional
        Coil current in A (default I_C, tuned network).
    d : float, optional
        Damping I_w/I_C (series resistance d·X_C0 of the zero sequence).
    f1 : float, optional
        Mains frequency in Hz.

    Returns
    -------
    float
        Current in A.
    """
    return network_estimate(U_m, m, mv_network_from_data(m, G, C_1, f1), Z_up, I_C, U_LE, Z_F=Z_F, I_L=I_L, d=d)


def network_data_envelope(U_m: float, m: int, G_min: float, G_max: float, C_1: float, Z_up: complex, I_C: float,
                          U_LE: float, Z_F: complex = 0.0, I_L: Optional[float] = None, d: float = 0.0,
                          f1: float = 50.0, points: int = 201) -> Tuple[float, float]:
    """Largest fault current of order m over a range of the damping of the MV network (V2, envelope).

    [`network_data_estimate`][groundfault.forecast.bounds.network_data_estimate] for G from ``G_min`` to ``G_max``
    (``points`` values, both ends included); the current is not monotonic in G – near the resonance a larger damping
    can raise it. With ``d = 0`` (the default) the zero sequence has no damping either. The envelope would be a bound
    if G lay in the range and C_1, Z_up and Z_0 were right; without a measurement that is not certain.

    Parameters
    ----------
    U_m, m, C_1, Z_up, I_C, U_LE, Z_F, I_L, d, f1
        As in [`network_data_estimate`][groundfault.forecast.bounds.network_data_estimate].
    G_min, G_max : float
        Range of the conductance of the MV network at order m in S – your assumption.
    points : int, optional
        Number of values of G.

    Returns
    -------
    (float, float)
        The largest current in A and the conductance in S at which it occurs.
    """
    gs = np.linspace(float(G_min), float(G_max), max(2, int(points)))
    currents = [network_data_estimate(U_m, m, g, C_1, Z_up, I_C, U_LE, Z_F=Z_F, I_L=I_L, d=d, f1=f1) for g in gs]
    k = int(np.argmax(currents))
    return float(currents[k]), float(gs[k])


def estimates_without_fault(voltages: Mapping[int, float], I_C: float, U_LE: float, Z_up: Mapping[int, complex],
                            Z_F: Union[float, Sequence[float]] = 0.0, I_L: Optional[float] = None, d: float = 0.0,
                            C_1: Optional[float] = None, m_r: Optional[float] = None, G_max: Optional[float] = None,
                            G: Optional[float] = None, G_range: Optional[Tuple[float, float]] = None,
                            Z_mv: Optional[Mapping[int, complex]] = None, f1: float = 50.0) -> pd.DataFrame:
    """The estimates without an earth fault side by side – per order and fault impedance, and I_H over the orders.

    * ``V0_A`` – [`classical_bound`][groundfault.forecast.bounds.classical_bound];
    * ``V1_A`` – [`resonance_bound`][groundfault.forecast.bounds.resonance_bound] with ``G_max``;
    * ``V2_A`` – [`network_data_estimate`][groundfault.forecast.bounds.network_data_estimate] with ``G`` and ``C_1``;
    * ``V2_envelope_A`` and ``G_envelope_S`` – [`network_data_envelope`][groundfault.forecast.bounds.network_data_envelope]
      over ``G_range`` with ``C_1``, without damping of the zero sequence (d = 0);
    * ``V3_A`` – [`network_estimate`][groundfault.forecast.bounds.network_estimate] with the MV network measured in
      undisturbed operation (``Z_mv`` per order, the natural sequence for both sequences – the MV network is
      symmetrical).

    A column is left out when its inputs are missing. The rows ``order == "I_H"`` hold √Σ I_m² over the orders of the
    table for each fault impedance – only these orders, without a source that arises in the fault.

    Parameters
    ----------
    voltages : mapping
        ``{order: U_m}`` – harmonic voltage (line-to-earth) of the busbar in V, e.g. the 95 % quantile.
    I_C, U_LE, I_L, d, f1
        As in [`network_estimate`][groundfault.forecast.bounds.network_estimate].
    Z_up : mapping
        ``{order: upstream impedance in Ω}``, e.g. from
        [`at_order`][groundfault.forecast.network_data.at_order].
    Z_F : float or sequence, optional
        Fault impedance(s) in Ω.
    C_1 : float, optional
        Operating capacitance of the MV network per phase in F (V2).
    m_r : float, optional
        Resonance order of the busbar ([`resonance_order`][groundfault.forecast.network_data.resonance_order]) – adds
        the column ``m_over_mr``.
    G_max : float, optional
        Upper limit of the damping for V1 in S.
    G : float, optional
        Damping for the V2 estimate in S.
    G_range : (float, float), optional
        Range of the damping for the V2 envelope in S.
    Z_mv : mapping, optional
        ``{order: Z_MV in Ω}`` measured in undisturbed operation (V3).

    Returns
    -------
    pandas.DataFrame
        ``order`` (or ``"I_H"``), ``f_Hz``, ``m_over_mr``, ``Z_F_Ohm``, ``U_V`` and the columns of the methods in A.
    """
    zfs = [float(z) for z in (Z_F if isinstance(Z_F, (list, tuple)) else [Z_F])]
    orders = sorted(int(m) for m in voltages)
    methods = ["V0_A"] + (["V1_A"] if G_max is not None else []) + (["V2_A"] if G is not None and C_1 else []) + \
              (["V2_envelope_A"] if G_range is not None and C_1 else []) + \
              (["V3_A"] if Z_mv is not None and any(m in Z_mv for m in orders) else [])
    rows = []
    for zf in zfs:
        for m in orders:
            U = abs(complex(voltages[m]))
            r = dict(order=m, f_Hz=m * f1, Z_F_Ohm=zf, U_V=U)
            if m_r:
                r["m_over_mr"] = m / m_r
            r["V0_A"] = classical_bound(U, m, I_C, U_LE, Z_F=zf, I_L=I_L)
            if "V1_A" in methods:
                r["V1_A"] = resonance_bound(U, m, I_C, U_LE, G_max, Z_F=zf, I_L=I_L)
            if "V2_A" in methods:
                r["V2_A"] = network_data_estimate(U, m, G, C_1, Z_up[m], I_C, U_LE, Z_F=zf, I_L=I_L, d=d, f1=f1)
            if "V2_envelope_A" in methods:
                r["V2_envelope_A"], r["G_envelope_S"] = network_data_envelope(U, m, G_range[0], G_range[1], C_1,
                                                                              Z_up[m], I_C, U_LE, Z_F=zf, I_L=I_L,
                                                                              d=0.0, f1=f1)
            if "V3_A" in methods:
                z = Z_mv.get(m)
                r["V3_A"] = (network_estimate(U, m, z, Z_up[m], I_C, U_LE, Z_F=zf, I_L=I_L, d=d)
                             if z is not None and np.isfinite(complex(z)) else float("nan"))
            rows.append(r)
        part = [r for r in rows if r["Z_F_Ohm"] == zf and r["order"] != "I_H"]
        total = dict(order="I_H", Z_F_Ohm=zf)
        for c in methods:
            total[c] = float(np.sqrt(sum(r[c] ** 2 for r in part)))
        rows.append(total)
    df = pd.DataFrame(rows)
    first = ["order", "f_Hz"] + (["m_over_mr"] if m_r else []) + ["Z_F_Ohm", "U_V"]
    rest = [c for c in df.columns if c not in first]
    return df[first + rest]
