"""Album matching utilities for artist disambiguation."""

import re
from typing import List, Tuple, Dict
import logging
from difflib import SequenceMatcher

log = logging.getLogger(__name__)


class AlbumMatcher:
    """Utility class for matching local album names against MusicBrainz releases."""

    # Common words to remove for better matching
    COMMON_WORDS = {
        "remastered",
        "deluxe",
        "expanded",
        "edition",
        "special",
        "bonus",
        "disc",
        "cd",
        "lp",
    }

    @staticmethod
    def normalize_album_title(title: str) -> str:
        """Normalize an album title for comparison."""
        if not title:
            return ""

        # Convert to lowercase
        normalized = title.lower().strip()

        # Remove common punctuation and special characters
        normalized = re.sub(r"[^\w\s]", " ", normalized)

        # Remove extra whitespace
        normalized = re.sub(r"\s+", " ", normalized).strip()

        # Remove common words
        words = normalized.split()
        filtered_words = [
            word for word in words if word not in AlbumMatcher.COMMON_WORDS
        ]

        # If we removed all words, keep the original (minus punctuation)
        if not filtered_words:
            return re.sub(r"[^\w\s]", " ", title.lower()).strip()

        return " ".join(filtered_words)

    @staticmethod
    def calculate_similarity(title1: str, title2: str) -> float:
        """Calculate similarity between two album titles."""
        norm1 = AlbumMatcher.normalize_album_title(title1)
        norm2 = AlbumMatcher.normalize_album_title(title2)

        if not norm1 or not norm2:
            return 0.0

        # Exact match after normalization
        if norm1 == norm2:
            return 1.0

        # Use sequence matcher for fuzzy matching
        similarity = SequenceMatcher(None, norm1, norm2).ratio()

        # Boost score for partial matches (one title contains the other)
        if norm1 in norm2 or norm2 in norm1:
            similarity = max(similarity, 0.8)

        return similarity

    @staticmethod
    def find_best_matches(
        local_albums: List[str], mb_releases: List[Dict], min_similarity: float = 0.6
    ) -> Tuple[List[Tuple[str, str, float]], float]:
        """
        Find the best matches between local albums and MusicBrainz releases.

        Returns:
            Tuple of (matches_list, overall_confidence_score)
            matches_list: List of (local_album, mb_release_title, similarity_score)
            overall_confidence_score: Float between 0.0 and 1.0
        """
        if not local_albums or not mb_releases:
            return [], 0.0

        matches = []
        total_similarity = 0.0
        matched_local_albums = 0

        mb_titles = [release.get("title", "") for release in mb_releases]

        for local_album in local_albums:
            best_similarity = 0.0
            best_mb_title = ""

            for mb_title in mb_titles:
                similarity = AlbumMatcher.calculate_similarity(local_album, mb_title)
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_mb_title = mb_title

            if best_similarity >= min_similarity:
                matches.append((local_album, best_mb_title, best_similarity))
                total_similarity += best_similarity
                matched_local_albums += 1

                log.debug(
                    f"Album match: '{local_album}' -> '{best_mb_title}' "
                    f"(similarity: {best_similarity:.2f})"
                )

        # Calculate overall confidence
        if matched_local_albums == 0:
            overall_confidence = 0.0
        else:
            # Average similarity of matched albums, weighted by match ratio
            avg_similarity = total_similarity / matched_local_albums
            match_ratio = matched_local_albums / len(local_albums)
            overall_confidence = avg_similarity * match_ratio

        log.debug(
            f"Album matching results: {matched_local_albums}/{len(local_albums)} albums matched, "
            f"overall confidence: {overall_confidence:.2f}"
        )

        return matches, overall_confidence

    @staticmethod
    def get_confidence_level(score: float) -> str:
        """Convert numerical confidence score to categorical level."""
        if score >= 0.75:
            return "high"
        elif score >= 0.5:
            return "medium"
        elif score >= 0.2:
            return "low"
        else:
            return "none"
