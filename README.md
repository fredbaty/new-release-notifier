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
  topic: "your-ntfy-topic"
  token: "tk_yourtoken"

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
