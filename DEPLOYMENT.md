# Deployment and Maintenance

This document describes the supported first-release deployment: one host, one
SQLite database, one FastAPI web process, and one persistent worker attached to
one NVIDIA GPU. Run commands from the repository root as the service account.

## 1. Prerequisites

- Linux with a writable local filesystem for the database, `data/`, and `logs/`.
- Python 3.10 and `uv`.
- Node.js 24 LTS and npm 11.6.
- An NVIDIA driver compatible with the installed PyTorch CUDA build.
- The CosyVoice source tree and `Fun-CosyVoice3-0.5B` model files at the path
  configured by `COSYVOICE_MODEL_DIR`.

Create the Python environment once. The final `source` verifies that the new
environment can be activated:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
uv sync --python 3.10
source .venv/bin/activate
python --version
```

`uv sync` installs the application and test dependencies, but not the
CosyVoice inference stack. Install the repository's verified inference lock
before starting a production worker. Preinstalling `pyworld` avoids its
isolated-build failure; the final inexact sync restores the application's
newer dependency constraints without removing inference-only packages:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
uv pip install --python .venv/bin/python wheel-stub
uv pip install --python .venv/bin/python pyworld==0.3.4
uv pip sync voice/CosyVoice/requirements_.txt --python .venv/bin/python --no-build-isolation
uv sync --python 3.10 --inexact
.venv/bin/python -c "import torch, torchaudio, vllm"
```

Treat `voice/CosyVoice/requirements_.txt` as part of the tested model runtime.
Review and rerun the GPU acceptance test before deploying any dependency or
model revision change.

Verify the required Node.js toolchain after activating the project environment:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
node --version
npm --version
```

## 2. Runtime Configuration

Copy `.env.example` to `.env`, restrict it to the service account, and replace
all development secrets and paths:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
cp .env.example .env
chmod 0600 .env
```

At minimum, review these values:

| Variable | Production requirement |
| --- | --- |
| `COSYVOICE_MODEL_DIR` | Absolute, read-only model directory. |
| `LISTENING_ENVIRONMENT` | `production`. |
| `LISTENING_DATABASE_URL` | Absolute SQLite URL, for example `sqlite:////srv/listening/data/listening.db`. |
| `LISTENING_DATA_DIR` | Absolute writable resource directory. |
| `LISTENING_LOG_DIR` | Absolute writable log directory. |
| `LISTENING_FRONTEND_DIST_DIR` | Absolute path to `frontend/dist`. |
| `LISTENING_DEBUG_AUTH_ENABLED` | `false`; debug headers are not production authentication. |
| `LISTENING_AUTH_SESSION_SECRET` | Unique random value of at least 32 characters. |
| `LISTENING_METRICS_TOKEN` | Unique random token; expose metrics only to internal monitoring. |

Keep the database and managed files on the same host and preferably the same
storage volume. Create fixed directories before migration. The service account
needs read/write/execute access; other accounts should not have access:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
install -d -m 0750 data data/voice data/audio data/jobs logs
test -r "$COSYVOICE_MODEL_DIR/cosyvoice3.yaml"
test -w data
test -w logs
```

For paths outside the repository, replace `data` and `logs` with the absolute
paths from `.env`. Do not grant the Web process write access to model files.

## 3. Frontend Installation and Build

Install exactly the locked frontend dependencies and run all frontend checks:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
npm --prefix frontend ci
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
test -f frontend/dist/index.html
```

`frontend/dist` is generated deployment output and is not committed. Production
FastAPI startup fails if `LISTENING_FRONTEND_DIST_DIR` does not contain the
build. Vite is for development only and must not be exposed in production.

## 4. Database and Initial Validation

Apply migrations before either process starts:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
.venv/bin/alembic -c alembic.ini upgrade head
.venv/bin/alembic -c alembic.ini current
```

Run the read-only consistency scan. A new deployment should report no issues:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
.venv/bin/python -m backend.app.consistency
```

