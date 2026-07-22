# 英语听力生成工具开发说明

## 1. 文档定位与当前状态

本文件记录项目当前实现、固定约束和后续开发流程。`PLAN.md` 中 A01-J04 已全部完成，实施结果和后续增量需求记录在 `COMPLETED.md`。处理新需求时以当前代码和本文件为准，不得按早期规划假设回退现有行为。

项目当前已具备：用户与权限分级、音色管理、听力库、逐话轮创建和预览、题目、批量语料生成草稿、试卷组装、资源管理、亮暗色模式和中英文界面。LLM 仍使用可替换的占位实现，CosyVoice 通过单一后端适配层接入。

## 2. 固定约束

- 所有命令先执行：

  ```bash
  export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
  source .venv/bin/activate
  ```

- 后端使用 Python 3.10、FastAPI、SQLAlchemy 2、Alembic、Pydantic 和 Loguru。
- 开发和测试默认使用 SQLite；模型和迁移不得依赖 SQLite 专有能力，保留切换 PostgreSQL 的可能。
- FastAPI 业务 JSON 接口统一使用 `/api` 前缀；`/auth`、`/health` 和受保护媒体接口保持独立前缀。前端不得绕过 API 直接访问数据文件。
- 前端使用 Vue 3、TypeScript、Vue Router、Pinia、Tailwind CSS 和 Vite。组件统一使用 Composition API 和 `<script setup>`，不得混用 Options API。
- 前端工具链版本以 `frontend/package.json` 和 `frontend/package-lock.json` 为准。Vite 将 `/api`、`/auth`、`/health` 和媒体请求代理到 FastAPI；生产构建输出到 `frontend/dist`，由 FastAPI 托管并提供 SPA fallback。
- CosyVoice 只允许由 `backend/app/integrations/cosyvoice.py` 调用 `voice/CosyVoice/modules.py` 的公开接口。业务服务、路由和任务处理器不得直接导入 CosyVoice。
- LLM 接口位于 `backend/app/integrations/llm.py`。占位实现可替换，业务代码和前端不得依赖其固定示例返回值。
- 数据库保存元数据，文件系统保存模型、上传文件和生成音频。所有路径由后端根据整数 ID 生成，不接受客户端传入磁盘路径。
- 后端操作写入轮转文件日志；启动、关闭、关键业务操作、警告和异常同时输出终端。日志不得记录会话凭证、完整上传内容或完整听力文本。
- 普通测试不得加载 CosyVoice 模型。真实 GPU 测试单独标记并手动执行。
- 禁止使用 emoji。前端需要图标时使用 SVG。
- 保持冷静、平实、简洁、准确的界面文案，不使用营销、自我宣传或夸张表达。
- 原有注释若与改动无关，不得随意删除。新增抽象应有实际复用或复杂度收益，重视可读性和可维护性。

## 3. 当前架构

### 3.1 目录

```text
backend/
  app/
    api/                 # JSON API、鉴权和媒体路由
    core/                # 配置、日志、异常、鉴权和安全中间件
    db/                  # 会话和 ORM 模型
    integrations/        # CosyVoice、音频转码、OIDC 和占位 LLM
    repositories/        # 数据访问
    services/            # 领域规则和文件操作
    workers/             # 持久化任务执行器
    main.py
  alembic/               # 数据库迁移
frontend/
  src/
    api/                 # 类型化 API 客户端
    components/          # 可复用界面组件
    i18n/                # 界面翻译
    router/              # Vue Router
    stores/              # Pinia 状态
    styles/              # Tailwind CSS 入口和全局样式
    views/               # 路由页面
  dist/                  # 生产构建产物，不提交 Git
category_examples/       # short、long、monologue 的 LLM 输出示例
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
data/jobs/<job_id>/...    # 任务输入、预览和中间文件，按任务策略清理
```

音色示例使用原始录音时播放 `reference.wav`；选择公开音频时只记录音频 ID，不复制文件。删除资源前必须检查音色示例、批量任务、试卷和结果音频等引用。

### 3.2 前端路由

- `/`：首页。
- `/audio`、`/audio/:id`：听力库和音频详情。
- `/create`：统一的听力创建页，不显式区分单人和对话。
- `/generate`、`/generate/:id`：批量语料生成。
- `/papers/new`：段落式组卷，直接生成新的 `assembly` 音频。
- `/voices`、`/voice/:id`、`/voices/create`：音色列表、详情和创建。
- `/manage`：教师资源管理。
- `/admin/users`：Super Admin 用户权限管理。
- `/user/:userId`：教师公开资料。

界面支持亮色和暗色模式。标签在资源列表、详情和选择器中使用 chip；搜索联想使用普通列表，不使用 chip。页面布局保持克制、清晰，不加入营销区块或功能宣传文案。

