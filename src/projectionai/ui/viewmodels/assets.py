"""AssetsViewModel — asset list, filter, search, and removal.

Qt-free. Renders whatever the :class:`AssetManager` holds; importing
real files into the project database is application logic, so this
viewmodel only wires the shell's add-by-path flow through the
manager's existing ``add_asset``.
"""

from __future__ import annotations

from pathlib import Path

from projectionai.domain.asset import Asset, AssetType
from projectionai.managers.asset_manager import AssetManager
from projectionai.ui.viewmodels.observable import Observable


class AssetsViewModel(Observable):
    """Observable asset-browser facade."""

    def __init__(self, asset_manager: AssetManager) -> None:
        super().__init__()
        self._assets = asset_manager
        self._filter: AssetType | None = None
        self._query: str = ""

    # -- Filtering ------------------------------------------------------------

    def set_type_filter(self, asset_type: AssetType | None) -> None:
        """Restrict the listing to one asset type (None = all)."""
        self._filter = asset_type
        self._notify()

    def set_search(self, query: str) -> None:
        """Set the name search substring."""
        self._query = query.strip()
        self._notify()

    # -- Listing --------------------------------------------------------------

    def assets(self) -> list[Asset]:
        """Assets matching the current filter and search."""
        if self._filter is not None:
            assets = self._assets.get_assets_by_type(self._filter)
        else:
            assets = self._assets.get_all_assets()
        if self._query:
            assets = [a for a in assets if self._query.lower() in a.name.lower()]
        return sorted(assets, key=lambda a: a.name.lower())

    @property
    def asset_count(self) -> int:
        """Total number of tracked assets."""
        return self._assets.asset_count

    @property
    def type_filter(self) -> AssetType | None:
        """Currently active type filter."""
        return self._filter

    @property
    def available_types(self) -> list[AssetType]:
        """Asset types present in the database, most common first."""
        counts: dict[AssetType, int] = {}
        for asset in self._assets.get_all_assets():
            counts[asset.type] = counts.get(asset.type, 0) + 1
        return sorted(counts, key=lambda t: (-counts[t], t.value))

    # -- Mutations ------------------------------------------------------------

    def remove(self, asset_id: str) -> None:
        """Remove an asset by id."""
        self._assets.remove_asset(asset_id)
        self._notify()

    def add_from_path(self, path: Path) -> Asset | None:
        """Register a file as an asset (shell import stub).

        Records the original path without copying content into the
        project — real import/persistence is application logic.
        Returns None if the path does not resolve to an existing file.
        """
        if not path.resolve().is_file():
            return None
        try:
            asset = Asset(
                name=path.stem,
                type=AssetType.from_extension(path.suffix),
                original_path=path,
            )
            self._assets.add_asset(asset)
        except ValueError:
            return None
        self._notify()
        return asset
