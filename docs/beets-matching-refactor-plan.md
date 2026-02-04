# Beets-Based Artist Matching Refactor Plan

## Overview

This document outlines a comprehensive plan to refactor the artist matching logic to leverage beets' MusicBrainz integration, with the goal of **eliminating the existing API-based matching workflow entirely**.

---

## Current State Analysis

### releases.db (Application Database)

**Schema:**
```sql
artists (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    musicbrainz_id TEXT,
    ignore_releases BOOLEAN DEFAULT FALSE,
    last_checked DATETIME,
    check_count INTEGER DEFAULT 0,
    disambiguation_confidence TEXT,  -- 'high', 'medium', 'low', 'none'
    confidence_last_checked DATETIME,
    created_at DATETIME
)
```

**Statistics:**
| Metric | Count | Percentage |
|--------|-------|------------|
| Total artists | 915 | 100% |
| Artists with MB ID | 343 | 37% |
| Ignored artists | 527 | 58% |
| High confidence | 305 | 33% |
| Medium confidence | 13 | 1% |
| Low confidence | 9 | 1% |
| No confidence | 16 | 2% |
| NULL confidence | 572 | 63% |

### musiclibrary.db (Beets Database)

**Key tables:** `albums`, `items`

**Relevant fields in `albums` table:**
| Field | Description |
|-------|-------------|
| `albumartist` | Artist name |
| `album` | Album title |
| `mb_albumartistid` | MusicBrainz artist ID |
| `mb_albumartistids` | Multiple artist IDs (for collaborations) |
| `mb_albumid` | MusicBrainz release ID |
| `mb_releasegroupid` | MusicBrainz release group ID |

**Statistics:**
| Metric | Count | Percentage |
|--------|-------|------------|
| Total albums | 1,678 | 100% |
| Albums with `mb_albumartistid` | 722 | 43% |
| Albums with `mb_releasegroupid` | 724 | 43% |
| Unique album artists | 795 | 100% |
| Unique artists with MB ID | 446 | 56% |

### Cross-Database Comparison

| Metric | Count |
|--------|-------|
| Artists in both DBs with matching MB IDs | 135 |
| Artists in both DBs with mismatched MB IDs | 16 |
| Beets artists not in releases.db | 295 |

**Mismatched artists** (16 total) are primarily collaborations where the "primary" artist differs:
- `Ali Farka Touré & Ry Cooder`
- `Burial + Four Tet`
- `Sigur Rós` (case difference in UUID)
- etc.

---

## Current Matching Logic Problems

### Flow (main.py lines 47-132)

1. **New artist discovery:**
   - Scans directory structure for artist folders
   - For each new artist, calls `search_artist_with_disambiguation()`
   - Searches MusicBrainz API for candidates
   - Fetches **ALL release groups** for each candidate to calculate confidence

2. **Confidence validation:**
   - Daily check on existing artists
   - Calls `validate_artist_confidence()` which fetches **ALL release groups**
   - Re-runs disambiguation if confidence is low

### Why This Is Inefficient

For an artist like "The Beatles" with 800+ release groups:
- Current logic fetches ALL 800 release groups to match against 2 local albums
- 25 releases per page = 32+ API calls
- Rate limiting at 1 req/sec = **30+ seconds per artist**
- Repeated on every confidence check

---

## Proposed Solution: Full Beets Migration

### Goal
**Eliminate API-based artist matching entirely** by using beets to match all albums to MusicBrainz, then reading MB IDs directly from the beets database.

### Key Insight: mbsync vs import

Based on beets documentation:

- **`beet mbsync`** - Syncs metadata for albums that **already have** MusicBrainz IDs. It updates tags from MB but requires existing matches.
- **`beet import`** - Matches albums to MusicBrainz and can optionally write tags to files.

For albums without MB IDs (57% of library), we need to use `beet import` with careful configuration to:
1. Match albums to MusicBrainz
2. Store MB IDs in beets database
3. **NOT write tags to audio files** (using `--nowrite` flag or config)

### Beets Configuration for Safe Matching

```yaml
# beets config.yaml - Safe configuration for matching without modifying files
import:
    write: no       # Don't write tags to files
    copy: no        # Don't copy files
    move: no        # Don't move files
    autotag: yes    # Enable autotagging

# MusicBrainz settings
musicbrainz:
    searchlimit: 5  # Limit search results
```

