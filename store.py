"""Tiny JSON-file persistence: the merch approval queue, an activity log, and the set of photos already handled."""
import json
import os
import threading
import time
from config import DATA_DIR

_MAX_ACTIVITY = 500


class Store:
    def __init__(self, data_dir: str = DATA_DIR):
        self.dir = data_dir
        os.makedirs(self.dir, exist_ok=True)
        self._lock = threading.RLock()
        self.pending: dict[str, dict] = self._read("pending.json", {})
        self.activity: list[dict] = self._read("activity.json", [])
        self.processed_media: set[str] = set(self._read("processed_media.json", []))

    def _path(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def _read(self, name, default):
        try:
            with open(self._path(name)) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    def _write(self, name, value):
        tmp = self._path(name + ".tmp")
        with open(tmp, "w") as f:
            json.dump(value, f, indent=1, ensure_ascii=False)
        os.replace(tmp, self._path(name))

    # -- pending SEO copy awaiting merch approval ---------------------------------
    def add_pending(self, product_id: int, record: dict) -> None:
        with self._lock:
            self.pending[str(product_id)] = {**record, "product_id": int(product_id), "created_at": time.time()}
            self._write("pending.json", self.pending)

    def remove_pending(self, product_ids) -> None:
        with self._lock:
            for pid in product_ids:
                self.pending.pop(str(pid), None)
            self._write("pending.json", self.pending)

    def get_pending(self) -> list[dict]:
        with self._lock:
            return sorted(self.pending.values(), key=lambda r: r["created_at"], reverse=True)

    def is_pending(self, product_id: int) -> bool:
        return str(product_id) in self.pending

    # -- activity log -----------------------------------------------------------------
    def log(self, event: str, **details) -> None:
        with self._lock:
            self.activity.append({"ts": time.time(), "event": event, **details})
            del self.activity[:-_MAX_ACTIVITY]
            self._write("activity.json", self.activity)

    def get_activity(self, limit: int = 200) -> list[dict]:
        with self._lock:
            return list(reversed(self.activity[-limit:]))

    # -- photos already tagged by the webhook (prevents re-processing loops) ------------
    def mark_media_processed(self, key) -> None:
        with self._lock:
            self.processed_media.add(str(key))
            self._write("processed_media.json", sorted(self.processed_media))

    def is_media_processed(self, key) -> bool:
        return str(key) in self.processed_media


store = Store()
