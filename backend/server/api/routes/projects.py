from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from server.api.dependencies import get_db, get_principal, get_storage_dep
from server.core.security import Principal
from server.schemas.edit import ProjectCreate, ProjectDetail, ProjectList, ProjectOut
from server.services import edit_service as es

router = APIRouter(prefix="/v1/projects", tags=["projects"])


@router.post("", status_code=201, response_model=ProjectOut)
def create_project(body: ProjectCreate, principal: Principal = Depends(get_principal), session=Depends(get_db),
                   storage=Depends(get_storage_dep)):
    return es.project_out(session, es.create_project(session, principal.user_id, body.name), storage)


@router.get("", response_model=ProjectList)
def list_projects(principal: Principal = Depends(get_principal), session=Depends(get_db), storage=Depends(get_storage_dep)):
    return ProjectList(items=es.list_projects(session, principal.user_id, storage))


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: uuid.UUID, principal: Principal = Depends(get_principal), session=Depends(get_db),
                storage=Depends(get_storage_dep)):
    return es.project_detail(session, es.get_project(session, project_id, principal.user_id), storage)
