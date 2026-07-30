"""Tests for AssetManager."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from projectionai.core.events import AssetDeleted, AssetImported, AssetUpdated
from projectionai.domain.asset import Asset, AssetType
from projectionai.managers.asset_manager import AssetManager


@pytest.fixture
async def manager(event_bus) -> AssetManager:
    m = AssetManager(event_bus)
    await m.initialize()
    return m


def _make_asset(
    name: str = "test",
    type_: AssetType = AssetType.IMAGE,
    path: str = "",
) -> Asset:
    return Asset(
        name=name,
        type=type_,
        path=Path(path) if path else None,
        original_path=Path(path) if path else None,
    )


class TestAssetManagerLifecycle:
    """Adding, removing, retrieving assets."""

    async def test_initialize(self, manager: AssetManager) -> None:
        assert manager.asset_count == 0
        assert manager.get_all_assets() == []

    async def test_add_asset(self, manager: AssetManager) -> None:
        asset = _make_asset("logo.png", AssetType.IMAGE, "imports/logo.png")
        asset_id = manager.add_asset(asset)

        assert asset_id == asset.id
        assert manager.asset_count == 1
        assert manager.get_asset(asset_id) is asset

    async def test_add_asset_emits_event(
        self, manager: AssetManager, event_bus
    ) -> None:
        asset = _make_asset("logo.png")
        manager.add_asset(asset)

        await asyncio.sleep(0)
        event_bus.assert_event_emitted(AssetImported)

    async def test_add_duplicate_id_raises(self, manager: AssetManager) -> None:
        asset = _make_asset("unique")
        manager.add_asset(asset)

        dup = Asset(id=asset.id, name="Duplicate")
        with pytest.raises(ValueError, match="already exists"):
            manager.add_asset(dup)

    async def test_get_asset_not_found(self, manager: AssetManager) -> None:
        assert manager.get_asset("nonexistent") is None

    async def test_remove_asset(self, manager: AssetManager) -> None:
        asset = _make_asset("remove_me")
        asset_id = manager.add_asset(asset)
        manager.remove_asset(asset_id)

        assert manager.get_asset(asset_id) is None
        assert manager.asset_count == 0

    async def test_remove_asset_emits_event(
        self, manager: AssetManager, event_bus
    ) -> None:
        asset_id = manager.add_asset(_make_asset("evicted"))
        manager.remove_asset(asset_id)

        await asyncio.sleep(0)
        event_bus.assert_event_emitted(AssetDeleted)

    async def test_remove_nonexistent(self, manager: AssetManager) -> None:
        manager.remove_asset("ghost")  # should not raise

    async def test_asset_ids_sorted(self, manager: AssetManager) -> None:
        ids = []
        for i in range(3):
            a = _make_asset(f"asset_{i}")
            ids.append(manager.add_asset(a))

        assert manager.asset_ids == sorted(ids)


class TestAssetManagerQuery:
    """Filtering and searching."""

    async def test_get_by_type(self, manager: AssetManager) -> None:
        img = _make_asset("img", AssetType.IMAGE)
        mesh = _make_asset("mesh", AssetType.MESH)
        vid = _make_asset("vid", AssetType.VIDEO)

        manager.add_asset(img)
        manager.add_asset(mesh)
        manager.add_asset(vid)

        images = manager.get_assets_by_type(AssetType.IMAGE)
        assert len(images) == 1
        assert images[0] is img

    async def test_get_by_original_path(self, manager: AssetManager) -> None:
        path = Path("/originals/file.png")
        asset = _make_asset("file.png", path=str(path))
        manager.add_asset(asset)

        found = manager.get_asset_by_original_path(str(path))
        assert found is asset

    async def test_get_by_original_path_no_match(self, manager: AssetManager) -> None:
        assert manager.get_asset_by_original_path("/missing") is None

    async def test_search_by_name(self, manager: AssetManager) -> None:
        manager.add_asset(_make_asset("Background Image"))
        manager.add_asset(_make_asset("Foreground Image"))
        manager.add_asset(_make_asset("Audio Track"))

        results = manager.search_by_name("image")
        assert len(results) == 2

    async def test_search_by_name_case_insensitive(self, manager: AssetManager) -> None:
        manager.add_asset(_make_asset("IMAGE"))
        manager.add_asset(_make_asset("image_001"))

        assert len(manager.search_by_name("image")) == 2

    async def test_search_by_name_no_match(self, manager: AssetManager) -> None:
        assert manager.search_by_name("zzzz_not_found") == []


class TestAssetManagerDependencies:
    """Dependency graph management."""

    async def test_add_dependency(self, manager: AssetManager) -> None:
        parent = _make_asset("parent")
        child = _make_asset("child")

        pid = manager.add_asset(parent)
        cid = manager.add_asset(child)

        manager.add_dependency(cid, pid)

        assert manager.get_dependency_ids(cid) == {pid}
        assert manager.get_dependent_ids(pid) == {cid}

    async def test_remove_dependency(self, manager: AssetManager) -> None:
        p = _make_asset("p")
        c = _make_asset("c")
        pid = manager.add_asset(p)
        cid = manager.add_asset(c)

        manager.add_dependency(cid, pid)
        manager.remove_dependency(cid, pid)

        assert manager.get_dependency_ids(cid) == set()
        assert manager.get_dependent_ids(pid) == set()

    async def test_dependency_nonexistent_source(self, manager: AssetManager) -> None:
        target = _make_asset("target")
        manager.add_asset(target)

        # Adding dependency from nonexistent asset should not raise
        manager.add_dependency("ghost", target.id)

    async def test_get_dependents(self, manager: AssetManager) -> None:
        parent = _make_asset("parent")
        c1 = _make_asset("child1")
        c2 = _make_asset("child2")

        pid = manager.add_asset(parent)
        c1id = manager.add_asset(c1)
        c2id = manager.add_asset(c2)

        manager.add_dependency(c1id, pid)
        manager.add_dependency(c2id, pid)

        dependents = manager.get_dependents(pid)
        assert len(dependents) == 2
        assert set(d.id for d in dependents) == {c1id, c2id}


class TestAssetManagerUpdates:
    """Metadata and preview updates."""

    async def test_update_metadata(self, manager: AssetManager) -> None:
        asset = _make_asset("updatable")
        aid = manager.add_asset(asset)

        manager.update_metadata(aid, key="value", number=42)
        assert asset.metadata["key"] == "value"
        assert asset.metadata["number"] == 42

    async def test_update_metadata_emits(
        self, manager: AssetManager, event_bus
    ) -> None:
        aid = manager.add_asset(_make_asset("m"))
        manager.update_metadata(aid, color="red")
        await asyncio.sleep(0)
        event_bus.assert_event_emitted(AssetUpdated)

    async def test_update_metadata_not_found(self, manager: AssetManager) -> None:
        with pytest.raises(ValueError, match="not found"):
            manager.update_metadata("ghost", weight=100)

    async def test_update_preview(self, manager: AssetManager) -> None:
        asset = _make_asset("preview")
        aid = manager.add_asset(asset)

        preview = Path("/thumbs/001.png")
        manager.update_preview(aid, preview)
        assert asset.preview_path == preview
        assert asset.has_thumbnail

    async def test_update_preview_not_found(self, manager: AssetManager) -> None:
        with pytest.raises(ValueError, match="not found"):
            manager.update_preview("ghost", Path("/preview.png"))
