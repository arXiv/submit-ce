FROM ghcr.io/astral-sh/uv:python3.11-bookworm AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

ARG git_commit
ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random

RUN apt-get update && apt-get -y upgrade
RUN useradd --create-home e-prints
USER e-prints
WORKDIR /home/e-prints
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev && uv cache clean
ENV PATH="/home/e-prints/.venv/bin:$PATH"
COPY ./submit_ce ./submit_ce

#################### tester ####################
# based on gcloud cli image for pubsub emulator
FROM builder AS run-tests
USER root

RUN apt-get install -y --no-install-recommends openjdk-17-jre-headless && \
    rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

USER e-prints
WORKDIR /home/e-prints
COPY --from=builder --chown=e-prints:e-prints /home/e-prints /home/e-prints
ENV PATH="/home/e-prints/.venv/bin:$PATH"

RUN uv sync --locked && uv cache clean && chown -R e-prints:e-prints /home/e-prints

ENV PATH="/home/e-prints/google-cloud-sdk/bin:$PATH"
RUN curl -sSL https://sdk.cloud.google.com | bash && \
    gcloud components install beta pubsub-emulator

RUN pytest --cov=submit_ce/api,submit_ce/implementations,submit_ce/ui \
    --cov-fail-under=60 \
    submit_ce/api submit_ce/implementations submit_ce/ui

#################### production ####################
FROM python:3.11-bookworm AS production
RUN apt-get update && apt-get -y upgrade && apt-get -y install default-libmysqlclient-dev

RUN useradd --create-home e-prints
USER e-prints
WORKDIR /home/e-prints
COPY --from=builder --chown=e-prints:e-prints /home/e-prints /home/e-prints
ENV PATH="/home/e-prints/.venv/bin:$PATH"

CMD ["gunicorn", "--bind", ":8080", \
    "--workers", "5",\
    "--threads", "10",\
    "--timeout", "0 ",\
    "submit_ce.ui.factory:create_web_app()"]
