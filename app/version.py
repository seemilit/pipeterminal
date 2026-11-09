"""Resolve the application version from its build resource or Git history."""

import re
import subprocess
from pathlib import Path


VERSION_RESOURCE = "app_version.txt"
_VERSION_TAG = re.compile(r"tag: refs/tags/v([0-9]+)\.([0-9]+)\.([0-9]+)")


def _git_output(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True,
        encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).stdout


def version_from_git(root: Path) -> str:
    if not (root / ".git").exists():
        raise ValueError("A Git checkout of PipeTerminal is required to derive its version.")
    history = _git_output(
        root, "log", "--first-parent", "--no-color", "--no-show-signature", "--no-notes",
        "--decorate=full", "--decorate-refs=refs/tags/v*", "--format=%H%x09%D", "HEAD",
    ).splitlines()
    for distance, entry in enumerate(history):
        decorations = entry.partition("\t")[2].split(", ")
        versions = [
            tuple(map(int, match.groups()))
            for decoration in decorations if (match := _VERSION_TAG.fullmatch(decoration))
        ]
        if versions:
            major, minor, patch = max(versions)
            return f"{major}.{minor}.{patch + distance}"
    if _git_output(root, "rev-parse", "--is-shallow-repository").strip() == "true":
        raise ValueError("Fetch the complete Git history before deriving a version without a version tag.")
    return f"0.0.{len(history)}"


def application_version(root: Path, *, frozen: bool) -> str:
    try:
        if frozen:
            return (root / "resources" / VERSION_RESOURCE).read_text(encoding="ascii").strip()
        return version_from_git(root)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return ""
