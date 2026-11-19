"""Unit tests must be able to import `backend.*` and `src.*` modules.

The project root is already added by the top-level tests/conftest.py
(which applies recursively); this file makes the guarantee explicit for
the unit directory per CLAUDE.md "Test Organization" convention.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
