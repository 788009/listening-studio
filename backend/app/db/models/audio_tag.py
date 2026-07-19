from __future__ import annotations

from enum import Enum

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class AudioTagType(str, Enum):
    AUTHOR = "author"
    VOICE = "voice"
    TOPIC = "topic"
    CATEGORY = "category"
    OTHER = "other"


class AudioTag(Base):
    __tablename__ = "audio_tags"
    __table_args__ = (
        UniqueConstraint(
            "type",
            "normalized_value",
            name="uq_audio_tags_type_normalized_value",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type: Mapped[AudioTagType] = mapped_column(
        SqlEnum(
            AudioTagType,
            name="ck_audio_tags_type",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(255), nullable=False)
    translations: Mapped[list[AudioTagTranslation]] = relationship(
        back_populates="tag",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AudioTagTranslation.language",
    )


class AudioTagTranslation(Base):
    __tablename__ = "audio_tag_translations"
    __table_args__ = (
        UniqueConstraint(
            "tag_id",
            "language",
            name="uq_audio_tag_translations_tag_language",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("audio_tags.id", ondelete="CASCADE"),
        nullable=False,
    )
    language: Mapped[str] = mapped_column(String(35), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(255), nullable=False)
    tag: Mapped[AudioTag] = relationship(back_populates="translations")
