from __future__ import annotations

from typing import ClassVar


ErrorDetails = dict[str, object] | list[object] | None


class DomainError(Exception):
    code: ClassVar[str] = "domain_error"
    status_code: ClassVar[int] = 400
    default_message: ClassVar[str] = "Request could not be completed"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: ErrorDetails = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details
        super().__init__(self.message)


class NotFoundError(DomainError):
    code = "not_found"
    status_code = 404
    default_message = "Resource not found"


class ForbiddenError(DomainError):
    code = "forbidden"
    status_code = 403
    default_message = "Operation is not permitted"


class ProfileIncompleteError(DomainError):
    code = "profile_incomplete"
    status_code = 403
    default_message = "Profile setup is required"


class ConflictError(DomainError):
    code = "conflict"
    status_code = 409
    default_message = "Resource state conflicts with this operation"


class UserIdTakenError(ConflictError):
    code = "user_id_taken"
    default_message = "This user ID is already in use. Choose another ID."


class UserIdImmutableError(ConflictError):
    code = "user_id_immutable"
    default_message = "User ID has already been set and cannot be changed."


class AudioTitleTakenError(ConflictError):
    code = "audio_title_taken"
    default_message = "An audio with this title already exists."


class VoiceTitleTakenError(ConflictError):
    code = "voice_title_taken"
    default_message = "A voice with this title already exists."


class DomainValidationError(DomainError):
    code = "validation_error"
    status_code = 422
    default_message = "Request validation failed"


class JobFailedError(DomainError):
    code = "job_failed"
    status_code = 500
    default_message = "Job failed"
