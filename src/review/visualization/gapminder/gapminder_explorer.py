#!/usr/bin/env python3

import os
import json
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.io as pio

# -------------------------------
# Helpers
# -------------------------------

# Put this near the top of trend_dashboard.py
ALIASES = {
    # canonical -> possible df column names (case-insensitive check)
    "Year":    ["Year", "year"],

    # NEW schema
    "Modality": ["Modality", "Imaging Method", "Imaging Method (Text) - verified"],
    "Habitat":  ["Habitat", "ParentHabitat", "ParentHabitat values"],
    "Task":     ["Task", "CV Tasks", "CV Tasks - verified"],
    "Spectra":  ["Spectra", "Light Spectra", "Light Spectra (Text) (new) - verified", "Light Spectra (Text) - verified"],
    "Country":  ["Country", "Countries", "Country - verified", "Country (Text) - verified"],
    "Family":   ["Family", "Taxonomy family", "Taxonomic family"],
    "Species":  ["Species", "Species (Text)(translated) - verified", "Species (Images)(translated) - verified"],
}


def _resolve_col(df: pd.DataFrame, want: str, *, aliases: dict[str, list[str]] | None = None) -> str:
    """
    Resolve a column name in df:
      - exact match
      - case-insensitive match
      - alias match (first existing alias wins)
    Raises KeyError if none found.
    """
    if want in df.columns:
        return want
    lower_map = {c.lower(): c for c in df.columns}
    key = want.lower()
    if key in lower_map:
        return lower_map[key]

    # alias search
    if aliases:
        names = aliases.get(want, [])
        for candidate in names:
            if candidate in df.columns:
                return candidate
            if candidate.lower() in lower_map:
                return lower_map[candidate.lower()]

    raise KeyError(f"Column '{want}' not found. Available: {list(df.columns)}")

def _is_multival(x) -> bool:
    return isinstance(x, (list, tuple, set))

def _coerce_listlike_to_list(v):
    if isinstance(v, set):
        return list(v)
    return list(v) if isinstance(v, (list, tuple)) else v

def convert_list_columns_to_sets(df: pd.DataFrame) -> pd.DataFrame:
    df_copy = df.copy()
    for col in df_copy.columns:
        if df_copy[col].apply(lambda x: isinstance(x, list)).any():
            df_copy[col] = df_copy[col].apply(lambda x: list(set(x)) if isinstance(x, list) else x)
    return df_copy


def unify_imaging_methods(lst):
    if not isinstance(lst, list):
        return [lst]
    res = []
    for l in lst:
        if l in [
            "Camera (manually triggered; e.g. Smartphone, System Camera, SLR Camera)",
            "Video Camera (e.g. CCTV Camera, Action Camera, PTZ Camera)",
        ]:
            res.append("Non-specialized Camera")
        elif l in ["Time-lapse Camera", "Event Camera"]:
            res.append("Other")
        elif l in ["Camera Trap (temperature- or motion triggered)", "Camera Trap"]:
            res.append("Camera Trap")
        else:
            res.append(l)
    if len(res) == 0:
        res.append("Non-specialized Camera")
    return list(set(res))


IUCN_MAPPING = {
    "Forest": "Forest",
    "Savanna": "Savanna",
    "Shrubland": "Shrubland",
    "Grassland": "Grassland",
    "WetlandsInland": "Wetlands (inland)",
    "Desert": "Desert",
    "RockyAreasEGInlandCliffsMountainPeaks": "Rocky areas (e.g. inland cliffs, mountain peaks)",
    "CavesSubterraneanHabitatsNonAquatic": "Cave and subterranean habitats (non-aquatic)",
    "MarineNeritic": "Marine",
    "MarineOceanic": "Marine",
    "MarineCoastalSupratidal": "Marine",
    "MarineDeepOceanFloorBenthicAndDemersal": "Marine",
    "MarineIntertidal": "Marine",
    "ArtificialTerrestrial": "Artificial Terrestrial",
    "ArtificialAquatic": "Artificial Aquatic",
    "Unknown": "Unknown / Other",
}


def map_to_first_level(habitat: str) -> str:
    return IUCN_MAPPING.get(habitat, "Unknown")


def map_all_to_first_level(habitats: list) -> list:
    if not isinstance(habitats, list):
        return ["Unknown"]
    res = []
    for habitat in habitats:
        res.append(map_to_first_level(habitat))
    return list(set(res))


