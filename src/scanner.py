"""Music directory scanner for discovering new artists."""

import os
from typing import List, Set
import logging

logger = logging.getLogger(__name__)


class MusicScanner:
    def __init__(self, music_library_path: str):
        self.music_library_path = music_library_path

    def scan_artist_folders(self) -> List[str]:
        """Scan the music directory and return a list of artist folder names."""
        if not os.path.exists(self.music_library_path):
            logger.warning(
                f"Music library path does not exist: {self.music_library_path}"
            )
            return []

        try:
            artist_folders = [
                folder
                for folder in os.listdir(self.music_library_path)
                if os.path.isdir(os.path.join(self.music_library_path, folder))
                and not folder.startswith(".")  # Skip hidden folders
            ]

            logger.info(f"Found {len(artist_folders)} artist folders in music library")
            return artist_folders

        except Exception as e:
            logger.error(f"Error scanning music library: {e}")
            return []

    def find_new_artists(self, existing_artists: Set[str]) -> List[str]:
        """Find artist folders that are not already in the database."""
        all_artists = self.scan_artist_folders()
        new_artists = [
            artist for artist in all_artists if artist not in existing_artists
        ]

        if new_artists:
            logger.info(f"Found {len(new_artists)} new artists: {new_artists[:5]}...")
        else:
            logger.info("No new artists found")

        return new_artists

    def get_artist_albums(self, artist_name: str) -> List[str]:
        """Get album directory names for a specific artist."""
        artist_path = os.path.join(self.music_library_path, artist_name)

        if not os.path.exists(artist_path):
            logger.warning(f"Artist directory does not exist: {artist_path}")
            return []

        if not os.path.isdir(artist_path):
            logger.warning(f"Artist path is not a directory: {artist_path}")
            return []

        try:
            album_folders = [
                folder
                for folder in os.listdir(artist_path)
                if os.path.isdir(os.path.join(artist_path, folder))
                and not folder.startswith(".")  # Skip hidden folders
            ]

            logger.debug(
                f"Found {len(album_folders)} albums for {artist_name}: {album_folders}"
            )
            return album_folders

        except Exception as e:
            logger.error(f"Error scanning albums for artist {artist_name}: {e}")
            return []
