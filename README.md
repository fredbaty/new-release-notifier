# new-release-notifier

Monitors your music library for new releases from artists you already own. Uses MusicBrainz to detect new albums/EPs/singles and sends notifications via ntfy.

## How it works

1. Syncs artist MusicBrainz IDs from your beets database
2. Queries MusicBrainz for recent releases from tracked artists
3. Stores new releases in a local SQLite database
4. Sends push notifications for releases not yet notified

## Requirements

- Python 3.12+
- A beets music library with MusicBrainz metadata
- ntfy topic for notifications
- (Optional) Health check service URL

## Configuration

Copy `sample_config.yml` to your config location and update paths:

```yaml
server_paths:
  releases_db: "/path/to/releases.db"

beets:
  database_path: "/path/to/beets/musiclibrary.db"
  enabled: true

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

## Installation

```bash
uv sync
```
