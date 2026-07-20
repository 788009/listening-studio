from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session

from backend.app.core.auth import Principal
from backend.app.core.exceptions import DomainValidationError, NotFoundError
from backend.app.db.models.generation_batch import GenerationBatch
from backend.app.db.models.job import Job
from backend.app.db.models.user import User
from backend.app.integrations.llm import (
    MAX_CORPUS_LENGTH,
    MAX_GENERATION_COUNT,
    QuestionType,
)
from backend.app.repositories.generation_batches import GenerationBatchRepository
from backend.app.repositories.voices import VoiceRepository
from backend.app.services.authorization import AuthorizationService
from backend.app.services.corpus_storage import CorpusStorage
from backend.app.services.jobs import JobService
from backend.app.services.voice_storage import VoiceStorage
from backend.app.services.voices import VoiceService


CORPUS_GENERATION_JOB_TYPE = "corpus_generation"
SUPPORTED_CORPUS_ENCODINGS = {
    "utf-8": "utf-8",
    "utf-8-sig": "utf-8-sig",
    "utf-16": "utf-16",
    "utf-16-le": "utf-16-le",
    "utf-16-be": "utf-16-be",
}


@dataclass(frozen=True)
class GenerationBatchSubmission:
    batch: GenerationBatch
    job: Job


@dataclass(frozen=True)
class GenerationBatchListResult:
    items: list[GenerationBatch]
    total: int


