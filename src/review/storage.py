from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass
class Storage:
    base_dir: Path

    def __post_init__(self) -> None:
        self.base_dir = Path(self.base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ---------- Atomic JSON I/O ----------

    def _atomic_write_text(self, path: Path, content: str) -> None:
        path = Path(path)
        tmp_dir = path.parent
        os.makedirs(tmp_dir, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=tmp_dir, encoding="utf-8") as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, path)

    def write_json(self, path: Path, data: Any, *, indent: int = 2) -> None:
        text = json.dumps(data, ensure_ascii=False, indent=indent)
        self._atomic_write_text(path, text)

    def read_json(self, path: Path) -> Any:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ---------- Cache paths ----------

    def cache_path_for_stem(self, stem: str) -> Path:
        return self.base_dir / f"{stem}.json"

    def has_cache(self, stem: str) -> bool:
        return self.cache_path_for_stem(stem).exists()

    def read_cache(self, stem: str) -> Dict[str, Any]:
        return self.read_json(self.cache_path_for_stem(stem))

    def write_cache(self, stem: str, data: Dict[str, Any]) -> None:
        self.write_json(self.cache_path_for_stem(stem), data)

    # ---------- Config snapshot & hashing ----------

    @staticmethod
    def _json_default(o: Any) -> Any:
        # Make common non-JSON types serializable in a predictable way.
        if isinstance(o, Path):
            return str(o)
        # Fallback: string representation
        return str(o)

    @staticmethod
    def _stable_json_dumps(obj: Any) -> str:
        return json.dumps(
            obj,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=Storage._json_default,
        )

    def _normalize_config(self, config_like: Any) -> Any:
        """
        Produce a JSON-serializable, *stable* representation of the config.
        We serialize with stable options and parse back to Python to guarantee
        normalized dict/list ordering and value shapes.
        """
        try:
            text = self._stable_json_dumps(config_like)
            return json.loads(text)
        except Exception:
            # As a last resort, return a string form.
            return str(config_like)

    def compute_config_hash(self, config_like: Any) -> str:
        """
        Compute SHA256 over a stable JSON serialization of the provided object.
        """
        payload = self._stable_json_dumps(config_like).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @property
    def config_snapshot_path(self) -> Path:
        return self.base_dir / "_config.json"

    def load_config_snapshot(self) -> Optional[Dict[str, Any]]:
        if not self.config_snapshot_path.exists():
            return None
        return self.read_json(self.config_snapshot_path)

    def save_config_snapshot(
        self,
        config: Any = None,
        *,
        config_hash: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Save a snapshot containing both the hash and, if provided, the full config.

        Preferred usage:
            store.save_config_snapshot(config=current_config, extra={...})

        Legacy (still supported):
            store.save_config_snapshot(config_hash=precomputed_hash)

        Args:
            config: Arbitrary (ideally dict-like) object describing prompts, model, etc.
            config_hash: Precomputed hash (used if `config` is not given).
            extra: Optional metadata to persist (user, run flags, etc.).
        """
        snapshot: Dict[str, Any] = {}

        if config is not None:
            normalized = self._normalize_config(config)
            cfg_hash = self.compute_config_hash(normalized)
            snapshot["config"] = normalized
            snapshot["config_hash"] = cfg_hash
        elif config_hash is not None:
            snapshot["config_hash"] = config_hash
        else:
            raise ValueError("Provide either `config` or `config_hash`.")

        if extra:
            snapshot["extra"] = self._normalize_config(extra)

        snapshot["created_at"] = datetime.now(timezone.utc).isoformat()

        self.write_json(self.config_snapshot_path, snapshot)

    # ---- Drift detection and diffs ----

    def config_has_drift(
        self,
        current_config: Any = None,
        *,
        current_hash: Optional[str] = None,
    ) -> bool:
        """
        Compare the *current* config (or hash) against the saved snapshot.
        Returns True if different, False if equal or no snapshot present.

        Preferred:
            store.config_has_drift(current_config=my_config)

        Legacy:
            store.config_has_drift(current_hash=hash_str)
        """
        snap = self.load_config_snapshot()
        if not snap:
            return False

        saved_hash = snap.get("config_hash")
        if current_config is not None:
            normalized = self._normalize_config(current_config)
            new_hash = self.compute_config_hash(normalized)
            return (saved_hash != new_hash)
        elif current_hash is not None:
            return (saved_hash != current_hash)
        else:
            raise ValueError("Provide either `current_config` or `current_hash`.")

    def _flatten_for_diff(self, obj: Any, prefix: str = "") -> Dict[str, Any]:
        """
        Flatten nested dict/list structures to a {path: value} mapping for diffing.
        Paths use dot notation for dict keys and [idx] for list indices.
        """
        out: Dict[str, Any] = {}
        if isinstance(obj, dict):
            for k in sorted(obj.keys()):
                sub = obj[k]
                path = f"{prefix}.{k}" if prefix else str(k)
                out.update(self._flatten_for_diff(sub, path))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                path = f"{prefix}[{i}]"
                out.update(self._flatten_for_diff(v, path))
        else:
            out[prefix] = obj
        return out

    def config_diff(self, current_config: Any) -> Dict[str, Dict[str, Any]]:
        """
        Return a structured diff between the saved config and `current_config`.

        Returns:
            {
              "added":   {path: value, ...},     # present now, absent before
              "removed": {path: value, ...},     # present before, absent now
              "changed": {path: {"from": old, "to": new}, ...}
            }
        If no snapshot is present, returns all values under "added".
        """
        snap = self.load_config_snapshot()
        normalized_current = self._normalize_config(current_config)

        if not snap or "config" not in snap:
            return {"added": self._flatten_for_diff(normalized_current), "removed": {}, "changed": {}}

        before = self._flatten_for_diff(snap["config"])
        after = self._flatten_for_diff(normalized_current)

        added: Dict[str, Any] = {}
        removed: Dict[str, Any] = {}
        changed: Dict[str, Dict[str, Any]] = {}

        before_keys = set(before.keys())
        after_keys = set(after.keys())

        for k in after_keys - before_keys:
            added[k] = after[k]
        for k in before_keys - after_keys:
            removed[k] = before[k]
        for k in before_keys & after_keys:
            if before[k] != after[k]:
                changed[k] = {"from": before[k], "to": after[k]}

        return {"added": added, "removed": removed, "changed": changed}

    # ---------- Summary export (optional pandas) ----------

    def _try_import_pandas(self):
        try:
            import pandas as pd  # type: ignore
            return pd
        except Exception:
            return None

    def flatten_results(self, results: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Flatten nested per-paper dicts into a row-wise structure for tabular export.
        - Datasets (list of {name,url}) -> semicolon strings
        - Arrays -> semicolon strings
        """
        rows: List[Dict[str, Any]] = []
        for rec in results:
            row: Dict[str, Any] = {}
            # Always carry basic keys if present
            for k in ("doi", "year",
                      "is_computer_vision_in_wildlife_study",
                      "is_computer_vision_in_wildlife_study_review",
                      "is_computer_vision_in_wildlife_study_explanation"):
                if k in rec:
                    row[k] = rec.get(k)

            # Simple arrays -> join
            if isinstance(rec, dict):
                for k, v in rec.items():
                    if k in ("Dataset", "Habitat"):
                        continue
                    if isinstance(v, list) and all(isinstance(x, str) for x in v):
                        row[k] = "; ".join(v)

            # Datasets: list[{"name":..., "url":...}]
            datasets = rec.get("Dataset")
            if isinstance(datasets, list):
                parts = []
                for d in datasets:
                    if isinstance(d, dict):
                        name = d.get("name") or ""
                        url = d.get("url") or ""
                        if url:
                            parts.append(f"{name}<{url}>")
                        else:
                            parts.append(name)
                    else:
                        parts.append(str(d))
                row["Dataset"] = "; ".join(parts)

            # Habitat: list[str]
            habitat = rec.get("Habitat")
            if isinstance(habitat, list):
                row["Habitat"] = "; ".join(map(str, habitat))

            rows.append(row)
        return rows

    def export_summary_csv(self, results: Iterable[Dict[str, Any]], out_csv: Path) -> None:
        rows = self.flatten_results(results)
        if not rows:
            self._atomic_write_text(Path(out_csv), "")
            return

        pd = self._try_import_pandas()
        if pd is not None:
            df = pd.DataFrame(rows)
            out_csv = Path(out_csv)
            out_csv.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(out_csv, index=False)
        else:
            import csv

            out_csv = Path(out_csv)
            out_csv.parent.mkdir(parents=True, exist_ok=True)
            with open(out_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)

    def export_summary_parquet(self, results: Iterable[Dict[str, Any]], out_parquet: Path) -> None:
        pd = self._try_import_pandas()
        if pd is None:
            return
        try:
            rows = self.flatten_results(results)
            if not rows:
                return
            df = pd.DataFrame(rows)
            out_parquet = Path(out_parquet)
            out_parquet.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(out_parquet, index=False)
        except Exception:
            # Optional export should not crash the pipeline
            pass
