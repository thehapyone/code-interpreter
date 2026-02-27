"""FastAPI server exposing MCP and REST code execution APIs.

This module wires together the Jupyter kernel manager, session registry, process
runner, and HTTP routes used by REST/MCP clients (LibreChat, Claude Desktop,
etc.). It also houses light-weight request logging and CORS configuration.
"""

import logging
import mimetypes
import os
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, JsonValue, field_validator

from mcp_code_interpreter.capabilities import (
    RuntimeLibrariesRegistry,
    discover_runtime_capabilities,
)
from mcp_code_interpreter.execution_service import ExecutionService
from mcp_code_interpreter.kernel_manager import KernelSessionManager
from mcp_code_interpreter.process_runner import ProcessRunner
from mcp_code_interpreter.session_registry import SessionRegistry

# Configuration helpers


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


# Configuration from environment
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "50"))
EXECUTION_TIMEOUT = int(os.getenv("EXECUTION_TIMEOUT", "300"))
SUBPROCESS_MAX_MEMORY_MB = int(os.getenv("SUBPROCESS_MAX_MEMORY_MB", "0")) or None
SUBPROCESS_MAX_CPU_SECONDS = int(os.getenv("SUBPROCESS_MAX_CPU_SECONDS", "0")) or None
BASH_STRICT_MODE = _env_flag("BASH_STRICT_MODE", True)
LOG_REQUESTS = _env_flag("LOG_REQUESTS", False)
PIP_INSTALL_HINTS = _env_flag("PIP_INSTALL_HINTS", True)
BASE_DIR = Path(os.getenv("APP_BASE_DIR") or Path.cwd())
NOTEBOOKS_DIR = Path(os.getenv("NOTEBOOKS_DIR") or (BASE_DIR / "notebooks"))
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR") or (BASE_DIR / "uploads"))
API_KEY = os.getenv("CODE_INTERPRETER_API_KEY")
CORS_ALLOW_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")]
ALLOW_ALL_ORIGINS = CORS_ALLOW_ORIGINS == ["*"]
SUPPORTED_LANG_CODES = [
    "py",
    "python",
    "bash",
    "sh",
    "js",
    "javascript",
    "node",
    "ts",
    "typescript",
    "go",
    "cpp",
    "c++",
]


ENTITY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
MAX_ENTITY_ID_LENGTH = 40
ENTITY_ID_ERROR = (
    "entity_id must be <= 40 characters and match ^[A-Za-z0-9_-]+$"
)

# Ensure directories exist
NOTEBOOKS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

RUNTIME_CAPABILITIES = discover_runtime_capabilities()

logger = logging.getLogger("mcp_code_interpreter")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.getLevelName(os.getenv("LOG_LEVEL", "INFO").upper()))

kernel_manager = KernelSessionManager(max_sessions=MAX_SESSIONS, uploads_dir=UPLOADS_DIR)
session_registry = SessionRegistry(uploads_root=UPLOADS_DIR)
process_runner = ProcessRunner(
    capabilities=RUNTIME_CAPABILITIES,
    execution_timeout=EXECUTION_TIMEOUT,
    max_memory_mb=SUBPROCESS_MAX_MEMORY_MB,
    max_cpu_seconds=SUBPROCESS_MAX_CPU_SECONDS,
    bash_strict_mode=BASH_STRICT_MODE,
)
library_registry = RuntimeLibrariesRegistry(base_dir=BASE_DIR)
execution_service = ExecutionService(
    kernel_manager=kernel_manager,
    sessions=session_registry,
    language_kernel_map={
        "py": "python3",
        "python": "python3",
    },
    execution_timeout=EXECUTION_TIMEOUT,
    process_runner=process_runner,
    pip_install_hints=PIP_INSTALL_HINTS,
)


