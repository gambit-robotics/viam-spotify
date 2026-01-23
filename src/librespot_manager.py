"""
Manager for go-librespot subprocess.

Handles starting, monitoring, and restarting go-librespot.
"""
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

import yaml

from viam.logging import getLogger

LOGGER = getLogger("gambit-robotics:service:spotify")

# Default paths
DEFAULT_BINARY_PATH = "/usr/local/bin/go-librespot"
DEFAULT_CONFIG_DIR = "/tmp/go-librespot"


class LibrespotManager:
    """Manages the go-librespot subprocess."""

    def __init__(
        self,
        device_name: str,
        api_port: int = 3678,
        audio_backend: str = "pulseaudio",
        audio_device: str = "default",
        bitrate: int = 320,
        initial_volume: int = 50,
        binary_path: Optional[str] = None,
        config_dir: Optional[str] = None,
    ):
        self.device_name = device_name
        self.api_port = api_port
        self.audio_backend = audio_backend
        self.audio_device = audio_device
        self.bitrate = bitrate
        self.initial_volume = initial_volume
        self.binary_path = binary_path or DEFAULT_BINARY_PATH
        self.config_dir = Path(config_dir or DEFAULT_CONFIG_DIR)

        self._process: Optional[subprocess.Popen] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._should_run = False
        self._restart_count = 0
        self._max_restarts = 5
        self._restart_delay = 2.0

    @property
    def config_path(self) -> Path:
        return self.config_dir / "config.yml"

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    def _generate_config(self) -> dict:
        """Generate go-librespot configuration."""
        config = {
            # Device identification
            "device_name": self.device_name,
            "device_type": "speaker",

            # Audio settings
            "audio_backend": self.audio_backend,
            "audio_device": self.audio_device,
            "bitrate": self.bitrate,

            # Volume settings
            "initial_volume": self.initial_volume,
            "volume_steps": 64,

            # Zeroconf discovery (allows Spotify app to find device)
            "zeroconf_enabled": True,
            "zeroconf_port": 0,  # Auto-select port

            # Credentials - use zeroconf with persistence
            "credentials": {
                "type": "zeroconf",
                "zeroconf": {
                    "persist_credentials": True,
                },
            },

            # HTTP API server
            "server": {
                "enabled": True,
                "address": "127.0.0.1",
                "port": self.api_port,
                "allow_origin": "*",
            },

            # Logging
            "log_level": "info",
        }

        return config

    def _write_config(self) -> None:
        """Write configuration to YAML file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        config = self._generate_config()

        with open(self.config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False)

        LOGGER.debug(f"Wrote go-librespot config to {self.config_path}")

    def _check_binary(self) -> bool:
        """Check if go-librespot binary exists and is executable."""
        binary = Path(self.binary_path)
        if not binary.exists():
            LOGGER.error(f"go-librespot binary not found at {self.binary_path}")
            LOGGER.error("Run setup.sh to install go-librespot")
            return False
        if not os.access(self.binary_path, os.X_OK):
            LOGGER.error(f"go-librespot binary at {self.binary_path} is not executable")
            return False
        return True

    def _start_process(self) -> bool:
        """Start the go-librespot process."""
        if not self._check_binary():
            return False

        self._write_config()

        try:
            # Use DEVNULL to avoid stdout buffer deadlock
            self._process = subprocess.Popen(
                [self.binary_path, "-config_path", str(self.config_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            LOGGER.info(f"Started go-librespot (PID: {self._process.pid})")
            return True
        except Exception as e:
            LOGGER.error(f"Failed to start go-librespot: {e}")
            return False

    def _stop_process(self) -> None:
        """Stop the go-librespot process."""
        if self._process is None:
            return

        try:
            self._process.send_signal(signal.SIGTERM)
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                LOGGER.warning("go-librespot did not stop gracefully, killing...")
                self._process.kill()
                self._process.wait()
            LOGGER.info("go-librespot stopped")
        except Exception as e:
            LOGGER.error(f"Error stopping go-librespot: {e}")
        finally:
            self._process = None

    def _monitor_loop(self) -> None:
        """Monitor thread that watches the process and restarts if needed."""
        while self._should_run:
            if self._process is not None:
                return_code = self._process.poll()
                if return_code is not None:
                    LOGGER.warning(f"go-librespot exited with code {return_code}")
                    self._process = None

                    if self._should_run and self._restart_count < self._max_restarts:
                        self._restart_count += 1
                        LOGGER.info(
                            f"Restarting go-librespot ({self._restart_count}/{self._max_restarts})..."
                        )
                        time.sleep(self._restart_delay)
                        self._start_process()
                    elif self._restart_count >= self._max_restarts:
                        LOGGER.error("Max restarts reached, giving up")
                        self._should_run = False

            time.sleep(1)

    def start(self) -> bool:
        """Start go-librespot and monitoring thread."""
        if self._should_run:
            LOGGER.warning("LibrespotManager already running")
            return True

        self._should_run = True
        self._restart_count = 0

        if not self._start_process():
            self._should_run = False
            return False

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="librespot-monitor",
        )
        self._monitor_thread.start()

        return True

    def stop(self) -> None:
        """Stop go-librespot and monitoring thread."""
        self._should_run = False
        self._stop_process()

        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=2)
            self._monitor_thread = None

    def is_running(self) -> bool:
        """Check if go-librespot is running."""
        return self._process is not None and self._process.poll() is None
