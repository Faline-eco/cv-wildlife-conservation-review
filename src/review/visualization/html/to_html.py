from review.visualization.gapminder.gapminder_explorer import load_many

"""
Paper DataFrame Merger and HTML Overview Generator

This script takes two pandas DataFrames about papers, merges them based on DOI,
and generates an interactive HTML page with filtering capabilities including
list-based filtering, full boolean filter support (AND, OR, NOT, groups),
count filters for lists, multi-value "in" filters, and a diagrams view
with custom comparison charts and distribution bar charts.
"""

import pandas as pd
import numpy as np
import json
import html
from typing import List, Optional, Any
from pathlib import Path


def normalize_value(val: Any) -> Any:
    """Normalize a value for consistent handling."""
    if isinstance(val, (list, tuple, np.ndarray)):
        return list(val)
    try:
        if pd.isna(val):
            return None
    except (ValueError, TypeError):
        pass
    if isinstance(val, str):
        val = val.strip()
        if val.startswith('[') and val.endswith(']'):
            try:
                parsed = eval(val)
                if isinstance(parsed, (list, tuple)):
                    return list(parsed)
            except:
                pass
    return val


def merge_values(val1: Any, val2: Any) -> Any:
    """Merge two values, preferring non-null values."""
    v1 = normalize_value(val1)
    v2 = normalize_value(val2)

    if v1 is None:
        return v2
    if v2 is None:
        return v1

    if isinstance(v1, list) and isinstance(v2, list):
        combined = list(v1)
        for item in v2:
            if item not in combined:
                combined.append(item)
        return combined

    return v1


def fill_missing_dois(df: pd.DataFrame, doi_col: str, file_col: str = 'file') -> pd.DataFrame:
    df = df.copy()
    if file_col in df.columns:
        mask = df[doi_col].isna() | (df[doi_col] == '')
        df.loc[mask, doi_col] = df.loc[mask, file_col].apply(
            lambda f: f"no-doi ({f})" if pd.notna(f) else "no-doi (unknown)"
        )
    return df


def merge_dataframes(
        df1: pd.DataFrame,
        df2: pd.DataFrame,
        columns1: List[str],
        columns2: List[str],
        doi_col1: str = 'doi',
        doi_col2: str = 'doi',
        file_col1: str = 'file',
        file_col2: str = 'file'
) -> pd.DataFrame:
    df1 = fill_missing_dois(df1, doi_col1, file_col1)
    df2 = fill_missing_dois(df2, doi_col2, file_col2)

    df1_doi_counts = df1[doi_col1].value_counts()
    df1_duplicates = df1_doi_counts[df1_doi_counts > 1]
    if len(df1_duplicates) > 0:
        print(
            f"df1: {len(df1_duplicates)} DOIs with duplicates ({df1_duplicates.sum() - len(df1_duplicates)} extra rows)")
        for doi, count in df1_duplicates.items():
            print(f"  - {doi}: {count} occurrences")

    df2_doi_counts = df2[doi_col2].value_counts()
    df2_duplicates = df2_doi_counts[df2_doi_counts > 1]
    if len(df2_duplicates) > 0:
        print(
            f"df2: {len(df2_duplicates)} DOIs with duplicates ({df2_duplicates.sum() - len(df2_duplicates)} extra rows)")
        for doi, count in df2_duplicates.items():
            print(f"  - {doi}: {count} occurrences")

    col_mapping = dict(zip(columns2, columns1))
    df2_renamed = df2.rename(columns=col_mapping)

    def get_composite_key(row, doi_col, file_col):
        doi = row[doi_col] if pd.notna(row[doi_col]) else ''
        file = row[file_col] if file_col in row.index and pd.notna(row[file_col]) else ''
        return (doi, file)

    df1_keys = set(df1.apply(lambda r: get_composite_key(r, doi_col1, file_col1), axis=1))
    df2_keys = set(df2_renamed.apply(lambda r: get_composite_key(r, doi_col1, file_col1), axis=1))
    all_keys = df1_keys | df2_keys

    all_columns = [doi_col1] + [col for col in columns1 if col != doi_col1]
    merged_data = []

    for (doi, file) in all_keys:
        row_data = {doi_col1: doi}
        mask1 = (df1[doi_col1] == doi) & (df1[file_col1] == file if file_col1 in df1.columns else True)
        mask2 = (df2_renamed[doi_col1] == doi) & (
            df2_renamed[file_col1] == file if file_col1 in df2_renamed.columns else True)
        rows1 = df1[mask1]
        rows2 = df2_renamed[mask2]

        for col in all_columns:
            if col == doi_col1:
                continue
            val1 = None
            val2 = None
            if col in df1.columns and len(rows1) > 0:
                val1 = rows1[col].iloc[0]
            if col in df2_renamed.columns and len(rows2) > 0:
                val2 = rows2[col].iloc[0]
            row_data[col] = merge_values(val1, val2)

        merged_data.append(row_data)

    return pd.DataFrame(merged_data, columns=all_columns)


def detect_list_columns(df: pd.DataFrame) -> List[str]:
    list_columns = []
    for col in df.columns:
        for val in df[col].dropna():
            if isinstance(val, list):
                list_columns.append(col)
                break
    return list_columns


def get_unique_list_values(df: pd.DataFrame, col: str) -> List[str]:
    unique_values = set()
    for val in df[col].dropna():
        if isinstance(val, list):
            for item in val:
                if item is not None and str(item).strip():
                    unique_values.add(str(item))
        elif val is not None and str(val).strip():
            unique_values.add(str(val))
    return sorted(unique_values)


def has_empty_values(df: pd.DataFrame, col: str) -> bool:
    for val in df[col]:
        if val is None:
            return True
        if isinstance(val, float) and pd.isna(val):
            return True
        if isinstance(val, list) and len(val) == 0:
            return True
    return False


