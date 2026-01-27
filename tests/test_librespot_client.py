"""Tests for librespot client."""

from unittest.mock import MagicMock, patch

from librespot_client import LibrespotClient


class TestLibrespotClientParsing:
    """Tests for LibrespotClient parsing methods."""

    def test_parse_release_date_full(self):
        """Test parsing full date format."""
        client = LibrespotClient()
        result = client._parse_release_date("year:2010 month:4 day:12")
        assert result == "2010-04-12"

    def test_parse_release_date_year_only(self):
        """Test parsing year-only date."""
        client = LibrespotClient()
        result = client._parse_release_date("year:2020")
        assert result == "2020-01-01"

    def test_parse_release_date_empty(self):
        """Test parsing empty date."""
        client = LibrespotClient()
        result = client._parse_release_date("")
        assert result == ""

    def test_parse_release_date_invalid(self):
        """Test parsing invalid date format returns original."""
        client = LibrespotClient()
        result = client._parse_release_date("invalid date")
        assert result == "invalid date"

    def test_parse_release_date_partial(self):
        """Test parsing partial date (year and month only)."""
        client = LibrespotClient()
        result = client._parse_release_date("year:2015 month:6")
        assert result == "2015-06-01"

    def test_format_artists_list_of_strings(self):
        """Test formatting list of artist strings."""
        client = LibrespotClient()
        result = client._format_artists(["Artist One", "Artist Two"])
        assert result == "Artist One, Artist Two"

    def test_format_artists_list_of_dicts(self):
        """Test formatting list of artist dicts."""
        client = LibrespotClient()
        result = client._format_artists([
            {"name": "Artist One"},
            {"name": "Artist Two"}
        ])
        assert result == "Artist One, Artist Two"

    def test_format_artists_empty_list(self):
        """Test formatting empty artist list."""
        client = LibrespotClient()
        result = client._format_artists([])
        assert result == ""

    def test_format_artists_none(self):
        """Test formatting None artists."""
        client = LibrespotClient()
        result = client._format_artists(None)
        assert result == ""

    def test_format_artists_mixed(self):
        """Test formatting mixed artist types."""
        client = LibrespotClient()
        result = client._format_artists([
            {"name": "Artist One"},
            "Artist Two",
            {"name": ""},  # Should be filtered out
        ])
        assert result == "Artist One, Artist Two"

    def test_get_best_image_empty(self):
        """Test getting best image from empty list."""
        client = LibrespotClient()
        result = client._get_best_image([])
        assert result == ""

    def test_get_best_image_single(self):
        """Test getting best image from single image."""
        client = LibrespotClient()
        result = client._get_best_image([
            {"url": "http://example.com/img.jpg", "width": 300, "height": 300}
        ])
        assert result == "http://example.com/img.jpg"

    def test_get_best_image_multiple(self):
        """Test getting best image selects largest."""
        client = LibrespotClient()
        result = client._get_best_image([
            {"url": "http://example.com/small.jpg", "width": 64, "height": 64},
            {"url": "http://example.com/large.jpg", "width": 640, "height": 640},
            {"url": "http://example.com/medium.jpg", "width": 300, "height": 300},
        ])
        assert result == "http://example.com/large.jpg"

    def test_parse_status_full(self):
        """Test parsing full status response."""
        client = LibrespotClient()
        data = {
            "stopped": False,
            "paused": False,
            "device_id": "abc123",
            "device_name": "Test Speaker",
            "username": "testuser",
            "device_type": "speaker",
            "play_origin": "playlist",
            "buffering": False,
            "volume_steps": 64,
            "volume": 75,
            "shuffle_context": True,
            "repeat_context": False,
            "repeat_track": True,
            "track": {
                "uri": "spotify:track:123",
                "name": "Test Song",
                "artist_names": ["Test Artist"],
                "album_name": "Test Album",
                "album_cover_url": "http://example.com/cover.jpg",
                "duration": 180000,
                "position": 60000,
                "release_date": "year:2020 month:5 day:15",
                "track_number": 3,
                "disc_number": 1,
            },
        }

        status = client._parse_status(data)

        assert status.active is True
        assert status.device_id == "abc123"
        assert status.device_name == "Test Speaker"
        assert status.username == "testuser"
        assert status.buffering is False

        assert status.track.uri == "spotify:track:123"
        assert status.track.name == "Test Song"
        assert status.track.artist == "Test Artist"
        assert status.track.album == "Test Album"
        assert status.track.artwork_url == "http://example.com/cover.jpg"
        assert status.track.duration_ms == 180000
        assert status.track.progress_ms == 60000
        assert status.track.is_playing is True
        assert status.track.volume == 75
        assert status.track.shuffle is True
        assert status.track.repeat_context is False
        assert status.track.repeat_track is True
        assert status.track.release_date == "2020-05-15"
        assert status.track.track_number == 3
        assert status.track.disc_number == 1

    def test_parse_status_stopped(self):
        """Test parsing status when stopped."""
        client = LibrespotClient()
        data = {
            "stopped": True,
            "paused": True,
        }

        status = client._parse_status(data)

        assert status.active is False
        assert status.track.is_playing is False

    def test_parse_status_no_track(self):
        """Test parsing status with no track."""
        client = LibrespotClient()
        data = {
            "stopped": False,
            "paused": True,
        }

        status = client._parse_status(data)

        assert status.active is True
        assert status.track.uri == ""
        assert status.track.name == ""


