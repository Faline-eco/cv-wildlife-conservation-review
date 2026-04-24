import math
from itertools import cycle

import pandas as pd
import numpy as np
from typing import Iterable, Optional

import plotly.express as px
import ipywidgets as W
from IPython.display import display

TAB20 = [
    '#1f77b4', '#aec7e8',
    '#ff7f0e', '#ffbb78',
    '#2ca02c', '#98df8a',
    '#d62728', '#ff9896',
    '#9467bd', '#c5b0d5',
    '#8c564b', '#c49c94',
    '#e377c2', '#f7b6d2',
    '#7f7f7f', '#c7c7c7',
    '#bcbd22', '#dbdb8d',
    '#17becf', '#9edae5'
]


# ---------- helpers ----------
def _is_list_like(x):
    return isinstance(x, (list, tuple, set))


def _safe_len(x):
    if _is_list_like(x):
        return len(x)
    if pd.isna(x):
        return 0
    # treat scalars as a single element
    return 1


def add_count_columns(df: pd.DataFrame) -> pd.DataFrame:
    """For each column that contains any list-like values, add COUNT[col] = length per row."""
    df = df.copy()
    for col in df.columns:
        if df[col].apply(_is_list_like).any():
            df[f"COUNT[{col}]"] = df[col].apply(_safe_len)
    return df


def explode_for_column(df: pd.DataFrame, col: Optional[str]) -> pd.DataFrame:
    """Explode df if the chosen column is list-like; otherwise return unchanged."""
    if col is None or col not in df.columns:
        return df
    if df[col].apply(_is_list_like).any():
        # Normalize to list for explode
        tmp = df.copy()
        tmp[col] = tmp[col].apply(lambda v: list(v) if _is_list_like(v) else ([v] if pd.notna(v) else []))
        return tmp.explode(col, ignore_index=True)
    return df


def infer_numeric_columns(df: pd.DataFrame):
    nums = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    return nums


def infer_categorical_columns(df: pd.DataFrame):
    # Consider anything not numeric as categorical candidate
    cats = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
    return cats


