from __future__ import annotations

import re

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.exceptions import (
    ConflictError,
    DomainValidationError,
    UserIdImmutableError,
    UserIdTakenError,
)
from backend.app.core.locales import normalize_supported_locale
from backend.app.db.models.user import User, UserStatus
from backend.app.repositories.users import UserRepository


_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{1,64}$")


class UserService:
    def __init__(self, repository: UserRepository | None = None) -> None:
        self.repository = repository or UserRepository()

    def create_pending_user(
        self,
        session: Session,
        *,
        issuer: str,
        subject: str,
        locale: str = "en",
    ) -> User:
        self._validate_identity(issuer, subject)
        normalized_locale = self._validate_locale(locale)
        if self.repository.get_by_identity(session, issuer, subject):
            raise ConflictError("Identity already exists")

        try:
            return self.repository.create_pending(
                session,
                issuer=issuer,
                subject=subject,
                locale=normalized_locale,
            )
        except IntegrityError as exc:
            session.rollback()
            raise ConflictError("Identity already exists") from exc

    def get_or_create_pending_user(
        self,
        session: Session,
        *,
        issuer: str,
        subject: str,
        locale: str = "en",
    ) -> User:
        existing = self.repository.get_by_identity(session, issuer, subject)
        if existing:
            return existing
        try:
            return self.create_pending_user(
                session,
                issuer=issuer,
                subject=subject,
                locale=locale,
            )
        except ConflictError:
            existing = self.repository.get_by_identity(session, issuer, subject)
            if existing:
                return existing
            raise

    def set_user_id(self, session: Session, user: User, user_id: str) -> User:
        if user.user_id is not None:
            raise UserIdImmutableError(details={"field": "userId"})
        if not _USER_ID_PATTERN.fullmatch(user_id):
            raise DomainValidationError(
                "User ID must contain only ASCII letters and numbers",
                details={"field": "userId"},
            )

        normalized_user_id = user_id.lower()
        existing = self.repository.get_by_normalized_user_id(
            session, normalized_user_id
        )
        if existing and existing.id != user.id:
            raise UserIdTakenError(details={"field": "userId"})

        user.user_id = user_id
        user.normalized_user_id = normalized_user_id
        user.status = UserStatus.ACTIVE
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise UserIdTakenError(details={"field": "userId"}) from exc
        return user

    def update_username(self, session: Session, user: User, username: str) -> User:
        normalized_username = username.strip()
        if not normalized_username or len(normalized_username) > 200:
            raise DomainValidationError(
                "Username must contain between 1 and 200 characters",
                details={"field": "username"},
            )
        user.username = normalized_username
        session.flush()
        return user

    def update_locale(self, session: Session, user: User, locale: str) -> User:
        user.locale = self._validate_locale(locale)
        session.flush()
        return user

    @staticmethod
    def _validate_identity(issuer: str, subject: str) -> None:
        if not issuer.strip() or not subject.strip():
            raise DomainValidationError(
                "Issuer and subject are required",
                details={"fields": ["issuer", "subject"]},
            )

    @staticmethod
    def _validate_locale(locale: str) -> str:
        try:
            normalized = normalize_supported_locale(locale)
        except ValueError:
            raise DomainValidationError(
                "Locale is invalid",
                details={"field": "locale"},
            ) from None
        assert isinstance(normalized, str)
        return normalized
