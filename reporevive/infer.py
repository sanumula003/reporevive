"""Infer dependencies, versions, and generate config files for broken repos."""

import ast
import sys
import re
from pathlib import Path

from reporevive.utils import read_file, write_file, console, find_files

# Standard library modules (Python 3.10+)
_STDLIB = {
    "abc", "aifc", "argparse", "array", "ast", "asynchat", "asyncio", "asyncore",
    "atexit", "audioop", "base64", "bdb", "binascii", "binhex", "bisect",
    "builtins", "bz2", "calendar", "cgi", "cgitb", "chunk", "cmath", "cmd",
    "code", "codecs", "codeop", "collections", "colorsys", "compileall",
    "concurrent", "configparser", "contextlib", "contextvars", "copy",
    "copyreg", "cProfile", "crypt", "csv", "ctypes", "curses", "dataclasses",
    "datetime", "dbm", "decimal", "difflib", "dis", "distutils", "doctest",
    "email", "encodings", "enum", "errno", "faulthandler", "fcntl",
    "filecmp", "fileinput", "fnmatch", "fractions", "ftplib", "functools",
    "gc", "getopt", "getpass", "gettext", "glob", "graphlib", "grp", "gzip",
    "hashlib", "heapq", "hmac", "html", "http", "idlelib", "imaplib",
    "imghdr", "imp", "importlib", "inspect", "io", "ipaddress", "itertools",
    "json", "keyword", "lib2to3", "linecache", "locale", "logging", "lzma",
    "mailbox", "mailcap", "marshal", "math", "mimetypes", "mmap",
    "modulefinder", "multiprocessing", "netrc", "nis", "nntplib", "numbers",
    "operator", "optparse", "os", "ossaudiodev", "pathlib", "pdb", "pickle",
    "pickletools", "pipes", "pkgutil", "platform", "plistlib", "poplib",
    "posix", "posixpath", "pprint", "profile", "pstats", "pty", "pwd",
    "py_compile", "pyclbr", "pydoc", "queue", "quopri", "random", "re",
    "readline", "reprlib", "resource", "rlcompleter", "runpy", "sched",
    "secrets", "select", "selectors", "shelve", "shlex", "shutil", "signal",
    "site", "smtpd", "smtplib", "sndhdr", "socket", "socketserver", "sqlite3",
    "ssl", "stat", "statistics", "string", "stringprep", "struct",
    "subprocess", "sunau", "symtable", "sys", "sysconfig", "syslog",
    "tabnanny", "tarfile", "telnetlib", "tempfile", "termios", "test",
    "textwrap", "threading", "time", "timeit", "tkinter", "token",
    "tokenize", "trace", "traceback", "tracemalloc", "tty", "turtle",
    "turtledemo", "types", "typing", "unicodedata", "unittest", "urllib",
    "uu", "uuid", "venv", "warnings", "wave", "weakref", "webbrowser",
    "winreg", "winsound", "wsgiref", "xdrlib", "xml", "xmlrpc",
    "zipapp", "zipfile", "zipimport", "zlib", "_thread",
}

# Known import-to-package mappings (import name ≠ pip package name)
_IMPORT_MAP = {
    "PIL": "pillow",
    "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4",
    "yaml": "pyyaml",
    "cv2": "opencv-python",
    "Crypto": "pycryptodome",
    "MySQLdb": "mysqlclient",
    "psycopg2": "psycopg2-binary",
    "dotenv": "python-dotenv",
    "dateutil": "python-dateutil",
    "pkg_resources": "setuptools",
    "google.protobuf": "protobuf",
    "scipy": "scipy",
    "matplotlib": "matplotlib",
    "pandas": "pandas",
    "numpy": "numpy",
    "tensorflow": "tensorflow",
    "torch": "torch",
    "transformers": "transformers",
    "flask": "flask",
    "django": "django",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "aiohttp": "aiohttp",
    "requests": "requests",
    "click": "click",
    "rich": "rich",
    "pydantic": "pydantic",
    "sqlalchemy": "sqlalchemy",
    "celery": "celery",
    "redis": "redis",
    "pymongo": "pymongo",
    "psutil": "psutil",
    "tqdm": "tqdm",
    "jinja2": "jinja2",
    "gradio": "gradio",
    "streamlit": "streamlit",
    "openai": "openai",
    "langchain": "langchain",
    "huggingface_hub": "huggingface-hub",
    "datasets": "datasets",
    "diffusers": "diffusers",
    "accelerate": "accelerate",
    "wandb": "wandb",
}


