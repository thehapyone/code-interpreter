"""Tests for REST execution endpoints."""

from typing import Any

import pytest

SHARED_ENTITY_ID = "tests_shared_entity"
SESSION_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


def assert_session_id(value: str) -> None:
    assert len(value) == 21
    assert all(ch in SESSION_CHARS for ch in value)


def assert_execute_response(payload: dict[str, Any]) -> None:
    required_keys = {"stdout", "stderr", "run", "files", "language", "session_id"}
    for key in required_keys:
        assert key in payload, f"missing '{key}' in execute response"
    assert isinstance(payload["files"], list)
    assert payload["stdout"] == payload["run"].get("stdout")
    assert payload["stderr"] == payload["run"].get("stderr")
    assert_session_id(payload["session_id"])


@pytest.mark.asyncio
async def test_health_check(api_client):
    response = await api_client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert "active_sessions" in payload
    assert "runtime_capabilities" in payload
    assert "runtime_libraries" in payload


@pytest.mark.asyncio
async def test_libraries_endpoint(api_client):
    response = await api_client.get("/libraries")
    assert response.status_code == 200
    payload = response.json()
    runtimes = payload.get("runtime_libraries", {})
    expected = {"python", "bash", "node", "typescript", "go", "cpp"}
    assert expected.issubset(runtimes.keys())
    python_info = runtimes.get("python")
    assert python_info is not None
    assert isinstance(python_info.get("packages"), list)


@pytest.mark.asyncio
async def test_execute_python_code(api_client):
    code = "print('Hello, World!')\nresult = 2 + 2\nprint(f'2 + 2 = {result}')"

    response = await api_client.post(
        "/exec",
        json={"code": code, "lang": "py", "entity_id": SHARED_ENTITY_ID},
    )

    assert response.status_code == 200
    payload = response.json()
    stdout = payload["run"]["stdout"]
    assert "Hello, World!" in stdout
    assert "2 + 2 = 4" in stdout
    assert payload["language"].startswith("py")
    assert_execute_response(payload)


@pytest.mark.asyncio
async def test_session_affinity_via_entity_id(api_client):
    entity_id = SHARED_ENTITY_ID

    first = await api_client.post(
        "/exec",
        json={
            "code": "counter = 41\nprint('counter set')",
            "lang": "py",
            "entity_id": entity_id,
        },
    )
    assert first.status_code == 200
    first_session = first.json()["session_id"]

    second = await api_client.post(
        "/exec",
        json={
            "code": "counter += 1\nprint(f'counter value: {counter}')",
            "lang": "py",
            "entity_id": entity_id,
        },
    )

    assert second.status_code == 200
    payload = second.json()
    assert payload["session_id"] == first_session
    assert "counter value: 42" in payload["run"]["stdout"]


@pytest.mark.asyncio
async def test_unsupported_language_returns_400(api_client):
    response = await api_client.post(
        "/exec",
        json={"code": "print('hi')", "lang": "fortran", "entity_id": SHARED_ENTITY_ID},
    )
    assert response.status_code == 400
    assert "Unsupported language" in response.json()["detail"]


@pytest.mark.asyncio
async def test_execute_with_streaming_endpoint(api_client):
    response = await api_client.post(
        "/exec/stream",
        json={"code": "print('stream hello')", "lang": "py", "entity_id": SHARED_ENTITY_ID},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    # Consume the streaming body and ensure we see at least one data chunk
    body = response.text
    assert "data:" in body


@pytest.mark.asyncio
async def test_exec_accepts_args_as_list(api_client):
    response = await api_client.post(
        "/exec",
        json={"code": "print('ok')", "lang": "py", "entity_id": "args_list_test", "args": []},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_missing_module_includes_pip_hint(api_client):
    response = await api_client.post(
        "/exec",
        json={"code": "import definitely_not_installed_abcdef", "lang": "py", "entity_id": "pip_hint"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["status"] == "error"
    stderr = payload["run"]["stderr"] or ""
    assert "No module named" in stderr
    assert "python -m pip install definitely_not_installed_abcdef" in stderr
    assert "subprocess.check_call" in stderr
    assert "sys.executable" in stderr


@pytest.mark.asyncio
async def test_tracebacks_are_returned_without_ansi_escape_codes(api_client):
    response = await api_client.post(
        "/exec",
        json={"code": "raise ValueError('boom')", "lang": "py", "entity_id": "no_ansi"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["status"] == "error"
    stderr = payload["run"]["stderr"] or ""
    assert "\x1b[" not in stderr
    assert "ValueError" in stderr



@pytest.mark.asyncio
async def test_execute_without_entity_id_creates_session(api_client):
    response = await api_client.post(
        "/exec",
        json={"code": "print('anon session')", "lang": "py"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert_execute_response(payload)


@pytest.mark.asyncio
async def test_exec_requires_api_key_when_configured(api_client, enforce_api_key):
    payload = {"code": "print('secure')", "lang": "py"}

    missing = await api_client.post("/exec", json=payload)
    assert missing.status_code == 401
    assert missing.json()["detail"] == "Invalid or missing API key"

    allowed = await api_client.post(
        "/exec",
        json=payload,
        headers={"x-api-key": enforce_api_key},
    )
    assert allowed.status_code == 200
