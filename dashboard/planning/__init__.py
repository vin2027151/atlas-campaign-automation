"""Plan & Adapt layer: state snapshots, plan comparison, changesets, executor.

The one rule: the LLM never touches an ad account. ``planning.llm`` reads a state
document and writes a proposal; ``planning.executor`` (deterministic, no LLM) is the
only path to an ad account, triggered by a human after reading the diff.

This package init stays import-free so ``import planning.executor`` never pulls in
the LLM modules.

``DATA_DIR`` is where planning files persist (snapshots, account overlay). Modules
read it at call time, so tests can repoint it at a temp directory.
"""

import os
import threading

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data", "planning")

# Held for the whole check-then-apply of any account write (a changeset publish or a
# direct Campaigns-page control), so two browsers can't interleave their requests.
ACCOUNT_LOCK = threading.RLock()


def data_path(*parts):
    # type: (*str) -> str
    """Path under DATA_DIR (resolved now, so a repointed DATA_DIR is honoured)."""
    return os.path.join(DATA_DIR, *parts)


def ensure_dir(path):
    # type: (str) -> str
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
    return path
