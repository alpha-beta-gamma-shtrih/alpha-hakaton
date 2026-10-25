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

cleanup_tests() {
    docker compose -f compose.yaml --profile test rm -sf tests postgres-test
}

echo "Running tests..."
trap cleanup_tests EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
docker compose -f compose.yaml --profile test up --exit-code-from tests tests
cleanup_tests
trap - EXIT INT TERM

echo "Starting PostgreSQL..."
docker compose -f compose.postgres.yaml up -d --wait postgres

echo "Starting Ollama and downloading model..."
docker compose -f compose.ollama.yaml up -d --wait ollama
docker compose -f compose.ollama.yaml run --rm ollama-model

echo "Starting application..."
docker compose -f compose.yaml up -d frontend
docker compose -f compose.yaml ps

echo "Frontend URL: http://localhost:8080"
