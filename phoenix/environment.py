"""Build and manage the project environment (venv, pip, dependency installation)."""

import sys
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

from phoenix.utils import run_command, read_file, write_file, console
from phoenix.analyzer import RepoAnalysis


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


def try_import(analysis: RepoAnalysis, result: BuildResult) -> dict[str, str]:
    """Attempt to import detected modules and return any errors."""
    if not result.venv_path or not result.success:
        return {}

    python = str(result.venv_path / "bin" / "python")
    import_errors = {}

    for module in analysis.importable_modules[:20]:  # Limit to avoid timeout
        # Only try top-level modules
        top = module.split(".")[0]
        rc, out, err = run_command(
            f'{python} -c "import {top}" 2>&1',
            result.venv_path.parent,
            timeout=30,
        )
        if rc != 0 and "ModuleNotFoundError" in err:
            import_errors[module] = err.strip()
        elif rc != 0:
            import_errors[module] = err.strip()

    return import_errors
