"""Export the FastAPI OpenAPI document without duplicating its schema logic."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
API_SOURCE = REPOSITORY_ROOT / "apps" / "api" / "src"
sys.path.insert(0, str(API_SOURCE))

from zhenfu_api.api import create_app
from zhenfu_api.config import Settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write to this file; stdout when omitted.")
    parser.add_argument("--force", action="store_true", help="Allow replacing an existing export.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    schema = create_app(
        settings=Settings(environment="test", synthetic_repository=True)
    ).openapi()
    rendered = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    if args.output is None:
        sys.stdout.write(rendered)
        return 0

    output = args.output.resolve()
    if output.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite {output}; pass --force after reviewing the version")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