## 4. 核心业务规则

### 4.1 用户与权限

- `users.id` 是从 1 开始的数据库自增主键。占位 OIDC 中间层以不可变的 `issuer + subject` 识别教师。
- 首次认证只创建待完善用户；设置 `userId` 后才能使用教师功能。
- `userId` 只允许 ASCII 大小写字母和数字，按 Unicode 规范化后的不区分大小写值保证唯一；设置后不能修改。
- `username` 是可修改的展示名，不能用于鉴权、外键或磁盘路径。
- 未认证访问者为学生，只能查看、搜索和播放公开且就绪的音频。
- 教师角色分为 `user`、`admin`、`super_admin`。普通教师可以查看公开资源和自己的私有资源，只能修改、删除自己的资源。
- Admin 和 Super Admin 可以删除其他教师的公开音频和公开音色，但不能修改这些资源，也不能访问其他教师的私有资源。
- 只有 Super Admin 可以在 `/admin/users` 将 User 设置为 Admin 或撤销 Admin。Super Admin 只能通过后端命令设置或撤销：

  ```bash
  .venv/bin/python -m backend.app.user_admin set-super-admin USER_ID
  .venv/bin/python -m backend.app.user_admin unset-super-admin USER_ID
  ```

- 只有 Admin 和 Super Admin 可以直接上传某一话轮的音频。上传预览不绑定上传时的文本、说话人或音色；发布时使用当前表单值。若随后重新生成该话轮，则恢复生成快照和修改确认规则。

### 4.2 音色和音频

- 音色、音频均使用从 1 开始的自增整数 ID。标题经过 Unicode NFKC 规范化和不区分大小写处理后全局唯一，不按作者分区。
- 数据库可见性只有 `private` 和 `public`。资源记录创建时保持私有；当前前端创建流程默认选择“就绪后公开”，只有状态为 `ready` 且文件存在的资源才能公开和播放。
- 音色包含作者、标题、模型状态、示例来源、可见性、时间戳和标签。参考录音及管理员话轮上传支持 WAV、MP3、M4A/AAC、FLAC、OGG/Opus 和 WebM，并由后端统一转为 WAV。
- 音频包含作者、标题、规范化全文、来源类型、生成状态、可见性、时长、时间戳、标签、题目和有序话轮。
- 每个话轮包含音色 ID、音频内说话人显示名、文本和顺序。`speaker` 只表示该音频内部给音色起的角色名；`voice` 表示可复用的音色资源。
- 创建页统一使用“说话人定义 + 有序话轮”。只有一个说话人时自然形成单人音频，不保存或展示人为的“单人/对话”模式选择。
- 每个话轮可以独立生成和预览，也可以重新生成。最终按钮先为所有未生成话轮生成预览，全部完成后才允许发布。
- 生成预览后修改文本或切换说话人会保留旧预览；发布前确认是否丢弃未重新生成的修改。仅修改说话人显示名不视为音频内容变化。
- 一个音频可以没有题目，也可以有多道题目。每道题包含题面、一个或多个正确答案、一个或多个错误答案；题目直接展示在音频详情页，不设置独立路由。
- 教师可以在公开音频详情使用“基于此音频创建”，复制说话人、文本、topic/category 标签和题目。后端按全局标题规则追加递增数字，系统标签在新音频发布时重新生成。

### 4.3 标签与搜索

- 音色标签和音频标签使用两套独立的表、ID、翻译和关联表，禁止跨系统复用 ID。
- 音色标签类型为 `author`、`gender`；音频标签类型为 `author`、`voice`、`topic`、`category`、`other`。
- 简写依次为 `a`、`g`、`v`、`t`、`c`、`o`。`a` 在音色和音频标签系统内分别解析。
- `author` 由系统根据不可变 `userId` 创建和关联；`voice` 由音频实际使用的音色生成；`other` 是系统类别，客户端不能创建、修改或直接关联这些标签。
- 音频存在题目时自动关联 `other:with_questions` 和 `other:N_question`，删除全部题目时自动移除。题数标签统一使用单数，提供固定中文翻译“N 道题”。
- 批量题型使用 `category:short`、`category:long`、`category:monologue`，固定中文翻译为“短对话”“长对话”“独白”。
- 标签英文规范值必填。值禁止保存空格和冒号；输入空白统一转为单个下划线。英文值只允许 ASCII 字母、数字、下划线和连字符；翻译允许 Unicode 字母和数字。
- 页面展示时将下划线替换为空格，优先使用当前语言翻译，不存在时回退英文。
- 搜索词用空白分隔，词之间采用 AND 语义。完整标签支持 `type:value` 和简写精确匹配；无类型词匹配英文标签、翻译或资源标题。
- 标题模糊搜索对标题和查询词做 Unicode NFKC 规范化及不区分大小写处理，再执行任意位置子串匹配。`%`、`_` 和转义符必须作为普通字符处理。
- 多语言标签输入先解析为标签 ID，再通过英文规范标签筛选。自动补全返回英文完整标签，例如 `topic:climate_change`。
- 联想结果按精确匹配、前缀、词边界、子串的位置和长度排序，不按纯字典序优先。
- 音频和音色列表中的所有标签 chip 都必须可点击并更新当前页面搜索；路由同步搜索框时不得触发联想。

