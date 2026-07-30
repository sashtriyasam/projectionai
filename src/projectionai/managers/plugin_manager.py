"""Plugin manager — capability-based plugin lifecycle management.

Wraps the ``PluginRegistry`` and integrates with the event bus:
- Load/unload plugins by name
- Query by capability
- Emit lifecycle events on plugin state changes

Supports both entry-point discovery and directory scanning.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, override

from projectionai.core.errors import PluginNotFoundError
from projectionai.core.events import EventBus, PluginError, PluginLoaded, PluginUnloaded
from projectionai.core.plugin import (
    PluginDescriptor,
    PluginRegistry,
    get_registry,
)
from projectionai.managers import Manager

_logger = logging.getLogger(__name__)


class PluginManager(Manager):
    """Manages plugin registration, discovery, and lifecycle.

    Delegates to the global ``PluginRegistry`` singleton and extends it
    with event bus integration and manager-level lifecycle.
    """

    def __init__(
        self,
        event_bus: EventBus,
        plugin_dirs: list[Path] | None = None,
        registry: PluginRegistry | None = None,
    ) -> None:
        super().__init__(event_bus)
        self._owns_registry: bool = registry is not None
        self._registry: PluginRegistry = (
            registry if registry is not None else get_registry()
        )
        self._plugin_dirs: list[Path] = plugin_dirs or []

    # -- Registry access ----------------------------------------------------

    @property
    def registry(self) -> PluginRegistry:
        """Return the underlying plugin registry."""
        return self._registry

    @property
    def names(self) -> list[str]:
        """Return sorted list of registered plugin names."""
        return self._registry.names

    @property
    def capabilities(self) -> list[str]:
        """Return all unique capability identifiers."""
        return self._registry.capabilities

    # -- Registration -------------------------------------------------------

    def register(self, descriptor: PluginDescriptor) -> None:
        """Register a plugin descriptor.

        Delegates to the underlying ``PluginRegistry``.
        """
        self._registry.register(descriptor)

    def unregister(self, name: str) -> None:
        """Unregister a plugin by name.

        Delegates to the underlying ``PluginRegistry``.
        """
        self._registry.unregister(name)

    # -- Discovery ----------------------------------------------------------

    def discover_entry_points(self) -> list[PluginDescriptor]:
        """Discover plugins via entry points."""
        return self._registry.discover_entry_points()

    def discover_directories(self) -> list[PluginDescriptor]:
        """Scan configured plugin directories for plugins."""
        discovered: list[PluginDescriptor] = []
        for directory in self._plugin_dirs:
            discovered.extend(self._registry.discover_package(directory))
        return discovered

    def discover_all(self) -> list[PluginDescriptor]:
        """Run all discovery methods and return the combined results."""
        result: list[PluginDescriptor] = []
        result.extend(self.discover_entry_points())
        result.extend(self.discover_directories())
        return result

    # -- Capability lookup --------------------------------------------------

    def get_by_capability(self, capability: str) -> list[PluginDescriptor]:
        """Return descriptors for plugins supporting *capability*."""
        return self._registry.get_by_capability(capability)

    def get_instances_by_capability(self, capability: str) -> list[Any]:
        """Return instances for plugins supporting *capability*."""
        return self._registry.get_instances_by_capability(capability)

    def has_capability(self, capability: str) -> bool:
        """Return ``True`` if at least one plugin supports *capability*."""
        return self._registry.has_capability(capability)

    # -- Lifecycle ----------------------------------------------------------

    async def load(self, name: str) -> None:
        """Load (initialize) a specific plugin.

        Emits ``PluginLoaded`` on success, ``PluginError`` on failure.
        """
        self._require_initialized()
        try:
            await self._registry.load_plugin(name)
            desc = self._registry.get(name)
            caps = ",".join(desc.capabilities) if desc else ""
            await self._event_bus.emit(
                PluginLoaded(
                    plugin_name=name,
                    capability=caps,
                )
            )
        except PluginNotFoundError:
            raise
        except Exception as exc:
            await self._event_bus.emit(PluginError(plugin_name=name, error=str(exc)))
            raise

    async def unload(self, name: str) -> None:
        """Unload (shut down) a specific plugin.

        Preserves the plugin descriptor for future reloads.
        Emits ``PluginUnloaded``.
        """
        self._require_initialized()
        desc = self._registry.get(name)
        if desc is None:
            return
        instance = desc.instance
        if instance is not None and hasattr(instance, "shutdown"):
            try:
                await instance.shutdown()
            except Exception as exc:
                _logger.warning("Error shutting down plugin %s: %s", name, exc)
        object.__setattr__(desc, "instance", None)
        await self._event_bus.emit(PluginUnloaded(plugin_name=name))

    # -- Manager lifecycle --------------------------------------------------

    @override
    async def _on_initialize(self) -> None:
        discovered: list[PluginDescriptor] = []
        try:
            discovered = self.discover_all()
        except Exception as exc:
            _logger.warning("Plugin discovery failed: %s", exc)
        _logger.info("Discovered %d plugin(s)", len(discovered))

    @override
    async def _on_shutdown(self) -> None:
        if self._owns_registry:
            await self._registry.shutdown_all()
        else:
            _logger.debug("Skipping shutdown_all on shared default registry")
