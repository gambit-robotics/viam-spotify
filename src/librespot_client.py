"""
HTTP/WebSocket client for go-librespot API.

Provides methods for playback control and real-time status updates.
"""
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import requests
import websocket
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
    """HTTP/WebSocket client for go-librespot API."""

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:3678",
        timeout: float = 5.0,
    ):
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout

        self._ws: websocket.WebSocketApp | None = None
        self._ws_thread: threading.Thread | None = None
        self._ws_connected = False
        self._should_connect = False
        self._reconnect_pending = False
        self._reconnect_lock = threading.Lock()

        self._status_lock = threading.Lock()
        self._cached_status: PlayerStatus | None = None
        self._last_status_time: float = 0

        self._event_callbacks: list[Callable[[dict], None]] = []

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

        with self._status_lock:
            self._cached_status = status
            self._last_status_time = time.time()

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

    def _get_best_image(self, images: list) -> str:
        """Get the best quality image URL from a list."""
        if not images:
            return ""

        # Prefer larger images
        sorted_images = sorted(
            images,
            key=lambda x: x.get("width", 0) * x.get("height", 0),
            reverse=True,
        )
        return sorted_images[0].get("url", "") if sorted_images else ""

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
        result = self._request(
            "POST", "/player/seek",
            json_data={"position": position_ms}
        )
        return result is not None

    def set_volume(self, volume: int) -> bool:
        """Set volume (0-100)."""
        volume = max(0, min(100, volume))
        result = self._request(
            "POST", "/player/volume",
            json_data={"volume": volume}
        )
        return result is not None

    def set_shuffle(self, enabled: bool) -> bool:
        """Set shuffle state."""
        result = self._request(
            "POST", "/player/shuffle_context",
            json_data={"shuffle_context": enabled}
        )
        return result is not None

    def set_repeat(self, mode: str) -> bool:
        """Set repeat mode: 'off', 'context', or 'track'."""
        # go-librespot uses separate endpoints for repeat_context and repeat_track
        if mode == "off":
            # Disable both repeat modes
            r1 = self._request(
                "POST", "/player/repeat_context",
                json_data={"repeat_context": False}
            )
            r2 = self._request(
                "POST", "/player/repeat_track",
                json_data={"repeat_track": False}
            )
            return r1 is not None and r2 is not None
        elif mode == "context":
            r1 = self._request(
                "POST", "/player/repeat_track",
                json_data={"repeat_track": False}
            )
            r2 = self._request(
                "POST", "/player/repeat_context",
                json_data={"repeat_context": True}
            )
            return r1 is not None and r2 is not None
        elif mode == "track":
            r1 = self._request(
                "POST", "/player/repeat_context",
                json_data={"repeat_context": False}
            )
            r2 = self._request(
                "POST", "/player/repeat_track",
                json_data={"repeat_track": True}
            )
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
        result = self._request(
            "POST", "/player/add_to_queue",
            json_data={"uri": uri}
        )
        return result is not None

    def get_queue(self) -> list[dict] | None:
        """Get the current queue (if supported by go-librespot version)."""
        result = self._request("GET", "/queue")
        if result is None:
            return None
        return result.get("tracks", [])

    def _on_ws_message(self, ws: websocket.WebSocket, message: str) -> None:
        """Handle WebSocket message."""
        try:
            data = json.loads(message)
            event_type = data.get("type", "")

            LOGGER.debug(f"WebSocket event: {event_type}")

            # Update cached status from events
            # DISABLED FOR DEBUGGING - this may be causing go-librespot to freeze
            # if event_type in ("metadata", "playing", "paused", "seek", "volume"):
            #     # Fetch fresh status on important events
            #     self.get_status()

            # Notify callbacks
            for callback in self._event_callbacks:
                try:
                    callback(data)
                except Exception as e:
                    LOGGER.error(f"Event callback error: {e}")

        except json.JSONDecodeError:
            LOGGER.warning(f"Invalid WebSocket JSON: {message}")

    def _on_ws_error(self, ws: websocket.WebSocket, error: Exception) -> None:
        """Handle WebSocket error."""
        LOGGER.warning(f"WebSocket error: {error}")
        self._ws_connected = False

    def _on_ws_close(
        self,
        ws: websocket.WebSocket,
        close_status_code: int | None,
        close_msg: str | None,
    ) -> None:
        """Handle WebSocket close."""
        LOGGER.debug(f"WebSocket closed: {close_status_code} {close_msg}")
        self._ws_connected = False

        # Reconnect in a new thread to avoid recursive blocking
        # Use lock to prevent spawning multiple reconnect threads
        if self._should_connect:
            with self._reconnect_lock:
                if self._reconnect_pending:
                    return  # Another reconnect is already scheduled
                self._reconnect_pending = True

            reconnect_thread = threading.Thread(
                target=self._reconnect_ws,
                daemon=True,
                name="librespot-ws-reconnect",
            )
            reconnect_thread.start()

    def _reconnect_ws(self) -> None:
        """Reconnect to WebSocket after a delay."""
        try:
            time.sleep(2)
            if self._should_connect:
                self._connect_ws()
        finally:
            with self._reconnect_lock:
                self._reconnect_pending = False

    def _on_ws_open(self, ws: websocket.WebSocket) -> None:
        """Handle WebSocket open."""
        LOGGER.info("WebSocket connected to go-librespot")
        self._ws_connected = True

    def _connect_ws(self) -> None:
        """Connect to WebSocket endpoint."""
        ws_url = self.api_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/events"

        self._ws = websocket.WebSocketApp(
            ws_url,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
            on_open=self._on_ws_open,
        )

        self._ws.run_forever()

    def start_event_listener(self) -> None:
        """Start WebSocket event listener in background thread."""
        if self._ws_thread is not None and self._ws_thread.is_alive():
            return

        self._should_connect = True
        self._ws_thread = threading.Thread(
            target=self._connect_ws,
            daemon=True,
            name="librespot-ws",
        )
        self._ws_thread.start()

    def stop_event_listener(self) -> None:
        """Stop WebSocket event listener."""
        self._should_connect = False
        if self._ws is not None:
            self._ws.close()
        self._ws = None
        self._ws_connected = False

    def add_event_callback(self, callback: Callable[[dict], None]) -> None:
        """Add a callback for WebSocket events."""
        self._event_callbacks.append(callback)

    def remove_event_callback(self, callback: Callable[[dict], None]) -> None:
        """Remove an event callback."""
        if callback in self._event_callbacks:
            self._event_callbacks.remove(callback)

    def get_cached_status(self, max_age: float = 1.0) -> PlayerStatus | None:
        """Get cached status if fresh enough, otherwise fetch new."""
        with self._status_lock:
            if (
                self._cached_status is not None
                and time.time() - self._last_status_time < max_age
            ):
                return self._cached_status
        return self.get_status()

    def close(self) -> None:
        """Clean up resources."""
        self.stop_event_listener()
