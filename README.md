# submit-ce API
arXiv paper submission system

## Install & use

To run the server, please execute the following from the root directory:

```bash
# Install gcld3 dependencies needed by arxiv-base metadata checks
sudo apt-get install cmake libprotobuf-dev protobuf-compiler
# mac notes: don't use a version greater than:
#   $ brew search protobuf
#   protobuf@21 ✔ (deprecated)

uv sync

uv run python submit_ce/make_test_db.py bootstrap_db
# this will give you an Authorization token, save that and use a browser extension
# like modheader to add Authorization=eyJhb...

uv run python local_dev.py
open http://localhost:8000
```

On the mac:
```
```bash
# mac notes: don't use a version of protobuf greater than 21:
brew search protobuf
brew install protobuf@21
uv sync
uv run python submit_ce/make_test_db.py bootstrap_db
# this will give you an Authorization token, save that and use a browser extension
# like modheader to add Authorization=eyJhb...
uv run python local_dev.py
open http://localhost:8000
```

##  Run the tests

```bash
pytest submit_ce
```

## Run the Flask app pointed to a different bucket
```bash
STORE=gs \
STORE_GS_BUCKET=xyz-bucket \
STORE_GS_PREFIX=data/new \
uv run flask --app submit_ce.ui.factory:create_web_app run -p 8000
```

## Build Docker Image

```bash
gcloud auth configure-docker gcr.io # only needed once
docker build . -t gcr.io/arxiv-development/submit-ce/submit-ce-ui
docker push gcr.io/arxiv-development/submit-ce/submit-ce-ui
```

