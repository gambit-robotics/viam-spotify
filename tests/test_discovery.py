"""Tests for audio discovery service."""

from unittest.mock import patch

import pytest

from audio_discovery import (
    BACKEND_ALSA,
    BACKEND_PIPEWIRE,
    BACKEND_PULSEAUDIO,
    AudioDiscovery,
)


class TestAudioDiscovery:
    """Tests for AudioDiscovery service."""

    def test_parse_pulseaudio_sinks(self):
        """Test parsing pactl list sinks output."""
        pactl_output = """Sink #0
	Name: alsa_output.pci-0000_00_1f.3.analog-stereo
	Description: Built-in Audio Analog Stereo
	State: SUSPENDED
	Sample Specification: s16le 2ch 44100Hz

Sink #1
	Name: alsa_output.usb-speaker
	Description: USB Speaker
	State: RUNNING
	Sample Specification: s24le 2ch 48000Hz
"""
        discovery = AudioDiscovery("test")

        with patch.object(discovery, "_run_command", return_value=pactl_output):
            sinks = discovery._discover_pulseaudio_sinks()

        assert len(sinks) == 2

        assert sinks[0]["name"] == "alsa_output.pci-0000_00_1f.3.analog-stereo"
        assert sinks[0]["description"] == "Built-in Audio Analog Stereo"
        assert sinks[0]["state"] == "SUSPENDED"
        assert sinks[0]["sample_rate"] == 44100
        assert sinks[0]["channels"] == 2
        assert sinks[0]["backend"] == BACKEND_PULSEAUDIO

        assert sinks[1]["name"] == "alsa_output.usb-speaker"
        assert sinks[1]["description"] == "USB Speaker"
        assert sinks[1]["state"] == "RUNNING"
        assert sinks[1]["sample_rate"] == 48000

    def test_parse_pulseaudio_sinks_empty(self):
        """Test parsing empty pactl output."""
        discovery = AudioDiscovery("test")

        with patch.object(discovery, "_run_command", return_value=None):
            sinks = discovery._discover_pulseaudio_sinks()

        assert sinks == []

    def test_parse_alsa_devices(self):
        """Test parsing aplay -l output."""
        aplay_output = """**** List of PLAYBACK Hardware Devices ****
card 0: PCH [HDA Intel PCH], device 0: ALC269VC Analog [ALC269VC Analog]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
card 1: USB [USB Audio], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
"""
        discovery = AudioDiscovery("test")

        with patch.object(discovery, "_run_command", return_value=aplay_output):
            devices = discovery._discover_alsa_devices()

        assert len(devices) == 2

        assert devices[0]["name"] == "hw:0,0"
        assert devices[0]["card_id"] == "PCH"
        assert devices[0]["card_num"] == 0
        assert devices[0]["device_num"] == 0
        assert devices[0]["backend"] == BACKEND_ALSA
        assert "HDA Intel PCH" in devices[0]["description"]

        assert devices[1]["name"] == "hw:1,0"
        assert devices[1]["card_id"] == "USB"

    def test_parse_alsa_devices_empty(self):
        """Test parsing empty aplay output."""
        discovery = AudioDiscovery("test")

        with patch.object(discovery, "_run_command", return_value=None):
            devices = discovery._discover_alsa_devices()

        assert devices == []

    def test_check_audio_backend_pipewire(self):
        """Test detecting PipeWire backend."""
        discovery = AudioDiscovery("test")

        def mock_run(cmd, *args, **kwargs):
            if cmd == ["pgrep", "-x", "pipewire"]:
                return "12345"
            return None

        with patch.object(discovery, "_run_command", side_effect=mock_run):
            backend = discovery._check_audio_backend()

        assert backend == BACKEND_PIPEWIRE

    def test_check_audio_backend_pulseaudio(self):
        """Test detecting PulseAudio backend."""
        discovery = AudioDiscovery("test")

        def mock_run(cmd, *args, **kwargs):
            if cmd == ["pgrep", "-x", "pipewire"]:
                return None
            if cmd == ["pactl", "info"]:
                return "Server Name: pulseaudio"
            return None

        with patch.object(discovery, "_run_command", side_effect=mock_run):
            backend = discovery._check_audio_backend()

        assert backend == BACKEND_PULSEAUDIO

    def test_check_audio_backend_alsa_fallback(self):
        """Test ALSA fallback when no PulseAudio/PipeWire."""
        discovery = AudioDiscovery("test")

        with patch.object(discovery, "_run_command", return_value=None):
            backend = discovery._check_audio_backend()

        assert backend == BACKEND_ALSA

    def test_run_command_not_found(self):
        """Test handling command not found."""
        discovery = AudioDiscovery("test")

        with patch("subprocess.run", side_effect=FileNotFoundError()):
            result = discovery._run_command(["nonexistent"])

        assert result is None

    def test_run_command_timeout(self):
        """Test handling command timeout."""
        import subprocess

        discovery = AudioDiscovery("test")

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5)):
            result = discovery._run_command(["slow_command"])

        assert result is None


class TestAudioDiscoveryAsync:
    """Tests for async discovery methods."""

    @pytest.mark.asyncio
    async def test_discover_resources_unique_names(self):
        """Test that duplicate device descriptions get unique names."""
        discovery = AudioDiscovery("test")

        # Mock two PulseAudio devices with same description
        duplicate_sinks = [
            {"name": "sink1", "description": "USB Audio", "backend": "pulseaudio"},
            {"name": "sink2", "description": "USB Audio", "backend": "pulseaudio"},
            {"name": "sink3", "description": "USB Audio", "backend": "pulseaudio"},
        ]

        with patch.object(discovery, "_check_audio_backend", return_value="pulseaudio"):
            with patch.object(discovery, "_discover_pulseaudio_sinks", return_value=duplicate_sinks):
                with patch.object(discovery, "_discover_alsa_devices", return_value=[]):
                    with patch("platform.system", return_value="Linux"):
                        configs = await discovery.discover_resources()

        # Should have 3 configs with unique names
        assert len(configs) == 3
        names = [c.name for c in configs]
        assert names[0] == "usb-audio"
        assert names[1] == "usb-audio-2"
        assert names[2] == "usb-audio-3"
