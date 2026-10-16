"""Sorgt dafuer, dass das Repo-Root importierbar ist (``import ql_editor``)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
