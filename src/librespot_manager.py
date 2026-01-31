"""
Manager for go-librespot subprocess.

Handles starting, monitoring, and restarting go-librespot.
"""
import os
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

import requests
import yaml
from viam.logging import getLogger

LOGGER = getLogger("gambit-robotics:service:spotify")

# Default paths
DEFAULT_CONFIG_DIR = os.path.expanduser("~/.config/go-librespot")


def _find_bundled_binary() -> str:
    """Find the go-librespot binary bundled with the module."""
    # Check VIAM_MODULE_ROOT first (set by viam-server)
    module_root = os.environ.get("VIAM_MODULE_ROOT")
    if module_root:
        bundled_path = os.path.join(module_root, "go-librespot")
        if os.path.isfile(bundled_path):
            return bundled_path

    # Fallback: look relative to this file's directory (for local dev)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for search_dir in [script_dir, os.path.dirname(script_dir)]:
        bundled_path = os.path.join(search_dir, "go-librespot")
        if os.path.isfile(bundled_path):
            return bundled_path

    # Not found - return expected path for error message
    if module_root:
        return os.path.join(module_root, "go-librespot")
    return "/usr/local/bin/go-librespot"


DEFAULT_BINARY_PATH = _find_bundled_binary()


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
        binary_path: str | None = None,
        config_dir: str | None = None,
    ):
        self.device_name = device_name
        self.api_port = api_port
        self.audio_backend = audio_backend
        self.audio_device = audio_device
        self.bitrate = bitrate
        self.initial_volume = initial_volume
        self.binary_path = binary_path or DEFAULT_BINARY_PATH
        self.config_dir = Path(config_dir or DEFAULT_CONFIG_DIR)

        LOGGER.info(f"Using go-librespot binary: {self.binary_path}")

        self._process: subprocess.Popen | None = None
        self._monitor_thread: threading.Thread | None = None
        self._should_run = False
        self._restart_count = 0
        self._max_restarts = 5
        self._restart_delay = 2.0
        self._api_ready_timeout = 10.0

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

            # HTTP API server (localhost only, no CORS needed)
            "server": {
                "enabled": True,
                "address": "127.0.0.1",
                "port": self.api_port,
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
            module_root = os.environ.get("VIAM_MODULE_ROOT", "unknown")
            LOGGER.error(f"Module root: {module_root}")
            LOGGER.error(
                "The go-librespot binary should be bundled with the module. "
                "Try redeploying the module or check that the build included go-librespot."
            )
            return False
        if not os.access(self.binary_path, os.X_OK):
            LOGGER.warning(f"go-librespot binary at {self.binary_path} is not executable, fixing...")
            try:
                os.chmod(self.binary_path, 0o755)
                LOGGER.info(f"Made {self.binary_path} executable")
            except OSError as e:
                LOGGER.error(f"Failed to make binary executable: {e}")
                return False
        return True

    def _kill_orphaned_process(self) -> bool:
        """Kill any orphaned go-librespot process using our port.

        This handles the case where the module was restarted but the old
        go-librespot subprocess is still running.

        Returns:
            True if port is now available, False if we couldn't free it.
        """
        try:
            # Find process using the port with lsof
            result = subprocess.run(
                ["lsof", "-ti", f"tcp:{self.api_port}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return True  # No process found, port should be available

            pids = result.stdout.strip().split("\n")
            for pid_str in pids:
                try:
                    pid = int(pid_str.strip())

                    # Verify it's actually a go-librespot process before killing
                    cmd_result = subprocess.run(
                        ["ps", "-p", str(pid), "-o", "comm="],
                        capture_output=True,
                        text=True,
                        timeout=2,
                    )
                    process_name = cmd_result.stdout.strip()
                    if "go-librespot" not in process_name:
                        LOGGER.warning(
                            f"Port {self.api_port} in use by '{process_name}' (PID {pid}), not killing"
                        )
                        continue

                    LOGGER.warning(f"Found orphaned go-librespot process {pid} on port {self.api_port}, killing...")
                    os.kill(pid, signal.SIGTERM)
                except (ValueError, ProcessLookupError):
                    continue
                except subprocess.TimeoutExpired:
                    continue

            # Wait briefly for process to exit
            time.sleep(0.5)
            return True

        except FileNotFoundError:
            # lsof not available, try fuser as fallback
            try:
                result = subprocess.run(
                    ["fuser", "-k", f"{self.api_port}/tcp"],
                    capture_output=True,
                    timeout=5,
                )
                time.sleep(0.5)
                return True
            except FileNotFoundError:
                LOGGER.debug("Neither lsof nor fuser available for orphan cleanup")
                return True  # Can't check, let port check handle it
        except Exception as e:
            LOGGER.debug(f"Error checking for orphaned process: {e}")
            return True  # Continue anyway, port check will catch issues

    def _check_port_available(self, retries: int = 5, delay: float = 1.0) -> bool:
        """Check if the API port is available, with retries for TIME_WAIT state."""
        for attempt in range(retries):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind(("127.0.0.1", self.api_port))
                    return True
            except OSError:
                if attempt < retries - 1:
                    LOGGER.debug(f"Port {self.api_port} not available, retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                LOGGER.error(
                    f"Port {self.api_port} is already in use after {retries} attempts. "
                    "Another instance may be running or choose a different api_port."
                )
                return False
        return False

    def _start_process(self) -> bool:
        """Start the go-librespot process."""
        if not self._check_binary():
            return False

        # Kill any orphaned go-librespot from a previous module instance
        self._kill_orphaned_process()

        if not self._check_port_available():
            return False

        self._write_config()

        try:
            # Capture stderr to see errors, stdout to DEVNULL
            self._process = subprocess.Popen(
                [self.binary_path, "--config_dir", str(self.config_dir)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            LOGGER.info(f"Started go-librespot (PID: {self._process.pid})")
            LOGGER.debug(f"Config dir: {self.config_dir}")
            return True
        except Exception as e:
            LOGGER.error(f"Failed to start go-librespot: {e}")
            return False

    def _wait_for_api_ready(self, timeout: float | None = None, poll_interval: float = 0.2) -> bool:
        """Wait for the go-librespot HTTP API to become responsive.

        Args:
            timeout: Maximum time to wait in seconds. Defaults to self._api_ready_timeout.
            poll_interval: Time between polling attempts in seconds.

        Returns:
            True if API became ready, False if timeout exceeded or shutdown requested.
        """
        if timeout is None:
            timeout = self._api_ready_timeout

        start_time = time.time()
        status_url = f"{self.api_url}/status"

        while time.time() - start_time < timeout:
            # Check if shutdown was requested
            if not self._should_run:
                LOGGER.debug("Shutdown requested while waiting for API ready")
                return False

            # Check if process died while waiting
            if self._process is None or self._process.poll() is not None:
                LOGGER.error("go-librespot process died while waiting for API ready")
                return False

            try:
                response = requests.get(status_url, timeout=1.0)
                if response.status_code == 200:
                    elapsed = time.time() - start_time
                    LOGGER.info(f"go-librespot API ready after {elapsed:.2f}s")
                    return True
            except requests.exceptions.RequestException:
                # API not ready yet, continue polling
                pass

            time.sleep(poll_interval)

        LOGGER.error(f"Timeout waiting for go-librespot API after {timeout}s")
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
                    # Capture stderr using communicate() to avoid blocking
                    stderr_output = ""
                    try:
                        _, stderr_output = self._process.communicate(timeout=1)
                    except subprocess.TimeoutExpired:
                        self._process.kill()
                        _, stderr_output = self._process.communicate()
                    except Exception:
                        pass

                    LOGGER.warning(f"go-librespot exited with code {return_code}")
                    if stderr_output:
                        LOGGER.error(f"go-librespot stderr: {stderr_output}")
                    self._process = None

                    if self._should_run and self._restart_count < self._max_restarts:
                        self._restart_count += 1
                        LOGGER.info(
                            f"Restarting go-librespot ({self._restart_count}/{self._max_restarts})..."
                        )
                        time.sleep(self._restart_delay)
                        if self._start_process():
                            # Wait for API to be ready after restart
                            if not self._wait_for_api_ready():
                                LOGGER.warning("go-librespot restarted but API not responsive, stopping")
                                self._stop_process()
                                # Let the next loop iteration trigger another restart attempt
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

        # Wait for the HTTP API to become responsive before returning success
        if not self._wait_for_api_ready():
            LOGGER.error("go-librespot started but API not responsive, stopping")
            self._stop_process()
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