def format_cell_value(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return '<span class="empty">—</span>'
    if isinstance(val, list):
        if len(val) == 0:
            return '<span class="empty">—</span>'
        items = [f'<span class="list-item">{html.escape(str(v))}</span>' for v in val if v is not None]
        return '<div class="list-cell">' + ''.join(items) + '</div>'
    return html.escape(str(val))


def generate_html(
        df: pd.DataFrame,
        output_path: str,
        title: str = "Paper Overview",
        year_column: str = "year"
) -> None:
    list_columns = detect_list_columns(df)

    filter_options = {}
    columns_with_empty = {}
    for col in df.columns:
        if col in list_columns:
            filter_options[col] = get_unique_list_values(df, col)
        else:
            unique_vals = df[col].dropna().unique()
            filter_options[col] = sorted([str(v) for v in unique_vals if str(v).strip()])
        columns_with_empty[col] = has_empty_values(df, col)

    data_for_js = []
    for _, row in df.iterrows():
        row_dict = {}
        for col in df.columns:
            val = row[col]
            if pd.isna(val) if not isinstance(val, list) else False:
                row_dict[col] = None
            elif isinstance(val, list):
                row_dict[col] = [str(v) for v in val if v is not None]
            else:
                row_dict[col] = str(val)
        data_for_js.append(row_dict)

    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2"></script>
    <style>
        * {{ box-sizing: border-box; }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
            color: #333;
        }}

        h1 {{ margin: 0 0 20px 0; color: #2c3e50; }}

        .stats {{
            background: #fff;
            padding: 15px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
        }}

        .stats span {{ font-weight: bold; color: #3498db; }}

        .view-toggle {{
            display: flex;
            border-radius: 4px;
            overflow: hidden;
            border: 1px solid #ddd;
        }}

        .view-toggle button {{
            padding: 8px 16px;
            border: none;
            background: #f0f0f0;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
        }}

        .view-toggle button.active {{
            background: #3498db;
            color: white;
        }}

        .controls {{
            background: #fff;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        .controls h3 {{ margin: 0 0 15px 0; color: #2c3e50; }}

        .filter-builder {{
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 15px;
            background: #fafafa;
        }}

        .filter-group {{
            border: 2px solid #3498db;
            border-radius: 8px;
            padding: 12px;
            margin: 8px 0;
            background: white;
        }}

        .filter-group.or-group {{ border-color: #9b59b6; }}

        .filter-group-header {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
            flex-wrap: wrap;
        }}

        .operator-toggle {{
            display: flex;
            border-radius: 4px;
            overflow: hidden;
            border: 1px solid #ddd;
        }}

        .operator-toggle button {{
            padding: 6px 12px;
            border: none;
            background: #f0f0f0;
            cursor: pointer;
            font-size: 12px;
            font-weight: bold;
        }}

        .operator-toggle button.active {{ background: #3498db; color: white; }}
        .operator-toggle button.active.or {{ background: #9b59b6; }}

        .filter-group-actions {{
            display: flex;
            gap: 5px;
            margin-left: auto;
        }}

        .filter-group-actions button {{
            padding: 4px 8px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 11px;
        }}

        .btn-add-condition {{ background: #27ae60; color: white; }}
        .btn-add-group {{ background: #3498db; color: white; }}
        .btn-remove-group {{ background: #e74c3c; color: white; }}

        .filter-condition {{
            display: flex;
            align-items: flex-start;
            gap: 8px;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 4px;
            margin: 6px 0;
            flex-wrap: wrap;
        }}

        .filter-condition.negated {{
            background: #fdf2f2;
            border-left: 3px solid #e74c3c;
        }}

        .filter-condition select, .filter-condition input[type="text"], .filter-condition input[type="number"] {{
            padding: 6px 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 13px;
        }}

        .filter-condition select {{ min-width: 120px; }}
        .filter-condition input[type="text"] {{ min-width: 120px; }}
        .filter-condition input[type="number"] {{ width: 80px; }}

        .filter-condition .btn-remove {{
            padding: 4px 8px;
            background: #e74c3c;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
        }}

        .filter-condition .option-count {{
            font-size: 11px;
            color: #888;
            min-width: 70px;
        }}

        .operator-label {{
            font-size: 11px;
            font-weight: bold;
            color: #3498db;
            padding: 2px 8px;
            background: #e8f4f8;
            border-radius: 10px;
            margin: 4px 0;
            display: inline-block;
        }}

        .operator-label.or {{ color: #9b59b6; background: #f3e8f8; }}

        .filter-actions {{
            margin-top: 15px;
            display: flex;
            gap: 10px;
        }}

        .filter-actions button {{
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
        }}

        .btn-apply {{ background: #27ae60; color: white; }}
        .btn-clear {{ background: #95a5a6; color: white; }}

        .filter-summary {{
            margin-top: 15px;
            padding: 10px;
            background: #e8f4f8;
            border-radius: 4px;
            font-family: monospace;
            font-size: 13px;
            word-break: break-all;
        }}

        .filter-summary.empty {{
            color: #888;
            font-style: italic;
            font-family: inherit;
        }}

        .nested-group {{
            margin-left: 20px;
            border-left: 3px solid #ddd;
            padding-left: 15px;
        }}

        .not-toggle {{
            display: flex;
            align-items: center;
            gap: 4px;
            padding: 4px 8px;
            background: #f0f0f0;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
            cursor: pointer;
            user-select: none;
        }}

        .not-toggle:hover {{ background: #e0e0e0; }}
        .not-toggle.active {{ background: #e74c3c; color: white; }}
        .not-toggle input {{ margin: 0; cursor: pointer; }}

        .multi-value-container {{
            display: flex;
            flex-direction: column;
            gap: 5px;
            max-width: 300px;
        }}

        .multi-value-search {{ width: 100%; }}

        .multi-value-list {{
            max-height: 150px;
            overflow-y: auto;
            border: 1px solid #ddd;
            border-radius: 4px;
            background: white;
        }}

        .multi-value-item {{
            display: flex;
            align-items: center;
            padding: 4px 8px;
            cursor: pointer;
            font-size: 12px;
        }}

        .multi-value-item:hover {{ background: #f0f0f0; }}
        .multi-value-item.selected {{ background: #e8f4f8; }}
        .multi-value-item input {{ margin-right: 6px; }}

        .selected-values {{
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            margin-top: 5px;
        }}

        .selected-tag {{
            background: #3498db;
            color: white;
            padding: 2px 6px;
            border-radius: 10px;
            font-size: 11px;
            display: flex;
            align-items: center;
            gap: 4px;
        }}

        .selected-tag .remove {{ cursor: pointer; font-weight: bold; }}

        .filter-type-row {{
            display: flex;
            align-items: center;
            gap: 8px;
            width: 100%;
            margin-bottom: 8px;
        }}

        .count-inputs {{
            display: flex;
            align-items: center;
            gap: 5px;
        }}

        .column-toggle {{
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #eee;
        }}

        .column-toggle summary {{
            cursor: pointer;
            font-weight: bold;
            color: #2c3e50;
        }}

        .column-checkboxes {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 10px;
            max-height: 200px;
            overflow-y: auto;
        }}

        .column-checkboxes label {{
            display: flex;
            align-items: center;
            gap: 5px;
            font-size: 13px;
            white-space: nowrap;
        }}

        .table-container {{
            background: #fff;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow: hidden;
        }}

        .table-scroll {{
            overflow-x: auto;
            max-height: 70vh;
            overflow-y: auto;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }}

        th {{
            background: #2c3e50;
            color: white;
            padding: 12px 10px;
            text-align: left;
            position: sticky;
            top: 0;
            z-index: 10;
            white-space: nowrap;
        }}

        th.sortable {{ cursor: pointer; }}
        th.sortable:hover {{ background: #34495e; }}
        th .sort-indicator {{ margin-left: 5px; }}

        td {{
            padding: 10px;
            border-bottom: 1px solid #eee;
            vertical-align: top;
            max-width: 300px;
        }}

        tr:hover {{ background: #f8f9fa; }}

        .empty {{ color: #aaa; }}

        .list-cell {{
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
        }}

        .list-item {{
            background: #e8f4f8;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 12px;
            display: inline-block;
        }}

        .doi-link {{ color: #3498db; text-decoration: none; }}
        .doi-link:hover {{ text-decoration: underline; }}

        .hidden {{ display: none !important; }}
        .empty-option {{ font-style: italic; color: #888; }}

        /* Diagrams View Styles */
        .diagrams-container {{
            display: none;
        }}

        .diagrams-container.active {{
            display: block;
        }}

        .chart-section {{
            background: #fff;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            padding: 20px;
            margin-bottom: 20px;
        }}

        .chart-section h3 {{
            margin: 0 0 15px 0;
            color: #2c3e50;
        }}

        .chart-wrapper {{
            position: relative;
            height: 300px;
            width: 100%;
        }}

        .chart-wrapper.distribution-chart {{
            height: auto;
            min-height: 400px;
        }}

        .custom-chart-builder {{
            display: flex;
            flex-direction: column;
            gap: 15px;
        }}

        .chart-config {{
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            align-items: flex-start;
        }}

        .chart-config-section {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}

        .chart-config-section label {{
            font-weight: 500;
            color: #2c3e50;
            font-size: 13px;
        }}

        .chart-config-section select, .chart-config-section input {{
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
            min-width: 150px;
        }}

        .chart-values-selector {{
            flex: 1;
            min-width: 300px;
        }}

        .chart-values-list {{
            max-height: 200px;
            overflow-y: auto;
            border: 1px solid #ddd;
            border-radius: 4px;
            background: white;
        }}

        .chart-value-item {{
            display: flex;
            align-items: center;
            padding: 6px 10px;
            cursor: pointer;
            font-size: 13px;
            border-bottom: 1px solid #f0f0f0;
        }}

        .chart-value-item:last-child {{
            border-bottom: none;
        }}

        .chart-value-item:hover {{
            background: #f8f9fa;
        }}

        .chart-value-item.selected {{
            background: #e8f4f8;
        }}

        .chart-value-item input {{
            margin-right: 8px;
        }}

        .chart-value-item .color-indicator {{
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 8px;
        }}

        .selected-chart-values {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-top: 10px;
        }}

        .chart-value-tag {{
            padding: 4px 10px;
            border-radius: 15px;
            font-size: 12px;
            color: white;
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        .chart-value-tag .remove {{
            cursor: pointer;
            font-weight: bold;
            opacity: 0.8;
        }}

        .chart-value-tag .remove:hover {{
            opacity: 1;
        }}

        .chart-search {{
            width: 100%;
            padding: 8px 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 13px;
            margin-bottom: 8px;
        }}

        .topn-config {{
            display: flex;
            gap: 8px;
            align-items: center;
        }}

        .topn-config input {{
            width: 70px;
            padding: 6px 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 13px;
        }}

        .topn-config button {{
            padding: 6px 12px;
            font-size: 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            background: #3498db;
            color: white;
            cursor: pointer;
            white-space: nowrap;
        }}

        .topn-config button:hover {{
            background: #2980b9;
        }}

        .chart-mode-tabs {{
            display: flex;
            border-bottom: 2px solid #e0e0e0;
            margin-bottom: 15px;
        }}

        .chart-mode-tab {{
            padding: 10px 20px;
            border: none;
            background: transparent;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            color: #666;
            border-bottom: 2px solid transparent;
            margin-bottom: -2px;
            transition: all 0.2s;
        }}

        .chart-mode-tab:hover {{
            color: #3498db;
        }}

        .chart-mode-tab.active {{
            color: #3498db;
            border-bottom-color: #3498db;
        }}

        .chart-mode-content {{
            padding: 15px 0;
        }}

        .chart-mode-content.hidden {{
            display: none;
        }}

        .topn-simple {{
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 14px;
        }}

        .topn-simple input {{
            width: 70px;
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
            text-align: center;
        }}

        .topn-simple label {{
            font-weight: 500;
            color: #2c3e50;
        }}

        .chart-options-row {{
            display: flex;
            align-items: center;
            gap: 20px;
            margin-bottom: 15px;
            padding: 10px 0;
        }}

        .chart-checkbox {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 14px;
            cursor: pointer;
            user-select: none;
        }}

        .chart-checkbox input {{
            width: 16px;
            height: 16px;
            cursor: pointer;
        }}

        .mode-toggle {{
            display: flex;
            border-radius: 4px;
            overflow: hidden;
            border: 1px solid #ddd;
        }}

        .mode-toggle button {{
            padding: 6px 12px;
            border: none;
            background: #f0f0f0;
            cursor: pointer;
            font-size: 12px;
            font-weight: 500;
        }}

        .mode-toggle button.active {{
            background: #3498db;
            color: white;
        }}

        .chart-config-row {{
            display: flex;
            gap: 15px;
            align-items: flex-end;
            flex-wrap: wrap;
        }}

        .distribution-canvas-wrapper {{
            width: 100%;
            overflow-x: auto;
        }}

        /* Stacked Bar Chart Styles */
        .stacked-config {{
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }}

        .stacked-column-config {{
            flex: 1;
            min-width: 280px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }}

        .stacked-values-selector {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}

        .stacked-values-selector label {{
            font-weight: 500;
            color: #2c3e50;
            font-size: 13px;
        }}

        .stacked-values-list {{
            max-height: 180px;
            overflow-y: auto;
            border: 1px solid #ddd;
            border-radius: 4px;
            background: white;
        }}

        .stacked-value-item {{
            display: flex;
            align-items: center;
            padding: 5px 10px;
            cursor: pointer;
            font-size: 12px;
            border-bottom: 1px solid #f0f0f0;
        }}

        .stacked-value-item:last-child {{
            border-bottom: none;
        }}

        .stacked-value-item:hover {{
            background: #f8f9fa;
        }}

        .stacked-value-item.selected {{
            background: #e8f4f8;
        }}

        .stacked-value-item input {{
            margin-right: 8px;
        }}

        .stacked-value-item .color-box {{
            width: 14px;
            height: 14px;
            margin-right: 8px;
            border-radius: 2px;
            flex-shrink: 0;
        }}

        .stacked-select-actions {{
            display: flex;
            gap: 8px;
        }}

        .stacked-select-actions button {{
            padding: 4px 10px;
            font-size: 11px;
            border: 1px solid #ddd;
            border-radius: 4px;
            background: #f5f5f5;
            cursor: pointer;
        }}

        .stacked-select-actions button:hover {{
            background: #e8e8e8;
        }}

        .stacked-topn-row {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 8px;
            font-size: 13px;
        }}

        .stacked-topn-row input {{
            width: 60px;
            padding: 5px 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 13px;
            text-align: center;
        }}

        .stacked-topn-row span {{
            color: #666;
        }}

        .stacked-chart-wrapper {{
            height: auto;
            min-height: 450px;
            margin-top: 15px;
        }}

        .stacked-canvas-wrapper {{
            width: 100%;
            overflow-x: auto;
            min-height: 400px;
        }}

        .stacked-legend {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 15px;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 4px;
        }}

        .stacked-legend-item {{
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
        }}

        .stacked-legend-color {{
            width: 16px;
            height: 16px;
            border-radius: 2px;
            flex-shrink: 0;
        }}

        @media (max-width: 768px) {{
            .filter-condition {{ flex-direction: column; align-items: stretch; }}
            .filter-condition select, .filter-condition input {{ width: 100%; }}
            .chart-config {{ flex-direction: column; }}
        }}
    </style>
</head>
<body>
    <h1 style="margin:0px">{html.escape(title)}</h1>
    <h5 style="margin:0px"><a href="https://orcid.org/0000-0002-9711-4818">Christoph Praschl <img width="16px" src="https://orcid.org/assets/vectors/orcid.logo.icon.svg" alt="ORCID Logo"/></a>, <a href="https://orcid.org/0009-0008-0508-8781">Stephanie Wohlfahrt <img width="16px" src="https://orcid.org/assets/vectors/orcid.logo.icon.svg" alt="ORCID Logo"/></a>, <a href="https://orcid.org/0000-0002-4286-6887">Marcus Rowcliffe <img width="16px" src="https://orcid.org/assets/vectors/orcid.logo.icon.svg" alt="ORCID Logo"/></a> and <a href="https://orcid.org/0000-0002-7621-3526">David C. Schedl <img width="16px" src="https://orcid.org/assets/vectors/orcid.logo.icon.svg" alt="ORCID Logo"/></a></h5>
    <h6 style="margin:0px; margin-bottom: 30px;">
    </h6>

    <div class="stats">
        <div>Showing <span id="visible-count">{len(df)}</span> of <span>{len(df)}</span> papers</div>
        <div class="view-toggle">
            <button class="active" onclick="switchView('table')">📊 Table</button>
            <button onclick="switchView('diagrams')">📈 Diagrams</button>
        </div>
    </div>

    <div class="controls">
        <h3>Filters</h3>
        <div class="filter-builder" id="filter-builder"></div>

        <div class="filter-actions">
            <button class="btn-apply" onclick="applyFilters()">Apply Filters</button>
            <button class="btn-clear" onclick="clearAllFilters()">Clear All</button>
        </div>

        <div id="filter-summary" class="filter-summary empty">No filters applied</div>

        <details class="column-toggle">
            <summary>Show/Hide Columns</summary>
            <div class="column-checkboxes" id="column-checkboxes">
                {chr(10).join(f'<label><input type="checkbox" checked onchange="toggleColumn(' + "'" + html.escape(col) + "'" + ')" data-column="' + html.escape(col) + '">' + html.escape(col) + '</label>' for col in df.columns)}
            </div>
        </details>
    </div>

    <!-- Table View -->
    <div class="table-container" id="table-view">
        <div class="table-scroll">
            <table id="papers-table">
                <thead>
                    <tr>
                        {chr(10).join(f'<th class="sortable" data-column="{html.escape(col)}" onclick="sortTable(' + "'" + html.escape(col) + "'" + ')">' + html.escape(col) + '<span class="sort-indicator"></span></th>' for col in df.columns)}
                    </tr>
                </thead>
                <tbody id="table-body"></tbody>
            </table>
        </div>
    </div>

    <!-- Diagrams View -->
    <div class="diagrams-container" id="diagrams-view">
        <!-- Overview Chart -->
        <div class="chart-section">
            <h3>📊 Papers per Year (Overview)</h3>
            <div class="chart-wrapper">
                <canvas id="overview-chart"></canvas>
            </div>
        </div>

        <!-- Distribution Bar Chart -->
        <div class="chart-section">
            <h3>📊 Value Distribution</h3>
            <div class="custom-chart-builder">
                <div class="chart-config-row">
                    <div class="chart-config-section">
                        <label>Select Column</label>
                        <select id="dist-column-select" onchange="updateDistributionChart()">
                            <option value="">Choose a column...</option>
                            {chr(10).join(f'<option value="{html.escape(col)}">{html.escape(col)}</option>' for col in df.columns)}
                        </select>
                    </div>
                    <div class="chart-config-section">
                        <label>Show Top N</label>
                        <input type="number" id="dist-top-n" value="20" min="5" max="100" onchange="updateDistributionChart()">
                    </div>
                    <div class="chart-config-section">
                        <label>Display Mode</label>
                        <div class="mode-toggle">
                            <button class="active" onclick="setDistMode('absolute')">Absolute</button>
                            <button onclick="setDistMode('relative')">Relative (%)</button>
                        </div>
                    </div>
                </div>
                <div class="chart-wrapper distribution-chart">
                    <div class="distribution-canvas-wrapper">
                        <canvas id="distribution-chart"></canvas>
                    </div>
                </div>
            </div>
        </div>

        <!-- Stacked Bar Chart (Cross-tabulation) -->
        <div class="chart-section">
            <h3>📊 Stacked Bar Chart (Cross-tabulation)</h3>
            <div> 
                <h4 style="margin-bottom: 0px">Important Interpretation Note – Multi-Label Linkage Problem:</h4>
                <div style="font-size: 8pt; margin-bottom: 10px;">
                    Many attributes in this review (e.g., CV Tasks, Light Spectra, Species, Habitats, Algorithms) are multi-label fields. This means that a single publication may be associated with multiple values within the same column. When generating cross-tabulations (stacked bar charts), each co-occurrence between an X-axis category and a stacked category is counted independently.As a consequence, stacked segments do not represent mutually exclusive partitions of papers. The sum of stacked segments may exceed the total number of unique papers shown on the X-axis. This effect arises from overlapping assignments within individual studies and reflects the multidimensional nature of ecological computer vision research rather than duplication in the dataset. Therefore, stacked bar charts visualize co-occurrence frequencies, not disjoint subsets of publications. Interpretations should focus on relative structural relationships between categories rather than absolute totals. As a result, depending on what columns you select disjoint information may be also connected, e.g. when a paper focuses on multiple species but in different habitats, the cross tabulation would link every mentioned species with every habitat of the paper.
                </div>
            </div>
            <div class="custom-chart-builder">
                <div class="stacked-config">
                    <div class="stacked-column-config">
                        <div class="chart-config-section">
                            <label>X-Axis Column (Categories)</label>
                            <select id="stacked-x-column" onchange="updateStackedXValues()">
                                <option value="">Choose a column...</option>
                                {chr(10).join(f'<option value="{html.escape(col)}">{html.escape(col)}</option>' for col in df.columns)}
                            </select>
                        </div>
                        <div class="stacked-values-selector">
                            <label>X-Axis Values</label>
                            <div class="stacked-topn-row">
                                <span>Top</span>
                                <input type="number" id="stacked-x-topn" value="" min="1" max="50" placeholder="N" onchange="applyStackedXTopN()">
                                <span>or select manually:</span>
                            </div>
                            <input type="text" class="chart-search" id="stacked-x-search" 
                                placeholder="Search values..." oninput="filterStackedXValues()">
                            <div class="stacked-values-list" id="stacked-x-values-list">
                                <div style="padding: 10px; color: #888;">Select a column first</div>
                            </div>
                            <div class="stacked-select-actions">
                                <button onclick="selectAllStackedX()">Select All</button>
                                <button onclick="deselectAllStackedX()">Deselect All</button>
                            </div>
                        </div>
                    </div>
                    <div class="stacked-column-config">
                        <div class="chart-config-section">
                            <label>Stack Column (Colors/Segments)</label>
                            <select id="stacked-stack-column" onchange="updateStackedStackValues()">
                                <option value="">Choose a column...</option>
                                {chr(10).join(f'<option value="{html.escape(col)}">{html.escape(col)}</option>' for col in df.columns)}
                            </select>
                        </div>
                        <div class="stacked-values-selector">
                            <label>Stack Values</label>
                            <div class="stacked-topn-row">
                                <span>Top</span>
                                <input type="number" id="stacked-stack-topn" value="" min="1" max="30" placeholder="N" onchange="applyStackedStackTopN()">
                                <span>or select manually:</span>
                            </div>
                            <input type="text" class="chart-search" id="stacked-stack-search" 
                                placeholder="Search values..." oninput="filterStackedStackValues()">
                            <div class="stacked-values-list" id="stacked-stack-values-list">
                                <div style="padding: 10px; color: #888;">Select a column first</div>
                            </div>
                            <div class="stacked-select-actions">
                                <button onclick="selectAllStackedStack()">Select All</button>
                                <button onclick="deselectAllStackedStack()">Deselect All</button>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="chart-wrapper stacked-chart-wrapper">
                    <div class="stacked-canvas-wrapper">
                        <canvas id="stacked-chart"></canvas>
                    </div>
                </div>
                <div class="stacked-legend" id="stacked-legend"></div>
            </div>
        </div>

        <!-- Custom Comparison Chart -->
        <div class="chart-section">
            <h3>📈 Custom Comparison Chart (by Year)</h3>
            <div class="custom-chart-builder">
                <div class="chart-config-section" style="margin-bottom: 15px;">
                    <label>Select Column</label>
                    <select id="chart-column-select" onchange="updateChartValueOptions()">
                        <option value="">Choose a column...</option>
                        {chr(10).join(f'<option value="{html.escape(col)}">{html.escape(col)}</option>' for col in df.columns if col != year_column)}
                    </select>
                </div>

                <div class="chart-options-row">
                    <label class="chart-checkbox">
                        <input type="checkbox" id="chart-log-scale" onchange="updateCustomChartScale()">
                        Logarithmic Y-Axis
                    </label>
                </div>

                <div class="chart-mode-tabs">
                    <button class="chart-mode-tab active" onclick="switchChartMode('topn')">Top N</button>
                    <button class="chart-mode-tab" onclick="switchChartMode('manual')">Manual Selection</button>
                </div>

                <div class="chart-mode-content" id="chart-mode-topn">
                    <div class="topn-simple">
                        <label>Show Top</label>
                        <input type="number" id="chart-top-n" value="10" min="1" max="15" onchange="applyChartTopN()">
                        <span>most frequent values</span>
                    </div>
                </div>

                <div class="chart-mode-content hidden" id="chart-mode-manual">
                    <div class="chart-values-selector">
                        <label>Select Values to Compare (max 15)</label>
                        <input type="text" class="chart-search" id="chart-value-search" 
                            placeholder="Search values..." oninput="filterChartValues()">
                        <div class="chart-values-list" id="chart-values-list">
                            <div style="padding: 10px; color: #888;">Select a column first</div>
                        </div>
                        <div class="stacked-select-actions">
                            <button onclick="selectAllChartValues()">Select All</button>
                            <button onclick="clearAllChartValues()">Clear</button>
                        </div>
                        <div class="selected-chart-values" id="selected-chart-values"></div>
                    </div>
                </div>

                <div class="chart-wrapper">
                    <canvas id="custom-chart"></canvas>
                </div>
            </div>
        </div>
    </div>

    <script>
        const data = {json.dumps(data_for_js)};
        const columns = {json.dumps(list(df.columns))};
        const listColumns = {json.dumps(list_columns)};
        const filterOptions = {json.dumps(filter_options)};
        const columnsWithEmpty = {json.dumps(columns_with_empty)};
        const EMPTY_FILTER_VALUE = '__EMPTY__';
        const YEAR_COLUMN = {json.dumps(year_column)};

        let sortColumn = null;
        let sortDirection = 'asc';
        let visibleColumns = new Set(columns);
        let currentView = 'table';

        let filterTree = {{ type: 'group', operator: 'AND', children: [] }};
        let nextId = 1;

        // Chart instances
        let overviewChart = null;
        let customChart = null;
        let distributionChart = null;
        let stackedChart = null;
        let selectedChartValues = [];
        let distMode = 'absolute';

        // Stacked chart selections
        let selectedStackedXValues = [];
        let selectedStackedStackValues = [];

        // Chart mode: 'topn' or 'manual'
        let chartMode = 'topn';

        // Color palette for chart lines
        const chartColors = [
            '#3498db', '#e74c3c', '#27ae60', '#9b59b6', '#f39c12',
            '#1abc9c', '#e67e22', '#2980b9', '#c0392b', '#16a085',
            '#8e44ad', '#d35400', '#2c3e50', '#7f8c8d', '#34495e'
        ];

        // Extended color palette for stacked charts (more distinct colors)
        const stackedColors = [
            '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
            '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
            '#aec7e8', '#ffbb78', '#98df8a', '#ff9896', '#c5b0d5',
            '#c49c94', '#f7b6d2', '#c7c7c7', '#dbdb8d', '#9edae5',
            '#393b79', '#637939', '#8c6d31', '#843c39', '#7b4173',
            '#5254a3', '#8ca252', '#bd9e39', '#ad494a', '#a55194'
        ];

        function generateId() {{ return 'filter-' + (nextId++); }}

        document.addEventListener('DOMContentLoaded', function() {{
            renderFilterBuilder();
            renderTable();
            initCharts();
        }});

        function switchView(view) {{
            currentView = view;
            document.querySelectorAll('.view-toggle button').forEach(btn => btn.classList.remove('active'));
            document.querySelector(`.view-toggle button:${{view === 'table' ? 'first-child' : 'last-child'}}`).classList.add('active');

            document.getElementById('table-view').style.display = view === 'table' ? 'block' : 'none';
            document.getElementById('diagrams-view').style.display = view === 'diagrams' ? 'block' : 'none';

            if (view === 'diagrams') {{
                updateCharts();
            }}
        }}

        function initCharts() {{
            // Overview chart
            const overviewCtx = document.getElementById('overview-chart').getContext('2d');
            overviewChart = new Chart(overviewCtx, {{
                type: 'bar',
                data: {{ labels: [], datasets: [] }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ display: false }},
                        datalabels: {{ display: false }}
                    }},
                    scales: {{
                        y: {{
                            beginAtZero: true,
                            title: {{ display: true, text: 'Number of Papers' }},
                            ticks: {{ stepSize: 1 }}
                        }},
                        x: {{
                            title: {{ display: true, text: 'Year' }}
                        }}
                    }}
                }}
            }});

            // Distribution chart
            const distCtx = document.getElementById('distribution-chart').getContext('2d');
            distributionChart = new Chart(distCtx, {{
                type: 'bar',
                data: {{ labels: [], datasets: [] }},
                plugins: [ChartDataLabels],
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    indexAxis: 'y',
                    plugins: {{
                        legend: {{ display: false }},
                        datalabels: {{
                            anchor: 'end',
                            align: 'end',
                            color: '#333',
                            font: {{ weight: 'bold', size: 11 }},
                            formatter: function(value, context) {{
                                if (distMode === 'relative') {{
                                    return value.toFixed(1) + '%';
                                }}
                                return value;
                            }}
                        }}
                    }},
                    scales: {{
                        x: {{
                            beginAtZero: true,
                            title: {{ 
                                display: true, 
                                text: distMode === 'relative' ? 'Relative Share (%)' : 'Number of Papers'
                            }},
                            ticks: {{
                                callback: function(value) {{
                                    if (distMode === 'relative') {{
                                        return value + '%';
                                    }}
                                    return value;
                                }}
                            }}
                        }},
                        y: {{
                            ticks: {{
                                autoSkip: false,
                                font: {{ size: 11 }}
                            }}
                        }}
                    }}
                }}
            }});

            // Custom comparison chart
            const customCtx = document.getElementById('custom-chart').getContext('2d');
            customChart = new Chart(customCtx, {{
                type: 'line',
                data: {{ labels: [], datasets: [] }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ 
                            display: true,
                            position: 'top'
                        }},
                        datalabels: {{ display: false }}
                    }},
                    scales: {{
                        y: {{
                            beginAtZero: true,
                            title: {{ display: true, text: 'Number of Papers' }},
                            ticks: {{ stepSize: 1 }}
                        }},
                        x: {{
                            title: {{ display: true, text: 'Year' }}
                        }}
                    }}
                }}
            }});

            // Stacked bar chart
            const stackedCtx = document.getElementById('stacked-chart').getContext('2d');
            stackedChart = new Chart(stackedCtx, {{
                type: 'bar',
                data: {{ labels: [], datasets: [] }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ display: false }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    const label = context.dataset.label || '';
                                    const value = context.parsed.y;
                                    return `${{label}}: ${{value.toFixed(1)}}%`;
                                }}
                            }}
                        }},
                        datalabels: {{ display: false }}
                    }},
                    scales: {{
                        x: {{
                            stacked: true,
                            ticks: {{
                                autoSkip: false,
                                maxRotation: 45,
                                minRotation: 45,
                                font: {{ size: 10 }}
                            }}
                        }},
                        y: {{
                            stacked: true,
                            beginAtZero: true,
                            max: 100,
                            title: {{ display: true, text: 'Relative share (%) per bar' }},
                            ticks: {{
                                callback: function(value) {{
                                    return value + '%';
                                }}
                            }}
                        }}
                    }}
                }}
            }});
        }}

        function updateCharts() {{
            const filteredData = filterData();
            updateOverviewChart(filteredData);
            updateDistributionChart();
            updateCustomChart(filteredData);
        }}

        function updateOverviewChart(filteredData) {{
            const yearCounts = {{}};
            filteredData.forEach(row => {{
                const year = row[YEAR_COLUMN];
                if (year && year !== 'null') {{
                    yearCounts[year] = (yearCounts[year] || 0) + 1;
                }}
            }});

            const years = Object.keys(yearCounts).sort();
            const counts = years.map(y => yearCounts[y]);

            overviewChart.data.labels = years;
            overviewChart.data.datasets = [{{
                label: 'Papers',
                data: counts,
                backgroundColor: '#3498db',
                borderColor: '#2980b9',
                borderWidth: 1
            }}];
            overviewChart.update();
        }}

        function setDistMode(mode) {{
            distMode = mode;
            document.querySelectorAll('.mode-toggle button').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');
            updateDistributionChart();
        }}

        function updateDistributionChart() {{
            const column = document.getElementById('dist-column-select').value;
            const topN = parseInt(document.getElementById('dist-top-n').value) || 20;

            if (!column) {{
                distributionChart.data.labels = [];
                distributionChart.data.datasets = [];
                distributionChart.update();
                return;
            }}

            const filteredData = filterData();
            const valueCounts = {{}};
            let totalCount = 0;

            filteredData.forEach(row => {{
                const cellValue = row[column];
                if (cellValue === null || cellValue === undefined) return;

                if (Array.isArray(cellValue)) {{
                    cellValue.forEach(v => {{
                        if (v && v.trim()) {{
                            valueCounts[v] = (valueCounts[v] || 0) + 1;
                            totalCount++;
                        }}
                    }});
                }} else if (cellValue && cellValue.trim()) {{
                    valueCounts[cellValue] = (valueCounts[cellValue] || 0) + 1;
                    totalCount++;
                }}
            }});

            // Sort by count and take top N
            const sorted = Object.entries(valueCounts)
                .sort((a, b) => b[1] - a[1])
                .slice(0, topN);

            const labels = sorted.map(([name]) => name.length > 40 ? name.substring(0, 40) + '...' : name);
            const values = sorted.map(([, count]) => {{
                if (distMode === 'relative') {{
                    return totalCount > 0 ? (count / totalCount * 100) : 0;
                }}
                return count;
            }});
            const absoluteValues = sorted.map(([, count]) => count);

            // Adjust chart height based on number of bars
            const chartWrapper = document.querySelector('.distribution-chart');
            const canvasWrapper = chartWrapper.querySelector('.distribution-canvas-wrapper');
            const minHeight = Math.max(400, sorted.length * 25 + 100);
            canvasWrapper.style.height = minHeight + 'px';

            // Update axis label
            distributionChart.options.scales.x.title.text = distMode === 'relative' ? 'Relative Share (%)' : 'Number of Papers';

            distributionChart.data.labels = labels;
            distributionChart.data.datasets = [{{
                label: column,
                data: values,
                backgroundColor: '#3498db',
                borderColor: '#2980b9',
                borderWidth: 1,
                absoluteValues: absoluteValues
            }}];

            // Update datalabels formatter
            distributionChart.options.plugins.datalabels.formatter = function(value, context) {{
                const absVal = context.dataset.absoluteValues[context.dataIndex];
                if (distMode === 'relative') {{
                    return value.toFixed(1) + '% (' + absVal + ')';
                }}
                return value;
            }};

            distributionChart.resize();
            distributionChart.update();
        }}

        function updateCustomChart(filteredData) {{
            if (selectedChartValues.length === 0) {{
                customChart.data.labels = [];
                customChart.data.datasets = [];
                customChart.update();
                return;
            }}

            const column = document.getElementById('chart-column-select').value;
            if (!column) return;

            const allYears = new Set();
            filteredData.forEach(row => {{
                const year = row[YEAR_COLUMN];
                if (year && year !== 'null') {{
                    allYears.add(year);
                }}
            }});
            const years = Array.from(allYears).sort();

            const datasets = selectedChartValues.map((value, idx) => {{
                const yearCounts = {{}};
                years.forEach(y => yearCounts[y] = 0);

                filteredData.forEach(row => {{
                    const year = row[YEAR_COLUMN];
                    if (!year || year === 'null') return;

                    const cellValue = row[column];
                    let matches = false;

                    if (Array.isArray(cellValue)) {{
                        matches = cellValue.some(v => v && v.toLowerCase() === value.toLowerCase());
                    }} else if (cellValue) {{
                        matches = cellValue.toLowerCase() === value.toLowerCase();
                    }}

                    if (matches) {{
                        yearCounts[year] = (yearCounts[year] || 0) + 1;
                    }}
                }});

                const color = chartColors[idx % chartColors.length];
                return {{
                    label: value,
                    data: years.map(y => yearCounts[y]),
                    borderColor: color,
                    backgroundColor: color + '20',
                    fill: false,
                    tension: 0.1,
                    pointRadius: 4,
                    pointHoverRadius: 6
                }};
            }});

            customChart.data.labels = years;
            customChart.data.datasets = datasets;
            customChart.update();
        }}

        function updateChartValueOptions() {{
            const column = document.getElementById('chart-column-select').value;
            const listEl = document.getElementById('chart-values-list');
            const searchEl = document.getElementById('chart-value-search');

            selectedChartValues = [];
            renderSelectedChartValues();
            searchEl.value = '';

            if (!column) {{
                listEl.innerHTML = '<div style="padding: 10px; color: #888;">Select a column first</div>';
                updateCustomChart(filterData());
                return;
            }}

            const options = filterOptions[column] || [];
            if (options.length === 0) {{
                listEl.innerHTML = '<div style="padding: 10px; color: #888;">No values available</div>';
                updateCustomChart(filterData());
                return;
            }}

            listEl.innerHTML = options.map((val, idx) => {{
                const color = chartColors[idx % chartColors.length];
                const displayVal = val.length > 50 ? val.substring(0, 50) + '...' : val;
                return `<div class="chart-value-item" data-value="${{escapeHtml(val)}}" onclick="toggleChartValue('${{escapeHtml(val).replace(/'/g, "\\'")}}')" >
                    <input type="checkbox" onclick="event.stopPropagation(); toggleChartValue('${{escapeHtml(val).replace(/'/g, "\\'")}}')" >
                    <span class="color-indicator" style="background: ${{color}}"></span>
                    ${{escapeHtml(displayVal)}}
                </div>`;
            }}).join('');

            // Trigger appropriate mode update
            if (chartMode === 'topn') {{
                applyChartTopN();
            }} else {{
                updateCustomChart(filterData());
            }}
        }}

        function filterChartValues() {{
            const search = document.getElementById('chart-value-search').value.toLowerCase();
            const items = document.querySelectorAll('#chart-values-list .chart-value-item');
            items.forEach(item => {{
                const val = item.dataset.value.toLowerCase();
                item.style.display = val.includes(search) ? '' : 'none';
            }});
        }}

        function toggleChartValue(value) {{
            const idx = selectedChartValues.indexOf(value);
            if (idx >= 0) {{
                selectedChartValues.splice(idx, 1);
            }} else {{
                if (selectedChartValues.length >= 15) {{
                    alert('Maximum 15 values can be compared at once');
                    return;
                }}
                selectedChartValues.push(value);
            }}

            updateChartValueCheckboxes();
            renderSelectedChartValues();
            updateCustomChart(filterData());
        }}

        function renderSelectedChartValues() {{
            const container = document.getElementById('selected-chart-values');
            container.innerHTML = selectedChartValues.map((val, idx) => {{
                const color = chartColors[idx % chartColors.length];
                const displayVal = val.length > 25 ? val.substring(0, 25) + '...' : val;
                return `<span class="chart-value-tag" style="background: ${{color}}">
                    ${{escapeHtml(displayVal)}}
                    <span class="remove" onclick="toggleChartValue('${{escapeHtml(val).replace(/'/g, "\\'")}}')">&times;</span>
                </span>`;
            }}).join('');
        }}

        function selectAllChartValues() {{
            const column = document.getElementById('chart-column-select').value;
            if (!column) return;

            const options = filterOptions[column] || [];
            // Limit to 15 values max
            selectedChartValues = options.slice(0, 15);

            if (options.length > 15) {{
                alert('Selected first 15 values (maximum limit). Use search to find specific values.');
            }}

            updateChartValueCheckboxes();
            renderSelectedChartValues();
            updateCustomChart(filterData());
        }}

        function clearAllChartValues() {{
            selectedChartValues = [];
            updateChartValueCheckboxes();
            renderSelectedChartValues();
            updateCustomChart(filterData());
        }}

        function switchChartMode(mode) {{
            chartMode = mode;

            // Update tab styling
            document.querySelectorAll('.chart-mode-tab').forEach(tab => {{
                tab.classList.toggle('active', tab.textContent.toLowerCase().includes(mode));
            }});

            // Show/hide content
            document.getElementById('chart-mode-topn').classList.toggle('hidden', mode !== 'topn');
            document.getElementById('chart-mode-manual').classList.toggle('hidden', mode !== 'manual');

            // Clear current selections and apply new mode
            selectedChartValues = [];

            if (mode === 'topn') {{
                applyChartTopN();
            }} else {{
                updateChartValueCheckboxes();
                renderSelectedChartValues();
                updateCustomChart(filterData());
            }}
        }}

        function applyChartTopN() {{
            const column = document.getElementById('chart-column-select').value;
            const topNInput = document.getElementById('chart-top-n');
            const topN = parseInt(topNInput.value);

            if (!column || !topN || topN < 1) {{
                selectedChartValues = [];
                updateCustomChart(filterData());
                return;
            }}

            const n = Math.min(topN, 15);
            const filteredData = filterData();

            // Count occurrences of each value
            const valueCounts = {{}};
            filteredData.forEach(row => {{
                const cellValue = row[column];
                if (cellValue === null || cellValue === undefined) return;

                if (Array.isArray(cellValue)) {{
                    cellValue.forEach(v => {{
                        if (v && v.trim()) {{
                            valueCounts[v] = (valueCounts[v] || 0) + 1;
                        }}
                    }});
                }} else if (cellValue && cellValue.trim()) {{
                    valueCounts[cellValue] = (valueCounts[cellValue] || 0) + 1;
                }}
            }});

            // Sort by count and take top N
            const sorted = Object.entries(valueCounts)
                .sort((a, b) => b[1] - a[1])
                .slice(0, n);

            selectedChartValues = sorted.map(([name]) => name);
            updateCustomChart(filteredData);
        }}

        function updateCustomChartScale() {{
            const isLog = document.getElementById('chart-log-scale').checked;

            customChart.options.scales.y = {{
                type: isLog ? 'logarithmic' : 'linear',
                beginAtZero: !isLog,
                title: {{ display: true, text: 'Number of Papers' }},
                ticks: isLog ? {{
                    callback: function(value) {{
                        if (value === 1 || value === 10 || value === 100 || value === 1000) {{
                            return value;
                        }}
                        return '';
                    }}
                }} : {{ stepSize: 1 }}
            }};

            customChart.update();
        }}

        function updateChartValueCheckboxes() {{
            document.querySelectorAll('#chart-values-list .chart-value-item').forEach(item => {{
                const isSelected = selectedChartValues.includes(item.dataset.value);
                item.classList.toggle('selected', isSelected);
                const checkbox = item.querySelector('input[type="checkbox"]');
                if (checkbox) checkbox.checked = isSelected;
            }});
        }}

        // ============ Stacked Bar Chart Functions ============

        function updateStackedXValues() {{
            const column = document.getElementById('stacked-x-column').value;
            const listEl = document.getElementById('stacked-x-values-list');
            const searchEl = document.getElementById('stacked-x-search');

            selectedStackedXValues = [];
            searchEl.value = '';

            if (!column) {{
                listEl.innerHTML = '<div style="padding: 10px; color: #888;">Select a column first</div>';
                return;
            }}

            const options = filterOptions[column] || [];
            if (options.length === 0) {{
                listEl.innerHTML = '<div style="padding: 10px; color: #888;">No values available</div>';
                return;
            }}

            listEl.innerHTML = options.map((val) => {{
                const displayVal = val.length > 40 ? val.substring(0, 40) + '...' : val;
                return `<div class="stacked-value-item" data-value="${{escapeHtml(val)}}" onclick="toggleStackedXValue('${{escapeHtml(val).replace(/'/g, "\\'")}}')" >
                    <input type="checkbox" onclick="event.stopPropagation(); toggleStackedXValue('${{escapeHtml(val).replace(/'/g, "\\'")}}')" >
                    ${{escapeHtml(displayVal)}}
                </div>`;
            }}).join('');
        }}

        function updateStackedStackValues() {{
            const column = document.getElementById('stacked-stack-column').value;
            const listEl = document.getElementById('stacked-stack-values-list');
            const searchEl = document.getElementById('stacked-stack-search');

            selectedStackedStackValues = [];
            searchEl.value = '';

            if (!column) {{
                listEl.innerHTML = '<div style="padding: 10px; color: #888;">Select a column first</div>';
                return;
            }}

            const options = filterOptions[column] || [];
            if (options.length === 0) {{
                listEl.innerHTML = '<div style="padding: 10px; color: #888;">No values available</div>';
                return;
            }}

            listEl.innerHTML = options.map((val, idx) => {{
                const color = stackedColors[idx % stackedColors.length];
                const displayVal = val.length > 40 ? val.substring(0, 40) + '...' : val;
                return `<div class="stacked-value-item" data-value="${{escapeHtml(val)}}" onclick="toggleStackedStackValue('${{escapeHtml(val).replace(/'/g, "\\'")}}')" >
                    <input type="checkbox" onclick="event.stopPropagation(); toggleStackedStackValue('${{escapeHtml(val).replace(/'/g, "\\'")}}')" >
                    <span class="color-box" style="background: ${{color}}"></span>
                    ${{escapeHtml(displayVal)}}
                </div>`;
            }}).join('');
        }}

        function filterStackedXValues() {{
            const search = document.getElementById('stacked-x-search').value.toLowerCase();
            const items = document.querySelectorAll('#stacked-x-values-list .stacked-value-item');
            items.forEach(item => {{
                const val = item.dataset.value.toLowerCase();
                item.style.display = val.includes(search) ? '' : 'none';
            }});
        }}

        function filterStackedStackValues() {{
            const search = document.getElementById('stacked-stack-search').value.toLowerCase();
            const items = document.querySelectorAll('#stacked-stack-values-list .stacked-value-item');
            items.forEach(item => {{
                const val = item.dataset.value.toLowerCase();
                item.style.display = val.includes(search) ? '' : 'none';
            }});
        }}

        function toggleStackedXValue(value) {{
            const idx = selectedStackedXValues.indexOf(value);
            if (idx >= 0) {{
                selectedStackedXValues.splice(idx, 1);
            }} else {{
                selectedStackedXValues.push(value);
            }}
            updateStackedXCheckboxes();
            updateStackedChart();
        }}

        function toggleStackedStackValue(value) {{
            const idx = selectedStackedStackValues.indexOf(value);
            if (idx >= 0) {{
                selectedStackedStackValues.splice(idx, 1);
            }} else {{
                selectedStackedStackValues.push(value);
            }}
            updateStackedStackCheckboxes();
            updateStackedChart();
        }}

        function updateStackedXCheckboxes() {{
            document.querySelectorAll('#stacked-x-values-list .stacked-value-item').forEach(item => {{
                const isSelected = selectedStackedXValues.includes(item.dataset.value);
                item.classList.toggle('selected', isSelected);
                const checkbox = item.querySelector('input[type="checkbox"]');
                if (checkbox) checkbox.checked = isSelected;
            }});
        }}

        function updateStackedStackCheckboxes() {{
            document.querySelectorAll('#stacked-stack-values-list .stacked-value-item').forEach(item => {{
                const isSelected = selectedStackedStackValues.includes(item.dataset.value);
                item.classList.toggle('selected', isSelected);
                const checkbox = item.querySelector('input[type="checkbox"]');
                if (checkbox) checkbox.checked = isSelected;
            }});
        }}

        function selectAllStackedX() {{
            const column = document.getElementById('stacked-x-column').value;
            if (!column) return;
            selectedStackedXValues = [...(filterOptions[column] || [])];
            updateStackedXCheckboxes();
            updateStackedChart();
        }}

        function deselectAllStackedX() {{
            selectedStackedXValues = [];
            updateStackedXCheckboxes();
            updateStackedChart();
        }}

        function selectAllStackedStack() {{
            const column = document.getElementById('stacked-stack-column').value;
            if (!column) return;
            selectedStackedStackValues = [...(filterOptions[column] || [])];
            updateStackedStackCheckboxes();
            updateStackedChart();
        }}

        function deselectAllStackedStack() {{
            selectedStackedStackValues = [];
            updateStackedStackCheckboxes();
            updateStackedChart();
        }}

        function applyStackedXTopN() {{
            const column = document.getElementById('stacked-x-column').value;
            const topNInput = document.getElementById('stacked-x-topn');
            const topN = parseInt(topNInput.value);

            if (!column || !topN || topN < 1) {{
                return;
            }}

            const n = Math.min(topN, 50);
            const filteredData = filterData();

            // Count occurrences of each value
            const valueCounts = {{}};
            filteredData.forEach(row => {{
                const cellValue = row[column];
                if (cellValue === null || cellValue === undefined) return;

                if (Array.isArray(cellValue)) {{
                    cellValue.forEach(v => {{
                        if (v && v.trim()) {{
                            valueCounts[v] = (valueCounts[v] || 0) + 1;
                        }}
                    }});
                }} else if (cellValue && cellValue.trim()) {{
                    valueCounts[cellValue] = (valueCounts[cellValue] || 0) + 1;
                }}
            }});

            // Sort by count and take top N
            const sorted = Object.entries(valueCounts)
                .sort((a, b) => b[1] - a[1])
                .slice(0, n);

            selectedStackedXValues = sorted.map(([name]) => name);
            updateStackedXCheckboxes();
            updateStackedChart();
        }}

        function applyStackedStackTopN() {{
            const column = document.getElementById('stacked-stack-column').value;
            const topNInput = document.getElementById('stacked-stack-topn');
            const topN = parseInt(topNInput.value);

            if (!column || !topN || topN < 1) {{
                return;
            }}

            const n = Math.min(topN, 30);
            const filteredData = filterData();

            // Count occurrences of each value
            const valueCounts = {{}};
            filteredData.forEach(row => {{
                const cellValue = row[column];
                if (cellValue === null || cellValue === undefined) return;

                if (Array.isArray(cellValue)) {{
                    cellValue.forEach(v => {{
                        if (v && v.trim()) {{
                            valueCounts[v] = (valueCounts[v] || 0) + 1;
                        }}
                    }});
                }} else if (cellValue && cellValue.trim()) {{
                    valueCounts[cellValue] = (valueCounts[cellValue] || 0) + 1;
                }}
            }});

            // Sort by count and take top N
            const sorted = Object.entries(valueCounts)
                .sort((a, b) => b[1] - a[1])
                .slice(0, n);

            selectedStackedStackValues = sorted.map(([name]) => name);
            updateStackedStackCheckboxes();
            updateStackedChart();
        }}

        function updateStackedChart() {{
            const xColumn = document.getElementById('stacked-x-column').value;
            const stackColumn = document.getElementById('stacked-stack-column').value;

            if (!xColumn || !stackColumn || selectedStackedXValues.length === 0 || selectedStackedStackValues.length === 0) {{
                stackedChart.data.labels = [];
                stackedChart.data.datasets = [];
                stackedChart.update();
                document.getElementById('stacked-legend').innerHTML = '';
                return;
            }}

            const filteredData = filterData();

            // Build cross-tabulation matrix
            // For each x-value, count how many times each stack-value appears
            // Also track unique papers per x-value
            const crossTab = {{}};
            const paperCounts = {{}};
            const linkCounts = {{}};

            selectedStackedXValues.forEach(xVal => {{
                crossTab[xVal] = {{}};
                paperCounts[xVal] = new Set();
                linkCounts[xVal] = 0;
                selectedStackedStackValues.forEach(stackVal => {{
                    crossTab[xVal][stackVal] = 0;
                }});
            }});

            // Count occurrences
            filteredData.forEach((row, rowIdx) => {{
                const xCellValue = row[xColumn];
                const stackCellValue = row[stackColumn];

                // Get x-values from this row
                let xVals = [];
                if (Array.isArray(xCellValue)) {{
                    xVals = xCellValue.filter(v => v && selectedStackedXValues.some(sv => sv.toLowerCase() === v.toLowerCase()));
                }} else if (xCellValue && selectedStackedXValues.some(sv => sv.toLowerCase() === xCellValue.toLowerCase())) {{
                    xVals = [xCellValue];
                }}

                // Get stack-values from this row
                let stackVals = [];
                if (Array.isArray(stackCellValue)) {{
                    stackVals = stackCellValue.filter(v => v && selectedStackedStackValues.some(sv => sv.toLowerCase() === v.toLowerCase()));
                }} else if (stackCellValue && selectedStackedStackValues.some(sv => sv.toLowerCase() === stackCellValue.toLowerCase())) {{
                    stackVals = [stackCellValue];
                }}

                // Cross-tabulate: for each x-value in this row, count each stack-value
                xVals.forEach(xv => {{
                    const xvNorm = selectedStackedXValues.find(sv => sv.toLowerCase() === xv.toLowerCase());
                    if (xvNorm) {{
                        paperCounts[xvNorm].add(rowIdx);
                        stackVals.forEach(sv => {{
                            const svNorm = selectedStackedStackValues.find(ssv => ssv.toLowerCase() === sv.toLowerCase());
                            if (svNorm) {{
                                crossTab[xvNorm][svNorm]++;
                                linkCounts[xvNorm]++;
                            }}
                        }});
                    }}
                }});
            }});

            // Sort x-values by total link count (descending) for better visualization
            const sortedXValues = [...selectedStackedXValues].sort((a, b) => linkCounts[b] - linkCounts[a]);

            // Calculate percentages and build datasets
            const datasets = selectedStackedStackValues.map((stackVal, idx) => {{
                const color = stackedColors[idx % stackedColors.length];
                const data = sortedXValues.map(xVal => {{
                    const total = linkCounts[xVal];
                    if (total === 0) return 0;
                    return (crossTab[xVal][stackVal] / total) * 100;
                }});

                return {{
                    label: stackVal,
                    data: data,
                    backgroundColor: color,
                    borderColor: color,
                    borderWidth: 1
                }};
            }});

            // Create labels with counts: "Category\\nAbsolute (Papers)"
            const labels = sortedXValues.map(xVal => {{
                const truncated = xVal.length > 25 ? xVal.substring(0, 25) + '...' : xVal;
                return truncated + '\\n' + linkCounts[xVal] + ' (' + paperCounts[xVal].size + ')';
            }});

            // Adjust canvas height based on number of bars
            const canvasWrapper = document.querySelector('.stacked-canvas-wrapper');
            const minWidth = Math.max(600, sortedXValues.length * 70);
            canvasWrapper.style.minWidth = minWidth + 'px';

            stackedChart.data.labels = labels;
            stackedChart.data.datasets = datasets;
            stackedChart.update();

            // Render custom legend
            renderStackedLegend();
        }}

        function renderStackedLegend() {{
            const legendEl = document.getElementById('stacked-legend');
            legendEl.innerHTML = selectedStackedStackValues.map((val, idx) => {{
                const color = stackedColors[idx % stackedColors.length];
                const displayVal = val.length > 40 ? val.substring(0, 40) + '...' : val;
                return `<div class="stacked-legend-item">
                    <span class="stacked-legend-color" style="background: ${{color}}"></span>
                    ${{escapeHtml(displayVal)}}
                </div>`;
            }}).join('');
        }}

        function isListColumn(col) {{
            return listColumns.includes(col);
        }}

        function renderFilterBuilder() {{
            const container = document.getElementById('filter-builder');
            container.innerHTML = renderGroup(filterTree, true);
        }}

        function renderGroup(group, isRoot = false) {{
            const groupId = group.id || (group.id = generateId());
            const isOr = group.operator === 'OR';

            let html = `<div class="filter-group ${{isOr ? 'or-group' : ''}}" data-id="${{groupId}}">`;
            html += `<div class="filter-group-header">`;
            html += `<div class="operator-toggle">
                <button class="${{!isOr ? 'active' : ''}}" onclick="setGroupOperator('${{groupId}}', 'AND')">AND</button>
                <button class="${{isOr ? 'active or' : ''}}" onclick="setGroupOperator('${{groupId}}', 'OR')">OR</button>
            </div>`;
            html += `<div class="filter-group-actions">
                <button class="btn-add-condition" onclick="addCondition('${{groupId}}')">+ Condition</button>
                <button class="btn-add-group" onclick="addGroup('${{groupId}}')">+ Group</button>
                ${{!isRoot ? `<button class="btn-remove-group" onclick="removeGroup('${{groupId}}')">Remove</button>` : ''}}
            </div>`;
            html += `</div>`;

            group.children.forEach((child, index) => {{
                if (index > 0) {{
                    html += `<span class="operator-label ${{isOr ? 'or' : ''}}">${{group.operator}}</span>`;
                }}
                if (child.type === 'group') {{
                    html += `<div class="nested-group">${{renderGroup(child)}}</div>`;
                }} else {{
                    html += renderCondition(child);
                }}
            }});

            if (group.children.length === 0) {{
                html += `<div class="filter-condition" style="color: #888; font-style: italic;">
                    Click "+ Condition" to add a filter
                </div>`;
            }}

            html += `</div>`;
            return html;
        }}

        function renderCondition(condition) {{
            const condId = condition.id || (condition.id = generateId());
            const selectedColumn = condition.column || '';
            const filterType = condition.filterType || 'contains';
            const isNegated = condition.negate || false;
            const isList = isListColumn(selectedColumn);

            let html = `<div class="filter-condition ${{isNegated ? 'negated' : ''}}" data-id="${{condId}}">`;

            html += `<div class="filter-type-row">`;

            html += `<label class="not-toggle ${{isNegated ? 'active' : ''}}" title="Negate this condition">
                <input type="checkbox" ${{isNegated ? 'checked' : ''}} 
                    onchange="toggleNegate('${{condId}}', this.checked)">
                NOT
            </label>`;

            html += `<select class="condition-column" onchange="updateConditionColumn('${{condId}}', this.value)">
                <option value="">Select column...</option>`;
            columns.forEach(col => {{
                const isColList = isListColumn(col);
                html += `<option value="${{escapeHtml(col)}}" ${{col === selectedColumn ? 'selected' : ''}}>${{escapeHtml(col)}}${{isColList ? ' [list]' : ''}}</option>`;
            }});
            html += `</select>`;

            if (selectedColumn) {{
                html += `<select class="filter-type" onchange="updateFilterType('${{condId}}', this.value)">`;
                html += `<option value="contains" ${{filterType === 'contains' ? 'selected' : ''}}>contains</option>`;
                html += `<option value="empty" ${{filterType === 'empty' ? 'selected' : ''}}>is empty</option>`;
                if (isList) {{
                    html += `<option value="count" ${{filterType === 'count' ? 'selected' : ''}}>count</option>`;
                    html += `<option value="hasAll" ${{filterType === 'hasAll' ? 'selected' : ''}}>has ALL of</option>`;
                    html += `<option value="hasAny" ${{filterType === 'hasAny' ? 'selected' : ''}}>has ANY of</option>`;
                    html += `<option value="hasOnly" ${{filterType === 'hasOnly' ? 'selected' : ''}}>has ONLY of</option>`;
                }}
                if (selectedColumn === YEAR_COLUMN) {{
                    html += `<option value="compare" ${{filterType === 'compare' ? 'selected' : ''}}>compare</option>`;
                }}
                html += `</select>`;
            }}

            if (selectedColumn && filterOptions[selectedColumn]) {{
                const count = filterOptions[selectedColumn].length + (columnsWithEmpty[selectedColumn] ? 1 : 0);
                html += `<span class="option-count">${{count}} options</span>`;
            }}

            html += `<button class="btn-remove" onclick="removeCondition('${{condId}}')" style="margin-left: auto;">×</button>`;
            html += `</div>`;

            if (selectedColumn && filterType !== 'empty') {{
                html += renderValueInputs(condition, condId, selectedColumn, filterType, isList);
            }}

            html += `</div>`;
            return html;
        }}

        function renderValueInputs(condition, condId, selectedColumn, filterType, isList) {{
            let html = '';

            if (filterType === 'count') {{
                const countOp = condition.countOp || '=';
                const countVal = condition.countValue !== undefined ? condition.countValue : '';

                html += `<div class="count-inputs">
                    <select onchange="updateCountOp('${{condId}}', this.value)">
                        <option value="=" ${{countOp === '=' ? 'selected' : ''}}>=</option>
                        <option value="!=" ${{countOp === '!=' ? 'selected' : ''}}>≠</option>
                        <option value=">" ${{countOp === '>' ? 'selected' : ''}}>&gt;</option>
                        <option value=">=" ${{countOp === '>=' ? 'selected' : ''}}>≥</option>
                        <option value="<" ${{countOp === '<' ? 'selected' : ''}}>&lt;</option>
                        <option value="<=" ${{countOp === '<=' ? 'selected' : ''}}>≤</option>
                    </select>
                    <input type="number" min="0" value="${{countVal}}" 
                        onchange="updateCountValue('${{condId}}', this.value)"
                        placeholder="count">
                </div>`;

            }} else if (filterType === 'hasAll' || filterType === 'hasAny' || filterType === 'hasOnly') {{
                const selectedValues = condition.values || [];
                const options = filterOptions[selectedColumn] || [];

                html += `<div class="multi-value-container">`;
                html += `<input type="text" class="multi-value-search" placeholder="Search values..." 
                    oninput="filterMultiValues('${{condId}}', this.value)">`;
                html += `<div class="multi-value-list" id="mvl-${{condId}}">`;
                options.forEach(val => {{
                    const isSelected = selectedValues.includes(val);
                    const displayVal = val.length > 35 ? val.substring(0, 35) + '...' : val;
                    html += `<div class="multi-value-item ${{isSelected ? 'selected' : ''}}" data-value="${{escapeHtml(val)}}">
                        <input type="checkbox" ${{isSelected ? 'checked' : ''}} 
                            onchange="toggleMultiValue('${{condId}}', '${{escapeHtml(val).replace(/'/g, "\\'")}}')">${{escapeHtml(displayVal)}}
                    </div>`;
                }});
                html += `</div>`;

                if (selectedValues.length > 0) {{
                    html += `<div class="selected-values">`;
                    selectedValues.forEach(val => {{
                        const displayVal = val.length > 20 ? val.substring(0, 20) + '...' : val;
                        html += `<span class="selected-tag">${{escapeHtml(displayVal)}}
                            <span class="remove" onclick="toggleMultiValue('${{condId}}', '${{escapeHtml(val).replace(/'/g, "\\'")}}')">×</span>
                        </span>`;
                    }});
                    html += `</div>`;
                }}
                html += `</div>`;

            }} else if (filterType === 'compare') {{
                const compareOp = condition.compareOp || '=';
                const compareVal = condition.compareValue !== undefined ? condition.compareValue : '';

                html += `<div class="count-inputs">
                    <select onchange="updateCompareOp('${{condId}}', this.value)">
                        <option value="=" ${{compareOp === '=' ? 'selected' : ''}}>=</option>
                        <option value="!=" ${{compareOp === '!=' ? 'selected' : ''}}>≠</option>
                        <option value=">" ${{compareOp === '>' ? 'selected' : ''}}>&gt;</option>
                        <option value=">=" ${{compareOp === '>=' ? 'selected' : ''}}>≥</option>
                        <option value="<" ${{compareOp === '<' ? 'selected' : ''}}>&lt;</option>
                        <option value="<=" ${{compareOp === '<=' ? 'selected' : ''}}>≤</option>
                    </select>
                    <input type="number" value="${{compareVal}}" 
                        onchange="updateCompareValue('${{condId}}', this.value)"
                        placeholder="year">
                </div>`;

            }} else {{
                const selectedValue = condition.value || '';

                html += `<select class="condition-value-select" onchange="updateConditionValue('${{condId}}', this.value)">
                    <option value="">Select value...</option>`;
                if (columnsWithEmpty[selectedColumn]) {{
                    html += `<option value="${{EMPTY_FILTER_VALUE}}" class="empty-option" ${{selectedValue === EMPTY_FILTER_VALUE ? 'selected' : ''}}>(empty)</option>`;
                }}
                (filterOptions[selectedColumn] || []).forEach(val => {{
                    const displayVal = val.length > 40 ? val.substring(0, 40) + '...' : val;
                    html += `<option value="${{escapeHtml(val)}}" ${{val === selectedValue ? 'selected' : ''}}>${{escapeHtml(displayVal)}}</option>`;
                }});
                html += `</select>`;

                const textVal = selectedValue && selectedValue !== EMPTY_FILTER_VALUE && !isInOptions(selectedColumn, selectedValue) ? selectedValue : '';
                html += `<input type="text" class="condition-value-text" placeholder="Or type to search..." 
                    value="${{escapeHtml(textVal)}}"
                    onchange="updateConditionValueText('${{condId}}', this.value)">`;
            }}

            return html;
        }}

        function isInOptions(column, value) {{
            if (!column || !filterOptions[column]) return false;
            return filterOptions[column].includes(value) || value === EMPTY_FILTER_VALUE;
        }}

        function findNodeById(node, id) {{
            if (node.id === id) return node;
            if (node.children) {{
                for (const child of node.children) {{
                    const found = findNodeById(child, id);
                    if (found) return found;
                }}
            }}
            return null;
        }}

        function findParentById(node, id, parent = null) {{
            if (node.id === id) return parent;
            if (node.children) {{
                for (const child of node.children) {{
                    const found = findParentById(child, id, node);
                    if (found) return found;
                }}
            }}
            return null;
        }}

        function setGroupOperator(groupId, operator) {{
            const group = findNodeById(filterTree, groupId);
            if (group) {{ group.operator = operator; renderFilterBuilder(); }}
        }}

        function addCondition(groupId) {{
            const group = findNodeById(filterTree, groupId);
            if (group) {{
                group.children.push({{ 
                    type: 'condition', 
                    column: '', 
                    value: '', 
                    filterType: 'contains', 
                    negate: false,
                    id: generateId() 
                }});
                renderFilterBuilder();
            }}
        }}

        function addGroup(groupId) {{
            const group = findNodeById(filterTree, groupId);
            if (group) {{
                group.children.push({{ type: 'group', operator: 'AND', children: [], id: generateId() }});
                renderFilterBuilder();
            }}
        }}

        function removeGroup(groupId) {{
            const parent = findParentById(filterTree, groupId);
            if (parent) {{ parent.children = parent.children.filter(c => c.id !== groupId); renderFilterBuilder(); }}
        }}

        function removeCondition(condId) {{
            const parent = findParentById(filterTree, condId);
            if (parent) {{ parent.children = parent.children.filter(c => c.id !== condId); renderFilterBuilder(); }}
        }}

        function toggleNegate(condId, negate) {{
            const condition = findNodeById(filterTree, condId);
            if (condition) {{
                condition.negate = negate;
                renderFilterBuilder();
            }}
        }}

        function updateConditionColumn(condId, column) {{
            const condition = findNodeById(filterTree, condId);
            if (condition) {{
                condition.column = column;
                condition.value = '';
                condition.values = [];
                condition.filterType = 'contains';
                condition.countOp = '=';
                condition.countValue = '';
                condition.compareOp = '=';
                condition.compareValue = '';
                renderFilterBuilder();
            }}
        }}

        function updateFilterType(condId, filterType) {{
            const condition = findNodeById(filterTree, condId);
            if (condition) {{
                condition.filterType = filterType;
                condition.value = '';
                condition.values = [];
                condition.countOp = '=';
                condition.countValue = '';
                condition.compareOp = '=';
                condition.compareValue = '';
                renderFilterBuilder();
            }}
        }}

        function updateConditionValue(condId, value) {{
            const condition = findNodeById(filterTree, condId);
            if (condition) {{
                condition.value = value;
                const condEl = document.querySelector(`.filter-condition[data-id="${{condId}}"]`);
                if (condEl) {{
                    const textInput = condEl.querySelector('.condition-value-text');
                    if (textInput) textInput.value = '';
                }}
            }}
        }}

        function updateConditionValueText(condId, value) {{
            const condition = findNodeById(filterTree, condId);
            if (condition && value.trim()) {{
                condition.value = value.trim();
                const condEl = document.querySelector(`.filter-condition[data-id="${{condId}}"]`);
                if (condEl) {{
                    const selectEl = condEl.querySelector('.condition-value-select');
                    if (selectEl) selectEl.value = '';
                }}
            }}
        }}

        function updateCountOp(condId, op) {{
            const condition = findNodeById(filterTree, condId);
            if (condition) condition.countOp = op;
        }}

        function updateCountValue(condId, value) {{
            const condition = findNodeById(filterTree, condId);
            if (condition) condition.countValue = parseInt(value) || 0;
        }}

        function updateCompareOp(condId, op) {{
            const condition = findNodeById(filterTree, condId);
            if (condition) condition.compareOp = op;
        }}

        function updateCompareValue(condId, value) {{
            const condition = findNodeById(filterTree, condId);
            if (condition) condition.compareValue = value !== '' ? parseFloat(value) : '';
        }}

        function toggleMultiValue(condId, value) {{
            const condition = findNodeById(filterTree, condId);
            if (condition) {{
                if (!condition.values) condition.values = [];
                const idx = condition.values.indexOf(value);
                if (idx >= 0) {{
                    condition.values.splice(idx, 1);
                }} else {{
                    condition.values.push(value);
                }}
                renderFilterBuilder();
            }}
        }}

        function filterMultiValues(condId, searchText) {{
            const listEl = document.getElementById(`mvl-${{condId}}`);
            if (!listEl) return;
            const items = listEl.querySelectorAll('.multi-value-item');
            const search = searchText.toLowerCase();
            items.forEach(item => {{
                const val = item.dataset.value.toLowerCase();
                item.style.display = val.includes(search) ? '' : 'none';
            }});
        }}

        function applyFilters() {{
            renderTable();
            updateFilterSummary();
            if (currentView === 'diagrams') {{
                updateCharts();
            }}
        }}

        function clearAllFilters() {{
            filterTree = {{ type: 'group', operator: 'AND', children: [], id: generateId() }};
            renderFilterBuilder();
            renderTable();
            updateFilterSummary();
            if (currentView === 'diagrams') {{
                updateCharts();
            }}
        }}

        function updateFilterSummary() {{
            const summary = document.getElementById('filter-summary');
            const expression = buildFilterExpression(filterTree);
            if (expression) {{
                summary.textContent = expression;
                summary.classList.remove('empty');
            }} else {{
                summary.textContent = 'No filters applied';
                summary.classList.add('empty');
            }}
        }}

        function buildFilterExpression(node) {{
            if (node.type === 'condition') {{
                if (!node.column) return null;

                const col = node.column;
                const ft = node.filterType || 'contains';
                const neg = node.negate ? 'NOT ' : '';

                let expr = null;

                if (ft === 'empty') {{
                    expr = `${{col}} IS EMPTY`;
                }} else if (ft === 'count') {{
                    if (node.countValue === undefined || node.countValue === '') return null;
                    expr = `COUNT(${{col}}) ${{node.countOp}} ${{node.countValue}}`;
                }} else if (ft === 'hasAll' || ft === 'hasAny' || ft === 'hasOnly') {{
                    if (!node.values || node.values.length === 0) return null;
                    const vals = node.values.map(v => `"${{v}}"`).join(', ');
                    const opLabel = ft === 'hasAll' ? 'ALL' : (ft === 'hasAny' ? 'ANY' : 'ONLY');
                    expr = `${{col}} HAS ${{opLabel}} OF (${{vals}})`;
                }} else if (ft === 'compare') {{
                    if (node.compareValue === undefined || node.compareValue === '') return null;
                    expr = `${{col}} ${{node.compareOp}} ${{node.compareValue}}`;
                }} else {{
                    if (!node.value) return null;
                    const displayValue = node.value === EMPTY_FILTER_VALUE ? '(empty)' : node.value;
                    expr = `${{col}} = "${{displayValue}}"`;
                }}

                return expr ? neg + expr : null;
            }}

            if (node.type === 'group') {{
                const childExprs = node.children.map(c => buildFilterExpression(c)).filter(e => e !== null);
                if (childExprs.length === 0) return null;
                if (childExprs.length === 1) return childExprs[0];
                return '(' + childExprs.join(` ${{node.operator}} `) + ')';
            }}

            return null;
        }}

        function evaluateCondition(row, node) {{
            if (!node.column) return true;

            const val = row[node.column];
            const ft = node.filterType || 'contains';

            if (ft === 'empty') {{
                if (val === null || val === undefined) return true;
                if (Array.isArray(val) && val.length === 0) return true;
                return false;
            }}

            if (ft === 'count') {{
                if (node.countValue === undefined || node.countValue === '') return true;
                const len = Array.isArray(val) ? val.length : (val ? 1 : 0);
                const target = node.countValue;
                switch (node.countOp) {{
                    case '=': return len === target;
                    case '!=': return len !== target;
                    case '>': return len > target;
                    case '>=': return len >= target;
                    case '<': return len < target;
                    case '<=': return len <= target;
                    default: return true;
                }}
            }}

            if (ft === 'hasAll' || ft === 'hasAny') {{
                if (!node.values || node.values.length === 0) return true;
                if (!Array.isArray(val)) return false;

                const valLower = val.map(v => v ? v.toLowerCase() : '');
                if (ft === 'hasAll') {{
                    return node.values.every(v => valLower.some(vl => vl.includes(v.toLowerCase())));
                }} else {{
                    return node.values.some(v => valLower.some(vl => vl.includes(v.toLowerCase())));
                }}
            }}

            if (ft === 'hasOnly') {{
                if (!node.values || node.values.length === 0) return true;
                if (!Array.isArray(val) || val.length === 0) return false;

                // Every value in the cell must be in the selected values (and nothing else)
                const allowedLower = node.values.map(v => v.toLowerCase());
                return val.every(v => {{
                    const vLower = v ? v.toLowerCase() : '';
                    return allowedLower.some(a => vLower.includes(a) || a.includes(vLower));
                }});
            }}

            if (ft === 'compare') {{
                if (node.compareValue === undefined || node.compareValue === '') return true;
                const numVal = parseFloat(val);
                if (isNaN(numVal)) return false;
                const target = parseFloat(node.compareValue);
                switch (node.compareOp) {{
                    case '=': return numVal === target;
                    case '!=': return numVal !== target;
                    case '>': return numVal > target;
                    case '>=': return numVal >= target;
                    case '<': return numVal < target;
                    case '<=': return numVal <= target;
                    default: return true;
                }}
            }}

            if (!node.value) return true;

            if (node.value === EMPTY_FILTER_VALUE) {{
                if (val === null || val === undefined) return true;
                if (Array.isArray(val) && val.length === 0) return true;
                return false;
            }}

            const searchVal = node.value.toLowerCase();
            if (val === null || val === undefined) return false;

            if (Array.isArray(val)) {{
                return val.some(v => v && v.toLowerCase().includes(searchVal));
            }} else {{
                return val.toLowerCase().includes(searchVal);
            }}
        }}

        function evaluateFilter(row, node) {{
            if (node.type === 'condition') {{
                let result = evaluateCondition(row, node);
                if (node.negate) {{
                    result = !result;
                }}
                return result;
            }}

            if (node.type === 'group') {{
                const validChildren = node.children.filter(c => {{
                    if (c.type === 'group') return true;
                    if (!c.column) return false;
                    const ft = c.filterType || 'contains';
                    if (ft === 'empty') return true;
                    if (ft === 'count') return c.countValue !== undefined && c.countValue !== '';
                    if (ft === 'hasAll' || ft === 'hasAny' || ft === 'hasOnly') return c.values && c.values.length > 0;
                    if (ft === 'compare') return c.compareValue !== undefined && c.compareValue !== '';
                    return c.value;
                }});

                if (validChildren.length === 0) return true;

                if (node.operator === 'AND') {{
                    return validChildren.every(child => evaluateFilter(row, child));
                }} else {{
                    return validChildren.some(child => evaluateFilter(row, child));
                }}
            }}

            return true;
        }}

        function renderTable() {{
            const tbody = document.getElementById('table-body');
            const filteredData = filterData();

            document.querySelectorAll('#papers-table th').forEach(th => {{
                const col = th.dataset.column;
                th.classList.toggle('hidden', !visibleColumns.has(col));
            }});

            tbody.innerHTML = filteredData.map(row => {{
                return '<tr>' + columns.map(col => {{
                    if (!visibleColumns.has(col)) return '';
                    const val = row[col];
                    let cellContent;

                    if (val === null || val === undefined) {{
                        cellContent = '<span class="empty">—</span>';
                    }} else if (Array.isArray(val)) {{
                        if (val.length === 0) {{
                            cellContent = '<span class="empty">—</span>';
                        }} else {{
                            cellContent = '<div class="list-cell">' +
                                val.map(v => '<span class="list-item">' + escapeHtml(v) + '</span>').join('') +
                                '</div>';
                        }}
                    }} else if (col === 'doi' && val) {{
                        cellContent = '<a class="doi-link" href="https://doi.org/' + encodeURIComponent(val) + '" target="_blank">' + escapeHtml(val) + '</a>';
                    }} else {{
                        cellContent = escapeHtml(val);
                    }}

                    return '<td>' + cellContent + '</td>';
                }}).join('') + '</tr>';
            }}).join('');

            document.getElementById('visible-count').textContent = filteredData.length;
        }}

        function filterData() {{
            let result = data.filter(row => evaluateFilter(row, filterTree));

            if (sortColumn) {{
                result = [...result].sort((a, b) => {{
                    let valA = a[sortColumn];
                    let valB = b[sortColumn];

                    if (valA === null && valB === null) return 0;
                    if (valA === null) return 1;
                    if (valB === null) return -1;

                    if (Array.isArray(valA)) valA = valA[0] || '';
                    if (Array.isArray(valB)) valB = valB[0] || '';

                    const cmp = String(valA).localeCompare(String(valB));
                    return sortDirection === 'asc' ? cmp : -cmp;
                }});
            }}

            return result;
        }}

        function sortTable(column) {{
            if (sortColumn === column) {{
                sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
            }} else {{
                sortColumn = column;
                sortDirection = 'asc';
            }}

            document.querySelectorAll('.sort-indicator').forEach(el => el.textContent = '');
            const th = document.querySelector('th[data-column="' + column + '"] .sort-indicator');
            if (th) th.textContent = sortDirection === 'asc' ? ' ↑' : ' ↓';

            renderTable();
        }}

        function toggleColumn(column) {{
            if (visibleColumns.has(column)) {{
                visibleColumns.delete(column);
            }} else {{
                visibleColumns.add(column);
            }}
            renderTable();
        }}

        function escapeHtml(text) {{
            if (text === null || text === undefined) return '';
            const div = document.createElement('div');
            div.textContent = String(text);
            return div.innerHTML;
        }}
    </script>
</body>
</html>'''

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"HTML overview generated: {output_path}")


def create_paper_overview(
        df1: pd.DataFrame,
        df2: pd.DataFrame,
        columns1: List[str],
        columns2: List[str],
        output_path: str = "paper_overview.html",
        title: str = "Paper Overview",
        doi_col1: str = 'doi',
        doi_col2: str = 'doi',
        year_column: str = 'year'
) -> pd.DataFrame:
    merged_df = merge_dataframes(df1, df2, columns1, columns2, doi_col1, doi_col2)
    generate_html(merged_df, output_path, title, year_column)
    return merged_df


if __name__ == '__main__':
    ma = load_many([r"..\..\..\..\review_output\gapminder\2026128_manual.parquet"])
    auto = load_many([r"..\..\..\..\review_output\gapminder\2026128_auto.parquet"])

    columns = ['file', 'doi', 'year', 'Country', 'Light Spectra', 'Imaging Method',
               'CV Tasks', 'CV Algorithms', 'Dataset', 'ParentHabitat', 'Kingdom',
               'Phylum', 'Class', 'Order', 'Family', 'Genus', 'Species', 'Modality', 'Type']

    create_paper_overview(
        ma,
        auto,
        columns,
        columns,
        output_path="paper_overview.html",
        title="Computer Vision in Wildlife Conservation: A Semi-Automated Review",
        year_column='year'
    )