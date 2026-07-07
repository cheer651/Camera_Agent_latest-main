# CosyVoice2-0.5B TTS 部署说明

小安大屏默认使用 CosyVoice2-0.5B 作为 TTS 服务。模型权重、源码、虚拟环境都放在 D 盘，避免继续占用 C 盘。

## 目录

```text
D:\camera_agent_data\local_models\cosyvoice\CosyVoice2-0.5B
D:\camera_agent_data\local_models\cosyvoice\CosyVoice
D:\camera_agent_data\venvs\cosyvoice2
D:\camera_agent_data\local_models\modelscope_cache
D:\camera_agent_data\local_models\hf_cache
```

## 安装

在项目根目录执行：

```powershell
.\tools\setup_cosyvoice2.ps1
```

脚本会完成：

- 创建 `D:\camera_agent_data\venvs\cosyvoice2`。
- 克隆官方 CosyVoice 源码。
- 下载 `CosyVoice2-0.5B` 权重到 D 盘。
- 安装 Windows 可用的最小 GPU 推理依赖。
- 使用 `pyworld-prebuilt` 替代需要 C++ 编译的 `pyworld`。

## 启动

正常启动主系统即可：

```powershell
python app.py
```

`voice_bridge.py` 会自动拉起 TTS 常驻服务，默认地址：

```text
http://127.0.0.1:5091
```

也可以单独启动：

```powershell
.\run_cosyvoice2.ps1
```

## 环境变量

- `XIAOAN_TTS_PROVIDER=cosyvoice2`：使用 CosyVoice2，默认值。
- `COSYVOICE2_DEVICE=auto|cuda|cpu`：默认 `auto`，本机建议 `cuda`。
- `COSYVOICE2_MODE=instruct2|zero_shot|sft`：默认 `instruct2`。
- `COSYVOICE2_PROMPT_AUDIO=参考音频路径`：替换音色参考音频。
- `COSYVOICE2_PROMPT_TEXT=参考音频对应文本`：zero-shot 模式使用。
- `COSYVOICE2_INSTRUCT_TEXT=音色和语气指令`：instruct2 模式使用。

## 自测

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:5091/health
```

语音合成：

```powershell
Invoke-RestMethod http://127.0.0.1:5091/synthesize -Method Post `
  -ContentType "application/json" `
  -Body '{"text":"您好，我是值班小安。","output_path":"D:\\camera_agent_data\\_voice\\outputs\\cosyvoice2\\test.wav"}'
```

## 说明

当前 Windows 环境下 `torchaudio.load/save` 会触发 TorchCodec 和 FFmpeg 依赖问题，因此项目的 `tools/cosyvoice2_server.py` 已将音频读写改为 `soundfile/librosa`，并关闭 CosyVoice 的 wetext 文本前端，由项目侧做轻量中文清洗。
