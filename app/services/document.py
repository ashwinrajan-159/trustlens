"""Document service: upload to object storage, list, presigned download.

Documents are always anchored to an application. Content type is verified by magic
bytes (#4); re-uploading the same document type supersedes the previous current
version (#9). On a storage failure after the row is flushed we best-effort delete the
orphaned object (#10). Phase 2 dispatches the OCR pipeline from the upload hook.
"""
from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.core.files import ALLOWED_CONTENT_TYPES, content_matches, detect_content_type
from app.core.logging import get_logger
from app.models.document import Document
from app.models.enums import AuditAction, DocumentStatus, DocumentType, UserRole
from app.repositories.application import ApplicationRepository
from app.repositories.document import DocumentRepository
from app.services.audit import AuditService
from app.services.storage import StorageService

log = get_logger(__name__)


class DocumentService:
    def __init__(self, session: AsyncSession, storage: StorageService):
        self.session = session
        self.storage = storage
        self.docs = DocumentRepository(session)
        self.apps = ApplicationRepository(session)
        self.audit = AuditService(session)

    async def _authorized_application(self, app_id: str, user_id: str, role: UserRole):
        app = await self.apps.get(app_id)
        if not app:
            raise NotFoundError("Application not found")
        if role == UserRole.CUSTOMER and app.applicant_id != user_id:
            raise AuthorizationError("You do not have access to this application")
        return app

    async def upload(
        self,
        *,
        application_id: str,
        document_type: DocumentType,
        filename: str,
        declared_content_type: str,
        data: bytes,
        checksum: str,
        user_id: str,
        role: UserRole,
        ip: str | None = None,
    ) -> Document:
        if not data:
            raise ValidationError("Empty file")

        # Validate by real magic bytes, not the client header (#4).
        head = data[:16]
        actual = detect_content_type(head)
        if actual is None or actual not in ALLOWED_CONTENT_TYPES:
            raise ValidationError("Unsupported or unrecognised file content")
        if not content_matches(declared_content_type, head):
            # Declared type lies about the bytes — trust the bytes, record the mismatch.
            log.warning(
                "document.content_type_mismatch",
                declared=declared_content_type, detected=actual,
            )
        content_type = actual

        await self._authorized_application(application_id, user_id, role)

        # Version supersession: same (application, type) — retire prior current versions (#9).
        prior = [
            d for d in await self.docs.list_for_application(application_id)
            if d.document_type == document_type
        ]
        next_version = (max((d.version for d in prior), default=0)) + 1
        if prior:
            await self.session.execute(
                update(Document)
                .where(
                    Document.application_id == application_id,
                    Document.document_type == document_type,
                    Document.is_current_version.is_(True),
                )
                .values(is_current_version=False)
            )

        doc = Document(
            application_id=application_id,
            document_type=document_type,
            original_filename=filename,
            storage_bucket=self.storage._bucket,
            storage_key="",  # set after we know the doc id
            content_type=content_type,
            file_size=len(data),
            checksum_sha256=checksum,
            version=next_version,
            is_current_version=True,
            status=DocumentStatus.QUEUED,
            uploaded_by=user_id,
        )
        await self.docs.add(doc)  # flush -> doc.id available
        doc.storage_key = StorageService.build_key(application_id, doc.id, filename)

        try:
            await self.storage.upload(doc.storage_key, data, content_type)
        except Exception:
            # Roll back the row so we don't keep a record pointing at nothing.
            await self.session.rollback()
            raise

        await self.audit.record(
            action=AuditAction.CREATE, entity_type="document", entity_id=doc.id,
            actor_id=user_id,
            after={"document_type": document_type.value, "checksum": checksum, "version": next_version},
            ip_address=ip,
        )
        try:
            await self.session.commit()
        except Exception:
            # Commit failed after the object landed in storage → best-effort cleanup (#10).
            await self.storage.delete(doc.storage_key)
            raise
        # Dispatch the OCR pipeline (best-effort; no-op under tests / if broker down).
        from app.tasks.ocr import dispatch_ocr

        dispatch_ocr(doc.id)
        log.info("document.upload", document_id=doc.id, application_id=application_id, version=next_version)
        return doc

    async def list_for_application(
        self, application_id: str, *, user_id: str, role: UserRole
    ) -> list[Document]:
        await self._authorized_application(application_id, user_id, role)
        return await self.docs.list_for_application(application_id)

    async def get_with_ocr(self, document_id: str, *, user_id: str, role: UserRole):
        """Return (document, current OcrResult|None) after an authorization check."""
        from sqlalchemy import select

        from app.models.ocr_result import OcrResult

        doc = await self.docs.get(document_id)
        if not doc:
            raise NotFoundError("Document not found")
        await self._authorized_application(doc.application_id, user_id, role)
        ocr = (
            await self.session.execute(
                select(OcrResult)
                .where(OcrResult.document_id == doc.id, OcrResult.deleted_at.is_(None))
                .order_by(OcrResult.created_at.desc())
                .limit(1)
            )
        ).scalars().first()
        return doc, ocr

    async def list_entities(
        self, *, document_id: str | None = None, application_id: str | None = None,
        user_id: str, role: UserRole, ip: str | None = None,
    ):
        """Return extracted entities for a document or an application (authorized).

        Recorded as a PII access in the audit trail (the result set contains identity
        fields, even though sensitive values are masked)."""
        from sqlalchemy import select

        from app.models.extracted_entity import ExtractedEntity

        if document_id is not None:
            doc = await self.docs.get(document_id)
            if not doc:
                raise NotFoundError("Document not found")
            app_id = doc.application_id
        elif application_id is not None:
            app_id = application_id
        else:
            raise ValidationError("document_id or application_id required")

        await self._authorized_application(app_id, user_id, role)

        stmt = select(ExtractedEntity).where(ExtractedEntity.deleted_at.is_(None))
        if document_id is not None:
            stmt = stmt.where(ExtractedEntity.document_id == document_id)
        else:
            stmt = stmt.where(ExtractedEntity.application_id == app_id)
        stmt = stmt.order_by(ExtractedEntity.created_at.asc())
        entities = list((await self.session.execute(stmt)).scalars().all())

        await self.audit.record(
            action=AuditAction.READ_PII, entity_type="application", entity_id=app_id,
            actor_id=user_id, after={"entities_viewed": len(entities)}, ip_address=ip,
        )
        await self.session.commit()
        return entities

    async def presigned_url(self, document_id: str, *, user_id: str, role: UserRole, ip: str | None = None) -> str:
        doc = await self.docs.get(document_id)
        if not doc:
            raise NotFoundError("Document not found")
        await self._authorized_application(doc.application_id, user_id, role)
        url = await self.storage.presigned_download_url(doc.storage_key)
        await self.audit.record(
            action=AuditAction.DOWNLOAD, entity_type="document", entity_id=doc.id,
            actor_id=user_id, ip_address=ip,
        )
        await self.session.commit()
        return url
