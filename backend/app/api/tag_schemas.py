from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.schemas import LanguageCode
from backend.app.db.models.audio_tag import AudioTagType
from backend.app.db.models.voice_tag import VoiceTagType


class VoiceTagTranslationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: LanguageCode
    value: str = Field(min_length=1, max_length=255)


class VoiceTagCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: VoiceTagType
    value: str = Field(min_length=1, max_length=255)
    translations: list[VoiceTagTranslationCreate] = Field(default_factory=list)


class VoiceTagTranslationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    language: str
    value: str


class VoiceTagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: VoiceTagType
    value: str
    translations: list[VoiceTagTranslationResponse]


class AudioTagCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: AudioTagType
    value: str = Field(min_length=1, max_length=255)
    translations: list[VoiceTagTranslationCreate] = Field(default_factory=list)


class AudioTagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: AudioTagType
    value: str
    translations: list[VoiceTagTranslationResponse]
