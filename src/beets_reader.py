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
                GROUP BY mb_albumartistid
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

            if stats["total_artists"] > 0:
                stats["coverage_pct"] = round(
                    100 * stats["artists_with_mb_id"] / stats["total_artists"], 1
                )
            else:
                stats["coverage_pct"] = 0.0

            return stats