### Command for matching without writing:
```bash
# Match a single album (test first)
beet import --nowrite --nocopy /path/to/artist/album

# Match all unmatched albums (after testing)
beet import --nowrite --nocopy /path/to/music/library
```

---

## Step-by-Step Implementation Plan

### Prerequisites
- [ ] Backup `musiclibrary.db` and `releases.db`
- [ ] Create feature branch: `git checkout -b feat/beets`

---

### Phase 1: Match Remaining Albums in Beets

**Goal:** Get MB IDs for the ~57% of albums currently without them.

#### Step 1.1: Update beets config for safe matching
```yaml
# ~/.config/beets/config.yaml
import:
    write: no
    copy: no
    move: no
```

#### Step 1.2: Test on a single artist
```bash
# Pick an artist without MB IDs (e.g., "A Winged Victory for the Sullen")
beet import --nowrite --nocopy "/Volumes/Samsung SSD/Music/A Winged Victory for the Sullen"

# Verify the match in beets
beet list albumartist:"A Winged Victory for the Sullen" -f '$albumartist - $album - $mb_albumartistid'
```

#### Step 1.3: Match remaining unmatched albums
```bash
# List albums without MB IDs
beet list mb_albumartistid::^$ -f '$albumartist - $album'

# Import remaining albums (interactive - you can skip uncertain matches)
beet import --nowrite --nocopy "/Volumes/Samsung SSD/Music"
```

#### Step 1.4: Verify coverage
```bash
# Check new coverage stats
beet stats
```

---

### Phase 2: Create BeetsReader Module

**New file:** `src/beets_reader.py`

```python
"""Read-only interface to beets musiclibrary.db"""

import sqlite3
import logging
from pathlib import Path

log = logging.getLogger(__name__)


class BeetsReader:
    """Read-only access to beets database for MusicBrainz IDs."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        if not Path(db_path).exists():
            raise FileNotFoundError(f"Beets database not found: {db_path}")

    def _get_connection(self):
        """Get a read-only database connection."""
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def get_artist_mb_id(self, artist_name: str) -> str | None:
        """Get MB artist ID by album artist name (case-insensitive)."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT DISTINCT mb_albumartistid
                FROM albums
                WHERE LOWER(albumartist) = LOWER(?)
                AND mb_albumartistid IS NOT NULL
                AND mb_albumartistid != ''
                LIMIT 1
                """,
                (artist_name,),
            )
            result = cursor.fetchone()
            return result[0] if result else None

    def get_all_artists_with_mb_ids(self) -> dict[str, str]:
        """Return {artist_name: mb_id} for all artists with MB IDs."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT DISTINCT albumartist, mb_albumartistid
                FROM albums
                WHERE mb_albumartistid IS NOT NULL
                AND mb_albumartistid != ''
                """
            )
            return {row["albumartist"]: row["mb_albumartistid"] for row in cursor}

    def get_all_artists(self) -> set[str]:
        """Return set of all artist names in beets."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT DISTINCT albumartist FROM albums")
            return {row[0] for row in cursor}

    def get_albums_for_artist(self, artist_name: str) -> list[dict]:
        """Get album details including MB release group IDs."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT album, mb_releasegroupid, mb_albumid, year
                FROM albums
                WHERE albumartist = ?
                """,
                (artist_name,),
            )
            return [dict(row) for row in cursor]

    def get_coverage_stats(self) -> dict:
        """Get statistics about MB ID coverage."""
        with self._get_connection() as conn:
            stats = {}

            cursor = conn.execute("SELECT COUNT(*) FROM albums")
            stats["total_albums"] = cursor.fetchone()[0]

            cursor = conn.execute(
                """SELECT COUNT(*) FROM albums
                   WHERE mb_albumartistid IS NOT NULL AND mb_albumartistid != ''"""
            )
            stats["albums_with_mb_id"] = cursor.fetchone()[0]

            cursor = conn.execute("SELECT COUNT(DISTINCT albumartist) FROM albums")
            stats["total_artists"] = cursor.fetchone()[0]

            cursor = conn.execute(
                """SELECT COUNT(DISTINCT albumartist) FROM albums
                   WHERE mb_albumartistid IS NOT NULL AND mb_albumartistid != ''"""
            )
            stats["artists_with_mb_id"] = cursor.fetchone()[0]

            stats["coverage_pct"] = round(
                100 * stats["artists_with_mb_id"] / stats["total_artists"], 1
            )

            return stats
```

