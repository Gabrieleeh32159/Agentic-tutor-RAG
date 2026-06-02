# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# uv: compile bytecode for faster cold starts, copy (not symlink) into the image
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first, in their own layer, for better build caching.
# --no-install-project: deps only (project code copied below) ; --no-dev: skip test/lint group.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy the application and install the project itself.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

EXPOSE 8000

# Render injects $PORT; fall back to 8000 for local `docker run`.
# `fastapi run` is the production server (not `fastapi dev`); it binds 0.0.0.0.
CMD ["sh", "-c", "uv run fastapi run app/main.py --host 0.0.0.0 --port ${PORT:-8000}"]
