"""Main entry point for the new release notifier."""

import logging

import typer

from src.beets_reader import BeetsReader
from src.config import load_config
from src.database import Database
from src.log_config import basic_config
from src.musicbrainz import MusicBrainzClient
from src.notifications import NotificationClient, HealthCheck


log = logging.getLogger(__name__)
app = typer.Typer()


def sync_artists_from_beets(db: Database, beets: BeetsReader) -> int:
    """Sync all artists with MB IDs from beets to releases.db."""
    beets_artists = beets.get_all_artists_with_mb_ids()
    synced = 0

    for artist_name, mb_id in beets_artists.items():
        existing = db.get_artist_by_name(artist_name)

        # Skip if already synced from beets with same ID
        if existing and existing.get("mb_id_source") == "beets":
            if existing.get("musicbrainz_id") == mb_id:
                continue

        db.sync_from_beets(artist_name, mb_id)
        synced += 1
        log.debug(f"Synced artist from beets: {artist_name}")

    return synced


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
        db = Database(config.server_paths.releases_db)
        mb_client = MusicBrainzClient(config.musicbrainz)
        notifier = NotificationClient(config.ntfy)

        # Initialize beets reader if enabled
        beets = None
        if config.beets.enabled and config.beets.database_path:
            try:
                beets = BeetsReader(config.beets.database_path)
                stats = beets.get_coverage_stats()
                log.info(
                    f"Beets coverage: {stats['artists_with_mb_id']}/{stats['total_artists']} "
                    f"artists ({stats['coverage_pct']}%)"
                )
            except FileNotFoundError as e:
                log.warning(f"Beets database not found: {e}")
                beets = None

        # Step 1: Sync artists from beets (if available)
        if beets:
            log.info("Syncing artists from beets database...")
            synced = sync_artists_from_beets(db, beets)
            log.info(f"Synced {synced} artists from beets")

        # Step 2: Get artists to check for new releases
        if artist:
            # Single artist mode for testing
            artist_data = db.get_artist_by_name(artist)
            if not artist_data:
                log.error(f"Artist not found: {artist}")
                health_check.ping(success=False)
                return
            artists_to_check = [artist_data]
            log.info(f"Single artist mode: checking {artist}")
        else:
            artists_to_check = db.get_artists_for_checking(
                config.detection_params.daily_check_limit
            )

        if not artists_to_check:
            log.info("No artists to check today")
            health_check.ping(success=True)
            return

        log.info(f"Checking {len(artists_to_check)} artists for new releases")

        # Step 3: Check each artist for new releases
        all_new_releases = []

        for artist_data in artists_to_check:
            if not artist_data:
                continue

            artist_id = artist_data["id"]
            artist_name = artist_data["name"]
            mb_id = artist_data.get("musicbrainz_id")

            if not mb_id:
                log.warning(f"No MB ID for {artist_name} - skipping")
                db.update_artist_check(artist_id)
                continue

            log.info(f"Checking releases for: {artist_name}")

            try:
                releases = mb_client.get_recent_releases(
                    mb_id, config.detection_params.release_window_days
                )

                for release in releases:
                    is_new = db.add_release(
                        artist_id=artist_id,
                        musicbrainz_id=release["id"],
                        title=release["title"],
                        release_date=release["first_release_date"],
                        release_type=release["type"],
                    )

                    if is_new:
                        log.info(f"New release: {artist_name} - {release['title']}")
                        all_new_releases.append(release)

                db.update_artist_check(artist_id)

            except Exception as e:
                log.error(f"Error checking {artist_name}: {e}")
                db.update_artist_check(artist_id)

        # Step 4: Send notifications
        unnotified = db.get_unnotified_releases()
        for release in unnotified:
            notifier.send_release_notification(
                artist_name=release["artist_name"],
                title=release["title"],
                release_date=release["release_date"],
                release_type=release["release_type"],
            )
            db.mark_release_notified(release["id"])

        log.info(
            f"Done. New releases: {len(all_new_releases)}, Notifications: {len(unnotified)}"
        )
        health_check.ping(success=True)

    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
        health_check.ping(success=False)

    finally:
        log.info("+-+-+-+-+-END-NEW_RELEASE_NOTIFIER-+-+-+-+-+")


if __name__ == "__main__":
    app()
