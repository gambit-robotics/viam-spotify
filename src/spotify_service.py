import asyncio
import io
from typing import Any, ClassVar, Mapping, Optional, Sequence

import requests
import spotipy
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

from .auth_server import AuthServer
from .token_manager import TokenManager

LOGGER = getLogger(__name__)


def extract_colors(image_url: str) -> list[str]:
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
    MODEL: ClassVar[Model] = Model(
        ModelFamily("gambit-robotics", "service"), "spotify"
    )

    _token_manager: Optional[TokenManager] = None
    _auth_server: Optional[AuthServer] = None
    _color_cache: Optional[dict[str, list[str]]] = None

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
    def validate_config(cls, config: ComponentConfig) -> Sequence[str]:
        attrs = config.attributes.fields
        if "client_id" not in attrs:
            raise ValueError("client_id is required")
        return []

    def reconfigure(
        self,
        config: ComponentConfig,
        dependencies: Mapping[ResourceName, ResourceBase],
    ) -> None:
        old_server = self._auth_server

        attrs = config.attributes.fields
        client_id = attrs["client_id"].string_value
        auth_port = int(attrs.get("auth_port", {}).number_value or 8888)
        token_path = (
            attrs.get("token_path", {}).string_value
            or "/tmp/.spotify_token"
        )

        redirect_uri = f"http://{{ip}}:{auth_port}/callback"

        self._token_manager = TokenManager(
            client_id=client_id,
            redirect_uri=redirect_uri,
            token_path=token_path,
        )
        self._auth_server = AuthServer(self._token_manager, port=auth_port)

        self._token_manager.redirect_uri = self._auth_server.callback_url
        self._color_cache = {}

        async def start_server():
            try:
                if old_server:
                    await old_server.stop()
                await self._auth_server.start()
            except Exception as e:
                LOGGER.error(f"Failed to start auth server: {e}")

        asyncio.create_task(start_server())

    async def close(self) -> None:
        if self._auth_server:
            await self._auth_server.stop()

    async def do_command(
        self,
        command: Mapping[str, Any],
        *,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> Mapping[str, Any]:
        cmd = command.get("command", "")

        handlers = {
            "get_auth_qr": self._cmd_get_auth_qr,
            "get_auth_status": self._cmd_get_auth_status,
            "logout": self._cmd_logout,
            "play": self._cmd_play,
            "pause": self._cmd_pause,
            "next": self._cmd_next,
            "previous": self._cmd_previous,
            "seek": self._cmd_seek,
            "set_volume": self._cmd_set_volume,
            "shuffle": self._cmd_shuffle,
            "repeat": self._cmd_repeat,
            "add_to_queue": self._cmd_add_to_queue,
            "get_current_track": self._cmd_get_current_track,
            "get_queue": self._cmd_get_queue,
            "search": self._cmd_search,
            "get_playlists": self._cmd_get_playlists,
            "get_playlist_tracks": self._cmd_get_playlist_tracks,
            "get_saved_tracks": self._cmd_get_saved_tracks,
            "get_recently_played": self._cmd_get_recently_played,
            "get_devices": self._cmd_get_devices,
            "transfer_playback": self._cmd_transfer_playback,
        }

        handler = handlers.get(cmd)
        if handler:
            return await handler(command)

        return {"error": f"Unknown command: {cmd}"}

    async def _cmd_get_auth_qr(self, cmd: Mapping[str, Any]) -> dict:
        return self._auth_server.get_qr_data()

    async def _cmd_get_auth_status(self, cmd: Mapping[str, Any]) -> dict:
        authenticated = self._token_manager.is_authenticated()
        user = self._token_manager.get_current_user() if authenticated else None
        return {"authenticated": authenticated, "user": user}

    async def _cmd_logout(self, cmd: Mapping[str, Any]) -> dict:
        self._token_manager.logout()
        return {"success": True}

    def _get_spotify(self) -> tuple[Optional[spotipy.Spotify], Optional[dict]]:
        sp = self._token_manager.get_spotify()
        if not sp:
            return None, {"error": "Not authenticated. Please authenticate first."}
        return sp, None

    async def _cmd_play(self, cmd: Mapping[str, Any]) -> dict:
        sp, err = self._get_spotify()
        if err:
            return err
        uri = cmd.get("uri")
        device_id = cmd.get("device_id")

        try:
            if uri:
                if uri.startswith("spotify:track:"):
                    sp.start_playback(device_id=device_id, uris=[uri])
                else:
                    sp.start_playback(device_id=device_id, context_uri=uri)
            else:
                sp.start_playback(device_id=device_id)
            return {"success": True}
        except Exception as e:
            LOGGER.warning(f"Play failed: {e}")
            return {"success": False, "error": str(e)}

    async def _cmd_pause(self, cmd: Mapping[str, Any]) -> dict:
        sp, err = self._get_spotify()
        if err:
            return err
        try:
            sp.pause_playback()
            return {"success": True}
        except Exception as e:
            LOGGER.warning(f"Pause failed: {e}")
            return {"success": False, "error": str(e)}

    async def _cmd_next(self, cmd: Mapping[str, Any]) -> dict:
        sp, err = self._get_spotify()
        if err:
            return err
        try:
            sp.next_track()
            return {"success": True}
        except Exception as e:
            LOGGER.warning(f"Next track failed: {e}")
            return {"success": False, "error": str(e)}

    async def _cmd_previous(self, cmd: Mapping[str, Any]) -> dict:
        sp, err = self._get_spotify()
        if err:
            return err
        try:
            sp.previous_track()
            return {"success": True}
        except Exception as e:
            LOGGER.warning(f"Previous track failed: {e}")
            return {"success": False, "error": str(e)}

    async def _cmd_seek(self, cmd: Mapping[str, Any]) -> dict:
        sp, err = self._get_spotify()
        if err:
            return err
        position_ms = cmd.get("position_ms", 0)
        try:
            sp.seek_track(position_ms)
            return {"success": True}
        except Exception as e:
            LOGGER.warning(f"Seek failed: {e}")
            return {"success": False, "error": str(e)}

    async def _cmd_set_volume(self, cmd: Mapping[str, Any]) -> dict:
        sp, err = self._get_spotify()
        if err:
            return err
        volume = cmd.get("volume", 50)
        volume = max(0, min(100, volume))
        try:
            sp.volume(volume)
            return {"success": True}
        except Exception as e:
            LOGGER.warning(f"Set volume failed: {e}")
            return {"success": False, "error": str(e)}

    async def _cmd_shuffle(self, cmd: Mapping[str, Any]) -> dict:
        sp, err = self._get_spotify()
        if err:
            return err
        state = cmd.get("state", True)
        try:
            sp.shuffle(state)
            return {"success": True}
        except Exception as e:
            LOGGER.warning(f"Shuffle failed: {e}")
            return {"success": False, "error": str(e)}

    async def _cmd_repeat(self, cmd: Mapping[str, Any]) -> dict:
        sp, err = self._get_spotify()
        if err:
            return err
        state = cmd.get("state", "off")
        if state not in ("track", "context", "off"):
            return {"success": False, "error": "Invalid repeat state"}
        try:
            sp.repeat(state)
            return {"success": True}
        except Exception as e:
            LOGGER.warning(f"Repeat failed: {e}")
            return {"success": False, "error": str(e)}

    async def _cmd_add_to_queue(self, cmd: Mapping[str, Any]) -> dict:
        sp, err = self._get_spotify()
        if err:
            return err
        uri = cmd.get("uri")
        if not uri:
            return {"success": False, "error": "uri is required"}
        try:
            sp.add_to_queue(uri)
            return {"success": True}
        except Exception as e:
            LOGGER.warning(f"Add to queue failed: {e}")
            return {"success": False, "error": str(e)}

    async def _get_colors_cached(self, artwork_url: str) -> list[str]:
        if self._color_cache and artwork_url in self._color_cache:
            return self._color_cache[artwork_url]

        loop = asyncio.get_running_loop()
        colors = await loop.run_in_executor(None, extract_colors, artwork_url)

        if self._color_cache is None:
            self._color_cache = {}
        if len(self._color_cache) > 100:
            self._color_cache.clear()
        self._color_cache[artwork_url] = colors
        return colors

    async def _cmd_get_current_track(self, cmd: Mapping[str, Any]) -> dict:
        sp, err = self._get_spotify()
        if err:
            return err
        try:
            loop = asyncio.get_running_loop()
            current = await loop.run_in_executor(None, sp.current_playback)
            if not current or not current.get("item"):
                return {
                    "is_playing": False,
                    "name": None,
                    "artist": None,
                    "album": None,
                    "artwork_url": None,
                    "colors": [],
                    "progress_ms": 0,
                    "duration_ms": 0,
                    "uri": None,
                }

            item = current["item"]
            artwork_url = None
            if item.get("album", {}).get("images"):
                artwork_url = item["album"]["images"][0]["url"]

            colors = await self._get_colors_cached(artwork_url) if artwork_url else []

            return {
                "is_playing": current.get("is_playing", False),
                "name": item.get("name"),
                "artist": ", ".join(a["name"] for a in item.get("artists", [])),
                "album": item.get("album", {}).get("name"),
                "artwork_url": artwork_url,
                "colors": colors,
                "progress_ms": current.get("progress_ms", 0),
                "duration_ms": item.get("duration_ms", 0),
                "uri": item.get("uri"),
            }
        except Exception as e:
            LOGGER.warning(f"Get current track failed: {e}")
            return {"error": str(e)}

    async def _cmd_get_queue(self, cmd: Mapping[str, Any]) -> dict:
        sp, err = self._get_spotify()
        if err:
            return err
        try:
            queue_data = sp.queue()
            queue = []
            for item in queue_data.get("queue", [])[:20]:
                artwork_url = None
                if item.get("album", {}).get("images"):
                    artwork_url = item["album"]["images"][0]["url"]
                queue.append({
                    "name": item.get("name"),
                    "artist": ", ".join(a["name"] for a in item.get("artists", [])),
                    "artwork_url": artwork_url,
                    "uri": item.get("uri"),
                })
            return {"queue": queue}
        except Exception as e:
            LOGGER.warning(f"Get queue failed: {e}")
            return {"error": str(e)}

    async def _cmd_search(self, cmd: Mapping[str, Any]) -> dict:
        sp, err = self._get_spotify()
        if err:
            return err
        query = cmd.get("query")
        if not query:
            return {"error": "query is required"}

        search_type = cmd.get("type", "track")
        if search_type not in ("track", "album", "artist", "playlist"):
            return {"error": "Invalid search type. Must be: track, album, artist, or playlist"}
        limit = cmd.get("limit", 10)

        try:
            results = sp.search(q=query, type=search_type, limit=limit)

            formatted = []
            type_key = f"{search_type}s"

            for item in results.get(type_key, {}).get("items", []):
                if search_type == "track":
                    artwork_url = None
                    if item.get("album", {}).get("images"):
                        artwork_url = item["album"]["images"][0]["url"]
                    formatted.append({
                        "name": item.get("name"),
                        "artist": ", ".join(a["name"] for a in item.get("artists", [])),
                        "album": item.get("album", {}).get("name"),
                        "artwork_url": artwork_url,
                        "uri": item.get("uri"),
                    })
                elif search_type == "album":
                    artwork_url = None
                    if item.get("images"):
                        artwork_url = item["images"][0]["url"]
                    formatted.append({
                        "name": item.get("name"),
                        "artist": ", ".join(a["name"] for a in item.get("artists", [])),
                        "artwork_url": artwork_url,
                        "uri": item.get("uri"),
                    })
                elif search_type == "artist":
                    artwork_url = None
                    if item.get("images"):
                        artwork_url = item["images"][0]["url"]
                    formatted.append({
                        "name": item.get("name"),
                        "artwork_url": artwork_url,
                        "uri": item.get("uri"),
                    })
                elif search_type == "playlist":
                    artwork_url = None
                    if item.get("images"):
                        artwork_url = item["images"][0]["url"]
                    formatted.append({
                        "name": item.get("name"),
                        "owner": item.get("owner", {}).get("display_name"),
                        "artwork_url": artwork_url,
                        "uri": item.get("uri"),
                    })

            return {"results": formatted}
        except Exception as e:
            LOGGER.warning(f"Search failed: {e}")
            return {"error": str(e)}

    async def _cmd_get_playlists(self, cmd: Mapping[str, Any]) -> dict:
        sp, err = self._get_spotify()
        if err:
            return err
        limit = cmd.get("limit", 20)

        try:
            playlists_data = sp.current_user_playlists(limit=limit)
            playlists = []
            for item in playlists_data.get("items", []):
                image_url = None
                if item.get("images"):
                    image_url = item["images"][0]["url"]
                playlists.append({
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "image_url": image_url,
                })
            return {"playlists": playlists}
        except Exception as e:
            LOGGER.warning(f"Get playlists failed: {e}")
            return {"error": str(e)}

    async def _cmd_get_playlist_tracks(self, cmd: Mapping[str, Any]) -> dict:
        sp, err = self._get_spotify()
        if err:
            return err
        playlist_id = cmd.get("playlist_id")
        if not playlist_id:
            return {"error": "playlist_id is required"}

        try:
            tracks_data = sp.playlist_tracks(playlist_id, limit=50)
            tracks = []
            for item in tracks_data.get("items", []):
                track = item.get("track")
                if track:
                    tracks.append({
                        "name": track.get("name"),
                        "artist": ", ".join(a["name"] for a in track.get("artists", [])),
                        "uri": track.get("uri"),
                    })
            return {"tracks": tracks}
        except Exception as e:
            LOGGER.warning(f"Get playlist tracks failed: {e}")
            return {"error": str(e)}

    async def _cmd_get_saved_tracks(self, cmd: Mapping[str, Any]) -> dict:
        sp, err = self._get_spotify()
        if err:
            return err
        limit = cmd.get("limit", 20)

        try:
            tracks_data = sp.current_user_saved_tracks(limit=limit)
            tracks = []
            for item in tracks_data.get("items", []):
                track = item.get("track")
                if track:
                    artwork_url = None
                    if track.get("album", {}).get("images"):
                        artwork_url = track["album"]["images"][0]["url"]
                    tracks.append({
                        "name": track.get("name"),
                        "artist": ", ".join(a["name"] for a in track.get("artists", [])),
                        "artwork_url": artwork_url,
                        "uri": track.get("uri"),
                    })
            return {"tracks": tracks}
        except Exception as e:
            LOGGER.warning(f"Get saved tracks failed: {e}")
            return {"error": str(e)}

    async def _cmd_get_recently_played(self, cmd: Mapping[str, Any]) -> dict:
        sp, err = self._get_spotify()
        if err:
            return err
        limit = cmd.get("limit", 20)

        try:
            tracks_data = sp.current_user_recently_played(limit=limit)
            tracks = []
            for item in tracks_data.get("items", []):
                track = item.get("track")
                if track:
                    artwork_url = None
                    if track.get("album", {}).get("images"):
                        artwork_url = track["album"]["images"][0]["url"]
                    tracks.append({
                        "name": track.get("name"),
                        "artist": ", ".join(a["name"] for a in track.get("artists", [])),
                        "artwork_url": artwork_url,
                        "uri": track.get("uri"),
                    })
            return {"tracks": tracks}
        except Exception as e:
            LOGGER.warning(f"Get recently played failed: {e}")
            return {"error": str(e)}

    async def _cmd_get_devices(self, cmd: Mapping[str, Any]) -> dict:
        sp, err = self._get_spotify()
        if err:
            return err
        try:
            devices_data = sp.devices()
            devices = []
            for device in devices_data.get("devices", []):
                devices.append({
                    "id": device.get("id"),
                    "name": device.get("name"),
                    "type": device.get("type"),
                    "is_active": device.get("is_active"),
                })
            return {"devices": devices}
        except Exception as e:
            LOGGER.warning(f"Get devices failed: {e}")
            return {"error": str(e)}

    async def _cmd_transfer_playback(self, cmd: Mapping[str, Any]) -> dict:
        sp, err = self._get_spotify()
        if err:
            return err
        device_id = cmd.get("device_id")
        if not device_id:
            return {"success": False, "error": "device_id is required"}

        try:
            sp.transfer_playback(device_id)
            return {"success": True}
        except Exception as e:
            LOGGER.warning(f"Transfer playback failed: {e}")
            return {"success": False, "error": str(e)}


Registry.register_resource_creator(
    Generic.API,
    SpotifyService.MODEL,
    ResourceCreatorRegistration(SpotifyService.new, SpotifyService.validate_config),
)
