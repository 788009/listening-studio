from __future__ import annotations

import unicodedata
from collections.abc import Callable

from loguru import logger
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.core.auth import Principal
from backend.app.core.exceptions import JobFailedError
from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioVisibility,
)
from backend.app.db.models.audio_tag import AudioTag, AudioTagType
from backend.app.db.models.generation_batch import (
    GenerationBatch,
    GenerationBatchItem,
    GenerationBatchStatus,
)
from backend.app.db.models.user import User
from backend.app.integrations.llm import (
    GeneratedListeningContent,
    ListeningContentGenerator,
    ListeningGenerationRequest,
    ListeningGenerationResult,
    QuestionType,
)
from backend.app.repositories.audio_tags import AudioTagRepository
from backend.app.repositories.audios import AudioRepository
from backend.app.repositories.generation_batches import GenerationBatchRepository
from backend.app.repositories.voices import VoiceRepository
from backend.app.services.audio_synthesis import AudioSynthesisService
from backend.app.services.audios import AudioUtteranceInput
from backend.app.services.authorization import AuthorizationService
from backend.app.services.corpus_storage import CorpusStorage
from backend.app.services.tag_values import normalize_english_tag_value
from backend.app.services.voice_storage import VoiceStorage
from backend.app.services.voices import VoiceService


