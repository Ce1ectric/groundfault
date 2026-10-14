# -*- coding: utf-8 -*-
"""Symmetrical components (Fortescue), line-to-line quantities and a common angle reference.

Convention (rotation operator a = e^{j120°}), phase sequence L1-L2-L3::

    U0 = (Ua + Ub + Uc)/3             zero sequence
    U1 = (Ua + a·Ub + a²·Uc)/3        positive sequence
    U2 = (Ua + a²·Ub + a·Uc)/3        negative sequence

Natural sequence of symmetrical harmonics of order m::

    m mod 3 = 1 → positive sequence (1, 7, 13, …), = 2 → negative sequence (5, 11, …), = 0 → zero sequence (3, 9, …)

Common angle reference: every measurement has its own time origin. Referring all phasors of order m to the
fundamental of a reference quantity (e.g. U_L1L2,1 with the angle φ), i.e. X̂_m = X_m·e^{−j·m·φ}, makes the
result independent of the time origin – a time shift τ rotates X_m by m·ω1·τ and φ by ω1·τ.
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np

A = np.exp(2j * np.pi / 3)
"""Rotation operator a = e^{j120°}."""
A2 = A * A
"""Square of the rotation operator, a² = e^{j240°}."""

__all__ = ["A", "A2", "fortescue", "inverse_fortescue", "line_to_line", "sequence_of_order",
           "rotate_to_reference", "reference_angle", "sequence_quantities"]


def fortescue(xa, xb, xc) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Symmetrical components of three phase quantities.

    Parameters
    ----------
    xa, xb, xc : array_like
        Complex phasors of L1, L2 and L3 (scalars or arrays of equal shape).

    Returns
    -------
    x0, x1, x2 : numpy.ndarray
        Zero, positive and negative sequence.

    Examples
    --------
    A symmetrical positive-sequence system has only a positive-sequence component:

    >>> import numpy as np
    >>> x0, x1, x2 = fortescue(1.0, A2, A)
    >>> np.round([abs(x0), abs(x1), abs(x2)], 12).tolist()
    [0.0, 1.0, 0.0]
    """
    xa = np.asarray(xa); xb = np.asarray(xb); xc = np.asarray(xc)
    x0 = (xa + xb + xc) / 3.0
    x1 = (xa + A * xb + A2 * xc) / 3.0
    x2 = (xa + A2 * xb + A * xc) / 3.0
    return x0, x1, x2


def inverse_fortescue(x0, x1, x2) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Phase quantities from the symmetrical components (inverse of [`fortescue`][groundfault.symmetrical.fortescue]).

    Parameters
    ----------
    x0, x1, x2 : array_like
        Zero, positive and negative sequence.

    Returns
    -------
    xa, xb, xc : numpy.ndarray
        Phasors of L1, L2 and L3.
    """
    x0 = np.asarray(x0); x1 = np.asarray(x1); x2 = np.asarray(x2)
    xa = x0 + x1 + x2
    xb = x0 + A2 * x1 + A * x2
    xc = x0 + A * x1 + A2 * x2
    return xa, xb, xc


def line_to_line(ua, ub, uc) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Line-to-line phasors from line-to-earth phasors.

    Parameters
    ----------
    ua, ub, uc : array_like
        Line-to-earth phasors of L1, L2 and L3.

    Returns
    -------
    u12, u23, u31 : numpy.ndarray
        U_L1-L2 = Ua − Ub, U_L2-L3 = Ub − Uc and U_L3-L1 = Uc − Ua.
    """
    ua = np.asarray(ua); ub = np.asarray(ub); uc = np.asarray(uc)
    return ua - ub, ub - uc, uc - ua


def sequence_of_order(m: int) -> str:
    """Natural sequence of a symmetrical harmonic of order ``m``.

    Returns
    -------
    str
        ``"pos"`` (m mod 3 = 1), ``"neg"`` (m mod 3 = 2) or ``"zero"`` (m mod 3 = 0).

    Examples
    --------
    >>> sequence_of_order(5), sequence_of_order(7), sequence_of_order(3)
    ('neg', 'pos', 'zero')
    """
    r = int(m) % 3
    return {1: "pos", 2: "neg", 0: "zero"}[r]


def reference_angle(u_reference_fundamental) -> np.ndarray:
    """Angle φ in rad of the fundamental phasor of the reference quantity."""
    return np.angle(u_reference_fundamental)


def rotate_to_reference(x_m, order, phi_ref):
    """Phasor independent of the time origin: X̂_m = X_m·e^{−j·m·φ_ref}.

    Parameters
    ----------
    x_m : array_like
        Phasor(s) of order ``order``.
    order : int or array_like
        Harmonic order m.
    phi_ref : float or array_like
        Angle of the fundamental of the reference quantity in rad
        ([`reference_angle`][groundfault.symmetrical.reference_angle]).

    Returns
    -------
    numpy.ndarray
    """
    return np.asarray(x_m) * np.exp(-1j * np.asarray(order) * np.asarray(phi_ref))


def sequence_quantities(ua, ub, uc) -> Dict[str, np.ndarray]:
    """All derived voltage quantities of three line-to-earth phasors.

    Returns
    -------
    dict
        ``U_L1E``, ``U_L2E``, ``U_L3E`` (line-to-earth), ``U_L12``, ``U_L23``, ``U_L31`` (line-to-line),
        ``U_zero``, ``U_pos`` and ``U_neg`` (symmetrical components).
    """
    u0, u1, u2 = fortescue(ua, ub, uc)
    u12, u23, u31 = line_to_line(ua, ub, uc)
    return {"U_L1E": np.asarray(ua), "U_L2E": np.asarray(ub), "U_L3E": np.asarray(uc),
            "U_L12": u12, "U_L23": u23, "U_L31": u31,
            "U_zero": u0, "U_pos": u1, "U_neg": u2}
