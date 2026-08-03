import difflib
from datetime import datetime
from pathlib import Path

from reporevive.utils import write_file, console


def generate(repo_path: Path, analysis, build_result, repairer, verification, url: str, before_snap: dict, after_snap: dict) -> Path:
    sections = []

    sections.append(f"# RepoRevive — Resurrection Report\n")
    sections.append(f"**Repository:** {url}")
    sections.append(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    sections.append(f"**Language:** {analysis.language}")
    sections.append(f"**Frameworks:** {', '.join(analysis.frameworks) or 'none'}")
    sections.append(f"**Dependencies:** {len(analysis.dependencies)} packages")
    sections.append(f"**Build:** {'PASSED' if build_result.success else 'FAILED'}")
    sections.append(f"**Fixes applied:** {repairer.fixes_applied}")
    sections.append(f"**Tests:** {verification.tests_passed} passed, {verification.tests_failed} failed")
    sections.append(f"**Verified:** {'YES' if verification.passed else 'NO'}")
    sections.append("")

    if build_result.install_errors:
        sections.append("## Build Errors")
        for e in build_result.install_errors[:30]:
            sections.append(f"- `{e[:150]}`")
        sections.append("")

    if repairer.fixes_applied > 0:
        sections.append("## Changes Applied")
        sections.append("")
        for path in sorted(after_snap):
            if path not in before_snap:
                sections.append(f"### `{path}` (NEW FILE)")
                sections.append("```")
                sections.append(after_snap[path][:2000])
                sections.append("```")
                sections.append("")
            elif before_snap[path] != after_snap[path]:
                sections.append(f"### `{path}` (MODIFIED)")
                diff = difflib.unified_diff(
                    before_snap[path].splitlines(keepends=True),
                    after_snap[path].splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                )
                sections.append("```diff")
                sections.append("".join(list(diff)[:80]))
                sections.append("```")
                sections.append("")

    if verification.errors:
        sections.append("## Remaining Issues")
        for e in verification.errors:
            sections.append(f"- {e}")
        sections.append("")

    sections.append("## Generated Files")
    for name in ["Dockerfile", "README.md", ".github/workflows/ci.yml", ".python-version", "requirements.txt"]:
        f = repo_path / name
        if f.exists():
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%H:%M:%S")
            sections.append(f"- `{name}` (modified {mtime})")
    sections.append("")

    report_path = repo_path / "REVIVE_REPORT.md"
    write_file(report_path, "\n".join(sections))
    console.print(f"  [green]Report: {report_path}[/green]")
    return report_path
