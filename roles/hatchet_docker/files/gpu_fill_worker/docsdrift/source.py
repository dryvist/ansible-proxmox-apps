"""Read public repository snapshots and pair documentation with implementation."""

import base64
import json
import re
from pathlib import PurePosixPath
from urllib.parse import quote
from urllib.request import Request, urlopen

REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*")


def request_json(url, method="GET", body=None, token=None):
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=json.dumps(body).encode() if body is not None else None,
                      headers=headers, method=method)
    with urlopen(request, timeout=60) as response:
        data = response.read(8_000_001)
        if len(data) > 8_000_000:
            raise ValueError("API response exceeds size limit")
        return json.loads(data)


def public_snapshot(repo, get=request_json):
    if not isinstance(repo, str) or not REPO.fullmatch(repo):
        raise ValueError("repo must be owner/name")
    base = f"https://api.github.com/repos/{repo}"
    metadata = get(base)
    if metadata.get("private") is not False:
        raise ValueError("docsdrift requires a public repository")
    commit = get(base + "/commits/" + quote(metadata["default_branch"], safe=""))["sha"]
    tree = get(base + f"/git/trees/{commit}?recursive=1")
    if tree.get("truncated"):
        raise ValueError("repository tree is truncated")
    files = {}
    for entry in tree["tree"]:
        path = entry["path"]
        if entry.get("mode") not in {"100644", "100755"}:
            continue
        if not (is_doc(path) or is_code(path)):
            continue
        if entry.get("size", 0) > 48_000:
            raise ValueError("repository source exceeds per-file budget")
        blob = get(base + "/git/blobs/" + entry["sha"])
        if blob.get("encoding") != "base64":
            raise ValueError("unsupported blob encoding")
        files[path] = base64.b64decode(blob["content"]).decode("utf-8")
    return commit, files


def is_doc(path):
    p = PurePosixPath(path)
    return p.suffix.lower() in {".md", ".mdx", ".rst"} and (
        p.name.lower().startswith("readme") or "docs" in p.parts)


def is_code(path):
    p = PurePosixPath(path)
    return (path.startswith("roles/") and "/defaults/" in path
            and p.suffix in {".yml", ".yaml"}) or (
        path.startswith(".github/workflows/") and p.suffix in {".yml", ".yaml"}
    ) or p.name == "flake.nix"


def pairs(files):
    """Role READMEs stay with their defaults; general guides cover all supported code."""
    for doc in sorted(p for p in files if is_doc(p)):
        parts = PurePosixPath(doc).parts
        role_prefix = "/".join(parts[:2]) + "/" if parts[0] == "roles" else None
        for code in sorted(p for p in files if is_code(p)):
            if role_prefix and not code.startswith(role_prefix):
                continue
            # General guides can describe any workflow or flake output without naming a path.
            yield doc, code