def validate_entity_id(value: str | None, *, raise_http: bool = False) -> str | None:
    """Validate entity IDs used for session affinity, raising HTTP 422 when requested."""
    if value is None:
        return None

    if len(value) > MAX_ENTITY_ID_LENGTH or not ENTITY_ID_PATTERN.fullmatch(value):
        if raise_http:
            raise HTTPException(status_code=422, detail=ENTITY_ID_ERROR)
        raise ValueError(ENTITY_ID_ERROR)

    return value


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan hook that shuts down stray Jupyter kernels on exit."""
    yield
    kernel_manager.shutdown_all()


# Initialize FastAPI app
app = FastAPI(
    title="MCP Code Interpreter",
    version="1.0.0",
    description="REST + MCP server for sandboxed code execution compatible with any MCP-compliant client",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if ALLOW_ALL_ORIGINS else CORS_ALLOW_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    logger.warning(
        "Validation error on %s %s: %s",
        request.method,
        request.url.path,
        exc.errors(),
    )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.middleware("http")
async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Optionally log incoming HTTP requests for debugging client integrations."""

    if not LOG_REQUESTS or request.url.path == "/health":
        return await call_next(request)

    start = time.perf_counter()
    headers = {k.lower(): v for k, v in request.headers.items()}
    if "x-api-key" in headers:
        headers["x-api-key"] = "***"

    content_type = headers.get("content-type", "")
    body_preview = ""
    form_preview = ""
    try:
        if content_type.startswith("application/json"):
            raw = await request.body()
            if raw:
                decoded = raw.decode("utf-8", errors="ignore")
                body_preview = decoded[:500]
        elif content_type.startswith("multipart/form-data"):
            # Avoid parsing multipart bodies here: consuming the request stream can
            # interfere with FastAPI's downstream form/file parsing and cause 422s.
            form_preview = "<multipart omitted>"
    except Exception:
        body_preview = body_preview or "<unavailable>"

    query = dict(request.query_params)
    logger.info(
        "REQ %s %s query=%s headers=%s body=%s files=%s",
        request.method,
        request.url.path,
        query,
        headers,
        body_preview,
        form_preview,
    )

    response = await call_next(request)
    duration = time.perf_counter() - start
    logger.info(
        "RES %s %s -> %s (%.3fs)",
        request.method,
        request.url.path,
        response.status_code,
        duration,
    )
    return response


# Request/Response models


class RestRequestFile(BaseModel):
    """Minimal file reference passed in execute payloads."""

    id: str = Field(..., description="File ID within the session registry")
    session_id: str = Field(..., description="Session ID owning the file")
    name: str = Field(..., description="Original file name")


