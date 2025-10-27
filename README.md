# submit-ce API
arXiv paper submission system

## Installation & Usage

To run the server, please execute the following from the root directory:

```bash
# setup venv in your preferred way
python --version
# 3.11

# this uses uv instead of pipenv or poetry
# see https://docs.astral.sh/uv/
uv venv
uv sync

# make sqlite dev db
python submit_ce/make_test_db.py bootstrap_db

# this will give you an Authorization token, save that and use a browser extension
# like modheader to add Authorization=eyJhb...

flask --app submit_ce.ui.factory:create_web_app run

google-chrome localhost:5000
```


## Build Docker Image

```bash
gcloud auth configure-docker gcr.io # only needed once
docker build . -t gcr.io/arxiv-development/submit-ce/submit-ce-ui
docker push gcr.io/arxiv-development/submit-ce/submit-ce-ui
```

## Tests

Test setup for Ubuntu:
```
sudo apt-get install google-cloud-cli-pubsub-emulator
```

See [emulator instructions](https://cloud.google.com/pubsub/docs/emulator) for other operating systems.

To run the tests:

```bash
pytest submit_ce
```
