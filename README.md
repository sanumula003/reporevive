# reporevive

CLI tool that resurrects abandoned GitHub repositories — rebuilds environments, fixes broken dependencies, migrates deprecated APIs, and verifies the project runs.

Uses [opencode](https://github.com/anomalyco/opencode) for LLM-powered code repair (no API key needed).

## Install

```bash
git clone https://github.com/sanumula003/reporevive.git
cd reporevive
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Requires opencode CLI: `curl -fsSL https://opencode.ai/install.sh | bash`

## Usage

```bash
reporevive analyze <repo-url-or-path>      # inspect only, no changes
reporevive revive <repo-url-or-path>       # full pipeline with repair
reporevive revive <path> --no-repair       # skip LLM repair
```

### Example: resurrecting robobrowser (last commit 2015)

```
$ reporevive revive /tmp/robobrowser

╭───────────────────────────────────╮
│ 📦 RepoRevive v0.1.0              │
╰───────────────────────────────────╯
Using local repo: /tmp/robobrowser

📊 Repository Analysis
  Language:        python
  Dependencies:    12 packages
  ⚠  No Python version constraint found

📦 Building environment...
✓ Environment built successfully
⚠ 1 import errors detected          ← from werkzeug import cached_property (removed in 2024)

🔧 Starting repair — 1 errors      ← opencode fixes: werkzeug → werkzeug.utils
Total fixes applied: 1

📦 Rebuilding after repairs...
✓ Environment built successfully

🔍 Verifying project...
  ✓ import docs
  ✓ import robobrowser

✓ Project verified successfully!
```

## Pipeline

```
Clone → Analyze → Build → (fails?) → Repair → Rebuild → Verify
```

| Step | Module | What it does |
|------|--------|-------------|
| Analyze | `analyzer.py` | Scans for `.py`, `requirements.txt`, `setup.py`, `pyproject.toml`. Detects language, frameworks, Python version, Dockerfile, CI. |
| Build | `environment.py` | Creates `.phoenix-venv/`, runs `pip install`, captures stderr per file. |
| Repair | `repairer.py` | Sends errors + source context to `opencode run`. Parses response for code fixes (`# FIX: path`) and dependency additions (`# DEP: pkg`). Retries up to 3 rounds. |
| Verify | `verifier.py` | Checks imports, runs pytest/unittest, tries launching entry points (`main.py`, `app.py`). |

## Files

```
reporevive/
├── cli.py              # Click entry point: revive & analyze commands
├── analyzer.py          # Repo analysis (language, deps, framework detection)
├── environment.py       # venv setup, pip install, error parsing, import checks
├── repairer.py          # opencode-backed repair pipeline
├── verifier.py          # Import verification, test runner, entry point detection
└── utils.py             # git clone, subprocess, file I/O helpers
```

## Fixes it can apply

| Type | Example |
|------|---------|
| Deprecated imports | `from werkzeug import cached_property` → `from werkzeug.utils import cached_property` |
| API migrations | `collections.MutableMapping` → `collections.abc.MutableMapping` |
| Missing deps | Detects `ModuleNotFoundError` and adds to `requirements.txt` |
| Version pinning | Replaces unavailable versions with compatible ranges |
| Python 2→3 | `urlparse` → `urllib.parse.urlparse`, `basestring` → `str` |
| Config files | Generates missing `requirements.txt`, `setup.cfg` |

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```