def fix_cv_tasks(tasks):
    res = []
    for task in tasks if isinstance(tasks, list) else [tasks]:
        if isinstance(task, str):
            y = task.lower()
            if y in ["identificaiton", "identification", "re-identification", "identifcation"]:
                res.append("Identification")
            elif y in ["counting", "detection", "localization"]:
                res.append("Detection")
            elif y in ["classification", "classifcation", "classificaiton"]:
                res.append("Classification")
            elif y in ["behaviour analysis", "activity recognition", "interaction monitoring", "behavior analysis"]:
                res.append("Activity Recognition")
            elif y in ["segmentation", "instance segmentation"]:
                res.append("Segmentation")
            else:
                res.append(task)
        else:
            res.append(task)
    if len(res) == 0:
        res.append("Unknown")
    return list(set(res))


def spectra_unknown_to_other(items):
    if not isinstance(items, list):
        return ["Other"]
    out = []
    for v in items:
        if v == "Unknown":
            out.append("Other")
        else:
            out.append(v)
    return list(set(out))


def _safe_len_list(x):
    if isinstance(x, list):
        return len(x)
    return 0


def _first_or_unknown(x):
    if isinstance(x, list) and len(x) > 0:
        return x[0]
    if isinstance(x, str) and x.strip():
        return x
    return "Unknown"


def _norm_name(s: str) -> str:
    if not isinstance(s, str):
        return ""
    return " ".join(s.strip().lower().split())


def _build_name_lookup_from_gbif_hits(hits: dict):
    name_to_match = {}
    if not isinstance(hits, dict):
        return name_to_match
    for _, payload in (hits.get("hits", hits) or {}).items():
        m = (payload or {}).get("match", {}) or {}
        # Index by canonicalName, scientificName, and originalQuery if present
        for c in [
            payload.get("originalQuery"),
            m.get("canonicalName"),
            m.get("scientificName"),
        ]:
            if not c:
                continue
            name_to_match[_norm_name(c)] = m
    return name_to_match


def _maybe_load_gbif_lookup(explicit_path: str | None = None):
    candidates = []
    if explicit_path:
        candidates.append(explicit_path)
    candidates += [
        os.path.join(os.getcwd(), "gbif_cache.json"),
        os.path.join(os.getcwd(), "data", "gbif_cache.json"),
    ]
    for p in candidates:
        try:
            if p and os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                return _build_name_lookup_from_gbif_hits(data)
        except Exception:
            continue
    return {}


# -------------------------------
# Core pipeline (multi-input, uniform merge)
# -------------------------------

def _select_first_existing(df: pd.DataFrame, candidates: list[str]):
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _clean_doi(val: any) -> str:
    s = str(val)
    try:
        return urlparse(s).path.lstrip("/") or s
    except Exception:
        return s


