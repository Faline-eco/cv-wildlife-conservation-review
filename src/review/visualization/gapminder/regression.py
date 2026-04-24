
# trend_dashboard.py
# Reusable regression trend helper + ipywidgets dashboard for Jupyter

from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

__all__ = [
    "make_regression_trend",
    "build_regression_dashboard",
    "show_regression_dashboard",
]

from review.visualization.gapminder.gapminder_explorer import ALIASES, _is_multival, _coerce_listlike_to_list


# ----------------------------- Helpers ----------------------------------

def _resolve_col(df: pd.DataFrame, name: str) -> str:
    """Return the actual df column matching 'name' case-insensitively; raise if none."""
    if name in df.columns:
        return name
    lower_map = {c.lower(): c for c in df.columns}
    key = name.lower()
    if key in lower_map:
        return lower_map[key]
    raise KeyError(f"Column '{name}' not found. Available: {list(df.columns)}")


import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

# --- replace your make_regression_trend with this version ---

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    if not isinstance(hex_color, str) or not hex_color.startswith("#") or len(hex_color) != 7:
        return f"rgba(31,119,180,{alpha})"
    r = int(hex_color[1:3], 16); g = int(hex_color[3:5], 16); b = int(hex_color[5:7], 16)
    return f"rgba({r},{g},{b},{alpha})"

