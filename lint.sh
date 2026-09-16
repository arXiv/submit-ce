#!/usr/bin/env bash
# ruff is pinned in pyproject's dev dependency group, so `uv run` uses the
# locked version. Installing it ad hoc here would float to whatever is latest,
# and ruff's default rule set changes between releases.
uv run ruff check --output-format=github submit_ce
