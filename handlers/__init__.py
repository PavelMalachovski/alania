from aiogram import Router

from .consultation import router as consultation_router
from .info import router as info_router
from .start import router as start_router


def setup_routers() -> Router:
    router = Router()
    router.include_router(start_router)
    router.include_router(consultation_router)
    router.include_router(info_router)
    return router
