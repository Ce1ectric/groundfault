# -*- coding: utf-8 -*-
"""COMTRADE input and output (IEEE C37.111, revisions 1991, 1999 and 2013).

Memory-friendly: the ``.dat`` file is opened as a *memory map*; only
[`Recording.read`][groundfault.comtrade.Recording.read] and
[`Recording.read_time`][groundfault.comtrade.Recording.read_time] turn an excerpt into physical floating-point values.
The envelope and the RMS trend over the *whole* recording are computed block by block, so even 24-min recordings at 40
kHz (≈ 1 GB) need little RAM.

Supported: BINARY (int16), BINARY32 (int32), FLOAT32 and ASCII data files; digital channels; ``timemult``;
conversion of secondary to primary values (PS field); missing-value markers (0x8000 …). The ``.cfg`` file is read
as UTF-8, otherwise as cp1252 (DANEO recorders write channel names such as ``DANEO 1_Ströme_IF1 Inst`` in cp1252).

Examples
--------
>>> from groundfault import open_recording
>>> with open_recording("recording.cfg") as rec:                  # doctest: +SKIP
...     t, x = rec.read_time(2.0, 2.2, ["IF1"])                   # 200 ms of the channel IF1
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import warnings
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from . import i18n
from .i18n import tr

__all__ = [
    "AnalogChannel", "DigitalChannel", "Recording", "ComtradeError",
    "open_recording", "write_comtrade",
]

_MISSING = {"BINARY": -32768, "BINARY32": -2147483648}
_DTYPE = {"BINARY": "<i2", "BINARY32": "<i4", "FLOAT32": "<f4"}

i18n.register({
    "comtrade.no_dat": {
        "en": "No .dat file found next to {path}.",
        "de": "Keine .dat neben {path} gefunden."},
    "comtrade.cfg_too_short": {
        "en": "CFG too short: {path}",
        "de": "CFG zu kurz: {path}"},
    "comtrade.line2_unreadable": {
        "en": "Line 2 (TT,##A,##D) not readable: {line!r}",
        "de": "Zeile 2 (TT,##A,##D) unlesbar: {line!r}"},
    "comtrade.unknown_format": {
        "en": "Unknown file format {format!r}",
        "de": "Unbekanntes Dateiformat {format!r}"},
    "comtrade.skew": {
        "en": "Channel skew given in the .cfg – it is not corrected.",
        "de": "Kanal-Skew in der .cfg angegeben – wird nicht korrigiert."},
    "comtrade.several_rates": {
        "en": "Several different sampling rates {rates} are not supported.",
        "de": "Mehrere unterschiedliche Abtastraten {rates} werden nicht unterstützt."},
    "comtrade.dat_size": {
        "en": "DAT size is not a multiple of the record length ({rest} B left over) – file possibly truncated.",
        "de": "DAT-Größe kein Vielfaches der Satzlänge ({rest} B Rest) – Datei evtl. abgeschnitten."},
    "comtrade.sample_count": {
        "en": "CFG states {expected} samples, DAT contains {found}.",
        "de": "CFG nennt {expected} Abtastwerte, DAT enthält {found}."},
    "comtrade.fs_manual": {
        "en": "manual (FS_OVERRIDE)",
        "de": "manuell (FS_OVERRIDE)"},
    "comtrade.fs_timestamps_rate0": {
        "en": "timestamps (cfg rate 0)",
        "de": "Zeitstempel (cfg-Rate 0)"},
    "comtrade.no_fs": {
        "en": "Sampling rate can be determined neither from the .cfg nor from the timestamps.",
        "de": "Abtastrate weder aus .cfg noch aus Zeitstempeln bestimmbar."},
    "comtrade.fs_deviation": {
        "en": "Sampling rate from the timestamps ({fs_timestamps:.3f} Hz) deviates by {deviation:.2f} % from the "
              ".cfg ({fs_cfg:.3f} Hz) – check the time base (diagnosis).",
        "de": "Abtastrate aus Zeitstempeln ({fs_timestamps:.3f} Hz) weicht um {deviation:.2f} % von der .cfg "
              "({fs_cfg:.3f} Hz) ab – Zeitbasis prüfen (Diagnose)."},
    "comtrade.index_out_of_range": {
        "en": "Channel index {index} outside 0…{last}",
        "de": "Kanalindex {index} außerhalb 0…{last}"},
    "comtrade.channel_ambiguous": {
        "en": "Channel {channel!r} not found unambiguously (matches: {matches})",
        "de": "Kanal {channel!r} nicht eindeutig gefunden (Treffer: {matches})"},
    "comtrade.correction_factor": {
        "en": "Correction factor must be finite and ≠ 0 (channel {channel}: {factor!r}).",
        "de": "Korrekturfaktor muss endlich und ≠ 0 sein (Kanal {channel}: {factor!r})."},
    "comtrade.empty_range": {
        "en": "Empty range [{i0}, {i1}) with {n} samples.",
        "de": "Leerer Bereich [{i0}, {i1}) bei {n} Abtastwerten."},
    "comtrade.timestamps_32bit": {
        "en": "Timestamps > 32 bit – increase timemult.",
        "de": "Zeitstempel > 32 bit – timemult erhöhen."},
})


class ComtradeError(Exception):
    """Formal error in a ``.cfg`` or ``.dat`` file."""


@dataclass
class AnalogChannel:
    """Analog channel as described in the ``.cfg`` file.

    Attributes
    ----------
    number : int
        Channel number (``An``).
    name : str
        Channel name (``ch_id``).
    phase : str
        Phase identification (``ph``).
    ccbm : str
        Circuit component being monitored.
    unit : str
        Unit (``uu``), e.g. ``"V"`` or ``"A"``.
    a, b : float
        Multiplier and offset: physical value = a·x + b for the stored value x.
    skew_us : float
        Time skew of the channel in µs (read, but not corrected).
    min_value, max_value : float
        Range of the stored values.
    primary, secondary : float
        Primary and secondary rated value of the instrument transformer.
    ps : str
        ``"P"`` if the stored values are primary values, ``"S"`` if they are secondary values.
    """

    number: int
    name: str
    phase: str = ""
    ccbm: str = ""
    unit: str = ""
    a: float = 1.0
    b: float = 0.0
    skew_us: float = 0.0
    min_value: float = -32767.0
    max_value: float = 32767.0
    primary: float = 1.0
    secondary: float = 1.0
    ps: str = "P"

    @property
    def primary_factor(self) -> float:
        """Factor that converts a·x + b into primary values (primary/secondary for ``ps="S"``, otherwise 1)."""
        if self.ps.upper() == "S" and self.secondary not in (0, 0.0):
            return float(self.primary) / float(self.secondary)
        return 1.0


@dataclass
class DigitalChannel:
    """Digital (status) channel as described in the ``.cfg`` file.

    Attributes
    ----------
    number : int
        Channel number (``Dn``).
    name : str
        Channel name (``ch_id``).
    phase : str
        Phase identification (``ph``).
    ccbm : str
        Circuit component being monitored.
    normal_state : int
        Normal state of the channel (``y``, 0 or 1).
    """

    number: int
    name: str
    phase: str = ""
    ccbm: str = ""
    normal_state: int = 0


def _f(s: str, default: float = 0.0) -> float:
    """Number from a ``.cfg`` field; an empty or unreadable field gives ``default``."""
    s = (s or "").strip()
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _read_text(path: str) -> Tuple[str, str]:
    """Text of a file and the encoding it was decoded with (UTF-8, cp1252, finally latin-1)."""
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"


def _parse_time(s: str, rev: str) -> Optional[_dt.datetime]:
    """Time stamp ``'dd/mm/yyyy,hh:mm:ss.ffffff'`` (1999/2013) or ``'mm/dd/yy,…'`` (1991); None if unreadable."""
    s = s.strip()
    if not s or "," not in s:
        return None
    date, time = [x.strip() for x in s.split(",", 1)]
    m = re.match(r"^(\d{1,2}):(\d{1,2}):(\d{1,2})(?:\.(\d+))?$", time)
    if not m:
        return None
    hh, mi, ss, frac = m.groups()
    us = int((frac or "0")[:6].ljust(6, "0"))
    d = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", date)
    if not d:
        return None
    p1, p2, yy = (int(x) for x in d.groups())
    if yy < 100:
        yy += 2000 if yy < 70 else 1900
    order_ = [(p2, p1), (p1, p2)] if rev in ("1991", "") else [(p1, p2), (p2, p1)]
    for day, month in order_:
        try:
            return _dt.datetime(yy, month, day, int(hh), int(mi), int(ss), us)
        except ValueError:
            continue
    return None


def _dat_path(cfg_path: str) -> Optional[str]:
    """Path of the ``.dat`` file next to ``cfg_path`` (extension in any of the usual cases) or None."""
    stem, _ = os.path.splitext(cfg_path)
    for ext in (".dat", ".DAT", ".Dat"):
        if os.path.exists(stem + ext):
            return stem + ext
    return None


class Recording:
    """Opened COMTRADE recording (metadata and memory map of the raw data).

    Time axis: ``t = i / fs`` (seconds from the first sample). Physical values per channel:
    ``(a·x + b) · primary_factor`` (primary values), multiplied by the correction factor of the channel
    ([`set_correction`][groundfault.comtrade.Recording.set_correction]). Usually created with
    [`open_recording`][groundfault.comtrade.open_recording].

    Parameters
    ----------
    cfg_path : str
        Path of the ``.cfg`` file; the ``.dat`` file must lie next to it (same stem).
    fs_source_pref : {"auto", "cfg", "timestamps"}, optional
        Source of the sampling rate, see [`open_recording`][groundfault.comtrade.open_recording].
    fs_override : float, optional
        Enforce this sampling rate in Hz.
    primary_values : bool, optional
        Convert secondary values to primary values (PS field), default True.

    Attributes
    ----------
    cfg_path, dat_path : str
        Absolute path of the ``.cfg`` file and path of the ``.dat`` file.
    station, device, revision : str
        First line of the ``.cfg`` file (station name, recording device, revision year).
    analog : list of AnalogChannel
        Analog channels.
    digital : list of DigitalChannel
        Digital channels.
    n : int
        Number of samples.
    fs : float
        Sampling rate used, in Hz.
    fs_source : str
        Origin of ``fs``: ``"cfg"``, ``"timestamp"`` or a text for an enforced rate or a cfg rate of 0.
    fs_cfg, fs_timestamps : float
        Sampling rate from the ``.cfg`` file and from the timestamps (NaN without timestamps).
    t_start, t_trigger : datetime.datetime or None
        Time of the first sample and of the trigger.
    line_frequency : float
        Nominal line frequency from the ``.cfg`` file in Hz.
    file_format : str
        ``"ASCII"``, ``"BINARY"``, ``"BINARY32"`` or ``"FLOAT32"``.
    timemult : float
        Multiplication factor of the timestamps.
    cfg_encoding : str
        Encoding the ``.cfg`` file was decoded with.
    warnings : list of str
        Findings while reading (channel skew, truncated ``.dat`` file, sample count, deviating sampling rate) in
        the active language.
    corrections : list of dict
        Applied correction factors (see [`set_correction`][groundfault.comtrade.Recording.set_correction]).

    Raises
    ------
    ComtradeError
        For a missing ``.dat`` file, a malformed ``.cfg`` file, an unsupported format or an undeterminable
        sampling rate.
    """

    def __init__(self, cfg_path: str, fs_source_pref: str = "auto",
                 fs_override: Optional[float] = None, primary_values: bool = True):
        self.cfg_path = os.path.abspath(cfg_path)
        self.primary_values = primary_values
        self.warnings: List[str] = []
        self._parse_cfg()
        self.dat_path = _dat_path(self.cfg_path)
        if self.dat_path is None:
            raise ComtradeError(tr("comtrade.no_dat", path=self.cfg_path))
        self._open_dat()
        self._determine_fs(fs_source_pref, fs_override)

    # ------------------------------------------------------------------ .cfg
    def _parse_cfg(self) -> None:
        """Read the ``.cfg`` file: station line, channel counts, channels, sampling rates, times, format."""
        text, self.cfg_encoding = _read_text(self.cfg_path)
        rows = [z.strip() for z in text.splitlines()]
        while rows and not rows[-1]:
            rows.pop()
        if len(rows) < 6:
            raise ComtradeError(tr("comtrade.cfg_too_short", path=self.cfg_path))
        i = 0
        f0 = [x.strip() for x in rows[i].split(",")] + ["", ""]
        self.station, self.device, self.revision = f0[0], f0[1], (f0[2] or "1991")
        i += 1
        f1 = [x.strip().upper() for x in rows[i].split(",")]
        try:
            n_a = int(f1[1].rstrip("A")); n_d = int(f1[2].rstrip("D"))
        except (IndexError, ValueError) as e:
            raise ComtradeError(tr("comtrade.line2_unreadable", line=rows[i])) from e
        i += 1
        self.analog: List[AnalogChannel] = []
        for _ in range(n_a):
            p = [x.strip() for x in rows[i].split(",")] + [""] * 13
            i += 1
            self.analog.append(AnalogChannel(
                number=int(_f(p[0], len(self.analog) + 1)), name=p[1], phase=p[2], ccbm=p[3],
                unit=p[4], a=_f(p[5], 1.0), b=_f(p[6], 0.0), skew_us=_f(p[7], 0.0),
                min_value=_f(p[8], -32767), max_value=_f(p[9], 32767),
                primary=_f(p[10], 1.0), secondary=_f(p[11], 1.0), ps=(p[12] or "P").upper()))
        self.digital: List[DigitalChannel] = []
        for _ in range(n_d):
            p = [x.strip() for x in rows[i].split(",")]
            i += 1
            if len(p) >= 5:
                self.digital.append(DigitalChannel(int(_f(p[0], 0)), p[1], p[2], p[3], int(_f(p[4], 0))))
            else:
                self.digital.append(DigitalChannel(int(_f(p[0], 0)), p[1] if len(p) > 1 else "",
                                                 normal_state=int(_f(p[-1], 0))))
        self.line_frequency = _f(rows[i], 50.0); i += 1
        nrates = int(_f(rows[i], 0)); i += 1
        self.sample_rates: List[Tuple[float, int]] = []
        for _ in range(max(nrates, 1)):
            p = [x.strip() for x in rows[i].split(",")]
            i += 1
            self.sample_rates.append((_f(p[0], 0.0), int(_f(p[1] if len(p) > 1 else "0", 0))))
        self.nrates = nrates
        self.t_start = _parse_time(rows[i], self.revision); i += 1
        self.t_trigger = _parse_time(rows[i], self.revision); i += 1
        self.file_format = rows[i].strip().upper() if i < len(rows) else "BINARY"
        i += 1
        self.timemult = 1.0
        if i < len(rows) and rows[i]:
            self.timemult = _f(rows[i], 1.0) or 1.0
        if self.file_format not in ("ASCII", "BINARY", "BINARY32", "FLOAT32"):
            raise ComtradeError(tr("comtrade.unknown_format", format=self.file_format))
        if any(abs(k.skew_us) > 0 for k in self.analog):
            self.warnings.append(tr("comtrade.skew"))
        rates = {r for r, _ in self.sample_rates if r > 0}
        if len(rates) > 1:
            raise ComtradeError(tr("comtrade.several_rates", rates=sorted(rates)))

    # ------------------------------------------------------------------ .dat
    def _open_dat(self) -> None:
        """Open the ``.dat`` file (memory map for binary formats, fully read for ASCII) and set up the scaling."""
        n_a, n_d = len(self.analog), len(self.digital)
        self._n_words = (n_d + 15) // 16
        self._ascii = None
        self._mm = None
        if self.file_format == "ASCII":
            data = np.loadtxt(self.dat_path, delimiter=",", ndmin=2)
            self._ascii = data
            self.n = data.shape[0]
        else:
            fields = [("n", "<u4"), ("t", "<u4")]
            if n_a:
                fields.append(("ana", _DTYPE[self.file_format], (n_a,)))
            if self._n_words:
                fields.append(("dig", "<u2", (self._n_words,)))
            dtype = np.dtype(fields)
            quantity = os.path.getsize(self.dat_path)
            self.n = quantity // dtype.itemsize
            rest = quantity - self.n * dtype.itemsize
            if rest:
                self.warnings.append(tr("comtrade.dat_size", rest=rest))
            self._mm = np.memmap(self.dat_path, dtype=dtype, mode="r", shape=(self.n,))
        endsamp = self.sample_rates[-1][1] if self.sample_rates else 0
        if endsamp and endsamp != self.n:
            self.warnings.append(tr("comtrade.sample_count", expected=endsamp, found=self.n))
        a = np.array([k.a for k in self.analog], dtype=np.float64)
        b = np.array([k.b for k in self.analog], dtype=np.float64)
        f = np.array([k.primary_factor if self.primary_values else 1.0 for k in self.analog])
        self._a, self._b, self._fp = a, b, f
        # correction factors per channel (e.g. a wrongly set CT ratio, see groundfault.corrections)
        self._cf = np.ones(len(self.analog))
        self.corrections: List[Dict[str, object]] = []

    def _determine_fs(self, source: str, override: Optional[float]) -> None:
        """Choose the sampling rate (override, timestamps or ``.cfg``) and compare the ``.cfg`` rate with the
        rate from the timestamps (warning above 0.5 % deviation)."""
        self.fs_cfg = float(self.sample_rates[0][0]) if self.sample_rates else 0.0
        self.fs_timestamps = self._fs_from_timestamps()
        if override:
            self.fs = float(override)
            self.fs_source = tr("comtrade.fs_manual")
        elif source == "timestamps" and np.isfinite(self.fs_timestamps):
            self.fs = self.fs_timestamps
            self.fs_source = "timestamp"
        elif self.fs_cfg > 0:
            self.fs = self.fs_cfg
            self.fs_source = "cfg"
        elif np.isfinite(self.fs_timestamps):
            self.fs = self.fs_timestamps
            self.fs_source = tr("comtrade.fs_timestamps_rate0")
        else:
            raise ComtradeError(tr("comtrade.no_fs"))
        if (self.fs_cfg > 0 and np.isfinite(self.fs_timestamps)
                and abs(self.fs_timestamps / self.fs_cfg - 1.0) > 0.005):
            self.warnings.append(tr("comtrade.fs_deviation", fs_timestamps=self.fs_timestamps,
                                    deviation=100 * (self.fs_timestamps / self.fs_cfg - 1), fs_cfg=self.fs_cfg))

    def _fs_from_timestamps(self, max_n: int = 400_000) -> float:
        """Sampling rate from the timestamps of the first ``max_n`` samples (NaN without usable timestamps)."""
        m = min(self.n, max_n)
        if m < 3:
            return float("nan")
        t = self.timestamps_us(0, m)
        if not np.any(t):
            return float("nan")
        dt_total = t[-1] - t[0]
        if dt_total <= 0:
            return float("nan")
        return (m - 1) / (dt_total * 1e-6)

    # ------------------------------------------------------------------ basic data
    @property
    def channel_names(self) -> List[str]:
        """Names of the analog channels."""
        return [k.name for k in self.analog]

    @property
    def units(self) -> List[str]:
        """Units of the analog channels."""
        return [k.unit for k in self.analog]

    @property
    def duration_s(self) -> float:
        """Duration of the recording in s (``n / fs``)."""
        return self.n / self.fs

    @property
    def trigger_s(self) -> Optional[float]:
        """Trigger time in s after the first sample (None without start or trigger time)."""
        if self.t_start and self.t_trigger:
            return (self.t_trigger - self.t_start).total_seconds()
        return None

    def index(self, channel: Union[int, str]) -> int:
        """Index of an analog channel.

        Parameters
        ----------
        channel : int or str
            Channel index, full channel name, short name (exact match, ignoring case, e.g. ``"IFr50"`` next to
            ``"IFr500"``) or a part of the name that matches exactly one channel.

        Returns
        -------
        int
            Channel index (0-based).

        Raises
        ------
        IndexError
            For an index outside the channel range.
        KeyError
            If the name matches no channel or several channels.
        """
        if isinstance(channel, (int, np.integer)):
            if not 0 <= int(channel) < len(self.analog):
                raise IndexError(tr("comtrade.index_out_of_range", index=channel, last=len(self.analog) - 1))
            return int(channel)
        names = self.channel_names
        if channel in names:
            return names.index(channel)
        from .channels import short_name                     # exact short name before substring match
        short = [i for i, nm in enumerate(names) if short_name(nm)[0].lower() == channel.lower()]
        if len(short) == 1:
            return short[0]
        hits = [i for i, nm in enumerate(names) if channel.lower() in nm.lower()]
        if len(hits) == 1:
            return hits[0]
        raise KeyError(tr("comtrade.channel_ambiguous", channel=channel, matches=[names[i] for i in hits]))

    def _indices(self, channels) -> List[int]:
        """Channel indices for ``channels`` (None → all channels; a single channel or a sequence)."""
        if channels is None:
            return list(range(len(self.analog)))
        if isinstance(channels, (str, int, np.integer)):
            channels = [channels]
        return [self.index(k) for k in channels]

    def channel_table(self):
        """Table of the analog channels.

        Returns
        -------
        pandas.DataFrame
            Columns ``no``, ``channel``, ``unit``, ``phase``, ``a``, ``b``, ``PS``, ``primary_factor`` and
            ``correction`` (product of all correction factors of the channel).
        """
        import pandas as pd
        return pd.DataFrame([dict(no=k.number, channel=k.name, unit=k.unit, phase=k.phase,
                                  a=k.a, b=k.b, PS=k.ps, primary_factor=k.primary_factor, correction=self._cf[j])
                             for j, k in enumerate(self.analog)])

    def set_correction(self, channel: Union[int, str], factor: float, remark: str = "",
                         source: str = "") -> int:
        """Multiply all physical values of a channel by ``factor`` (several calls → product of the factors).

        For errors of the measuring chain that are noticed only after the test: a wrong CT ratio, a clamp on one
        of three parallel conductors, a clamp with reversed polarity (factor −1). Every correction is logged in
        [`corrections`][groundfault.corrections] and passed on by the evaluation to the hints and the result file.

        Parameters
        ----------
        channel : int or str
            Channel (see [`index`][groundfault.comtrade.Recording.index]).
        factor : float
            Multiplier, finite and not zero.
        remark : str, optional
            Reason of the correction.
        source : str, optional
            Origin of the correction (e.g. file and line of the corrections file).

        Returns
        -------
        int
            Index of the corrected channel.

        Raises
        ------
        ValueError
            If ``factor`` is zero or not finite.
        """
        f = float(factor)
        if not np.isfinite(f) or f == 0.0:
            raise ValueError(tr("comtrade.correction_factor", channel=channel, factor=factor))
        j = self.index(channel)
        self._cf[j] *= f
        from .channels import short_name
        self.corrections.append(dict(channel=self.analog[j].name, short=short_name(self.analog[j].name)[0],
                                     factor=f, factor_total=float(self._cf[j]), remark=str(remark),
                                     source=str(source)))
        return j

    # ------------------------------------------------------------------ raw access
    def _raw(self, i0: int, i1: int, idx: Sequence[int]) -> np.ndarray:
        """Stored (unscaled) values of the samples ``[i0, i1)`` for the channel indices ``idx``."""
        if self._mm is not None:
            blk = self._mm["ana"][i0:i1]
            return np.asarray(blk[:, list(idx)])
        return self._ascii[i0:i1, 2:2 + len(self.analog)][:, list(idx)]

    def _scale(self, raw: np.ndarray, idx: Sequence[int]) -> np.ndarray:
        """Stored values → physical values (a·x + b, primary factor, correction); missing values → NaN."""
        idx = list(idx)
        x = raw.astype(np.float64)
        if self.file_format in _MISSING:
            miss = raw == _MISSING[self.file_format]
        elif self.file_format == "FLOAT32":
            miss = ~np.isfinite(x)
        else:
            miss = raw == 99999
        x *= self._a[idx]
        x += self._b[idx]
        x *= self._fp[idx] * self._cf[idx]
        if miss.any():
            x[miss] = np.nan
        return x

    def timestamps_us(self, i0: int = 0, i1: Optional[int] = None) -> np.ndarray:
        """Timestamps of the samples ``[i0, i1)`` in µs (including ``timemult``)."""
        i1 = self.n if i1 is None else i1
        if self._mm is not None:
            t = np.asarray(self._mm["t"][i0:i1], dtype=np.float64)
        else:
            t = self._ascii[i0:i1, 1].astype(np.float64)
        return t * self.timemult

    def sample_numbers(self, i0: int = 0, i1: Optional[int] = None) -> np.ndarray:
        """Sample numbers of the samples ``[i0, i1)`` as stored in the ``.dat`` file."""
        i1 = self.n if i1 is None else i1
        if self._mm is not None:
            return np.asarray(self._mm["n"][i0:i1])
        return self._ascii[i0:i1, 0].astype(np.int64)

    def digital_values(self, i0: int = 0, i1: Optional[int] = None) -> np.ndarray:
        """Digital channels of the samples ``[i0, i1)`` as a boolean matrix (n, number of digital channels)."""
        i1 = self.n if i1 is None else i1
        n_d = len(self.digital)
        if n_d == 0:
            return np.zeros((max(i1 - i0, 0), 0), bool)
        if self._mm is not None:
            words = np.ascontiguousarray(np.asarray(self._mm["dig"][i0:i1]), dtype="<u2")
            bits = np.unpackbits(words.view(np.uint8).reshape(-1, self._n_words, 2),
                                 axis=-1, bitorder="little")          # bit 0 = first channel
            bits = bits.reshape(words.shape[0], self._n_words * 16)
            return bits[:, :n_d].astype(bool)
        start = 2 + len(self.analog)
        return self._ascii[i0:i1, start:start + n_d].astype(bool)

    # ------------------------------------------------------------------ physical values
    def read(self, i0: int, i1: int, channels=None,
             shift: Optional[Dict[int, int]] = None) -> np.ndarray:
        """Physical values of the samples ``[i0, i1)``.

        Parameters
        ----------
        i0, i1 : int
            First sample and the sample after the last one; samples outside the file are NaN.
        channels : int, str, sequence or None, optional
            Channels (see [`index`][groundfault.comtrade.Recording.index]); None reads all analog channels.
        shift : dict, optional
            ``{channel index: Δn}`` – reads this channel from ``[i0+Δn, i1+Δn)`` (correction of a time offset
            between subsystems of the recorder).

        Returns
        -------
        numpy.ndarray
            Matrix of shape (i1 − i0, number of channels).

        Raises
        ------
        ValueError
            If ``[i0, i1)`` does not overlap the recording.
        """
        idx = self._indices(channels)
        i0 = int(i0); i1 = int(i1)
        a0, a1 = max(0, i0), min(self.n, i1)
        if a1 <= a0:
            raise ValueError(tr("comtrade.empty_range", i0=i0, i1=i1, n=self.n))
        out = np.full((i1 - i0, len(idx)), np.nan)
        out[a0 - i0:a1 - i0] = self._scale(self._raw(a0, a1, idx), idx)
        if shift:
            for column, j in enumerate(idx):
                dn = int(shift.get(j, 0))
                if not dn:
                    continue
                out[:, column] = np.nan
                s0, s1 = max(0, i0 + dn), min(self.n, i1 + dn)
                if s1 > s0:
                    out[s0 - dn - i0:s1 - dn - i0, column] = self._scale(self._raw(s0, s1, [j]), [j])[:, 0]
        return out

    def read_time(self, t0: float, t1: float, channels=None,
                  shift_s: Optional[Dict[Union[int, str], float]] = None):
        """Physical values of the time range ``[t0, t1)`` (in s, limited to the recording).

        Parameters
        ----------
        t0, t1 : float
            Start and end of the range in s after the first sample.
        channels : int, str, sequence or None, optional
            Channels (see [`index`][groundfault.comtrade.Recording.index]); None reads all analog channels.
        shift_s : dict, optional
            ``{channel: Δt in s}`` – time offset per channel (see ``shift`` of
            [`read`][groundfault.comtrade.Recording.read]).

        Returns
        -------
        t : numpy.ndarray
            Times of the samples in s.
        values : numpy.ndarray
            Matrix of shape (len(t), number of channels).
        """
        i0 = int(round(t0 * self.fs)); i1 = int(round(t1 * self.fs))
        i0 = max(0, i0); i1 = min(self.n, i1)
        vs = None
        if shift_s:
            vs = {self.index(k): int(round(v * self.fs)) for k, v in shift_s.items()}
        return np.arange(i0, i1) / self.fs, self.read(i0, i1, channels, vs)

    # ------------------------------------------------------------------ overviews (block by block)
    def envelope(self, n_bins: int = 2000, channels=None, block: int = 1 << 21):
        """Minimum/maximum envelope over the whole recording (computed block by block with little RAM).

        Parameters
        ----------
        n_bins : int, optional
            Approximate number of bins (each bin covers ``n // n_bins`` samples).
        channels : int, str, sequence or None, optional
            Channels (see [`index`][groundfault.comtrade.Recording.index]); None = all analog channels.
        block : int, optional
            Number of samples read at once.

        Returns
        -------
        t_mid : numpy.ndarray
            Centre of each bin in s.
        minimum, maximum : numpy.ndarray
            Smallest and largest physical value per bin, shape (number of bins, number of channels).
        """
        idx = self._indices(channels)
        step = max(1, self.n // max(int(n_bins), 1))
        nb = self.n // step
        mn = np.empty((nb, len(idx))); mx = np.empty((nb, len(idx)))
        bins_per_block = max(1, block // step)
        for b0 in range(0, nb, bins_per_block):
            b1 = min(nb, b0 + bins_per_block)
            raw = self._raw(b0 * step, b1 * step, idx).reshape(b1 - b0, step, len(idx))
            mn[b0:b1] = raw.min(axis=1); mx[b0:b1] = raw.max(axis=1)
        f = self._fp[idx] * self._cf[idx]
        lo = (mn * self._a[idx] + self._b[idx]) * f
        hi = (mx * self._a[idx] + self._b[idx]) * f
        lo, hi = np.minimum(lo, hi), np.maximum(lo, hi)        # negative a or negative correction factor
        t = (np.arange(nb) * step + step / 2.0) / self.fs
        return t, lo, hi

    def rms_trend(self, channels=None, window_s: float = 0.02, block_s: float = 20.0,
                             dc: str = "median"):
        """True RMS value in consecutive, non-overlapping windows over the whole recording (block by block).

        The DC component is removed per window (median or mean) before the RMS value
        x_RMS = sqrt((1/N)·Σ (x[n] − DC)²) is computed.

        Parameters
        ----------
        channels : int, str, sequence or None, optional
            Channels (see [`index`][groundfault.comtrade.Recording.index]); None = all analog channels.
        window_s : float, optional
            Window length in s (default 20 ms).
        block_s : float, optional
            Length of the blocks read at once, in s.
        dc : {"median", "mean"}, optional
            Estimate of the DC component per window.

        Returns
        -------
        t : numpy.ndarray
            Window centres in s.
        rms : numpy.ndarray
            RMS values, shape (number of windows, number of channels).
        """
        idx = self._indices(channels)
        nw = max(2, int(round(window_s * self.fs)))
        window_samples = self.n // nw
        out = np.empty((window_samples, len(idx)))
        win_per_block = max(1, int(block_s * self.fs) // nw)
        for f0 in range(0, window_samples, win_per_block):
            f1 = min(window_samples, f0 + win_per_block)
            x = self._scale(self._raw(f0 * nw, f1 * nw, idx), idx).reshape(f1 - f0, nw, len(idx))
            ref = np.median(x, axis=1, keepdims=True) if dc == "median" else x.mean(axis=1, keepdims=True)
            out[f0:f1] = np.sqrt(np.mean((x - ref) ** 2, axis=1))
        t = (np.arange(window_samples) * nw + nw / 2.0) / self.fs
        return t, out

    # ------------------------------------------------------------------ miscellaneous
    def info(self) -> Dict[str, object]:
        """Metadata of the recording.

        Returns
        -------
        dict
            Keys ``file``, ``path``, ``station``, ``device``, ``revision``, ``format``, ``channels``,
            ``digital_channels``, ``samples``, ``fs_hz``, ``fs_source``, ``fs_cfg_hz``, ``fs_timestamps_hz``,
            ``duration_s``, ``start``, ``trigger`` (ISO time stamps), ``trigger_s``, ``line_frequency_hz``,
            ``cfg_encoding`` and ``warnings``.
        """
        return dict(file=os.path.basename(self.cfg_path), path=self.cfg_path, station=self.station, device=self.device,
                    revision=self.revision, format=self.file_format, channels=len(self.analog),
                    digital_channels=len(self.digital), samples=int(self.n), fs_hz=self.fs,
                    fs_source=self.fs_source, fs_cfg_hz=self.fs_cfg,
                    fs_timestamps_hz=self.fs_timestamps, duration_s=self.duration_s,
                    start=self.t_start.isoformat() if self.t_start else None,
                    trigger=self.t_trigger.isoformat() if self.t_trigger else None,
                    trigger_s=self.trigger_s, line_frequency_hz=self.line_frequency,
                    cfg_encoding=self.cfg_encoding, warnings=list(self.warnings))

    def close(self) -> None:
        """Close the memory map of the ``.dat`` file (also done by the context manager)."""
        if self._mm is not None:
            mm = self._mm
            self._mm = None
            try:
                mm._mmap.close()  # type: ignore[attr-defined]
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __repr__(self) -> str:
        return ("<Recording %s | %d channels | %.0f Hz | %.2f s | %s>"
                % (os.path.basename(self.cfg_path), len(self.analog), self.fs, self.duration_s, self.file_format))


def open_recording(cfg_path: str, fs_source_pref: str = "auto", fs_override: Optional[float] = None,
           primary_values: bool = True, emit_warnings: bool = True) -> Recording:
    """Open a COMTRADE recording.

    Parameters
    ----------
    cfg_path : str
        Path of the ``.cfg`` file; the ``.dat`` file must lie next to it.
    fs_source_pref : {"auto", "cfg", "timestamps"}, optional
        ``"auto"`` and ``"cfg"``: sampling rate from the ``.cfg`` file – the timestamps serve as a check, and as
        the source if the ``.cfg`` file gives the rate 0; ``"timestamps"``: sampling rate from the timestamps.
    fs_override : float, optional
        Enforce a sampling rate in Hz (for a defective time base, see the diagnosis).
    primary_values : bool, optional
        Convert secondary values to primary values (PS field), default True.
    emit_warnings : bool, optional
        Issue the findings of the reader (``Recording.warnings``) as ``UserWarning``, default True.

    Returns
    -------
    Recording
        The opened recording; use it as a context manager to close the memory map.

    Raises
    ------
    ComtradeError
        For a missing ``.dat`` file, a malformed ``.cfg`` file or an undeterminable sampling rate.
    """
    rec = Recording(cfg_path, fs_source_pref=fs_source_pref, fs_override=fs_override,
                       primary_values=primary_values)
    if emit_warnings:
        for w in rec.warnings:
            warnings.warn(w, stacklevel=2)
    return rec


# ====================================================================== writing (demo recordings and tests)
def write_comtrade(cfg_path: str, signals: "Dict[str, Tuple[str, np.ndarray]]", fs: float,
                      t_start: Optional[_dt.datetime] = None, trigger_s: float = 0.0,
                      file_format: str = "BINARY", station: str = "", device: str = "TEST",
                      line_frequency: float = 50.0, phases: Optional[Dict[str, str]] = None,
                      offsets: Optional[Dict[str, float]] = None, ps: str = "P",
                      primary: float = 1.0, secondary: float = 1.0, timemult: float = 1.0,
                      digital: Optional["Dict[str, np.ndarray]"] = None, encoding: str = "cp1252",
                      timestamps: bool = True) -> str:
    """Write a COMTRADE-1999 file pair (``.cfg``/``.dat``), e.g. for synthetic recordings and tests.

    Parameters
    ----------
    cfg_path : str
        Path of the ``.cfg`` file; the ``.dat`` file gets the same stem.
    signals : dict
        ``{channel name: (unit, values)}``. The values are interpreted as the *stored* quantity (secondary
        values for ``ps="S"``).
    fs : float
        Sampling rate in Hz.
    t_start : datetime.datetime, optional
        Time of the first sample (default 2026-01-01 12:00:00).
    trigger_s : float, optional
        Trigger time in s after the first sample.
    file_format : {"BINARY", "BINARY32", "FLOAT32", "ASCII"}, optional
        Format of the ``.dat`` file. Integer formats are scaled to 98 % of their range.
    station, device : str, optional
        Station name and device id in the first line of the ``.cfg`` file.
    line_frequency : float, optional
        Nominal line frequency in Hz.
    phases : dict, optional
        Phase identification per channel name.
    offsets : dict, optional
        Offset ``b`` per channel name (checks the handling of ``b`` by the reader).
    ps : {"P", "S"}, optional
        PS field of all channels.
    primary, secondary : float, optional
        Transformer ratio written for all channels.
    timemult : float, optional
        Multiplication factor of the timestamps.
    digital : dict, optional
        ``{channel name: 0/1 values}`` of digital channels.
    encoding : str, optional
        Encoding of the ``.cfg`` file (default cp1252, as written by DANEO recorders).
    timestamps : bool, optional
        Write the timestamps (False: all timestamps 0).

    Returns
    -------
    str
        ``cfg_path``.

    Raises
    ------
    ValueError
        If the timestamps do not fit into 32 bit (increase ``timemult``).
    """
    t_start = t_start or _dt.datetime(2026, 1, 1, 12, 0, 0)
    names = list(signals)
    n = len(next(iter(signals.values()))[1]) if names else len(next(iter(digital.values())))
    file_format = file_format.upper()
    rows = ["%s,%s,1999" % (station, device)]
    n_d = len(digital or {})
    rows.append("%d,%dA,%dD" % (len(names) + n_d, len(names), n_d))
    raw_columns = []
    for j, nm in enumerate(names):
        unit, x = signals[nm]
        x = np.asarray(x, dtype=np.float64)
        b = float((offsets or {}).get(nm, 0.0))
        if file_format == "FLOAT32":
            a = 1.0
            raw = (x - b).astype(np.float32)
            lo, hi = -3.4e38, 3.4e38
        else:
            limit_ = 32767 if file_format in ("BINARY", "ASCII") else 2147483647
            span = float(np.nanmax(np.abs(x - b))) if x.size else 1.0
            a = max(span / (0.98 * limit_), 1e-12)
            raw = np.clip(np.round((x - b) / a), -limit_, limit_)
            raw = raw.astype(np.int16 if file_format == "BINARY" else np.int32)
            lo, hi = -limit_, limit_
        raw_columns.append(raw)
        ph = (phases or {}).get(nm, "")
        rows.append("%d,%s,%s,,%s,%.17g,%.17g,0,%d,%d,%.10g,%.10g,%s"
                      % (j + 1, nm, ph, unit, a, b, lo, hi, primary, secondary, ps))
    for k, nm in enumerate(digital or {}):
        rows.append("%d,%s,,,0" % (k + 1, nm))
    rows.append("%g" % line_frequency)
    rows.append("1")
    rows.append("%.10g,%d" % (fs, n))
    t_trig = t_start + _dt.timedelta(seconds=trigger_s)
    rows.append(t_start.strftime("%d/%m/%Y,%H:%M:%S.%f"))
    rows.append(t_trig.strftime("%d/%m/%Y,%H:%M:%S.%f"))
    rows.append(file_format)
    rows.append("%g" % timemult)
    with open(cfg_path, "w", encoding=encoding, newline="") as f:
        f.write("\r\n".join(rows) + "\r\n")
    ts = (np.round(np.arange(n) / fs * 1e6 / timemult).astype(np.uint64)
          if timestamps else np.zeros(n, np.uint64))
    if np.any(ts > 0xFFFFFFFF):
        raise ValueError(tr("comtrade.timestamps_32bit"))
    stem = os.path.splitext(cfg_path)[0]
    if file_format == "ASCII":
        columns = [np.arange(1, n + 1), ts] + raw_columns + [np.asarray(v, int) for v in (digital or {}).values()]
        np.savetxt(stem + ".dat", np.column_stack(columns), fmt="%d" if file_format != "FLOAT32" else "%g",
                   delimiter=",")
        return cfg_path
    n_words = (n_d + 15) // 16
    fields = [("n", "<u4"), ("t", "<u4")]
    if names:
        fields.append(("ana", _DTYPE[file_format], (len(names),)))
    if n_words:
        fields.append(("dig", "<u2", (n_words,)))
    rec = np.zeros(n, dtype=np.dtype(fields))
    rec["n"] = np.arange(1, n + 1, dtype=np.uint32)
    rec["t"] = ts.astype(np.uint32)
    if names:
        rec["ana"] = np.column_stack(raw_columns)
    if n_words:
        words = np.zeros((n, n_words), np.uint16)
        for k, v in enumerate((digital or {}).values()):
            words[:, k // 16] |= (np.asarray(v).astype(np.uint16) & 1) << (k % 16)
        rec["dig"] = words
    rec.tofile(stem + ".dat")
    return cfg_path
