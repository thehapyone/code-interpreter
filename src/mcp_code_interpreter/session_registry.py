from __future__ import annotations

import mimetypes
import secrets
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from fastapi import HTTPException, UploadFile

SESSION_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
SESSION_ID_LENGTH = 21


def _now() -> datetime:
    return datetime.now(timezone.utc)  # noqa: UP017


def _generate_id(prefix: str | None = None) -> str:
    core = "".join(secrets.choice(SESSION_ID_ALPHABET) for _ in range(SESSION_ID_LENGTH))
    return f"{prefix}{core}" if prefix else core


def generate_session_id() -> str:
    return _generate_id()


def sanitize_session_id(session_id: str) -> str:
    value = session_id.removeprefix("session_")
    allowed = set(SESSION_ID_ALPHABET)
    filtered = "".join(ch for ch in value if ch in allowed)
    return filtered[:SESSION_ID_LENGTH]


def generate_file_id() -> str:
    return _generate_id()


def sanitize_filename(value: str | None) -> str:
    """Return a safe filename for storing on disk (no directory traversal)."""
    if not value:
        return "upload"
    name = Path(value).name.strip()
    return name or "upload"


@dataclass
class FileRecord:
    """Metadata describing a file stored within a session."""

    id: str
    session_id: str
    entity_id: str | None
    name: str
    disk_path: Path
    size: int
    content_type: str | None
    created_at: datetime
    etag: str | None = None

    @property
    def download_path(self) -> str:
        return f"/download/{self.session_id}/{self.id}"

    def to_summary(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "session_id": self.session_id,
            "path": self.download_path,
        }

    def to_file_object(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "fileId": self.id,
            "name": self.name,
            "filename": self.name,
            "session_id": self.session_id,
            "entity_id": self.entity_id,
            "content": None,
            "size": self.size,
            "lastModified": self.created_at.isoformat(),
            "etag": self.etag,
            "metadata": {
                "content-type": self.content_type or "",
                "original-filename": self.name,
            },
            "contentType": self.content_type,
            "path": self.download_path,
        }


@dataclass
class SessionContext:
    """Tracks kernel/file state for a given session."""

    session_id: str
    kernel_name: str
    workspace: Path
    entity_id: str | None = None
    files: dict[str, FileRecord] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def touch(self) -> None:
        self.updated_at = _now()


