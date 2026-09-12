FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/
COPY migrations/ migrations/
RUN uv sync --frozen --no-dev

ENV PYTHONPATH="/app/src/GoogleFindMyTools:${PYTHONPATH}"

CMD ["uv", "run", "find-hub-tracker", "start"]
