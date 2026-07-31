# ProjectionAI

**AI-powered projection mapping platform.**

[![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-000000)](https://docs.astral.sh/ruff/)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-blue)](https://mypy-lang.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Scan any object — a painting, sculpture, building facade, or stage — and ProjectionAI automatically estimates its geometry, detects projection surfaces, and lets you generate and warp content onto it using natural language prompts.

The long-term vision: become the "ChatGPT for Projection Mapping."

---

## Features

- **Object Scanning** — Photograph or scan physical objects to auto-estimate geometry
- **Surface Detection** — Computer vision identifies planar and curved projection surfaces
- **AI Content Generation** — Provider-agnostic AI engine (Gemini, OpenAI, Anthropic, Replicate)
- **Automatic Warping** — Generated content is automatically mapped onto object surfaces
- **Real-time Preview** — See exactly how projections will look before projecting
- **Multi-projector Ready** — Architecture supports future multi-projector setups

---

## Quick Start

```bash
# Prerequisites: Python 3.12+, uv

# Clone and install
git clone https://github.com/your-org/projectionai.git
cd projectionai

# Create virtual environment and install dependencies
uv sync

# Activate
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS/Linux

# Configure AI provider (copy and edit)
cp .env.example .env
# Edit .env with your API keys

# Run
python -m projectionai
```

---

## Development

```bash
# Install with dev dependencies (included in uv sync)
uv sync

# Run tests
pytest

# Type check
mypy src/projectionai

# Lint and format
ruff check src/
ruff format src/

# Install pre-commit hooks
pre-commit install
```

### Project Structure

```
src/projectionai/          # Main package
├── core/                  # Framework: event bus, plugin system, config, errors
├── domain/                # Business models: scene, project, surface, calibration
├── services/              # Abstractions: vision, AI, renderer, calibration, storage
├── infrastructure/        # Implementations: AI providers, OpenCV, ModernGL, SQLite
├── application/           # Use cases: scan, generate, warp, preview, project
├── managers/              # Concrete managers: scene, asset, project, job, plugin, settings, workspace, command
├── editor/                # Editor subsystems: selection, gizmos, transform tools, camera
├── calibration/           # Projector calibration: pipeline, models, validation
├── ui/                    # PySide6: main window, viewmodels, views, widgets
├── app.py                 # Application bootstrap / DI container
└── main.py                # CLI entry point
```

See [docs/Architecture.md](docs/Architecture.md) for detailed documentation and [docs/ADR/](docs/ADR/) for architecture decision records.

### AI Providers

ProjectionAI uses a plugin-based architecture for AI providers. Install only what you need:

```bash
# All providers
uv sync --group all

# Individual
uv sync --group gemini
uv sync --group openai
uv sync --group anthropic
uv sync --group replicate
```

Set the active provider via `PROJECTIONAI_AI_PROVIDER` in `.env`.

---

## Project Status

Current release: **v0.1.0** — see the [Roadmap](docs/Roadmap.md) for milestone tracking and [CHANGELOG.md](CHANGELOG.md) for release history.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, and PR workflow.

---

## License

Licensed under the [MIT License](LICENSE).
