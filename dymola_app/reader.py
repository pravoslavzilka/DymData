"""Loading and caching of Dymola .mat result files via the sdf package."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import sdf
import streamlit as st


@dataclass
class ResultFile:
    """A single loaded Dymola result file, split into time series and parameters."""

    path: str
    label: str
    time: dict[str, np.ndarray] = field(default_factory=dict)  # varname -> time vector
    series: dict[str, np.ndarray] = field(default_factory=dict)  # varname -> values
    units: dict[str, str] = field(default_factory=dict)  # varname -> unit (may be "")
    params: dict[str, float] = field(default_factory=dict)  # varname -> scalar value
    param_units: dict[str, str] = field(default_factory=dict)


def list_result_files(directory: str) -> list[str]:
    """Return sorted .mat file paths found directly inside `directory`."""
    d = Path(directory)
    if not d.is_dir():
        return []
    return sorted(str(p) for p in d.glob("*.mat") if p.is_file())


def _unit_of(ds) -> str:
    unit = getattr(ds, "unit", None)
    return unit if unit else ""


@st.cache_data(show_spinner=False)
def _load_result_cached(path: str, mtime: float, label: str) -> ResultFile:
    group = sdf.load(path)
    rf = ResultFile(path=path, label=label)

    for ds in group.datasets:
        name = ds.name
        if name == "Time":
            continue
        data = np.asarray(ds.data)
        unit = _unit_of(ds)
        if data.ndim == 0:
            rf.params[name] = float(data)
            rf.param_units[name] = unit
        else:
            rf.series[name] = data
            rf.units[name] = unit
            scale = ds.scales[0] if ds.scales else None
            if scale is not None:
                rf.time[name] = np.asarray(scale.data)
            else:
                # fall back to the file's own Time dataset
                try:
                    rf.time[name] = np.asarray(group["Time"].data)
                except KeyError:
                    rf.time[name] = np.arange(data.shape[0], dtype=float)

    return rf


def load_result(path: str, label: str | None = None) -> ResultFile:
    """Load (with caching) a single Dymola .mat result file."""
    mtime = os.path.getmtime(path)
    if label is None:
        label = Path(path).stem
    return _load_result_cached(path, mtime, label)


def variable_names(results: list[ResultFile]) -> list[str]:
    """Union of time-series variable names across the given result files, sorted."""
    names: set[str] = set()
    for rf in results:
        names.update(rf.series.keys())
    return sorted(names)


def parameter_names(results: list[ResultFile]) -> list[str]:
    names: set[str] = set()
    for rf in results:
        names.update(rf.params.keys())
    return sorted(names)
