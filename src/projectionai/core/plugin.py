"""Capability-based plugin system.

Instead of classifying plugins by provider name (e.g. "gemini", "openai"),
plugins declare *capabilities* they support. Capabilities are well-known
strings that map to interface protocols::

    class MyLLM:
        async def generate(self, prompt: str) -> str: ...

    registry.register("my-llm", MyLLM(), capabilities=["llm_provider"])

Other parts of the application query by capability, not by name::

    for plugin in registry.get_by_capability("llm_provider"):
        await plugin.generate(prompt)

Design decisions:
- Capabilities are strings (not enums) so external plugins can declare
  new capabilities without updating the core.
- Plugins are registered as instances (not factories) — they are created
  by the plugin author and registered after construction.
- Discovery uses entry-point groups (``projectionai.plugins``) and
  directory scanning for external Python modules.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
import sys
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from projectionai.core.errors import (
    PluginConflictError,
    PluginLoadError,
    PluginNotFoundError,
)

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Well-known capability identifiers
# ---------------------------------------------------------------------------

# AI / LLM
CAP_LLM_PROVIDER = "llm_provider"
CAP_IMAGE_GENERATOR = "image_generator"

# Vision / geometry
CAP_DEPTH_ESTIMATOR = "depth_estimator"
CAP_SEGMENTER = "segmenter"

# Rendering / output
CAP_RENDERER = "renderer"
CAP_AUDIO_PROVIDER = "audio_provider"

# Calibration
CAP_CALIBRATION_PROVIDER = "calibration_provider"


# ---------------------------------------------------------------------------
# Plugin descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PluginDescriptor:
    """Metadata about a registered plugin."""

    name: str
    version: str = "0.1.0"
    description: str = ""
    capabilities: tuple[str, ...] = ()
    instance: Any = None
    factory: Callable[..., Any] | None = None


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------


def make_register(
    name: str,
    version: str,
    description: str,
    factory: type,
) -> Callable[[PluginRegistry], Coroutine[None, None, None]]:
    """Return an async ``register(registry)`` entry point for a provider.

    Usage in a provider module::

        register = make_register(
            name="my-provider",
            version="0.1.0",
            description="My AI provider",
            factory=MyProvider,
        )
    """
    capabilities = ("llm_provider",)

    async def register(registry: PluginRegistry) -> None:
        registry.register(
            PluginDescriptor(
                name=name,
                version=version,
                description=description,
                capabilities=capabilities,
                factory=factory,
            )
        )

    return register


# ---------------------------------------------------------------------------
# Instance protocols (structural typing for plugins)
# ---------------------------------------------------------------------------


class Plugin(Protocol):
    """Minimal protocol for any plugin instance."""

    @property
    def name(self) -> str: ...

    async def initialize(self) -> None: ...

    async def shutdown(self) -> None: ...


class LLMProvider(Protocol):
    """Plugin that provides LLM text generation."""

    async def generate(self, prompt: str, **kwargs: Any) -> str: ...


class ImageGenerator(Protocol):
    """Plugin that provides image generation."""

    async def generate_image(self, prompt: str, **kwargs: Any) -> bytes: ...


class DepthEstimator(Protocol):
    """Plugin that estimates depth from an image."""

    async def estimate_depth(self, image: bytes, **kwargs: Any) -> Any: ...


class Segmenter(Protocol):
    """Plugin that segments an image into regions."""

    async def segment(self, image: bytes, **kwargs: Any) -> Any: ...


class Renderer(Protocol):
    """Plugin that renders a scene to an image/stream."""

    async def render(self, scene_data: Any, **kwargs: Any) -> bytes: ...


class AudioProvider(Protocol):
    """Plugin that provides audio generation/processing."""

    async def generate_audio(self, text: str, **kwargs: Any) -> bytes: ...


class CalibrationProvider(Protocol):
    """Plugin that provides calibration algorithms."""

    async def calibrate(self, image_data: list[bytes], **kwargs: Any) -> Any: ...


# ---------------------------------------------------------------------------
# Capability-based registry
# ---------------------------------------------------------------------------


class PluginRegistry:
    """Holds all registered plugins, indexed by name and capability."""

    def __init__(self) -> None:
        self._descriptors: dict[str, PluginDescriptor] = {}
        self._capability_index: dict[str, list[str]] = defaultdict(list)

    # -- Registration -------------------------------------------------------

    def register(
        self,
        descriptor: PluginDescriptor,
    ) -> None:
        """Register a plugin descriptor.

        Raises ``PluginConflictError`` if *name* is already registered.
        Raises ``PluginConflictError`` if another plugin already registered
        the same capability with the same name.
        """
        if descriptor.name in self._descriptors:
            raise PluginConflictError(
                f"Plugin {descriptor.name!r} is already registered",
            )
        self._descriptors[descriptor.name] = descriptor
        for cap in descriptor.capabilities:
            self._capability_index[cap].append(descriptor.name)
        _logger.info(
            "Registered plugin: %s v%s capabilities=%s",
            descriptor.name,
            descriptor.version,
            list(descriptor.capabilities),
        )

    def unregister(self, name: str) -> None:
        """Remove a previously registered plugin."""
        desc = self._descriptors.pop(name, None)
        if desc is not None:
            for cap in desc.capabilities:
                if name in self._capability_index[cap]:
                    self._capability_index[cap].remove(name)

    # -- Discovery ----------------------------------------------------------

    def discover_entry_points(self) -> list[PluginDescriptor]:
        """Discover plugins via the ``projectionai.plugins`` entry-point group.

        Each entry point should return a ``PluginDescriptor`` or a
        callable that returns one.
        """
        discovered: list[PluginDescriptor] = []
        try:
            from importlib.metadata import entry_points

            eps = entry_points(group="projectionai.plugins")
            for ep in eps:
                try:
                    plugin = ep.load()
                    if isinstance(plugin, PluginDescriptor):
                        desc: PluginDescriptor = plugin
                    elif callable(plugin):
                        result = plugin()
                        if not isinstance(result, PluginDescriptor):
                            _logger.warning(
                                "Entry-point %s callable returned unexpected type %s",
                                ep.name,
                                type(result).__name__,
                            )
                            continue
                        desc = result
                    else:
                        _logger.warning(
                            "Entry-point %s returned unexpected type %s",
                            ep.name,
                            type(plugin).__name__,
                        )
                        continue
                    self.register(desc)
                    discovered.append(desc)
                except Exception as exc:
                    _logger.warning(
                        "Failed to load entry-point plugin %s: %s", ep.name, exc
                    )
        except Exception:
            _logger.debug("Entry-point discovery not available")
        return discovered

    def discover_package(self, package_path: Path) -> list[PluginDescriptor]:
        """Discover plugins by scanning a directory for Python modules
        that expose a ``create_plugin`` function returning a PluginDescriptor."""
        discovered: list[PluginDescriptor] = []
        if not package_path.is_dir():
            return discovered

        for _finder, module_name, _ispkg in pkgutil.iter_modules([str(package_path)]):
            mod_key = f"projectionai.plugins.{module_name}"
            try:
                mod_path = str(package_path / f"{module_name}.py")
                spec = importlib.util.spec_from_file_location(module_name, mod_path)
                if spec is None or spec.loader is None:
                    _logger.warning("Could not load spec for plugin %s", module_name)
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[mod_key] = module
                spec.loader.exec_module(module)

                if hasattr(module, "create_plugin") and callable(module.create_plugin):
                    desc = module.create_plugin()
                    if isinstance(desc, PluginDescriptor):
                        self.register(desc)
                        discovered.append(desc)
            except Exception as exc:
                sys.modules.pop(mod_key, None)
                _logger.warning("Failed to scan plugin %s: %s", module_name, exc)

        return discovered

    # -- Lookup by name -----------------------------------------------------

    def get(self, name: str) -> PluginDescriptor | None:
        """Return the descriptor for *name*, or ``None``."""
        return self._descriptors.get(name)

    def get_instance(self, name: str) -> Any:
        """Return the plugin instance for *name*.

        Raises ``PluginNotFoundError`` if not registered.
        """
        desc = self._descriptors.get(name)
        if desc is None:
            raise PluginNotFoundError(f"Plugin {name!r} is not registered")
        return desc.instance

    # -- Lookup by capability -----------------------------------------------

    def get_by_capability(self, capability: str) -> list[PluginDescriptor]:
        """Return all plugin descriptors that support *capability*."""
        names = self._capability_index.get(capability, [])
        return [self._descriptors[n] for n in names if n in self._descriptors]

    def get_instances_by_capability(self, capability: str) -> list[Any]:
        """Return all plugin instances that support *capability*."""
        return [
            desc.instance
            for desc in self.get_by_capability(capability)
            if desc.instance is not None
        ]

    def has_capability(self, capability: str) -> bool:
        """Return ``True`` if at least one plugin supports *capability*."""
        return len(self._capability_index.get(capability, [])) > 0

    # -- Properties ---------------------------------------------------------

    @property
    def names(self) -> list[str]:
        """Return sorted list of registered plugin names."""
        return sorted(self._descriptors)

    @property
    def descriptors(self) -> list[PluginDescriptor]:
        """Return all registered descriptors."""
        return list(self._descriptors.values())

    @property
    def capabilities(self) -> list[str]:
        """Return all unique capability identifiers."""
        return sorted(self._capability_index)

    # -- Lifecycle ----------------------------------------------------------

    async def load_plugin(self, name: str) -> None:
        """Initialize a registered plugin's instance.

        The plugin's instance is expected to have an ``initialize`` method.
        The initialized instance is stored on the descriptor.
        """
        desc = self._descriptors.get(name)
        if desc is None:
            raise PluginNotFoundError(f"Plugin {name!r} is not registered")

        instance = desc.instance
        if instance is None:
            if desc.factory is not None:
                instance = desc.factory()
                object.__setattr__(desc, "instance", instance)
            else:
                raise PluginLoadError(
                    f"Plugin {name!r} has no instance set on descriptor"
                )

        if hasattr(instance, "initialize"):
            try:
                await instance.initialize()
                _logger.info("Initialized plugin: %s", name)
            except Exception as exc:
                raise PluginLoadError(
                    f"Failed to initialize plugin {name!r}: {exc}"
                ) from exc

    async def load_all(self) -> None:
        """Initialize all registered plugins that have instances."""
        for name in list(self._descriptors):
            try:
                await self.load_plugin(name)
            except Exception:
                _logger.exception("Failed to load plugin %s", name)

    async def shutdown_all(self) -> None:
        """Shut down all loaded plugin instances."""
        for name, desc in self._descriptors.items():
            instance = desc.instance
            if instance is not None and hasattr(instance, "shutdown"):
                try:
                    await instance.shutdown()
                except Exception as exc:
                    _logger.warning("Error shutting down plugin %s: %s", name, exc)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_registry: PluginRegistry | None = None


def get_registry() -> PluginRegistry:
    """Return the global plugin registry singleton."""
    global _registry
    if _registry is None:
        _registry = PluginRegistry()
    return _registry


def reset_registry() -> None:
    """Reset the registry (primarily for testing)."""
    global _registry
    _registry = None
