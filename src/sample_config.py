"""Configuration settings for the new release notifier."""

# Paths - server paths
MUSIC_LIBRARY_PATH = ""
DATABASE_PATH = ""
LEGACY_CSV_PATH = ""

# MusicBrainz settings
MUSICBRAINZ_USER_AGENT = "ReleaseNotifier"
MUSICBRAINZ_VERSION = 1.0
MUSICBRAINZ_CONTACT = ""

# Cache and checking settings
CACHE_EXPIRY_DAYS = 30
DAILY_CHECK_LIMIT = 50  # Artists to check per day
API_RATE_LIMIT_DELAY = 1.1  # Seconds between API calls (MusicBrainz allows 1/sec)

# Release detection settings
RELEASE_WINDOW_DAYS = 30  # Check for releases in the last N days and future releases

# Release type filtering (empty means include all)
EXCLUDED_RELEASE_TYPES = []  # Example: ['Live', 'Compilation']
INCLUDED_RELEASE_TYPES = []  # If empty, includes all; otherwise only these types

# Notification settings
NTFY_TOPIC = ""
NTFY_TOKEN = ""

# Health check settings
HEALTHCHECK_URL = ""
HEALTHCHECK_TIMEOUT = 10

# Disambiguation settings
DISAMBIGUATION_MIN_CONFIDENCE_THRESHOLD = 0.3  # Minimum match score to accept
DISAMBIGUATION_MAX_CANDIDATES = 5  # How many artist candidates to check
DISAMBIGUATION_ALBUM_MATCH_WEIGHT = 0.6  # Minimum similarity for album matches
CONFIDENCE_VALIDATION_INTERVAL_DAYS = 90  # How often to re-check confidence
DAILY_CONFIDENCE_CHECK_LIMIT = 10  # How many existing artists to validate per day

# Retry settings for API calls
MAX_RETRIES = 3
INITIAL_BACKOFF = 1  # seconds
MAX_BACKOFF = 60  # seconds
