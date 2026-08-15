# 英语听力生成工具

[English](README.md)

用于创建英语听力练习的 Web 应用。项目包含 FastAPI 后端、Vue 前端、持久化生成任务、CosyVoice 语音合成、题目编辑、批量内容生成和组卷功能。

## 环境要求

- Linux
- Git
- Python 3.10
- [uv](https://docs.astral.sh/uv/)
- Node.js 24.15 和 npm 11.6
- 用于语音合成的 NVIDIA GPU 及兼容的 CUDA 运行环境

Web/API 进程不会加载 CosyVoice。持久化任务进程负责加载模型，一块 GPU 只应运行一个任务进程。

## 克隆仓库

```bash
git clone https://github.com/788009/listening-studio.git
cd listening-studio
```

仓库已经包含 CosyVoice 源码，但不包含预训练模型和本地 Python 环境。

## 配置应用

创建本地环境文件：

```bash
cp .env.example .env
```

后端会自动读取 `.env`。默认模型路径相对于仓库根目录：

```dotenv
COSYVOICE_MODEL_DIR=voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
```

启动前应检查认证和 LLM 配置。本地开发可以启用调试认证，也可以配置 OIDC。会话密钥应替换为至少 32 个字符的唯一值。

不要提交 `.env`，其中可能包含 API 密钥和认证凭据。

## 安装应用依赖

在仓库根目录安装后端环境：

```bash
uv sync --python 3.10
source .venv/bin/activate
```

安装锁定的前端依赖：

```bash
npm --prefix frontend ci
```

### CosyVoice 运行环境

语音生成还需要与本机 CUDA 兼容的推理环境，其中应包含 `torch`、`torchaudio`、`vllm` 以及 `voice/CosyVoice/requirements.txt` 中列出的依赖。具体版本取决于 NVIDIA 驱动和 CUDA 运行环境。请参考 [`voice/CosyVoice/README_cosyvoice.md`](voice/CosyVoice/README_cosyvoice.md) 完成安装，然后验证项目环境：

```bash
.venv/bin/python -c "import torch, torchaudio, vllm"
```

项目最近一次验证使用 Python 3.10、CUDA 12.8 对应的 PyTorch 和 torchaudio 2.8.0，以及 vLLM 0.11.0。

## 下载模型

将 `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` 下载到 `.env` 配置的目录。可以使用 ModelScope：

```bash
uv run --with modelscope==1.20.0 python -c "from modelscope import snapshot_download; snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', local_dir='voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B')"
```

中国大陆以外的环境也可以使用 Hugging Face：

```bash
uv run --with huggingface-hub python -c "from huggingface_hub import snapshot_download; snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', local_dir='voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B')"
```

模型文件已被 Git 忽略。

## 初始化数据库

```bash
source .venv/bin/activate
.venv/bin/alembic -c alembic.ini upgrade head
```

开发配置使用 SQLite，运行数据写入 `data/`，日志写入 `logs/`。

## 启动开发服务

在仓库根目录启动 API：

```bash
source .venv/bin/activate
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 18765 --reload
```

确认 CosyVoice 运行环境和模型可用后，在第二个终端启动持久化任务进程：

```bash
source .venv/bin/activate
.venv/bin/python -m backend.app.workers.main
```

在第三个终端启动前端：

```bash
npm --prefix frontend run dev
```

访问 `http://127.0.0.1:5173/`。Vite 开发服务器会将 API、认证、健康检查和媒体请求代理到 `http://127.0.0.1:18765`。

健康检查地址：

- `http://127.0.0.1:18765/health/live`
- `http://127.0.0.1:18765/health/ready`

## 认证配置

本地调试认证配置：

```dotenv
LISTENING_DEBUG_AUTH_ENABLED=true
LISTENING_OIDC_ENABLED=false
```

使用 OIDC 时，应关闭调试认证，并在 `.env` 中配置发现地址、客户端凭据、回调地址和登录后地址。回调地址必须在身份提供方登记。登录入口和回调必须使用同一来源，以便浏览器保留 OIDC 流程 Cookie。

## LLM 配置

批量生成和 AI 修改草稿使用兼容 OpenAI 协议的接口：

```dotenv
DASHSCOPE_API_KEY=replace-with-api-key
DASHSCOPE_BASE_URL=https://example.com/compatible-mode/v1
DASHSCOPE_MODEL=replace-with-model-name
```

## 测试与检查

后端测试：

```bash
source .venv/bin/activate
.venv/bin/python -m unittest discover -s tests
```

前端检查：

```bash
npm --prefix frontend test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run build
```

普通测试不会加载 CosyVoice 模型。真实 GPU 验收测试需要手动启用：

```bash
source .venv/bin/activate
RUN_COSYVOICE_GPU_TESTS=1 .venv/bin/python -m unittest tests.gpu.test_cosyvoice_smoke -v
```

## 生产部署

生产安装、进程布局、健康检查、备份、恢复和一致性处理见 [DEPLOYMENT.md](DEPLOYMENT.md)。

使用 `LISTENING_ENVIRONMENT=production` 启动 FastAPI 前需要构建前端：

```bash
npm --prefix frontend run build
```

每块 GPU 只运行一个持久化 TTS 任务进程。SQLite 部署适用于单机；多机部署需要共享数据库和受管理的文件存储。

## 管理员设置

教师完成个人资料后，可以在仓库根目录设置 Super Admin：

```bash
source .venv/bin/activate
.venv/bin/python -m backend.app.user_admin set-super-admin USER_ID
```

撤销 Super Admin：

```bash
.venv/bin/python -m backend.app.user_admin unset-super-admin USER_ID
```
