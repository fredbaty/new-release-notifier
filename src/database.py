"""Database operations for the new release notifier."""

import sqlite3
import logging
from pathlib import Path

log = logging.getLogger(__name__)


class NotificationDatabase:
    """Simplified database for tracking ignored artists and notified releases."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        if db_path == ":memory:":
            self._conn = sqlite3.connect(db_path)
            self._conn.row_factory = sqlite3.Row
            self.init_database()
        else:
            self._conn = None
            self.init_database()

    def _get_connection(self):
        """Get a database connection."""
        if self._conn:
            return self._conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_database(self):
        """Initialize the database schema."""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ignored_artists (
                    mb_albumartistid TEXT PRIMARY KEY
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS releases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mb_releasegroupid TEXT UNIQUE NOT NULL,
                    artist_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    release_date TEXT,
                    release_type TEXT,
                    notified_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_releases_releasegroupid ON releases (mb_releasegroupid)"
            )

    def is_artist_ignored(self, mb_id: str) -> bool:
        """Check if an artist is in the ignored list."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM ignored_artists WHERE mb_albumartistid = ?",
                (mb_id,),
            )
            return cursor.fetchone() is not None

    def ignore_artist(self, mb_id: str):
        """Add an artist to the ignored list."""
        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO ignored_artists (mb_albumartistid) VALUES (?)",
                (mb_id,),
            )

    def unignore_artist(self, mb_id: str):
        """Remove an artist from the ignored list."""
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM ignored_artists WHERE mb_albumartistid = ?",
                (mb_id,),
            )

    def is_release_notified(self, mb_releasegroupid: str) -> bool:
        """Check if a release has already been notified."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM releases WHERE mb_releasegroupid = ?",
                (mb_releasegroupid,),
            )
            return cursor.fetchone() is not None

    def add_notified_release(
        self,
        mb_releasegroupid: str,
        artist_name: str,
        title: str,
        release_date: str | None,
        release_type: str | None,
    ):
        """Record a release as notified."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO releases
                (mb_releasegroupid, artist_name, title, release_date, release_type)
                VALUES (?, ?, ?, ?, ?)
                """,
                (mb_releasegroupid, artist_name, title, release_date, release_type),
            )

    def get_stats(self) -> dict:
        """Get database statistics."""
        with self._get_connection() as conn:
            stats = {}

            cursor = conn.execute("SELECT COUNT(*) FROM ignored_artists")
            stats["ignored_artists"] = cursor.fetchone()[0]

            cursor = conn.execute("SELECT COUNT(*) FROM releases")
            stats["notified_releases"] = cursor.fetchone()[0]

            return stats

    def get_ignored_artists(self) -> list[str]:
        """Get all ignored artist MB IDs."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT mb_albumartistid FROM ignored_artists")
            return [row[0] for row in cursor.fetchall()]
