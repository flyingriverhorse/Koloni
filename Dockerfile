# syntax=docker/dockerfile:1
# KOLONİ in a box (0.1.0-docker), optional: the page, the API and the database in one
# container, for API and local models. No CLI is in it. README → "Docker" says how to run it.
# Not KOLONİ's own "Docker execution" setting, which runs agents' commands in containers.
# Base images pinned by digest: built and run 4 Nov 2026 (Docker 29.7.2) - the page opened, migrations ran.
# Move a digest on purpose, with a build and a run.

FROM node:24-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c AS page
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
# git: KOLONİ merges an agent's changes with yours and commits with it.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
# A real home: the MCP servers' folder is under ~/.cache. /data and /projects are its own,
# so a named volume starts with them writable.
RUN useradd --create-home --uid 1000 koloni \
 && mkdir /data /projects \
 && chown koloni:koloni /data /projects

# The source tree, as a checkout has it: KOLONİ reads alembic/, pyproject.toml, the built
# page, generated.ts (the page's API hash) and the draw.io viewer (app.diagram) beside app/.
# Owned by root: agents cannot change it.
WORKDIR /app
COPY pyproject.toml requirements-dev.lock README.md alembic.ini LICENSE NOTICE THIRD-PARTY-NOTICES.md ./
COPY alembic ./alembic
COPY app ./app
COPY scripts/koloni_statusline.py ./scripts/
COPY frontend/src/api/generated.ts ./frontend/src/api/
COPY frontend/THIRD-PARTY-NOTICES.md ./frontend/
COPY frontend/public/drawio ./frontend/public/drawio
COPY --from=page /src/frontend/dist ./frontend/dist
# The lock's versions, without its dev tools (pytest, ruff, ty).
# shortcut: the lock is made on Windows, so Linux-only packages (uvloop) are not pinned by it;
# make a universal lock if the image is published.
RUN pip install --no-cache-dir --disable-pip-version-check -c requirements-dev.lock -e .

# 0.0.0.0 inside the container only: the port is published as 127.0.0.1:8790:8790.
ENV KOLONI_HOST=0.0.0.0 \
    KOLONI_IN_CONTAINER=1 \
    KOLONI_PORT=8790 \
    KOLONI_RUNTIME_ROOT=/data \
    KOLONI_OPEN_BROWSER=0
USER koloni
VOLUME /data
EXPOSE 8790
CMD ["python", "-m", "app.main"]
