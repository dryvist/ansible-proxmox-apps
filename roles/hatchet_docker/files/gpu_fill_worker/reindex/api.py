"""Router and Qdrant REST calls, with credentials read only from environment."""

import json
import math
import os
from urllib.request import Request, urlopen

from adapter import _check_latency_guard


class APIs:
    def __init__(self, config, latency_guard=None):
        self.config = config
        self.latency_guard = latency_guard
        self.router_key = os.environ["GPU_FILL_ROUTER_API_KEY"]
        self.qdrant_key = os.environ["GPU_FILL_REINDEX_QDRANT_API_KEY"]

    def call(self, service, path, body, method="POST"):
        base = self.config[f"{service}_url"].rstrip("/")
        headers = {"Content-Type": "application/json"}
        if service == "router":
            headers["Authorization"] = f"Bearer {self.router_key}"
        else:
            headers["api-key"] = self.qdrant_key
        request = Request(base + path, data=json.dumps(body).encode(), headers=headers, method=method)
        with urlopen(request, timeout=120) as response:
            result = json.load(response)
        return result

    def embed(self, text):
        if self.latency_guard is not None:
            _check_latency_guard(self.latency_guard, 120)
        result = self.call("router", "/embeddings", {"model": "embed", "input": [text]})
        vector = result["data"][0]["embedding"]
        if not isinstance(vector, list) or not vector or any(
            type(value) not in {int, float} or not math.isfinite(value) for value in vector
        ):
            raise ValueError("router returned an invalid embedding")
        return vector

    def upsert(self, collection, point):
        result = self.call("qdrant", f"/collections/{collection}/points?wait=true",
                           {"points": [point]}, "PUT")
        self.completed(result)

    def delete(self, collection, ids):
        result = self.call("qdrant", f"/collections/{collection}/points/delete?wait=true", {"points": ids})
        self.completed(result)

    @staticmethod
    def completed(result):
        if result.get("status") != "ok" or result.get("result", {}).get("status") != "completed":
            raise ValueError("Qdrant did not confirm a completed operation")

    def smoke(self, collection, query):
        result = self.call("qdrant", f"/collections/{collection}/points/query", {
            "query": self.embed(query), "limit": 5, "with_payload": True,
        })
        texts = [point["payload"]["text"] for point in result["result"]["points"]]
        if not texts:
            raise ValueError("smoke query retrieved no documents")
        ranked = self.call("router", "/rerank", {"model": "rerank", "query": query, "documents": texts})
        if not ranked.get("results"):
            raise ValueError("rerank smoke query returned no results")
        return len(ranked["results"])
