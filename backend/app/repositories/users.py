from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models.user import User, UserStatus


class UserRepository:
    def get_by_id(self, session: Session, user_id: int) -> User | None:
        return session.get(User, user_id)

    def get_by_identity(
        self,
        session: Session,
        issuer: str,
        subject: str,
    ) -> User | None:
        statement = select(User).where(
            User.issuer == issuer,
            User.subject == subject,
        )
        return session.scalar(statement)

    def get_by_normalized_user_id(
        self,
        session: Session,
        normalized_user_id: str,
    ) -> User | None:
        statement = select(User).where(
            User.normalized_user_id == normalized_user_id
        )
        return session.scalar(statement)

    def get_by_user_id(self, session: Session, user_id: str) -> User | None:
        return self.get_by_normalized_user_id(session, user_id.lower())

    def create_pending(
        self,
        session: Session,
        *,
        issuer: str,
        subject: str,
        locale: str,
    ) -> User:
        user = User(
            issuer=issuer,
            subject=subject,
            status=UserStatus.PENDING_PROFILE,
            locale=locale,
        )
        session.add(user)
        session.flush()
        return user
