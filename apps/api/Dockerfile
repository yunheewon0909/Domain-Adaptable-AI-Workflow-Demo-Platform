# Image for both the `api` and `worker` containers.
# Built from the repo root so the uv workspace root (pyproject.toml + uv.lock)
# and the `apps/api` member are both in context.
FROM python:3.12-slim

# Pin to 3.12 for broad wheel availability (the repo's .python-version is 3.14
# for local dev; container images intentionally use 3.12 — see ADR 0007).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON=3.12 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv binary
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/

WORKDIR /app

# Dependency layer (cached unless lock/manifests change).
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
RUN uv sync --no-dev --project apps/api --no-install-workspace

# Application code.
COPY . .
RUN uv sync --no-dev --project apps/api

EXPOSE 8000

# Default command runs the API; the worker service overrides this in compose.
# The `api` package is installed into the venv by `uv sync`, so it imports
# without an explicit --app-dir.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
