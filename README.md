# Phoenix AI — Autonomous Software Archaeologist 🐦‍🔥

**One-line pitch:** An AI system that resurrects abandoned GitHub repositories — rebuilding environments, repairing dependency breakages, migrating deprecated APIs, and producing a runnable project.

## Installation

```bash
git clone https://github.com/sanumula003/phoenix-ai.git
cd phoenix-ai
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Set your OpenAI API key:

```bash
export OPENAI_API_KEY=sk-...
```

## Usage

### Analyze a repository

```bash
phoenix analyze https://github.com/user/repo
```

### Resurrect a repository

```bash
phoenix revive https://github.com/user/repo
```

Options:

- `--target /path/to/output` — Clone to a specific directory
- `--model gpt-4o` — Use a different OpenAI model for repair
- `--max-rounds 5` — More repair rounds for stubborn issues
- `--no-repair` — Skip LLM repair (just analyze, build, verify)

## How It Works

```
Clone → Analyze → Build → Repair → Verify → Done
```

1. **Analyze** — Detect language, framework, dependencies, Python version constraints, Dockerfile/CI presence
2. **Build** — Create venv, install dependencies, capture errors
3. **Repair** — LLM-powered analysis of build failures; generates targeted file fixes and dependency additions
4. **Verify** — Import checks, test runner, entry point validation

## Supported Repair Patterns

- Deprecated Python APIs (collections → collections.abc, etc.)
- Missing dependency inference from imports
- Python 2 → 3 migrations
- Broken requirements.txt / setup.py / pyproject.toml
- Missing configuration files
- Import errors from incorrect package names

## Architecture

```
phoenix/
├── cli.py           # Click CLI with revive & analyze commands
├── analyzer.py      # Repo analysis: language, deps, framework, structure
├── environment.py   # Virtual environment setup + dependency installation
├── repairer.py      # LLM pipeline: error → prompt → fix → apply
├── verifier.py      # Import checks, test runner, build verification
└── utils.py         # Git operations, subprocess, file I/O helpers
```

## Roadmap

- **V1** — Detect environment and dependency issues ✅
- **V2** — Repair code using LLMs and AST-based transformations ✅
- **V3** — Generate tests and validate fixes automatically
- **V4** — Learn repair strategies from historical GitHub fixes
- **Multi-language** — Node.js, Rust, Java support
- **Docker generation** — Auto-create Dockerfiles for resurrected projects
