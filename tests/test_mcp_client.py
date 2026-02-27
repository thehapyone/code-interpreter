"""High-level MCP-style smoke tests exercising the published manifest and endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import status

from mcp_code_interpreter import server as server_module

MANIFEST_PATH = Path("openapi.json")


@pytest.mark.asyncio
async def test_manifest_and_basic_flow(api_client):
    """Load the MCP manifest and ensure every declared tool responds as expected."""
    assert MANIFEST_PATH.exists(), "OpenAPI manifest missing"
    manifest = json.loads(MANIFEST_PATH.read_text())

    # sanity check: ensure core endpoints exist
    paths = manifest.get("paths", {})
    for required in ["/exec", "/upload", "/files/{session_id}", "/libraries"]:
        assert required in paths, f"Missing {required} in manifest"

    execute_schema = (
        manifest
        .get("components", {})
        .get("schemas", {})
        .get("ExecuteResponse", {})
    )
    health_schema = (
        manifest
        .get("components", {})
        .get("schemas", {})
        .get("HealthResponse", {})
    )
    assert health_schema, "HealthResponse schema missing from manifest"
    assert "runtime_libraries" in health_schema.get("properties", {})
    assert execute_schema, "ExecuteResponse schema missing from manifest"

    # Run a python execution (MCP clients use /exec)
    payload = {"code": "print('hi from mcp')", "lang": "py", "entity_id": "mcp_test"}
    response = await api_client.post("/exec", json=payload)
    assert response.status_code == status.HTTP_200_OK, response.text
    body = response.json()
    assert body["language"] == "py"
    assert "hi from mcp" in body["run"]["stdout"]
    assert body["stdout"] == body["run"]["stdout"]
    assert body["stderr"] == body["run"]["stderr"]

    # Stream variant should emit session + final done event
    stream_payload = {"code": "import time\nprint('tick')", "lang": "py", "entity_id": "mcp_test"}
    stream_response = await api_client.post("/exec/stream", json=stream_payload)
    assert stream_response.status_code == status.HTTP_200_OK
    text = stream_response.text
    assert "\n\n" in text
    assert "\"type\": " in text

    # Upload a file and list via /files to mimic MCP file tool usage
    files = {"files": ("sample.txt", b"mcp", "text/plain")}
    upload_resp = await api_client.post("/upload", files=files)
    assert upload_resp.status_code == status.HTTP_200_OK
    upload_body = upload_resp.json()
    uploaded_session = upload_body["session_id"]
    list_resp = await api_client.get(f"/files/{uploaded_session}?detail=full")
    assert list_resp.status_code == status.HTTP_200_OK
    listed = list_resp.json()
    assert listed, "Expected uploaded file to appear"
    file_id = listed[0]["id"]

    # Delete file via MCP endpoint to ensure cleanup still works
    delete_resp = await api_client.delete(f"/files/{uploaded_session}/{file_id}")
    assert delete_resp.status_code == status.HTTP_200_OK
    delete_body = delete_resp.json()
    assert delete_body["status"] == "deleted"

    # Verify libraries endpoint presence via FastAPI app helper
    client = server_module.app
    assert client.openapi().get("paths", {}).get("/libraries"), "Libraries endpoint missing in schema"


@pytest.mark.asyncio
async def test_manifest_allows_declared_languages(api_client):
    """Ensure each lang enum in the manifest is accepted by /exec (when runtime available)."""
    manifest = json.loads(MANIFEST_PATH.read_text())
    lang_enum = (
        manifest
        .get("components", {})
        .get("schemas", {})
        .get("RestExecRequest", {})
        .get("properties", {})
        .get("lang", {})
        .get("enum", [])
    )
    assert lang_enum, "Manifest lang enum empty"

    for lang in lang_enum:
        payload = {"code": "print('ok')", "lang": lang, "entity_id": "mcp_test"}
        resp = await api_client.post("/exec", json=payload)
        if resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
            # runtime missing on this host; that's acceptable
            continue
        if resp.status_code == status.HTTP_400_BAD_REQUEST:
            # streaming-only languages are not supported here; skip
            assert "streaming" in resp.text.lower() or "unsupported" in resp.text.lower()
            continue
        assert resp.status_code == status.HTTP_200_OK, f"lang={lang} failed: {resp.text}"
