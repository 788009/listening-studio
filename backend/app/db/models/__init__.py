"""ORM model registry."""

from backend.app.db.models.audio import (
    Audio,
    AudioQuestion,
    AudioQuestionAnswer,
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
from backend.app.db.models.assembly import (
    AssemblySegmentType,
    AssemblyTemplate,
    AssemblyTemplateSegment,
)
from backend.app.db.models.generation_batch import (
    GenerationBatch,
    GenerationBatchItem,
    GenerationBatchQuestionType,
    GenerationBatchSpeakerVoice,
    GenerationBatchStatus,
    generation_batch_tag_associations,
)
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.paper import Paper, PaperItem, PaperPreset, PaperStatus
from backend.app.db.models.user import User, UserRole, UserStatus
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
    "AudioQuestion",
    "AudioQuestionAnswer",
    "AudioSourceType",
    "AudioStatus",
    "AudioTag",
    "AudioTagTranslation",
    "AudioTagType",
    "AudioUtterance",
    "AudioVisibility",
    "AssemblySegmentType",
    "AssemblyTemplate",
    "AssemblyTemplateSegment",
    "Job",
    "JobStatus",
    "Paper",
    "PaperItem",
    "PaperPreset",
    "PaperStatus",
    "GenerationBatch",
    "GenerationBatchItem",
    "GenerationBatchQuestionType",
    "GenerationBatchSpeakerVoice",
    "GenerationBatchStatus",
    "User",
    "UserRole",
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
