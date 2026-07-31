"""Tests for PluginManager."""

from __future__ import annotations

from pathlib import Path

import pytest

from projectionai.core.errors import PluginNotFoundError
from projectionai.core.events import PluginLoaded, PluginUnloaded
from projectionai.core.plugin import (
    PluginDescriptor,
    reset_registry,
)
from projectionai.managers.plugin_manager import PluginManager


class _DummyLLMProvider:
    """A minimal test LLM provider plugin."""

    async def generate(self, prompt: str) -> str:
        return f"Response to: {prompt}"


def _make_descriptor(
    name: str = "test-plugin",
    capabilities: tuple[str, ...] = ("llm_provider",),
) -> PluginDescriptor:
    return PluginDescriptor(
        name=name,
        capabilities=capabilities,
    )


def _make_descriptor_with_instance(
    name: str = "test-plugin",
    capabilities: tuple[str, ...] = ("llm_provider",),
    instance: object = None,
) -> PluginDescriptor:
    return PluginDescriptor(
        name=name,
        capabilities=capabilities,
        instance=instance,
    )


@pytest.fixture(autouse=True)
def _registry_isolation():
    try:
        yield
    finally:
        reset_registry()


@pytest.fixture
async def manager(event_bus) -> PluginManager:
    reset_registry()
    m = PluginManager(event_bus)
    await m.initialize()
    return m


class TestPluginManagerRegistration:
    """Registering and unregistering plugins."""

    async def test_register(self, manager: PluginManager) -> None:
        desc = _make_descriptor("simple")
        manager.register(desc)

        assert "simple" in manager.names

    async def test_unregister(self, manager: PluginManager) -> None:
        manager.register(_make_descriptor("bye"))
        manager.unregister("bye")

        assert "bye" not in manager.names

    async def test_unregister_nonexistent(self, manager: PluginManager) -> None:
        manager.unregister("ghost")  # should not raise

    async def test_names_sorted(self, manager: PluginManager) -> None:
        for name in ["z_last", "a_first", "m_mid"]:
            manager.register(_make_descriptor(name))

        assert manager.names == ["a_first", "m_mid", "z_last"]


class TestPluginManagerCapabilities:
    """Capability-based lookup."""

    async def test_capabilities_list(self, manager: PluginManager) -> None:
        d1 = _make_descriptor("p1", ("llm_provider", "image_generator"))
        manager.register(d1)

        d2 = _make_descriptor("p2", ("llm_provider",))
        manager.register(d2)

        caps = manager.capabilities
        assert "llm_provider" in caps
        assert "image_generator" in caps

    async def test_get_by_capability(self, manager: PluginManager) -> None:
        manager.register(_make_descriptor("p1", ("llm_provider",)))
        manager.register(_make_descriptor("p2", ("renderer",)))

        results = manager.get_by_capability("llm_provider")
        assert len(results) == 1
        assert results[0].name == "p1"

    async def test_get_by_capability_none(self, manager: PluginManager) -> None:
        assert manager.get_by_capability("nonexistent") == []

    async def test_has_capability(self, manager: PluginManager) -> None:
        manager.register(_make_descriptor("test", ("llm_provider",)))

        assert manager.has_capability("llm_provider")
        assert not manager.has_capability("renderer")

    async def test_get_instances_by_capability(self, manager: PluginManager) -> None:
        instance = _DummyLLMProvider()
        desc = _make_descriptor_with_instance(
            "provider",
            ("llm_provider",),
            instance=instance,
        )
        manager.register(desc)

        instances = manager.get_instances_by_capability("llm_provider")
        assert len(instances) == 1
        assert instances[0] is instance

    async def test_get_instances_capability_empty(self, manager: PluginManager) -> None:
        assert manager.get_instances_by_capability("missing") == []


class TestPluginManagerDiscovery:
    """Plugin discovery mechanisms."""

    async def test_discover_entry_points(self, manager: PluginManager) -> None:
        plugins = manager.discover_entry_points()
        assert isinstance(plugins, list)

    async def test_discover_directories_nonexistent(
        self, manager: PluginManager
    ) -> None:
        """Scanning a nonexistent directory should yield empty results."""
        manager._plugin_dirs = [Path("/nonexistent/plugins")]
        plugins = manager.discover_directories()
        assert plugins == []

    async def test_discover_all(self, manager: PluginManager) -> None:
        plugins = manager.discover_all()
        assert isinstance(plugins, list)


class _DummyLifecyclePlugin:
    """A minimal test plugin with lifecycle methods."""

    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


class TestPluginManagerLifecycleEvents:
    """Event emission on plugin load/unload."""

    async def test_load_unload_cycle(self, manager: PluginManager, event_bus) -> None:
        instance = _DummyLifecyclePlugin()
        manager.register(
            PluginDescriptor(
                name="lifecycle-test",
                capabilities=("llm_provider",),
                instance=instance,
            )
        )
        await manager.load("lifecycle-test")
        event_bus.assert_event_emitted(PluginLoaded)
        await manager.unload("lifecycle-test")
        event_bus.assert_event_emitted(PluginUnloaded)

    async def test_load_plugin_not_found(self, manager: PluginManager) -> None:
        with pytest.raises(PluginNotFoundError):
            await manager.load("nonexistent_plugin")

    async def test_unload_nonexistent(self, manager: PluginManager) -> None:
        await manager.unload("ghost")  # should not raise


class TestPluginManagerRegistryAccess:
    """Access to underlying registry."""

    async def test_registry_property(self, manager: PluginManager) -> None:
        from projectionai.core.plugin import PluginRegistry

        assert isinstance(manager.registry, PluginRegistry)

    async def test_registry_persistent(self, event_bus) -> None:
        """The global registry is shared across PluginManager instances."""
        reset_registry()

        m1 = PluginManager(event_bus)
        m1.register(_make_descriptor("shared"))

        m2 = PluginManager(event_bus)
        assert "shared" in m2.names
