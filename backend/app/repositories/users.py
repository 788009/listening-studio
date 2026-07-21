from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models.audio import Audio, AudioStatus, AudioVisibility
from backend.app.db.models.user import User, UserStatus
from backend.app.db.models.voice import Voice, VoiceStatus, VoiceVisibility


@dataclass(frozen=True)
class UserResourceStatistics:
    public_voice_count: int
    public_audio_count: int
    private_voice_count: int
    private_audio_count: int


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

    def list_active(
        self,
        session: Session,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[User], int]:
        filters = (
            User.status == UserStatus.ACTIVE,
            User.user_id.is_not(None),
        )
        total = session.scalar(
            select(func.count()).select_from(User).where(*filters)
        )
        users = list(
            session.scalars(
                select(User)
                .where(*filters)
                .order_by(User.normalized_user_id, User.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return users, int(total or 0)

    def resource_statistics(
        self,
        session: Session,
        user_id: int,
    ) -> UserResourceStatistics:
        public_voice_count = session.scalar(
            select(func.count())
            .select_from(Voice)
            .where(
                Voice.author_id == user_id,
                Voice.visibility == VoiceVisibility.PUBLIC,
                Voice.status == VoiceStatus.READY,
            )
        )
        public_audio_count = session.scalar(
            select(func.count())
            .select_from(Audio)
            .where(
                Audio.author_id == user_id,
                Audio.visibility == AudioVisibility.PUBLIC,
                Audio.status == AudioStatus.READY,
            )
        )
        private_voice_count = session.scalar(
            select(func.count())
            .select_from(Voice)
            .where(
                Voice.author_id == user_id,
                Voice.visibility == VoiceVisibility.PRIVATE,
            )
        )
        private_audio_count = session.scalar(
            select(func.count())
            .select_from(Audio)
            .where(
                Audio.author_id == user_id,
                Audio.visibility == AudioVisibility.PRIVATE,
            )
        )
        return UserResourceStatistics(
            public_voice_count=int(public_voice_count or 0),
            public_audio_count=int(public_audio_count or 0),
            private_voice_count=int(private_voice_count or 0),
            private_audio_count=int(private_audio_count or 0),
        )

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
