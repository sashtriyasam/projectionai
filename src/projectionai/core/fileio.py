"""Crash-safe file writing helpers.

Writes go to a temporary file in the destination directory, are flushed
and fsynced, then moved into place with :func:`os.replace`. A crash or
power loss mid-write therefore leaves either the previous file or the
new one on disk — never a truncated mix of both.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write *text* to *path* atomically (tmp -> fsync -> os.replace).

    Creates parent directories if needed and removes the temporary file
    on any failure.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=path.stem
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, str(path))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def atomic_write_json(path: Path, data: Any) -> None:
    """Write *data* as indented JSON to *path* atomically."""
    atomic_write_text(path, json.dumps(data, indent=2, default=str))