Do not use `--apply` until the report has been reviewed. Unknown files and
directories are reported but intentionally retained.

## 5. Starting Services

Start the Web process without `--reload`. Bind it to a private interface behind
an HTTPS reverse proxy:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Start exactly one persistent TTS worker for the GPU in a separate service:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
.venv/bin/python -m backend.app.workers.main
```

Both processes must use the same working directory, `.env`, database URL, data
directory, log directory, model directory, and application revision. Configure
the service manager to send `SIGTERM`, restart on failure, and stop the worker
before replacing application code or model files.

Check Web liveness and database/data-directory readiness:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
curl --noproxy 127.0.0.1 --fail --silent --show-error http://127.0.0.1:8000/health/live
curl --noproxy 127.0.0.1 --fail --silent --show-error http://127.0.0.1:8000/health/ready
```

The readiness endpoint deliberately does not load or test the GPU model. Run
the manually gated GPU acceptance test after installing or changing the model;
the command and verified baseline are in `README.md`.

## 6. Authentication Replacement Boundary

`PlaceholderIdentityProvider` is only a development adapter. When
`LISTENING_DEBUG_AUTH_ENABLED=false`, it authenticates nobody, and the debug
session endpoint returns 404. A production deployment does not have teacher
login until a real provider is supplied.

A real OIDC adapter must implement `IdentityProvider.authenticate(request)` and
return only a validated `ExternalIdentity(issuer, subject)`. It must validate
the provider's signature, issuer, audience, expiry, nonce/state, and redirect
flow or trusted proxy assertion. Never accept the debug issuer/subject headers
from clients. Inject the provider at the composition root with
`create_app(settings, identity_provider=provider)`; do not change middleware,
repositories, foreign keys, or disk paths. The immutable `issuer + subject`
pair remains the account identity, while `userId` and `username` retain their
existing application roles.

Terminate the OIDC session through the provider and the application session
together. Preserve secure, HTTP-only, same-site cookies and the existing CSRF
check for cookie-authenticated state-changing requests.

## 7. LLM Replacement Boundary

`PlaceholderListeningContentGenerator` is deterministic scaffolding, not a
production content model. A real implementation must satisfy
`ListeningContentGenerator.generate(request, call_id=...)`. It belongs in the
worker composition root in `backend/app/workers/main.py`, replacing only the
placeholder passed to `ValidatingListeningContentGenerator`.

Keep `ValidatingListeningContentGenerator` around every implementation. It
enforces item counts, question types, field lengths, tags, language, and the
stable result schema before synthesis starts. The adapter should define request
timeouts, bounded retries, provider authentication, and error mapping. It must
log `call_id` and metadata only, never the complete corpus or generated
listening text. Routes, services, and job handlers must not import a provider
SDK directly.

## 8. Backup and Restore

The database describes files under `data/`; backing up either side alone can
produce references to missing or incorrect files. Take one consistent snapshot:

1. Stop the Web process so no new requests can commit.
2. Stop the worker and wait for it to exit so no file replacement is in flight.
3. Copy the SQLite database and the complete data directory in the same
   maintenance window.
4. Record the application revision, model identifier, and migration revision.
5. Restart only after both copies complete.

For an absolute SQLite path outside `data/`, a stopped-service backup can use:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
BACKUP_DIR=/srv/listening/backups/$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 0750 "$BACKUP_DIR"
cp --archive /srv/listening/state/listening.db "$BACKUP_DIR/listening.db"
tar --create --file "$BACKUP_DIR/data.tar" --directory /srv/listening/data .
.venv/bin/alembic -c alembic.ini current > "$BACKUP_DIR/migration.txt"
git rev-parse HEAD > "$BACKUP_DIR/application-revision.txt"
```

If SQLite is stored inside `data/`, archive the complete directory once instead
of making a second database copy. For PostgreSQL, coordinate `pg_dump` with the
same stopped-write filesystem snapshot; a database dump taken at a different
time from `data/` is not sufficient.

Restore into empty target paths while both services are stopped, set ownership
and permissions, then run migrations and a read-only consistency scan:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
cp --archive /srv/listening/backups/RESTORE_ID/listening.db /srv/listening/state/listening.db
tar --extract --file /srv/listening/backups/RESTORE_ID/data.tar --directory /srv/listening/data
chmod -R u=rwX,g=rX,o= /srv/listening/data
.venv/bin/alembic -c alembic.ini upgrade head
.venv/bin/python -m backend.app.consistency
```

