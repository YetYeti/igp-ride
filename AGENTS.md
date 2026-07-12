# Agent Guide

This repository contains `igp-ride`, a Python CLI for syncing IGPSPORT ride
activities to a local SQLite database, downloading FIT files, and optionally
uploading FIT files to Intervals.icu.

## Quick Context

- Package source: `src/igp_ride/`
- CLI entry point: `igp_ride.cli:main`
- User-facing command: `igp-ride`
- Codex/OpenClaw skill: `skills/igp-ride-cli/SKILL.md`
- Tests: `tests/`

Runtime data is not stored in the repository. By default it lives under the
platform user config/data directories, such as `~/.config/igp-ride` and
`~/.local/share/igp-ride` on macOS/Linux.

## Development Commands

Set up the project:

```bash
uv sync
```

Run the CLI from the workspace:

```bash
uv run igp-ride --help
uv run igp-ride --version
```

Run checks:

```bash
uv run ruff check src tests
uv run basedpyright
uv run pytest
```

Format Python files:

```bash
uv run ruff format src tests
```

## Agent Operating Notes

- Prefer local read-only commands first: `igp-ride list`, `igp-ride show last`,
  and `igp-ride icu status`.
- `igp-ride list` and `igp-ride show` only read the local SQLite database and do
  not contact IGPSPORT.
- `igp-ride update` contacts IGPSPORT, writes the local database, and downloads
  FIT files.
- `igp-ride icu sync --dry-run` previews Intervals.icu uploads without changing
  local sync state or uploading files.
- `igp-ride icu sync` uploads local FIT files to Intervals.icu.
- Do not run `igp-ride reset`, `igp-ride logout`, or `igp-ride icu logout`
  unless the user explicitly asks for that destructive or clearing action.
- When a command fails, use the documented exit code first, then inspect the
  printed `Error:` and `Tip:` lines.

## Non-Interactive Usage

Use flags or environment variables when a command would otherwise prompt:

```bash
IGP_USERNAME="..." IGP_PASSWORD="..." uv run igp-ride update
uv run igp-ride icu login --api-key "..."
uv run igp-ride logout --yes
uv run igp-ride icu logout --yes
uv run igp-ride reset --yes
```

Only use `--yes` after the user has confirmed the operation.

## Output Contract

The CLI intentionally prints stable plain text:

- Section headers look like `== Update ==`.
- Status lines use `Label: value`.
- Summaries use `Summary: key=value key=value`.
- Errors print to stderr as `Error: ...`, usually with a `Tip: ...`.
- Non-TTY progress is line-oriented and throttled.

Structured output is available via `--format json` (stdout carries a single JSON
payload; progress and logs go to stderr). Extend the contract in
`tests/test_cli.py` when changing the JSON shape.
