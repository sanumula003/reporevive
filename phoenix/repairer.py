"""LLM-based code repair pipeline.

Takes build errors, analyzes source files, and generates fixes using an LLM.
"""

import os
from pathlib import Path

from openai import OpenAI

from phoenix.utils import read_file, write_file, console
from phoenix.analyzer import RepoAnalysis

SYSTEM_PROMPT = """You are an expert Python software engineer specializing in resurrecting abandoned repositories.
Your job: analyze build/import errors in a Python project and output precise code fixes.

Rules:
1. Return ONLY the fix - no explanations, no markdown, no code fences
2. Each fix must be a complete file rewrite or a targeted edit
3. Use the format: --- FILE: path/to/file.py --- then the complete new file content
4. For dependency issues, output: --- DEP: package_name>=version --- on separate lines
5. Fix only what's broken - don't refactor working code
6. Preserve the original code's style, comments, and structure wherever possible
7. If a package doesn't exist anymore, suggest the replacement package

Common Python migration patterns:
- collections.MutableMapping → collections.abc.MutableMapping
- inspect.getargspec → inspect.getfullargspec
- import imp → import importlib
- unicode → str
- basestring → str
- cPickle → pickle
- ConfigParser → configparser
- urllib2 → urllib.request
- StringIO.StringIO → io.StringIO
- thread → _thread
- Queue → queue
- AnyStr.DEFAULT_TYPE → AnyStr (newer typing)
"""

FIX_PROMPT = """A Python project has the following build/install errors:

Project: {project_path}
Python version target: {python_version}
Detected frameworks: {frameworks}

Errors:
{errors}

Source files in the project:
{source_files}

Relevant source content:
{relevant_sources}

Provide fixes for ALL issues above. Output format:
--- FILE: path/to/file.py ---
(complete fixed file content)

--- DEP: package_name>=version ---
(for dependency additions)"""


class Repairer:
    """LLM-powered code repair engine."""

    def __init__(self, model: str = "gpt-4o-mini"):
        self.model = model
        self.client = None
        self.fixes_applied = 0

    def _get_client(self) -> OpenAI:
        if self.client is None:
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY environment variable not set. "
                    "Set it with: export OPENAI_API_KEY=sk-..."
                )
            self.client = OpenAI(api_key=api_key)
        return self.client

    def repair(self, analysis: RepoAnalysis, errors: list[str], repo_path: Path, max_rounds: int = 3) -> int:
        """Run the repair pipeline. Returns number of fixes applied."""
        if not errors:
            console.print("[green]No errors to repair[/green]")
            return 0

        # Filter to meaningful errors
        significant_errors = [e for e in errors if len(e) > 10 and "warning" not in e.lower()]
        if not significant_errors:
            significant_errors = errors[:20]

        console.print(f"\n[bold yellow]🔧 Starting repair — {len(significant_errors)} errors[/bold yellow]")

        for round_num in range(1, max_rounds + 1):
            console.print(f"\n[dim]Repair round {round_num}/{max_rounds}...[/dim]")

            # Gather source files
            py_files = sorted(repo_path.rglob("*.py"))
            source_map = {}
            relevant_sources = ""

            # Read key files: setup.py, requirements.txt, and main modules
            for f in py_files:
                if f.name in ("setup.py", "setup.cfg", "conftest.py", "__init__.py"):
                    try:
                        content = read_file(f)
                        source_map[str(f.relative_to(repo_path))] = content
                        relevant_sources += f"\n--- {f.relative_to(repo_path)} ---\n{content[:3000]}\n"
                    except Exception:
                        pass

            # Read dependency files
            for f in analysis.dependency_files:
                try:
                    content = read_file(f)
                    relevant_sources += f"\n--- {f.relative_to(repo_path)} ---\n{content[:3000]}\n"
                except Exception:
                    pass

            # Build prompt
            prompt = FIX_PROMPT.format(
                project_path=str(repo_path),
                python_version=analysis.python_version or "3.10+",
                frameworks=", ".join(analysis.frameworks) if analysis.frameworks else "unknown",
                errors="\n".join(significant_errors[:15]),
                source_files="\n".join(f"  {f}" for f in sorted(source_map.keys())[:30]),
                relevant_sources=relevant_sources[:8000],
            )

            try:
                client = self._get_client()
                response = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                    max_tokens=4000,
                )

                reply = response.choices[0].message.content
                if not reply:
                    console.print("[dim]LLM returned empty response[/dim]")
                    break

                applied = self._apply_fixes(reply, repo_path)
                self.fixes_applied += applied

                if applied == 0:
                    console.print("[dim]No fixes applied this round[/dim]")
                    break

            except Exception as e:
                console.print(f"[red]LLM error:[/red] {e}")
                break

        console.print(f"\n[bold]Total fixes applied: [green]{self.fixes_applied}[/green][/bold]")
        return self.fixes_applied

    def _apply_fixes(self, llm_response: str, repo_path: Path) -> int:
        """Parse LLM response and apply file/dependency fixes. Returns count."""
        applied = 0
        current_file = None
        current_content = []
        current_mode = None

        for line in llm_response.splitlines():
            line = line.strip()

            if line.startswith("--- FILE:") and "---" in line[8:]:
                # Save previous file
                if current_file and current_content:
                    self._write_fix(current_file, current_content, repo_path)
                    applied += 1

                # Start new file
                parts = line.split("--- FILE:", 1)[1].strip()
                current_file = parts.split("---")[0].strip()
                current_content = []
                current_mode = "file"

            elif line.startswith("--- DEP:"):
                # Dependency fix
                dep_spec = line.split("--- DEP:", 1)[1].strip()
                if dep_spec:
                    self._add_dependency(dep_spec, repo_path)
                    applied += 1

            elif current_file and current_mode == "file":
                # Don't include trailing --- markers
                if line.startswith("---") and not line.startswith("--- FILE:") and not line.startswith("--- DEP:"):
                    continue
                current_content.append(line)

        # Save last file
        if current_file and current_content:
            self._write_fix(current_file, current_content, repo_path)
            applied += 1

        return applied

    def _write_fix(self, rel_path: str, content_lines: list[str], repo_path: Path) -> None:
        """Write a fixed file."""
        target = repo_path / rel_path

        # Normalize content
        content = "\n".join(content_lines).strip() + "\n"
        if content == "\n":
            return

        # Read original for comparison
        original = ""
        if target.exists():
            original = read_file(target)

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
