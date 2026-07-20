from __future__ import annotations

from collections.abc import Callable

from loguru import logger
from sqlalchemy.orm import Session

from backend.app.core.exceptions import JobFailedError
from backend.app.db.models.audio_tag import AudioTag, AudioTagType
from backend.app.db.models.generation_batch import (
    GenerationBatch,
    GenerationBatchSpeakerVoice,
    GenerationBatchStatus,
)
from backend.app.db.models.user import User
from backend.app.db.models.voice_tag import VoiceTagType
from backend.app.integrations.llm import (
    GeneratedListeningContent,
    ListeningContentGenerator,
    ListeningGenerationRequest,
    ListeningGenerationResult,
    QuestionType,
    TopicSuggestionRequest,
    TopicSuggestionResult,
    TopicTagSuggester,
)
from backend.app.repositories.audio_tags import AudioTagRepository
from backend.app.repositories.generation_batches import GenerationBatchRepository
from backend.app.services.corpus_storage import CorpusStorage
from backend.app.services.tag_values import (
    TagTranslationInput,
    normalize_english_tag_value,
    normalize_tag_translations,
)


_QUESTION_TYPE_CATEGORY_VALUES = {
    QuestionType.SHORT_DIALOGUE: "short",
    QuestionType.LONG_DIALOGUE: "long",
    QuestionType.MONOLOGUE: "monologue",
}


