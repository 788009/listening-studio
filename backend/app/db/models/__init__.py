"""ORM model registry."""

from backend.app.db.models.audio_tag import (
    AudioTag,
    AudioTagTranslation,
    AudioTagType,
)
from backend.app.db.models.user import User, UserStatus
from backend.app.db.models.voice import (
    Voice,
    VoiceExampleMode,
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
    "AudioTag",
    "AudioTagTranslation",
    "AudioTagType",
    "User",
    "UserStatus",
    "Voice",
    "VoiceExampleMode",
    "VoiceStatus",
    "VoiceVisibility",
    "VoiceTag",
    "VoiceTagTranslation",
    "VoiceTagType",
    "voice_tag_associations",
]
