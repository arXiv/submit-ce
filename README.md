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
python tests/make_test_db.py

# this will give you an Authorization token, save that and use a browser extension
# like modheader to add Authorization=eyJhb...

python main.py

google-chrome localhost:8080
```


## Build Docker Image

```bash
docker build . -t arxiv/submit_ce
```

## Tests

To run the tests:

```bash
pytest tests
```
