# 采集、录制、抽帧、关键帧分析

## 视频采集与录制

- `camera_recorder.py`：本地直连 RTSP 时，负责两路摄像头录制和预览帧读取
- `remote_capture_client.py`：远程录制模式下，从服务器拉取 `clips.jsonl` 里的视频片段到本地

## 关键帧提取

- `smart_extractor.py`：对录好的视频片段做运动检测、候选帧筛选、重复帧过滤、代表帧提取

## 关键帧分析工作流

- `monitoring_analysis.py`：关键帧分析 LangGraph 工作流，包含构建提示词、调用图像模型、解析 JSON、事件合并、风险决策、写库、飞书告警
- `monitoring_types.py`：分析任务和分析状态的类型定义
- `llm_client.py`：图像大模型调用客户端，目前支持 OpenAI 兼容接口和旧版表单接口

## 总编排入口

- `monitoring_service.py`：负责按当前采集模式组织“取视频 -> 抽关键帧 -> 分析 -> 入库/告警”

## 建议后续归档目录

- `capture/`
- `extractor/`
- `analysis/`

