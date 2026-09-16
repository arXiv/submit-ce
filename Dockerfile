FROM ghcr.io/astral-sh/uv:python3.11-bookworm AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
ENV UV_PYTHON_INSTALL_DIR=/python


# used with the pubsub test for the COPY of python
# ENV UV_PYTHON_PREFERENCE=only-managed
# RUN uv python install 3.11

ENV UV_PYTHON_DOWNLOADS=0

ARG GIT_COMMIT
ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PATH="/usr/sbin:/usr/local/bin:/usr/bin:/bin"

RUN apt-get -q update && apt-get -y -q upgrade && \
    apt-get -y install default-libmysqlclient-dev \
                       cmake \
                       libprotobuf-dev \
                       protobuf-compiler


RUN useradd --create-home e-prints
USER e-prints
WORKDIR /home/e-prints
RUN echo $GIT_COMMIT > git_commit.txt
COPY pyproject.toml uv.lock ./

RUN uv venv && \
    uv sync --locked --no-install-project --no-dev
COPY ./submit_ce ./submit_ce

ENV PATH="/home/e-prints/.venv/bin:$PATH"
USER root
RUN python submit_ce/ui/compile_sass.py
USER e-prints

#################### with-dev-venv ####################
FROM builder AS with-dev-venv
USER e-prints
WORKDIR /home/e-prints
RUN uv sync --locked

# This is a test that tries to do pubsub but it takes a very long time on GCP
#################### tester ####################
# based on gcloud cli image for pubsub emulator
# FROM gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators AS run-tests
# USER root
# # If we don't copy the python the links in the venv will point nowhere
# COPY --from=builder  /python /python

# RUN useradd --create-home e-prints
# USER e-prints
# WORKDIR /home/e-prints
# COPY --from=with-dev-venv --chown=e-prints:e-prints /home/e-prints /home/e-prints

# # # Install pubsub emulator, used by submit_ce/implementations/pubsub
# RUN gcloud components install beta pubsub-emulator --quiet

# ENV PATH="/home/e-prints/.venv/bin:$PATH"
# RUN pytest submit_ce/implementations submit_ce/api submit_ce/ui

#################### tester ####################
FROM with-dev-venv AS run-tests
USER e-prints
WORKDIR /home/e-prints
ENV PATH="/home/e-prints/.venv/bin:$PATH"
RUN pytest submit_ce/api submit_ce/ui submit_ce/implementations/legacy_implementation/ \
    submit_ce/implementations/file_store/ submit_ce/implementations/compile

#################### production ####################
FROM python:3.11-bookworm AS production
RUN apt-get -q update && apt-get -q -y upgrade && \
    apt-get -y install default-libmysqlclient-dev libprotobuf32

# this has the same python paths as ghcr.io/astral-sh/uv:python3.11-bookworm
# so this is no longer needed.
#COPY --from=builder  /python /python

RUN useradd --create-home e-prints
USER e-prints
WORKDIR /home/e-prints
COPY --from=builder --chown=e-prints:e-prints /home/e-prints /home/e-prints
ENV PATH="/home/e-prints/.venv/bin:$PATH"

# The default CMD is the Flask submission UI;
# The SWORD deposit API is the same image, and Cloud Run overrides the
# entrypoint per service (see cicd/cloudbuild-sword-dev-arxiv.yaml):
#
#     uvicorn --factory --host 0.0.0.0 --port 8080 submit_ce.sword.app:create_sword_app
#
CMD ["gunicorn", "--bind", ":8080", \
    "--workers", "5",\
    "--threads", "10",\
    "--timeout", "0 ",\
    "submit_ce.ui.factory:create_web_app()"]
