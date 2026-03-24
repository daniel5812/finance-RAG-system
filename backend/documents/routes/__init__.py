# documents/routes/ — Document pipeline route handlers.
#
# Each file = one stage of the pipeline.
# Add new stage files here and include their router.
from fastapi import APIRouter

from documents.routes.upload import router as upload_router
from documents.routes.status import router as status_router

router = APIRouter()
router.include_router(upload_router)   # POST /documents/upload
router.include_router(status_router)   # GET  /documents/{id}
