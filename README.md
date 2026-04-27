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

uv sync

uv run python submit_ce/make_test_db.py bootstrap_db
# this will give you an Authorization token, save that and use a browser extension
# like modheader to add Authorization=eyJhb...

uv run flask --app submit_ce.ui.factory:create_web_app run -p 8000
open http://localhost:8000
# mac notes: pick another port if 5000 used for music:
#   uv run flask --app submit_ce.ui.factory:create_web_app run -p 5000

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
uv run flask --app submit_ce.ui.factory:create_web_app run -p 8000
open http://localhost:8000
```

## Running with the GCS emulator (fsouza/fake-gcs-server)

Use this instead of real Google Cloud Storage for local development.

**1. Start the emulator**
```bash
docker run -d --rm --name fake-gcs -p 4443:4443 \
  fsouza/fake-gcs-server -scheme http -port 4443
```

**2. Create a bucket**
```bash
curl -X POST "http://localhost:4443/storage/v1/b?project=local" \
  -H "Content-Type: application/json" \
  -d '{"name": "submit-local"}'
```

**3. Bootstrap the test DB** (if not done already)
```bash
uv run python submit_ce/make_test_db.py bootstrap_db
```

**4. Run the Flask app**
```bash
STORE=gs \
STORE_GS_BUCKET=submit-local \
STORE_GS_PREFIX=data/new \
STORAGE_EMULATOR_HOST=http://localhost:4443 \
GCLOUD_PROJECT=local \
uv run flask --app submit_ce.ui.factory:create_web_app run -p 8000
```

`STORAGE_EMULATOR_HOST` causes the Google Cloud Storage Python client to route all requests to the local emulator instead of GCS. `GCLOUD_PROJECT` can be any string when using the emulator.

To stop the emulator: `docker stop fake-gcs`

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
