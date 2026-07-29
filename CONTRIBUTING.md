# Contributing to Hermetic Club

Thank you for your interest in contributing to **Hermetic Club**! This document will guide you through the process of setting up your development environment, running tests, and submitting changes.

## Table of Contents

- [Development Setup](#development-setup)
- [Running Tests](#running-tests)
- [Code Style](#code-style)
- [Submitting Changes](#submitting-changes)
- [Reporting Issues](#reporting-issues)
- [Security](#security)

## Development Setup

### Prerequisites

- **Python 3.11+** (recommended: Python 3.12)
- **uv** (recommended package manager) or **pip**
- **Git**
- **SQLite** (included with Python)

### 1. Clone the Repository

```bash
git clone https://github.com/luluthehungrycat/hermetic-club.git
cd hermetic-club
```

### 2. Install Dependencies

#### Using uv (recommended)

```bash
# Install the package in development mode
uv pip install -e ".[dev]"
```

#### Using pip

```bash
pip install -e ".[dev]"
```

### 3. Set Up Configuration

Generate a default configuration file:

```bash
hclub init
```

This creates a configuration file at `~/.hermetic-club/config.yaml`. You can edit it to customize your setup:

```yaml
# ~/.hermetic-club/config.yaml
host: "127.0.0.1"
port: 8765
secret_key: "your-strong-random-secret-here"  # Auto-generated if not set
```

> **Note:** If `secret_key` is not set, Hermetic Club will **automatically generate a secure random key** on startup.

### 4. Run the Server

```bash
hclub serve
```

The server will start on `http://127.0.0.1:8765`. Open this URL in your browser to access the web UI.

## Running Tests

Hermetic Club uses **pytest** for testing. We have two types of tests:

1. **Unit tests** – Fast, isolated tests that don't require a running server.
2. **Smoke tests** – Integration tests that require a running Hermetic Club server.

### Unit Tests

Run all unit tests:

```bash
pytest tests/ -m "not smoke"
```

### Smoke Tests

Smoke tests require a running Hermetic Club server. Start the server in one terminal:

```bash
# Terminal 1
HC_SECRET_KEY="test-secret" hclub serve
```

Then run the smoke tests in another terminal:

```bash
# Terminal 2
pytest tests/test_smoke.py
```

### Rate Limit Tests

Test rate limiting functionality:

```bash
pytest tests/test_rate_limits.py -v
```

### All Tests

Run all tests (unit + smoke + rate limits):

```bash
# Start the server first (see above)
pytest tests/
```

## Code Style

Hermetic Club follows these style guidelines:

- **Python:** PEP 8 (with some exceptions)
- **Type Hints:** Strongly encouraged (Python 3.11+)
- **Docstrings:** Google-style docstrings for public functions/classes
- **Line Length:** 88 characters (soft limit)

### Formatting

We use **ruff** for linting and formatting:

```bash
# Check code style
ruff check src/ tests/

# Fix code style issues
ruff format src/ tests/
```

### Type Checking

We use **mypy** for static type checking:

```bash
mypy src/
```

## Submitting Changes

### 1. Fork the Repository

Create a fork of [hermetic-club](https://github.com/luluthehungrycat/hermetic-club) on GitHub.

### 2. Create a Feature Branch

```bash
git checkout -b feat/your-feature-name
```

Use a descriptive branch name:

- `feat/` for new features
- `fix/` for bug fixes
- `docs/` for documentation changes
- `refactor/` for code refactoring
- `chore/` for maintenance tasks

### 3. Make Your Changes

- Follow the [Code Style](#code-style) guidelines.
- Add tests for new functionality.
- Update documentation if needed.

### 4. Commit Your Changes

Use clear, descriptive commit messages:

```bash
git commit -m "feat: add rate limiting for handoffs"
```

### 5. Push to Your Fork

```bash
git push origin feat/your-feature-name
```

### 6. Open a Pull Request

1. Go to the [Hermetic Club repository](https://github.com/luluthehungrycat/hermetic-club) on GitHub.
2. Click **"Pull requests"** > **"New pull request"**.
3. Select your fork and branch.
4. Fill out the PR template with:
   - A clear title
   - A description of your changes
   - Any related issues (use `Closes #123` to auto-close issues)
5. Click **"Create pull request"**.

### Pull Request Guidelines

- **Title:** Clear and concise (e.g., "feat: add Telegram bot integration")
- **Description:** Explain what your PR does and why it's needed
- **Tests:** All tests must pass
- **Code Review:** At least one maintainer must approve your PR
- **Squash Merge:** We prefer squash merges for clean history

## Reporting Issues

### Bug Reports

When reporting a bug, please include:

1. **Python version** (`python --version`)
2. **Hermetic Club version** (`hclub --version`)
3. **Operating System** (Linux, macOS, Windows)
4. **Steps to reproduce** the issue
5. **Expected behavior** vs. **actual behavior**
6. **Relevant logs** (if applicable)

### Feature Requests

For feature requests, please:

1. Check if the feature already exists or is in the [Roadmap](#roadmap)
2. Open an issue with:
   - A clear description of the feature
   - The use case or problem it solves
   - Any relevant examples or mockups

## Security

If you discover a **security vulnerability**, please **do not** open a public issue. Instead, follow the instructions in our [Security Policy](https://github.com/luluthehungrycat/hermetic-club/security/policy).

## Roadmap

Check the [README.md](README.md#roadmap) for the current roadmap and planned features.

## License

By contributing to Hermetic Club, you agree that your contributions will be licensed under the **MIT License**. See [LICENSE](LICENSE) for details.

---

Thank you for contributing to Hermetic Club! Your help makes this project better for everyone.
