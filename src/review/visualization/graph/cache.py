import datetime
import json
from pathlib import Path


def normalize_name(name: str) -> str:
    return " ".join((name or "").strip().split()).lower()

class GBIFCache:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = {"hits": {}, "misses": {}}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
                # Backward/defensive: ensure sections exist
                self.data.setdefault("hits", {})
                self.data.setdefault("misses", {})
            except Exception:
                # Corrupt cache? start fresh but keep the file around
                self.data = {"hits": {}, "misses": {}}

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            print("---- Error saving cache")

    def get(self, name: str):
        key = normalize_name(name)
        if key in self.data["hits"]:
            entry = self.data["hits"][key]
            return entry["chosenKey"], entry.get("match"), True  # found in cache (hit)
        if key in self.data["misses"]:
            miss = self.data["misses"][key]
            return None, miss.get("match"), True  # present in cache (miss)
        return None, None, False  # not in cache

    def put_hit(self, name: str, chosen_key: int, match: dict):
        key = normalize_name(name)
        self.data["hits"][key] = {
            "chosenKey": int(chosen_key),
            "match": match,
            "cachedAt": datetime.datetime.now(datetime.UTC).isoformat() + "Z",
            "originalQuery": name,
        }

    def put_miss(self, name: str, match: dict | None):
        key = normalize_name(name)
        self.data["misses"][key] = {
            "match": match,
            "cachedAt": datetime.datetime.now(datetime.UTC).isoformat() + "Z",
            "originalQuery": name,
        }

