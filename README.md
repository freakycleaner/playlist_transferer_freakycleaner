# 🎵 Playlist Transfer

Transfer playlists between **Spotify** and **YouTube Music** with intelligent fuzzy matching.

```
┌─────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   Spotify   │───▶│  FastAPI Backend  │───▶│  YouTube Music   │
│  Playlists  │    │  + Fuzzy Matcher  │    │   (ytmusicapi)   │
└─────────────┘    └──────────────────┘    └──────────────────┘
```

---

## Features

- ✅ **OAuth** login for Spotify; browser-headers auth for YouTube Music
- 🔍 **Fuzzy matching** using `rapidfuzz` (title + artist + duration scoring)
- 🧹 **Text normalization** strips "feat.", "remastered", "live", brackets, etc.
- 🚀 **Async** concurrent search requests with rate-limit handling
- 💾 **Search result caching** to avoid duplicate API calls
- 📊 **Detailed transfer report** (matched / skipped / confidence scores)
- 🖥️ **CLI** support for scripted transfers
- 🌐 **Clean web UI** — no frameworks needed

---

## Project Structure

```
playlist-transfer/
├── backend/
│   ├── main.py                  # FastAPI app + endpoints
│   ├── requirements.txt
│   ├── .env.example
│   ├── cli.py                   # CLI transfer tool
│   ├── api/
│   │   ├── spotify_api.py       # Spotify Web API client
│   │   └── ytmusic_api.py       # YouTube Music client (ytmusicapi wrapper)
│   ├── matching/
│   │   └── song_matcher.py      # Normalization + fuzzy matching logic
│   └── services/
│       └── transfer_service.py  # Orchestrates the full transfer workflow
└── frontend/
    └── index.html               # Single-page web UI
```

---

## Setup

### 1. Spotify Developer App

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new app
3. Set **Redirect URI** to `http://localhost:8000/callback/spotify`
4. Copy **Client ID** and **Client Secret**

### 2. Backend

```bash
cd backend

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and fill in your Spotify credentials

# Start the server
python main.py
# Server runs at http://localhost:8000
```

### 3. YouTube Music Auth

YouTube Music doesn't have an official public API, so we use
[ytmusicapi](https://ytmusicapi.readthedocs.io/) with browser cookie auth:

```bash
# In the backend directory (with venv active):
ytmusicapi browser
# Follow the prompts — paste your browser headers when asked
# This generates headers_auth.json
```

Then in the web UI, click **YouTube Music → Upload headers_auth.json**.

### 4. Frontend

Just open `frontend/index.html` in a browser:

```bash
open frontend/index.html
# or: python -m http.server 3000 (from frontend directory)
```

---

## Usage

### Web UI

1. Open `frontend/index.html`
2. Click **Spotify** → authorize in the popup
3. Click **YouTube Music** → upload your `headers_auth.json`
4. Select source platform and playlist
5. Select target platform
6. Click **Transfer Playlist**
7. View the detailed report

### CLI

```bash
cd backend
source venv/bin/activate

# Set credentials
export SPOTIFY_ACCESS_TOKEN="your_token_here"
export YTMUSIC_AUTH_FILE="headers_auth.json"

# Transfer from Spotify to YouTube Music
python cli.py --from spotify --to ytmusic --playlist "My Favorites"

# Transfer from YouTube Music to Spotify
python cli.py --from ytmusic --to spotify --playlist "Chill Vibes"
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/login/spotify` | Redirects to Spotify OAuth |
| `GET` | `/callback/spotify` | Handles OAuth callback |
| `GET` | `/login/ytmusic` | Returns YTMusic auth instructions |
| `POST` | `/login/ytmusic/upload` | Accepts headers JSON for YTMusic auth |
| `GET` | `/auth/status` | Check which platforms are connected |
| `GET` | `/get-playlists?source=spotify` | List playlists from a platform |
| `POST` | `/transfer-playlist` | Run a transfer and get report |
| `GET` | `/health` | Health check |

---

## Matching Algorithm

Songs are matched using a weighted confidence score:

```
confidence = title_similarity × 0.50
           + artist_similarity × 0.30
           + duration_closeness × 0.20
```

- **Text normalization**: lowercase, remove feat./live/remastered/brackets
- **Fuzzy similarity**: `rapidfuzz.token_sort_ratio` (handles word reordering)
- **Duration score**: 1.0 if diff ≤ 3s, 0.0 if diff > 10s
- **Threshold**: 80% confidence required to accept a match (configurable)

Songs below the threshold are skipped and reported with their best candidate.

---

## Configuration

In `backend/matching/song_matcher.py`:

```python
SongMatcher(confidence_threshold=0.80)  # default: 80%
```

Lower for more matches (higher false positive rate).
Higher for stricter matching (more songs skipped).

---

## Rate Limits

- **Spotify**: Automatically retries on 429 with `Retry-After` header
- **YouTube Music**: Batches playlist writes in groups of 50 with 0.5s delay
- **Concurrent searches**: Limited to 5 simultaneous requests via asyncio Semaphore
- **Search caching**: Identical queries served from in-memory cache

---

## Limitations

- YouTube Music uses an unofficial API (`ytmusicapi`) — may break with YT changes
- Some region-locked or unavailable songs will be skipped
- YTMusic auth requires manual browser header extraction (no OAuth)
- In-memory cache resets on server restart
