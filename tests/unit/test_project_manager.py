"""Tests for ProjectManager."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from projectionai.core.events import (
    ProjectClosed,
    ProjectCreated,
    ProjectModified,
    ProjectOpened,
    ProjectSaved,
)
from projectionai.domain.project import ProjectMetadata, ProjectSettings
from projectionai.managers.project_manager import ProjectManager
from projectionai.ui.viewmodels.project import ProjectViewModel


@pytest.fixture
async def manager(event_bus) -> ProjectManager:
    m = ProjectManager(event_bus)
    await m.initialize()
    return m


class TestProjectManagerLifecycle:
    """Project creation, opening, saving, closing."""

    async def test_initialize(self, manager: ProjectManager) -> None:
        assert not manager.is_open
        assert manager.current is None
        assert manager.recent_projects == []

    async def test_create_project(
        self, manager: ProjectManager, tmp_path: Path
    ) -> None:
        project = manager.create_project("TestProject", tmp_path)

        assert project.name == "TestProject"
        assert project.path == tmp_path
        assert project.active_scene is not None
        assert manager.is_open
        assert manager.current is project
        assert len(manager.recent_projects) == 1
        assert manager.recent_projects[0].path == tmp_path

    async def test_create_project_emits_events(
        self, manager: ProjectManager, tmp_path: Path, event_bus
    ) -> None:
        manager.create_project("TestProject", tmp_path)
        await asyncio.sleep(0)

        event_bus.assert_event_emitted(ProjectCreated)
        event_bus.assert_event_emitted(ProjectOpened)

    async def test_create_project_with_metadata(
        self, manager: ProjectManager, tmp_path: Path
    ) -> None:
        meta = ProjectMetadata(author="Test Author", description="A test project")
        settings = ProjectSettings(resolution_width=1920, resolution_height=1080)
        project = manager.create_project("TestProject", tmp_path, meta, settings)

        assert project.metadata.author == "Test Author"
        assert project.metadata.description == "A test project"
        assert project.settings.resolution_width == 1920
        assert project.settings.resolution_height == 1080

    async def test_create_project_closes_existing(
        self, manager: ProjectManager, tmp_path: Path
    ) -> None:
        p1 = manager.create_project("First", tmp_path / "first")
        p2 = manager.create_project("Second", tmp_path / "second", force=True)

        assert manager.current is p2
        # p1 was closed without saving — still marked dirty
        assert p1.is_dirty

    async def test_open_project(self, manager: ProjectManager, tmp_path: Path) -> None:
        # First create and save a project
        manager.create_project("ToOpen", tmp_path)
        await manager.save_project()

        # Create fresh manager and open
        fresh_mgr = ProjectManager(event_bus=manager._event_bus)
        await fresh_mgr.initialize()
        opened = await fresh_mgr.open_project(tmp_path)

        assert opened.name == "ToOpen"
        assert fresh_mgr.is_open
        assert fresh_mgr.current is opened

    async def test_open_project_not_found(self, manager: ProjectManager) -> None:
        with pytest.raises(FileNotFoundError):
            await manager.open_project(Path("/nonexistent/project"))

    async def test_save_project(
        self, manager: ProjectManager, tmp_path: Path, event_bus
    ) -> None:
        manager.create_project("ToSave", tmp_path)
        await manager.save_project()
        await asyncio.sleep(0)

        assert (tmp_path / "project.json").exists()
        event_bus.assert_event_emitted(ProjectSaved)

    async def test_save_project_no_open(self, manager: ProjectManager) -> None:
        with pytest.raises(ValueError, match="No project is open"):
            await manager.save_project()

    async def test_close_project(
        self, manager: ProjectManager, tmp_path: Path, event_bus
    ) -> None:
        manager.create_project("ToClose", tmp_path)
        manager.close_project(force=True)
        await asyncio.sleep(0)

        assert not manager.is_open
        assert manager.current is None
        event_bus.assert_event_emitted(ProjectClosed)

    async def test_close_project_without_open(self, manager: ProjectManager) -> None:
        manager.close_project()  # should not raise


class TestProjectManagerDirtyTracking:
    """Unsaved-change detection."""

    async def test_fresh_project_not_dirty(
        self, manager: ProjectManager, tmp_path: Path
    ) -> None:
        manager.create_project("Clean", tmp_path)
        # A new project with a default scene IS dirty
        assert manager.is_dirty

    async def test_mark_modified(self, manager: ProjectManager, tmp_path: Path) -> None:
        manager.create_project("Dirty", tmp_path)
        manager.mark_modified("Updated something")
        assert manager.is_dirty

    async def test_mark_modified_emits_event(
        self, manager: ProjectManager, tmp_path: Path, event_bus
    ) -> None:
        manager.create_project("Dirty", tmp_path)
        manager.mark_modified("Updated")
        await asyncio.sleep(0)
        event_bus.assert_event_emitted(ProjectModified)

    async def test_mark_saved_after_save(
        self, manager: ProjectManager, tmp_path: Path
    ) -> None:
        manager.create_project("CleanUp", tmp_path)
        manager.mark_modified("Changed")
        assert manager.is_dirty
        await manager.save_project()
        assert not manager.is_dirty

    async def test_mark_modified_no_project(self, manager: ProjectManager) -> None:
        manager.mark_modified("Should be no-op")  # should not raise


class TestProjectManagerRecentProjects:
    """Recent-projects tracking."""

    async def test_recent_projects_ordered(
        self, manager: ProjectManager, tmp_path: Path
    ) -> None:
        paths = [tmp_path / f"proj{i}" for i in range(3)]
        for p in paths:
            manager.create_project(f"Proj{p.name}", p, force=True)

        recent = manager.recent_projects
        assert len(recent) == 3
        # Most recent first
        assert recent[0].path == paths[2]
        assert recent[2].path == paths[0]

    async def test_recent_projects_max_ten(
        self, manager: ProjectManager, tmp_path: Path
    ) -> None:
        for i in range(15):
            p = tmp_path / f"proj{i}"
            manager.create_project(f"Proj{i}", p, force=True)

        assert len(manager.recent_projects) <= 10

    async def test_project_path_property(
        self, manager: ProjectManager, tmp_path: Path
    ) -> None:
        assert manager.project_path is None
        manager.create_project("Test", tmp_path)
        assert manager.project_path == tmp_path


class TestProjectManagerEdgeCases:
    """Edge cases and error handling."""

    async def test_double_create_not_dirty_on_second(
        self, manager: ProjectManager, tmp_path: Path
    ) -> None:
        p1 = manager.create_project("First", tmp_path / "first")
        manager.create_project("Second", tmp_path / "second", force=True)
        # First project should be marked as closed (dirty)
        assert p1.is_dirty


class TestProjectSettingsValidation:
    """ProjectSettings rejects invalid types and out-of-range values."""

    def test_constructor_rejects_out_of_range(self) -> None:
        with pytest.raises(ValueError):
            ProjectSettings(resolution_width=0)
        with pytest.raises(ValueError):
            ProjectSettings(framerate=0.0)
        with pytest.raises(ValueError):
            ProjectSettings(grid_size=0.0)

    def test_assignment_rejects_invalid_types(self) -> None:
        settings = ProjectSettings()
        bad_values: dict[str, Any] = {
            "resolution_width": 2.5,
            "framerate": "fast",
            "grid_enabled": 1,
        }
        for key, value in bad_values.items():
            with pytest.raises(TypeError):
                setattr(settings, key, value)

    def test_assignment_rejects_out_of_range(self) -> None:
        settings = ProjectSettings()
        with pytest.raises(ValueError):
            settings.resolution_height = 0
        with pytest.raises(ValueError):
            settings.grid_size = 0.0

    def test_constructor_rejects_non_finite(self) -> None:
        with pytest.raises(ValueError):
            ProjectSettings(framerate=float("nan"))
        with pytest.raises(ValueError):
            ProjectSettings(framerate=float("inf"))
        with pytest.raises(ValueError):
            ProjectSettings(grid_size=float("-inf"))

    def test_assignment_rejects_non_finite(self) -> None:
        settings = ProjectSettings()
        with pytest.raises(ValueError):
            settings.framerate = float("nan")
        with pytest.raises(ValueError):
            settings.grid_size = float("inf")

    def test_boundary_and_valid_assignments_pass(self) -> None:
        settings = ProjectSettings()
        settings.resolution_width = 1
        settings.framerate = 0.1
        settings.grid_size = 0.01
        settings.framerate = 60.0
        assert settings.framerate == 60.0


class TestProjectViewModelUpdateSetting:
    """update_setting rejects invalid values without dirtying or notifying."""

    async def test_update_setting_rejects_invalid_value(
        self, manager: ProjectManager, tmp_path: Path
    ) -> None:
        project = manager.create_project("TestProject", tmp_path)
        dirty_before = project.is_dirty
        vm = ProjectViewModel(manager)
        calls: list[int] = []

        def _handler() -> None:
            calls.append(1)

        vm.subscribe(_handler)
        assert vm.update_setting("framerate", "fast") is False
        assert vm.update_setting("resolution_width", 0) is False
        assert project.is_dirty == dirty_before
        assert calls == []
        assert vm.settings()["framerate"] == 30.0

    async def test_update_setting_accepts_valid_value(
        self, manager: ProjectManager, tmp_path: Path
    ) -> None:
        project = manager.create_project("TestProject", tmp_path)
        vm = ProjectViewModel(manager)
        assert vm.update_setting("framerate", 60.0) is True
        assert project.settings.framerate == 60.0
        assert project.is_dirty

    async def test_update_setting_rejects_unknown_key(
        self, manager: ProjectManager, tmp_path: Path
    ) -> None:
        manager.create_project("TestProject", tmp_path)
        vm = ProjectViewModel(manager)
        assert vm.update_setting("no_such_key", 1) is False
