"""Document endpoints: upload (multipart), list per application, presigned download."""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import ValidationError
from app.database import get_db
from app.dependencies import (
    CurrentUser,
    client_ip,
    get_current_user,
    get_storage,
)
from app.models.enums import DocumentType
from app.schemas.common import ERROR_RESPONSES
from app.schemas.document import (
    DocumentDetail,
    DocumentPublic,
    ExtractedEntityPublic,
    OcrSummary,
    PresignedDownloadResponse,
)
from app.services.document import DocumentService
from app.services.storage import StorageService

router = APIRouter(tags=["documents"], responses=ERROR_RESPONSES)

_UPLOAD_CHUNK = 1024 * 1024  # 1 MB


async def _read_capped(file: UploadFile, limit: int) -> tuple[bytes, str]:
    """Read an upload in chunks, abort past ``limit``, hash incrementally (#5)."""
    hasher = hashlib.sha256()
    buf = bytearray()
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ValidationError("File exceeds the maximum allowed size")
        hasher.update(chunk)
        buf.extend(chunk)
    return bytes(buf), hasher.hexdigest()


@router.post(
    "/applications/{application_id}/documents",
    response_model=DocumentPublic,
    status_code=201,
)
async def upload_document(
    application_id: str,
    request: Request,
    document_type: DocumentType = Form(...),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: StorageService = Depends(get_storage),
) -> DocumentPublic:
    data, checksum = await _read_capped(file, settings.max_request_body_bytes)
    doc = await DocumentService(db, storage).upload(
        application_id=application_id,
        document_type=document_type,
        filename=file.filename or "document",
        declared_content_type=file.content_type or "application/octet-stream",
        data=data,
        checksum=checksum,
        user_id=user.id,
        role=user.role,
        ip=client_ip(request),
    )
    return DocumentPublic.model_validate(doc)


@router.get(
    "/applications/{application_id}/documents",
    response_model=list[DocumentPublic],
)
async def list_documents(
    application_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: StorageService = Depends(get_storage),
) -> list[DocumentPublic]:
    docs = await DocumentService(db, storage).list_for_application(
        application_id, user_id=user.id, role=user.role
    )
    return [DocumentPublic.model_validate(d) for d in docs]


@router.get("/documents/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: StorageService = Depends(get_storage),
) -> DocumentDetail:
    doc, ocr = await DocumentService(db, storage).get_with_ocr(
        document_id, user_id=user.id, role=user.role
    )
    detail = DocumentDetail.model_validate(doc)
    if ocr is not None:
        detail.ocr = OcrSummary(
            engine=ocr.engine,
            confidence_score=ocr.confidence_score,
            page_count=ocr.page_count,
            has_text=bool(ocr.raw_text),
            char_count=len(ocr.raw_text or ""),
        )
    return detail


def _entity_to_public(e) -> ExtractedEntityPublic:
    # Sensitive values are shown masked; non-sensitive show the decrypted clear value.
    display = e.masked_value if e.is_sensitive else e.value
    return ExtractedEntityPublic(
        id=e.id,
        document_id=e.document_id,
        entity_type=e.entity_type,
        value=display,
        is_sensitive=e.is_sensitive,
        confidence=e.confidence,
        extraction_method=e.extraction_method,
        source_page=e.source_page,
    )


@router.get(
    "/documents/{document_id}/entities",
    response_model=list[ExtractedEntityPublic],
)
async def list_document_entities(
    document_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: StorageService = Depends(get_storage),
) -> list[ExtractedEntityPublic]:
    entities = await DocumentService(db, storage).list_entities(
        document_id=document_id, user_id=user.id, role=user.role, ip=client_ip(request)
    )
    return [_entity_to_public(e) for e in entities]


@router.get(
    "/applications/{application_id}/entities",
    response_model=list[ExtractedEntityPublic],
)
async def list_application_entities(
    application_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: StorageService = Depends(get_storage),
) -> list[ExtractedEntityPublic]:
    entities = await DocumentService(db, storage).list_entities(
        application_id=application_id, user_id=user.id, role=user.role, ip=client_ip(request)
    )
    return [_entity_to_public(e) for e in entities]


@router.get(
    "/documents/{document_id}/download",
    response_model=PresignedDownloadResponse,
)
async def download_document(
    document_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: StorageService = Depends(get_storage),
) -> PresignedDownloadResponse:
    url = await DocumentService(db, storage).presigned_url(
        document_id, user_id=user.id, role=user.role, ip=client_ip(request)
    )
    return PresignedDownloadResponse(
        url=url, expires_in_seconds=settings.presigned_url_ttl_seconds
    )
