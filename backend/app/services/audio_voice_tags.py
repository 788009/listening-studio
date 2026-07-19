from __future__ import annotations

from backend.app.core.exceptions import DomainValidationError
from backend.app.db.models.voice import Voice
from backend.app.services.tag_values import (
    NormalizedTagValue,
    normalize_english_tag_value,
)


def audio_voice_tag_value(voice: Voice) -> NormalizedTagValue:
    try:
        return normalize_english_tag_value(voice.title)
    except DomainValidationError:
        return normalize_english_tag_value(f"voice_{voice.id}")
