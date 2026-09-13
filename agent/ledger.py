"""Tracks the agent's money: costs vs. revenue. This is 'survival'."""
import json
from datetime import datetime, timezone

from . import config


def _now():
    return datetime.now(timezone.utc).isoformat()


def load():
    if config.LEDGER_PATH.exists():
        return json.loads(config.LEDGER_PATH.read_text())
    return {"balance": 0.0, "entries": []}


def save(ledger):
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    config.LEDGER_PATH.write_text(json.dumps(ledger, indent=2))


def record(kind, amount, note=""):
    """kind: 'cost' (negative) or 'revenue' (positive)."""
    ledger = load()
    signed = -abs(amount) if kind == "cost" else abs(amount)
    ledger["balance"] = round(ledger["balance"] + signed, 4)
    ledger["entries"].append(
        {"ts": _now(), "kind": kind, "amount": signed, "note": note}
    )
    save(ledger)
    return ledger["balance"]


def balance():
    return load()["balance"]


def is_solvent():
    return balance() >= config.SURVIVAL_THRESHOLD


def summary():
    ledger = load()
    revenue = sum(e["amount"] for e in ledger["entries"] if e["amount"] > 0)
    cost = sum(-e["amount"] for e in ledger["entries"] if e["amount"] < 0)
    return {
        "balance": round(ledger["balance"], 4),
        "total_revenue": round(revenue, 4),
        "total_cost": round(cost, 4),
        "runs": sum(1 for e in ledger["entries"] if e["kind"] == "cost"),
    }
