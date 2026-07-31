"""Streamlit app for browsing and plotting Dymola simulation results (.mat via sdf)."""
from __future__ import annotations

import json
import math
import os
import tempfile

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from dymola_app.reader import ResultFile, list_result_files, load_result, variable_names, parameter_names
from dymola_app.treeutils import group_variables

DEFAULT_DIR = r"D:\projects\IPP\Cryogenics\Dymola\compass-u-cryo-loop\dymola-thermal-systems\data\PF\overCoolStabilize delay"
DASH_STYLES = ["solid", "dash", "dot", "dashdot", "longdash", "longdashdot"]
MAX_BULK_ADD = 300
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".dymdata_settings.json")


def load_settings() -> dict:
    """Read persisted app settings from disk (empty dict if none/invalid)."""
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_settings() -> None:
    """Persist the current directory, file selection and charts to disk."""
    data = {
        "directory": st.session_state.get("directory_input", DEFAULT_DIR),
        "col_a_select": st.session_state.get("col_a_select"),
        "col_b_select": st.session_state.get("col_b_select"),
        "charts": st.session_state.get("charts", []),
        "active_chart_id": st.session_state.get("active_chart_id"),
        "next_chart_id": st.session_state.get("next_chart_id", 0),
        "basic_params": st.session_state.get("basic_params", []),
    }
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        pass


def clean_label(name_or_path: str) -> str:
    """Display name for a result file: strip directory, .mat extension and 'result_' prefix."""
    base = os.path.basename(name_or_path)
    if base.lower().endswith(".mat"):
        base = base[:-4]
    if base.startswith("result_"):
        base = base[len("result_"):]
    return base or base


st.set_page_config(page_title="Dymola Results Viewer", layout="wide")
st.title("Dymola Results Viewer")

# ---------------------------------------------------------------------------
# Restore persisted settings (once per session, on first load only) so the
# app reopens showing the same directory, files and charts as last time.
# ---------------------------------------------------------------------------
if "_settings_restored" not in st.session_state:
    st.session_state["_settings_restored"] = True
    _saved = load_settings()
else:
    _saved = None

if _saved:
    st.session_state["directory_input"] = _saved.get("directory", DEFAULT_DIR)
    saved_charts = _saved.get("charts") or []
    for _chart in saved_charts:
        if _chart.get("time_range") is not None:
            _chart["time_range"] = tuple(_chart["time_range"])
    if saved_charts:
        st.session_state["charts"] = saved_charts
        st.session_state["active_chart_id"] = _saved.get("active_chart_id", saved_charts[0]["id"])
        st.session_state["next_chart_id"] = _saved.get(
            "next_chart_id", max(c["id"] for c in saved_charts)
        )
    if _saved.get("basic_params"):
        st.session_state["basic_params"] = _saved["basic_params"]

# ---------------------------------------------------------------------------
# Sidebar: locate result files
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Results")
    if "directory_input" not in st.session_state:
        st.session_state["directory_input"] = DEFAULT_DIR
    directory = st.text_input("Results directory", key="directory_input")
    files = list_result_files(directory)

    if _saved:
        for _key, _path in (("col_a_select", _saved.get("col_a_select")), ("col_b_select", _saved.get("col_b_select"))):
            if _path and _path in files:
                st.session_state[_key] = _path

    if not files:
        st.warning("No .mat files found in that directory.")
        st.stop()

    file_labels = {f: clean_label(f) for f in files}

tab_charts, tab_params, tab_data = st.tabs(["Charts", "Parameters", "Data"])


# ---------------------------------------------------------------------------
# Per-column file picker (small popover: pick an existing file or upload one)
# ---------------------------------------------------------------------------
def _column_file_picker(container, col_key: str, default_index: int) -> tuple[str, str]:
    select_key = f"{col_key}_select"
    if select_key not in st.session_state:
        st.session_state[select_key] = files[min(default_index, len(files) - 1)]
    with container:
        with st.popover("📁", help="Change or upload the file shown in this column"):
            sel_path = st.selectbox(
                "Existing file",
                options=files,
                format_func=lambda p: file_labels[p],
                key=select_key,
            )
            up = st.file_uploader("...or upload a .mat file", type="mat", key=f"{col_key}_upload")
    if up is not None:
        tmp_path = os.path.join(tempfile.gettempdir(), up.name)
        with open(tmp_path, "wb") as fh:
            fh.write(up.getbuffer())
        return tmp_path, clean_label(up.name)
    return sel_path, file_labels[sel_path]


