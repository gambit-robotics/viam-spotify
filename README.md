# Module spotify

Turns your device into a Spotify Connect speaker. Users connect from their Spotify app - no OAuth, no developer app required.

## Supported Platforms

- **Linux x64**
- **Linux ARM64**

## Models

This module provides the following models:

- [`gambit-robotics:service:spotify`](#model-gambit-roboticsservicespotify) - Spotify Connect playback control
- [`gambit-robotics:service:audio-discovery`](#model-gambit-roboticsserviceaudio-discovery) - Discover audio output devices

## Model gambit-robotics:service:spotify

### Configuration

The following attribute template can be used to configure this model:

```json
{
  "device_name": "<string>",
  "audio_device": "<string>",
  "audio_backend": "<string>",
  "api_port": <int>,
  "bitrate": <int>,
  "initial_volume": <int>
}
```

#### Configuration Attributes

The following attributes are available for the `gambit-robotics:service:spotify` model:

| Name | Type | Inclusion | Description |
|------|------|-----------|-------------|
| `device_name` | string | **Required** | Name shown in Spotify app (e.g., "Kitchen Speaker") |
| `audio_device` | string | Optional | Audio device/sink name. Default: `default` |
| `audio_backend` | string | Optional | Audio backend: `pulseaudio` (recommended) or `alsa`. Default: `pulseaudio` |
| `api_port` | int | Optional | Port for go-librespot API. Default: `3678` |
| `bitrate` | int | Optional | Audio bitrate (96, 160, or 320 kbps). Default: `320` |
| `initial_volume` | int | Optional | Initial volume (0-100). Default: `50` |

#### Requirements

- Spotify Premium account (required for Spotify Connect)
- Audio output device (speakers, DAC, etc.)
- PulseAudio or PipeWire (default on Debian Trixie / Raspberry Pi OS)

### do_command()

All commands are called via `do_command({"command": "...", ...})`.

#### Status Commands

| Command | Params | Returns |
|---------|--------|---------|
| `get_status` | - | Full player state |
| `get_current_track` | - | Track info with album art colors |

#### Playback Commands

| Command | Params | Returns |
|---------|--------|---------|
| `play` | `uri?` | `{success: bool}` |
| `pause` | - | `{success: bool}` |
| `toggle_playback` | - | `{success: bool}` |
| `next` | - | `{success: bool}` |
| `previous` | - | `{success: bool}` |
| `seek` | `position_ms: int` | `{success: bool}` |
| `set_volume` | `volume: int (0-100)` | `{success: bool}` |
| `shuffle` | `state: bool` | `{success: bool}` |
| `repeat` | `state: "track"/"context"/"off"` | `{success: bool}` |
| `add_to_queue` | `uri: str` | `{success: bool}` |
| `play_uri` | `uri: str`, `skip_to_uri?: str` | `{success: bool}` |
| `get_queue` | - | `{queue: [{name, artist, uri}, ...]}` |

## Model gambit-robotics:service:audio-discovery

Discovers available audio output devices and provides suggested Spotify configurations.

### Configuration

The following attribute template can be used to configure this model:

```json
{}
```

#### Configuration Attributes

No configuration attributes required.

### discover_resources()

Call `discover_resources()` to get suggested Spotify configurations for each detected audio device.

---

## How It Works

```
┌─────────────────────┐     HTTP/WS      ┌──────────────────┐
│  Viam SpotifyService│<────────────────>│   go-librespot   │
│  (Python)           │                  │   (subprocess)   │
└─────────────────────┘                  └──────────────────┘
                                                  │
                                                  │ Spotify Connect
                                                  v
                                         ┌──────────────────┐
                                         │  User's Phone    │
                                         │  (Spotify App)   │
                                         └──────────────────┘
```

The module runs [go-librespot](https://github.com/devgianlu/go-librespot) as a subprocess, which implements the Spotify Connect protocol. Your device appears as a speaker in the Spotify app, just like a Sonos or Chromecast.

**No Spotify Developer App needed!**

## User Flow

1. **Module starts** - go-librespot subprocess launches
2. **Device advertises** - Appears on local network via Zeroconf/mDNS
3. **User opens Spotify** - On phone, tablet, or desktop
4. **User taps device** - In "Devices Available" list
5. **First connection** - Credentials stored for future sessions
6. **Music plays** - Through your device's speakers

## API Response Examples

**`get_status` response:**
```json
{
  "active": true,
  "device_id": "abc123",
  "device_name": "Kitchen Chef",
  "username": "spotify_user_id",
  "device_type": "SPEAKER",
  "play_origin": "playlist",
  "buffering": false,
  "volume_steps": 64,
  "is_playing": true,
  "volume": 75,
  "shuffle": false,
  "repeat_track": false,
  "repeat_context": false,
  "progress_ms": 45000,
  "duration_ms": 210000,
  "uri": "spotify:track:xxx",
  "name": "Track Name",
  "artist": "Artist Name",
  "album": "Album Name",
  "artwork_url": "https://i.scdn.co/image/...",
  "release_date": "2023-05-12",
  "track_number": 3,
  "disc_number": 1
}
```

**`get_current_track` response:**
```json
{
  "is_playing": true,
  "buffering": false,
  "name": "Track Name",
  "artist": "Artist Name",
  "album": "Album Name",
  "artwork_url": "https://i.scdn.co/image/...",
  "colors": ["#1a1a2e", "#e94560", "#0f3460"],
  "progress_ms": 45000,
  "duration_ms": 210000,
  "uri": "spotify:track:xxx",
  "release_date": "2023-05-12",
  "track_number": 3,
  "disc_number": 1
}
```

## Usage Examples

### Basic playback control

```python
from viam.services.generic import Generic

spotify = Generic.from_robot(robot, "spotify")

# Get current track
track = await spotify.do_command({"command": "get_current_track"})
print(f"Now playing: {track['name']} by {track['artist']}")

# Pause/resume
await spotify.do_command({"command": "pause"})
await spotify.do_command({"command": "play"})

# Skip tracks
await spotify.do_command({"command": "next"})
await spotify.do_command({"command": "previous"})

# Volume control
await spotify.do_command({"command": "set_volume", "volume": 75})
```

### Play a specific album or playlist

```python
# Play an album
await spotify.do_command({
    "command": "play_uri",
    "uri": "spotify:album:4aawyAB9vmqN3uQ7FjRGTy"
})

# Play a playlist
await spotify.do_command({
    "command": "play_uri",
    "uri": "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"
})
```

### Kiosk display with dynamic colors

```python
import asyncio

async def display_loop():
    while True:
        track = await spotify.do_command({"command": "get_current_track"})

        if track.get("is_playing"):
            print(f"Now playing: {track['name']}")
            print(f"By: {track['artist']}")
            print(f"Album: {track['album']}")
            print(f"UI Colors: {track['colors']}")  # For dynamic theming

        await asyncio.sleep(1)
```

## Development

### Local Setup

```bash
# Clone the repository
git clone https://github.com/gambit-robotics/viam-spotify.git
cd viam-spotify

# Setup for development
make setup-dev

# Run locally
make run
```

### Make Commands

| Command | Description |
|---------|-------------|
| `make setup` | Install production dependencies |
| `make setup-dev` | Install dev dependencies (includes linting, testing) |
| `make run` | Run the module locally |
| `make test` | Run tests |
| `make lint` | Check code style |
| `make lint-fix` | Auto-fix code style issues |
| `make typecheck` | Run type checking |
| `make build` | Build module tarball |
| `make clean` | Remove build artifacts |

## Troubleshooting

### Device doesn't appear in Spotify app

1. Check that go-librespot is running: `ps aux | grep go-librespot`
2. Verify Zeroconf/mDNS is working: `avahi-browse -a` (Linux)
3. Ensure device and phone are on the same network

### No audio

1. Use the discovery service to find available audio devices (see Audio Discovery section)
2. Check PulseAudio/PipeWire is running: `pactl info`
3. List available sinks: `pactl list sinks short`
4. Test audio: `paplay /usr/share/sounds/alsa/Front_Center.wav`

**Note:** Raspberry Pi OS Lite doesn't include PulseAudio. Set `audio_backend: alsa` in config.

### Connection drops

- Credentials are stored in `~/.config/go-librespot/`
- Delete `~/.config/go-librespot/state.json` to force re-authentication
- Check network stability

## Known Limitations

- **Spotify Premium required** - Free accounts don't support Spotify Connect
- **No search/browse/library access** - This module uses the Spotify Connect protocol (go-librespot), not the Spotify Web API. You can control playback (play, pause, skip, volume, etc.) and play any URI if you know it, but you cannot search for tracks or access user playlists. Users search on their phone and cast to the device - same model as Sonos or Chromecast.
- **Protocol changes** - Spotify can break librespot (rare, usually fixed quickly)
- **Linux only** - This module only supports Linux (x64 and ARM64)

## Roadmap / TODO

### Search for URIs

Currently, users must know the Spotify URI to play specific content. A search feature would allow looking up tracks, albums, and playlists by name.

**Why it's not built-in:** [go-librespot](https://github.com/devgianlu/go-librespot) only implements the Spotify Connect protocol (playback control). It has no search endpoint - see the [API spec](https://github.com/devgianlu/go-librespot/blob/master/api-spec.yml).

**Implementation approach:** Use the [Spotify Web API](https://developer.spotify.com/documentation/web-api) search endpoint:

```
GET https://api.spotify.com/v1/search?q={query}&type=track,album,playlist
```

**Requirements:**
- Create a [Spotify Developer App](https://developer.spotify.com/dashboard) to get `client_id` and `client_secret`
- Implement [Client Credentials Flow](https://developer.spotify.com/documentation/web-api/tutorials/client-credentials-flow) for OAuth 2.0 token
- Add new config attributes: `spotify_client_id`, `spotify_client_secret`
- Add new commands: `search_tracks`, `search_albums`, `search_playlists`

**Example response structure:**
```json
{
  "command": "search_tracks",
  "query": "bohemian rhapsody",
  "results": [
    {"name": "Bohemian Rhapsody", "artist": "Queen", "uri": "spotify:track:4u7EnebtmKWzUH433cf5Qv"},
    ...
  ]
}
```

**Note:** As of [November 2024](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api), some Web API endpoints (recommendations, audio features) are restricted for new apps, but the search endpoint remains available.

## License

Apache 2.0