def make_regression_trend(
    papers: pd.DataFrame,
    *,
    time_col: str = "Year",
    start: int | float | None = None,
    end: int | float | None = None,
    filters: dict | None = None,     # e.g. {"Modality": ["Camera Trap","Ground Robot"]}
    y_measure: str = "count",        # "count" | "sum" | "mean"
    y_col: str | None = None,
    normalize: str = "none",         # "none" | "per_x" | "per_category"
    category_strategy: str = "explode",  # "explode" | "first" | "join"
    show_ci: bool = True,
    marker_opacity: float = 0.8,
    height: int = 520,
):
    """
    Flexible regression with alias-aware columns and multi-valued category handling.
    """
    if papers is None or len(papers) == 0:
        raise ValueError("Empty DataFrame provided.")

    if normalize not in ("none", "per_x", "per_category"):
        raise ValueError("normalize must be one of: 'none', 'per_x', 'per_category'.")
    if normalize != "none" and y_measure != "count":
        raise ValueError("Relative modes require y_measure='count'.")

    df = papers.copy()

    # --- resolve columns
    time_col = _resolve_col(df, time_col)
    if y_measure in ("sum", "mean"):
        if not y_col:
            raise ValueError("y_col must be provided when y_measure='sum' or 'mean'.")
        y_col = _resolve_col(df, y_col)

    # Identify category filter key (optional)
    category_filter = None
    other_filters = {}
    if filters:
        items = list(filters.items())
        cat_key, cat_vals = items[0]
        cat_col = _resolve_col(df, cat_key)
        cat_vals = list(cat_vals) if isinstance(cat_vals, (list, tuple, set, pd.Series, np.ndarray)) else [cat_vals]
        category_filter = (cat_col, cat_vals)
        other_filters = { _resolve_col(df, k): v for k, v in items[1:] }

    # --- coerce time + window
    df = df[pd.to_numeric(df[time_col], errors="coerce").notna()].copy()
    df[time_col] = pd.to_numeric(df[time_col], errors="coerce")
    if start is not None: df = df[df[time_col] >= start]
    if end is not None:   df = df[df[time_col] <= end]

    # --- Apply non-category filters (robust to list-like)
    for k, v in other_filters.items():
        if isinstance(v, (list, tuple, set, pd.Series, np.ndarray)):
            # If k is list-like per row, keep row if any overlap; else simple isin
            if df[k].apply(_is_multival).any():
                vset = set(v)
                df = df[df[k].apply(lambda x: bool(vset & set(_coerce_listlike_to_list(x))) if _is_multival(x) else (x in vset))]
            else:
                df = df[df[k].isin(list(v))]
        else:
            if df[k].apply(_is_multival).any():
                df = df[df[k].apply(lambda x: v in set(_coerce_listlike_to_list(x)))]
            else:
                df = df[df[k] == v]

    # --- Prepare base totals for normalization (per_x)
    totals_by_time = None
    if normalize == "per_x":
        base_df = df.copy()
        totals_by_time = base_df.groupby(time_col, sort=True).size().rename("denom").reset_index()

    # --- Handle category (including multi-valued)
    if category_filter:
        cat_col = category_filter[0]
        # Standardize list-like shapes now
        if df[cat_col].apply(_is_multival).any():
            if category_strategy == "explode":
                df = df.copy()
                df[cat_col] = df[cat_col].apply(_coerce_listlike_to_list)
                df = df.explode(cat_col, ignore_index=True)
            elif category_strategy == "first":
                df = df.copy()
                df[cat_col] = df[cat_col].apply(lambda x: _coerce_listlike_to_list(x)[0] if _is_multival(x) and _coerce_listlike_to_list(x) else "Unknown")
            elif category_strategy == "join":
                df = df.copy()
                df[cat_col] = df[cat_col].apply(lambda x: "; ".join(map(str, _coerce_listlike_to_list(x))) if _is_multival(x) else x)
            else:
                raise ValueError("category_strategy must be one of: 'explode','first','join'.")

        # Now apply the chosen category values filter (post-strategy)
        sel_vals = set(category_filter[1])
        df = df[df[cat_col].isin(sel_vals)]

        groups = sorted(sel_vals, key=lambda v: str(v))
        group_col = cat_col
        legend_title = _resolve_col(pd.DataFrame(columns=[cat_col]), cat_col)  # its own name
    else:
        # No category filter → single series over "All"
        groups = [None]
        group_col = None
        legend_title = "Category"

    # --- aggregation helper (handles y_measure and normalization)
    def _aggregate(series_df: pd.DataFrame) -> pd.DataFrame:
        if y_measure == "count":
            agg = series_df.groupby(time_col, sort=True).size().reset_index(name="y_raw")
        else:
            gb = series_df.groupby(time_col, sort=True)[y_col]
            val = gb.sum() if y_measure == "sum" else gb.mean()
            agg = val.rename("y_raw").reset_index()
        if normalize == "none":
            agg["y"] = agg["y_raw"]
            return agg, None, None
        if normalize == "per_x":
            tmp = agg.merge(totals_by_time, on=time_col, how="left")
            tmp["y"] = tmp["y_raw"] / tmp["denom"].replace({0: np.nan})
            return tmp, "Share per time (of base)", ".0%"
        # per_category
        total_cat = agg["y_raw"].sum()
        agg["y"] = agg["y_raw"] / (total_cat if total_cat else np.nan)
        return agg, "Share within category", ".0%"

    # --- plotting
    palette = px.colors.qualitative.Plotly
    def _color_for(idx): return palette[idx % len(palette)]

    fig = go.Figure()
    stats = {}
    y_axis_label = "Count" if y_measure == "count" else f"{y_measure.title()}({y_col})"
    y_plot_label = y_axis_label
    y_tickformat = None

    for gi, gval in enumerate(groups):
        dfi = df if gval is None else df[df[group_col] == gval]
        agg, y_label_override, tick_fmt = _aggregate(dfi)
        if y_label_override: y_plot_label = y_label_override
        if tick_fmt: y_tickformat = tick_fmt

        base_color = _color_for(gi)

        fig.add_trace(go.Scatter(
            x=agg[time_col], y=agg["y"], mode="markers",
            marker=dict(color=base_color),
            name=str(gval) if gval is not None else "All",
            showlegend=False, legendgroup=str(gval) if gval is not None else "All",
            opacity=marker_opacity
        ))

        # regression
        valid = agg["y"].notna()
        if valid.sum() < 2:
            stats[str(gval) if gval is not None else "All"] = {
                "slope": np.nan, "intercept": np.nan, "r2": np.nan, "n": int(valid.sum()),
                "period": (start, end)
            }
            continue

        x = pd.to_numeric(agg.loc[valid, time_col], errors="coerce").to_numpy(float)
        y = pd.to_numeric(agg.loc[valid, "y"], errors="coerce").to_numpy(float)
        a, b = np.polyfit(x, y, 1)
        r2 = 0.0 if np.std(y) == 0 else float(np.corrcoef(x, y)[0, 1] ** 2)
        x_line = np.linspace(x.min(), x.max(), 200); y_line = a * x_line + b

        fig.add_trace(go.Scatter(
            x=x_line, y=y_line, mode="lines",
            line=dict(color=base_color, width=2),
            name=(str(gval) if gval is not None else "All") + " trend",
            legendgroup=str(gval) if gval is not None else "All",
            showlegend=True
        ))

        if show_ci and len(x) > 2:
            n = len(x); x_bar = x.mean(); sxx = np.sum((x - x_bar)**2)
            y_pred = a * x + b
            s2 = np.sum((y - y_pred)**2) / max(n-2, 1)
            t = 1.96
            se = np.sqrt(s2 * (1/n + (x_line - x_bar)**2 / max(sxx, 1e-12)))
            ci_up, ci_lo = y_line + t*se, y_line - t*se
            fig.add_trace(go.Scatter(
                x=list(x_line) + list(x_line[::-1]),
                y=list(ci_up) + list(ci_lo[::-1]),
                fill="toself",
                fillcolor=_hex_to_rgba(base_color, 0.5),
                line=dict(width=0),
                showlegend=False,
                hoverinfo="skip",
                legendgroup=str(gval) if gval is not None else "All",
                name="CI"
            ))

        stats[str(gval) if gval is not None else "All"] = {
            "slope": float(a), "intercept": float(b), "r2": float(r2), "n": int(len(x)),
            "period": (start, end)
        }

    fig.update_layout(
        height=height, title="",
        xaxis_title=time_col,
        yaxis_title=y_plot_label,
        legend_title=legend_title,
    )
    if y_tickformat:
        fig.update_yaxes(tickformat=y_tickformat, rangemode="tozero")

    return fig, stats


