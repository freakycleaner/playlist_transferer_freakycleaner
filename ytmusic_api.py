"""
YouTube Music API Client
Wraps ytmusicapi (unofficial) for playlist operations.
Auth uses browser-cookie headers JSON file.
"""

import asyncio
import json
import os
from typing import Optional, List, Dict, Any
from functools import lru_cache


class YTMusicAPI:
    """
    Wraps ytmusicapi for YouTube Music operations.

    ytmusicapi is synchronous, so we run it in a thread pool executor
    to keep FastAPI's async event loop unblocked.
    """

    def __init__(self):
        self._ytm = None  # YTMusic client instance
        self._headers_data: Optional[Dict] = None
        self._search_cache: Dict[str, Any] = {}

    # ─── Auth ──────────────────────────────────────────────────────────────

    def setup_from_headers(self, headers_json: dict) -> bool:
        """
        Initialize ytmusicapi from browser headers JSON.
        This is the auth method for ytmusicapi (no official OAuth).
        """
        try:
            from ytmusicapi import YTMusic
            # Write headers to a temp file (ytmusicapi expects file path or dict)
            self._ytm = YTMusic(auth=headers_json)
            self._headers_data = headers_json
            return True
        except Exception as e:
            print(f"YTMusic setup error: {e}")
            return False

    def setup_from_file(self, filepath: str = "headers_auth.json") -> bool:
        """Initialize from a headers_auth.json file on disk."""
        try:
            from ytmusicapi import YTMusic
            self._ytm = YTMusic(filepath)
            return True
        except Exception as e:
            print(f"YTMusic file setup error: {e}")
            # Try unauthenticated (read-only search still works)
            try:
                from ytmusicapi import YTMusic
                self._ytm = YTMusic()
                return True
            except Exception:
                return False

    def is_authenticated(self) -> bool:
        return self._ytm is not None

    # ─── Private helpers ───────────────────────────────────────────────────

    async def _run_sync(self, func, *args, **kwargs):
        """Run a synchronous ytmusicapi call in a thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    def _parse_duration(self, duration_str: Optional[str]) -> int:
        """
        Convert duration string '3:45' or '1:03:45' to seconds.
        Returns 0 if not parseable.
        """
        if not duration_str:
            return 0
        parts = duration_str.strip().split(":")
        try:
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except ValueError:
            pass
        return 0

    # ─── Public API methods ────────────────────────────────────────────────

    async def get_playlists(self) -> List[Dict[str, Any]]:
        """Fetch all library playlists for authenticated YTMusic user."""
        raw = await self._run_sync(self._ytm.get_library_playlists, limit=100)
        playlists = []
        for item in raw:
            playlists.append({
                "id": item.get("playlistId", ""),
                "name": item.get("title", "Untitled"),
                "track_count": item.get("count", 0),
                "platform": "ytmusic",
            })
        return playlists

    async def get_playlist_tracks(self, playlist_id: str) -> List[Dict[str, Any]]:
        """
        Fetch all tracks from a YouTube Music playlist.
        Handles pagination and normalizes metadata.
        """
        raw = await self._run_sync(self._ytm.get_playlist, playlistId=playlist_id, limit=500)
        tracks_raw = raw.get("tracks", [])
        tracks = []

        for item in tracks_raw:
            # Extract artist name(s)
            artists = item.get("artists", [])
            artist_str = ", ".join(a.get("name", "") for a in artists if a.get("name"))

            # Duration
            duration_s = self._parse_duration(item.get("duration"))

            tracks.append({
                "title": item.get("title", ""),
                "artist": artist_str,
                "album": item.get("album", {}).get("name", "") if item.get("album") else "",
                "duration_s": duration_s,
                "duration_ms": duration_s * 1000,
                "id": item.get("videoId", ""),
            })

        return tracks

    async def search_track(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Search for a song on YouTube Music.
        Returns the top song result with metadata, or None.
        Caches results to avoid duplicate API calls.
        """
        cache_key = query.lower().strip()
        if cache_key in self._search_cache:
            return self._search_cache[cache_key]

        try:
            # Search specifically in 'songs' category for best results
            results = await self._run_sync(
                self._ytm.search, query=query, filter="songs", limit=5
            )
            if not results:
                self._search_cache[cache_key] = None
                return None

            top = results[0]
            artists = top.get("artists", [])
            artist_str = ", ".join(a.get("name", "") for a in artists if a.get("name"))
            duration_s = self._parse_duration(top.get("duration"))

            result = {
                "title": top.get("title", ""),
                "artist": artist_str,
                "album": top.get("album", {}).get("name", "") if top.get("album") else "",
                "duration_s": duration_s,
                "video_id": top.get("videoId", ""),
            }
            self._search_cache[cache_key] = result
            return result
        except Exception as e:
            print(f"YTMusic search error: {e}")
            self._search_cache[cache_key] = None
            return None

    async def create_playlist(self, name: str, description: str = "") -> str:
        """Create a new YTMusic playlist and return its ID."""
        result = await self._run_sync(
            self._ytm.create_playlist,
            title=name,
            description=description,
            privacy_status="PRIVATE",
        )
        # create_playlist returns the playlist ID string
        return result if isinstance(result, str) else result.get("playlistId", "")

    async def add_tracks_to_playlist(self, playlist_id: str, video_ids: List[str]):
        """
        Add tracks to a YouTube Music playlist.
        Batches into groups of 50 to stay within limits.
        """
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i + 50]
            await self._run_sync(
                self._ytm.add_playlist_items,
                playlistId=playlist_id,
                videoIds=batch,
            )
            await asyncio.sleep(0.5)  # polite delay between batches