def load_and_prepare_many(paths: list[str], gbif_cache_path: str | None = None) -> pd.DataFrame:
    frames = []
    gbif_lookup = _maybe_load_gbif_lookup(gbif_cache_path)
    for p in paths:
        df = convert_list_columns_to_sets(pd.read_parquet(p))
        df = df[(df.get("year", pd.Series(dtype=float)) >= 2014) & (df.get("year", pd.Series(dtype=float)) <= 2024)] if "year" in df.columns else df

        # Ensure required logical columns exist (with fallbacks)
        species_cols = [c for c in [
            "Species (Text)(translated) - verified",
            "Species (Images)(translated) - verified",
        ] if c in df.columns]
        species_col = species_cols[0] if species_cols else None
        tasks_col = _select_first_existing(df, ["CV Tasks - verified"]) or None
        habitat_col = _select_first_existing(df, ["ParentHabitat values"]) or None
        modality_col = _select_first_existing(df, ["Imaging Method (new) - verified", "Imaging Method (Text) - verified"]) or None
        spectra_col = _select_first_existing(df, ["Light Spectra (Text) (new) - verified", "Light Spectra (Text) - verified"]) or None
        family_col = _select_first_existing(df, ["Family - verified", "family", "Family", "Taxonomy family", "Taxonomic family"]) or None
        country_col = _select_first_existing(df, ["Country - verified", "Country", "Countries", "Country (Text) - verified"]) or None

        if habitat_col is not None:
            mask = (
                df[habitat_col].isna()
                | (df[habitat_col] == "")
                | (df[habitat_col].apply(lambda v: isinstance(v, list) and len(v) == 0))
            )
            df.loc[mask, habitat_col] = pd.Series([["Unknown"] for _ in range(mask.sum())], index=df.index[mask])
            df[habitat_col] = df[habitat_col].apply(map_all_to_first_level)

        if tasks_col is not None:
            df[tasks_col] = df[tasks_col].map(fix_cv_tasks)

        if modality_col is not None:
            df[modality_col] = df[modality_col].apply(unify_imaging_methods)

        if spectra_col is not None:
            df[spectra_col] = df[spectra_col].apply(spectra_unknown_to_other)

        # Derived metrics
        n_species = df[species_col].apply(_safe_len_list) if species_col is not None else 0
        n_modalities = df[modality_col].apply(_safe_len_list) if modality_col is not None else 0
        primary_habitat = df[habitat_col].apply(_first_or_unknown) if habitat_col is not None else "Unknown"
        primary_modality = df[modality_col].apply(_first_or_unknown) if modality_col is not None else "Unknown"
        primary_task = df[tasks_col].apply(_first_or_unknown) if tasks_col is not None else "Unknown"
        if family_col is not None:
            primary_family = df[family_col].apply(_first_or_unknown)
        elif gbif_lookup and species_cols:
            # derive family from species columns via GBIF lookup
            from collections import Counter
            def _derive_family(row):
                fams = []
                for c in species_cols:
                    vals = row.get(c)
                    if isinstance(vals, list):
                        iter_vals = vals
                    elif isinstance(vals, str):
                        iter_vals = [vals]
                    else:
                        iter_vals = []
                    for nm in iter_vals:
                        key = _norm_name(nm)
                        m = gbif_lookup.get(key)
                        fam = (m or {}).get("family")
                        if fam:
                            fams.append(fam)
                if fams:
                    return Counter(fams).most_common(1)[0][0]
                return "Unknown"
            primary_family = df.apply(_derive_family, axis=1)
        else:
            primary_family = "Unknown"

        source_name = os.path.basename(p)

        out = pd.DataFrame({
            "doi": df.get("doi", pd.Series(index=df.index)).apply(_clean_doi) if "doi" in df.columns else None,
            "year": df.get("year", pd.Series(index=df.index)),
            "source": source_name,
            "n_species": n_species,
            "n_modalities": n_modalities,
            "primary_habitat": primary_habitat,
            "primary_modality": primary_modality,
            "primary_task": primary_task,
            "primary_spectra": (df[spectra_col].apply(_first_or_unknown) if spectra_col is not None else "Unknown"),
            "primary_country": (df[country_col].apply(_first_or_unknown) if country_col is not None else "Unknown"),
            "primary_family": primary_family,
        })
        frames.append(out)

    papers = pd.concat(frames, ignore_index=True)
    # Drop duplicate dois if present
    if "doi" in papers.columns:
        papers = papers.drop_duplicates(subset=["doi"], keep="first")
    papers["study_size"] = papers[["n_species", "n_modalities"]].sum(axis=1).clip(lower=1)
    papers["year_bin"] = pd.cut(papers["year"], bins=[2014, 2016, 2018, 2020, 2022, 2024], include_lowest=True, ordered=True)
    return papers