# ---------------------------------------------------------------------------
# Basic-parameters comparison: pick a short list of scalar parameters (e.g.
# PID.k, PID.Ti) and compare their values for the two loaded runs.
# ---------------------------------------------------------------------------
def _param_differs(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is not b
    try:
        return not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    except TypeError:
        return a != b


@st.dialog("Configure basic parameters")
def _configure_basic_params_dialog(all_params: list[str]) -> None:
    current = [p for p in st.session_state.get("basic_params", []) if p in all_params]
    picked = st.multiselect(
        "Parameters to compare",
        options=all_params,
        default=current,
        help="Pick scalar parameters (e.g. PID.k, PID.Ti) to show side by side for the two runs.",
    )
    if st.button("Save", type="primary"):
        st.session_state["basic_params"] = picked
        st.rerun()


@st.dialog("Compare run parameters", width="large")
def _show_param_compare_dialog(rf_a: ResultFile, rf_b: ResultFile) -> None:
    basic_params = st.session_state.get("basic_params", [])
    if not basic_params:
        st.info("No parameters configured yet — use the “⚙ Configure basic parameters” button below the overview table.")
        return
    col1, col2 = st.columns(2)
    for col, rf, other in ((col1, rf_a, rf_b), (col2, rf_b, rf_a)):
        with col:
            st.subheader(rf.label)
            for p in basic_params:
                val = rf.params.get(p)
                other_val = other.params.get(p)
                unit = rf.param_units.get(p, "") or other.param_units.get(p, "")
                shown = f"{val:g}" if val is not None else "—"
                text = f"**{p}** = {shown}" + (f" {unit}" if unit else "")
                if _param_differs(val, other_val):
                    st.markdown(f":red[{text}]")
                else:
                    st.markdown(text)


with tab_charts:
    outer_a, outer_b = st.columns(2)
    with outer_a:
        head_a = st.columns([6, 1])
        path_a, label_a = _column_file_picker(head_a[1], "col_a", default_index=0)
    with outer_b:
        head_b = st.columns([6, 1])
        path_b, label_b = _column_file_picker(head_b[1], "col_b", default_index=1 if len(files) > 1 else 0)

col_a_result = load_result(path_a, label=label_a)
col_b_result = load_result(path_b, label=label_b)
results: list[ResultFile] = [col_a_result, col_b_result]
all_param_names = parameter_names(results)

with tab_charts:
    if head_a[0].button(f"**{label_a}**", key="title_btn_a", type="tertiary", help="Compare basic parameters for both runs"):
        _show_param_compare_dialog(col_a_result, col_b_result)
    if head_b[0].button(f"**{label_b}**", key="title_btn_b", type="tertiary", help="Compare basic parameters for both runs"):
        _show_param_compare_dialog(col_a_result, col_b_result)

    overview_rows = []
    for rf in results:
        n_points = max((len(v) for v in rf.time.values()), default=0)
        t_end = max((t[-1] for t in rf.time.values() if len(t)), default=0.0)
        overview_rows.append(
            {
                "File": rf.label,
                "Variables": len(rf.series),
                "Parameters": len(rf.params),
                "Time points": n_points,
                "Duration [s]": round(t_end, 3),
            }
        )
    st.dataframe(pd.DataFrame(overview_rows), hide_index=True, width="stretch", height=110)
    if st.button("⚙ Configure basic parameters"):
        _configure_basic_params_dialog(all_param_names)

all_var_names = variable_names(results)
groups = group_variables(all_var_names)

# ---------------------------------------------------------------------------
# Multi-chart state
# ---------------------------------------------------------------------------
def _new_chart(name: str) -> dict:
    st.session_state["next_chart_id"] = st.session_state.get("next_chart_id", 0) + 1
    return {
        "id": st.session_state["next_chart_id"],
        "name": name,
        "vars": [],
        "layout": "combined",
        "time_range": None,
    }


if "charts" not in st.session_state:
    st.session_state["charts"] = [_new_chart("Chart 1")]
    st.session_state["active_chart_id"] = st.session_state["charts"][0]["id"]

charts: list[dict] = st.session_state["charts"]
if not any(c["id"] == st.session_state.get("active_chart_id") for c in charts):
    st.session_state["active_chart_id"] = charts[0]["id"]
active_id = st.session_state["active_chart_id"]
active_chart = next(c for c in charts if c["id"] == active_id)


def _widget_key(field: str, chart_id: int) -> str:
    return f"{field}_editor_{chart_id}"


def _time_bounds(var_list: list[str]) -> tuple[float, float] | None:
    times = [t for rf in results for v, t in rf.time.items() if v in var_list and len(t)]
    if not times:
        return None
    return float(min(t[0] for t in times)), float(max(t[-1] for t in times))


# ---------------------------------------------------------------------------
# Sidebar: variable editor (edits the ACTIVE chart)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header(f"Variables — editing “{active_chart['name']}”")
    top_level_names = [n for n in all_var_names if "." not in n]

    vars_key = _widget_key("vars", active_id)
    sane_vars = [v for v in active_chart["vars"] if v in all_var_names]
    if vars_key not in st.session_state:
        st.session_state[vars_key] = sane_vars
    else:
        st.session_state[vars_key] = [v for v in st.session_state[vars_key] if v in all_var_names]

    st.multiselect(
        "Variables to plot",
        options=all_var_names,
        key=vars_key,
        help=(
            "Type to search — this searches the full nested Modelica "
            "hierarchy too, e.g. type 'valve1' to find PF1L.valve1.summary.Kv."
        ),
    )
    active_chart["vars"] = st.session_state[vars_key]

    def _add_bulk_matches() -> None:
        q = st.session_state.get("bulk_search_text", "").lower().strip()
        if not q:
            return
        matches = [n for n in all_var_names if q in n.lower()]
        if len(matches) > MAX_BULK_ADD:
            return
        cur = set(st.session_state.get(vars_key, []))
        cur.update(matches)
        st.session_state[vars_key] = sorted(cur)

    def _clear_selection() -> None:
        st.session_state[vars_key] = []

    with st.expander("Bulk-add by prefix (e.g. whole subcomponent or array)"):
        st.text_input("Prefix / substring", key="bulk_search_text")
        bulk_l = st.session_state.get("bulk_search_text", "").lower().strip()
        bulk_matches = [n for n in all_var_names if bulk_l in n.lower()] if bulk_l else []

        add_disabled = not bulk_matches or len(bulk_matches) > MAX_BULK_ADD
        st.button("Add matches", width="stretch", disabled=add_disabled, on_click=_add_bulk_matches)
        if len(bulk_matches) > MAX_BULK_ADD:
            st.caption(f"{len(bulk_matches)} matches — narrow below {MAX_BULK_ADD} to bulk-add.")
        elif bulk_matches:
            st.caption(f"{len(bulk_matches)} match(es).")
        st.button("Clear selection", width="stretch", on_click=_clear_selection)

    st.caption(
        f"{len(all_var_names)} variables available ({len(top_level_names)} top-level) "
        f"in {len(groups)} groups."
    )

    # -------------------------------------------------------------------
    # Sidebar: view editor (edits the ACTIVE chart's display settings)
    # -------------------------------------------------------------------
    st.header("Chart view")

    name_key = _widget_key("name", active_id)
    if name_key not in st.session_state:
        st.session_state[name_key] = active_chart["name"]
    st.text_input("Chart name", key=name_key)
    active_chart["name"] = st.session_state[name_key] or active_chart["name"]

    layout_key = _widget_key("layout", active_id)
    if layout_key not in st.session_state:
        st.session_state[layout_key] = active_chart["layout"]
    st.radio(
        "Chart layout",
        options=["combined", "subplot"],
        key=layout_key,
        format_func=lambda v: "One combined chart" if v == "combined" else "Separate subplot per variable",
        help=(
            "Combined: all selected variables overlaid on one chart "
            "(up to 2 distinct units get their own y-axis). "
            "Separate: one subplot per variable, each with its own y-scale."
        ),
    )
    active_chart["layout"] = st.session_state[layout_key]

    bounds = _time_bounds(active_chart["vars"])
    if bounds is None:
        st.caption("Pick variables above to enable the time window.")
        active_chart["time_range"] = None
    else:
        t_min, t_max = bounds
        if t_max <= t_min:
            active_chart["time_range"] = (t_min, t_max)
        else:
            time_key = _widget_key("time", active_id)
            if time_key not in st.session_state:
                stored_range = active_chart.get("time_range")
                if stored_range and len(stored_range) == 2:
                    lo = min(max(stored_range[0], t_min), t_max)
                    hi = min(max(stored_range[1], t_min), t_max)
                    st.session_state[time_key] = (lo, hi) if lo <= hi else (t_min, t_max)
                else:
                    st.session_state[time_key] = (t_min, t_max)
            else:
                lo, hi = st.session_state[time_key]
                lo = min(max(lo, t_min), t_max)
                hi = min(max(hi, t_min), t_max)
                st.session_state[time_key] = (lo, hi) if lo <= hi else (t_min, t_max)
            st.slider("Time window [s]", min_value=t_min, max_value=t_max, key=time_key)
            active_chart["time_range"] = st.session_state[time_key]


# ---------------------------------------------------------------------------
# Chart data / figure builders
# ---------------------------------------------------------------------------
def build_chart_df(chart: dict, results_list: list[ResultFile]) -> pd.DataFrame:
    t_range = chart["time_range"]
    frames = []
    for rf in results_list:
        for var in chart["vars"]:
            if var not in rf.series:
                continue
            t = rf.time[var]
            v = rf.series[var]
            unit = rf.units.get(var, "")
            mask = (t >= t_range[0]) & (t <= t_range[1]) if t_range else slice(None)
            t_sel, v_sel = (t[mask], v[mask]) if t_range else (t, v)
            if t_range and not mask.any():
                continue
            label = f"{var} [{unit}]" if unit else var
            frames.append(
                pd.DataFrame(
                    {
                        "time": t_sel,
                        "value": v_sel,
                        "variable": var,
                        "variable_label": label,
                        "unit": unit,
                        "file": rf.label,
                    }
                )
            )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def render_chart_figure(chart: dict, df: pd.DataFrame, results_list: list[ResultFile]) -> go.Figure:
    if chart["layout"] == "subplot":
        n_vars = df["variable"].nunique()
        fig = px.line(
            df,
            x="time",
            y="value",
            color="file",
            facet_row="variable_label",
            height=max(220, 180 * n_vars),
        )
        fig.update_yaxes(matches=None)
        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=", 1)[-1]))
        fig.update_traces(mode="lines+markers", marker=dict(size=4))
        fig.update_layout(
            legend_title_text="",
            margin=dict(t=40, b=20),
            hovermode="x unified",
            hoverlabel=dict(font_size=16),
        )
        fig.update_xaxes(title_text="Time [s]")
        return fig

    ordered_vars = [v for v in chart["vars"] if v in set(df["variable"])]
    var_unit = df.drop_duplicates("variable").set_index("variable")["unit"].to_dict()
    unique_units = list(dict.fromkeys(var_unit[v] for v in ordered_vars))

    palette = px.colors.qualitative.Plotly
    color_map = {v: palette[i % len(palette)] for i, v in enumerate(ordered_vars)}
    file_labels_ordered = [rf.label for rf in results_list]
    dash_map = {lbl: DASH_STYLES[i % len(DASH_STYLES)] for i, lbl in enumerate(file_labels_ordered)}
    multi_file = len(results_list) > 1

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    for var in ordered_vars:
        unit = var_unit.get(var, "")
        secondary = len(unique_units) > 1 and unique_units.index(unit) == 1
        for lbl in file_labels_ordered:
            sub = df[(df["variable"] == var) & (df["file"] == lbl)]
            if sub.empty:
                continue
            name = f"{var} [{unit}]" if unit else var
            if multi_file:
                name += f" — {lbl}"
            fig.add_trace(
                go.Scatter(
                    x=sub["time"],
                    y=sub["value"],
                    mode="lines+markers",
                    name=name,
                    legendgroup=var,
                    line=dict(color=color_map[var], dash=dash_map[lbl]),
                    marker=dict(size=4, color=color_map[var]),
                ),
                secondary_y=secondary,
            )

    fig.update_layout(
        legend_title_text="",
        margin=dict(t=40, b=20),
        height=350,
        hovermode="x unified",
        hoverlabel=dict(font_size=16),
    )
    fig.update_xaxes(title_text="Time [s]")
    fig.update_yaxes(title_text=unique_units[0] or "value", secondary_y=False)
    if len(unique_units) > 1:
        fig.update_yaxes(title_text=unique_units[1] or "value", secondary_y=True)
    if len(unique_units) > 2:
        st.caption(
            f"{len(unique_units)} different units among the selected variables "
            f"({', '.join(u or '–' for u in unique_units)}); only the first two get "
            "their own y-axis, the rest share the primary axis. Use 'Separate subplot "
            "per variable' for a fully independent scale per variable."
        )
    return fig


def _cleanup_chart_state(chart_id: int) -> None:
    for field in ("vars", "name", "layout", "time"):
        st.session_state.pop(_widget_key(field, chart_id), None)


def _chart_header(chart: dict, is_active: bool) -> None:
    border_css = (
        "border-left:4px solid #1f77b4; background-color: rgba(31,119,180,0.12);"
        if is_active
        else "border-left:4px solid rgba(128,128,128,0.35);"
    )
    st.markdown(
        f"<div style='{border_css} padding:6px 10px; border-radius:4px;'><b>{chart['name']}</b></div>",
        unsafe_allow_html=True,
    )


def _render_chart_plot(chart: dict, results_list: list[ResultFile], slot: str, csv_label: str) -> None:
    matched_vars = [v for v in chart["vars"] if any(v in rf.series for rf in results_list)]
    if not chart["vars"]:
        st.info("No variables selected for this chart yet.")
        return
    if not matched_vars:
        st.info("None of this chart's variables exist in this file.")
        return
    scoped_chart = dict(chart, vars=matched_vars)
    chart_df = build_chart_df(scoped_chart, results_list)
    if chart_df.empty:
        st.warning("No data in the selected time window for the chosen variables.")
        return
    fig = render_chart_figure(scoped_chart, chart_df, results_list)
    st.plotly_chart(fig, width="stretch", key=f"plotly_{chart['id']}_{slot}")
    st.download_button(
        "Download CSV",
        data=chart_df.to_csv(index=False).encode("utf-8"),
        file_name=f"{chart['name'].replace(' ', '_')}_{csv_label.replace(' ', '_')}.csv",
        mime="text/csv",
        key=f"dl_{chart['id']}_{slot}",
    )


# ---------------------------------------------------------------------------
# Charts tab: one row per chart, both file columns rendered side by side
# ---------------------------------------------------------------------------
with tab_charts:
    for idx, chart in enumerate(charts):
        is_active = chart["id"] == active_id
        with st.container(border=True):
            header_cols = st.columns([10, 1, 1, 1])
            with header_cols[0]:
                _chart_header(chart, is_active)
            if header_cols[1].button("▶", key=f"activate_{chart['id']}", disabled=is_active, help="Activate (edit in sidebar)"):
                st.session_state["active_chart_id"] = chart["id"]
                st.rerun()
            if header_cols[2].button("⧉", key=f"dup_{chart['id']}", help="Duplicate this chart"):
                new_chart = dict(chart)
                new_chart["id"] = st.session_state.get("next_chart_id", 0) + 1
                st.session_state["next_chart_id"] = new_chart["id"]
                new_chart["name"] = f"{chart['name']} (copy)"
                new_chart["vars"] = list(chart["vars"])
                charts.insert(idx + 1, new_chart)
                st.session_state["active_chart_id"] = new_chart["id"]
                st.rerun()
            if header_cols[3].button("🗑", key=f"del_{chart['id']}", disabled=len(charts) == 1, help="Delete this chart"):
                charts.pop(idx)
                _cleanup_chart_state(chart["id"])
                if is_active:
                    st.session_state["active_chart_id"] = charts[0]["id"]
                st.rerun()

            plot_a, plot_b = st.columns(2)
            with plot_a:
                _render_chart_plot(chart, [col_a_result], slot="A", csv_label=col_a_result.label)
            with plot_b:
                _render_chart_plot(chart, [col_b_result], slot="B", csv_label=col_b_result.label)

    st.divider()
    if st.button("+ New chart", width="stretch"):
        new_chart = _new_chart(f"Chart {len(charts) + 1}")
        charts.append(new_chart)
        st.session_state["active_chart_id"] = new_chart["id"]
        st.rerun()

with tab_params:
    param_names = parameter_names(results)
    if not param_names:
        st.info("No scalar parameters found.")
    else:
        search_p = st.text_input("Filter parameters", "", key="param_search")
        pnames = [p for p in param_names if search_p.lower() in p.lower()] if search_p else param_names

        table = {"Unit": []}
        units_row = {}
        for rf in results:
            table[rf.label] = []
        for p in pnames:
            unit = next((rf.param_units.get(p, "") for rf in results if p in rf.param_units), "")
            units_row[p] = unit
            for rf in results:
                table[rf.label].append(rf.params.get(p, float("nan")))
        table["Unit"] = [units_row[p] for p in pnames]

        param_df = pd.DataFrame(table, index=pnames)
        if len(results) > 1:
            value_cols = [rf.label for rf in results]
            differs = param_df[value_cols].nunique(axis=1, dropna=False) > 1
            param_df.insert(0, "Differs", differs.map({True: "yes", False: ""}))
        st.dataframe(param_df, width="stretch", height=350)

with tab_data:
    st.caption(f"Wide table (Time + variables) for the active chart, “{active_chart['name']}”.")
    if not active_chart["vars"]:
        st.info("Pick variables for the active chart in the sidebar first.")
    else:
        file_choice = st.selectbox("File", options=[rf.label for rf in results])
        rf = next(r for r in results if r.label == file_choice)
        cols = {}
        ref_len = None
        skipped = []
        for var in active_chart["vars"]:
            if var not in rf.series:
                continue
            t = rf.time[var]
            if ref_len is None:
                ref_len = len(t)
                cols["Time"] = t
            if len(t) != ref_len:
                skipped.append(var)
                continue
            unit = rf.units.get(var, "")
            colname = f"{var} [{unit}]" if unit else var
            cols[colname] = rf.series[var]
        if cols:
            wide_df = pd.DataFrame(cols)
            t_range = active_chart["time_range"]
            mask = (wide_df["Time"] >= t_range[0]) & (wide_df["Time"] <= t_range[1]) if t_range else slice(None)
            shown = wide_df[mask] if t_range else wide_df
            st.dataframe(shown, width="stretch", height=300)
            st.download_button(
                "Download this table (CSV)",
                data=shown.to_csv(index=False).encode("utf-8"),
                file_name=f"{file_choice}_selected_vars.csv",
                mime="text/csv",
            )
        if skipped:
            st.caption(f"Skipped (different time grid than the first variable): {', '.join(skipped)}")

# ---------------------------------------------------------------------------
# Persist current settings so the same directory, files and charts come
# back the next time the app is opened.
# ---------------------------------------------------------------------------
save_settings()
