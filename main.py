
import logging

from src.config import *
from src.database import Database
from src.musicbrainz import MusicBrainzClient
from src.scanner import MusicScanner
from src.notifications import NotificationClient, HealthCheck
from src.scheduler import ArtistScheduler

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger('musicbrainzngs').setLevel(logging.WARNING)

def main(migrate_from_csv: bool = False):
    """Main entry point for the new release notifier."""
    log.info("+-+-+-+-+-START-NEW_RELEASE_NOTIFIER-+-+-+-+-+")

    # Initialize components
    health_check = HealthCheck()
    health_check.ping_start()

    try:
        # Initialize database
        db = Database(DATABASE_PATH)

        # Migrate from CSV if it exists
        if migrate_from_csv:
            try:
                db.migrate_from_csv(LEGACY_CSV_PATH)
            except Exception as e:
                log.warning(
                    f"CSV migration failed (this is normal if already migrated): {e}"
                )

        # Initialize other components
        mb_client = MusicBrainzClient()
        scanner = MusicScanner(MUSIC_LIBRARY_PATH)
        notifier = NotificationClient()
        scheduler = ArtistScheduler(db, DAILY_CHECK_LIMIT)

        # Display current statistics
        stats = scheduler.get_schedule_stats()
        log.info(f"Database stats: {stats}")

        # Step 1: Scan for new artists in music directory
        log.info("Scanning music directory for new artists...")
        existing_artists = set(db.get_all_artists())
        new_artists = scanner.find_new_artists(existing_artists)

        # Add new artists to database with disambiguation
        for artist_name in new_artists:
            log.info(f"Adding new artist: {artist_name}")
            # Get albums for disambiguation
            known_albums = scanner.get_artist_albums(artist_name)
            
            if known_albums:
                # Use disambiguation for new artists
                mb_id, confidence_level = mb_client.search_artist_with_disambiguation(
                    artist_name, known_albums
                )
                artist_id = db.add_artist(artist_name, mb_id, ignore_releases=False)
                if mb_id and artist_id:
                    scheduler.update_artist_confidence(artist_id, confidence_level, mb_id)
            else:
                # Fallback to basic search if no albums found
                mb_id = mb_client.search_artist(artist_name)
                artist_id = db.add_artist(artist_name, mb_id, ignore_releases=False)
                if mb_id and artist_id:
                    scheduler.update_artist_confidence(artist_id, "low", mb_id)

        # Step 1.5: Validate confidence for existing artists
        log.info(f"Checking confidence for up to {DAILY_CONFIDENCE_CHECK_LIMIT} existing artists...")
        artists_for_confidence_check = scheduler.get_artists_for_confidence_check(DAILY_CONFIDENCE_CHECK_LIMIT)
        
        for artist in artists_for_confidence_check:
            artist_id = artist["id"]
            artist_name = artist["name"]
            current_mb_id = artist["musicbrainz_id"]
            
            log.info(f"Validating confidence for: {artist_name}")
            known_albums = scanner.get_artist_albums(artist_name)
            
            if known_albums and current_mb_id:
                # Validate current MusicBrainz ID
                confidence_score, confidence_level = mb_client.validate_artist_confidence(
                    current_mb_id, known_albums
                )
                
                # If confidence is too low, try to find a better match
                if confidence_score < DISAMBIGUATION_MIN_CONFIDENCE_THRESHOLD:
                    log.warning(f"Low confidence for {artist_name}, attempting re-disambiguation")
                    new_mb_id, new_confidence_level = mb_client.search_artist_with_disambiguation(
                        artist_name, known_albums
                    )
                    if new_mb_id != current_mb_id:
                        log.info(f"Updated MusicBrainz ID for {artist_name}: {current_mb_id} -> {new_mb_id}")
                        scheduler.update_artist_confidence(artist_id, new_confidence_level, new_mb_id)
                    else:
                        scheduler.update_artist_confidence(artist_id, confidence_level)
                else:
                    scheduler.update_artist_confidence(artist_id, confidence_level)
            else:
                # Mark as low confidence if no albums or no MB ID
                scheduler.update_artist_confidence(artist_id, "low")

        # Step 2: Get artists to check today
        log.info(f"Getting up to {DAILY_CHECK_LIMIT} artists to check today...")
        artists_to_check = scheduler.get_artists_to_check_today()

        if not artists_to_check:
            log.info("No artists to check today")
            health_check.ping(success=True)
            return

        log.info(f"Checking {len(artists_to_check)} artists for new releases")

        # Step 3: Check each artist for new releases
        api_calls = 0
        cache_hits = 0
        all_new_releases = []

        for artist in artists_to_check:
            artist_id = artist["id"]
            artist_name = artist["name"]
            mb_id = artist["musicbrainz_id"]

            log.info(f"Checking releases for: {artist_name}")

            if not mb_id:
                log.warning(
                    f"No MusicBrainz ID for {artist_name}, trying to find one..."
                )
                mb_id = mb_client.search_artist(artist_name)
                if mb_id:
                    db.update_artist_musicbrainz_id(artist_name, mb_id)
                    api_calls += 1
                else:
                    log.warning(f"Could not find MusicBrainz ID for {artist_name}")
                    scheduler.update_artist_after_check(artist_id)
                    continue

            # Get recent releases
            try:
                releases = mb_client.get_recent_releases(mb_id, RELEASE_WINDOW_DAYS)
                api_calls += 1

                # Add new releases to database
                for release in releases:
                    is_new = db.add_release(
                        artist_id=artist_id,
                        musicbrainz_id=release["id"],
                        title=release["title"],
                        release_date=release["first_release_date"],
                        release_type=release["type"],
                    )

                    if is_new:
                        log.info(
                            f"New release found: {artist_name} - {release['title']} ({release['first_release_date']})"
                        )
                        all_new_releases.append(
                            {
                                "id": None,  # Will be set by database
                                "artist_name": artist_name,
                                "title": release["title"],
                                "release_date": release["first_release_date"],
                                "release_type": release["type"],
                            }
                        )

                scheduler.update_artist_after_check(artist_id)

            except Exception as e:
                log.error(f"Error checking releases for {artist_name}: {e}")
                # Still update the check time even if there was an error
                scheduler.update_artist_after_check(artist_id)
                continue

        # Step 4: Send notifications for unnotified releases
        log.info("Checking for releases to notify...")
        unnotified_releases = db.get_unnotified_releases()

        if unnotified_releases:
            log.info(
                f"Sending notifications for {len(unnotified_releases)} releases"
            )

            for release in unnotified_releases:
                notifier.send_release_notification(
                    artist_name=release["artist_name"],
                    title=release["title"],
                    release_date=release["release_date"],
                    release_type=release["release_type"],
                )
                db.mark_release_notified(release["id"])
        else:
            log.info("No new releases to notify")

        # Step 5: Log final statistics
        log.info(
            f"Completed. API calls: {api_calls}, New releases found: {len(all_new_releases)}"
        )
        log.info(f"Notifications sent: {len(unnotified_releases)}")

        # Send success health check
        health_check.ping(success=True)

    except Exception as e:
        log.error(f"Fatal error in main execution: {e}", exc_info=True)
        health_check.ping(success=False)
    
    finally:
        log.info("+-+-+-+-+-END-NEW_RELEASE_NOTIFIER-+-+-+-+-+")


if __name__ == "__main__":
    main()
