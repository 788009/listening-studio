# Voice 模块

`voice/modules.py` 提供多用户音色存储和语音合成功能。每个音色属于一个用户，每段合成音频属于一个音色。底层音色提取和语音合成统一通过 `voice/CosyVoice/modules.py` 调用。

## 环境要求

- Python 虚拟环境：项目根目录下的 `.venv`
- 可用的 NVIDIA GPU 和 CUDA 驱动
- 已安装并可使用 vLLM
- CosyVoice 模型目录：`voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B`

在项目根目录执行：

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
```

调用模块时使用绝对包导入：

```python
from voice.modules import (
    create_voice,
    delete_speech,
    delete_voice,
    fork_voice,
    get_final_prompt,
    synthesize_speech,
)
```

不要直接导入或调用 `voice/CosyVoice` 下的实现。

## 数据结构

数据统一存储在 `voice/data`：

```text
voice/data/
└── <username>/
    └── voice/
        └── <voice_name>/
            ├── voice.pt
            ├── <speech_name>.wav
            └── ...
```

- `voice.pt` 是从参考音频提取的音色文件。
- 每个 `.wav` 文件是使用当前目录下的 `voice.pt` 合成的声音。
- fork 只复制 `voice.pt`，不会复制已有的 `.wav` 文件。

`username`、`voice_name` 和 `speech_name` 必须是非空字符串，并且只能表示单个路径段。不能包含 `/`、`\`、空字符，也不能是 `.` 或 `..`。`speech_name` 不需要包含 `.wav` 后缀。

## 接口

### 创建音色

```python
create_voice(username, voice_name, audio_path) -> Path
```

从参考音频创建音色，返回生成的 `voice.pt` 路径。

```python
voice_path = create_voice(
    username="alice",
    voice_name="english_teacher",
    audio_path="samples/reference.wav",
)
```

参考音频不存在时抛出 `FileNotFoundError`。目标音色目录已存在时抛出 `FileExistsError`，不会覆盖已有音色或声音。

### 合成声音

```python
synthesize_speech(
    username,
    voice_name,
    speech_name,
    text,
    params=None,
) -> Path
```

使用指定音色合成声音，返回生成的 WAV 路径。

```python
audio_path = synthesize_speech(
    username="alice",
    voice_name="english_teacher",
    speech_name="lesson_001",
    text="Listen to the conversation and answer the question.",
    params={},
)
```

音色不存在时抛出 `FileNotFoundError`。同名声音已存在时抛出 `FileExistsError`，不会覆盖已有文件。

`params` 必须是字典或 `None`，当前作为预留参数传给 `get_final_prompt`，暂不改变合成行为。

### 构建最终 prompt

```python
get_final_prompt(text, params=None) -> str
```

该函数负责生成最终传给 CosyVoice 的文本。目前直接返回原始 `text`，包括原有的首尾空白。后续需要增加语速、情绪或文本格式控制时，应在该函数中统一处理。

### 删除音色

```python
delete_voice(username, voice_name) -> None
```

删除整个音色目录，包括 `voice.pt` 和该音色下的所有 WAV 文件。音色目录不存在时抛出 `FileNotFoundError`。

```python
delete_voice("alice", "english_teacher")
```

### 删除声音

```python
delete_speech(username, voice_name, speech_name) -> None
```

只删除指定的 WAV 文件，不删除音色。声音不存在时抛出 `FileNotFoundError`。

```python
delete_speech("alice", "english_teacher", "lesson_001")
```

### Fork 音色

```python
fork_voice(
    source_username,
    source_voice_name,
    target_username,
    target_voice_name,
) -> Path
```

将源音色复制到目标用户和目标名称，返回目标 `voice.pt` 路径。源音色可以 fork 给其他用户，也可以在同一用户下重命名。

```python
forked_path = fork_voice(
    source_username="alice",
    source_voice_name="english_teacher",
    target_username="bob",
    target_voice_name="shared_teacher",
)
```

源音色不存在时抛出 `FileNotFoundError`。目标音色目录已存在时抛出 `FileExistsError`。fork 不复制源音色目录下已经合成的声音。

## 写入行为

创建音色、合成声音和 fork 音色均先写入同目录临时文件，成功后再替换为最终文件。操作失败时会清理临时文件，避免留下可被当作有效资源使用的不完整文件。

模块使用进程内可重入锁保护存储操作。同一进程中的创建、合成、删除和 fork 操作不会并行修改存储目录。

## 日志

模块使用 `loguru` 记录关键操作、警告和异常：

```text
voice/logs/modules.log
```

日志文件按 `10 MB` 轮转，保留最近 10 个文件。测试脚本另写入：

```text
voice/logs/modules_test.log
```

## 运行完整测试

`voice/modules_test.py` 使用以下测试素材：

```text
voice/test/input.wav
voice/test/prompt.txt
```

测试流程如下：

1. 清理 `test/input` 和 `test/input_fork` 两个既有测试音色。
2. 为用户 `test` 创建音色 `input`。
3. 使用 `input` 合成 `output.wav`。
4. 将音色 fork 为同一用户下的 `input_fork`。
5. 使用 fork 后的音色再次合成 `output.wav`。

在项目根目录运行：

```bash
export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B
source .venv/bin/activate
.venv/bin/python voice/modules_test.py
```

成功后生成：

```text
voice/data/test/voice/input/voice.pt
voice/data/test/voice/input/output.wav
voice/data/test/voice/input_fork/voice.pt
voice/data/test/voice/input_fork/output.wav
```

测试脚本会删除上述同名音色后重新生成，不应对需要保留的数据使用这些测试名称。
