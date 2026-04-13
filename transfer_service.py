"""
Transfer Service
Orchestrates the full playlist transfer workflow:
  1. Fetch source tracks
  2. Search each on target platform
  3. Fuzzy-match results
  4. Create new playlist and add matched tracks
  5. Return detailed report
"""

import asyncio
from typing import Dict, Any, List

from api.spotify_api import SpotifyAPI
from api.ytmusic_api import YTMusicAPI
from matching.song_matcher import SongMatcher


class TransferService:
    """
    High-level transfer orchestrator.
    Separates concerns: source fetch, matching, target write.
    """

    def __init__(
        self,
        spotify: SpotifyAPI,
        ytmusic: YTMusicAPI,
        matcher: SongMatcher,
        max_concurrent_searches: int = 5,
    ):
        self.spotify = spotify
        self.ytmusic = ytmusic
        self.matcher = matcher
        # Semaphore limits concurrent API search calls to avoid rate limits
        self._sem = asyncio.Semaphore(max_concurrent_searches)

    # ─── Internal Helpers ──────────────────────────────────────────────────

    async def _search_and_match(
        self,
        source_track: Dict[str, Any],
        target: str,
    ) -> Dict[str, Any]:
        """
        Search for source_track on target platform, then fuzzy-match the top result.
        Returns a result dict with match status, scores, and track IDs.
        """
        query = self.matcher.build_search_query(source_track)

        async with self._sem:
            if target == "spotify":
                candidate = await self.spotify.search_track(query)
            else:
                candidate = await self.ytmusic.search_track(query)

        if candidate is None:
            return {
                "source": source_track,
                "matched": False,
                "reason": "No search results found",
                "candidate": None,
                "scores": {},
            }

        matched, confidence, breakdown = self.matcher.is_match(source_track, candidate)

        return {
            "source": source_track,
            "matched": matched,
            "reason": "Confidence below threshold" if not matched else "OK",
            "candidate": candidate,
            "confidence": confidence,
            "scores": breakdown,
        }

    # ─── Main Transfer ─────────────────────────────────────────────────────

    async def transfer(
        self,
        source: str,
        target: str,
        playlist_id: str,
        playlist_name: str,
    ) -> Dict[str, Any]:
        """
        Full transfer flow.

        Returns a report dict containing:
          - total: int
          - transferred: int
          - skipped: int
          - transferred_songs: list
          - skipped_songs: list
          - new_playlist_id: str
        """

        # ── Step 1: Fetch source tracks ──────────────────────────────────
        print(f"[Transfer] Fetching tracks from {source} playlist '{playlist_name}'...")
        if source == "spotify":
            source_tracks = await self.spotify.get_playlist_tracks(playlist_id)
        else:
            source_tracks = await self.ytmusic.get_playlist_tracks(playlist_id)

        print(f"[Transfer] Found {len(source_tracks)} tracks")

        if not source_tracks:
            return {
                "total": 0,
                "transferred": 0,
                "skipped": 0,
                "transferred_songs": [],
                "skipped_songs": [],
                "new_playlist_id": None,
                "error": "Source playlist is empty",
            }

        # ── Step 2: Search & match all tracks concurrently ───────────────
        print(f"[Transfer] Searching on {target}...")
        tasks = [
            self._search_and_match(track, target)
            for track in source_tracks
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # ── Step 3: Separate matched from skipped ────────────────────────
        transferred_songs = []
        skipped_songs = []
        track_ids = []  # IDs/URIs to add to new playlist

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                # Unexpected error for this track - mark as skipped
                skipped_songs.append({
                    "source": source_tracks[i],
                    "reason": f"Error: {str(result)}",
                })
                continue

            if result["matched"] and result["candidate"]:
                transferred_songs.append(result)
                candidate = result["candidate"]
                if target == "spotify":
                    track_ids.append(candidate["uri"])
                else:
                    track_ids.append(candidate["video_id"])
            else:
                skipped_songs.append({
                    "source": result["source"],
                    "reason": result.get("reason", "No match"),
                    "best_candidate": result.get("candidate"),
                    "confidence": result.get("confidence", 0),
                })

        # ── Step 4: Create target playlist ───────────────────────────────
        new_playlist_name = f"{playlist_name} (from {source.title()})"
        new_playlist_id = None

        if track_ids:
            print(f"[Transfer] Creating playlist '{new_playlist_name}' on {target}...")
            if target == "spotify":
                user = await self.spotify.get_current_user()
                user_id = user["id"]
                new_playlist_id = await self.spotify.create_playlist(
                    user_id,
                    new_playlist_name,
                    description=f"Transferred from {source.title()} by PlaylistTransfer",
                )
                await self.spotify.add_tracks_to_playlist(new_playlist_id, track_ids)
            else:
                new_playlist_id = await self.ytmusic.create_playlist(
                    new_playlist_name,
                    description=f"Transferred from {source.title()} by PlaylistTransfer",
                )
                await self.ytmusic.add_tracks_to_playlist(new_playlist_id, track_ids)

        print(f"[Transfer] Done! {len(transferred_songs)} transferred, {len(skipped_songs)} skipped")

        # ── Step 5: Build report ─────────────────────────────────────────
        return {
            "total": len(source_tracks),
            "transferred": len(transferred_songs),
            "skipped": len(skipped_songs),
            "new_playlist_id": new_playlist_id,
            "new_playlist_name": new_playlist_name,
            "transferred_songs": [
                {
                    "title": r["source"]["title"],
                    "artist": r["source"]["artist"],
                    "matched_title": r["candidate"]["title"],
                    "matched_artist": r["candidate"]["artist"],
                    "confidence": round(r.get("confidence", 0) * 100, 1),
                }
                for r in transferred_songs
            ],
            "skipped_songs": [
                {
                    "title": s["source"]["title"],
                    "artist": s["source"]["artist"],
                    "reason": s["reason"],
                    "best_match": s.get("best_candidate", {}).get("title") if s.get("best_candidate") else None,
                    "confidence": round(s.get("confidence", 0) * 100, 1),
                }
                for s in skipped_songs
            ],
        }
