# Spotify Connect Module for Viam

A Viam service module that turns your device into a **Spotify Connect speaker**. Users connect from their Spotify app - no OAuth, no developer app required.

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

## Models

| Model | API | Description |
|-------|-----|-------------|
| `gambit-robotics:service:spotify` | `rdk:service:generic` | Spotify Connect playback control service |
| `gambit-robotics:service:audio-discovery` | `rdk:service:discovery` | Discover audio output devices for configuration |

### Requirements

- Spotify Premium account (required for Spotify Connect)
- Audio output device (speakers, DAC, etc.)
- PulseAudio or PipeWire (default on Debian Trixie / Raspberry Pi OS) - allows coexistence with other audio modules like [system-audio](https://github.com/viam-modules/system-audio)

**No Spotify Developer App needed!**

## Configuration

| Attribute | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `device_name` | string | **Yes** | - | Name shown in Spotify app (e.g., "Kitchen Speaker") |
| `api_port` | int | No | `3678` | Port for go-librespot API |
| `audio_backend` | string | No | `pulseaudio` | Audio backend: `pulseaudio` (recommended) or `alsa` |
| `audio_device` | string | No | `default` | Audio device/sink name |
| `bitrate` | int | No | `320` | Audio bitrate (96, 160, or 320 kbps) |
| `initial_volume` | int | No | `50` | Initial volume (0-100) |

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
        "device_name": "Kitchen Chef",
        "audio_device": "default",
        "bitrate": 320,
        "initial_volume": 50
      }
    }
  ]
}
```

## Audio Discovery

The module includes a discovery service to help identify available audio devices on your system. This is useful for finding the correct `audio_device` value for your configuration.

### Using Discovery

Add the discovery service to your configuration:

```json
{
  "services": [
    {
      "name": "audio-discovery",
      "namespace": "rdk",
      "type": "discovery",
      "model": "gambit-robotics:service:audio-discovery"
    }
  ]
}
```

Then use `discover_resources()` to get suggested Spotify configurations for each audio device:

```python
from viam.services.discovery import Discovery

discovery = Discovery.from_robot(robot, "audio-discovery")
configs = await discovery.discover_resources()

for config in configs:
    print(f"Device: {config.attributes['_description']}")
    print(f"  audio_backend: {config.attributes['audio_backend']}")
    print(f"  audio_device: {config.attributes['audio_device']}")
```

### Discovery Commands

| Command | Description |
|---------|-------------|
| `get_backend` | Returns detected audio backend (`pipewire`, `pulseaudio`, or `alsa`) |
| `list_sinks` | List PulseAudio/PipeWire sinks with details |
| `list_alsa` | List ALSA devices |

```python
# Check which audio backend is available
result = await discovery.do_command({"command": "get_backend"})
print(f"Audio backend: {result['backend']}")
```

## User Flow

1. **Module starts** - go-librespot subprocess launches
2. **Device advertises** - Appears on local network via Zeroconf/mDNS
3. **User opens Spotify** - On phone, tablet, or desktop
4. **User taps device** - In "Devices Available" list
5. **First connection** - Credentials stored for future sessions
6. **Music plays** - Through your device's speakers

No QR codes, no OAuth, no developer dashboard. Just connect and play.

## API Reference

All commands are called via `do_command({"command": "...", ...})`.

### Status

| Command | Params | Returns |
|---------|--------|---------|
| `get_status` | - | Full player state (see below) |
| `get_current_track` | - | Track info with album art colors |

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

### Playback Control

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

### Queue

| Command | Params | Returns |
|---------|--------|---------|
| `get_queue` | - | `{queue: [{name, artist, uri}, ...]}` |

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

### CI/CD

This module uses GitHub Actions for continuous integration and deployment:

- **checks.yml** - Runs linting and type checking on PRs
- **build.yml** - Builds module on PRs and pushes to main
- **deploy.yml** - Deploys to Viam Registry on release

To deploy a new version:
1. Create a GitHub release with a semantic version tag (e.g., `v1.0.0`)
2. The deploy workflow automatically builds and uploads to the Viam Registry

**Required secrets:**
- `VIAM_KEY_ID` - Organization API key ID
- `VIAM_KEY_VALUE` - Organization API key value

Generate keys with:
```bash
viam organizations list  # Get your org ID
viam organization api-key create --org-id YOUR_ORG_ID --name github-actions
```

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
- **Linux only** - go-librespot pre-built binaries are only available for Linux. The module will start on macOS but playback won't work without building go-librespot from source.

## License

Apache 2.0
