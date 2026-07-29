# new-release-notifier

Monitors your music library for new releases from artists you already own. Uses MusicBrainz to detect new albums/EPs/singles and sends notifications via ntfy.

## How it works

1. Reads all artists with MusicBrainz IDs from your beets database
2. Filters out any ignored artists
3. Queries MusicBrainz for recent releases from each artist
4. Sends push notifications for new releases not previously notified
5. Records notified releases to prevent duplicates

## Requirements

- Python 3.12+
- A beets music library with MusicBrainz metadata
- ntfy topic for notifications
- (Optional) Health check service URL

## Configuration

Copy `sample_config.yml` to your config location and update paths:

```yaml
databases:
  beets_db: "/path/to/beets/musiclibrary.db"
  notifications_db: "/path/to/notifications.db"

ntfy:
  base_url: "https://ntfy.sh"   # Server root, no topic, no trailing slash
  topic: "your-ntfy-topic"      # Topic name only
  token: "tk_yourtoken"         # Sent as "Bearer <token>"; omit the prefix here

health_check:
  url: "https://hc-ping.com/your-uuid"

musicbrainz:
  contact: "your-email@example.com"
```

## Usage

```bash
# Run with default config path
python main.py

# Specify config file
python main.py --config /path/to/config.yml

# Test with a single artist
python main.py --artist "Artist Name"

# Enable debug logging
python main.py --verbose
```

## Managing ignored artists

Use `update_db.py` to ignore artists you don't want release notifications for:

```bash
# Ignore artists matching search terms
python update_db.py ignore "the beatles" "rolling stones"

# Unignore an artist
python update_db.py unignore "the beatles"

# List all ignored artists
python update_db.py list-ignored

# Skip confirmation prompt
python update_db.py ignore "various artists" -y
```

## Installation

```bash
uv sync
```

## Docker

The image mounts its config rather than baking it in, so it holds no secrets:

```bash
docker build -t new-release-notifier .

docker run --rm \
  --user 1001:1001 \
  -v /path/to/musiclibrary.db:/music/musiclibrary.db:ro \
  -v /path/to/data:/data \
  -v /path/to/config.yml:/config/config.yml:ro \
  new-release-notifier
```

The beets database is opened read-only, so a `:ro` mount is safe. Other commands
run by overriding the default, e.g.:

```bash
docker run --rm ... new-release-notifier python update_db.py list-ignored
```
