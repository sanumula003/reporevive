"""Generate CI/CD pipeline configuration for resurrected projects."""

from pathlib import Path

from reporevive.utils import write_file, console


def generate_ci_python(repo_path: Path, python_version: str, has_tests: bool, test_cmd: str = "") -> Path:
    """Generate .github/workflows/ci.yml for a Python project."""

    py_ver = python_version.lstrip(">=^~") if python_version else "3.10"
    py_ver = py_ver.split(",")[0].strip()

    test_step = ""
    if test_cmd:
        test_step = f"\n      - name: Run tests\n        run: {test_cmd}"
    elif has_tests:
        test_step = "\n      - name: Run tests\n        run: python -m pytest -v"

    workflow_dir = repo_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)

    ci_file = workflow_dir / "ci.yml"
    content = f"""name: CI

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["{py_ver}", "3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{{{ matrix.python-version }}}}
        uses: actions/setup-python@v5
        with:
          python-version: ${{{{ matrix.python-version }}}}

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt || pip install -e .
          pip install pytest{test_step}
"""
    write_file(ci_file, content)
    console.print(f"  [green]✓[/green] Generated CI pipeline (.github/workflows/ci.yml)")
    return ci_file


def generate_ci_node(repo_path: Path, node_version: str, has_tests: bool) -> Path:
    """Generate .github/workflows/ci.yml for a Node.js project."""

    node_ver = node_version or "18"
    # Clean version string (remove >=, ^, ~, etc.)
    import re
    node_ver = re.sub(r'[^\d]', '', node_ver.split()[0] if node_ver else "18") or "18"

    test_step = ""
    if has_tests:
        test_step = "\n      - name: Run tests\n        run: npm test"

    workflow_dir = repo_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)

    ci_file = workflow_dir / "ci.yml"
    content = f"""name: CI

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node-version: [{node_ver}, 20, 22]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Node.js ${{{{ matrix.node-version }}}}
        uses: actions/setup-node@v4
        with:
          node-version: ${{{{ matrix.node-version }}}}
          cache: 'npm'

      - name: Install dependencies
        run: npm ci || npm install{test_step}
"""
    write_file(ci_file, content)
    console.print(f"  [green]✓[/green] Generated CI pipeline (.github/workflows/ci.yml)")
    return ci_file