### 4.4 批量生成与组卷

- 批量生成接收语料、每种题型的独立数量和说话人到音色的映射。短对话和长对话至少需要两个说话人，独白至少需要一个说话人。
- LLM 协议分为内容生成和 topic 建议两个稳定调用。当前占位实现从 `category_examples/` 返回示例并从已有 topic 随机选择建议；替换真实 LLM 时不得修改前后端调用协议。
- LLM 内容统一使用 `Man` 和 `Woman`。后处理优先按音色的 `male`、`female` 性别标签映射用户说话人；没有对应性别时选择尚未占用的第一个说话人。
- 后处理按全局音频标题规则解决重名，并为草稿关联建议 topic 和对应题型 category。前端把批量结果带入 `/create`，先生成所有草稿的逐话轮预览，再批量发布；失败草稿及其预览必须保留以便重试。
- 组卷由有序音频、静默、占位和智能段落组成。每个音频段落独立设置重复次数、重复间隔、正文和 topic 标签继承；题目不随音频重复。智能段落根据此前题数和下一占位音频题数动态选择 `pre_{start}` 或 `pre_{start}-{end}`。
- 组卷直接通过持久化任务生成 `assembly` 音频，不经过 `/create` 或 TTS。结果强制关联 `category:full_paper`，固定中文翻译“套卷”，且不能“基于此音频创建”。模板只允许 Admin 和 Super Admin 创建，不包含标签。

### 4.5 文件与事务一致性

- 创建文件型资源时，先创建状态记录和临时目录，再运行模型，最后原子替换目标文件并将状态更新为 `ready`。
- 失败时记录可诊断的错误摘要，删除临时文件，将资源状态改为 `failed`；不得留下可播放的半成品。
- 数据库提交和文件替换不能组成单一事务，服务层必须实现补偿和启动时一致性扫描。
- 删除操作先验证权限、活动任务和所有引用，再删除数据库关联和文件。失败必须可重试并记录审计日志。
- 预览、生成、批量生成和试卷渲染使用持久化 Job。进度应按实际阶段细分，不能在长时间任务中仅停留在一个粗粒度百分比。

## 5. 开发与验证流程

### 5.1 增量需求

1. 开始前检查 `git status --short` 和 `COMPLETED.md`，保留用户已有的无关修改。
2. 先阅读相关代码和测试，只实现当前用户请求，不顺带重构无关模块。
3. 根据风险补充后端集成/单元测试和前端 Vitest 测试；界面变更同时检查中英文、亮暗色和响应式布局。
4. 完成后更新 `COMPLETED.md`，执行聚焦测试，再执行受影响范围的全量检查。
5. 只暂存本任务文件，验证通过后立即创建独立提交，不合并无关改动，不改写他人提交历史。

提交信息采用 `type(scope): summary`，其中 `type` 使用 `feat`、`fix`、`test`、`docs`、`refactor`、`chore` 之一。模型、生成音频、数据库、日志、临时文件、前端构建产物和依赖目录不得提交。

常用验证命令：

```bash
.venv/bin/python -m unittest discover -s tests
npm --prefix frontend test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run build
```

修改迁移时还需在新数据库和现有数据库路径上验证：

```bash
.venv/bin/alembic -c alembic.ini upgrade head
```

### 5.2 PLAN.md 任务

只有用户明确要求继续或实施 `PLAN.md` 中的编号任务时，才使用 `scripts/plan_task.py`。不要为普通增量需求自动读取整个 `PLAN.md`。当前 A01-J04 均已完成；若以后新增规划任务，使用：

```bash
.venv/bin/python scripts/plan_task.py
.venv/bin/python scripts/plan_task.py A03
```

脚本返回当前任务内容和 `next_task_id`。一次只实现一个任务；先检查依赖和 `COMPLETED.md`，已完成的任务先重新验证，未通过则修复。出现未完成依赖时先处理依赖并返回，出现循环依赖时停止。

维护 `PLAN.md` 时，子任务必须位于 `## 子任务清单` 内，使用唯一的 `#### A01 标题` 四级标题；阶段使用三级标题。调整后必须运行：

```bash
.venv/bin/python -m unittest tests/test_plan_task.py
```

脚本依赖 Markdown AST 的标题节点和源码行映射定位任务，不得改为用正则表达式切割 Markdown 正文。
