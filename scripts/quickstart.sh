#!/bin/bash

# Quick Start Script for the MCP Code Interpreter
# This script helps you get started quickly

set -e

# Always operate from the project root regardless of where the script is invoked
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

echo "🚀 MCP Code Interpreter - Quick Start"
echo "================================================"
echo ""

# Check if UV is installed
if ! command -v uv &> /dev/null; then
    echo "❌ UV is not installed. Installing UV..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    echo "✅ UV installed successfully"
    echo ""
fi

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "⚠️  Docker is not installed. Please install Docker first."
    echo "   Visit: https://docs.docker.com/get-docker/"
    exit 1
fi

# Detect Docker Compose v2 plugin or fallback to docker-compose
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
elif command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE="docker-compose"
else
    echo "⚠️  Docker Compose is not installed. Please install Docker Compose v2."
    exit 1
fi

echo "📦 Creating necessary directories..."
mkdir -p notebooks uploads logs
echo "✅ Directories created"
echo ""

# Ask user for deployment method
echo "Choose deployment method:"
echo "1) Docker (Recommended for production)"
echo "2) Local development with UV"
read -r -p "Enter choice (1 or 2): " choice

if [ "$choice" == "1" ]; then
    echo ""
    echo "🐳 Docker Deployment Selected"
    echo "=============================="
    echo ""
    
    if [ "${MCP_NETWORK_EXTERNAL:-false}" = "true" ]; then
        if ! docker network ls | grep -q "${MCP_NETWORK_NAME:-mcp-network}"; then
            echo "Creating Docker network: ${MCP_NETWORK_NAME:-mcp-network}"
            docker network create "${MCP_NETWORK_NAME:-mcp-network}"
        fi
    fi
    
    echo "Building Docker image..."
    ${DOCKER_COMPOSE} build
    
    echo ""
    echo "Starting services..."
    ${DOCKER_COMPOSE} up -d
    
    echo ""
    echo "⏳ Waiting for server to be ready..."
    sleep 5
    
    # Health check
    max_attempts=12
    attempt=0
    while [ $attempt -lt $max_attempts ]; do
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            echo "✅ Server is healthy!"
            break
        fi
        echo "   Attempt $((attempt + 1))/$max_attempts - waiting..."
        sleep 5
        attempt=$((attempt + 1))
    done
    
    if [ $attempt -eq $max_attempts ]; then
        echo "❌ Server failed to start. Check logs with: ${DOCKER_COMPOSE} logs"
        exit 1
    fi
    
    echo ""
    echo "📊 Viewing logs (Ctrl+C to exit):"
    echo ""
    ${DOCKER_COMPOSE} logs -f
    
elif [ "$choice" == "2" ]; then
    echo ""
    echo "💻 Local Development Selected"
    echo "=============================="
    echo ""
    
    echo "Installing dependencies..."
    uv sync
    
    echo ""
    echo "✅ Dependencies installed"
    echo ""
    echo "Starting development server..."
    echo "Server will be available at: http://localhost:8000"
    echo "API docs at: http://localhost:8000/docs"
    echo ""
    echo "Press Ctrl+C to stop the server"
    echo ""
    
    uv run uvicorn mcp_code_interpreter.server:app --host 0.0.0.0 --port 8000 --reload
    
else
    echo "❌ Invalid choice. Please run the script again and select 1 or 2."
    exit 1
fi
