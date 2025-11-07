"""Artist checking scheduler to manage the daily check rotation."""

import logging

from src.database import Database

log = logging.getLogger(__name__)


class ArtistScheduler:
    def __init__(self, database: Database, daily_limit: int):
        self.db = database
        self.daily_limit = daily_limit

    def get_artists_to_check_today(self) -> list[dict]:
        """Get the list of artists that should be checked today."""
        return self.db.get_artists_for_checking(self.daily_limit)

    def update_artist_after_check(self, artist_id: int):
        """Update an artist's record after checking for releases."""
        self.db.update_artist_check(artist_id)

    def get_schedule_stats(self) -> dict:
        """Get statistics about the checking schedule."""
        stats = self.db.get_stats()

        if stats["active_artists"] > 0:
            days_for_full_cycle = max(1, stats["active_artists"] / self.daily_limit)
            stats["estimated_cycle_days"] = round(days_for_full_cycle, 1)
        else:
            stats["estimated_cycle_days"] = 0

        stats["daily_limit"] = self.daily_limit
        return stats

    def get_artists_for_confidence_check(self, limit: int) -> list[dict]:
        """Get artists that need confidence validation."""
        return self.db.get_artists_for_confidence_check(limit)

    def update_artist_confidence(
        self,
        artist_id: int,
        confidence_level: str,
        musicbrainz_id: str | None = None,
    ):
        """Update an artist's confidence after validation."""
        self.db.update_artist_confidence(artist_id, confidence_level, musicbrainz_id)
