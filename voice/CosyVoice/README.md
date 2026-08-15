# CosyVoice Zero-shot 语音模块

`modules.py` 基于 Fun-CosyVoice3 和 vLLM，提供音色提取与语音生成两个接口。

## 环境要求

- 已按 CosyVoice 项目要求安装依赖
- 已创建并启用项目虚拟环境 `.venv`
- 已准备模型 `pretrained_models/Fun-CosyVoice3-0.5B`
- 使用 vLLM 推理时需要可用的 CUDA 环境

默认模型路径可以通过环境变量覆盖：

```bash
export COSYVOICE_MODEL_DIR=/path/to/Fun-CosyVoice3-0.5B
```

## 接口说明

### 保存音色

```python
save_zero_shot_voice(audio_path, output_path)
```

从参考音频中提取 zero-shot 音色信息，并保存为 PyTorch 文件。

- `audio_path`：参考音频路径，音频长度不能超过 30 秒
- `output_path`：音色文件输出路径，建议使用 `.pt` 后缀

### 生成语音

```python
generate_speech(voice_path, text, output_path)
```

使用已保存的音色生成指定文本的语音。

- `voice_path`：由 `save_zero_shot_voice` 生成的音色文件路径
- `text`：需要合成的非空文本
- `output_path`：生成的 WAV 音频路径

音色文件必须与当前使用的模型版本一致。

## 使用示例

```python
from modules import generate_speech, save_zero_shot_voice


save_zero_shot_voice(
    "test/input.wav",
    "test/input_voice.pt",
)

generate_speech(
    "test/input_voice.pt",
    "你好，这是一段测试语音。",
    "test/output.wav",
)
```

模型在首次调用接口时加载，后续调用会复用同一个模型实例。输出目录不存在时会自动创建。

## 运行测试

`modules_test.py` 会提取 `test/input.wav` 的音色，读取 `test/prompt.txt`，并生成 `test/output.wav`：

```bash
source .venv/bin/activate
python modules_test.py
```

测试产物：

- `test/input_voice.pt`：提取的音色文件
- `test/output.wav`：生成的语音文件
