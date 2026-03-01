"""
HTTP client for go-librespot API.

Provides methods for playback control and status queries.
"""

import json
from dataclasses import dataclass, field
from typing import Any

import requests
from viam.logging import getLogger

LOGGER = getLogger("gambit-robotics:service:spotify")


@dataclass
class TrackMetadata:
    """Current track metadata from go-librespot."""

    uri: str = ""
    name: str = ""
    artist: str = ""
    album: str = ""
    artwork_url: str = ""
    duration_ms: int = 0
    is_playing: bool = False
    progress_ms: int = 0
    volume: int = 50
    shuffle: bool = False
    repeat_context: bool = False
    repeat_track: bool = False
    release_date: str = ""
    track_number: int = 0
    disc_number: int = 0


@dataclass
class PlayerStatus:
    """Full player status."""

    active: bool = False
    track: TrackMetadata = field(default_factory=TrackMetadata)
    device_id: str = ""
    device_name: str = ""
    username: str = ""
    device_type: str = ""
    play_origin: str = ""
    buffering: bool = False
    volume_steps: int = 64


class LibrespotClient:
    """HTTP client for go-librespot API."""

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:3678",
        timeout: float = 5.0,
    ):
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout

    def _request(
        self,
        method: str,
        endpoint: str,
        json_data: dict | None = None,
        params: dict | None = None,
    ) -> dict | None:
        """Make an HTTP request to go-librespot API."""
        url = f"{self.api_url}{endpoint}"
        try:
            response = requests.request(
                method=method,
                url=url,
                json=json_data,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            if response.text:
                return response.json()
            return {}
        except requests.exceptions.ConnectionError:
            LOGGER.debug(f"Connection error to go-librespot at {url}")
            return None
        except requests.exceptions.Timeout:
            LOGGER.warning(f"Timeout connecting to go-librespot at {url}")
            return None
        except requests.exceptions.HTTPError as e:
            LOGGER.warning(f"HTTP error from go-librespot: {e}")
            return None
        except json.JSONDecodeError:
            LOGGER.warning(f"Invalid JSON from go-librespot: {url}")
            return None

    def is_available(self) -> bool:
        """Check if go-librespot API is available."""
        result = self._request("GET", "/status")
        return result is not None

    def get_status(self) -> PlayerStatus | None:
        """Get current player status."""
        data = self._request("GET", "/status")
        if data is None:
            return None

        return self._parse_status(data)

    def _parse_status(self, data: dict) -> PlayerStatus:
        """Parse status response into PlayerStatus object."""
        status = PlayerStatus()

        # Device/session info
        status.active = data.get("stopped", True) is False
        status.device_id = data.get("device_id", "")
        status.device_name = data.get("device_name", "")
        status.username = data.get("username", "")
        status.device_type = data.get("device_type", "")
        status.play_origin = data.get("play_origin", "")
        status.buffering = data.get("buffering", False)
        status.volume_steps = data.get("volume_steps", 64)

        # Parse track metadata (go-librespot field names)
        track = data.get("track", {})
        if track:
            status.track = TrackMetadata(
                uri=track.get("uri", ""),
                name=track.get("name", ""),
                artist=self._format_artists(track.get("artist_names", [])),
                album=track.get("album_name", ""),
                artwork_url=track.get("album_cover_url", ""),
                duration_ms=track.get("duration", 0),
                release_date=self._parse_release_date(track.get("release_date", "")),
                track_number=track.get("track_number", 0),
                disc_number=track.get("disc_number", 0),
            )
            # Position is inside track object
            status.track.progress_ms = track.get("position", 0)

        # Player state (from top-level response)
        status.track.is_playing = data.get("paused", True) is False
        status.track.volume = data.get("volume", 50)
        status.track.shuffle = data.get("shuffle_context", False)
        status.track.repeat_context = data.get("repeat_context", False)
        status.track.repeat_track = data.get("repeat_track", False)

        return status

    def _parse_release_date(self, date_str: str) -> str:
        """Parse go-librespot date format to ISO format.

        Input: "year:2010 month:4 day:12"
        Output: "2010-04-12"
        """
        if not date_str:
            return ""
        try:
            parts = {}
            for part in date_str.split():
                if ":" in part:
                    key, value = part.split(":", 1)
                    parts[key] = int(value)
            year = parts.get("year", 0)
            month = parts.get("month", 1)
            day = parts.get("day", 1)
            if year:
                return f"{year:04d}-{month:02d}-{day:02d}"
        except (ValueError, AttributeError):
            pass
        return date_str  # Return original if parsing fails

    def _format_artists(self, artists: list) -> str:
        """Format artist list into comma-separated string."""
        if isinstance(artists, list):
            names = []
            for artist in artists:
                if isinstance(artist, dict):
                    names.append(artist.get("name", ""))
                elif isinstance(artist, str):
                    names.append(artist)
            return ", ".join(filter(None, names))
        return str(artists) if artists else ""

    def resume(self) -> bool:
        """Resume playback."""
        result = self._request("POST", "/player/resume")
        return result is not None

    def pause(self) -> bool:
        """Pause playback."""
        result = self._request("POST", "/player/pause")
        return result is not None

    def play_pause(self) -> bool:
        """Toggle play/pause."""
        result = self._request("POST", "/player/playpause")
        return result is not None

    def next_track(self) -> bool:
        """Skip to next track."""
        result = self._request("POST", "/player/next")
        return result is not None

    def previous_track(self) -> bool:
        """Go to previous track."""
        result = self._request("POST", "/player/prev")
        return result is not None

    def seek(self, position_ms: int) -> bool:
        """Seek to position in current track."""
        result = self._request("POST", "/player/seek", json_data={"position": position_ms})
        return result is not None

    def set_volume(self, volume: int) -> bool:
        """Set volume (0-100)."""
        volume = max(0, min(100, volume))
        result = self._request("POST", "/player/volume", json_data={"volume": volume})
        return result is not None

    def set_shuffle(self, enabled: bool) -> bool:
        """Set shuffle state."""
        result = self._request(
            "POST", "/player/shuffle_context", json_data={"shuffle_context": enabled}
        )
        return result is not None

    def set_repeat(self, mode: str) -> bool:
        """Set repeat mode: 'off', 'context', or 'track'."""
        # go-librespot uses separate endpoints for repeat_context and repeat_track
        if mode == "off":
            # Disable both repeat modes
            r1 = self._request(
                "POST", "/player/repeat_context", json_data={"repeat_context": False}
            )
            r2 = self._request("POST", "/player/repeat_track", json_data={"repeat_track": False})
            return r1 is not None and r2 is not None
        elif mode == "context":
            r1 = self._request("POST", "/player/repeat_track", json_data={"repeat_track": False})
            r2 = self._request("POST", "/player/repeat_context", json_data={"repeat_context": True})
            return r1 is not None and r2 is not None
        elif mode == "track":
            r1 = self._request(
                "POST", "/player/repeat_context", json_data={"repeat_context": False}
            )
            r2 = self._request("POST", "/player/repeat_track", json_data={"repeat_track": True})
            return r1 is not None and r2 is not None
        else:
            LOGGER.warning(f"Unknown repeat mode: {mode}")
            return False

    def play_uri(self, uri: str, skip_to_uri: str | None = None) -> bool:
        """Play a Spotify URI (track, album, playlist, etc.)."""
        body: dict[str, Any] = {"uri": uri}
        if skip_to_uri:
            body["skip_to_uri"] = skip_to_uri
        result = self._request("POST", "/player/play", json_data=body)
        return result is not None

    def add_to_queue(self, uri: str) -> bool:
        """Add a track to the queue."""
        result = self._request("POST", "/player/add_to_queue", json_data={"uri": uri})
        return result is not None

    def get_queue(self) -> list[dict] | None:
        """Get the current queue (if supported by go-librespot version)."""
        result = self._request("GET", "/queue")
        if result is None:
            return None
        return result.get("tracks", [])

    def close(self) -> None:
        """Clean up resources."""
        pass
