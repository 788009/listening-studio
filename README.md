# English Listening Generator

See [DEPLOYMENT.md](DEPLOYMENT.md) for the complete production installation,
startup, backup, restore, integration-boundary, troubleshooting, and security
procedure.

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
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 18765 --reload
```

Start the persistent job worker in a separate process:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
.venv/bin/python -m backend.app.workers.main
```

The liveness endpoint is available at `http://127.0.0.1:18765/health/live`.
Database and data-directory readiness is available at
`http://127.0.0.1:18765/health/ready`.
Set `LISTENING_METRICS_TOKEN` to enable the internal job metrics endpoint at
`http://127.0.0.1:18765/health/metrics`. It requires that value as a Bearer token.

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

The frontend displays a development sign-in control when debug authentication
is enabled. Enter a stable issuer and subject to reuse a test teacher; change the
subject to exercise first-login profile setup with a new teacher. The form posts
the identity as structured JSON to the same debug session endpoint. Signing out
clears both the application session and CSRF cookies.

`GET /auth/capabilities` tells the frontend whether login is unavailable, uses
the debug form, or should redirect to a provider login URL. This keeps debug
identity fields out of normal business API calls and allows a real OIDC adapter
to replace the login mechanism without changing the account UI.

### OpenID Connect Authentication

Set `LISTENING_OIDC_ENABLED=true` and configure the discovery URL, client ID,
client secret, redirect URI, and post-login URL shown in `.env.example`. When
debug authentication is disabled, the application uses the OIDC Authorization
Code flow with `state`, `nonce`, discovery metadata, and signed ID Token
validation. Set `LISTENING_OIDC_PKCE_ENABLED=true` only when the provider
advertises S256 PKCE support. The configured redirect URI must also be
registered with the OIDC provider. Set
`LISTENING_OIDC_TOKEN_ENDPOINT_AUTH_METHOD` to the client authentication method
implemented by the provider.

Debug authentication takes precedence when both authentication modes are
enabled. This allows existing development identities to remain available by
changing only `LISTENING_DEBUG_AUTH_ENABLED`; disable it to test or use OIDC.
OIDC profile claims are not copied into local profiles automatically. Local
accounts continue to use the validated `issuer` and `subject` pair as their
immutable authentication identity.

## Frontend

The frontend requires Node 24.15 and npm 11.6. Install dependencies and start
the Vite development server from `frontend/`:

```bash
npm ci
npm run dev
```

Vite proxies `/api`, `/auth`, `/health`, and `/media` to FastAPI on port 18765.
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

### Super Admin Assignment

`super_admin` is never assignable through the application API or frontend. Set
it through the backend command after the teacher has completed profile setup:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
.venv/bin/python -m backend.app.user_admin set-super-admin TeacherOne
```

The user ID match is case-insensitive. To revoke Super Admin and restore the
account to User:

```bash
.venv/bin/python -m backend.app.user_admin unset-super-admin TeacherOne
```

Both commands are idempotent and print the previous role, resulting role, and
whether a change was made. Super Admins can assign the `admin` and `user` roles
from the User roles page.

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

## GPU Acceptance Test

Run the manually gated real-model test on an otherwise idle GPU:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
export RUN_COSYVOICE_GPU_TESTS=1
.venv/bin/python -m unittest tests.gpu.test_cosyvoice_smoke -v
```

The test defaults to `voice/CosyVoice/asset/zero_shot_prompt.wav`. Set
`COSYVOICE_SMOKE_INPUT_WAV` to use another readable speech sample. It creates a
dedicated temporary teacher, runs real voice extraction plus single-turn and
two-turn synthesis through the persistent job worker, validates PCM16 WAV
outputs and serial job claims, exercises failure cleanup and structured logs,
then deletes generated audio and voice resources through their API services.
The database, logs and any remaining test data are held in a temporary
directory. The test is skipped unless `RUN_COSYVOICE_GPU_TESTS=1`.

### Verified GPU Baseline

The acceptance test passed on 2026-07-17 with:

- NVIDIA GeForce RTX 4060 Laptop GPU, 8 GB; driver 571.96; CUDA 12.8.
- Python 3.10.17, PyTorch and torchaudio 2.8.0+cu128, vLLM 0.11.0.
- Fun-CosyVoice3-0.5B-2512 with CosyVoice repository commit `b4750f9`.
- Voice extraction 61.184 s; single-turn synthesis 1.459 s; two-turn synthesis
  1.876 s; total 66.731 s.
- Generated WAV durations 1.400 s and 2.290 s. Both were parseable PCM16 files.

The timings are a single acceptance run, not performance targets. On this 8 GB
GPU, the configured 32,768-token vLLM context requires the GPU to be otherwise
idle. WSL disables pinned memory, and this environment uses the PyTorch sampler
because FlashInfer is unavailable. The test disables vLLM usage reporting and
runs its engine in-process so no child process retains GPU memory. CosyVoice's
WeText frontend may still query ModelScope during initialization, including
when its files are already cached. Production remains limited to one persistent
TTS worker per GPU.

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
