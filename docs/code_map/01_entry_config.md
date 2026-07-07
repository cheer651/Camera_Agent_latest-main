# 入口与配置

这一组文件决定“项目怎么启动、用哪套配置、运行在哪种模式”。

## 入口文件

- [app.py](C:\Users\chens\Desktop\camera_project\app.py)
  Flask Web 入口。负责注册页面、接口、流式聊天接口，并在启动时创建 `MonitoringOrchestrator`。

- [main.py](C:\Users\chens\Desktop\camera_project\main.py)
  命令行入口。适合不用网页时直接跑一次任务或生成日报。

## 主编排器

- [monitoring_service.py](C:\Users\chens\Desktop\camera_project\monitoring_service.py)
  项目的总调度器。负责：
  - 读配置
  - 初始化模型客户端、数据库、向量库、飞书
  - 根据模式选择“本地直连采集”或“远程片段拉取”
  - 启动分析图、问答图、总结图

## 配置文件

- [camera_config.json](C:\Users\chens\Desktop\camera_project\camera_config.json)
  默认配置。当前等同于本地直连版。

- [camera_config.local.json](C:\Users\chens\Desktop\camera_project\camera_config.local.json)
  本地直连模式配置。人在研究院、能直接访问 RTSP 时用它。

- [camera_config.remote.json](C:\Users\chens\Desktop\camera_project\camera_config.remote.json)
  远程录制模式配置。服务器先录视频，本地再拉片分析。

- [schemas.py](C:\Users\chens\Desktop\camera_project\schemas.py)
  所有配置结构和数据结构定义，包括：
  - `SystemConfig`
  - `CaptureConfig`
  - `ServerConfig`
  - `TextLLMConfig`
  - `FrameAnalysis`

## 启动脚本

- [run_local.ps1](C:\Users\chens\Desktop\camera_project\run_local.ps1)
  用 `camera_config.local.json` 启动。

- [run_remote.ps1](C:\Users\chens\Desktop\camera_project\run_remote.ps1)
  用 `camera_config.remote.json` 启动。

## 提示词入口

- [prompt.txt](C:\Users\chens\Desktop\camera_project\prompt.txt)
  关键帧分析基础提示词。

- [monitoring_prompts.py](C:\Users\chens\Desktop\camera_project\monitoring_prompts.py)
  项目里其他提示词模板，例如：
  - 问答
  - 润色
  - 日志总结
  - 时间段总结
