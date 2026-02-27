"""Kernel manager for Jupyter kernel lifecycle management"""

import json
from pathlib import Path
from typing import Any

from jupyter_client import KernelManager


class KernelSessionManager:
    """Manages Jupyter kernel sessions with lifecycle control"""

    def __init__(self, max_sessions: int = 50, uploads_dir: Path = Path("/app/uploads")):
        self.kernel_sessions: dict[str, KernelManager] = {}
        self.max_sessions = max_sessions
        self.uploads_dir = uploads_dir
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    def get_or_create_kernel(
        self,
        session_id: str,
        kernel_name: str = "python3",
        workspace: Path | None = None,
    ) -> KernelManager:
        """Get existing kernel or create new one"""
        if session_id in self.kernel_sessions:
            return self.kernel_sessions[session_id]

        # Create new kernel
        km = KernelManager(kernel_name=kernel_name)
        km.start_kernel()

        # Set working directory to uploads
        kc = km.client()
        kc.start_channels()
        kc.wait_for_ready(timeout=30)

        workdir = workspace or self.uploads_dir
        uploads_path = json.dumps(str(workdir))

        # Execute setup code in the new kernel to ensure proper working directory and imports
        setup_code = f"""
import os
import sys
from mcp_code_interpreter.kernel_fs_alias import install_mnt_data_alias
os.makedirs({uploads_path}, exist_ok=True)
if {uploads_path} not in sys.path:
    sys.path.insert(0, {uploads_path})
try:
    import pip  # noqa: F401
except Exception:
    pass
data_root = install_mnt_data_alias({uploads_path})
os.chdir(str(data_root))
"""
        kc.execute(setup_code)
        kc.stop_channels()

        self.kernel_sessions[session_id] = km

        # Clean up old sessions if needed
        if len(self.kernel_sessions) > self.max_sessions:
            oldest = list(self.kernel_sessions.keys())[0]
            self.kernel_sessions[oldest].shutdown_kernel()
            del self.kernel_sessions[oldest]

        return km

    def shutdown_kernel(self, session_id: str) -> bool:
        """Shutdown a specific kernel session"""
        if session_id in self.kernel_sessions:
            km = self.kernel_sessions[session_id]
            km.shutdown_kernel()
            del self.kernel_sessions[session_id]
            return True
        return False

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all active sessions"""
        sessions = []
        for session_id, km in self.kernel_sessions.items():
            sessions.append(
                {"session_id": session_id, "kernel": km.kernel_name, "is_alive": km.is_alive()}
            )
        return sessions

    def cleanup_dead_sessions(self) -> int:
        """Remove dead kernel sessions"""
        dead_sessions = [
            session_id for session_id, km in self.kernel_sessions.items() if not km.is_alive()
        ]

        for session_id in dead_sessions:
            del self.kernel_sessions[session_id]

        return len(dead_sessions)

    def shutdown_all(self) -> None:
        """Shutdown all kernel sessions"""
        for km in self.kernel_sessions.values():
            try:
                km.shutdown_kernel()
            except Exception:
                pass
        self.kernel_sessions.clear()
