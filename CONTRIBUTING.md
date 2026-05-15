# Contributing to VidDup

Thank you for your interest in contributing! VidDup is a small, focused tool and contributions of all sizes are welcome.

---

## Getting Started

```bash
git clone https://github.com/Pengfei-Kou/viddup.git
cd viddup

# Create virtual environment and install in editable mode with dev dependencies
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Verify everything works
pytest
viddup --help
```

---

## Project Structure

```
viddup/
├── viddup/
│   ├── cli.py              # Click CLI entry point
│   ├── config.py           # Config dataclass and constants
│   ├── core/
│   │   ├── scanner.py      # Directory scan + .viddup_ignore
│   │   ├── database.py     # SQLite fingerprint cache
│   │   ├── fingerprinter.py # L1/L2/L3 fingerprint generation
│   │   ├── comparator.py   # Similarity comparison + grouping
│   │   ├── reporter.py     # Rich terminal + JSON output
│   │   └── html_reporter.py # Self-contained HTML report
│   └── utils/
│       └── ffmpeg_utils.py # ffprobe/ffmpeg subprocess wrappers
└── tests/
    ├── conftest.py
    ├── test_scanner.py
    ├── test_comparator.py
    └── test_fingerprinter.py
```

---

## Development Workflow

### Running Tests

```bash
pytest                  # all tests
pytest -v               # verbose output
pytest tests/test_scanner.py  # specific file
```

### Linting

```bash
ruff check viddup/ tests/   # lint
ruff format viddup/ tests/  # format
```

### Type Checking

```bash
mypy viddup/
```

---

## Making Changes

### Bug Fixes

1. Write a failing test that reproduces the bug
2. Fix the code
3. Confirm the test passes
4. Open a PR with a clear description of the bug and the fix

### New Features

1. Open an issue first to discuss the idea — this avoids duplicate work
2. Keep changes focused and minimal
3. Add tests for new behaviour
4. Update the README if the feature is user-facing

### Algorithm Changes

Changes to the core fingerprinting or comparison logic should include:
- A description of what the change improves and why
- Evidence that it reduces false positives or false negatives (test cases or real-world examples)

---

## Code Style

- Python 3.11+ features are welcome (match statements, `X | Y` unions, etc.)
- Type annotations are required for all public functions
- Docstrings use plain English — no need for NumPy or Google style
- Keep functions small and focused; prefer pure functions where possible

---

## Commit Messages

Use concise, imperative-mood messages:

```
Add .viddup_ignore support to scanner
Fix false positive when video starts with black frames
Bump threshold default from 0.80 to 0.85
```

---

## Reporting Issues

When filing a bug, please include:

- OS and Python version
- `ffmpeg -version` output
- The command you ran
- The error message or unexpected behaviour
- If possible, a minimal reproduction case

---

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
