FROM python:3.14-slim

ARG APP_UID=1000
ARG APP_GID=1000

# Install system dependencies and language toolchains
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    nodejs \
    npm \
    git \
    curl \
    wget \
    build-essential \
    golang \
    && npm install -g ts-node typescript \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g typescript

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PORT=8000

# Install UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Create non-root user early so we can chown directories later
RUN groupadd --gid ${APP_GID} app && useradd --uid ${APP_UID} --gid app --create-home app

# Copy dependency files
COPY pyproject.toml uv.lock* README.md ./

# Copy application code before syncing so the project package is available for install
COPY src/ ./src/

# Install dependencies using UV
RUN uv sync --frozen --no-dev && \
    /opt/venv/bin/python -m pip --version && \
    chown -R app:app /opt/venv /app

# Drop privileges for runtime
USER app

ENV PATH="/opt/venv/bin:${PATH}"

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Run the application (uv will use the synced virtualenv)
CMD ["sh", "-c", "uvicorn mcp_code_interpreter.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
