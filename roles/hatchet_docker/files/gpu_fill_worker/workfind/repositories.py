"""Clone public default branches and choose recent, substantive tracked files."""

import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit


def _hidden_path(relative):
    return any(part.startswith(".") and part != ".github" for part in Path(relative).parts)


def validate_public_repo_url(url):
    parsed = urlsplit(url) if isinstance(url, str) else None
    if (
        parsed is None
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("repository URL must be a public HTTPS URL without credentials")


def clone_repo(url, destination, run=subprocess.run):
    """Shallow-clone the remote default branch without credentials or shell expansion."""
    validate_public_repo_url(url)
    run(
        ["git", "clone", "--depth", "1000", "--single-branch", "--filter=blob:none", "--", url, str(destination)],
        check=True,
        capture_output=True,
        timeout=180,
    )


def _recency_map(repository):
    """Return each tracked path's newest commit time from the shallow history."""
    result = subprocess.run(
        ["git", "log", "-z", "--format=%ct", "--name-only", "-n", "1000"],
        cwd=repository,
        check=True,
        capture_output=True,
        timeout=30,
    )
    latest = None
    recency = {}
    for raw in result.stdout.split(b"\0"):
        value = raw.strip(b"\r\n")
        if re.fullmatch(rb"[0-9]+", value):
            latest = int(value)
        elif latest is not None and value:
            recency.setdefault(os.fsdecode(value), latest)
    return recency


def _tracked_paths(repository):
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repository,
        check=True,
        capture_output=True,
        timeout=30,
    )
    return [os.fsdecode(path) for path in result.stdout.split(b"\0") if path]


def select_files(repository, count, max_file_bytes):
    """Select text files by latest commit first, then larger file, then stable path."""
    root = Path(repository).resolve()
    recency = _recency_map(root)
    candidates = []
    for relative in _tracked_paths(root):
        path = root / relative
        if path.is_symlink() or _hidden_path(relative):
            continue
        try:
            resolved = path.resolve(strict=True)
            size = resolved.stat().st_size
            if not resolved.is_relative_to(root) or size < 1 or size > max_file_bytes:
                continue
        except OSError:
            continue
        candidates.append((recency.get(relative, 0), size, relative, resolved))
    candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
    selected = []
    for committed_at, size, relative, path in candidates:
        try:
            content = path.read_bytes()
            if b"\0" in content[:8192]:
                continue
            text = content.decode("utf-8")
        except (OSError, UnicodeError):
            continue
        selected.append({"path": relative, "text": text, "size": size, "committed_at": committed_at})
        if len(selected) >= count:
            break
    return selected


def select_context_files(repository, focus_paths, max_file_bytes, total_bytes=262144):
    """Read related docs, code, tests, and CI for cross-file evidence.

    shortcut: context is capped at 256 KiB per file review; raise the budget if
    relevant references routinely fall outside the selected files.
    """
    root = Path(repository).resolve()
    focus_paths = {focus_paths} if isinstance(focus_paths, str) else set(focus_paths)
    recency = _recency_map(root)
    candidates = []
    for relative in _tracked_paths(root):
        path = root / relative
        if path.is_symlink() or _hidden_path(relative):
            continue
        try:
            resolved = path.resolve(strict=True)
            size = resolved.stat().st_size
            if not resolved.is_relative_to(root) or size < 1 or size > max_file_bytes:
                continue
        except OSError:
            continue
        normalized = relative.casefold()
        basename = Path(normalized).name
        priority = 0 if relative in focus_paths else 1
        if basename.startswith("readme") or basename == "agents.md":
            priority = min(priority, 1)
        if normalized.startswith(("docs/", "doc/")):
            priority = min(priority, 2)
        if normalized.startswith(("tests/", "test/", ".github/workflows/")) or "/tests/" in normalized:
            priority = min(priority, 2)
        if basename in {"pyproject.toml", "package.json", "go.mod", "cargo.toml", "ansible.cfg"}:
            priority = min(priority, 2)
        if normalized.startswith(("src/", "lib/", "app/", "roles/", "packages/")):
            priority = min(priority, 3)
        candidates.append((priority, -recency.get(relative, 0), -size, relative, resolved))
    candidates.sort()
    context = {}
    used = 0
    for _priority, _recent, _size, relative, path in candidates:
        try:
            content = path.read_bytes()
            if b"\0" in content[:8192]:
                continue
            text = content.decode("utf-8")
        except (OSError, UnicodeError):
            continue
        cost = len(content)
        if used + cost > total_bytes:
            continue
        context[relative] = text
        used += cost
        if used >= total_bytes:
            break
    return context
