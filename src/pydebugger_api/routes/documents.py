"""Authenticated document ingestion and management endpoints."""

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from pydebugger.jobs import JobQueueFullError

from ..dependencies import get_current_user, get_document_service, get_session
from ..models import User
from ..schemas.documents import (
    DocumentResponse,
    IngestionJobResponse,
    YouTubeIngestionRequest,
)
from ..services.documents import (
    DocumentService,
    OwnedResourceNotFoundError,
)

router = APIRouter(tags=["documents"])


def _service_error(error: Exception) -> HTTPException:
    if isinstance(error, OwnedResourceNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, JobQueueFullError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(error)
        )
    if isinstance(error, SQLAlchemyError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document persistence is temporarily unavailable",
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Document operation failed",
    )


@router.post(
    "/documents/upload",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def upload_document(
    file: Annotated[UploadFile, File()],
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    documents: Annotated[DocumentService, Depends(get_document_service)],
) -> IngestionJobResponse:
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Upload requires a filename")
    data = file.file.read(documents.upload_limit_bytes + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded document is empty")
    if len(data) > documents.upload_limit_bytes:
        raise HTTPException(status_code=413, detail="Uploaded document is too large")
    try:
        job = documents.start_upload(
            session, user.id, filename, data, file.content_type
        )
    except Exception as error:
        raise _service_error(error) from error
    return IngestionJobResponse.from_job(job)


@router.post(
    "/documents/youtube",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def ingest_youtube(
    request: YouTubeIngestionRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    documents: Annotated[DocumentService, Depends(get_document_service)],
) -> IngestionJobResponse:
    try:
        job = documents.start_youtube(
            session, user.id, request.reference, tuple(request.languages)
        )
    except Exception as error:
        raise _service_error(error) from error
    return IngestionJobResponse.from_job(job)


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    documents: Annotated[DocumentService, Depends(get_document_service)],
) -> list[DocumentResponse]:
    try:
        sources = documents.list_documents(session, user.id)
    except Exception as error:
        raise _service_error(error) from error
    return [DocumentResponse.from_source(source) for source in sources]


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    documents: Annotated[DocumentService, Depends(get_document_service)],
) -> Response:
    try:
        documents.delete_document(session, user.id, document_id)
    except Exception as error:
        raise _service_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/ingestion-jobs/{job_id}", response_model=IngestionJobResponse)
def get_ingestion_job(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    documents: Annotated[DocumentService, Depends(get_document_service)],
) -> IngestionJobResponse:
    try:
        job = documents.get_job(session, user.id, job_id)
    except Exception as error:
        raise _service_error(error) from error
    return IngestionJobResponse.from_job(job)


@router.post("/ingestion-jobs/{job_id}/cancel", response_model=IngestionJobResponse)
def cancel_ingestion_job(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    documents: Annotated[DocumentService, Depends(get_document_service)],
) -> IngestionJobResponse:
    try:
        job = documents.cancel_job(session, user.id, job_id)
    except Exception as error:
        raise _service_error(error) from error
    return IngestionJobResponse.from_job(job)
