ARG DOCKER_CLI=docker:29-cli
ARG PYTHON_RUNTIME=python:3.12-slim-bookworm
FROM ${DOCKER_CLI} AS dockercli
FROM ${PYTHON_RUNTIME}
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
WORKDIR /app
COPY pyproject.toml uv.lock /app/
RUN python -m pip install --no-cache-dir uv==0.11.8 && uv sync --frozen --no-dev
COPY src /app/src
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1
EXPOSE 8092
CMD ["uv","run","--no-sync","uvicorn","repo_agent.app:create_app","--factory","--host","0.0.0.0","--port","8092"]
