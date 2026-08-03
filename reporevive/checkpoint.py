import json
from datetime import datetime
from pathlib import Path

from reporevive.utils import write_file, read_file, console

CHECKPOINT_FILE = ".reporevive-checkpoint.json"


def save(repo_path: Path, state: dict) -> None:
    state["_timestamp"] = datetime.now().isoformat()
    state["_repo"] = str(repo_path)
    cp = repo_path / CHECKPOINT_FILE
    write_file(cp, json.dumps(state, indent=2, default=str))
    console.print(f"  [dim]Checkpoint saved (round {state.get('round', 0)}, {state.get('fixes_applied', 0)} fixes)[/dim]")


def load(repo_path: Path) -> dict | None:
    cp = repo_path / CHECKPOINT_FILE
    if not cp.exists():
        return None
    try:
        data = json.loads(read_file(cp))
        console.print(f"[dim]Resuming from checkpoint: round {data.get('round', 0)}, {data.get('fixes_applied', 0)} fixes[/dim]")
        return data
    except Exception:
        console.print("[yellow]Corrupted checkpoint, starting fresh[/yellow]")
        return None


def discard(repo_path: Path) -> None:
    cp = repo_path / CHECKPOINT_FILE
    if cp.exists():
        cp.unlink()
