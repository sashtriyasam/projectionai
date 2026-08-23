""".projectai format reader and writer.

The ``.projectai`` format is a structured directory that stores
a complete project on disk::

    my_project.projectai/
    ├── project.json         # Manifest
    ├── scenes/
    │   └── {scene_id}.json  # Per-scene data
    ├── assets/
    │   └── {asset_id}.ext   # Imported files
    └── thumbnails/
        └── {asset_id}.png   # Preview images
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from projectionai.domain.asset import Asset
from projectionai.domain.project import (
    HistoryEntry,
    HistoryEntryType,
    Project,
    ProjectMetadata,
    ProjectSettings,
)
from projectionai.domain.projection import ProjectionMapping
from projectionai.domain.scene import Scene

_logger = logging.getLogger(__name__)


PROJECT_MANIFEST = "project.json"
SCENES_DIR = "scenes"
ASSETS_DIR = "assets"
THUMBNAILS_DIR = "thumbnails"


def create_project_structure(project: Project, path: Path) -> None:
    """Create the ``.projectai`` directory for a new project.

    Args:
        project: The project to persist.
        path: Target directory path (will be created).
    """
    path.mkdir(parents=True, exist_ok=True)
    (path / SCENES_DIR).mkdir(exist_ok=True)
    (path / ASSETS_DIR).mkdir(exist_ok=True)
    (path / THUMBNAILS_DIR).mkdir(exist_ok=True)
    _write_manifest(project, path)


def write_project(project: Project, path: Path) -> None:
    """Write a complete project to its ``.projectai`` directory.

    Args:
        project: The project to persist.
        path: Existing ``.projectai`` directory.
    """
    _write_manifest(project, path)

    # Write projections
    projections_dir = path / "projections"
    projections_dir.mkdir(exist_ok=True)
    known_proj_ids = set(project.projections.keys())
    for proj in project.projections.values():
        proj_path = projections_dir / f"{proj.id}.json"
        proj_path.write_text(
            json.dumps(proj.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    for f in projections_dir.iterdir():
        if f.suffix == ".json" and f.stem not in known_proj_ids:
            try:
                f.unlink()
            except Exception as exc:
                _logger.warning("Failed to remove stale projection file %s: %s", f, exc)

    # Write scenes
    scenes_dir = path / SCENES_DIR
    scenes_dir.mkdir(exist_ok=True)
    for scene in project.scenes.values():
        scene_path = scenes_dir / f"{scene.id}.json"
        scene_path.write_text(
            json.dumps(scene.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    # Remove stale scene files
    known_ids = set(project.scenes.keys())
    for f in scenes_dir.iterdir():
        if f.suffix == ".json" and f.stem not in known_ids:
            try:
                f.unlink()
            except Exception as exc:
                _logger.warning("Failed to remove stale scene file %s: %s", f, exc)


def read_project(path: Path) -> Project:
    """Read a ``.projectai`` directory and return a ``Project``.

    Args:
        path: Path to the ``.projectai`` directory.

    Returns:
        The deserialized ``Project`` instance.

    Raises:
        FileNotFoundError: If the directory or manifest does not exist.
        ValueError: If the manifest is malformed.
    """
    if not path.is_dir():
        raise FileNotFoundError(f"Project directory not found: {path}")

    manifest = path / PROJECT_MANIFEST
    if not manifest.exists():
        raise ValueError(f"Missing {PROJECT_MANIFEST} in {path}")

    data = json.loads(manifest.read_text(encoding="utf-8"))

    # Reconstruct project
    project = Project(
        id=data.get("id", ""),
        name=data.get("name", path.stem),
        path=path,
    )

    # Settings
    settings_data = data.get("settings", {})
    if settings_data:
        try:
            project.settings = ProjectSettings(**settings_data)
        except Exception as exc:
            _logger.warning("Failed to load project settings: %s", exc)

    # Metadata
    meta_data = data.get("metadata", {})
    if meta_data:
        try:
            project.metadata = ProjectMetadata(**meta_data)
        except Exception as exc:
            _logger.warning("Failed to load project metadata: %s", exc)

    # Timestamps
    from datetime import UTC, datetime

    if "created_at" in data:
        try:
            project.created_at = datetime.fromisoformat(data["created_at"])
        except Exception as exc:
            _logger.warning("Failed to parse created_at: %s", exc)
    if "updated_at" in data:
        try:
            project.updated_at = datetime.fromisoformat(data["updated_at"])
        except Exception as exc:
            _logger.warning("Failed to parse updated_at: %s", exc)

    # History
    for entry_data in data.get("history", []):
        try:
            ts = entry_data.get("timestamp")
            parsed_ts = datetime.fromisoformat(ts) if ts else datetime.now(UTC)
            project.history.append(
                HistoryEntry(
                    type=HistoryEntryType(entry_data["type"]),
                    description=entry_data.get("description", ""),
                    timestamp=parsed_ts,
                    user=entry_data.get("user", ""),
                    details=entry_data.get("details", {}),
                )
            )
        except Exception as exc:
            _logger.warning("Skipping invalid history entry: %s", exc)

    projections_dir = path / "projections"
    if projections_dir.is_dir():
        for f in sorted(projections_dir.iterdir()):
            if f.suffix != ".json":
                continue
            try:
                proj_data = json.loads(f.read_text(encoding="utf-8"))
                projection = ProjectionMapping.from_dict(proj_data)
                project.add_projection(projection)
            except Exception as exc:
                _logger.warning("Failed to read projection %s: %s", f, exc)

    # Read scenes
    scenes_dir = path / SCENES_DIR
    if scenes_dir.is_dir():
        for f in sorted(scenes_dir.iterdir()):
            if f.suffix != ".json":
                continue
            try:
                scene_data = json.loads(f.read_text(encoding="utf-8"))
                scene = Scene.from_dict(scene_data)
                project.add_scene(scene)
            except Exception as exc:
                _logger.warning("Failed to read scene %s: %s", f, exc)

    # Restore active scene
    if data.get("active_scene_id") and data["active_scene_id"] in project.scenes:
        project.active_scene_id = data["active_scene_id"]

    project.is_dirty = False
    return project


# -- Asset I/O --------------------------------------------------------------


def asset_storage_path(project_path: Path, asset: Asset) -> Path:
    """Return the path where an asset file should be stored.

    The file name mirrors the asset ID to guarantee uniqueness.
    """
    ext = Path(asset.name).suffix if asset.name else ".dat"
    return project_path / ASSETS_DIR / f"{asset.id}{ext}"


def thumbnail_storage_path(project_path: Path, asset_id: str) -> Path:
    """Return the path where an asset's thumbnail should be stored."""
    return project_path / THUMBNAILS_DIR / f"{asset_id}.png"


