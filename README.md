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

# Change LOCAL_LOGIN_USER_ID in local_dev.py, as needed.

# submit-ui:
uv run python local_ui.py
open http://localhost:8000/debug/login

# sword-api:
uv run python local_sword.py
open http://localhost:8001/status
```

##  Run the tests

```bash
./test.sh
```

##  Test pubsub

```bash
# Edit local_ui.py:
#   Set QA_PUBSUB_ENABLED to True

# Run the emulator:
gcloud beta emulators pubsub start --project=arxiv-development

# Echo messages sent to emulator:
uv run python local_subscriber.py
```

##  Test sword

- Also see: [sword-getting-started](docs/sword-getting-started.md)

```
# Run regression tests:
cd arxiv-test-regression/pytest
pyenv shell 3.11.11
python -m venv venv
cp envfile.example envfile
pip install requests pytest pydantic_settings
services_env=local pytest --run-loggedin --run-readwrite tests/test_sword.py
```

## Build Docker Image

```bash
gcloud auth configure-docker gcr.io # only needed once
docker build . -t gcr.io/arxiv-development/submit-ce/submit-ce-ui
docker push gcr.io/arxiv-development/submit-ce/submit-ce-ui
```
