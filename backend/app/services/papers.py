from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.app.core.auth import Principal
from backend.app.core.exceptions import (
    ConflictError,
    DomainValidationError,
    NotFoundError,
)
from backend.app.db.models.audio import Audio, AudioStatus
from backend.app.db.models.paper import Paper, PaperPreset
from backend.app.db.models.user import User
from backend.app.repositories.audios import AudioRepository
from backend.app.repositories.papers import PaperRepository
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audios import AudioService
from backend.app.services.authorization import AuthorizationService


MAX_PAPER_ITEMS = 100
MAX_SILENCE_MILLISECONDS = 60_000
MAX_REPEAT_COUNT = 10


@dataclass(frozen=True)
class PaperPresetParameters:
    intro_silence_milliseconds: int
    inter_item_silence_milliseconds: int
    repeat_count: int
    outro_silence_milliseconds: int


@dataclass(frozen=True)
class PaperListResult:
    items: list[Paper]
    total: int


class PaperService:
    def __init__(
        self,
        storage: AudioStorage,
        *,
        repository: PaperRepository | None = None,
        audio_repository: AudioRepository | None = None,
        authorization: AuthorizationService | None = None,
    ) -> None:
        self.repository = repository or PaperRepository()
        self.audio_repository = audio_repository or AudioRepository()
        self.audio_service = AudioService(storage, self.audio_repository)
        self.authorization = authorization or AuthorizationService()

    def list_presets(self, session: Session, owner: User) -> list[PaperPreset]:
        return self.repository.list_presets(session, owner.id)

    def create_preset(
        self,
        session: Session,
        owner: User,
        *,
        name: str,
        parameters: PaperPresetParameters,
    ) -> PaperPreset:
        normalized_name = self._name(name)
        values = self._parameters(parameters)
        return self.repository.create_preset(
            session,
            owner=owner,
            name=normalized_name,
            **values.__dict__,
        )

    def update_preset(
        self,
        session: Session,
        owner: User,
        preset_id: int,
        *,
        name: str,
        parameters: PaperPresetParameters,
    ) -> PaperPreset:
        preset = self._owned_custom_preset(session, owner, preset_id)
        values = self._parameters(parameters)
        preset.name = self._name(name)
        preset.intro_silence_milliseconds = values.intro_silence_milliseconds
        preset.inter_item_silence_milliseconds = (
            values.inter_item_silence_milliseconds
        )
        preset.repeat_count = values.repeat_count
        preset.outro_silence_milliseconds = values.outro_silence_milliseconds
        session.flush()
        return preset

    def delete_preset(
        self,
        session: Session,
        owner: User,
        preset_id: int,
    ) -> None:
        preset = self._owned_custom_preset(session, owner, preset_id)
        self.repository.delete_preset(session, preset)

    def create_paper(
        self,
        session: Session,
        owner: User,
        *,
        title: str,
        preset_id: int,
        audio_ids: list[int],
    ) -> Paper:
        preset = self._visible_preset(session, owner, preset_id)
        normalized_title, search_title = self._title(title)
        if not audio_ids or len(audio_ids) > MAX_PAPER_ITEMS:
            raise DomainValidationError(
                "Paper item count is outside the allowed range",
                details={"field": "audioIds", "maxItems": MAX_PAPER_ITEMS},
            )
        audios = [
            self._visible_ready_audio(session, owner, value) for value in audio_ids
        ]
        return self.repository.create_paper(
            session,
            owner=owner,
            preset=preset,
            title=normalized_title,
            normalized_title=search_title,
            audios=audios,
        )

    def get_owned(self, session: Session, owner: User, paper_id: int) -> Paper:
        paper = self.repository.get_paper(session, paper_id)
        if paper is None or paper.owner_id != owner.id:
            raise NotFoundError("Paper not found")
        return paper

    def list_owned(
        self,
        session: Session,
        owner: User,
        *,
        page: int,
        page_size: int,
    ) -> PaperListResult:
        items, total = self.repository.list_papers(
            session,
            owner_id=owner.id,
            page=page,
            page_size=page_size,
        )
        return PaperListResult(items, total)

    def _visible_preset(
        self,
        session: Session,
        owner: User,
        preset_id: int,
    ) -> PaperPreset:
        preset = self.repository.get_preset(session, preset_id)
        if preset is None or not (preset.is_builtin or preset.owner_id == owner.id):
            raise NotFoundError("Paper preset not found")
        return preset

    def _owned_custom_preset(
        self,
        session: Session,
        owner: User,
        preset_id: int,
    ) -> PaperPreset:
        preset = self.repository.get_preset(session, preset_id)
        if preset is None or (not preset.is_builtin and preset.owner_id != owner.id):
            raise NotFoundError("Paper preset not found")
        if preset.is_builtin:
            raise ConflictError("Built-in paper presets are read-only")
        return preset

    def _visible_ready_audio(
        self,
        session: Session,
        owner: User,
        audio_id: int,
    ) -> Audio:
        if isinstance(audio_id, bool) or not isinstance(audio_id, int) or audio_id < 1:
            raise DomainValidationError(
                "Paper audio ID is invalid",
                details={"field": "audioIds"},
            )
        audio = self.audio_repository.get_by_id(session, audio_id)
        if audio is None:
            raise NotFoundError("Audio not found")
        self.authorization.require_view(
            Principal(owner),
            self.audio_service.descriptor(audio),
        )
        if (
            audio.status is not AudioStatus.READY
            or not self.audio_service.is_ready(audio)
        ):
            raise ConflictError("Paper items must reference ready audios")
        return audio

    @staticmethod
    def _parameters(value: PaperPresetParameters) -> PaperPresetParameters:
        if not isinstance(value, PaperPresetParameters):
            raise DomainValidationError("Paper preset parameters are invalid")
        for field_name in (
            "intro_silence_milliseconds",
            "inter_item_silence_milliseconds",
            "outro_silence_milliseconds",
        ):
            field_value = getattr(value, field_name)
            if (
                isinstance(field_value, bool)
                or not isinstance(field_value, int)
                or not 0 <= field_value <= MAX_SILENCE_MILLISECONDS
            ):
                raise DomainValidationError(
                    "Paper silence duration is outside the allowed range",
                    details={"field": field_name},
                )
        if (
            isinstance(value.repeat_count, bool)
            or not isinstance(value.repeat_count, int)
            or not 1 <= value.repeat_count <= MAX_REPEAT_COUNT
        ):
            raise DomainValidationError(
                "Paper repeat count is outside the allowed range",
                details={"field": "repeatCount"},
            )
        return value

    @staticmethod
    def _name(value: str) -> str:
        return PaperService._text(value, "name")

    @staticmethod
    def _title(value: str) -> tuple[str, str]:
        normalized = PaperService._text(value, "title")
        search_title = normalized.casefold()
        if len(search_title) > 200:
            raise DomainValidationError(
                "Paper title normalization is too long",
                details={"field": "title"},
            )
        return normalized, search_title

    @staticmethod
    def _text(value: str, field: str) -> str:
        if not isinstance(value, str):
            raise DomainValidationError(
                "Paper text field is invalid",
                details={"field": field},
            )
        normalized = unicodedata.normalize("NFKC", value.strip())
        if not normalized or len(normalized) > 200:
            raise DomainValidationError(
                "Paper text field must contain between 1 and 200 characters",
                details={"field": field},
            )
        return normalized
