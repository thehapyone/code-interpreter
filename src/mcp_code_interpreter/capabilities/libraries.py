"""Runtime library inventory helper.

Collects information about available libraries/tooling for every runtime the
interpreter exposes. For Python, it inspects installed packages and declared
`pyproject` dependencies. For other runtimes, it surfaces global tool versions
plus optional package manager metadata when feasible.
"""

from __future__ import annotations

import copy
import datetime as dt
import importlib.metadata as metadata
import json
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

tomllib: ModuleType | None
try:  # Python 3.11+
    import tomllib as _tomllib

    tomllib = _tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for older interpreters
    tomllib = None


def _canonicalize_name(name: str) -> str:
    """Normalize package names for comparison (PEP 503 style)."""
    return name.replace("_", "-").lower()


def _strip_requirement_marker(spec: str) -> str:
    """Extract the package portion from a dependency spec string."""
    head = spec.strip()
    if not head:
        return ""
    for delimiter in (" ", "[", "<", ">", "=", "!", "~", ";"):
        index = head.find(delimiter)
        if index != -1:
            head = head[:index]
            break
    return head.strip()


@dataclass(slots=True)
class LibraryPackage:
    """Represents a single library entry for a runtime."""

    name: str
    version: str | None
    declared: bool
    installed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "declared": self.declared,
            "installed": self.installed,
        }


CANONICAL_RUNTIMES = ("python", "bash", "node", "typescript", "go", "cpp")
RUNTIME_ALIASES = {
    "python": "python",
    "py": "python",
    "bash": "bash",
    "sh": "bash",
    "node": "node",
    "javascript": "node",
    "js": "node",
    "typescript": "typescript",
    "ts": "typescript",
    "go": "go",
    "cpp": "cpp",
    "c++": "cpp",
}