def infer_dependencies(repo_path: Path) -> list[str]:
    """Scan all .py files for import statements and infer required packages."""
    py_files = [p for p in repo_path.rglob("*.py")
                if ".venv" not in str(p) and "__pycache__" not in str(p)
                and ".phoenix-venv" not in str(p)]

    imports = set()
    for f in py_files:
        try:
            content = read_file(f)
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module.split(".")[0])
        except (SyntaxError, Exception):
            # Fallback: regex-based import detection for files with syntax errors
            try:
                content = read_file(f)
                for match in re.finditer(r'(?:from|import)\s+(\w+)', content):
                    imports.add(match.group(1))
            except Exception:
                pass

    # Filter: remove stdlib, map to pip names
    packages = set()
    for imp in imports:
        if imp in _STDLIB:
            continue
        if imp.startswith("_"):
            continue
        # Check if it's a local module
        if (repo_path / f"{imp}.py").exists() or (repo_path / imp / "__init__.py").exists():
            continue
        packages.add(_IMPORT_MAP.get(imp, imp.lower()))

    return sorted(packages)


def generate_requirements(repo_path: Path, packages: list[str]) -> Path:
    """Generate requirements.txt from inferred packages."""
    req_file = repo_path / "requirements.txt"
    content = "\n".join(packages) + "\n"
    write_file(req_file, content)
    console.print(f"  [green]✓[/green] Inferred {len(packages)} packages → requirements.txt")
    return req_file


def detect_python_version(repo_path: Path) -> str | None:
    """Detect minimum Python version from code syntax."""
    features = {"3.6": False, "3.8": False, "3.10": False, "3.12": False}

    for f in repo_path.rglob("*.py"):
        if ".venv" in str(f) or "__pycache__" in str(f):
            continue
        try:
            content = read_file(f)
            # f-strings → 3.6+
            if 'f"' in content or "f'" in content:
                features["3.6"] = True
            # walrus operator := → 3.8+
            if ":=" in content and "if " in content and " = " not in content.split(":=")[0]:
                features["3.8"] = True
            # match/case → 3.10+
            if re.search(r'\bmatch\s+\w+\s*:', content) and 'case ' in content:
                features["3.10"] = True
            # Type parameter syntax → 3.12+
            if re.search(r'class\s+\w+\[', content):
                features["3.12"] = True
        except Exception:
            pass

    for ver in ["3.12", "3.10", "3.8", "3.6"]:
        if features[ver]:
            return f">={ver}"
    return ">=3.6"


def generate_dockerfile(repo_path: Path, python_version: str, has_reqs: bool, has_setup: bool) -> Path:
    """Generate a Dockerfile for the project."""
    df = repo_path / "Dockerfile"

    install_cmd = []
    if has_reqs:
        install_cmd.append("COPY requirements.txt .")
        install_cmd.append("RUN pip install --no-cache-dir -r requirements.txt")
    if has_setup:
        install_cmd.append("COPY setup.py .")
        install_cmd.append("COPY . .")
        install_cmd.append("RUN pip install --no-cache-dir -e .")
    if not install_cmd:
        install_cmd.append("COPY . .")

    # Find entry point
    entry = ""
    for name in ["app.py", "main.py", "run.py", "cli.py"]:
        if (repo_path / name).exists():
            entry = name
            break

    content = f"""FROM python:{python_version.lstrip(">=")}-slim

WORKDIR /app

{"".join(chr(10) + line for line in install_cmd)}

{("CMD [\"python\", \"" + entry + "\"]") if entry else "# Add your CMD here"}
"""

    write_file(df, content.strip() + "\n")
    console.print(f"  [green]✓[/green] Generated Dockerfile (Python {python_version})")
    return df


def generate_readme(repo_path: Path) -> Path | None:
    """Generate a basic README if none exists."""
    existing = list(repo_path.glob("README*"))
    if existing:
        return None

    name = repo_path.name
    py_count = len(list(repo_path.rglob("*.py")))
    modules = []
    for d in repo_path.iterdir():
        if d.is_dir() and (d / "__init__.py").exists() and d.name[0] != ".":
            modules.append(d.name)

    content = f"""# {name}

> Auto-resurrected by [reporevive](https://github.com/sanumula003/reporevive)

{py_count} Python files{" in " + ", ".join(modules) if modules else ""}

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```python
# Add usage examples here
```
"""

    write_file(repo_path / "README.md", content)
    console.print(f"  [green]✓[/green] Generated README.md")
    return repo_path / "README.md"
