FROM python:3.12-slim AS base
WORKDIR /app
RUN useradd --create-home --uid 10003 observer
COPY --chown=observer:observer observer/server.py ./
COPY --chown=observer:observer observer/publisher.py ./publisher.py
COPY --chown=observer:observer observer/pyproject.toml ./
COPY --chown=observer:observer collector/src ./src

FROM base AS development
RUN pip install --no-cache-dir "pytest>=8.3,<9" "ruff>=0.9,<1"
COPY --chown=observer:observer observer/tests ./tests
USER observer
CMD ["python", "server.py"]

FROM base AS production
USER observer
CMD ["python", "server.py"]

FROM base AS publisher
RUN pip install --no-cache-dir "psycopg[binary]>=3.2,<4"
USER observer
CMD ["python", "publisher.py"]