class TestLibrespotClientRequests:
    """Tests for LibrespotClient HTTP requests."""

    def test_request_connection_error(self):
        """Test handling connection error."""
        import requests as req_module

        client = LibrespotClient()

        with patch("librespot_client.requests.request") as mock_request:
            mock_request.side_effect = req_module.exceptions.ConnectionError("Connection refused")
            result = client._request("GET", "/status")

        assert result is None

    def test_request_timeout(self):
        """Test handling timeout."""
        import requests

        client = LibrespotClient()

        with patch("requests.request") as mock_request:
            mock_request.side_effect = requests.exceptions.Timeout()
            result = client._request("GET", "/status")

        assert result is None

    def test_request_success(self):
        """Test successful request."""
        client = LibrespotClient()

        mock_response = MagicMock()
        mock_response.text = '{"status": "ok"}'
        mock_response.json.return_value = {"status": "ok"}

        with patch("requests.request", return_value=mock_response):
            result = client._request("GET", "/status")

        assert result == {"status": "ok"}

    def test_request_empty_response(self):
        """Test handling empty response body."""
        client = LibrespotClient()

        mock_response = MagicMock()
        mock_response.text = ""

        with patch("requests.request", return_value=mock_response):
            result = client._request("POST", "/player/pause")

        assert result == {}

    def test_is_available_true(self):
        """Test is_available returns True when API responds."""
        client = LibrespotClient()

        with patch.object(client, "_request", return_value={"status": "ok"}):
            assert client.is_available() is True

    def test_is_available_false(self):
        """Test is_available returns False when API fails."""
        client = LibrespotClient()

        with patch.object(client, "_request", return_value=None):
            assert client.is_available() is False


