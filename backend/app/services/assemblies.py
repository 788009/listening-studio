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
    AssemblySmartMode,
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
from backend.app.db.models.job import Job, JobStatus
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
from backend.app.services.job_storage import ASSEMBLY_PREVIEW_JOB_TYPE, JobStorage
from backend.app.services.jobs import JobService
from backend.app.services.tag_values import (
    TagTranslationInput,
    normalize_tag_translations,
)


ASSEMBLY_JOB_TYPE = "audio_assembly"
FULL_PAPER_VALUE = "full_paper"


@dataclass(frozen=True)
class AssemblySegmentInput:
    type: AssemblySegmentType
    audio_id: int | None = None
    suggested_query: str | None = None
    comment_text: str | None = None
    silence_milliseconds: int = 0
    smart_mode: AssemblySmartMode = AssemblySmartMode.QUESTION_NUMBER
    smart_silence_previous: bool = False
    smart_silence_next: bool = False
    repeat_count: int = 1
    repeat_interval_milliseconds: int = 0
    include_text: bool = True
    include_topic: bool = True


@dataclass(frozen=True)
class AssemblySubmission:
    audio: Audio
    job_id: int


@dataclass(frozen=True)
class AssemblyPreviewSubmission:
    job: Job


class AssemblyService:
    def __init__(self, storage: AudioStorage) -> None:
        self.storage = storage
        self.job_storage = JobStorage(storage.job_root.parent)
        self.audio_repository = AudioRepository()
        self.tag_repository = AudioTagRepository()
        self.audio_service = AudioService(storage, self.audio_repository)
        self.authorization = AuthorizationService()
        self.jobs = JobService()

    def submit_preview(
        self,
        session: Session,
        owner: User,
        *,
        segments: list[AssemblySegmentInput],
        start_index: int,
        end_index: int | None,
    ) -> AssemblyPreviewSubmission:
        if not segments:
            raise DomainValidationError(
                "Assembly requires at least one segment",
                details={"field": "segments"},
            )
        if (
            isinstance(start_index, bool)
            or not isinstance(start_index, int)
            or start_index < 0
            or start_index >= len(segments)
        ):
            raise DomainValidationError(
                "Assembly preview start index is invalid",
                details={"field": "startIndex"},
            )
        last_index = len(segments) - 1 if end_index is None else end_index
        if (
            isinstance(last_index, bool)
            or not isinstance(last_index, int)
            or last_index < start_index
            or last_index >= len(segments)
        ):
            raise DomainValidationError(
                "Assembly preview end index is invalid",
                details={"field": "endIndex"},
            )
        selected = self._resolve_preview_range(
            session,
            owner,
            segments,
            start_index,
            last_index,
        )
        if not any(item.audio is not None for item in selected):
            raise DomainValidationError(
                "Assembly preview requires an audio segment",
                details={"field": "segments"},
            )
        job: Job | None = None
        try:
            job = self.jobs.create_job(
                session,
                owner=owner,
                job_type=ASSEMBLY_PREVIEW_JOB_TYPE,
                input_summary={
                    "startIndex": start_index,
                    "endIndex": last_index,
                    "segmentCount": len(selected),
                },
            )
            session.flush()
            self.job_storage.write_assembly_preview_input(
                job.id,
                {
                    "segments": [
                        item.summary()
                        for item in selected
                        if item.input.type is not AssemblySegmentType.COMMENT
                    ]
                },
            )
            session.commit()
            return AssemblyPreviewSubmission(job)
        except Exception:
            session.rollback()
            if job is not None and job.id is not None:
                self.job_storage.cleanup(job.id)
            raise

    def process_preview(
        self,
        session: Session,
        *,
        job_id: int,
        owner_id: int,
        checkpoint: Callable[[int], None],
    ) -> None:
        preview_path = self.job_storage.assembly_preview_path(job_id)
        if preview_path.is_file() and not preview_path.is_symlink():
            self.storage.inspect_file(preview_path)
            return
        try:
            payload = self.job_storage.read_assembly_preview_input(job_id)
            values = payload.get("segments")
            if not isinstance(values, list) or not all(
                isinstance(item, dict) for item in values
            ):
                raise JobFailedError("Assembly preview task segments are invalid")
            checkpoint(15)
            plans = self._render_segments(session, owner_id, values)
            checkpoint(30)
            temporary = self.job_storage.assembly_preview_temporary_path(job_id)
            AssemblyAudioRenderer().render(plans, temporary)
            checkpoint(80)
            self.storage.inspect_file(temporary)
            self.job_storage.finalize_assembly_preview(job_id)
            self.job_storage.assembly_preview_input_path(job_id).unlink(missing_ok=True)
            checkpoint(95)
        except Exception as exc:
            self.job_storage.cleanup(job_id)
            raise JobFailedError("Assembly preview rendering failed") from exc

    def get_owned_preview(self, session: Session, owner: User, job_id: int) -> Job:
        job = self.jobs.get_owned_job(session, owner, job_id)
        if job.type != ASSEMBLY_PREVIEW_JOB_TYPE:
            raise ConflictError("Job is not an assembly preview")
        return job

    def delete_preview(
        self, session: Session, *, owner: User, job_id: int
    ) -> None:
        job = self.get_owned_preview(session, owner, job_id)
        if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            self.jobs.request_cancel(session, owner, job_id)
            session.commit()
            if job.status is JobStatus.RUNNING:
                return
        self.job_storage.cleanup(job_id)

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
            item.text
            for item in resolved
            if item.include_text and item.text is not None
        )
        audio: Audio | None = None
        job: Job | None = None
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
            summary_segments = [
                item.summary()
                for item in resolved
                if item.input.type is not AssemblySegmentType.COMMENT
            ]
            job = self.jobs.create_job(
                session,
                owner=owner,
                job_type=ASSEMBLY_JOB_TYPE,
                input_summary={
                    "audioId": audio.id,
                    "targetVisibility": visibility.value,
                },
                retryable=True,
            )
            session.flush()
            self.job_storage.write_assembly_input(
                job.id,
                {"segments": summary_segments},
            )
            session.commit()
            return AssemblySubmission(audio, job.id)
        except Exception:
            session.rollback()
            if audio is not None:
                self.storage.delete_audio(audio.id)
            if job is not None and job.id is not None:
                self.job_storage.cleanup(job.id)
            raise

    def process(
        self,
        session: Session,
        *,
        audio_id: int,
        job_id: int,
        owner_id: int,
        visibility: AudioVisibility,
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
            payload = self.job_storage.read_assembly_input(job_id)
            segments = payload.get("segments")
            if not isinstance(segments, list) or not all(
                isinstance(item, dict) for item in segments
            ):
                raise JobFailedError("Assembly task segments are invalid")
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
            if item.type is AssemblySegmentType.COMMENT:
                result.append(_ResolvedSegment(item, None))
                continue
            if item.type is AssemblySegmentType.SILENCE:
                result.append(_ResolvedSegment(item, None))
                continue
            if item.type is AssemblySegmentType.SMART:
                if item.smart_mode is AssemblySmartMode.QUESTION_COUNT_SILENCE:
                    associated_position = self._question_count_placeholder_position(
                        segments,
                        index,
                        previous=item.smart_silence_previous,
                    )
                    associated_question_count = len(
                        self._visible_audio(
                            session,
                            owner,
                            segments[associated_position].audio_id,
                            associated_position,
                        ).questions
                    )
                    result.append(
                        _ResolvedSegment(
                            item,
                            None,
                            item.silence_milliseconds * associated_question_count,
                        )
                    )
                    continue
                next_position = self._question_placeholder_position(segments, index)
                next_item = segments[next_position]
                next_audio = self._visible_audio(
                    session, owner, next_item.audio_id, next_position
                )
                count = len(next_audio.questions)
                if count == 0:
                    raise DomainValidationError(
                        "The placeholder after a smart segment requires questions",
                        details={"field": "segments", "position": next_position},
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

    def _resolve_preview_range(
        self,
        session: Session,
        owner: User,
        segments: list[AssemblySegmentInput],
        start_index: int,
        end_index: int,
    ) -> list[_ResolvedSegment]:
        smart_positions = [
            position
            for position in range(start_index, end_index + 1)
            if segments[position].type is AssemblySegmentType.SMART
        ]
        if smart_positions:
            resolution_end = end_index
            while True:
                expanded_end = resolution_end
                for position in range(resolution_end + 1):
                    item = segments[position]
                    if item.type is not AssemblySegmentType.SMART:
                        continue
                    if item.smart_mode is AssemblySmartMode.QUESTION_NUMBER:
                        expanded_end = max(
                            expanded_end,
                            self._question_placeholder_position(segments, position),
                        )
                    elif item.smart_silence_next:
                        expanded_end = max(
                            expanded_end,
                            self._question_count_placeholder_position(
                                segments,
                                position,
                                previous=False,
                            ),
                        )
                if expanded_end == resolution_end:
                    break
                resolution_end = expanded_end
            relevant = segments[: resolution_end + 1]
            self._validate_segments(relevant, allow_placeholders=True)
            return self._resolve_segments(session, owner, relevant)[
                start_index : end_index + 1
            ]

        relevant = segments[start_index : end_index + 1]
        self._validate_segments(relevant, allow_placeholders=True)
        result: list[_ResolvedSegment] = []
        for offset, item in enumerate(relevant):
            if item.type in {
                AssemblySegmentType.SILENCE,
                AssemblySegmentType.COMMENT,
            }:
                result.append(_ResolvedSegment(item, None))
                continue
            audio = self._visible_audio(
                session,
                owner,
                item.audio_id,
                start_index + offset,
            )
            result.append(_ResolvedSegment(item, audio))
        return result

    @staticmethod
    def _question_placeholder_position(
        segments: list[AssemblySegmentInput], position: int
    ) -> int:
        for next_position in range(position + 1, len(segments)):
            item = segments[next_position]
            if item.type is AssemblySegmentType.PLACEHOLDER:
                return next_position
            if item.type in {
                AssemblySegmentType.SILENCE,
                AssemblySegmentType.COMMENT,
            } or (
                item.type is AssemblySegmentType.SMART
                and item.smart_mode is AssemblySmartMode.QUESTION_COUNT_SILENCE
            ):
                continue
            break
        raise DomainValidationError(
            "A question-number smart segment requires a following placeholder with only silence or comments between",
            details={"field": "segments", "position": position},
        )

    @staticmethod
    def _question_count_placeholder_position(
        segments: list[AssemblySegmentInput], position: int, *, previous: bool
    ) -> int:
        direction = -1 if previous else 1
        smart_position = position
        candidate_position = position + direction
        while 0 <= candidate_position < len(segments):
            item = segments[candidate_position]
            if item.type is AssemblySegmentType.COMMENT:
                candidate_position += direction
                continue
            if item.type is AssemblySegmentType.PLACEHOLDER:
                return candidate_position
            break
        relation = "previous" if previous else "next"
        raise DomainValidationError(
            f"Question-count silence requires the {relation} segment to be a placeholder with only comments between",
            details={"field": "segments", "position": smart_position},
        )

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
                inherit_smart_topic = (
                    item.input.type is AssemblySegmentType.SMART
                    and item.include_topic
                    and tag.type is AudioTagType.TOPIC
                )
                if tag.type is AudioTagType.VOICE or inherit_smart_topic:
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
                    comment_text=item.comment_text,
                    silence_milliseconds=item.silence_milliseconds,
                    smart_mode=item.smart_mode,
                    smart_silence_previous=item.smart_silence_previous,
                    smart_silence_next=item.smart_silence_next,
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
        if not segments:
            raise DomainValidationError(
                "Assembly requires at least one segment",
                details={"field": "segments"},
            )
        for position, item in enumerate(segments):
            if not isinstance(item, AssemblySegmentInput) or not isinstance(
                item.type, AssemblySegmentType
            ):
                raise DomainValidationError(
                    "Assembly segment is invalid",
                    details={"field": "segments", "position": position},
                )
            if item.type is AssemblySegmentType.COMMENT:
                if (
                    not isinstance(item.comment_text, str)
                    or not item.comment_text.strip()
                ):
                    raise DomainValidationError(
                        "Comment segments require text",
                        details={"field": "segments", "position": position},
                    )
                continue
            if item.comment_text is not None:
                raise DomainValidationError(
                    "Only comment segments accept comment text",
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
            if item.type is AssemblySegmentType.SMART:
                if not isinstance(item.smart_mode, AssemblySmartMode):
                    raise DomainValidationError(
                        "Assembly smart mode is invalid",
                        details={"field": "segments", "position": position},
                    )
                if item.smart_mode is AssemblySmartMode.QUESTION_NUMBER:
                    AssemblyService._question_placeholder_position(segments, position)
                else:
                    if item.smart_silence_previous == item.smart_silence_next:
                        raise DomainValidationError(
                            "Question-count silence requires exactly one associated segment",
                            details={"field": "segments", "position": position},
                        )
                    AssemblyService._question_count_placeholder_position(
                        segments,
                        position,
                        previous=item.smart_silence_previous,
                    )
                    if (
                        not isinstance(item.silence_milliseconds, int)
                        or not 0 <= item.silence_milliseconds <= 60_000
                    ):
                        raise DomainValidationError(
                            "Question-count silence duration is invalid",
                            details={"field": "segments", "position": position},
                        )
                    continue
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
    resolved_silence_milliseconds: int | None = None

    @property
    def include_text(self) -> bool:
        return self.input.include_text

    @property
    def include_topic(self) -> bool:
        return self.input.include_topic

    @property
    def text(self) -> str | None:
        if self.input.type is AssemblySegmentType.COMMENT:
            assert self.input.comment_text is not None
            return self.input.comment_text.strip()
        return self.audio.text if self.audio is not None else None

    def summary(self) -> dict[str, object]:
        if self.audio is None:
            return {
                "type": "silence",
                "silenceMilliseconds": (
                    self.resolved_silence_milliseconds
                    if self.resolved_silence_milliseconds is not None
                    else self.input.silence_milliseconds
                ),
            }
        return {
            "type": "audio",
            "audioId": self.audio.id,
            "repeatCount": self.input.repeat_count,
            "repeatIntervalMilliseconds": self.input.repeat_interval_milliseconds,
        }
