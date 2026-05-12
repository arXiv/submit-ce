# submit-ce API
arXiv paper submission system

## Install & use

```bash
# Start the compiler api:
gcloud run services proxy tex2pdf-api-default --project arxiv-development --region us-central1 --port=9001

# Install gcld3 dependencies needed by arxiv-base metadata checks
#   On linux:
sudo apt-get install cmake libprotobuf-dev protobuf-compiler
uv sync
#   On mac, you need a version of protobuf <= 21:
brew search protobuf
brew install protobuf@21

pyenv shell 3.11  # or similar
source .venv/bin/activate
uv sync

# this will give you an Authorization token, save that and use a browser extension
# like modheader to add Authorization=eyJhb...
uv run python submit_ce/make_test_db.py bootstrap_db

uv run python local_dev.py
open http://localhost:8000
```

##  Run the tests

```bash
./test.sh
```

## Build Docker Image

```bash
gcloud auth configure-docker gcr.io # only needed once
docker build . -t gcr.io/arxiv-development/submit-ce/submit-ce-ui
docker push gcr.io/arxiv-development/submit-ce/submit-ce-ui
```