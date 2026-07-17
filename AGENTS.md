# 英语听力生成工具实施规划

## 1. 规划目标

本规划将 `TASK.md` 和 `AGENTS.md` 中的要求拆成可独立实现、测试和验收的子任务。每个编号子任务对应一次 LLM 实施会话；一次只处理一个子任务，不跨任务顺带重构。每次实施结束前必须运行该任务列出的检查，并更新项目文档中受影响的部分。

## 2. 固定约束

- 所有命令先执行：

  ```bash
  export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
  source .venv/bin/activate
  ```

- 后端使用 Python 3.10、FastAPI、SQLAlchemy 2、Alembic、Pydantic 和 Loguru。
- 开发和测试默认使用 SQLite，模型及迁移避免依赖 SQLite 专有能力，保留切换 PostgreSQL 的可能。
- FastAPI 业务 JSON 接口统一使用 `/api` 前缀；`/auth`、`/health` 和受保护媒体接口保持独立前缀，前端不得绕过 API 直接访问数据文件。
- 前端使用 Vue 3、TypeScript、Vue Router、Pinia、Tailwind CSS 和 Vite。组件统一使用 Composition API 和 `<script setup>`，不得混用 Options API。
- 前端开发使用 Node.js LTS；Vite 开发服务器将 `/api`、`/auth`、`/health` 和受保护的媒体请求代理到 FastAPI。生产构建输出到 `frontend/dist`，由 FastAPI 托管静态资源并为前端路由提供 SPA fallback。
- CosyVoice 只允许由一个后端适配模块调用 `voice/CosyVoice/modules.py` 的两个公开接口。业务服务、路由和任务处理器不得直接导入 CosyVoice。
- LLM 首版使用可替换的占位实现。接口要稳定，业务代码不得依赖固定返回值。
- 数据库保存元数据，文件系统保存模型、上传文件和生成音频。所有路径由后端根据整数 ID 生成，不接受客户端传入磁盘路径。
- 后端所有操作写入轮转文件日志；启动、关闭、关键业务操作、警告和异常同时输出终端。日志不得记录会话凭证、完整上传内容或完整听力文本。
- 普通测试不得加载 CosyVoice 模型。真实 GPU 测试单独标记并手动执行。
- 自主维护 Git 仓库。每个子任务开始和结束都检查工作区，只暂存本任务文件；验证通过后立即创建一个独立提交，不合并无关改动，不改写他人提交历史。
- 提交信息采用 `type(scope): summary`，其中 `type` 使用 `feat`、`fix`、`test`、`docs`、`refactor`、`chore` 之一。模型、生成音频、数据库、日志、临时文件、前端构建产物和依赖目录不得提交。
- 禁止在任何场景使用 emoji，前端若需要图标请使用 svg，来源由你决定。
- 重视代码设计，适当考虑可读性和可维护性。

## 3. 首版架构与目录

计划建立以下结构：

```text
backend/
  app/
    api/                 # JSON API 路由
    core/                # 配置、日志、异常、鉴权
    db/                  # 会话、ORM 模型、迁移辅助
    integrations/        # CosyVoice 和占位 LLM 的唯一接入点
    repositories/        # 数据访问
    services/            # 领域规则和文件操作
    workers/             # 持久化任务执行器
    main.py
  alembic/
frontend/
  src/
    api/                 # 类型化 API 客户端
    components/          # 可复用界面组件
    router/              # Vue Router
    stores/              # Pinia 状态
    views/               # 路由页面
    styles/              # Tailwind CSS 入口和少量全局样式
  public/
  package.json
  vite.config.ts
  dist/                  # 生产构建产物，不提交 Git
tests/
  unit/
  integration/
  e2e/
data/
  voice/<voice_id>/
  audio/<audio_id>/
  jobs/<job_id>/
logs/
```

文件布局固定为：

```text
data/voice/<id>/voice.pt
data/voice/<id>/reference.wav
data/audio/<id>/audio.wav
data/jobs/<job_id>/...    # 仅存任务中间文件，成功或失败后按策略清理
```

音色示例若使用原始录音，播放 `reference.wav`；若选择其他公开音频，数据库记录该音频 ID，不复制文件。删除资源时必须先检查这些引用。

## 4. 核心数据规则

### 4.1 用户与权限

- `users.id` 是从 1 开始的数据库自增主键。
- 占位 OIDC 中间层以不可变的 `issuer + subject` 识别教师。
- 首次认证只创建待完善用户；设置 `userId` 后才能使用教师功能。
- `userId` 只允许 ASCII 大小写字母和数字，按不区分大小写方式保证唯一，设置后首版不允许修改。
- `username` 是可修改的展示名，不能用于鉴权、外键或磁盘路径。
- 未认证访问者为学生，只能查看和播放公开音频。
- 教师可以查看公开资源和自己的私有资源，只能修改、删除自己的资源。

### 4.2 资源

