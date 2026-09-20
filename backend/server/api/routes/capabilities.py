from __future__ import annotations

from fastapi import APIRouter, Depends

from server.api.dependencies import get_principal, get_redis_dep, get_settings_dep
from server.schemas.misc import CapabilitiesOut
from server.services.capabilities import capabilities_document

router = APIRouter(prefix="/v1", tags=["capabilities"], dependencies=[Depends(get_principal)])


@router.get("/capabilities", response_model=CapabilitiesOut)
def get_capabilities(redis_client=Depends(get_redis_dep), settings=Depends(get_settings_dep)):
    return capabilities_document(redis_client, settings)
