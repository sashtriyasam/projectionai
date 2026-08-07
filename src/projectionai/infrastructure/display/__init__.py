"""Display enumeration, full-screen pattern projection, and providers.

Legacy calibration backend (unchanged):
- :func:`list_displays` / :class:`DisplayInfo` / :class:`DisplayError`
  / :class:`QtPatternProjector` — used by the real-hardware validation
  workflow (detect displays, pick the projector, show structured light
  patterns, blank afterwards).

Hardware subsystem providers (new):
- :class:`QtDisplayProvider` — real topology enumeration via ``QScreen``
- :class:`MockDisplayProvider` — simulated topology for tests/demos

Importing this package registers both providers with
``DisplayProviderFactory``.
"""

from projectionai.infrastructure.display.mock_provider import (
    MockDisplayProvider,
    default_displays,
    make_display,
)
from projectionai.infrastructure.display.qt import (
    DisplayError,
    DisplayInfo,
    QtPatternProjector,
    list_displays,
)
from projectionai.infrastructure.display.qt_provider import QtDisplayProvider
from projectionai.services.display import DisplayProviderFactory

DisplayProviderFactory.register("mock", MockDisplayProvider)
DisplayProviderFactory.register("qt", QtDisplayProvider)

__all__ = [
    "DisplayError",
    "DisplayInfo",
    "MockDisplayProvider",
    "QtDisplayProvider",
    "QtPatternProjector",
    "default_displays",
    "list_displays",
    "make_display",
]
