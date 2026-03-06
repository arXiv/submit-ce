# submit-ce API
arXiv paper submission system

## Installation & Usage

To run the server, please execute the following from the root directory:

```bash
# Install gcld3 dependencies needed by arxiv-base metadata checks
sudo apt-get install cmake libprotobuf-dev protobuf-compiler
# mac notes: don't use a version greater than:
#   $ brew search protobuf
#   protobuf@21 ✔ (deprecated)

# this uses uv instead of pipenv or poetry
uv sync

# make sqlite dev db
python submit_ce/make_test_db.py bootstrap_db

# this will give you an Authorization token, save that and use a browser extension
# like modheader to add Authorization=eyJhb...

flask --app submit_ce.ui.factory:create_web_app run
# mac notes: pick another port if 5000 used for music:
#   flask --app submit_ce.ui.factory:create_web_app run -p 5000

google-chrome localhost:5000
open localhost:8001

```


## Build Docker Image

```bash
gcloud auth configure-docker gcr.io # only needed once
docker build . -t gcr.io/arxiv-development/submit-ce/submit-ce-ui
docker push gcr.io/arxiv-development/submit-ce/submit-ce-ui
```

## Tests

Test setup:
```
sudo apt-get install google-cloud-cli-pubsub-emulator

# mac notes: gcloud components install pubsub-emulator
```

See [emulator instructions](https://cloud.google.com/pubsub/docs/emulator) for other operating systems.

To run the tests:

```bash
pytest submit_ce
```
