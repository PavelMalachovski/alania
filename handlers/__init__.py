from aiogram import Router

from .admin import router as admin_router
from .booking import router as booking_router
from .consultation import router as consultation_router
from .info import router as info_router
from .lead import router as lead_router
from .start import router as start_router


def setup_routers() -> Router:
    router = Router()
    router.include_router(admin_router)
    router.include_router(start_router)
    router.include_router(lead_router)
    router.include_router(booking_router)
    router.include_router(consultation_router)
    router.include_router(info_router)
    return router
