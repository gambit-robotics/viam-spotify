"""Tests for librespot manager."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from librespot_manager import LibrespotManager


class TestLibrespotManagerConfig:
    """Tests for LibrespotManager configuration."""

    def test_default_config_dir(self):
        """Test default config directory is in user home."""
        manager = LibrespotManager(device_name="Test")
        assert str(manager.config_dir).startswith(os.path.expanduser("~"))
        assert "go-librespot" in str(manager.config_dir)

    def test_custom_config_dir(self):
        """Test custom config directory."""
        manager = LibrespotManager(
            device_name="Test",
            config_dir="/custom/path"
        )
        assert manager.config_dir == Path("/custom/path")

    def test_api_url(self):
        """Test API URL generation."""
        manager = LibrespotManager(device_name="Test", api_port=1234)
        assert manager.api_url == "http://127.0.0.1:1234"

    def test_config_path(self):
        """Test config file path."""
        manager = LibrespotManager(
            device_name="Test",
            config_dir="/tmp/test"
        )
        assert manager.config_path == Path("/tmp/test/config.yml")

    def test_generate_config(self):
        """Test config generation."""
        manager = LibrespotManager(
            device_name="My Speaker",
            api_port=3678,
            audio_backend="pulseaudio",
            audio_device="default",
            bitrate=320,
            initial_volume=50,
        )

        config = manager._generate_config()

        assert config["device_name"] == "My Speaker"
        assert config["device_type"] == "speaker"
        assert config["audio_backend"] == "pulseaudio"
        assert config["audio_device"] == "default"
        assert config["bitrate"] == 320
        assert config["initial_volume"] == 50
        assert config["zeroconf_enabled"] is True
        assert config["server"]["enabled"] is True
        assert config["server"]["port"] == 3678
        assert config["server"]["address"] == "127.0.0.1"
        # CORS should not be present (security fix)
        assert "allow_origin" not in config["server"]

    def test_generate_config_alsa(self):
        """Test config generation with ALSA backend."""
        manager = LibrespotManager(
            device_name="ALSA Speaker",
            audio_backend="alsa",
            audio_device="hw:0,0",
        )

        config = manager._generate_config()

        assert config["audio_backend"] == "alsa"
        assert config["audio_device"] == "hw:0,0"


class TestLibrespotManagerBinaryCheck:
    """Tests for binary existence checks."""

    def test_check_binary_exists(self):
        """Test binary check when file exists and is executable."""
        manager = LibrespotManager(device_name="Test")

        with patch("pathlib.Path.exists", return_value=True):
            with patch("os.access", return_value=True):
                assert manager._check_binary() is True

    def test_check_binary_not_found(self):
        """Test binary check when file doesn't exist."""
        manager = LibrespotManager(device_name="Test")

        with patch("pathlib.Path.exists", return_value=False):
            assert manager._check_binary() is False

    def test_check_binary_not_executable(self):
        """Test binary check when file isn't executable."""
        manager = LibrespotManager(device_name="Test")

        with patch("pathlib.Path.exists", return_value=True):
            with patch("os.access", return_value=False):
                assert manager._check_binary() is False


class TestLibrespotManagerPortCheck:
    """Tests for port availability checks."""

    def test_port_available(self):
        """Test port check when port is available."""
        manager = LibrespotManager(device_name="Test", api_port=19999)

        # Use a high port that's unlikely to be in use
        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_socket.return_value.__enter__ = MagicMock(return_value=mock_sock)
            mock_socket.return_value.__exit__ = MagicMock(return_value=False)
            mock_sock.bind = MagicMock()

            assert manager._check_port_available() is True

    def test_port_in_use(self):
        """Test port check when port is in use."""
        manager = LibrespotManager(device_name="Test", api_port=3678)

        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_socket.return_value.__enter__ = MagicMock(return_value=mock_sock)
            mock_socket.return_value.__exit__ = MagicMock(return_value=False)
            mock_sock.bind = MagicMock(side_effect=OSError("Address in use"))

            assert manager._check_port_available() is False


class TestLibrespotManagerLifecycle:
    """Tests for process lifecycle management."""

    def test_is_running_false_when_no_process(self):
        """Test is_running returns False when no process."""
        manager = LibrespotManager(device_name="Test")
        assert manager.is_running() is False

    def test_is_running_false_when_process_exited(self):
        """Test is_running returns False when process exited."""
        manager = LibrespotManager(device_name="Test")

        mock_process = MagicMock()
        mock_process.poll.return_value = 1  # Non-None means exited
        manager._process = mock_process

        assert manager.is_running() is False

    def test_is_running_true_when_process_alive(self):
        """Test is_running returns True when process is alive."""
        manager = LibrespotManager(device_name="Test")

        mock_process = MagicMock()
        mock_process.poll.return_value = None  # None means still running
        manager._process = mock_process

        assert manager.is_running() is True

    def test_start_fails_without_binary(self):
        """Test start fails when binary doesn't exist."""
        manager = LibrespotManager(device_name="Test")

        with patch.object(manager, "_check_binary", return_value=False):
            assert manager.start() is False
            assert manager._should_run is False

    def test_start_fails_when_port_in_use(self):
        """Test start fails when port is in use."""
        manager = LibrespotManager(device_name="Test")

        with patch.object(manager, "_check_binary", return_value=True):
            with patch.object(manager, "_check_port_available", return_value=False):
                assert manager.start() is False

    def test_stop_sends_sigterm(self):
        """Test stop sends SIGTERM to process."""
        import signal

        manager = LibrespotManager(device_name="Test")

        mock_process = MagicMock()
        mock_process.wait = MagicMock()
        manager._process = mock_process
        manager._should_run = True

        manager.stop()

        mock_process.send_signal.assert_called_once_with(signal.SIGTERM)
        assert manager._should_run is False

    def test_stop_kills_on_timeout(self):
        """Test stop kills process if SIGTERM times out."""
        import signal
        import subprocess

        manager = LibrespotManager(device_name="Test")

        mock_process = MagicMock()
        mock_process.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5), None]
        manager._process = mock_process
        manager._should_run = True

        manager.stop()

        mock_process.send_signal.assert_called_once_with(signal.SIGTERM)
        mock_process.kill.assert_called_once()

    def test_stop_noop_when_no_process(self):
        """Test stop does nothing when no process."""
        manager = LibrespotManager(device_name="Test")
        manager._process = None

        # Should not raise
        manager.stop()


class TestLibrespotManagerRestarts:
    """Tests for restart behavior."""

    def test_max_restarts_default(self):
        """Test default max restarts."""
        manager = LibrespotManager(device_name="Test")
        assert manager._max_restarts == 5

    def test_restart_delay_default(self):
        """Test default restart delay."""
        manager = LibrespotManager(device_name="Test")
        assert manager._restart_delay == 2.0

    def test_restart_count_reset_on_start(self):
        """Test restart count is reset when start is called."""
        manager = LibrespotManager(device_name="Test")
        manager._restart_count = 3

        with patch.object(manager, "_check_binary", return_value=False):
            manager.start()

        assert manager._restart_count == 0
