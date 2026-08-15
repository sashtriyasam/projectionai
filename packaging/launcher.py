"""Entry script for the packaged desktop application.

PyInstaller executes this file; it hands control to the real
``main`` entry point so the packaged exe behaves exactly like
``python -m projectionai``.
"""

from __future__ import annotations

import sys

from projectionai.main import main

if __name__ == "__main__":
    sys.exit(main())
