"""Helpers for grouping flat Modelica variable names for display / selection."""
from __future__ import annotations

import re

_ARRAY_SUFFIX = re.compile(r"\[(\d+(?:,\d+)*)\]$")


def base_name(name: str) -> str:
    """Strip a trailing array index, e.g. 'coilOpen[3]' -> 'coilOpen'."""
    return _ARRAY_SUFFIX.sub("", name)


def group_variables(names: list[str]) -> dict[str, list[str]]:
    """Group variable names by their array base name, preserving element order.

    Scalars (no array suffix) become single-item groups keyed by their own name.
    """
    groups: dict[str, list[str]] = {}
    for name in names:
        key = base_name(name)
        groups.setdefault(key, []).append(name)

    def elem_sort_key(n: str):
        m = _ARRAY_SUFFIX.search(n)
        if not m:
            return (0,)
        return tuple(int(x) for x in m.group(1).split(","))

    for key in groups:
        groups[key].sort(key=elem_sort_key)

    return dict(sorted(groups.items(), key=lambda kv: kv[0].lower()))
