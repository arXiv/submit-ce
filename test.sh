#!/usr/bin/env bash

# all coverage settings configured in pyproject.toml
uv run pytest \
   --cov=submit_ce \
   --ignore=submit_ce/implementations/pubsub \
   submit_ce/api \
   submit_ce/implementations \
   submit_ce/domain \
   submit_ce/ui