Review the scan before running the explicit repair form:

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
.venv/bin/python -m backend.app.consistency --apply
```

Test restore procedures regularly on a separate host or isolated directory.

## 9. Supported Limits

- SQLite is a single-host first-release database. Do not share its file over
  NFS, run a multi-host deployment, or expect high write concurrency. Move to
  PostgreSQL and shared managed-file storage before multi-host operation.
- Run one TTS worker per GPU. Multiple workers can load duplicate models,
  exhaust memory, and violate the intended serialized GPU queue.
- Web processes never load CosyVoice. With SQLite, start with one Web process;
  scale only after measuring lock contention and accounting for per-process
  rate limiting.
- Database commits and filesystem replacement are compensating operations, not
  one atomic transaction. Run consistency scanning after an unclean shutdown,
  restore, disk error, or manual file intervention.
- Model, generated audio, database, logs, frontend build output, dependency
  directories, and job staging files are runtime state and must not enter Git.

## 10. Logs and Common Failures

All backend and worker events are written to `LISTENING_LOG_DIR/backend.log` and
rotated according to `LISTENING_LOG_ROTATION_BYTES` and
`LISTENING_LOG_RETENTION_FILES`. INFO and higher also go to stderr for the
service manager. Use request and job IDs to correlate submissions, worker
claims, failures, and resources. Logs intentionally omit credentials, complete
uploads, corpora, and generated listening text.

| Symptom | Check |
| --- | --- |
| Production startup fails | Build `frontend/dist` and verify `LISTENING_FRONTEND_DIST_DIR`. |
| `/health/ready` fails | Database connectivity and write permission on `LISTENING_DATA_DIR`. |
| All teacher calls return 401 | Real OIDC is not installed, the provider rejected the token, or debug auth is correctly disabled. |
| State-changing cookie request returns 403 | Send the `listening_csrf` cookie value in `X-CSRF-Token`. |
| Upload returns 422 | Use a complete uncompressed WAV within configured duration and size limits. |
| Resource returns 409 | Inspect status, missing files, and database references before publishing or deleting. |
| Request returns 429 | Respect `Retry-After`; review rate limits rather than bypassing them. |
| Jobs stay queued | Confirm the worker, database URL, application revision, and log path match the Web process. |
| GPU job fails at startup | Check `nvidia-smi`, model files, CUDA/PyTorch/vLLM versions, free GPU memory, and `backend.log`. |
| SQLite reports locked database | Stop duplicate processes and reduce write concurrency; do not use network storage. |
| Disk or process failed mid-job | Preserve logs, restart once, run the read-only consistency scan, then review any repair. |

## 11. Security Go-Live Checklist

- Use `LISTENING_ENVIRONMENT=production`, HTTPS, and a trusted reverse proxy.
- Replace placeholder OIDC before enabling teacher access; keep debug auth off.
- Replace the placeholder LLM or explicitly accept its non-production behavior.
- Generate unique session and metrics secrets; store `.env` with mode `0600`.
- Restrict database, `data/`, logs, model files, and backups to the service account.
- Expose only the reverse proxy; keep the app port, worker, database, and metrics
  endpoint on private interfaces.
- Preserve request size limits, CSRF enforcement, secure cookies, and rate limits.
- Apply migrations, run ordinary tests, build the frontend, run the consistency
  scan, and complete the GPU acceptance test for the deployed model revision.
- Verify log rotation, monitoring, disk alerts, backup completion, and a recent
  restore drill before accepting production data.
