"""
Spotify Connect service using go-librespot.

This module exposes Spotify playback control through the Viam generic service API.
Audio is played via go-librespot subprocess, which appears as a Spotify Connect device.
Users connect from their Spotify app - no OAuth or developer app required.
"""
import asyncio
import io
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

import requests
from colorthief import ColorThief
from typing_extensions import Self
from viam.logging import getLogger
from viam.module.types import Reconfigurable
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import ResourceName
from viam.resource.base import ResourceBase
from viam.resource.registry import Registry, ResourceCreatorRegistration
from viam.resource.types import Model, ModelFamily
from viam.services.generic import Generic

from librespot_client import LibrespotClient
from librespot_manager import LibrespotManager

LOGGER = getLogger("gambit-robotics:service:spotify")


def extract_colors(image_url: str) -> list[str]:
    """Extract dominant colors from album artwork."""
    try:
        response = requests.get(image_url, timeout=5)
        response.raise_for_status()
        img_data = io.BytesIO(response.content)
        color_thief = ColorThief(img_data)
        palette = color_thief.get_palette(color_count=3, quality=1)
        return [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in palette]
    except Exception:
        return ["#1a1a2e", "#e94560", "#0f3460"]


class SpotifyService(Generic, Reconfigurable):
    """Spotify Connect playback control service."""

    MODEL: ClassVar[Model] = Model(
        ModelFamily("gambit-robotics", "service"), "spotify"
    )

    _manager: LibrespotManager | None = None
    _client: LibrespotClient | None = None
    _color_cache: OrderedDict[str, list[str]] | None = None
    _color_cache_max_size: int = 100
    _startup_error: str | None = None

    @classmethod
    def new(
        cls,
        config: ComponentConfig,
        dependencies: Mapping[ResourceName, ResourceBase],
    ) -> Self:
        service = cls(config.name)
        service.reconfigure(config, dependencies)
        return service

    @classmethod
    def validate_config(cls, config: ComponentConfig) -> tuple[Sequence[str], Sequence[str]]:
        attrs = config.attributes.fields
        if "device_name" not in attrs:
            raise ValueError("device_name is required")
        return [], []  # (required_deps, optional_deps)

    def reconfigure(
        self,
        config: ComponentConfig,
        dependencies: Mapping[ResourceName, ResourceBase],
    ) -> None:
        # Stop existing manager if running
        if self._manager is not None:
            self._manager.stop()
        if self._client is not None:
            self._client.close()

        attrs = config.attributes.fields

        # Required config
        device_name = attrs["device_name"].string_value

        # Optional config with defaults
        api_port = int(attrs["api_port"].number_value) if "api_port" in attrs else 3678
        audio_backend = attrs["audio_backend"].string_value if "audio_backend" in attrs else "pulseaudio"
        audio_device = attrs["audio_device"].string_value if "audio_device" in attrs else "default"
        bitrate = int(attrs["bitrate"].number_value) if "bitrate" in attrs else 320
        initial_volume = int(attrs["initial_volume"].number_value) if "initial_volume" in attrs else 50

        # Create manager and client
        self._manager = LibrespotManager(
            device_name=device_name,
            api_port=api_port,
            audio_backend=audio_backend,
            audio_device=audio_device,
            bitrate=bitrate,
            initial_volume=initial_volume,
        )
        self._client = LibrespotClient(api_url=self._manager.api_url)
        self._color_cache = OrderedDict()

        # Start go-librespot
        self._startup_error = None
        if self._manager.start():
            LOGGER.info(f"Spotify Connect device '{device_name}' starting...")
            # DISABLED FOR DEBUGGING - WebSocket may be causing go-librespot to freeze
            # self._client.start_event_listener()
        else:
            self._startup_error = (
                "Failed to start go-librespot. Check that the binary is installed "
                "at /usr/local/bin/go-librespot and the configured port is available."
            )
            LOGGER.error(self._startup_error)

    async def close(self) -> None:
        """Clean up resources."""
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._manager is not None:
            self._manager.stop()
            self._manager = None

    async def do_command(
        self,
        command: Mapping[str, Any],
        *,
        timeout: float | None = None,
        **kwargs,
    ) -> Mapping[str, Any]:
        cmd = command.get("command", "")

        handlers = {
            # Status
            "get_status": self._cmd_get_status,
            "get_current_track": self._cmd_get_current_track,
            # Playback control
            "play": self._cmd_play,
            "pause": self._cmd_pause,
            "toggle_playback": self._cmd_toggle_playback,
            "next": self._cmd_next,
            "previous": self._cmd_previous,
            "seek": self._cmd_seek,
            "set_volume": self._cmd_set_volume,
            "shuffle": self._cmd_shuffle,
            "repeat": self._cmd_repeat,
            "add_to_queue": self._cmd_add_to_queue,
            "play_uri": self._cmd_play_uri,
            # Queue
            "get_queue": self._cmd_get_queue,
        }

        handler = handlers.get(cmd)
        if handler:
            return await handler(command)

        return {"error": f"Unknown command: {cmd}"}

    def _check_ready(self) -> dict | None:
        """Check if service is ready for commands."""
        if self._manager is None or self._client is None:
            return {"error": "Service not configured"}
        if self._startup_error:
            return {"error": self._startup_error}
        if not self._manager.is_running():
            return {
                "error": "go-librespot not running. It may have crashed - check logs for details."
            }
        return None

    async def _cmd_get_status(self, cmd: Mapping[str, Any]) -> dict:
        """Get full player status."""
        err = self._check_ready()
        if err:
            return err

        loop = asyncio.get_running_loop()
        status = await loop.run_in_executor(None, self._client.get_status)

        if status is None:
            return {"error": "Failed to get status from go-librespot"}

        return {
            # Device/session info
            "active": status.active,
            "device_id": status.device_id,
            "device_name": status.device_name,
            "username": status.username or None,
            "device_type": status.device_type or None,
            "play_origin": status.play_origin or None,
            "buffering": status.buffering,
            "volume_steps": status.volume_steps,
            # Playback state
            "is_playing": status.track.is_playing,
            "volume": status.track.volume,
            "shuffle": status.track.shuffle,
            "repeat_track": status.track.repeat_track,
            "repeat_context": status.track.repeat_context,
            "progress_ms": status.track.progress_ms,
            "duration_ms": status.track.duration_ms,
            # Track metadata
            "uri": status.track.uri or None,
            "name": status.track.name or None,
            "artist": status.track.artist or None,
            "album": status.track.album or None,
            "artwork_url": status.track.artwork_url or None,
            "release_date": status.track.release_date or None,
            "track_number": status.track.track_number,
            "disc_number": status.track.disc_number,
        }

    async def _get_colors_cached(self, artwork_url: str) -> list[str]:
        """Get colors for artwork, using LRU cache."""
        if self._color_cache is not None and artwork_url in self._color_cache:
            # Move to end (most recently used)
            self._color_cache.move_to_end(artwork_url)
            return self._color_cache[artwork_url]

        loop = asyncio.get_running_loop()
        colors = await loop.run_in_executor(None, extract_colors, artwork_url)

        if self._color_cache is None:
            self._color_cache = OrderedDict()

        # Evict oldest entries if cache is full
        while len(self._color_cache) >= self._color_cache_max_size:
            self._color_cache.popitem(last=False)

        self._color_cache[artwork_url] = colors
        return colors

    async def _cmd_get_current_track(self, cmd: Mapping[str, Any]) -> dict:
        """Get current track info with colors."""
        err = self._check_ready()
        if err:
            return err

        loop = asyncio.get_running_loop()
        status = await loop.run_in_executor(None, self._client.get_status)

        if status is None:
            return {
                "is_playing": False,
                "buffering": False,
                "name": None,
                "artist": None,
                "album": None,
                "artwork_url": None,
                "colors": [],
                "progress_ms": 0,
                "duration_ms": 0,
                "uri": None,
                "release_date": None,
                "track_number": None,
                "disc_number": None,
            }

        artwork_url = status.track.artwork_url
        colors = await self._get_colors_cached(artwork_url) if artwork_url else []

        return {
            "is_playing": status.track.is_playing,
            "buffering": status.buffering,
            "name": status.track.name or None,
            "artist": status.track.artist or None,
            "album": status.track.album or None,
            "artwork_url": artwork_url or None,
            "colors": colors,
            "progress_ms": status.track.progress_ms,
            "duration_ms": status.track.duration_ms,
            "uri": status.track.uri or None,
            "release_date": status.track.release_date or None,
            "track_number": status.track.track_number,
            "disc_number": status.track.disc_number,
        }

    async def _cmd_play(self, cmd: Mapping[str, Any]) -> dict:
        """Resume playback or play a URI."""
        err = self._check_ready()
        if err:
            return err

        uri = cmd.get("uri")
        loop = asyncio.get_running_loop()

        if uri:
            success = await loop.run_in_executor(None, self._client.play_uri, uri)
        else:
            success = await loop.run_in_executor(None, self._client.resume)

        return {"success": success}

    async def _cmd_pause(self, cmd: Mapping[str, Any]) -> dict:
        """Pause playback."""
        err = self._check_ready()
        if err:
            return err

        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(None, self._client.pause)
        return {"success": success}

    async def _cmd_toggle_playback(self, cmd: Mapping[str, Any]) -> dict:
        """Toggle play/pause."""
        err = self._check_ready()
        if err:
            return err

        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(None, self._client.play_pause)
        return {"success": success}

    async def _cmd_next(self, cmd: Mapping[str, Any]) -> dict:
        """Skip to next track."""
        err = self._check_ready()
        if err:
            return err

        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(None, self._client.next_track)
        return {"success": success}

    async def _cmd_previous(self, cmd: Mapping[str, Any]) -> dict:
        """Go to previous track."""
        err = self._check_ready()
        if err:
            return err

        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(None, self._client.previous_track)
        return {"success": success}

    async def _cmd_seek(self, cmd: Mapping[str, Any]) -> dict:
        """Seek to position in current track."""
        err = self._check_ready()
        if err:
            return err

        position_ms = cmd.get("position_ms", 0)
        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(
            None, self._client.seek, int(position_ms)
        )
        return {"success": success}

    async def _cmd_set_volume(self, cmd: Mapping[str, Any]) -> dict:
        """Set volume (0-100)."""
        err = self._check_ready()
        if err:
            return err

        volume = cmd.get("volume", 50)
        volume = max(0, min(100, int(volume)))
        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(None, self._client.set_volume, volume)
        return {"success": success}

    async def _cmd_shuffle(self, cmd: Mapping[str, Any]) -> dict:
        """Set shuffle state."""
        err = self._check_ready()
        if err:
            return err

        state = cmd.get("state", True)
        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(None, self._client.set_shuffle, state)
        return {"success": success}

    async def _cmd_repeat(self, cmd: Mapping[str, Any]) -> dict:
        """Set repeat mode: 'off', 'context', or 'track'."""
        err = self._check_ready()
        if err:
            return err

        state = cmd.get("state", "off")
        if state not in ("track", "context", "off"):
            return {"success": False, "error": "Invalid repeat state"}

        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(None, self._client.set_repeat, state)
        return {"success": success}

    async def _cmd_add_to_queue(self, cmd: Mapping[str, Any]) -> dict:
        """Add a track to the queue."""
        err = self._check_ready()
        if err:
            return err

        uri = cmd.get("uri")
        if not uri:
            return {"success": False, "error": "uri is required"}

        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(None, self._client.add_to_queue, uri)
        return {"success": success}

    async def _cmd_play_uri(self, cmd: Mapping[str, Any]) -> dict:
        """Play a specific Spotify URI."""
        err = self._check_ready()
        if err:
            return err

        uri = cmd.get("uri")
        if not uri:
            return {"success": False, "error": "uri is required"}

        skip_to = cmd.get("skip_to_uri")
        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(
            None, self._client.play_uri, uri, skip_to
        )
        return {"success": success}

    async def _cmd_get_queue(self, cmd: Mapping[str, Any]) -> dict:
        """Get the current playback queue."""
        err = self._check_ready()
        if err:
            return err

        loop = asyncio.get_running_loop()
        queue = await loop.run_in_executor(None, self._client.get_queue)

        if queue is None:
            return {"queue": [], "error": "Queue not available"}

        # Format queue tracks
        formatted = []
        for track in queue[:20]:
            formatted.append({
                "name": track.get("name"),
                "artist": track.get("artist"),
                "uri": track.get("uri"),
            })

        return {"queue": formatted}


Registry.register_resource_creator(
    Generic.API,
    SpotifyService.MODEL,
    ResourceCreatorRegistration(SpotifyService.new, SpotifyService.validate_config),
)
