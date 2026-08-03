"""Node.js/npm project support — analyze, build, and repair."""

import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from reporevive.utils import run_command, read_file, write_file, console


@dataclass
class NodeAnalysis:
    """Analysis of a Node.js project."""
    language: str = "javascript"
    has_package_json: bool = False
    has_lockfile: bool = False
    node_version: Optional[str] = None
    dependencies: list[str] = field(default_factory=list)
    dev_dependencies: list[str] = field(default_factory=list)
    scripts: dict = field(default_factory=dict)
    framework: Optional[str] = None
    entry_point: Optional[str] = None


def analyze_node(repo_path: Path) -> NodeAnalysis:
    """Analyze a Node.js project."""
    result = NodeAnalysis()
    pkg_json = repo_path / "package.json"

    if not pkg_json.exists():
        return result

    result.has_package_json = True
    result.has_lockfile = (repo_path / "package-lock.json").exists() or (repo_path / "yarn.lock").exists()

    try:
        data = json.loads(read_file(pkg_json))
    except Exception:
        console.print("[yellow]⚠ package.json is invalid JSON[/yellow]")
        return result

    result.dependencies = sorted(data.get("dependencies", {}).keys())
    result.dev_dependencies = sorted(data.get("devDependencies", {}).keys())
    result.scripts = data.get("scripts", {})

    # Detect framework
    all_deps = set(result.dependencies + result.dev_dependencies)
    _FRAMEWORKS = {
        "react": "React",
        "next": "Next.js",
        "vue": "Vue.js",
        "nuxt": "Nuxt",
        "express": "Express",
        "fastify": "Fastify",
        "nestjs": "NestJS",
        "angular": "Angular",
        "svelte": "Svelte",
        "astro": "Astro",
        "gatsby": "Gatsby",
        "remix": "Remix",
    }
    for dep, name in _FRAMEWORKS.items():
        if dep in all_deps or dep in str(data.get("name", "")):
            result.framework = name
            break

    # Detect entry point
    result.entry_point = data.get("main") or data.get("module") or "index.js"

    # Detect node version
    engines = data.get("engines", {})
    if "node" in engines:
        result.node_version = engines["node"]

    # Check .nvmrc
    nvmrc = repo_path / ".nvmrc"
    if nvmrc.exists():
        result.node_version = nvmrc.read_text().strip()

    _log_node_analysis(result)
    return result


def build_node(repo_path: Path) -> tuple[bool, list[str]]:
    """Run npm install. Returns (success, errors)."""
    pkg_json = repo_path / "package.json"
    if not pkg_json.exists():
        return False, ["No package.json found"]

    # Check if node_modules already exists
    if (repo_path / "node_modules").exists():
        console.print("[dim]node_modules exists, running npm install...[/dim]")

    console.print("[dim]Running npm install...[/dim]")
    rc, out, err = run_command("npm install --no-audit --no-fund 2>&1", repo_path, timeout=300)

    errors = []
    if rc != 0:
        for line in (out + err).splitlines():
            line_lower = line.lower()
            if "error" in line_lower or "ERR!" in line or "failed" in line_lower:
                errors.append(line.strip())

    if rc == 0:
        console.print("[green]✓[/green] npm install succeeded")
    else:
        console.print(f"[yellow]⚠[/yellow] npm install failed with {len(errors)} errors")

    return rc == 0, errors


def check_node_entry(repo_path: Path, analysis: NodeAnalysis) -> list[str]:
    """Check if the entry point file exists and can be parsed."""
    errors = []
    if analysis.entry_point:
        ep = repo_path / analysis.entry_point
        if not ep.exists():
            errors.append(f"Entry point '{analysis.entry_point}' not found")
    else:
        errors.append("No entry point specified in package.json")
    return errors


def generate_node_dockerfile(repo_path: Path, analysis: NodeAnalysis) -> Path:
    """Generate a Dockerfile for a Node.js project."""
    node_ver = analysis.node_version or "18"
    node_ver = re.sub(r'[^\d.]', '', node_ver) or "18"

    df = repo_path / "Dockerfile"
    content = f"""FROM node:{node_ver}-slim

WORKDIR /app

COPY package.json {"package-lock.json" if analysis.has_lockfile else ""} ./

RUN npm install --production

COPY . .

{f"CMD [\"node\", \"{analysis.entry_point or 'index.js'}\"]" if analysis.entry_point else "# Add your CMD here"}
"""
    write_file(df, content.strip() + "\n")
    console.print(f"  [green]✓[/green] Generated Node.js Dockerfile (node:{node_ver})")
    return df


def _log_node_analysis(a: NodeAnalysis) -> None:
    """Pretty-print Node.js analysis."""
    console.print()
    console.print("[bold cyan]📊 Node.js Analysis[/bold cyan]")
    console.print(f"  Language:        [green]javascript[/green]")
    if a.framework:
        console.print(f"  Framework:       [yellow]{a.framework}[/yellow]")
    console.print(f"  Dependencies:    {len(a.dependencies)} runtime, {len(a.dev_dependencies)} dev")
    console.print(f"  Lockfile:        {'[green]yes' if a.has_lockfile else '[yellow]no[/yellow]'}")
    if a.node_version:
        console.print(f"  Node version:    [green]{a.node_version}[/green]")
    if a.scripts:
        cmds = ", ".join(a.scripts.keys())
        console.print(f"  Scripts:         [dim]{cmds}[/dim]")
