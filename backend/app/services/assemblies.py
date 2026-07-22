from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from backend.app.core.auth import Principal
from backend.app.core.exceptions import (
    ConflictError,
    DomainValidationError,
    JobFailedError,
    NotFoundError,
)
from backend.app.db.models.assembly import (
    AssemblySegmentType,
    AssemblyTemplate,
    AssemblyTemplateSegment,
)
from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioUtterance,
    AudioVisibility,
)
from backend.app.db.models.audio_tag import AudioTag, AudioTagType
from backend.app.db.models.user import User
from backend.app.repositories.audio_tags import AudioTagRepository
from backend.app.repositories.audios import AudioRepository
from backend.app.services.assembly_renderer import (
    AssemblyAudioRenderer,
    RenderAssemblySegment,
)
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audios import (
    AudioQuestionInput,
    AudioService,
    normalize_audio_title,
)
from backend.app.services.authorization import AuthorizationService
from backend.app.services.jobs import JobService
from backend.app.services.tag_values import (
    TagTranslationInput,
    normalize_tag_translations,
)


ASSEMBLY_JOB_TYPE = "audio_assembly"
MAX_SEGMENTS = 40
FULL_PAPER_VALUE = "full_paper"


@dataclass(frozen=True)
class AssemblySegmentInput:
    type: AssemblySegmentType
    audio_id: int | None = None
    suggested_query: str | None = None
    silence_milliseconds: int = 0
    repeat_count: int = 1
    repeat_interval_milliseconds: int = 0
    include_text: bool = True
    include_topic: bool = True


@dataclass(frozen=True)
class AssemblySubmission:
    audio: Audio
    job_id: int


