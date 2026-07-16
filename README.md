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
Database and data-directory readiness is available at
`http://127.0.0.1:8000/health/ready`.

## Configuration

Runtime settings can be placed in `.env`; `.env.example` contains all supported
variables and their development defaults. `COSYVOICE_MODEL_DIR` is required.
Other settings use the `LISTENING_` prefix and cover the database URL, runtime
data and log directories, upload size limit, debug authentication, and log
rotation retention.

## Database Migrations

Apply all migrations to the configured database:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
.venv/bin/alembic -c alembic.ini upgrade head
```

Return an empty database to the pre-baseline state:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
.venv/bin/alembic -c alembic.ini downgrade base
```

## API Conventions

Errors use one stable envelope. `details` is `null` when no structured detail
is available, and `request_id` matches the `X-Request-ID` response header:

```json
{
  "error": {
    "code": "not_found",
    "message": "Resource not found",
    "details": null,
    "request_id": "request-123"
  }
}
```

Paginated JSON responses contain `items`, `page`, `page_size`, and `total`.

## Tests

Run the test suite from the repository root:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
.venv/bin/python -m unittest discover -s tests
```
