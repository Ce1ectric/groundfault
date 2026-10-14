# -*- coding: utf-8 -*-
"""Channel roles: assignment of channel names to physical roles.

Two naming schemes are recognised:

* channel names of recorder exports such as ``DANEO 1_Ströme_ISp21 Inst`` (device prefix ``<name> <number>_``,
  channel group, short name, kind of values; see [`short_name`][groundfault.channels.short_name]),
* a structured naming convention ``<quantity>_<voltage level>_<component>_…`` such as ``i_20kv_res_j01_ct_m01_a__raw``
  (quantity ``i`` or ``u``, voltage level such as ``20kv``, ``110kv``, ``400v``, ``0.4kv``, ``0_4kv`` or ``0,4kv``,
  component ``res``, ``coil``, ``l1`` … ``l3``, ``n``, ``l1e`` … ``l3e``, ``l12``, ``l23``, ``l31`` or ``ne``). The
  roles of the medium-voltage network (the faulted network) go to the channels of the MV level of the recording: the
  only level, or – with channels of several levels – the levels from [`MV_MIN_KV`][groundfault.channels.MV_MIN_KV] to
  below [`HV_MIN_KV`][groundfault.channels.HV_MIN_KV]. Line-to-earth voltages of a higher level get the HV roles
  ``u_hv_l1e`` … ``u_hv_l3e``, the neutral current of a lower level the role ``i_pen``; all other channels of other
  levels ``u_gen``/``i_gen``.

Every assignment can be fixed with ``overrides`` (for example from the corrections file of the campaign).

| Role | Meaning |
|---|---|
| ``u_l1e``, ``u_l2e``, ``u_l3e`` | line-to-earth voltages (MV) |
| ``u_hv_l1e``, ``u_hv_l2e``, ``u_hv_l3e`` | line-to-earth voltages (HV) |
| ``u_l12``, ``u_l23``, ``u_l31`` | line-to-line voltages (measured) |
| ``u_ne`` | neutral displacement voltage (measured directly) |
| ``u_e`` | earth potential rise (station; possibly several probe distances) |
| ``u_t`` | touch voltage |
| ``u_gen`` | other voltage |
| ``i_res`` | residual earth-fault current (possibly several CTs) |
| ``i_coil`` | coil current (arc suppression coil) |
| ``i_l1``, ``i_l2``, ``i_l3`` | line currents (transformer) |
| ``i_shield`` | shield current |
| ``i_pen`` | PEN or earth-electrode leakage current |
| ``i_gen`` | other current |

PEN currents at a secondary substation are usually measured at two points. The position
(``ChannelInfo.position``) follows from the channel name or from the role ``i_pen_feeders`` /
``i_pen_busbar`` given in the corrections file or in ``overrides``:

* ``feeders`` (``IPEN_v``) – before the transformer star point: sum of the PEN conductors of all outgoing LV
  cables,
* ``busbar`` (``IPEN_n``) – after the transformer star point: connection to the main earthing busbar of the
  station.

The transformer star point lies in between. The current that the earth fault drives into the LV network flows
through both measuring points (Kirchhoff's current law: the current of the transformer star point – the load
unbalance – does not change because of the earth fault).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from . import i18n
from .i18n import tr
from .legacy import check_option

__all__ = ["ChannelInfo", "RoleAssignment", "detect_role", "detect_roles", "short_name", "pen_position",
           "canonical_role", "role_description", "pen_position_description", "ROLE_DESCRIPTIONS", "ROLE_ALIASES",
           "LEGACY_ROLES", "PEN_POSITION_DESCRIPTIONS", "ONE_METRE_PROBE_MAX_M", "TOUCH_PROBE_MAX_M", "MV_MIN_KV",
           "HV_MIN_KV"]

ONE_METRE_PROBE_MAX_M = 1.5
"""Probes up to this distance (m) measure the touch voltage (measurement at 1 m distance, EN 50522)."""
TOUCH_PROBE_MAX_M = 5.0
"""Without a 1-m probe: the shortest probe up to this distance (m) serves as an approximation of the touch
voltage."""
MV_MIN_KV = 1.0
"""Structured channel names: lowest voltage level (kV) of the medium voltage (below it: low voltage)."""
HV_MIN_KV = 60.0
"""Structured channel names: voltage level (kV) from which on a level counts as high voltage."""

# role code, English description, German description
_ROLES = (
    ("u_l1e", "line-to-earth voltage L1 (MV)", "Leiter-Erde-Spannung L1 (MS)"),
    ("u_l2e", "line-to-earth voltage L2 (MV)", "Leiter-Erde-Spannung L2 (MS)"),
    ("u_l3e", "line-to-earth voltage L3 (MV)", "Leiter-Erde-Spannung L3 (MS)"),
    ("u_hv_l1e", "line-to-earth voltage L1 (HV)", "Leiter-Erde-Spannung L1 (HS)"),
    ("u_hv_l2e", "line-to-earth voltage L2 (HV)", "Leiter-Erde-Spannung L2 (HS)"),
    ("u_hv_l3e", "line-to-earth voltage L3 (HV)", "Leiter-Erde-Spannung L3 (HS)"),
    ("u_l12", "line-to-line voltage L1-L2", "Leiter-Leiter-Spannung L1-L2"),
    ("u_l23", "line-to-line voltage L2-L3", "Leiter-Leiter-Spannung L2-L3"),
    ("u_l31", "line-to-line voltage L3-L1", "Leiter-Leiter-Spannung L3-L1"),
    ("u_ne", "neutral displacement voltage (measured)", "Verlagerungsspannung (gemessen)"),
    ("u_e", "earth potential rise", "Erdungsspannung"),
    ("u_t", "touch voltage", "Berührungsspannung"),
    ("u_gen", "voltage (unspecified)", "Spannung (unbestimmt)"),
    ("i_res", "residual earth-fault current", "Erdschlussreststrom"),
    ("i_coil", "coil current", "Spulenstrom"),
    ("i_l1", "line current L1", "Leiterstrom L1"),
    ("i_l2", "line current L2", "Leiterstrom L2"),
    ("i_l3", "line current L3", "Leiterstrom L3"),
    ("i_shield", "shield current", "Schirmstrom"),
    ("i_pen", "PEN/leakage current", "PEN-/Ableitstrom"),
    ("i_gen", "current (unspecified)", "Strom (unbestimmt)"),
    (None, "– (not assigned)", "– (nicht zugeordnet)"),
)
ROLE_DESCRIPTIONS = {role: en for role, en, _ in _ROLES}
"""Role code → English description (key None: channel without a role). The keys are the valid role codes;
[`role_description`][groundfault.channels.role_description] returns the description in the active language."""
ROLE_ALIASES = {"i_pen_feeders": ("i_pen", "feeders"), "i_pen_busbar": ("i_pen", "busbar"),
                "i_pen_v": ("i_pen", "feeders"), "i_pen_n": ("i_pen", "busbar")}      # i_pen_v/_n: legacy names
"""Additional role names for the corrections file and ``overrides`` → (role, PEN position)."""
LEGACY_ROLES = {"i_schirm": "i_shield", "u_hs_l1e": "u_hv_l1e", "u_hs_l2e": "u_hv_l2e", "u_hs_l3e": "u_hv_l3e",
                "i_pen_v": "i_pen_feeders", "i_pen_n": "i_pen_busbar"}
"""Role names of the predecessor tool (corrections files, result files) → current role."""

# position code, English description, German description (with the German code shown in German tables, see
# i18n.VALUES_DE["position"])
_PEN_POSITIONS = (
    ("feeders", "feeders – LV feeders (before the transformer star point)",
     "v – NS-Abgänge (vor dem Trafoknoten)"),
    ("busbar", "busbar – to the main earthing busbar (after the transformer star point)",
     "n – zur HES (nach dem Trafoknoten)"),
)
PEN_POSITION_DESCRIPTIONS = {position: en for position, en, _ in _PEN_POSITIONS}
"""Position of a PEN current at the station → English description
([`pen_position_description`][groundfault.channels.pen_position_description] returns the description in the active
language)."""


def _role_key(role: Optional[str]) -> str:
    """Message key of a role description (``"channels.role_i_res"``, ``"channels.role_none"``)."""
    return "channels.role_%s" % (role or "none")


def _position_key(position: str) -> str:
    """Message key of a PEN position description (``"channels.pen_position_feeders"``)."""
    return "channels.pen_position_%s" % position


i18n.register({_role_key(role): {"en": en, "de": de} for role, en, de in _ROLES})
i18n.register({_position_key(position): {"en": en, "de": de} for position, en, de in _PEN_POSITIONS})
i18n.register({
    "channels.source_probe": {
        "en": "automatic (probe {distance:g} m)",
        "de": "automatisch (Sonde {distance:g} m)"},
    "channels.source_shortest_probe": {
        "en": "automatic (shortest probe {distance:g} m – approximation)",
        "de": "automatisch (kürzeste Sonde {distance:g} m – Näherung)"},
    "channels.main_channel_not_found": {
        "en": "Main channel {channel!r} for role {role} not among {candidates}",
        "de": "Hauptkanal {channel!r} für Rolle {role} nicht unter {candidates}"},
})


def role_description(role: Optional[str], default: str = "", lang: Optional[str] = None) -> str:
    """Description of a channel role in the active (or given) language.

    Parameters
    ----------
    role : str or None
        Role code such as ``"i_res"`` (see [`ROLE_DESCRIPTIONS`][groundfault.channels.ROLE_DESCRIPTIONS]); None stands
        for a channel without a role.
    default : str, optional
        Returned for a code that is not a role.
    lang : {"en", "de"}, optional
        Output language; default: the active language
        ([`groundfault.i18n.get_language`][groundfault.i18n.get_language]).

    Returns
    -------
    str
        For example ``"residual earth-fault current"`` (English) or ``"Erdschlussreststrom"`` (German).

    Examples
    --------
    >>> role_description("i_coil", lang="en")
    'coil current'
    >>> role_description("i_coil", lang="de")
    'Spulenstrom'
    """
    if role not in ROLE_DESCRIPTIONS:
        return default
    return tr(_role_key(role), lang=lang)


def canonical_role(role: str, option: str = "role", alias: bool = False) -> str:
    """Current code of a role name given in an option (role overrides, main channels, alignment).

    Role names of the predecessor tool ([`LEGACY_ROLES`][groundfault.channels.LEGACY_ROLES], e.g. ``"i_schirm"``) are
    translated, as in the corrections file; the PEN aliases of [`ROLE_ALIASES`][groundfault.channels.ROLE_ALIASES]
    (``"i_pen_feeders"`` …) become ``"i_pen"`` unless ``alias`` is True.

    Parameters
    ----------
    role : str
        Role name.
    option : str, optional
        Name of the option, used in the error message.
    alias : bool, optional
        Keep a PEN alias (role overrides: the alias also gives the position of the PEN current).

    Returns
    -------
    str
        Role code (see [`ROLE_DESCRIPTIONS`][groundfault.channels.ROLE_DESCRIPTIONS]), or the alias.

    Raises
    ------
    ValueError
        For a name that is neither a role nor an alias; the message lists the roles.

    Examples
    --------
    >>> canonical_role("i_schirm")
    'i_shield'
    >>> canonical_role("i_pen_v"), canonical_role("i_pen_v", alias=True)
    ('i_pen', 'i_pen_feeders')
    """
    r = LEGACY_ROLES.get(role, role) if isinstance(role, str) else role
    check_option(option, r, [x for x in ROLE_DESCRIPTIONS if x], aliases=ROLE_ALIASES)
    return r if alias else ROLE_ALIASES.get(r, (r,))[0]


def pen_position_description(position: Optional[str], default: str = "", lang: Optional[str] = None) -> str:
    """Description of the position of a PEN current (``"feeders"``, ``"busbar"``) in the active (or given) language.

    Parameters
    ----------
    position : str or None
        Position code (see [`PEN_POSITION_DESCRIPTIONS`][groundfault.channels.PEN_POSITION_DESCRIPTIONS]).
    default : str, optional
        Returned for None or an unknown code.
    lang : {"en", "de"}, optional
        Output language; default: the active language.

    Returns
    -------
    str
        For example ``"busbar – to the main earthing busbar (after the transformer star point)"``.
    """
    if position not in PEN_POSITION_DESCRIPTIONS:
        return default
    return tr(_position_key(position), lang=lang)


@dataclass
class ChannelInfo:
    """Role of one analog channel of a recording.

    Attributes
    ----------
    index : int
        Channel index in the recording (0-based).
    name : str
        Full channel name.
    short : str
        Short name, e.g. ``"UE_70m"`` (see [`short_name`][groundfault.channels.short_name]).
    group : str
        Channel group of a recorder export (``"Ströme"``, ``"System 1"`` …) or ``""``.
    unit : str
        Unit from the ``.cfg`` file.
    role : str or None
        Role code (see [`ROLE_DESCRIPTIONS`][groundfault.channels.ROLE_DESCRIPTIONS]); None = not assigned or ignored.
    distance_m : float or None
        Probe distance in m (earth-potential and touch-voltage channels).
    source : str
        ``"automatic"`` (detected from the name), ``"override"`` (fixed by ``overrides``) or, for a touch voltage
        derived from the probe distances, a text in the active language such as ``"automatic (probe 1 m)"``.
    position : str or None
        Position of a PEN current: ``"feeders"`` (LV feeders) or ``"busbar"`` (to the main earthing busbar).
    touch_approximation : bool
        True if the role ``u_t`` was given to the shortest probe as an approximation of the touch voltage (no
        probe within [`ONE_METRE_PROBE_MAX_M`][groundfault.channels.ONE_METRE_PROBE_MAX_M]).
    """

    index: int
    name: str
    short: str
    group: str
    unit: str
    role: Optional[str]
    distance_m: Optional[float] = None      # probe distance of earth-potential channels
    source: str = "automatic"               # "automatic" | "override" | text of a derived touch voltage
    position: Optional[str] = None          # PEN current: "feeders" (LV feeders) | "busbar" (to the MEB) | None
    touch_approximation: bool = False       # u_t from the shortest probe (approximation, no 1-m probe)


#: Recorder/device prefix of a channel name: ``<name> <number>_`` (``DANEO 1_``, ``REC 2_``, ``Recorder-A 3_``), and
#: ``DANEO`` with an optional number directly attached (``DANEO_``, ``DANEO1_``)
_DEVICE_PREFIX = re.compile(r"^(?:[a-z][a-z0-9-]*\s+\d+|DANEO\s*\d*)_", re.I)
#: Channel groups of a recorder export (``System 1`` has the form of a device prefix but is a group)
_CHANNEL_GROUP = re.compile(r"^(System\s*\d+|Str.{0,3}me|Spannungen|Currents|Voltages)$", re.I)


def short_name(name: str):
    """Short name, channel group and kind of values of a channel name of a recorder export.

    A recorder/device prefix of the form ``<name> <number>_`` (``DANEO 1_``, ``REC 2_``, ``Recorder-A 3_``; also
    ``DANEO_``/``DANEO1_``) is removed; a channel group such as ``System 1`` is not a device prefix. Names without
    such a prefix are kept as they are.

    Parameters
    ----------
    name : str
        Channel name, e.g. ``"DANEO 1_Spannungen_UE_70m Inst"``.

    Returns
    -------
    short, group, kind : str
        e.g. ``("UE_70m", "Spannungen", "Inst")``; ``group`` and ``kind`` are ``""`` if the name has none.

    Examples
    --------
    >>> short_name("DANEO 1_Spannungen_UE_70m Inst")
    ('UE_70m', 'Spannungen', 'Inst')
    >>> short_name("REC 2_Voltages_V1 RMS")
    ('V1', 'Voltages', 'RMS')
    """
    s = name.strip()
    kind = ""
    m = re.search(r"\s+(Inst|RMS|Raw)$", s, flags=re.I)
    if m:
        kind = m.group(1); s = s[:m.start()]
    m = _DEVICE_PREFIX.match(s)
    if m and not _CHANNEL_GROUP.match(m.group(0)[:-1]):
        s = s[m.end():]
    parts = s.split("_")
    group = ""
    if len(parts) > 1 and _CHANNEL_GROUP.match(parts[0]):
        group = parts[0]; parts = parts[1:]
    return "_".join(parts), group, kind


_STRUCTURED_NAME = re.compile(r"^(?P<qty>[iu])_(?P<vl>\d+(?:[.,_]\d+)?)(?P<vu>k?v)_(?P<comp>[a-z0-9]+)_", re.I)
#: roles of the structured components at the MV level of the recording
_STRUCTURED_MV = {"i": {"res": "i_res", "coil": "i_coil", "l1": "i_l1", "l2": "i_l2", "l3": "i_l3", "n": "i_pen"},
                  "u": {"l1e": "u_l1e", "l2e": "u_l2e", "l3e": "u_l3e", "l12": "u_l12", "l21": "u_l12",
                        "l23": "u_l23", "l31": "u_l31", "ne": "u_ne"}}
#: roles that exist for other levels: HV line-to-earth voltages, the neutral (PEN) current of the low voltage
_STRUCTURED_HV = {"u": {"l1e": "u_hv_l1e", "l2e": "u_hv_l2e", "l3e": "u_hv_l3e"}}
_STRUCTURED_LV = {"i": {"n": "i_pen"}}


def _structured(name: str):
    """(quantity, voltage level in kV, component) of a structured channel name, or None."""
    m = _STRUCTURED_NAME.match(name.strip())
    if not m:
        return None
    value = float(re.sub(r"[,_]", ".", m.group("vl")))
    level = value if m.group("vu").lower() == "kv" else value / 1000.0
    return m.group("qty").lower(), round(level, 9), m.group("comp").lower()


def _mv_levels_kv(names: Sequence[str]) -> set:
    """MV level(s) of a recording from its structured channel names: the only level, or – with several levels – the
    levels from [`MV_MIN_KV`][groundfault.channels.MV_MIN_KV] to below [`HV_MIN_KV`][groundfault.channels.HV_MIN_KV]
    (empty without structured names)."""
    levels = {s[1] for s in map(_structured, names) if s is not None}
    if len(levels) <= 1:
        return levels
    return {v for v in levels if MV_MIN_KV <= v < HV_MIN_KV}


def detect_role(name: str, unit: str = "", mv_levels_kv: Optional[Iterable[float]] = None):
    """Role (and probe distance, if any) of a channel from its name.

    Parameters
    ----------
    name : str
        Channel name (recorder export or structured naming convention).
    unit : str, optional
        Unit of the channel; decides between ``u_gen`` and ``i_gen`` for names that are not recognised.
    mv_levels_kv : iterable of float, optional
        Structured names only: voltage level(s) in kV of the MV network of the recording (see the module description;
        [`detect_roles`][groundfault.channels.detect_roles] determines them from all channel names). A channel of
        another level gets an HV role (line-to-earth voltages from [`HV_MIN_KV`][groundfault.channels.HV_MIN_KV] on),
        the role ``i_pen`` (neutral current below [`MV_MIN_KV`][groundfault.channels.MV_MIN_KV]) or ``u_gen``/``i_gen``.
        Default: the level of ``name`` itself is the MV level.

    Returns
    -------
    role : str or None
        Role code (see [`ROLE_DESCRIPTIONS`][groundfault.channels.ROLE_DESCRIPTIONS]) or None.
    distance_m : float or None
        Probe distance in m for earth-potential channels whose name contains it (``UE_70m``, ``U30m``,
        ``UE100``).

    Examples
    --------
    >>> detect_role("DANEO 1_Spannungen_UE_70m Inst", "V")
    ('u_e', 70.0)
    >>> detect_role("i_20kv_res_j01_ct_m01_a__raw", "A")
    ('i_res', None)
    >>> detect_role("u_110kv_l1e_j03_vt_m01_v__raw", "V", mv_levels_kv=[20.0])
    ('u_hv_l1e', None)
    """
    s = _structured(name)
    if s is not None:  # structured naming convention <quantity>_<voltage level>_<component>_…
        qty, level, comp = s
        if mv_levels_kv is None or any(abs(level - v) <= 1e-9 * max(1.0, abs(v)) for v in mv_levels_kv):
            roles = _STRUCTURED_MV
        elif level >= HV_MIN_KV:
            roles = _STRUCTURED_HV
        elif level < MV_MIN_KV:
            roles = _STRUCTURED_LV
        else:                                           # a second MV level that is not the one of the recording
            roles = {}
        return roles.get(qty, {}).get(comp, "i_gen" if qty == "i" else "u_gen"), None
    short, group, _ = short_name(name)
    k = short.upper().replace(" ", "")
    # --- voltages
    hv = k.endswith("HS") or "HS" in group.upper()
    m = re.match(r"^(?:V|UL?|U_L)([123])E?(HS)?$", k)
    if m and not re.match(r"^U\d+M$", k):
        return ("u_hv_l%se" if (m.group(2) or hv) else "u_l%se") % m.group(1), None
    m = re.match(r"^(?:V|UL?|U_L)([123])([123])$", k)
    if m and m.group(1) != m.group(2):
        par = {"12": "12", "21": "12", "23": "23", "32": "23", "31": "31", "13": "31"}[m.group(1) + m.group(2)]
        return "u_l" + par, None
    if re.match(r"^(UNE|UVE|U0|UNULL|UVERL.*)$", k):
        return "u_ne", None
    if re.match(r"^UT(\d*|_.*)?$", k) or k.startswith("UB"):
        return "u_t", None
    m = re.match(r"^U_?E(?:_?(\d+(?:[.,]\d+)?)\s*M?)?([RL])?$", k)
    if m:
        d = m.group(1)
        return "u_e", (float(d.replace(",", ".")) if d else None)
    m = re.match(r"^U_?(\d+(?:[.,]\d+)?)M$", k)
    if m:
        return "u_e", float(m.group(1).replace(",", "."))
    # --- currents
    if re.match(r"^(I_?F|IRES|IREST|IFEHLER)", k):
        return "i_res", None
    if re.match(r"^(I|E)_?SP", k) or k.startswith("ICOIL") or k.startswith("ISPULE"):
        return "i_coil", None
    m = re.match(r"^IL?([123])$", k)
    if m:
        return "i_l" + m.group(1), None
    if re.match(r"^I_?(SCHIRM|SH)", k) or k == "IS":
        return "i_shield", None
    if re.match(r"^I_?PEN", k):
        return "i_pen", None
    e = (unit or "").strip().upper()
    if e.startswith("V") or e.startswith("KV"):
        return "u_gen", None
    if e.startswith("A") or e.startswith("KA"):
        return "i_gen", None
    return None, None


def pen_position(name: str) -> Optional[str]:
    """Position of a PEN current channel from its name.

    ``IPEN_v``, ``IPENv``, ``IPEN_vor``, ``IPEN_feeders``, ``IPEN_LV`` → ``"feeders"``; ``IPEN_n``, ``IPEN_nach``,
    ``IPEN_busbar``, ``IPEN_MEB`` → ``"busbar"``; otherwise None.
    """
    short, _, _ = short_name(name)
    m = re.match(r"^I_?PEN_?(VOR|NACH|FEEDERS?|BUSBAR|LV|MEB|V|N)\d*$", short.upper().replace(" ", ""))
    if not m:
        return None
    return "feeders" if m.group(1) in ("VOR", "V", "FEEDER", "FEEDERS", "LV") else "busbar"


def _ires_rank(short: str) -> tuple:
    """Sort key for several fault-current channels: IF/I_F before IF1 before IF2 …; with a measuring range in the
    name (IFr500/IFr50) the larger range first (not overdriven)."""
    k = short.upper()
    if k in ("IF", "I_F"):
        return (0, 0)
    m = re.match(r"^I_?F(\d+)$", k)
    if m:
        return (1, int(m.group(1)))
    m = re.match(r"^I_?FR(\d+)$", k)
    if m:
        return (2, -int(m.group(1)))
    return (3, 0)


class RoleAssignment:
    """Result of the role detection for a recording (usually created with
    [`detect_roles`][groundfault.channels.detect_roles]).

    Parameters
    ----------
    names, units : sequence of str
        Channel names and units of the recording.
    overrides : dict, optional
        ``{channel: role or None}`` – fixed role per channel (full or short name); None ignores the channel. Role names
        of the predecessor tool ([`LEGACY_ROLES`][groundfault.channels.LEGACY_ROLES]) and
        [`ROLE_ALIASES`][groundfault.channels.ROLE_ALIASES] are accepted.
    main_channel : dict, optional
        ``{role: channel}`` – main channel of a role (full or short name), see
        [`main`][groundfault.channels.RoleAssignment.main]; role names of the predecessor tool are translated here as
        well.

    Raises
    ------
    ValueError
        For an unknown role in ``overrides`` or ``main_channel``
        ([`canonical_role`][groundfault.channels.canonical_role]).
    distances : dict, optional
        ``{channel: probe distance in m}`` for earth-potential channels whose name contains no distance.

    Attributes
    ----------
    channels : list of ChannelInfo
        One entry per analog channel, in the order of the recording.
    """

    def __init__(self, names: Sequence[str], units: Sequence[str],
                 overrides: Optional[Dict[str, Optional[str]]] = None,
                 main_channel: Optional[Dict[str, str]] = None,
                 distances: Optional[Dict[str, float]] = None):
        overrides = overrides or {}
        distances = distances or {}
        mv_levels = _mv_levels_kv(names)                 # structured names: MV level(s) of the recording
        self.channels: List[ChannelInfo] = []
        for i, (nm, eh) in enumerate(zip(names, units)):
            short, group, _ = short_name(nm)
            role, distance = detect_role(nm, eh, mv_levels)
            source = "automatic"
            position = None
            for key in (nm, short):
                if key in overrides:
                    role = overrides[key]; source = "override"
                    role = canonical_role(role, "overrides", alias=True) if isinstance(role, str) else role
                    break
            if role in ROLE_ALIASES:                         # i_pen_feeders / i_pen_busbar
                role, position = ROLE_ALIASES[role]
            elif role == "i_pen":
                position = pen_position(nm)
            for key in (nm, short):                     # probe distance from the corrections file (distance_m)
                if distances.get(key) is not None:
                    distance = float(distances[key])
                    break
            self.channels.append(ChannelInfo(i, nm, short, group, eh, role, distance, source, position))
        self._main = {canonical_role(r, "main_channel"): k for r, k in (main_channel or {}).items()}
        self._derive_touch_voltage()

    def _derive_touch_voltage(self) -> None:
        """Derive the touch voltage from the probe distances if no channel is explicitly named ``UT…``.

        * Probes at most [`ONE_METRE_PROBE_MAX_M`][groundfault.channels.ONE_METRE_PROBE_MAX_M] (1.5 m) away (``U1m``,
          ``UE1``) measure the (prospective) touch voltage.
        * Without such a probe, but with at least two probes with a known distance, the shortest probe up to
          [`TOUCH_PROBE_MAX_M`][groundfault.channels.TOUCH_PROBE_MAX_M] serves as an approximation (``UE_5m`` next to
          ``UE_70m``); this is stated in the column *source* of the role table (and ``ChannelInfo.touch_approximation``
          is set) and as a hint in the station evaluation.

        Only automatically detected channels are reinterpreted; a role from the corrections file or from
        ``overrides`` stays unchanged.
        """
        if any(k.role == "u_t" for k in self.channels):
            return
        probes = [k for k in self.channels
                  if k.role == "u_e" and k.source == "automatic" and k.distance_m is not None]
        short = [k for k in probes if k.distance_m <= ONE_METRE_PROBE_MAX_M]
        if short:
            for k in short:
                k.role, k.source = "u_t", tr("channels.source_probe", distance=k.distance_m)
            return
        if len(probes) >= 2:
            k = min(probes, key=lambda s: (s.distance_m, s.index))
            if k.distance_m <= TOUCH_PROBE_MAX_M and k.distance_m < max(s.distance_m for s in probes):
                k.role, k.source = "u_t", tr("channels.source_shortest_probe", distance=k.distance_m)
                k.touch_approximation = True

    # -------------------------------------------------------------- queries
    def with_role(self, role: str) -> List[ChannelInfo]:
        """Channels with the role ``role``, best candidate first.

        Fault-current channels are ordered IF/I_F, IF1, IF2 …, then by decreasing measuring range (``IFr500``
        before ``IFr50``); earth-potential channels by decreasing probe distance (the remote probe first).
        """
        ks = [k for k in self.channels if k.role == role]
        if role == "i_res":
            ks.sort(key=lambda k: _ires_rank(k.short))
        if role == "u_e":
            ks.sort(key=lambda k: (-(k.distance_m or 0.0), k.index))
        return ks

    def has(self, *roles: str) -> bool:
        """True if there is at least one channel for each of the given roles."""
        return all(self.with_role(r) for r in roles)

    def main(self, role: str) -> Optional[ChannelInfo]:
        """Main channel of a role: the channel given in ``main_channel``, otherwise the first one of
        [`with_role`][groundfault.channels.RoleAssignment.with_role].

        Returns
        -------
        ChannelInfo or None
            None if no channel has this role.

        Raises
        ------
        KeyError
            If the main channel given for this role does not have this role.
        """
        ks = self.with_role(role)
        if not ks:
            return None
        choice = self._main.get(role)
        if choice:
            for k in ks:
                if choice in (k.name, k.short):
                    return k
            raise KeyError(tr("channels.main_channel_not_found", channel=choice, role=role,
                              candidates=[k.short for k in ks]))
        return ks[0]

    def index(self, role: str) -> Optional[int]:
        """Channel index of the main channel of a role (None if no channel has this role)."""
        k = self.main(role)
        return None if k is None else k.index

    @property
    def line_to_earth(self) -> Optional[List[int]]:
        """Indices of the main channels ``u_l1e``, ``u_l2e``, ``u_l3e`` (None unless all three exist)."""
        ids = [self.index(r) for r in ("u_l1e", "u_l2e", "u_l3e")]
        return None if any(i is None for i in ids) else ids

    @property
    def line_to_earth_hv(self) -> Optional[List[int]]:
        """Indices of the main channels ``u_hv_l1e``, ``u_hv_l2e``, ``u_hv_l3e`` (None unless all three exist)."""
        ids = [self.index(r) for r in ("u_hv_l1e", "u_hv_l2e", "u_hv_l3e")]
        return None if any(i is None for i in ids) else ids

    @property
    def line_currents(self) -> Optional[List[int]]:
        """Indices of the main channels ``i_l1``, ``i_l2``, ``i_l3`` (None unless all three exist)."""
        ids = [self.index(r) for r in ("i_l1", "i_l2", "i_l3")]
        return None if any(i is None for i in ids) else ids

    def capabilities(self) -> Dict[str, bool]:
        """Evaluations that are possible with these channels.

        Returns
        -------
        dict
            ``{capability: bool}`` with ``fault_current`` (``i_res``), ``voltage_analysis`` (three line-to-earth
            voltages), ``angle_method`` (``i_res`` and the line-to-earth voltages or ``u_ne``), ``coil_currents``
            (``i_coil``), ``station`` (``u_e`` or ``u_t``) and ``transformer`` (three line currents and the
            line-to-earth voltages of the MV or HV side).
        """
        le = self.line_to_earth is not None
        return {
            "fault_current": self.has("i_res"),
            "voltage_analysis": le,
            "angle_method": self.has("i_res") and (le or self.has("u_ne")),
            "coil_currents": self.has("i_coil"),
            "station": self.has("u_e") or self.has("u_t"),
            "transformer": self.line_currents is not None and (le or self.line_to_earth_hv is not None),
        }

    def measurement_kind(self) -> str:
        """Kind of measurement derived from [`capabilities`][groundfault.channels.RoleAssignment.capabilities].

        Returns
        -------
        str
            ``"station"``, ``"substation"`` (fault current and line-to-earth voltages without station channels)
            and ``"transformer"``, joined with ``"+"`` (e.g. ``"substation+transformer"``), or
            ``"undetermined"``.
        """
        f = self.capabilities()
        parts = []
        if f["station"]:
            parts.append("station")
        if f["fault_current"] and f["voltage_analysis"] and not f["station"]:
            parts.append("substation")
        if f["transformer"]:
            parts.append("transformer")
        if not parts:
            parts.append("undetermined")
        return "+".join(parts)

    def table(self):
        """Role table for display.

        Returns
        -------
        pandas.DataFrame
            Columns ``no`` (1-based), ``channel``, ``short``, ``unit``, ``role`` (``"–"`` without a role), ``meaning``
            ([`role_description`][groundfault.channels.role_description]), ``main_channel`` (``"✓"``), ``distance_m``,
            ``position`` (only if a PEN position is known,
            [`pen_position_description`][groundfault.channels.pen_position_description]) and ``source``. The
            descriptions are in the active language.
        """
        import pandas as pd
        main = {r: (self.main(r).index if self.main(r) else None)
                 for r in {k.role for k in self.channels if k.role}}
        df = pd.DataFrame([dict(no=k.index + 1, channel=k.name, short=k.short, unit=k.unit,
                                role=k.role or "–", meaning=role_description(k.role),
                                main_channel="✓" if (k.role and main.get(k.role) == k.index) else "",
                                distance_m=k.distance_m, position=pen_position_description(k.position),
                                source=k.source)
                           for k in self.channels])
        if not any(k.position for k in self.channels):
            df = df.drop(columns="position")
        return df

    def as_dict(self) -> Dict[str, Optional[str]]:
        """``{channel name: role}`` of all channels."""
        return {k.name: k.role for k in self.channels}


def detect_roles(names: Sequence[str], units: Sequence[str],
                   overrides: Optional[Dict[str, Optional[str]]] = None,
                   main_channel: Optional[Dict[str, str]] = None,
                   distances: Optional[Dict[str, float]] = None) -> RoleAssignment:
    """Roles of all channels of a recording.

    Channels in ``overrides``, ``main_channel`` and ``distances`` can be given by their full or short name.

    Parameters
    ----------
    names, units : sequence of str
        Channel names and units (``rec.channel_names``, ``rec.units``).
    overrides : dict, optional
        ``{channel: role or None}`` – fixed roles (None ignores the channel).
    main_channel : dict, optional
        ``{role: channel}`` – main channel per role.
    distances : dict, optional
        ``{channel: probe distance in m}`` (e.g. from
        [`groundfault.corrections.Corrections.distances`][groundfault.corrections.Corrections.distances]).

    Returns
    -------
    RoleAssignment
        Roles, main channels and capabilities of the recording.

    Raises
    ------
    ValueError
        For an unknown role in ``overrides`` or ``main_channel``; role names of the predecessor tool are translated
        ([`canonical_role`][groundfault.channels.canonical_role]).

    Examples
    --------
    >>> r = detect_roles(["DANEO 1_Ströme_IF2 Inst", "DANEO 1_Ströme_IF1 Inst"], ["A", "A"])
    >>> r.main("i_res").short
    'IF1'
    """
    return RoleAssignment(names, units, overrides, main_channel, distances)