class RestExecRequest(BaseModel):
    """OpenAPI-style execute request for LibreChat compatibility."""

    code: str
    lang: str = Field(
        ...,
        description="Language code (py, bash, js, ts, go, cpp, etc.)",
        json_schema_extra={"enum": cast(list[JsonValue], SUPPORTED_LANG_CODES)},
    )
    args: str | list[str] | None = None
    session_id: str | None = None
    user_id: str | None = None
    entity_id: str | None = Field(
        default=None,
        max_length=MAX_ENTITY_ID_LENGTH,
        description=(
            "Optional assistant/agent identifier (<=40 chars, alphanumeric, '_' or '-')"
        ),
        pattern=ENTITY_ID_PATTERN.pattern,
    )
    files: list[RestRequestFile] | None = None

    @field_validator("entity_id")
    @classmethod
    def _validate_entity_id(cls, value: str | None) -> str | None:
        return validate_entity_id(value)

    @field_validator("args")
    @classmethod
    def _normalize_args(cls, value: str | list[str] | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        # LibreChat sometimes sends [] for "no args" and arrays for argv-like inputs.
        if not value:
            return None
        return " ".join(str(item) for item in value)

    def normalized_args(self) -> str | None:
        value = self.args
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if not value:
            return None
        return " ".join(str(item) for item in value)


class RunResult(BaseModel):
    """Sub-structure mirroring LibreChat's ExecuteResponse.run payload."""

    stdout: str = ""
    stderr: str = ""
    code: int | None = None
    signal: str | None = None
    output: str = ""
    memory: int | None = None
    message: str | None = None
    status: str | None = None
    cpu_time: float | None = None
    wall_time: float | None = None


class FileRef(BaseModel):
    """Summary describing a file stored in the session workspace."""

    id: str
    name: str
    session_id: str
    path: str


class ExecuteResponse(BaseModel):
    """Unified response model returned by /exec."""

    stdout: str = ""
    stderr: str = ""
    run: RunResult
    files: list[FileRef]
    language: str
    version: str | None = None
    session_id: str


class HealthResponse(BaseModel):
    status: str
    active_sessions: int
    cleaned_sessions: int
    notebooks_dir: str
    uploads_dir: str
    max_sessions: int
    execution_timeout: int
    runtime_capabilities: dict[str, Any]
    runtime_libraries: dict[str, Any] | None = None


class RootResponse(BaseModel):
    name: str
    version: str
    features: list[str]
    endpoints: dict[str, str]


# NOTE: Response shape is produced by ExecutionService and matches LibreChat ExecuteResponse.


class FileObject(BaseModel):
    """Detailed file metadata matching LibreChat's schema."""

    id: str
    fileId: str
    name: str
    filename: str
    session_id: str
    path: str
    content: str | None = None
    size: int
    lastModified: str
    etag: str | None = None
    metadata: dict[str, Any] | None = None
    contentType: str | None = None


class UploadResponse(BaseModel):
    """Formal response for /upload, mirroring LibreChat expectations."""

    message: str
    session_id: str
    files: list[FileObject]


def require_api_key(x_api_key: str | None = Header(default=None)) -> str | None:
    """Validate the optional CODE_INTERPRETER_API_KEY header for protected endpoints."""
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return x_api_key


# API Endpoints


@app.post("/upload", response_model=UploadResponse)
async def upload_files_rest(
    entity_id: str | None = Form(default=None),
    files: list[UploadFile] | None = File(default=None),
    file: UploadFile | None = File(default=None),
    x_api_key: str | None = Depends(require_api_key),
) -> UploadResponse:
    """REST upload endpoint backed by SessionRegistry."""
    entity_id = validate_entity_id(entity_id, raise_http=True)
    context = session_registry.resolve_session(entity_id=entity_id)
    session_id = context.session_id

    uploads: list[UploadFile] = []
    if files:
        uploads.extend(files)
    if file:
        uploads.append(file)
    if not uploads:
        raise HTTPException(status_code=422, detail="No files uploaded")

    stored_files: list[FileObject] = []
    for upload in uploads:
        record = await session_registry.save_file(
            session_id=session_id,
            entity_id=entity_id,
            upload=upload,
        )
        payload = record.to_file_object()
        # LibreChat's Code Environment upload expects `fileId` and `filename`.
        payload["fileId"] = record.id
        payload["filename"] = record.name
        stored_files.append(FileObject(**payload))
        if LOG_REQUESTS:
            logger.info(
                "UPLOAD file session=%s entity=%s name=%s size=%s type=%s",
                session_id,
                entity_id,
                upload.filename,
                record.size,
                upload.content_type,
            )

    return UploadResponse(
        message="success",
        session_id=session_id,
        files=stored_files,
    )


@app.get("/libraries")
async def list_libraries(
    runtime: str | None = Query(default=None, description="Optional runtime filter"),
    x_api_key: str | None = Depends(require_api_key),
) -> JSONResponse:
    try:
        payload = library_registry.snapshot(runtime=runtime) if runtime else library_registry.snapshot()
    except KeyError as exc:  # runtime filter not found
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(content={"runtime_libraries": payload})


@app.get("/files/{session_id}", response_model=list[FileRef | FileObject])
async def list_files_rest(
    session_id: str,
    detail: Literal["simple", "summary", "full"] = "simple",
    x_api_key: str | None = Depends(require_api_key),
) -> list[FileRef | FileObject]:
    """List files for a given session via SessionRegistry."""
    is_full = detail == "full"
    files = session_registry.list_files(session_id, detail=is_full)
    if detail in {"simple", "summary"}:
        return [FileRef(**f) for f in files]
    return [FileObject(**f) for f in files]


@app.delete("/files/{session_id}/{file_id}")
async def delete_file_rest(
    session_id: str,
    file_id: str,
    x_api_key: str | None = Depends(require_api_key),
) -> dict[str, str]:
    """Delete a file from a session."""
    session_registry.delete_file(session_id, file_id)
    return {"status": "deleted", "session_id": session_id, "file_id": file_id}

@app.get("/download/{session_id}/{file_id}")
async def download_file_rest(
    session_id: str,
    file_id: str,
    x_api_key: str | None = Depends(require_api_key),
) -> FileResponse:
    """Download a file from a session."""
    record = session_registry.get_file(session_id, file_id)
    filename = Path(record.name).name
    media_type = record.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    if LOG_REQUESTS:
        logger.info(
            "DOWNLOAD file session=%s file=%s name=%s type=%s size=%s",
            session_id,
            file_id,
            record.name,
            media_type,
            record.size,
        )
    return FileResponse(
        record.disk_path,
        filename=filename,
        media_type=media_type,
    )


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check"""
    cleaned = kernel_manager.cleanup_dead_sessions()

    return HealthResponse(
        status="healthy",
        active_sessions=len(kernel_manager.kernel_sessions),
        cleaned_sessions=cleaned,
        notebooks_dir=str(NOTEBOOKS_DIR),
        uploads_dir=str(UPLOADS_DIR),
        max_sessions=MAX_SESSIONS,
        execution_timeout=EXECUTION_TIMEOUT,
        runtime_capabilities=discover_runtime_capabilities(),
        runtime_libraries=library_registry.snapshot(),
    )


@app.get("/", response_model=RootResponse)
async def root() -> RootResponse:
    """API documentation"""
    return RootResponse(
        name="MCP Code Interpreter",
        version="1.0.0",
        features=[
            "Jupyter kernel execution (persistent state)",
            "Python runtime with persistent session affinity",
            "File upload/download",
            "Streaming execution",
            "Session management",
            "Rich output support (plots, HTML, LaTeX)",
        ],
        endpoints={
            "GET /health": "Health check",
            "POST /exec": "OpenAPI compatible interpreter execute endpoint",
            "POST /exec/stream": "Server-Sent Events variant of execute",
            "POST /upload": "OpenAPI compatible interpreter upload endpoint",
            "GET /files/{session_id}": "List files for a session",
            "DELETE /files/{session_id}/{file_id}": "Delete a file from a session",
            "GET /download/{session_id}/{file_id}": "Download a file from a session",
        },
    )


@app.post("/exec", response_model=ExecuteResponse, response_model_exclude_none=True)
async def exec_rest(
    request: RestExecRequest,
    x_api_key: str | None = Depends(require_api_key),
) -> ExecuteResponse:
    """OpenAPI-compatible execute endpoint backed by ExecutionService."""
    # Map request files into simple dicts for ExecutionService
    files_payload = (
        [
            {
                "id": f.id,
                "session_id": f.session_id,
                "name": f.name,
                "path": f"/download/{f.session_id}/{f.id}",
            }
            for f in (request.files or [])
        ]
        if request.files
        else None
    )

    result = await execution_service.run(
        language=request.lang,
        code=request.code,
        args=request.normalized_args(),
        session_id=request.session_id
        or (request.files[0].session_id if request.files and len(request.files) > 0 else None),
        entity_id=request.entity_id,
        files=files_payload,
    )
    if LOG_REQUESTS:
        logger.info(
            "EXEC response session=%s stdout_len=%s files=%s",
            result.get("session_id"),
            len(result.get("stdout", "")),
            [f.get("id") for f in (result.get("files") or [])],
        )
    return ExecuteResponse(**result)


@app.post("/exec/stream")
async def exec_rest_stream(
    request: RestExecRequest,
    x_api_key: str | None = Depends(require_api_key),
) -> StreamingResponse:
    """Server-Sent Event variant of the execute endpoint."""

    files_payload = (
        [
            {
                "id": f.id,
                "session_id": f.session_id,
                "name": f.name,
                "path": f"/download/{f.session_id}/{f.id}",
            }
            for f in (request.files or [])
        ]
        if request.files
        else None
    )

    async def event_stream() -> AsyncIterator[str]:
        async for chunk in execution_service.stream(
            language=request.lang,
            code=request.code,
            args=request.normalized_args(),
            session_id=request.session_id
            or (request.files[0].session_id if request.files and len(request.files) > 0 else None),
            entity_id=request.entity_id,
            files=files_payload,
        ):
            yield chunk

    response = StreamingResponse(event_stream(), media_type="text/event-stream")
    if LOG_REQUESTS:
        logger.info(
            "EXEC stream initiated entity=%s files=%s",
            request.entity_id,
            [f.get("id") for f in (files_payload or [])],
        )
    return response


def main() -> None:
    """Entry point for running the server"""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
