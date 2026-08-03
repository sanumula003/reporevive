"""Shared utilities: git operations, subprocess helpers, logging."""

import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional

from git import Repo, GitCommandError
from rich.console import Console

console = Console()


def clone_repo(url: str, target: Optional[Path] = None) -> Path:
    """Clone a GitHub repo to a directory. Returns the path."""
    if target is None:
        target = Path(tempfile.mkdtemp(prefix="phoenix_"))
    else:
        target.mkdir(parents=True, exist_ok=True)

    console.print(f"[dim]Cloning {url}...[/dim]")
    try:
        Repo.clone_from(url, str(target), depth=1)
    except GitCommandError as e:
        console.print(f"[red]Clone failed:[/red] {e}")
        raise
    console.print(f"[green]✓[/green] Cloned to {target}")
    return target


def run_command(cmd: str, cwd: Path, capture: bool = True, timeout: int = 300) -> tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=str(cwd),
            capture_output=capture,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


def find_files(root: Path, patterns: list[str]) -> list[Path]:
    """Find files matching patterns in a directory tree."""
    results = []
    for pattern in patterns:
        results.extend(root.rglob(pattern))
    return sorted(results)


def read_file(path: Path) -> str:
    """Read a file with encoding fallbacks."""
    for enc in ["utf-8", "latin-1", "cp1252"]:
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def write_file(path: Path, content: str) -> None:
    """Write content to a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
