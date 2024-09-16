# submit-ce API
arXiv paper submission system

## Installation & Usage

To run the server, please execute the following from the root directory:

```bash
poetry install
fastapi dev src/arxiv/submit_fastapi/main.py
```

and open your browser at `http://localhost:8000/docs/` to see the docs.

## Running with Docker

To run the server on a Docker container, please execute the following from the root directory:

```bash
docker-compose up --build
```

## Tests

To run the tests:

```bash
pip3 install pytest
PYTHONPATH=src pytest tests
```
