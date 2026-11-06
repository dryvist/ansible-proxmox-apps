"""Idempotent content-hash indexing with a durable checkpoint after confirmed writes."""

import hashlib
import json
import logging
import time
import uuid
from pathlib import Path

from .api import APIs
from .sources import documents

logger = logging.getLogger("gpu_fill.reindex")


def write_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def run(config, *, api=None, source=None, latency_guard=None):
    root = Path(config["output_dir"])
    root.mkdir(parents=True, exist_ok=True)
    checkpoint = root / "checkpoint.json"
    # Endpoint changes must not reuse a checkpoint belonging to another database.
    target = config["qdrant_url"] + "|embed|chunks-6000-v1"
    previous = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
    old = previous.get("points", {}) if previous.get("target") == target else {}
    journal = root / "pending.json"
    pending = json.loads(journal.read_text()) if journal.exists() else {}
    owned = pending.get("points", {}) if pending.get("target") == target else {}
    old.update(owned)
    current, results = {}, {}
    started = time.monotonic()
    report = {"status": "failed", "collections": results}
    try:
        api = api or APIs(config, latency_guard)
        collection_names = {repo["collection"] for repo in config["repos"]}
        if config["hindsight_export"]:
            collection_names.add(config["hindsight_collection"])
        collection_names.update(item["collection"] for item in old.values())
        for name in sorted(collection_names):
            results[name] = {"changed": 0, "unchanged": 0, "deleted": 0, "duration_s": 0.0, "reranked": 0}
        for collection, key, text in (source if source is not None else documents(config)):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, collection + "/" + key))
            if point_id in current:
                raise ValueError("duplicate source identity")
            digest = hashlib.sha256(text.encode()).hexdigest()
            item = {"collection": collection, "hash": digest}
            tick = time.monotonic()
            if old.get(point_id) == item:
                results[collection]["unchanged"] += 1
            else:
                vector = api.embed(text)
                # Record ownership before a write whose outcome may be unknown on failure.
                owned[point_id] = {"collection": collection, "hash": None}
                write_json(journal, {"target": target, "points": owned})
                api.upsert(collection, {"id": point_id, "vector": vector,
                                       "payload": {"source": key, "content_hash": digest, "text": text}})
                results[collection]["changed"] += 1
            current[point_id] = item
            results[collection]["duration_s"] += time.monotonic() - tick
        # Delete only points owned by this checkpoint, after every source has loaded successfully.
        for point_id in old.keys() - current.keys():
            collection = old[point_id]["collection"]
            tick = time.monotonic()
            api.delete(collection, [point_id])
            results[collection]["deleted"] += 1
            results[collection]["duration_s"] += time.monotonic() - tick
        for collection in results:
            if config["smoke_query"] and any(item["collection"] == collection for item in current.values()):
                tick = time.monotonic()
                results[collection]["reranked"] = api.smoke(collection, config["smoke_query"])
                results[collection]["duration_s"] += time.monotonic() - tick
        write_json(checkpoint, {"target": target, "points": current})
        journal.unlink(missing_ok=True)
        report["status"] = "completed"
        return report
    finally:
        report["duration_s"] = time.monotonic() - started
        write_json(root / "results.json", report)
        logger.info("reindex_metrics %s", json.dumps(report, sort_keys=True))
        lines = [f'gpu_fill_reindex_success {int(report["status"] == "completed")}']
        lines.append(f'gpu_fill_reindex_duration_seconds {report["duration_s"]}')
        for collection, counts in sorted(results.items()):
            for key, value in counts.items():
                metric = "duration_seconds" if key == "duration_s" else key
                lines.append(f'gpu_fill_reindex_{metric}{{collection="{collection}"}} {value}')
        temporary = root / "reindex.prom.tmp"
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        temporary.replace(root / "reindex.prom")