# ------------------------- Dashboard builder -----------------------------

def build_regression_dashboard(df: pd.DataFrame, *, default_time: str = "Year"):
    import ipywidgets as w
    from IPython.display import clear_output

    # column type guesses
    numeric_like = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) or pd.api.types.is_integer_dtype(df[c])]
    categorical_like = [c for c in df.columns if (pd.api.types.is_object_dtype(df[c]) or pd.api.types.is_categorical_dtype(df[c]))]

    # include alias canonical names if any of their aliases exist
    for canonical, candidates in ALIASES.items():
        if any((c in df.columns) for c in candidates):
            if canonical not in categorical_like and canonical not in numeric_like:
                categorical_like.append(canonical)

    # default time via aliases
    try:
        default_time_resolved = _resolve_col(df, default_time)
    except KeyError:
        default_time_resolved = next((c for c in df.columns if c.lower() == "year"), numeric_like[0] if numeric_like else df.columns[0])

    time_dd = w.Dropdown(options=sorted(set(numeric_like + [default_time_resolved])), value=default_time_resolved, description="Time")

    # period slider configured from numeric values in the chosen time column
    def _year_min_max(col):
        real_col = _resolve_col(df, col)
        ser = pd.to_numeric(df[real_col], errors="coerce").dropna()
        return (int(ser.min()), int(ser.max())) if len(ser) else (0, 1)

    ymin, ymax = _year_min_max(time_dd.value)
    range_slider = w.IntRangeSlider(value=[ymin, ymax], min=ymin, max=max(ymin, ymax), step=1, description="Period", continuous_update=False)

    # category chooser
    cat_dd = w.Dropdown(
        options=sorted(set(categorical_like + list(ALIASES.keys()))),
        value="Modality" if "Modality" in ALIASES else (categorical_like[0] if categorical_like else None),
        description="Category"
    )

    # strategy toggle
    strat_rb = w.ToggleButtons(
        options=[("Explode rows", "explode"), ("Take first", "first"), ("Join as text", "join")],
        value="explode",
        description="Multivalue"
    )

    def _cat_values(col):
        try:
            real = _resolve_col(df, col)
        except KeyError:
            return []
        s = df[real]
        if s.apply(_is_multival).any():
            # flatten distinct values
            vals = set()
            for v in s.dropna():
                if _is_multival(v):
                    vals.update(_coerce_listlike_to_list(v))
                else:
                    vals.add(v)
            return sorted(vals, key=lambda v: str(v))
        else:
            return sorted(s.dropna().unique().tolist(), key=lambda v: str(v))

    default_vals = _cat_values(cat_dd.value)
    vals_sel = w.SelectMultiple(options=default_vals,
                                value=tuple(v for v in default_vals if str(v).lower() == "camera trap") if default_vals else (),
                                description="Value(s)", rows=8)

    measure_rb = w.ToggleButtons(options=["count", "sum", "mean"], value="count", description="Measure")
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    ycol_dd = w.Dropdown(options=num_cols, value=(num_cols[0] if num_cols else None), description="Value col")
    norm_rb = w.ToggleButtons(
        options=[("Absolute", "none"), ("Relative per year", "per_x"), ("Relative within category", "per_category")],
        value="none",
        description="Scale"
    )
    show_ci_cb = w.Checkbox(value=True, description="Show 95% CI")
    refresh_btn = w.Button(description="Update", button_style="primary")
    stats_out = w.HTML()
    plot_out = w.Output()

    controls_left = w.VBox([time_dd, range_slider, show_ci_cb])
    controls_right = w.VBox([cat_dd, vals_sel, strat_rb, measure_rb, ycol_dd, norm_rb, refresh_btn])
    ui = w.HBox([controls_left, controls_right])
    container = w.VBox([ui, plot_out, stats_out])

    def _sync_range(*_):
        mn, mx = _year_min_max(time_dd.value)
        range_slider.min = mn; range_slider.max = max(mn, mx)
        v0, v1 = range_slider.value
        v0 = max(v0, mn); v1 = min(v1, range_slider.max)
        if v0 >= v1:
            v0, v1 = mn, range_slider.max
        range_slider.value = (v0, v1)

    def _on_cat_change(*_):
        vals = _cat_values(cat_dd.value)
        vals_sel.options = vals
        vals_sel.value = tuple(v for v in vals_sel.value if v in vals)

    def _toggle_ycol(*_):
        ycol_dd.layout.display = "" if measure_rb.value in ("sum", "mean") else "none"

    def render(*_):
        from IPython.display import clear_output, display
        with plot_out:
            clear_output(wait=True)
            flt = {}
            if cat_dd.value and len(vals_sel.value) > 0:
                flt[cat_dd.value] = list(vals_sel.value)

            tcol = time_dd.value
            start, end = range_slider.value
            y_measure = measure_rb.value
            y_col = ycol_dd.value if y_measure in ("sum", "mean") else None

            try:
                fig, stats = make_regression_trend(
                    df,
                    time_col=tcol,
                    start=start,
                    end=end,
                    filters=flt if flt else None,
                    y_measure=y_measure,
                    y_col=y_col,
                    normalize=norm_rb.value,
                    category_strategy=strat_rb.value,
                    show_ci=show_ci_cb.value,
                )
                fig.update_layout(
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
                    legend_title_text=None
                )
                display(fig)

                # multi-series stats table
                if isinstance(stats, dict):
                    rows = [
                        f"<tr><td>{k}</td><td>{v['slope']:.4g}</td><td>{v['r2']:.3f}</td><td>{v['n']}</td></tr>"
                        for k, v in stats.items()
                    ]
                    stats_out.value = (
                        "<table style='border-collapse:collapse'>"
                        "<tr><th style='padding:4px 8px;text-align:left'>Series</th>"
                        "<th style='padding:4px 8px;text-align:right'>Slope</th>"
                        "<th style='padding:4px 8px;text-align:right'>R²</th>"
                        "<th style='padding:4px 8px;text-align:right'>n</th></tr>"
                        + "".join(rows) + "</table>"
                    )
                else:
                    stats_out.value = ""
            except Exception as e:
                stats_out.value = f"<span style='color:#b00'>Error: {e}</span>"

    _sync_range(); _toggle_ycol(); _on_cat_change(); render()
    time_dd.observe(lambda *_: (_sync_range(), render()), names="value")
    range_slider.observe(render, names="value")
    cat_dd.observe(lambda *_: (_on_cat_change(), render()), names="value")
    vals_sel.observe(render, names="value")
    strat_rb.observe(render, names="value")
    measure_rb.observe(lambda *_: (_toggle_ycol(), render()), names="value")
    ycol_dd.observe(render, names="value")
    show_ci_cb.observe(render, names="value")
    refresh_btn.on_click(render)

    return {"container": container, "render": render,
            "widgets": {"time_dd": time_dd, "range_slider": range_slider, "cat_dd": cat_dd, "vals_sel": vals_sel,
                        "strat_rb": strat_rb, "measure_rb": measure_rb, "ycol_dd": ycol_dd,
                        "norm_rb": norm_rb, "show_ci_cb": show_ci_cb, "refresh_btn": refresh_btn},
            "outputs": {"plot_out": plot_out, "stats_out": stats_out}}


