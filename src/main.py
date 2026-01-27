import asyncio

from viam.module.module import Module
from viam.services.discovery import Discovery
from viam.services.generic import Generic

# Import registers models with the Registry
from audio_discovery import AudioDiscovery  # noqa: F401
from spotify_service import SpotifyService  # noqa: F401


async def main():
    module = Module.from_args()
    module.add_model_from_registry(Generic.API, SpotifyService.MODEL)
    module.add_model_from_registry(Discovery.API, AudioDiscovery.MODEL)
    await module.start()


if __name__ == "__main__":
    asyncio.run(main())
