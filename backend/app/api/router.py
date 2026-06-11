from fastapi import APIRouter

from app.features.auth.router import router as auth_router
from app.features.blogs.router import router as blogs_router
from app.features.customers.router import router as customers_router
from app.features.landing_pages.router import router as landing_pages_router
from app.features.settings.router import router as settings_router
from app.features.seo_tracker.router import router as seo_tracker_router
from app.features.seo_meta.router import router as seo_meta_router
from app.features.website_audit.router import router as website_audit_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(blogs_router)
router.include_router(customers_router)
router.include_router(landing_pages_router)
router.include_router(settings_router)
router.include_router(seo_tracker_router)
router.include_router(seo_meta_router)
router.include_router(website_audit_router)
