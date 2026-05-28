FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl tzdata && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --no-dev --frozen

COPY . .

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "ticorates.main:app", "--host", "0.0.0.0", "--port", "8000"]
