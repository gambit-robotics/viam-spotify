import json
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

import spotipy
from spotipy.oauth2 import SpotifyPKCE


SCOPES = [
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read",
    "user-read-recently-played",
]


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
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            token_type=data["token_type"],
            expires_at=data["expires_at"],
            scope=data["scope"],
        )


class TokenManager:
    def __init__(
        self,
        client_id: str,
        redirect_uri: str,
        token_path: str,
    ):
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.token_path = Path(token_path)
        self._token_info: Optional[TokenInfo] = None
        self._spotify: Optional[spotipy.Spotify] = None
        self._pending_oauth: Optional[SpotifyPKCE] = None

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

    def _create_oauth(self) -> SpotifyPKCE:
        return SpotifyPKCE(
            client_id=self.client_id,
            redirect_uri=self.redirect_uri,
            scope=" ".join(SCOPES),
            open_browser=False,
        )

    def get_auth_url(self) -> str:
        self._pending_oauth = self._create_oauth()
        return self._pending_oauth.get_authorize_url()

    def exchange_code(self, code: str) -> bool:
        if not self._pending_oauth:
            self._pending_oauth = self._create_oauth()

        try:
            token_data = self._pending_oauth.get_access_token(code, as_dict=True)
            self._token_info = TokenInfo.from_dict(token_data)
            self._save_token()
            self._spotify = None
            self._pending_oauth = None
            return True
        except Exception:
            self._pending_oauth = None
            return False

    def refresh_if_needed(self) -> bool:
        if not self._token_info:
            return False

        if self._token_info.is_expired():
            oauth = self._create_oauth()
            try:
                token_data = oauth.refresh_access_token(
                    self._token_info.refresh_token
                )
                self._token_info = TokenInfo.from_dict(token_data)
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
