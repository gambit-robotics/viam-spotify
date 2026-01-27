"""Tests for Spotify service."""

from collections import OrderedDict
from unittest.mock import MagicMock, patch

import pytest

from librespot_client import PlayerStatus, TrackMetadata
from spotify_service import SpotifyService, extract_colors


class TestExtractColors:
    """Tests for color extraction."""

    def test_extract_colors_fallback_on_error(self):
        """Test color extraction returns fallback on error."""
        with patch("requests.get", side_effect=Exception("Network error")):
            colors = extract_colors("http://invalid-url")

        assert len(colors) == 3
        assert colors == ["#1a1a2e", "#e94560", "#0f3460"]

    def test_extract_colors_success(self):
        """Test successful color extraction."""
        mock_response = MagicMock()
        mock_response.content = b"fake image data"
        mock_response.raise_for_status = MagicMock()

        with patch("spotify_service.requests.get", return_value=mock_response):
            with patch("spotify_service.ColorThief") as mock_ct:
                mock_ct_instance = MagicMock()
                mock_ct_instance.get_palette.return_value = [
                    (255, 0, 0),
                    (0, 255, 0),
                    (0, 0, 255),
                ]
                mock_ct.return_value = mock_ct_instance

                colors = extract_colors("http://example.com/image.jpg")

        assert colors == ["#ff0000", "#00ff00", "#0000ff"]


class TestSpotifyServiceConfig:
    """Tests for SpotifyService configuration."""

    def test_validate_config_requires_device_name(self):
        """Test config validation requires device_name."""
        config = MagicMock()
        config.attributes.fields = {}

        with pytest.raises(ValueError, match="device_name is required"):
            SpotifyService.validate_config(config)

    def test_validate_config_success(self):
        """Test config validation with device_name."""
        config = MagicMock()
        config.attributes.fields = {"device_name": MagicMock(string_value="Test")}

        deps, opt_deps = SpotifyService.validate_config(config)
        assert deps == []
        assert opt_deps == []


class TestSpotifyServiceCheckReady:
    """Tests for _check_ready method."""

    def test_check_ready_not_configured(self):
        """Test check_ready when not configured."""
        service = SpotifyService("test")
        service._manager = None
        service._client = None

        result = service._check_ready()

        assert result is not None
        assert "not configured" in result["error"]

    def test_check_ready_startup_error(self):
        """Test check_ready with startup error."""
        service = SpotifyService("test")
        service._manager = MagicMock()
        service._client = MagicMock()
        service._startup_error = "Binary not found"

        result = service._check_ready()

        assert result is not None
        assert "Binary not found" in result["error"]

    def test_check_ready_not_running(self):
        """Test check_ready when process not running."""
        service = SpotifyService("test")
        service._manager = MagicMock()
        service._manager.is_running.return_value = False
        service._client = MagicMock()
        service._startup_error = None

        result = service._check_ready()

        assert result is not None
        assert "not running" in result["error"]

    def test_check_ready_success(self):
        """Test check_ready when all is well."""
        service = SpotifyService("test")
        service._manager = MagicMock()
        service._manager.is_running.return_value = True
        service._client = MagicMock()
        service._startup_error = None

        result = service._check_ready()

        assert result is None


class TestSpotifyServiceColorCache:
    """Tests for color caching."""

    @pytest.mark.asyncio
    async def test_color_cache_hit(self):
        """Test color cache hit."""
        service = SpotifyService("test")
        service._color_cache = OrderedDict()
        service._color_cache["http://example.com/img.jpg"] = ["#ff0000", "#00ff00"]

        colors = await service._get_colors_cached("http://example.com/img.jpg")

        assert colors == ["#ff0000", "#00ff00"]

    @pytest.mark.asyncio
    async def test_color_cache_miss(self):
        """Test color cache miss fetches colors."""
        service = SpotifyService("test")
        service._color_cache = OrderedDict()

        with patch("spotify_service.extract_colors", return_value=["#aabbcc"]):
            colors = await service._get_colors_cached("http://example.com/new.jpg")

        assert colors == ["#aabbcc"]
        assert "http://example.com/new.jpg" in service._color_cache

    @pytest.mark.asyncio
    async def test_color_cache_lru_eviction(self):
        """Test LRU eviction when cache is full."""
        service = SpotifyService("test")
        service._color_cache = OrderedDict()
        service._color_cache_max_size = 3

        # Fill cache
        service._color_cache["url1"] = ["#111111"]
        service._color_cache["url2"] = ["#222222"]
        service._color_cache["url3"] = ["#333333"]

        # Add new entry - should evict url1 (oldest)
        with patch("spotify_service.extract_colors", return_value=["#444444"]):
            await service._get_colors_cached("url4")

        assert "url1" not in service._color_cache
        assert "url2" in service._color_cache
        assert "url3" in service._color_cache
        assert "url4" in service._color_cache

    @pytest.mark.asyncio
    async def test_color_cache_access_updates_order(self):
        """Test accessing cache entry moves it to end."""
        service = SpotifyService("test")
        service._color_cache = OrderedDict()
        service._color_cache_max_size = 3

        service._color_cache["url1"] = ["#111111"]
        service._color_cache["url2"] = ["#222222"]
        service._color_cache["url3"] = ["#333333"]

        # Access url1 - should move to end
        await service._get_colors_cached("url1")

        # Add new entry - should evict url2 (now oldest)
        with patch("spotify_service.extract_colors", return_value=["#444444"]):
            await service._get_colors_cached("url4")

        assert "url1" in service._color_cache
        assert "url2" not in service._color_cache
        assert "url3" in service._color_cache
        assert "url4" in service._color_cache


