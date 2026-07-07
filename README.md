# 智能视频监控 Agent 系统

面向安防场景的本地视频分析系统，支持三路摄像头实时监控、AI 关键帧分析、自然语言查询、语音助手和飞书告警。

## 核心能力

- **三路摄像头** RTSP / HTTP 视频采集与片段录制
- **关键帧智能提取**（HOG 人体检测 + MOG2 背景减除 + KMeans 聚类）
- **视觉大模型分析** Qwen2.5-VL 对关键帧进行结构化事件分析
- **高危事件飞书告警** 自动推送火灾、倒地等高风险事件
- **SQLite + Qdrant** 双存储，支持结构化查询与向量语义检索
- **自然语言对话** 按日期、摄像头、风险等级、衣着等维度查询事件
- **小安语音助手** ASR 语音输入 + TTS 语音播报
- **每日安防总结** AI 自动生成并推送飞书

---

## 1. 项目架构

```
摄像头 (RTSP/HTTP)
    │
    ▼
录制片段 (camera_recorder.py)
    │
    ▼
关键帧提取 (smart_extractor.py)  ← HOG + MOG2 + SSIM + KMeans
    │
    ▼
Qwen2.5-VL 分析 (llm_client.py)  ← OpenAI 兼容接口
    │
    ├──► SQLite (event_store.py)   结构化事件存储
    ├──► Qdrant (vector_store.py)  向量语义检索
    │
    ▼
Web 仪表盘 (app.py + templates/)
    ├── 实时监控画面
    ├── 关键帧事件浏览
    ├── 自然语言对话 (Qwen2.5 via Ollama)
    ├── 小安语音助手 (SenseVoice ASR + sherpa-onnx TTS)
    └── 每日安防总结 + 飞书推送
```

---

## 2. 项目文件

```
Camera_Agent_latest-main/
├── app.py                          Flask Web 入口（仪表盘 + API）
├── main.py                         CLI 离线分析入口
├── monitoring_service.py           主编排器（采集→分析→存储→告警）
├── monitoring_analysis.py          关键帧分析 LangGraph 工作流
├── monitoring_query.py             自然语言查询 LangGraph 工作流
├── monitoring_summary.py           每日总结 LangGraph 工作流
├── monitoring_dashboard.py         仪表盘数据接口
├── monitoring_prompts.py           分析/查询/总结提示词模板
├── monitoring_types.py             TypedDict 状态定义
│
├── camera_recorder.py              RTSP 直连录制 + 实时预览
├── smart_extractor.py              关键帧提取 + 事件合并
│
├── llm_client.py                   视觉模型客户端（OpenAI 兼容）
├── ollama_client.py                文本模型客户端（Ollama）
├── embedding_client.py             Embedding 服务客户端
│
├── vector_store.py                 Qdrant 向量库客户端
├── event_store.py                  SQLite 事件/任务/总结存储
├── feishu_agent.py                 飞书告警与消息推送
│
├── xiaoan_assistant.py             小安语音助手查询逻辑
├── xiaoan_prompts.py               小安提示词模板
├── voice_bridge.py                 语音管线桥接（ASR + TTS）
│
├── api_server.py                   Embedding API 服务（FastAPI）
├── schemas.py                      配置数据模型
│
├── camera_config.json              配置文件（默认）
├── camera_config.local.json        配置文件（本地直连，内容相同）
├── prompt.txt                      视觉分析提示词模板
├── run_local.ps1                   启动脚本
│
├── tools/
│   ├── sensevoice_server.py        SenseVoiceSmall ASR HTTP 服务
│   ├── sherpa_onnx_tts_server.py   sherpa-onnx VITS TTS HTTP 服务
│   ├── run_sensevoice_asr.py       ASR 命令行工具
│   ├── test_sensevoice.py          ASR 模型测试
│   ├── setup_sherpa_onnx_tts.ps1   TTS 环境安装脚本
│   └── setup_rospug_usb_network.ps1 机械狗网络配置
│
├── templates/
│   ├── index.html                   前端页面
│   └── dashboard.html              仪表盘页面
│
├── static/
│   ├── js/script.js                 前端逻辑
│   ├── js/dashboard/main.js         仪表盘逻辑
│   ├── css/style.css                前端样式
│   ├── css/dashboard.css            仪表盘样式
│   ├── img/xiaoan-logo.png          小安 Logo
│   └── vendor/vue.*.js             Vue.js
│
└── docs/
    ├── system_architecture.md       系统架构文档
    ├── agent_design.md              Agent 设计文档
    ├── sensevoice_small_deploy.md   ASR 部署指南
    ├── cosyvoice2_tts_deploy.md     CosyVoice2 TTS 部署指南
    └── melotts_deploy.md            MeloTTS 部署指南
```

