"""The agent loop: observe -> decide -> act -> account for money."""
import json

from . import config, ledger
from .brain import Brain
from .content import create_content
from .publish import publish


def _load_memory():
    if config.MEMORY_PATH.exists():
        return json.loads(config.MEMORY_PATH.read_text())
    return {"recent_titles": []}


def _save_memory(mem):
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    config.MEMORY_PATH.write_text(json.dumps(mem, indent=2))


def run_once():
    print("=== Agent waking up ===")
    bal = ledger.balance()
    print(f"Balance: ${bal:.4f} | solvent: {ledger.is_solvent()}")

    if not ledger.is_solvent():
        print("!! Below survival threshold. Halting to avoid running up costs.")
        print("   Fund the ledger or wire real revenue, then resume.")
        return 1

    brain = Brain()
    print(f"Brain online: {brain.online} (model={config.GEMINI_MODEL})")

    memory = _load_memory()

    # ACT: create + publish content (the 'work' that should earn money).
    post = create_content(brain, memory)
    path = publish(post)
    print(f"Published: {path.name} -> {post['title']}")

    # ACCOUNT: record the cost of this run.
    ledger.record("cost", config.COST_PER_RUN, note=f"run: {post['slug']}")

    # Revenue hook: real income arrives asynchronously (affiliate/ad payouts).
    # Wire ingest_revenue() to a real webhook/report when available.
    ingest_revenue()

    memory["recent_titles"] = (memory.get("recent_titles", []) + [post["title"]])[-30:]
    _save_memory(memory)

    print("Ledger:", ledger.summary())
    print("=== Agent sleeping ===")
    return 0


def ingest_revenue():
    """Placeholder for real payouts. Replace with a real data source:
    - Amazon/affiliate report API
    - AdSense/Ezoic earnings API
    - Ko-fi / Stripe webhook totals
    For now it records nothing (honest $0)."""
    return 0.0


if __name__ == "__main__":
    raise SystemExit(run_once())
