"""Database operations for the new release notifier."""

import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        # Ensure the directory exists (except for in-memory databases)
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # For in-memory databases, we need to keep a persistent connection
        if db_path == ":memory:":
            self._conn = sqlite3.connect(db_path)
            self._conn.execute("PRAGMA foreign_keys = ON")
            self.init_database()
        else:
            self._conn = None
            self.init_database()

    def get_connection(self):
        """Get a database connection with foreign key support."""
        if self._conn:
            return self._conn
        else:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA foreign_keys = ON")
            return conn

    def init_database(self):
        """Initialize the database schema."""
        with self.get_connection() as conn:
            # Artists table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS artists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    musicbrainz_id TEXT,
                    ignore_releases BOOLEAN DEFAULT FALSE,
                    last_checked DATETIME,
                    check_count INTEGER DEFAULT 0,
                    disambiguation_confidence TEXT,
                    confidence_last_checked DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Releases table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS releases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    artist_id INTEGER,
                    musicbrainz_id TEXT UNIQUE,
                    title TEXT NOT NULL,
                    release_date TEXT,
                    release_type TEXT,
                    notified BOOLEAN DEFAULT FALSE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (artist_id) REFERENCES artists (id)
                )
            """
            )

            # Create indexes for better performance
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_artists_ignore ON artists (ignore_releases)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_artists_last_checked ON artists (last_checked)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_releases_artist_id ON releases (artist_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_releases_notified ON releases (notified)"
            )

    def migrate_from_csv(self, csv_path: str):
        """Migrate data from the legacy CSV file."""
        if not Path(csv_path).exists():
            logger.warning(f"CSV file not found: {csv_path}")
            return

        try:
            df = pd.read_csv(csv_path, encoding="utf-8")
            logger.info(f"Migrating {len(df)} artists from CSV")

            with self.get_connection() as conn:
                for _, row in df.iterrows():
                    artist_name = row["artist"]
                    musicbrainz_id = (
                        row["artist_id"] if pd.notna(row["artist_id"]) else None
                    )
                    ignore_releases = row["ignore"] == "y"

                    # Insert or update artist
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO artists (name, musicbrainz_id, ignore_releases)
                        VALUES (?, ?, ?)
                    """,
                        (artist_name, musicbrainz_id, ignore_releases),
                    )

            logger.info("CSV migration completed successfully")

        except Exception as e:
            logger.error(f"Error migrating from CSV: {e}")
            raise

    def add_artist(
        self,
        name: str,
        musicbrainz_id: Optional[str] = None,
        ignore_releases: bool = False,
    ) -> int:
        """Add a new artist and return their ID."""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO artists (name, musicbrainz_id, ignore_releases)
                VALUES (?, ?, ?)
            """,
                (name, musicbrainz_id, ignore_releases),
            )

            if cursor.rowcount == 0:
                # Artist already exists, get their ID
                cursor = conn.execute("SELECT id FROM artists WHERE name = ?", (name,))
                return cursor.fetchone()[0]

            return cursor.lastrowid or 0

    def get_artists_for_checking(self, limit: int) -> List[Dict]:
        """Get artists that need to be checked, prioritizing least recently checked."""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, name, musicbrainz_id, last_checked, check_count
                FROM artists 
                WHERE ignore_releases = FALSE 
                AND musicbrainz_id IS NOT NULL
                ORDER BY 
                    CASE WHEN last_checked IS NULL THEN 0 ELSE 1 END,
                    last_checked ASC
                LIMIT ?
            """,
                (limit,),
            )

            columns = ["id", "name", "musicbrainz_id", "last_checked", "check_count"]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def update_artist_check(self, artist_id: int):
        """Update the last checked timestamp and increment check count."""
        with self.get_connection() as conn:
            conn.execute(
                """
                UPDATE artists 
                SET last_checked = CURRENT_TIMESTAMP, check_count = check_count + 1
                WHERE id = ?
            """,
                (artist_id,),
            )

    def add_release(
        self,
        artist_id: int,
        musicbrainz_id: str,
        title: str,
        release_date: str,
        release_type: Optional[str] = None,
    ) -> bool:
        """Add a new release. Returns True if it's a new release, False if duplicate."""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO releases 
                (artist_id, musicbrainz_id, title, release_date, release_type)
                VALUES (?, ?, ?, ?, ?)
            """,
                (artist_id, musicbrainz_id, title, release_date, release_type),
            )

            return cursor.rowcount > 0

    def get_unnotified_releases(self) -> List[Dict]:
        """Get releases that haven't been notified yet."""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT r.id, a.name as artist_name, r.title, r.release_date, r.release_type
                FROM releases r
                JOIN artists a ON r.artist_id = a.id
                WHERE r.notified = FALSE
                ORDER BY r.release_date DESC
            """
            )

            columns = ["id", "artist_name", "title", "release_date", "release_type"]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def mark_release_notified(self, release_id: int):
        """Mark a release as notified."""
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE releases SET notified = TRUE WHERE id = ?", (release_id,)
            )

    def get_all_artists(self) -> List[str]:
        """Get all artist names in the database."""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT name FROM artists")
            return [row[0] for row in cursor.fetchall()]

    def update_artist_musicbrainz_id(self, name: str, musicbrainz_id: str):
        """Update an artist's MusicBrainz ID."""
        with self.get_connection() as conn:
            conn.execute(
                """
                UPDATE artists SET musicbrainz_id = ? WHERE name = ?
            """,
                (musicbrainz_id, name),
            )

    def get_stats(self) -> Dict:
        """Get database statistics."""
        with self.get_connection() as conn:
            stats = {}

            # Total artists
            cursor = conn.execute("SELECT COUNT(*) FROM artists")
            stats["total_artists"] = cursor.fetchone()[0]

            # Active artists (not ignored)
            cursor = conn.execute(
                "SELECT COUNT(*) FROM artists WHERE ignore_releases = FALSE"
            )
            stats["active_artists"] = cursor.fetchone()[0]

            # Artists with MusicBrainz IDs
            cursor = conn.execute(
                "SELECT COUNT(*) FROM artists WHERE musicbrainz_id IS NOT NULL"
            )
            stats["artists_with_mb_id"] = cursor.fetchone()[0]

            # Total releases
            cursor = conn.execute("SELECT COUNT(*) FROM releases")
            stats["total_releases"] = cursor.fetchone()[0]

            # Unnotified releases
            cursor = conn.execute(
                "SELECT COUNT(*) FROM releases WHERE notified = FALSE"
            )
            stats["unnotified_releases"] = cursor.fetchone()[0]

            return stats

    def update_artist_confidence(
        self,
        artist_id: int,
        confidence_level: str,
        musicbrainz_id: Optional[str] = None,
    ):
        """Update an artist's disambiguation confidence and optionally their MusicBrainz ID."""
        with self.get_connection() as conn:
            if musicbrainz_id is not None:
                conn.execute(
                    """
                    UPDATE artists 
                    SET disambiguation_confidence = ?, 
                        confidence_last_checked = CURRENT_TIMESTAMP,
                        musicbrainz_id = ?
                    WHERE id = ?
                """,
                    (confidence_level, musicbrainz_id, artist_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE artists 
                    SET disambiguation_confidence = ?, 
                        confidence_last_checked = CURRENT_TIMESTAMP
                    WHERE id = ?
                """,
                    (confidence_level, artist_id),
                )

    def get_artists_for_confidence_check(self, limit: int) -> List[Dict]:
        """Get artists that need confidence validation."""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, name, musicbrainz_id, disambiguation_confidence, confidence_last_checked
                FROM artists 
                WHERE ignore_releases = FALSE 
                AND musicbrainz_id IS NOT NULL
                ORDER BY 
                    CASE 
                        WHEN confidence_last_checked IS NULL THEN 0
                        WHEN disambiguation_confidence IN ('low', 'none') THEN 1
                        ELSE 2
                    END,
                    confidence_last_checked ASC
                LIMIT ?
            """,
                (limit,),
            )

            columns = [
                "id",
                "name",
                "musicbrainz_id",
                "disambiguation_confidence",
                "confidence_last_checked",
            ]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
