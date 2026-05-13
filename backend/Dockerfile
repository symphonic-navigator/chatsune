FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY backend/pyproject.toml ./backend/
RUN uv venv /app/.venv && cd backend && UV_PROJECT_ENVIRONMENT=/app/.venv uv sync --no-install-project

COPY backend/ ./backend/
COPY shared/ ./shared/

# Build-time version metadata. The CI workflow injects these; local builds
# fall back to inert placeholders. ``CHATSUNE_VERSION`` is consumed by
# ``backend.modules.system._version``; the file is a belt-and-braces fallback
# in case the env var is overridden at runtime.
ARG VERSION=0.0.0-dev
ARG CHATSUNE_GIT_SHA=""
ARG CHATSUNE_BUILT_AT=""
RUN echo "$VERSION" > /app/VERSION
ENV CHATSUNE_VERSION=$VERSION
ENV CHATSUNE_GIT_SHA=$CHATSUNE_GIT_SHA
ENV CHATSUNE_BUILT_AT=$CHATSUNE_BUILT_AT

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
