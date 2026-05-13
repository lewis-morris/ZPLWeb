# Repository Guidelines

## Project Structure & Modules
- `ZPLWeb/`: Application code.
  - `main.py`: PySide6 GUI and Socket.IO client; entrypoint for `zplweb`.
  - `utils.py`: helpers (e.g., resource path, fingerprints).
  - `assets/`: app icons and bundled resources.
- `tests/`: Pytest-based tests (e.g., `test_utils.py`).
- `ZPLWeb.spec`: PyInstaller build spec.
- `pyproject.toml`: tooling config (Black, isort, Flake8) and console script.
- `requirements.txt`, `README.md`: dependencies and quickstart.

## Build, Test, and Development
- Create venv and install:
  - `python -m venv .venv && source .venv/bin/activate`
  - `pip install -r requirements.txt`
  - Optional (for CLI entrypoint): `pip install -e .`
- Run app (dev): `python -m ZPLWeb.main` or `zplweb`
- Run tests: `pytest -q`
- Lint/format: `flake8`, `black .`, `isort .`
- Build executable: `pyinstaller ZPLWeb.spec`

## Coding Style & Naming
- Formatting: Black (line length 88), isort aligned with Black; Flake8 rules in `.flake8` and `pyproject.toml`.
- Python style: 4-space indents; `snake_case` functions, `PascalCase` classes, `UPPER_CASE` constants.
- Type hints preferred for new/changed code.
- Keep modules focused; UI in `main.py`, helpers in `utils.py`.

## Testing Guidelines
- Framework: Pytest. Place tests in `tests/` named `test_*.py`.
- Write unit tests for added utilities and side-effect boundaries where feasible.
- Run locally with `pytest -q`; avoid requiring a printer in tests.

## Commit & Pull Requests
- Commits: concise, imperative summaries (e.g., "Add tray menu action"). No strict conventional commit requirement in history.
- PRs should include:
  - Clear description of behavior change and rationale.
  - Steps to run (`python -m ZPLWeb.main`, `pytest`) and any screenshots of UI changes.
  - Notes on platform impact (Windows printing via `win32print`).

## Security & Configuration Tips
- Secrets: do not hardcode API keys. Configure via the app Options dialog; values persist with `QSettings` (scope `ColemanAgent/PrintAgent`).
- Data: print history stored in SQLite at OS user data dir (`appdirs.user_data_dir("ColemanAgent", "Coleman")/prints.sqlite`). Avoid committing artifacts.
- Non‑Windows hosts skip physical printing; use Test ZPL dialog for validation.

