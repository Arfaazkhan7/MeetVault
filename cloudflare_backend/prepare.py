"""Stage only backend source for pywrangler, excluding server-only requirements.

Run this before each local build/deploy. Generated source is never committed.
No environment files, uploads, database files, or credentials are copied.
"""
from pathlib import Path
import shutil


def prepare() -> None:
    project = Path(__file__).resolve().parent
    backend = project.parent / "backend"
    destination = project / "src"
    destination.mkdir(exist_ok=True)
    shutil.copytree(
        backend / "app", destination / "app", dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copy2(backend / "worker.py", destination / "worker.py")


if __name__ == "__main__":
    prepare()
