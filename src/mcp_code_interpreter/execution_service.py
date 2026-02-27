from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from fastapi import HTTPException

from mcp_code_interpreter.kernel_manager import KernelSessionManager
from mcp_code_interpreter.process_runner import ProcessRunner, RunnerResult
from mcp_code_interpreter.session_registry import SessionContext, SessionRegistry
from mcp_code_interpreter.utils import execute_code_jupyter, execute_code_streaming


class OutputFormatter:
    _ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    @classmethod
    def strip_ansi(cls, value: str) -> str:
        return cls._ANSI_ESCAPE_RE.sub("", value)

    @staticmethod
    def normalize_stdout(result: dict[str, Any]) -> str:
        text = result.get("output") or ""
        if text and text.strip():
            return OutputFormatter.strip_ansi(text)

        outputs = result.get("outputs") or []
        text_parts: list[str] = []
        for entry in outputs:
            data = entry.get("data") if isinstance(entry, dict) else None
            if not data:
                continue
            if "text/plain" in data:
                text_parts.append(data["text/plain"])
        fallback = "\n".join(part.strip() for part in text_parts if part.strip())
        if fallback:
            return OutputFormatter.strip_ansi(fallback)

        error = result.get("error")
        return OutputFormatter.strip_ansi(error or "")


class ExecutionService:
    """Shared execution surface returning LibreChat ExecuteResponse payloads."""

    PYTHON_ALIASES = {"py", "python"}
    _MODULE_NOT_FOUND_RE = re.compile(r"No module named ['\"]([^'\"]+)['\"]")

    def __init__(
        self,
        *,
        kernel_manager: KernelSessionManager,
        sessions: SessionRegistry,
        language_kernel_map: dict[str, str],
        execution_timeout: int = 300,
        process_runner: ProcessRunner | None = None,
        pip_install_hints: bool = True,
    ):
        self.kernel_manager = kernel_manager
        self.sessions = sessions
        self.language_kernel_map = language_kernel_map
        self.execution_timeout = execution_timeout
        self.process_runner = process_runner
        self.pip_install_hints = pip_install_hints

    def _maybe_append_pip_hint(self, stderr: str) -> str:
        if not self.pip_install_hints or not stderr:
            return stderr

        stderr = OutputFormatter.strip_ansi(stderr)
        match = self._MODULE_NOT_FOUND_RE.search(stderr)
        if not match:
            return stderr

        module_name = match.group(1)
        if not module_name or module_name.startswith("."):
            return stderr

        hint = (
            f"\n\nHint: missing dependency '{module_name}'. Install it in this session, then re-run.\n\n"
            "Option A (recommended; uses the same interpreter):\n"
            "```python\n"
            "import subprocess, sys\n"
            f"subprocess.check_call([sys.executable, '-m', 'pip', 'install', '{module_name}'])\n"
            "```\n\n"
            "Option B:\n"
            f"  python -m pip install {module_name}\n\n"
            "Note: package names sometimes differ from import names."
        )
        if "python -m pip install" in stderr:
            return stderr
        return f"{stderr}{hint}"

    def _resolve_kernel_name(self, language: str) -> str | None:
        """Return the configured kernel name for ``language`` if one exists."""
        return self.language_kernel_map.get(language.lower())

    @staticmethod
    def _normalize_mnt_data_name(value: str) -> str:
        """Return a safe relative path under `mnt/data/` for a given file name reference.

        LibreChat may send `name` values like:
        - `gitlab_usage.csv`
        - `mnt/data/gitlab_usage.csv`
        - `/mnt/data/gitlab_usage.csv`

        We normalize these to a relative path (e.g., `gitlab_usage.csv`) and block traversal.
        """
        candidate = value.strip().replace("\\", "/")
        while candidate.startswith("/mnt/data/"):
            candidate = candidate.removeprefix("/mnt/data/").lstrip("/")
        while candidate.startswith("mnt/data/"):
            candidate = candidate.removeprefix("mnt/data/").lstrip("/")

        if not candidate:
            raise HTTPException(status_code=400, detail="Invalid file name reference")

        parts = [p for p in candidate.split("/") if p not in {"", "."}]
        if any(p == ".." for p in parts):
            raise HTTPException(status_code=400, detail="Invalid file name reference")
        return "/".join(parts)

    def _hydrate_files(self, context: SessionContext, files: list[dict[str, str]] | None) -> None:
        """Materialize referenced files into the session workspace.

        LibreChat's Execute Code tool references uploaded files by `{session_id, id, name}`.
        These files may originate from a different session than the one executing code, so we
        copy them into the active session workspace under `mnt/data/` for `/mnt/data/...`
        compatibility inside the Python kernel.
        """
        if not files:
            return

        mnt_data_dir = context.workspace / "mnt" / "data"
        mnt_data_dir.mkdir(parents=True, exist_ok=True)

        for file_ref in files:
            file_id = file_ref.get("id")
            if not file_id:
                raise HTTPException(status_code=400, detail="File references must include id")
            source_session = file_ref.get("session_id") or context.session_id
            registry_file = self.sessions.get_file(source_session, file_id)
            dest_name_raw = file_ref.get("name") or registry_file.name
            if not str(dest_name_raw).strip():
                dest_name_raw = registry_file.name
            dest_name = self._normalize_mnt_data_name(dest_name_raw)
            dest = mnt_data_dir / dest_name
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                dest.write_bytes(registry_file.disk_path.read_bytes())
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail="Referenced file content not found") from exc
            except PermissionError as exc:
                raise HTTPException(status_code=400, detail="Invalid file reference") from exc

    async def run(
        self,
        *,
        language: str,
        code: str,
        args: str | None,
        session_id: str | None,
        entity_id: str | None,
        files: list[dict[str, str]] | None,
    ) -> dict[str, Any]:
        """Execute code via the Python kernel or the ProcessRunner and return LibreChat payloads."""
        lang = language.lower()
        kernel_name = self._resolve_kernel_name(lang)

        # Resolve session + kernel affinity
        context = self.sessions.resolve_session(
            session_id=session_id,
            entity_id=entity_id,
            kernel_name=kernel_name,
        )
        session_id = context.session_id

        self._hydrate_files(context, files)

        if kernel_name:
            return await self._run_python(
                kernel_name=kernel_name,
                context=context,
                language=language,
                code=code,
                args=args,
            )

        if not self.process_runner:
            raise HTTPException(status_code=400, detail=f"Unsupported language '{language}'")

        result = await self.process_runner.run(
            language=lang,
            code=code,
            context=context,
            args=args,
        )

        self.sessions.sync_workspace_files(session_id)
        context = self.sessions.get_session(session_id)

        return self._format_process_response(language, session_id, context, result)

    async def stream(
        self,
        *,
        language: str,
        code: str,
        args: str | None,
        session_id: str | None,
        entity_id: str | None,
        files: list[dict[str, str]] | None,
    ) -> AsyncIterator[str]:
        """Yield SSE frames for Python executions (non-Python languages remain buffered)."""
        lang = language.lower()
        kernel_name = self._resolve_kernel_name(lang)
        context = self.sessions.resolve_session(
            session_id=session_id,
            entity_id=entity_id,
            kernel_name=kernel_name,
        )

        if not kernel_name:
            raise HTTPException(status_code=400, detail="Streaming is only supported for python")

        self._hydrate_files(context, files)

        km = self.kernel_manager.get_or_create_kernel(
            context.session_id,
            kernel_name=kernel_name,
            workspace=context.workspace,
        )
        final_code = f"# args: {args}\n{code}" if args else code

        yield f"data: {json.dumps({'type': 'session', 'session_id': context.session_id})}\n\n"

        async for chunk in execute_code_streaming(km, final_code, self.execution_timeout):
            yield chunk

        self.sessions.sync_workspace_files(context.session_id)

    async def _run_python(
        self,
        *,
        kernel_name: str,
        context: SessionContext,
        language: str,
        code: str,
        args: str | None,
    ) -> dict[str, Any]:
        """Execute Python within the shared kernel and build a LibreChat-style response."""
        session_id = context.session_id

        km = self.kernel_manager.get_or_create_kernel(
            session_id,
            kernel_name=kernel_name,
            workspace=context.workspace,
        )

        final_code = f"# args: {args}\n{code}" if args else code

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: execute_code_jupyter(km, final_code, self.execution_timeout),
        )
        assert isinstance(result, dict)
        result_dict: dict[str, Any] = result

        self.sessions.sync_workspace_files(session_id)
        context = self.sessions.get_session(session_id)

        stdout = OutputFormatter.normalize_stdout(result_dict)
        stderr = result_dict.get("error", "") or ""
        stderr = self._maybe_append_pip_hint(stderr)

        payload = {
            "run": {
                "stdout": stdout,
                "stderr": stderr,
                "code": 0 if result_dict.get("status") == "success" else 1,
                "signal": None,
                "output": stdout,
                "memory": None,
                "message": stderr if stderr else None,
                "status": result_dict.get("status"),
                "cpu_time": None,
                "wall_time": None,
            },
            "language": language,
            "version": "unknown",
            "session_id": session_id,
            "files": [f.to_summary() for f in context.files.values()],
            "output": stdout,
            "stdout": stdout,
            "stderr": stderr,
            "result": stdout,
        }
        return payload

    def _format_process_response(
        self, language: str, session_id: str, context: SessionContext, result: RunnerResult
    ) -> dict[str, Any]:
        """Return a consistent response payload for non-Python executions."""
        stdout = OutputFormatter.strip_ansi(result.stdout or result.stderr or "")
        stderr = OutputFormatter.strip_ansi(result.stderr or "")
        return {
            "run": {
                "stdout": stdout,
                "stderr": stderr,
                "code": result.code,
                "signal": None,
                "output": stdout,
                "memory": None,
                "message": stderr if result.code != 0 and stderr else None,
                "status": result.status,
                "cpu_time": None,
                "wall_time": None,
            },
            "language": language,
            "version": "unknown",
            "session_id": session_id,
            "files": [f.to_summary() for f in context.files.values()],
            "output": stdout,
            "stdout": stdout,
            "stderr": result.stderr,
            "result": stdout,
        }