# -- Manifest helpers -------------------------------------------------------


def _write_manifest(project: Project, path: Path) -> None:
    """Write the ``project.json`` manifest file."""
    scenes_data: list[dict[str, str]] = []
    for scene in project.scenes.values():
        try:
            scenes_data.append({"id": scene.id, "name": scene.name})
        except Exception as exc:
            _logger.warning("Failed to serialize scene %s: %s", scene.id, exc)

    projections_data: list[dict[str, str]] = []
    for proj in project.projections.values():
        try:
            projections_data.append({"id": proj.id, "name": proj.name})
        except Exception as exc:
            _logger.warning("Failed to serialize projection %s: %s", proj.id, exc)

    data: dict[str, Any] = {
        "id": project.id,
        "name": project.name,
        "active_scene_id": project.active_scene_id,
        "scenes": scenes_data,
        "projections": projections_data,
        "settings": {
            "resolution_width": project.settings.resolution_width,
            "resolution_height": project.settings.resolution_height,
            "framerate": project.settings.framerate,
            "color_space": project.settings.color_space,
        },
        "metadata": {
            "author": project.metadata.author,
            "company": project.metadata.company,
            "description": project.metadata.description,
            "application_version": project.metadata.application_version,
            "project_format_version": project.metadata.project_format_version,
            "tags": list(project.metadata.tags),
        },
        "history": [
            {
                "type": entry.type.value,
                "description": entry.description,
                "timestamp": entry.timestamp.isoformat(),
                "user": entry.user,
                "details": entry.details,
            }
            for entry in project.history
        ],
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }

    manifest = path / PROJECT_MANIFEST
    _ = manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
