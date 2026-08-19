# submit-ce API
arXiv paper submission system

## Install & use

```bash
# On linux, Install gcld3 dependencies needed by arxiv-base metadata checks
sudo apt-get install cmake libprotobuf-dev protobuf-compiler

# On mac, you need a version of protobuf <= 21
brew install protobuf@21

# For service account use, to use buckets.
gcloud auth application-default login

pyenv shell 3.11  # or similar
source .venv/bin/activate
uv sync

# Bootstrap the local test DB (also creates test users):
uv run python submit_ce/make_test_db.py bootstrap_db

uv run python local_ui.py
open http://localhost:8000
```

##  Run the tests

```bash
./test.sh
```

##  Test pubsub

```bash
# Edit local_ui.py:
#   Set QA_PUBSUB_ENABLED to True

# shell 1, to run the emulator:
gcloud beta emulators pubsub start --project=arxiv-development

# shell 2 optional, to echo messages:
uv run python local_subscriber.py
```


## Build Docker Image

```bash
gcloud auth configure-docker gcr.io # only needed once
docker build . -t gcr.io/arxiv-development/submit-ce/submit-ce-ui
docker push gcr.io/arxiv-development/submit-ce/submit-ce-ui
```
