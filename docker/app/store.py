"""SQLite storage: the page's documents (progress, settings, weather, garmin) plus a small cache and key/value store."""
import json
import os
import sqlite3
import threading
import time

DB_PATH = os.getenv("DB_PATH", "/data/kerrchowfit.db")
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS docs (path TEXT PRIMARY KEY, data TEXT NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, stored REAL NOT NULL);
            """
        )
    return _conn


# ---------- documents (what the page reads and writes) ----------
def doc_get(path: str):
    with _lock:
        row = _db().execute("SELECT data FROM docs WHERE path = ?", (path,)).fetchone()
    return json.loads(row[0]) if row else None


def doc_set(path: str, data: dict) -> None:
    with _lock:
        _db().execute(
            "INSERT INTO docs (path, data, updated) VALUES (?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET data = excluded.data, updated = excluded.updated",
            (path, json.dumps(data), time.time()),
        )
        _db().commit()


def doc_merge(path: str, data: dict) -> None:
    cur = doc_get(path) or {}
    cur.update(data)
    doc_set(path, cur)


def doc_delete(path: str) -> None:
    with _lock:
        _db().execute("DELETE FROM docs WHERE path = ?", (path,))
        _db().commit()


def collection(path: str) -> list[dict]:
    """Documents directly inside a collection, e.g. 'progress' -> progress/w1, progress/w2."""
    prefix = path.rstrip("/") + "/"
    with _lock:
        rows = _db().execute("SELECT path, data FROM docs WHERE path LIKE ?", (prefix + "%",)).fetchall()
    out = []
    for p, d in rows:
        rest = p[len(prefix):]
        if rest and "/" not in rest:
            out.append({"id": rest, "data": json.loads(d)})
    return out


# ---------- key/value + cache (tokens, API responses) ----------
def kv_get(key: str):
    with _lock:
        row = _db().execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def kv_put(key: str, value) -> float:
    now = time.time()
    with _lock:
        _db().execute(
            "INSERT INTO kv (key, value, stored) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, stored = excluded.stored",
            (key, json.dumps(value), now),
        )
        _db().commit()
    return now


def cache_get(key: str, max_age: float | None):
    """Returns (value, stored_epoch_seconds) when younger than max_age (None = any age), else None."""
    with _lock:
        row = _db().execute("SELECT value, stored FROM kv WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    if max_age is not None and time.time() - row[1] > max_age:
        return None
    return json.loads(row[0]), row[1]


def cache_put(key: str, value) -> float:
    return kv_put(key, value)
