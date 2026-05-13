# submit-ce API
arXiv paper submission system

## Install & use

To run the server, please execute the following from the root directory:

Configure:
In submit_ce/ui/config.py,
append your username to STORE_GS_PREFIX

Start the compiler api:
gcloud run services proxy tex2pdf-api-default --project arxiv-development --region us-central1 --port=9001


On linux:
```bash
# Install gcld3 dependencies needed by arxiv-base metadata checks
sudo apt-get install cmake libprotobuf-dev protobuf-compiler
uv sync

# this will give you an Authorization token, save that and use a browser extension
# like modheader to add Authorization=eyJhb...
uv run python submit_ce/make_test_db.py bootstrap_db

uv run flask --app submit_ce.ui.factory:create_web_app run -p 8000

google-chrome http://localhost:8000
```

On mac:
```bash
# You need a version of protobuf <= 21:
brew search protobuf
brew install protobuf@21

pyenv shell 3.11  # or similar
uv sync
source .venv/bin/activate

# this will give you an Authorization token, save that and use a browser extension
# like modheader to add Authorization=eyJhb...

python submit_ce/make_test_db.py bootstrap_db

uv run python local_dev.py
open http://localhost:8000
```

##  Run the tests

```bash
./test.sh
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