---

## 3. 外部服务依赖

启动主程序之前，以下服务必须按顺序运行：

### 3.1 Ollama（文本 LLM + Embedding）

```powershell
# 拉取模型（首次）
ollama pull qwen2.5:7b-instruct
ollama pull qwen3-embedding:0.6b

# 验证
ollama ps
```

端口：`127.0.0.1:11434`

### 3.2 Qdrant（向量数据库）

已下载到 `D:\qdrant\qdrant.exe`，直接运行即可（不需要 Docker）：

```powershell
cd D:\qdrant
.\qdrant.exe
```

数据目录：`D:\qdrant.data`
管理界面：`http://localhost:6333/dashboard`
端口：`6333`（HTTP）、`6334`（gRPC）

### 3.3 Embedding API

```powershell
& "D:\camera_agent_data\venvs\camera-agent\Scripts\python.exe" api_server.py
```

模型目录：`D:\camera_agent_data\local_models\qwen3_embedding_0_6b\`
端口：`127.0.0.1:8080`
健康检查：`curl http://127.0.0.1:8080/health`

### 3.4 视觉模型服务

Qwen2.5-VL 通过 OpenAI 兼容接口调用，配置在 `camera_config.json` 的 `server` 段：

```json
"server": {
  "provider": "openai_compatible",
  "base_url": "http://172.16.20.114:8000/v1",
  "model": "qwen2_5_VL"
}
```

---

## 4. 启动主程序

### 方式 A：Web 仪表盘（含实时预览 + 语音助手）

```powershell
.\run_local.ps1
# 或
& "D:\camera_agent_data\venvs\camera-agent\Scripts\python.exe" app.py
```

浏览器打开：`http://127.0.0.1:5000`

功能：
- 实时监控画面预览
- 关键帧事件浏览
- 自然语言对话
- 小安语音助手（自动启动 ASR 端口 5092 + TTS 端口 5091）
- 每日总结 + 飞书推送

### 方式 B：CLI 离线分析

```powershell
# 所有启用的摄像头，录制 30 秒
& "D:\camera_agent_data\venvs\camera-agent\Scripts\python.exe" main.py --duration 30

# 指定摄像头
& "D:\camera_agent_data\venvs\camera-agent\Scripts\python.exe" main.py --duration 30 --cameras cam01 cam02

# 生成每日总结并推送到飞书
& "D:\camera_agent_data\venvs\camera-agent\Scripts\python.exe" main.py --summary --date 2026-07-08
```

> CLI 模式会自动跳过摄像头实时预览，避免 RTSP 流并发冲突。

---

## 5. 摄像头配置

当前配置了三路摄像头，在 `camera_config.json` 的 `cameras` 段：

| ID | 名称 | 类型 | 地址 |
|----|------|------|------|
| cam01 | 1号摄像头 | RTSP | `rtsp://admin:Agent123@172.16.6.79:554/stream2` |
| cam02 | 2号摄像头 | RTSP | `rtsp://admin:Agent123@172.16.6.105:554/stream2` |
| cam03 | 3号摄像头 | HTTP | `http://172.16.6.195:8080/stream?topic=/csi_camera/image_raw` |

---

## 6. 配置文件说明

| 文件 | 用途 |
|------|------|
| `camera_config.json` | 默认配置（当前等同于本地直连版） |
| `camera_config.local.json` | 本地直连版配置（内容相同） |

主要配置项：

| 段 | 说明 |
|----|------|
| `server` | 视觉模型 API 地址、模型名、参数 |
| `text_llm` | 文本 LLM（Ollama）地址、模型名 |
| `embedding` | Embedding 服务地址、模型名 |
| `vector_store` | Qdrant 地址、集合名、向量维度 |
| `storage` | 数据目录、数据库路径、提取参数、录制参数 |
| `feishu` | 飞书应用凭证和群聊 ID |
| `cameras` | 摄像头列表 |

