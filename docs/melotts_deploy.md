# MeloTTS 本地部署说明

本文档记录当前项目中 `MeloTTS` 的本地部署方式。当前部署目标是：

- 只保证中文播报可用
- 优先走 `CPU`
- 不抢占你现有的 `SenseVoice`、本地问答模型和视觉模型资源
- 尽量把缓存和模型文件落到 `D 盘`

## 1. 环境位置

- 虚拟环境：`C:\Users\chens\Desktop\camera_project\.melo`
- MeloTTS 源码目录：`D:\camera_agent_data\local_models\melo\src\melotts-0.1.1`
- Melo 缓存目录：`D:\camera_agent_data\local_models\melo\cache`
- Hugging Face 缓存目录：`D:\camera_agent_data\local_models\huggingface`

## 2. 当前部署特点

这次不是直接用 PyPI 的原始安装结果，而是做了兼容性修正，原因如下：

- `MeloTTS 0.1.1` 的 PyPI 源码包缺失根目录 `requirements.txt`
- 原始依赖锁定了旧版 `transformers`，在 `Python 3.12` 下会卡在 `tokenizers` 的 Rust 编译
- 官方代码里有一些“无关语言强依赖”，会把日语、韩语、法语、西语模块一起拉进来

所以当前可用版本做了几处本地修补：

- 修正 `setup.py`，允许在没有 `requirements.txt` 的情况下安装
- 修正 `english.py`，去掉对日语模块的硬依赖
- 修正 `cleaner.py`，改为按语言懒加载
- 修正 `text/__init__.py`，只按当前语言加载对应的 BERT 模块
- 修正 `download_utils.py`，把中文模型下载改为 Hugging Face 直链，并把缓存固定到 `D 盘`

## 3. 进入环境

```powershell
cd C:\Users\chens\Desktop\camera_project
.\.melo\Scripts\Activate.ps1
```

## 4. 测试命令

默认中文播报测试：

```powershell
python .\tools\test_melotts.py
```

自定义文本：

```powershell
python .\tools\test_melotts.py --text "今天下午二号摄像头检测到一条高风险事件。"
```

指定输出路径：

```powershell
python .\tools\test_melotts.py --text "测试播报" --output "D:\camera_agent_data\local_models\melo\outputs\alert.wav"
```

## 5. 当前验证结果

已经实际生成成功的测试音频：

- `D:\camera_agent_data\local_models\melo\test_zh.wav`

说明当前链路已经跑通：

- MeloTTS 可导入
- 中文模型可下载
- 中文文本可合成为 `wav`

## 6. 建议使用方式

在你这个安防项目里，建议这样接：

1. 语音输入
2. `SenseVoiceSmall` 转文本
3. 复用现有“安防智能助理”问答链路
4. 把最终回复文本交给 `MeloTTS`
5. 输出语音播报

建议保持 `MeloTTS` 独立运行在 `.melo` 环境里，不要混进 `.venv` 或 `.sensevoice`。
