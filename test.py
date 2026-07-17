import os
import sys

# 获取 CosyVoice 文件夹的绝对路径并加入 sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
cosyvoice_dir = os.path.join(current_dir, 'CosyVoice')
sys.path.append(cosyvoice_dir)

# 现在可以正常导入
from voice.modules import *
