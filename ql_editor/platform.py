"""Plattformweichen, an einer Stelle.

Der Rest der App fragt hier nach, statt ``sys.platform`` zu verstreuen.
Die drei Flags schliessen sich aus: genau eines ist wahr.
"""

from __future__ import annotations

import sys

IS_LINUX = sys.platform.startswith("linux")
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

__all__ = ["IS_LINUX", "IS_MAC", "IS_WINDOWS"]