# ---------- main widget ----------
class DataVisWidget:
    def __init__(self, df: pd.DataFrame):
        self._raw = df
        self.df = add_count_columns(df)

        self.numeric_cols = infer_numeric_columns(self.df)
        self.categorical_cols = infer_categorical_columns(self.df)

        # Controls
        col_opts_all = ["— None —"] + list(self.df.columns)
        num_opts = ["— None —"] + self.numeric_cols
        cat_opts = ["— None —"] + self.categorical_cols

        self.chart_type = W.ToggleButtons(
            options=[("Scatter", "scatter"), ("Stacked bar", "bar"), ("Line", "line")],
            value="scatter", description="Chart", button_style=""
        )
        self.x_col = W.Dropdown(options=col_opts_all, value=self._default_x(), description="X")
        self.y_col = W.Dropdown(options=col_opts_all, value=self._default_y(), description="Y")
        self.color_col = W.Dropdown(options=cat_opts, value="— None —", description="Color")
        self.size_col = W.Dropdown(options=num_opts, value="— None —", description="Size")
        self.group_col = W.Dropdown(options=cat_opts, value="— None —", description="Group by")

        self.agg_fn = W.Dropdown(
            options=[("sum", "sum"), ("mean", "mean"), ("count (rows)", "count")],
            value="sum", description="Aggregate"
        )

        self.normalize_line = W.Checkbox(value=False, description="Relative within line (percent)")
        self.stack_normalize = W.Checkbox(value=False, description="Stacked to 100% (bar only)")
        self.log_y = W.Checkbox(value=False, description="Log scale Y-axis")
        self.vary_line_dash = W.Checkbox(value=False, description="Vary line styles")
        self.vary_symbols = W.Checkbox(value=False, description="Vary point symbols")

        self.filter_missing = W.Checkbox(value=True, description="Drop NaNs in X/Y")

        # NEW: Top N control (0 = all)
        self.top_n = W.IntText(value=0, description="Top N (0 = all)")

        # X-jittering controls
        self.x_jitter = W.Checkbox(value=False, description="X-jitter (reduce overlap)")
        self.jitter_amount = W.FloatSlider(value=0.2, min=0.01, max=1.0, step=0.01, description="Jitter amount")

        self.out = W.Output()

        # Preferred defaults based on your request
        x_default = self._pick_if_exists(["Year", "year"])
        y_default = self._pick_if_exists(["COUNT[Species]", "Count[Species]", "COUNT[Species]", "Species_count"])
        color_default = self._pick_if_exists(["imaging method", "Imaging Method", "Imaging_method"])
        size_default = self._pick_if_exists(["study_size", "Study_size", "Study Size"])

        # Assign only if those exist, otherwise fall back to normal defaults
        self.x_col.value = x_default or self._default_x()
        self.y_col.value = y_default or self._default_y()
        self.color_col.value = color_default or "— None —"
        self.size_col.value = size_default or "— None —"

        # Wire events
        for w in [self.chart_type, self.x_col, self.y_col, self.color_col,
                  self.size_col, self.group_col, self.agg_fn,
                  self.normalize_line, self.stack_normalize, self.log_y,
                  self.vary_line_dash, self.vary_symbols, self.filter_missing, self.top_n,
                  self.x_jitter, self.jitter_amount]:
            w.observe(self._redraw, names="value")

    def _default_x(self):
        if "Year" in self.df.columns:
            return "Year"
        return self.df.columns[0]

    def _default_y(self):
        for candidate in ["# Species", "Species", "Count", "Value"]:
            if candidate in self.df.columns:
                return candidate
        return self.numeric_cols[0] if self.numeric_cols else self.df.columns[0]

    def _value_or_none(self, widget):
        v = widget.value
        return None if v == "— None —" else v

    def _aggregate(self, dfe, x, y, color, group):
        """
        Aggregation for bar/line charts.
        If y is None -> use row count.
        """
        by = [c for c in [x, color, group] if c is not None]
        if not by:
            by = [x] if x is not None else []

        if y is None:
            agg = dfe.groupby(by, dropna=False).size().rename("value").reset_index()
        else:
            if self.agg_fn.value == "sum":
                agg = dfe.groupby(by, dropna=False)[y].sum().rename("value").reset_index()
            elif self.agg_fn.value == "mean":
                agg = dfe.groupby(by, dropna=False)[y].mean().rename("value").reset_index()
            else:
                agg = dfe.groupby(by, dropna=False)[y].count().rename("value").reset_index()

        return agg

    def _normalize_within_line(self, agg, x, color, group):
        """
        (Still available if you need it elsewhere; currently not used directly.)
        """
        if agg.empty:
            return agg
        line_keys = [c for c in [color, group] if c is not None]
        if not line_keys:
            total = agg.groupby([])["value"].transform("sum")
            agg["value"] = np.where(total.eq(0), 0, agg["value"] / total * 100)
            return agg

        agg["value"] = agg.groupby(line_keys)["value"].transform(
            lambda s: (s / s.sum() * 100) if s.sum() else s
        )
        return agg

    def _prepare_df_for_plot(self, x, y, color, group):
        dfe = self.df
        for col in [x, y, color, group]:
            dfe = explode_for_column(dfe, col)

        if self.filter_missing.value:
            if x is not None and x in dfe.columns:
                dfe = dfe[dfe[x].notna()]
            if y is not None and y in dfe.columns:
                dfe = dfe[dfe[y].notna()]
        return dfe

    def _make_combo_labels(self, dfe, color, group, name="_combo"):
        if color and group:
            dfe[name] = dfe[color].astype(str) + " | " + dfe[group].astype(str)
            return name
        return color or group  # one of them or None

    def _pick_if_exists(self, candidates):
        for c in candidates:
            if c in self.df.columns:
                return c
        return None

    # ---------- NEW helper methods for Top N ----------

    def _top_n_value(self) -> int:
        """Return sanitized top-n value (>= 0)."""
        try:
            n = int(self.top_n.value)
        except Exception:
            return 0
        return max(0, n)

    def _apply_x_jitter(self, df: pd.DataFrame, x_col: str) -> pd.DataFrame:
        """Apply random jitter to x-values if enabled."""
        if not self.x_jitter.value or x_col is None or x_col not in df.columns:
            return df
        df = df.copy()
        jitter = self.jitter_amount.value
        n = len(df)
        # Create jittered x column
        x_vals = df[x_col]
        if pd.api.types.is_numeric_dtype(x_vals):
            # For numeric: jitter as fraction of typical spacing or range
            noise = np.random.uniform(-jitter, jitter, n)
            df["_x_jittered"] = x_vals + noise
        else:
            # For categorical: convert to codes, jitter, keep as float for plotting
            codes = pd.Categorical(x_vals).codes.astype(float)
            noise = np.random.uniform(-jitter, jitter, n)
            df["_x_jittered"] = codes + noise
        return df

    def _filter_top_n_raw(self, dfe: pd.DataFrame, label_col: Optional[str], y_col: Optional[str]):
        """
        For scatter with raw points:
        keep only rows whose label_col (color/group combo) is among the top N
        by impact (sum of y_col if numeric, else row count).
        """
        n = self._top_n_value()
        if n <= 0 or label_col is None or label_col not in dfe.columns:
            return dfe

        if y_col is not None and y_col in dfe.columns and pd.api.types.is_numeric_dtype(dfe[y_col]):
            impact = dfe.groupby(label_col)[y_col].sum()
        else:
            impact = dfe.groupby(label_col).size()

        keep_labels = impact.nlargest(min(n, len(impact))).index
        return dfe[dfe[label_col].isin(keep_labels)]

    def _filter_top_n_agg(self, agg: pd.DataFrame, label_col: Optional[str]):
        """
        For aggregated data (bar/line and scatter without y):
        keep only rows whose label_col is among the top N by sum of 'value'.
        """
        n = self._top_n_value()
        if n <= 0 or label_col is None or label_col not in agg.columns:
            return agg

        impact = agg.groupby(label_col)["value"].sum()
        keep_labels = impact.nlargest(min(n, len(impact))).index
        return agg[agg[label_col].isin(keep_labels)]

    # ---------- main redraw ----------

    def _redraw(self, *_):
        with self.out:
            self.out.clear_output()

            palette = getattr(self, "color_scheme", TAB20)

            x = self._value_or_none(self.x_col)
            y = self._value_or_none(self.y_col)
            color = self._value_or_none(self.color_col)
            size = self._value_or_none(self.size_col)
            group = self._value_or_none(self.group_col)

            dfe = self._prepare_df_for_plot(x, y, color, group)
            combo = self._make_combo_labels(dfe, color, group, name="_label")

            if self.chart_type.value == "scatter":
                if y is None:
                    # Aggregated scatter (count)
                    agg = self._aggregate(dfe, x, None, combo, None)
                    agg = self._filter_top_n_agg(agg, combo)
                    # Apply jitter if enabled
                    agg = self._apply_x_jitter(agg, x)
                    x_plot = "_x_jittered" if "_x_jittered" in agg.columns else x
                    fig = px.scatter(
                        agg, x=x_plot, y="value", color=combo,
                        color_discrete_sequence=palette
                    )
                    fig.update_layout(yaxis_title="count", xaxis_title=x)
                else:
                    # Raw scatter: filter rows based on top-N impact
                    dfe = self._filter_top_n_raw(dfe, combo, y)
                    # Apply jitter if enabled
                    dfe = self._apply_x_jitter(dfe, x)
                    x_plot = "_x_jittered" if "_x_jittered" in dfe.columns else x
                    kwargs = {"color_discrete_sequence": palette}
                    if combo:
                        kwargs["color"] = combo
                    if size:
                        kwargs["size"] = size
                    if group:
                        kwargs["symbol"] = group
                    fig = px.scatter(dfe, x=x_plot, y=y, **kwargs)
                    if x_plot != x:
                        fig.update_layout(xaxis_title=x)

                fig.update_traces(mode="markers")
                fig.update_layout(height=520)
                if self.log_y.value:
                    fig.update_yaxes(type="log")
                fig.update_layout(
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="center",
                        x=0.5
                    ),
                    legend_title_text=None,
                    font=dict(
                        size=18
                    )
                )
                config = {
                    "toImageButtonOptions": {
                        "format": "svg",
                        "filename": "plot",
                        "height": 600,
                        "width": 1400,
                        "scale": 1,
                    }
                }
                fig.show(config=config)

            elif self.chart_type.value == "bar":
                agg = self._aggregate(dfe, x, y, combo, None)
                agg = self._filter_top_n_agg(agg, combo)

                if self.stack_normalize.value:
                    agg["value"] = agg.groupby([x])["value"].transform(
                        lambda s: (s / s.sum() * 100) if s.sum() else s
                    )
                    yaxis_title = "percent"
                else:
                    yaxis_title = "value"

                fig = px.bar(
                    agg, x=x, y="value", color=combo, barmode="stack",
                    color_discrete_sequence=palette
                )
                if self.log_y.value:
                    fig.update_yaxes(type="log")
                fig.update_layout(yaxis_title=yaxis_title, height=520,
                                  font=dict(
                                      size=18
                                  ))
                config = {
                    "toImageButtonOptions": {
                        "format": "svg",
                        "filename": "plot",
                        "height": 600,
                        "width": 1400,
                        "scale": 1,
                    }
                }
                fig.show(config=config)

            elif self.chart_type.value == "line":
                agg = self._aggregate(dfe, x, y, combo, None)
                agg = self._filter_top_n_agg(agg, combo)

                if self.normalize_line.value:
                    if combo:
                        agg["value"] = agg.groupby([combo])["value"].transform(
                            lambda s: (s / s.sum() * 100) if s.sum() else s
                        )
                    else:
                        total = agg["value"].sum()
                        agg["value"] = 0 if total == 0 else agg["value"] / total * 100
                    yaxis_title = "percent within line"
                else:
                    yaxis_title = "value"

                # Apply jitter if enabled
                agg = self._apply_x_jitter(agg, x)
                x_plot = "_x_jittered" if "_x_jittered" in agg.columns else x

                line_kwargs = {
                    "x": x_plot,
                    "y": "value",
                    "color": combo,
                    "markers": True,
                    "color_discrete_sequence": palette,
                }
                if self.vary_line_dash.value and combo:
                    line_kwargs["line_dash"] = combo
                if self.vary_symbols.value and combo:
                    line_kwargs["symbol"] = combo
                fig = px.line(agg, **line_kwargs)
                fig.update_traces(marker=dict(size=10))

                # Combine y-axis updates to avoid conflicts between log scale and percentage formatting
                yaxis_kwargs = {}
                if self.log_y.value:
                    yaxis_kwargs["type"] = "log"
                if self.normalize_line.value:
                    if self.log_y.value:
                        # For log scale with percentages, don't use ticksuffix - it conflicts with log formatting
                        # Instead, just update the axis title to indicate percentages
                        pass
                    else:
                        yaxis_kwargs["tickformat"] = ".0f"
                        yaxis_kwargs["ticksuffix"] = "%"
                if yaxis_kwargs:
                    fig.update_yaxes(**yaxis_kwargs)

                fig.update_layout(yaxis_title=yaxis_title, xaxis_title=x, height=520)
                fig.update_layout(
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="center",
                        x=0.5
                    ),
                    legend_title_text=None,
                    font=dict(
                        size=18
                    )
                )
                config = {
                    "toImageButtonOptions": {
                        "format": "svg",
                        "filename": "plot",
                        "height": 600,
                        "width": 1400,
                        "scale": 1,
                    }
                }
                fig.show(config=config)

    def display(self):
        left = W.VBox([
            self.chart_type,
            self.x_col, self.y_col,
            self.color_col, self.size_col, self.group_col,
        ])
        right = W.VBox([
            self.agg_fn,
            self.normalize_line,
            self.stack_normalize,
            self.log_y,
            self.vary_line_dash,
            self.vary_symbols,
            self.filter_missing,
            self.top_n,  # <-- show Top N control
            self.x_jitter,
            self.jitter_amount,
        ])
        ui = W.HBox([left, W.Label("  "), right])
        display(ui, self.out)
        self._redraw()