class CorpusGenerationService:
    def __init__(
        self,
        *,
        generator: ListeningContentGenerator,
        tag_suggester: TopicTagSuggester,
        corpus_storage: CorpusStorage,
        batch_repository: GenerationBatchRepository | None = None,
        tag_repository: AudioTagRepository | None = None,
    ) -> None:
        self.generator = generator
        self.tag_suggester = tag_suggester
        self.corpus_storage = corpus_storage
        self.batch_repository = batch_repository or GenerationBatchRepository()
        self.tag_repository = tag_repository or AudioTagRepository()

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
        if item_id is not None:
            raise JobFailedError("Individual draft generation is not supported")
        batch = self.batch_repository.get_by_id(session, batch_id)
        if batch is None or batch.owner_id != owner_id:
            raise JobFailedError("Generation batch is unavailable")
        owner = session.get(User, owner_id)
        if owner is None or not owner.is_profile_complete:
            raise JobFailedError("Generation batch owner is unavailable")

        try:
            batch.status = GenerationBatchStatus.PROCESSING
            batch.error_summary = None
            session.commit()
            corpus = self._read_corpus(job_id)
            checkpoint(20)
            result = ListeningGenerationResult.model_validate(
                self.generator.generate(
                    ListeningGenerationRequest(
                        corpus=corpus,
                        question_type_counts=batch.question_type_counts,
                        language=owner.locale,
                    ),
                    call_id=request_id,
                )
            )
            checkpoint(55)
            topic_tags = self._suggest_topics(
                session,
                corpus=corpus,
                language=owner.locale,
                request_id=request_id,
            )
            category_tags = self._question_type_categories(session, result.items)
            batch.tags = [*topic_tags, *category_tags]
            speaker_mapping = self._assign_speakers(batch, result.items)
            drafts = [
                self._draft(content, speaker_mapping) for content in result.items
            ]
            self.batch_repository.replace_items(session, batch=batch, drafts=drafts)
            batch.status = GenerationBatchStatus.COMPLETED
            batch.error_summary = None
            session.commit()
            checkpoint(90)
            logger.bind(
                request_id=request_id,
                job_id=job_id,
                user_db_id=owner.id,
                resource_type="generation_batch",
                resource_id=batch.id,
            ).info(
                "Corpus draft generation completed batch_id={} draft_count={} "
                "topic_count={} category_count={}",
                batch.id,
                len(drafts),
                len(topic_tags),
                len(category_tags),
            )
            return batch
        except JobFailedError:
            self._fail(session, batch)
            raise
        except Exception as exc:
            self._fail(session, batch)
            raise JobFailedError("Corpus draft generation failed") from exc
        finally:
            self.corpus_storage.cleanup(job_id)

    def _read_corpus(self, job_id: int) -> str:
        path = self.corpus_storage.path(job_id)
        if not path.is_file() or path.is_symlink():
            raise JobFailedError("Staged corpus is unavailable")
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise JobFailedError("Staged corpus could not be read") from exc

    def _suggest_topics(
        self,
        session: Session,
        *,
        corpus: str,
        language: str,
        request_id: str,
    ) -> list[AudioTag]:
        existing = self.tag_repository.list_tags(session, AudioTagType.TOPIC)
        result = TopicSuggestionResult.model_validate(
            self.tag_suggester.suggest(
                TopicSuggestionRequest(
                    corpus=corpus,
                    existing_topics=tuple(tag.value for tag in existing),
                    language=language,
                ),
                call_id=request_id,
            )
        )
        tags: list[AudioTag] = []
        for suggestion in result.topics:
            normalized = normalize_english_tag_value(suggestion.english_value)
            tag = self.tag_repository.get_by_normalized_value(
                session,
                AudioTagType.TOPIC,
                normalized.normalized_value,
            )
            if tag is None:
                tag = self.tag_repository.create(
                    session,
                    tag_type=AudioTagType.TOPIC,
                    value=normalized.value,
                    normalized_value=normalized.normalized_value,
                )
                translations = normalize_tag_translations(
                    [
                        TagTranslationInput(
                            language=item.language,
                            value=item.value,
                        )
                        for item in suggestion.translations
                    ]
                )
                for translation in translations:
                    self.tag_repository.add_translation(
                        session,
                        tag=tag,
                        language=translation.language,
                        value=translation.value.value,
                        normalized_value=translation.value.normalized_value,
                    )
            tags.append(tag)
        return tags

    def _question_type_categories(
        self,
        session: Session,
        contents: list[GeneratedListeningContent],
    ) -> list[AudioTag]:
        tags: list[AudioTag] = []
        seen: set[QuestionType] = set()
        for content in contents:
            question_type = content.question_type
            if question_type in seen:
                continue
            seen.add(question_type)
            value = _QUESTION_TYPE_CATEGORY_VALUES[question_type]
            normalized = normalize_english_tag_value(value)
            tag = self.tag_repository.get_by_normalized_value(
                session,
                AudioTagType.CATEGORY,
                normalized.normalized_value,
            )
            if tag is None:
                tag = self.tag_repository.create(
                    session,
                    tag_type=AudioTagType.CATEGORY,
                    value=normalized.value,
                    normalized_value=normalized.normalized_value,
                )
            tags.append(tag)
        return tags

    @staticmethod
    def _assign_speakers(
        batch: GenerationBatch,
        contents: list[GeneratedListeningContent],
    ) -> dict[str, GenerationBatchSpeakerVoice]:
        roles = {
            utterance.speaker
            for content in contents
            for utterance in content.utterances
        }
        entries = list(batch.speaker_voices)
        assigned: dict[str, GenerationBatchSpeakerVoice] = {}
        occupied: set[int] = set()
        preferred_gender = {"Man": "male", "Woman": "female"}

        for role in ("Man", "Woman"):
            if role not in roles:
                continue
            matching = next(
                (
                    entry
                    for entry in entries
                    if entry.id not in occupied
                    and any(
                        tag.type is VoiceTagType.GENDER
                        and tag.normalized_value == preferred_gender[role]
                        for tag in entry.voice.tags
                    )
                ),
                None,
            )
            selected = matching or next(
                (entry for entry in entries if entry.id not in occupied),
                None,
            )
            if selected is None:
                raise JobFailedError("Speaker voice mapping is incomplete")
            assigned[role] = selected
            occupied.add(selected.id)
        return assigned

    @staticmethod
    def _draft(
        content: GeneratedListeningContent,
        speaker_mapping: dict[str, GenerationBatchSpeakerVoice],
    ) -> dict[str, object]:
        return {
            "question_type": content.question_type.value,
            "title": content.title,
            "utterances": [
                {
                    "speaker_display_name": speaker_mapping[item.speaker].speaker,
                    "voice_id": speaker_mapping[item.speaker].voice_id,
                    "text": item.text,
                }
                for item in content.utterances
            ],
            "questions": [question.model_dump(mode="json") for question in content.questions],
        }

    @staticmethod
    def _fail(session: Session, batch: GenerationBatch) -> None:
        session.rollback()
        batch.status = GenerationBatchStatus.FAILED
        batch.error_summary = "Corpus draft generation failed"
        session.commit()
