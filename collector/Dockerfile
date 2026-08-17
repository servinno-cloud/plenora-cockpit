FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONPATH=/app
RUN useradd --create-home --uid 10002 collector && mkdir /state && chown collector:collector /state
COPY --chown=collector:collector src ./src
COPY --chown=collector:collector pyproject.toml ./

FROM base AS development
RUN pip install --no-cache-dir "pytest>=8.3,<9" "ruff>=0.9,<1" "psycopg[binary]>=3.2,<4"
COPY --chown=collector:collector tests ./tests
USER collector
CMD ["python", "-m", "src.runner"]

FROM base AS production
RUN pip install --no-cache-dir "psycopg[binary]>=3.2,<4"
USER collector
CMD ["python", "-m", "src.runner"]
