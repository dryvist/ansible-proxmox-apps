"""Read public shallow checkouts and a configured Hindsight JSON export."""

import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from fill.corpus import chunk_text

TEXT_SUFFIXES = {".md", ".mdx", ".rst", ".txt", ".py", ".js", ".ts", ".yml", ".yaml", ".json"}


def documents(config, clone=None):
    """Yield (collection, stable source key, text); clones never use ambient credentials."""
    for repo in config["repos"]:
        with TemporaryDirectory(prefix="reindex-") as directory:
            if clone is None:
                env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
                env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null")
                subprocess.run(
                    ["git", "-c", "credential.helper=", "clone", "--depth", "1", "--",
                     repo["url"], directory],
                    env=env, check=True, capture_output=True, timeout=300,
                )
            else:
                clone(repo["url"], directory)
            root = Path(directory)
            for path in sorted(root.rglob("*")):
                relative = path.relative_to(root)
                if (not path.is_file() or path.is_symlink()
                        or any(part.startswith(".") for part in relative.parts)
                        or path.suffix.lower() not in TEXT_SUFFIXES):
                    continue
                # Bound individual files; binary source assets are not embedding inputs.
                if path.stat().st_size > 1_000_000:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                for index, body in enumerate(chunk_text(text)):
                    yield repo["collection"], f'{repo["url"]}/{relative}#{index}', body
    if config["hindsight_export"]:
        records = json.loads(Path(config["hindsight_export"]).read_text(encoding="utf-8"))
        seen = set()
        for record in records:
            identifier, text = record["id"], record["text"]
            if not isinstance(identifier, str) or not identifier or identifier in seen:
                raise ValueError("Hindsight export requires unique nonempty string ids")
            if not isinstance(text, str):
                raise ValueError("Hindsight export text must be a string")
            seen.add(identifier)
            for index, body in enumerate(chunk_text(text)):
                yield config["hindsight_collection"], f"hindsight/{identifier}#{index}", body
