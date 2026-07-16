from __future__ import annotations

from enum import Enum

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class VoiceTagType(str, Enum):
    AUTHOR = "author"
    GENDER = "gender"


class VoiceTag(Base):
    __tablename__ = "voice_tags"
    __table_args__ = (
        UniqueConstraint(
            "type",
            "normalized_value",
            name="uq_voice_tags_type_normalized_value",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type: Mapped[VoiceTagType] = mapped_column(
        SqlEnum(
            VoiceTagType,
            name="ck_voice_tags_type",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(255), nullable=False)
    translations: Mapped[list[VoiceTagTranslation]] = relationship(
        back_populates="tag",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="VoiceTagTranslation.language",
    )


class VoiceTagTranslation(Base):
    __tablename__ = "voice_tag_translations"
    __table_args__ = (
        UniqueConstraint(
            "tag_id",
            "language",
            name="uq_voice_tag_translations_tag_language",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("voice_tags.id", ondelete="CASCADE"),
        nullable=False,
    )
    language: Mapped[str] = mapped_column(String(35), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(255), nullable=False)
    tag: Mapped[VoiceTag] = relationship(back_populates="translations")
