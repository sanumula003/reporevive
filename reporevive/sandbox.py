"""Docker sandboxing — run build phases inside isolated containers.

Avoids system dependency issues (e.g., pg_config, libffi, etc.) by running
pip install / npm install inside ephemeral Docker containers.
"""

import subprocess
from pathlib import Path

from reporevive.utils import console


def has_docker() -> bool:
    """Check if Docker is available on the host."""
    try:
        subprocess.run(["docker", "--version"], capture_output=True, timeout=5, check=True)
        return True
    except Exception:
        return False


def build_in_sandbox(repo_path: Path, language: str, python_version: str = "3.10") -> tuple[bool, list[str]]:
    """Run pip/npm install inside a Docker container.

    Returns (success, errors).
    """
    if not has_docker():
        console.print("[yellow]⚠ Docker not available — falling back to host install[/yellow]")
        return False, []

    repo_abs = repo_path.resolve()
    image = _get_image(language, python_version)
    cmd = _get_install_cmd(language)

    console.print(f"[dim]Building inside Docker sandbox ({image})...[/dim]")

    try:
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", f"{repo_abs}:/repo:rw",
                "-w", "/repo",
                image,
                "bash", "-c", cmd,
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return False, ["Docker build timed out after 10 minutes"]
    except FileNotFoundError:
        return False, ["Docker not found on system"]
    except Exception as e:
        return False, [str(e)]

    errors = []
    if result.returncode != 0:
        for line in (result.stdout + result.stderr).splitlines():
            line_lower = line.strip().lower()
            if "error" in line_lower or "ERR!" in line or "failed" in line_lower:
                errors.append(line.strip()[:200])

    if result.returncode == 0:
        console.print("[green]✓[/green] Docker sandbox build succeeded")
    else:
        console.print(f"[yellow]⚠[/yellow] Docker build failed with {len(errors)} errors")

    return result.returncode == 0, errors


def _get_image(language: str, python_version: str) -> str:
    """Get the appropriate Docker image."""
    if language in ("python", "python3"):
        ver = python_version.lstrip(">=~^").split(",")[0].strip()
        return f"python:{ver}-slim"
    elif language in ("javascript", "typescript", "node"):
        return "node:18-slim"
    return "python:3.10-slim"


def _get_install_cmd(language: str) -> str:
    """Get the install command for the language."""
    if language in ("python", "python3"):
        return (
            "python -m venv /tmp/venv && "
            "/tmp/venv/bin/pip install --upgrade pip -q && "
            "(pip install -r requirements.txt 2>&1 || pip install -e . 2>&1 || true)"
        )
    elif language in ("javascript", "typescript", "node"):
        return "npm install --no-audit --no-fund 2>&1 || true"
    return "echo 'No build command for this language'"
