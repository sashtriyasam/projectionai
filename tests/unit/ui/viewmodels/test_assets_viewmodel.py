"""Regression tests for AssetsViewModel.add_from_path.

``add_from_path`` must refuse paths that do not resolve to an existing
regular file (None) while preserving the pre-existing contract: unknown
file extensions register as ``AssetType.UNKNOWN`` (``from_extension``
never raises) and any ``ValueError`` from the manager (e.g. duplicate
registration) still maps to None.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from projectionai.domain.asset import Asset, AssetType
from projectionai.managers.asset_manager import AssetManager
from projectionai.ui.viewmodels.assets import AssetsViewModel


class _FakeManager:
    """Duck-typed AssetManager stand-in tracking registered assets."""

    def __init__(self, *, raise_on_add: bool = False) -> None:
        self._assets: list[Asset] = []
        self._raise_on_add = raise_on_add

    @property
    def asset_count(self) -> int:
        return len(self._assets)

    def add_asset(self, asset: Asset) -> str:
        if self._raise_on_add:
            raise ValueError("registration rejected")
        self._assets.append(asset)
        return asset.id

    def get_all_assets(self) -> list[Asset]:
        return list(self._assets)

    def get_assets_by_type(self, asset_type: AssetType) -> list[Asset]:
        return [a for a in self._assets if a.type == asset_type]

    def remove_asset(self, asset_id: str) -> None:
        self._assets = [a for a in self._assets if a.id != asset_id]


def _vm(manager: _FakeManager) -> AssetsViewModel:
    return AssetsViewModel(cast(AssetManager, manager))


class TestAddFromPath:
    def test_existing_file_is_registered(self, tmp_path: Path) -> None:
        vm = _vm(_FakeManager())
        source = tmp_path / "clip.mp4"
        source.write_bytes(b"x")
        asset = vm.add_from_path(source)
        assert asset is not None
        assert asset.name == "clip"
        assert asset.type == AssetType.VIDEO
        assert vm.asset_count == 1
        assert asset in vm.assets()

    def test_resolved_relative_path_is_registered(self, tmp_path: Path) -> None:
        vm = _vm(_FakeManager())
        source = tmp_path / "clip.mp4"
        source.write_bytes(b"x")
        indirect = tmp_path / "sub" / ".." / "clip.mp4"
        assert vm.add_from_path(indirect) is not None
        assert vm.asset_count == 1

    def test_missing_path_returns_none(self, tmp_path: Path) -> None:
        vm = _vm(_FakeManager())
        assert vm.add_from_path(tmp_path / "missing.png") is None
        assert vm.asset_count == 0

    def test_directory_returns_none(self, tmp_path: Path) -> None:
        vm = _vm(_FakeManager())
        assert vm.add_from_path(tmp_path) is None
        assert vm.asset_count == 0

    def test_unknown_extension_registers_as_unknown(self, tmp_path: Path) -> None:
        # from_extension maps unmapped suffixes to UNKNOWN without
        # raising; registration still succeeds (ValueError path unused).
        vm = _vm(_FakeManager())
        source = tmp_path / "render.xyz"
        source.write_bytes(b"x")
        asset = vm.add_from_path(source)
        assert asset is not None
        assert asset.type == AssetType.UNKNOWN
        assert vm.asset_count == 1

    def test_manager_value_error_still_returns_none(self, tmp_path: Path) -> None:
        # The pre-existing ValueError swallow (duplicate registration /
        # manager rejection) must keep returning None.
        vm = _vm(_FakeManager(raise_on_add=True))
        source = tmp_path / "clip.mp4"
        source.write_bytes(b"x")
        assert vm.add_from_path(source) is None
