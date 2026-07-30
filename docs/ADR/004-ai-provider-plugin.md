# ADR-004: Plugin-Based AI Provider Architecture

## Status

Accepted

## Context

The application needs to support multiple AI providers (Gemini, OpenAI, Anthropic, Replicate) for content generation. Each provider has a different API, SDK, and authentication method. Hard-coding all providers would create tight coupling and make adding new providers difficult.

## Decision

Use a plugin architecture with a common `AIProvider` interface and per-provider optional dependencies.

- Each provider implements the same interface (e.g., `generate_text`, `generate_image`).
- Providers are registered via a plugin registry and selected via `PROJECTIONAI_AI_PROVIDER` env var.
- Optional dependency groups in `pyproject.toml`: `[gemini]`, `[openai]`, `[anthropic]`, `[replicate]`, `[all]`.

## Consequences

- **Positive**: Clean separation of concerns — each provider is self-contained.
- **Positive**: Users install only the providers they need.
- **Positive**: Adding a new provider requires no changes to existing code — just implement the interface and register.
- **Positive**: The pattern extends naturally to other plugin domains (e.g., export formats, vision backends).
- **Negative**: Slightly more boilerplate than a monolithic provider class.
- **Negative**: Runtime discovery of available providers adds complexity.
