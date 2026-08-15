from pathlib import Path

from modules import generate_speech, save_zero_shot_voice


ROOT_DIR = Path(__file__).resolve().parent
TEST_DIR = ROOT_DIR / "test"


def main() -> None:
    voice_path = TEST_DIR / "input_voice.pt"
    output_path = TEST_DIR / "output.wav"

    save_zero_shot_voice(TEST_DIR / "input.wav", voice_path)
    text = (TEST_DIR / "prompt.txt").read_text(encoding="utf-8").strip()
    generate_speech(voice_path, text, output_path)

    print(f"voice file: {voice_path}")
    print(f"audio file: {output_path}")


if __name__ == "__main__":
    main()
