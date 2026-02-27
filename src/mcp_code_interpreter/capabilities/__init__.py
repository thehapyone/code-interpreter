"""Runtime capability discovery utilities and helpers."""

from __future__ import annotations

import shutil

from .libraries import RuntimeLibrariesRegistry

REQUIRED_BINARIES: dict[str, list[str]] = {
    "bash": ["/bin/bash"],
    "node": ["node"],
    "ts-node": ["npx", "ts-node"],
    "go": ["go"],
    "c++": ["g++"],
}


def discover_runtime_capabilities() -> dict[str, dict[str, object]]:
    capabilities: dict[str, dict[str, object]] = {}
    for runtime, binaries in REQUIRED_BINARIES.items():
        missing = [binary for binary in binaries if shutil.which(binary) is None]
        capabilities[runtime] = {
            "available": not missing,
            "binaries": binaries,
            "missing": missing,
        }
    return capabilities


__all__ = ["RuntimeLibrariesRegistry", "discover_runtime_capabilities"]
