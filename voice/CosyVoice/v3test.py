import sys
sys.path.append('third_party/Matcha-TTS')
from cosyvoice.cli.cosyvoice import AutoModel
import torchaudio

def cosyvoice3_example():
    cosyvoice = AutoModel(model_dir='pretrained_models/Fun-CosyVoice3-0.5B')

    # 1. 提取并持久化存储 v3 的音色参数（注意添加 v3 特有的前缀）
    prompt_text_v3 = 'You are a helpful assistant.<|endofprompt|>希望你以后能够做的比我还好呦。'
    assert cosyvoice.add_zero_shot_spk(prompt_text_v3, './asset/zero_shot_prompt.wav', 'my_v3_spk') is True
    cosyvoice.save_spkinfo()

    # 2. 之后仅使用绑定的名字进行推理（将提示文本和音频路径留空）
    for i, j in enumerate(cosyvoice.inference_zero_shot(
        '八百标兵奔北坡，北坡炮兵并排跑。',
        '',
        '',
        zero_shot_spk_id='my_v3_spk',
        stream=False
    )):
        torchaudio.save('zero_shot_v3_by_id_{}.wav'.format(i), j['tts_speech'], cosyvoice.sample_rate)

cosyvoice3_example()
