"""Shared persistence utilities — checksums, atomic writes, file locking.

Provides canonical implementations used by both ``CalibrationPersistence``
and ``CalibrationHistoryStore``.  Consolidates the previously duplicated
``_compute_checksum``, ``_atomic_write``, and adds a lightweight
``FileLock`` for single-writer safety.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Checksum helpers
# ---------------------------------------------------------------------------


def compute_checksum(data: dict[str, Any] | list[Any]) -> str:
    """SHA-256 hex digest of a JSON-serialisable dict or list."""
    raw = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def verify_checksum(data: dict[str, Any] | list[Any], expected: str) -> bool:
    """Return ``True`` if the checksum of *data* matches *expected*."""
    return compute_checksum(data) == expected


# ---------------------------------------------------------------------------
# Atomic write helper
# ---------------------------------------------------------------------------


def atomic_write_json(path: Path, data: Any) -> None:
    """Write *data* as JSON to *path* atomically (tmp -> os.replace).

    Creates parent directories if needed.  Cleans up the temporary file
    on any failure.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=path.stem
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, str(path))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


# ---------------------------------------------------------------------------
# File locking — single-writer safety
# ---------------------------------------------------------------------------

# Stale lock threshold: if a lock file is older than this, it is considered
# abandoned (e.g. process crashed without releasing).
STALE_LOCK_SECONDS: float = 60.0


class FileLock:
    """Lightweight file-based lock for single-writer safety.

    Guarantees:
    - Only one writer at a time (atomic lock-file creation)
    - Stale locks are automatically reclaimed
    - Read operations are never blocked
    - Lock is always released on normal exit and on exception

    Mutual exclusion is provided by atomic ``os.open`` with
    ``O_CREAT | O_EXCL``, which works on both POSIX and Windows.
    The lock file contains the owning PID to prevent accidental
    release of another process's lock.

    This is **thread-safe** (within a single process) when used as a
    context manager, and **cross-process** safe via the atomic file
    creation.

    Usage::

        with FileLock(directory / ".lock"):
            # exclusive write section
            ...
    """

    def __init__(
        self,
        lock_path: Path,
        *,
        timeout: float = 10.0,
        stale_after: float = STALE_LOCK_SECONDS,
    ) -> None:
        self._lock_path = lock_path
        self._timeout = timeout
        self._stale_after = stale_after

    def acquire(self) -> None:
        """Acquire the lock, blocking up to *timeout* seconds.

        The lock file contains the owning PID so that :meth:`release`
        can verify ownership before removing the file.
        """
        deadline = time.monotonic() + self._timeout
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)

        while True:
            try:
                fd = os.open(
                    str(self._lock_path),
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o644,
                )
                try:
                    content = f"{os.getpid()}\n{time.time()}\n"
                    os.write(fd, content.encode())
                finally:
                    os.close(fd)
                _logger.debug("Lock acquired: %s", self._lock_path)
                return
            except FileExistsError:
                if self._is_stale():
                    _logger.warning(
                        "Stale lock detected, reclaiming: %s", self._lock_path
                    )
                    self._force_remove()
                    continue

                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Could not acquire lock {self._lock_path} "
                        f"within {self._timeout}s"
                    ) from None
                time.sleep(0.05)
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Could not acquire lock {self._lock_path} "
                        f"within {self._timeout}s"
                    ) from None
                time.sleep(0.05)

    def release(self) -> None:
        """Release the lock.

        Only removes the lock file if it was created by this process
        (PID match).  Prevents accidentally releasing another process's
        lock when locks overlap due to stale-lock reclamation.
        """
        try:
            content = self._lock_path.read_text(encoding="utf-8")
            stored_pid = int(content.split("\n")[0])
        except (OSError, ValueError):
            stored_pid = -1

        if stored_pid == os.getpid():
            self._force_remove()
            _logger.debug("Lock released: %s", self._lock_path)
        else:
            _logger.warning(
                "Lock held by PID %d (not %d), skipping release: %s",
                stored_pid,
                os.getpid(),
                self._lock_path,
            )

    def _is_stale(self) -> bool:
        """Return True if the lock file is older than *stale_after* seconds."""
        try:
            mtime = os.path.getmtime(str(self._lock_path))
            return (time.time() - mtime) > self._stale_after
        except OSError:
            return False

    def _force_remove(self) -> None:
        """Remove the lock file if it exists."""
        with contextlib.suppress(OSError):
            os.unlink(str(self._lock_path))

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()
