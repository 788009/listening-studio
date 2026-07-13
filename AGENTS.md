# AGENTS.md

项目总目标是实现一个支持多用户的英语听力生成工具

所有操作均在 `source .venv/bin/activate` 环境内执行

所有操作之前先执行 `export COSYVOICE_MODEL_DIR=/home/uuk/listening/voice/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B`

使用 `loguru` 记录日志，所有操作都要记录到文件，关键操作、警告和错误要输出到终端

voice/CosyVoice/modules.py 实现了两个接口，分别是获取音色和合成音频，具体见 voice/CosyVoice/README.md，对 CosyVoice 的所有使用都只能通过 voice/CosyVoice/modules.py；使用时需要解决模块导入问题，见 voice/modules_test.py


