"""Main entry point for the new release notifier."""

import logging

import typer

from src.beets_reader import BeetsReader
from src.config import load_config
from src.database import NotificationDatabase
from src.log_config import basic_config
from src.musicbrainz import MusicBrainzClient
from src.notifications import NotificationClient, HealthCheck


log = logging.getLogger(__name__)
app = typer.Typer()


@app.command()
def main(
    config_path: str = typer.Option(
        "data/app_config.yml", "--config", help="Path to configuration file"
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging"),
    artist: str = typer.Option(
        None, "--artist", help="Test with a single artist by name"
    ),
):
    """Main entry point for the new release notifier."""
    basic_config(verbose)
    log = logging.getLogger(__name__)

    log.info("+-+-+-+-+-START-NEW_RELEASE_NOTIFIER-+-+-+-+-+")
    config = load_config(config_path)

    health_check = HealthCheck(config.health_check)
    health_check.ping_start()

    try:
        # Initialize components
        beets = BeetsReader(config.databases.beets_db)
        db = NotificationDatabase(config.databases.notifications_db)
        mb_client = MusicBrainzClient(config.musicbrainz)
        notifier = NotificationClient(config.ntfy)

        # Log beets coverage stats
        stats = beets.get_coverage_stats()
        log.info(
            f"Beets coverage: {stats['artists_with_mb_id']}/{stats['total_artists']} "
            f"artists ({stats['coverage_pct']}%)"
        )

        # Get all artists from beets
        artists = beets.get_all_artists_with_mb_ids()
        log.info(f"Loaded {len(artists)} artists from beets")

        # Filter to single artist if specified
        if artist:
            if artist not in artists:
                log.error(f"Artist not found in beets: {artist}")
                health_check.ping(success=False)
                return
            artists = {artist: artists[artist]}
            log.info(f"Single artist mode: checking {artist}")

        # Filter out ignored artists
        artists_to_check = {
            name: mb_id
            for name, mb_id in artists.items()
            if not db.is_artist_ignored(mb_id)
        }
        if not artists_to_check:
            log.info("No artists to check after applying ignore list")
            health_check.ping(success=True)
            return

        ignored_count = len(artists) - len(artists_to_check)
        if ignored_count > 0:
            log.info(f"Filtered out {ignored_count} ignored artists")

        log.info(f"Checking {len(artists_to_check)} artists for new releases")

        # Check each artist for new releases
        new_releases = []
        for artist_name, mb_id in artists_to_check.items():
            log.debug(f"Checking releases for: {artist_name}")

            try:
                releases = mb_client.get_recent_releases(
                    mb_id, config.detection_params.release_window_days
                )

                for release in releases:
                    if not db.is_release_notified(release["id"]):
                        new_releases.append({**release, "artist_name": artist_name})
                        log.info(f"New release: {artist_name} - {release['title']}")

            except Exception as e:
                log.error(f"Error checking {artist_name}: {e}")

        # Send notifications and record releases
        notifications_sent = 0
        for release in new_releases:
            try:
                notifier.send_release_notification(
                    artist_name=release["artist_name"],
                    title=release["title"],
                    release_date=release["first_release_date"],
                    release_type=release["type"],
                )
                db.add_notified_release(
                    mb_releasegroupid=release["id"],
                    artist_name=release["artist_name"],
                    title=release["title"],
                    release_date=release["first_release_date"],
                    release_type=release["type"],
                )
                notifications_sent += 1
            except Exception as e:
                log.error(f"Error notifying release {release['title']}: {e}")

        log.info(
            f"Done. New releases: {len(new_releases)}, Notifications sent: {notifications_sent}"
        )
        health_check.ping(success=True)

    except FileNotFoundError as e:
        log.error(f"Database not found: {e}")
        health_check.ping(success=False)

    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
        health_check.ping(success=False)

    finally:
        log.info("+-+-+-+-+-END-NEW_RELEASE_NOTIFIER-+-+-+-+-+")


if __name__ == "__main__":
    app()
