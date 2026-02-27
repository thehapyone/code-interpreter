"""Generate the FastAPI OpenAPI schema and write it to disk."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.openapi.utils import get_openapi

from mcp_code_interpreter.server import app


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    output.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