class SessionRegistry:
    """In-memory registry providing session + file bookkeeping."""

    CHUNK_SIZE_BYTES = 1024 * 1024

    def __init__(self, uploads_root: Path):
        self._uploads_root = uploads_root
        self._uploads_root.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, SessionContext] = {}
        self._entity_to_session: dict[str, str] = {}
        self._lock = RLock()

    def resolve_session(
        self,
        *,
        session_id: str | None = None,
        entity_id: str | None = None,
        kernel_name: str | None = None,
    ) -> SessionContext:
        """Return existing session or create a new one with optional entity affinity."""
        with self._lock:
            context: SessionContext | None = None

            normalized_session = sanitize_session_id(session_id) if session_id else None

            if normalized_session and normalized_session in self._sessions:
                context = self._sessions[normalized_session]

            elif entity_id and entity_id in self._entity_to_session:
                mapped_session = self._entity_to_session[entity_id]
                context = self._sessions.get(mapped_session)

            if context is None:
                context = self._create_session(
                    kernel_name=kernel_name or "python3", entity_id=entity_id
                )

            if entity_id:
                self._entity_to_session[entity_id] = context.session_id
                context.entity_id = entity_id

            context.kernel_name = kernel_name or context.kernel_name
            context.touch()
            return context

    def _create_session(self, kernel_name: str, entity_id: str | None = None) -> SessionContext:
        session_id = generate_session_id()
        workspace = self._uploads_root / session_id
        workspace.mkdir(parents=True, exist_ok=True)

        context = SessionContext(
            session_id=session_id,
            kernel_name=kernel_name,
            workspace=workspace,
            entity_id=entity_id,
        )
        self._sessions[session_id] = context
        if entity_id:
            self._entity_to_session[entity_id] = session_id
        return context

    def get_session(self, session_id: str) -> SessionContext:
        with self._lock:
            if session_id not in self._sessions:
                raise HTTPException(status_code=404, detail="Session not found")
            return self._sessions[session_id]

    def list_sessions(self) -> list[SessionContext]:
        with self._lock:
            return list(self._sessions.values())

    def session_dir(self, session_id: str) -> Path:
        return self._uploads_root / session_id

    async def save_file(
        self,
        *,
        session_id: str,
        entity_id: str | None,
        upload: UploadFile,
    ) -> FileRecord:
        context = self.get_session(session_id)
        file_id = generate_file_id()
        directory = self.session_dir(session_id)
        base_name = sanitize_filename(upload.filename) or file_id
        destination = directory / "mnt" / "data" / base_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            stem = destination.stem or base_name
            suffix = destination.suffix
            counter = 1
            while True:
                candidate = destination.parent / f"{stem}_{counter}{suffix}"
                if not candidate.exists():
                    destination = candidate
                    break
                counter += 1

        size = 0
        with destination.open("wb") as buffer:
            while True:
                chunk = await upload.read(self.CHUNK_SIZE_BYTES)
                if not chunk:
                    break
                buffer.write(chunk)
                size += len(chunk)

        await upload.close()

        record = FileRecord(
            id=file_id,
            session_id=session_id,
            entity_id=entity_id or context.entity_id,
            name=base_name,
            disk_path=destination,
            size=size,
            content_type=upload.content_type,
            created_at=_now(),
        )
        with self._lock:
            context.files[record.id] = record
            context.touch()
        return record

    def list_files(self, session_id: str, *, detail: bool = False) -> list[dict[str, Any]]:
        context = self.get_session(session_id)
        files = list(context.files.values())
        return [f.to_file_object() if detail else f.to_summary() for f in files]

    def get_file(self, session_id: str, file_id: str) -> FileRecord:
        context = self.get_session(session_id)
        record = context.files.get(file_id)
        if not record:
            raise HTTPException(status_code=404, detail="File not found")
        return record

    def delete_file(self, session_id: str, file_id: str) -> None:
        context = self.get_session(session_id)
        record = context.files.pop(file_id, None)
        if not record:
            raise HTTPException(status_code=404, detail="File not found")

        if record.disk_path.exists():
            record.disk_path.unlink()

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            context = self._sessions.pop(session_id, None)
            if not context:
                raise HTTPException(status_code=404, detail="Session not found")

            if context.entity_id and self._entity_to_session.get(context.entity_id) == session_id:
                self._entity_to_session.pop(context.entity_id, None)

        shutil.rmtree(context.workspace, ignore_errors=True)

    def attach_entity(self, session_id: str, entity_id: str) -> None:
        with self._lock:
            context = self.get_session(session_id)
            context.entity_id = entity_id
            self._entity_to_session[entity_id] = session_id
            context.touch()

    def sync_workspace_files(self, session_id: str) -> list[FileRecord]:
        """Register any new files that were created directly in the workspace."""
        context = self.get_session(session_id)
        created: list[FileRecord] = []

        with self._lock:
            known_paths = {record.disk_path.resolve(strict=False) for record in context.files.values()}
            for path in context.workspace.rglob("*"):
                if not path.is_file():
                    continue

                resolved = path.resolve(strict=False)
                if resolved in known_paths:
                    continue

                relative = path.relative_to(context.workspace).as_posix()
                if any(record.name == relative for record in context.files.values()):
                    continue

                record = FileRecord(
                    id=generate_file_id(),
                    session_id=session_id,
                    entity_id=context.entity_id,
                    name=relative,
                    disk_path=path,
                    size=path.stat().st_size,
                    content_type=mimetypes.guess_type(path.name)[0],
                    created_at=_now(),
                )
                context.files[record.id] = record
                created.append(record)

            if created:
                context.touch()

        return created
