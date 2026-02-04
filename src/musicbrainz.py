"""MusicBrainz API client - simplified for release fetching only."""

import musicbrainzngs
import time
import random
import logging
from datetime import datetime, timedelta

from src.config import MusicBrainzConfig

log = logging.getLogger(__name__)


class ConnectionTimeoutError(Exception):
    """Raised when the connection timeout is exceeded."""

    pass


class MusicBrainzClient:
    """Simplified client for fetching release groups only."""

    def __init__(self, config: MusicBrainzConfig = MusicBrainzConfig()):
        musicbrainzngs.set_useragent(
            app=config.user_agent,
            version=config.version,
            contact=config.contact,
        )
        self.last_request_time = 0
        self.rate_limit_delay = config.rate_limit_delay
        self.max_retries = config.max_retries
        self.initial_backoff = getattr(config, "initial_backoff", 1)
        self.max_backoff = getattr(config, "max_backoff", 60)
        self.connection_timeout = getattr(config, "connection_timeout", 300)
        self.excluded_release_types = getattr(config, "excluded_release_types", [])
        self.included_release_types = getattr(config, "included_release_types", [])

    def _rate_limit(self):
        """Ensure we don't exceed the MusicBrainz rate limit of 1 request per second."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time

        if time_since_last < self.rate_limit_delay:
            sleep_time = self.rate_limit_delay - time_since_last
            time.sleep(sleep_time)

        self.last_request_time = time.time()

    def _retry_with_backoff(self, func, *args, **kwargs):
        """Execute a function with exponential backoff retry."""
        start_time = time.time()

        for attempt in range(self.max_retries):
            elapsed_time = time.time() - start_time
            if elapsed_time > self.connection_timeout:
                raise ConnectionTimeoutError(
                    f"Connection timeout exceeded ({self.connection_timeout}s)"
                )

            try:
                self._rate_limit()
                return func(*args, **kwargs)

            except musicbrainzngs.NetworkError as e:
                log.warning(f"Network error on attempt {attempt + 1}: {e}")
                if attempt == self.max_retries - 1:
                    raise

            except musicbrainzngs.ResponseError as e:
                if (
                    hasattr(e, "cause")
                    and hasattr(e.cause, "code")
                    and e.cause.code == 429
                ):
                    log.warning(f"Rate limit exceeded on attempt {attempt + 1}")
                    if attempt == self.max_retries - 1:
                        raise
                else:
                    raise

            except Exception as e:
                log.error(f"Unexpected error on attempt {attempt + 1}: {e}")
                if attempt == self.max_retries - 1:
                    raise

            # Exponential backoff with jitter
            sleep_time = min(self.initial_backoff * (2**attempt), self.max_backoff)
            jitter = random.uniform(0.1, 0.3) * sleep_time
            time.sleep(sleep_time + jitter)

    def get_recent_releases(self, artist_id: str, days_back: int = 30) -> list[dict]:
        """Get releases from the last N days."""
        cutoff_date = datetime.now() - timedelta(days=days_back)
        return self._get_release_groups(artist_id, since_date=cutoff_date)

    def _get_release_groups(
        self, artist_id: str, since_date: datetime | None = None
    ) -> list[dict]:
        """Fetch release groups for an artist."""
        results = []
        offset = 0

        while True:
            self._rate_limit()

            try:
                response = self._retry_with_backoff(
                    musicbrainzngs.browse_release_groups,
                    artist=artist_id,
                    offset=offset,
                    limit=25,
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

                results.append(
                    {
                        "id": rg["id"],
                        "title": rg["title"],
                        "type": release_type,
                        "first_release_date": date_str,
                    }
                )

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
