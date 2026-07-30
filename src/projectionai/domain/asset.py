"""Asset model — the internal asset database representation.

Assets are not loose files. Each asset is a tracked entity with a UUID,
type, hash, dependency graph, and metadata. They are stored in the
project's internal asset database and referenced by ID throughout the
application.

The asset database is backed by SQLite inside each ``.projectai`` project.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4


class AssetType(StrEnum):
    """Well-known asset types.

    Each type corresponds to a category of importable/creatable content.
    """

    IMAGE = "image"
    VIDEO = "video"
    MESH = "mesh"
    MATERIAL = "material"
    TEXTURE = "texture"
    CALIBRATION = "calibration"
    AI_RESULT = "ai_result"
    AUDIO = "audio"
    PROJECTION = "projection"
    SHADER = "shader"
    UNKNOWN = "unknown"

    @classmethod
    def from_extension(cls, ext: str) -> AssetType:
        """Map a file extension to a likely asset type."""
        extension_map: dict[str, AssetType] = {
            # Images
            ".png": cls.IMAGE,
            ".jpg": cls.IMAGE,
            ".jpeg": cls.IMAGE,
            ".webp": cls.IMAGE,
            ".tiff": cls.IMAGE,
            ".bmp": cls.IMAGE,
            ".exr": cls.IMAGE,
            ".hdr": cls.IMAGE,
            # Video
            ".mp4": cls.VIDEO,
            ".mov": cls.VIDEO,
            ".avi": cls.VIDEO,
            ".webm": cls.VIDEO,
            # Mesh
            ".obj": cls.MESH,
            ".fbx": cls.MESH,
            ".glb": cls.MESH,
            ".gltf": cls.MESH,
            ".stl": cls.MESH,
            ".ply": cls.MESH,
            ".3ds": cls.MESH,
            # Audio
            ".wav": cls.AUDIO,
            ".mp3": cls.AUDIO,
            ".flac": cls.AUDIO,
            ".ogg": cls.AUDIO,
            # Shader
            ".glsl": cls.SHADER,
            ".vert": cls.SHADER,
            ".frag": cls.SHADER,
            ".comp": cls.SHADER,
        }
        return extension_map.get(ext.lower(), cls.UNKNOWN)


# ---------------------------------------------------------------------------
# Asset dependency
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssetDependency:
    """A directed dependency between two assets.

    If asset A depends on asset B, then A cannot be removed while B
    has dependents.
    """

    asset_id: str
    depends_on_id: str
    dependency_type: str = "reference"  # reference, embed, instance


# ---------------------------------------------------------------------------
# Asset
# ---------------------------------------------------------------------------


@dataclass
class Asset:
    """A tracked asset in the project.

    Assets are identified by UUID and referenced by ID throughout the
    application. The ``path`` is relative to the project's asset storage
    directory.
    """

    id: str = field(default_factory=lambda: uuid4().hex)
    name: str = "Untitled Asset"
    type: AssetType = AssetType.UNKNOWN

    # The relative path within the project's asset storage directory.
    # For imported assets, this is a copy of the original file.
    path: Path | None = None
    original_path: Path | None = None  # The path the asset was imported from

    # Content fingerprint for deduplication
    hash: str = ""
    size_bytes: int = 0
    mime_type: str = ""

    # Preview / thumbnail
    preview_path: Path | None = None
    has_thumbnail: bool = False

    # Dependencies (which assets this one uses)
    dependencies: dict[str, AssetDependency] = field(default_factory=dict)
    # Reverse-dependency cache (computed, not stored)
    _dependents_cache: set[str] = field(default_factory=set, repr=False, compare=False)

    # Metadata — type-specific, free-form
    metadata: dict[str, Any] = field(default_factory=dict)

    # Ownership and versioning
    owner: str = ""
    version: int = 1

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    modified_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # ------------------------------------------------------------------
    # Dependency management
    # ------------------------------------------------------------------

    def add_dependency(
        self,
        asset_id: str,
        dependency_type: str = "reference",
    ) -> None:
        """Record that this asset depends on *asset_id*."""
        self.dependencies[asset_id] = AssetDependency(
            asset_id=self.id,
            depends_on_id=asset_id,
            dependency_type=dependency_type,
        )

    def remove_dependency(self, asset_id: str) -> None:
        """Remove a dependency record."""
        _ = self.dependencies.pop(asset_id, None)

    @property
    def dependency_ids(self) -> set[str]:
        """Return the set of asset IDs this asset depends on."""
        return set(self.dependencies.keys())

    def add_dependent(self, asset_id: str) -> None:
        """Register a reverse-dependency (called when another asset
        depends on this one)."""
        self._dependents_cache.add(asset_id)

    def remove_dependent(self, asset_id: str) -> None:
        """Unregister a reverse-dependency."""
        self._dependents_cache.discard(asset_id)

    @property
    def dependent_ids(self) -> set[str]:
        """Return asset IDs that depend on this asset."""
        return self._dependents_cache

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_db_dict(self) -> dict[str, Any]:
        """Return a dict suitable for database storage."""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "path": str(self.path) if self.path else None,
            "original_path": str(self.original_path) if self.original_path else None,
            "hash": self.hash,
            "size_bytes": self.size_bytes,
            "mime_type": self.mime_type,
            "preview_path": str(self.preview_path) if self.preview_path else None,
            "has_thumbnail": int(self.has_thumbnail),
            "dependencies": [
                {"depends_on_id": d.depends_on_id, "dependency_type": d.dependency_type}
                for d in self.dependencies.values()
            ],
            "metadata": self.metadata,
            "owner": self.owner,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "modified_at": self.modified_at.isoformat(),
        }

    @staticmethod
    def from_db_dict(data: dict[str, Any]) -> Asset:
        """Create an Asset from a database dict."""
        deps: dict[str, AssetDependency] = {}
        for dep in data.get("dependencies", ()):
            deps[dep["depends_on_id"]] = AssetDependency(
                asset_id=data["id"],
                depends_on_id=dep["depends_on_id"],
                dependency_type=dep.get("dependency_type", "reference"),
            )
        return Asset(
            id=data["id"],
            name=data.get("name", "Untitled"),
            type=AssetType(data["type"]) if "type" in data else AssetType.UNKNOWN,
            path=Path(data["path"]) if data.get("path") else None,
            original_path=Path(data["original_path"])
            if data.get("original_path")
            else None,
            hash=data.get("hash", ""),
            size_bytes=data.get("size_bytes", 0),
            mime_type=data.get("mime_type", ""),
            preview_path=Path(data["preview_path"])
            if data.get("preview_path")
            else None,
            has_thumbnail=bool(data.get("has_thumbnail", False)),
            dependencies=deps,
            metadata=data.get("metadata", {}),
            owner=data.get("owner", ""),
            version=data.get("version", 1),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(UTC),
            modified_at=datetime.fromisoformat(data["modified_at"])
            if "modified_at" in data
            else datetime.now(UTC),
        )


# ---------------------------------------------------------------------------
# Thumbnail
# ---------------------------------------------------------------------------


@dataclass
class ThumbnailInfo:
    """Metadata about a generated thumbnail."""

    asset_id: str
    path: Path
    width: int = 256
    height: int = 256
    format: str = "png"
    size_bytes: int = 0
