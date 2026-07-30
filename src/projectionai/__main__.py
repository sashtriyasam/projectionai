"""Allows ``python -m projectionai`` to work by forwarding to ``main()``."""

from __future__ import annotations

import sys

from projectionai.main import main

if __name__ == "__main__":
    sys.exit(main())
