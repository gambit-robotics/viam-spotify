import base64
import html
import io
import socket
from typing import TYPE_CHECKING, Optional

import qrcode
from aiohttp import web

if TYPE_CHECKING:
    from .token_manager import TokenManager


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def generate_qr_base64(url: str) -> str:
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


class AuthServer:
    def __init__(self, token_manager: "TokenManager", port: int = 8888):
        self.token_manager = token_manager
        self.port = port
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._running = False

    @property
    def local_ip(self) -> str:
        return get_local_ip()

    @property
    def base_url(self) -> str:
        return f"http://{self.local_ip}:{self.port}"

    @property
    def login_url(self) -> str:
        return f"{self.base_url}/login"

    @property
    def callback_url(self) -> str:
        return f"{self.base_url}/callback"

    def get_qr_data(self) -> dict:
        return {
            "qr_image": generate_qr_base64(self.login_url),
            "auth_url": self.login_url,
        }

    async def _handle_login(self, _request: web.Request) -> web.Response:
        auth_url = self.token_manager.get_auth_url()
        raise web.HTTPFound(auth_url)

    async def _handle_callback(self, request: web.Request) -> web.Response:
        code = request.query.get("code")
        error = request.query.get("error")

        if error:
            safe_error = html.escape(error)
            return web.Response(
                text=f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <style>
                        body {{
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                            display: flex;
                            justify-content: center;
                            align-items: center;
                            height: 100vh;
                            margin: 0;
                            background: #1a1a2e;
                            color: #fff;
                        }}
                        .container {{
                            text-align: center;
                            padding: 40px;
                        }}
                        .icon {{ font-size: 64px; margin-bottom: 20px; }}
                        h1 {{ color: #e94560; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="icon">&#10060;</div>
                        <h1>Authentication Failed</h1>
                        <p>Error: {safe_error}</p>
                        <p>Please try again.</p>
                    </div>
                </body>
                </html>
                """,
                content_type="text/html",
            )

        if not code:
            return web.Response(
                text="Missing authorization code",
                status=400,
            )

        success = self.token_manager.exchange_code(code)

        if success:
            user = self.token_manager.get_current_user() or "User"
            safe_user = html.escape(user)
            return web.Response(
                text=f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <style>
                        body {{
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                            display: flex;
                            justify-content: center;
                            align-items: center;
                            height: 100vh;
                            margin: 0;
                            background: linear-gradient(135deg, #1DB954 0%, #191414 100%);
                            color: #fff;
                        }}
                        .container {{
                            text-align: center;
                            padding: 40px;
                        }}
                        .icon {{ font-size: 64px; margin-bottom: 20px; }}
                        h1 {{ color: #1DB954; }}
                        p {{ opacity: 0.8; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="icon">&#9989;</div>
                        <h1>Success!</h1>
                        <p>Welcome, {safe_user}!</p>
                        <p>You can close this page and return to your kiosk.</p>
                    </div>
                </body>
                </html>
                """,
                content_type="text/html",
            )
        else:
            return web.Response(
                text="""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <style>
                        body {
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                            display: flex;
                            justify-content: center;
                            align-items: center;
                            height: 100vh;
                            margin: 0;
                            background: #1a1a2e;
                            color: #fff;
                        }
                        .container {
                            text-align: center;
                            padding: 40px;
                        }
                        .icon { font-size: 64px; margin-bottom: 20px; }
                        h1 { color: #e94560; }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="icon">&#10060;</div>
                        <h1>Authentication Failed</h1>
                        <p>Could not exchange authorization code.</p>
                        <p>Please try again.</p>
                    </div>
                </body>
                </html>
                """,
                content_type="text/html",
            )

    async def start(self) -> None:
        if self._running:
            return

        self._app = web.Application()
        self._app.router.add_get("/login", self._handle_login)
        self._app.router.add_get("/callback", self._handle_callback)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await self._site.start()
        self._running = True

    async def stop(self) -> None:
        if not self._running:
            return

        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

        self._app = None
        self._runner = None
        self._site = None
        self._running = False