---

### Phase 3: Add Configuration

**Modify:** `src/sample_config.py`

```python
class BeetsConfig(BaseModel):
    """Beets integration configuration."""

    database_path: str = ""  # Path to musiclibrary.db
    enabled: bool = True


class AppConfig(BaseModel):
    """Application configuration settings."""

    server_paths: ServerPaths = ServerPaths()
    musicbrainz: MusicBrainzConfig = MusicBrainzConfig()
    detection_params: DetectionParams = DetectionParams()
    beets: BeetsConfig = BeetsConfig()  # ADD THIS
    ntfy: NtfyConfig = NtfyConfig()
    health_check: HealthCheckConfig = HealthCheckConfig()
```

**Remove from AppConfig:**
- `disambiguation_params: DisambiguationParams` - No longer needed

---

### Phase 4: Simplify Database Schema

**Modify:** `src/database.py`

Remove fields that are no longer needed:
- `disambiguation_confidence`
- `confidence_last_checked`

Add new field:
- `mb_id_source` - Track where MB ID came from ("beets" or legacy)

```python
def init_database(self):
    """Initialize the database schema."""
    with self.get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS artists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                musicbrainz_id TEXT,
                ignore_releases BOOLEAN DEFAULT FALSE,
                last_checked DATETIME,
                check_count INTEGER DEFAULT 0,
                mb_id_source TEXT,  -- 'beets' or NULL for legacy
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # ... releases table unchanged ...
```

Add migration for existing databases:
```python
def _migrate_schema(self):
    """Add mb_id_source column if missing."""
    with self.get_connection() as conn:
        try:
            conn.execute("ALTER TABLE artists ADD COLUMN mb_id_source TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
```

Add new methods:
```python
def get_artist_by_name(self, name: str) -> dict | None:
    """Get artist by name."""
    with self.get_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM artists WHERE name = ?", (name,)
        )
        row = cursor.fetchone()
        if row:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        return None

def sync_from_beets(self, artist_name: str, mb_id: str):
    """Update or insert artist with beets MB ID."""
    with self.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO artists (name, musicbrainz_id, mb_id_source)
            VALUES (?, ?, 'beets')
            ON CONFLICT(name) DO UPDATE SET
                musicbrainz_id = excluded.musicbrainz_id,
                mb_id_source = 'beets'
            """,
            (artist_name, mb_id),
        )
```

---

### Phase 5: Refactor Main Application

**Rewrite:** `main.py`

The new flow is dramatically simpler:

