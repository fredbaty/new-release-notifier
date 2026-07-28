FROM python:3.12-slim

# uv resolves from uv.lock, so image builds match local runs exactly.
COPY --from=ghcr.io/astral-sh/uv:0.9.29 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first — this layer is reused unless the lockfile changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
COPY main.py update_db.py ./

ENV PATH="/app/.venv/bin:$PATH"

# Config is mounted in rather than baked, so the image holds no secrets.
# Set here so update_db.py and main.py both find it without --config.
ENV NRN_CONFIG=/config/config.yml

CMD ["python", "main.py"]
