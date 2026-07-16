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
