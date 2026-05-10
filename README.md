# igp-ride

`igp-ride` is a minimal command-line tool for keeping IGPSPORT ride activities in a local SQLite database, downloading FIT files, and optionally uploading those FIT files to Intervals.icu.

## Requirements

- Python 3.14 or newer
- A working system keyring
- An IGPSPORT account
- An Intervals.icu API key if you want to upload activities to Intervals.icu

## Install

From a checked-out copy of this repository:

```bash
uv tool install .
```

For development:

```bash
uv sync
uv run igp-ride --help
```

The installed console command is:

```bash
igp-ride
```

## Basic Workflow

Log in to IGPSPORT:

```bash
igp-ride login
```

The command prompts for your username and password. Credentials are saved in the system keyring.

Sync rides and FIT files:

```bash
igp-ride update
```

List local rides:

```bash
igp-ride list
```

Show the newest ride:

```bash
igp-ride show last
```

Show one ride by IGPSPORT ride ID:

```bash
igp-ride show 123456
```

## Commands

### `login`

```bash
igp-ride login
```

Logs in to IGPSPORT and saves credentials/session data locally.

No options.

### `logout`

```bash
igp-ride logout
igp-ride logout --yes
```

Clears local IGPSPORT credentials and session data.

Without `--yes`, the command asks for confirmation and only continues when you type `LOGOUT`.

Options:

- `--yes`: skip confirmation.

### `reset`

```bash
igp-ride reset
igp-ride reset --yes
```

Deletes local `igp-ride` data, including the SQLite database, downloaded FIT files, IGPSPORT credentials, and session data.

Without `--yes`, the command asks for confirmation and only continues when you type `RESET`.

Options:

- `--yes`: skip confirmation.

### `update`

```bash
igp-ride update
igp-ride update --all
```

Fetches IGPSPORT activities, stores them in the local SQLite database, downloads FIT files, and repairs missing or invalid FIT files.

By default, `update` performs an incremental sync. Use `--all` to force a full activity refresh.

Options:

- `--all`: force a full update of all available activities.

### `list`

```bash
igp-ride list
igp-ride list --limit 10
igp-ride list --sort distance --desc
igp-ride list --sort power --asc --limit 10
```

Lists activities already stored in the local database. This command does not contact IGPSPORT.

Options:

- `--limit N`: show at most `N` activities.
- `--sort date|distance|time|speed|elev|power`: choose the sort field. Default is `date`.
- `--asc`: sort ascending.
- `--desc`: sort descending.

If neither `--asc` nor `--desc` is provided, output is descending.

### `show`

```bash
igp-ride show last
igp-ride show 123456
```

Shows details for one local activity. Use `last` for the newest local activity, or pass a ride ID.

This command does not contact IGPSPORT.

## Intervals.icu

### `icu login`

```bash
igp-ride icu login
igp-ride icu login --api-key YOUR_API_KEY
```

Saves an Intervals.icu API key. If `--api-key` is not provided, the command prompts securely.

Options:

- `--api-key API_KEY`: pass the API key non-interactively.

### `icu logout`

```bash
igp-ride icu logout
igp-ride icu logout --yes
```

Clears the saved Intervals.icu API key and local ICU config file. It does not delete local rides or ICU sync history stored in the local database.

Without `--yes`, the command asks for confirmation and only continues when you type `LOGOUT`.

Options:

- `--yes`: skip confirmation.

### `icu status`

```bash
igp-ride icu status
```

Shows whether an Intervals.icu API key is configured and checks whether the key can authenticate with Intervals.icu.

No options.

### `icu sync`

```bash
igp-ride icu sync --dry-run
igp-ride icu sync
```

Uploads local downloaded FIT files to Intervals.icu.

The sync uses `external_id=igp-<ride_id>` so repeated runs can detect activities that already exist remotely. Activities that failed in a previous run are retried by the next `igp-ride icu sync`.

Options:

- `--dry-run`: show what would be synced without uploading or changing local sync state.

## Configuration And Storage

`igp-ride` uses platform-specific user directories.

On macOS and Linux, defaults are:

- Config directory: `~/.config/igp-ride`
- Session file: `~/.config/igp-ride/session.json`
- ICU config file: `~/.config/igp-ride/icu.json`
- Data directory: `~/.local/share/igp-ride`
- SQLite database: `~/.local/share/igp-ride/rides.db`
- FIT directory: `~/.local/share/igp-ride/fit`
- Log file: `~/.local/share/igp-ride/logs/igp-ride.log`

On Windows, directories are resolved with `platformdirs`:

- Config directory: `%APPDATA%\igp-ride`
- Session file: `%APPDATA%\igp-ride\session.json`
- Session data file: `%APPDATA%\igp-ride\session_data.json`
- ICU config file: `%APPDATA%\igp-ride\icu.json`
- Data directory: `%LOCALAPPDATA%\igp-ride`
- SQLite database: `%LOCALAPPDATA%\igp-ride\rides.db`
- FIT directory: `%LOCALAPPDATA%\igp-ride\fit`

## Environment Variables

IGPSPORT:

- `IGP_USERNAME`: username used by commands that need IGPSPORT credentials.
- `IGP_PASSWORD`: password used by commands that need IGPSPORT credentials.

Intervals.icu:

- `IGP_RIDE_ICU_API_KEY`: Intervals.icu API key.
- `INTERVALS_ICU_API_KEY`: alternate Intervals.icu API key variable.
- `IGP_RIDE_ICU_ATHLETE_ID`: optional athlete ID override.
- `INTERVALS_ICU_ATHLETE_ID`: alternate athlete ID variable.
- `IGP_RIDE_ICU_BASE_URL`: optional Intervals.icu API base URL override.

The CLI does not expose athlete ID or base URL flags. The default Intervals.icu athlete is `0`, which means the API key's current athlete.

## Exit Codes

- `0`: success or cancelled confirmation.
- `2`: configuration or value error.
- `3`: IGPSPORT authentication error.
- `4`: network error.
- `5`: database error.
- `6`: data sync error.
- `7`: file error.
- `8`: requested activity was not found.
- `10`: reset completed with at least one deletion failure.

## Development Checks

```bash
uv run pytest
uv run ruff check
uv run basedpyright
```

## License

MIT
