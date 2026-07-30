from __future__ import annotations

import re
import tempfile
from pathlib import Path

from backend.app.core.exceptions import DomainValidationError
from backend.app.integrations.cosyvoice import CosyVoiceIntegration
from backend.app.services.audio_combiner import AudioCombiner


MAX_SYNTHESIS_CHUNK_WORDS = 30
_WORD = re.compile(r"[A-Za-z0-9]+(?:['\u2019-][A-Za-z0-9]+)*")
_SENTENCE_ENDINGS = frozenset(".!?")
_SENTENCE_CLOSERS = frozenset("\"')]}\u2019\u201d")
_NON_TERMINAL_ABBREVIATIONS = frozenset(
    {
        "dr",
        "e.g",
        "etc",
        "i.e",
        "jr",
        "mr",
        "mrs",
        "ms",
        "prof",
        "sr",
        "st",
        "vs",
    }
)


def chunk_synthesis_text(
    text: str,
    *,
    max_words: int = MAX_SYNTHESIS_CHUNK_WORDS,
) -> list[str]:
    if not isinstance(text, str) or not text.strip():
        raise DomainValidationError(
            "Synthesis text cannot be empty",
            details={"field": "text"},
        )
    if isinstance(max_words, bool) or not isinstance(max_words, int) or max_words < 1:
        raise ValueError("Maximum synthesis chunk words must be a positive integer")

    chunks: list[str] = []
    current_sentences: list[str] = []
    current_word_count = 0
    for sentence in _split_sentences(text.strip()):
        sentence_word_count = len(_WORD.findall(sentence))
        if current_sentences and current_word_count + sentence_word_count > max_words:
            chunks.append(" ".join(current_sentences))
            current_sentences = []
            current_word_count = 0
        current_sentences.append(sentence)
        current_word_count += sentence_word_count

    if current_sentences:
        chunks.append(" ".join(current_sentences))
    return chunks


def _split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    start = 0
    position = 0
    while position < len(text):
        if text[position] not in _SENTENCE_ENDINGS:
            position += 1
            continue

        end = position + 1
        while end < len(text) and text[end] in _SENTENCE_CLOSERS:
            end += 1
        if (
            (end == len(text) or text[end].isspace())
            and not _is_non_terminal_period(text, position)
        ):
            sentence = text[start:end].strip()
            if sentence:
                sentences.append(sentence)
            while end < len(text) and text[end].isspace():
                end += 1
            start = end
            position = end
            continue
        position += 1

    trailing = text[start:].strip()
    if trailing:
        sentences.append(trailing)
    return sentences


def _is_non_terminal_period(text: str, position: int) -> bool:
    if text[position] != ".":
        return False
    if (
        position > 0
        and position + 1 < len(text)
        and text[position - 1].isdigit()
        and text[position + 1].isdigit()
    ):
        return True
    prefix = text[:position]
    token_match = re.search(r"(?:[A-Za-z]\.)*[A-Za-z]+$", prefix)
    if token_match is None:
        return False
    token = token_match.group().casefold()
    return token in _NON_TERMINAL_ABBREVIATIONS or len(token) == 1


class ChunkedSpeechSynthesizer:
    def __init__(
        self,
        integration: CosyVoiceIntegration,
        *,
        combiner: AudioCombiner | None = None,
    ) -> None:
        self.integration = integration
        self.combiner = combiner or AudioCombiner()

    def synthesize(
        self,
        voice_path: Path,
        text: str,
        output_audio_path: Path,
    ) -> Path:
        chunks = chunk_synthesis_text(text)
        output = Path(output_audio_path)
        if len(chunks) == 1:
            return self.integration.synthesize(voice_path, chunks[0], output)

        with tempfile.TemporaryDirectory(
            dir=output.parent,
            prefix=f".{output.stem}.tts-",
        ) as temporary_dir:
            segment_paths: list[Path] = []
            temporary_root = Path(temporary_dir)
            for position, chunk in enumerate(chunks):
                segment_path = temporary_root / f"segment-{position:04d}.wav"
                self.integration.synthesize(voice_path, chunk, segment_path)
                segment_paths.append(segment_path)
            return self.combiner.combine_wav(
                segment_paths,
                output,
                silence_milliseconds=0,
            )
