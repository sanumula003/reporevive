"""Build and manage the project environment (venv, pip, dependency installation)."""

import sys
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

from reporevive.utils import run_command, read_file, write_file, console
from reporevive.analyzer import RepoAnalysis


@dataclass
class BuildResult:
    """Result of attempting to build/install a project."""
    success: bool = False
    venv_path: Optional[Path] = None
    install_errors: list[str] = field(default_factory=list)
    missing_packages: list[str] = field(default_factory=list)
    version_conflicts: list[str] = field(default_factory=list)
    pip_output: str = ""


def setup_environment(analysis: RepoAnalysis, repo_path: Path) -> BuildResult:
    """Set up a Python virtual environment and install dependencies.

    Returns BuildResult with success status and any errors.
    """
    result = BuildResult()

    # Create venv
    venv_dir = repo_path / ".phoenix-venv"
    if venv_dir.exists():
        shutil.rmtree(venv_dir)

    console.print("[dim]Creating virtual environment...[/dim]")
    rc, out, err = run_command(f"{sys.executable} -m venv {venv_dir}", repo_path)
    if rc != 0:
        result.install_errors.append(f"Failed to create venv: {err}")
        return result

    result.venv_path = venv_dir
    pip = str(venv_dir / "bin" / "pip")
    python = str(venv_dir / "bin" / "python")

    # Upgrade pip
    run_command(f"{python} -m pip install --upgrade pip --quiet", repo_path, timeout=120)

    # Install from requirements.txt
    req_files = [f for f in analysis.dependency_files if f.name.startswith("requirements")]
    if req_files:
        for req_file in req_files:
            console.print(f"[dim]Installing from {req_file.name}...[/dim]")
            rc, out, err = run_command(f"{pip} install -r {req_file} 2>&1", repo_path, timeout=600)
            result.pip_output += out + "\n" + err
            if rc != 0:
                _parse_install_errors(out + err, result)

    # Install from pyproject.toml
    for f in analysis.dependency_files:
        if f.name == "pyproject.toml":
            console.print("[dim]Installing from pyproject.toml...[/dim]")
            rc, out, err = run_command(f"{pip} install -e . 2>&1", repo_path, timeout=600)
            result.pip_output += out + "\n" + err
            if rc != 0:
                _parse_install_errors(out + err, result)

    # Install from setup.py (fallback if no requirements.txt or pyproject.toml)
    has_setup_py = any(f.name == "setup.py" for f in analysis.dependency_files)
    has_any_install = req_files or any(f.name == "pyproject.toml" for f in analysis.dependency_files)
    if has_setup_py and not has_any_install:
        console.print("[dim]Installing from setup.py...[/dim]")
        rc, out, err = run_command(f"{pip} install -e . 2>&1", repo_path, timeout=600)
        result.pip_output += out + "\n" + err
        if rc != 0:
            _parse_install_errors(out + err, result)

    result.success = len(result.install_errors) == 0

    if result.success:
        console.print("[green]✓[/green] Environment built successfully")
    else:
        console.print(f"[yellow]⚠[/yellow] Environment built with {len(result.install_errors)} issues")

    return result


def _parse_install_errors(output: str, result: BuildResult) -> None:
    """Parse pip install output for specific error types."""
    lines = output.splitlines()

    for line in lines:
        line_lower = line.lower()

        # Missing package
        if "no matching distribution found" in line_lower or "could not find a version" in line_lower:
            # Extract package name
            pkg = line.split("for ")[-1].strip() if "for " in line else ""
            if pkg:
                result.missing_packages.append(pkg)

        # Version conflict
        if "conflicting" in line_lower or "incompatible" in line_lower or "version conflict" in line_lower:
            result.version_conflicts.append(line.strip())

        # General error
        if "error:" in line_lower or "failed" in line_lower:
            result.install_errors.append(line.strip())


def check_imports(analysis: RepoAnalysis, result: BuildResult, repo_path: Path) -> list[str]:
    """Check if key modules can be imported. Returns list of error strings."""
    if not result.venv_path:
        return ["No virtual environment available"]

    python = str(result.venv_path / "bin" / "python")
    errors = []
    seen = set()

    for module in analysis.importable_modules[:15]:
        top = module.split(".")[0]
        if top in ("test", "tests", "setup", "conftest", "docs", "examples") or top in seen:
            continue
        seen.add(top)

        rc, out, err = run_command(
            f'{python} -c "import {top}" 2>&1',
            repo_path,
            timeout=15,
        )
        if rc != 0:
            error_line = err.strip().split("\n")[-1] if err.strip() else "Import failed"
            errors.append(f"Import '{top}' failed: {error_line}")

    return errors
