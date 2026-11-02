# syntax=docker/dockerfile:1
# Adapted from AssemblyAI's LiveKit reference voice agent, itself adapted from
# https://github.com/livekit-examples/agent-starter-python
ARG PYTHON_VERSION=3.13
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS base

# Don't buffer logs, and compile bytecode at install time for a faster cold start
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV HF_HOME=/app/.cache/huggingface

FROM base AS build

# Compilers for packages with native extensions. git and git-lfs install LiveKit Agents from
# GitHub until the AssemblyAI TTS plugin is on PyPI (see pyproject.toml).
RUN apt-get update && apt-get install -y gcc g++ python3-dev git git-lfs \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so code-only changes reuse this layer
COPY pyproject.toml uv.lock ./
RUN mkdir -p src
RUN uv sync --locked --no-dev

# Download model files at build time rather than on the first call
RUN uv run --module livekit.agents download-files

COPY . .

# Runs the unit tests and, given ASSEMBLYAI_API_KEY, the LLM tests:
#   docker build --target test -t notes-agent-test . && docker run --rm --env-file .env.local notes-agent-test
FROM build AS test
RUN uv sync --locked
CMD ["uv", "run", "pytest", "-q"]

FROM base

# Run as an unprivileged user
ARG UID=10001
RUN adduser --disabled-password --gecos "" --home "/app" --shell "/sbin/nologin" --uid "${UID}" appuser
COPY --from=build --chown=appuser:appuser /app /app
WORKDIR /app

# The notes the agent works on. Mount any folder of Markdown or text files here; without a
# mount, the sample notes baked into the image are used.
ENV WORKSPACE_ROOT=/workspace
RUN mkdir -p /workspace && cp -r /app/sample-workspace/. /workspace/ && chown -R appuser:appuser /workspace
VOLUME ["/workspace"]

USER appuser

CMD ["uv", "run", "--no-dev", "src/agent.py", "start"]
