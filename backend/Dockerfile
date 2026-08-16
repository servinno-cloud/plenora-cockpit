FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONPATH=/app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 10001 cockpit

FROM base AS development
ENV RUFF_CACHE_DIR=/tmp/ruff-cache
ENV PYTEST_ADDOPTS="-q -o cache_dir=/tmp/pytest-cache"
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY --chown=cockpit:cockpit . .
USER cockpit
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS production
COPY --chown=cockpit:cockpit alembic.ini ./
COPY --chown=cockpit:cockpit alembic ./alembic
COPY --chown=cockpit:cockpit app ./app
USER cockpit
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
