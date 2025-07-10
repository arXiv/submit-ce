FROM ghcr.io/astral-sh/uv:python3.11-bookworm AS builder

RUN apt-get update && apt-get install dnsutils
RUN nslookup github.com

WORKDIR /usr/app

COPY pyproject.toml uv.lock .

RUN uv sync --no-dev  && \
    uv cache clean

ENV PATH="/usr/app/.venv/bin:$PATH"

COPY ./submit_ce ./submit_ce
CMD ["gunicorn", "submit_ce.ui.factory:create_web_app()", "--host", "0.0.0.0", "--port", "8000"]
