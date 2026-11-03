"""Create missing Langfuse eval datasets and items from the prompts checkout.

The agents/evals YAML files are the source of truth. Each run creates a dataset
that does not exist and an item that does not exist. It never deletes or
overwrites an existing dataset or item.
"""

from pathlib import Path

import yaml

from evals.sync_judges import _request

PAGE_SIZE = 100


def _list_all(request_fn, path: str) -> list[dict]:
    rows: list[dict] = []
    page = 1
    while True:
        separator = "&" if "?" in path else "?"
        data = request_fn("GET", f"{path}{separator}page={page}&limit={PAGE_SIZE}")
        batch = data.get("data", [])
        rows.extend(batch)
        # Read until an empty page, so a server that caps page size is still read in full.
        if not batch:
            return rows
        page += 1


def case_payload(case: dict) -> tuple[dict, dict]:
    """Split one eval case into dataset input and expected output.

    Every key that starts with "expected" is the expected output. The other keys,
    except the case id, are the input.
    """
    expected = {key: value for key, value in case.items() if key.startswith("expected")}
    inputs = {
        key: value
        for key, value in case.items()
        if key != "id" and not key.startswith("expected")
    }
    return inputs, expected


def sync_datasets(evals_dir: Path, request_fn=_request) -> list[str]:
    existing = {
        dataset["name"] for dataset in _list_all(request_fn, "/api/public/v2/datasets")
    }
    report = []
    for path in sorted(evals_dir.glob("*.yaml")):
        definition = yaml.safe_load(path.read_text(encoding="utf-8"))
        agent = definition["agent"]
        if agent not in existing:
            request_fn(
                "POST",
                "/api/public/v2/datasets",
                {
                    "name": agent,
                    "description": f"Eval set from agents/evals/{path.name}",
                },
            )
            existing.add(agent)
            report.append(f"created dataset {agent}")
        present = {
            item["id"]
            for item in _list_all(
                request_fn, f"/api/public/dataset-items?datasetName={agent}"
            )
        }
        created = 0
        for case in definition["cases"]:
            item_id = f"{agent}:{case['id']}"
            if item_id in present:
                continue
            inputs, expected = case_payload(case)
            request_fn(
                "POST",
                "/api/public/dataset-items",
                {
                    "datasetName": agent,
                    "id": item_id,
                    "input": inputs,
                    "expectedOutput": expected,
                },
            )
            created += 1
        report.append(
            f"{agent}: created {created} items, {len(present)} already present"
        )
    return report
