# ProjectionAI

**AI-powered projection mapping platform.**

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

## Quick Start

```bash
# Prerequisites: Python 3.12+, pip

# Clone and install
git clone https://github.com/your-org/projectionai.git
cd projectionai

# Create virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

# Install base + development dependencies
pip install -e ".[dev]"

# Configure AI provider (copy and edit)
cp .env.example .env
# Edit .env with your API keys

# Run
python -m projectionai
```

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                        UI Layer                         │
│            PySide6 · MVVM · ViewModels                  │
├─────────────────────────────────────────────────────────┤
│                     Application Layer                   │
│                 Use Cases · Workflows                    │
├────────────────────────┬────────────────────────────────┤
│    Domain Models       │        Services (ifaces)       │
│  Scene · Object ·      │  Vision · AI · Renderer        │
│  Surface · Calibration │  Calibration · Storage         │
├────────────────────────┴────────────────────────────────┤
│                   Infrastructure                        │
│  AI Providers  │  Vision CV  │  ModernGL   │  SQLite    │
│  (plugin)      │  (OpenCV)   │  (OpenGL)   │            │
└─────────────────────────────────────────────────────────┘
```

See [docs/Architecture.md](docs/Architecture.md) for detailed documentation.

## Project Structure

```
src/projectionai/          # Main package
├── core/                  # Framework: plugin system, event bus, config, errors
├── domain/                # Business models: scene, object, surface, calibration
├── services/              # Abstractions: vision, AI, renderer, calibration, storage
├── infrastructure/        # Implementations: AI providers, OpenCV, ModernGL, SQLite
├── application/           # Use cases: scan, generate, warp, preview, project
├── ui/                    # PySide6: main window, viewmodels, views, widgets
├── app.py                # Application bootstrap / DI container
└── main.py               # CLI entry point
```

## AI Providers

ProjectionAI uses a plugin-based architecture for AI providers.
Install only the providers you need:

```bash
# All providers
pip install -e ".[all]"

# Individual
pip install -e ".[gemini]"
pip install -e ".[openai]"
pip install -e ".[anthropic]"
pip install -e ".[replicate]"
```

Set the active provider via the `PROJECTIONAI_AI_PROVIDER` environment variable
in your `.env` file.

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type check
mypy src/projectionai

# Lint
ruff check src/projectionai

# Format
black src/projectionai
isort src/projectionai
```

## License

Proprietary. All rights reserved.
