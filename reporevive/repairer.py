"""LLM-based code repair pipeline powered by opencode CLI."""

import json
import subprocess
from pathlib import Path

from reporevive.utils import read_file, write_file, console
from reporevive.analyzer import RepoAnalysis

REPAIR_INSTRUCTIONS = """You are an expert Python software engineer. Your job: analyze build/install errors in a Python project and output precise code fixes.

RULES (follow strictly):
1. Output ONLY file patches and dependency changes — no explanations, no markdown, no chat
2. Format for file fixes:
   ```python
   # FIX: path/to/file.py
   (complete new file content)
   ```
3. Format for dependency additions (new packages needed):
   # DEP: package_name>=version
4. Fix ONLY what's broken — don't refactor working code
5. Preserve the original code's style and structure wherever possible
6. If a package doesn't exist anymore, suggest the replacement

Common Python migration issues to check:
- collections.MutableMapping → collections.abc.MutableMapping (Python 3.10+)
- imports from collections.abc for all ABCs (Iterable, Mapping, Sequence, etc.)
- urlparse → urllib.parse.urlparse (Python 3)
- ConfigParser → configparser
- StringIO.StringIO → io.StringIO
- cPickle → pickle
- basestring → str
- unicode → str
- Queue → queue (Python 3)
- inspect.getargspec → inspect.getfullargspec
- AnyStr.DEFAULT_TYPE → AnyStr (newer typing)
"""


