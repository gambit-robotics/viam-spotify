import asyncio
from viam.module.module import Module
from viam.services.generic import Generic

# Import registers SpotifyService.MODEL with the Registry
from .spotify_service import SpotifyService  # noqa: F401


async def main():
    module = Module.from_args()
    module.add_model_from_registry(Generic.SUBTYPE, SpotifyService.MODEL)
    await module.start()


if __name__ == "__main__":
    asyncio.run(main())
