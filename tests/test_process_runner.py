import shutil

import pytest
from fastapi import HTTPException

from mcp_code_interpreter.process_runner import ProcessRunner
from mcp_code_interpreter.session_registry import SessionContext


@pytest.mark.asyncio
async def test_process_runner_executes_bash(tmp_path):
    context = SessionContext(
        session_id="session_test",
        kernel_name="python3",
        workspace=tmp_path / "session",
    )
    runner = ProcessRunner(
        capabilities={"bash": {"available": True, "binaries": ["/bin/bash"], "missing": []}},
        execution_timeout=5,
    )

    result = await runner.run(language="bash", code='echo "hello world"', context=context, args=None)

    assert result.code == 0
    assert "hello world" in result.stdout


@pytest.mark.asyncio
async def test_process_runner_bash_strict_mode(tmp_path):
    strict_context = SessionContext(
        session_id="strict",
        kernel_name="python3",
        workspace=tmp_path / "strict",
    )
    lenient_context = SessionContext(
        session_id="lenient",
        kernel_name="python3",
        workspace=tmp_path / "lenient",
    )
    capabilities = {"bash": {"available": True, "binaries": ["/bin/bash"], "missing": []}}

    strict_runner = ProcessRunner(
        capabilities=capabilities,
        execution_timeout=5,
        bash_strict_mode=True,
    )

    lenient_runner = ProcessRunner(
        capabilities=capabilities,
        execution_timeout=5,
        bash_strict_mode=False,
    )

    code = "#!/bin/bash\n echo start\n false\n echo done\n"

    strict = await strict_runner.run(language="bash", code=code, context=strict_context, args=None)
    assert strict.code != 0
    assert "done" not in strict.stdout

    lenient = await lenient_runner.run(language="bash", code=code, context=lenient_context, args=None)
    assert lenient.code == 0
    assert "done" in lenient.stdout


@pytest.mark.asyncio
async def test_process_runner_env_sanitized(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "ultra-secret")

    context = SessionContext(
        session_id="session_env",
        kernel_name="python3",
        workspace=tmp_path / "env",
    )
    runner = ProcessRunner(
        capabilities={"bash": {"available": True, "binaries": ["/bin/bash"], "missing": []}},
        execution_timeout=5,
    )

    code = 'echo "secret=${SECRET_TOKEN:-missing}"\nprintf "home=%s\\n" "$HOME"\n'
    result = await runner.run(language="bash", code=code, context=context, args=None)

    assert result.code == 0
    assert "secret=missing" in result.stdout
    assert f"home={context.workspace}" in result.stdout


@pytest.mark.asyncio
async def test_process_runner_missing_runtime(tmp_path):
    context = SessionContext(
        session_id="session_test_missing",
        kernel_name="python3",
        workspace=tmp_path / "session",
    )
    runner = ProcessRunner(
        capabilities={"node": {"available": False, "binaries": ["node"], "missing": ["node"]}},
        execution_timeout=5,
    )

    with pytest.raises(HTTPException) as exc:
        await runner.run(language="js", code="console.log('hi')", context=context, args=None)

    assert exc.value.status_code == 503


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ not installed")
async def test_process_runner_cpp(tmp_path):
    context = SessionContext(
        session_id="session_test_cpp",
        kernel_name="python3",
        workspace=tmp_path / "session",
    )
    runner = ProcessRunner(
        capabilities={
            "c++": {"available": True, "binaries": ["g++"], "missing": []},
        },
        execution_timeout=5,
    )

    code = """
#include <iostream>
int main() {
    std::cout << "cpp-ok" << std::endl;
    return 0;
}
"""
    result = await runner.run(language="cpp", code=code, context=context, args=None)
    assert result.code == 0
    assert "cpp-ok" in result.stdout