class TestLibrespotClientPlayback:
    """Tests for LibrespotClient playback control."""

    def test_resume(self):
        """Test resume playback."""
        client = LibrespotClient()

        with patch.object(client, "_request", return_value={}) as mock:
            result = client.resume()
            mock.assert_called_once_with("POST", "/player/resume")

        assert result is True

    def test_pause(self):
        """Test pause playback."""
        client = LibrespotClient()

        with patch.object(client, "_request", return_value={}) as mock:
            result = client.pause()
            mock.assert_called_once_with("POST", "/player/pause")

        assert result is True

    def test_next_track(self):
        """Test skip to next track."""
        client = LibrespotClient()

        with patch.object(client, "_request", return_value={}) as mock:
            result = client.next_track()
            mock.assert_called_once_with("POST", "/player/next")

        assert result is True

    def test_seek(self):
        """Test seek to position."""
        client = LibrespotClient()

        with patch.object(client, "_request", return_value={}) as mock:
            result = client.seek(60000)
            mock.assert_called_once_with(
                "POST", "/player/seek",
                json_data={"position": 60000}
            )

        assert result is True

    def test_set_volume(self):
        """Test set volume."""
        client = LibrespotClient()

        with patch.object(client, "_request", return_value={}) as mock:
            result = client.set_volume(75)
            mock.assert_called_once_with(
                "POST", "/player/volume",
                json_data={"volume": 75}
            )

        assert result is True

    def test_set_volume_clamped(self):
        """Test volume is clamped to 0-100."""
        client = LibrespotClient()

        with patch.object(client, "_request", return_value={}) as mock:
            client.set_volume(150)
            mock.assert_called_once_with(
                "POST", "/player/volume",
                json_data={"volume": 100}
            )

        with patch.object(client, "_request", return_value={}) as mock:
            client.set_volume(-10)
            mock.assert_called_once_with(
                "POST", "/player/volume",
                json_data={"volume": 0}
            )

    def test_set_shuffle(self):
        """Test set shuffle."""
        client = LibrespotClient()

        with patch.object(client, "_request", return_value={}) as mock:
            result = client.set_shuffle(True)
            mock.assert_called_once_with(
                "POST", "/player/shuffle_context",
                json_data={"shuffle_context": True}
            )

        assert result is True

    def test_set_repeat_off(self):
        """Test set repeat off."""
        client = LibrespotClient()

        with patch.object(client, "_request", return_value={}) as mock:
            result = client.set_repeat("off")

        assert result is True
        assert mock.call_count == 2

    def test_set_repeat_track(self):
        """Test set repeat track."""
        client = LibrespotClient()

        with patch.object(client, "_request", return_value={}) as mock:
            result = client.set_repeat("track")

        assert result is True
        assert mock.call_count == 2

    def test_set_repeat_invalid(self):
        """Test set repeat with invalid mode."""
        client = LibrespotClient()

        with patch.object(client, "_request", return_value={}) as mock:
            result = client.set_repeat("invalid")

        assert result is False
        mock.assert_not_called()

    def test_play_uri(self):
        """Test play a URI."""
        client = LibrespotClient()

        with patch.object(client, "_request", return_value={}) as mock:
            result = client.play_uri("spotify:album:123")
            mock.assert_called_once_with(
                "POST", "/player/play",
                json_data={"uri": "spotify:album:123"}
            )

        assert result is True

    def test_play_uri_with_skip_to(self):
        """Test play URI with skip_to_uri."""
        client = LibrespotClient()

        with patch.object(client, "_request", return_value={}) as mock:
            result = client.play_uri("spotify:album:123", "spotify:track:456")
            mock.assert_called_once_with(
                "POST", "/player/play",
                json_data={"uri": "spotify:album:123", "skip_to_uri": "spotify:track:456"}
            )

        assert result is True

    def test_add_to_queue(self):
        """Test add to queue."""
        client = LibrespotClient()

        with patch.object(client, "_request", return_value={}) as mock:
            result = client.add_to_queue("spotify:track:123")
            mock.assert_called_once_with(
                "POST", "/player/add_to_queue",
                json_data={"uri": "spotify:track:123"}
            )

        assert result is True

    def test_get_queue(self):
        """Test get queue."""
        client = LibrespotClient()

        with patch.object(client, "_request", return_value={"tracks": [{"name": "Song"}]}):
            result = client.get_queue()

        assert result == [{"name": "Song"}]

    def test_get_queue_none(self):
        """Test get queue returns None on failure."""
        client = LibrespotClient()

        with patch.object(client, "_request", return_value=None):
            result = client.get_queue()

        assert result is None
