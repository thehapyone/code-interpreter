import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from mcp_code_interpreter import server as server_module
from mcp_code_interpreter.server import app


@pytest_asyncio.fixture
async def api_client():
    """Reusable HTTPX client against the FastAPI app with lifespan support."""
    await app.router.startup()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await app.router.shutdown()


@pytest.fixture
def enforce_api_key():
    """Temporarily require an API key for REST requests."""
    previous = server_module.API_KEY
    server_module.API_KEY = "test-key"
    try:
        yield "test-key"
    finally:
        server_module.API_KEY = previous
