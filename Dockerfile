FROM ghcr.io/astral-sh/uv:python3.11-bookworm AS builder

WORKDIR /usr/app

RUN uv venv /venv
ENV PATH="/venv/bin:$PATH"

COPY pyproject.toml uv.lock .
RUN uv sync --no-dev  && \
    uv cache clean


# FROM builder AS test
# RUN uv sync --only-dev && \
#     uv cache clean
# COPY ./submit_ce ./submit_ce
# RUN pytest tests


FROM python:3.11.8-bookworm AS service
WORKDIR /usr/app
COPY --from=builder /venv /venv
ENV PATH=/venv/bin:$PATH
COPY ./submit_ce ./submit_ce
CMD ["uvicorn", "submit_ce.ui.factory:create_web_app", "--host", "0.0.0.0", "--port", "8000"]
