# submit-ce API
arXiv paper submission system

## Installation & Usage

To run the server, please execute the following from the root directory:

```bash
# setup venv in your preferred way
python --version
# 3.11

pip install --no-deps -r requirements.txt
pip install --no-deps -r requirements-dev.txt

# make sqlite dev db
python test/make_test_db.py

python main.py
```

and open your browser at `http://localhost:8000/docs/` to see the docs.

## Build Docker Image

```bash
docker build . -t arxiv/submit_ce
```

## Tests

To run the tests:

```bash
pytest tests
```
