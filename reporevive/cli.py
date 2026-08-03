"""CLI entry point for RepoRevive."""

import sys
from pathlib import Path

import click
from rich.panel import Panel

from reporevive import __version__
from reporevive.utils import clone_repo, console
from reporevive.analyzer import analyze, RepoAnalysis
from reporevive.environment import setup_environment, check_imports
from reporevive.repairer import Repairer
from reporevive.verifier import verify
from reporevive.infer import (
    infer_dependencies, generate_requirements, detect_python_version,
    generate_dockerfile, generate_readme,
)
from reporevive.lang_node import (
    analyze_node, build_node, check_node_entry, generate_node_dockerfile,
)
from reporevive.ci_gen import generate_ci_python, generate_ci_node


@click.group()
@click.version_option(__version__, prog_name="reporevive")
def main():
    """RepoRevive — Resurrect abandoned GitHub repositories."""
    pass


@main.command()
@click.argument("url")
@click.option("--target", "-t", default=None, help="Target directory for the cloned repo")
@click.option("--model", "-m", default="gpt-4o-mini", help="Model for code repair")
@click.option("--max-rounds", default=3, help="Maximum repair rounds")
@click.option("--no-repair", is_flag=True, help="Skip LLM repair, just analyze and build")
def revive(url: str, target: str | None, model: str, max_rounds: int, no_repair: bool):
    """Resurrect an abandoned GitHub repository.

    URL: GitHub repository URL or local path.

    Pipeline: Clone → Analyze → Build → Repair → Verify → Generate
    """
    console.print()
    console.print(Panel.fit(
        f"[bold cyan]📦 RepoRevive[/bold cyan] [dim]v{__version__}[/dim]\n"
        "[dim]Autonomous Software Archaeologist[/dim]",
        border_style="cyan",
    ))

    target_path = Path(target) if target else None

    # Step 1: Clone
    if url.startswith("http://") or url.startswith("https://") or url.startswith("git@"):
        repo_path = clone_repo(url, target_path)
    else:
        repo_path = Path(url).resolve()
        if not repo_path.exists():
            console.print(f"[red]Path not found:[/red] {repo_path}")
            sys.exit(1)
        console.print(f"[dim]Using local repo: {repo_path}[/dim]")

    # Step 2: Analyze
    analysis = analyze(repo_path)

    if analysis.language == "javascript" or analysis.language == "typescript":
        console.print(f"\n[dim]Detected: Node.js project[/dim]")
        _revive_node(repo_path, url, model, max_rounds, no_repair)
        return

    if analysis.language != "python":
        console.print(f"\n[yellow]⚠ RepoRevive currently supports Python and Node.js projects.[/yellow]")
        console.print(f"[dim]Detected language: {analysis.language}[/dim]")
        return

    # v0.2: Infer deps if none found
    if not analysis.dependency_files:
        console.print("\n[bold yellow]⚠ No dependency files found — inferring from imports...[/bold yellow]")
        packages = infer_dependencies(repo_path)
        if packages:
            generate_requirements(repo_path, packages)
            analysis = analyze(repo_path)  # re-analyze with new deps

    # Step 3: Build environment
    console.print("\n[bold cyan]📦 Building environment...[/bold cyan]")
    build_result = setup_environment(analysis, repo_path)

    # Step 3.5: Check imports if build succeeded
    import_errors = []
    if build_result.success:
        import_errors = check_imports(analysis, build_result, repo_path)
        if import_errors:
            console.print(f"[yellow]⚠[/yellow] {len(import_errors)} import errors detected")

    # Step 4: Repair if needed
    repairer = Repairer(model=model)
    all_errors = build_result.install_errors + build_result.missing_packages + build_result.version_conflicts + import_errors

    if all_errors and not no_repair:
        repairer.repair(analysis, all_errors, repo_path, max_rounds=max_rounds)

        console.print("\n[bold cyan]📦 Rebuilding after repairs...[/bold cyan]")
        build_result = setup_environment(analysis, repo_path)

        if build_result.success:
            import_errors = check_imports(analysis, build_result, repo_path)
            if import_errors:
                console.print(f"[yellow]⚠[/yellow] {len(import_errors)} import errors remain after repair")

    elif all_errors and no_repair:
        console.print(f"[yellow]⚠ {len(all_errors)} issues found but --no-repair is set. Skipping repair.[/yellow]")

    # Step 5: Verify
    verification = verify(analysis, build_result, repo_path)

    # v0.2: Generate missing config files
    generated = []
    console.print("\n[bold cyan]📝 Generating config files...[/bold cyan]")

    if not analysis.python_version:
        ver = detect_python_version(repo_path)
        if ver:
            with open(repo_path / ".python-version", "w") as f:
                f.write(ver.lstrip(">=") + "\n")
            console.print(f"  [green]✓[/green] Detected Python {ver} → .python-version")
            generated.append("python-version")

    if not analysis.has_dockerfile:
        has_reqs = bool(list(repo_path.glob("requirements*.txt")))
        has_setup = (repo_path / "setup.py").exists()
        generate_dockerfile(repo_path, analysis.python_version or "3.10", has_reqs, has_setup)
        generated.append("Dockerfile")

    readme = generate_readme(repo_path)
    if readme:
        generated.append("README")

    if not analysis.has_ci:
        generate_ci_python(repo_path, analysis.python_version or "3.10", bool(analysis.test_framework))
        generated.append("CI")

    # Summary
    console.print()
    console.print(Panel.fit(
        f"[bold]Resurrection Summary[/bold]\n\n"
        f"  Repository:     [dim]{url}[/dim]\n"
        f"  Language:       [green]{analysis.language}[/green]\n"
        f"  Frameworks:     [yellow]{', '.join(analysis.frameworks) or 'none'}[/yellow]\n"
        f"  Dependencies:   {len(analysis.dependencies)}\n"
        f"  Build:          {'[green]✓[/green]' if build_result.success else '[yellow]⚠[/yellow]'}\n"
        f"  Fixes applied:  [green]{repairer.fixes_applied}[/green]\n"
        f"  Tests passed:   {verification.tests_passed}/{verification.tests_passed + verification.tests_failed}\n"
        f"  Verified:       {'[green]✓[/green]' if verification.passed else '[yellow]⚠[/yellow]'}\n"
        f"  Generated:      [green]{', '.join(generated) if generated else 'none'}[/green]\n"
        f"\n  [dim]Output: {repo_path}[/dim]",
        border_style="green" if build_result.success else "yellow",
    ))


