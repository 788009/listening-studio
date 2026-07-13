import sys
from pathlib import Path

from loguru import logger


ROOT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ROOT_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from voice.modules import create_voice, delete_voice, fork_voice, synthesize_speech


TEST_DIR = ROOT_DIR / "test"
USERNAME = "test"
SOURCE_VOICE_NAME = "input"
FORKED_VOICE_NAME = "input_fork"


def _delete_test_voice(voice_name: str) -> None:
    try:
        delete_voice(USERNAME, voice_name)
    except FileNotFoundError:
        pass


def main() -> None:
    logger.add(ROOT_DIR / "logs" / "modules_test.log", encoding="utf-8")
    _delete_test_voice(SOURCE_VOICE_NAME)
    _delete_test_voice(FORKED_VOICE_NAME)

    text = (TEST_DIR / "prompt.txt").read_text(encoding="utf-8").strip()
    voice_path = create_voice(USERNAME, SOURCE_VOICE_NAME, TEST_DIR / "input.wav")
    output_path = synthesize_speech(
        USERNAME,
        SOURCE_VOICE_NAME,
        "output",
        text,
    )
    forked_voice_path = fork_voice(
        USERNAME,
        SOURCE_VOICE_NAME,
        USERNAME,
        FORKED_VOICE_NAME,
    )
    forked_output_path = synthesize_speech(
        USERNAME,
        FORKED_VOICE_NAME,
        "output",
        text,
    )

    logger.info("Voice file: {}", voice_path)
    logger.info("Audio file: {}", output_path)
    logger.info("Forked voice file: {}", forked_voice_path)
    logger.info("Forked audio file: {}", forked_output_path)


if __name__ == "__main__":
    main()
