#!/bin/sh

set -eu

PART="${1:-patch}"

case "$PART" in
  patch|minor|major)
    ;;
  *)
    echo "Usage: scripts/bump_version.sh [patch|minor|major]" >&2
    exit 2
    ;;
esac

uv run bump-my-version bump "$PART"
uv sync --group dev