class CorpusGenerationService:
    def __init__(
        self,
        *,
        generator: ListeningContentGenerator,
        corpus_storage: CorpusStorage,
        synthesis_service: AudioSynthesisService,
        voice_storage: VoiceStorage,
        silence_milliseconds: int,
        batch_repository: GenerationBatchRepository | None = None,
        audio_repository: AudioRepository | None = None,
        tag_repository: AudioTagRepository | None = None,
        voice_repository: VoiceRepository | None = None,
        authorization: AuthorizationService | None = None,
    ) -> None:
        if not 0 <= silence_milliseconds <= 10_000:
            raise ValueError("Dialogue silence duration is invalid")
        self.generator = generator
        self.corpus_storage = corpus_storage
        self.synthesis_service = synthesis_service
        self.silence_milliseconds = silence_milliseconds
        self.batch_repository = batch_repository or GenerationBatchRepository()
        self.audio_repository = audio_repository or AudioRepository()
        self.tag_repository = tag_repository or AudioTagRepository()
        self.voice_repository = voice_repository or VoiceRepository()
        self.voice_service = VoiceService(voice_storage)
        self.authorization = authorization or AuthorizationService()

    def process(
        self,
        session: Session,
        *,
        batch_id: int,
        job_id: int,
        owner_id: int,
        item_id: int | None,
        request_id: str,
        checkpoint: Callable[[int], None],
    ) -> GenerationBatch:
        batch = self.batch_repository.get_by_id(session, batch_id)
        if batch is None or batch.owner_id != owner_id:
            raise JobFailedError("Generation batch is unavailable")
        owner = session.get(User, owner_id)
        if owner is None or not owner.is_profile_complete:
            raise JobFailedError("Generation batch owner is unavailable")
        try:
            if item_id is None:
                self._prepare_generated_content(
                    session,
                    batch,
                    owner,
                    job_id=job_id,
                    request_id=request_id,
                )
                items = list(batch.items)
            else:
                item = self.batch_repository.get_item(session, item_id)
                if item is None or item.batch_id != batch.id:
                    raise JobFailedError("Generation batch item is unavailable")
                if item.status is GenerationBatchStatus.COMPLETED:
                    return batch
                if item.generated_content is None:
                    raise JobFailedError("Generation batch item content is unavailable")
                batch.status = GenerationBatchStatus.PROCESSING
                batch.error_summary = None
                session.commit()
                items = [item]

            contents = [self._content(item) for item in items]
            voice_ids = self._validate_speaker_voices(
                session,
                batch,
                owner,
                contents,
            )
            checkpoint(10)
            for index, (item, content) in enumerate(zip(items, contents, strict=True)):
                if item.status is GenerationBatchStatus.COMPLETED:
                    checkpoint(self._item_progress(index + 1, len(items)))
                    continue
                self._process_item(
                    session,
                    batch,
                    item,
                    content,
                    owner,
                    voice_ids=voice_ids,
                    job_id=job_id,
                    request_id=request_id,
                    checkpoint=lambda value, position=index: checkpoint(
                        self._synthesis_progress(position, len(items), value)
                    ),
                )
                checkpoint(self._item_progress(index + 1, len(items)))
            self._finish_batch(session, batch)
            return batch
        except JobFailedError:
            if batch.status is not GenerationBatchStatus.COMPLETED:
                self._fail_before_synthesis(session, batch)
            raise
        except Exception as exc:
            if batch.status is not GenerationBatchStatus.COMPLETED:
                self._fail_before_synthesis(session, batch)
            raise JobFailedError("Corpus generation failed") from exc
        finally:
            self.corpus_storage.cleanup(job_id)

    def _prepare_generated_content(
        self,
        session: Session,
        batch: GenerationBatch,
        owner: User,
        *,
        job_id: int,
        request_id: str,
    ) -> None:
        populated = [item.generated_content is not None for item in batch.items]
        if all(populated):
            batch.status = GenerationBatchStatus.PROCESSING
            batch.error_summary = None
            session.commit()
            return
        if any(populated):
            raise JobFailedError("Generation batch content is inconsistent")
        path = self.corpus_storage.path(job_id)
        if not path.is_file() or path.is_symlink():
            raise JobFailedError("Staged corpus is unavailable")
        try:
            corpus = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise JobFailedError("Staged corpus could not be read") from exc
        request = ListeningGenerationRequest(
            corpus=corpus,
            question_types={QuestionType(value) for value in batch.question_types},
            count=batch.requested_count,
            language=owner.locale,
        )
        result = ListeningGenerationResult.model_validate(
            self.generator.generate(request, call_id=request_id)
        )
        if len(result.items) != len(batch.items):
            raise JobFailedError("Generated item count is invalid")
        for item, content in zip(batch.items, result.items, strict=True):
            item.generated_content = content.model_dump(mode="json")
            item.status = GenerationBatchStatus.PENDING
            item.error_summary = None
        batch.status = GenerationBatchStatus.PROCESSING
        batch.error_summary = None
        session.commit()

    def _validate_speaker_voices(
        self,
        session: Session,
        batch: GenerationBatch,
        owner: User,
        contents: list[GeneratedListeningContent],
    ) -> dict[str, int]:
        mappings = {
            item.normalized_speaker: item.voice_id for item in batch.speaker_voices
        }
        required = {
            self._normalize_speaker(turn.speaker)
            for content in contents
            for turn in content.turns
        }
        missing = sorted(required - mappings.keys())
        if missing:
            raise JobFailedError(
                "Speaker voice mapping is incomplete",
                details={"missingSpeakerCount": len(missing)},
            )
        for voice_id in {mappings[speaker] for speaker in required}:
            voice = self.voice_repository.get_by_id(session, voice_id)
            if voice is None:
                raise JobFailedError("Mapped voice is unavailable")
            try:
                self.authorization.require_use_for_synthesis(
                    Principal(owner),
                    self.voice_service.descriptor(voice),
                )
            except Exception as exc:
                raise JobFailedError("Mapped voice is unavailable") from exc
        return mappings

    def _process_item(
        self,
        session: Session,
        batch: GenerationBatch,
        item: GenerationBatchItem,
        content: GeneratedListeningContent,
        owner: User,
        *,
        voice_ids: dict[str, int],
        job_id: int,
        request_id: str,
        checkpoint: Callable[[int], None],
    ) -> None:
        audio = self._prepare_audio(
            session,
            batch,
            item,
            content,
            owner,
            voice_ids,
        )
        try:
            self.synthesis_service.process(
                session,
                audio_id=audio.id,
                job_id=job_id,
                target_visibility=AudioVisibility.PRIVATE,
                request_id=request_id,
                checkpoint=checkpoint,
                silence_milliseconds=self.silence_milliseconds,
            )
        except JobFailedError as exc:
            item = self.batch_repository.get_item(session, item.id)
            if item is None:
                raise
            item.status = GenerationBatchStatus.FAILED
            item.error_summary = f"Audio generation failed ({type(exc).__name__})"
            session.commit()
            logger.bind(
                request_id=request_id,
                job_id=job_id,
                user_db_id=owner.id,
                resource_type="audio",
                resource_id=audio.id,
            ).warning(
                "Corpus batch item failed batch_id={} item_id={} audio_id={}",
                batch.id,
                item.id,
                audio.id,
            )
            return
        item = self.batch_repository.get_item(session, item.id)
        if item is None:
            raise JobFailedError("Generation batch item is unavailable")
        item.status = GenerationBatchStatus.COMPLETED
        item.error_summary = None
        session.commit()

    def _prepare_audio(
        self,
        session: Session,
        batch: GenerationBatch,
        item: GenerationBatchItem,
        content: GeneratedListeningContent,
        owner: User,
        voice_ids: dict[str, int],
    ) -> Audio:
        if item.audio_id is not None:
            existing = self.audio_repository.get_by_id(session, item.audio_id)
            if existing is not None and existing.status in {
                AudioStatus.PENDING,
                AudioStatus.PROCESSING,
                AudioStatus.READY,
            }:
                item.status = GenerationBatchStatus.PROCESSING
                item.attempt_count += 1
                session.commit()
                return existing
            item.audio_id = None
            session.flush()
            if existing is not None:
                self.synthesis_service.audio_storage.delete_audio(existing.id)
                self.audio_repository.delete(session, existing)

        utterances = [
            AudioUtteranceInput(
                voice_id=voice_ids[self._normalize_speaker(turn.speaker)],
                speaker_display_name=turn.speaker,
                text=turn.text,
            )
            for turn in content.turns
        ]
        tags = self._tags(session, batch, content, utterances)
        audio = self.synthesis_service.audio_service.create_audio(
            session,
            author=owner,
            title=content.title,
            source_type=AudioSourceType.CORPUS,
            utterances=utterances,
            tags=tags,
        )
        item.audio_id = audio.id
        item.status = GenerationBatchStatus.PROCESSING
        item.error_summary = None
        item.attempt_count += 1
        session.commit()
        return audio

    def _tags(
        self,
        session: Session,
        batch: GenerationBatch,
        content: GeneratedListeningContent,
        utterances: list[AudioUtteranceInput],
    ) -> list[AudioTag]:
        tags = list(batch.tags)
        tags.extend(
            self._tag(session, AudioTagType.TOPIC, value)
            for value in content.suggested_topics
        )
        tags.extend(
            self._tag(session, AudioTagType.CATEGORY, value)
            for value in content.suggested_categories
        )
        tags.extend(
            self._tag(session, AudioTagType.SPEAKER, item.speaker_display_name)
            for item in utterances
        )
        return list({tag.id: tag for tag in tags}.values())

    def _tag(
        self,
        session: Session,
        tag_type: AudioTagType,
        value: str,
    ) -> AudioTag:
        normalized = normalize_english_tag_value(value)
        tag = self.tag_repository.get_by_normalized_value(
            session,
            tag_type,
            normalized.normalized_value,
        )
        if tag is not None:
            return tag
        return self.tag_repository.create(
            session,
            tag_type=tag_type,
            value=normalized.value,
            normalized_value=normalized.normalized_value,
        )

    def _finish_batch(self, session: Session, batch: GenerationBatch) -> None:
        session.refresh(batch, attribute_names=["items"])
        if all(
            item.status is GenerationBatchStatus.COMPLETED for item in batch.items
        ):
            batch.status = GenerationBatchStatus.COMPLETED
            batch.error_summary = None
        else:
            batch.status = GenerationBatchStatus.FAILED
            batch.error_summary = "One or more generated audios failed"
        session.commit()

    def _fail_before_synthesis(
        self,
        session: Session,
        batch: GenerationBatch,
    ) -> None:
        session.rollback()
        batch = self.batch_repository.get_by_id(session, batch.id)
        if batch is None:
            return
        batch.status = GenerationBatchStatus.FAILED
        batch.error_summary = "Batch generation failed before synthesis"
        for item in batch.items:
            if item.status is not GenerationBatchStatus.COMPLETED:
                item.status = GenerationBatchStatus.FAILED
                item.error_summary = "Batch generation failed before synthesis"
        session.commit()

    @staticmethod
    def _content(item: GenerationBatchItem) -> GeneratedListeningContent:
        try:
            return GeneratedListeningContent.model_validate(item.generated_content)
        except ValidationError as exc:
            raise JobFailedError("Generated item content is invalid") from exc

    @staticmethod
    def _normalize_speaker(value: str) -> str:
        return unicodedata.normalize("NFKC", value.strip()).casefold()

    @staticmethod
    def _item_progress(completed: int, total: int) -> int:
        return 10 + completed * 85 // total

    @classmethod
    def _synthesis_progress(cls, position: int, total: int, value: int) -> int:
        start = cls._item_progress(position, total)
        end = cls._item_progress(position + 1, total)
        return start + (end - start) * value // 100