def show_regression_dashboard(df: pd.DataFrame, *, default_time: str = "Year"):
    """
    Build and display the dashboard. Returns the same dict as build_regression_dashboard.
    """
    from IPython.display import display
    state = build_regression_dashboard(df, default_time=default_time)
    display(state["container"])
    return state

import numpy as np
import pandas as pd

def compute_trends_by_category(
    df: pd.DataFrame,
    category_col: str,                 # e.g., "Modality" (can be an alias like "Imaging Method")
    *,
    time_col: str = "Year",            # numeric or convertible
    start: int | float | None = None,  # inclusive start
    end: int | float | None = None,    # inclusive end
    y_measure: str = "count",          # "count" | "sum" | "mean"
    y_col: str | None = None,          # required for "sum"/"mean"
    values: list | None = None,        # optional subset of category values
    alpha: float = 0.05,               # p-value threshold & CI level
    relative: bool = False,            # regress on per-year shares
    category_strategy: str = "explode" # "explode" | "first" | "join"
) -> pd.DataFrame:
    """
    Trend per category value with robust handling of list/set category columns and alias resolution.
    Returns DataFrame columns:
      [<category_col>, slope, intercept, r2, n, slope_std_err, t_stat, p_value, slope_ci_low, slope_ci_high, significant]
    """
    # ---------- Helpers ----------
    ALIASES = {
        "Year": ["Year", "year"],
        "Modality": ["Modality", "Imaging Method"],
        "Habitat": ["Habitat", "ParentHabitat", "ParentHabitat values"],
        "Task": ["Task", "CV Tasks", "CV Tasks - verified"],
        "Spectra": ["Spectra", "Light Spectra"],
        "Country": ["Country", "Countries", "Country - verified"],
        "Family": ["Family", "Taxonomy family", "Taxonomic family"],
        "Species": ["Species",
                    "Species (Text)(translated) - verified",
                    "Species (Images)(translated) - verified"],
    }
    def _resolve_col(df_, name: str) -> str:
        if name in df_.columns: return name
        lower_map = {c.lower(): c for c in df_.columns}
        if name.lower() in lower_map: return lower_map[name.lower()]
        for cand in ALIASES.get(name, []):
            if cand in df_.columns: return cand
            if cand.lower() in lower_map: return lower_map[cand.lower()]
        raise KeyError(f"Column '{name}' not found. Available: {list(df_.columns)}")

    def _is_multival(x) -> bool:
        return isinstance(x, (list, tuple, set))

    def _to_list(x):
        if isinstance(x, set): return list(x)
        return list(x) if isinstance(x, (list, tuple)) else x

    def _first_or_unknown(x):
        if _is_multival(x):
            xs = _to_list(x)
            return xs[0] if xs else "Unknown"
        return x if pd.notna(x) and x != "" else "Unknown"

    # ---------- Resolve columns ----------
    time_col_res = _resolve_col(df, time_col)
    cat_col_res  = _resolve_col(df, category_col)
    if y_measure in ("sum", "mean"):
        if not y_col:
            raise ValueError("y_col must be provided when y_measure is 'sum' or 'mean'.")
        y_col_res = _resolve_col(df, y_col)
    else:
        y_col_res = None
    if relative and y_measure == "mean":
        raise ValueError("relative=True is not supported with y_measure='mean'.")

    data = df.copy()

    # ---------- Coerce time + window ----------
    data = data[pd.to_numeric(data[time_col_res], errors="coerce").notna()].copy()
    data[time_col_res] = pd.to_numeric(data[time_col_res], errors="coerce")
    if start is not None: data = data[data[time_col_res] >= start]
    if end   is not None: data = data[data[time_col_res] <= end]

    # ---------- Prepare category column (avoid unhashables) ----------
    if data[cat_col_res].apply(_is_multival).any():
        if category_strategy == "explode":
            data = data.copy()
            data[cat_col_res] = data[cat_col_res].apply(_to_list)
            data = data.explode(cat_col_res, ignore_index=True)
        elif category_strategy == "first":
            data = data.copy()
            data[cat_col_res] = data[cat_col_res].apply(_first_or_unknown)
        elif category_strategy == "join":
            data = data.copy()
            data[cat_col_res] = data[cat_col_res].apply(
                lambda x: "; ".join(map(str, _to_list(x))) if _is_multival(x) else x
            )
        else:
            raise ValueError("category_strategy must be one of: 'explode', 'first', 'join'.")

    # ---------- Optional subset on category values ----------
    if values is not None:
        sel = set(values)
        # Now cat col is scalar (explode/first) or joined string
        if category_strategy == "join":
            # keep row if any token is in sel
            data = data[data[cat_col_res].apply(
                lambda s: bool(sel & set(map(str.strip, str(s).split(";")))) if pd.notna(s) else False
            )]
        else:
            data = data[data[cat_col_res].isin(sel)]

    # ---------- Aggregate per (category, time) ----------
    if y_measure == "count":
        agg = (
            data.groupby([cat_col_res, time_col_res], dropna=False, sort=True)
                .size()
                .reset_index(name="y")
        )
    elif y_measure in ("sum", "mean"):
        gb = data.groupby([cat_col_res, time_col_res], dropna=False, sort=True)[y_col_res]
        series = gb.sum() if y_measure == "sum" else gb.mean()
        agg = series.rename("y").reset_index()
    else:
        raise ValueError("y_measure must be 'count', 'sum', or 'mean'.")

    # ---------- Relative normalization (per time) ----------
    if relative:
        denom = agg.groupby(time_col_res, dropna=False)["y"].transform("sum")
        agg["y"] = agg["y"] / denom.replace(0, pd.NA)

    # ---------- Stats per category ----------
    try:
        from scipy.stats import t as t_dist  # type: ignore
        _has_scipy = True
    except Exception:
        _has_scipy = False

    rows = []
    for val, sub in agg.groupby(cat_col_res, sort=False):
        sub = sub.sort_values(time_col_res, kind="mergesort")
        x = sub[time_col_res].to_numpy(dtype=float)
        y = sub["y"].to_numpy(dtype=float)
        n = len(sub)

        if n < 2:
            rows.append({
                cat_col_res: val,
                "slope": np.nan, "intercept": np.nan, "r2": np.nan, "n": n,
                "slope_std_err": np.nan, "t_stat": np.nan, "p_value": np.nan,
                "slope_ci_low": np.nan, "slope_ci_high": np.nan,
                "significant": False,
            })
            continue

        a, b = np.polyfit(x, y, 1)
        y_pred = a * x + b
        r2 = 0.0 if np.std(y) == 0 else float(np.corrcoef(x, y)[0, 1] ** 2)

        df_dof = max(n - 2, 1)
        x_bar = float(x.mean())
        sxx = float(np.sum((x - x_bar) ** 2))
        sse = float(np.sum((y - y_pred) ** 2))
        s2 = sse / df_dof if df_dof > 0 else np.nan
        slope_std_err = np.sqrt(s2 / sxx) if sxx > 0 and np.isfinite(s2) else np.nan

        if np.isfinite(slope_std_err) and slope_std_err > 0:
            t_stat = float(a / slope_std_err)
            if _has_scipy:
                p_value = float(2 * t_dist.sf(np.abs(t_stat), df=df_dof))
                tcrit = float(t_dist.ppf(1 - alpha / 2, df=df_dof))
            else:
                from math import erf, sqrt
                z = abs(t_stat)
                p_value = float(2 * (1 - 0.5 * (1 + erf(z / sqrt(2)))))
                tcrit = 1.959963984540054
        else:
            t_stat = np.nan
            p_value = np.nan
            tcrit = np.nan

        if np.isfinite(tcrit) and np.isfinite(slope_std_err):
            slope_ci_low  = float(a - tcrit * slope_std_err)
            slope_ci_high = float(a + tcrit * slope_std_err)
        else:
            slope_ci_low = slope_ci_high = np.nan

        rows.append({
            cat_col_res: val,
            "slope": float(a),
            "intercept": float(b),
            "r2": float(r2),
            "n": int(n),
            "slope_std_err": float(slope_std_err) if np.isfinite(slope_std_err) else np.nan,
            "t_stat": float(t_stat) if np.isfinite(t_stat) else np.nan,
            "p_value": float(p_value) if np.isfinite(p_value) else np.nan,
            "slope_ci_low": slope_ci_low,
            "slope_ci_high": slope_ci_high,
            "significant": (p_value < alpha) if np.isfinite(p_value) else False,
        })

    result = pd.DataFrame(rows).sort_values(
        by=["significant", "slope"],
        ascending=[False, False],
        na_position="last",
        kind="mergesort",
    ).reset_index(drop=True)

    # Keep the original parameter name as the output column header (nice UX),
    # but only if it differs from the resolved name.
    if cat_col_res != category_col and category_col not in result.columns:
        result = result.rename(columns={cat_col_res: category_col})

    return result
