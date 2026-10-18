# -*- coding: utf-8 -*-
"""Impedances of the fault loop from network data – for the estimates without a staged fault test.

The forecast without an earth fault takes the impedances of the fault loop from the data a network operator has:
the rating plate of the transformer, the short-circuit power of the HV network, the capacitive earth-fault current
and the operating capacitance of the MV network. All values are referred to the MV side.

* [`transformer_reactance`][groundfault.forecast.network_data.transformer_reactance] – X_T = u_k·U_n²/S_rT;
* [`hv_network_reactance`][groundfault.forecast.network_data.hv_network_reactance] – X_Q = c·U_n²/S″_k;
* [`at_order`][groundfault.forecast.network_data.at_order] – an impedance at order m from its reactance at the
  fundamental and an R/X ratio you choose, m·X·(R/X + j);
* [`earth_capacitance`][groundfault.forecast.network_data.earth_capacitance] – C_E = I_C/(3·ω₁·U_LE) per phase;
* [`mv_network_from_data`][groundfault.forecast.network_data.mv_network_from_data] – the MV network as a damping G in
  parallel with its operating capacitance C_1, Z_MV = 1/(G + j·m·ω₁·C_1);
* [`resonance_order`][groundfault.forecast.network_data.resonance_order] – the parallel resonance of the busbar,
  m_r = √(X_C1/X_up) with X_C1 = 1/(ω₁·C_1).

The R/X ratios, the damping G and the operating capacitance are assumptions about the network; the package contains
no values for them.
"""
from __future__ import annotations

import math

__all__ = ["transformer_reactance", "hv_network_reactance", "at_order", "earth_capacitance", "mv_network_from_data",
           "resonance_order"]


def transformer_reactance(u_k: float, S_rT: float, U_n: float) -> float:
    """Short-circuit reactance of the transformer at the fundamental, X_T = u_k·U_n²/S_rT.

    Parameters
    ----------
    u_k : float
        Short-circuit voltage as a fraction (0.14 for 14 %).
    S_rT : float
        Rated power in VA.
    U_n : float
        Nominal voltage (line-to-line) of the side the impedance is referred to, in V.

    Returns
    -------
    float
        Reactance in Ω.
    """
    return float(u_k) * float(U_n) ** 2 / float(S_rT)


def hv_network_reactance(S_k: float, U_n: float, c: float = 1.1) -> float:
    """Reactance of the HV network at the fundamental from its short-circuit power, X_Q = c·U_n²/S″_k.

    Parameters
    ----------
    S_k : float
        Initial symmetrical short-circuit power S″_k of the HV network in VA.
    U_n : float
        Nominal voltage (line-to-line) of the side the impedance is referred to, in V.
    c : float, optional
        Voltage factor of the short-circuit calculation (1.1 = c_max of IEC 60909 for nominal voltages above 1 kV).

    Returns
    -------
    float
        Reactance in Ω.
    """
    return float(c) * float(U_n) ** 2 / float(S_k)


def at_order(X1: float, m: int, r_x: float) -> complex:
    """Impedance at order m from the reactance at the fundamental with a constant R/X ratio: m·X1·(R/X + j).

    Parameters
    ----------
    X1 : float
        Reactance at the fundamental in Ω (e.g. X_T + X_Q).
    m : int
        Harmonic order.
    r_x : float
        Ratio R/X at order m – your assumption (smaller for the transformer than for the HV network).

    Returns
    -------
    complex
        Impedance in Ω.
    """
    return complex(r_x, 1.0) * float(m) * float(X1)


def earth_capacitance(I_C: float, U_LE: float, f1: float = 50.0) -> float:
    """Earth capacitance of the MV network from its capacitive earth-fault current, C_E = I_C/(3·ω₁·U_LE).

    Parameters
    ----------
    I_C : float
        Capacitive earth-fault current in A (e.g. from the coil controller).
    U_LE : float
        Line-to-earth voltage (fundamental) in V.
    f1 : float, optional
        Mains frequency in Hz.

    Returns
    -------
    float
        Capacitance line-to-earth per phase in F.
    """
    return float(I_C) / (3.0 * 2.0 * math.pi * float(f1) * float(U_LE))


def mv_network_from_data(m: int, G: float, C_1: float, f1: float = 50.0) -> complex:
    """Impedance of the MV network seen from the busbar at order m from a damping and the operating capacitance:
    Z_MV = 1/(G + j·m·ω₁·C_1).

    The operating capacitance C_1 comes from the cable lengths, or as C_1 ≈ q·C_E from the earth capacitance (cable
    networks q ≈ 1, mixed networks somewhat more); the damping G of the MV network at the order (loads, lines) is
    an assumption – measure it in undisturbed operation where you can
    ([`mv_network_impedance`][groundfault.transformer.mv_network_impedance]).

    Parameters
    ----------
    m : int
        Harmonic order.
    G : float
        Conductance of the MV network at order m in S.
    C_1 : float
        Operating capacitance of the MV network per phase in F.
    f1 : float, optional
        Mains frequency in Hz.

    Returns
    -------
    complex
        Impedance in Ω.
    """
    return 1.0 / complex(float(G), float(m) * 2.0 * math.pi * float(f1) * float(C_1))


def resonance_order(X_up: float, C_1: float, f1: float = 50.0) -> float:
    """Order of the parallel resonance of the busbar, m_r = √(X_C1/X_up) with X_C1 = 1/(ω₁·C_1).

    The upstream impedance (transformer and HV network) resonates with the operating capacitance of the MV network.
    Above about m_r both are capacitive in the fault loop and the classical estimate lies above the current; below
    m_r the positive and negative sequence are inductive and partly cancel the capacitive zero sequence, and the
    current can exceed the classical estimate (see
    [`classical_bound`][groundfault.forecast.bounds.classical_bound]).

    Parameters
    ----------
    X_up : float
        Upstream reactance at the fundamental in Ω (X_T + X_Q).
    C_1 : float
        Operating capacitance of the MV network per phase in F.
    f1 : float, optional
        Mains frequency in Hz.

    Returns
    -------
    float
        The resonance order m_r.
    """
    X_C1 = 1.0 / (2.0 * math.pi * float(f1) * float(C_1))
    return math.sqrt(X_C1 / float(X_up))
