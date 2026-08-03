"""Analyze a repository: detect language, dependencies, framework, and structure."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from reporevive.utils import find_files, read_file, console

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # Python < 3.11


@dataclass
class RepoAnalysis:
    """Structured analysis of a repository."""
    language: str = "unknown"
    python_version: Optional[str] = None
    dependency_files: list[Path] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    test_framework: Optional[str] = None
    has_dockerfile: bool = False
    has_readme: bool = False
    has_ci: bool = False
    importable_modules: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def analyze(root: Path) -> RepoAnalysis:
    """Analyze a repository and return structured findings."""
    analysis = RepoAnalysis()

    # Detect language
    analysis.language = _detect_language(root)
    if analysis.language != "python":
        analysis.issues.append(f"Language '{analysis.language}' is not yet fully supported; Python is primary target")
        return analysis

    # Find dependency files
    dep_patterns = ["requirements*.txt", "setup.py", "setup.cfg", "pyproject.toml", "Pipfile"]
    analysis.dependency_files = find_files(root, dep_patterns)

    # Has README / Dockerfile / CI?
    analysis.has_readme = (root / "README.md").exists() or (root / "README.rst").exists()
    analysis.has_dockerfile = (root / "Dockerfile").exists()
    analysis.has_ci = bool(list(root.glob(".github/workflows/*.yml")))

    # Parse dependencies
    analysis.dependencies = _parse_dependencies(root, analysis.dependency_files)
    analysis.python_version = _detect_python_version(root, analysis.dependency_files)
    analysis.frameworks = _detect_frameworks(analysis.dependencies)
    analysis.test_framework = _detect_test_framework(analysis.dependencies)
    analysis.importable_modules = _find_modules(root)

    # Check for issues
    if not analysis.dependency_files:
        analysis.issues.append("No dependency files found — dependencies must be inferred from imports")

    if not analysis.python_version:
        analysis.issues.append("No Python version constraint found")

    _log_analysis(analysis)
    return analysis


def _detect_language(root: Path) -> str:
    """Detect primary programming language."""
    py_count = len(list(root.rglob("*.py")))
    js_count = len(list(root.rglob("*.js")))
    ts_count = len(list(root.rglob("*.ts")))
    rs_count = len(list(root.rglob("*.rs")))
    java_count = len(list(root.rglob("*.java")))

    counts = {"python": py_count, "javascript": js_count + ts_count, "rust": rs_count, "java": java_count}
    return max(counts, key=counts.get)


def _parse_dependencies(root: Path, dep_files: list[Path]) -> list[str]:
    """Extract dependency names from all dependency files."""
    deps = set()
    _clean = lambda p: p.split(">=")[0].split("==")[0].split("<=")[0].split("~=")[0].split("!=")[0].split("[")[0].strip().lower()

    for f in dep_files:
        content = read_file(f)
        name = f.name.lower()

        if name == "requirements.txt" or name.startswith("requirements"):
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("-"):
                    pkg = _clean(line)
                    if pkg and not pkg.startswith("git+") and not pkg.startswith("http"):
                        deps.add(pkg)
        elif name == "pyproject.toml":
            try:
                data = tomllib.loads(content)
                proj = data.get("project", {})
                for dep in proj.get("dependencies", []):
                    deps.add(_clean(dep))
                for opt in proj.get("optional-dependencies", {}).values():
                    for dep in opt:
                        deps.add(_clean(dep))
            except Exception:
                pass
        elif name == "setup.cfg":
            in_requires = False
            for line in content.splitlines():
                stripped = line.strip()
                if "install_requires" in stripped:
                    in_requires = True
                    continue
                if in_requires:
                    if stripped and not stripped.startswith("#") and not stripped.startswith("["):
                        deps.add(_clean(stripped))
                    if stripped.startswith("[") or not stripped:
                        in_requires = False
        elif name == "setup.py":
            # First pass: extract variable-based dependency lists
            var_deps = {}
            for line in content.splitlines():
                stripped = line.strip()
                # Match: VARNAME = ['pkg1', 'pkg2']
                for quote in ('"', "'"):
                    if '=' in stripped and '[' in stripped and ']' in stripped:
                        parts = stripped.split('=', 1)
                        if len(parts) == 2:
                            varname = parts[0].strip()
                            rest = parts[1].strip()
                            if rest.startswith('[%s' % quote):
                                for pkg in rest.split(quote)[1::2]:
                                    var_deps.setdefault(varname, []).append(pkg)
                # Match: VARNAME += ['pkg'] (list extension)
                if '+=' in stripped and '[' in stripped:
                    for quote in ('"', "'"):
                        parts = stripped.split('+=', 1)
                        if len(parts) == 2:
                            varname = parts[0].strip()
                            rest = parts[1].strip()
                            if rest.startswith('[%s' % quote):
                                for pkg in rest.split(quote)[1::2]:
                                    var_deps.setdefault(varname, []).append(pkg)
            # Second pass: find install_requires references
            in_requires = False
            for line in content.splitlines():
                stripped = line.strip()
                if "install_requires" in stripped:
                    in_requires = True
                    # Try direct list
                    for quote in ('"', "'"):
                        pkgs = stripped.split(quote)[1::2]
                        for pkg in pkgs:
                            cleaned = _clean(pkg)
                            if cleaned and cleaned.isidentifier():
                                # Could be a variable reference
                                if cleaned in var_deps:
                                    for vp in var_deps[cleaned]:
                                        deps.add(_clean(vp))
                        # Direct package names
                        for p in pkgs:
                            deps.add(_clean(p))
                    if "]" in stripped and not stripped.endswith(","):
                        in_requires = False
                    continue
                if in_requires:
                    for quote in ('"', "'"):
                        for pkg in stripped.split(quote)[1::2]:
                            deps.add(_clean(pkg))
                    if "]" in stripped:
                        in_requires = False

    return sorted(deps)


def _detect_python_version(root: Path, dep_files: list[Path]) -> Optional[str]:
    """Detect Python version constraint."""
    # Check .python-version (pyenv)
    pv_file = root / ".python-version"
    if pv_file.exists():
        return pv_file.read_text().strip()

    # Check pyproject.toml
    for f in dep_files:
        if f.name == "pyproject.toml":
            try:
                data = tomllib.loads(read_file(f))
                return data.get("project", {}).get("requires-python")
            except Exception:
                pass

    # Check setup.cfg
    for f in dep_files:
        if f.name == "setup.cfg":
            for line in read_file(f).splitlines():
                if line.strip().startswith("python_requires"):
                    return line.split("=", 1)[1].strip()

    # Check runtime.txt (common in some deploy setups)
    rt = root / "runtime.txt"
    if rt.exists():
        content = rt.read_text().strip()
        if "python-" in content:
            return content.replace("python-", "")

    return None


_FRAMEWORK_MAP = {
    "django": "Django",
    "flask": "Flask",
    "fastapi": "FastAPI",
    "tensorflow": "TensorFlow",
    "torch": "PyTorch",
    "transformers": "HuggingFace Transformers",
    "gradio": "Gradio",
    "streamlit": "Streamlit",
    "aiohttp": "aiohttp",
    "sqlalchemy": "SQLAlchemy",
    "celery": "Celery",
    "jax": "JAX",
}


def _detect_frameworks(deps: list[str]) -> list[str]:
    """Detect frameworks from dependency list."""
    frameworks = []
    for dep in deps:
        for key, name in _FRAMEWORK_MAP.items():
            if key in dep:
                frameworks.append(name)
    return sorted(set(frameworks))


_TEST_FRAMEWORKS = ["pytest", "unittest", "nose", "tox", "coverage"]


def _detect_test_framework(deps: list[str]) -> Optional[str]:
    """Detect test framework."""
    for dep in deps:
        for tf in _TEST_FRAMEWORKS:
            if tf in dep:
                return tf
    return None


def _find_modules(root: Path) -> list[str]:
    """Find Python modules/packages (directories with __init__.py or standalone .py files)."""
    modules = []
    for item in root.rglob("*.py"):
        if item.name.startswith("_") or item.name == "setup.py":
            continue
        rel = item.relative_to(root)
        parts = list(rel.parts)
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
        if parts:
            module = ".".join(parts).replace(".py", "")
            if module and not module.startswith("."):
                modules.append(module)
    return sorted(set(modules))


def _log_analysis(analysis: RepoAnalysis) -> None:
    """Pretty-print analysis results."""
    console.print()
    console.print("[bold cyan]📊 Repository Analysis[/bold cyan]")
    console.print(f"  Language:        [green]{analysis.language}[/green]")
    if analysis.python_version:
        console.print(f"  Python requires: [green]{analysis.python_version}[/green]")
    if analysis.frameworks:
        console.print(f"  Frameworks:      [yellow]{', '.join(analysis.frameworks)}[/yellow]")
    if analysis.dependencies:
        console.print(f"  Dependencies:    [dim]{len(analysis.dependencies)} packages[/dim]")
    if analysis.test_framework:
        console.print(f"  Tests:           [green]{analysis.test_framework}[/green]")
    console.print(f"  Dockerfile:      {'[green]yes' if analysis.has_dockerfile else '[dim]no[/dim]'}")
    console.print(f"  CI/CD:           {'[green]yes' if analysis.has_ci else '[dim]no[/dim]'}")
    if analysis.issues:
        for issue in analysis.issues:
            console.print(f"  [yellow]⚠[/yellow]  {issue}")