class TestSpotifyServiceCommands:
    """Tests for do_command handlers."""

    @pytest.mark.asyncio
    async def test_unknown_command(self):
        """Test unknown command returns error."""
        service = SpotifyService("test")

        result = await service.do_command({"command": "unknown_cmd"})

        assert "error" in result
        assert "Unknown command" in result["error"]

    @pytest.mark.asyncio
    async def test_play_command_not_ready(self):
        """Test play command when service not ready."""
        service = SpotifyService("test")
        service._manager = None

        result = await service.do_command({"command": "play"})

        assert "error" in result

    @pytest.mark.asyncio
    async def test_pause_command(self):
        """Test pause command."""
        service = SpotifyService("test")
        service._manager = MagicMock()
        service._manager.is_running.return_value = True
        service._client = MagicMock()
        service._client.pause.return_value = True
        service._startup_error = None

        result = await service.do_command({"command": "pause"})

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_set_volume_command(self):
        """Test set_volume command."""
        service = SpotifyService("test")
        service._manager = MagicMock()
        service._manager.is_running.return_value = True
        service._client = MagicMock()
        service._client.set_volume.return_value = True
        service._startup_error = None

        result = await service.do_command({"command": "set_volume", "volume": 75})

        assert result["success"] is True
        service._client.set_volume.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_volume_clamped(self):
        """Test set_volume clamps values."""
        service = SpotifyService("test")
        service._manager = MagicMock()
        service._manager.is_running.return_value = True
        service._client = MagicMock()
        service._client.set_volume.return_value = True
        service._startup_error = None

        # Volume over 100 should be clamped
        await service.do_command({"command": "set_volume", "volume": 150})
        service._client.set_volume.assert_called_with(100)

        # Volume under 0 should be clamped
        await service.do_command({"command": "set_volume", "volume": -10})
        service._client.set_volume.assert_called_with(0)

    @pytest.mark.asyncio
    async def test_repeat_invalid_state(self):
        """Test repeat command with invalid state."""
        service = SpotifyService("test")
        service._manager = MagicMock()
        service._manager.is_running.return_value = True
        service._client = MagicMock()
        service._startup_error = None

        result = await service.do_command({"command": "repeat", "state": "invalid"})

        assert result["success"] is False
        assert "Invalid repeat state" in result["error"]

    @pytest.mark.asyncio
    async def test_add_to_queue_requires_uri(self):
        """Test add_to_queue requires uri."""
        service = SpotifyService("test")
        service._manager = MagicMock()
        service._manager.is_running.return_value = True
        service._client = MagicMock()
        service._startup_error = None

        result = await service.do_command({"command": "add_to_queue"})

        assert result["success"] is False
        assert "uri is required" in result["error"]

    @pytest.mark.asyncio
    async def test_get_status_command(self):
        """Test get_status command."""
        service = SpotifyService("test")
        service._manager = MagicMock()
        service._manager.is_running.return_value = True
        service._startup_error = None

        mock_status = PlayerStatus(
            active=True,
            device_id="abc123",
            device_name="Test Speaker",
            username="testuser",
            track=TrackMetadata(
                uri="spotify:track:123",
                name="Test Song",
                artist="Test Artist",
                is_playing=True,
                volume=75,
            ),
        )
        service._client = MagicMock()
        service._client.get_status.return_value = mock_status

        result = await service.do_command({"command": "get_status"})

        assert result["active"] is True
        assert result["device_name"] == "Test Speaker"
        assert result["name"] == "Test Song"
        assert result["is_playing"] is True
        assert result["volume"] == 75

    @pytest.mark.asyncio
    async def test_get_status_no_response(self):
        """Test get_status when API returns None."""
        service = SpotifyService("test")
        service._manager = MagicMock()
        service._manager.is_running.return_value = True
        service._client = MagicMock()
        service._client.get_status.return_value = None
        service._startup_error = None

        result = await service.do_command({"command": "get_status"})

        assert "error" in result


class TestSpotifyServiceLifecycle:
    """Tests for service lifecycle."""

    @pytest.mark.asyncio
    async def test_close_cleans_up(self):
        """Test close method cleans up resources."""
        service = SpotifyService("test")
        mock_manager = MagicMock()
        mock_client = MagicMock()
        service._manager = mock_manager
        service._client = mock_client

        await service.close()

        mock_client.close.assert_called_once()
        mock_manager.stop.assert_called_once()
        assert service._client is None
        assert service._manager is None

    @pytest.mark.asyncio
    async def test_close_handles_none(self):
        """Test close handles None resources."""
        service = SpotifyService("test")
        service._manager = None
        service._client = None

        # Should not raise
        await service.close()
