"""
Playlist Transfer App - Main FastAPI Application
Transfers playlists between Spotify and YouTube Music
"""

import os
import asyncio
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional
import uvicorn

from api.spotify_api import SpotifyAPI
from api.ytmusic_api import YTMusicAPI
from services.transfer_service import TransferService
from matching.song_matcher import SongMatcher

app = FastAPI(title="Playlist Transfer API", version="1.0.0")

# Allow frontend to call backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Instantiate API clients (singletons)
spotify_api = SpotifyAPI()
ytmusic_api = YTMusicAPI()
song_matcher = SongMatcher()
transfer_service = TransferService(spotify_api, ytmusic_api, song_matcher)


# ─── Auth Endpoints ──────────────────────────────────────────────────────────

@app.get("/login/spotify")
async def login_spotify():
    """Redirect user to Spotify OAuth authorization page."""
    auth_url = spotify_api.get_auth_url()
    return RedirectResponse(url=auth_url)


@app.get("/callback/spotify")
async def spotify_callback(code: str = Query(...), state: str = Query(None)):
    """Handle Spotify OAuth callback and exchange code for token."""
    try:
        token_info = await spotify_api.exchange_code(code)
        # In production, store token in session/DB. Here we return it for frontend to store.
        return JSONResponse({
            "status": "success",
            "message": "Spotify connected successfully",
            "access_token": token_info["access_token"],
            "expires_in": token_info.get("expires_in", 3600),
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Spotify auth failed: {str(e)}")


@app.get("/login/ytmusic")
async def login_ytmusic():
    """
    YouTube Music uses browser-cookie auth (ytmusicapi).
    Returns instructions for setting up ytmusicapi headers auth.
    """
    return {
        "status": "info",
        "message": "YouTube Music authentication requires browser headers.",
        "instructions": (
            "Run `ytmusicapi browser` in terminal and follow instructions, "
            "then upload the generated headers_auth.json file via /login/ytmusic/upload"
        ),
    }


@app.post("/login/ytmusic/upload")
async def upload_ytmusic_headers(headers_json: dict):
    """Accept YouTube Music auth headers JSON from the frontend."""
    try:
        success = ytmusic_api.setup_from_headers(headers_json)
        if success:
            return {"status": "success", "message": "YouTube Music connected successfully"}
        raise HTTPException(status_code=400, detail="Invalid headers format")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/auth/status")
async def auth_status():
    """Check which services are currently authenticated."""
    return {
        "spotify": spotify_api.is_authenticated(),
        "ytmusic": ytmusic_api.is_authenticated(),
    }


# ─── Playlist Endpoints ───────────────────────────────────────────────────────

@app.get("/get-playlists")
async def get_playlists(
    source: str = Query(..., description="'spotify' or 'ytmusic'"),
    spotify_token: Optional[str] = Query(None, description="Spotify access token"),
):
    """Fetch all playlists from the specified source platform."""
    try:
        if source == "spotify":
            if spotify_token:
                spotify_api.set_token(spotify_token)
            if not spotify_api.is_authenticated():
                raise HTTPException(status_code=401, detail="Spotify not authenticated")
            playlists = await spotify_api.get_playlists()
        elif source == "ytmusic":
            if not ytmusic_api.is_authenticated():
                raise HTTPException(status_code=401, detail="YouTube Music not authenticated")
            playlists = await ytmusic_api.get_playlists()
        else:
            raise HTTPException(status_code=400, detail="source must be 'spotify' or 'ytmusic'")

        return {"source": source, "playlists": playlists}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Transfer Endpoint ────────────────────────────────────────────────────────

class TransferRequest(BaseModel):
    source: str          # "spotify" or "ytmusic"
    target: str          # "spotify" or "ytmusic"
    playlist_id: str     # platform playlist ID
    playlist_name: str   # human-readable name
    spotify_token: Optional[str] = None  # pass token from frontend


@app.post("/transfer-playlist")
async def transfer_playlist(request: TransferRequest):
    """
    Transfer a playlist from source to target platform.
    Returns a detailed report of matched/skipped songs.
    """
    if request.source == request.target:
        raise HTTPException(status_code=400, detail="Source and target must be different")

    if request.source not in ("spotify", "ytmusic") or request.target not in ("spotify", "ytmusic"):
        raise HTTPException(status_code=400, detail="Invalid source or target platform")

    # Set Spotify token if provided
    if request.spotify_token:
        spotify_api.set_token(request.spotify_token)

    # Validate auth
    if request.source == "spotify" and not spotify_api.is_authenticated():
        raise HTTPException(status_code=401, detail="Spotify not authenticated")
    if request.source == "ytmusic" and not ytmusic_api.is_authenticated():
        raise HTTPException(status_code=401, detail="YouTube Music not authenticated")
    if request.target == "spotify" and not spotify_api.is_authenticated():
        raise HTTPException(status_code=401, detail="Spotify not authenticated")
    if request.target == "ytmusic" and not ytmusic_api.is_authenticated():
        raise HTTPException(status_code=401, detail="YouTube Music not authenticated")

    try:
        report = await transfer_service.transfer(
            source=request.source,
            target=request.target,
            playlist_id=request.playlist_id,
            playlist_name=request.playlist_name,
        )
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Health Check ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