```python
"""Main entry point for the new release notifier."""

import logging
import typer

from src.beets_reader import BeetsReader
from src.config import load_config
from src.database import Database
from src.log_config import basic_config
from src.musicbrainz import MusicBrainzClient
from src.notifications import NotificationClient, HealthCheck

app = typer.Typer()


def sync_artists_from_beets(db: Database, beets: BeetsReader) -> int:
    """Sync all artists with MB IDs from beets to releases.db."""
    beets_artists = beets.get_all_artists_with_mb_ids()
    synced = 0

    for artist_name, mb_id in beets_artists.items():
        existing = db.get_artist_by_name(artist_name)

        # Skip if already synced from beets with same ID
        if existing and existing.get("mb_id_source") == "beets":
            if existing.get("musicbrainz_id") == mb_id:
                continue

        db.sync_from_beets(artist_name, mb_id)
        synced += 1

    return synced


@app.command()
def main(
    config_path: str = typer.Option("data/app_config.yml", "--config"),
    verbose: bool = typer.Option(False, "--verbose"),
    artist: str = typer.Option(None, "--artist", help="Test with single artist"),
):
    """Main entry point for the new release notifier."""
    basic_config(verbose)
    log = logging.getLogger(__name__)

    log.info("+-+-+-+-+-START-NEW_RELEASE_NOTIFIER-+-+-+-+-+")
    config = load_config(config_path)

    health_check = HealthCheck(config.health_check)
    health_check.ping_start()

    try:
        # Initialize components
        db = Database(config.server_paths.database)
        beets = BeetsReader(config.beets.database_path)
        mb_client = MusicBrainzClient(config.musicbrainz)
        notifier = NotificationClient(config.ntfy)

        # Log beets coverage
        stats = beets.get_coverage_stats()
        log.info(f"Beets coverage: {stats['artists_with_mb_id']}/{stats['total_artists']} artists ({stats['coverage_pct']}%)")

        # Step 1: Sync artists from beets
        log.info("Syncing artists from beets database...")
        synced = sync_artists_from_beets(db, beets)
        log.info(f"Synced {synced} artists from beets")

        # Step 2: Get artists to check for new releases
        if artist:
            # Single artist mode for testing
            artists_to_check = [db.get_artist_by_name(artist)]
            if not artists_to_check[0]:
                log.error(f"Artist not found: {artist}")
                return
        else:
            artists_to_check = db.get_artists_for_checking(
                config.detection_params.daily_check_limit
            )

        if not artists_to_check:
            log.info("No artists to check today")
            health_check.ping(success=True)
            return

        log.info(f"Checking {len(artists_to_check)} artists for new releases")

        # Step 3: Check each artist for new releases
        all_new_releases = []

        for artist_data in artists_to_check:
            if not artist_data:
                continue

            artist_id = artist_data["id"]
            artist_name = artist_data["name"]
            mb_id = artist_data["musicbrainz_id"]

            if not mb_id:
                log.warning(f"No MB ID for {artist_name} - skipping")
                continue

            log.info(f"Checking releases for: {artist_name}")

            try:
                releases = mb_client.get_recent_releases(
                    mb_id, config.detection_params.release_window_days
                )

                for release in releases:
                    is_new = db.add_release(
                        artist_id=artist_id,
                        musicbrainz_id=release["id"],
                        title=release["title"],
                        release_date=release["first_release_date"],
                        release_type=release["type"],
                    )

                    if is_new:
                        log.info(f"New release: {artist_name} - {release['title']}")
                        all_new_releases.append(release)

                db.update_artist_check(artist_id)

            except Exception as e:
                log.error(f"Error checking {artist_name}: {e}")
                db.update_artist_check(artist_id)

        # Step 4: Send notifications
        unnotified = db.get_unnotified_releases()
        for release in unnotified:
            notifier.send_release_notification(
                artist_name=release["artist_name"],
                title=release["title"],
                release_date=release["release_date"],
                release_type=release["release_type"],
            )
            db.mark_release_notified(release["id"])

        log.info(f"Done. New releases: {len(all_new_releases)}, Notifications: {len(unnotified)}")
        health_check.ping(success=True)

    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
        health_check.ping(success=False)

    finally:
        log.info("+-+-+-+-+-END-NEW_RELEASE_NOTIFIER-+-+-+-+-+")


if __name__ == "__main__":
    app()
```

---

### Phase 6: Simplify MusicBrainz Client

**Modify:** `src/musicbrainz.py`

Remove:
- `search_artist()` - No longer needed
- `search_artist_with_disambiguation()` - No longer needed
- `validate_artist_confidence()` - No longer needed
- All disambiguation-related code

Keep only:
- `get_release_groups()` - For fetching new releases
- `get_recent_releases()` - Wrapper with date filtering
- Rate limiting and retry logic

```python
"""MusicBrainz API client - simplified for release fetching only."""

import musicbrainzngs
import time
import logging
from datetime import datetime, timedelta

from src.config import MusicBrainzConfig

log = logging.getLogger(__name__)


class MusicBrainzClient:
    """Simplified client for fetching release groups only."""

    def __init__(self, config: MusicBrainzConfig = MusicBrainzConfig()):
        musicbrainzngs.set_useragent(
            app=config.user_agent,
            version=config.version,
            contact=config.contact,
        )
        self.rate_limit_delay = config.rate_limit_delay
        self.last_request_time = 0
        self.included_release_types = config.included_release_types
        self.excluded_release_types = config.excluded_release_types

    def _rate_limit(self):
        """Ensure we don't exceed MusicBrainz rate limit."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self.last_request_time = time.time()

    def get_recent_releases(self, artist_id: str, days_back: int = 30) -> list[dict]:
        """Get releases from the last N days."""
        cutoff = datetime.now() - timedelta(days=days_back)
        return self._get_release_groups(artist_id, since_date=cutoff)

    def _get_release_groups(
        self, artist_id: str, since_date: datetime | None = None
    ) -> list[dict]:
        """Fetch release groups for an artist."""
        results = []
        offset = 0

        while True:
            self._rate_limit()

            try:
                response = musicbrainzngs.browse_release_groups(
                    artist=artist_id, offset=offset, limit=25
                )
            except Exception as e:
                log.error(f"Error fetching releases for {artist_id}: {e}")
                break

            for rg in response.get("release-group-list", []):
                # Skip if no release date
                date_str = rg.get("first-release-date")
                if not date_str:
                    continue

                # Parse date
                release_date = self._parse_date(date_str)
                if not release_date:
                    continue

                # Filter by date
                if since_date and release_date < since_date:
                    continue

                # Filter by type
                release_type = rg.get("type", "")
                if self.excluded_release_types and release_type in self.excluded_release_types:
                    continue
                if self.included_release_types and release_type not in self.included_release_types:
                    continue

                results.append({
                    "id": rg["id"],
                    "title": rg["title"],
                    "type": release_type,
                    "first_release_date": date_str,
                })

            if len(response.get("release-group-list", [])) < 25:
                break
            offset += 25

        return results

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        """Parse MusicBrainz date formats."""
        for fmt in ["%Y-%m-%d", "%Y-%m", "%Y"]:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None
```

