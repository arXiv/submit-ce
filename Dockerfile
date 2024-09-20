FROM python:3.11-bookworm AS builder

ADD https://astral.sh/uv/install.sh /install.sh
RUN chmod -R 655 /install.sh && /install.sh && rm /install.sh
ENV UV=/root/.cargo/bin/uv

WORKDIR /usr/app

RUN $UV venv /venv
ENV PATH="/venv/bin:$PATH"

RUN $UV pip install --upgrade pip
COPY ./requirements.txt .
RUN $UV pip install --no-cache-dir --no-deps -r requirements.txt && \
    $UV cache clean


FROM builder AS test
COPY ./requirements-dev.txt .
RUN $UV pip install --no-deps --no-cache-dir -r requirements-dev.txt && \
    $UV cache clean
COPY ./tests ./tests
COPY ./submit_ce ./submit_ce
RUN pytest tests


FROM python:3.11.8-bookworm AS service
WORKDIR /usr/app
COPY --from=builder /venv /venv
ENV PATH=/venv/bin:$PATH
COPY ./submit_ce ./submit_ce
COPY ./main.py .
CMD ["uvicorn", "submit_ce.fastapi.app:app", "--host", "0.0.0.0", "--port", "8000"]
