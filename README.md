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

## Model

`gambit-robotics:service:spotify` - Spotify Connect playback control service

### Requirements

- Spotify Premium account (required for Spotify Connect)
- Audio output device (speakers, DAC, etc.)
- PulseAudio (default on Raspberry Pi OS) - allows coexistence with other audio modules like [viam-labs/speech](https://github.com/viam-labs/speech)

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
  "is_playing": true,
  "name": "Track Name",
  "artist": "Artist Name",
  "album": "Album Name",
  "artwork_url": "https://i.scdn.co/image/...",
  "progress_ms": 45000,
  "duration_ms": 210000,
  "volume": 75,
  "shuffle": false,
  "repeat_track": false,
  "repeat_context": false,
  "uri": "spotify:track:xxx"
}
```

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

## Local Development

```bash
# Clone the repository
git clone https://github.com/gambit-robotics/viam-spotify.git
cd viam-spotify

# Run setup (downloads go-librespot, installs deps)
./setup.sh

# Run locally
./exec.sh
```

## Troubleshooting

### Device doesn't appear in Spotify app

1. Check that go-librespot is running: `ps aux | grep go-librespot`
2. Verify Zeroconf/mDNS is working: `avahi-browse -a` (Linux)
3. Ensure device and phone are on the same network

### No audio

1. Check PulseAudio is running: `pulseaudio --check && echo "running"`
2. List available sinks: `pactl list sinks short`
3. Test audio: `paplay /usr/share/sounds/alsa/Front_Center.wav`

**Note:** Raspberry Pi OS Lite doesn't include PulseAudio. Set `audio_backend: alsa` in config.

### Connection drops

- Credentials are stored in `~/.config/go-librespot/`
- Delete `~/.config/go-librespot/state.json` to force re-authentication
- Check network stability

## Known Limitations

- **Spotify Premium required** - Free accounts don't support Spotify Connect
- **No search/browse** - Users search on their phone and cast to the device
- **No playlist management** - Read-only access to what's playing
- **Protocol changes** - Spotify can break librespot (rare, usually fixed quickly)
- **One instance per device** - Credentials are stored per-user, so only one Spotify module per machine

## License

Apache 2.0
