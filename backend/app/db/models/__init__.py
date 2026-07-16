"""ORM model registry."""

from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioUtterance,
    AudioVisibility,
    audio_tag_associations,
)
from backend.app.db.models.audio_tag import (
    AudioTag,
    AudioTagTranslation,
    AudioTagType,
)
from backend.app.db.models.generation_batch import (
    GenerationBatch,
    GenerationBatchItem,
    GenerationBatchSpeakerVoice,
    GenerationBatchStatus,
    generation_batch_tag_associations,
)
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.user import User, UserStatus
from backend.app.db.models.voice import (
    Voice,
    VoiceSampleSource,
    VoiceStatus,
    VoiceVisibility,
    voice_tag_associations,
)
from backend.app.db.models.voice_tag import (
    VoiceTag,
    VoiceTagTranslation,
    VoiceTagType,
)

__all__ = [
    "Audio",
    "AudioSourceType",
    "AudioStatus",
    "AudioTag",
    "AudioTagTranslation",
    "AudioTagType",
    "AudioUtterance",
    "AudioVisibility",
    "Job",
    "JobStatus",
    "GenerationBatch",
    "GenerationBatchItem",
    "GenerationBatchSpeakerVoice",
    "GenerationBatchStatus",
    "User",
    "UserStatus",
    "Voice",
    "VoiceSampleSource",
    "VoiceStatus",
    "VoiceVisibility",
    "VoiceTag",
    "VoiceTagTranslation",
    "VoiceTagType",
    "audio_tag_associations",
    "generation_batch_tag_associations",
    "voice_tag_associations",
]
