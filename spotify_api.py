"""
Spotify API Client
Handles OAuth flow and all Spotify Web API calls.
"""

import os
import asyncio
import aiohttp
import urllib.parse
from typing import Optional, List, Dict, Any
import secrets


class SpotifyAPI:
    """
    Wraps the Spotify Web API.
    Uses Authorization Code Flow for OAuth.
    Caches search results to avoid duplicate API calls.
    """

    AUTH_URL = "https://accounts.spotify.com/authorize"
    TOKEN_URL = "https://accounts.spotify.com/api/token"
    API_BASE = "https://api.spotify.com/v1"

    SCOPES = [
        "playlist-read-private",
        "playlist-read-collaborative",
        "playlist-modify-public",
        "playlist-modify-private",
    ]

    def __init__(self):
        self.client_id = os.getenv("SPOTIFY_CLIENT_ID", "")
        self.client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "")
        self.redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8000/callback/spotify")
        self._access_token: Optional[str] = None
        self._search_cache: Dict[str, Any] = {}  # query -> result

    # ─── Auth ──────────────────────────────────────────────────────────────

    def get_auth_url(self) -> str:
        """Build Spotify OAuth authorization URL."""
        state = secrets.token_urlsafe(16)
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.SCOPES),
            "state": state,
        }
        return f"{self.AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for access/refresh tokens."""
        import base64
        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                },
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Token exchange failed: {text}")
            token_data = await resp.json()
            self._access_token = token_data["access_token"]
            return token_data

    def set_token(self, token: str):
        """Set access token directly (e.g., passed from frontend)."""
        self._access_token = token

    def is_authenticated(self) -> bool:
        return bool(self._access_token)

    # ─── Private helpers ───────────────────────────────────────────────────

    async def _get(self, endpoint: str, params: Dict = None) -> Any:
        """Make an authenticated GET request to Spotify API."""
        url = f"{self.API_BASE}{endpoint}"
        headers = {"Authorization": f"Bearer {self._access_token}"}
        async with aiohttp.ClientSession() as session:
            resp = await session.get(url, headers=headers, params=params or {})
            if resp.status == 429:
                # Rate limited - wait and retry
                retry_after = int(resp.headers.get("Retry-After", 2))
                await asyncio.sleep(retry_after)
                return await self._get(endpoint, params)
            if resp.status not in (200, 201):
                text = await resp.text()
                raise Exception(f"Spotify GET {endpoint} failed ({resp.status}): {text}")
            return await resp.json()

    async def _post(self, endpoint: str, json_body: Dict = None) -> Any:
        """Make an authenticated POST request to Spotify API."""
        url = f"{self.API_BASE}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession() as session:
            resp = await session.post(url, headers=headers, json=json_body or {})
            if resp.status == 429:
                retry_after = int(resp.headers.get("Retry-After", 2))
                await asyncio.sleep(retry_after)
                return await self._post(endpoint, json_body)
            if resp.status not in (200, 201):
                text = await resp.text()
                raise Exception(f"Spotify POST {endpoint} failed ({resp.status}): {text}")
            return await resp.json()

    # ─── Public API methods ────────────────────────────────────────────────

    async def get_playlists(self) -> List[Dict[str, Any]]:
        """Fetch all playlists for the authenticated user."""
        playlists = []
        endpoint = "/me/playlists"
        params = {"limit": 50, "offset": 0}

        while True:
            data = await self._get(endpoint, params)
            for item in data["items"]:
                playlists.append({
                    "id": item["id"],
                    "name": item["name"],
                    "track_count": item["tracks"]["total"],
                    "platform": "spotify",
                })
            if data["next"] is None:
                break
            params["offset"] += 50

        return playlists

    async def get_playlist_tracks(self, playlist_id: str) -> List[Dict[str, Any]]:
        """
        Fetch all tracks from a Spotify playlist with metadata.
        Paginates automatically through all pages.
        """
        tracks = []
        endpoint = f"/playlists/{playlist_id}/tracks"
        params = {"limit": 100, "offset": 0, "fields": "items,next,total"}

        while True:
            data = await self._get(endpoint, params)
            for item in data["items"]:
                track = item.get("track")
                if not track or track.get("is_local"):
                    continue  # skip local/unavailable tracks
                tracks.append({
                    "title": track["name"],
                    "artist": ", ".join(a["name"] for a in track["artists"]),
                    "album": track.get("album", {}).get("name", ""),
                    "duration_ms": track.get("duration_ms", 0),
                    "duration_s": track.get("duration_ms", 0) // 1000,
                    "uri": track["uri"],
                    "id": track["id"],
                })
            if data["next"] is None:
                break
            params["offset"] += 100

        return tracks

    async def search_track(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Search for a track on Spotify.
        Returns the top result with normalized metadata, or None.
        Results are cached to avoid duplicate API calls.
        """
        cache_key = query.lower().strip()
        if cache_key in self._search_cache:
            return self._search_cache[cache_key]

        try:
            data = await self._get("/search", {"q": query, "type": "track", "limit": 5})
            items = data.get("tracks", {}).get("items", [])
            if not items:
                self._search_cache[cache_key] = None
                return None

            # Return the top result
            track = items[0]
            result = {
                "title": track["name"],
                "artist": ", ".join(a["name"] for a in track["artists"]),
                "album": track.get("album", {}).get("name", ""),
                "duration_s": track.get("duration_ms", 0) // 1000,
                "uri": track["uri"],
                "id": track["id"],
            }
            self._search_cache[cache_key] = result
            return result
        except Exception:
            self._search_cache[cache_key] = None
            return None

    async def get_current_user(self) -> Dict[str, Any]:
        """Get current authenticated user's profile."""
        return await self._get("/me")

    async def create_playlist(self, user_id: str, name: str, description: str = "") -> str:
        """Create a new playlist and return its ID."""
        data = await self._post(
            f"/users/{user_id}/playlists",
            {"name": name, "description": description, "public": False},
        )
        return data["id"]

    async def add_tracks_to_playlist(self, playlist_id: str, track_uris: List[str]):
        """
        Add tracks to a Spotify playlist.
        Spotify allows max 100 URIs per request, so we batch.
        """
        for i in range(0, len(track_uris), 100):
            batch = track_uris[i:i + 100]
            await self._post(f"/playlists/{playlist_id}/tracks", {"uris": batch})
            await asyncio.sleep(0.3)  # polite delay