class CorpusValidator:
    def __init__(self, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("Maximum corpus size must be positive")
        self.max_bytes = max_bytes

    def validate_text(self, text: str) -> str:
        if not isinstance(text, str):
            raise self._invalid("Corpus text is invalid", "corpus")
        encoded = text.encode("utf-8")
        self._validate_size(encoded, "corpus")
        return self._validate_decoded(text, "corpus")

    def validate_file(self, filename: str, content: bytes, encoding: str) -> str:
        if not isinstance(filename, str) or Path(filename).suffix.casefold() != ".txt":
            raise self._invalid("Corpus file must use the .txt extension", "file")
        if not isinstance(content, bytes):
            raise self._invalid("Corpus file content is invalid", "file")
        self._validate_size(content, "file")
        codec = self._normalize_encoding(encoding)
        try:
            decoded = content.decode(codec, errors="strict")
        except (UnicodeDecodeError, UnicodeError) as exc:
            raise self._invalid(
                "Corpus file does not match the declared encoding",
                "encoding",
            ) from exc
        return self._validate_decoded(decoded, "file")

    def _validate_size(self, content: bytes, field: str) -> None:
        if not content:
            raise self._invalid("Corpus cannot be empty", field)
        if len(content) > self.max_bytes:
            raise DomainValidationError(
                "Corpus exceeds the upload size limit",
                details={"field": field, "maxBytes": self.max_bytes},
            )

    @staticmethod
    def _normalize_encoding(value: str) -> str:
        if not isinstance(value, str):
            raise CorpusValidator._invalid(
                "Corpus file encoding is required",
                "encoding",
            )
        codec = SUPPORTED_CORPUS_ENCODINGS.get(
            value.strip().casefold().replace("_", "-")
        )
        if codec is None:
            raise CorpusValidator._invalid(
                "Corpus file encoding is not supported",
                "encoding",
            )
        return codec

    @staticmethod
    def _validate_decoded(value: str, field: str) -> str:
        normalized = value.removeprefix("\ufeff").strip()
        if not normalized:
            raise CorpusValidator._invalid("Corpus cannot be empty", field)
        if len(normalized) > MAX_CORPUS_LENGTH:
            raise DomainValidationError(
                "Corpus text is too long",
                details={"field": field, "maxLength": MAX_CORPUS_LENGTH},
            )
        if any(
            unicodedata.category(character) == "Cc"
            and character not in {"\n", "\r", "\t"}
            for character in normalized
        ):
            raise CorpusValidator._invalid(
                "Corpus contains binary or control data",
                field,
            )
        return normalized

    @staticmethod
    def _invalid(message: str, field: str) -> DomainValidationError:
        return DomainValidationError(message, details={"field": field})


class GenerationBatchService:
    def __init__(
        self,
        *,
        storage: CorpusStorage,
        voice_storage: VoiceStorage,
        max_corpus_bytes: int,
        max_generation_count: int,
        repository: GenerationBatchRepository | None = None,
        job_service: JobService | None = None,
        voice_repository: VoiceRepository | None = None,
        authorization: AuthorizationService | None = None,
    ) -> None:
        if not 1 <= max_generation_count <= MAX_GENERATION_COUNT:
            raise ValueError("Maximum generation count is invalid")
        self.storage = storage
        self.max_generation_count = max_generation_count
        self.validator = CorpusValidator(max_corpus_bytes)
        self.repository = repository or GenerationBatchRepository()
        self.job_service = job_service or JobService()
        self.voice_repository = voice_repository or VoiceRepository()
        self.voice_service = VoiceService(voice_storage)
        self.authorization = authorization or AuthorizationService()

    def submit_text(
        self,
        session: Session,
        *,
        owner: User,
        corpus: str,
        question_types: list[QuestionType],
        count: int,
        speaker_voice_map: Mapping[str, int],
        request_id: str,
    ) -> GenerationBatchSubmission:
        return self._submit(
            session,
            owner=owner,
            corpus=self.validator.validate_text(corpus),
            question_types=question_types,
            count=count,
            speaker_voice_map=speaker_voice_map,
            request_id=request_id,
        )

    def submit_file(
        self,
        session: Session,
        *,
        owner: User,
        filename: str,
        content: bytes,
        encoding: str,
        question_types: list[QuestionType],
        count: int,
        speaker_voice_map: Mapping[str, int],
        request_id: str,
    ) -> GenerationBatchSubmission:
        return self._submit(
            session,
            owner=owner,
            corpus=self.validator.validate_file(filename, content, encoding),
            question_types=question_types,
            count=count,
            speaker_voice_map=speaker_voice_map,
            request_id=request_id,
        )

    def get_owned(
        self,
        session: Session,
        owner: User,
        batch_id: int,
    ) -> GenerationBatch:
        batch = self.repository.get_by_id(session, batch_id)
        if batch is None or batch.owner_id != owner.id:
            raise NotFoundError("Generation batch not found")
        return batch

    def list_owned(
        self,
        session: Session,
        owner: User,
        *,
        page: int,
        page_size: int,
    ) -> GenerationBatchListResult:
        items, total = self.repository.list_for_owner(
            session,
            owner_id=owner.id,
            page=page,
            page_size=page_size,
        )
        return GenerationBatchListResult(items, total)

    def _submit(
        self,
        session: Session,
        *,
        owner: User,
        corpus: str,
        question_types: list[QuestionType],
        count: int,
        speaker_voice_map: Mapping[str, int],
        request_id: str,
    ) -> GenerationBatchSubmission:
        normalized_types = self._question_types(question_types)
        self._validate_count(count, normalized_types)
        speaker_voices = self._speaker_voices(session, owner, speaker_voice_map)
        minimum_speakers = 2 if any(
            item in {QuestionType.SHORT_DIALOGUE, QuestionType.LONG_DIALOGUE}
            for item in normalized_types
        ) else 1
        if len(speaker_voices) < minimum_speakers:
            raise DomainValidationError(
                "Selected question types require more speakers",
                details={
                    "field": "speakerVoiceMap",
                    "minimumSpeakers": minimum_speakers,
                },
            )

        job: Job | None = None
        try:
            job = self.job_service.create_job(
                session,
                owner=owner,
                job_type=CORPUS_GENERATION_JOB_TYPE,
                input_summary={"batchId": 0},
                retryable=True,
            )
            batch = self.repository.create(
                session,
                owner=owner,
                job=job,
                question_types=[item.value for item in normalized_types],
                requested_count=count,
                tags=[],
                speaker_voices=speaker_voices,
            )
            job.input_summary = {"batchId": batch.id}
            self.storage.write(job.id, corpus)
            session.commit()
        except Exception:
            session.rollback()
            if job is not None:
                self.storage.cleanup(job.id)
            raise
        logger.bind(
            request_id=request_id,
            job_id=job.id,
            user_db_id=owner.id,
            resource_type="generation_batch",
            resource_id=batch.id,
        ).info(
            "Corpus generation batch submitted batch_id={} job_id={} "
            "corpus_length={} requested_count={}",
            batch.id,
            job.id,
            len(corpus),
            count,
        )
        return GenerationBatchSubmission(batch=batch, job=job)

    @staticmethod
    def _question_types(values: list[QuestionType]) -> list[QuestionType]:
        if not values:
            raise DomainValidationError(
                "At least one question type is required",
                details={"field": "questionTypes"},
            )
        try:
            normalized = [QuestionType(value) for value in values]
        except (TypeError, ValueError) as exc:
            raise DomainValidationError(
                "Question type is invalid",
                details={"field": "questionTypes"},
            ) from exc
        if len(normalized) != len(set(normalized)):
            raise DomainValidationError(
                "Question types must be unique",
                details={"field": "questionTypes"},
            )
        return normalized

    def _validate_count(self, count: int, question_types: list[QuestionType]) -> None:
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not len(question_types) <= count <= self.max_generation_count
        ):
            raise DomainValidationError(
                "Generation count is outside the allowed range",
                details={
                    "field": "count",
                    "minimumCount": len(question_types),
                    "maxCount": self.max_generation_count,
                },
            )

    def _speaker_voices(
        self,
        session: Session,
        owner: User,
        values: Mapping[str, int],
    ) -> list[tuple[str, str, int]]:
        if not isinstance(values, Mapping):
            raise self._invalid_speaker_voice_map()
        result: list[tuple[str, str, int]] = []
        seen_speakers: set[str] = set()
        for speaker, voice_id in values.items():
            if not isinstance(speaker, str):
                raise self._invalid_speaker_voice_map()
            display = unicodedata.normalize("NFKC", speaker.strip())
            normalized = display.casefold()
            if not display or len(display) > 200 or normalized in seen_speakers:
                raise self._invalid_speaker_voice_map()
            if (
                isinstance(voice_id, bool)
                or not isinstance(voice_id, int)
                or voice_id < 1
            ):
                raise self._invalid_speaker_voice_map()
            voice = self.voice_repository.get_by_id(session, voice_id)
            if voice is None:
                raise NotFoundError("Voice not found")
            self.authorization.require_use_for_synthesis(
                Principal(owner),
                self.voice_service.descriptor(voice),
            )
            result.append((display, normalized, voice.id))
            seen_speakers.add(normalized)
        return result

    @staticmethod
    def _invalid_speaker_voice_map() -> DomainValidationError:
        return DomainValidationError(
            "Speaker voice map is invalid",
            details={"field": "speakerVoiceMap"},
        )