class Repairer:
    """Code repair engine powered by opencode CLI."""

    def __init__(self, model: str = ""):
        self.fixes_applied = 0
        self.model = model

    def repair(self, analysis: RepoAnalysis, errors: list[str], repo_path: Path, max_rounds: int = 3) -> int:
        """Run the repair pipeline. Returns number of fixes applied."""
        if not errors:
            console.print("[green]No errors to repair[/green]")
            return 0

        significant = [e for e in errors if len(e) > 10 and "warning" not in e.lower()]
        if not significant:
            significant = errors[:20]

        console.print(f"\n[bold yellow]🔧 Starting repair — {len(significant)} errors[/bold yellow]")

        for round_num in range(1, max_rounds + 1):
            console.print(f"\n[dim]Repair round {round_num}/{max_rounds}...[/dim]")

            # Gather source context
            context = self._gather_context(analysis, repo_path, significant[:20])

            prompt = f"""{REPAIR_INSTRUCTIONS}

The project at {repo_path} has the following build/install errors:

Python version target: {analysis.python_version or '3.10+'}
Detected frameworks: {', '.join(analysis.frameworks) if analysis.frameworks else 'unknown'}

Errors:
{chr(10).join(significant[:15])}

Current project files and their contents:
{context}

Provide fixes for ALL issues above using the exact formats specified."""

            try:
                result = subprocess.run(
                    ["opencode", "run", prompt, "--dir", str(repo_path), "--auto", "--format", "json"],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                reply = self._parse_opencode_output(result.stdout)
                if not reply:
                    console.print("[dim]Opencode returned no content[/dim]")
                    break

                applied = self._apply_fixes(reply, repo_path)
                self.fixes_applied += applied

                if applied == 0:
                    console.print("[dim]No fixes applied this round[/dim]")
                    break

            except subprocess.TimeoutExpired:
                console.print("[red]Opencode timed out[/red]")
                break
            except Exception as e:
                console.print(f"[red]Repair error:[/red] {e}")
                break

        console.print(f"\n[bold]Total fixes applied: [green]{self.fixes_applied}[/green][/bold]")
        return self.fixes_applied

    def _gather_context(self, analysis: RepoAnalysis, repo_path: Path, errors: list[str]) -> str:
        """Gather relevant source files for context (trimmed for speed)."""
        parts = []
        total_chars = 0
        max_chars = 6000

        # 1. Add dependency files (most important)
        for f in analysis.dependency_files:
            try:
                content = read_file(f)
                snippet = content[:2500]
                parts.append(f"=== {f.relative_to(repo_path)} ===\n{snippet}")
                total_chars += len(snippet)
            except Exception:
                pass

        # 2. Add setup.py/pyproject.toml if not already included
        for f in ["setup.py", "pyproject.toml", "setup.cfg"]:
            fp = repo_path / f
            if fp.exists() and fp not in analysis.dependency_files:
                try:
                    content = read_file(fp)
                    snippet = content[:2000]
                    parts.append(f"=== {f} ===\n{snippet}")
                    total_chars += len(snippet)
                except Exception:
                    pass

        # 3. Add top-level Python files (not venvs, not tests)
        py_files = sorted(repo_path.glob("*.py"))[:5]
        py_files += [p for p in sorted(repo_path.rglob("*.py"))
                     if p.parent != repo_path
                     and ".venv" not in str(p)
                     and "__pycache__" not in str(p)
                     and ".phoenix-venv" not in str(p)
                     and "test" not in str(p).lower()][:8]

        for f in py_files:
            if total_chars > max_chars:
                break
            try:
                content = read_file(f)
                if content.strip():
                    snippet = content[:1500]
                    parts.append(f"=== {f.relative_to(repo_path)} ===\n{snippet}")
                    total_chars += len(snippet)
            except Exception:
                pass

        # 4. Add errors
        parts.append("=== BUILD ERRORS ===\n" + "\n".join(errors[:10]))

        return "\n\n".join(parts)

    def _parse_opencode_output(self, stdout: str) -> str:
        """Extract the text content from opencode JSON output."""
        if not stdout.strip():
            return ""

        texts = []
        for line in stdout.strip().split("\n"):
            try:
                data = json.loads(line)
                if data.get("type") == "text":
                    part = data.get("part", {})
                    text = part.get("text", "")
                    if text:
                        texts.append(text)
            except json.JSONDecodeError:
                continue

        return "\n".join(texts)

    def _apply_fixes(self, response: str, repo_path: Path) -> int:
        """Parse LLM response and apply file/dependency fixes. Returns count."""
        applied = 0
        current_file = None
        current_content = []
        in_code_block = False

        for line in response.splitlines():
            stripped = line.strip()

            # Detect code blocks with file markers
            if stripped.startswith("```") and "# FIX:" in stripped:
                # End any previous block
                if current_file and current_content:
                    self._write_fix(current_file, current_content, repo_path)
                    applied += 1
                # Start new block
                current_file = stripped.split("# FIX:", 1)[1].strip().split("```")[0].strip()
                current_content = []
                in_code_block = True
                continue

            if stripped == "```" and in_code_block:
                in_code_block = False
                if current_file and current_content:
                    self._write_fix(current_file, current_content, repo_path)
                    applied += 1
                current_file = None
                continue

            # Dependency additions
            if stripped.startswith("# DEP:") or stripped.startswith("DEP:"):
                dep = stripped.split("DEP:", 1)[1].strip()
                if dep:
                    self._add_dependency(dep, repo_path)
                    applied += 1

            if in_code_block and current_file:
                current_content.append(line)

        # Save last file
        if current_file and current_content:
            self._write_fix(current_file, current_content, repo_path)
            applied += 1

        return applied

    def _write_fix(self, rel_path: str, content_lines: list[str], repo_path: Path) -> None:
        """Write a fixed file."""
        target = repo_path / rel_path
        content = "\n".join(content_lines).strip() + "\n"

        if content == "\n" or content == "`\n":
            return

        original = read_file(target) if target.exists() else ""
        if original == content:
            return

        write_file(target, content)
        console.print(f"  [green]✓[/green] Fixed: {rel_path}")

    def _add_dependency(self, dep_spec: str, repo_path: Path) -> None:
        """Add a dependency to requirements.txt."""
        req_file = repo_path / "requirements.txt"
        if req_file.exists():
            content = read_file(req_file)
            if dep_spec not in content:
                content = content.rstrip() + "\n" + dep_spec + "\n"
                write_file(req_file, content)
                console.print(f"  [green]✓[/green] Added dep: {dep_spec}")
        else:
            write_file(req_file, dep_spec + "\n")
            console.print(f"  [green]✓[/green] Created requirements.txt with: {dep_spec}")
