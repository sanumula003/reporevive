"""CLI entry point for Phoenix AI."""

import sys
from pathlib import Path

import click
from rich.panel import Panel

from reporevive import __version__
from reporevive.utils import clone_repo, console
from reporevive.analyzer import analyze
from reporevive.environment import setup_environment, check_imports
from reporevive.repairer import Repairer
from reporevive.verifier import verify


@click.group()
@click.version_option(__version__, prog_name="phoenix")
def main():
    """RepoRevive — Resurrect abandoned GitHub repositories."""
    pass


@main.command()
@click.argument("url")
@click.option("--target", "-t", default=None, help="Target directory for the cloned repo")
@click.option("--model", "-m", default="gpt-4o-mini", help="OpenAI model for code repair")
@click.option("--max-rounds", default=3, help="Maximum repair rounds")
@click.option("--no-repair", is_flag=True, help="Skip LLM repair, just analyze and build")
def revive(url: str, target: str | None, model: str, max_rounds: int, no_repair: bool):
    """Resurrect an abandoned GitHub repository.

    URL: GitHub repository URL or local path.

    Pipeline: Clone → Analyze → Build → Repair → Verify
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

    if analysis.language != "python":
        console.print(f"\n[yellow]⚠ Phoenix currently focuses on Python projects.[/yellow]")
        console.print(f"[dim]Detected language: {analysis.language}[/dim]")
        if not click.confirm("Continue anyway?"):
            return

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

        # Retry build after repair
        console.print("\n[bold cyan]📦 Rebuilding after repairs...[/bold cyan]")
        build_result = setup_environment(analysis, repo_path)

        # Re-check imports
        if build_result.success:
            import_errors = check_imports(analysis, build_result, repo_path)
            if import_errors:
                console.print(f"[yellow]⚠[/yellow] {len(import_errors)} import errors remain after repair")

    elif all_errors and no_repair:
        console.print(f"[yellow]⚠ {len(all_errors)} issues found but --no-repair is set. Skipping repair.[/yellow]")

    # Step 5: Verify
    verification = verify(analysis, build_result, repo_path)

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
        f"\n  [dim]Output: {repo_path}[/dim]",
        border_style="green" if build_result.success else "yellow",
    ))


@main.command()
@click.argument("url")
def analyze_cmd(url: str):
    """Analyze a repository without building or repairing."""
    console.print()
    console.print(Panel.fit("[bold cyan]🔍 Phoenix Analysis[/bold cyan]", border_style="cyan"))

    if url.startswith("http"):
        repo_path = clone_repo(url)
    else:
        repo_path = Path(url).resolve()
        if not repo_path.exists():
            console.print(f"[red]Path not found:[/red] {repo_path}")
            sys.exit(1)

    analyze(repo_path)


if __name__ == "__main__":
    main()
