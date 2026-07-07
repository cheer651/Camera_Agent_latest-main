# 模型服务、存储、告警

## 模型服务

- `llm_client.py`：远端 Qwen2.5-VL 图像分析接口客户端
- `ollama_client.py`：本地 Qwen2.5 文本模型客户端
- `api_server.py`：本地 Qwen3-Embedding HTTP 服务，用于向量化文本
- `embedding_client.py`：调用 `api_server.py` 的 embedding 接口

## 存储层

- `event_store.py`：SQLite 结构化事件库，保存关键帧事件、摘要、问答所需结构化字段
- `vector_store.py`：Qdrant 向量库封装，保存事件文本向量，支持语义检索

## 告警层

- `feishu_agent.py`：飞书图片上传、消息发送、高危事件告警推送
- `test_alert.py`：飞书配置与推送测试脚本

## 建议后续归档目录

- `models/`
- `storage/`
- `alerts/`

