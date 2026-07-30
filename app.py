"""Streamlit app for browsing and plotting Dymola simulation results (.mat via sdf)."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from dymola_app.reader import ResultFile, list_result_files, load_result, variable_names, parameter_names
from dymola_app.treeutils import group_variables

DEFAULT_DIR = r"D:\projects\IPP\Cryogenics\Dymola\compass-u-cryo-loop\dymola-thermal-systems\data\PF\overCoolStabilize delay"

st.set_page_config(page_title="Dymola Results Viewer", layout="wide")
st.title("Dymola Results Viewer")

# ---------------------------------------------------------------------------
# Sidebar: locate & load result files
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Results")
    directory = st.text_input("Results directory", value=DEFAULT_DIR)
    files = list_result_files(directory)

    if not files:
        st.warning("No .mat files found in that directory.")
        st.stop()

    file_labels = {f: f.split("\\")[-1].split("/")[-1] for f in files}
    selected_files = st.multiselect(
        "Result file(s) to load / compare",
        options=files,
        default=files[:1],
        format_func=lambda p: file_labels[p],
    )

    uploaded = st.file_uploader("...or upload additional .mat file(s)", type="mat", accept_multiple_files=True)

if not selected_files and not uploaded:
    st.info("Select or upload at least one result (.mat) file to begin.")
    st.stop()

results: list[ResultFile] = []
for p in selected_files:
    results.append(load_result(p, label=file_labels[p]))

if uploaded:
    import tempfile, os
    for uf in uploaded:
        tmp_dir = tempfile.gettempdir()
        tmp_path = os.path.join(tmp_dir, uf.name)
        with open(tmp_path, "wb") as fh:
            fh.write(uf.getbuffer())
        results.append(load_result(tmp_path, label=uf.name))

if not results:
    st.info("Select or upload at least one result (.mat) file to begin.")
    st.stop()

# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
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
st.dataframe(pd.DataFrame(overview_rows), hide_index=True, width="stretch")

all_var_names = variable_names(results)
groups = group_variables(all_var_names)

# ---------------------------------------------------------------------------
# Sidebar: variable selection
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Variables")
    top_level_names = [n for n in all_var_names if "." not in n]
    search = st.text_input(
        "Filter (substring, case-insensitive)",
        "",
        help=(
            "Empty shows only top-level variables. Type a component name "
            "(e.g. 'sensorT' or 'valve1.') to search the full nested "
            "Modelica hierarchy, e.g. sensorT.valueSensor."
        ),
    )
    search_l = search.lower().strip()
    filtered = [n for n in all_var_names if search_l in n.lower()] if search_l else top_level_names

    if "selected_vars" not in st.session_state:
        st.session_state["selected_vars"] = []

    MAX_ADD = 300
    col_a, col_b = st.columns(2)
    with col_a:
        add_disabled = len(filtered) > MAX_ADD
        if st.button("Add filtered", width="stretch", disabled=add_disabled):
            cur = set(st.session_state["selected_vars"])
            cur.update(filtered)
            st.session_state["selected_vars"] = sorted(cur)
        if add_disabled:
            st.caption(f"Narrow the filter below {MAX_ADD} matches to add in bulk ({len(filtered)} match).")
    with col_b:
        if st.button("Clear", width="stretch"):
            st.session_state["selected_vars"] = []

    display_options = sorted(set(filtered) | set(st.session_state["selected_vars"]))
    st.multiselect(
        "Variables to plot",
        options=display_options,
        key="selected_vars",
    )
    selected_vars = st.session_state["selected_vars"]

    st.caption(
        f"{len(all_var_names)} variables available ({len(top_level_names)} top-level) "
        f"in {len(groups)} groups."
    )

if not selected_vars:
    st.info("Pick one or more variables in the sidebar to plot.")
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar: time window & layout options
# ---------------------------------------------------------------------------
t_min = min(
    (t[0] for rf in results for v, t in rf.time.items() if v in selected_vars and len(t)),
    default=0.0,
)
t_max = max(
    (t[-1] for rf in results for v, t in rf.time.items() if v in selected_vars and len(t)),
    default=1.0,
)

with st.sidebar:
    st.header("Display")
    if t_max > t_min:
        t_range = st.slider(
            "Time window [s]",
            min_value=float(t_min),
            max_value=float(t_max),
            value=(float(t_min), float(t_max)),
        )
    else:
        t_range = (t_min, t_max)
    separate_subplots = st.checkbox("Separate subplot per variable (own y-scale)", value=True)

# ---------------------------------------------------------------------------
# Build tidy long dataframe for plotting
# ---------------------------------------------------------------------------
frames = []
for rf in results:
    for var in selected_vars:
        if var not in rf.series:
            continue
        t = rf.time[var]
        v = rf.series[var]
        unit = rf.units.get(var, "")
        mask = (t >= t_range[0]) & (t <= t_range[1])
        if not mask.any():
            continue
        label = f"{var} [{unit}]" if unit else var
        frames.append(
            pd.DataFrame(
                {
                    "time": t[mask],
                    "value": v[mask],
                    "variable": var,
                    "variable_label": label,
                    "unit": unit,
                    "file": rf.label,
                }
            )
        )

if not frames:
    st.warning("No data in the selected time window for the chosen variables.")
    st.stop()

df = pd.concat(frames, ignore_index=True)

# ---------------------------------------------------------------------------
# Tabs: Plot / Parameters / Data
# ---------------------------------------------------------------------------
tab_plot, tab_params, tab_data = st.tabs(["Plot", "Parameters", "Data"])

with tab_plot:
    n_vars = df["variable"].nunique()
    if separate_subplots:
        fig = px.line(
            df,
            x="time",
            y="value",
            color="file",
            facet_row="variable_label",
            height=max(300, 260 * n_vars),
        )
        fig.update_yaxes(matches=None)
        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=", 1)[-1]))
    else:
        fig = px.line(
            df,
            x="time",
            y="value",
            color="variable_label",
            line_dash="file" if len(results) > 1 else None,
            height=600,
        )
    fig.update_layout(legend_title_text="", margin=dict(t=40, b=20))
    fig.update_xaxes(title_text="Time [s]")
    st.plotly_chart(fig, width="stretch")

    st.download_button(
        "Download plotted data (CSV)",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name="dymola_results.csv",
        mime="text/csv",
    )

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
        st.dataframe(param_df, width="stretch")

with tab_data:
    st.caption("Wide table (Time + selected variables) for a single result file.")
    file_choice = st.selectbox("File", options=[rf.label for rf in results])
    rf = next(r for r in results if r.label == file_choice)
    cols = {}
    ref_len = None
    skipped = []
    for var in selected_vars:
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
        mask = (wide_df["Time"] >= t_range[0]) & (wide_df["Time"] <= t_range[1])
        st.dataframe(wide_df[mask], width="stretch", height=400)
        st.download_button(
            "Download this table (CSV)",
            data=wide_df[mask].to_csv(index=False).encode("utf-8"),
            file_name=f"{file_choice}_selected_vars.csv",
            mime="text/csv",
        )
    if skipped:
        st.caption(f"Skipped (different time grid than the first variable): {', '.join(skipped)}")
