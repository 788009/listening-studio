# English Listening Generator

## Environment

The backend requires Python 3.10. Set up the project environment from the repository root:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
uv sync --python 3.10
source .venv/bin/activate
```

## Backend

Start the development server:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
uvicorn backend.app.main:app --reload
```

The liveness endpoint is available at `http://127.0.0.1:8000/health/live`.

## Tests

Run the test suite from the repository root:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
.venv/bin/python -m unittest discover -s tests
```
