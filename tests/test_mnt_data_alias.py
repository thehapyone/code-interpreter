"""Tests for the /mnt/data compatibility alias inside the Python kernel."""

import pytest


@pytest.mark.asyncio
async def test_exec_can_write_to_mnt_data_alias(api_client):
    entity_id = "asst_mnt_data_alias"
    code = """
from pathlib import Path

out_path = "/mnt/data/alias_test.txt"
Path("/mnt/data").mkdir(parents=True, exist_ok=True)
Path(out_path).write_text("hello", encoding="utf-8")
print(out_path)
"""

    response = await api_client.post(
        "/exec",
        json={"code": code, "lang": "py", "entity_id": entity_id},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "/mnt/data/alias_test.txt" in payload["run"]["stdout"]
    assert any(f["name"] == "mnt/data/alias_test.txt" for f in payload["files"])


@pytest.mark.asyncio
async def test_mnt_data_alias_blocks_path_traversal(api_client):
    entity_id = "asst_mnt_data_escape"
    code = """
from pathlib import Path

Path("/mnt/data/../escape.txt").write_text("nope", encoding="utf-8")
"""

    response = await api_client.post(
        "/exec",
        json={"code": code, "lang": "py", "entity_id": entity_id},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["status"] == "error"
    assert "PermissionError" in (payload.get("stderr") or payload["run"]["stderr"])

