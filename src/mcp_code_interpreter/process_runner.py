from __future__ import annotations

import asyncio
import os
import shlex
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from fastapi import HTTPException

from mcp_code_interpreter.session_registry import SessionContext

try:  # POSIX-only resource controls
    import resource

    resource_module: ModuleType | None = resource
    _HAS_RESOURCE = True
except ImportError:  # pragma: no cover - platform specific
    resource_module = None
    _HAS_RESOURCE = False


@dataclass
class RunnerResult:
    stdout: str
    stderr: str
    code: int

    @property
    def status(self) -> str:
        return "success" if self.code == 0 else "error"


class ProcessRunner:
    """Executes non-Python code by invoking local runtimes inside a session workspace."""

    PYTHON_ALIASES = {"py", "python"}

    ENV_ALLOWLIST = {
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LC_NUMERIC",
        "TZ",
        "TERM",
    }
    ENV_PREFIX_ALLOWLIST = ("LC_",)

    def __init__(
        self,
        *,
        capabilities: dict[str, dict[str, object]],
        execution_timeout: int,
        max_memory_mb: int | None = None,
        max_cpu_seconds: int | None = None,
        bash_strict_mode: bool = True,
    ):
        self.capabilities = capabilities
        self.execution_timeout = execution_timeout
        self.max_memory_mb = max_memory_mb
        self.max_cpu_seconds = max_cpu_seconds
        self.bash_strict_mode = bash_strict_mode

    async def run(
        self,
        *,
        language: str,
        code: str,
        context: SessionContext,
        args: str | None,
    ) -> RunnerResult:
        """Execute a non-Python snippet inside the session workspace.

        The call selects the correct runtime for ``language`` and writes ``code`` to
        a temporary file rooted in ``context.workspace``. Bash/Node/TS/Go run the
        source via ``_run_single`` while C++ is compiled via ``_run_cpp``.
        """
        lang = language.lower()
        if lang in self.PYTHON_ALIASES:
            raise HTTPException(status_code=500, detail="ProcessRunner should not handle python")

        if lang in {"bash", "sh"}:
            return await self._run_single(
                capability="bash",
                extension=".sh",
                command_builder=self._bash_command,
                code=code,
                context=context,
                args=args,
                code_transform=self._apply_bash_guard if self.bash_strict_mode else None,
            )
        if lang in {"js", "javascript", "node"}:
            return await self._run_single(
                capability="node",
                extension=".mjs",
                command_builder=self._node_command,
                code=code,
                context=context,
                args=args,
            )
        if lang in {"ts", "typescript"}:
            return await self._run_single(
                capability="ts-node",
                extension=".ts",
                command_builder=self._ts_command,
                code=code,
                context=context,
                args=args,
            )
        if lang == "go":
            return await self._run_single(
                capability="go",
                extension=".go",
                command_builder=self._go_command,
                code=code,
                context=context,
                args=args,
            )
        if lang in {"cpp", "c++"}:
            return await self._run_cpp(code=code, context=context, args=args)

        raise HTTPException(status_code=400, detail=f"Unsupported language '{language}'")

    def _ensure_capability(self, capability: str) -> None:
        info = self.capabilities.get(capability)
        if not info or not info.get("available"):
            raise HTTPException(status_code=503, detail=f"Runtime '{capability}' is unavailable")

    async def _run_single(
        self,
        *,
        capability: str,
        extension: str,
        command_builder: Callable[[Path], list[str]],
        code: str,
        context: SessionContext,
        args: str | None,
        code_transform: Callable[[str], str] | None = None,
    ) -> RunnerResult:
        """Write ``code`` to disk, execute it, and clean up the temporary file."""
        self._ensure_capability(capability)
        payload = code_transform(code) if code_transform else code
        mnt_data = context.workspace / "mnt" / "data"
        mnt_data.mkdir(parents=True, exist_ok=True)
        source = self._write_source(mnt_data, extension, payload)
        try:
            command = command_builder(source)
            if args:
                command.extend(shlex.split(args))
            return await self._exec(command, cwd=mnt_data)
        finally:
            source.unlink(missing_ok=True)

    async def _run_cpp(self, *, code: str, context: SessionContext, args: str | None) -> RunnerResult:
        """Compile a C++ program, run the binary, and delete artifacts afterward."""
        capability = "c++"
        self._ensure_capability(capability)
        mnt_data = context.workspace / "mnt" / "data"
        mnt_data.mkdir(parents=True, exist_ok=True)
        source = self._write_source(mnt_data, ".cpp", code)
        binary = mnt_data / f"exec_{uuid.uuid4().hex}"
        try:
            compile_result = await self._exec([
                "g++",
                str(source),
                "-std=c++17",
                "-O2",
                "-o",
                str(binary),
            ], cwd=mnt_data)
            if compile_result.code != 0:
                return compile_result

            command = [str(binary)]
            if args:
                command.extend(shlex.split(args))
            run_result = await self._exec(command, cwd=mnt_data)
            return run_result
        finally:
            source.unlink(missing_ok=True)
            if binary.exists():
                binary.unlink()

    def _write_source(self, workspace: Path, extension: str, code: str) -> Path:
        workspace.mkdir(parents=True, exist_ok=True)
        source = workspace / f"run_{uuid.uuid4().hex}{extension}"
        source.write_text(code)
        return source

    def _bash_command(self, source: Path) -> list[str]:
        return ["/bin/bash", str(source)]

    def _node_command(self, source: Path) -> list[str]:
        return ["node", str(source)]

    def _ts_command(self, source: Path) -> list[str]:
        return ["npx", "ts-node", str(source)]

    def _go_command(self, source: Path) -> list[str]:
        return ["go", "run", str(source)]

    async def _exec(self, command: list[str], *, cwd: Path) -> RunnerResult:
        """Execute ``command`` with a sanitized environment and return captured output."""
        env = self._build_env(cwd)

        preexec_fn = None
        if _HAS_RESOURCE and (self.max_memory_mb or self.max_cpu_seconds):
            preexec_fn = self._build_preexec()

        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=preexec_fn,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self.execution_timeout
            )
        except TimeoutError:
            proc.kill()
            raise HTTPException(status_code=504, detail="Execution timed out") from None

        stdout = stdout_bytes.decode("utf-8", errors="ignore")
        stderr = stderr_bytes.decode("utf-8", errors="ignore")
        return RunnerResult(stdout=stdout, stderr=stderr, code=int(proc.returncode or 0))

    def _build_preexec(self) -> Callable[[], None]:  # pragma: no cover - platform specific
        if resource_module is None:
            raise RuntimeError("POSIX resource module unavailable")

        max_memory_bytes = None
        if self.max_memory_mb:
            max_memory_bytes = self.max_memory_mb * 1024 * 1024

        max_cpu_seconds = self.max_cpu_seconds

        def preexec() -> None:
            if max_memory_bytes:
                resource_module.setrlimit(resource_module.RLIMIT_AS, (max_memory_bytes, max_memory_bytes))
            if max_cpu_seconds:
                resource_module.setrlimit(resource_module.RLIMIT_CPU, (max_cpu_seconds, max_cpu_seconds))

        return preexec

    def _build_env(self, workspace: Path) -> dict[str, str]:
        """Return a minimal environment where HOME/PYTHONPATH point at ``workspace``."""
        env: dict[str, str] = {}
        allowlist = set(self.ENV_ALLOWLIST)

        for key in allowlist:
            if key == "PATH":
                env[key] = os.environ.get("PATH") or os.defpath
                continue
            value = os.environ.get(key)
            if value is not None:
                env[key] = value

        for key, value in os.environ.items():
            if any(key.startswith(prefix) for prefix in self.ENV_PREFIX_ALLOWLIST):
                env[key] = value

        env["HOME"] = str(workspace)
        env["PYTHONPATH"] = ""
        return env

    def _apply_bash_guard(self, code: str) -> str:
        """Prepend ``set -euo pipefail`` (respecting shebangs) for safer bash execution."""
        guard = "set -euo pipefail\n"
        if code.startswith("#!"):
            newline = code.find("\n")
            if newline == -1:
                return f"{code}\n{guard}"
            return f"{code[: newline + 1]}{guard}{code[newline + 1:]}"
        return f"{guard}{code}"
