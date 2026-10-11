FROM node:26.10.0-bookworm-slim@sha256:3ffc19ea878019d9e9ae8971732ad4a03cda44f167107173174b60ed7c65bed3 AS browser
WORKDIR /browser
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --registry=https://registry.npmjs.org
COPY frontend/index.html ./
COPY frontend/src ./src
RUN npm run build

FROM python:3.12-alpine3.24@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4 AS python-base
RUN apk add --no-cache zlib=1.3.2-r1

FROM python-base AS dependencies
COPY --from=ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-editable --no-managed-python --no-build --no-cache

FROM python-base AS runtime
RUN python -m pip uninstall --yes pip && rm -rf /usr/local/lib/python3.12/ensurepip
WORKDIR /app
ARG RELEASE
RUN python -c "import os,pathlib,re; value=os.environ['RELEASE']; assert re.fullmatch('[a-f0-9]{40}', value), 'RELEASE must be a commit SHA'; pathlib.Path('/app/release.txt').write_text(value+'\n')"
LABEL org.opencontainers.image.revision=$RELEASE
COPY --from=dependencies /app/.venv /app/.venv
COPY --from=browser /browser/dist /app/frontend/dist
COPY energy_ai /app/energy_ai
COPY examples/monthly-office /app/examples/monthly-office
RUN mkdir -p /data /etc/energy-ai && chown 10001:10001 /data
ENV PATH="/app/.venv/bin:/usr/local/bin:/usr/bin:/bin" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["/app/.venv/bin/python", "-B", "-m", "energy_ai.web.serve"]
