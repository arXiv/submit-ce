FROM ghcr.io/astral-sh/uv:python3.11-bookworm AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
ENV UV_PYTHON_INSTALL_DIR=/python
ENV UV_PYTHON_PREFERENCE=only-managed
RUN uv python install 3.11

ARG git_commit
ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PATH="/usr/sbin:/usr/local/bin:/usr/bin:/bin"

RUN apt-get -q update && apt-get -y -q upgrade && \
    apt-get -y install default-libmysqlclient-dev

RUN useradd --create-home e-prints
USER e-prints
WORKDIR /home/e-prints
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv && \
    uv sync --locked --no-install-project --no-dev
COPY ./submit_ce ./submit_ce
# RUN --mount=type=cache,target=/root/.cache/uv \
#     uv sync --locked --no-dev

ENV PATH="/home/e-prints/.venv/bin:$PATH"

#################### with-dev-venv ####################
FROM builder AS with-dev-venv
USER e-prints
WORKDIR /home/e-prints
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked


#################### tester ####################
# based on gcloud cli image for pubsub emulator
FROM gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators AS run-tests
USER root
# If we don't copy the python the links in the venv will point nowhere
COPY --from=builder --chown=python:python /python /python

RUN useradd --create-home e-prints
USER e-prints
WORKDIR /home/e-prints
COPY --from=with-dev-venv --chown=e-prints:e-prints /home/e-prints /home/e-prints

# # Install pubsub emulator, used by submit_ce/implementations/pubsub
RUN gcloud components install beta pubsub-emulator --quiet

ENV PATH="/home/e-prints/.venv/bin:$PATH"
RUN pytest submit_ce/implementations submit_ce/api submit_ce/ui

#################### production ####################
FROM python:3.11-bookworm AS production
RUN apt-get -q update && apt-get -q -y upgrade && \
    apt-get -y install default-libmysqlclient-dev
COPY --from=builder --chown=python:python /python /python

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
