"""Configuration settings for the new release notifier."""

import yaml
from pydantic import BaseModel, SecretStr


class DatabasePaths(BaseModel):
    """Database path configurations."""

    beets_db: str = ""  # Path to beets musiclibrary.db
    notifications_db: str = "data/notifications.db"  # Path to notifications.db


class MusicBrainzConfig(BaseModel):
    """MusicBrainz API configuration settings."""

    user_agent: str = "ReleaseNotifier"
    version: float = 1.0
    contact: str = ""
    rate_limit_delay: float = 1.1
    max_retries: int = 3
    initial_backoff: int = 1  # seconds
    max_backoff: int = 60  # seconds
    connection_timeout: int = 300  # seconds
    # MusicBrainz never uses the same name for both, so each list has its own field:
    # "single" is a primary type, "compilation" a secondary one.
    excluded_primary_types: list[str] = []
    excluded_secondary_types: list[str] = []
    release_window_days: int = 30
    full_scan_days: int = 7


class NtfyConfig(BaseModel):
    """ntfy notification service configuration settings."""

    base_url: str = ""  # Server root, e.g. http://ntfy or https://ntfy.example.com
    topic: str = ""  # Topic name only, e.g. music-releases
    # SecretStr so the token renders as ********** wherever the config is logged.
    token: SecretStr = SecretStr("")  # Access token, without the "Bearer " prefix

    @property
    def url(self) -> str:
        """Full publish endpoint for the configured topic."""
        return f"{self.base_url.rstrip('/')}/{self.topic}"


class HealthCheckConfig(BaseModel):
    """Health check configuration settings."""

    url: str = ""
    timeout: int = 10  # seconds


class AppConfig(BaseModel):
    """Application configuration settings."""

    databases: DatabasePaths = DatabasePaths()
    musicbrainz: MusicBrainzConfig = MusicBrainzConfig()
    ntfy: NtfyConfig = NtfyConfig()
    health_check: HealthCheckConfig = HealthCheckConfig()


def load_config(yaml_path: str = "data/app_config.yml") -> AppConfig:
    """Load configuration from a YAML file."""

    with open(yaml_path, "r") as file:
        config_data = yaml.safe_load(file)

    return AppConfig(**config_data)
