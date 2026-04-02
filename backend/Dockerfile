FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY backend/pyproject.toml ./backend/
RUN uv venv /app/.venv && cd backend && UV_PROJECT_ENVIRONMENT=/app/.venv uv sync --no-install-project

COPY backend/ ./backend/
COPY shared/ ./shared/

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
