from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.main import app

OUTPUT = Path(__file__).resolve().parents[1] / "openapi" / "data-referee-v1.json"


def rendered_contract() -> str:
    schema = app.openapi()
    schema["paths"] = {
        path: definition
        for path, definition in schema["paths"].items()
        if path.startswith("/v1/") or path.startswith("/health/")
    }
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the committed Data Referee v1 contract.")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = rendered_contract()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit("OpenAPI contract is stale; run scripts/export_openapi.py")
        return
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8")


if __name__ == "__main__":
    main()
