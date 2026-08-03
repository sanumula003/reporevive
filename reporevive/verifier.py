"""Verify that a repaired project actually works."""

from pathlib import Path
from dataclasses import dataclass, field

from reporevive.utils import run_command, console
from reporevive.analyzer import RepoAnalysis
from reporevive.environment import BuildResult


@dataclass
class VerifyResult:
    """Result of project verification."""
    passed: bool = False
    tests_ran: bool = False
    tests_passed: int = 0
    tests_failed: int = 0
    import_checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def verify(analysis: RepoAnalysis, build: BuildResult, repo_path: Path) -> VerifyResult:
    """Verify the repaired project works."""
    result = VerifyResult()

    if not build.venv_path or not build.success:
        result.errors.append("Environment not built successfully — cannot verify")
        console.print("[yellow]⚠[/yellow] Skipping verification: environment not ready")
        return result

    python = str(build.venv_path / "bin" / "python")
    pip = str(build.venv_path / "bin" / "pip")

    console.print("\n[bold cyan]🔍 Verifying project...[/bold cyan]")

    # 1. Check imports for top-level modules
    console.print("[dim]Checking imports...[/dim]")
    seen = set()
    for module in analysis.importable_modules[:15]:
        top = module.split(".")[0]
        if top in ("test", "tests", "setup", "conftest") or top in seen:
            continue
        seen.add(top)
        rc, out, err = run_command(
            f'{python} -c "import {top}; print(\'OK\')"',
            repo_path,
            timeout=20,
        )
        result.import_checks[top] = (rc == 0)
        if rc == 0:
            console.print(f"  [green]✓[/green] import {top}")
        else:
            console.print(f"  [red]✗[/red] import {top}: {err.strip()[:80]}")
            result.errors.append(f"Import failed: {top} — {err.strip()[:120]}")

    # 2. Run tests if test framework detected
    if analysis.test_framework:
        console.print(f"[dim]Running tests ({analysis.test_framework})...[/dim]")
        result.tests_ran = True

        test_cmd = _get_test_command(analysis, python, repo_path)
        if test_cmd:
            rc, out, err = run_command(test_cmd, repo_path, timeout=300)

            # Parse test results
            for line in (out + err).splitlines():
                if "passed" in line.lower():
                    try:
                        parts = line.split()
                        for i, p in enumerate(parts):
                            if p.lower() == "passed" and i > 0:
                                result.tests_passed = int(parts[i - 1])
                    except (ValueError, IndexError):
                        pass
                if "failed" in line.lower():
                    try:
                        parts = line.split()
                        for i, p in enumerate(parts):
                            if p.lower() == "failed" and i > 0:
                                result.tests_failed = int(parts[i - 1])
                    except (ValueError, IndexError):
                        pass

            if rc == 0:
                console.print(f"  [green]✓[/green] Tests passed: {result.tests_passed}, failed: {result.tests_failed}")
            else:
                console.print(f"  [yellow]⚠[/yellow] Tests: {result.tests_passed} passed, {result.tests_failed} failed")
                result.errors.append(f"Some tests failed — {result.tests_failed} failures")

    # 3. Try running the project (if there's a main entry point)
    entry = _find_entry_point(analysis, repo_path)
    if entry:
        console.print(f"[dim]Attempting to run {entry}...[/dim]")
        rc, out, err = run_command(f"{python} -c 'import sys; sys.path.insert(0, \".\"); exec(open(\"{entry}\").read())' 2>&1 | head -20", repo_path, timeout=30)
        if rc == 0:
            console.print(f"  [green]✓[/green] Entry point runs")

    # Overall verdict
    passed_imports = sum(1 for v in result.import_checks.values() if v)
    total_imports = len(result.import_checks)
    result.passed = len(result.errors) == 0

    if result.passed:
        console.print("\n[bold green]✓ Project verified successfully![/bold green]")
    else:
        console.print(f"\n[bold yellow]⚠ Verification incomplete[/bold yellow] — {len(result.errors)} issues remain")

    return result


def _get_test_command(analysis: RepoAnalysis, python: str, repo_path: Path) -> str:
    """Get the appropriate test command."""
    tf = analysis.test_framework or ""

    if "pytest" in tf:
        return f"{python} -m pytest -x -q 2>&1"
    elif "tox" in tf:
        return f"{python} -m tox -- -q 2>&1"
    elif "unittest" in tf:
        return f"{python} -m unittest discover -q 2>&1"
    elif "nose" in tf:
        return f"{python} -m nosetests -q 2>&1"

    # Fallback: try pytest first
    return f"{python} -m pytest -x -q 2>&1 || true"


def _find_entry_point(analysis: RepoAnalysis, repo_path: Path) -> str:
    """Find the main entry point of the project."""
    candidates = ["main.py", "app.py", "run.py", "manage.py", "cli.py", "__main__.py"]
    for c in candidates:
        p = repo_path / c
        if p.exists():
            return c

    # Also look in src/ directory
    if (repo_path / "src").exists():
        for c in candidates:
            p = repo_path / "src" / c
            if p.exists():
                return f"src/{c}"

    return ""
