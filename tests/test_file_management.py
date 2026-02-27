"""Tests for REST file management endpoints."""

from typing import Any

import pytest


async def _upload_file(api_client, filename: str, content: bytes, entity_id: str | None = None):
    files: dict[str, tuple[str, bytes, str]] = {"files": (filename, content, "text/plain")}
    request_kwargs: dict[str, Any] = {"files": files}
    if entity_id:
        request_kwargs["data"] = {"entity_id": entity_id}

    response = await api_client.post("/upload", **request_kwargs)
    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "success"
    file_info = payload["files"][0]
    return payload["session_id"], file_info["id"], file_info


@pytest.mark.asyncio
async def test_upload_succeeds_with_request_logging_enabled(api_client):
    from mcp_code_interpreter import server as server_module

    previous = server_module.LOG_REQUESTS
    server_module.LOG_REQUESTS = True
    try:
        files: dict[str, tuple[str, bytes, str]] = {"files": ("logged.txt", b"hello", "text/plain")}
        response = await api_client.post("/upload", files=files)
        assert response.status_code == 200
    finally:
        server_module.LOG_REQUESTS = previous


@pytest.mark.asyncio
async def test_upload_accepts_singular_file_field(api_client):
    files: dict[str, tuple[str, bytes, str]] = {"file": ("single.txt", b"one file", "text/plain")}
    response = await api_client.post("/upload", files=files)

    assert response.status_code == 200
    payload = response.json()
    assert payload["files"][0]["name"] == "single.txt"


@pytest.mark.asyncio
async def test_uploaded_file_available_under_mnt_data(api_client):
    session_id, file_id, file_info = await _upload_file(
        api_client, "data.csv", b"a,b\n1,2\n", entity_id="mnt_data_upload"
    )
    assert file_info["id"] == file_id

    code = "from pathlib import Path\nprint(Path('/mnt/data/data.csv').exists())"
    exec_resp = await api_client.post(
        "/exec",
        json={
            "code": code,
            "lang": "py",
            "entity_id": "mnt_data_upload",
            "session_id": session_id,
            "files": [{"id": file_id, "session_id": session_id, "name": "data.csv"}],
        },
    )
    assert exec_resp.status_code == 200
    assert "True" in exec_resp.json()["run"]["stdout"]


@pytest.mark.asyncio
async def test_upload_file_returns_file_object(api_client):
    session_id, file_id, file_info = await _upload_file(api_client, "test.csv", b"a,b\n1,2\n")

    assert len(session_id) == 21
    assert all(ch.isalnum() or ch in "-_" for ch in session_id)
    assert file_info["path"] == f"/download/{session_id}/{file_id}"
    assert file_info["name"] == "test.csv"
    assert file_info["filename"] == "test.csv"
    assert file_info["size"] == 8
    assert file_info["session_id"] == session_id
    assert file_info["id"] == file_id
    assert file_info["fileId"] == file_id


@pytest.mark.asyncio
async def test_list_files_simple_and_full(api_client):
    session_id, file_id, _ = await _upload_file(api_client, "sample.txt", b"hello world")

    simple = await api_client.get(f"/files/{session_id}?detail=simple")
    assert simple.status_code == 200
    assert simple.json()[0] == {
        "id": file_id,
        "name": "sample.txt",
        "session_id": session_id,
        "path": f"/download/{session_id}/{file_id}",
    }

    full = await api_client.get(f"/files/{session_id}?detail=full")
    assert full.status_code == 200
    assert full.json()[0]["size"] == 11


@pytest.mark.asyncio
async def test_download_file(api_client):
    session_id, file_id, _ = await _upload_file(api_client, "download.txt", b"download me")

    response = await api_client.get(f"/download/{session_id}/{file_id}")
    assert response.status_code == 200
    assert response.content == b"download me"


