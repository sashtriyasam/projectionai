# ADR-007: Domain-Driven Package Structure

## Status

Accepted

## Context

The codebase organises business logic across several layers: domain concepts (scene, surface, calibration), service abstractions, infrastructure implementations, and the UI. Without clear boundaries, code tends to mix concerns, making it hard to test domain logic independently or swap infrastructure.

## Decision

Organise the package into four layers following domain-driven design principles:

```
projectionai/
├── domain/          # Business entities, value objects, domain logic
├── services/        # Interface definitions (protocols / ABCs)
├── infrastructure/  # Implementations of service interfaces
├── application/     # Use cases / workflows
└── ui/              # PySide6 views, viewmodels, widgets
```

Dependencies flow inward: `ui → application → services ← infrastructure`, with `domain` at the centre having no dependencies.

## Consequences

- **Positive**: Clear dependency direction — infrastructure depends on services, not vice versa.
- **Positive**: Domain logic is pure Python with no infrastructure coupling — easy to unit test.
- **Positive**: Services layer makes it trivial to swap implementations (e.g., test doubles, different AI providers).
- **Positive**: New developers can understand the architecture from the directory structure alone.
- **Negative**: More directories and files than a flat structure.
- **Negative**: Requires discipline to maintain dependency direction — leaks happen during rapid development.
- **Negative**: Sometimes requires adapter/wrapper code at infrastructure boundaries.