@main.command()
@click.argument("url")
def analyze_cmd(url: str):
    """Analyze a repository without building or repairing."""
    console.print()
    console.print(Panel.fit("[bold cyan]🔍 RepoRevive Analysis[/bold cyan]", border_style="cyan"))

    if url.startswith("http"):
        repo_path = clone_repo(url)
    else:
        repo_path = Path(url).resolve()
        if not repo_path.exists():
            console.print(f"[red]Path not found:[/red] {repo_path}")
            sys.exit(1)

    analysis = analyze(repo_path)

    if analysis.language == "python" and not analysis.dependency_files:
        console.print("\n[bold yellow]No dependency files found. Run 'reporevive generate' to infer them.[/bold yellow]")


@main.command()
@click.argument("path", default=".")
def generate(path: str):
    """Generate missing config files (requirements.txt, Dockerfile, README)."""
    repo_path = Path(path).resolve()
    if not repo_path.exists():
        console.print(f"[red]Path not found:[/red] {repo_path}")
        sys.exit(1)

    console.print()
    console.print(Panel.fit("[bold cyan]📝 RepoRevive — Generate Config[/bold cyan]", border_style="cyan"))
    console.print(f"[dim]Target: {repo_path}[/dim]\n")

    # Check for existing deps
    has_reqs = bool(list(repo_path.glob("requirements*.txt")))
    has_setup = (repo_path / "setup.py").exists()
    has_pyproject = (repo_path / "pyproject.toml").exists()
    has_package_json = (repo_path / "package.json").exists()

    if has_package_json:
        # Node.js project
        node = analyze_node(repo_path)
        generate_node_dockerfile(repo_path, node)
        generate_readme(repo_path)
        generate_ci_node(repo_path, node.node_version or "18", "test" in node.scripts)
        console.print("\n[green]✓ Done[/green]")
        return

    if not has_reqs and not has_setup and not has_pyproject:
        console.print("[bold yellow]No dependency files found — inferring from imports...[/bold yellow]")
        packages = infer_dependencies(repo_path)
        if packages:
            generate_requirements(repo_path, packages)
        else:
            console.print("[dim]No third-party imports found[/dim]")

    # Python version
    ver = detect_python_version(repo_path)
    if ver:
        pv_file = repo_path / ".python-version"
        write_ver = not pv_file.exists()
        if write_ver:
            from reporevive.utils import write_file
            write_file(pv_file, ver.lstrip(">=") + "\n")
        console.print(f"  [green]✓[/green] Detected Python {ver}{' → .python-version' if write_ver else ''}")

    # Dockerfile
    if not (repo_path / "Dockerfile").exists():
        has_reqs_now = bool(list(repo_path.glob("requirements*.txt")))
        has_setup_now = (repo_path / "setup.py").exists()
        generate_dockerfile(repo_path, ver or "3.10", has_reqs_now, has_setup_now)

    # README
    generate_readme(repo_path)

    # CI
    if not (repo_path / ".github" / "workflows").exists():
        generate_ci_python(repo_path, ver or "3.10", True)

    console.print("\n[green]✓ Done[/green]")