class RuntimeLibrariesRegistry:
    """Collects and caches information about libraries available per runtime."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = Path(base_dir or Path.cwd())
        self._pyproject = self._base_dir / "pyproject.toml"
        self._lock = threading.Lock()
        self._snapshot: dict[str, dict[str, Any]] = {}
        self.refresh()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def snapshot(self, runtime: str | None = None) -> dict[str, dict[str, Any]]:
        """Return the cached library inventory, optionally filtered by runtime."""
        with self._lock:
            if runtime is None:
                return copy.deepcopy(self._snapshot)

            key = RUNTIME_ALIASES.get(runtime.lower(), runtime.lower())
            info = self._snapshot.get(key)
            if info is None:
                raise KeyError(f"runtime '{runtime}' not found")
            return {key: copy.deepcopy(info)}

    def refresh(self) -> dict[str, dict[str, Any]]:
        """Recompute the inventory and update the cached snapshot."""
        snapshot = self._build_snapshot()
        with self._lock:
            self._snapshot = snapshot
            return copy.deepcopy(self._snapshot)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _build_snapshot(self) -> dict[str, dict[str, Any]]:
        data: dict[str, dict[str, Any]] = {}

        builders = {
            "python": self._build_python_snapshot,
            "bash": self._build_bash_snapshot,
            "node": self._build_node_snapshot,
            "typescript": self._build_typescript_snapshot,
            "go": self._build_go_snapshot,
            "cpp": self._build_cpp_snapshot,
        }

        for runtime, builder in builders.items():
            snapshot = builder()
            if snapshot is not None:
                data[runtime] = snapshot

        return data

    def _build_python_snapshot(self) -> dict[str, Any] | None:
        packages: list[LibraryPackage] = []
        declared = self._read_declared_python_dependencies()
        installed = self._discover_installed_python_packages()

        for canonical, package in sorted(installed.items()):
            packages.append(
                LibraryPackage(
                    name=package["name"],
                    version=package.get("version"),
                    declared=canonical in declared,
                    installed=True,
                )
            )

        for canonical, display in sorted(declared.items()):
            if canonical in installed:
                continue
            packages.append(
                LibraryPackage(
                    name=display,
                    version=None,
                    declared=True,
                    installed=False,
                )
            )

        if not packages:
            return None

        return {
            "packages": [pkg.to_dict() for pkg in packages],
            "refreshed_at": dt.datetime.now(dt.UTC).isoformat(),
            "metadata": {
                "declared_count": len(declared),
                "installed_count": len(installed),
            },
        }

    def _read_declared_python_dependencies(self) -> dict[str, str]:
        if tomllib is None or not self._pyproject.exists():
            return {}

        try:
            data = tomllib.loads(self._pyproject.read_text(encoding="utf-8"))
        except Exception:
            return {}

        declared: dict[str, str] = {}
        project = data.get("project", {})
        deps = project.get("dependencies", []) or []
        for entry in deps:
            self._record_declared(entry, declared)

        optional = project.get("optional-dependencies", {}) or {}
        for entries in optional.values():
            for entry in entries:
                self._record_declared(entry, declared)

        return declared

    def _record_declared(self, entry: str, declared: dict[str, str]) -> None:
        name = _strip_requirement_marker(entry)
        if not name:
            return
        canonical = _canonicalize_name(name)
        declared.setdefault(canonical, name)

    def _discover_installed_python_packages(self) -> dict[str, dict[str, Any]]:
        installed: dict[str, dict[str, Any]] = {}
        for dist in metadata.distributions():
            name = dist.metadata.get("Name") or dist.metadata.get("Summary")
            if not name:
                continue
            canonical = _canonicalize_name(name)
            installed[canonical] = {
                "name": name,
                "version": dist.version,
            }
        return installed

    def _build_bash_snapshot(self) -> dict[str, Any] | None:
        return self._single_binary_snapshot(
            runtime="bash",
            binaries=["/bin/bash"],
            version_command=["/bin/bash", "--version"],
        )

    def _build_node_snapshot(self) -> dict[str, Any] | None:
        snapshot = self._single_binary_snapshot(
            runtime="node",
            binaries=["node"],
            version_command=["node", "--version"],
        )
        if not snapshot:
            return None
        npm_info = self._npm_list() if snapshot.get("available") else []
        if npm_info:
            snapshot["packages"] = npm_info
        return snapshot

    def _build_typescript_snapshot(self) -> dict[str, Any] | None:
        snapshot = self._single_binary_snapshot(
            runtime="typescript",
            binaries=["npx", "ts-node"],
            version_command=["npx", "ts-node", "--version"],
        )
        if snapshot is None:
            return None
        snapshot.setdefault("packages", []).append({
            "name": "ts-node",
            "version": snapshot.get("version"),
            "declared": False,
            "installed": bool(snapshot.get("version")),
        })
        return snapshot

    def _build_go_snapshot(self) -> dict[str, Any] | None:
        return self._single_binary_snapshot(
            runtime="go",
            binaries=["go"],
            version_command=["go", "version"],
        )

    def _build_cpp_snapshot(self) -> dict[str, Any] | None:
        snapshot = self._single_binary_snapshot(
            runtime="cpp",
            binaries=["g++"],
            version_command=["g++", "--version"],
        )
        if snapshot is None:
            return None
        snapshot.setdefault("packages", []).append(
            {
                "name": "libstdc++",
                "version": snapshot.get("version"),
                "declared": False,
                "installed": bool(snapshot.get("version")),
            }
        )
        return snapshot

    def _single_binary_snapshot(
        self,
        *,
        runtime: str,
        binaries: list[str],
        version_command: list[str] | None,
    ) -> dict[str, Any] | None:
        missing = [binary for binary in binaries if not self._which(binary)]
        available = not missing
        version = self._run_command(version_command) if (available and version_command) else None
        return {
            "binaries": binaries,
            "missing": missing,
            "available": available,
            "version": version,
            "refreshed_at": dt.datetime.now(dt.UTC).isoformat(),
        }

    def _npm_list(self) -> list[dict[str, Any]]:
        output = self._run_command(["npm", "list", "--depth=0", "--json"])
        if not output:
            return []
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return []
        dependencies = payload.get("dependencies", {})
        entries: list[dict[str, Any]] = []
        for name, info in dependencies.items():
            entries.append(
                {
                    "name": name,
                    "version": info.get("version"),
                    "declared": True,
                    "installed": True,
                }
            )
        return entries

    def _which(self, binary: str) -> str | None:
        result = shutil.which(binary)
        return result

    def _run_command(self, command: list[str] | None) -> str | None:
        if not command:
            return None
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return None
        return completed.stdout.strip()
