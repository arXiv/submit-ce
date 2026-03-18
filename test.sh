#!/usr/bin/env bash

# all coverage settings configured in pyproject.toml
uv run pytest \
   submit_ce/api \
   submit_ce/implementations \
   submit_ce/ui
