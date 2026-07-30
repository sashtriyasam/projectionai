"""Asset manager — project asset import, storage, and dependency tracking.

Manages the asset database (in-memory with optional persistence).
Assets are referenced by scene nodes and jobs.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, override

from projectionai.core.events import AssetDeleted, AssetImported, AssetUpdated, EventBus
from projectionai.domain.asset import Asset, AssetType
from projectionai.managers import Manager

_logger = logging.getLogger(__name__)


class AssetManager(Manager):
    """Manages project assets: import, lookup, dependency tracking.

    Assets are stored in memory with a dictionary keyed by asset ID.
    External file references are tracked as original import paths.
    """

    def __init__(self, event_bus: EventBus) -> None:
        super().__init__(event_bus)
        self._assets: dict[str, Asset] = {}
        self._original_path_index: dict[str, str] = {}

    # -- Asset lifecycle ----------------------------------------------------

    def add_asset(self, asset: Asset) -> str:
        """Register an asset.

        Args:
            asset: The asset to register. Must have a unique ID.

        Returns:
            The asset ID.

        Raises:
            ValueError: If an asset with the same ID already exists.
        """
        self._require_initialized()
        if asset.id in self._assets:
            raise ValueError(f"Asset {asset.id!r} already exists")
        self._assets[asset.id] = asset
        orig = os.path.normpath(str(asset.original_path)) if asset.original_path else ""
        if orig:
            self._original_path_index[orig] = asset.id
        _logger.debug("Added asset: %s (%s)", asset.name, asset.id)
        self._emit_nowait(
            AssetImported(
                asset_id=asset.id,
                asset_type=asset.type.value,
                source_path=orig,
            )
        )
        return asset.id

    def remove_asset(self, asset_id: str) -> None:
        """Remove an asset by ID.

        Does nothing if the asset doesn't exist.
        """
        self._require_initialized()
        asset = self._assets.pop(asset_id, None)
        if asset is None:
            return
        orig = os.path.normpath(str(asset.original_path)) if asset.original_path else ""
        if orig and self._original_path_index.get(orig) == asset_id:
            del self._original_path_index[orig]
        self._emit_nowait(AssetDeleted(asset_id=asset_id))
        _logger.debug("Removed asset: %s", asset_id)

    def get_asset(self, asset_id: str) -> Asset | None:
        """Return an asset by ID, or ``None``."""
        return self._assets.get(asset_id)

    def get_all_assets(self) -> list[Asset]:
        """Return all registered assets."""
        return list(self._assets.values())

    def get_assets_by_type(self, asset_type: AssetType) -> list[Asset]:
        """Return all assets of a given type."""
        return [a for a in self._assets.values() if a.type == asset_type]

    def get_asset_by_original_path(self, original_path: str) -> Asset | None:
        """Find an asset by its original source file path."""
        key = os.path.normpath(original_path)
        asset_id = self._original_path_index.get(key)
        if asset_id is None:
            return None
        return self._assets.get(asset_id)

    @property
    def asset_count(self) -> int:
        """Return the total number of assets."""
        return len(self._assets)

    @property
    def asset_ids(self) -> list[str]:
        """Return sorted list of asset IDs."""
        return sorted(self._assets)

    # -- Asset properties ---------------------------------------------------

    def update_metadata(self, asset_id: str, **metadata: Any) -> None:
        """Update custom metadata on an asset.

        Merges the provided dict with existing metadata.
        """
        self._require_initialized()
        asset = self._assets.get(asset_id)
        if asset is None:
            raise ValueError(f"Asset {asset_id!r} not found")
        asset.metadata.update(metadata)
        self._emit_nowait(AssetUpdated(asset_id=asset_id))

    def update_preview(self, asset_id: str, preview_path: Path) -> None:
        """Set or update the preview/thumbnail path for an asset."""
        self._require_initialized()
        asset = self._assets.get(asset_id)
        if asset is None:
            raise ValueError(f"Asset {asset_id!r} not found")
        asset.preview_path = preview_path
        asset.has_thumbnail = True
        self._emit_nowait(AssetUpdated(asset_id=asset_id))

    # -- Dependencies -------------------------------------------------------

    def add_dependency(
        self, asset_id: str, depends_on_id: str, dependency_type: str = "reference"
    ) -> None:
        """Record a dependency from *asset_id* to *depends_on_id*.

        Does nothing if *asset_id* does not exist.

        Args:
            asset_id: The asset that depends on another.
            depends_on_id: The asset being depended on.
            dependency_type: Type of dependency (reference, embed, instance).
        """
        self._require_initialized()
        asset = self._assets.get(asset_id)
        if asset is None:
            return
        asset.add_dependency(depends_on_id, dependency_type)

        target = self._assets.get(depends_on_id)
        if target is not None:
            target.add_dependent(asset_id)

    def remove_dependency(self, asset_id: str, depends_on_id: str) -> None:
        """Remove a dependency from *asset_id* to *depends_on_id*."""
        self._require_initialized()
        asset = self._assets.get(asset_id)
        if asset is None:
            return
        asset.remove_dependency(depends_on_id)

        target = self._assets.get(depends_on_id)
        if target is not None:
            target.remove_dependent(asset_id)

    def get_dependency_ids(self, asset_id: str) -> set[str]:
        """Return IDs of assets that *asset_id* depends on."""
        asset = self._assets.get(asset_id)
        if asset is None:
            return set()
        return asset.dependency_ids

    def get_dependent_ids(self, asset_id: str) -> set[str]:
        """Return IDs of assets that depend on *asset_id*."""
        asset = self._assets.get(asset_id)
        if asset is None:
            return set()
        return asset.dependent_ids

    def get_dependents(self, asset_id: str) -> list[Asset]:
        """Return assets that depend on the given asset."""
        asset = self._assets.get(asset_id)
        if asset is None:
            return []
        return [a for a in self._assets.values() if a.id in asset.dependent_ids]

    # -- Query helpers ------------------------------------------------------

    def search_by_name(self, query: str) -> list[Asset]:
        """Search assets by name (case-insensitive substring match)."""
        q = query.lower()
        return [a for a in self._assets.values() if q in a.name.lower()]

    # -- Lifecycle ----------------------------------------------------------

    @override
    async def _on_initialize(self) -> None:
        _logger.debug("AssetManager initialized")

    @override
    async def _on_shutdown(self) -> None:
        self._assets.clear()
        self._original_path_index.clear()
