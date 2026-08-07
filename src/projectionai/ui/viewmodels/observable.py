"""Observable base class for viewmodels.

Provides a poll-based notification pattern: widgets call ``subscribe``
with a no-arg callback, then read ``revision`` on a timer to decide
whether to re-render.  The ``_notify`` method bumps the revision and
fires every registered handler.

Subclasses call ``self._notify()`` after each mutation.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

_logger = logging.getLogger(__name__)

PollHandler = Callable[[], None]


class Observable:
    """Mixin that adds subscribe/unsubscribe/revision to a viewmodel."""

    def __init__(self) -> None:
        self._handlers: list[PollHandler] = []
        self._revision: int = 0

    # -- Observation ----------------------------------------------------------

    @property
    def revision(self) -> int:
        """Increment on every mutation (poll target)."""
        return self._revision

    def subscribe(self, handler: PollHandler) -> None:
        """Register a callback invoked after every mutation."""
        if handler not in self._handlers:
            self._handlers.append(handler)

    def unsubscribe(self, handler: PollHandler) -> None:
        """Remove a previously registered callback."""
        if handler in self._handlers:
            self._handlers.remove(handler)

    def _notify(self) -> None:
        self._revision += 1
        for handler in list(self._handlers):
            try:
                handler()
            except Exception:
                _logger.exception("Poll handler %r failed", handler)
