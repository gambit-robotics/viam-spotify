# Spotify Module for Viam

A Viam service module for Spotify playback control with QR code authentication. Designed for kiosk displays and headless devices where browser-based OAuth isn't practical.

## Model

`gambit-robotics:service:spotify` - Spotify playback control service

### Requirements

- Spotify Premium account (required for playback control)
- Spotify Developer App (client ID only, no secret needed - uses PKCE)
- Device must be on same network as phone for QR auth

### Spotify Developer Setup

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new app
3. Add redirect URI: `http://<your-device-ip>:8888/callback`
4. Copy your **Client ID** (no secret needed)

> **Note:** This module uses [PKCE authentication](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow) which doesn't require a client secret. Each user authenticates with their own Spotify account and gets access to their own playlists, library, and playback.

### Attributes

| Attribute | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `client_id` | string | **Yes** | - | Spotify app client ID |
| `auth_port` | int | No | `8888` | Port for OAuth callback server |
| `token_path` | string | No | `/tmp/.spotify_token` | Path to store auth tokens |

### Example Configuration

```json
{
  "modules": [
    {
      "type": "registry",
      "name": "gambit_spotify",
      "module_id": "gambit-robotics:spotify"
    }
  ],
  "services": [
    {
      "name": "spotify",
      "namespace": "rdk",
      "type": "generic",
      "model": "gambit-robotics:service:spotify",
      "attributes": {
        "client_id": "your_spotify_client_id",
        "auth_port": 8888,
        "token_path": "/home/pi/.spotify_token"
      }
    }
  ]
}
```

## Features

- QR code authentication flow (scan with phone to authenticate)
- Full playback control (play, pause, skip, seek, volume, shuffle, repeat)
- Now playing info with album artwork and dominant colors
- Search (tracks, albums, artists, playlists)
- Library access (playlists, saved tracks, recently played)
- Device management and playback transfer
- Token persistence (survives restarts)

## Authentication Flow

1. Call `get_auth_status` to check if already authenticated
2. If not, call `get_auth_qr` to get a QR code image
3. Display QR code on your kiosk screen
4. User scans QR with phone and completes Spotify login
5. Poll `get_auth_status` until authenticated
6. Start using playback commands

```python
from viam.services.generic import Generic

spotify = Generic.from_robot(robot, "spotify")

# Check auth status
status = await spotify.do_command({"command": "get_auth_status"})
if not status["authenticated"]:
    # Get QR code for display
    auth = await spotify.do_command({"command": "get_auth_qr"})
    # auth["qr_image"] is base64 PNG
    # auth["auth_url"] is the URL encoded in QR
```

## API Reference

All commands are called via `do_command({"command": "...", ...})`.

### Authentication

| Command | Params | Returns |
|---------|--------|---------|
| `get_auth_qr` | - | `{qr_image: str, auth_url: str}` |
| `get_auth_status` | - | `{authenticated: bool, user: str}` |
| `logout` | - | `{success: bool}` |

### Playback Control

| Command | Params | Returns |
|---------|--------|---------|
| `play` | `uri?`, `device_id?` | `{success: bool}` |
| `pause` | - | `{success: bool}` |
| `next` | - | `{success: bool}` |
| `previous` | - | `{success: bool}` |
| `seek` | `position_ms: int` | `{success: bool}` |
| `set_volume` | `volume: int (0-100)` | `{success: bool}` |
| `shuffle` | `state: bool` | `{success: bool}` |
| `repeat` | `state: "track"/"context"/"off"` | `{success: bool}` |
| `add_to_queue` | `uri: str` | `{success: bool}` |

### Now Playing

| Command | Params | Returns |
|---------|--------|---------|
| `get_current_track` | - | See below |
| `get_queue` | - | `{queue: [{name, artist, artwork_url, uri}, ...]}` |

**`get_current_track` response:**
```json
{
  "is_playing": true,
  "name": "Track Name",
  "artist": "Artist Name",
  "album": "Album Name",
  "artwork_url": "https://i.scdn.co/image/...",
  "colors": ["#1a1a2e", "#e94560", "#0f3460"],
  "progress_ms": 45000,
  "duration_ms": 210000,
  "uri": "spotify:track:xxx"
}
```

### Search

| Command | Params | Returns |
|---------|--------|---------|
| `search` | `query: str`, `type?: str`, `limit?: int` | `{results: [...]}` |

Search types: `track` (default), `album`, `artist`, `playlist`

### Library

| Command | Params | Returns |
|---------|--------|---------|
| `get_playlists` | `limit?: int` | `{playlists: [{id, name, image_url}, ...]}` |
| `get_playlist_tracks` | `playlist_id: str` | `{tracks: [{name, artist, uri}, ...]}` |
| `get_saved_tracks` | `limit?: int` | `{tracks: [...]}` |
| `get_recently_played` | `limit?: int` | `{tracks: [...]}` |

### Devices

| Command | Params | Returns |
|---------|--------|---------|
| `get_devices` | - | `{devices: [{id, name, type, is_active}, ...]}` |
| `transfer_playback` | `device_id: str` | `{success: bool}` |

## Usage Examples

### Play a playlist
```python
await spotify.do_command({
    "command": "play",
    "uri": "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"
})
```

### Get current track for display
```python
track = await spotify.do_command({"command": "get_current_track"})
print(f"Now playing: {track['name']} by {track['artist']}")
print(f"Album art: {track['artwork_url']}")
print(f"Colors for UI: {track['colors']}")
```

### Search and play
```python
results = await spotify.do_command({
    "command": "search",
    "query": "bohemian rhapsody",
    "type": "track",
    "limit": 5
})
if results["results"]:
    await spotify.do_command({
        "command": "play",
        "uri": results["results"][0]["uri"]
    })
```

### Voice control integration
```python
# Works great with speech-to-text
spoken_query = "play some jazz music"
results = await spotify.do_command({
    "command": "search",
    "query": spoken_query,
    "type": "playlist"
})
```

## Local Development

```bash
# Clone the repository
git clone https://github.com/gambit-robotics/viam-spotify.git
cd viam-spotify

# Install dependencies
pip install -r requirements.txt

# Run locally
./exec.sh
```

## License

Apache 2.0
