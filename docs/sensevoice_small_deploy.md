# SenseVoiceSmall 本地部署说明

本文档说明如何在当前项目中单独部署 `SenseVoiceSmall`，避免影响主项目已有的 `.venv` 和 `.embed-gpu` 环境。

## 1. 环境位置

- 虚拟环境：`C:\Users\chens\Desktop\camera_project\.sensevoice`
- 模型目录：`D:\camera_agent_data\local_models\sensevoice\iic\SenseVoiceSmall`
- 测试脚本：`C:\Users\chens\Desktop\camera_project\tools\test_sensevoice.py`

## 2. 进入环境

```powershell
cd C:\Users\chens\Desktop\camera_project
.\.sensevoice\Scripts\Activate.ps1
```

## 3. 关键依赖

当前环境已安装：

- `torch 2.11.0+cu130`
- `torchaudio 2.11.0+cu130`
- `torchvision 0.26.0+cu130`
- `funasr 1.3.1`
- `modelscope 1.35.4`
- `soundfile`
- `librosa`

说明：

- 之所以单独新建环境，是因为原有 `torch 2.6.0+cu124` 无法正确支持你本机 `RTX 5070 Laptop GPU (sm_120)`。
- 现在这套环境已经实际验证过，可以在 GPU 上完成 SenseVoiceSmall 推理。

## 4. 测试命令

默认使用模型自带的中文示例音频：

```powershell
.\.sensevoice\Scripts\python.exe .\tools\test_sensevoice.py
```

指定你自己的音频文件：

```powershell
.\.sensevoice\Scripts\python.exe .\tools\test_sensevoice.py --audio "D:\your_audio.wav"
```

如果你想强制走 CPU：

```powershell
.\.sensevoice\Scripts\python.exe .\tools\test_sensevoice.py --device cpu
```

## 5. 当前验证结果

已在本机完成以下验证：

- `torch.cuda.is_available() == True`
- 能识别到 `NVIDIA GeForce RTX 5070 Laptop GPU`
- `SenseVoiceSmall` 可成功加载
- 中文示例音频可成功输出转写结果

示例输出类似：

```json
[
  {
    "key": "zh",
    "text": "<|zh|><|NEUTRAL|><|Speech|><|withitn|>开饭时间早上9点至下午5点。"
  }
]
```

## 6. 下一步如何接入你的项目

后续接入语音问答时，建议按下面方式复用：

1. 麦克风采集音频，保存为 `wav`
2. 用 `SenseVoiceSmall` 做 ASR，转成文本
3. 把文本直接送入现有“安防智能助理”问答工作流
4. 问答结果如果需要语音播报，再接一个 TTS 模块

建议保持 ASR 独立模块化，不要直接塞进 `monitoring_service.py`。