if __name__ == "__main__":
    main()


def _revive_node(repo_path: Path, url: str, model: str, max_rounds: int, no_repair: bool):
    """Run the revive pipeline for a Node.js project."""
    node = analyze_node(repo_path)

    if not node.has_package_json:
        console.print("[red]No package.json found — cannot proceed[/red]")
        return

    # Build
    console.print("\n[bold cyan]📦 Installing npm dependencies...[/bold cyan]")
    success, errors = build_node(repo_path)

    # Entry point check
    entry_errors = check_node_entry(repo_path, node)

    # Repair if needed
    repairer = Repairer(model=model)
    all_errors = errors + entry_errors

    if all_errors and not no_repair:
        repairer.repair(RepoAnalysis(), all_errors, repo_path, max_rounds=max_rounds)
        console.print("\n[bold cyan]📦 Rebuilding after repairs...[/bold cyan]")
        success, errors = build_node(repo_path)

    # Generate config files
    generated = []
    console.print("\n[bold cyan]📝 Generating config files...[/bold cyan]")

    if not (repo_path / "Dockerfile").exists():
        generate_node_dockerfile(repo_path, node)
        generated.append("Dockerfile")

    readme = generate_readme(repo_path)
    if readme:
        generated.append("README")

    if not (repo_path / ".github" / "workflows").exists():
        generate_ci_node(repo_path, node.node_version or "18", "test" in node.scripts)
        generated.append("CI")

    # Summary
    console.print()
    console.print(Panel.fit(
        f"[bold]Resurrection Summary[/bold]\n\n"
        f"  Repository:     [dim]{url}[/dim]\n"
        f"  Language:       [green]Node.js[/green]\n"
        f"  Framework:      [yellow]{node.framework or 'none'}[/yellow]\n"
        f"  Dependencies:   {len(node.dependencies)} runtime, {len(node.dev_dependencies)} dev\n"
        f"  Build:          {'[green]✓[/green]' if success else '[yellow]⚠[/yellow]'}\n"
        f"  Fixes applied:  [green]{repairer.fixes_applied}[/green]\n"
        f"  Generated:      [green]{', '.join(generated) if generated else 'none'}[/green]\n"
        f"\n  [dim]Output: {repo_path}[/dim]",
        border_style="green" if success else "yellow",
    ))