def standardize_for_viz(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    # Ensure 'Year' exists (dashboard default is "Year", case-insensitive, but let's add it)
    if "year" in out.columns and "Year" not in out.columns:
        out["Year"] = out["year"]

    # Map your new names -> canonical single-value columns the UI expects
    if "Imaging Method" in out.columns:
        out["Modality"] = out["Imaging Method"].apply(_first_or_unknown)
    else:
        out["Modality"] = "Unknown"

    if "ParentHabitat" in out.columns:
        out["Habitat"] = out["ParentHabitat"].apply(_first_or_unknown)
    else:
        out["Habitat"] = "Unknown"

    if "CV Tasks" in out.columns:
        out["Task"] = out["CV Tasks"].apply(_first_or_unknown)

    if "Light Spectra" in out.columns:
        out["Spectra"] = out["Light Spectra"].apply(_first_or_unknown)

    if "Country" in out.columns:
        out["Country1"] = out["Country"].apply(_first_or_unknown)  # avoid clobbering if needed

    # Simple metrics your plots use
    out["n_species"]   = out["Species"].apply(lambda x: len(x) if isinstance(x, (list, set, tuple)) else (1 if pd.notna(x) and x != "" else 0)) if "Species" in out.columns else 0
    out["n_modalities"] = out["Imaging Method"].apply(lambda x: len(x) if isinstance(x, (list, set, tuple)) else (1 if pd.notna(x) and x != "" else 0)) if "Imaging Method" in out.columns else 0

    # Family (single)
    if "Family" in out.columns:
        out["Family1"] = out["Family"].apply(_first_or_unknown)

    return out

def load_many(paths: list[str]) -> pd.DataFrame:
    frames = []
    for p in paths:
        df = convert_list_columns_to_sets(pd.read_parquet(p))
        # Year filter
        if "year" in df.columns:
            yr = pd.to_numeric(df["year"], errors="coerce")
            df = df[(yr >= 2014) & (yr <= 2024)].copy()

        # Length metrics (tolerant)
        if "Species" in df.columns:
            df["n_species"] = df["Species"].apply(_safe_len_list)
        else:
            df["n_species"] = 0
        if "Imaging Method" in df.columns:
            df["n_modalities"] = df["Imaging Method"].apply(_safe_len_list)
        else:
            df["n_modalities"] = 0

        # >>> minimal, viz-critical: produce single-value categorical columns
        # map to names the dashboard naturally uses
        if "Imaging Method" in df.columns:
            df["Modality"] = df["Imaging Method"].apply(_first_or_unknown)
        else:
            df["Modality"] = "Unknown"
        if "ParentHabitat values" in df.columns:
            df["Habitat"] = df["ParentHabitat values"].apply(_first_or_unknown)
        else:
            df["Habitat"] = "Unknown"
        if "CV Tasks - verified" in df.columns:
            df["Task"] = df["CV Tasks - verified"].apply(_first_or_unknown)

        frames.append(df)

    papers = pd.concat(frames, ignore_index=True)
    if "doi" in papers.columns and "file" in papers.columns:
        papers = papers.drop_duplicates(subset=["doi", "file"], keep="first")

    papers["study_size"] = papers[["n_species", "n_modalities"]].sum(axis=1).clip(lower=1)
    if "year" in papers.columns:
        papers["year_bin"] = pd.cut(papers["year"], bins=[2014, 2016, 2018, 2020, 2022, 2024],
                                    include_lowest=True, ordered=True)
    return papers

# -------------------------------
# Figure generation
# -------------------------------

def _year_bin_order(papers: pd.DataFrame):
    if "year_bin" not in papers.columns:
        return None
    s = papers["year_bin"]
    try:
        cats = list(s.cat.categories)
        return [str(c) for c in cats]
    except Exception:
        vals = [v for v in s.dropna().unique()]
        try:
            vals.sort(key=lambda iv: getattr(iv, "left", str(iv)))
        except Exception:
            vals = sorted(vals, key=lambda v: str(v))
        return [str(v) for v in vals]


def make_figure(
    papers: pd.DataFrame,
    x_col: str,
    y_col: str,
    color_col: str,
    size_col: str,
    chart: str = "scatter",            # "scatter" or "line"
    show_markers: bool = True,         # only relevant for line charts
    line_shape: str = "linear"         # e.g., "linear", "spline", "vhv", "hvh"
):
    """
    Create a visualization of `papers` as either a scatter plot (default) or a line chart.

    Parameters
    ----------
    papers : pd.DataFrame
    x_col, y_col : str
        Columns used for x and y. Supports special handling for "year" and "year_bin".
    color_col : str
        Column for color grouping (also the line grouping for chart="line").
    size_col : str
        Column for marker size (used only for scatter).
    chart : {"scatter","line"}
        Type of chart to render.
    show_markers : bool
        For chart="line", whether to overlay markers on the line.
    line_shape : str
        Shape of the line (Plotly line_shape option).
    """
    df = papers.copy()

    # Prepare year_bin labels if used
    x_arg = x_col
    y_arg = y_col
    if x_col == "year_bin" and "year_bin" in df:
        df["__year_bin_str__"] = df["year_bin"].astype(str)
        x_arg = "__year_bin_str__"
    if y_col == "year_bin" and "year_bin" in df:
        df["__year_bin_str_y__"] = df["year_bin"].astype(str)
        y_arg = "__year_bin_str_y__"

    # Sort by x within color groups for sensible line connections
    if x_col == "year" and "year" in df.columns:
        if color_col in df.columns:
            df = df.sort_values([color_col, "year"], kind="mergesort")
        else:
            df = df.sort_values(["year"], kind="mergesort")
    elif x_arg == "__year_bin_str__":
        # map to category order index for stable sorting
        yb_order = _year_bin_order(papers) or []
        order_map = {v: i for i, v in enumerate(yb_order)}
        df["__yb_sort__"] = df["__year_bin_str__"].map(lambda v: order_map.get(v, 1_000_000))
        if color_col in df.columns:
            df = df.sort_values([color_col, "__yb_sort__"], kind="mergesort")
        else:
            df = df.sort_values(["__yb_sort__"], kind="mergesort")

    # Size safeguard (used for scatter)
    df["__size_safe__"] = pd.to_numeric(df[size_col], errors="coerce").fillna(1).clip(lower=1)

    # Shared hover + labels
    hover = {
        "doi": True, "year": True, "source": True,
        "primary_habitat": True, "primary_modality": True, "primary_task": True
    }
    labels = {
        "year": "Year",
        "year_bin": "Year (binned)",
        "__year_bin_str__": "Year (binned)",
        "__year_bin_str_y__": "Year (binned)",
        "n_species": "# Species",
        "n_modalities": "# Modalities",
        "study_size": "Study size",
    }

    color_arg = color_col if color_col in df.columns else None

    if chart == "line":
        # Line chart (grouping by color)
        fig = px.line(
            df,
            x=x_arg,
            y=y_arg,
            color=color_arg,
            hover_data=hover,
            labels=labels,
            line_shape=line_shape,
            markers=show_markers,
            color_discrete_map=colors
        )
        # Optional: set a uniform marker size for visibility on line charts.
        # fig.update_traces(marker=dict(size=6))
    else:
        # Default: scatter chart (uses size)
        fig = px.scatter(
            df,
            x=x_arg,
            y=y_arg,
            color=color_arg,
            size="__size_safe__",
            hover_data=hover,
            labels=labels,
            opacity=0.85,
        )
        fig.update_traces(marker=dict(line=dict(width=0)))

    # Enforce sorted category order for year_bin axes
    yb_order = _year_bin_order(papers)
    if x_col == "year_bin" and yb_order is not None:
        fig.update_xaxes(categoryorder="array", categoryarray=yb_order)
    if y_col == "year_bin" and yb_order is not None:
        fig.update_yaxes(categoryorder="array", categoryarray=yb_order)

    fig.update_layout(
        height=680,
        legend_title_text="",
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig


# -------------------------------
# Optional: ipywidgets explorer for notebooks
# -------------------------------

def widgets_explorer(papers: pd.DataFrame):
    try:
        from ipywidgets import Dropdown, HBox, Output
        from IPython.display import display
    except Exception as e:
        raise RuntimeError("ipywidgets is required for widgets_explorer()") from e

    axis_options = {
        "Year": "year",
        "Year (binned)": "year_bin",
        "# Species": "n_species",
        "# Modalities": "n_modalities",
        "Study size (#species + #modalities)": "study_size",
        "Papers count (by group)": "papers_count",
        "Country": "primary_country",
        "Modality": "primary_modality",
        "Spectra": "primary_spectra",
        "Family": "primary_family",
        "Task": "primary_task",
        "Habitat": "primary_habitat",
    }
    color_options = {
        "Source": "source",
        "Habitat": "primary_habitat",
        "Modality": "primary_modality",
        "Task": "primary_task",
        "Spectra": "primary_spectra",
        "Country": "primary_country",
        "Family": "primary_family",
    }
    size_options = {
        "Study size": "study_size",
        "# Species": "n_species",
        "# Modalities": "n_modalities",
    }

    x_dd = Dropdown(options=list(axis_options.keys()), value="Year", description="X")
    y_dd = Dropdown(options=list(axis_options.keys()), value="# Species", description="Y")
    color_dd = Dropdown(options=list(color_options.keys()), value="Habitat", description="Color")
    size_dd = Dropdown(options=list(size_options.keys()), value="Study size", description="Size")
    group_dd = Dropdown(options=["None", "Habitat", "Modality", "Spectra", "Country", "Family", "Year (binned)", "Task"], value="None", description="Group By")
    viz_dd = Dropdown(options=["Scatter", "Stacked bar", "Line chart", "Line Chart (relative)"], value="Scatter", description="Chart")
    connect_cb = Dropdown(options=["Off", "Lines per color"], value="Off", description="Connect")
    box = HBox([x_dd, y_dd, color_dd, size_dd, group_dd, viz_dd, connect_cb])
    out = Output()

    def _make_agg_df(group_label: str, x_sel: str, y_sel: str):
        label_to_col = {
            "Habitat": "primary_habitat",
            "Modality": "primary_modality",
            "Spectra": "primary_spectra",
            "Country": "primary_country",
            "Family": "primary_family",
            "Year (binned)": "year_bin",
            "Task": "primary_task",
        }
        col = label_to_col.get(group_label)
        if col is None:
            return None, None, None, None
        df = papers.copy()
        key = col
        # ensure year ordering data
        ord_list = None
        if col == "year_bin":
            ord_list = _year_bin_order(df)
            df["__yb_str_grp__"] = df["year_bin"].astype(str)
            key = "__yb_str_grp__"

        # detect time axis in selections
        time_axis = None
        time_key = None
        if x_sel in ("year", "year_bin"):
            time_axis = x_sel
        if y_sel in ("year", "year_bin") and time_axis is None:
            time_axis = y_sel

        if time_axis == "year":
            # numeric year
            df = df[df["year"].notna()].copy()
            agg = df.groupby([key, "year"], dropna=False).size().reset_index(name="papers_count")
            time_key = "year"
        elif time_axis == "year_bin":
            df["__yb_str_ax__"] = df["year_bin"].astype(str)
            agg = df.groupby([key, "__yb_str_ax__"], dropna=False).size().reset_index(name="papers_count")
            time_key = "__yb_str_ax__"
            ord_list = _year_bin_order(papers)
            if ord_list is not None:
                agg[time_key] = pd.Categorical(agg[time_key], categories=ord_list, ordered=True)
                agg = agg.sort_values(time_key)
        else:
            agg = df.groupby(key, dropna=False).size().reset_index(name="papers_count")

        # apply order to grouping key if it's year_bin
        if col == "year_bin" and ord_list is not None:
            agg[key] = pd.Categorical(agg[key], categories=ord_list, ordered=True)
            agg = agg.sort_values(key)

        return agg, key, time_key, ord_list

    # add once near the top of the function (after imports)
    EXPORT_CONFIG = {
        "toImageButtonOptions": {
            "format": "svg",  # use "svg" if you prefer SVG
            "filename": "plot",
            "height": 600,
            "width": 1400,
            "scale": 1,
        }
    }

    def render(*_):
        with out:
            out.clear_output(wait=True)

            group_label = group_dd.value
            x_sel = axis_options[x_dd.value]
            y_sel = axis_options[y_dd.value]

            # Normalize viz selector to avoid string mismatches
            viz = (viz_dd.value or "").strip().lower()

            # Decide whether to use aggregated data
            use_agg = (group_label != "None") or (x_sel == "papers_count") or (y_sel == "papers_count")

            if use_agg:
                # Build aggregated frame
                agg_df, key, time_key, ord_list = _make_agg_df(
                    group_label if group_label != "None" else "Habitat", x_sel, y_sel
                )

                if viz in ("stacked bar", "stacked bar chart", "stacked"):
                    # choose x axis: prefer time axis if available, else the group key
                    x_axis = time_key or key
                    if x_axis is None:
                        # fallback to Habitat grouping
                        agg_df, key, time_key, ord_list = _make_agg_df("Habitat", x_sel, y_sel)
                        x_axis = time_key or key
                    piv = agg_df.pivot_table(
                        index=x_axis, columns=key, values="papers_count",
                        aggfunc="sum", fill_value=0
                    ).sort_index()

                    fig = px.bar(
                        piv.reset_index(),
                        x=x_axis,
                        y=list(piv.columns),
                        barmode="stack",
                        labels={
                            "value": "Papers count",
                            "variable": (group_label if group_label != "None" else "Group"),
                            x_axis: x_axis,
                        },
                    )

                    # Enforce year_bin order on x if relevant
                    ord_apply = ord_list or _year_bin_order(papers)
                    if ord_apply is not None and x_axis in ("__yb_str_ax__", "__yb_str_grp__"):
                        fig.update_xaxes(categoryorder="array", categoryarray=ord_apply)

                elif viz in ("line chart", "line", "linechart"):
                    # Absolute counts over x by color
                    x_arg = time_key or key
                    if x_arg is None:
                        agg_df, key, time_key, ord_list = _make_agg_df("Habitat", x_sel, y_sel)
                        x_arg = time_key or key

                    # Stable sort: by color then x
                    sort_cols = ([key] if key is not None else []) + ([x_arg] if x_arg is not None else [])
                    if sort_cols:
                        agg_df = agg_df.sort_values(sort_cols, kind="mergesort")

                    fig = px.line(
                        agg_df,
                        x=x_arg,
                        y="papers_count",
                        color=key,
                        markers=(connect_cb.value == "Lines per color"),
                        labels={
                            key: group_label if group_label != "None" else "Group",
                            "papers_count": "Entries",
                            x_arg: x_arg,
                        },
                    )

                    # year_bin order
                    ord_apply = ord_list or _year_bin_order(papers)
                    if ord_apply is not None and x_arg in ("__yb_str_ax__", "__yb_str_grp__"):
                        fig.update_xaxes(categoryorder="array", categoryarray=ord_apply)

                elif viz in ("line chart (relative)", "relative line chart", "line (relative)"):
                    # PER-CATEGORY normalization across all x (your requested behavior)
                    x_arg = time_key or key
                    if x_arg is None:
                        agg_df, key, time_key, ord_list = _make_agg_df("Habitat", x_sel, y_sel)
                        x_arg = time_key or key

                    df_rel = agg_df.copy()

                    # Each category's count at x divided by that category's total across all x
                    totals = df_rel.groupby(key, dropna=False)["papers_count"].transform("sum")
                    df_rel["portion"] = df_rel["papers_count"] / totals.replace(0, pd.NA)

                    # Stable sort
                    sort_cols = ([key] if key is not None else []) + ([x_arg] if x_arg is not None else [])
                    if sort_cols:
                        df_rel = df_rel.sort_values(sort_cols, kind="mergesort")

                    fig = px.line(
                        df_rel,
                        x=x_arg,
                        y="portion",
                        color=key,
                        markers=(connect_cb.value == "Lines per color"),
                        labels={
                            key: group_label if group_label != "None" else "Group",
                            "portion": "Share within category",
                            x_arg: x_arg,
                        },
                    )
                    fig.update_yaxes(tickformat=".0%")

                    # year_bin order
                    ord_apply = ord_list or _year_bin_order(papers)
                    if ord_apply is not None and x_arg in ("__yb_str_ax__", "__yb_str_grp__"):
                        fig.update_xaxes(categoryorder="array", categoryarray=ord_apply)

                else:
                    # Aggregated scatter (original behavior)
                    def map_axis(sel):
                        if sel == "papers_count":
                            return "papers_count"
                        if sel in ("year", "year_bin") and time_key is not None:
                            return time_key
                        return key

                    x_arg = map_axis(x_sel)
                    y_arg = map_axis(y_sel)
                    if x_arg == y_arg == key:
                        y_arg = "papers_count"

                    fig = px.scatter(
                        agg_df,
                        x=x_arg,
                        y=y_arg,
                        color=key,
                        size="papers_count",
                        hover_data={key: True, "papers_count": True},
                        labels={
                            key: group_label if group_label != "None" else "Group",
                            "papers_count": "Papers count",
                        },
                        opacity=0.9,
                    )

                    # Optional connecting lines per group along x
                    if connect_cb.value == "Lines per color" and x_arg in ("year", "__yb_str_ax__"):
                        for cat, sub in agg_df.groupby(key, sort=False):
                            fig.add_traces(
                                px.line(
                                    sub.sort_values(x_arg, kind="mergesort"),
                                    x=x_arg, y=y_arg
                                ).update_traces(showlegend=False).data
                            )

                    # Enforce year_bin order if relevant
                    if (group_label == "Year (binned)" and ord_list is not None) or (time_key in ("__yb_str_ax__",)):
                        ord_apply = ord_list or _year_bin_order(papers)
                        if ord_apply is not None:
                            if x_arg in ("__yb_str_ax__", "__yb_str_grp__"):
                                fig.update_xaxes(categoryorder="array", categoryarray=ord_apply)
                            if y_arg in ("__yb_str_ax__", "__yb_str_grp__"):
                                fig.update_yaxes(categoryorder="array", categoryarray=ord_apply)

            else:
                # RAW (non-aggregated) data
                if viz in ("line chart", "line", "linechart"):
                    # Absolute counts per (color, x)
                    dfp = papers.copy()
                    color_col = color_options[color_dd.value]

                    x_arg = x_sel
                    if x_sel == "year_bin" and "year_bin" in dfp:
                        yb = _year_bin_order(dfp) or []
                        dfp["__yb_str__"] = dfp["year_bin"].astype(str)
                        x_arg = "__yb_str__"
                        order_map = {v: i for i, v in enumerate(yb)}
                        dfp["__yb_sort__"] = dfp["__yb_str__"].map(lambda v: order_map.get(v, 1_000_000))

                    counts = (
                        dfp.groupby([color_col, x_arg], dropna=False, sort=False)
                        .size()
                        .reset_index(name="entries")
                    )

                    # Stable sort within color by x
                    if x_sel == "year":
                        counts = counts.sort_values([color_col, x_arg], kind="mergesort")
                    elif x_sel == "year_bin":
                        counts = counts.merge(
                            dfp[[x_arg, "__yb_sort__"]].drop_duplicates(), on=x_arg, how="left"
                        ).sort_values([color_col, "__yb_sort__"], kind="mergesort")

                    fig = px.line(
                        counts,
                        x=x_arg,
                        y="entries",
                        color=color_col,
                        markers=(connect_cb.value == "Lines per color"),
                        labels={color_col: color_dd.value, "entries": "Entries"},
                    )

                    # year_bin order
                    if x_sel == "year_bin":
                        ord_apply = _year_bin_order(papers)
                        if ord_apply is not None:
                            fig.update_xaxes(categoryorder="array", categoryarray=ord_apply)

                elif viz in ("line chart (relative)", "relative line chart", "line (relative)"):
                    # PER-CATEGORY normalization across all x (raw)
                    dfp = papers.copy()
                    color_col = color_options[color_dd.value]

                    x_arg = x_sel
                    if x_sel == "year_bin" and "year_bin" in dfp:
                        yb = _year_bin_order(dfp) or []
                        dfp["__yb_str__"] = dfp["year_bin"].astype(str)
                        x_arg = "__yb_str__"
                        order_map = {v: i for i, v in enumerate(yb)}
                        dfp["__yb_sort__"] = dfp["__yb_str__"].map(lambda v: order_map.get(v, 1_000_000))

                    # counts per (color, x)
                    counts = (
                        dfp.groupby([color_col, x_arg], dropna=False, sort=False)
                        .size()
                        .reset_index(name="entries")
                    )

                    # Portion within each color across all x
                    totals = counts.groupby(color_col, dropna=False)["entries"].transform("sum")
                    counts["portion"] = counts["entries"] / totals.replace(0, pd.NA)

                    # sort by color then x
                    if x_sel == "year":
                        counts = counts.sort_values([color_col, x_arg], kind="mergesort")
                    elif x_sel == "year_bin":
                        counts = counts.merge(
                            dfp[[x_arg, "__yb_sort__"]].drop_duplicates(), on=x_arg, how="left"
                        ).sort_values([color_col, "__yb_sort__"], kind="mergesort")

                    fig = px.line(
                        counts,
                        x=x_arg,
                        y="portion",
                        color=color_col,
                        markers=(connect_cb.value == "Lines per color"),
                        labels={color_col: color_dd.value, "portion": "Share within category"},
                    )
                    fig.update_yaxes(tickformat=".0%")

                    # year_bin order
                    if x_sel == "year_bin":
                        ord_apply = _year_bin_order(papers)
                        if ord_apply is not None:
                            fig.update_xaxes(categoryorder="array", categoryarray=ord_apply)

                else:
                    # Default scatter via make_figure (original behavior)
                    fig = make_figure(
                        papers,
                        x_sel,
                        y_sel,
                        color_options[color_dd.value],
                        size_options[size_dd.value],
                    )

                    # Optional connecting lines in scatter mode
                    if connect_cb.value == "Lines per color" and x_sel in ("year", "year_bin"):
                        dfp = papers.copy()
                        x_arg = x_sel
                        if x_sel == "year_bin":
                            yb = _year_bin_order(dfp) or []
                            dfp["__yb_str__"] = dfp["year_bin"].astype(str)
                            x_arg = "__yb_str__"
                            order_map = {v: i for i, v in enumerate(yb)}
                            dfp["__yb_sort__"] = dfp["__yb_str__"].map(lambda v: order_map.get(v, 1_000_000))

                        color_col = color_options[color_dd.value]
                        if x_sel == "year":
                            dfp = dfp.sort_values([color_col, "year"], kind="mergesort")
                        else:
                            dfp = dfp.sort_values([color_col, "__yb_sort__"], kind="mergesort")
                        for _, sub in dfp.groupby(color_col, sort=False):
                            fig.add_traces(
                                px.line(sub, x=x_arg, y=y_sel).update_traces(showlegend=False).data
                            )

            fig.update_layout(
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="center",
                    x=0.5
                ),
                legend_title_text=None
            )
            pio.show(fig, config=EXPORT_CONFIG)

    # Reconnect observers and render once
    for w in [x_dd, y_dd, color_dd, size_dd, group_dd, viz_dd, connect_cb]:
        w.observe(render, names="value")

    display(box)
    render()
    display(out)

# Notebook/interactive usage only. Optional: if run as a script, display a minimal widget if possible.
if __name__ == "__main__":
    try:
        from IPython import get_ipython
        if get_ipython() is None:
            print("This module is intended for use in Jupyter notebooks. Import and call widgets_explorer().")
        else:
            print("Load or build your DataFrame with load_and_prepare_many([...]) and call widgets_explorer(papers).")
    except Exception:
        print("Import this module in a Jupyter notebook and call widgets_explorer().")