@pytest.mark.asyncio
async def test_delete_file(api_client):
    session_id, file_id, _ = await _upload_file(api_client, "delete.txt", b"bye")

    response = await api_client.delete(f"/files/{session_id}/{file_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "deleted"

    missing = await api_client.get(f"/download/{session_id}/{file_id}")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_file_not_found(api_client):
    response = await api_client.get("/download/session_fake/file_fake")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_upload_and_use_file_in_execution(api_client):
    entity_id = "asst_file_exec"
    session_id, file_id, file_info = await _upload_file(
        api_client,
        "data.csv",
        b"name,value\nAlice,10\nBob,20\n",
        entity_id=entity_id,
    )

    code = """
import pandas as pd
from pathlib import Path
print(Path('data.csv').exists())
df = pd.read_csv('data.csv')
print(f"Rows: {len(df)}")
print(f"Sum of values: {df['value'].sum()}")
"""

    response = await api_client.post(
        "/exec",
        json={
            "code": code,
            "lang": "py",
            "entity_id": entity_id,
            "files": [
                {
                    "id": file_id,
                    "session_id": session_id,
                    "name": file_info["name"],
                }
            ],
        },
    )

    assert response.status_code == 200
    stdout = response.json()["run"]["stdout"]
    assert "Rows: 2" in stdout
    assert "Sum of values: 30" in stdout


@pytest.mark.asyncio
async def test_exec_file_hydration_accepts_mnt_data_prefixed_names(api_client):
    entity_id = "mnt_data_prefix_hydration"
    session_id, file_id, file_info = await _upload_file(api_client, "input.csv", b"a,b\n1,2\n", entity_id=entity_id)

    # Produce an output file under /mnt/data so it is registered as `mnt/data/<name>`.
    create_resp = await api_client.post(
        "/exec",
        json={
            "code": "from pathlib import Path\nPath('/mnt/data/out.txt').write_text('ok')\nprint('made')",
            "lang": "py",
            "entity_id": entity_id,
            "session_id": session_id,
            "files": [{"id": file_id, "session_id": session_id, "name": file_info["name"]}],
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    out_files = [f for f in created["files"] if f["name"].startswith("mnt/data/")]
    assert any(f["name"] == "mnt/data/out.txt" for f in out_files)

    # Re-run with file refs including a `name` that is already mnt/data-prefixed (LibreChat behavior).
    file_refs = [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in out_files]
    file_refs.append({"id": file_id, "session_id": session_id, "name": file_info["name"]})

    rerun_resp = await api_client.post(
        "/exec",
        json={
            "code": "from pathlib import Path\nprint(Path('/mnt/data/out.txt').read_text())",
            "lang": "py",
            "entity_id": entity_id,
            "session_id": session_id,
            "files": file_refs,
        },
    )
    assert rerun_resp.status_code == 200
    assert "ok" in (rerun_resp.json()["run"]["stdout"] or "")


@pytest.mark.asyncio
async def test_exec_file_hydration_falls_back_when_name_is_empty(api_client):
    entity_id = "empty_name_hydration"
    session_id, file_id, _ = await _upload_file(api_client, "data.csv", b"a,b\n1,2\n", entity_id=entity_id)

    response = await api_client.post(
        "/exec",
        json={
            "code": "from pathlib import Path\nprint(Path('/mnt/data/data.csv').exists())",
            "lang": "py",
            "entity_id": entity_id,
            "session_id": session_id,
            "files": [{"id": file_id, "session_id": session_id, "name": ""}],
        },
    )
    assert response.status_code == 200
    assert "True" in (response.json()["run"]["stdout"] or "")


@pytest.mark.asyncio
async def test_upload_requires_api_key_when_configured(api_client, enforce_api_key):
    def _payload():
        return {"files": ("secure.txt", b"secret", "text/plain")}

    missing = await api_client.post("/upload", files=_payload())
    assert missing.status_code == 401
    assert missing.json()["detail"] == "Invalid or missing API key"

    allowed = await api_client.post(
        "/upload",
        files=_payload(),
        headers={"x-api-key": enforce_api_key},
    )
    assert allowed.status_code == 200