---

### Phase 7: Delete Obsolete Code

**Delete files:**
- `src/disambiguation.py` - No longer needed
- `src/scheduler.py` - Functionality moved to database.py

**Remove from `src/sample_config.py`:**
- `DisambiguationParams` class

---

### Phase 8: Add Single-Artist Test Mode

Already included in Phase 5 main.py with `--artist` flag:

```bash
# Test the pipeline with a single artist
python main.py --artist "Radiohead" --verbose

# Test with an artist that has recent releases
python main.py --artist "Taylor Swift" --verbose
```

---

## Files Summary

| File | Action | Description |
|------|--------|-------------|
| `src/beets_reader.py` | **CREATE** | Read-only beets database interface |
| `src/sample_config.py` | **MODIFY** | Add BeetsConfig, remove DisambiguationParams |
| `src/database.py` | **MODIFY** | Simplify schema, add beets sync methods |
| `main.py` | **REWRITE** | Simplified flow using beets |
| `src/musicbrainz.py` | **SIMPLIFY** | Keep only release fetching |
| `src/disambiguation.py` | **DELETE** | No longer needed |
| `src/scheduler.py` | **DELETE** | Functionality absorbed elsewhere |
| `src/scanner.py` | **KEEP** | Still used for directory scanning |

---

## Testing Checklist

### Phase 1 Testing (Beets Matching)
- [ ] Backup databases before any changes
- [ ] Test `beet import --nowrite` on single album
- [ ] Verify audio file tags unchanged after import
- [ ] Verify beets DB contains new MB IDs
- [ ] Run full import on remaining albums
- [ ] Check coverage stats improved

### Phase 2-7 Testing (Code Refactor)
- [ ] BeetsReader reads MB IDs correctly
- [ ] Single artist mode (`--artist`) works
- [ ] Beets sync populates releases.db
- [ ] Release checking still works
- [ ] Notifications still work
- [ ] ignore_releases still respected
- [ ] No writes to beets database

### End-to-End Test
```bash
# Full test sequence
python main.py --artist "Radiohead" --verbose  # Single artist
python main.py --verbose                        # Full run
```

---

## Verification Commands

```bash
# Check beets coverage before/after
beet stats

# List albums without MB IDs
beet list mb_albumartistid::^$ -f '$albumartist - $album'

# Verify specific artist has MB ID
beet list albumartist:"Radiohead" -f '$albumartist - $mb_albumartistid'

# Check releases.db after sync
sqlite3 releases.db "SELECT name, musicbrainz_id, mb_id_source FROM artists LIMIT 10"
```

---

## Rollback Plan

If issues arise:
1. Restore `musiclibrary.db` from backup
2. Restore `releases.db` from backup
3. `git checkout main` to return to original code

---

## Summary

This refactor:
1. **Eliminates** the slow, unreliable API-based artist matching
2. **Leverages** beets' proven MusicBrainz matching
3. **Preserves** audio file tags (no writes)
4. **Simplifies** the codebase significantly
5. **Provides** single-artist testing capability

The key prerequisite is running `beet import --nowrite` to match the remaining 57% of albums to MusicBrainz, giving us near-complete coverage of artist MB IDs.

---

*Document created: 2026-02-04*
*Based on analysis of musiclibrary.db (1,678 albums, 446 artists with MB IDs) and releases.db (915 artists, 343 with MB IDs)*
