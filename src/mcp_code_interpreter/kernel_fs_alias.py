"""Kernel-side path aliases for compatibility with Code Interpreter conventions.

This module is imported from the Jupyter kernel process (not the API server)
during kernel bootstrap.
"""

from __future__ import annotations

import builtins
import io
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

_MNT_DATA_PREFIX = "/mnt/data"
_INSTALLED = False

T = TypeVar("T")


def _is_mnt_data_path(value: str) -> bool:
    return value == _MNT_DATA_PREFIX or value.startswith(f"{_MNT_DATA_PREFIX}/")


def _install_guard() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True


def install_mnt_data_alias(workspace: str | os.PathLike[str]) -> Path:
    """Map POSIX ``/mnt/data`` to a per-session workspace directory.

    The alias is implemented by monkey-patching common filesystem entrypoints in
    the kernel process, ensuring that reads/writes to ``/mnt/data/...`` land
    under ``<workspace>/mnt/data/...``. Attempted path traversal escapes raise
    ``PermissionError``.
    """

    _install_guard()

    workspace_path = Path(workspace)
    data_root = (workspace_path / "mnt" / "data")
    data_root.mkdir(parents=True, exist_ok=True)

    data_root_resolved = data_root.resolve(strict=False)

    def translate(value: Any) -> Any:
        if value is None:
            return value

        try:
            fspath = os.fspath(value)
        except TypeError:
            return value

        if isinstance(fspath, bytes):
            prefix = _MNT_DATA_PREFIX.encode()
            if fspath != prefix and not fspath.startswith(prefix + b"/"):
                return value
            decoded = fspath.decode("utf-8", errors="surrogatepass")
            mapped = translate(decoded)
            return os.fsencode(mapped)

        if not isinstance(fspath, str) or not _is_mnt_data_path(fspath):
            return value

        suffix = fspath[len(_MNT_DATA_PREFIX) :].lstrip("/")
        candidate = (data_root / suffix).resolve(strict=False)
        if candidate != data_root_resolved and data_root_resolved not in candidate.parents:
            raise PermissionError(f"Path escapes /mnt/data alias: {fspath!r}")
        return str(candidate)

    def wrap_open(orig: Callable[..., Any]) -> Callable[..., Any]:
        def patched(file: Any, *args: Any, **kwargs: Any) -> Any:
            return orig(translate(file), *args, **kwargs)

        return patched

    def wrap_os_path1(orig: Callable[..., T]) -> Callable[..., T]:
        def patched(path: Any, *args: Any, **kwargs: Any) -> T:
            return orig(translate(path), *args, **kwargs)

        return patched

    def wrap_os_path2(orig: Callable[..., T]) -> Callable[..., T]:
        def patched(src: Any, dst: Any, *args: Any, **kwargs: Any) -> T:
            return orig(translate(src), translate(dst), *args, **kwargs)

        return patched

    builtins.open = wrap_open(builtins.open)
    io.open = wrap_open(io.open)
    os.open = wrap_os_path1(os.open)

    for name in ("mkdir", "makedirs", "remove", "unlink", "rmdir"):
        setattr(os, name, wrap_os_path1(getattr(os, name)))

    for name in ("listdir", "scandir", "stat", "lstat"):
        setattr(os, name, wrap_os_path1(getattr(os, name)))

    for name in ("rename", "replace"):
        setattr(os, name, wrap_os_path2(getattr(os, name)))

    return data_root
