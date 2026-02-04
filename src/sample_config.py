"""Configuration settings for the new release notifier."""

import yaml
from pydantic import BaseModel


class ServerPaths(BaseModel):
    """Server path configurations."""

    music_library: str = ""
    releases_db: str = ""  # Path to releases.db


class MusicBrainzConfig(BaseModel):
    """MusicBrainz API configuration settings."""

    user_agent: str = "ReleaseNotifier"
    version: float = 1.0
    contact: str = ""
    rate_limit_delay: float = 1.1
    max_retries: int = 3
    intial_backoff: int = 1  # seconds
    max_backoff: int = 60  # seconds


class DetectionParams(BaseModel):
    """Parameters for release detection."""

    cache_expiry_days: int = 30
    daily_check_limit: int = 50
    release_window_days: int = 30
    excluded_release_types: list[str] = []
    included_release_types: list[str] = []


class BeetsConfig(BaseModel):
    """Beets integration configuration."""

    database_path: str = ""  # Path to musiclibrary.db
    enabled: bool = True


class NtfyConfig(BaseModel):
    """ntfy notification service configuration settings."""

    topic: str = ""
    token: str = ""


class HealthCheckConfig(BaseModel):
    """Health check configuration settings."""

    url: str = ""
    timeout: int = 10  # seconds


class AppConfig(BaseModel):
    """Application configuration settings."""

    server_paths: ServerPaths = ServerPaths()
    musicbrainz: MusicBrainzConfig = MusicBrainzConfig()
    detection_params: DetectionParams = DetectionParams()
    beets: BeetsConfig = BeetsConfig()
    ntfy: NtfyConfig = NtfyConfig()
    health_check: HealthCheckConfig = HealthCheckConfig()


def load_config(yaml_path: str = "data/app_config.yml") -> AppConfig:
    """Load configuration from a YAML file."""

    with open(yaml_path, "r") as file:
        config_data = yaml.safe_load(file)

    return AppConfig(**config_data)
