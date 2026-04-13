#!/usr/bin/env python3
"""
CLI Tool for Playlist Transfer
Usage: python cli.py --from spotify --to ytmusic --playlist "My Playlist"

Requires environment variables:
  SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
  YTMusic: headers_auth.json in current directory
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


async def run_transfer(source: str, target: str, playlist_name: str):
    """Main async transfer routine for CLI use."""
    # Import here to allow running without starting the full FastAPI server
    sys.path.insert(0, str(Path(__file__).parent))
    from api.spotify_api import SpotifyAPI
    from api.ytmusic_api import YTMusicAPI
    from matching.song_matcher import SongMatcher
    from services.transfer_service import TransferService

    spotify = SpotifyAPI()
    ytmusic = YTMusicAPI()
    matcher = SongMatcher()
    service = TransferService(spotify, ytmusic, matcher)

    # ── Auth Setup ────────────────────────────────────────────────────────
    if source == "spotify" or target == "spotify":
        token = os.getenv("SPOTIFY_ACCESS_TOKEN")
        if not token:
            print("ERROR: Set SPOTIFY_ACCESS_TOKEN env variable for Spotify access.")
            print("You can get a token from https://developer.spotify.com/console/")
            sys.exit(1)
        spotify.set_token(token)

    if source == "ytmusic" or target == "ytmusic":
        auth_file = os.getenv("YTMUSIC_AUTH_FILE", "headers_auth.json")
        if not Path(auth_file).exists():
            print(f"ERROR: YouTube Music auth file not found: {auth_file}")
            print("Run `ytmusicapi browser` to generate it.")
            sys.exit(1)
        success = ytmusic.setup_from_file(auth_file)
        if not success:
            print("ERROR: Failed to authenticate with YouTube Music.")
            sys.exit(1)

    # ── Fetch Playlists ───────────────────────────────────────────────────
    print(f"\n🎵 Fetching playlists from {source}...")
    if source == "spotify":
        playlists = await spotify.get_playlists()
    else:
        playlists = await ytmusic.get_playlists()

    # Find matching playlist by name (case-insensitive)
    matched_playlist = next(
        (p for p in playlists if p["name"].lower() == playlist_name.lower()),
        None
    )

    if not matched_playlist:
        print(f"\nERROR: Playlist '{playlist_name}' not found on {source}.")
        print("\nAvailable playlists:")
        for p in playlists:
            print(f"  - {p['name']} ({p['track_count']} tracks)")
        sys.exit(1)

    print(f"✓ Found playlist: '{matched_playlist['name']}' ({matched_playlist['track_count']} tracks)")

    # ── Run Transfer ──────────────────────────────────────────────────────
    print(f"\n🔄 Transferring to {target}...\n")
    report = await service.transfer(
        source=source,
        target=target,
        playlist_id=matched_playlist["id"],
        playlist_name=matched_playlist["name"],
    )

    # ── Print Report ──────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  TRANSFER REPORT")
    print("═" * 60)
    print(f"  Total songs:       {report['total']}")
    print(f"  ✓ Transferred:     {report['transferred']}")
    print(f"  ✗ Skipped:         {report['skipped']}")
    print(f"  New playlist ID:   {report.get('new_playlist_id', 'N/A')}")
    print("═" * 60)

    if report["transferred_songs"]:
        print("\n✓ TRANSFERRED:")
        for s in report["transferred_songs"]:
            print(f"  [{s['confidence']}%] {s['title']} - {s['artist']}")
            print(f"         → {s['matched_title']} - {s['matched_artist']}")

    if report["skipped_songs"]:
        print("\n✗ SKIPPED:")
        for s in report["skipped_songs"]:
            print(f"  {s['title']} - {s['artist']}")
            print(f"    Reason: {s['reason']}")
            if s.get("best_match"):
                print(f"    Best match ({s['confidence']}%): {s['best_match']}")

    print(f"\n✅ Done! New playlist created on {target}.")


def main():
    parser = argparse.ArgumentParser(
        description="Transfer playlists between Spotify and YouTube Music",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py --from spotify --to ytmusic --playlist "My Favorites"
  python cli.py --from ytmusic --to spotify --playlist "Chill Vibes"

Environment Variables:
  SPOTIFY_ACCESS_TOKEN    Required for Spotify (get from Spotify Developer Console)
  YTMUSIC_AUTH_FILE       Path to headers_auth.json (default: headers_auth.json)
        """,
    )
    parser.add_argument(
        "--from", dest="source", required=True,
        choices=["spotify", "ytmusic"],
        help="Source platform"
    )
    parser.add_argument(
        "--to", dest="target", required=True,
        choices=["spotify", "ytmusic"],
        help="Target platform"
    )
    parser.add_argument(
        "--playlist", required=True,
        help="Name of the playlist to transfer"
    )

    args = parser.parse_args()

    if args.source == args.target:
        print("ERROR: Source and target must be different platforms.")
        sys.exit(1)

    asyncio.run(run_transfer(args.source, args.target, args.playlist))


if __name__ == "__main__":
    main()
