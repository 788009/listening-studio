# English Listening Generator

[简体中文](README.zh-CN.md)

A Web application for creating English listening exercises. It includes a
FastAPI backend, a Vue frontend, persistent generation jobs, CosyVoice speech
synthesis, question editing, batch content generation, and paper assembly.

## Requirements

- Linux
- Git
- Python 3.10
- [uv](https://docs.astral.sh/uv/)
- Node.js 24.15 and npm 11.6
- An NVIDIA GPU and compatible CUDA runtime for speech synthesis

The Web/API process does not load CosyVoice. The persistent job worker loads
the model and should be the only worker using a given GPU.

## Clone the Repository

```bash
git clone https://github.com/788009/listening-studio.git
cd listening-studio
```

CosyVoice source code is included in this repository. Pretrained models and
local Python environments are not included.

## Configure the Application

Create the local environment file:

```bash
cp .env.example .env
```

The backend reads `.env` automatically. The default model path is relative to
the repository root:

```dotenv
COSYVOICE_MODEL_DIR=voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
```

Review the authentication and LLM values before starting the application.
For local development, either enable debug authentication or configure an OIDC
provider. Replace the session secret with a unique value of at least 32
characters.

Do not commit `.env`. It may contain API keys and authentication secrets.

## Install Application Dependencies

Install the backend environment from the repository root:

```bash
uv sync --python 3.10
source .venv/bin/activate
```

Install the locked frontend dependencies:

```bash
npm --prefix frontend ci
```

### CosyVoice Runtime

Speech generation additionally requires a CUDA-compatible inference stack
that provides `torch`, `torchaudio`, `vllm`, and the packages listed in
`voice/CosyVoice/requirements.txt`. These versions depend on the installed
NVIDIA driver and CUDA runtime. Follow the installation notes in
[`voice/CosyVoice/README_cosyvoice.md`](voice/CosyVoice/README_cosyvoice.md),
then verify the project environment:

```bash
.venv/bin/python -c "import torch, torchaudio, vllm"
```

The last verified project baseline used Python 3.10, PyTorch and torchaudio
2.8.0 with CUDA 12.8, and vLLM 0.11.0.

## Download the Model

Download `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` into the path configured in
`.env`. One option is ModelScope:

```bash
uv run --with modelscope==1.20.0 python -c "from modelscope import snapshot_download; snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', local_dir='voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B')"
```

For environments outside mainland China, Hugging Face can be used instead:

```bash
uv run --with huggingface-hub python -c "from huggingface_hub import snapshot_download; snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', local_dir='voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B')"
```

Model files are ignored by Git.

## Initialize the Database

```bash
source .venv/bin/activate
.venv/bin/alembic -c alembic.ini upgrade head
```

The development configuration uses SQLite and creates runtime files under
`data/` and logs under `logs/`.

## Start the Development Services

Run the API server from the repository root:

```bash
source .venv/bin/activate
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 18765 --reload
```

Run the persistent job worker in a second terminal after the CosyVoice runtime
and model are available:

```bash
source .venv/bin/activate
.venv/bin/python -m backend.app.workers.main
```

Run the frontend in a third terminal:

```bash
npm --prefix frontend run dev
```

Open `http://127.0.0.1:5173/`. The Vite development server proxies API,
authentication, health, and media requests to `http://127.0.0.1:18765`.

Health endpoints:

- `http://127.0.0.1:18765/health/live`
- `http://127.0.0.1:18765/health/ready`

## Authentication

For local debug authentication, set:

```dotenv
LISTENING_DEBUG_AUTH_ENABLED=true
LISTENING_OIDC_ENABLED=false
```

For OIDC, disable debug authentication and configure the discovery URL, client
credentials, callback URL, and post-login URL in `.env`. The callback URL must
be registered with the provider. The login endpoint and callback must use the
same origin so the OIDC flow cookie is retained.

## LLM Configuration

Batch generation and AI draft editing use an OpenAI-compatible API. Configure:

```dotenv
DASHSCOPE_API_KEY=replace-with-api-key
DASHSCOPE_BASE_URL=https://example.com/compatible-mode/v1
DASHSCOPE_MODEL=replace-with-model-name
```

## Tests and Checks

Backend tests:

```bash
source .venv/bin/activate
.venv/bin/python -m unittest discover -s tests
```

Frontend checks:

```bash
npm --prefix frontend test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run build
```

Ordinary tests do not load the CosyVoice model. The real GPU acceptance test is
manually gated:

```bash
source .venv/bin/activate
RUN_COSYVOICE_GPU_TESTS=1 .venv/bin/python -m unittest tests.gpu.test_cosyvoice_smoke -v
```

## Production

See [DEPLOYMENT.md](DEPLOYMENT.md) for production installation, process layout,
health checks, backup, restore, and consistency procedures.

Build the frontend before starting FastAPI with
`LISTENING_ENVIRONMENT=production`:

```bash
npm --prefix frontend run build
```

Use one persistent TTS worker per GPU. A SQLite deployment is intended for one
host; multi-host deployment requires a shared database and managed file
storage.

## Administration

After a teacher has completed profile setup, assign Super Admin from the
repository root:

```bash
source .venv/bin/activate
.venv/bin/python -m backend.app.user_admin set-super-admin USER_ID
```

Revoke it with:

```bash
.venv/bin/python -m backend.app.user_admin unset-super-admin USER_ID
```
