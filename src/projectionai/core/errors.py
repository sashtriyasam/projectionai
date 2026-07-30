"""Application-wide error hierarchy.

Every exception raised by ProjectionAI inherits from ``ProjectionAIError``.
Error boundaries in the UI layer catch ``ProjectionAIError`` and display
user-friendly messages. Unexpected exceptions (``Exception``) are logged and
converted to a generic error dialog.
"""

from __future__ import annotations

from typing import override


class ProjectionAIError(Exception):
    """Base exception for all ProjectionAI errors."""

    _code: str | None

    def __init__(self, message: str, *, code: str | None = None) -> None:
        self._code = code
        super().__init__(message)

    @property
    def message(self) -> str:
        """Return the human-readable error message."""
        msg: object = self.args[0] if self.args else ""
        return str(msg)

    @property
    def code(self) -> str | None:
        """Return the machine-readable error code, if any."""
        return self._code

    @override
    def __str__(self) -> str:
        parts = [self.message]
        if self._code:
            parts.insert(0, f"[{self._code}]")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Configuration errors
# ---------------------------------------------------------------------------


class ConfigurationError(ProjectionAIError):
    """Raised when the application configuration is invalid or missing."""


class ProviderNotConfiguredError(ConfigurationError):
    """Raised when a requested AI provider has no credentials configured."""


# ---------------------------------------------------------------------------
# Manager errors
# ---------------------------------------------------------------------------


class ManagerError(ProjectionAIError):
    """Base for all manager-level errors."""


class ManagerNotInitializedError(ManagerError):
    """Raised when a manager is used before initialization."""


class ManagerStateError(ManagerError):
    """Raised when a manager operation is invalid for the current state."""


# ---------------------------------------------------------------------------
# Command errors
# ---------------------------------------------------------------------------


class CommandError(ManagerError):
    """Base for command pattern errors."""


class CommandExecutionError(CommandError):
    """Raised when a command fails during execute/undo/redo."""


class CommandValidationError(CommandError):
    """Raised when a command's preconditions are not met."""


class CommandHistoryEmptyError(CommandError):
    """Raised when trying to undo/redo with an empty history."""


# ---------------------------------------------------------------------------
# Job errors
# ---------------------------------------------------------------------------


class JobError(ManagerError):
    """Base for job system errors."""


class JobExecutionError(JobError):
    """Raised when a job fails during execution."""


class JobCancelledError(JobError):
    """Raised when a job is cancelled (not an error, but needs propagation)."""


class JobNotFoundError(JobError):
    """Raised when a requested job ID does not exist."""


class JobQueueFullError(JobError):
    """Raised when the job queue is at capacity."""


# ---------------------------------------------------------------------------
# Asset errors
# ---------------------------------------------------------------------------


class AssetError(ManagerError):
    """Base for asset management errors."""


class AssetNotFoundError(AssetError):
    """Raised when a requested asset is not in the database."""


class AssetImportError(AssetError):
    """Raised when an asset cannot be imported."""


class AssetExportError(AssetError):
    """Raised when an asset cannot be exported."""


class AssetDuplicateError(AssetError):
    """Raised when an asset with the same source path already exists."""


# ---------------------------------------------------------------------------
# Project errors
# ---------------------------------------------------------------------------


class ProjectError(ManagerError):
    """Base for project-level errors."""


class ProjectNotFoundError(ProjectError):
    """Raised when the project file is not found."""


class ProjectFormatError(ProjectError):
    """Raised when a project file has an invalid format."""


class ProjectSaveError(ProjectError):
    """Raised when saving a project fails."""


class ProjectLoadError(ProjectError):
    """Raised when loading a project fails."""


# ---------------------------------------------------------------------------
# Plugin errors
# ---------------------------------------------------------------------------


class PluginError(ManagerError):
    """Base for plugin system errors."""


class PluginNotFoundError(PluginError):
    """Raised when a requested plugin is not registered."""


class PluginLoadError(PluginError):
    """Raised when a plugin fails to load or initialize."""


class PluginConflictError(PluginError):
    """Raised when two plugins register for the same capability."""


class PluginCapabilityError(PluginError):
    """Raised when a plugin does not support the requested capability."""


# ---------------------------------------------------------------------------
# Domain errors
# ---------------------------------------------------------------------------


class DomainError(ProjectionAIError):
    """Base for domain-level errors."""


class InvalidSceneError(DomainError):
    """Raised when a scene definition is invalid."""


class CalibrationError(DomainError):
    """Raised when calibration fails or produces invalid results."""


# ---------------------------------------------------------------------------
# Scene errors
# ---------------------------------------------------------------------------


class SceneError(DomainError):
    """Base for scene graph errors."""


class SceneNodeNotFoundError(SceneError):
    """Raised when a scene node is not found."""


class InvalidSceneOperationError(SceneError):
    """Raised when a scene operation is not allowed (e.g. cycle)."""


# ---------------------------------------------------------------------------
# Service errors
# ---------------------------------------------------------------------------


class ServiceError(ProjectionAIError):
    """Base for service-level errors."""


class VisionError(ServiceError):
    """Raised when a vision pipeline operation fails."""


class RendererError(ServiceError):
    """Raised when the rendering engine encounters an error."""


class StorageError(ServiceError):
    """Raised when persistence/storage operations fail."""


# ---------------------------------------------------------------------------
# AI provider errors
# ---------------------------------------------------------------------------


class AIProviderError(ProjectionAIError):
    """Base for AI provider errors."""


class AIProviderTimeoutError(AIProviderError):
    """Raised when an AI provider request times out."""


class AIProviderRateLimitError(AIProviderError):
    """Raised when an AI provider rate-limits the request."""


class AIProviderContentFilteredError(AIProviderError):
    """Raised when the AI provider filtered the response content."""
