"""MusicBrainz API client."""

import logging
import random
import time
from datetime import datetime, timedelta

import requests

from src.config import MusicBrainzConfig

log = logging.getLogger(__name__)

WS_ROOT = "https://musicbrainz.org/ws/2"
PAGE_SIZE = 100


class ConnectionTimeoutError(Exception):
    """Raised when the connection timeout is exceeded."""

    pass


class MusicBrainzClient:
    """Main client for interacting with the MusicBrainz API, including rate limiting and retries."""

    def __init__(self, config: MusicBrainzConfig = MusicBrainzConfig()):
        self.last_request_time = 0.0
        self.rate_limit_delay = config.rate_limit_delay
        self.max_retries = config.max_retries
        self.initial_backoff = config.initial_backoff
        self.max_backoff = config.max_backoff
        self.connection_timeout = config.connection_timeout
        self.excluded_primary_types = {
            t.lower() for t in config.excluded_primary_types
        }
        self.excluded_secondary_types = {
            t.lower() for t in config.excluded_secondary_types
        }

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": f"{config.user_agent}/{config.version} ( {config.contact} )",
                "Accept": "application/json",
            }
        )

    def close(self):
        """Close the underlying HTTP connection pool."""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def _rate_limit(self):
        """Ensure we don't exceed the MusicBrainz rate limit of 1 request per second."""
        time_since_last = time.time() - self.last_request_time

        if time_since_last < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - time_since_last)

        self.last_request_time = time.time()

    def _get(self, path: str, params: dict) -> dict:
        """GET a MusicBrainz endpoint with rate limiting and exponential backoff."""
        start_time = time.time()

        for attempt in range(self.max_retries):
            if time.time() - start_time > self.connection_timeout:
                raise ConnectionTimeoutError(
                    f"Connection timeout exceeded ({self.connection_timeout}s)"
                )

            last_attempt = attempt == self.max_retries - 1

            try:
                self._rate_limit()
                response = self.session.get(
                    f"{WS_ROOT}/{path}",
                    params={**params, "fmt": "json"},
                    timeout=30,
                )
            except requests.RequestException as e:
                log.warning(f"Network error on attempt {attempt + 1}: {e}")
                if last_attempt:
                    raise
            else:
                # MusicBrainz signals throttling with 503, not just 429.
                if response.status_code not in (429, 503):
                    response.raise_for_status()
                    return response.json()

                log.warning(
                    f"Rate limit exceeded ({response.status_code}) on attempt {attempt + 1}"
                )
                if last_attempt:
                    response.raise_for_status()

            sleep_time = min(self.initial_backoff * (2**attempt), self.max_backoff)
            jitter = random.uniform(0.1, 0.3) * sleep_time
            time.sleep(sleep_time + jitter)

        raise ConnectionTimeoutError(f"Exhausted {self.max_retries} attempts for {path}")

    def get_recent_releases(
        self,
        artist_id: str,
        days_back: int = 30,
        known_count: int | None = None,
    ) -> tuple[list[dict], int | None]:
        """Get releases from the last N days, with the artist's total release-group count.

        MusicBrainz cannot sort a browse by date, so finding recent releases means
        paging the artist's whole discography. When known_count matches the count the
        first page reports, nothing has been added since it was recorded and the
        remaining pages are skipped. The count is returned so the caller can store it;
        None means the fetch failed and the stored value should be left alone.
        """
        cutoff_date = datetime.now() - timedelta(days=days_back)
        results = []
        offset = 0
        total = 0

        while True:
            try:
                response = self._get(
                    "release-group",
                    {"artist": artist_id, "limit": PAGE_SIZE, "offset": offset},
                )
            except Exception as e:
                log.error(f"Error fetching releases for {artist_id}: {e}")
                return results, None

            total = response.get("release-group-count", 0)
            page = response.get("release-groups", [])

            for rg in page:
                release = self._filter_release_group(rg, cutoff_date)
                if release:
                    results.append(release)

            if known_count is not None and total == known_count:
                log.debug(
                    f"{artist_id}: release-group count unchanged ({total}), "
                    "skipping remaining pages"
                )
                break

            offset += len(page)
            if not page or offset >= total:
                break

        return results, total

    def _filter_release_group(self, rg: dict, cutoff_date: datetime) -> dict | None:
        """Return a release group as a result dict, or None if it is filtered out."""
        date_str = rg.get("first-release-date")
        if not date_str:
            return None

        release_date = self._parse_date(date_str)
        if not release_date or release_date < cutoff_date:
            return None

        # MusicBrainz splits these: "single" is only ever primary, "compilation" only
        # ever secondary, so the two lists are matched against their own field.
        primary = (rg.get("primary-type") or "").lower()
        secondary = {(t or "").lower() for t in rg.get("secondary-types") or []}

        if primary and primary in self.excluded_primary_types:
            log.debug(f"{rg['title']} (primary type: {primary}) is excluded. Skipping.")
            return None

        excluded = secondary & self.excluded_secondary_types
        if excluded:
            log.debug(
                f"{rg['title']} (secondary type: {', '.join(sorted(excluded))}) "
                "is excluded. Skipping."
            )
            return None

        return {
            "id": rg["id"],
            "title": rg["title"],
            "type": " + ".join(t for t in [primary, *sorted(secondary)] if t),
            "first_release_date": date_str,
        }

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        """Parse MusicBrainz date formats."""
        for fmt in ["%Y-%m-%d", "%Y-%m", "%Y"]:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None
