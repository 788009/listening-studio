# English Listening Generator

## Environment

The backend requires Python 3.10. Set up the project environment from the repository root:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
uv sync --python 3.10
source .venv/bin/activate
```

## Operations

Apply database migrations before starting the services:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
.venv/bin/alembic -c alembic.ini upgrade head
```

Start the Web service:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
uvicorn backend.app.main:app --reload
```

Start the persistent job worker in a separate process:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
.venv/bin/python -m backend.app.workers.main
```

The liveness endpoint is available at `http://127.0.0.1:8000/health/live`.
Database and data-directory readiness is available at
`http://127.0.0.1:8000/health/ready`.
Set `LISTENING_METRICS_TOKEN` to enable the internal job metrics endpoint at
`http://127.0.0.1:8000/health/metrics`. It requires that value as a Bearer token.

Run only one TTS worker for a single GPU. Web processes can scale independently
because they do not load CosyVoice. A SQLite deployment is intended for a
single host; multi-host deployment requires a shared production database and
shared managed-file storage and is not supported by the SQLite configuration.

## Configuration

Runtime settings can be placed in `.env`; `.env.example` contains all supported
variables and their development defaults. `COSYVOICE_MODEL_DIR` is required.
Other settings use the `LISTENING_` prefix and cover the database URL, runtime
data and log directories, upload size limit, debug authentication, and log
rotation retention.

Set `LISTENING_ENVIRONMENT=production` after building the frontend to serve
`frontend/dist` from FastAPI. Production startup fails when the build is absent.

### Debug Authentication

When `LISTENING_DEBUG_AUTH_ENABLED=true`, development requests can provide
`X-Debug-OIDC-Issuer` and `X-Debug-OIDC-Subject`. Posting those headers to
`/auth/debug/session` creates an HTTP-only signed session cookie. Set a unique
`LISTENING_AUTH_SESSION_SECRET` of at least 32 characters. Debug headers and
placeholder session cookies are ignored when debug authentication is disabled.

## Frontend

The frontend requires Node 24.15 and npm 11.6. Install dependencies and start
the Vite development server from `frontend/`:

```bash
npm ci
npm run dev
```

Vite proxies `/api`, `/auth`, `/health`, and `/media` to FastAPI on port 8000.
Set `VITE_BACKEND_TARGET` when FastAPI uses another local address.
Run `npm run typecheck`, `npm run lint`, `npm run test`, and `npm run build`
before producing a release build.

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

## Consistency Scan

Report database and managed-file inconsistencies without changing either:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
.venv/bin/python -m backend.app.consistency
```

Apply the reported repairs explicitly:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
.venv/bin/python -m backend.app.consistency --apply
```

Unknown and orphaned filesystem entries are reported but retained.

## GPU Smoke Test

Run the manually gated real-model test with a readable reference WAV file:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
export COSYVOICE_SMOKE_INPUT_WAV=/absolute/path/to/reference.wav
export RUN_COSYVOICE_GPU_TESTS=1
.venv/bin/python -m unittest tests.gpu.test_cosyvoice_smoke
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

Authenticated teachers complete their profile with `POST /api/users/me/profile`
and update username or locale with `PATCH /api/users/me/profile`. Public profiles
are available at `GET /api/users/{userId}`; private statistics are included only
for the matching authenticated user.

Cookie-authenticated `POST`, `PUT`, `PATCH`, and `DELETE` requests must send the
`listening_csrf` cookie value in the `X-CSRF-Token` header. Login, search,
upload, generation, and media endpoints return HTTP 429 with `Retry-After` when
their configured request limit is exceeded.

## Tests

Run the test suite from the repository root:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
.venv/bin/python -m unittest discover -s tests
```
