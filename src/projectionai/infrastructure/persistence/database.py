"""SQLite-based storage implementation."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, override

import aiosqlite
from platformdirs import user_data_dir

from projectionai.core.config import AppConfig
from projectionai.domain.project import (
    HistoryEntry,
    HistoryEntryType,
    Project,
    ProjectMetadata,
    ProjectSettings,
)
from projectionai.domain.scene import Scene
from projectionai.infrastructure.persistence import project_format
from projectionai.services.storage import StorageService

_logger = logging.getLogger(__name__)


_TABLE_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    active_scene_id TEXT,
    settings        TEXT NOT NULL DEFAULT '{}',
    metadata        TEXT NOT NULL DEFAULT '{}',
    history         TEXT NOT NULL DEFAULT '[]',
    scenes          TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
)
"""


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _project_to_dict(project: Project) -> dict[str, Any]:
    """Convert a ``Project`` to a JSON-compatible dict."""
    return {
        "id": project.id,
        "name": project.name,
        "active_scene_id": project.active_scene_id,
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
        "scenes": [scene.to_dict() for scene in project.scenes.values()],
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


def _project_from_dict(data: dict[str, Any]) -> Project:
    """Reconstruct a ``Project`` from a dict previously created by
    ``_project_to_dict``."""
    project = Project(
        id=data.get("id", ""),
        name=data.get("name", "Untitled"),
    )

    settings_data = data.get("settings", {})
    if settings_data:
        project.settings = ProjectSettings(**settings_data)

    meta_data = data.get("metadata", {})
    if meta_data:
        project.metadata = ProjectMetadata(**meta_data)

    for entry_data in data.get("history", []):
        try:
            ts = entry_data.get("timestamp")
            parsed_ts = (
                datetime.fromisoformat(ts) if isinstance(ts, str) else datetime.now(UTC)
            )
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

    for scene_data in data.get("scenes", []):
        try:
            scene = Scene.from_dict(scene_data)
            project.add_scene(scene)
        except Exception as exc:
            _logger.warning("Skipping invalid scene: %s", exc)

    active_id = data.get("active_scene_id")
    if active_id and active_id in project.scenes:
        project.active_scene_id = active_id

    created = data.get("created_at")
    updated = data.get("updated_at")
    if isinstance(created, str):
        project.created_at = datetime.fromisoformat(created)
    if isinstance(updated, str):
        project.updated_at = datetime.fromisoformat(updated)

    project.is_dirty = False
    return project


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class SQLiteProjectRepository:
    """SQLite-backed project repository."""

    def __init__(self, db_path: Path) -> None:
        self._db_path: Path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        conn = await aiosqlite.connect(str(self._db_path))
        self._conn = conn
        _ = await conn.execute("PRAGMA journal_mode=WAL")
        _ = await conn.execute("PRAGMA foreign_keys=ON")
        await self._create_tables()

    async def _create_tables(self) -> None:
        conn = self._conn
        if conn is None:
            raise RuntimeError("Repository not initialised")
        await conn.execute(_TABLE_PROJECTS)
        await conn.commit()

    async def save(self, project: Project) -> None:
        conn = self._conn
        if conn is None:
            raise RuntimeError("Repository not initialised")
        data = _project_to_dict(project)
        await conn.execute(
            """INSERT OR REPLACE INTO projects
               (id, name, active_scene_id, settings, metadata, history,
                scenes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["id"],
                data["name"],
                data["active_scene_id"],
                json.dumps(data["settings"]),
                json.dumps(data["metadata"]),
                json.dumps(data["history"]),
                json.dumps(data["scenes"]),
                data["created_at"],
                data["updated_at"],
            ),
        )
        await conn.commit()

    async def load(self, project_id: str) -> Project | None:
        conn = self._conn
        if conn is None:
            raise RuntimeError("Repository not initialised")
        cursor = await conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_project(row)

    async def delete(self, project_id: str) -> None:
        conn = self._conn
        if conn is None:
            raise RuntimeError("Repository not initialised")
        await conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        await conn.commit()

    async def list_projects(self) -> list[Project]:
        conn = self._conn
        if conn is None:
            raise RuntimeError("Repository not initialised")
        cursor = await conn.execute("SELECT * FROM projects ORDER BY updated_at DESC")
        rows = await cursor.fetchall()
        return [self._row_to_project(row) for row in rows]

    async def shutdown(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    # -- Helpers ---------------------------------------------------------------

    @staticmethod
    def _row_to_project(row: aiosqlite.Row) -> Project:
        """Reconstruct a ``Project`` from a SQLite row."""
        data: dict[str, Any] = dict(row)
        # Columns that are JSON strings need parsing
        for col in ("settings", "metadata", "history", "scenes"):
            raw = data.get(col)
            if isinstance(raw, str):
                try:
                    data[col] = json.loads(raw)
                except json.JSONDecodeError:
                    data[col] = {} if col in ("settings", "metadata") else []
        return _project_from_dict(data)


# ---------------------------------------------------------------------------
# Storage service
# ---------------------------------------------------------------------------


class SQLiteStorageService(StorageService):
    """SQLite-based storage service."""

    def __init__(self, config: AppConfig) -> None:
        self._config: AppConfig = config
        self._repo: SQLiteProjectRepository | None = None
        self._data_dir: Path = Path(
            config.data_dir
            if config.data_dir
            else user_data_dir("projectionai", ensure_exists=True)
        )

    @override
    async def initialize(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        db_path = self._data_dir / "projectionai.db"
        self._repo = SQLiteProjectRepository(db_path)
        await self._repo.initialize()
        _logger.info("Storage initialised at %s", db_path)

    @override
    async def shutdown(self) -> None:
        if self._repo:
            await self._repo.shutdown()
            self._repo = None

    @property
    @override
    def projects(self) -> SQLiteProjectRepository:
        if self._repo is None:
            raise RuntimeError("Storage not initialised")
        return self._repo

    @override
    async def import_project(self, path: Path) -> Project:
        """Import a project from a ``.projectai`` archive directory.

        Delegates to ``project_format.read_project``.
        """
        project = await asyncio.to_thread(project_format.read_project, path)
        _logger.info("Imported project '%s' from %s", project.name, path)
        return project

    @override
    async def export_project(self, project: Project, path: Path) -> None:
        """Export a project to a ``.projectai`` archive directory.

        Delegates to ``project_format.write_project`` which creates
        the directory structure, writes the manifest, and serialises
        all scenes. Failures propagate to the caller.
        """
        await asyncio.to_thread(project_format.write_project, project, path)
        _logger.info("Exported project '%s' to %s", project.name, path)

    @override
    async def get_asset_path(self, project_id: str, filename: str) -> Path:
        asset_dir = self._data_dir / "assets" / project_id
        asset_dir.mkdir(parents=True, exist_ok=True)
        return asset_dir / filename
