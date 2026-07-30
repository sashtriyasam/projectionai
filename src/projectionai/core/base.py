"""Abstract base classes used throughout the application."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel as PydanticModel

# ---------------------------------------------------------------------------
# Type variables
# ---------------------------------------------------------------------------

T = TypeVar("T")
T_config = TypeVar("T_config", bound=PydanticModel)


# ---------------------------------------------------------------------------
# Base protocol — all services, plugins, and workers.
# ---------------------------------------------------------------------------


class Initializable(Protocol):
    """Protocol for objects requiring async or deferred initialization."""

    async def initialize(self) -> None:
        """Perform one-time initialization. Called once before first use."""
        ...

    async def shutdown(self) -> None:
        """Release resources. Called once before application exit."""
        ...


# ---------------------------------------------------------------------------
# Service — the primary abstraction for long-lived components.
# ---------------------------------------------------------------------------


class Service[T_config: PydanticModel](ABC):
    """A long-lived component with a defined lifecycle.

    Every service receives its configuration at construction time
    and exposes ``initialize`` / ``shutdown`` for lifecycle management.

    Type parameter ``T_config`` is a Pydantic model holding the
    configuration data specific to this service.
    """

    def __init__(self, config: T_config) -> None:
        self._config: T_config = config

    @property
    def config(self) -> T_config:
        """Return the service configuration."""
        return self._config

    @abstractmethod
    async def initialize(self) -> None:
        """Perform one-time initialization."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Release resources."""


# ---------------------------------------------------------------------------
# Result — generic wrapper for operations that can fail.
# ---------------------------------------------------------------------------
# Used internally to avoid raising exceptions in hot paths.
# Public-facing methods still raise typed exceptions for error boundaries.


class Ok[T]:
    """Represents a successful operation result."""

    __slots__: tuple[str, ...] = ("_value",)

    def __init__(self, value: T) -> None:
        self._value: T = value

    @property
    def value(self) -> T:
        return self._value

    def unwrap(self) -> T:
        return self._value


class Error:
    """Represents a failed operation result."""

    __slots__: tuple[str, ...] = ("_cause", "_message")

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        self._message: str = message
        self._cause: Exception | None = cause

    @property
    def message(self) -> str:
        return self._message

    @property
    def cause(self) -> Exception | None:
        return self._cause


Result = Ok[T] | Error


def ok[T](value: T) -> Ok[T]:
    """Wrap a value in ``Ok``."""
    return Ok(value)


def err(message: str, cause: Exception | None = None) -> Error:
    """Wrap an error message in ``Error``."""
    return Error(message, cause)


# ---------------------------------------------------------------------------
# Inspector — debug/diagnostics interface for any component.
# ---------------------------------------------------------------------------


class Inspectable(Protocol):
    """Protocol for components that can report their internal state."""

    def inspect(self) -> dict[str, Any]:
        """Return a snapshot of internal state for diagnostics."""
        ...
