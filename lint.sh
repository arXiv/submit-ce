#!/usr/bin/env bash
uv pip install ruff
uv run ruff check --output-format=github submit_ce
