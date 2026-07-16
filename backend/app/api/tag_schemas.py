from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.schemas import LanguageCode
from backend.app.db.models.audio_tag import AudioTagType
from backend.app.db.models.voice_tag import VoiceTagType


def _to_camel(field_name: str) -> str:
    first, *rest = field_name.split("_")
    return first + "".join(part.capitalize() for part in rest)


class TagApiModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=_to_camel,
        extra="forbid",
    )


class TagTranslationCreate(TagApiModel):
    language: LanguageCode
    value: str = Field(min_length=1, max_length=255)


class TagTranslationUpdate(TagApiModel):
    value: str = Field(min_length=1, max_length=255)


class VoiceTagCreate(TagApiModel):
    type: VoiceTagType
    value: str = Field(min_length=1, max_length=255)
    translations: list[TagTranslationCreate] = Field(default_factory=list)


class AudioTagCreate(TagApiModel):
    type: AudioTagType
    value: str = Field(min_length=1, max_length=255)
    translations: list[TagTranslationCreate] = Field(default_factory=list)


class TagTranslationResponse(TagApiModel):
    language: str
    value: str


class VoiceTagResponse(TagApiModel):
    id: int
    type: VoiceTagType
    english_value: str
    display_value: str
    full_tag: str
    translations: list[TagTranslationResponse]


class AudioTagResponse(TagApiModel):
    id: int
    type: AudioTagType
    english_value: str
    display_value: str
    full_tag: str
    translations: list[TagTranslationResponse]
