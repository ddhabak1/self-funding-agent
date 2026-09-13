"""Entry point.

MODE=night -> run the all-night autonomous factory (scout -> videos -> tune).
MODE=cycle (default) -> run one classic single-article multi-agent cycle.
"""
import os

if __name__ == "__main__":
    mode = os.environ.get("MODE", "cycle").lower()
    if mode == "doctor":
        from .selfheal import doctor
        raise SystemExit(doctor())
    if mode == "night":
        from .night import run_night
        raise SystemExit(run_night())
    from .orchestrator import run_cycle
    make_short = os.environ.get("MAKE_SHORT", "0") == "1"
    raise SystemExit(run_cycle(make_short=make_short))
