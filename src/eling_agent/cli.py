"""Entry point for the eling-agent CLI.

Wraps agent.py at the repo root so console_scripts works in both
editable (pip install -e .) and regular install modes.
"""
import os
import sys

_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# agent.py lives at the repo root, one level above src/.
# Only insert if the repo root itself isn't already on sys.path.
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from agent import main  # noqa: E402


__all__ = ["main"]
