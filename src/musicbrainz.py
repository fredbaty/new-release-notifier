"""MusicBrainz API client with retry logic and rate limiting."""

import musicbrainzngs
import time
import random
import logging
from datetime import datetime, timedelta

from config import DisambiguationParams, MusicBrainzConfig
from .disambiguation import AlbumMatcher

log = logging.getLogger(__name__)


class ConnectionTimeoutError(Exception):
    """Raised when the connection timeout is exceeded."""

    pass


class MusicBrainzClient:
    def __init__(
        self,
        config: MusicBrainzConfig = MusicBrainzConfig(),
        disambig_params: DisambiguationParams = DisambiguationParams(),
    ):
        musicbrainzngs.set_useragent(
            app=config.user_agent,
            version=config.version,
            contact=config.contact,
        )
        self.last_request_time = config.last_request_time
        self.connection_timeout = config.connection_timeout
        self.rate_limit_delay = config.rate_limit_delay
        self.max_retries = config.max_retries
        self.initial_backoff = config.initial_backoff
        self.max_backoff = config.max_backoff
        self.excluded_release_types = config.excluded_release_types
        self.included_release_types = config.included_release_types
        self.disambig_params = disambig_params

    def _rate_limit(self):
        """Ensure we don't exceed the MusicBrainz rate limit of 1 request per second."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time

        if time_since_last < self.rate_limit_delay:
            sleep_time = self.rate_limit_delay - time_since_last
            time.sleep(sleep_time)

        self.last_request_time = time.time()

    def _retry_with_backoff(self, func, *args, **kwargs):
        """Execute a function with exponential backoff retry and connection timeout."""
        start_time = time.time()

        for attempt in range(self.max_retries):
            # Check if we've exceeded the connection timeout
            elapsed_time = time.time() - start_time
            if elapsed_time > self.connection_timeout:
                raise ConnectionTimeoutError(
                    f"Connection timeout exceeded ({self.connection_timeout}s) after {attempt + 1} attempts"
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
                    # For other response errors, don't retry
                    raise

            except Exception as e:
                log.error(f"Unexpected error on attempt {attempt + 1}: {e}")
                if attempt == self.max_retries - 1:
                    raise

            # Calculate sleep time with exponential backoff and jitter
            sleep_time = min(self.initial_backoff * (2**attempt), self.max_backoff)
            jitter = random.uniform(0.1, 0.3) * sleep_time
            total_sleep_time = sleep_time + jitter

            # Check if sleeping would exceed the timeout
            if elapsed_time + total_sleep_time > self.connection_timeout:
                remaining_time = self.connection_timeout - elapsed_time
                if remaining_time <= 0:
                    raise ConnectionTimeoutError(
                        f"Connection timeout exceeded ({self.connection_timeout}s) during backoff"
                    )
                # Sleep for the remaining time only
                time.sleep(remaining_time)
            else:
                time.sleep(total_sleep_time)

    def search_artist(self, artist_name: str) -> str | None:
        """Search for an artist and return their MusicBrainz ID."""
        try:
            result = self._retry_with_backoff(
                musicbrainzngs.search_artists, artist=artist_name
            )

            if result["artist-count"] > 0:
                artist_id = result["artist-list"][0]["id"]
                log.debug(f"Found MusicBrainz ID for {artist_name}: {artist_id}")
                return artist_id
            else:
                log.debug(f"No MusicBrainz ID found for {artist_name}")
                return None

        except Exception as e:
            log.error(f"Error searching for artist {artist_name}: {e}")
            return None

    def get_release_groups(
        self, artist_id: str, since_date: datetime | None = None
    ) -> list[dict]:
        """Get release groups for an artist, optionally filtered by date."""
        all_release_groups = []
        offset = 0
        page_size = 25

        try:
            while True:
                log.debug(f"Fetching release groups for {artist_id}, offset {offset}")

                response = self._retry_with_backoff(
                    musicbrainzngs.browse_release_groups,
                    artist=artist_id,
                    offset=offset,
                    limit=page_size,
                )

                release_groups = response["release-group-list"]

                for rg in release_groups:
                    # Only include releases with a date
                    if "first-release-date" not in rg:
                        continue

                    # Apply release type filtering if configured
                    if self.excluded_release_types:
                        release_type = rg.get("type", "")
                        if release_type in self.excluded_release_types:
                            continue

                    if self.included_release_types:
                        release_type = rg.get("type", "")
                        if release_type not in self.included_release_types:
                            continue

                    # Parse and filter by date if specified
                    date_str = rg["first-release-date"]
                    try:
                        # Try full date format first
                        try:
                            release_date = datetime.strptime(date_str, "%Y-%m-%d")
                        except ValueError:
                            # Fall back to year-month format
                            try:
                                release_date = datetime.strptime(date_str, "%Y-%m")
                            except ValueError:
                                # Skip releases with unparseable dates
                                continue

                        # Filter by date if since_date is provided
                        if since_date and release_date < since_date:
                            continue

                        all_release_groups.append(
                            {
                                "id": rg["id"],
                                "title": rg["title"],
                                "type": rg.get("type", ""),
                                "first_release_date": date_str,
                                "parsed_date": release_date,
                            }
                        )

                    except Exception as e:
                        log.warning(
                            f"Error parsing date for release {rg.get('title', 'Unknown')}: {e}"
                        )
                        continue

                # Check if we've reached the end
                if len(release_groups) < page_size:
                    break

                offset += page_size

            log.info(
                f"Retrieved {len(all_release_groups)} release groups for artist {artist_id}"
            )
            return all_release_groups

        except Exception as e:
            log.error(f"Error fetching release groups for artist {artist_id}: {e}")
            return []

    def get_recent_releases(self, artist_id: str, days_back: int = 30) -> list[dict]:
        """Get releases from the last N days and any future releases."""
        cutoff_date = datetime.now() - timedelta(days=days_back)
        return self.get_release_groups(artist_id, since_date=cutoff_date)

    def validate_artist_confidence(
        self, artist_id: str, known_albums: list[str]
    ) -> tuple[float, str]:
        """
        Validate confidence of an existing MusicBrainz ID using known albums.

        Returns:
            Tuple of (confidence_score, confidence_level)
        """
        if not known_albums:
            log.warning(
                f"No known albums provided for confidence validation of {artist_id}"
            )
            return 0.0, "none"

        try:
            # Get all release groups for this artist (no date filter for confidence check)
            log.info(f"Getting all release groups for artist id {artist_id}")
            all_releases = self.get_release_groups(artist_id, since_date=None)

            if not all_releases:
                log.warning(f"No releases found for artist {artist_id}")
                return 0.0, "none"

            # Use album matcher to calculate confidence
            log.info(
                f"Calculating confidence using {len(all_releases)} retrieved release groups"
            )
            matches, confidence_score = AlbumMatcher.find_best_matches(
                known_albums,
                all_releases,
                min_similarity=self.disambig_params.album_match_weight,
            )

            confidence_level = AlbumMatcher.get_confidence_level(confidence_score)

            log.info(
                f"Confidence validation for {artist_id}: {confidence_score:.2f} ({confidence_level}) "
                f"- {len(matches)} album matches found"
            )

            return confidence_score, confidence_level

        except Exception as e:
            log.error(f"Error validating confidence for artist {artist_id}: {e}")
            return 0.0, "none"

    def search_artist_with_disambiguation(
        self, artist_name: str, known_albums: list[str]
    ) -> tuple[str | None, str]:
        """Search for an artist with disambiguation using known albums."""
        try:
            result = self._retry_with_backoff(
                musicbrainzngs.search_artists,
                artist=artist_name,
                limit=self.disambig_params.max_candidates,
            )

            if result["artist-count"] == 0:
                return None, "none"

            candidates = result["artist-list"]

            if not known_albums:
                return candidates[0]["id"], "low"

            best_candidate = None
            best_confidence = 0.0
            best_confidence_level = "none"

            for candidate in candidates:
                candidate_id = candidate["id"]
                try:
                    confidence_score, confidence_level = (
                        self.validate_artist_confidence(candidate_id, known_albums)
                    )

                    if confidence_score > best_confidence:
                        best_candidate = candidate_id
                        best_confidence = confidence_score
                        best_confidence_level = confidence_level

                except Exception as e:
                    log.warning(f"Error evaluating candidate: {e}")
                    continue

            if (
                best_candidate
                and best_confidence >= self.disambig_params.min_confidence_threshold
            ):
                log.info(
                    f"Selected {best_candidate} for {artist_name} with confidence {best_confidence:.2f}"
                )
                return best_candidate, best_confidence_level
            else:
                log.warning(
                    f"Low confidence for {artist_name}, using top candidate: {candidates[0]['id']}"
                )
                return candidates[0]["id"], "low"

        except Exception as e:
            log.error(f"Error in disambiguation for {artist_name}: {e}")
            return None, "none"
