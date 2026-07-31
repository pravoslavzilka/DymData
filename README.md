# Dymola Results Viewer

A local [Streamlit](https://streamlit.io/) app for browsing and plotting Dymola simulation
results (`.mat` files) without needing Dymola, MATLAB, or a spreadsheet. It reads results
via the [`sdf`](https://pypi.org/project/sdf/) package and lets you build a small dashboard
of charts to inspect and compare simulation runs.

## Motivation

Dymola result files (`dsres`-style `.mat`) contain thousands of variables in a nested
Modelica component hierarchy (e.g. `PF1L.valve1.summary.Kv`), but only a handful of them
matter for a given investigation, and stakeholders often need to compare two runs
(e.g. "ideal" vs. "not-ideal" PID tuning, or a control-delay parameter sweep) side by side.
Opening Dymola or MATLAB just to eyeball a few signals is slow and not shareable. This app
gives a fast, scriptable-free way to:

- browse the full nested variable tree of a result file without knowing exact names up front,
- build a small set of chart definitions (which variables, which layout, which time window, or
  an X-Y dependency between two variables) once, and have them **persist across app restarts**,
- compare two result files against those same chart definitions side by side, so a chart in
  one column and its counterpart in the other are always the same variables, same order, and
- quickly spot which scalar parameters (PID gains, delays, etc.) actually differ between two
  runs, with values shown in whatever engineering units you prefer (°C instead of K, bar
  instead of Pa, ...).

## Requirements

- Python 3.12 (a `.venv` is expected at the project root; see Setup)
- Packages: `streamlit`, `sdf`, `pandas`, `plotly`, `numpy` (see `requirements.txt`)

## Setup

```powershell
cd D:\projects\IPP\DymData
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Running

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

This starts a local server (default `http://localhost:8501`) and opens the app in your
browser. Leave the terminal running while you use the app; `Ctrl+C` stops it.

## Usage

### 1. Point it at a results folder

The sidebar's **Results directory** field defaults to the project's Dymola output folder.
Change it to browse any folder containing `.mat` result files.

### 2. Pick a file per column

The Charts tab shows **two columns**, each with its own small 📁 button in the top-right of
its header. Click it to either pick a different `.mat` file from the folder or upload one
directly. Each column is independent — this is how you compare two runs (e.g. one column on
`ideal-run-PID`, the other on `not-ideal-run-PID`).

### 3. Build charts

Each *chart* is a named definition, shown as one row that spans both columns — so a chart
always shows the same variables from both files, letting you compare them directly. Only one
chart is *active* at a time (highlighted with a blue left border); the sidebar always edits
whichever chart is active. There are two chart types, added via the two buttons below the
chart list:

- **New Time Chart** — the standard variables-vs-time chart (variables + layout + time
  window), as described below.
- **New Dependant Chart** — an X-Y chart: pick one X-axis variable and one or more Y-axis
  variable(s), and it plots Y against X instead of against time (e.g. valve position vs.
  pressure drop). Shown with an "(X-Y)" badge in the chart row. If the X and Y variables don't
  share the same time grid, Y is resampled onto X's timestamps automatically.

Other controls on each chart row:

- **Activate (▶)** a chart to edit it — the sidebar's "Variables" and "Chart view" sections
  switch to that chart.
- **Duplicate (⧉)** copies a chart (handy for tweaking a variant without losing the original).
- **Delete (🗑)** removes a chart (disabled if it's the only one left).

If a chart's variables don't exist in a given column's file, that slot shows a short notice
instead of erroring; if only some of the variables exist there, just those are plotted.

### 4. Pick variables (sidebar)

For a Time Chart, the **Variables to plot** box lists every variable in the active chart's
file(s), including the full nested Modelica hierarchy — type to search, e.g. `valve1` finds
`PF1L.valve1.summary.Kv`. For adding many at once (a whole array like `coilOpen[1..8]`, or an
entire subcomponent), use the **Bulk-add by prefix** expander instead of clicking through the
dropdown one by one.

For a Dependant Chart, the sidebar instead shows an **X-axis variable** selectbox (single pick)
above the same variable box, now labeled **Y-axis variable(s)** (multi-pick).

### 5. Chart view (sidebar)

For the active chart:

- **Chart name** — rename it (shown in the row header and used in CSV filenames).
- Time Charts only:
  - **Chart layout**:
    - *One combined chart* — all selected variables overlaid on one plot. Up to two distinct
      units get their own y-axis (primary/secondary); with more than two units, a caption
      warns that the rest share the primary axis.
    - *Separate subplot per variable* — one subplot per variable, each with its own y-scale.
  - **Time window** — restricts the plotted range; bounds are computed from the chart's own
    variables.
- Dependant Charts always render as one combined X-Y plot (no layout/time-window controls).

Hovering a chart shows a tooltip with every overlapping line's value at that point, and lines
are drawn with small markers so overlapping traces stay distinguishable.

### 6. Compare basic parameters between the two runs

Click either column's file-name title to open a **Compare run parameters** dialog, split into
one side per run, listing a short curated list of scalar parameters (e.g. `PID.k`, `PID.Ti`)
with any value that differs between the two runs highlighted in red. Use the **⚙ Configure
basic parameters** button (below the overview table) to pick which parameters appear in that
list — it's a plain multiselect, just like picking chart variables.

### 7. Display units

Use the **⚙ Configure display units** button to change how a given raw unit is shown across
*all* charts — e.g. temperatures in °C or °F instead of K, pressures in bar/kPa/MPa instead of
Pa, durations in min/h instead of s. Only units with a known conversion are offered; anything
without one (dimensionless gains, oddball composite units, ...) is left as-is. The conversion
applies to axis titles, legend labels, and CSV exports for both chart types.

### 8. Parameters tab

Compares every scalar (non-time-series) parameter — PID gains, margins, delays, etc. —
between the two currently loaded files, with a **Differs** column flagging anything that's
not identical between them.

### 9. Data tab

A wide table (Time + the active chart's variables) for whichever of the two files you pick,
with a CSV download.

### 10. Settings persist automatically

The results directory, both files' selections, every chart (including its type, variables,
layout and time window), the basic-parameters list, and the display-unit preferences are all
saved to `.dymdata_settings.json` next to `app.py` after every interaction, and restored the
next time you open the app — so closing and reopening it brings back the same setup. This file
is git-ignored since it's local, machine-specific state.

## Project structure

```
app.py                     Streamlit UI — file pickers, chart grid, sidebar editors, tabs,
                           settings persistence, unit conversion, parameter comparison
dymola_app/
  reader.py                 Loads .mat files via sdf, recursively walks the full nested
                             component tree, splits variables into time series vs. scalar
                             parameters, and caches loads (keyed on path + mtime)
  treeutils.py               Groups array-indexed variable names (e.g. coilOpen[1..8])
requirements.txt
.dymdata_settings.json     Auto-saved app settings (git-ignored, created on first run)
```

## Notes

- Loading is cached per file (`st.cache_data`, keyed on path and modification time), so
  re-selecting an already-loaded file is instant; editing the `.mat` file on disk invalidates
  the cache automatically.
- A Dymola result file here exposes ~5,000+ variables once the full nested hierarchy is
  walked (not just top-level ones), so the variable search is what makes browsing practical —
  don't expect to eyeball the whole list.
- `.venv/` and `.claude/` are git-ignored; nothing in this repo assumes those exist on a
  fresh clone beyond running Setup again.
- Runs fully offline — everything (reading `.mat` files, charting, etc.) happens locally;
  Plotly's JS is bundled with Streamlit itself rather than fetched from a CDN. The only
  network activity is Streamlit's own optional, best-effort anonymous usage ping, which fails
  silently if you're offline and doesn't affect the app; disable it with
  `browser.gatherUsageStats = false` in `~/.streamlit/config.toml` if you'd rather it not try.
