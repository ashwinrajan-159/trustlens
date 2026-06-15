"""Application data access."""
from __future__ import annotations

from sqlalchemy import func, select

from app.models.application import Application
from app.models.enums import ApplicationStatus, LoanType
from app.repositories.base import BaseRepository


class ApplicationRepository(BaseRepository[Application]):
    model = Application

    async def get_by_number(self, number: str) -> Application | None:
        stmt = self._alive(
            select(Application).where(Application.application_number == number)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    def _filtered(
        self,
        stmt,
        *,
        status: ApplicationStatus | None,
        loan_type: LoanType | None,
        sort: str,
    ):
        if status is not None:
            stmt = stmt.where(Application.status == status)
        if loan_type is not None:
            stmt = stmt.where(Application.loan_type == loan_type)
        col = Application.created_at
        stmt = stmt.order_by(col.asc() if sort == "created_at" else col.desc())
        return stmt

    async def query(
        self,
        *,
        applicant_id: str | None = None,
        status: ApplicationStatus | None = None,
        loan_type: LoanType | None = None,
        sort: str = "-created_at",
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Application], int]:
        """Filtered + sorted page plus the matching total (#21)."""
        base = self._alive(select(Application))
        if applicant_id is not None:
            base = base.where(Application.applicant_id == applicant_id)

        rows_stmt = self._filtered(base, status=status, loan_type=loan_type, sort=sort)
        rows_stmt = rows_stmt.offset(offset).limit(limit)
        items = list((await self.session.execute(rows_stmt)).scalars().all())

        count_stmt = base.with_only_columns(func.count()).order_by(None)
        if status is not None:
            count_stmt = count_stmt.where(Application.status == status)
        if loan_type is not None:
            count_stmt = count_stmt.where(Application.loan_type == loan_type)
        total = (await self.session.execute(count_stmt)).scalar_one()
        return items, total
