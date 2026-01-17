import base64
import io
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import qrcode
import requests
import spotipy

SCOPES = [
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read",
    "user-read-recently-played",
]

SPOTIFY_DEVICE_CODE_URL = "https://accounts.spotify.com/api/device/code"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"


@dataclass
class TokenInfo:
    access_token: str
    refresh_token: str
    token_type: str
    expires_at: int
    scope: str

    def is_expired(self) -> bool:
        return time.time() >= self.expires_at - 60

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TokenInfo":
        # Handle both expires_at and expires_in formats
        expires_at = data.get("expires_at")
        if expires_at is None and "expires_in" in data:
            expires_at = int(time.time()) + data["expires_in"]
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            token_type=data["token_type"],
            expires_at=expires_at,
            scope=data.get("scope", ""),
        )


@dataclass
class DeviceAuthInfo:
    """Holds pending device authorization info."""
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: Optional[str]
    expires_at: float
    interval: int

    def is_expired(self) -> bool:
        return time.time() >= self.expires_at


def generate_qr_base64(url: str) -> str:
    """Generate a QR code as base64 PNG."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return base64.b64encode(buffer.getvalue()).decode("utf-8")


class TokenManager:
    def __init__(self, client_id: str, token_path: str):
        self.client_id = client_id
        self.token_path = Path(token_path)
        self._token_info: Optional[TokenInfo] = None
        self._spotify: Optional[spotipy.Spotify] = None
        self._pending_auth: Optional[DeviceAuthInfo] = None

        self._load_token()

    def _load_token(self) -> None:
        if self.token_path.exists():
            try:
                with open(self.token_path, "r") as f:
                    data = json.load(f)
                    self._token_info = TokenInfo.from_dict(data)
            except (json.JSONDecodeError, KeyError):
                self._token_info = None

    def _save_token(self) -> None:
        if self._token_info:
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_path, "w") as f:
                json.dump(self._token_info.to_dict(), f)

    def _clear_token(self) -> None:
        self._token_info = None
        self._spotify = None
        if self.token_path.exists():
            self.token_path.unlink()

    def start_device_auth(self) -> DeviceAuthInfo:
        """
        Start the device authorization flow.
        Returns device auth info with user_code and verification URL.
        """
        response = requests.post(
            SPOTIFY_DEVICE_CODE_URL,
            data={
                "client_id": self.client_id,
                "scope": " ".join(SCOPES),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        self._pending_auth = DeviceAuthInfo(
            device_code=data["device_code"],
            user_code=data["user_code"],
            verification_uri=data["verification_uri"],
            verification_uri_complete=data.get("verification_uri_complete"),
            expires_at=time.time() + data["expires_in"],
            interval=data.get("interval", 5),
        )
        return self._pending_auth

    def get_auth_qr_data(self) -> dict:
        """
        Get QR code and auth info for device authorization.
        Starts a new auth flow if needed.
        """
        if self._pending_auth is None or self._pending_auth.is_expired():
            self.start_device_auth()

        # Use verification_uri_complete if available (includes code in URL)
        # Otherwise use base verification_uri
        qr_url = (
            self._pending_auth.verification_uri_complete
            or self._pending_auth.verification_uri
        )

        return {
            "qr_image": generate_qr_base64(qr_url),
            "auth_url": qr_url,
            "user_code": self._pending_auth.user_code,
            "verification_uri": self._pending_auth.verification_uri,
            "expires_in": int(self._pending_auth.expires_at - time.time()),
        }

    def poll_for_token(self) -> dict:
        """
        Poll Spotify to check if user has completed authorization.
        Returns {"authenticated": True/False, "error": str or None}
        """
        if self._pending_auth is None:
            return {"authenticated": False, "error": "No pending authorization"}

        if self._pending_auth.is_expired():
            self._pending_auth = None
            return {"authenticated": False, "error": "Authorization expired"}

        try:
            response = requests.post(
                SPOTIFY_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "device_code": self._pending_auth.device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )

            if response.status_code == 200:
                # Success - got tokens
                data = response.json()
                self._token_info = TokenInfo.from_dict(data)
                self._save_token()
                self._spotify = None
                self._pending_auth = None
                return {"authenticated": True, "error": None}

            # Handle error responses
            error_data = response.json()
            error = error_data.get("error", "unknown_error")

            if error == "authorization_pending":
                # User hasn't completed auth yet - this is normal
                return {"authenticated": False, "error": None, "pending": True}
            elif error == "slow_down":
                # We're polling too fast
                return {"authenticated": False, "error": None, "pending": True}
            elif error == "expired_token":
                self._pending_auth = None
                return {"authenticated": False, "error": "Authorization expired"}
            elif error == "access_denied":
                self._pending_auth = None
                return {"authenticated": False, "error": "User denied access"}
            else:
                return {"authenticated": False, "error": error}

        except requests.RequestException as e:
            return {"authenticated": False, "error": str(e)}

    def refresh_if_needed(self) -> bool:
        if not self._token_info:
            return False

        if self._token_info.is_expired():
            try:
                response = requests.post(
                    SPOTIFY_TOKEN_URL,
                    data={
                        "client_id": self.client_id,
                        "grant_type": "refresh_token",
                        "refresh_token": self._token_info.refresh_token,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()

                # Refresh response may not include refresh_token, keep the old one
                if "refresh_token" not in data:
                    data["refresh_token"] = self._token_info.refresh_token

                self._token_info = TokenInfo.from_dict(data)
                self._save_token()
                self._spotify = None
                return True
            except Exception:
                self._clear_token()
                return False
        return True

    def is_authenticated(self) -> bool:
        if not self._token_info:
            return False
        return self.refresh_if_needed()

    def get_spotify(self) -> Optional[spotipy.Spotify]:
        if not self.is_authenticated():
            return None

        if self._spotify is None:
            self._spotify = spotipy.Spotify(auth=self._token_info.access_token)
        return self._spotify

    def get_current_user(self) -> Optional[str]:
        sp = self.get_spotify()
        if sp:
            try:
                user = sp.current_user()
                return user.get("display_name") or user.get("id")
            except Exception:
                return None
        return None

    def logout(self) -> None:
        self._clear_token()
        self._pending_auth = None