class AssemblyService:
    def __init__(self, storage: AudioStorage) -> None:
        self.storage = storage
        self.audio_repository = AudioRepository()
        self.tag_repository = AudioTagRepository()
        self.audio_service = AudioService(storage, self.audio_repository)
        self.authorization = AuthorizationService()
        self.jobs = JobService()

    def list_templates(self, session: Session) -> list[AssemblyTemplate]:
        statement = (
            select(AssemblyTemplate)
            .options(selectinload(AssemblyTemplate.segments))
            .order_by(AssemblyTemplate.created_at.desc(), AssemblyTemplate.id.desc())
        )
        return list(session.scalars(statement))

    def create_template(
        self,
        session: Session,
        owner: User,
        title: str,
        segments: list[AssemblySegmentInput],
    ) -> AssemblyTemplate:
        self._require_admin(owner)
        value, normalized = normalize_audio_title(title)
        template = AssemblyTemplate(
            owner=owner, title=value, normalized_title=normalized
        )
        session.add(template)
        self._replace_template_segments(session, template, segments)
        try:
            session.flush()
        except IntegrityError as exc:
            raise ConflictError("Assembly template title already exists") from exc
        return template

    def update_template(
        self,
        session: Session,
        owner: User,
        template_id: int,
        title: str,
        segments: list[AssemblySegmentInput],
    ) -> AssemblyTemplate:
        self._require_admin(owner)
        template = self._template(session, template_id)
        value, normalized = normalize_audio_title(title)
        template.title = value
        template.normalized_title = normalized
        template.segments.clear()
        session.flush()
        self._replace_template_segments(session, template, segments)
        try:
            session.flush()
        except IntegrityError as exc:
            raise ConflictError("Assembly template title already exists") from exc
        return template

    def delete_template(self, session: Session, owner: User, template_id: int) -> None:
        self._require_admin(owner)
        session.delete(self._template(session, template_id))
        session.flush()

    def submit(
        self,
        session: Session,
        owner: User,
        *,
        title: str,
        segments: list[AssemblySegmentInput],
        tag_ids: list[int],
        visibility: AudioVisibility,
    ) -> AssemblySubmission:
        self._validate_segments(segments, allow_placeholders=True)
        resolved = self._resolve_segments(session, owner, segments)
        audio_segments = [item for item in resolved if item.audio is not None]
        if not audio_segments:
            raise DomainValidationError(
                "Assembly requires at least one audio segment",
                details={"field": "segments"},
            )
        explicit_tags = self._editable_tags(session, tag_ids)
        tags = self._assembly_tags(session, explicit_tags, resolved)
        questions = self._questions(audio_segments)
        text = "\n\n".join(
            item.audio.text for item in audio_segments if item.include_text
        )
        audio: Audio | None = None
        try:
            audio = self.audio_service.create_audio(
                session,
                author=owner,
                title=title,
                source_type=AudioSourceType.ASSEMBLY,
                text=text or "Assembly audio",
                questions=questions,
                tags=tags,
            )
            if not text:
                audio.text = ""
            self._copy_utterances(session, audio, audio_segments)
            summary_segments = [item.summary() for item in resolved]
            job = self.jobs.create_job(
                session,
                owner=owner,
                job_type=ASSEMBLY_JOB_TYPE,
                input_summary={
                    "audioId": audio.id,
                    "targetVisibility": visibility.value,
                    "segments": summary_segments,
                },
                retryable=True,
            )
            session.commit()
            return AssemblySubmission(audio, job.id)
        except Exception:
            session.rollback()
            if audio is not None:
                self.storage.delete_audio(audio.id)
            raise

    def process(
        self,
        session: Session,
        *,
        audio_id: int,
        job_id: int,
        owner_id: int,
        visibility: AudioVisibility,
        segments: list[dict[str, object]],
        checkpoint: Callable[[int], None],
    ) -> Audio:
        audio = self.audio_repository.get_by_id(session, audio_id)
        if audio is None or audio.author_id != owner_id:
            raise JobFailedError("Assembly output audio is unavailable")
        if audio.status is AudioStatus.READY and self.audio_service.is_ready(audio):
            return audio
        try:
            if audio.status is AudioStatus.PENDING:
                self.audio_service.transition_status(
                    session, audio, AudioStatus.PROCESSING
                )
            elif audio.status is not AudioStatus.PROCESSING:
                raise JobFailedError("Assembly output audio is not renderable")
            session.commit()
            plans = self._render_segments(session, owner_id, segments)
            checkpoint(25)
            AssemblyAudioRenderer().render(
                plans, self.storage.temporary_audio_path(job_id)
            )
            checkpoint(80)
            self.storage.inspect_temporary(job_id)
            self.storage.atomic_replace(audio.id, job_id)
            self.audio_service.record_file_metadata(session, audio)
            self.audio_service.transition_status(session, audio, AudioStatus.READY)
            self.audio_service.set_visibility(session, audio, visibility)
            session.commit()
            return audio
        except Exception as exc:
            self.storage.delete_audio(audio_id)
            session.rollback()
            audio = self.audio_repository.get_by_id(session, audio_id)
            if audio is not None:
                if audio.status is AudioStatus.PENDING:
                    self.audio_service.transition_status(
                        session, audio, AudioStatus.PROCESSING
                    )
                if audio.status is AudioStatus.PROCESSING:
                    self.audio_service.transition_status(
                        session,
                        audio,
                        AudioStatus.FAILED,
                        error_summary=f"Assembly rendering failed ({type(exc).__name__})",
                    )
                session.commit()
            raise JobFailedError("Assembly rendering failed") from exc
        finally:
            self.storage.cleanup_job(job_id)

    def _resolve_segments(
        self, session: Session, owner: User, segments: list[AssemblySegmentInput]
    ) -> list[_ResolvedSegment]:
        result: list[_ResolvedSegment] = []
        question_count = 0
        for index, item in enumerate(segments):
            if item.type is AssemblySegmentType.SILENCE:
                result.append(_ResolvedSegment(item, None))
                continue
            if item.type is AssemblySegmentType.SMART:
                if (
                    index + 1 >= len(segments)
                    or segments[index + 1].type is not AssemblySegmentType.PLACEHOLDER
                ):
                    raise DomainValidationError(
                        "A smart segment must be followed by a placeholder",
                        details={"field": "segments", "position": index},
                    )
                next_item = segments[index + 1]
                next_audio = self._visible_audio(
                    session, owner, next_item.audio_id, index + 1
                )
                count = len(next_audio.questions)
                if count == 0:
                    raise DomainValidationError(
                        "The placeholder after a smart segment requires questions",
                        details={"field": "segments", "position": index + 1},
                    )
                start = question_count + 1
                end = question_count + count
                smart_title = f"pre_{start}" if start == end else f"pre_{start}-{end}"
                smart_audio = self.audio_repository.get_by_normalized_title(
                    session, smart_title
                )
                if (
                    smart_audio is None
                    or (
                        smart_audio.author_id != owner.id
                        and smart_audio.visibility is not AudioVisibility.PUBLIC
                    )
                    or smart_audio.status is not AudioStatus.READY
                    or not self.storage.exists(smart_audio.id)
                ):
                    raise ConflictError(
                        f"Create a ready visible audio titled {smart_title} or adjust the segments",
                        details={"position": index, "requiredTitle": smart_title},
                    )
                result.append(_ResolvedSegment(item, smart_audio))
                question_count += len(smart_audio.questions)
                continue
            audio = self._visible_audio(session, owner, item.audio_id, index)
            result.append(_ResolvedSegment(item, audio))
            question_count += len(audio.questions)
        return result

    def _visible_audio(
        self, session: Session, owner: User, audio_id: int | None, position: int
    ) -> Audio:
        if isinstance(audio_id, bool) or not isinstance(audio_id, int) or audio_id < 1:
            raise DomainValidationError(
                "Assembly audio ID is invalid",
                details={"field": "segments", "position": position},
            )
        audio = self.audio_repository.get_by_id(session, audio_id)
        if audio is None:
            raise NotFoundError("Audio not found")
        self._require_visible_ready(owner, audio, position)
        return audio

    def _require_visible_ready(self, owner: User, audio: Audio, position: int) -> None:
        self.authorization.require_view(
            Principal(owner), self.audio_service.descriptor(audio)
        )
        if audio.status is not AudioStatus.READY or not self.audio_service.is_ready(
            audio
        ):
            raise ConflictError(
                "Assembly segments must reference ready audios",
                details={"position": position},
            )

    def _render_segments(
        self, session: Session, owner_id: int, values: list[dict[str, object]]
    ) -> list[RenderAssemblySegment]:
        result: list[RenderAssemblySegment] = []
        for value in values:
            if value.get("type") == AssemblySegmentType.SILENCE.value:
                result.append(
                    RenderAssemblySegment(None, int(value["silenceMilliseconds"]))
                )
                continue
            audio_id = value.get("audioId")
            if isinstance(audio_id, bool) or not isinstance(audio_id, int):
                raise JobFailedError("Assembly task data is invalid")
            audio = self.audio_repository.get_by_id(session, audio_id)
            if audio is None or not self.storage.exists(audio.id):
                raise JobFailedError("An assembly source audio is unavailable")
            if (
                audio.author_id != owner_id
                and audio.visibility is not AudioVisibility.PUBLIC
            ):
                raise JobFailedError("An assembly source audio is no longer visible")
            result.append(
                RenderAssemblySegment(
                    self.storage.path(audio.id),
                    0,
                    int(value["repeatCount"]),
                    int(value["repeatIntervalMilliseconds"]),
                )
            )
        return result

    def _assembly_tags(
        self,
        session: Session,
        explicit: list[AudioTag],
        segments: list[_ResolvedSegment],
    ) -> list[AudioTag]:
        result = list(explicit)
        seen = {tag.id for tag in result}
        for item in segments:
            if item.audio is None:
                continue
            for tag in item.audio.tags:
                if tag.type is AudioTagType.VOICE:
                    if tag.id not in seen:
                        result.append(tag)
                        seen.add(tag.id)
        full_paper = self.tag_repository.get_by_normalized_value(
            session, AudioTagType.CATEGORY, FULL_PAPER_VALUE
        )
        if full_paper is None:
            full_paper = self.tag_repository.create(
                session,
                tag_type=AudioTagType.CATEGORY,
                value=FULL_PAPER_VALUE,
                normalized_value=FULL_PAPER_VALUE,
            )
            normalized = normalize_tag_translations(
                [TagTranslationInput("zh-CN", "套卷")]
            )[0]
            self.tag_repository.add_translation(
                session,
                tag=full_paper,
                language=normalized.language,
                value=normalized.value.value,
                normalized_value=normalized.value.normalized_value,
            )
        if full_paper.id not in seen:
            result.append(full_paper)
        return result

    def _editable_tags(self, session: Session, tag_ids: list[int]) -> list[AudioTag]:
        result: list[AudioTag] = []
        for tag_id in dict.fromkeys(tag_ids):
            tag = self.tag_repository.get_by_id(session, tag_id)
            if tag is None or tag.type not in {
                AudioTagType.TOPIC,
                AudioTagType.CATEGORY,
            }:
                raise NotFoundError("Audio tag not found")
            result.append(tag)
        return result

    @staticmethod
    def _questions(segments: list[_ResolvedSegment]) -> list[AudioQuestionInput]:
        result: list[AudioQuestionInput] = []
        for item in segments:
            assert item.audio is not None
            for question in item.audio.questions:
                result.append(
                    AudioQuestionInput(
                        question.prompt,
                        tuple(
                            answer.text
                            for answer in question.answers
                            if answer.is_correct
                        ),
                        tuple(
                            answer.text
                            for answer in question.answers
                            if not answer.is_correct
                        ),
                    )
                )
        return result

    @staticmethod
    def _copy_utterances(
        session: Session, target: Audio, segments: list[_ResolvedSegment]
    ) -> None:
        position = 0
        for item in segments:
            assert item.audio is not None
            if not item.include_text:
                continue
            for utterance in item.audio.utterances:
                session.add(
                    AudioUtterance(
                        audio=target,
                        voice_id=utterance.voice_id,
                        speaker_display_name=utterance.speaker_display_name,
                        text=utterance.text,
                        position=position,
                    )
                )
                position += 1

    def _replace_template_segments(
        self,
        session: Session,
        template: AssemblyTemplate,
        segments: list[AssemblySegmentInput],
    ) -> None:
        self._validate_segments(segments, allow_placeholders=True)
        for position, item in enumerate(segments):
            if item.type is AssemblySegmentType.AUDIO:
                audio = self._visible_audio(
                    session,
                    template.owner,
                    item.audio_id,
                    position,
                )
                if audio.visibility is not AudioVisibility.PUBLIC:
                    raise ConflictError(
                        "Template audio segments must be public",
                        details={"position": position},
                    )
            session.add(
                AssemblyTemplateSegment(
                    template=template,
                    type=item.type,
                    audio_id=item.audio_id,
                    suggested_query=item.suggested_query,
                    silence_milliseconds=item.silence_milliseconds,
                    repeat_count=item.repeat_count,
                    repeat_interval_milliseconds=item.repeat_interval_milliseconds,
                    include_text=item.include_text,
                    include_topic=item.include_topic,
                    position=position,
                )
            )

    @staticmethod
    def _validate_segments(
        segments: list[AssemblySegmentInput], *, allow_placeholders: bool
    ) -> None:
        if not segments or len(segments) > MAX_SEGMENTS:
            raise DomainValidationError(
                "Assembly segment count is outside the allowed range",
                details={"field": "segments", "maxItems": MAX_SEGMENTS},
            )
        for position, item in enumerate(segments):
            if not isinstance(item, AssemblySegmentInput) or not isinstance(
                item.type, AssemblySegmentType
            ):
                raise DomainValidationError(
                    "Assembly segment is invalid",
                    details={"field": "segments", "position": position},
                )
            if (
                item.type
                in {AssemblySegmentType.PLACEHOLDER, AssemblySegmentType.SMART}
                and not allow_placeholders
            ):
                raise DomainValidationError(
                    "Template-only assembly segment is invalid",
                    details={"field": "segments", "position": position},
                )
            if item.type is AssemblySegmentType.SMART and (
                position + 1 >= len(segments)
                or segments[position + 1].type is not AssemblySegmentType.PLACEHOLDER
            ):
                raise DomainValidationError(
                    "A smart segment must be followed by a placeholder",
                    details={"field": "segments", "position": position},
                )
            if item.type is AssemblySegmentType.SILENCE:
                if (
                    not isinstance(item.silence_milliseconds, int)
                    or not 0 <= item.silence_milliseconds <= 60_000
                ):
                    raise DomainValidationError(
                        "Assembly silence is invalid",
                        details={"field": "segments", "position": position},
                    )
                continue
            if (
                not isinstance(item.repeat_count, int)
                or not 1 <= item.repeat_count <= 10
                or not isinstance(item.repeat_interval_milliseconds, int)
                or not 0 <= item.repeat_interval_milliseconds <= 60_000
            ):
                raise DomainValidationError(
                    "Assembly repeat settings are invalid",
                    details={"field": "segments", "position": position},
                )

    @staticmethod
    def _require_admin(owner: User) -> None:
        if owner.role.value not in {"admin", "super_admin"}:
            from backend.app.core.exceptions import ForbiddenError

            raise ForbiddenError("Admin access is required")

    @staticmethod
    def _template(session: Session, template_id: int) -> AssemblyTemplate:
        template = session.get(AssemblyTemplate, template_id)
        if template is None:
            raise NotFoundError("Assembly template not found")
        return template


@dataclass(frozen=True)
class _ResolvedSegment:
    input: AssemblySegmentInput
    audio: Audio | None

    @property
    def include_text(self) -> bool:
        return self.input.include_text

    @property
    def include_topic(self) -> bool:
        return self.input.include_topic

    def summary(self) -> dict[str, object]:
        if self.audio is None:
            return {
                "type": "silence",
                "silenceMilliseconds": self.input.silence_milliseconds,
            }
        return {
            "type": "audio",
            "audioId": self.audio.id,
            "repeatCount": self.input.repeat_count,
            "repeatIntervalMilliseconds": self.input.repeat_interval_milliseconds,
        }
