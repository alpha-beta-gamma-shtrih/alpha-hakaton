#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$PROJECT_DIR"

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker CLI not found." >&2
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "Docker Compose plugin is unavailable." >&2
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "Docker Engine is unavailable. On macOS, start Colima: colima start --cpu 4 --memory 8" >&2
    exit 1
fi

if [ ! -f .env ]; then
    echo "Create .env from .env.example and set the passwords and CSRF signing key." >&2
    exit 1
fi

echo "Building backend image..."
docker build -f Dockerfile -t credit-cabinet-app:local .

echo "Building frontend image..."
docker build -f frontend/Dockerfile -t credit-cabinet-frontend:local ./frontend

echo "Starting Compose: tests, database and model initialization, application..."
docker compose -f compose.yaml up -d
docker compose -f compose.yaml ps

FRONTEND_ADDRESS=$(docker compose -f compose.yaml port frontend 80)
echo "Frontend URL: http://localhost:${FRONTEND_ADDRESS##*:}"
