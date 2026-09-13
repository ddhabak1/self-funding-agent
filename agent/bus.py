"""Inter-agent message bus + shared intel store (SQLite).

Lets the specialized agents (research, trends, content, shorts) communicate:
they post messages and read each other's findings from a shared, persistent
store so the team coordinates across runs.
"""
import json
import sqlite3
import time
from datetime import datetime, timezone

from . import config

DB_PATH = config.STATE_DIR / "agentbus.db"


def _conn():
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT, sender TEXT, topic TEXT, payload TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS intel(
        key TEXT PRIMARY KEY, value TEXT, ts TEXT)""")
    return c


def _now():
    return datetime.now(timezone.utc).isoformat()


def post(sender, topic, payload):
    """An agent broadcasts a message to the team."""
    c = _conn()
    c.execute("INSERT INTO messages(ts,sender,topic,payload) VALUES(?,?,?,?)",
              (_now(), sender, topic, json.dumps(payload)))
    c.commit()
    c.close()
    print(f"[bus] {sender} -> {topic}: "
          f"{json.dumps(payload)[:120]}")


def recent(limit=10):
    c = _conn()
    rows = c.execute(
        "SELECT ts,sender,topic,payload FROM messages ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()
    c.close()
    return [{"ts": r[0], "sender": r[1], "topic": r[2],
             "payload": json.loads(r[3])} for r in rows]


def set_intel(key, value):
    c = _conn()
    c.execute("INSERT INTO intel(key,value,ts) VALUES(?,?,?) "
              "ON CONFLICT(key) DO UPDATE SET value=excluded.value, ts=excluded.ts",
              (key, json.dumps(value), _now()))
    c.commit()
    c.close()


def get_intel(key, default=None):
    c = _conn()
    row = c.execute("SELECT value FROM intel WHERE key=?", (key,)).fetchone()
    c.close()
    return json.loads(row[0]) if row else default
