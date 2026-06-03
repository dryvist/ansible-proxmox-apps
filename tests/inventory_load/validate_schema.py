#!/usr/bin/env python3
"""Validate tofu_inventory.json against the JSON Schema contract.

Run from the repo root:
    python3 tests/inventory_load/validate_schema.py

Exit codes:
    0 - validation passed
    1 - validation failed or an error occurred
"""

import json
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).parent.parent.parent
    inventory_path = repo_root / "tests" / "inventory_load" / "tofu_inventory.json"
    schema_path = repo_root / "tests" / "inventory_load" / "tofu_inventory.schema.json"

    # Load files
    try:
        with inventory_path.open() as fh:
            inventory = json.load(fh)
    except FileNotFoundError:
        print(f"ERROR: inventory file not found: {inventory_path}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"ERROR: inventory file is not valid JSON: {exc}", file=sys.stderr)
        return 1

    try:
        with schema_path.open() as fh:
            schema = json.load(fh)
    except FileNotFoundError:
        print(f"ERROR: schema file not found: {schema_path}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"ERROR: schema file is not valid JSON: {exc}", file=sys.stderr)
        return 1

    # Validate
    try:
        import jsonschema  # noqa: PLC0415  # type: ignore[import-untyped]
    except ImportError:
        print("ERROR: 'jsonschema' package is not installed. Run: pip install jsonschema", file=sys.stderr)
        return 1

    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(inventory), key=lambda e: list(e.absolute_path))

    if errors:
        print(f"FAILED: tofu_inventory.json does not conform to schema ({len(errors)} error(s)):")
        for error in errors:
            path = " -> ".join(str(p) for p in error.absolute_path) if error.absolute_path else "(root)"
            print(f"  [{path}] {error.message}")
        return 1

    print("OK: tofu_inventory.json is valid against tofu_inventory.schema.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
