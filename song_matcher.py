"""
Song Matching Logic
Normalizes song metadata and uses fuzzy matching to find equivalents
across platforms. Confidence threshold filters out bad matches.
"""

import re
from typing import Optional, Dict, Any, Tuple


# Patterns to strip from titles/artists for better matching
STRIP_PATTERNS = [
    r"\bfeat\.?\s+[^,\)]+",      # feat. Artist Name
    r"\bft\.?\s+[^,\)]+",         # ft. Artist Name
    r"\bfeaturing\s+[^,\)]+",     # featuring Artist Name
    r"\bremastered\b.*",           # remastered 2011, etc.
    r"\blive\b.*",                 # live at ..., live version
    r"\bacoustic\b.*",             # acoustic version
    r"\bradio edit\b",             # radio edit
    r"\bsingle version\b",         # single version
    r"\bdeluxe\b.*",               # deluxe edition
    r"\bbonus track\b",            # bonus track
    r"\boriginal\s+mix\b",         # original mix
    r"\bexplicit\b",               # explicit
    r"\(.*?\)",                    # anything in parentheses
    r"\[.*?\]",                    # anything in brackets
]

# Compile patterns for speed
_STRIP_RE = re.compile("|".join(STRIP_PATTERNS), re.IGNORECASE)
_SPECIAL_CHARS_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


class SongMatcher:
    """
    Handles normalization and fuzzy comparison of song metadata.

    Confidence score = weighted average of:
      - title similarity (50%)
      - artist similarity (30%)
      - duration closeness (20%)

    A song is accepted if confidence >= threshold (default 80%).
    """

    def __init__(self, confidence_threshold: float = 0.80):
        self.confidence_threshold = confidence_threshold

    # ─── Normalization ─────────────────────────────────────────────────────

    def normalize(self, text: str) -> str:
        """
        Normalize a string for comparison:
        1. Lowercase
        2. Strip feat./live/remastered/etc.
        3. Remove special characters
        4. Collapse whitespace
        """
        if not text:
            return ""
        text = text.lower()
        text = _STRIP_RE.sub("", text)
        text = _SPECIAL_CHARS_RE.sub(" ", text)
        text = _WHITESPACE_RE.sub(" ", text).strip()
        return text

    # ─── Fuzzy Similarity ──────────────────────────────────────────────────

    def _fuzzy_ratio(self, a: str, b: str) -> float:
        """
        Compute fuzzy similarity ratio between two strings.
        Uses rapidfuzz if available, falls back to difflib.
        Returns a value in [0.0, 1.0].
        """
        if not a or not b:
            return 0.0
        try:
            from rapidfuzz import fuzz
            # Use token_sort_ratio to handle word-order differences
            return fuzz.token_sort_ratio(a, b) / 100.0
        except ImportError:
            # Fallback to stdlib SequenceMatcher
            import difflib
            return difflib.SequenceMatcher(None, a, b).ratio()

    def _duration_score(self, dur_a: int, dur_b: int) -> float:
        """
        Score based on duration difference.
        Returns 1.0 if difference <= 3s, 0.0 if difference > 10s.
        Linear interpolation in between.
        """
        if dur_a == 0 or dur_b == 0:
            # If duration is unknown, give neutral score
            return 0.7
        diff = abs(dur_a - dur_b)
        if diff <= 3:
            return 1.0
        if diff > 10:
            return 0.0
        # Linear: 1.0 at diff=3, 0.0 at diff=10
        return 1.0 - (diff - 3) / 7.0

    # ─── Main Matching ─────────────────────────────────────────────────────

    def compute_confidence(
        self,
        source: Dict[str, Any],
        candidate: Dict[str, Any],
    ) -> Tuple[float, Dict[str, float]]:
        """
        Compute confidence score between source and candidate tracks.

        Args:
            source: dict with keys title, artist, duration_s
            candidate: dict with keys title, artist, duration_s

        Returns:
            (confidence: float, breakdown: dict with component scores)
        """
        # Normalize all fields
        src_title = self.normalize(source.get("title", ""))
        src_artist = self.normalize(source.get("artist", ""))
        cand_title = self.normalize(candidate.get("title", ""))
        cand_artist = self.normalize(candidate.get("artist", ""))

        # Compute individual scores
        title_score = self._fuzzy_ratio(src_title, cand_title)
        artist_score = self._fuzzy_ratio(src_artist, cand_artist)
        duration_score = self._duration_score(
            source.get("duration_s", 0),
            candidate.get("duration_s", 0),
        )

        # Weighted confidence
        confidence = (
            title_score * 0.50
            + artist_score * 0.30
            + duration_score * 0.20
        )

        breakdown = {
            "title_score": round(title_score, 3),
            "artist_score": round(artist_score, 3),
            "duration_score": round(duration_score, 3),
            "confidence": round(confidence, 3),
        }
        return confidence, breakdown

    def is_match(self, source: Dict[str, Any], candidate: Dict[str, Any]) -> Tuple[bool, float, Dict]:
        """
        Determine if candidate is a good enough match for source.

        Returns:
            (matched: bool, confidence: float, breakdown: dict)
        """
        confidence, breakdown = self.compute_confidence(source, candidate)
        return confidence >= self.confidence_threshold, confidence, breakdown

    def build_search_query(self, track: Dict[str, Any]) -> str:
        """
        Build a clean search query string from track metadata.
        Uses normalized title + artist for best cross-platform results.
        """
        title = self.normalize(track.get("title", ""))
        artist = self.normalize(track.get("artist", ""))
        # Combine, but limit length to avoid overly specific queries
        if artist:
            return f"{title} {artist}"[:100]
        return title[:100]
