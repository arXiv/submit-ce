# submit-ce API
arXiv paper submission system

## Install & use

```bash
# On linux, Install gcld3 dependencies needed by arxiv-base metadata checks
sudo apt-get install cmake libprotobuf-dev protobuf-compiler

# On mac, you need a version of protobuf <= 21
brew install protobuf@21

pyenv shell 3.11  # or similar
source .venv/bin/activate
uv sync

# Generate an Authorization token:
uv run python submit_ce/make_test_db.py bootstrap_db

# Use a browser extension like modheader to send the token for localhost
#   add Authorization=eyJhb...

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