- 音色、音频都使用从 1 开始的自增整数 ID。
- 可见性首版只有 `private` 和 `public`，新资源默认 `private`。
- 音色包含作者、标题、音色模型状态、示例来源、时间戳。
- 音频包含作者、标题、完整文本、来源类型、生成状态、可见性、时长和时间戳。
- 多人对话额外保存有序话轮，每个话轮包含音色 ID、说话人显示名、文本和顺序；`audios.text` 保存可阅读的规范化全文。
- 只有状态为 `ready` 且文件存在的资源能被播放或设为公开。

### 4.3 标签

- 音色标签和音频标签使用两套独立的表、ID、翻译和关联表，禁止跨系统复用 ID。
- 音色标签类型为 `author`、`gender`；音频标签类型为 `author`、`speaker`、`topic`、`category`。
- 简写依次为 `a`、`g`、`s`、`t`、`c`。`a` 在两套系统内分别解析。
- 一个标签由类型、英文规范值和多语言翻译组成。英文值必填。
- 标签值禁止保存空格和冒号；输入中的空白在保存前统一转为单个下划线。英文规范值只允许 ASCII 字母、数字、下划线和连字符，翻译值允许 Unicode 字母和数字；两者都使用适合对应语言的规范字段做唯一性和搜索判断。
- 作者标签由系统根据不可变 `userId` 自动创建和关联，客户端不能删除或替换。
- 页面展示时将下划线替换为空格，并优先使用当前语言翻译；翻译不存在时回退英文。
- 搜索词用空白分隔，词之间采用 AND 语义。完整标签支持 `type:value` 和简写并进行精确标签匹配；无类型词可匹配英文标签、翻译或对音色及音频标题进行模糊搜索。
- 标题模糊搜索定义为：对标题和查询词做 Unicode NFKC 规范化及不区分大小写处理，再执行任意位置子串匹配。`%`、`_` 和转义符必须按普通字符处理，不能成为 SQL 通配符。
- 多语言标签输入先解析到标签 ID，再通过英文规范标签执行筛选。自动补全的返回文本始终是英文完整标签，例如 `topic:climate_change`。

### 4.4 一致性

- 创建文件型资源时，先创建状态记录和临时目录，再运行模型，最后以原子替换写入目标文件并把状态更新为 `ready`。
- 失败时记录可诊断的错误摘要，删除临时文件，资源状态改为 `failed`；不留下可播放的半成品。
- 数据库提交和文件替换无法组成单一事务，服务层必须实现补偿和启动时一致性扫描。
- 删除操作先验证权限与引用，再删除数据库关联和文件。失败必须可重试，并记录审计日志。

## 5. 子任务自动化工作流

`PLAN.md` 只保存子任务清单、统一完成标准、里程碑和实施假设。Agent 不应为获取单个任务而把整个文件加入上下文，必须使用 `scripts/plan_task.py` 读取任务。

### 5.1 获取任务

所有命令仍需先设置模型目录并激活虚拟环境。当前虚拟环境使用项目内解释器执行脚本：

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
.venv/bin/python scripts/plan_task.py
```

不传任务编号时返回文档中的第一个任务。指定任务时把编号作为位置参数传入，编号不区分大小写：

```bash
.venv/bin/python scripts/plan_task.py A03
```

脚本向标准输出写入 JSON：

```json
{
  "task_id": "A03",
  "content": "#### A03 数据库会话和迁移框架\n...",
  "next_task_id": "A04"
}
```

最后一个任务的 `next_task_id` 为 `null`。文件无法读取、规划结构错误、任务编号重复或任务不存在时，脚本向标准错误输出原因并以状态码 2 退出。

### 5.2 Agent 执行顺序

1. 首次执行调用不带编号的命令；继续指定任务时调用带编号的命令。
2. 只把返回的 `content` 作为本次实现范围，同时遵守本文件中的全局约束。
3. 开始实现前检查任务的前置依赖是否已经完成。`next_task_id` 只表示文档顺序，不代表依赖已经满足。
4. 一次只实现一个任务，完成对应测试和验收，不提前实现下一任务。
5. 验证通过后按 Git 约束创建独立提交，并在结果中记录提交哈希。
6. 需要继续时使用本次返回的 `next_task_id` 再次调用脚本；值为 `null` 时停止。
7. 若一项任务的前置依赖包含未实现的任务，则先实现前置依赖，实现之后立刻返回。
8. 为了防止错乱，每完成一项任务，都需要更新 `COMPLETED.md`，开始一项任务之前，也需要先检查 `COMPLETED.md`，若已实现，则直接执行测试与验收，通过则直接转到下一项任务，若不通过则修改至通过。
9. 若出现循环依赖，则停止整个流程。

### 5.3 维护规划格式

- 子任务必须位于 `## 子任务清单` 内，并使用 `#### A01 标题` 形式的四级标题。
- 任务编号由一个 ASCII 字母和两位数字组成，在文件内必须唯一。
- 阶段使用三级标题；下一个一级至四级标题表示当前任务内容结束。
- 调整 `PLAN.md` 后必须运行：

  ```bash
  .venv/bin/python -m unittest tests/test_plan_task.py
  ```

- 脚本使用 Markdown AST 的标题节点和源码行映射定位任务，不得改为用正则表达式切割 Markdown 正文。