---

## 7. 数据存储

所有数据存储在 `D:\camera_agent_data\`：

```
D:\camera_agent_data\
├── security_events.db              SQLite 数据库
├── <task_id>\
│   ├── raw_clips\<cam_id>.mp4      录制的原始视频片段
│   └── analysis\<cam_id>\
│       └── extracted_frames\       提取的关键帧图片
├── _voice\
│   ├── inputs\                     上传的语音文件
│   ├── outputs\                    合成的 TTS 音频
│   ├── cache\                      TTS 缓存
│   ├── meta\                       ASR/TTS 元数据
│   └── logs\                       语音服务日志
├── local_models\
│   ├── qwen3_embedding_0_6b\       Embedding 模型
│   ├── sensevoice\iic\SenseVoiceSmall\  ASR 模型
│   └── sherpa_onnx_tts\sherpa-onnx-vits-zh-ll\  TTS 模型
└── venvs\
    ├── camera-agent\                主程序 Python 虚拟环境
    ├── sensevoice\                  ASR Python 虚拟环境
    └── sherpa-onnx-tts\             TTS Python 虚拟环境
```

Qdrant 数据独立存储：`D:\qdrant.data\`

---

## 8. 语音功能

### 8.1 小安语音助手

Web 仪表盘内嵌的语音助手，支持：

- **语音输入**：前端录音 → SenseVoiceSmall ASR 转写 → 自然语言查询
- **语音播报**：查询结果 → sherpa-onnx VITS TTS 合成 → 前端播放

语音服务由 `voice_bridge.py` 自动管理，首次调用时自动拉起子进程：

| 服务 | 端口 | 模型 |
|------|------|------|
| ASR（语音识别） | 5092 | SenseVoiceSmall |
| TTS（语音合成） | 5091 | sherpa-onnx VITS zh-LL |

### 8.2 虚拟环境

| 用途 | 路径 | 关键包 |
|------|------|--------|
| ASR | `D:\camera_agent_data\venvs\sensevoice\` | funasr, torch, torchaudio |
| TTS | `D:\camera_agent_data\venvs\sherpa-onnx-tts\` | sherpa-onnx, numpy |

---

## 9. 主要 API 接口

### 页面
- `GET /` — 仪表盘主页

### 实时视频
- `GET /video_feed/<camera_id>` — 摄像头实时 MJPG 流

### 状态与任务
- `GET /api/overview` — 系统概览（摄像头状态、最近事件、日志）
- `GET /api/status` — 当前任务状态
- `GET /api/logs` — 系统日志
- `POST /api/tasks/start` — 手动触发采集分析任务

### 事件与总结
- `GET /api/events?date=YYYY-MM-DD` — 按日期查询事件
- `GET /api/summaries/latest` — 最新每日总结
- `POST /api/reports/daily` — 生成每日报告

### 对话
- `POST /api/chat` — 自然语言查询
- `POST /api/chat/stream` — 流式对话

### 语音
- `POST /api/voice/transcribe` — 上传音频转文字
- `POST /api/voice/synthesize` — 文字合成语音
- `GET /session_data/<path>` — 访问存储目录下的文件

---

## 10. 模型清单

| 用途 | 模型 | 部署方式 |
|------|------|---------|
| 视觉分析 | Qwen2.5-VL | 远程 API（OpenAI 兼容） |
| 文本对话/总结 | qwen2.5:7b | 本地 Ollama |
| 向量嵌入 | qwen3-embedding:0.6b | 本地 Ollama + FastAPI |
| 语音识别 | SenseVoiceSmall | 本地 funasr |
| 语音合成 | sherpa-onnx VITS zh-LL | 本地 sherpa-onnx |

---

## 11. 快速启动检查清单

```powershell
# 1. 确认 Ollama 运行并有所需模型
ollama ps
ollama list

# 2. 启动 Qdrant
cd D:\qdrant
Start-Process .\qdrant.exe

# 3. 启动 Embedding API
Start-Process -NoNewWindow `
  "D:\camera_agent_data\venvs\camera-agent\Scripts\python.exe" `
  -ArgumentList "api_server.py"

# 4. 确认视觉模型服务可达
curl http://172.16.20.114:8000/v1/models

# 5. 启动主程序
.\run_local.ps1
# 浏览器打开 http://127.0.0.1:5000
```
