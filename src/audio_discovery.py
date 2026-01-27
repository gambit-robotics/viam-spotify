"""
Audio device discovery service.

Discovers available audio output devices on the system to help users
configure the spotify service with the correct audio_device setting.
"""
import asyncio
import platform
import re
import subprocess
from typing import Any, ClassVar, Mapping, Optional, Sequence

from typing_extensions import Self
from viam.logging import getLogger
from viam.module.types import Reconfigurable
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import ResourceName
from viam.resource.base import ResourceBase
from viam.resource.registry import Registry, ResourceCreatorRegistration
from viam.resource.types import Model, ModelFamily
from viam.services.discovery import Discovery

LOGGER = getLogger("gambit-robotics:service:audio-discovery")

# Backend constants
BACKEND_PIPEWIRE = "pipewire"
BACKEND_PULSEAUDIO = "pulseaudio"
BACKEND_ALSA = "alsa"


class AudioDiscovery(Discovery, Reconfigurable):
    """Discovers audio output devices available on the system."""

    MODEL: ClassVar[Model] = Model(
        ModelFamily("gambit-robotics", "service"), "audio-discovery"
    )

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
        return [], []

    def reconfigure(
        self,
        config: ComponentConfig,
        dependencies: Mapping[ResourceName, ResourceBase],
    ) -> None:
        pass

    async def close(self) -> None:
        pass

    def _run_command(self, cmd: list[str], timeout: int = 5) -> Optional[str]:
        """Run a shell command and return output."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode == 0:
                return result.stdout
            LOGGER.warning(f"Command '{cmd[0]}' exited with code {result.returncode}")
            return None
        except FileNotFoundError:
            LOGGER.warning(f"Command '{cmd[0]}' not found - is it installed?")
            return None
        except subprocess.TimeoutExpired:
            LOGGER.warning(f"Command '{cmd[0]}' timed out after {timeout}s")
            return None
        except Exception as e:
            LOGGER.warning(f"Command '{cmd[0]}' failed: {e}")
            return None

    def _discover_pulseaudio_sinks(self) -> list[dict]:
        """Discover PulseAudio/PipeWire sinks using pactl."""
        devices = []
        output = self._run_command(["pactl", "list", "sinks"])
        if not output:
            return devices

        current_sink: dict = {}
        for line in output.split("\n"):
            line = line.strip()

            if line.startswith("Sink #"):
                if current_sink:
                    devices.append(current_sink)
                current_sink = {"backend": BACKEND_PULSEAUDIO}

            elif line.startswith("Name:"):
                current_sink["name"] = line.split(":", 1)[1].strip()

            elif line.startswith("Description:"):
                current_sink["description"] = line.split(":", 1)[1].strip()

            elif line.startswith("State:"):
                current_sink["state"] = line.split(":", 1)[1].strip()

            elif "Sample Specification:" in line:
                spec = line.split(":", 1)[1].strip()
                match = re.search(r"(\d+)Hz", spec)
                if match:
                    current_sink["sample_rate"] = int(match.group(1))
                match = re.search(r"(\d+)ch", spec)
                if match:
                    current_sink["channels"] = int(match.group(1))

        if current_sink:
            devices.append(current_sink)

        return devices

    def _discover_alsa_devices(self) -> list[dict]:
        """Discover ALSA devices using aplay."""
        devices = []
        output = self._run_command(["aplay", "-l"])
        if not output:
            return devices

        for line in output.split("\n"):
            match = re.match(r"card (\d+): ([\w-]+) \[([^\]]+)\], device (\d+): (.+)", line)
            if match:
                card_num = match.group(1)
                card_id = match.group(2)
                card_name = match.group(3)
                device_num = match.group(4)
                device_name = match.group(5)

                devices.append({
                    "backend": BACKEND_ALSA,
                    "name": f"hw:{card_num},{device_num}",
                    "description": f"{card_name} - {device_name}",
                    "card_id": card_id,
                    "card_num": int(card_num),
                    "device_num": int(device_num),
                })

        return devices

    def _check_audio_backend(self) -> str:
        """Determine which audio backend is available."""
        if self._run_command(["pgrep", "-x", "pipewire"]):
            return BACKEND_PIPEWIRE
        if self._run_command(["pactl", "info"]):
            return BACKEND_PULSEAUDIO
        return BACKEND_ALSA

    async def discover_resources(
        self,
        *,
        extra: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> list[ComponentConfig]:
        """Discover available audio output devices."""
        if platform.system() != "Linux":
            LOGGER.warning("Audio discovery only supported on Linux")
            return []

        loop = asyncio.get_running_loop()

        # Run all discovery in parallel
        backend, pulse_devices, alsa_devices = await asyncio.gather(
            loop.run_in_executor(None, self._check_audio_backend),
            loop.run_in_executor(None, self._discover_pulseaudio_sinks),
            loop.run_in_executor(None, self._discover_alsa_devices),
        )

        configs = []

        # Add PulseAudio/PipeWire sinks
        for i, device in enumerate(pulse_devices):
            config = ComponentConfig(
                name=f"spotify-{device.get('name', f'sink-{i}')}",
                api="rdk:service:generic",
                model="gambit-robotics:service:spotify",
            )
            config.attributes.fields["audio_backend"].string_value = BACKEND_PULSEAUDIO
            config.attributes.fields["audio_device"].string_value = device.get("name", "default")
            config.attributes.fields["device_name"].string_value = f"Spotify ({device.get('description', 'Speaker')})"

            if "description" in device:
                config.attributes.fields["_description"].string_value = device["description"]
            if "sample_rate" in device:
                config.attributes.fields["_sample_rate"].number_value = device["sample_rate"]
            if "channels" in device:
                config.attributes.fields["_channels"].number_value = device["channels"]
            if "state" in device:
                config.attributes.fields["_state"].string_value = device["state"]

            configs.append(config)

        # Add ALSA devices
        for i, device in enumerate(alsa_devices):
            config = ComponentConfig(
                name=f"spotify-alsa-{device.get('card_id', f'card-{i}')}",
                api="rdk:service:generic",
                model="gambit-robotics:service:spotify",
            )
            config.attributes.fields["audio_backend"].string_value = BACKEND_ALSA
            config.attributes.fields["audio_device"].string_value = device.get("name", "default")
            config.attributes.fields["device_name"].string_value = f"Spotify ({device.get('description', 'Speaker')})"

            if "description" in device:
                config.attributes.fields["_description"].string_value = device["description"]

            configs.append(config)

        LOGGER.info(
            f"Discovered {len(pulse_devices)} PulseAudio/PipeWire sinks, "
            f"{len(alsa_devices)} ALSA devices (backend: {backend})"
        )

        return configs

    async def do_command(
        self,
        command: Mapping[str, Any],
        *,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> Mapping[str, Any]:
        """Handle custom commands."""
        cmd = command.get("command", "")
        loop = asyncio.get_running_loop()

        if cmd == "get_backend":
            backend = await loop.run_in_executor(None, self._check_audio_backend)
            return {"backend": backend}

        if cmd == "list_sinks":
            sinks = await loop.run_in_executor(None, self._discover_pulseaudio_sinks)
            return {"sinks": sinks}

        if cmd == "list_alsa":
            devices = await loop.run_in_executor(None, self._discover_alsa_devices)
            return {"devices": devices}

        return {"error": f"Unknown command: {cmd}"}


Registry.register_resource_creator(
    Discovery.API,
    AudioDiscovery.MODEL,
    ResourceCreatorRegistration(AudioDiscovery.new, AudioDiscovery.validate_config),
)
