# Contributing to ProjectionAI

## Development Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/your-org/projectionai.git
   cd projectionai
   ```

2. Create and activate the virtual environment:

   ```bash
   uv sync
   .venv\Scripts\activate  # Windows
   # source .venv/bin/activate  # macOS/Linux
   ```

3. Install pre-commit hooks:

   ```bash
   pre-commit install
   ```

4. Configure your AI provider:
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

## Code Style

- **Linting**: `ruff check src/`
- **Formatting**: `ruff format src/` (automatically run by pre-commit)
- **Type checking**: `mypy src/projectionai/`
- All checks must pass before committing.

## Testing

- Run tests: `pytest`
- Run with coverage: `pytest --cov=src/projectionai`
- Tests live in `tests/unit/` and `tests/integration/`
- Test files follow `test_<module>.py` naming convention.

## Pull Request Workflow

1. Create a feature branch from `main`: `git checkout -b feature/my-feature`
2. Make your changes with atomic commits
3. Run all checks locally
4. Push and open a PR against `main`
5. Ensure CI passes
6. Request review from a maintainer

## Commit Messages

Follow conventional commits format: `type(scope): description`

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `style`

## Issue Guidelines

- Bug reports: include steps to reproduce, expected vs actual behaviour, environment details
- Feature requests: describe the use case and proposed solution
- Questions: use GitHub Discussions
