"""Display abstraction.

Device-agnostic interface for enumerating displays and their video
modes. Concrete implementations (Qt, mock, future platform APIs such as
Windows EnumDisplayDevices / macOS CGDisplay / Linux XRandR) live in
``infrastructure.display`` and are created through
:class:`DisplayProviderFactory`.

The abstraction is deliberately free of Qt and windowing concepts:
managers consume :class:`DisplayInfo` models and drive window
operations through the structural :class:`OutputWindow` protocol.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from projectionai.hardware.models import (
    DisplayCapabilities,
    DisplayInfo,
    DisplayMode,
)


class DisplayProvider(ABC):
    """Abstract display source: discovers displays and their modes.

    Providers never raise for missing hardware — an empty result set
    means "no displays". Operations that target a display that
    disappeared raise :class:`DisplayNotFoundError`.
    """

    #: Registered provider name (used by the factory).
    name: ClassVar[str] = "display"

    @abstractmethod
    async def list_displays(self) -> list[DisplayInfo]:
        """Enumerate all currently connected displays.

        Returns:
            Fresh metadata for each detected display, classified via
            the default classifier unless the provider sets ``kind``.
            Empty list when no displays are available.
        """

    async def get_modes(self, display_id: str) -> tuple[DisplayMode, ...]:
        """Return the selectable modes for *display_id*.

        Defaults to the display's reported ``supported_modes``. Raise
        :class:`DisplayNotFoundError` when unknown.
        """
        info = self._require(display_id)
        return info.supported_modes

    async def identify(self, display_id: str) -> None:  # noqa: B027 - intentional no-op default
        """Flash/identify *display_id* (no-op when unsupported)."""

    def capabilities(self, display_id: str) -> DisplayCapabilities:
        """Return the capabilities of *display_id* (cached query)."""
        info = self._require(display_id)
        return info.capabilities

    def _require(self, display_id: str) -> DisplayInfo:
        raise NotImplementedError


class DisplayProviderFactory:
    """Creates display providers by backend name."""

    _registry: ClassVar[dict[str, type[DisplayProvider]]] = {}

    @classmethod
    def register(cls, name: str, provider_cls: type[DisplayProvider]) -> None:
        """Register a provider class under *name*."""
        cls._registry[name] = provider_cls

    @classmethod
    def create(cls, name: str, **kwargs: object) -> DisplayProvider:
        """Create a provider instance by registered name."""
        if name not in cls._registry:
            cls._ensure_builtin_providers()
        if name not in cls._registry:
            msg = (
                f"Unknown display provider: {name!r}. Available: {list(cls._registry)}"
            )
            raise ValueError(msg)
        return cls._registry[name](**kwargs)

    @classmethod
    def _ensure_builtin_providers(cls) -> None:
        """Register the built-in ``mock``/``qt`` providers on demand.

        Importing the provider modules registers their classes with this
        factory, so ``create()`` works regardless of whether the
        ``infrastructure.display`` package was imported first.
        """
        from projectionai.infrastructure.display.mock_provider import (
            MockDisplayProvider,
        )
        from projectionai.infrastructure.display.qt_provider import (
            QtDisplayProvider,
        )

        cls.register("mock", MockDisplayProvider)
        cls.register("qt", QtDisplayProvider)

    @classmethod
    def available(cls) -> tuple[str, ...]:
        """Return all registered provider names."""
        return tuple(sorted(cls._registry))
