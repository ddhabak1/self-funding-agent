"""Git auto-publish for non-CI (VM / container) deployments.

In GitHub Actions the workflow commits + pushes the new site. But when the
agent runs 24x7 on your own box (via agent/watchdog.py), nothing pushes the
freshly generated posts + learned state back to GitHub Pages. This module is
that missing piece: when AUTO_PUSH=1, it commits `docs/` + `state/` and pushes.

Safe by design: best-effort, never fatal to the run. Auth is whatever git is
already configured with on the host (a PAT-embedded remote or a credential
helper — see deploy/DEPLOY.md). Set GIT_AUTHOR_* via env if you want.
"""
import os
import subprocess
from datetime import datetime, timezone

from . import config

_PATHS = ["docs", "state"]


def _run(args):
    return subprocess.run(args, cwd=str(config.ROOT), capture_output=True,
                          text=True, timeout=180)


def push_if_enabled(note="autopublish"):
    """Commit docs+state and push, only when AUTO_PUSH=1. Returns True on push."""
    if os.environ.get("AUTO_PUSH", "0") != "1":
        return False
    try:
        name = os.environ.get("GIT_AUTHOR_NAME", "self-funding-agent")
        email = os.environ.get("GIT_AUTHOR_EMAIL",
                               "agent@users.noreply.github.com")
        _run(["git", "config", "user.name", name])
        _run(["git", "config", "user.email", email])
        _run(["git", "add", *_PATHS])
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        commit = _run(["git", "commit", "-m",
                       f"agent: {note} ({stamp})"])
        if commit.returncode != 0 and "nothing to commit" in (
                commit.stdout + commit.stderr).lower():
            print("[gitsync] nothing new to publish")
            return False
        # integrate any CI-side commits, then publish
        _run(["git", "pull", "--rebase", "--autostash"])
        push = _run(["git", "push"])
        if push.returncode == 0:
            print("[gitsync] published to remote")
            return True
        print(f"[gitsync] push failed: {(push.stderr or '')[:160]}")
        return False
    except Exception as e:
        print(f"[gitsync] skipped: {str(e)[:160]}")
        return False
